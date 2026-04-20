// Karma Mobile — offline-first PWA
(function() {
  "use strict";

  const $ = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  // -- Service Worker --
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js").catch(() => {});
  }

  // -- Clock --
  function tick() {
    const el = $("#clock");
    if (el) el.textContent = new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
  }
  setInterval(tick, 10000);
  tick();

  // -- Online/Offline detection --
  let online = navigator.onLine;
  function updateStatus(isOnline) {
    online = isOnline;
    const d = $("#dot");
    d.className = "dot " + (online ? "live" : "off");
    d.title = online ? "connected" : "offline";
  }
  window.addEventListener("online", () => updateStatus(true));
  window.addEventListener("offline", () => updateStatus(false));

  async function probe() {
    try {
      const r = await fetch("/api/log", {method: "GET", cache: "no-store"});
      updateStatus(r.ok);
    } catch(_) { updateStatus(false); }
  }
  probe();
  setInterval(probe, 15000);

  // -- Tab Navigation --
  $$(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".tab").forEach(b => b.classList.remove("active"));
      $$(".panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const p = $("#panel-" + btn.dataset.tab);
      if (p) p.classList.add("active");
      const t = btn.dataset.tab;
      if (t === "models") refreshModels();
      else if (t === "memory") refreshMemory();
      else if (t === "system") refreshSystem();
    });
  });

  // -- SSE --
  let sse = null;
  function connectSSE() {
    if (!online) return;
    try {
      sse = new EventSource("/api/events");
      sse.onmessage = e => {
        try { handleEvent(JSON.parse(e.data)); } catch(_) {}
      };
      sse.onerror = () => {
        if (sse) { sse.close(); sse = null; }
        setTimeout(connectSSE, 5000);
      };
    } catch(_) {}
  }

  function handleEvent(evt) {
    const kind = evt.kind || "";
    const data = evt.data || {};
    const log = $("#learn-log");
    if (!log) return;
    if (kind.startsWith("learn_") || kind === "source_fetched" || kind === "note_written") {
      const detail = data.subtopic || data.topic || data.url || data.error || "";
      const cls = kind.includes("error") ? "ev-error" : "ev-learn";
      const el = document.createElement("div");
      el.className = cls;
      el.textContent = kind.replace("learn_", "").replace("_", " ") + (detail ? ": " + detail.slice(0, 60) : "");
      log.appendChild(el);
      while (log.children.length > 40) log.removeChild(log.firstChild);
      log.scrollTop = log.scrollHeight;
    }
  }
  connectSSE();

  // -- Chat --
  const messages = $("#messages");
  const cmdform = $("#cmdform");
  const cmdinput = $("#cmdinput");
  const sendBtn = $("#send-btn");
  let cmdQueue = JSON.parse(localStorage.getItem("karma_queue") || "[]");

  function addMsg(text, type) {
    const el = document.createElement("div");
    el.className = "msg msg-" + type;
    el.textContent = text;
    messages.appendChild(el);
    while (messages.children.length > 150) messages.removeChild(messages.firstChild);
    messages.scrollTop = messages.scrollHeight;
  }

  function addThinking() {
    const el = document.createElement("div");
    el.className = "msg-thinking";
    el.id = "thinking";
    el.textContent = "thinking...";
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
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

    if (!online) {
      cmdQueue.push(text);
      localStorage.setItem("karma_queue", JSON.stringify(cmdQueue));
      addMsg("Queued (offline). Will send when connected.", "karma");
      return;
    }

    sendBtn.disabled = true;
    addThinking();
    try {
      const resp = await fetch("/api/command", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({command: text}),
      });
      removeThinking();
      const data = await resp.json();
      addMsg(data.result || "Done.", data.success ? "karma" : "karma error");
    } catch(err) {
      removeThinking();
      cmdQueue.push(text);
      localStorage.setItem("karma_queue", JSON.stringify(cmdQueue));
      addMsg("Connection lost. Command queued.", "karma error");
      updateStatus(false);
    }
    sendBtn.disabled = false;
    cmdinput.focus();
  });

  window.addEventListener("online", async () => {
    if (!cmdQueue.length) return;
    addMsg("Sending " + cmdQueue.length + " queued command(s)...", "karma");
    const q = [...cmdQueue];
    cmdQueue = [];
    localStorage.setItem("karma_queue", "[]");
    for (const cmd of q) {
      try {
        const resp = await fetch("/api/command", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({command: cmd}),
        });
        const data = await resp.json();
        addMsg("[queued] " + cmd, "user");
        addMsg(data.result || "Done.", data.success ? "karma" : "karma error");
      } catch(_) { cmdQueue.push(cmd); }
    }
    localStorage.setItem("karma_queue", JSON.stringify(cmdQueue));
  });

  // -- GoLearn --
  $("#gl-btn").addEventListener("click", async () => {
    const topic = $("#gl-topic").value.trim();
    if (!topic) return;
    const mins = parseInt($("#gl-mins").value) || 3;
    const mode = $("#gl-mode").value;
    const btn = $("#gl-btn");
    if (!online) { addMsg("Cannot learn while offline.", "karma error"); return; }
    btn.disabled = true;
    btn.textContent = "Learning...";
    addMsg('golearn "' + topic + '" ' + mins + " " + mode, "user");
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
    btn.textContent = "Start";
    $("#gl-topic").value = "";
  });

  // -- Models View (operator readiness) --
  async function refreshModels() {
    const badge = $("#ready-badge");
    const checks = $("#ready-checks");
    const roleList = $("#role-list");
    const issuesSec = $("#model-issues-section");
    const issuesEl = $("#model-issues");
    const nextEl = $("#model-next");

    badge.textContent = "loading...";
    badge.className = "ready-badge";

    try {
      const resp = await fetch("/api/model-ops/status");
      const j = await resp.json();
      const r = j.data;

      // Readiness badge
      const isReady = r.ready === true;
      badge.textContent = isReady ? "READY" : "NOT READY";
      badge.className = "ready-badge " + (isReady ? "ready" : "not-ready");

      // Checks
      checks.innerHTML = "";
      for (const c of (r.checks || [])) {
        addKV(checks, c.name, (c.ok ? "✓ " : "✗ ") + c.detail);
      }

      // Role assignments
      roleList.innerHTML = "";
      for (const row of (r.roles || [])) {
        const el = document.createElement("div");
        el.className = "role-row";

        const name = document.createElement("span");
        name.className = "role-name";
        name.textContent = row.role;

        const model = document.createElement("span");
        model.className = "role-model" + (row.assigned_model_id ? "" : " unassigned");
        model.textContent = row.assigned_model_id || "unassigned";

        const pill = document.createElement("span");
        if (!row.assigned_model_id) {
          pill.className = "model-pill unassigned";
          pill.textContent = "—";
        } else if (!row.exists_in_ollama) {
          pill.className = "model-pill missing";
          pill.textContent = "missing";
        } else if (row.warm_now) {
          pill.className = "model-pill warm";
          pill.textContent = "warm";
        } else {
          pill.className = "model-pill idle";
          pill.textContent = "idle";
        }

        el.appendChild(name);
        el.appendChild(model);
        el.appendChild(pill);
        roleList.appendChild(el);
      }

      // Issues (only show section if any)
      const roleIssues = (r.issues || {}).role_issues || [];
      issuesSec.style.display = roleIssues.length ? "" : "none";
      issuesEl.innerHTML = "";
      for (const iss of roleIssues) {
        addKV(issuesEl, iss.role, (iss.issues || []).join(", "));
      }

      // Next steps
      nextEl.innerHTML = "";
      const steps = r.next_steps || [];
      if (!steps.length || (steps.length === 1 && steps[0].includes("Ready to roll"))) {
        const el = document.createElement("div");
        el.style.color = "var(--green)";
        el.textContent = steps[0] || "All good.";
        nextEl.appendChild(el);
      } else {
        for (const s of steps) {
          const el = document.createElement("div");
          el.textContent = s;
          nextEl.appendChild(el);
        }
      }

      localStorage.setItem("karma_models_cache", JSON.stringify({r, t: Date.now()}));
    } catch(_) {
      badge.textContent = "OFFLINE";
      badge.className = "ready-badge not-ready";
      try {
        const c = JSON.parse(localStorage.getItem("karma_models_cache") || "null");
        if (c) {
          checks.innerHTML = "";
          addKV(checks, "Cached at", new Date(c.t).toLocaleTimeString());
        }
      } catch(_) {}
    }
  }

  // -- Memory View --
  async function refreshMemory() {
    try {
      const [memR, factsR, tasksR] = await Promise.all([
        fetch("/api/memory"), fetch("/api/facts"), fetch("/api/tasks")
      ]);
      const mem = await memR.json();
      const facts = await factsR.json();
      const tasks = await tasksR.json();

      const sr = $("#mem-stats");
      sr.innerHTML = "";
      addStat(sr, mem.facts_count || 0, "Facts");
      addStat(sr, mem.episodic_count || 0, "Episodes");
      addStat(sr, mem.tasks_count || 0, "Tasks");
      if (mem.learn_sessions !== undefined) addStat(sr, mem.learn_sessions, "Sessions");

      const fl = $("#facts-list");
      fl.innerHTML = "";
      if (!facts.length) fl.innerHTML = '<div style="color:var(--text2);padding:10px 0">No facts yet</div>';
      for (const f of facts.slice(0, 40)) {
        const conf = typeof f.value === "object" ? (f.value.confidence || 0) : 0;
        const row = document.createElement("div");
        row.className = "item-row";
        const key = document.createElement("span");
        key.className = "item-key";
        key.textContent = f.key;
        const badge = document.createElement("span");
        badge.className = "item-badge" + (conf >= 0.7 ? " high" : "");
        badge.textContent = (conf * 100).toFixed(0) + "%";
        row.appendChild(key);
        row.appendChild(badge);
        fl.appendChild(row);
      }

      const tl = $("#tasks-list");
      tl.innerHTML = "";
      if (!tasks.length) tl.innerHTML = '<div style="color:var(--text2);padding:10px 0">No tasks</div>';
      for (const t of tasks.slice(0, 20)) {
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

      localStorage.setItem("karma_mem_cache", JSON.stringify({mem, facts, tasks, t: Date.now()}));
    } catch(_) {
      try {
        const c = JSON.parse(localStorage.getItem("karma_mem_cache") || "null");
        if (c) {
          const sr = $("#mem-stats");
          sr.innerHTML = '<div class="stat"><div class="stat-val">cached</div><div class="stat-lbl">Offline data</div></div>';
        }
      } catch(_) {}
    }
  }

  // -- System View --
  async function refreshSystem() {
    try {
      const [stR, rtR, mapR, capsR, healthR, tlR] = await Promise.all([
        fetch("/api/state"), fetch("/api/active_runtime"),
        fetch("/api/system-map"), fetch("/api/capabilities"),
        fetch("/api/health"), fetch("/api/timeline")
      ]);
      const state = await stR.json();
      const rt = await rtR.json();
      const sysMap = await mapR.json();
      const caps = await capsR.json();
      const health = await healthR.json();
      const timeline = await tlR.json();

      // Runtime (new: posture, active role/slot/model)
      const rtd = (rt.data || rt);
      const sl = $("#sys-runtime");
      sl.innerHTML = "";
      const posture = rtd.posture || "CALM";
      addKV(sl, "Posture", posture);
      addKV(sl, "Active role", rtd.current_role !== "none" ? rtd.current_role : "—");
      addKV(sl, "Active model", rtd.active_model !== "none" ? rtd.active_model : "—");
      addKV(sl, "Last task", rtd.last_task || "—");
      if (rtd.latest_receipt && rtd.latest_receipt.action) {
        addKV(sl, "Last action", rtd.latest_receipt.action + " (" + (rtd.latest_receipt.status || "?") + ")");
      }
      // Update posture pill in topbar
      const pill = $("#posture-pill");
      if (pill) {
        pill.textContent = posture;
        pill.className = "posture-pill " + posture.toLowerCase();
      }

      // Agent state
      const agentEl = $("#sys-state");
      agentEl.innerHTML = "";
      addKV(agentEl, "Last run", state.last_run || "never");
      addKV(agentEl, "Task", state.current_task || "none");
      const ds = state.decision_summary || {};
      addKV(agentEl, "Decisions", ds.total_decisions || 0);
      addKV(agentEl, "Success", ((ds.success_rate || 0) * 100).toFixed(0) + "%");
      addKV(agentEl, "Confidence", (ds.average_confidence || 0).toFixed(2));

      // System Map
      const sm = $("#sys-map");
      sm.innerHTML = "";
      for (const [k, v] of Object.entries(sysMap)) {
        addKV(sm, k.replace(/_/g, " "), v);
      }

      // Health
      const hl = $("#sys-health");
      hl.innerHTML = "";
      const issues = health.issues || [];
      addKV(hl, "Status", issues.length ? issues.length + " issues" : "Healthy");
      for (const iss of issues.slice(0, 6)) {
        addKV(hl, iss.repair_class || "?", iss.issue || "?");
      }

      // Capabilities
      const cl = $("#sys-caps");
      cl.innerHTML = "";
      for (const cap of caps) {
        const tag = document.createElement("span");
        tag.className = "tag " + (cap.type || "");
        let label = cap.name;
        if (cap.score) label += " " + (cap.score.recent_success_rate * 100).toFixed(0) + "%";
        tag.textContent = label;
        cl.appendChild(tag);
      }

      // Timeline
      const te = $("#sys-timeline");
      te.innerHTML = "";
      if (!timeline.length) te.innerHTML = '<div style="color:var(--text2)">No activity</div>';
      for (const entry of timeline) {
        const row = document.createElement("div");
        row.className = "tl-row";
        row.innerHTML =
          '<span class="tl-dot ' + (entry.success ? "ok" : "fail") + '"></span>' +
          '<span class="tl-time">' + esc(entry.time ? entry.time.slice(11, 16) : "?") + '</span>' +
          '<span class="tl-name">' + esc(entry.intent) + '</span>' +
          '<span class="tl-conf">' + (entry.confidence * 100).toFixed(0) + '%</span>';
        te.appendChild(row);
      }

      localStorage.setItem("karma_sys_cache", JSON.stringify({state, rt: rtd, sysMap, caps, health, timeline, t: Date.now()}));
    } catch(_) {
      try {
        const c = JSON.parse(localStorage.getItem("karma_sys_cache") || "null");
        if (c) {
          const sl = $("#sys-state");
          sl.innerHTML = "";
          addKV(sl, "Status", "Offline (cached)");
          addKV(sl, "Cached at", new Date(c.t).toLocaleTimeString());
        }
      } catch(_) {}
    }
  }

  // -- Helpers --
  function addStat(container, value, label) {
    const el = document.createElement("div");
    el.className = "stat";
    el.innerHTML = '<div class="stat-val">' + esc(String(value)) + '</div><div class="stat-lbl">' + esc(label) + '</div>';
    container.appendChild(el);
  }

  function addKV(container, label, value) {
    const row = document.createElement("div");
    row.className = "kv-row";
    row.innerHTML = '<span class="kv-l">' + esc(label) + '</span><span class="kv-v">' + esc(String(value)) + '</span>';
    container.appendChild(row);
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // -- Startup --
  addMsg("Karma mobile. " + (online ? "Connected." : "Offline mode."), "karma");
  // Pre-fetch models on startup so the badge is ready when user taps Models tab
  if (online) refreshModels();
})();
