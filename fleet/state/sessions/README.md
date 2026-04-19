# Sessions State

Active agent sessions and their context.

## Track

- Session ID
- Agent role
- Project target
- Start time
- Current context

```yaml
sessions:
  session-123:
    agent: opencode
    role: builder
    project: nexus
    started: "2026-04-02T18:30:00Z"
    context_file: /nexus/.fleet/recent_context.md
```