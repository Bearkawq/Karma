# Troubleshooting

## Common Issues

### Project Not Found

**Symptom**: "Project not found: <name>"

**Solution**:
- Verify project exists in karma
- Check `.fleet/project.yaml` exists
- Ensure path is correct

### Context Load Failure

**Symptom**: "Failed to load project context"

**Solution**:
- Check `.fleet/` directory exists
- Verify all required files present:
  - project.yaml
  - local_rules.md
  - recent_context.md
  - task_board.md

### Role Not Found

**Symptom**: "Unknown role: <role>"

**Solution**:
- Check role is in `fleet/core/roles/`
- Verify role name spelled correctly

### Handoff Blocked

**Symptom**: "Cannot handoff, task incomplete"

**Solution**:
- Complete required work first
- Update task status to done
- Document completion in recent_context.md

## Getting Help

- Check fleet architecture: `fleet/docs/architecture/`
- Review runbooks: `fleet/docs/runbooks/`
- Check fleet memory for past issues: `fleet/memory/failures/`