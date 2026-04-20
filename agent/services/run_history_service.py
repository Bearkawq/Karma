"""Run history persistence, digest building, and artifact formatting.

Extracted from AgentLoop; AgentLoop delegates to RunHistoryService for all
run-digest / artifact logic.  No UI or API surface touched.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIGEST_SKIP_NAMES: frozenset = frozenset(
    {
        "help",
        "status_query",
        "list_capabilities",
        "repair_report",
        "teach_response",
        "forget_response",
        "list_custom_tools",
    }
)

CRITIC_TRIVIAL_TOOLS: frozenset = frozenset(
    {
        "help",
        "list",
        "list_files",
        "list_capabilities",
        "list_tools",
        "status_query",
        "health_check",
        "repair_report",
        "teach",
        "forget",
    }
)

# Outcome → compact badge label
_OUTCOME_BADGE_MAP: Dict[str, str] = {
    "success": "ok",
    "recovered": "recovered",
    "failed": "failed",
    "recovery_failed": "recovery_failed",
    "partial": "partial",
    "empty": "empty",
}

# ---------------------------------------------------------------------------
# Pure static helpers (no external state)
# ---------------------------------------------------------------------------


def outcome_badge(outcome: str) -> str:
    """Return compact badge label for a run outcome string."""
    return _OUTCOME_BADGE_MAP.get((outcome or "").lower(), "unknown")


def format_compact_output(value: Any, max_len: int = 200) -> str:
    """Compact, copy-friendly rendering of tool output for digest storage."""
    if value is None:
        return ""
    if isinstance(value, str):
        # Collapse internal whitespace; preserve newlines as \\n for copy-friendliness
        lines = [l.rstrip() for l in value.strip().splitlines() if l.strip()]
        cleaned = " | ".join(lines) if len(lines) > 1 else (lines[0] if lines else "")
        return cleaned[:max_len]
    if isinstance(value, (list, tuple)):
        items = [str(x) for x in value[:10]]
        joined = ", ".join(items)
        suffix = f" (+{len(value) - 10} more)" if len(value) > 10 else ""
        return (joined + suffix)[:max_len]
    if isinstance(value, dict):
        if len(value) <= 5:
            parts = [
                f"{k}={v}" for k, v in list(value.items())[:5]
                if v not in (None, "", False)
            ]
            return (", ".join(parts))[:max_len]
        keys = list(value.keys())[:6]
        return f"{{{', '.join(str(k) for k in keys)}}}"[:max_len]
    return str(value)[:max_len]


def format_error_compact(error: str) -> str:
    """Compact error: surface the root message, strip traceback noise."""
    if not error:
        return ""
    lines = [l.strip() for l in error.strip().splitlines() if l.strip()]
    # Prefer the last line that contains a known error pattern
    for line in reversed(lines):
        if any(p in line for p in ("Error:", "Exception:", "FATAL:", "failed:", "error:")):
            return line[:120]
    # Fall back to last non-empty line (often the actual message)
    return lines[-1][:120] if lines else error[:120]


def build_run_detail(run_key: str, memory) -> Optional[Dict[str, Any]]:
    """Return enriched run detail dict for operator display.

    Includes run_kind, outcome_badge, critic fields, recovery linkage,
    key output/error, step counts.  Returns None when key is absent.
    """
    try:
        fact = memory.get_fact_value(run_key)
    except Exception:
        return None
    if not isinstance(fact, dict):
        return None

    raw_outcome = fact.get("outcome", "")
    badge = fact.get("outcome_badge") or outcome_badge(raw_outcome)

    return {
        "run_id": fact.get("run_id", run_key),
        "run_kind": fact.get("run_kind", "primary"),
        "outcome_badge": badge,
        "task": fact.get("task"),
        "outcome": raw_outcome,
        "ts": fact.get("ts"),
        "n_steps": fact.get("n_steps", 0),
        "n_failed": fact.get("n_failed", 0),
        "n_skipped": fact.get("n_skipped", 0),
        "completed_steps": (fact.get("completed_steps") or [])[:8],
        "failed_steps": (fact.get("failed_steps") or [])[:3],
        "key_output": fact.get("key_output", ""),
        "key_error": fact.get("key_error", ""),
        "recovery_outcome": fact.get("recovery_outcome"),
        "recovery_run_id": fact.get("recovery_run_id"),
        "path_findings": fact.get("path_findings") or [],
        "touched_paths": fact.get("touched_paths") or [],
        "critic_issues": fact.get("critic_issues") or [],
        "critic_lesson": fact.get("critic_lesson", ""),
        "summary": fact.get("summary", ""),
    }


def failure_first_sort(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Re-sort retrieval result entries so failures surface before successes.

    Order: failed / recovery_failed / empty  →  recovered  →  success / other.
    Stable sort preserves timestamp ordering within each tier.
    """
    _PRIORITY: Dict[str, int] = {
        "failed": 0, "recovery_failed": 0, "empty": 1,
        "recovered": 2,
    }

    def _key(r: Dict[str, Any]) -> int:
        val = r.get("value") if isinstance(r, dict) else {}
        if not isinstance(val, dict):
            val = {}
        return _PRIORITY.get(val.get("outcome", "success"), 3)

    return sorted(results, key=_key)


