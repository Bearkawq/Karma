# Karma v3.8.0 — Local Autonomous Agent

Offline-first, self-contained agent with symbolic reasoning, lightweight ML, web research, persistent memory, distributed worker orchestration, and predictive cognition. No cloud APIs, no heavyweight ML frameworks. Core runtime is Python stdlib; optional UI/system features use Flask, Textual, and psutil.

## What It Does

- **Understands natural language** via 3-tier parsing (grammar → symbolic rules → ML classifier)
- **Learns from the web** via GoLearn (DuckDuckGo search → fetch → extract → remember)
- **Executes tools** (shell, file ops, code analysis, custom user-created tools)
- **Remembers everything** in persistent disk-based memory (facts, episodes, workflows, failures)
- **Self-tunes** scoring weights based on execution history
- **Self-checks** for broken tools, memory corruption, confidence collapse
- **Compresses knowledge** into concept crystals and deduplicates stale facts
- **Distributes work** across worker nodes (Dell, phone, Raspberry Pi)
- **Predicts outcomes** and triggers proactive reasoning on prediction failures

## Architecture

```
Karma/
├── agent/agent_loop.py      # 10-step agent cycle (observe → parse → plan → score → execute → reflect)
├── core/
│   ├── symbolic.py          # Rule-based intent parser + typo correction
│   ├── grammar.py           # Fast NL pattern matching
│   ├── planner.py           # HTN planner with capability map integration
│   ├── responder.py         # Conversation engine with evidence-first answering
│   ├── retrieval.py         # Retrieval bus — unified evidence across 6 memory strata
│   ├── capability_map.py    # Tool success/failure tracking + capability pressure furnace
│   ├── meta.py              # Meta observer — adjusts scoring weights every N cycles
│   ├── observer.py          # Background environment monitor (file changes, system stats)
│   ├── health.py            # Self-check + repair suggestions
│   ├── normalize.py         # Text normalization with learned language mappings
│   ├── events.py            # Event bus (JSONL append-only log)
│   ├── prediction_engine.py # Predictive cognition - triggers reasoning on prediction failures
│   ├── telemetry/           # System telemetry and metrics collection
│   ├── model_scanner.py      # Local model discovery
│   ├── slot_manager.py      # Model slot assignments
│   └── agent_model_manager.py # Agent/model orchestration
├── distributed/             # Distributed worker node system
│   ├── worker_registry.py   # Worker node discovery and tracking
│   ├── worker_client.py     # Worker communication client
│   ├── scheduler.py         # Role-based task scheduling
│   └── node_health.py       # Worker health monitoring
├── ml/ml.py                 # Naive Bayes + logistic regression (no sklearn/torch)
├── storage/memory.py        # Episodic + facts + tasks + compression
├── research/
│   ├── session.py           # GoLearn — autonomous web research sessions
│   ├── crawler.py           # DuckDuckGo search + page fetch
│   ├── brancher.py          # Subtopic exploration strategy
│   ├── index.py             # Knowledge extraction + fact persistence
│   └── timekeeper.py        # Wall-clock budget enforcement
├── tools/
│   ├── tool_interface.py    # Tool registry + execution
│   ├── tool_builder.py      # User-created tool management
│   ├── code_tool.py         # AST-aware code operations
│   └── self_upgrade.py      # Codebase self-analysis
├── ui/
│   ├── web.py               # Flask web dashboard (SSE, JSON API)
│   ├── cockpit.py           # Textual TUI dashboard
│   ├── templates/           # HTML
│   └── static/              # CSS + JS
├── config.json              # All configuration
└── karma                    # CLI launcher
```

## Key Systems

### Retrieval Bus (v3.1)
Unified evidence retrieval across 6 memory strata before every agent decision:
- **Lexicon** — language mappings and synonyms
- **World** — general facts
- **Procedure** — workflow cache (successful task sequences)
- **Failure** — failure fingerprints with lessons
- **Capability** — tool success rates and operational memory
- **Health** — past repairs and diagnostics

Evidence items carry `effect_hint` tags (`boost_action`, `block_action`, `answer_fact`, `suggest_repair`) that directly influence scoring, planning, and responses.

### Confidence Economy (v3)
Unified confidence signal propagates through parser → planner → execution → reflection. If confidence drops below threshold, the agent asks for clarification instead of guessing.

### GoLearn
Autonomous web research: give it a topic and time budget, it searches DuckDuckGo, fetches pages, extracts key points and code, saves facts to memory, and learns language mappings.

### Distributed Worker System (v3.8)
Role-based task scheduling across distributed worker nodes:
- **Dell (Primary)** — Executor, coder, navigator
- **Galaxy S25+ (Planner)** — Planner, summarizer, critic
- **Raspberry Pi (Utility)** — Retriever, embedder

Features include automatic fallback, health monitoring, and worker capability discovery.

### Prediction Engine (v3.8)
Proactive cognition layer that:
- Makes predictions about system behavior
- Compares predictions to observations
- Triggers reasoning when predictions fail (HIGH/CRITICAL severity)
- Tracks accuracy per domain (tool outcomes, agent state, user actions, system behavior, model responses, worker health)

### Capability Pressure Furnace
Detects repeated tasks and failure streaks. Proposes new tool creation when utility threshold is reached.

### Memory Compression
Periodic consolidation: deduplicates facts, clusters related entries into summaries, decays confidence on stale knowledge. Concept crystals compress topic knowledge into structured summaries.

### Meta Observation
Every N cycles, analyzes execution history and adjusts scoring weights (symbolic / ML / capability map) based on success rate trends.

## Usage

```bash
# CLI
python3 agent/agent_loop.py

# Web UI (Flask)
python3 ui/web.py
# → http://localhost:5000
# Access via local network IP on phone/DeX

# Commands
> list files
> golearn "python decorators" 5
> self check
> repair report
> crystallize "python"
> create tool "hello" bash "echo hello world"
> what do you know
```

## Requirements

- Python 3.10+
- Flask (web UI)
- Textual (cockpit TUI)
- psutil (system memory/cpu inspection)
- No cloud APIs, no heavyweight ML frameworks, no GPU required

## Design Principles

1. **Offline first** — runs without internet (except GoLearn)
2. **No frameworks** — ML from scratch, no sklearn/torch/transformers
3. **Disk-persistent** — all state survives restarts
4. **Self-improving** — learns from usage, compresses knowledge, tunes itself
5. **Transparent** — full decision trace logging, no black boxes
6. **Local-only** — no cloud inference, no hosted APIs, no API keys
7. **Karma as orchestrator** — agents and models are tools, not autonomous entities
