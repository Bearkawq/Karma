# Patterns

Reusable patterns discovered across projects.

## Categories

- **code/** - Code patterns (e.g., API handlers, data models)
- **workflows/** - Process patterns
- **solutions/** - Solutions to common problems

## Example

```yaml
pattern:
  name: "async-api-handler"
  description: "Standard async API endpoint pattern"
  applies_to: ["python", "fastapi"]
  template: |
    async def handle_{resource}(request: Request) -> Response:
        data = await request.json()
        result = await process(data)
        return json(result)
```