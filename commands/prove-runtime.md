# Prove Runtime Behavior

You are proving runtime behavior of the Karma system.

## Workflow
1. Create a minimal test script to demonstrate the behavior
2. Run the script and capture raw output
3. Analyze the results
4. Summarize findings

## Output Requirements
- Show raw outputs (no filtering)
- Use unified diffs for any before/after comparisons
- Do not claim "fixed" without runtime validation
- Run `pytest -q` to verify
- Run `python3 tests/smoke_test.py` to verify

## Simulation Pattern
```
read code /tmp/sample.py
run /tmp/sample.py
debug /tmp/buggy.py
go on
summarize that
```

## Testing Approach
- Write isolated test cases in /tmp/
- Execute directly to see live behavior
- Compare expected vs actual outcomes
