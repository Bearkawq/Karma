"""Maintenance scheduler — offloaded from AgentLoop (#1).

Handles periodic maintenance tasks:
- Capability pressure detection
- Memory compression
- Health self-checks
- Auto-crystallization
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("karma")


class MaintenanceScheduler:
    """Runs periodic maintenance tasks based on cycle count."""

    def __init__(self, meta, capability_map, memory, health, retrieval, bus):
        self._meta = meta
        self._cap_map = capability_map
        self._memory = memory
        self._health = health
        self._retrieval = retrieval
        self._bus = bus

    def tick(self, execution_log: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Run periodic maintenance. Returns meta report if adjustment happened."""
        cycle = self._meta._cycle_count
        report = {}

        # Meta observation tick
        meta_report = self._meta.tick(execution_log)
        if meta_report:
            self._bus.emit("meta_adjust", report=meta_report)
            logger.info(f"Meta adjustment: {meta_report}")
            report["meta"] = meta_report

        # Capability pressure — every 50 cycles
        if cycle % 50 == 0:
            proposals = self._cap_map.detect_pressure()
            for p in proposals:
                self._bus.emit("capability_pressure", proposal=p)
                self._memory.save_episodic("capability_pressure", p, confidence=0.6)
            if proposals:
                report["pressure_proposals"] = len(proposals)

        # Memory compression — every 100 cycles
        if cycle % 100 == 0:
            comp_report = self._memory.compress()
            self._bus.emit("memory_compressed", report=comp_report)
            logger.info(f"Memory compression: {comp_report}")
            report["compression"] = comp_report

        # Health self-check — every 200 cycles
        if cycle % 200 == 0:
            health_report = self._health.run_check()
            if health_report.get("issues_found", 0) > 0:
                self._bus.emit("health_check", report=health_report)
                logger.info(f"Health check: {health_report['status']} ({health_report['issues_found']} issues)")
                report["health"] = health_report

        # Auto-crystallize — every 150 cycles
        if cycle % 150 == 0:
            topics = set()
            for key in list(self._memory.facts.keys())[:500]:
                parts = key.split(":")
                if len(parts) >= 2 and parts[0] == "learn":
                    topics.add(parts[1])
            for topic in list(topics)[:5]:
                self._retrieval.crystallize(topic)
            if topics:
                report["crystallized_topics"] = min(len(topics), 5)

        return report if report else None
