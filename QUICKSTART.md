# Karma v3.8.0 — Quick Start

## System State (2026-04-19)

Karma is **operational** on this machine. Ollama is healthy, all 6 agent roles are assigned,
and `--ready` reports READY. No setup required before running.

```bash
# Confirm ready state
python3 agent/agent_loop.py --ready

# Inspect model assignments
python3 agent/agent_loop.py --models
```

See `docs/model_ops_runbook.md` for operator commands.

---

## Shortest Path to Run

```bash
cd /home/mikoleye/karma
./karma gui
```

Web UI at http://localhost:5000

## Required Commands

```bash
# Install Flask if needed
pip install flask

# Start web UI
./karma gui

# Or direct Python start
python3 ui/web.py
```

## First Checks

After starting, open http://localhost:5000 and verify:

1. Page loads with "Karma" title
2. Nav buttons (Chat, GoLearn, Memory, System, Evidence, Telemetry, Models) visible
3. Status dot is green (connected)

## First Functional Checks

In the Chat view, type:
```
what can you do
```
Expected: Lists tools and memory stats.

```
list files in core
```
Expected: Shows `path: .../karma/core` with entries like `action_registry.py`, etc.

```
the third one
```
Expected: "Got it. You mean: action_registry.py"

```
summarize that
```
Expected: Shows file role and symbols.

## Confirm Working State

```bash
# Run full test suite
python3 -m pytest tests/ -q
# Expected: 344 passed

# Test agent boots
python3 -c "
from agent.bootstrap import load_config, build_agent
a = build_agent(load_config())
print(a.run('what can you do'))
a.stop()
"
# Expected: lists tools and memory stats

# Check all API endpoints
python3 -c "
import urllib.request, json
for ep in ['/api/state', '/api/health', '/api/models', '/api/agents']:
    r = urllib.request.urlopen('http://localhost:5000' + ep)
    d = json.loads(r.read())
    print(ep, d.get('ok', 'raw'))
"
# Expected: /api/state True, /api/health True, /api/models True, /api/agents True
```

## Key File Locations

| What | Where |
|------|-------|
| Config | `config.json` |
| Log | `data/logs/karma.log` |
| State | `data/agent_state.json` |
| Facts | `data/facts.json` |
| Version | `karma_version.py` → 3.8.0 |
