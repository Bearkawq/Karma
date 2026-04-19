# Fleet Architecture

## Overview

Fleet is the shared multi-agent coordination system. It provides reusable infrastructure that any project can use.

## Operating Model

```
fleet → project target → project-local context → execute
```

1. **fleet** receives a target (project identifier)
2. **project target** is resolved to a project directory
3. **project-local context** is loaded from `<project>/.fleet/`
4. **execute** - agents work using fleet systems + project context

## Core Components

### core/
Reusable orchestration logic - project-agnostic.
- `bridge/` - Inter-process communication
- `roles/` - Agent role definitions
- `dispatcher/` - Task distribution
- `routing/` - Request routing
- `prompts/` - Prompt templates
- `playbooks/` - Reusable workflows
- `policies/` - Global policies
- `shared_tools/` - Common tools
- `shared_config/` - Shared configuration

### state/
Live operational state - ephemeral.
- `planner/` - Planner's current plans
- `workers/` - Worker status
- `sessions/` - Active sessions
- `events/` - Event log
- `inbox/` - Incoming tasks
- `outbox/` - Outgoing messages
- `locks/` - Distributed locks
- `summaries/` - State summaries

### memory/
Fleet-wide reusable memory - project-agnostic.
- `shared/` - General knowledge
- `episodic/` - Past events
- `failures/` - Lessons from failures
- `patterns/` - Reusable patterns

### comms/
Structured communication patterns.
- `handoffs/` - Agent handoff protocols
- `signals/` - Lightweight signals
- `reports/` - Report formats

## Project Context

Each project has its own `.fleet/` directory:

```
project/
  .fleet/
    project.yaml       - Project metadata
    local_rules.md     - Project-specific rules
    recent_context.md  - Current state
    task_board.md      - Active tasks
    handoff_index.md   - Handoff log
    notes.md           - Project notes
```

## Execution Flow

1. Agent receives task with project target
2. Fleet resolves project path from target
3. Loads project context from `.fleet/project.yaml`
4. Applies project rules from `.fleet/local_rules.md`
5. Checks current state from `.fleet/recent_context.md`
6. Executes task using fleet core systems
7. Updates project context on completion

## Key Principles

- Fleet is shared and project-agnostic
- Project context is local to each project
- No project-specific logic in fleet (unless truly generic)
- Agents always load project context before executing