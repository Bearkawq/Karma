# Fleet Control Deck

Terminal UI for the fleet multi-agent system.

## Quick Start

```bash
cd /home/mikoleye/karma/fleet
python3 control_deck.py
```

## Controls

| Key | Action |
|-----|--------|
| `t` | Select target project |
| `c` | Show project context |
| `tasks` / `k` | Show task board |
| `h` | Show pending handoffs |
| `w` | Show worker states |
| `r` | Refresh display |
| `q` | Quit |

## Design

- Dark matte terminal UI
- Copper/bronze accents (ANSI colors 172, 216, 130)
- Three-panel layout: workers | project | handoffs/warnings
- Reads directly from fleet and project .fleet/ files
- No external dependencies (Python stdlib + yaml)

## File Sources

- Fleet state: `/home/mikoleye/karma/fleet/state/`
- Project context: `/home/mikoleye/karma/<project>/.fleet/`
- Worker status: simulated (extend to read from state/workers/)