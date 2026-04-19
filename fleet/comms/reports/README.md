# Reports

Structured report formats for various outputs.

## Report Types

- **status** - Current state reports
- **completion** - Task completion summaries
- **error** - Error reports with context
- **review** - Code review reports

## Usage

```python
from fleet.comms.reports import create_report

report = create_report(
    type="completion",
    task="implement-login",
    result="success",
    details={...}
)
```