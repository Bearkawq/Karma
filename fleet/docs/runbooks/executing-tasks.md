# Executing Tasks

## Flow

1. **Load project context**
   - Read `.fleet/project.yaml` for metadata
   - Read `.fleet/local_rules.md` for rules
   - Read `.fleet/task_board.md` for active tasks

2. **Select role**
   - Default from project.yaml or specify
   - Load role spec from `fleet/core/roles/`

3. **Execute task**
   - Use fleet core systems as needed
   - Apply project-specific rules
   - Update task board on completion

4. **Update context**
   - Write to `.fleet/recent_context.md`
   - Update `.fleet/task_board.md`
   - Log handoff if passing to another agent

## Example

```
fleet → nexus
role: builder
task: "add user profile"
```