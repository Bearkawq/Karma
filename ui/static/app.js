// Karma Web UI — DeX dashboard client v2
(function() {
  "use strict";

  const $ = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  // -- Clock --
  function tick() {
    const el = $("#clock");
    if (el) el.textContent = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  }
  setInterval(tick, 10000);
  tick();

  // -- Navigation (1-7 keyboard shortcuts) --
  const viewNames = ["chat", "learn", "memory", "system", "evidence", "telemetry", "models"];
  let activeView = "chat";

  function switchView(v) {
    activeView = v;
    $$(".nav-btn").forEach(b => b.classList.remove("active"));
    $$(".view").forEach(vw => vw.classList.remove("active"));
    const btn = document.querySelector(`[data-view="${v}"]`);
    if (btn) btn.classList.add("active");
    const view = document.getElementById("view-" + v);
    if (view) view.classList.add("active");
    if (v === "memory") refreshMemory();
    else if (v === "system") refreshSystem();
    else if (v === "evidence") refreshEvidence();
    else if (v === "telemetry") refreshTelemetry();
    else if (v === "models") refreshModels();
  }

  $$(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  document.addEventListener("keydown", e => {
    // Number keys 1-5 switch views (when not in input)
    if (!e.ctrlKey && !e.metaKey && !e.altKey && e.target.tagName !== "INPUT" && e.target.tagName !== "TEXTAREA") {
      const idx = parseInt(e.key) - 1;
      if (idx >= 0 && idx < viewNames.length) {
        switchView(viewNames[idx]);
        return;
      }
    }
  });

  // -- SSE --
  let sse = null;
  function connectSSE() {
    sse = new EventSource("/api/events");
    sse.onopen = () => {
      const dot = $("#status-dot");
      dot.className = "status-dot live";
      dot.title = "connected";
    };
    sse.onerror = () => {
      const dot = $("#status-dot");
      dot.className = "status-dot error";
      dot.title = "reconnecting";
    };
    sse.onmessage = e => {
      try {
        const evt = JSON.parse(e.data);
        handleEvent(evt);
      } catch(_) {}
    };
  }

  function handleEvent(evt) {
    const kind = evt.kind || "";
    const data = evt.data || {};

    // Learn activity log
    const log = $("#learn-log");
    if (log && (kind.startsWith("learn_") || kind === "source_fetched" || kind === "note_written" || kind === "branch_selected")) {
      const detail = data.subtopic || data.topic || data.url || data.error || "";
      const cls = kind.includes("error") ? "ev-error" : "ev-learn";
      const label = kind.replace("learn_", "").replace("_", " ");
      const el = document.createElement("div");
      el.className = cls;
      el.textContent = label + (detail ? ": " + detail.slice(0, 80) : "");
      log.appendChild(el);
      while (log.children.length > 50) log.removeChild(log.firstChild);
      log.scrollTop = log.scrollHeight;
    }

    // Toast notification
    let toastCls = "";
    let toastText = "";
    if (kind.startsWith("learn_")) {
      toastCls = kind.includes("error") ? "ev-error" : "ev-learn";
      toastText = kind.replace("learn_", "").replace("_", " ") + ": " + (data.subtopic || data.topic || "").slice(0, 50);
    } else if (kind === "executed") {
      toastCls = "ev-exec";
      toastText = "executed: " + (data.action || data.tool || "?");
    } else if (kind === "reflected") {
      toastCls = "ev-exec";
      const c = data.confidence !== undefined ? " (" + (data.confidence * 100).toFixed(0) + "%)" : "";
      toastText = "reflected" + c;
    }
    if (toastText) showToast(toastText, toastCls);

    // Update confidence gauge on reflect events
    if (kind === "reflected" && data.confidence !== undefined) {
      updateConfGauge(data.confidence);
    }
  }

  connectSSE();

  // -- Toast --
  function showToast(text, cls) {
    const container = $("#toasts");
    if (!container) return;
    const el = document.createElement("div");
    el.className = "toast " + (cls || "");
    el.textContent = text;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
    while (container.children.length > 5) container.removeChild(container.firstChild);
  }

  // -- Confidence Gauge --
  function updateConfGauge(conf) {
    const fill = $("#conf-fill");
    const text = $("#conf-text");
    if (!fill || !text) return;
    const pct = Math.round(conf * 100);
    fill.style.width = pct + "%";
    fill.className = "conf-fill " + (pct >= 70 ? "high" : pct >= 40 ? "mid" : "low");
    text.textContent = pct + "%";
  }

  // Fetch initial confidence
  fetch("/api/confidence").then(r => r.json()).then(d => {
    if (d.current !== undefined) updateConfGauge(d.current);
  }).catch(() => {});

  // -- Chat --
  const messages = $("#messages");
  const cmdform = $("#cmdform");
  const cmdinput = $("#cmdinput");
  const sendBtn = $("#send-btn");

  function addMsg(text, type) {
    const el = document.createElement("div");
    el.className = "msg msg-" + type;
    el.textContent = text;
    // Timestamp
    const ts = document.createElement("div");
    ts.className = "msg-ts";
    ts.textContent = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
    el.appendChild(ts);
    messages.appendChild(el);
    while (messages.children.length > 200) messages.removeChild(messages.firstChild);
    messages.scrollTop = messages.scrollHeight;
  }

  function addThinking() {
    const el = document.createElement("div");
    el.className = "msg-thinking";
    el.id = "thinking";
    el.textContent = "thinking";
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
    return el;
  }

  function removeThinking() {
    const el = document.getElementById("thinking");
    if (el) el.remove();
  }

  cmdform.addEventListener("submit", async e => {
    e.preventDefault();
    const text = cmdinput.value.trim();
    if (!text) return;
    cmdinput.value = "";
    addMsg(text, "user");

    sendBtn.disabled = true;
    addThinking();

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message: text}),
      });
      removeThinking();
      const data = await resp.json();
      const result = data.data?.response || data.result || "Done.";
      const cls = data.ok ? "karma" : "karma error";
      addMsg(result, cls);
      // Update confidence after chat
      fetch("/api/confidence").then(r => r.json()).then(d => {
        if (d.current !== undefined) updateConfGauge(d.current);
      }).catch(() => {});
    } catch(err) {
      removeThinking();
      addMsg("Connection error: " + err.message, "karma error");
    }
    sendBtn.disabled = false;
    cmdinput.focus();
  });

  // -- GoLearn --
  $("#gl-btn").addEventListener("click", async () => {
    const topic = $("#gl-topic").value.trim();
    if (!topic) return;
    const mins = parseInt($("#gl-mins").value) || 3;
    const mode = $("#gl-mode").value;
    const btn = $("#gl-btn");

    addMsg('golearn "' + topic + '" ' + mins + " " + mode, "user");

    btn.disabled = true;
    btn.textContent = "Learning...";
    addThinking();

    try {
      const resp = await fetch("/api/golearn", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({topic, minutes: mins, mode}),
      });
      removeThinking();
      const data = await resp.json();
      addMsg(data.result || "Done.", data.success ? "karma" : "karma error");
    } catch(err) {
      removeThinking();
      addMsg("Error: " + err.message, "karma error");
    }

    btn.disabled = false;
    btn.textContent = "Start Learning";
    $("#gl-topic").value = "";
    refreshMemory();
  });

  // -- Memory View --
  let allFacts = []; // cached for filtering

  async function refreshMemory() {
    try {
      const [memResp, factsResp, tasksResp] = await Promise.all([
        fetch("/api/memory"), fetch("/api/facts"), fetch("/api/tasks")
      ]);
      const mem = await memResp.json();
      const facts = await factsResp.json();
      const tasks = await tasksResp.json();

      allFacts = facts;

      // Stats
      const stats = $("#mem-stats");
      stats.innerHTML = "";
      addStat(stats, mem.facts_count || 0, "Facts");
      addStat(stats, mem.episodic_count || 0, "Episodes");
      addStat(stats, mem.tasks_count || 0, "Tasks");
      if (mem.learn_sessions !== undefined) addStat(stats, mem.learn_sessions, "Sessions");

      renderFacts(facts);

      // Tasks list
      const tl = $("#tasks-list");
      tl.innerHTML = "";
      if (!tasks.length) { tl.innerHTML = '<div style="color:var(--text2)">No tasks</div>'; }
      for (const t of tasks.slice(0, 30)) {
        const row = document.createElement("div");
        row.className = "item-row";
        const key = document.createElement("span");
        key.className = "item-key";
        key.textContent = t.goal || t.id || "?";
        const badge = document.createElement("span");
        badge.className = "item-badge";
        badge.textContent = t.status || "?";
        row.appendChild(key);
        row.appendChild(badge);
        tl.appendChild(row);
      }
    } catch(_) {}
  }

  function renderFacts(facts) {
    const fl = $("#facts-list");
    const countEl = $("#facts-count");
    fl.innerHTML = "";
    if (countEl) countEl.textContent = facts.length;
    if (!facts.length) { fl.innerHTML = '<div style="color:var(--text2)">No facts yet</div>'; return; }
    for (const f of facts.slice(0, 80)) {
      const v = (typeof f.value === "object") ? f.value : {};
      const conf = v.confidence || 0;
      const useCount = v.use_count || 0;
      const infCount = v.influence_count || 0;

      const row = document.createElement("div");
      row.className = "item-row";
      row.style.cursor = "pointer";

      const key = document.createElement("span");
      key.className = "item-key";
      key.textContent = f.key;

      const meta = document.createElement("span");
      meta.className = "item-meta";
      if (useCount > 0 || infCount > 0) {
        meta.innerHTML = '<span class="used">' + useCount + 'u</span><span class="used">' + infCount + 'i</span>';
      } else {
        meta.innerHTML = '<span class="unused">unused</span>';
      }

      const badge = document.createElement("span");
      badge.className = "item-badge" + (conf >= 0.7 ? " high" : "");
      badge.textContent = (conf * 100).toFixed(0) + "%";

      row.appendChild(key);
      row.appendChild(meta);
      row.appendChild(badge);

      // Expandable detail
      const detail = document.createElement("div");
      detail.className = "item-detail";
      const valText = v.value || (typeof f.value === "string" ? f.value : JSON.stringify(f.value));
      detail.textContent = "Value: " + valText + "\nSource: " + (v.source || "?") + "\nUpdated: " + (v.last_updated || "?").slice(0, 19);
      if (v.last_used) detail.textContent += "\nLast used: " + v.last_used.slice(0, 19);

      row.addEventListener("click", () => {
        row.classList.toggle("expanded");
        detail.classList.toggle("show");
      });

      fl.appendChild(row);
      fl.appendChild(detail);
    }
  }

  // Fact search/filter
  const factSearch = $("#fact-search");
  if (factSearch) {
    factSearch.addEventListener("input", () => {
      const q = factSearch.value.toLowerCase();
      if (!q) { renderFacts(allFacts); return; }
      const filtered = allFacts.filter(f => {
        const key = f.key.toLowerCase();
        const val = typeof f.value === "object" ? JSON.stringify(f.value).toLowerCase() : String(f.value).toLowerCase();
        return key.includes(q) || val.includes(q);
      });
      renderFacts(filtered);
    });
  }

  function addStat(container, value, label) {
    const el = document.createElement("div");
    el.className = "stat";
    el.innerHTML = '<div class="stat-value">' + esc(String(value)) + '</div><div class="stat-label">' + esc(label) + '</div>';
    container.appendChild(el);
  }

  // -- System View --
  let sysAutoInterval = null;

  // Selected run key for detail panel
  let selectedRunKey = null;

  async function refreshSystem() {
    try {
      const [stateResp, toolsResp, logResp, mapResp, tlResp, capsResp, healthResp, confResp, runtimeResp, workersResp, runsResp, sessionResp] = await Promise.all([
        fetch("/api/state"), fetch("/api/tools"), fetch("/api/log"),
        fetch("/api/system-map"), fetch("/api/timeline"), fetch("/api/capabilities"),
        fetch("/api/health"), fetch("/api/confidence"),
        fetch("/api/active_runtime"), fetch("/api/workers"),
        fetch("/api/runs/recent"), fetch("/api/session")
      ]);
      const state = (await stateResp.json()).data || {};
      const tools = await toolsResp.json();
      const log = await logResp.json();
      const sysMap = await mapResp.json();
      const timeline = await tlResp.json();
      const caps = await capsResp.json();
      const health = (await healthResp.json()).data || {};
      const confData = await confResp.json();
      const runtime = (await runtimeResp.json()).data || {};
      const workers = (await workersResp.json()).data || [];
      const runs = (await runsResp.json()).data || {};
      const session = (await sessionResp.json()).data || {};
      
      // === SESSION PANEL ===
      const sessionEl = $("#sys-session");
      if (sessionEl) {
        sessionEl.innerHTML = "";
        const ss = session.summary || {};
        addKV(sessionEl, "Started", session.session_start?.slice(11, 19) || "?");
        addKV(sessionEl, "Runs", ss.total_runs || 0);
        addKV(sessionEl, "Success", ss.ok_count || 0, (ss.ok_count || 0) > 0 ? "good" : "");
        addKV(sessionEl, "Failed", ss.failed_count || 0, (ss.failed_count || 0) > 0 ? "warn" : "");
        addKV(sessionEl, "Recovered", ss.recovered_count || 0, (ss.recovered_count || 0) > 0 ? "warn" : "");
      }
      
      // Session summary formatted text
      const ssBox = $("#sys-session-summary");
      if (ssBox) {
        if (session.formatted) {
          ssBox.innerHTML = esc(session.formatted);
        } else {
          ssBox.innerHTML = '<div style="color:var(--text2)">No runs this session</div>';
        }
      }
      
      // === SELF-CHECK PANEL ===
      const scBox = $("#sys-selfcheck");
      if (scBox) {
        const check = session.selfcheck;
        if (check) {
          scBox.textContent = check;
          const issues = (session.summary?.issues || []).length;
          scBox.className = "selfcheck-box " + (issues === 0 ? "sc-good" : issues <= 2 ? "sc-warn" : "sc-bad");
        } else {
          scBox.innerHTML = '<div style="color:var(--text2)">No issues detected</div>';
          scBox.className = "selfcheck-box sc-good";
        }
      }
      
      // === RUNS PANEL ===
      const recentRuns = runs.recent_runs || [];
      
      // Compute run stats from actual data using run_kind semantics
      const toolRuns = recentRuns.filter(r => r.run_kind === 'tool');
      const primaryRuns = recentRuns.filter(r => r.run_kind === 'primary' || !r.run_kind);
      const recoveryRuns = recentRuns.filter(r => r.run_kind === 'recovery');
      
      const failedRuns = recentRuns.filter(r => r.outcome === 'failed');
      const successRuns = recentRuns.filter(r => r.outcome === 'success');
      const recoveredRuns = recentRuns.filter(r => r.recovered);
      
      const rlStats = $("#sys-runs");
      if (rlStats) {
        rlStats.innerHTML = "";
        addKV(rlStats, "Total", recentRuns.length);
        addKV(rlStats, "Primary", primaryRuns.length);
        addKV(rlStats, "Tool", toolRuns.length);
        addKV(rlStats, "Recovery", recoveryRuns.length);
        addKV(rlStats, "Failed", failedRuns.length, failedRuns.length > 0 ? "warn" : "");
        addKV(rlStats, "Success", successRuns.length, successRuns.length > 0 ? "good" : "");
        addKV(rlStats, "Recovered", recoveredRuns.length, recoveredRuns.length > 0 ? "warn" : "");
        if (runs.last_task) {
          addKV(rlStats, "Last", runs.last_task, runs.last_outcome === "failed" ? "warn" : "");
        }
      }
      
      // Update run detail panel with selected run
      const rdBox = $("#sys-run-detail");
      if (rdBox) {
        if (selectedRunKey) {
          const run = recentRuns.find(r => r.key === selectedRunKey);
          if (run) {
            const outcome = run.outcome || "";
            const badgeClass = outcome === 'success' ? 'ok' : run.recovered ? 'recovered' : outcome === 'failed' ? 'fail' : (run.run_kind === 'tool' ? 'tool' : 'primary');
            const toolLabel = run.tool ? `[${run.tool}] ` : '';
            const kindLabel = run.run_kind ? run.run_kind : '';
            
            // Critic findings - show prominently when present
            let criticHtml = '';
            const issues = run.critic_issues || [];
            const lesson = run.critic_lesson || '';
            if (issues.length || lesson) {
              criticHtml = `<div class="rd-critic-box">
                <div class="rd-critic-header">Critic Findings</div>
                ${issues.length ? `<div class="rd-issues">${issues.map((i, idx) => `<div class="rd-issue">${idx+1}. ${esc(i)}</div>`).join('')}</div>` : ''}
                ${lesson && (!issues.length || issues[0] !== lesson) ? `<div class="rd-lesson"><strong>Lesson:</strong> ${esc(lesson)}</div>` : ''}
              </div>`;
            }
            
            rdBox.innerHTML = `
              <div class="rd-header">
                <span class="rd-badge ${badgeClass}">${outcome || 'unknown'}</span>
                ${kindLabel ? `<span class="rd-badge" style="background:var(--surface);color:var(--text)">${kindLabel}</span>` : ''}
                ${run.tool ? `<span class="rd-badge" style="background:var(--cyan);color:#000">${run.tool}</span>` : ''}
              </div>
              <div class="rd-task">${toolLabel}${run.task || run.key}</div>
              ${run.summary ? `<div class="rd-summary">${run.summary}</div>` : ''}
              ${run.error ? `<div class="rd-error">${esc(run.error)}</div>` : ''}
              ${criticHtml}
              <div class="rd-meta">
                ${run.timestamp ? `<span>${run.timestamp.slice(0, 19)}</span>` : ''}
                ${run.key ? `<span class="rd-key">${run.key}</span>` : ''}
              </div>
            `;
          } else {
            rdBox.innerHTML = '<div style="color:var(--text2)">Select a run from the list</div>';
          }
        } else {
          rdBox.innerHTML = '<div style="color:var(--text2)">Click a run to see details</div>';
        }
      }
      
      // Single runs list with click selection and critic indicators
      const rlList = $("#sys-singles");
      if (rlList) {
        rlList.innerHTML = "";
        for (const r of recentRuns.slice(0, 10)) {
          const row = document.createElement("div");
          row.className = "tl-entry" + (r.key === selectedRunKey ? " selected" : "");
          const outcome = r.outcome === 'success' ? 'ok' : r.recovered ? 'recovered' : r.outcome === 'failed' ? 'fail' : '';
          const hasCritic = (r.critic_issues && r.critic_issues.length) || r.critic_lesson;
          const label = r.tool ? `[${r.tool}] ` : '';
          const kind = r.run_kind === 'tool' ? '[T]' : r.run_kind === 'recovery' ? '[R]' : '';
          row.innerHTML = `<span class="tl-dot ${outcome}"></span><span class="tl-intent">${kind}${label}${r.task || r.key}</span>${hasCritic ? '<span class="tl-critic-dot" title="Has critic">●</span>' : ''}<span class="tl-conf">${r.outcome}</span>`;
          row.style.cursor = "pointer";
          row.addEventListener("click", () => {
            selectedRunKey = r.key;
            refreshSystem();
          });
          rlList.appendChild(row);
        }
      }

      // Active Runtime
      const rl = $("#sys-runtime");
      if (rl) {
        rl.innerHTML = "";
        const rtd = runtime;
        const isActive = rtd.is_active;
        addKV(rl, "Status", isActive ? "ACTIVE" : "idle", isActive ? "good" : "");
        addKV(rl, "Role", rtd.current_role || "none");
        addKV(rl, "Task", rtd.current_task || "none");
        addKV(rl, "Slot", rtd.active_slot || "none");
        addKV(rl, "Model", rtd.active_model || "none");
        addKV(rl, "Execution", rtd.execution_mode || "local");
        if (rtd.fallback_used) {
          addKV(rl, "Fallback", "yes", "warn");
        }
        addKV(rl, "Posture", rtd.posture || "CALM");
      }

      // Worker Status
      const wl = $("#sys-workers");
      if (wl) {
        wl.innerHTML = "";
        const workerList = workers.data || [];
        if (workerList.length === 0) {
          addKV(wl, "Workers", "none registered");
          addKV(wl, "Mode", "local only");
        } else {
          for (const w of workerList) {
            const status = w.status || "unknown";
            const statusCls = status === "online" ? "good" : status === "offline" ? "bad" : "";
            addKV(wl, w.node_id, status, statusCls);
            const caps = [];
            if (w.capabilities) {
              if (w.capabilities.can_plan) caps.push("plan");
              if (w.capabilities.can_execute) caps.push("exec");
              if (w.capabilities.can_retrieve) caps.push("retrieve");
              if (w.capabilities.can_summarize) caps.push("summarize");
            }
            if (caps.length) {
              addKV(wl, "  caps", caps.join(", "));
            }
          }
        }
      }

      // State
      const sl = $("#sys-state");
      sl.innerHTML = "";
      addKV(sl, "Last run", state.last_run ? state.last_run.slice(0, 19) : "never");
      addKV(sl, "Current task", state.current_task || "none");
      const ds = state.decision_summary || {};
      addKV(sl, "Decisions", ds.total_decisions || 0);
      const sr = ((ds.success_rate || 0) * 100).toFixed(0);
      addKV(sl, "Success rate", sr + "%", sr >= 70 ? "good" : sr >= 40 ? "warn" : "bad");
      addKV(sl, "Confidence", (ds.average_confidence || 0).toFixed(2));

      // System Map
      const sm = $("#sys-map");
      if (sm) {
        sm.innerHTML = "";
        for (const [k, v] of Object.entries(sysMap)) {
          let cls = "";
          if (k === "ram_available") {
            const mb = parseInt(v) / 1024;
            cls = mb > 500 ? "good" : mb > 200 ? "warn" : "bad";
          }
          addKV(sm, k.replace(/_/g, " "), v, cls);
        }
      }

      // Tools
      const tl = $("#sys-tools");
      tl.innerHTML = "";
      addKV(tl, "Enabled", (tools.enabled || []).join(", "));
      addKV(tl, "Registered", (tools.registered || []).join(", "));
      if (tools.custom && tools.custom.length) addKV(tl, "Custom", tools.custom.join(", "));

      // Capabilities (with scores)
      const cl = $("#sys-caps");
      if (cl) {
        cl.innerHTML = "";
        for (const cap of caps) {
          const tag = document.createElement("span");
          tag.className = "cap-tag " + (cap.type || "");
          let label = cap.name;
          if (cap.score) {
            const sr2 = (cap.score.recent_success_rate * 100).toFixed(0);
            label += " " + sr2 + "%";
            if (cap.score.recent_success_rate < 0.5) tag.classList.add("warn");
          }
          tag.textContent = label;
          tag.title = cap.score ? "Uses: " + cap.score.total_uses + ", Contexts: " + (cap.score.best_contexts || []).join(", ") : "";
          cl.appendChild(tag);
        }
      }

      // Health
      const hl = $("#sys-health");
      if (hl) {
        hl.innerHTML = "";
        if (health.error) {
          addKV(hl, "Error", health.error, "bad");
        } else {
          const issues = health.issues || [];
          addKV(hl, "Status", issues.length ? issues.length + " issues" : "Healthy", issues.length ? "warn" : "good");
          addKV(hl, "Checked", (health.timestamp || "?").slice(11, 19));
          for (const iss of issues.slice(0, 8)) {
            const cls2 = iss.repair_class || "unknown";
            addKV(hl, cls2, iss.issue || "?", "warn");
          }
        }
      }

      // Confidence trend chart
      drawConfChart(confData.points || []);
      if (confData.current !== undefined) updateConfGauge(confData.current);

      // Timeline
      const te = $("#sys-timeline");
      if (te) {
        te.innerHTML = "";
        if (!timeline.length) {
          te.innerHTML = '<div style="color:var(--text2)">No activity yet</div>';
        }
        for (const entry of timeline) {
          const row = document.createElement("div");
          row.className = "tl-entry";
          const dot = document.createElement("span");
          dot.className = "tl-dot " + (entry.success ? "ok" : "fail");
          const time = document.createElement("span");
          time.className = "tl-time";
          time.textContent = entry.time ? entry.time.slice(11, 16) : "?";
          const intent = document.createElement("span");
          intent.className = "tl-intent";
          intent.textContent = entry.intent;
          const conf = document.createElement("span");
          conf.className = "tl-conf";
          conf.textContent = (entry.confidence * 100).toFixed(0) + "%";
          row.appendChild(dot);
          row.appendChild(time);
          row.appendChild(intent);
          row.appendChild(conf);
          te.appendChild(row);
        }
        te.scrollTop = te.scrollHeight;
      }

      // Log (with color coding)
      const ll = $("#sys-log");
      ll.innerHTML = "";
      for (const line of (log.lines || []).slice(-40)) {
        const el = document.createElement("div");
        el.textContent = line;
        if (line.includes("ERROR") || line.includes("error")) el.className = "log-err";
        else if (line.includes("WARNING") || line.includes("warn")) el.className = "log-warn";
        ll.appendChild(el);
      }
      ll.scrollTop = ll.scrollHeight;
    } catch(_) {}
  }

  // Auto-refresh system view
  const sysAutoCheck = $("#sys-auto");
  if (sysAutoCheck) {
    function startSysAuto() {
      if (sysAutoInterval) clearInterval(sysAutoInterval);
      sysAutoInterval = setInterval(() => {
        if (activeView === "system" && sysAutoCheck.checked) refreshSystem();
      }, 10000);
    }
    sysAutoCheck.addEventListener("change", () => {
      if (sysAutoCheck.checked) startSysAuto();
      else if (sysAutoInterval) { clearInterval(sysAutoInterval); sysAutoInterval = null; }
    });
    startSysAuto();
  }

  // -- Confidence trend chart --
  function drawConfChart(points) {
    const canvas = $("#conf-canvas");
    if (!canvas || !points.length) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.offsetWidth;
    const h = 80;
    canvas.width = w * 2;
    canvas.height = h * 2;
    ctx.scale(2, 2);

    ctx.clearRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = "rgba(255,255,255,.06)";
    ctx.lineWidth = 1;
    for (const y of [0.25, 0.5, 0.75]) {
      ctx.beginPath();
      ctx.moveTo(0, h - y * h);
      ctx.lineTo(w, h - y * h);
      ctx.stroke();
    }

    // Threshold line at 0.4
    ctx.strokeStyle = "rgba(255,92,92,.3)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, h - 0.4 * h);
    ctx.lineTo(w, h - 0.4 * h);
    ctx.stroke();
    ctx.setLineDash([]);

    // Confidence line
    const step = w / Math.max(points.length - 1, 1);
    ctx.beginPath();
    ctx.strokeStyle = "rgba(108,138,255,.8)";
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    for (let i = 0; i < points.length; i++) {
      const x = i * step;
      const y = h - (points[i].c * h);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Dots for success/fail
    for (let i = 0; i < points.length; i++) {
      const x = i * step;
      const y = h - (points[i].c * h);
      ctx.fillStyle = points[i].s ? "#4cdf8a" : "#ff5c5c";
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // -- Evidence View --
  async function refreshEvidence() {
    try {
      const [retResp, capResp, repairResp] = await Promise.all([
        fetch("/api/retrieval-stats"), fetch("/api/capability-map"), fetch("/api/repair-history")
      ]);
      const ret = await retResp.json();
      const capMap = await capResp.json();
      const repairs = await repairResp.json();

      // Retrieval stats
      const sr = $("#ev-stats");
      sr.innerHTML = "";
      addStat(sr, ret.decisions || 0, "Decisions");
      addStat(sr, ret.total_hits || 0, "Total Hits");
      addStat(sr, ret.total_used || 0, "Used");
      addStat(sr, ret.total_ignored || 0, "Ignored");

      // Retrieval details
      const rl = $("#ev-retrieval");
      rl.innerHTML = "";
      for (const [k, v] of Object.entries(ret)) {
        if (k.startsWith("hits_")) {
          addKV(rl, k.replace("hits_", ""), v);
        }
      }

      // Capability map bars
      const cm = $("#ev-capmap");
      cm.innerHTML = "";
      const entries = Object.entries(capMap).sort((a, b) => b[1].total_uses - a[1].total_uses);
      for (const [name, data] of entries) {
        const row = document.createElement("div");
        row.className = "cap-bar-row";
        const nameEl = document.createElement("span");
        nameEl.className = "cap-bar-name";
        nameEl.textContent = name;
        nameEl.title = "Contexts: " + (data.best_contexts || []).join(", ");
        const track = document.createElement("div");
        track.className = "cap-bar-track";
        const fill = document.createElement("div");
        fill.className = "cap-bar-fill";
        const pct = data.recent_success_rate * 100;
        fill.style.width = pct + "%";
        fill.classList.add(pct >= 70 ? "high" : pct >= 40 ? "mid" : "low");
        track.appendChild(fill);
        const pctEl = document.createElement("span");
        pctEl.className = "cap-bar-pct";
        pctEl.textContent = pct.toFixed(0) + "%";
        row.appendChild(nameEl);
        row.appendChild(track);
        row.appendChild(pctEl);
        cm.appendChild(row);
      }
      if (!entries.length) cm.innerHTML = '<div style="color:var(--text2)">No capability data yet</div>';

      // Repair history
      const rp = $("#ev-repairs");
      rp.innerHTML = "";
      const repairEntries = Object.entries(repairs);
      if (!repairEntries.length) {
        rp.innerHTML = '<div style="color:var(--text2)">No repair history</div>';
      }
      for (const [cls, history] of repairEntries) {
        const successes = history.filter(h => h.success).length;
        const total = history.length;
        const rate = total ? successes / total : 0;

        const row = document.createElement("div");
        row.className = "repair-row";
        const nameEl = document.createElement("span");
        nameEl.className = "repair-class";
        nameEl.textContent = cls;
        const track = document.createElement("div");
        track.className = "repair-bar-track";
        const fill = document.createElement("div");
        fill.className = "repair-bar-fill";
        fill.style.width = (rate * 100) + "%";
        fill.style.background = rate >= 0.7 ? "var(--green)" : rate >= 0.4 ? "var(--yellow)" : "var(--red)";
        track.appendChild(fill);
        const countEl = document.createElement("span");
        countEl.className = "repair-count";
        countEl.textContent = successes + "/" + total;
        row.appendChild(nameEl);
        row.appendChild(track);
        row.appendChild(countEl);
        rp.appendChild(row);
      }
    } catch(_) {}
  }

  // -- Tool Sandbox --
  const sandboxBtn = $("#sandbox-btn");
  const sandboxCmd = $("#sandbox-cmd");
  if (sandboxBtn && sandboxCmd) {
    const runSandbox = async () => {
      const text = sandboxCmd.value.trim();
      if (!text) return;
      sandboxCmd.value = "";
      addMsg(text, "user");
      sandboxBtn.disabled = true;
      addThinking();
      try {
        const resp = await fetch("/api/command", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({command: text}),
        });
        removeThinking();
        const data = await resp.json();
        const result = data.data?.result || data.result || "Done.";
        const cls = data.ok ? "karma" : "karma error";
        addMsg(result, cls);
      } catch(err) {
        removeThinking();
        addMsg("Error: " + err.message, "karma error");
      }
      sandboxBtn.disabled = false;
      switchView("chat");
    };
    sandboxBtn.addEventListener("click", runSandbox);
    sandboxCmd.addEventListener("keydown", e => { if (e.key === "Enter") runSandbox(); });
  }

  // -- Command Palette (Ctrl+K) --
  const PALETTE_COMMANDS = [
    {name: "help", hint: "Show what Karma can do", key: ""},
    {name: "what do you know", hint: "List learned topics", key: ""},
    {name: "self-upgrade", hint: "Analyze codebase for improvements", key: ""},
    {name: "list tools", hint: "Show custom tools", key: ""},
    {name: "list files", hint: "Show files in current directory", key: ""},
    {name: "status", hint: "Agent status", key: ""},
    {name: "reload language", hint: "Reload language mappings", key: ""},
    {name: "teach", hint: "Teach Karma a new fact", key: ""},
    {name: "forget", hint: "Remove a fact from memory", key: ""},
    {name: "golearn", hint: "Start a learning session", key: "2"},
    {name: "health check", hint: "Run health diagnostics", key: ""},
    {name: "compress memory", hint: "Run memory compression", key: ""},
  ];

  const overlay = $("#palette-overlay");
  const palInput = $("#palette-input");
  const palResults = $("#palette-results");
  let palSelected = 0;

  function openPalette() {
    overlay.classList.add("open");
    palInput.value = "";
    palInput.focus();
    palSelected = 0;
    renderPalette("");
  }
  function closePalette() {
    overlay.classList.remove("open");
  }
  function renderPalette(query) {
    palResults.innerHTML = "";
    const q = query.toLowerCase();
    const filtered = q ? PALETTE_COMMANDS.filter(c => c.name.includes(q) || c.hint.toLowerCase().includes(q)) : PALETTE_COMMANDS;
    palSelected = Math.min(palSelected, filtered.length - 1);
    if (palSelected < 0) palSelected = 0;
    filtered.forEach((cmd, i) => {
      const el = document.createElement("div");
      el.className = "palette-item" + (i === palSelected ? " selected" : "");
      let inner = esc(cmd.name) + ' <span class="palette-hint">' + esc(cmd.hint) + '</span>';
      if (cmd.key) inner += '<span class="palette-key">' + cmd.key + '</span>';
      el.innerHTML = inner;
      el.addEventListener("click", () => {
        closePalette();
        cmdinput.value = cmd.name;
        cmdform.dispatchEvent(new Event("submit"));
      });
      palResults.appendChild(el);
    });
    if (q && !filtered.length) {
      const el = document.createElement("div");
      el.className = "palette-item selected";
      el.innerHTML = 'Run: <strong>' + esc(q) + '</strong>';
      el.addEventListener("click", () => {
        closePalette();
        cmdinput.value = q;
        cmdform.dispatchEvent(new Event("submit"));
      });
      palResults.appendChild(el);
    }
  }

  document.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault();
      if (overlay.classList.contains("open")) closePalette();
      else openPalette();
    }
    if (e.key === "Escape" && overlay.classList.contains("open")) closePalette();
  });
  if (overlay) overlay.addEventListener("click", e => { if (e.target === overlay) closePalette(); });
  if (palInput) {
    palInput.addEventListener("input", () => {
      palSelected = 0;
      renderPalette(palInput.value);
    });
    palInput.addEventListener("keydown", e => {
      const items = palResults.querySelectorAll(".palette-item");
      if (e.key === "ArrowDown") {
        e.preventDefault();
        palSelected = Math.min(palSelected + 1, items.length - 1);
        renderPalette(palInput.value);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        palSelected = Math.max(palSelected - 1, 0);
        renderPalette(palInput.value);
      } else if (e.key === "Enter") {
        const sel = palResults.querySelector(".palette-item.selected") || palResults.querySelector(".palette-item");
        if (sel) sel.click();
      }
    });
  }

  function addKV(container, label, value, cls) {
    const row = document.createElement("div");
    row.className = "kv-row";
    row.innerHTML = '<span class="kv-label">' + esc(label) + '</span><span class="kv-value' + (cls ? ' ' + cls : '') + '">' + esc(String(value)) + '</span>';
    container.appendChild(row);
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // -- Telemetry View --
  async function refreshTelemetry() {
    try {
      const resp = await fetch("/api/telemetry/dashboard");
      const j = await resp.json();
      if (!j.ok) return;
      const d = j.data;
      
      // Posture
      const posture = d.posture?.posture || "CALM";
      document.getElementById("telemetry-posture").textContent = posture;
      document.getElementById("telemetry-posture").className = "posture-badge " + posture.toLowerCase();
      document.getElementById("stat-posture").textContent = posture;
      document.getElementById("stat-revision").textContent = d.revision || 0;
      document.getElementById("stat-pipeline").textContent = d.pipeline?.manager?.agents?.enabled || 0 + " agents";
      
      // Last receipt
      const receipt = d.latest_receipt;
      const receiptEl = document.getElementById("telemetry-receipt");
      receiptEl.innerHTML = "";
      if (receipt) {
        addKV(receiptEl, "Action", receipt.action_name);
        addKV(receiptEl, "Handler", receipt.handler);
        addKV(receiptEl, "Time", receipt.execution_time_ms?.toFixed(1) + "ms");
        addKV(receiptEl, "Status", receipt.result_status);
      } else {
        receiptEl.innerHTML = '<div class="kv-row"><span class="kv-value">No receipts yet</span></div>';
      }
      
      // Last mutation
      const mutation = d.last_mutation;
      const mutationEl = document.getElementById("telemetry-mutation");
      mutationEl.innerHTML = "";
      if (mutation) {
        addKV(mutationEl, "Source", mutation.source);
        addKV(mutationEl, "Change", mutation.change_type);
        addKV(mutationEl, "Object", mutation.object_id);
      } else {
        mutationEl.innerHTML = '<div class="kv-row"><span class="kv-value">No mutations yet</span></div>';
      }
      
      // Route trace
      const trace = d.latest_route_trace;
      const routeEl = document.getElementById("telemetry-route");
      routeEl.innerHTML = "";
      if (trace) {
        addKV(routeEl, "Intent", trace.detected_intent || "?");
        addKV(routeEl, "Confidence", (trace.confidence * 100).toFixed(0) + "%");
        addKV(routeEl, "Action", trace.selected_action || "?");
        addKV(routeEl, "Lane", trace.lane || "?");
      } else {
        routeEl.innerHTML = '<div class="kv-row"><span class="kv-value">No traces yet</span></div>';
      }
      
      // Events
      const eventsEl = document.getElementById("telemetry-events");
      eventsEl.innerHTML = "";
      const events = d.events?.recent || [];
      for (const evt of events.slice(0, 10)) {
        const item = document.createElement("div");
        item.className = "event-item";
        item.innerHTML = '<span class="event-time">' + (evt.timestamp?.slice(11, 19) || "") + '</span><span class="event-type">' + (evt.event_type || "") + '</span>';
        eventsEl.appendChild(item);
      }
      
    } catch (e) {
      console.error("Telemetry refresh error:", e);
    }
  }

  // -- Models View --
  async function refreshModels() {
    try {
      // Agents
      const agentsResp = await fetch("/api/agents");
      const agentsJ = await agentsResp.json();
      const agentsEl = document.getElementById("model-agents");
      agentsEl.innerHTML = "";
      if (agentsJ.ok) {
        for (const agent of agentsJ.data) {
          const status = agent.available ? "ready" : "disabled";
          addKV(agentsEl, agent.role, status);
        }
      }
      
      // Models
      const modelsResp = await fetch("/api/models");
      const modelsJ = await modelsResp.json();
      const modelsEl = document.getElementById("model-list");
      modelsEl.innerHTML = "";
      if (modelsJ.ok) {
        for (const model of modelsJ.data) {
          const status = model.loaded ? "loaded" : model.status;
          addKV(modelsEl, model.model_id, status);
        }
      }
      
      // Slots
      const slotsResp = await fetch("/api/slots");
      const slotsJ = await slotsResp.json();
      const slotsEl = document.getElementById("model-slots");
      slotsEl.innerHTML = "";
      if (slotsJ.ok) {
        for (const slot of slotsJ.data.roles) {
          const div = document.createElement("div");
          div.className = "slot-item";
          div.innerHTML = '<div class="slot-name">' + esc(slot.role) + '</div><div class="slot-model"><span class="slot-status ' + (slot.model_loaded ? "loaded" : "unloaded") + '"></span>' + (slot.assigned_model_id || "none") + '</div>';
          slotsEl.appendChild(div);
        }
      }
      
    } catch (e) {
      console.error("Models refresh error:", e);
    }
  }

  // -- Model Scan --
  document.getElementById("scan-models-btn")?.addEventListener("click", async () => {
    const path = document.getElementById("scan-path").value || "/models";
    try {
      const resp = await fetch("/api/models/scan", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path, recursive: true})
      });
      const j = await resp.json();
      if (!j.ok) return;
      
      const resultsEl = document.getElementById("model-scan-results");
      resultsEl.innerHTML = "";
      
      for (const candidate of j.data.candidates) {
        const div = document.createElement("div");
        div.className = "scan-candidate";
        div.innerHTML = '<div class="scan-candidate-name">' + esc(candidate.name) + '</div><div class="scan-candidate-path">' + esc(candidate.path) + '</div><div class="scan-candidate-meta"><span>' + candidate.model_type + '</span><span>' + candidate.guessed_capability + '</span><span>' + candidate.runtime_hint + '</span></div>';
        
        const regBtn = document.createElement("button");
        regBtn.className = "btn-sm scan-register-btn";
        regBtn.textContent = "Register";
        regBtn.onclick = async () => {
          await fetch("/api/models/register", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              name: candidate.name,
              path: candidate.path,
              type: candidate.model_type
            })
          });
          refreshModels();
        };
        div.appendChild(regBtn);
        resultsEl.appendChild(div);
      }
      
      if (j.data.candidates.length === 0) {
        resultsEl.innerHTML = '<div class="kv-row"><span class="kv-value">No models found</span></div>';
      }
      
    } catch (e) {
      console.error("Scan error:", e);
    }
  });

  // -- Startup --
  addMsg("Karma online. Ctrl+K for commands, 1-5 to switch views.", "karma");
})();
