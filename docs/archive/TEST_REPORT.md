# Karma — Test Report

This build was smoke-tested in an offline environment.

## Static checks
- `python -m py_compile` over all `.py` files: PASS

## Runtime smoke tests
Executed the agent loop with:
- `List all files`  -> FileTool list operation: PASS
- `Find files *.py` -> FileTool search operation: PASS
- `What can you do` -> capability listing: PASS

## Artifacts produced
- `data/agent_state.json` created/updated
- `data/episodic.jsonl` appended with reflection entries
- `data/logs/karma.log` written

