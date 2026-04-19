"""Critic Agent - Reviews plans and results.

This agent is a functional role, NOT a personality.
It reviews plans, identifies weak points, contradictions, and missing steps.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import time

from agents.base_agent import (
    BaseAgent, AgentCapabilities, AgentContext, AgentResult, AgentStatus
)


class CriticAgent(BaseAgent):
    """Reviews plans and identifies weaknesses.
    
    Analyzes plans and results for issues, missing steps,
    contradictions, and areas for improvement.
    """
    
    def __init__(self):
        super().__init__("critic", "critic")
        self._capabilities = AgentCapabilities(
            can_criticize=True,
            requires_model=False,
            deterministic_fallback=True,
            model_role_preference="coder",
            tags=["review", "analysis", "quality"],
        )
        self._status = AgentStatus.READY
    
    def get_capabilities(self) -> AgentCapabilities:
        return self._capabilities
    
    _SYSTEM = (
        "You are a hard critic. Find real issues only. No praise. No padding. "
        "Output a bullet list of flaws. If nothing is wrong, output 'OK'. Max 5 bullets."
    )

    def run(self, context: AgentContext) -> AgentResult:
        """Review and analyze input — model-first, deterministic fallback."""
        start_time = time.time()
        try:
            input_data = context.input_data or {}
            content_type = input_data.get("content_type", "plan")
            content = input_data.get("content", [])
            tp_parent: List[str] = input_data.get("touched_paths_parent") or []
            tp_recovery: List[str] = input_data.get("touched_paths_recovery") or []

            # For model path: format dict artifact to readable string; leave others as-is
            if content_type == "run_artifact" and isinstance(content, dict):
                try:
                    from agent.services.run_history_service import format_run_artifact_content
                    content_str = format_run_artifact_content(content)[:1400]
                except Exception:
                    content_str = str(content)[:1400]
            else:
                content_str = str(content)[:1200]

            # Model path
            model_text = self._try_model(
                prompt=f"Review this {content_type}:\n\n{content_str}\n\nIssues:",
                system=self._SYSTEM,
                max_tokens=250,
            )
            if model_text:
                from agents.base_agent import _extract_bullet_issues
                model_text = _extract_bullet_issues(model_text)
                path_findings: List[Dict[str, str]] = []
                if content_type == "run_artifact":
                    path_findings = self._analyze_touched_paths(tp_parent, tp_recovery)
                    if path_findings:
                        model_text = model_text + "\n" + "\n".join(
                            f"- {f['detail']}" for f in path_findings
                        )
                return AgentResult(
                    success=True,
                    output={"critique": model_text, "content_type": content_type,
                            "model_generated": True, "path_findings": path_findings},
                    used_model=self.role_name,
                    execution_time_ms=(time.time() - start_time) * 1000,
                )

            # Deterministic fallback
            if content_type == "plan":
                review = self._review_plan(content)
            elif content_type == "result":
                review = self._review_result(content)
            elif content_type == "run_artifact":
                review = self._review_run_artifact(content, tp_parent, tp_recovery)
            else:
                review = self._review_general(content)
            return AgentResult(success=True, output=review,
                               execution_time_ms=(time.time() - start_time) * 1000)
        except Exception as e:
            self._last_error = str(e)
            self._record_execution(False)
            return AgentResult(success=False, error=str(e),
                               execution_time_ms=(time.time() - start_time) * 1000)
    
    def _review_plan(self, plan: List) -> Dict[str, Any]:
        """Review a task plan."""
        issues = []
        suggestions = []
        
        if not plan:
            issues.append("Plan is empty")
            return {"issues": issues, "suggestions": suggestions, "score": 0}
        
        # Check for missing steps
        step_nums = [s.get("step") for s in plan if "step" in s]
        if step_nums and max(step_nums) != len(plan):
            issues.append("Step numbering is inconsistent")
        
        # Check for vague actions
        for step in plan:
            if not step.get("action"):
                issues.append(f"Step {step.get('step')} has no action")
            if not step.get("target"):
                suggestions.append(f"Step {step.get('step')} has no specific target")
        
        # Calculate score
        score = max(0, 100 - len(issues) * 20 - len(suggestions) * 5)
        
        return {
            "issues": issues,
            "suggestions": suggestions,
            "score": score,
            "step_count": len(plan),
        }
    
    def _review_result(self, result: Dict) -> Dict[str, Any]:
        """Review an execution result."""
        issues = []
        suggestions = []
        
        success = result.get("success", True)
        if not success:
            issues.append("Execution failed")
            error = result.get("error")
            if error:
                issues.append(f"Error: {error}")
        
        output = result.get("output")
        if output is None:
            suggestions.append("No output generated")
        
        return {
            "issues": issues,
            "suggestions": suggestions,
            "success": success,
        }
    
    def _review_run_artifact(
        self,
        content: Any,
        parent_paths: Optional[List[str]] = None,
        recovery_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Deterministic review of a run artifact.

        Accepts either:
        - dict: the full _run_artifact struct (preferred — no parsing needed)
        - str: the formatted string from _format_run_artifact_content (legacy)

        Checks for: failed steps, wasted/skipped steps, poor recovery, empty outcome.
        When recovery is present and touched_paths are supplied, also checks for
        structural path issues (overlap, gap, weak coverage, broad spread).
        """
        issues: List[str] = []
        suggestions: List[str] = []

        if isinstance(content, dict):
            # Structured dict path — direct field access, no fragile parsing
            outcome = content.get("outcome", "")
            steps = content.get("steps", [])
            failed = content.get("failed", [])
            recovery = content.get("recovery")

            n_steps = len(steps)
            n_failed_steps = sum(1 for s in steps if s.get("status") == "failed")
            n_skipped = sum(1 for s in steps if s.get("status") == "skipped")
            has_recovery = bool(recovery)
            recovery_outcome = (recovery or {}).get("outcome", "") if has_recovery else ""

            for fs in failed:
                err_lower = (fs.get("error") or "").lower()
                if "timeout" in err_lower or "timed out" in err_lower:
                    issues.append("Step timed out — consider smaller step scope or retry logic")
                    break
        else:
            # Legacy: parse from formatted content string
            content_str = content if isinstance(content, str) else str(content)
            lines = content_str.splitlines()
            outcome = ""
            n_steps = n_failed_steps = n_skipped = 0
            has_recovery = False
            recovery_outcome = ""

            for line in lines:
                if line.startswith("Outcome:"):
                    outcome = line.split(":", 1)[1].strip()
                elif line.startswith("Steps:"):
                    import re
                    m = re.search(
                        r"(\d+) total.*?(\d+) done.*?(\d+) failed.*?(\d+) skipped", line
                    )
                    if m:
                        n_steps, _, n_failed_steps, n_skipped = (int(x) for x in m.groups())
                elif line.startswith("Failed:"):
                    if "timeout" in line.lower():
                        issues.append("Step timed out — consider smaller step scope or retry logic")
                elif line.startswith("Recovery:"):
                    has_recovery = True
                    rec_val = line.split(":", 1)[1].strip()
                    # Strip trailing "(N step(s))" appended by format_run_artifact_content
                    recovery_outcome = rec_val.split("(")[0].strip()

        # Outcome checks
        if outcome in ("failed", "empty"):
            issues.append(f"Run ended with outcome '{outcome}' — no successful output")
        if outcome == "recovery_failed":
            issues.append("Recovery was attempted but also failed — root cause unresolved")
        if outcome == "empty":
            issues.append("No output produced despite steps executing")

        # Step quality
        if n_failed_steps > 0 and not has_recovery:
            issues.append(f"{n_failed_steps} step(s) failed with no recovery attempt")
        if n_skipped > 1:
            suggestions.append(
                f"{n_skipped} steps were skipped — plan may be over-specified for this input"
            )
        if n_steps > 7:
            suggestions.append(f"Plan has {n_steps} steps — consider whether all are necessary")

        # Recovery quality
        if has_recovery and recovery_outcome == "stopped":
            issues.append("Replanner returned no recovery steps — plan may need better fallback actions")
        if has_recovery and recovery_outcome not in ("recovered", "stopped", ""):
            suggestions.append(
                f"Recovery outcome was '{recovery_outcome}' — verify recovery plan quality"
            )

        # Path-aware critique (only when recovery present and paths supplied)
        path_findings: List[Dict[str, str]] = []
        if has_recovery:
            path_findings = self._analyze_touched_paths(parent_paths, recovery_paths)
            issues.extend(f["detail"] for f in path_findings)

        score = max(0, 100 - len(issues) * 25 - len(suggestions) * 5)
        return {
            "issues": issues,
            "suggestions": suggestions,
            "score": score,
            "outcome": outcome,
            "content_type": "run_artifact",
            "path_findings": path_findings,
        }

    @staticmethod
    def _analyze_touched_paths(
        parent_paths: Optional[List[str]],
        recovery_paths: Optional[List[str]],
    ) -> List[Dict[str, str]]:
        """Compare parent vs recovery touched paths and return structured findings.

        Detects: overlap_risk, gap_risk, weak_coverage, broad_spread.
        Each finding is {"kind": "<kind>", "detail": "<human-readable detail>"}.
        Returns [] when either path list is absent — degrades safely.
        """
        p_set = set(parent_paths or [])
        r_set = set(recovery_paths or [])

        if not p_set or not r_set:
            return []

        findings: List[Dict[str, str]] = []
        overlap = p_set & r_set
        gap = p_set - r_set
        new_in_recovery = r_set - p_set

        if overlap:
            ex = ", ".join(sorted(overlap)[:3])
            findings.append({
                "kind": "overlap_risk",
                "detail": f"recovery re-touches {len(overlap)} failed-run path(s): {ex}",
                "paths": sorted(overlap)[:10],
            })
        else:
            findings.append({
                "kind": "weak_coverage",
                "detail": "recovery touches no paths from failed run",
                "paths": [],
            })

        if gap and len(gap) >= max(1, len(p_set) // 2):
            ex = ", ".join(sorted(gap)[:3])
            findings.append({
                "kind": "gap_risk",
                "detail": f"{len(gap)} failed-run path(s) not addressed in recovery: {ex}",
                "paths": sorted(gap)[:10],
            })

        if len(new_in_recovery) > 2 and len(new_in_recovery) > len(p_set):
            ex = ", ".join(sorted(new_in_recovery)[:3])
            findings.append({
                "kind": "broad_spread",
                "detail": f"recovery introduces {len(new_in_recovery)} new path(s) not in failed run: {ex}",
                "paths": sorted(new_in_recovery)[:10],
            })

        return findings

    @staticmethod
    def _critique_tool_failure(tool_name: str, error: str) -> Optional[str]:
        """Deterministic single-line critique for a failed tool execution.

        Returns a compact bullet string or None when there is nothing actionable to say.
        Never calls a model — zero latency.
        """
        if not error or not error.strip():
            return None
        err_lower = error.lower()

        if "permission denied" in err_lower or "access denied" in err_lower:
            hint = "check permissions or run with elevated access"
        elif "no such file" in err_lower or "not found" in err_lower or "does not exist" in err_lower:
            hint = "verify the target path exists before retrying"
        elif "timed out" in err_lower or "timeout" in err_lower:
            hint = "consider smaller scope or increase timeout"
        elif "connection refused" in err_lower or "network unreachable" in err_lower:
            hint = "check network connectivity or service availability"
        elif "already exists" in err_lower:
            hint = "target already present — check idempotency before overwriting"
        elif "syntax error" in err_lower or "parse error" in err_lower or "invalid syntax" in err_lower:
            hint = "fix syntax before retrying"
        elif "out of memory" in err_lower or " oom" in err_lower or "memory error" in err_lower:
            hint = "reduce input size or add memory limit"
        elif "not implemented" in err_lower or "unsupported" in err_lower:
            hint = "check tool capabilities or use an alternative"
        else:
            hint = "inspect error and verify preconditions"

        err_short = error.strip()[:80]
        label = tool_name if tool_name else "tool"
        return f"- {label} failed: {err_short} — {hint}"

    def _review_general(self, content: Any) -> Dict[str, Any]:
        """General review."""
        return {
            "issues": [],
            "suggestions": ["Content review not implemented for this type"],
        }


def create_critic_agent() -> CriticAgent:
    """Factory function to create critic agent."""
    return CriticAgent()
