from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from storage.episodic import EpisodicStore


def _make_file(path: Path, lines: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_dir_fsync_called_during_rotation(tmp_path):
    ep = tmp_path / "episodic.jsonl"
    lines = [f'{{"event": "e{i}"}}' for i in range(10)]
    _make_file(ep, lines)

    dir_fsynced = []

    orig_fsync = os.fsync

    def spy_fsync(fd):
        try:
            import stat as stat_mod
            if stat_mod.S_ISDIR(os.fstat(fd).st_mode):
                dir_fsynced.append(fd)
        except Exception:
            pass
        return orig_fsync(fd)

    with patch("os.fsync", side_effect=spy_fsync):
        es = EpisodicStore(ep)
        # call rotate directly
        es._rotate()

    assert len(dir_fsynced) >= 1, "Directory fsync not called during rotation"


def test_dir_fsync_failure_sets_flag(tmp_path):
    ep = tmp_path / "episodic.jsonl"
    lines = [f'{{"event": "e{i}"}}' for i in range(8)]
    _make_file(ep, lines)

    orig_fsync = os.fsync

    def failing_fsync(fd):
        try:
            import stat as stat_mod
            if stat_mod.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("fsync failed")
        except OSError:
            raise
        except Exception:
            pass
        return orig_fsync(fd)

    with patch("os.fsync", side_effect=failing_fsync):
        es = EpisodicStore(ep)
        es._last_save_failed = False
        es._rotate()

    assert es._last_save_failed is True


def test_rotated_data_reloads_correctly(tmp_path):
    ep = tmp_path / "episodic.jsonl"
    # make 6 JSON lines with event names e1..e6
    lines = [f'{{"event": "e{i}"}}' for i in range(1, 7)]
    _make_file(ep, lines)

    es = EpisodicStore(ep)
    # perform rotation
    es._rotate()
    # reload into memory
    es.load()
    # keep should be len(lines)//2 == 3, so remaining events are e4,e5,e6
    events = [e.get("event") for e in es.log]
    assert events == ["e4", "e5", "e6"]
