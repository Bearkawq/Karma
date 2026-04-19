# Handoff Index

Log of cross-agent handoffs for this project.

## Format

```yaml
handoffs:
  - id: "handoff-001"
    from_role: "builder"
    to_role: "checker"
    task: "implement-login"
    timestamp: "2026-04-02T17:00:00Z"
    summary: "Login feature implemented, needs review"
    context_files:
      - "models/user.py"
      - "handlers/auth.py"
    next_action: "Review code quality and test coverage"
    
  - id: "handoff-002"
    from_role: "checker"
    to_role: "builder"
    task: "fix-login-bug"
    timestamp: "2026-04-02T17:30:00Z"
    summary: "Found edge case in password validation"
    context_files:
      - "tests/test_auth.py:45"
    next_action: "Fix validation logic for empty passwords"
```

## Usage

Every time work transfers between agents, log it here. Provides trace of who did what.