# HANDOFF.md — Append-Only Handoff Log

*Add entries for every agent-to-agent handoff. Include confidence, knowns, unknowns, recommended next role.*

---

## Handoff Template
```
## [YYYY-MM-DD] [from_agent] -> [to_agent]

**Task**: [brief]
**Phase**: [phase]
**Confidence**: 0.X

**Known**:
- [what is confirmed]

**Unknown**:
- [what is uncertain]

**Recommended Next Role**: [role]
**Notes**: [optional]
```

---

## Example Entry

## 2026-03-31 Builder -> Faultfinder

**Task**: Debug test failures in test_update_3_5_3.py
**Phase**: patch
**Confidence**: 0.7

**Known**:
- Tests fail at line 298: RATE_LIMIT_REQUESTS assertion
- Expected 10, actual value is 20

**Unknown**:
- Whether this is test bug or intentional change

**Recommended Next Role**: Faultfinder
**Notes**: Check research/providers.py for actual constant value

---

## Example Future-Phase Packet

## 2026-03-31 Forecaster Packet (Goose/Qwen)

**Phase Prediction**: upgrade
**Likely Files**: config.json, agent/agent_loop.py, ui/web.py
**Likely Blocker**: Version compatibility, Flask route changes
**Suggested First Check**: Compare config.json version with karma_version.py
**Recommended Role**: Builder with Validator support

---

## Handovers Log

*Append new handoffs below this line*

---
*Never delete history. Keep append-only.*

## 2026-04-16 Claude -> next

**Task**: Wire Ollama backend end-to-end
**Phase**: Integration complete
**Confidence**: 0.97

**Known**:
- Ollama running at localhost:11434
- qwen3:4b → planner/executor/critic (confirmed generates)
- granite3.3:2b → summarizer/navigator
- nomic-embed-text → retriever (768-dim, cosine sim 0.97)
- AgentModelManager.initialize() probes Ollama on startup, falls back to mock
- Slot assignments persisted to data/slot_assignments.json
- /api/models returns real models when Ollama is up
- 330 tests pass

**Unknown**:
- qwen3:4b generates verbose thinking-style text inline even with think:false — acceptable for current use
- granite3.3:2b not yet load-tested under inference load

**Recommended Next Role**: executor (wire generate() calls into planner/critic agents)
**Notes**: scripts/ensure_ollama.sh starts Ollama if not running. No NetSentinel changes made (watchdog-only as requested).

## 2026-04-16 Claude -> next (seat execution wiring)

**Task**: Wire real seat execution — agents call assigned Ollama models
**Phase**: Seat wiring complete
**Confidence**: 0.95

**Known**:
- All 6 agents now call real local models via `_try_model()` / `_get_embed_adapter()`
- planner/executor/critic: qwen3:4b via /api/generate
- summarizer/navigator: granite3.3:2b via /api/generate
- retriever: nomic-embed-text via /api/embed (cosine similarity, >0.4 threshold)
- Extractors clean model output: `_extract_numbered_lines`, `_extract_bullet_issues`
- Deterministic fallback preserved in every agent
- 330 tests pass

**Model outputs verified**:
- Planner: 4-step real diagnosis plan, no duplicates
- Executor: numbered concrete steps
- Critic: caught SQL injection, missing validation; "OK" when tradeoffs are legitimate
- Summarizer: accurate 3-sentence code summary
- Navigator: 3 grounded hardware invention directions (specific, not fluff)
- Retriever: cosine sim 0.648 LiPo > 0.547 Pi for "battery safety and electronics power"

**Remaining limits**:
- qwen3:4b ignores "no explanation" instructions; extractors compensate but can't always get clean output
- Navigator uses model imagination for file paths (may hallucinate paths that don't exist)
- Retriever embeds up to 200 facts per query — larger memory stores need indexed approach
- granite3.3:2b sometimes truncates output mid-sentence

**Recommended Next Role**: executor — index memory facts at startup, add vector store for O(1) retrieval

## 2026-04-16 Claude -> next (hardening pass)

**Task**: Harden 6-seat real-model setup
**Confidence**: 0.97

**Patches**:
- navigator: only uses model when real `available` context provided; `_scan_real_paths` extracts real dirs from task; deterministic fallback when no context
- `_clean_model_output`: fixed DOTALL over-consumption (changed `.*?` to `[^\n]*`)
- retriever: embedding cache (MD5-keyed process-lifetime dict); 5.2s → 0.01s on repeated queries; expanded to 500 facts
- summarizer: max_tokens 200→400, input window 2000→3000 chars

**Proof**: 330 tests pass, cache speedup verified, navigator no longer invents paths

## 2026-04-16 Claude -> next (grounding/persistence pass)

**Task**: Persistent index, default navigator grounding, validation layer
**Confidence**: 0.97

**Patches**:
- `agents/retriever_agent.py`: SQLite persistent index (`data/embed_index.db`); packed float32 blobs; `_load_persistent_cache()` on first use, `_persist_vector()` write-through; 1.4s cold → 0.00s after restart
- `agents/navigator_agent.py`: `_scan_real_paths` → `_scan_project_files()` for code-keyword tasks (auto-inventory of real .py/.json files, depth ≤2, skip data/docs/cache); `_validate_options()` strips lines whose item token doesn't appear in available list
- `agents/summarizer_agent.py`: system prompt tightened to "only information explicitly present in the input"

**Proof**: 330 tests pass; DB exists at data/embed_index.db; 4 vectors loaded from DB on restart; validation stripped 2/3 invented paths; code-task navigator auto-grounded to real project files

**Remaining limits**:
- qwen3:4b reasoning leakage still present; extractor-only mitigation
- `_validate_options` uses substring match; aliased/abbreviated paths may slip through
- No summarizer sentence-level hallucination detection (lightweight approach only: system prompt)
- embed_index.db grows unbounded; no eviction/TTL yet
