"""Persistence utilities — atomic writes and file quarantine.

Shared by all storage modules for crash-safe disk operations.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _fsync_parent_dir(path: Path) -> None:
    """Best-effort fsync of a file's parent directory after rename/unlink.

    File fsync protects file contents. Directory fsync protects the directory
    entry created by os.replace(). Without this, a power/OS crash can lose the
    rename even though the file body reached disk.
    """
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        # Some platforms/filesystems do not permit directory fsync. Do not make
        # persistence unusable there; callers can still detect write failures.
        pass


def atomic_write_text(path: Path, text: str):
    """Write text to file atomically via temp + rename + parent dir fsync."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
        _fsync_parent_dir(path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except Exception:
                pass


def quarantine_file(path: Path, reason: str = 'corrupt'):
    """Move a corrupt file to a .bak suffix so it doesn't block loading."""
    path = Path(path)
    if not path.exists():
        return None
    target = path.with_suffix(path.suffix + f'.{reason}.bak')
    idx = 1
    while target.exists():
        target = path.with_suffix(path.suffix + f'.{reason}.{idx}.bak')
        idx += 1
    try:
        os.replace(path, target)
        _fsync_parent_dir(path)
        return target
    except Exception:
        return None


def load_json_file(path: Path, default: Any = None):
    """Load a JSON file, quarantining if corrupt."""
    path = Path(path)
    if not path.exists():
        return default if default is not None else {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        quarantine_file(path)
        return default if default is not None else {}


def save_json_file(path: Path, data: Any):
    """Save data as JSON atomically."""
    atomic_write_text(Path(path), json.dumps(data, indent=2, default=str))
