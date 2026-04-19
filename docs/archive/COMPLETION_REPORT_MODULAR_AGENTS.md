# Karma Modular Agents & Models Architecture Upgrade Report

**Date:** March 15, 2026  
**Status:** Completed Successfully

---

## Executive Summary

This upgrade implements a modular agent and language model framework that allows Karma to use specialized workers and swappable language engines while maintaining Karma's fixed identity. All components run locally with no external dependencies.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        KARMA CORE                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │   Identity  │  │    Role    │  │  Response           │   │
│  │   Guard     │◄─┤   Router   │◄─┤  Normalizer         │   │
│  └─────────────┘  └─────────────┘  └─────────────────────┘   │
│         ▲                ▲                                    │
│         │                │                                    │
│  ┌──────┴────────────────┴─────────────────────────────────┐  │
│  │              Agent Model Manager                         │  │
│  │  • Registers agents & models                             │  │
│  │  • Routes tasks to appropriate workers                  │  │
│  │  • Applies identity guard to all outputs                │  │
│  │  • Falls back to deterministic mode when needed         │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                                           │
         ▼                                           ▼
┌─────────────────────┐                 ┌─────────────────────┐
│   AGENTS            │                 │   MODELS             │
│   (Workers)         │                 │   (Engines)         │
├─────────────────────┤                 ├─────────────────────┤
│ • planner           │                 │ • local_llm         │
│ • executor          │                 │ • local_embedding   │
│ • retriever        │                 │ • (swappable)       │
│ • summarizer       │                 │                     │
│ • critic           │                 │                     │
│ • navigator        │                 │                     │
└─────────────────────┘                 └─────────────────────┘
```

---

## Non-Negotiables Implemented

1. **Karma stays Karma** - Identity guard prevents personality bleeding
2. **No hosted AI** - All local, no API keys, no cloud
3. **No hard dependency** - Works without models in deterministic mode
4. **Optional integration** - Models can be added/removed cleanly
5. **Karma as conductor** - Agents/models are instruments, Karma is the boss

---

## Component Details

### 1. AGENTS PACKAGE (`agents/`)

**Purpose:** Specialized workers for task roles. NOT personalities.

#### Base Agent (`base_agent.py`)
- Abstract interface all agents implement
- Properties: `agent_id`, `role_name`, `status`
- Methods: `run()`, `warmup()`, `shutdown()`, `enable()`, `disable()`
- Capabilities: What each agent can do

#### Role Agents

| Agent | Role | Description | Model Required |
|-------|------|-------------|----------------|
| Planner | `planner` | Decomposes goals into steps | No (deterministic) |
| Executor | `executor` | Performs structured actions | No |
| Retriever | `retriever` | Searches local knowledge | No |
| Summarizer | `summarizer` | Condenses logs/plans | Optional |
| Critic | `critic` | Reviews plans/results | No |
| Navigator | `navigator` | Navigates resources/views | No |

Each agent exposes:
- `agent_id` - Unique identifier
- `role_name` - Functional role
- `capabilities` - What it can do
- `run(context)` - Execute task
- `status` - Operational state

---

### 2. MODELS PACKAGE (`models/`)

**Purpose:** Swappable local language model backends.

#### Base Model Adapter (`base_model_adapter.py`)
- Abstract interface for all model adapters
- Metadata: model_id, type, path, quantization, memory footprint
- Capabilities: supports_generate, supports_embed, supports_classify, supports_rerank

#### Model Types

| Adapter | Type | Purpose |
|---------|------|---------|
| LocalLLMAdapter | LLM | Text generation |
| LocalEmbeddingAdapter | Embedding | Vector embeddings |

#### Model Registry (`registry.py`)
- Register/unregister models
- Find by capability
- Find by role
- Save/load registry

**Karma doesn't care about model family** - only capabilities.

---

### 3. IDENTITY GUARD (`core/identity_guard.py`)

**Critical component** that ensures Karma's identity remains stable.

#### Responsibilities:
- Prevent agents/models from changing Karma's tone
- Enforce Karma formatting conventions
- Ensure all output is mediated by Karma core
- Strip personality markers

#### Features:
```python
# All outputs pass through guard
guard.guard(raw_output, context)
# Returns: GuardResult with normalized output
```

#### Detection:
- Tone detection (neutral, enthusiastic, uncertain, error)
- Personality marker stripping
- Prohibited content blocking

---

### 4. ROLE ROUTER (`core/role_router.py`)

Determines which agent and/or model to use for a task.

#### Routing Logic:
1. **Explicit mode**: Force specific role
2. **Auto mode**: Match task to role by pattern
3. **Fallback**: Use default when no match

#### Default Mappings:
```
plan        → planner (fallback: executor)
search/find → retriever
summarize   → summarizer (model preferred)
review/critique → critic
navigate   → navigator
execute/run → executor
```

#### Decision Output:
```python
RouteDecision(
    role="planner",
    mode=InvocationMode.AUTO,
    model_used=False,
    fallback_used=False,
    confidence=0.9
)
```

---

### 5. RESPONSE NORMALIZER (`core/response_normalizer.py`)

Formats all responses in Karma's voice.

#### Features:
- Whitespace normalization
- Length limits
- Error/success/info formatting
- List formatting

---

### 6. AGENT MODEL MANAGER (`core/agent_model_manager.py`)

Main orchestration layer tying everything together.

#### Capabilities:
- Register agents and models
- Route tasks to appropriate workers
- Apply identity guard
- Handle fallbacks
- Track pipeline type

#### Pipeline Types:
- `karma_only` - Direct Karma handling
- `agent_only` - Agent processed
- `model_assisted` - Agent + model
- `mixed` - Multiple sources

---

## Configuration Files

### `config/agent_roles.json`
```json
{
  "roles": {
    "planner": { "enabled": true, "requires_model": false },
    "summarizer": { "enabled": true, "requires_model": true }
  }
}
```

### `config/model_registry.json`
```json
{
  "models": [
    {
      "model_id": "llama3",
      "type": "llm",
      "path": "/models/llama3.bin",
      "capabilities": { "supports_generate": true }
    }
  ]
}
```

### `config/model_preferences.json`
```json
{
  "role_preferences": {
    "summarizer": { "preferred_model": "llama3" }
  }
}
```

---

## Fallback Behavior

### No Model Mode
When no models are available:
- Agents work in deterministic mode
- Summarizer uses deterministic extraction
- System remains fully functional

### Missing Agent
- Falls back to `executor` role
- Returns error if no fallback available

### Model Load Failure
- Continues with deterministic agent
- Logs failure for diagnostics

---

## Telemetry Integration

Events tracked:
- `agent_selected` - Which agent was chosen
- `model_selected` - Which model was selected
- `model_loaded` / `model_unloaded` - Load state
- `role_fallback` - When fallback was used
- `identity_guard_applied` - Output normalization

Exposed via existing telemetry system.

---

## UI Integration

Endpoints exposed:
- `/api/agents` - Available agents with status
- `/api/models` - Registered models
- `/api/pipeline` - Pipeline execution info
- Debug panels show role/model selection

---

## Tests

| Test | Status |
|------|--------|
| All imports | SUCCESS |
| Identity guard | PASSED |
| Role router | PASSED |
| Agent manager | PASSED |
| Pipeline execution | PASSED |
| Smoke test | 12/12 PASSED |

---

## File Structure

```
core/
├── agent_model_manager.py    # Main orchestration
├── identity_guard.py        # Identity protection
├── role_router.py          # Task routing
└── response_normalizer.py  # Output formatting

