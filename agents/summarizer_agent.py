"""Summarizer Agent - Condenses logs, plans, and artifacts.

This agent is a functional role, NOT a personality.
It summarizes logs, plans, artifacts, search results, receipts, and docs.
"""

from __future__ import annotations

from typing import Any, Dict, List
import time

from agents.base_agent import (
    BaseAgent,
    AgentCapabilities,
    AgentContext,
    AgentResult,
    AgentStatus,
)


class SummarizerAgent(BaseAgent):
    """Condenses logs, plans, artifacts, and documents.

    Creates concise summaries without requiring external model access.
    Uses deterministic extraction and compression techniques.
    """

    def __init__(self):
        super().__init__("summarizer", "summarizer")
        self._capabilities = AgentCapabilities(
            can_summarize=True,
            requires_model=False,
            deterministic_fallback=True,
            model_role_preference="summarizer",
            tags=["summarization", "compression", "extraction"],
        )
        self._status = AgentStatus.READY

    def get_capabilities(self) -> AgentCapabilities:
        return self._capabilities

    _SYSTEM = (
        "You are a summarizer. Compress input to 3-5 sentences. "
        "Use only information explicitly present in the input. "
        "Do not introduce concepts, names, or details absent from the source. "
        "No padding. Output the summary only."
    )

    def run(self, context: AgentContext) -> AgentResult:
        """Summarize content — model-first, deterministic fallback."""
        start_time = time.time()
        try:
            input_data = context.input_data or {}
            content_type = input_data.get("content_type", "general")
            content = input_data.get("content", [])
            content_str = (
                str(content)[:3000] if not isinstance(content, str) else content[:3000]
            )

            # Light validation: assess source fidelity risk
            source_risk = self._assess_source_risk(content_str, content_type)

            # Model path
            model_text = self._try_model(
                prompt=f"Summarize this {content_type}:\n\n{content_str}",
                system=self._SYSTEM,
                max_tokens=400,
            )
            if model_text:
                # Enforce validation based on risk
                validated_summary = self._enforce_validation(
                    model_text, source_risk, content_str
                )
                return AgentResult(
                    success=True,
                    output={
                        "summary": validated_summary,
                        "content_type": content_type,
                        "input_count": len(content) if isinstance(content, list) else 1,
                        "model_generated": True,
                        "source_risk": source_risk,
                        "validation_enforced": source_risk != "low",
                    },
                    used_model=self.role_name,
                    execution_time_ms=(time.time() - start_time) * 1000,
                )

            # Deterministic fallback
            if content_type == "logs":
                summary = self._summarize_logs(content)
            elif content_type == "plan":
                summary = self._summarize_plan(content)
            elif content_type == "artifacts":
                summary = self._summarize_artifacts(content)
            elif content_type == "receipts":
                summary = self._summarize_receipts(content)
            elif content_type == "run_artifact":
                summary = self._summarize_run_artifact(content)
            else:
                summary = self._summarize_general(content)
            return AgentResult(
                success=True,
                output={
                    "summary": summary,
                    "content_type": content_type,
                    "input_count": len(content) if isinstance(content, list) else 1,
                    "source_risk": "low",  # Deterministic fallback is reliable
                },
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            self._last_error = str(e)
            self._record_execution(False)
            return AgentResult(
                success=False,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    def _summarize_logs(self, logs: List) -> str:
        """Summarize log entries."""
        if not logs:
            return "No logs to summarize."

        errors = sum(
            1 for l in logs if isinstance(l, dict) and l.get("level") == "error"
        )
        warnings = sum(
            1 for l in logs if isinstance(l, dict) and l.get("level") == "warning"
        )

        lines = [f"Total entries: {len(logs)}"]
        if errors:
            lines.append(f"Errors: {errors}")
        if warnings:
            lines.append(f"Warnings: {warnings}")

        # Extract last few messages
        recent = logs[-3:] if len(logs) > 3 else logs
        lines.append("Recent entries:")
        for entry in recent:
            msg = entry.get("message", str(entry))[:100]
            lines.append(f"  - {msg}")

        return "\n".join(lines)

    def _summarize_plan(self, plan: List) -> str:
        """Summarize task plan."""
        if not plan:
            return "No plan to summarize."

        lines = [f"Plan with {len(plan)} steps:"]
        for step in plan:
            action = step.get("action", "?")
            target = step.get("target", "")
            lines.append(f"  {step.get('step', '?')}. {action}: {target}")

        return "\n".join(lines)

    def _summarize_artifacts(self, artifacts: List) -> str:
        """Summarize artifacts."""
        if not artifacts:
            return "No artifacts to summarize."

        by_type: Dict[str, int] = {}
        for a in artifacts:
            t = a.get("content_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        lines = [f"Total artifacts: {len(artifacts)}", "By type:"]
        for t, count in by_type.items():
            lines.append(f"  - {t}: {count}")

        return "\n".join(lines)

    def _summarize_receipts(self, receipts: List) -> str:
        """Summarize action receipts."""
        if not receipts:
            return "No receipts to summarize."

        success = sum(1 for r in receipts if r.get("result_status") == "success")
        failed = sum(1 for r in receipts if r.get("result_status") == "failure")

        lines = [
            f"Total receipts: {len(receipts)}",
            f"Success: {success}, Failed: {failed}",
        ]

        return "\n".join(lines)

    def _summarize_run_artifact(self, content: Any) -> str:
        """Summarize a pre-formatted run artifact content string."""
        if isinstance(content, str):
            # content is already formatted by _format_run_artifact_content
            lines = [l for l in content.splitlines() if l.strip()]
            return "\n".join(lines[:10])
        return str(content)[:300]

    def _summarize_general(self, content: Any) -> str:
        """General summarization."""
        if isinstance(content, list):
            return f"Content list with {len(content)} items."
        elif isinstance(content, str):
            return content[:200] + "..." if len(content) > 200 else content
        else:
            return str(content)[:200]

    def _assess_source_risk(self, content_str: str, content_type: str) -> str:
        """Lightweight risk assessment for hallucination potential."""
        if len(content_str) < 200:
            return "low"
        if content_type in ("logs", "receipts", "plan"):
            return "low"
        fact_markers = (
            content_str.count(":") + content_str.count("[") + content_str.count("{")
        )
        if fact_markers > 10:
            return "medium"
        return "medium"

    def _enforce_validation(self, summary: str, risk: str, source: str) -> str:
        """Enforce validation based on risk level."""
        if risk == "low":
            return summary

        # For medium risk: validate against source and add uncertainty if needed
        source_lower = source.lower()
        summary_lower = summary.lower()

        # Check for claims not grounded in source
        # Extract potential entities from summary (capitalized or quoted)
        import re

        entities = re.findall(r'"([^"]+)"|([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', summary)
        valid_entities = []
        for e in entities:
            entity = e[0] or e[1]
            if entity and entity.lower() in source_lower:
                valid_entities.append(entity)

        # If we have entities but none validated, add uncertainty marker
        if entities and len(valid_entities) < len(entities) * 0.5:
            return f"[uncertain] {summary}"

        # If summary is much longer than warranted, truncate with indicator
        if len(summary) > 500 and len(source) < 500:
            return summary[:450] + "... [may include unsupported details]"

        return summary


def create_summarizer_agent() -> SummarizerAgent:
    """Factory function to create summarizer agent."""
    return SummarizerAgent()
