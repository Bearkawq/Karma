"""Persistence utilities — atomic writes and file quarantine.

Shared by all storage modules for crash-safe disk operations.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str):
    """Write text to file atomically via temp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except Exception:
                pass


def quarantine_file(path: Path, reason: str = 'corrupt'):
    """Move a corrupt file to a .bak suffix so it doesn't block loading."""
    if not path.exists():
        return None
    target = path.with_suffix(path.suffix + f'.{reason}.bak')
    idx = 1
    while target.exists():
        target = path.with_suffix(path.suffix + f'.{reason}.{idx}.bak')
        idx += 1
    try:
        os.replace(path, target)
        return target
    except Exception:
        return None


def load_json_file(path: Path, default: Any = None):
    """Load a JSON file, quarantining if corrupt."""
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
    atomic_write_text(path, json.dumps(data, indent=2))
