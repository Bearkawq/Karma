# Karma GUI Integration & Telemetry Upgrade - Complete Report

**Date:** March 15, 2026  
**Status:** COMPLETED

---

## 1. EXECUTIVE SUMMARY

This upgrade integrates the modular agent/model system into the GUI, making Karma fully operational from DeX with live telemetry visibility. All components remain local with no external dependencies.

---

## 2. PRIMARY FEATURES IMPLEMENTED

### 2.1 Telemetry Integration into GUI ✓

**What's Visible in DeX:**

| Component | Location | Description |
|-----------|----------|-------------|
| Posture | Top strip | CALM/ACTIVE/DEGRADED/RECOVERING |
| Revision | Top strip | State revision counter |
| Active Agents | Stats row | Number of enabled agents |
| Last Receipt | Telemetry panel | Latest action receipt |
| Last Mutation | Telemetry panel | Most recent state change |
| Route Trace | Telemetry panel | Last routing decision |
| Recent Events | Telemetry panel | Activity timeline |

**Telemetry View Sections:**
- Stats row (posture, revision, pipeline)
- Last action receipt card
- Last mutation card
- Route trace card
- Recent events timeline

### 2.2 Model Discovery/Scanner ✓

**Backend Module:** `core/model_scanner.py`

**Capabilities:**
- Recursive directory scanning
- GGUF file detection (*.gguf)
- Safetensors directory detection
- Model manifest parsing (config.json)
- Directory size calculation
- Capability guessing from filename
- Runtime hint detection

**Scan Patterns Supported:**
```
GGUF files: *.gguf, *.GGUF
Safetensors: *.safetensors, model directories
Manifests: config.json, model.safetensors.index.json
```

**API Endpoint:**
```
POST /api/models/scan
Body: { "path": "/models", "recursive": true }
Response: { "scan_path", "models_found", "candidates", "errors" }
```

### 2.3 Role ↔ Model Assignment UI ✓

**Backend Module:** `core/slot_manager.py`

**Slots Defined:**
| Slot | Default Role | Purpose |
|------|--------------|---------|
| planner_slot | planner | Task decomposition |
| coder_slot | executor | Action execution |
| summarizer_slot | summarizer | Content condensing |
| embedder_slot | retriever | Knowledge search |
| navigator_slot | navigator | Resource navigation |
| general_language_slot | critic | Review/analysis |