agents/
├── __init__.py
├── base_agent.py            # Abstract interface
├── planner_agent.py        # Task decomposition
├── executor_agent.py       # Action execution
├── retriever_agent.py      # Knowledge search
├── summarizer_agent.py     # Content condensing
├── critic_agent.py         # Review/analysis
└── navigator_agent.py      # Resource navigation

models/
├── __init__.py
├── base_model_adapter.py   # Abstract interface
├── local_llm_adapter.py   # LLM backend
├── local_embedding_adapter.py
└── registry.py           # Model registry

config/
├── agent_roles.json       # Role definitions
├── model_registry.json    # Model metadata
└── model_preferences.json # Role preferences
```

---

## Usage Examples

```python
# Get agent model manager
from core.agent_model_manager import get_agent_model_manager

manager = get_agent_model_manager()
manager.initialize()

# Execute task (deterministic mode)
result = manager.execute(
    task="list files in /tmp",
    force_no_model=True
)
# result.pipeline_type == "agent_only"
# result.role_used == "executor"

# Execute with model assistance
result = manager.execute(
    task="summarize the research",
    force_no_model=False
)
# result.pipeline_type == "model_assisted"
# result.model_used == "mock_llm"

# Identity guard applied automatically
# result.identity_guard_applied == True
```

---

## Design Principles Maintained

1. **No personality handoff** - Identity guard ensures Karma stays Karma
2. **Local-only** - No external APIs, no cloud inference
3. **Deterministic fallback** - Works without models
4. **Swappable models** - Add/remove without code changes
5. **Clear separation** - Agents are workers, not personalities

---

## Conclusion

Karma now has a modular execution framework where:
- Agents are specialized functional roles
- Models are swappable language engines
- Identity remains fixed and protected
- Everything runs locally
- System degrades gracefully when components unavailable

Karma remains the conductor, not the violin.
