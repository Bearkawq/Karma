# Local Rules - NEXUS

Project-specific operating boundaries for NEXUS.

## Rules

```yaml
rules:
  - id: "modular-agents"
    description: "Use modular agent architecture"
    applies_to: ["builder", "surgeon"]
    policy: |
      Keep agents modular with clear interfaces.
      Each agent should have single responsibility.

  - id: "memory-persistence"
    description: "Maintain memory persistence"
    applies_to: ["builder"]
    policy: |
      Use the memory module for all persistence.
      Don't use ad-hoc file storage.

  - id: "safe-deliberation"
    description: "Safe deliberation practices"
    applies_to: ["builder", "stabilizer"]
    policy: |
      Deliberation should be non-destructive.
      Keep historical states for recovery.
```

## Guidelines

- Follow the modular architecture in /core/
- Use memory/ for all persistent storage
- Test all agents individually before integration
- Document agent interfaces in /docs/