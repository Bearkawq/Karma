# Local Project Rules

Project-specific operating boundaries and rules that add to (not override) fleet policies.

## Rule Format

```yaml
rules:
  - id: "rule-name"
    description: "What this rule enforces"
    applies_to: ["builder", "checker"]
    policy: |
      Rule description here.
```

## Example Rules

```yaml
rules:
  - id: "test-first"
    description: "Write tests before implementation"
    applies_to: ["builder"]
    policy: |
      Always write failing test first, then implement to pass it.

  - id: "no-breaking-changes"
    description: "Maintain backward compatibility"
    applies_to: ["builder", "surgeon"]
    policy: |
      Don't remove or change existing APIs without deprecation cycle.
```

## Guidelines

- Rules should be specific to this project
- Can add restrictions but not override fleet policies
- Keep rules concise and actionable