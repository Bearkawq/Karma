"""Live-status, session-summary, self-check, and run-history query handlers.

Extracted from AgentLoop; AgentLoop delegates to StatusQueryService for all
pre-pass introspection responses. No UI or API surface touched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants — class-level in AgentLoop are forwarded here for single source
# ---------------------------------------------------------------------------

LIVE_STATUS_TRIGGERS = (
    "what are you doing",
    "what are you working on",
    "what is blocked",
    "what's blocked",
    "whats blocked",
    "what failed",
    "what just failed",
    "what failed most recently",
    "what happens next",
    "what's next",
    "whats next",
    "what are you waiting",
    "what should i inspect",
    "what should i look at next",
    "are you blocked",
    "are you stuck",
    "what is karma doing",
    "what is karma working on",
    "current status",
    "what is your status",
    "what's your status",
    "show status",
    "show me status",
    "agent status",
    "what task",
    "current task",
    "how confident",
    "what is your confidence",
    "what's your confidence",
    "success rate",
    "how healthy",
    "are you healthy",
    "system health",
    "karma health",
    "health check",
)

LIVE_STATUS_ANTITOKENS = (
    "architecture",
    "how does",
    "explain the",
    "history of",
    "what is karma",
)

SESSION_SUMMARY_TRIGGERS = (
    "last session",
    "this session",
    "since startup",
    "since boot",
    "since start",
    "what happened this",
    "what did you do",
    "what did karma do",
    "summarize recent work",
    "summarize what",
    "session summary",
    "boot summary",
    "what changed since",
    "what have you done",
    "what tasks",
    "recent work",
)

SESSION_SUMMARY_ANTITOKENS = (
    "last session of",
    "architecture",
    "how does",
    "explain",
    "history of",
)

SELF_CHECK_TRIGGERS = (
    "run a quick self-check",
    "run self check",
    "self-check",
    "self check",
    "diagnose yourself",
    "diagnose karma",
    "run diagnostics",
    "quick diagnostics",
    "check yourself",
    "run a check",
)

# ---------------------------------------------------------------------------
# Module-level classifiers (pure functions — no state)
# ---------------------------------------------------------------------------


def is_live_status_query(query: str) -> bool:
    q = query.lower().strip()
    for anti in LIVE_STATUS_ANTITOKENS:
        if anti in q:
            return False
    for trigger in LIVE_STATUS_TRIGGERS:
        if trigger in q:
            return True
    return False


def is_session_summary_query(query: str) -> bool:
    q = query.lower().strip()
    for anti in SESSION_SUMMARY_ANTITOKENS:
        if anti in q:
            return False
    for trigger in SESSION_SUMMARY_TRIGGERS:
        if trigger in q:
            return True
    return False


def is_self_check_query(query: str) -> bool:
    q = query.lower().strip()
    for trigger in SELF_CHECK_TRIGGERS:
        if trigger in q:
            return True
    return False


# ---------------------------------------------------------------------------
# Service class (needs current_state, memory, health)
# ---------------------------------------------------------------------------


class StatusQueryService:
    def __init__(self, current_state: Dict[str, Any], memory, health) -> None:
        # current_state is a mutable dict reference — reads are always live
        self._state = current_state
        self._memory = memory
        self._health = health

    # -- live status ----------------------------------------------------------

    def get_live_status_snapshot(self) -> Dict[str, Any]:
        from agent.services.run_history_service import format_review_targets

        snap: Dict[str, Any] = {
            "current_task": self._state.get("current_task"),
            "last_run": self._state.get("last_run"),
            "confidence": self._state.get("confidence", 0.0),
            "last_failure": self._state.get("last_failure"),
            "blocked_reason": self._state.get("blocked_reason"),
            "decision_summary": self._state.get("decision_summary") or {},
            "run_last": None,
        }
        try:
            run_last = self._memory.get_fact_value("run:last")
            if not isinstance(run_last, dict):
                run_last = self.find_most_recent_run_digest()
            if isinstance(run_last, dict):
                snap["run_last"] = run_last
        except Exception:
            pass
        return snap

    def find_most_recent_run_digest(self) -> Optional[Dict[str, Any]]:
        try:
            best_ts = ""
            best_val = None
            for key, outer in self._memory.facts.items():
                if not isinstance(outer, dict) or outer.get("topic") != "run_history":
                    continue
                if key == "run:last":
                    continue
                ts = outer.get("last_updated", "")
                if ts > best_ts:
                    best_ts = ts
                    best_val = outer.get("value", outer)
            return best_val if isinstance(best_val, dict) else None
        except Exception:
            return None

    def format_live_status(self, snap: Dict[str, Any], query: str) -> Optional[str]:
        from agent.services.run_history_service import format_review_targets

        q = query.lower()
        current_task = snap.get("current_task")
        blocked = snap.get("blocked_reason")
        last_failure = snap.get("last_failure")
        run_last = snap.get("run_last") or {}
        confidence = snap.get("confidence", 0.0)
        decision_summary = snap.get("decision_summary") or {}

        if any(k in q for k in ("blocked", "stuck", "waiting")):
            if blocked:
                return f"Blocked: {blocked}"
            last_fail_intent = (last_failure or {}).get("intent", "")
            if last_fail_intent:
                err = (last_failure or {}).get("error", "")
                return f"Not currently blocked, but last failure was '{last_fail_intent}'" + (
                    f": {err}" if err else ""
                )
            return "Nothing is blocked."

        if any(k in q for k in ("failed", "failure", "error")):
            if last_failure and last_failure.get("intent"):
                intent = last_failure["intent"]
                err = last_failure.get("error", "")
                ts = last_failure.get("ts", "")
                line = f"Last failure: '{intent}'"
                if err:
                    line += f" — {err}"
                if ts:
                    line += f" (at {ts[:19]})"
                return line
            rl_outcome = run_last.get("outcome", "")
            rl_task = run_last.get("task", "")
            if rl_outcome in ("failed", "recovery_failed") and rl_task:
                return f"Last failure: '{rl_task}' — outcome: {rl_outcome}"
            return "No recent failures recorded."

        if "inspect" in q or ("look at" in q and "next" in q):
            pf = run_last.get("path_findings") or []
            tp = run_last.get("touched_paths") or []
            rt = format_review_targets(tp, pf)
            if rt:
                return rt
            if tp:
                return f"Files from last run: {', '.join(tp[:5])}"
            return "No file targets available."

        if any(k in q for k in ("next", "happens next", "what's next", "whats next")):
            if blocked:
                return f"Blocked ({blocked}) — resolve the failure before proceeding."
            if last_failure and last_failure.get("intent"):
                return f"Suggested: retry or diagnose '{last_failure['intent']}'"
            if current_task:
                return f"Last task was '{current_task}'. Ready for next input."
            return "Ready — no active task."

        if any(k in q for k in ("confident", "confidence", "success rate", "health", "healthy")):
            lines: List[str] = []
            if confidence > 0:
                lines.append(f"Confidence: {confidence:.0%}")
            sr = decision_summary.get("success_rate")
            if sr is not None:
                lines.append(f"Success rate: {sr:.0%}")
            total = decision_summary.get("total_decisions")
            if total:
                lines.append(f"Decisions tracked: {total}")
            if blocked:
                lines.append(f"Blocked: {blocked}")
            if not lines:
                return "No health data recorded yet."
            return "\n".join(lines)

        if not current_task and not run_last:
            return None

        lines: List[str] = []
        if current_task:
            conf_str = f" (confidence {confidence:.0%})" if confidence > 0 else ""
            lines.append(f"Last task: {current_task}{conf_str}")
        elif run_last.get("task"):
            lines.append(f"Last task: {run_last['task']} — {run_last.get('outcome', 'unknown')}")

        if blocked:
            lines.append(f"Blocked: {blocked}")
        elif last_failure and last_failure.get("intent"):
            lines.append(f"Last failure: {last_failure['intent']}")

        last_run_ts = snap.get("last_run") or run_last.get("ts", "")
        if last_run_ts:
            lines.append(f"Last run: {last_run_ts[:19]}")

        return "\n".join(lines) if lines else None

    def try_live_status_response(self, user_input: str) -> Optional[str]:
        try:
            query = (user_input or "").strip()
            if not is_live_status_query(query):
                return None
            snap = self.get_live_status_snapshot()
            return self.format_live_status(snap, query)
        except Exception:
            return None

    # -- session summary ------------------------------------------------------

    def build_session_summary(self) -> Dict[str, Any]:
        session_start = self._state.get("session_start_ts", "")
        logs = self._state.get("execution_log", [])

        if session_start:
            session_logs = [l for l in logs if l.get("timestamp", "") >= session_start]
        else:
            session_logs = logs[-20:]

        if not session_logs:
            run_last = None
            try:
                run_last = self._memory.get_fact_value("run:last")
            except Exception:
                pass
            return {
                "empty": True,
                "session_start": session_start,
                "run_last": run_last if isinstance(run_last, dict) else None,
            }

        succeeded = [l for l in session_logs if l.get("success")]
        failed = [l for l in session_logs if not l.get("success")]
        intents = [
            l.get("intent", {}).get("intent", "")
            for l in session_logs
            if isinstance(l.get("intent"), dict)
        ]
        success_intents = list(dict.fromkeys(
            l.get("intent", {}).get("intent", "") for l in succeeded
            if isinstance(l.get("intent"), dict)
        ))
        _seen_fail: Dict[str, Dict[str, str]] = {}
        for l in failed:
            _intent = l.get("intent", {}).get("intent", "") if isinstance(l.get("intent"), dict) else ""
            _seen_fail[_intent] = {
                "intent": _intent,
                "error": (l.get("execution_result") or {}).get("error") or "",
            }
        fail_entries = list(_seen_fail.values())[-3:]

        return {
            "empty": False,
            "session_start": session_start,
            "total": len(session_logs),
            "n_succeeded": len(succeeded),
            "n_failed": len(failed),
            "success_intents": success_intents[:6],
            "fail_entries": fail_entries,
            "last_intent": intents[-1] if intents else None,
            "blocked_reason": self._state.get("blocked_reason"),
            "run_last": None,
        }

    def format_session_summary(self, summary: Dict[str, Any]) -> Optional[str]:
        if summary.get("empty"):
            run_last = summary.get("run_last") or {}
            if run_last.get("task"):
                return (
                    f"No tasks this session yet. "
                    f"Last known run: '{run_last['task']}' — {run_last.get('outcome', 'unknown')}"
                )
            return "No tasks this session yet."

        total = summary["total"]
        n_ok = summary["n_succeeded"]
        n_fail = summary["n_failed"]
        session_start = (summary.get("session_start") or "")[:19]

        header = f"Session ({session_start}): {total} task(s) — {n_ok} ok, {n_fail} failed"
        lines = [header]

        if summary["success_intents"]:
            lines.append(f"Done: {', '.join(summary['success_intents'])}")
        if summary["fail_entries"]:
            for fe in summary["fail_entries"]:
                intent = fe.get("intent", "?")
                err = fe.get("error", "")
                lines.append(f"Failed: {intent}" + (f" — {err}" if err else ""))
        if summary.get("blocked_reason"):
            lines.append(f"Blocked: {summary['blocked_reason']}")
        last = summary.get("last_intent")
        success_intents = summary.get("success_intents") or []
        if last and last != (success_intents[-1] if success_intents else None):
            lines.append(f"Last: {last}")

        return "\n".join(lines)

    def try_session_summary_response(self, user_input: str) -> Optional[str]:
        try:
            query = (user_input or "").strip()
            if not is_session_summary_query(query):
                return None
            summary = self.build_session_summary()
            return self.format_session_summary(summary)
        except Exception:
            return None

    # -- self-check -----------------------------------------------------------

    def try_self_check_response(self, user_input: str, health=None) -> Optional[str]:
        try:
            query = (user_input or "").strip()
            if not is_self_check_query(query):
                return None
            health = health if health is not None else self._health
            report = health.run_check()
            status = report.get("status", "unknown")
            n_issues = report.get("issues_found", 0)
            issues = report.get("issues") or []

            if n_issues == 0:
                return f"Self-check: {status} (no issues found)"

            lines = [f"Self-check: {status} ({n_issues} issue(s))"]
            for issue in issues[:5]:
                sev = issue.get("severity", "info")
                subsystem = issue.get("subsystem", "")
                text = issue.get("issue", "")[:80]
                prefix = f"  [{sev}]" + (f" {subsystem}:" if subsystem else "")
                lines.append(f"{prefix} {text}")
                suggestion = issue.get("suggestion", "")
                if suggestion:
                    lines.append(f"    → {suggestion[:80]}")
            return "\n".join(lines)
        except Exception:
            return None

    # -- run history ----------------------------------------------------------

    def try_run_history_response(self, user_input: str) -> Optional[str]:
        try:
            from agents.retriever_agent import RetrieverAgent
            from agents.base_agent import AgentContext
            from agent.services.run_history_service import format_retrieval_results

            query = (user_input or "").strip()
            if not (
                RetrieverAgent._is_recovery_linked_query(query)
                or RetrieverAgent._is_recent_task_query(query)
                or RetrieverAgent._is_path_query(query)
            ):
                return None

            agent = RetrieverAgent()
            ctx = AgentContext(
                task=query,
                input_data={"query": query},
                memory=self._memory,
            )
            result = agent.run(ctx)
            if not result.success or not result.output:
                return None
            return format_retrieval_results(result.output)
        except Exception:
            return None