def extract_critic_fields(critique: str) -> Dict[str, Any]:
    """Extract compact critic fields from a critique string.

    Returns {"critic_issues": [...], "critic_lesson": "..."} or {} if empty.
    Issues are parsed from bullet lines; lesson is the first issue.
    Each issue is truncated to 120 chars; at most 3 issues stored.
    """
    if not critique or not critique.strip():
        return {}
    lines = critique.splitlines()
    issues: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped[0] in ("-", "•", "→", "*"):
            body = stripped.lstrip("-•→* ").strip()
            if len(body) > 4:
                issues.append(body[:120])
    if not issues:
        for line in lines:
            stripped = line.strip()
            if stripped and len(stripped) > 4:
                issues = [stripped[:120]]
                break
    if not issues:
        return {}
    return {
        "critic_issues": issues[:3],
        "critic_lesson": issues[0],
    }


def format_run_artifact_content(run_artifact: Dict[str, Any]) -> str:
    task = run_artifact.get("task", "unknown")
    outcome = run_artifact.get("outcome", "unknown")
    steps = run_artifact.get("steps", [])
    outputs = run_artifact.get("outputs", [])
    failed = run_artifact.get("failed", [])
    recovery = run_artifact.get("recovery")

    n_done = sum(1 for s in steps if s.get("status") == "done")
    n_failed = sum(1 for s in steps if s.get("status") == "failed")
    n_skipped = sum(1 for s in steps if s.get("status") == "skipped")

    lines = [
        f"Task: {task}",
        f"Outcome: {outcome}",
        f"Steps: {len(steps)} total ({n_done} done, {n_failed} failed, {n_skipped} skipped)",
    ]

    done_steps = [s for s in steps if s.get("status") == "done"]
    if done_steps:
        descs = [
            f"{s.get('action', '?')} {s.get('target', '')}".strip()
            for s in done_steps[:6]
        ]
        lines.append(f"Completed: {', '.join(descs)}")

    for fs in failed[:3]:
        err = (fs.get("error") or "")[:100]
        lines.append(
            f"Failed: step {fs.get('step')} ({fs.get('action', '?')} {fs.get('target', '').strip()})"
            + (f" — {err}" if err else "")
        )

    if outputs and n_done > 0:
        lines.append("Output:")
        for o in outputs[:3]:
            lines.append(f"  {str(o)[:120]}")

    if recovery:
        rec_outcome = recovery.get("outcome", "unknown")
        rec_exec = recovery.get("recovery_execution") or {}
        rec_n = len(rec_exec.get("steps", [])) or len(
            recovery.get("recovery_plan") or []
        )
        lines.append(f"Recovery: {rec_outcome} ({rec_n} step(s))")
        rec_failed = rec_exec.get("failed") or []
        if rec_failed:
            rf = rec_failed[0]
            lines.append(
                f"  Recovery failed at: {rf.get('action', '?')} — {(rf.get('error') or '')[:80]}"
            )

    return "\n".join(lines)


