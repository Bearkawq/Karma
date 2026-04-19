# Starting Fleet

## Prerequisites

- Python 3.8+
- Access to karma directory
- OpenCode or similar agent tool

## Steps

1. **Verify fleet directory exists**
   ```bash
   ls -la /home/mikoleye/karma/fleet/
   ```

2. **Check fleet core is intact**
   ```bash
   ls /home/mikoleye/karma/fleet/core/
   ```

3. **Verify state directories exist**
   ```bash
   ls /home/mikoleye/karma/fleet/state/
   ```

4. **Ensure projects have .fleet/ directories**
   ```bash
   ls /home/mikoleye/karma/nexus/.fleet/
   ```

## Verification

Run diagnostics:
```python
from fleet.core.routing import verify_fleet
verify_fleet()
```