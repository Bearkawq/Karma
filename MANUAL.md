# Karma v3.8.0 — Operations Manual

## Architecture Overview

Karma is a local-only autonomous agent with symbolic NL parsing, lightweight ML, web research, persistent disk memory, and a Flask web UI. No cloud APIs. No external AI inference.

### Core Pipeline

```
User Input
    │
    ▼
Grammar Match (regex patterns, 0.95 confidence)
    │  if miss ▼
Symbolic Parser (SymbolicCore — rules + typo correction)
    │  if miss ▼
ML Classifier (Naive Bayes, trained from data/ml_intent_training.jsonl)
    │
    ▼
Routing Lane: command / chat / dialogue / golearn
    │
    ▼
Tool Execution (shell, file, system, research)
    │
    ▼
PostExecutor (artifact registration, conversation state update)
    │
    ▼
Responder (evidence-first answer from 6 memory strata)
    │
    ▼
Response + State Persistence
```

---

## Directory Map

```
karma/
├── agent/
│   ├── bootstrap.py          # Single config/agent factory entrypoint
│   ├── agent_loop.py         # Core 10-step loop
│   ├── dialogue_manager.py   # Handles correction/continuation/summary/introspection
│   └── reflection_engine.py  # Post-run reflection
├── core/
│   ├── actions/              # Action handlers: golearn, ingest, digest, navigate, pulse
│   ├── action_receipts/      # Receipt tracking
│   ├── artifacts/            # Artifact store
│   ├── telemetry/            # Metrics collection
│   ├── dialogue.py           # Dialogue act classifier
│   ├── conversation_state.py # ConversationState — subject, topic, artifact ledger
│   ├── symbolic.py           # Rule-based intent + entity extraction
│   ├── grammar.py            # Fast regex pattern matching
│   ├── planner.py            # HTN planner
│   ├── responder.py          # Evidence-first answer engine
│   ├── retrieval.py          # 6-strata retrieval bus
│   ├── capability_map.py     # Tool success/failure tracking
│   ├── slot_manager.py       # Local model slot assignments
│   └── agent_model_manager.py # Agent/model orchestration
├── ml/ml.py                  # Naive Bayes + logistic regression (stdlib only)
├── storage/
│   ├── memory.py             # Episodic + facts + tasks
│   ├── episodic.py           # Episode log
│   └── facts.py              # Fact store
├── tools/
│   ├── tool_interface.py     # Shell, file, system tools
│   ├── tool_builder.py       # Custom tool builder
│   ├── code_tool.py          # Code analysis tools
│   └── self_upgrade.py       # Self-modification tools
├── research/
│   ├── session.py            # GoLearn autonomous research sessions
│   ├── crawler.py            # DuckDuckGo search + page fetch
│   ├── providers/            # Provider chain: DuckDuckGo → Brave → Browser
│   └── knowledge_spine.py    # Knowledge extraction
├── distributed/              # Worker node orchestration
├── navigator/                # Wikipedia/browser navigation
├── ui/
│   ├── web.py                # Flask dashboard (port 5000)
│   ├── templates/dashboard.html
│   └── static/app.js, style.css, mobile.js
├── config/
│   ├── model_registry.json   # Local model registry
│   ├── model_preferences.json # Role-to-model mappings
│   └── agent_roles.json      # Agent role definitions
├── config.json               # Main config
├── karma_version.py          # Version: 3.8.0
├── karma                     # Launcher script
├── data/                     # Runtime data (logs, memory, state)
├── tests/                    # Test suite (344 tests)
├── scripts/                  # watchdog-daemon.py, bridge_watch.sh, etc.
├── docs/archive/             # Old completion reports and version logs
└── bridge/                   # Bridge inbox/outbox/planner/workers
```

---

## Install / Start / Run

### Prerequisites

```bash
pip install flask  # Required for web UI
# Optional: pip install psutil   (system monitoring)
# Optional: pip install requests (research module)
```

### Start Web UI

```bash
cd /home/mikoleye/karma
./karma gui
# or
python3 ui/web.py
```

Web UI at: http://localhost:5000 (or http://0.0.0.0:5000 for network access)

### Start CLI (direct agent loop)

```bash
cd /home/mikoleye/karma
python3 -c "
from agent.bootstrap import load_config, build_agent
agent = build_agent(load_config())
while True:
    text = input('> ')
    if text in ('quit', 'exit'): break
    print(agent.run(text))
agent.stop()
"
```

### Check Status

```bash
./karma status   # Shows running services
./karma log      # Tail the log
```

---

## Config Guide

Main config: `config.json`

| Key | Description |
|-----|-------------|
| `system.offline` | `true` — no remote calls allowed |
| `web.port` | Flask port (default 5000) |
| `memory.*_file` | Paths to episodic, facts, tasks, state files |
| `tools.enabled` | Active tools: `shell`, `file`, `system`, `research` |
| `tools.shell.allowed_commands` | Whitelisted shell commands |
| `tools.research.max_session_minutes` | GoLearn session cap |
| `logging.level` | DEBUG/INFO/WARNING |
| `confidence.threshold` | Min confidence before asking for clarification |
| `ml.models` | ML model configs (intent classifier, candidate scorer) |