def build_compact_digest_summary(run_artifact: Dict[str, Any]) -> str:
    task = run_artifact.get("task", "unknown")
    outcome = run_artifact.get("outcome", "unknown")
    steps = run_artifact.get("steps", [])
    failed = run_artifact.get("failed", [])
    recovery = run_artifact.get("recovery")

    done = [s for s in steps if s.get("status") == "done"]
    n_skip = sum(1 for s in steps if s.get("status") == "skipped")

    if run_artifact.get("run_kind") == "tool" and not steps:
        tool = run_artifact.get("tool", "")
        target = run_artifact.get("target", "")
        desc = f"{tool} {target}".strip() if target else tool
        parts = [f"{task}: {outcome}"]
        if desc:
            parts.append(f"tool={desc}")
        if failed:
            err = (failed[0].get("error") or "")[:70]
            parts.append(f"error={err}" if err else "error=unknown")
        elif run_artifact.get("key_output"):
            parts.append(f"out={run_artifact['key_output'][:60]}")
        return " | ".join(parts)

    parts = [f"{task}: {outcome}"]
    if done:
        descs = [
            f"{s.get('action', '?')} {s.get('target', '')}".strip() for s in done[:4]
        ]
        parts.append(f"done={', '.join(descs)}")
    if failed:
        fs = failed[0]
        err = (fs.get("error") or "")[:70]
        parts.append(f"failed={fs.get('action', '?')}" + (f"({err})" if err else ""))
    if n_skip:
        parts.append(f"skipped={n_skip}")
    if recovery:
        rec_out = recovery.get("outcome", "unknown")
        parts.append(f"recovery={rec_out}")
    return " | ".join(parts)


def extract_touched_paths(run_artifact: Dict[str, Any]) -> List[str]:
    _PATH_RE = re.compile(
        r"^(?:/|\.{1,2}/|~/)[\w./\-]+"
        r"|^[\w./\-]+\.\w{1,8}$"
    )
    seen: set = set()
    paths: List[str] = []
    for collection in ("steps", "plan"):
        for step in run_artifact.get(collection, []):
            target = (step.get("target") or "").strip()
            if target and _PATH_RE.match(target) and target not in seen:
                seen.add(target)
                paths.append(target)
    return paths[:20]


