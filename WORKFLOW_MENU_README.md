# STG Workflow Menu

## Overview
DeX-friendly terminal launcher for the STG Karma workflow.

## Files
- `~/workflow_menu.sh` - Main menu launcher
- `~/paste_command.sh` - Paste content into command.md

## Launch
```bash
# Via alias (after sourcing .bashrc)
wf

# Or directly
bash ~/workflow_menu.sh
```

## Aliases
- `wf` - Launch workflow menu
- `pc` - Paste command (write to command.md)

## Menu Options
1. STG Shell - Interactive SSH to STG
2. View Summary - Read summary.md
3. Edit Command - Edit command.md with nano
4. Quick View Both Files - Show summary + command
5. Watch Files - Live watch both files
6. Workflow Status - Process and file status
7. Start Goose Loop - Start dispatch loop
8. Start Bridge Watch - Start bridge watcher
9. Dispatch Once - Run dispatch one time
10. Tail Events - Watch events log
11. Exit

## Two-File Contract
| File | Access |
|------|--------|
| `summary.md` | READ ONLY (human copies from here) |
| `command.md` | WRITE ONLY (human pastes here) |

## command.md Structure
```markdown
# NEXT ROLE
scout

# OBJECTIVE
Identify failing tests

# FILES IN SCOPE
- tests/

# INSTRUCTIONS
1. Run tests
2. Map failures

# SUCCESS CHECK
All failures identified

# IF BLOCKED
Report blocker
```

## STG Config
Edit STG connection in each script:
- STG_HOST=192.168.68.59
- STG_USER=user
- STG_PORT=8022
