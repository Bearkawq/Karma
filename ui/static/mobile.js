// Karma Mobile — offline-first PWA for S25 Plus
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

  // Probe server
  async function probe() {
    try {
      const r = await fetch("/api/log", {method: "GET", cache: "no-store"});
      updateStatus(r.ok);
    } catch(_) {
      updateStatus(false);
    }
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
      // Refresh data
      const t = btn.dataset.tab;
      if (t === "memory") refreshMemory();
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
        try {
          const evt = JSON.parse(e.data);
          handleEvent(evt);
        } catch(_) {}
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

  // Queue for offline commands
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
      // Queue for later
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

  // Flush queue when coming back online
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
      } catch(_) {
        cmdQueue.push(cmd);
      }
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

    if (!online) {
      addMsg("Cannot learn while offline.", "karma error");
      return;
    }

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

      // Cache for offline
      localStorage.setItem("karma_mem_cache", JSON.stringify({mem, facts, tasks, t: Date.now()}));
    } catch(_) {
      // Load from cache
      try {
        const c = JSON.parse(localStorage.getItem("karma_mem_cache") || "null");
        if (c) {
          const sr = $("#mem-stats");
          sr.innerHTML = '<div class="stat"><div class="stat-val">cached</div><div class="stat-lbl">Offline data</div></div>';
        }
      } catch(_) {}
    }
  }

  function addStat(container, value, label) {
    const el = document.createElement("div");
    el.className = "stat";
    el.innerHTML = '<div class="stat-val">' + esc(String(value)) + '</div><div class="stat-lbl">' + esc(label) + '</div>';
    container.appendChild(el);
  }

  // -- System View --
  async function refreshSystem() {
    try {
      const [stR, mapR, capsR, healthR, tlR] = await Promise.all([
        fetch("/api/state"), fetch("/api/system-map"), fetch("/api/capabilities"),
        fetch("/api/health"), fetch("/api/timeline")
      ]);
      const state = await stR.json();
      const sysMap = await mapR.json();
      const caps = await capsR.json();
      const health = await healthR.json();
      const timeline = await tlR.json();

      // State
      const sl = $("#sys-state");
      sl.innerHTML = "";
      addKV(sl, "Last run", state.last_run || "never");
      addKV(sl, "Task", state.current_task || "none");
      const ds = state.decision_summary || {};
      addKV(sl, "Decisions", ds.total_decisions || 0);
      addKV(sl, "Success", ((ds.success_rate || 0) * 100).toFixed(0) + "%");
      addKV(sl, "Confidence", (ds.average_confidence || 0).toFixed(2));

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

      // Cache for offline
      localStorage.setItem("karma_sys_cache", JSON.stringify({state, sysMap, caps, health, timeline, t: Date.now()}));
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
})();
