# Failures

Lessons learned from failed operations.

## Storage

```yaml
failures/
  2026-04/
    failed-deploy-nexus.yaml
    broken-tests-nexus-c.yaml
```

## Format

```yaml
failure:
  timestamp: "2026-04-02T18:30:00Z"
  project: nexus
  operation: "deploy"
  error: "Connection refused"
  lesson: "Check service is running before deploy"
  resolution: "Added health check to deploy script"
```