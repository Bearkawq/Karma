"""Digest action handler.

Handles drop folder auto-ingestion.
"""

from __future__ import annotations

from typing import Any, Dict


class DigestHandler:
    """Handler for drop folder auto-ingestion."""

    def __init__(self, agent):
        self.agent = agent

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run digest to auto-ingest files from drop folders."""
        from research.dropbox_digest import get_digest, run_digest

        try:
            stats = run_digest()

            lines = [
                "# Dropbox Digest Complete",
                "",
                f"**Files scanned**: {stats.files_scanned}",
                f"**Files ingested**: {stats.files_ingested}",
                f"**Files failed**: {stats.files_failed}",
                "",
                "## Drop Folder Status",
            ]

            digest = get_digest()
            status = digest.get_drop_folder_status()
            for folder, info in status.items():
                lines.append(f"- {folder}: {info['count']} files")

            if stats.errors:
                lines.extend(["", "## Errors"])
                for err in stats.errors[:5]:
                    lines.append(f"- {err}")

            return {
                "success": True,
                "output": {"content": "\n".join(lines)},
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": f"Digest failed: {str(e)}",
            }
