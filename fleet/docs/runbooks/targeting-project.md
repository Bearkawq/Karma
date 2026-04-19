# Targeting a Project

## Command Format

```
fleet → <project-name>
```

## Examples

- Target nexus: `fleet → nexus`
- Target nexus-c: `fleet → nexus-c`

## What Happens

1. Fleet resolves project path from name
2. Loads project metadata from `<project>/.fleet/project.yaml`
3. Applies local rules from `<project>/.fleet/local_rules.md`
4. Loads recent context from `<project>/.fleet/recent_context.md`

## Verification

Check project is recognized:
```bash
cat /home/mikoleye/karma/nexus/.fleet/project.yaml
```