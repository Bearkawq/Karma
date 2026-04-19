# Fix GoLearn

You are fixing issues in the GoLearn ML library integration.

## Workflow
1. Reproduce the issue with a minimal test case
2. Identify the root cause in the GoLearn code
3. Apply a surgical fix
4. Validate with runtime tests

## Output Requirements
- Show stop_reason if the fix cannot be completed
- Show artifact paths for any generated files
- Show live outputs from tests
- Run `pytest -q` after patching
- Run `python3 tests/smoke_test.py` after patching

## Common Patterns
- Check ml/golearn directory for integration code
- Look at core/ for base classes
- Verify with actual GoLearn binaries if needed
