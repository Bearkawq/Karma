# Local Rules - NEXUS-C

Project-specific operating boundaries for NEXUS-C.

## Rules

```yaml
rules:
  - id: "cli-first"
    description: "CLI-first design"
    applies_to: ["builder", "surgeon"]
    policy: |
      NEXUS-C is a CLI tool.
      Keep interface simple and terminal-focused.

  - id: "async-core"
    description: "Use async for I/O operations"
    applies_to: ["builder"]
    policy: |
      Use asyncio for all I/O-bound operations.
      Keep core synchronous for simplicity.

  - id: "cyberpunk-gui"
    description: "Maintain cyberpunk aesthetic"
    applies_to: ["builder", "designer"]
    policy: |
      GUI uses ANSI escape codes for terminal UI.
      Keep colors and styling consistent with cyberpunk theme.
```

## Guidelines

- Keep CLI simple and fast
- Use async for external API calls
- Maintain cyberpunk terminal aesthetic