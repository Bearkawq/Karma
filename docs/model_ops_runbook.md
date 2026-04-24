# Model Operations Runbook

## Purpose

Operational notes for real model scan, registration, slot assignment, warm loading, installed model inventory, and fallback behavior.

## Real commands

Show model/operator doctor output:

python3 agent/agent_loop.py --doctor

Show readiness:

python3 agent/agent_loop.py --ready

Show installed and warm model status:

python3 agent/agent_loop.py --models

Assign planner role:

python3 agent/agent_loop.py --assign-role planner qwen3:4b

Assign navigator slot:

python3 agent/agent_loop.py --assign-slot navigator_slot granite3.3:2b

Bootstrap recommended model layout:

python3 agent/agent_loop.py --bootstrap-models

Run model loading tests:

python3 -m pytest tests/test_model_loading.py --tb=short -q

Run model operator tests:

python3 -m pytest tests/test_model_operator.py --tb=short -q

## Failure handling

- If Ollama is unavailable, Karma continues in deterministic fallback mode.
- If one configured model fails to load, other models should still initialize.
- Slot assignment must only occur for successfully loaded models.
- Unloaded or failed models must not appear in get_loaded_models().
- Warm loading failures should produce warnings, not crash the whole manager.
- Installed models can be present but not warm.

## Validation

python3 -m pytest tests/test_model_loading.py tests/test_model_operator.py --tb=short -q
