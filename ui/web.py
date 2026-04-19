"""Karma Web UI — Flask dashboard for DeX.

Runs on Dell at 0.0.0.0:5000. Access via local network IP
SSE for live event streaming. JSON API for all data.

Unified API response schema:
{
    "ok": boolean,
    "data": any,
    "error": {
        "code": string,
        "message": string,
        "details": any
    } | null,
    "revision": integer,
    "ts": string
}
"""

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

try:
    from flask import Flask, Response, jsonify, render_template, request

    FLASK_IMPORT_ERROR = None
except Exception as e:
    Flask = None
    Response = jsonify = render_template = request = None
    FLASK_IMPORT_ERROR = e

# Ensure project root on sys.path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agent.bootstrap import load_config, build_agent, get_version, PROJECT_ROOT
from agent.agent_loop import AgentLoop

# Request tracking for stale response protection
_request_counter = 0
_request_lock = threading.Lock()


def _next_request_id() -> int:
    global _request_counter
    with _request_lock:
        _request_counter += 1
        return _request_counter


def api_response(
    data: Any = None, error: Optional[Dict] = None, revision: int = 0
) -> Dict:
    """Build unified API response with schema."""
    return {
        "ok": error is None,
        "data": data,
        "error": error,
        "revision": revision,
        "ts": datetime.now().isoformat(),
    }


def api_error(code: str, message: str, details: Any = None, revision: int = 0) -> Dict:
    """Build error response with translation."""
    return api_response(
        data=None,
        error={"code": code, "message": message, "details": details},
        revision=revision,
    )


if Flask is not None:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
else:
    app = None

# Singleton agent
_agent = None
_agent_lock = threading.Lock()
_run_lock = threading.Lock()
_base_dir = Path(__file__).resolve().parent.parent


def get_agent() -> AgentLoop:
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                _agent = build_agent()
    return _agent


# ── Pages ──────────────────────────────────────────────────


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/mobile")
def mobile():
    return render_template("mobile.html")


# ── API ────────────────────────────────────────────────────


@app.route("/api/chat", methods=["POST"])
def run_chat():
    """Chat endpoint - for free-form natural language.

    Always routes to chat lane, never to tools.
    """
    data = request.get_json(silent=True) or {}
    text = data.get("message", "").strip()
    if not text:
        return jsonify(api_error("EMPTY_INPUT", "No message provided")), 400

    agent = get_agent()
    revision_before = agent.get_revision()

    # Force safe mode for chat endpoint
    was_safe = agent.is_safe_mode()
    agent.set_safe_mode(True)

    try:
        with _run_lock:
            result = agent.run(text)
        revision_after = agent.get_revision()

        return jsonify(
            api_response(
                data={
                    "response": result,
                    "lane": agent.get_current_lane(),
                    "revision_before": revision_before,
                    "revision_after": revision_after,
                },
                revision=revision_after,
            )
        )
    except Exception as e:
        revision = agent.get_revision()
        return jsonify(api_error("CHAT_ERROR", str(e), revision=revision)), 500
    finally:
        agent.set_safe_mode(was_safe)


@app.route("/api/command", methods=["POST"])
def run_command():
    """Command endpoint - for explicit commands with tool execution."""
    data = request.get_json(silent=True) or {}
    text = data.get("command", "").strip()
    if not text:
        return jsonify(api_error("EMPTY_INPUT", "No command provided")), 400

    request_id = _next_request_id()
    agent = get_agent()
    revision_before = agent.get_revision()

    # Disable safe mode for command endpoint - allow tool execution
    was_safe = agent.is_safe_mode()
    agent.set_safe_mode(False)

    try:
        with _run_lock:
            result = agent.run(text)
        revision_after = agent.get_revision()

        return jsonify(
            api_response(
                data={
                    "result": result,
                    "lane": "command",
                    "request_id": request_id,
                    "revision_before": revision_before,
                    "revision_after": revision_after,
                },
                revision=revision_after,
            )
        )
    except Exception as e:
        revision = agent.get_revision()
        return jsonify(api_error("COMMAND_ERROR", str(e), revision=revision)), 500
    finally:
        agent.set_safe_mode(was_safe)


@app.route("/api/state")
def get_state():
    """Get current agent state with revision."""
    agent = get_agent()
    revision = agent.get_revision()
    state_file = agent._state_file()
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            return jsonify(api_response(data=state, revision=revision))
        except Exception:
            pass
    return jsonify(api_response(data=agent.current_state, revision=revision))


@app.route("/api/session/summary")
def get_session_summary():
    """Get session summary - what Karma did this session."""
    agent = get_agent()
    revision = agent.get_revision()
    summary = agent._build_session_summary()
    formatted = agent._format_session_summary(summary)
    return jsonify(
        api_response(
            data={"summary": summary, "formatted": formatted}, revision=revision
        )
    )


@app.route("/api/session/selfcheck")
def get_self_check():
    """Get self-check - Karma's health introspection."""
    agent = get_agent()
    revision = agent.get_revision()
    check = agent._try_self_check_response("self-check")
    return jsonify(api_response(data={"check": check}, revision=revision))


