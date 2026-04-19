# Routing - Request Routing

Routes incoming requests to appropriate handlers based on target, type, and content.

## Purpose

- Resolve project targets from identifiers
- Route requests to correct handlers
- Handle redirects and fallbacks

## Routing Logic

```python
def route(request):
    if request.target in PROJECTS:
        return load_project_context(request.target)
    elif request.target == "fleet":
        return load_fleet_system(request.system)
    else:
        return error("Unknown target")
```