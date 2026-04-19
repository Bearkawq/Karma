# NEXT ROLE
goose_planner

# OBJECTIVE
Test routing: assign 3 tasks to different workers

# FILES IN SCOPE
bridge/roles/

# INSTRUCTIONS
Assign each task to the correct worker based on routing policy:

1. Task: "Analyze the nexus architecture for coupling issues" → Assign to the reasoning specialist
2. Task: "Fix the bug in ui/web.py at line 45" → Assign to the implementation specialist  
3. Task: "Check disk usage and report storage status" → Assign to the system maintainer

For each, output a task assignment with: worker, task, expected output.

# SUCCESS CHECK
Each task assigned to the correct worker type

# IF BLOCKED
Report which assignment is unclear