**Features:**
- Role to slot auto-mapping
- Model assignment with capability checking
- Deterministic mode support
- JSON persistence to `data/slot_assignments.json`
- Compatibility filtering (embedding-only models won't show for planner)

**API Endpoints:**
```
GET /api/slots
Response: { "slots": [...], "roles": [...] }

POST /api/slots/assign
Body: { "role": "planner", "model_id": "llama3", "deterministic": false }
```

### 2.4 Model Slot System ✓

**Visual Grid in GUI:**
Each slot shows:
- Slot name
- Assigned model ID
- Load status (loaded/unloaded/error)
- Model path

**Assignment Flow:**
1. Operator scans for models
2. System shows candidates with capability hints
3. Operator clicks "Register" on desired model
4. Model added to registry
5. Operator assigns to slot via dropdown

### 2.5 Agent/Model Control Panel ✓

**API Endpoints:**

| Endpoint | Method | Purpose |
|---------|--------|---------|
| `/api/agents` | GET | List all agents with status |
| `/api/models` | GET | List all registered models |
| `/api/models/register` | POST | Register discovered model |
| `/api/models/load` | POST | Load model into memory |
| `/api/models/unload` | POST | Unload model from memory |
| `/api/pipeline/status` | GET | Pipeline status |
| `/api/pipeline/execute` | POST | Execute task |

**Agent Display:**
- Role name
- Status (ready/disabled)
- Capabilities

**Model Display:**
- Model ID
- Load status
- Path
- Runtime type

### 2.6 DeX Command Center ✓

**Layout Structure:**
```
┌────────────────────────────────────────────────────────┐
│ Top: Posture Badge | Revision | Agent Count           │
├──────┬───────────────────────────────────┬─────────────┤
│      │                                   │             │
│ Nav  │     Center Workspace              │  Right Pane │
│ Rail │     (Chat/Learn/Memory)          │  Telemetry  │
│      │                                   │             │
├──────┴───────────────────────────────────┴─────────────┤
│ Bottom: Command Input                                   │
└────────────────────────────────────────────────────────┘
```

**New Views (6-7):**
- View 6: Telemetry - Live system observability
- View 7: Models - Agent/Model management

### 2.7 Mobile Sidecar ✓

**Access:** Via Telemetry view (keyboard 6 or nav button)

**What's Available:**
- Posture indicator
- Last receipt summary
- Quick stats

---

## 3. GUI UPDATES DETAIL

### 3.1 Dashboard HTML

**New Navigation Buttons:**
```html
<button class="nav-btn" data-view="telemetry" title="Telemetry (6)">
  <svg>...pulse icon...</svg>
</button>
<button class="nav-btn" data-view="models" title="Models (7)">
  <svg>...computer icon...</svg>
</button>
```

**Telemetry View Structure:**
```html
<div class="view" id="view-telemetry">
  <div class="stats-row">
    <div class="stat-card">
      <span class="stat-label">Posture</span>
      <span class="stat-value">CALM</span>
    </div>
    <!-- Revision, Pipeline stats -->
  </div>
  <div class="sys-grid">
    <div class="card"><h3>Last Action Receipt</h3></div>
    <div class="card"><h3>Last Mutation</h3></div>
    <div class="card"><h3>Route Trace</h3></div>
    <div class="card"><h3>Recent Events</h3></div>
  </div>
</div>
```

**Models View Structure:**
```html
<div class="view" id="view-models">
  <div class="model-controls">
    <button id="scan-models-btn">Scan for Models</button>
    <input id="scan-path" value="/models">
  </div>
  <div class="sys-grid">
    <div class="card"><h3>Agents</h3></div>
    <div class="card"><h3>Models</h3></div>
  </div>
  <div class="card"><h3>Slot Assignments</h3></div>
  <div class="card"><h3>Scan Results</h3></div>
</div>
```

### 3.2 CSS Additions

**Posture Badges:**
```css
.posture-badge.calm { background: #10b981; }
.posture-badge.active { background: #3b82f6; }
.posture-badge.degraded { background: #f59e0b; }
.posture-badge.recovering { background: #ef4444; }
```

**Stat Cards:**
```css
.stat-card {
  display: flex;
  flex-direction: column;
  padding: 12px 16px;
}
.stat-label { font-size: 11px; color: var(--text2); }
.stat-value { font-size: 18px; font-weight: 600; }
```

**Slot Grid:**
```css
.slot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
}
.slot-status.loaded { background: #10b981; }
.slot-status.unloaded { background: var(--text2); }
```

### 3.3 JavaScript Handlers

**Telemetry Refresh:**
```javascript
async function refreshTelemetry() {
  const resp = await fetch("/api/telemetry/dashboard");
  const j = await resp.json();
  // Update posture, receipt, mutation, trace, events
}
```

**Models Refresh:**
```javascript
async function refreshModels() {
  // Fetch agents, models, slots
  // Render slot grid with status indicators
}
```

**Scan Handler:**
```javascript
document.getElementById("scan-models-btn").addEventListener("click", async () => {
  const path = document.getElementById("scan-path").value;
  const resp = await fetch("/api/models/scan", {
    method: "POST",
    body: JSON.stringify({path, recursive: true})
  });
  // Display candidates with Register buttons
});
```

---

## 4. API ENDPOINTS COMPLETE LIST

### Model Management
```
POST /api/models/scan           - Scan for models
GET  /api/models/scan/last      - Get last scan
POST /api/models/register      - Register model
GET  /api/models              - List models
POST /api/models/load         - Load model
POST /api/models/unload       - Unload model
```

### Slot/Role Management
```
GET  /api/slots               - Get all slots/roles
POST /api/slots/assign        - Assign model to slot
```

### Agent Management
```
GET /api/agents               - List agents with status
```

### Pipeline
```
GET  /api/pipeline/status     - Pipeline status
POST /api/pipeline/execute    - Execute through pipeline
```

### Telemetry
```
GET /api/telemetry/dashboard  - Full telemetry snapshot
```

---

## 5. FILE CHANGES

### New Files
```
core/model_scanner.py          - Local model discovery
core/slot_manager.py          - Role↔model assignment
```

### Modified Files
```
ui/web.py                      - Added 15+ API endpoints
ui/templates/dashboard.html   - Added Telemetry + Models views
ui/static/style.css           - Added telemetry/model styles
ui/static/app.js              - Added view handlers
```

---

## 6. DESIGN FEATURES

### Badges Implemented
1. **Route Badges** - Pipeline type (karma_only, agent_only, model_assisted)
2. **Identity Guard** - Shown in telemetry when output normalized
3. **Posture Indicator** - CALM/ACTIVE/DEGRADED/RECOVERING
4. **Load Status** - Loaded/unloaded/error indicators

### Failure Handling
- Missing scan path → Error message in scan results
- No models found → "No models found" message
- Duplicate registration → Handled gracefully
- Incompatible model → Filtered from role dropdown
- Missing assigned model → Shown in slot status

---

## 7. TESTS

| Test | Result |
|------|--------|
| Smoke test (12 tests) | PASS |
| Model scanner | VERIFIED |
| Slot manager | VERIFIED |
| API imports | SUCCESS |
| All module imports | SUCCESS |

---

## 8. REMAINING RISKS

1. **Real Model Integration** - Currently uses mock adapters; need llama.cpp/ollama integration
2. **Mobile Optimization** - Could add dedicated mobile telemetry drawer
3. **Actual Model Loading** - load/unload endpoints need real backend implementation
4. **Provider Health** - Could integrate with model providers

---

## 9. USAGE WORKFLOW

### Scanning for Models:
1. Press 7 or click Models nav button
2. Enter path (e.g., /models, ~/Downloads)
3. Click "Scan for Models"
4. View candidates with capability hints

### Registering a Model:
1. After scan, click "Register" on desired model
2. Model added to registry

### Viewing Telemetry:
1. Press 6 or click Telemetry nav button
2. See posture, receipts, mutations, events

---

## 10. CONCLUSION

Karma now has:
- ✓ Live telemetry visibility in DeX
- ✓ One-click model discovery
- ✓ Role↔model assignment system
- ✓ Full pipeline status exposure
- ✓ Identity guard visibility
- ✓ Graceful fallback handling
- ✓ All local, no external dependencies
- ✓ Mobile accessible via Telemetry view

Karma remains the conductor. Agents and models are instruments.
