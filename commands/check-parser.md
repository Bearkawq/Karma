# Check Parser Behavior

You are checking parser behavior in the Karma system.

## Workflow
1. Identify the parser code (likely in core/ or agent/)
2. Create test inputs to probe parser behavior
3. Run parser on test inputs
4. Document the parsing results

## Output Requirements
- Show raw parser output
- Highlight any edge cases or failures
- Use unified diffs for comparisons
- Run `pytest -q` after any changes
- Run `python3 tests/smoke_test.py` after any changes

## Common Areas
- Check agent/ for parsing logic
- Look at core/ for base parser classes
- Review schemas/ for expected input formats
