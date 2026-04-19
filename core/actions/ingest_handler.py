"""Ingest action handler.

Handles file/directory ingestion.
"""

from __future__ import annotations

from typing import Any, Dict


class IngestHandler:
    """Handler for file/directory ingestion."""
    
    def __init__(self, agent):
        self.agent = agent
    
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest knowledge from local path into Karma."""
        from research.ingestor import SeedIngestor
        
        path = params.get("path", "")
        if not path:
            return {
                "success": False,
                "output": None,
                "error": "No path provided for ingestion. Use: ingest <path>",
            }
        
        ingestor = SeedIngestor()
        
        try:
            stats = ingestor.ingest_path(path, move_processed=True, move_rejected=True)
            
            lines = [
                "# Ingestion Complete",
                "",
                f"**Files scanned**: {stats.files_scanned}",
                f"**Files accepted**: {stats.files_accepted}",
                f"**Files rejected**: {stats.files_rejected}",
                f"**Duplicates skipped**: {stats.duplicates_skipped}",
                "",
                "## Topic Counts",
            ]
            
            for topic, count in sorted(stats.topic_counts.items()):
                lines.append(f"- {topic}: {count}")
            
            lines.extend([
                "",
                "## Provenance Counts",
            ])
            
            for prov, count in sorted(stats.provenance_counts.items()):
                lines.append(f"- {prov}: {count}")
            
            if stats.errors:
                lines.extend(["", "## Errors",])
                for err in stats.errors[:5]:
                    lines.append(f"- {err}")
            
            all_items = ingestor.get_all_items()
            lines.extend(["", f"**Total items in knowledge base**: {len(all_items)}",])
            
            return {
                "success": True,
                "output": {"content": "\n".join(lines)},
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": f"Ingestion failed: {str(e)}",
            }