def resolve_touched_paths(
    paths: List[str],
    base_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    import os

    if not paths:
        return []

    base = base_dir or os.getcwd()
    results: List[Dict[str, Any]] = []

    for p in paths:
        if not isinstance(p, str) or not p.strip():
            continue
        try:
            expanded = os.path.expanduser(p)
            if not os.path.isabs(expanded):
                expanded = os.path.join(base, expanded)
            resolved = os.path.normpath(os.path.abspath(expanded))
            common = os.path.commonpath([resolved, os.path.abspath(base)])
            if common != os.path.abspath(base):
                results.append(
                    {"path": p, "status": "unresolvable", "resolved": resolved}
                )
                continue
            if os.path.isfile(resolved):
                status = "file"
            elif os.path.isdir(resolved):
                status = "directory"
            elif os.path.exists(resolved):
                status = "unknown"
            else:
                status = "missing"
            results.append({"path": p, "status": status, "resolved": resolved})
        except Exception:
            results.append({"path": p, "status": "unresolvable", "resolved": p})

    return results


def should_digest_single_tool(selected_action: Dict[str, Any]) -> bool:
    name = selected_action.get("name") or ""
    if name in DIGEST_SKIP_NAMES:
        return False
    if selected_action.get("_seat_generated"):
        return False
    return True


def extract_tool_output(raw_output: Any, max_len: int = 200) -> str:
    """Extract the most useful string from tool output.

    String values are preserved verbatim (with newlines) up to max_len — this
    keeps stdout/command output copy-friendly.  Non-string types (dict, list)
    use format_compact_output for compact rendering.
    """
    if raw_output is None:
        return ""
    if isinstance(raw_output, str):
        return raw_output[:max_len].strip()
    if isinstance(raw_output, (list, tuple)):
        return format_compact_output(raw_output, max_len)
    if isinstance(raw_output, dict):
        for key in ("output", "stdout", "content", "text", "result", "summary", "message"):
            v = raw_output.get(key)
            if v and isinstance(v, str) and v.strip():
                return v[:max_len].strip()
        for key in ("files", "items", "results", "lines", "entries"):
            v = raw_output.get(key)
            if v and isinstance(v, (list, tuple)):
                return format_compact_output(v, max_len)
        skip = {"success", "error", "exit_code", "stderr", "returncode"}
        meaningful = {
            k: v for k, v in raw_output.items()
            if k not in skip and v not in (None, "", False)
        }
        if meaningful:
            return format_compact_output(meaningful, max_len)
    return format_compact_output(raw_output, max_len)


def build_single_tool_artifact(
    intent: Dict[str, Any],
    selected_action: Dict[str, Any],
    execution_result: Dict[str, Any],
    user_input: str = "",
) -> Dict[str, Any]:
    name = selected_action.get("name") or ""
    tool = selected_action.get("tool") or name
    params = selected_action.get("parameters") or {}
    target = (
        params.get("target")
        or params.get("path")
        or params.get("command")
        or params.get("name")
        or ""
    )
    task = (user_input or intent.get("intent", name) or name)[:120]
    success = bool(execution_result.get("success", False))
    outcome = "success" if success else "failed"
    raw_output = execution_result.get("output")
    key_output = extract_tool_output(raw_output)
    error = (execution_result.get("error") or "")[:120]

    return {
        "task": task,
        "outcome": outcome,
        "run_kind": "tool",
        "tool": tool,
        "target": str(target)[:80],
        "steps": [],
        "outputs": [key_output] if key_output else [],
        "failed": [
            {"step": 1, "action": tool, "target": str(target)[:80], "error": error}
        ]
        if not success and error
        else [],
        "recovery": None,
        "key_output": key_output,
        "key_error": error,
    }


def format_review_targets(
    touched_paths: List[str],
    path_findings: List[Dict[str, Any]],
    label_prefix: str = "",
) -> str:
    if not touched_paths and not path_findings:
        return ""

    _RISK_KINDS_WITH_PATHS = ("overlap_risk", "gap_risk", "broad_spread")
    _RISK_LABELS = {
        "overlap_risk": "overlap with failed run",
        "gap_risk": "missed by recovery",
        "broad_spread": "new in recovery",
        "weak_coverage": "recovery skipped failed-run files",
    }
    risk_lines: List[str] = []
    risk_seen: set = set()

    for f in path_findings or []:
        kind = f.get("kind", "")
        if kind not in _RISK_LABELS:
            continue
        f_paths = f.get("paths") or []
        label = _RISK_LABELS.get(kind, kind)
        if kind in _RISK_KINDS_WITH_PATHS and f_paths:
            for p in f_paths:
                risk_seen.add(p)
            risk_lines.append(f"  [{label}] {', '.join(f_paths[:5])}")
        else:
            risk_lines.append(f"  Risks: {label}")

    other_paths = [p for p in touched_paths if p not in risk_seen]
    resolved_other = resolve_touched_paths(other_paths) if other_paths else []
    existing_other = [
        r["path"] for r in resolved_other if r["status"] in ("file", "directory")
    ]
    missing_other = [r["path"] for r in resolved_other if r["status"] == "missing"]

    lines: List[str] = []
    if risk_lines:
        header = (
            f"{label_prefix}Review targets (risk-first):"
            if label_prefix
            else "Review targets (risk-first):"
        )
        lines.append(header)
        lines.extend(risk_lines)
    if existing_other:
        lines.append(f"  Other paths (exist): {', '.join(existing_other[:10])}")
    if missing_other:
        lines.append(f"  Other paths (missing): {', '.join(missing_other[:10])}")
    if not lines and touched_paths:
        resolved_all = resolve_touched_paths(touched_paths)
        existing = [
            r["path"] for r in resolved_all if r["status"] in ("file", "directory")
        ]
        missing = [r["path"] for r in resolved_all if r["status"] == "missing"]
        prefix = f"{label_prefix}Paths:" if label_prefix else "Paths:"
        if existing:
            lines.append(f"{prefix} {', '.join(existing[:10])}")
        if missing:
            lines.append(f"Missing paths: {', '.join(missing[:10])}")
    return "\n".join(lines)


def _format_critic_for_display(val: Dict[str, Any]) -> str:
    """Format critic findings for display in run results."""
    if not val:
        return ""
    issues = val.get("critic_issues") or []
    lesson = val.get("critic_lesson", "")
    if issues:
        return f"Critic: {issues[0][:100]}"
    if lesson:
        return f"Critic: {lesson[:100]}"
    return ""


def _should_include_critic(val: Dict[str, Any]) -> bool:
    """Check if critic findings should be shown for this artifact."""
    if not val:
        return False
    tool = val.get("tool", "").lower()
    outcome = val.get("outcome", "")
    TRIVIAL_TOOLS = frozenset(
        {
            "help",
            "list",
            "list_files",
            "list_capabilities",
            "list_tools",
            "status_query",
            "health_check",
            "repair_report",
            "teach",
            "forget",
        }
    )
    if tool and tool in TRIVIAL_TOOLS:
        return False
    if outcome == "success":
        return bool(val.get("critic_issues"))
    return True


def format_retrieval_results(output: Any, failure_first: bool = False) -> Optional[str]:
    """Format run history results from retriever for display.

    failure_first=True re-sorts results so failed/recovery_failed entries
    surface before successful ones (same-tier entries keep timestamp order).
    """
    if not isinstance(output, dict):
        return None
    if "results" not in output or "method" not in output:
        return None

    results = output.get("results") or []
    if not results:
        return None

    if failure_first:
        results = failure_first_sort(results)

    sections: list = []
    seen_critic: set = set()

    for r in results:
        if not isinstance(r, dict):
            continue
        linked = r.get("linked")
        if isinstance(linked, dict) and linked.get("kind") == "linked_run_history":
            sections.append(format_linked_run_result(linked))
            continue

        val = r.get("value")
        if not isinstance(val, dict):
            if val is not None:
                sections.append(str(val)[:200])
            continue

        task = val.get("task") or r.get("key") or ""
        outcome = val.get("outcome") or ""
        summary = val.get("summary") or ""
        run_kind = val.get("run_kind", "primary")
        paths = val.get("touched_paths") or []
        resolved = resolve_touched_paths(paths)

        if not task:
            continue

        if run_kind == "tool":
            entry = [
                f"[tool] {summary.strip()}" if summary else f"[tool] {task}: {outcome}"
            ]
            if val.get("key_error") and outcome == "failed":
                entry.append(f"  Error: {val.get('key_error', '')[:120]}")
            if _should_include_critic(val):
                critic = _format_critic_for_display(val)
                if critic and critic not in seen_critic:
                    entry.append(f"  {critic}")
                    seen_critic.add(critic)
            sections.append("\n".join(entry))
            continue

        if run_kind == "recovery":
            parent_task = val.get("parent_task", "")
            label = f"[recovery for: {parent_task}]" if parent_task else "[recovery]"
            entry = [f"{label} {task}: {outcome}"]
            if summary:
                s = summary.strip()
                prefix_cut = f"{task}: {outcome} | "
                if s.startswith(prefix_cut):
                    s = s[len(prefix_cut) :]
                if s and s != task:
                    entry.append(f"  {s[:200]}")
            sections.append("\n".join(entry))
            continue

        header = f"Run: {task}"
        if outcome:
            header += f" — {outcome}"
        entry = [header]
        if summary:
            s = summary.strip()
            prefix_cut = f"{task}: {outcome} | "
            if s.startswith(prefix_cut):
                s = s[len(prefix_cut) :]
            if s and s != task:
                entry.append(f"  {s[:200]}")

        pf = val.get("path_findings") or []
        rt = format_review_targets(paths, pf)
        if rt:
            for rt_line in rt.splitlines():
                entry.append(
                    f"  {rt_line}" if not rt_line.startswith("  ") else rt_line
                )
        else:
            if resolved:
                existing = [
                    rp["path"]
                    for rp in resolved
                    if rp["status"] in ("file", "directory")
                ]
                missing = [rp["path"] for rp in resolved if rp["status"] == "missing"]
                if existing:
                    entry.append(f"  Paths (exist): {', '.join(existing[:10])}")
                if missing:
                    entry.append(f"  Paths (missing): {', '.join(missing[:10])}")

        if _should_include_critic(val):
            critic = _format_critic_for_display(val)
            if critic and critic not in seen_critic:
                entry.append(f"  {critic}")
                seen_critic.add(critic)
        sections.append("\n".join(entry))

    text = "\n\n".join(s for s in sections if s)
    return text if text else None


def format_linked_run_result(linked: Dict[str, Any]) -> str:
    parent = linked.get("parent") or {}
    recovery = linked.get("recovery") or {}

    lines: list = []
    seen_critic: set = set()

    p_task = parent.get("task") or "unknown task"
    p_outcome = parent.get("outcome") or "unknown"
    p_summary = parent.get("summary") or ""
    p_paths = parent.get("touched_paths") or []
    lines.append(f"Failed run: {p_task}")
    lines.append(f"Outcome: {p_outcome}")
    if p_summary and p_summary.strip() != p_task:
        lines.append(f"Details: {p_summary.strip()[:200]}")
    p_findings = parent.get("path_findings") or []
    rt = format_review_targets(p_paths, p_findings, label_prefix="Failed-run ")
    if rt:
        lines.append(rt)
    p_critic = _format_critic_for_display(parent)
    if p_critic:
        lines.append(f"  {p_critic}")
        seen_critic.add(p_critic)

    lines.append("")

    r_task = recovery.get("task") or "recovery"
    r_outcome = recovery.get("outcome") or "unknown"
    r_summary = recovery.get("summary") or ""
    r_n_steps = recovery.get("n_steps") or 0
    r_n_failed = recovery.get("n_failed") or 0
    r_paths = recovery.get("touched_paths") or []
    lines.append(f"Recovery attempt: {r_task}")
    lines.append(f"Recovery outcome: {r_outcome}")
    if r_n_steps:
        lines.append(f"Steps attempted: {r_n_steps}")
    if r_summary and r_summary.strip() != r_task:
        lines.append(f"Summary: {r_summary.strip()[:200]}")
    rrt = format_review_targets(r_paths, [], label_prefix="Recovery ")
    if rrt:
        lines.append(rrt)
    r_critic = _format_critic_for_display(recovery)
    if r_critic and r_critic not in seen_critic:
        lines.append(f"  {r_critic}")

    if r_n_failed > 0:
        lines.append(f"Remaining failures: {r_n_failed} step(s) did not complete.")
    elif r_outcome in ("success", "recovered"):
        lines.append("Recovery succeeded.")

    return "\n".join(lines)


def _should_show_critic(val: Dict[str, Any]) -> bool:
    """Check if critic findings should be surfaced for this run artifact.

    Only show critic for:
    - Failed tool runs (where critic adds value)
    - Runs with actual issues (not trivial help/status tools)
    """
    if not val:
        return False
    tool = val.get("tool", "").lower()
    outcome = val.get("outcome", "")

    if tool and tool in CRITIC_TRIVIAL_TOOLS:
        return False
    if outcome == "success":
        has_issues = bool(val.get("critic_issues"))
        return has_issues
    return True


def _format_critic_line(val: Dict[str, Any]) -> str:
    """Format a single critic finding line for operator output."""
    critic_issues = val.get("critic_issues") or []
    critic_lesson = val.get("critic_lesson", "")
    if critic_issues:
        return f"Lesson: {critic_issues[0][:100]}"
    if critic_lesson:
        return f"Lesson: {critic_lesson[:100]}"
    return ""


class RunHistoryService:
    def __init__(self, memory) -> None:
        self._memory = memory
        self._last_persist_failed: bool = False

    def seat_summarize_run(self, run_artifact: Dict[str, Any]) -> str:
        content = format_run_artifact_content(run_artifact)
        try:
            from core.agent_model_manager import get_agent_model_manager

            mgr = get_agent_model_manager()
            if not mgr._no_model_mode:
                result = mgr.execute(
                    task="summarize run",
                    context={
                        "content_type": "run_artifact",
                        "content": content,
                        "memory": self._memory,
                    },
                    explicit_role="summarizer",
                )
                if result.success and result.output:
                    out = result.output
                    summary = (
                        out.get("summary", "") if isinstance(out, dict) else str(out)
                    )
                    if isinstance(summary, str) and len(summary.strip()) > 10:
                        return summary.strip()
        except Exception:
            pass
        return build_compact_digest_summary(run_artifact)

    def persist_run_digest(self, run_artifact: Dict[str, Any], summary: str) -> None:
        import hashlib
        from datetime import datetime

        try:
            task = run_artifact.get("task", "unknown")
            outcome = run_artifact.get("outcome", "unknown")
            failed = run_artifact.get("failed", [])
            recovery = run_artifact.get("recovery")
            ts = datetime.now().isoformat(timespec="seconds")

            run_key = "run:" + hashlib.md5(f"{task}{ts}".encode()).hexdigest()[:8]

            recovery_run_id: Optional[str] = None
            recovery_exec = recovery.get("recovery_execution") if recovery else None
            if recovery_exec and recovery_exec.get("steps"):
                rec_task = recovery_exec.get("task", task)
                rec_outcome = recovery_exec.get("outcome", "unknown")
                rec_ts = datetime.now().isoformat(timespec="seconds")
                rec_key = (
                    "run:recovery:"
                    + hashlib.md5(f"{rec_task}{rec_ts}".encode()).hexdigest()[:8]
                )
                recovery_run_id = rec_key

                rec_n_steps = len(recovery_exec.get("steps", []))
                rec_paths = extract_touched_paths(recovery_exec)
                rec_steps = recovery_exec.get("steps", [])
                rec_done = [s for s in rec_steps if s.get("status") == "done"]
                rec_fail = recovery_exec.get("failed", [])
                rec_compact = build_compact_digest_summary(recovery_exec)
                rec_digest = {
                    "run_id": rec_key,
                    "run_kind": "recovery",
                    "parent_run_id": run_key,
                    "parent_task": task,
                    "task": rec_task,
                    "outcome": rec_outcome,
                    "n_steps": rec_n_steps,
                    "n_failed": len(rec_fail),
                    "n_skipped": sum(
                        1 for s in rec_steps if s.get("status") == "skipped"
                    ),
                    "completed_steps": [
                        {
                            "step": s.get("step"),
                            "action": s.get("action"),
                            "target": s.get("target", ""),
                        }
                        for s in rec_done[:8]
                    ],
                    "failed_steps": [
                        {
                            "step": s.get("step"),
                            "action": s.get("action"),
                            "target": s.get("target", ""),
                            "error": (s.get("error") or "")[:120],
                        }
                        for s in rec_fail[:3]
                    ],
                    "key_errors": list(
                        dict.fromkeys(
                            (s.get("error") or "")[:80]
                            for s in rec_fail
                            if s.get("error")
                        )
                    )[:3],
                    "outcome_badge": outcome_badge(rec_outcome),
                    "summary": rec_compact,
                    "ts": rec_ts,
                    "touched_paths": rec_paths,
                    "path_findings": run_artifact.get("path_findings") or [],
                }
                self._memory.save_fact(
                    rec_key,
                    rec_digest,
                    source="run_artifact",
                    confidence=0.9,
                    topic="run_history",
                )

            steps = run_artifact.get("steps", [])
            done_steps = [s for s in steps if s.get("status") == "done"]
            fail_steps = [s for s in steps if s.get("status") == "failed"]
            n_skipped = sum(1 for s in steps if s.get("status") == "skipped")
            compact_summary = build_compact_digest_summary(run_artifact)
            parent_paths = extract_touched_paths(run_artifact)
            run_kind = run_artifact.get("run_kind", "primary")
            digest: Dict[str, Any] = {
                "run_id": run_key,
                "run_kind": run_kind,
                "task": task,
                "outcome": outcome,
                "n_steps": len(steps),
                "n_failed": len(failed),
                "n_skipped": n_skipped,
                "completed_steps": [
                    {
                        "step": s.get("step"),
                        "action": s.get("action"),
                        "target": s.get("target", ""),
                    }
                    for s in done_steps[:8]
                ],
                "failed_steps": [
                    {
                        "step": s.get("step"),
                        "action": s.get("action"),
                        "target": s.get("target", ""),
                        "error": (s.get("error") or "")[:120],
                    }
                    for s in fail_steps[:3]
                ],
                "key_errors": list(
                    dict.fromkeys(
                        (s.get("error") or "")[:80]
                        for s in fail_steps
                        if s.get("error")
                    )
                )[:3],
                "recovery_outcome": recovery.get("outcome") if recovery else None,
                "recovery_run_id": recovery_run_id,
                "summary": compact_summary,
                "ts": ts,
                "touched_paths": parent_paths,
                "outcome_badge": outcome_badge(outcome),
                "path_findings": run_artifact.get("path_findings") or [],
            }
            if run_kind == "tool":
                digest["tool"] = run_artifact.get("tool", "")
                digest["target"] = run_artifact.get("target", "")
                digest["key_output"] = run_artifact.get("key_output", "")
                digest["key_error"] = format_error_compact(run_artifact.get("key_error", ""))

            critic_fields = extract_critic_fields(run_artifact.get("critic", ""))
            if critic_fields:
                digest.update(critic_fields)

            self._memory.save_fact(
                "run:last",
                digest,
                source="run_artifact",
                confidence=0.9,
                topic="run_history",
            )
            self._memory.save_fact(
                run_key,
                digest,
                source="run_artifact",
                confidence=0.9,
                topic="run_history",
            )
            self._last_persist_failed = False
        except Exception as e:
            self._last_persist_failed = True
            print(f"Error persisting run digest: {e}")
