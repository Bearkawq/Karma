# Copilot instructions for Karma repository

Purpose: quick, targeted guidance for Copilot sessions working in this repo.

Build / test / lint commands
- Run web UI: `./karma gui` or `python3 ui/web.py`
- Run CLI agent loop: `python3 agent/agent_loop.py` or use the factory: `python3 -c "from agent.bootstrap import load_config, build_agent; a = build_agent(load_config()); print(a.run('what can you do')); a.stop()"`
- Install deps: `pip install -r requirements.txt` (or install Flask/psutil/requests as needed)
- Full test suite: `python3 -m pytest tests/ -q`
- Single test file: `python3 -m pytest tests/smoke_test.py -q`
- Run a single test by node/name: `python3 -m pytest tests/test_file.py::TestClass::test_name -q` or use `-k "expr"` to select by keyword
- Linting: no dedicated linter configured in repo. Use `python -m pyflakes <file>` or `ruff` if added locally.

High-level architecture (short)
- agent/: agent lifecycle + bootstrap and the core event loop
- core/: symbolic parser, grammar, planner, responder, retrieval bus (6 memory strata), capability map, telemetry, model/slot managers
- storage/: memory stores (episodic, facts, tasks)
- research/: GoLearn autonomous web-research (DuckDuckGo crawler, extractors)
- tools/: tool registry and tool implementations (shell, file, system, research, code analysis)
- ui/: Flask web dashboard (http://localhost:5000) and TUI cockpit
- distributed/: worker node orchestration (role-based scheduling)
- data/: runtime files — logs, facts, episodic JSONL, traces

Key repo conventions (important and repo-specific)
- Local-only by design: no external AI inference; local models are registered in `config/model_registry.json` (Ollama or file-based models). Keep `system.offline` in `config.json` unless intentionally changed.
- Config-first behavior: `config.json` controls tools.enabled, memory file paths, confidence thresholds, web port, and allowed shell commands. Update `config.json` or `config/*` for role/model preferences.
- Retrieval bus & memory strata: retrieval pulls evidence from 6 strata (lexicon, world, procedure, failure, capability, health). Responses weigh evidence via `effect_hint` tags.
- Safety / modes: Chat (safe, no tool execution) vs Command (executes tools). Use `/api/chat` for safe conversation, `/api/command` for toolful commands.
- Ordinal selection UX: after a `list files` action, users can say "the first one", "the third one" to select items — useful for guiding Copilot to follow that interaction model when suggesting CLI sequences.
- Tool whitelist: `tools.shell.allowed_commands` in `config.json` limits shell operations; prefer using tool interfaces (tools/tool_interface.py) rather than invoking arbitrary shell commands.
- Adding extensions: follow documented steps — create handler under `core/actions`, register in agent_loop, add grammar/symbolic rules. See MANUAL.md and QUICKSTART.md for examples.
- Tests: tests live under `tests/` and expect many unit-level smoke checks (smoke_test example). Use pytest `-k` or explicit node paths to run single tests.

Other assistant-friendly notes
- Read these files first: README.md, QUICKSTART.md, MANUAL.md, AGENTS.md (multi-agent rules). AGENTS.md contains the repo's multi-agent roles and phase rules used by planners.
- Data and runtime paths: `data/episodic.jsonl`, `data/facts.json`, `data/agent_state.json`, and `data/logs/karma.log` — avoid committing runtime files.
- Model registration: register Ollama or GGUF models in `config/model_registry.json` and map roles in `config/model_preferences.json`.

If this file already exists, prefer merging these bullets into the existing content rather than replacing wholesale.

CI / MCP servers
- A ready GitHub Actions workflow for running Playwright UI tests has been added at `.github/workflows/playwright.yml`. It starts the Flask UI, installs Playwright and runs tests in `tests/playwright` (adjust paths as needed).
