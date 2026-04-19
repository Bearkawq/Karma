# Karma Micro-Update Report v3.8.1
## Date: March 15, 2026

---

## Summary

Added final operator visibility pieces before large-scale testing.

**Status: COMPLETE**

---

## Changes Made

### 1. Active Runtime Endpoint
**File:** `ui/web.py`

Added `/api/active_runtime` endpoint returning:
- `is_active`: boolean (is something running)
- `current_role`: string (none if idle)
- `current_task`: string (what's running)
- `active_slot`: string (which slot)
- `active_model`: string (which model)
- `execution_mode`: string (local/remote)
- `fallback_used`: boolean
- `posture`: string (CALM/ACTIVE/etc)
- `latest_receipt`: object or null
- `latest_mutation`: object or null

### 2. Active Runtime Panel
**File:** `ui/templates/dashboard.html`

Added to System view showing:
- Status (ACTIVE/idle)
- Role
- Task
- Slot
- Model
- Execution mode
- Fallback indicator
- Posture

### 3. Worker Status Panel
**File:** `ui/templates/dashboard.html`

Added to System view showing:
- Registered workers (or "none registered")
- Worker status (online/offline)
- Worker capabilities
- Mode (local only if no workers)

### 4. Frontend Wiring
**File:** `ui/static/app.js`

Updated `refreshSystem()` to fetch:
- `/api/active_runtime`
- `/api/workers`

Displays data in respective panels.

---

## Endpoint Responses

### /api/active_runtime
```json
{
  "ok": true,
  "data": {
    "is_active": true,
    "current_role": "none",
    "current_task": "read_file",
    "active_slot": "none",
    "active_model": "none",
    "execution_mode": "local",
    "fallback_used": false,
    "posture": "CALM",
    "latest_receipt": null,
    "latest_mutation": null
  },
  "revision": 0,
  "ts": "2026-03-15T..."
}
```

### /api/workers
```json
{
  "ok": true,
  "data": [],
  "revision": 0,
  "ts": "2026-03-15T..."
}
```

---

## GUI Panels

### Active Runtime Panel (System View)
Located in System view, first card:
- Shows honest idle state when nothing active
- Shows role/slot/model when running
- Color-coded status (green when active)

### Worker Status Panel (System View)
Located in System view:
- Shows "none registered" when no workers
- Shows worker status with color coding
- Shows capabilities for each worker

---

## Verification

```
=== MICRO-UPDATE VERIFICATION ===
✓ Active Runtime: is_active=True, role=none
✓ Workers: 0 registered
=== VERIFICATION PASSED ===
```

Routes: 61 (was 60)

---

## Weak Points Remaining

1. **No workers registered** - Backend ready, needs real worker nodes
2. **Current role always "none"** - Agent doesn't track current_role in state file
3. **No remote execution tracking** - Execution mode always "local"

These are honest states - the panels show what the machine is actually doing.

---

## Files Changed

```
ui/web.py                   # +65 lines (active_runtime endpoint)
ui/templates/dashboard.html # +15 lines (2 new panels)
ui/static/app.js           # +60 lines (fetch and display)
```

---

*Generated: March 15, 2026*
*Version: 3.8.1*