@app.route("/api/runs/recent")
def get_recent_runs():
    """Get recent run history with outcomes."""
    agent = get_agent()
    revision = agent.get_revision()
    memory = agent.memory
    recent = []
    if memory and hasattr(memory, "facts"):
        for key, val in list(memory.facts.items())[:15]:
            if key.startswith("run:"):
                value = val.get("value", val) if isinstance(val, dict) else {}
                outcome = value.get("outcome", "")
                recent.append(
                    {
                        "key": key,
                        "task": value.get("task", ""),
                        "outcome": outcome,
                        "summary": value.get("summary", "")[:100],
                        "run_kind": value.get("run_kind", ""),
                        "tool": value.get("tool", ""),
                        "error": value.get("error", ""),
                        "recovered": value.get("recovered", False),
                        "timestamp": value.get("timestamp", ""),
                        "critic_issues": value.get("critic_issues", []),
                        "critic_lesson": value.get("critic_lesson", ""),
                    }
                )

    # Also get latest from execution log
    state_data = agent.current_state
    exec_log = state_data.get("execution_log", [])
    last_exec = exec_log[-1] if exec_log else {}

    return jsonify(
        api_response(
            data={
                "recent_runs": recent,
                "last_task": last_exec.get("intent", {}).get("intent", ""),
                "last_outcome": "success" if last_exec.get("success") else "failed",
                "last_error": last_exec.get("execution_result", {}).get("error"),
            },
            revision=revision,
        )
    )


@app.route("/api/runs/<path:run_key>")
def get_run_detail(run_key):
    """Get detailed run information by key."""
    agent = get_agent()
    revision = agent.get_revision()
    memory = agent.memory

    full_key = run_key if run_key.startswith("run:") else f"run:{run_key}"

    if memory and hasattr(memory, "facts") and full_key in memory.facts:
        val = memory.facts[full_key]
        value = val.get("value", val) if isinstance(val, dict) else {}
        return jsonify(
            api_response(
                data={
                    "key": full_key,
                    "task": value.get("task", ""),
                    "outcome": value.get("outcome", ""),
                    "summary": value.get("summary", ""),
                    "run_kind": value.get("run_kind", ""),
                    "tool": value.get("tool", ""),
                    "error": value.get("error", ""),
                    "recovered": value.get("recovered", False),
                    "timestamp": value.get("timestamp", ""),
                    "digest": value.get("digest", ""),
                },
                revision=revision,
            )
        )

    return jsonify(
        api_error("NOT_FOUND", f"Run {run_key} not found", revision=revision)
    ), 404


@app.route("/api/session")
def get_session():
    """Get session summary and self-check for operator visibility."""
    agent = get_agent()
    revision = agent.get_revision()

    summary = agent._build_session_summary()
    formatted = agent._format_session_summary(summary)
    check = agent._try_self_check_response("self-check")

    state_data = agent.current_state
    exec_log = state_data.get("execution_log", [])

    return jsonify(
        api_response(
            data={
                "summary": summary,
                "formatted": formatted,
                "selfcheck": check,
                "session_start": state_data.get("session_start_ts", ""),
                "recent_outcomes": [
                    {
                        "intent": e.get("intent", {}).get("intent", ""),
                        "success": e.get("success", False),
                        "confidence": e.get("confidence", 0),
                        "error": e.get("execution_result", {}).get("error", ""),
                    }
                    for e in exec_log[-10:]
                ],
            },
            revision=revision,
        )
    )


@app.route("/api/facts")
def get_facts():
    agent = get_agent()
    items = sorted(
        agent.memory.facts.items(),
        key=lambda kv: (
            float(kv[1].get("confidence", 0.0)) if isinstance(kv[1], dict) else 0.0
        ),
        reverse=True,
    )[:100]
    return jsonify([{"key": k, "value": v} for k, v in items])


@app.route("/api/tasks")
def get_tasks():
    agent = get_agent()
    tasks = sorted(
        agent.memory.tasks.values(),
        key=lambda t: int(t.get("priority", 99)),
    )[:50]
    return jsonify(tasks)


@app.route("/api/memory")
def get_memory():
    agent = get_agent()
    stats = agent.memory.get_stats()
    learn_dir = _base_dir / "data" / "learn"
    if learn_dir.exists():
        stats["learn_sessions"] = len([d for d in learn_dir.iterdir() if d.is_dir()])
    return jsonify(stats)


@app.route("/api/tools")
def get_tools():
    agent = get_agent()
    enabled = agent.config.get("tools", {}).get("enabled", [])
    registered = agent.tool_manager.list_tools()
    custom = []
    if hasattr(agent, "tool_builder") and hasattr(agent.tool_builder, "registry"):
        reg = agent.tool_builder.registry
        if isinstance(reg, list):
            custom = [e.get("name", "?") for e in reg if isinstance(e, dict)]
        elif isinstance(reg, dict):
            custom = list(reg.keys())
    return jsonify({"enabled": enabled, "registered": registered, "custom": custom})


