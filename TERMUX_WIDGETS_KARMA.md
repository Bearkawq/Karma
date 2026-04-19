# Termux Widgets - STG Control Loop

## Overview
Set of one-tap widgets for managing the STG bridge system from Termux.

## Configuration
Edit once in: `~/.shortcuts/tasks/.stg_env`
```bash
STG_HOST="192.168.68.59"
STG_USER="user"
STG_PORT="8022"
STG_REPO="/home/mikoleye/karma"
```

## Widgets

| Widget | Action |
|--------|--------|
| STG Shell | Open interactive SSH session |
| Summary | View `summary.md` |
| Command Edit | Edit `command.md` with nano |
| Watch | Live watch summary + command |
| Goose Loop | Start/check goose_loop.sh |
| Bridge Watch | Start/check bridge_watch.sh |
| Status | Show process status, file times, events |
| View | Show both summary.md + command.md |
| STG tmux | Attach to tmux session |
| Events | Tail events log live |
| Goose Dispatch Once | Run dispatch script once |

## Refresh Termux:Widget
After copying to Termux device:
1. Long-press home screen
2. Add Widget → Termux:Widget
3. Select widgets to add

Or run: `termux-widget` to refresh.
