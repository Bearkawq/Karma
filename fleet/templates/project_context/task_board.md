# Task Board

Active work queue and objectives for this project.

## Format

```yaml
active_tasks:
  - id: "task-001"
    title: "Implement user authentication"
    status: "in_progress"
    priority: "high"
    assignee: "builder"
    created: "2026-04-02T10:00:00Z"
    depends_on: []
    
  - id: "task-002"
    title: "Add API documentation"
    status: "pending"
    priority: "medium"
    assignee: ""
    created: "2026-04-02T11:00:00Z"
    depends_on: ["task-001"]

completed_today:
  - id: "task-000"
    title: "Set up project structure"
    completed: "2026-04-02T09:30:00Z"
    
backlog:
  - id: "task-010"
    title: "Add unit tests"
    priority: "low"
    
  - id: "task-011"
    title: "Performance optimization"
    priority: "low"
```

## Usage

Track all active work here. Update status as tasks progress.