@app.route("/api/system-map")
def get_system_map():
    """Return live system resource snapshot."""
    import shutil

    info = {}
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {l.split(":")[0]: l.split(":")[1].strip() for l in lines if ":" in l}
        info["ram_total"] = mem.get("MemTotal", "?")
        info["ram_available"] = mem.get("MemAvailable", "?")
        info["swap_total"] = mem.get("SwapTotal", "?")
        info["swap_free"] = mem.get("SwapFree", "?")
    except Exception:
        pass
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        info["load"] = f"{parts[0]} {parts[1]} {parts[2]}"
    except Exception:
        pass
    try:
        total, used, free = shutil.disk_usage("/")
        gb = 2**30
        info["disk"] = f"{used // gb}G / {total // gb}G"
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        h, m = divmod(int(up) // 60, 60)
        info["uptime"] = f"{h}h {m}m"
    except Exception:
        pass
    return jsonify(info)


@app.route("/api/timeline")
def get_timeline():
    """Return recent execution log entries for timeline display."""
    agent = get_agent()
    log = agent.current_state.get("execution_log", [])
    entries = []
    for entry in log[-20:]:
        intent = entry.get("intent", {})
        entries.append(
            {
                "time": entry.get("timestamp", ""),
                "intent": intent.get("intent", "?"),
                "success": entry.get("success", False),
                "confidence": round(entry.get("confidence", 0), 2),
            }
        )
    return jsonify(entries)


@app.route("/api/capabilities")
def get_capabilities():
    """Return all agent capabilities with v2 operational data."""
    agent = get_agent()
    caps = []
    # Built-in intents
    for name in sorted(agent._DIRECT_INTENTS):
        caps.append({"name": name, "type": "intent"})
    # Tools with capability map scores
    cap_map = agent.capability_map.get_full_map()
    for tool_name in agent.tool_manager.list_tools():
        entry = {"name": tool_name, "type": "tool"}
        if tool_name in cap_map:
            entry["score"] = cap_map[tool_name]
        caps.append(entry)
    # Custom tools
    if hasattr(agent, "tool_builder") and hasattr(agent.tool_builder, "registry"):
        reg = agent.tool_builder.registry
        if isinstance(reg, list):
            for e in reg:
                if isinstance(e, dict):
                    caps.append({"name": e.get("name", "?"), "type": "custom"})
        elif isinstance(reg, dict):
            for n in reg:
                caps.append({"name": n, "type": "custom"})
    return jsonify(caps)


@app.route("/api/health")
def get_health():
    """Return health report with repair classes and success rates."""
    agent = get_agent()
    try:
        report = agent.health.run_check()
        return jsonify(api_response(data=report, revision=agent.get_revision()))
    except Exception as e:
        return jsonify(
            api_error("HEALTH_ERROR", str(e), revision=agent.get_revision())
        ), 500


# ── Safe Mode & Revision ───────────────────────────────────


@app.route("/api/safe_mode", methods=["GET", "POST"])
def safe_mode():
    """Get or set safe mode.

    When safe mode is enabled, free-form natural language always goes to chat
    and is never routed to file/path/system tools.
    """
    agent = get_agent()

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        enabled = data.get("enabled", True)
        agent.set_safe_mode(enabled)

    return jsonify(
        api_response(
            data={
                "safe_mode": agent.is_safe_mode(),
                "description": "When enabled, free-form input always goes to chat lane",
            },
            revision=agent.get_revision(),
        )
    )


@app.route("/api/revision")
def get_revision():
    """Get current state revision and last mutation info."""
    agent = get_agent()
    return jsonify(
        api_response(
            data={
                "revision": agent.get_revision(),
                "last_mutation": agent.get_last_mutation(),
            },
            revision=agent.get_revision(),
        )
    )


@app.route("/api/lane")
def get_lane():
    """Get current routing lane for diagnostics."""
    agent = get_agent()
    return jsonify(
        api_response(
            data={
                "lane": agent.get_current_lane(),
                "safe_mode": agent.is_safe_mode(),
            },
            revision=agent.get_revision(),
        )
    )


@app.route("/api/capability-map")
def get_capability_map():
    """Return full capability map with operational data."""
    agent = get_agent()
    return jsonify(agent.capability_map.get_full_map())


@app.route("/api/retrieval-stats")
def get_retrieval_stats():
    """Return retrieval bus metrics."""
    agent = get_agent()
    return jsonify(agent.retrieval.get_metrics())


@app.route("/api/repair-history")
def get_repair_history():
    """Return repair outcome history."""
    agent = get_agent()
    return jsonify(agent.health._repair_history)


@app.route("/api/confidence")
def get_confidence():
    """Return confidence trend from execution log."""
    agent = get_agent()
    log = agent.current_state.get("execution_log", [])
    points = []
    for entry in log[-50:]:
        points.append(
            {
                "t": entry.get("timestamp", ""),
                "c": round(entry.get("confidence", 0), 3),
                "s": entry.get("success", False),
            }
        )
    return jsonify(
        {
            "current": round(agent.current_state.get("confidence", 0.5), 3),
            "points": points,
        }
    )


@app.route("/api/diagnostic")
def get_diagnostic():
    """Runtime diagnostic — verify code path and dialogue state."""
    agent = get_agent()
    from core import dialogue as dlg

    return jsonify(
        {
            "version": get_version(),
            "dialogue_api": [x for x in dir(dlg) if not x.startswith("_")],
            "conversation_type": type(agent.conversation).__name__,
            "has_retrieval_cs": agent.retrieval.conversation_state is not None,
            "conversation_fields": sorted(
                [f for f in vars(agent.conversation) if not f.startswith("_")]
            ),
            "current_topic": agent.conversation.current_topic,
            "artifact_count": len(agent.conversation.artifact_ledger),
            "thread_count": len(agent.conversation.threads),
            "scar_count": len(agent.conversation.scars),
            "answer_fragment_count": len(agent.conversation.answer_fragments),
        }
    )


_golearn_state = {
    "running": False,
    "result": None,
    "error": None,
    "topic": None,
    "started": None,
    "progress": "idle",
}
_golearn_lock = threading.Lock()


@app.route("/api/golearn", methods=["POST"])
def start_golearn():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    minutes = float(data.get("minutes", 5))
    mode = data.get("mode", "auto")
    if not topic:
        return jsonify({"error": "No topic provided"}), 400

    with _golearn_lock:
        if _golearn_state["running"]:
            return jsonify(
                {"error": "GoLearn already running", "topic": _golearn_state["topic"]}
            ), 409
        _golearn_state.update(
            running=True,
            result=None,
            error=None,
            topic=topic,
            started=time.time(),
            progress="starting",
        )

    def _run_golearn():
        agent = get_agent()
        cmd = f'golearn "{topic}" {int(minutes)} {mode}'
        try:
            with _run_lock:
                _golearn_state["progress"] = "researching"
                result = agent.run(cmd)
            with _golearn_lock:
                _golearn_state.update(result=result, running=False, progress="done")
        except Exception as e:
            with _golearn_lock:
                _golearn_state.update(error=str(e), running=False, progress="failed")

    threading.Thread(target=_run_golearn, daemon=True).start()
    return jsonify(
        {
            "success": True,
            "message": f"GoLearn started for '{topic}'",
            "poll": "/api/golearn/status",
        }
    )


@app.route("/api/golearn/status")
def golearn_status():
    with _golearn_lock:
        state = dict(_golearn_state)
    if state["started"]:
        state["elapsed_seconds"] = round(time.time() - state["started"], 1)
    return jsonify(state)


# ── SSE Events Stream ─────────────────────────────────────


@app.route("/api/events")
def event_stream():
    """Server-Sent Events stream from events.jsonl."""
    events_file = _base_dir / "data" / "events.jsonl"

    def generate():
        try:
            pos = events_file.stat().st_size if events_file.exists() else 0
        except OSError:
            pos = 0
        while True:
            try:
                size = events_file.stat().st_size
                if size > pos:
                    with open(events_file, "r") as f:
                        f.seek(pos)
                        new_lines = f.read()
                        pos = f.tell()
                    for line in new_lines.strip().splitlines():
                        try:
                            yield f"data: {line}\n\n"
                        except Exception:
                            continue
                elif size < pos:
                    pos = 0
            except OSError:
                pass
            time.sleep(1.0)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Log tail ──────────────────────────────────────────────


@app.route("/api/log")
def get_log():
    log_file = _base_dir / "data" / "logs" / "karma.log"
    if not log_file.exists():
        return jsonify({"lines": []})
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return jsonify({"lines": lines[-50:]})
    except Exception:
        return jsonify({"lines": []})


# ── Telemetry endpoints ────────────────────────────────────────


@app.route("/api/telemetry")
def get_telemetry():
    """Get telemetry snapshot."""
    from core.telemetry import get_telemetry_snapshot

    agent = get_agent()
    revision = agent.get_revision()
    snapshot = get_telemetry_snapshot()
    return jsonify(api_response(data=snapshot.get_snapshot(), revision=revision))


@app.route("/api/telemetry/events")
def get_telemetry_events():
    """Get recent telemetry events."""
    from core.telemetry import get_telemetry_snapshot

    agent = get_agent()
    revision = agent.get_revision()
    snapshot = get_telemetry_snapshot()
    limit = request.args.get("limit", 20, type=int)
    event_type = request.args.get("type", None)
    if event_type:
        events = snapshot.get_events_by_type(event_type, limit)
    else:
        events = snapshot.get_recent_events(limit)
    return jsonify(api_response(data=events, revision=revision))


# ── Route trace endpoints ─────────────────────────────────────


@app.route("/api/route-trace")
def get_route_trace():
    """Get latest route trace."""
    from core.routing_trace import get_route_tracer

    agent = get_agent()
    revision = agent.get_revision()
    tracer = get_route_tracer()
    latest = tracer.get_latest_trace()
    return jsonify(
        api_response(data=latest.to_dict() if latest else None, revision=revision)
    )


@app.route("/api/route-trace/all")
def get_all_route_traces():
    """Get all route traces."""
    from core.routing_trace import get_route_tracer

    agent = get_agent()
    revision = agent.get_revision()
    tracer = get_route_tracer()
    traces = [t.to_dict() for t in tracer.get_recent_traces(20)]
    return jsonify(api_response(data=traces, revision=revision))


# ── Action receipts endpoints ─────────────────────────────────


@app.route("/api/receipts")
def get_receipts():
    """Get recent action receipts."""
    from core.action_receipts import get_receipt_store

    agent = get_agent()
    revision = agent.get_revision()
    store = get_receipt_store()
    receipts = [r.to_dict() for r in store.get_recent_receipts(20)]
    return jsonify(api_response(data=receipts, revision=revision))


@app.route("/api/receipts/summary")
def get_receipts_summary():
    """Get receipts summary."""
    from core.action_receipts import get_receipt_store

    agent = get_agent()
    revision = agent.get_revision()
    store = get_receipt_store()
    return jsonify(api_response(data=store.get_summary(), revision=revision))


# ── Mutation log endpoints ────────────────────────────────────


@app.route("/api/mutations")
def get_mutations():
    """Get recent mutations."""
    from core.mutation_log import get_mutation_log

    agent = get_agent()
    revision = agent.get_revision()
    log = get_mutation_log()
    mutations = [m.to_dict() for m in log.get_recent_mutations(20)]
    return jsonify(api_response(data=mutations, revision=revision))


# ── System posture endpoints ─────────────────────────────────


@app.route("/api/posture")
def get_posture():
    """Get current system posture."""
    from core.posture import get_system_posture

    agent = get_agent()
    revision = agent.get_revision()
    posture = get_system_posture()
    return jsonify(
        api_response(data=posture.get_posture_with_metrics(), revision=revision)
    )


# ── Provider health endpoints ────────────────────────────────


@app.route("/api/providers/health")
def get_provider_health():
    """Get provider health status."""
    from core.provider_health import get_provider_health_monitor

    agent = get_agent()
    revision = agent.get_revision()
    monitor = get_provider_health_monitor()
    return jsonify(api_response(data=monitor.get_summary(), revision=revision))


# ── Artifact endpoints ───────────────────────────────────────


@app.route("/api/artifacts")
def get_artifacts():
    """Get recent artifacts."""
    from core.artifacts import get_artifact_store

    agent = get_agent()
    revision = agent.get_revision()
    store = get_artifact_store()
    artifacts = [a.to_dict() for a in store.get_recent_artifacts(20)]
    return jsonify(api_response(data=artifacts, revision=revision))


@app.route("/api/artifacts/search")
def search_artifacts():
    """Search artifacts."""
    from core.artifacts import get_artifact_store

    agent = get_agent()
    revision = agent.get_revision()
    query = request.args.get("q", "")
    store = get_artifact_store()
    artifacts = [a.to_dict() for a in store.search_artifacts(query)]
    return jsonify(api_response(data=artifacts, revision=revision))


# ── Scratchpad endpoints ─────────────────────────────────────


@app.route("/api/scratchpad")
def get_scratchpad():
    """Get scratchpad notes."""
    from core.scratchpad import get_scratchpad

    agent = get_agent()
    revision = agent.get_revision()
    scratch = get_scratchpad(str(_base_dir / "data" / "scratchpad.json"))
    notes = [
        {
            "note_id": n.note_id,
            "content": n.content,
            "timestamp": n.timestamp,
            "tags": n.tags,
        }
        for n in scratch.get_all_notes()
    ]
    return jsonify(api_response(data=notes, revision=revision))


@app.route("/api/scratchpad", methods=["POST"])
def add_scratchpad_note():
    """Add a scratchpad note."""
    from core.scratchpad import get_scratchpad

    agent = get_agent()
    revision = agent.get_revision()
    data = request.get_json() or {}
    content = data.get("content", "")
    tags = data.get("tags", [])
    scratch = get_scratchpad(str(_base_dir / "data" / "scratchpad.json"))
    note = scratch.add_note(content, tags)
    return jsonify(
        api_response(
            data={"note_id": note.note_id, "timestamp": note.timestamp},
            revision=revision,
        )
    )


# ── Drop bay endpoints ────────────────────────────────────────


@app.route("/api/dropbay")
def get_dropbay():
    """Get drop bay status."""
    from core.drop_bay import get_drop_bay

    agent = get_agent()
    revision = agent.get_revision()
    bay = get_drop_bay()
    return jsonify(api_response(data=bay.get_status(), revision=revision))


@app.route("/api/dropbay/items")
def get_dropbay_items():
    """Get drop bay items."""
    from core.drop_bay import get_drop_bay

    agent = get_agent()
    revision = agent.get_revision()
    bay = get_drop_bay()
    return jsonify(api_response(data=bay.get_all_items(), revision=revision))


# ── Model Scanner Endpoints ─────────────────────────────────


@app.route("/api/models/scan", methods=["POST"])
def scan_models():
    """Scan a path for local models."""
    from core.model_scanner import get_model_scanner

    agent = get_agent()
    revision = agent.get_revision()
    data = request.get_json() or {}
    path = data.get("path", "")
    recursive = data.get("recursive", True)

    if not path:
        return jsonify(
            api_error("INVALID_PATH", "No path provided", revision=revision)
        ), 400

    scanner = get_model_scanner()
    receipt = scanner.scan(path, recursive=recursive)

    return jsonify(
        api_response(
            data={
                "scan_path": receipt.scan_path,
                "scan_time": receipt.scan_time,
                "models_found": receipt.models_found,
                "candidates": receipt.candidates,
                "errors": receipt.errors,
            },
            revision=revision,
        )
    )


@app.route("/api/models/scan/last")
def get_last_scan():
    """Get the last scan receipt."""
    from core.model_scanner import get_model_scanner

    agent = get_agent()
    revision = agent.get_revision()
    scanner = get_model_scanner()
    last = scanner.get_last_scan()

    if not last:
        return jsonify(api_response(data=None, revision=revision))

    return jsonify(
        api_response(
            data={
                "scan_path": last.scan_path,
                "scan_time": last.scan_time,
                "models_found": last.models_found,
                "candidates": last.candidates,
                "errors": last.errors,
            },
            revision=revision,
        )
    )


# ── Slot Manager Endpoints ─────────────────────────────────


@app.route("/api/slots")
def get_slots():
    """Get all slots and their assignments."""
    from core.slot_manager import get_slot_manager

    agent = get_agent()
    revision = agent.get_revision()
    manager = get_slot_manager(str(_base_dir / "data" / "slot_assignments.json"))
    slots = manager.get_all_slots()
    roles = manager.get_all_roles()
    return jsonify(
        api_response(data={"slots": slots, "roles": roles}, revision=revision)
    )


@app.route("/api/slots/assign", methods=["POST"])
def assign_slot():
    """Assign a model to a slot or role."""
    from core.slot_manager import get_slot_manager
    from models import get_model_registry

    agent = get_agent()
    revision = agent.get_revision()
    data = request.get_json() or {}

    slot = data.get("slot")
    role = data.get("role")
    model_id = data.get("model_id")
    deterministic = data.get("deterministic", False)

    manager = get_slot_manager(str(_base_dir / "data" / "slot_assignments.json"))

    if slot:
        success = manager.assign_model(slot, model_id, deterministic)
    elif role:
        success = manager.assign_role(role, model_id, deterministic)
    else:
        return jsonify(
            api_error(
                "INVALID_ASSIGNMENT", "Must specify slot or role", revision=revision
            )
        ), 400

    if success:
        return jsonify(api_response(data={"success": True}, revision=revision))
    return jsonify(
        api_error("ASSIGNMENT_FAILED", "Failed to assign", revision=revision)
    )


# ── Agent/Model Control Panel Endpoints ────────────────────────────


@app.route("/api/agents")
def get_agents():
    """Get all registered agents with status."""
    from agents import get_all_agents

    agent = get_agent()
    revision = agent.get_revision()

    all_agents = get_all_agents()
    agents_data = []
    for role, a in all_agents.items():
        agents_data.append(
            {
                "role": role,
                "status": a.status.value,
                "available": a.is_available,
                "capabilities": {
                    "can_plan": a.get_capabilities().can_plan,
                    "can_execute": a.get_capabilities().can_execute,
                    "can_retrieve": a.get_capabilities().can_retrieve,
                    "can_summarize": a.get_capabilities().can_summarize,
                    "can_criticize": a.get_capabilities().can_criticize,
                    "can_navigate": a.get_capabilities().can_navigate,
                    "requires_model": a.get_capabilities().requires_model,
                },
                "execution_count": a._execution_count,
                "last_error": a.last_error,
            }
        )

    return jsonify(api_response(data=agents_data, revision=revision))


@app.route("/api/models")
def get_models():
    """Get all registered models with status."""
    from core.agent_model_manager import get_agent_model_manager

    agent = get_agent()
    revision = agent.get_revision()
    manager = get_agent_model_manager()
    manager.initialize()

    models = manager.get_available_models()
    loaded = manager.get_loaded_models()

    for m in models:
        m["loaded"] = m["model_id"] in loaded

    return jsonify(api_response(data=models, revision=revision))


@app.route("/api/models/register", methods=["POST"])
def register_model():
    """Register a discovered model."""
    from core.agent_model_manager import get_agent_model_manager
    from models.local_llm_adapter import create_llm_adapter

    agent = get_agent()
    revision = agent.get_revision()
    data = request.get_json() or {}

    model_path = data.get("path")
    model_name = data.get("name", "unknown")
    model_type = data.get("type", "llm")

    if not model_path:
        return jsonify(
            api_error("INVALID_MODEL", "No model path provided", revision=revision)
        ), 400

    manager = get_agent_model_manager()

    # Create adapter based on type
    if model_type == "embedding":
        from models.local_embedding_adapter import create_embedding_adapter

        adapter = create_embedding_adapter(model_name, model_path)
    else:
        adapter = create_llm_adapter(model_name, model_path)

    manager.register_model(model_name, adapter)

    return jsonify(
        api_response(
            data={"model_id": model_name, "registered": True}, revision=revision
        )
    )


@app.route("/api/models/load", methods=["POST"])
def load_model():
    """Load a model into memory."""
    from core.agent_model_manager import get_agent_model_manager

    agent = get_agent()
    revision = agent.get_revision()
    data = request.get_json() or {}
    model_id = data.get("model_id")

    if not model_id:
        return jsonify(
            api_error("INVALID_MODEL", "No model_id provided", revision=revision)
        ), 400

    manager = get_agent_model_manager()
    success = manager.load_model(model_id)

    return jsonify(
        api_response(data={"model_id": model_id, "loaded": success}, revision=revision)
    )


@app.route("/api/models/unload", methods=["POST"])
def unload_model():
    """Unload a model from memory."""
    from core.agent_model_manager import get_agent_model_manager

    agent = get_agent()
    revision = agent.get_revision()
    data = request.get_json() or {}
    model_id = data.get("model_id")

    if not model_id:
        return jsonify(
            api_error("INVALID_MODEL", "No model_id provided", revision=revision)
        ), 400

    manager = get_agent_model_manager()
    success = manager.unload_model(model_id)

    return jsonify(
        api_response(
            data={"model_id": model_id, "unloaded": success}, revision=revision
        )
    )


@app.route("/api/pipeline/status")
def get_pipeline_status():
    """Get agent/model pipeline status."""
    from core.agent_model_manager import get_agent_model_manager
    from core.identity_guard import get_identity_guard
    from core.role_router import get_role_router

    agent = get_agent()
    revision = agent.get_revision()

    manager = get_agent_model_manager()
    manager.initialize()
    status = manager.get_status()

    guard = get_identity_guard()
    router = get_role_router()

    return jsonify(
        api_response(
            data={
                "manager": status,
                "available_roles": router.get_available_roles(),
                "identity_guard_active": True,
            },
            revision=revision,
        )
    )


@app.route("/api/pipeline/execute", methods=["POST"])
def execute_pipeline():
    """Execute a task through the pipeline."""
    from core.agent_model_manager import get_agent_model_manager

    agent = get_agent()
    revision = agent.get_revision()
    data = request.get_json() or {}

    task = data.get("task", "")
    role = data.get("role")
    force_no_model = data.get("force_no_model", True)

    if not task:
        return jsonify(
            api_error("INVALID_TASK", "No task provided", revision=revision)
        ), 400

    manager = get_agent_model_manager()
    manager.initialize()

    result = manager.execute(task, explicit_role=role, force_no_model=force_no_model)

    return jsonify(
        api_response(
            data={
                "success": result.success,
                "output": result.output,
                "role_used": result.role_used,
                "model_used": result.model_used,
                "pipeline_type": result.pipeline_type,
                "identity_guard_applied": result.identity_guard_applied,
                "execution_time_ms": result.execution_time_ms,
                "error": result.error,
            },
            revision=revision,
        )
    )


# ── Active Runtime Endpoint ─────────────────────────────────────


@app.route("/api/active_runtime")
def get_active_runtime():
    """Get current runtime state - role, slot, model, node, execution mode."""
    from core.slot_manager import get_slot_manager
    from core.posture import get_system_posture
    from core.action_receipts import get_receipt_store
    from core.mutation_log import get_mutation_log

    agent = get_agent()
    revision = agent.get_revision()

    # Get current slot manager state
    slot_manager = get_slot_manager(str(_base_dir / "data" / "slot_assignments.json"))

    # Get active role from agent state file
    current_role = None
    current_task = None
    try:
        state_file = agent._state_file()
        if state_file.exists():
            state = json.loads(state_file.read_text())
            current_role = state.get("current_role")
            current_task = state.get("current_task")
    except Exception:
        pass

    # Get slot assignments
    roles = slot_manager.get_all_roles()
    active_slot = None
    active_model = None
    for r in roles:
        if r.get("role") == current_role:
            active_slot = r.get("slot")
            active_model = r.get("assigned_model_id")
            break

    # Get posture
    posture = get_system_posture()
    posture_data = posture.get_posture_with_metrics()

    # Get latest receipt
    receipts = get_receipt_store()
    latest_receipt = receipts.get_latest_receipt()

    # Get latest mutation
    mutations = get_mutation_log()
    latest_mutation = mutations.get_latest_mutation()

    # Determine execution mode
    execution_mode = "local"
    fallback_used = False

    # Check if anything is active
    is_active = current_task is not None and current_task != ""

    runtime_data = {
        "is_active": is_active,
        "current_role": current_role or "none",
        "current_task": current_task or "none",
        "active_slot": active_slot or "none",
        "active_model": active_model or "none",
        "execution_mode": execution_mode,
        "fallback_used": fallback_used,
        "posture": posture_data.get("posture", "CALM"),
        "latest_receipt": {
            "action": latest_receipt.action_name if latest_receipt else None,
            "handler": latest_receipt.handler if latest_receipt else None,
            "status": latest_receipt.result_status if latest_receipt else None,
        }
        if latest_receipt
        else None,
        "latest_mutation": {
            "source": latest_mutation.source if latest_mutation else None,
            "change_type": latest_mutation.change_type if latest_mutation else None,
        }
        if latest_mutation
        else None,
    }

    return jsonify(api_response(data=runtime_data, revision=revision))


# ── Worker/Scheduler Endpoints ───────────────────────────────────


@app.route("/api/workers")
def get_workers():
    """Get all registered workers with status."""
    from distributed.worker_registry import get_worker_registry

    agent = get_agent()
    revision = agent.get_revision()
    registry = get_worker_registry()

    workers = registry.get_all()
    workers_data = []
    for w in workers:
        workers_data.append(
            {
                "node_id": w.node_id,
                "role": w.role,
                "status": w.status,
                "hostname": w.hostname,
                "ip_address": w.ip_address,
                "capabilities": {
                    "can_plan": w.capabilities.can_plan,
                    "can_execute": w.capabilities.can_execute,
                    "can_retrieve": w.capabilities.can_retrieve,
                    "can_summarize": w.capabilities.can_summarize,
                    "can_criticize": w.capabilities.can_criticize,
                    "can_embed": w.capabilities.can_embed,
                },
                "last_seen": w.last_seen,
                "metadata": w.metadata,
            }
        )

    return jsonify(api_response(data=workers_data, revision=revision))


@app.route("/api/workers/<worker_id>")
def get_worker(worker_id):
    """Get specific worker details."""
    from distributed.worker_registry import get_worker_registry
    from distributed.node_health import get_node_health

    agent = get_agent()
    revision = agent.get_revision()
    registry = get_worker_registry()

    worker = registry.get(worker_id)
    if not worker:
        return jsonify(
            api_error("NOT_FOUND", f"Worker {worker_id} not found", revision=revision)
        ), 404

    health_monitor = get_node_health()
    health = health_monitor.get_health(worker_id)

    return jsonify(
        api_response(
            data={
                "node_id": worker.node_id,
                "role": worker.role,
                "status": worker.status,
                "hostname": worker.hostname,
                "ip_address": worker.ip_address,
                "capabilities": {
                    "can_plan": worker.capabilities.can_plan,
                    "can_execute": worker.capabilities.can_execute,
                    "can_retrieve": worker.capabilities.can_retrieve,
                    "can_summarize": worker.capabilities.can_summarize,
                    "can_criticize": worker.capabilities.can_criticize,
                    "can_embed": worker.capabilities.can_embed,
                },
                "last_seen": worker.last_seen,
                "metadata": worker.metadata,
                "health": health,
            },
            revision=revision,
        )
    )


@app.route("/api/scheduler/summary")
def get_scheduler_summary():
    """Get scheduler summary with role assignments."""
    from distributed.scheduler import get_scheduler

    agent = get_agent()
    revision = agent.get_revision()
    scheduler = get_scheduler()

    summary = scheduler.get_schedule_summary()

    return jsonify(api_response(data=summary, revision=revision))


@app.route("/api/scheduler/execute", methods=["POST"])
def execute_scheduler():
    """Execute a role via scheduler."""
    from distributed.scheduler import get_scheduler

    agent = get_agent()
    revision = agent.get_revision()
    data = request.get_json() or {}

    role = data.get("role")
    input_data = data.get("input_data", {})
    force_worker = data.get("force_worker")
    allow_fallback = data.get("allow_fallback", True)

    if not role:
        return jsonify(
            api_error("INVALID_ROLE", "No role specified", revision=revision)
        ), 400

    scheduler = get_scheduler()
    result = scheduler.schedule(
        role=role,
        input_data=input_data,
        force_worker=force_worker,
        allow_fallback=allow_fallback,
    )

    return jsonify(
        api_response(
            data={
                "success": result.success,
                "task_id": result.task_id,
                "result": result.result,
                "worker_id": result.worker_id,
                "execution_time_ms": result.execution_time_ms,
                "error": result.error,
                "scheduling": {
                    "role": result.scheduling_decision.role,
                    "selected_worker": result.scheduling_decision.selected_worker,
                    "fallback_used": result.scheduling_decision.fallback_used,
                    "fallback_reason": result.scheduling_decision.fallback_reason,
                    "confidence": result.scheduling_decision.confidence,
                },
            },
            revision=revision,
        )
    )


@app.route("/api/health/nodes")
def get_nodes_health():
    """Get health status of all worker nodes."""
    from distributed.node_health import get_node_health

    agent = get_agent()
    revision = agent.get_revision()
    monitor = get_node_health()

    health_data = monitor.get_all_health()

    return jsonify(api_response(data=health_data, revision=revision))


# ── Prediction Engine Endpoints ─────────────────────────────────


@app.route("/api/predictions")
def get_predictions():
    """Get prediction engine summary."""
    from core.prediction_engine import get_prediction_engine

    agent = get_agent()
    revision = agent.get_revision()
    engine = get_prediction_engine(str(_base_dir))

    summary = engine.get_prediction_summary()
    pending = engine.get_pending_predictions()

    pending_data = [
        {
            "prediction_id": p.prediction_id,
            "domain": p.domain.value,
            "target": p.target,
            "expected": p.expected,
            "confidence": p.confidence,
            "expires_at": p.expires_at,
        }
        for p in pending[:20]
    ]

    return jsonify(
        api_response(
            data={
                "summary": summary,
                "pending_predictions": pending_data,
            },
            revision=revision,
        )
    )


@app.route("/api/predictions/mismatches")
def get_prediction_mismatches():
    """Get recent prediction mismatches."""
    from core.prediction_engine import get_prediction_engine, PredictionDomain

    agent = get_agent()
    revision = agent.get_revision()
    engine = get_prediction_engine(str(_base_dir))

    domain = request.args.get("domain")
    domain_enum = PredictionDomain(domain) if domain else None
    limit = int(request.args.get("limit", 20))

    mismatches = engine.get_mismatch_history(domain_enum, limit)

    mismatch_data = [
        {
            "mismatch_id": m.mismatch_id,
            "prediction_id": m.prediction_id,
            "domain": m.domain.value,
            "expected": m.expected,
            "actual": m.actual,
            "deviation": m.deviation,
            "severity": m.severity.value,
            "triggered_reasoning": m.triggered_reasoning,
            "timestamp": m.timestamp,
        }
        for m in mismatches
    ]

    return jsonify(api_response(data=mismatch_data, revision=revision))


# ── Telemetry Dashboard Endpoints ────────────────────────────────


@app.route("/api/telemetry/dashboard")
def get_telemetry_dashboard():
    """Get complete telemetry dashboard data."""
    from core.telemetry import get_telemetry_snapshot
    from core.posture import get_system_posture
    from core.action_receipts import get_receipt_store
    from core.mutation_log import get_mutation_log
    from core.routing_trace import get_route_tracer
    from core.agent_model_manager import get_agent_model_manager

    agent = get_agent()
    revision = agent.get_revision()

    # Get telemetry
    snapshot = get_telemetry_snapshot()
    telemetry = snapshot.get_snapshot()

    # Get posture
    posture = get_system_posture()
    posture_data = posture.get_posture_with_metrics()

    # Get recent receipt
    receipts = get_receipt_store()
    latest_receipt = receipts.get_latest_receipt()

    # Get last mutation
    mutations = get_mutation_log()
    last_mutation = mutations.get_latest_mutation()

    # Get latest route trace
    tracer = get_route_tracer()
    latest_trace = tracer.get_latest_trace()

    # Get pipeline status
    manager = get_agent_model_manager()
    manager.initialize()
    pipeline = manager.get_status()

    return jsonify(
        api_response(
            data={
                "posture": posture_data,
                "revision": revision,
                "latest_receipt": latest_receipt.to_dict() if latest_receipt else None,
                "last_mutation": last_mutation.to_dict() if last_mutation else None,
                "latest_route_trace": latest_trace.to_dict() if latest_trace else None,
                "events": telemetry.get("events", {}),
                "pipeline": pipeline,
            },
            revision=revision,
        )
    )


# ── Main ──────────────────────────────────────────────────


def main():
    if FLASK_IMPORT_ERROR is not None:
        raise RuntimeError(f"Flask is required for the web UI: {FLASK_IMPORT_ERROR}")
    cfg = load_config(str(_base_dir / "config.json"))
    web_cfg = cfg.get("web", {})
    host = web_cfg.get("host", "0.0.0.0")
    port = int(web_cfg.get("port", 5000))
    debug = web_cfg.get("debug", False)
    print(f"Karma Web UI: http://{host}:{port}")
    print(f"Phone access: http://<local-ip>:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    main()
