# STG Control Loop - Documentation

## Overview
One-tap workflow: Phone/DeX → Termux Widget → SSH → STG → Karma Bridge → Goose

## Files

### Canonical Two-File Contract
| File | Human Access | Goose Access |
|------|-------------|--------------|
| `bridge/planner/summary.md` | READ ONLY | WRITE |
| `bridge/planner/command.md` | WRITE ONLY | READ |

### Scripts
- `scripts/goose_dispatch.sh` - Read command.md, execute role, render summary
- `scripts/goose_loop.sh` - Continuous loop running dispatch
- `scripts/bridge_watch.sh` - Watch for changes, maintain heartbeat

### Roles
- `bridge/roles/scout.md` - Map files, read-only
- `bridge/roles/builder.md` - Implement fixes, minimal diff
- `bridge/roles/checker.md` - Diagnose and verify
- `bridge/roles/helper.md` - Unstick stalled work

## Widgets (on phone Termux)

| Widget | Action |
|--------|--------|
| STG Shell | Interactive SSH to STG |
| Summary | View summary.md |
| Command Edit | Edit command.md with nano |
| Watch | Live watch summary + command |
| Status | Process status, file times, events |
| View | Both summary + command |
| Goose Loop | Start/check goose loop |
| Bridge Watch | Start/check bridge watcher |
| Goose Dispatch Once | Run dispatch once |
| Events | Tail events log |
| STG tmux | Attach to tmux |

## Commands

### Run Dispatch Manually
```bash
cd /home/mikoleye/karma
bash scripts/goose_dispatch.sh
```

### Start Goose Loop
```bash
cd /home/mikoleye/karma
nohup scripts/goose_loop.sh > /tmp/goose_loop.log 2>&1 &
echo $!
```

### Start Bridge Watch
```bash
cd /home/mikoleye/karma
nohup scripts/bridge_watch.sh > /tmp/bridge_watch.log 2>&1 &
echo $!
```

### Quick View Summary
```bash
cat /home/mikoleye/karma/bridge/planner/summary.md
```

### Widget Repair (on phone)
```bash
bash /sdcard/Download/widgets/fix_termux_widgets.sh
```

### Widget Refresh (on phone)
```bash
am broadcast -a com.termux.widget.refresh
```

## command.md Structure
```markdown
# NEXT ROLE
<scout|builder|checker|helper>

# OBJECTIVE
...

# FILES IN SCOPE
- path/to/file

# INSTRUCTIONS
...

# SUCCESS CHECK
...

# IF BLOCKED
...
```

## Summary Structure
```markdown
# Planner Summary

Generated: <timestamp>

## ACTIVE ROLE
<role>

## STATUS
<complete|blocked|error>

## SUMMARY
...

## FILES READ
- path

## FILES CHANGED
- path

## BLOCKERS
...

## RECOMMENDED NEXT ROLE
...

## RECOMMENDED NEXT STEP
...

## LAST UPDATED
<timestamp>
```

## Config
Edit once: `~/.shortcuts/tasks/.stg_env`
- STG_HOST
- STG_USER  
- STG_PORT
- STG_REPO=/home/mikoleye/karma