---

## Local Model Guide

Karma supports pluggable local models via `config/model_registry.json`. Currently empty — no models registered.

### Register an Ollama Model

1. Start Ollama: `ollama serve`
2. Pull a model: `ollama pull llama3.2`
3. Register in `config/model_registry.json`:

```json
{
  "models": [
    {
      "model_id": "llama3.2",
      "model_type": "llm",
      "local_path": null,
      "metadata": {
        "memory_footprint_mb": 4096,
        "capabilities": {
          "supports_generate": true,
          "supports_embed": false,
          "context_window": 8192,
          "max_tokens": 4096
        }
      }
    }
  ]
}
```

4. Assign to a role in `config/model_preferences.json`:

```json
{
  "role_preferences": {
    "planner": { "preferred_model": "llama3.2", "fallback_models": [] }
  }
}
```

Without registered models, Karma operates in symbolic-only mode (grammar + ML classifier). This is fully functional for all built-in intents.

---

## UI Walkthrough

The web dashboard has 7 views (keyboard shortcuts 1-7):

| View | Key | Description |
|------|-----|-------------|
| Chat | 1 | Natural language chat with safe mode |
| GoLearn | 2 | Autonomous web research on a topic |
| Memory | 3 | Facts, episodes, tasks |
| System | 4 | Health, tools, capabilities, telemetry |
| Evidence | 5 | Retrieval evidence and fragments |
| Telemetry | 6 | Execution log, route traces |
| Models | 7 | Model slots, agents, capabilities |

### Chat vs Command

- **Chat** (`/api/chat`): Safe mode — runs language flow only, no tool execution
- **Command** (`/api/command`): Tool mode — executes shell/file/research tools

### Status Indicators

- **Status dot** (top right): Green = connected, Red = error
- **Confidence gauge**: Live agent confidence (0.0–1.0)
- **Clock**: Local time

---

## Operating Instructions

### Common Commands

```
list files                  → lists project root entries
list files in core          → lists core/ directory
read config.json            → reads and displays file
the second one              → selects 2nd item from last listing
the third one               → selects 3rd item from last listing
summarize that              → summarizes current subject
go on                       → continues discussing current subject
what can you do             → shows capabilities
golearn python asyncio      → researches topic via web search
status                      → agent health status
self check                  → runs internal diagnostic
```

### Ordinal Selection

After a listing (`list files in X`), reference items by position:
- "the first one" → item 1 (skips `__pycache__`)
- "the second one" → item 2
- "the third one" → item 3
- "that file" → most recently mentioned file
- "that folder" → most recently mentioned folder

---

## Logs / State Guide

| Path | Contents |
|------|----------|
| `data/logs/karma.log` | Main application log |
| `data/episodic.jsonl` | Episode memory (append-only) |
| `data/facts.json` | Persistent facts |
| `data/agent_state.json` | Agent state (confidence, history) |
| `data/decision_trace.jsonl` | Routing decision trace |
| `data/events.jsonl` | Event bus log |
| `data/capability_map.json` | Tool capability scores |
| `data/health_memory.json` | Health check history |

---

## Troubleshooting

### Port already in use
```bash
lsof -i :5000
# kill the conflicting process, or use a different port:
WEB_PORT=5001 python3 ui/web.py
```

### Flask not found
```bash
pip install flask
```

### Agent won't boot
```bash
python3 -c "from agent.bootstrap import load_config, build_agent; build_agent(load_config()); print('OK')"
# If error: check imports with python3 -c "import core.symbolic; import ml.ml; print('OK')"
```

### Tests failing
```bash
python3 -m pytest tests/ -q
# Run specific test file:
python3 -m pytest tests/smoke_test.py -v
```

### Memory corruption
```bash
python3 -c "
from agent.bootstrap import load_config, build_agent
a = build_agent(load_config())
print(a.run('self check'))
"
```

---

## Extension Guide (Local-Only Rules)

Karma is designed to remain local. Any extension must comply:

1. **No remote AI inference** — no calls to OpenAI, Anthropic, etc.
2. **No external data transmission** beyond web search (DuckDuckGo/Brave)
3. **Local models only** — register via `config/model_registry.json` using Ollama or file-based GGUF

### Adding a Custom Tool

1. Create handler in `core/actions/my_handler.py` implementing `execute(agent, intent, **kwargs)`
2. Register in `agent/agent_loop.py` `_register_action_handlers()`
3. Add grammar pattern in `core/grammar.py`
4. Add symbolic rule in `core/symbolic.py`

### Adding a Custom Agent Role

1. Define role in `config/agent_roles.json`
2. Create agent class in `agents/my_agent.py` subclassing `BaseAgent`
3. Register in `core/agent_model_manager.py`
