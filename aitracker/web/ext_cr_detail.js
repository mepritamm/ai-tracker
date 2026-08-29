// cr_detail.js — Control Room detail view (doc 03-detail-view.md).
//
// Namespace: window.CR.detail = { mount(root, ctx), update(state) }.
// No network calls here (contract rule 5) — everything is derived from the
// `session` detail dict the bootstrap already fetched from /api/session
// (aitracker/registry.py:parse_any -> aitracker/providers/claude.py:parse_session
// / aitracker/providers/auggie.py, whichever's return dict, shared shape).
//
// Real detail-dict key paths this file relies on (verified by reading the
// providers, not guessed):
//   meta            aitracker/providers/claude.py:976 {cwd,gitBranch,version,sessionId,
//                   entrypoint,aiTitle,customTitle,model,effort,title}
//                   aitracker/providers/auggie.py:382 {cwd,title,source,entrypoint,gitBranch,model}
//   todos[]         {content,status,activeForm} — aitracker/store.py:67-70 (load_tasks) and
//                   aitracker/providers/claude.py:892-893 (in-transcript TodoWrite fallback).
//                   NO startedAt/endedAt exist on a todo anywhere in the codebase — see the
//                   REQUIRED ADDITION note by spineSegments() below.
//   files[]         {path,ops,last,created,agent?} — aitracker/providers/claude.py:978,964-970
//   reads[]         {path,t} — aitracker/providers/claude.py:979-980
//   commands[]      {id,t,cmd,kind,ok} — aitracker/providers/claude.py:911,931,981 (capped to last 60)
//   commits[]       {t,msg} — aitracker/providers/claude.py:918,982
//   tests[]         same shape as commands, kind==='test' — claude.py:933,983
//   requests[]      {t,text} — user prompts, chronological oldest-first — claude.py:853,984
//   agents[]        {t,type,desc} — Task tool dispatches — claude.py:922-923,985
//   agents_bg[]     {id,aid,wf,task,last,ts,running,tools} — claude.py:537-546,986
//   shells[]        parse_shells() shape, opaque here — claude.py:971,988
//   decisions[]     {t,open,answer,questions:[{q,header,options[]}]} — claude.py:924-929,990
//   waiting         bool — claude.py:993
//   prs[]           {url,repo,num,created,narr,state,t,agent?} — util.py:162-220, claude.py:994
//                   NOTE: no PR title is ever captured (only url/repo/num) — see REQUIRED ADDITION.
//   narrative[]     {t,text} — assistant's own words, newest-first — claude.py:869,995
//                   (server pages this to NARR_PAGE=60 on /api/session — server.py:308-310)
//   tokens          {in,out} — claude.py:997
//   context         {current,limit,pct} — util.py:223-237, claude.py:1000
//   counts          {done,todos,created,edited,read,commits,tests,tests_failed,errors,agents,searches}
//                   claude.py:1001-1009
//   mtime, now      epoch seconds — claude.py:1010-1011
//   notes[]         {text,pushed} — claude.py:1012, store.py:87-96
//   push_when       "turn"|"wake"|"none" — util.py:240-251, claude.py:1015
//   overview        {where,goal,now,now_kind,sofar,commits[]} — overview.py:64-65
//   continued_as / continued_from — fork lineage sid strings, "" when none — registry.py:106-107
//
// Fields the doc assumes but that do NOT exist in the detail dict — flagged as
// REQUIRED ADDITIONs in the final report, not silently invented here:
//   session.pinned, session.open_flags, session.note_count  (only on the LIST dict —
//     registry.py:70-72 all_sessions() — never merged into parse_any()'s per-session detail)
//   todos[].startedAt / todos[].endedAt                     (spineSegments below)
//   a generic "links" array for the Links panel                (deriveLinks below)
//   PR title text                                              (prs[] carries url/repo/num only)
//   terminal pty-attached signal for the Terminal controls panel (GET /api/term/attached,
//     keyed by a `tty` id the session detail dict never carries)
//   a triage-queue position ("1 of 4 needing attention") for the back-line hint

(function () {
  window.CR = window.CR || {};

  var LIVE_WINDOW = 300; // seconds — aitracker/config.py:60, mirrored in aitracker/web/app.js:699

  // ============================== small pure helpers ==============================

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtNum(n) {
    n = Math.round(n || 0);
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function parseT(iso) {
    if (!iso) return null;
    var ms = Date.parse(iso);
    return isNaN(ms) ? null : ms;
  }

  function fmtClock(ms) {
    if (ms == null || isNaN(ms)) return "--:--";
    var d = new Date(ms);
    var h = d.getHours(), m = d.getMinutes();
    return (h < 10 ? "0" + h : h) + ":" + (m < 10 ? "0" + m : m);
  }

  function fmtAge(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    if (sec < 60) return sec + "s";
    if (sec < 3600) return Math.floor(sec / 60) + "m";
    return Math.floor(sec / 3600) + "h " + Math.floor((sec % 3600) / 60) + "m";
  }

  function fmtDurMs(ms) {
    if (ms == null || isNaN(ms)) return "";
    return fmtAge(ms / 1000);
  }

  function initials(title) {
    var words = (title || "").trim().split(/\s+/).filter(Boolean).slice(0, 2);
    return words.map(function (w) { return w[0]; }).join("").toUpperCase() || "??";
  }

  // NOTE: Claude's raw model string ("claude-sonnet-4-5-20250929") isn't the short
  // display name the doc's "model · sonnet" chip wants; this trims to the family name.
  function shortModel(m) {
    if (!m) return "";
    var hit = /sonnet|opus|haiku/i.exec(m);
    return hit ? hit[0].toLowerCase() : m;
  }

  function basename(p) {
    if (!p) return "";
    var parts = String(p).split("/");
    return parts[parts.length - 1] || p;
  }

  function el(html) {
    var t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstChild;
  }

  function qs(root, sel) { return root.querySelector(sel); }
  function qsa(root, sel) { return Array.prototype.slice.call(root.querySelectorAll(sel)); }

  // ============================== localStorage panel state ==============================

  function panelKey(sid, key) { return "cr.detail.panel." + sid + "." + key; }

  function getCollapsed(sid, key, def) {
    try {
      var v = localStorage.getItem(panelKey(sid, key));
      return v === null ? def : v === "1";
    } catch (e) { return def; }
  }

  function setCollapsed(sid, key, val) {
    try { localStorage.setItem(panelKey(sid, key), val ? "1" : "0"); } catch (e) {}
  }

  // ============================== derived / pure logic ==============================

  // Earliest timestamp we can find anywhere in the detail dict — there is no explicit
  // "session started at" field in the shared shape (claude.py tracks t_first internally
  // for build_overview's "41m active" text but never returns it — overview.py:12-17).
  // This is the best honest proxy: earliest of the first prompt, oldest loaded narration,
  // oldest loaded command, oldest commit, oldest decision.
  function firstEventTime(session) {
    var cands = [];
    var reqs = session.requests || [];
    if (reqs.length) cands.push(parseT(reqs[0].t));
    var narr = session.narrative || []; // newest-first
    if (narr.length) cands.push(parseT(narr[narr.length - 1].t));
    var cmds = session.commands || []; // newest-first, capped to last 60
    if (cmds.length) cands.push(parseT(cmds[cmds.length - 1].t));
    var commits = session.commits || []; // newest-first
    if (commits.length) cands.push(parseT(commits[commits.length - 1].t));
    (session.decisions || []).forEach(function (d) {
      var t = parseT(d.t);
      if (t != null) cands.push(t);
    });
    cands = cands.filter(function (x) { return x != null; });
    return cands.length ? Math.min.apply(Math, cands) : null;
  }

  // The progress spine's derived layout. Pure: (session, nowMs) -> plan object.
  //
  // REQUIRED ADDITION: the doc's own pseudocode (spineWidths) assumes
  // todos[i].startedAt / todos[i].endedAt. Neither field is ever written anywhere in
  // this codebase (aitracker/store.py:load_tasks and aitracker/providers/claude.py's
  // in-transcript TodoWrite path both emit only {content,status,activeForm,desc}).
  // This function still honours the doc's algorithm exactly WHEN that data someday
  // shows up (the `hasTimes` branch), and falls back to an honest equal-width split
  // among active/pending todos otherwise — never fabricating a per-todo duration.
  function spineSegments(session, nowMs) {
    var todos = (session.todos || []).filter(function (t) { return t && typeof t === "object"; });
    var total = todos.length;
    var firstMs = firstEventTime(session);
    var elapsedMs = firstMs != null ? Math.max(0, nowMs - firstMs) : null;
    var out = {
      segments: [], markers: [], elapsedMs: elapsedMs, firstMs: firstMs,
      doneCount: 0, runningCount: 0, pendingCount: 0, total: total, ariaLabel: "",
      timeAccurate: false
    };
    if (!total) {
      out.ariaLabel = "Progress: no tasks recorded.";
      out.markers = buildMarkers(session, nowMs, firstMs, elapsedMs);
      return out;
    }

    var doneIdx = [], runIdx = -1, pendIdx = [];
    todos.forEach(function (t, i) {
      if (t.status === "completed") doneIdx.push(i);
      else if (t.status === "in_progress") runIdx = i;
      else pendIdx.push(i);
    });
    out.doneCount = doneIdx.length;
    out.runningCount = runIdx >= 0 ? 1 : 0;
    out.pendingCount = pendIdx.length;

    var FLOOR = 3, MAX_USED = 88, GROUP_THRESHOLD = 16;
    var activeIdx = doneIdx.concat(runIdx >= 0 ? [runIdx] : []);
    var hasTimes = elapsedMs != null && activeIdx.length > 0 &&
      activeIdx.every(function (i) { return !!todos[i].startedAt; });

    var segs = [];
    if (hasTimes) {
      out.timeAccurate = true;
      var spentTotal = 0, spentByIdx = {};
      activeIdx.forEach(function (i) {
        var t = todos[i];
        var started = parseT(t.startedAt);
        var ended = t.endedAt ? parseT(t.endedAt) : nowMs;
        var ms = (started != null && ended != null) ? Math.max(0, ended - started) : 0;
        spentByIdx[i] = ms; spentTotal += ms;
      });
      var usedPct = spentTotal > 0 ? Math.min(MAX_USED, (spentTotal / elapsedMs) * 100) : 0;
      var pendingEach = pendIdx.length ? (100 - usedPct) / pendIdx.length : 0;
      activeIdx.forEach(function (i) {
        var pct = spentTotal > 0 ? (spentByIdx[i] / spentTotal) * usedPct : 0;
        segs.push({ idx: i, kind: i === runIdx ? "running" : "done", widthPct: Math.max(pct, FLOOR),
          elapsedMs: spentByIdx[i], todo: todos[i] });
      });
      pendIdx.forEach(function (i) {
        segs.push({ idx: i, kind: "pending", widthPct: Math.max(pendingEach, FLOOR), todo: todos[i] });
      });
      segs.sort(function (a, b) { return a.idx - b.idx; });
    } else {
      // Fallback: no per-todo timing exists. Equal-width split — never invented precision.
      var usedPct2 = pendIdx.length ? Math.min(MAX_USED, (activeIdx.length / total) * 100) : 100;
      if (!activeIdx.length) usedPct2 = 0;
      var eachActive = activeIdx.length ? usedPct2 / activeIdx.length : 0;
      var eachPending = pendIdx.length ? (100 - usedPct2) / pendIdx.length : 0;
      todos.forEach(function (t, i) {
        if (i === runIdx) segs.push({ idx: i, kind: "running", widthPct: Math.max(eachActive, FLOOR), elapsedMs: null, todo: t });
        else if (t.status === "completed") segs.push({ idx: i, kind: "done", widthPct: Math.max(eachActive, FLOOR), elapsedMs: null, todo: t });
        else segs.push({ idx: i, kind: "pending", widthPct: Math.max(eachPending, FLOOR), todo: t });
      });
    }

    // group a long completed tail into "N earlier" (doc: >~16 todos)
    if (segs.length > GROUP_THRESHOLD) {
      var headDone = [];
      for (var k = 0; k < segs.length; k++) {
        if (segs[k].kind === "done") headDone.push(k); else break;
      }
      if (headDone.length > 4) {
        var groupCount = headDone.length - 3; // keep the 3 most recent done segments visible
        var grouped = segs.slice(0, groupCount);
        var groupedWidth = grouped.reduce(function (s, x) { return s + x.widthPct; }, 0);
        segs = [{ idx: -1, kind: "grouped", widthPct: groupedWidth, count: groupCount,
          label: groupCount + " earlier" }].concat(segs.slice(groupCount));
      }
    }

    var sum = segs.reduce(function (s, x) { return s + x.widthPct; }, 0) || 1;
    segs.forEach(function (s) { s.widthPct = (s.widthPct / sum) * 100; });
    out.segments = segs;
    out.markers = buildMarkers(session, nowMs, firstMs, elapsedMs);

    var failMarker = out.markers.filter(function (m) { return m.kind === "fail"; })[0];
    var askMarker = out.markers.filter(function (m) { return m.kind === "ask"; })[0];
    out.ariaLabel = "Progress: " + out.doneCount + " of " + total + " todos done" +
      (out.runningCount ? ", 1 running" + (out.timeAccurate && segs.some(function (s) { return s.kind === "running"; }) ?
        " for " + fmtDurMs(segs.filter(function (s) { return s.kind === "running"; })[0].elapsedMs) : "") : "") +
      ", " + out.pendingCount + " to go." +
      (failMarker ? " One failure at " + fmtClock(failMarker.t) + "." : "") +
      (askMarker ? " One open question at " + fmtClock(askMarker.t) + "." : "");
    return out;
  }

  function buildMarkers(session, nowMs, firstMs, elapsedMs) {
    var markers = [];
    (session.requests || []).forEach(function (r) {
      var t = parseT(r.t);
      if (t != null) markers.push({ t: t, kind: "prompt", glyph: "💬", label: "",
        title: "Your prompt · " + fmtClock(t) });
    });
    (session.commands || []).forEach(function (c) {
      if (!c.ok) {
        var t = parseT(c.t);
        if (t != null) markers.push({ t: t, kind: "fail", glyph: "", label: "FAIL",
          title: "Failed: " + (c.cmd || "") + " · " + fmtClock(t) });
      }
    });
    (session.decisions || []).forEach(function (d) {
      var t = parseT(d.t);
      if (t != null) markers.push({ t: t, kind: "ask", glyph: "⏳", label: "",
        title: ((d.questions && d.questions[0] && d.questions[0].q) || "Question") + " · " + fmtClock(t) });
    });
    (session.agents_bg || []).forEach(function (a) {
      if (!a.running && a.ts) {
        var t = parseT(a.ts);
        if (t != null) markers.push({ t: t, kind: "agent", glyph: "🤖", label: "",
          title: (a.task || "Background agent") + " finished · " + fmtClock(t) });
      }
    });
    markers.push({ t: nowMs, kind: "now", label: "NOW", title: "Now · " + fmtClock(nowMs) });
    markers.sort(function (a, b) { return a.t - b.t; });
    if (firstMs != null && elapsedMs) {
      markers.forEach(function (m) { m.pct = Math.max(0, Math.min(100, ((m.t - firstMs) / elapsedMs) * 100)); });
      for (var i = 1; i < markers.length; i++) {
        if (Math.abs(markers[i].pct - markers[i - 1].pct) < 2) {
          markers[i].pct = Math.min(100, markers[i - 1].pct + 2);
        }
      }
    } else {
      markers.forEach(function (m) { m.pct = m.kind === "now" ? 100 : 0; });
    }
    return markers;
  }

  // Merges narration + prompts (+ decisions + commands) into one chronological list.
  // Pure: (session) -> [{kind, t, ...}] oldest-first.
  function mergeTimeline(session) {
    var out = [];
    (session.requests || []).forEach(function (r, i) {
      var t = parseT(r.t);
      out.push({ kind: "prompt", t: t == null ? 0 : t, text: r.text, key: "p" + i });
    });
    (session.narrative || []).forEach(function (n, i) { // newest-first in the dict; order fixed by sort below
      var t = parseT(n.t);
      out.push({ kind: "narration", t: t == null ? 0 : t, text: n.text, key: "n" + i });
    });
    (session.decisions || []).forEach(function (d, i) {
      var t = parseT(d.t);
      out.push({ kind: "ask", t: t == null ? 0 : t, decision: d, key: "a" + i });
    });
    (session.commands || []).forEach(function (c, i) {
      var t = parseT(c.t);
      out.push({ kind: c.ok ? "command" : "command-fail", t: t == null ? 0 : t, cmd: c, key: "c" + i });
    });
    out.sort(function (a, b) { return a.t - b.t; });
    return out;
  }

  // Derives the Links panel's two groups from data that DOES exist (prs[], files[]) plus
  // a generic URL scan of narration/prompt/command text.
  //
  // REQUIRED ADDITION: this is a best-effort approximation, not a real parser feature.
  // The parser never records WebFetch calls or a generic "links this session touched"
  // list — only PR urls (util.py:collect_prs, PR-shaped urls only) and local file writes.
  // A `session.links[]` field emitted at the shared seam (mirroring how `prs` is built)
  // would replace this regex scan with something that actually counts WebFetch reads.
  var URL_RE = /https?:\/\/[^\s<>"'()\[\]]+/g;
  function hostOf(url) {
    var m = /^https?:\/\/([^\/]+)/.exec(url);
    return m ? m[1] : "";
  }
  function isLocalHost(h) {
    return /^(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$/.test(h);
  }
  function deriveLinks(session) {
    var map = {};
    function add(url, group, verb, agent, t) {
      url = url.replace(/[)\].,;'"]+$/, "");
      if (!url) return;
      var e = map[url];
      if (!e) { map[url] = { url: url, group: group, verb: verb, agent: !!agent, count: 1, t: t || 0 }; return; }
      e.count++;
      if (group === "generated") e.group = "generated"; // generated beats worked-on
      if (agent) e.agent = true;
      if (t && t > e.t) e.t = t;
    }
    (session.prs || []).forEach(function (p) {
      var t = parseT(p.t);
      if (p.created) add(p.url, "generated", p.state === "merged" ? "merged" : (p.state === "closed" ? "closed" : "created"), p.agent, t);
      else add(p.url, "worked", "cited", p.agent, t);
    });
    (session.files || []).forEach(function (f) {
      if (f.created) add(f.path, "generated", "wrote", f.agent, parseT(f.last));
    });
    var texts = [];
    (session.narrative || []).forEach(function (n) { texts.push([n.text, parseT(n.t)]); });
    (session.requests || []).forEach(function (r) { texts.push([r.text, parseT(r.t)]); });
    (session.commands || []).forEach(function (c) { texts.push([c.cmd, parseT(c.t)]); });
    texts.forEach(function (pair) {
      var text = pair[0], t = pair[1];
      if (!text) return;
      URL_RE.lastIndex = 0;
      var m;
      while ((m = URL_RE.exec(text))) {
        var url = m[0].replace(/[)\].,;'"]+$/, "");
        if (/\/(pull|pull-requests|merge_requests)\/\d+/.test(url)) continue; // handled via prs[] above
        var h = hostOf(url);
        if (isLocalHost(h)) add(url, "generated", "endpoint", false, t);
        else add(url, "worked", "cited", false, t);
      }
    });
    var all = Object.keys(map).map(function (k) { return map[k]; });
    all.forEach(function (e) { if (e.group === "worked" && e.count > 1) e.verb = "read ×" + e.count; });
    var generated = all.filter(function (e) { return e.group === "generated"; }).sort(function (a, b) { return b.t - a.t; });
    var worked = all.filter(function (e) { return e.group === "worked"; }).sort(function (a, b) { return b.t - a.t; });
    return { generated: generated, worked: worked, total: all.length };
  }

  // REQUIRED ADDITION: session.open_flags (unresolved 🚩 count) is only computed inside
  // registry.all_sessions() for the board list (registry.py:70-72) and never merged into
  // parse_any()'s per-session detail dict — so the header's state pill can't see flags
  // without that count. Treated as unknown (falsy) here.
  function stateOf(session, nowSec) {
    var idle = nowSec - (session.mtime || 0);
    var live = idle < LIVE_WINDOW;
    var openFlags = session.open_flags || 0;
    var running = (session.agents_bg || []).some(function (a) { return a.running; });
    var inProgress = (session.todos || []).some(function (t) { return t.status === "in_progress"; });
    var failing = session.counts && (session.counts.errors > 0 || session.counts.tests_failed > 0);
    if (session.waiting) return { word: "Waiting on you", cls: "awaiting", age: fmtAge(idle) };
    if (openFlags) return { word: openFlags + " flag" + (openFlags === 1 ? "" : "s") + " open", cls: "flagged" };
    if (failing) return { word: "Failing", cls: "failed" };
    if (live && (running || inProgress)) return { word: "Working", cls: "working" };
    if (live) return { word: "Landed", cls: "done" };
    return { word: "Idle", cls: "idle", age: fmtAge(idle) };
  }

  function statChips(session) {
    var c = session.counts || {};
    var tokTotal = ((session.tokens && session.tokens.in) || 0) + ((session.tokens && session.tokens.out) || 0);
    return [
      { label: "files", value: (session.files || []).length },
      // NOTE: `commands` is capped to the last 60 by the parser (claude.py:981,
      // auggie.py:391) — there is no separate "total commands ever run" counter, so
      // this chip reads the same cap the panel does rather than a fabricated total.
      { label: "commands", value: (session.commands || []).length },
      { label: "reads", value: (session.reads || []).length },
      { label: "commits", value: c.commits || 0 },
      { label: "tests", value: c.tests ? (c.tests + (c.tests_failed ? " failing" : "")) : "--", failing: !!c.tests_failed },
      { label: "tokens", value: tokTotal ? fmtNum(tokTotal) : "--" },
      { label: "branch", value: (session.meta && session.meta.gitBranch) || "--" }
    ];
  }

  // NOTE: no field in the shared shape says "this provider's transcript is unreadable".
  // Approximated from meta.source/meta.entrypoint containing "augment" but not "auggie"
  // (Auggie IS readable; the VSCode/Cursor extension providers are the degraded ones —
  // see aitracker/registry.py:3, AugmentVscodeProvider/AugmentCursorProvider).
  function isDegradedTranscript(session) {
    var src = ((session.meta && (session.meta.source || session.meta.entrypoint)) || "").toLowerCase();
    return /augment/.test(src) && !/auggie/.test(src);
  }

  // ============================== rendering ==============================

  function svgIcon(ctx, name, fallback) {
    try {
      var s = ctx && ctx.icon && ctx.icon(name);
      if (s) return s;
    } catch (e) {}
    return fallback || "";
  }

  function makePanel(ctx, sid, col, key, title, opts) {
    opts = opts || {};
    var defCollapsed = opts.defaultCollapsed !== false;
    var collapsed = getCollapsed(sid, key, defCollapsed);
    var wrap = el(
      '<section class="crd-panel' + (opts.tint ? " crd-tint-" + opts.tint : "") + '"' +
      ' data-panel="' + esc(key) + '">' +
      '<header class="crd-panel-head" data-act="toggle-panel" data-panel="' + esc(key) + '" data-col="' + esc(col) + '">' +
      '<span class="crd-chevron">' + (collapsed ? "▸" : "▾") + "</span>" +
      '<span class="crd-panel-label">' + esc(title) + "</span>" +
      '<span class="crd-panel-count"></span>' +
      "</header>" +
      '<div class="crd-panel-body"></div>' +
      "</section>"
    );
    wrap.classList.toggle("is-collapsed", collapsed);
    return wrap;
  }

  function setPanelCollapsed(wrap, sid, val) {
    var key = wrap.getAttribute("data-panel");
    wrap.classList.toggle("is-collapsed", val);
    qs(wrap, ".crd-chevron").textContent = val ? "▸" : "▾";
    setCollapsed(sid, key, val);
  }

  function setPanelCount(wrap, text) {
    qs(wrap, ".crd-panel-count").innerHTML = text || "";
  }

  function setPanelBody(wrap, html) {
    qs(wrap, ".crd-panel-body").innerHTML = html;
  }

  // ---- skeleton ----

  var SKELETON =
    '<div class="crd">' +
      '<div class="crd-backline">' +
        '<button class="crd-back" data-act="back">‹ Back to the board</button>' +
        '<span class="crd-back-hint mono"></span>' +
      "</div>" +
      '<div class="crd-header">' +
        '<div class="crd-id">' +
          '<div class="crd-id-row1">' +
            '<span class="crd-src"></span>' +
            '<span class="crd-div"></span>' +
            '<span class="crd-metaline mono"></span>' +
            '<span class="crd-pill crd-pill-state"></span>' +
            '<span class="crd-pill crd-pill-agents" hidden></span>' +
          "</div>" +
          '<div class="crd-id-row2">' +
            '<h1 class="crd-goal"></h1>' +
            '<button class="crd-rename" data-act="rename" title="Rename" aria-label="Rename session"></button>' +
            '<span class="crd-pill crd-pill-pinned" hidden>📌 Pinned</span>' +
          "</div>" +
          '<div class="crd-chips"></div>' +
        "</div>" +
        '<div class="crd-actions">' +
          '<div class="crd-actions-row1">' +
            '<button class="crd-btn crd-pillbtn" data-act="toggle-search">' +
              '<span class="crd-ico"></span>Search this session</button>' +
            '<button class="crd-btn crd-pillbtn crd-flagbtn" data-act="toggle-flag">' +
              '<span class="crd-ico"></span><span class="crd-flag-label">Flag an issue</span></button>' +
          "</div>" +
          '<div class="crd-actions-row2">' +
            '<button class="crd-btn crd-btn-solid" data-act="open-terminal">Open terminal</button>' +
            '<button class="crd-btn crd-btn-outline" data-act="resume">Resume here</button>' +
            '<button class="crd-btn crd-btn-bare" data-act="external" hidden>External</button>' +
          "</div>" +
        "</div>" +
      "</div>" +
      '<div class="crd-card crd-searchcard" hidden>' +
        '<input class="crd-search-input" type="text" placeholder="Search this session…">' +
        '<div class="crd-search-results"></div>' +
      "</div>" +
      '<div class="crd-card crd-flagcard" hidden>' +
        '<div class="crd-flag-count mono"></div>' +
        '<textarea class="crd-flag-input" rows="2" placeholder="What needs a second look?"></textarea>' +
        '<div class="crd-flag-row">' +
          '<span class="crd-flag-note">View-only — this creates a flag entry; the tracker never writes to the session.</span>' +
          '<button class="crd-btn crd-btn-solid" data-act="submit-flag">Flag it</button>' +
        "</div>" +
      "</div>" +
      '<div class="crd-forkbanner" hidden>' +
        '<span class="crd-ico crd-fork-ico"></span>' +
        '<span class="crd-fork-text"></span>' +
        '<button class="crd-fork-link" data-act="fork-open"></button>' +
      "</div>" +
      '<div class="crd-spine" role="img">' +
        '<div class="crd-spine-head">' +
          '<span class="crd-spine-chevron">▾</span>' +
          '<span class="crd-spine-label">PROGRESS SPINE</span>' +
          '<span class="crd-spine-count mono"></span>' +
          '<span class="crd-spine-hint mono">segment width = time actually spent · click to jump the chat there</span>' +
        "</div>" +
        '<div class="crd-spine-bar"></div>' +
        '<div class="crd-spine-gutter"></div>' +
        '<div class="crd-spine-foot mono">' +
          '<span class="crd-spine-first"></span>' +
          '<span class="crd-spine-mid"></span>' +
          '<span class="crd-spine-now"></span>' +
        "</div>" +
      "</div>" +
      '<div class="crd-columns">' +
        '<div class="crd-col crd-col-state">' +
          '<div class="crd-col-eyebrow">State' +
            '<span class="crd-colbtns">' +
              '<button data-act="expand-all" data-col="state">Expand all</button>' +
              '<button data-act="collapse-all" data-col="state">Collapse all</button>' +
            "</span></div>" +
          '<div class="crd-col-body"></div>' +
        "</div>" +
        '<div class="crd-col crd-col-convo">' +
          '<div class="crd-col-eyebrow">Conversation' +
            '<span class="crd-marker" title="Narration is the assistant’s own text, interleaved with your prompts in one timeline">Its own words</span>' +
            '<span class="crd-convonav">' +
              '<button data-act="convo-prev">‹ prev</button>' +
              '<button data-act="convo-next">next ›</button>' +
              '<button data-act="convo-latest">⤒ latest</button>' +
            "</span></div>" +
          '<div class="crd-col-body"></div>' +
        "</div>" +
        '<div class="crd-col crd-col-evidence">' +
          '<div class="crd-col-eyebrow">Evidence' +
            '<span class="crd-colbtns">' +
              '<button data-act="expand-all" data-col="evidence">Expand all</button>' +
              '<button data-act="collapse-all" data-col="evidence">Collapse all</button>' +
            "</span></div>" +
          '<div class="crd-col-body"></div>' +
        "</div>" +
      "</div>" +
      '<div class="crd-phonebar">' +
        '<input class="crd-phone-input" type="text" placeholder="Queue a note…">' +
        '<button class="crd-phone-send" data-act="phone-send" aria-label="Send"></button>' +
        '<button class="crd-phone-stop" data-act="phone-stop" aria-label="Stop" disabled ' +
          'title="Not available yet — there’s no server route to stop a running session.">■</button>' +
      "</div>" +
    "</div>";

  var STATE_PANELS = [
    ["decisions", "Decisions & open questions"],
    ["prs", "Pull requests"],
    ["links", "Links"],
    ["summary", "Session summary"],
    ["plan", "Plan on the go"]
  ];
  var EVIDENCE_PANELS = [
    ["files", "Files"],
    ["commands", "Commands"],
    ["agents", "Agents & shells"],
    ["run", "Run a command"],
    ["terminal", "Terminal controls"]
  ];

  function Detail() {}

  Detail.prototype.mount = function (root, ctx) {
    root.innerHTML = "";
    var node = el(SKELETON);
    root.appendChild(node);

    var ui = {
      sid: null,
      panels: {}, // key -> wrap element
      timelineSeen: 0,
      timelineStuckBottom: true,
      timelineFilter: "all",
      agentsShowFinished: false,
      searchOpen: false,
      flagOpen: false
    };

    var stateBody = qs(node, ".crd-col-state .crd-col-body");
    var evidenceBody = qs(node, ".crd-col-evidence .crd-col-body");
    var convoBody = qs(node, ".crd-col-convo .crd-col-body");

    STATE_PANELS.forEach(function (p) {
      var opts = {};
      if (p[0] === "plan") opts.tint = "note";
      var wrap = makePanel(ctx, "_", "state", p[0], p[1], opts);
      stateBody.appendChild(wrap);
      ui.panels[p[0]] = wrap;
    });
    EVIDENCE_PANELS.forEach(function (p) {
      var wrap = makePanel(ctx, "_", "evidence", p[0], p[1]);
      evidenceBody.appendChild(wrap);
      ui.panels[p[0]] = wrap;
    });

    // Conversation timeline: single panel, starts expanded (doc: the only exception).
    var timelineWrap = el(
      '<section class="crd-panel crd-timeline-panel" data-panel="timeline">' +
        '<header class="crd-panel-head" data-act="toggle-panel" data-panel="timeline" data-col="convo">' +
          '<span class="crd-chevron">▾</span>' +
          '<span class="crd-panel-label">TIMELINE</span>' +
          '<span class="crd-timeline-legend mono">prompts · narration · tools · results</span>' +
          '<span class="crd-timeline-filters">' +
            '<button class="is-active" data-act="timeline-filter" data-mode="all">all</button>' +
            '<button data-act="timeline-filter" data-mode="talk">talk only</button>' +
          "</span>" +
        "</header>" +
        '<div class="crd-panel-body">' +
          '<div class="crd-timeline-scroll"></div>' +
          '<div class="crd-timeline-foot mono">older turns page in as you scroll — history is unbounded</div>' +
        "</div>" +
      "</section>"
    );
    convoBody.appendChild(timelineWrap);
    ui.panels.timeline = timelineWrap;

    var scrollEl = qs(timelineWrap, ".crd-timeline-scroll");
    scrollEl.addEventListener("scroll", function () {
      var atBottom = scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 40;
      ui.timelineStuckBottom = atBottom;
    });

    // ---- single delegated click handler ----
    node.addEventListener("click", function (ev) {
      var t = ev.target.closest("[data-act]");
      if (!t) return;
      var act = t.getAttribute("data-act");
      var sid = ui.sid;
      switch (act) {
        case "back":
          ctx.go("board");
          break;
        case "toggle-panel": {
          var key = t.getAttribute("data-panel");
          var wrap = ui.panels[key];
          if (!wrap) return;
          setPanelCollapsed(wrap, sid, !wrap.classList.contains("is-collapsed"));
          break;
        }
        case "expand-all":
        case "collapse-all": {
          var col = t.getAttribute("data-col");
          var list = col === "state" ? STATE_PANELS : EVIDENCE_PANELS;
          var val = act === "collapse-all";
          list.forEach(function (p) { setPanelCollapsed(ui.panels[p[0]], sid, val); });
          break;
        }
        case "rename":
          // NOTE: dialog name/shape follows the lowercase-hyphenated convention already
          // established by aitracker/web/cr_term.js (ctx.dialog("model", …), ("effort", …),
          // ("fork-lineage", …)) rather than the camelCase names this file first guessed.
          ctx.dialog("rename", { sessionId: sid, currentTitle: ui.lastTitle || "" });
          break;
        case "toggle-search":
          ui.searchOpen = !ui.searchOpen;
          qs(node, ".crd-searchcard").hidden = !ui.searchOpen;
          if (ui.searchOpen) qs(node, ".crd-search-input").focus();
          break;
        case "toggle-flag":
          ui.flagOpen = !ui.flagOpen;
          qs(node, ".crd-flagcard").hidden = !ui.flagOpen;
          break;
        case "submit-flag": {
          var note = qs(node, ".crd-flag-input").value.trim();
          if (!note) return;
          ctx.emit("cr:flag-create", { sessionId: sid, note: note, context: (ui.lastGoal || "") });
          qs(node, ".crd-flag-input").value = "";
          ui.flagOpen = false;
          qs(node, ".crd-flagcard").hidden = true;
          break;
        }
        case "open-terminal":
          // NOTE: 'terminal:open' + {id} is the EXACT event/payload aitracker/web/cr_board.js
          // already emits for its own "open terminal" tile action (cr_board.js:737,812) —
          // reused verbatim instead of inventing a second event for the same action.
          ctx.emit("terminal:open", { id: sid });
          break;
        case "resume":
          // REQUIRED ADDITION: no existing sibling event covers "resume this session in a
          // terminal" (cr_board.js only has terminal:open, which cr_term.js treats as "attach/
          // open a pty", not "run `claude --resume <sid>`"). Named to match the session:* /
          // terminal:* namespaces already in use; the bootstrap needs to wire this one up.
          ctx.emit("session:resume", { id: sid });
          break;
        case "external":
          // REQUIRED ADDITION: the external URL needs the bound port (aitracker/config.py's
          // PORT_FILE), which the detail dict never carries — the bootstrap must resolve it.
          ctx.emit("session:openExternal", { id: sid });
          break;
        case "fork-open":
          if (ui.forkTarget) ctx.go("detail", ui.forkTarget);
          break;
        case "spine-segment": {
          var idx = parseInt(t.getAttribute("data-idx"), 10);
          scrollTimelineToTodo(node, ui, idx);
          break;
        }
        case "timeline-filter": {
          ui.timelineFilter = t.getAttribute("data-mode");
          qsa(timelineWrap, ".crd-timeline-filters button").forEach(function (b) {
            b.classList.toggle("is-active", b === t);
          });
          renderTimelineEntries(scrollEl, ui, ui.lastSession, true);
          break;
        }
        case "convo-latest":
          ui.timelineStuckBottom = true;
          scrollEl.scrollTop = scrollEl.scrollHeight;
          break;
        case "convo-prev":
          jumpPrompt(scrollEl, -1);
          break;
        case "convo-next":
          jumpPrompt(scrollEl, 1);
          break;
        case "note-copy": {
          var idx2 = parseInt(t.getAttribute("data-idx"), 10);
          var n = (ui.lastSession && ui.lastSession.notes || [])[idx2];
          if (n && navigator.clipboard) navigator.clipboard.writeText(n.text || "").catch(function () {});
          break;
        }
        case "note-remove":
          ctx.emit("cr:note-remove", { sessionId: sid, index: parseInt(t.getAttribute("data-idx"), 10) });
          break;
        case "note-push": {
          var input = qs(node, ".crd-plan-input");
          var text = input && input.value.trim();
          if (!text) return;
          ctx.emit("cr:note-push", { sessionId: sid, text: text });
          input.value = "";
          break;
        }
        case "file-row":
          ctx.dialog("file-diff", { sessionId: sid, path: t.getAttribute("data-path") });
          break;
        case "command-row":
          ctx.dialog("command-output", { sessionId: sid, cmdId: t.getAttribute("data-id") });
          break;
        case "agents-show-finished":
          ui.agentsShowFinished = !ui.agentsShowFinished;
          renderAgentsPanel(ui.panels.agents, ui, ui.lastSession);
          break;
        case "agent-open":
          ctx.dialog("agent-transcript", { sessionId: sid, agentId: t.getAttribute("data-id") });
          break;
        case "shell-open":
          ctx.dialog("shell-tail", { sessionId: sid, shellId: t.getAttribute("data-id") });
          break;
        case "run-submit": {
          var argvInput = qs(node, ".crd-run-input");
          var argv = argvInput && argvInput.value.trim();
          if (!argv) return;
          ctx.emit("cr:run-command", { sessionId: sid, argv: argv });
          break;
        }
        case "terminal-model":
        case "terminal-effort":
          // REQUIRED ADDITION: aitracker/web/cr_term.js's own model/effort dialogs
          // (ctx.dialog("model", {current, ladder, onPick}), cr_term.js:594-607) are driven
          // by that module's live pty state (the ladder + the /api/term/inject callback) —
          // data this read-only detail panel doesn't have. Emitting a request instead of
          // fabricating a ladder/onPick the bootstrap would have to fill in anyway; whichever
          // module owns the attached pty for this session should open its own "model"/"effort"
          // dialog in response.
          ctx.emit("cr:term-controls-request", { sessionId: sid, control: act === "terminal-model" ? "model" : "effort" });
          break;
        case "phone-send": {
          var pInput = qs(node, ".crd-phone-input");
          var pText = pInput && pInput.value.trim();
          if (!pText) return;
          ctx.emit("cr:note-push", { sessionId: sid, text: pText });
          pInput.value = "";
          break;
        }
        case "phone-stop":
          ctx.emit("cr:stop", { sessionId: sid });
          break;
      }
    });

    qs(node, ".crd-search-input").addEventListener("input", function (ev) {
      renderSearchResults(node, ui, ev.target.value);
    });

    root._crDetail = { node: node, ui: ui };
  };

  function jumpPrompt(scrollEl, dir) {
    var bubbles = qsa(scrollEl, ".crd-entry-prompt");
    if (!bubbles.length) return;
    var rectTop = scrollEl.getBoundingClientRect().top;
    var idx = 0;
    for (var i = 0; i < bubbles.length; i++) {
      if (bubbles[i].getBoundingClientRect().top - rectTop > 4) { idx = i; break; }
      idx = i;
    }
    var target = bubbles[Math.max(0, Math.min(bubbles.length - 1, idx + dir))];
    if (target) target.scrollIntoView({ block: "center" });
  }

  function scrollTimelineToTodo(node, ui, idx) {
    var todo = (ui.lastSession && ui.lastSession.todos || [])[idx];
    if (!todo) return;
    var scrollEl = qs(node, ".crd-timeline-scroll");
    var match = qsa(scrollEl, "[data-todo-text]").filter(function (e) {
      return e.getAttribute("data-todo-text") === (todo.content || "");
    })[0];
    if (match) match.scrollIntoView({ block: "center" });
  }

  // ---- update ----
  // update() is called on the CR.detail object with (state) — see below, implemented
  // as free functions closing over the mounted node via root._crDetail.

  var singleton = new Detail();

  window.CR.detail = {
    mount: function (root, ctx) {
      this._root = root;
      this._ctx = ctx;
      singleton.mount(root, ctx);
    },
    update: function (state) {
      renderUpdate(this._root, this._ctx, state);
    }
  };

  function renderUpdate(root, ctx, state) {
    if (!root || !root._crDetail) return;
    var node = root._crDetail.node;
    var ui = root._crDetail.ui;
    var session = state && state.session;
    if (!session) return;
    var nowSec = state.now || Math.floor(Date.now() / 1000);
    var nowMs = nowSec * 1000;
    var sid = (session.meta && session.meta.sessionId) || session.id || ui.sid || "unknown";
    var firstMount = ui.sid == null;
    ui.sid = sid;
    ui.lastSession = session;
    ui.lastTitle = (session.meta && session.meta.title) || "";
    ui.lastGoal = (session.overview && session.overview.goal) || ui.lastTitle;

    // panel keys are localStorage-scoped per session; rebind on first sight of a session id
    if (firstMount || ui._boundSid !== sid) {
      ui._boundSid = sid;
      Object.keys(ui.panels).forEach(function (key) {
        var wrap = ui.panels[key];
        var def = key === "timeline" ? false : true;
        var collapsed = getCollapsed(sid, key, def);
        setPanelCollapsed(wrap, sid, collapsed);
      });
    }

    renderBackline(node, session, state);
    renderHeader(node, ctx, session, nowSec);
    renderForkBanner(node, ctx, session, ui);
    renderSpine(node, ctx, session, nowMs);

    renderDecisions(ui.panels.decisions, session);
    renderPRs(ui.panels.prs, session);
    renderLinks(ui.panels.links, session);
    renderSummary(ui.panels.summary, session);
    renderPlan(ui.panels.plan, ctx, session);

    renderFiles(ui.panels.files, session);
    renderCommands(ui.panels.commands, session);
    renderAgentsPanel(ui.panels.agents, ui, session);
    renderRunPanel(ui.panels.run, session);
    renderTerminalPanel(ui.panels.terminal, session);

    renderTimeline(node, ui, session);
  }

  function renderBackline(node, session, state) {
    var hint = qs(node, ".crd-back-hint");
    // REQUIRED ADDITION: no triage-queue position (e.g. "1 of 4 needing attention") is
    // available on the detail dict or via ctx — hidden rather than fabricated.
    if (state && state.triage && state.triage.total) {
      hint.hidden = false;
      hint.textContent = state.triage.index + " of " + state.triage.total +
        " needing attention · j / k to move between them";
    } else {
      hint.hidden = true;
      hint.textContent = "";
    }
  }

  function renderHeader(node, ctx, session, nowSec) {
    var meta = session.meta || {};
    var src = /auggie/i.test(meta.source || meta.entrypoint || "") ? "Auggie" :
      (/augment/i.test(meta.source || meta.entrypoint || "") ? "Augment" : "Claude CLI");
    qs(node, ".crd-src").textContent = src;

    var proj = basename(meta.cwd || "");
    var idleSec = nowSec - (session.mtime || 0);
    var span = fmtAge(idleSec);
    var metaBits = [proj || "--", meta.cwd || "--", meta.title || "--", span + " ago"].filter(Boolean);
    qs(node, ".crd-metaline").textContent = metaBits.join(" · ");

    var st = stateOf(session, nowSec);
    var pill = qs(node, ".crd-pill-state");
    pill.className = "crd-pill crd-pill-state crd-state-" + st.cls;
    var glyph = st.cls === "awaiting" ? "⏳ " : (st.cls === "failed" ? "" : (st.cls === "done" ? "✅ " : ""));
    pill.textContent = glyph + st.word + (st.age ? " · " + st.age : "");

    var agentsRunning = (session.agents_bg || []).filter(function (a) { return a.running; }).length;
    var agentsPill = qs(node, ".crd-pill-agents");
    if (agentsRunning) {
      agentsPill.hidden = false;
      agentsPill.textContent = agentsRunning + " agent" + (agentsRunning === 1 ? "" : "s") + " running";
    } else {
      agentsPill.hidden = true;
    }

    var goal = (session.overview && session.overview.goal) || meta.title || "(untitled session)";
    qs(node, ".crd-goal").textContent = goal;
    qs(node, ".crd-rename").innerHTML = svgIcon(ctx, "edit", "✎");

    // REQUIRED ADDITION: session.pinned is only present on the board-list dict
    // (registry.py:70), never on parse_any()'s detail dict — hidden unless the
    // bootstrap starts forwarding it.
    qs(node, ".crd-pill-pinned").hidden = !session.pinned;

    var chips = statChips(session);
    qs(node, ".crd-chips").innerHTML = chips.map(function (c) {
      var failCls = c.failing ? " crd-chip-failing" : "";
      return '<span class="crd-chip' + failCls + '"><span class="crd-chip-label">' + esc(c.label) +
        "</span> " + esc(c.value) + "</span>";
    }).join("");

    var icoEls = qsa(node, ".crd-pillbtn .crd-ico");
    if (icoEls[0]) icoEls[0].innerHTML = svgIcon(ctx, "search", "⌕");
    if (icoEls[1]) icoEls[1].innerHTML = svgIcon(ctx, "alert", "⚠");

    // REQUIRED ADDITION: session.open_flags (unresolved-flag count) is not on the
    // detail dict (see stateOf's note above) — shows "—" rather than a fabricated 0.
    var flagCount = session.open_flags;
    qs(node, ".crd-flag-label").textContent = "Flag an issue" + (flagCount ? " · " + flagCount : "");
    qs(node, ".crd-flagcard .crd-flag-count").textContent = flagCount ?
      flagCount + " open flag" + (flagCount === 1 ? "" : "s") + " on this session" :
      "Open-flag count needs the board's flag store wired into this view (not yet on /api/session).";

    var isLocalhost = /^(localhost|127\.0\.0\.1)/.test(location.hostname);
    qs(node, '[data-act="external"]').hidden = !isLocalhost;
  }

  function renderForkBanner(node, ctx, session, ui) {
    var banner = qs(node, ".crd-forkbanner");
    if (session.continued_as) {
      banner.hidden = false;
      qs(banner, ".crd-fork-ico").innerHTML = svgIcon(ctx, "branch", "⑂");
      qs(banner, ".crd-fork-text").textContent =
        "This session continued as a fresh copy — the original kept running as a background agent.";
      qs(banner, ".crd-fork-link").textContent = "Open the copy";
      ui.forkTarget = session.continued_as;
    } else if (session.continued_from) {
      banner.hidden = false;
      qs(banner, ".crd-fork-ico").innerHTML = svgIcon(ctx, "branch", "⑂");
      qs(banner, ".crd-fork-text").textContent =
        "Resume was refused — this session was running as a background agent, so it was forked. " +
        "You're looking at the copy; the original is still running.";
      qs(banner, ".crd-fork-link").textContent = "Open the original";
      ui.forkTarget = session.continued_from;
    } else {
      banner.hidden = true;
      ui.forkTarget = null;
    }
  }

  function renderSpine(node, ctx, session, nowMs) {
    var plan = spineSegments(session, nowMs);
    var doneN = plan.doneCount, total = plan.total;
    qs(node, ".crd-spine-count").textContent = doneN + " of " + total +
      (plan.elapsedMs != null ? " · " + fmtDurMs(plan.elapsedMs) + " elapsed" : "");

    var bar = qs(node, ".crd-spine-bar");
    bar.innerHTML = plan.segments.map(function (s, i) {
      var isFirst = i === 0, isLast = i === plan.segments.length - 1;
      var radiusCls = (isFirst ? " crd-seg-first" : "") + (isLast ? " crd-seg-last" : "");
      var title = s.kind === "grouped" ? s.label :
        (s.todo ? (s.todo.content || s.todo.activeForm || "") + " · " +
          (s.kind === "pending" ? "not started" : (s.elapsedMs != null ? fmtDurMs(s.elapsedMs) : s.kind)) : "");
      var inner = "";
      if (s.kind === "done" && s.widthPct >= 7 && s.elapsedMs != null) {
        inner = '<span class="crd-seg-elapsed mono">' + esc(fmtDurMs(s.elapsedMs)) + "</span>";
      } else if (s.kind === "running") {
        inner = '<span class="crd-seg-dot"></span><span class="crd-seg-running mono">RUNNING' +
          (s.elapsedMs != null ? " " + esc(fmtDurMs(s.elapsedMs)) : "") + "</span>" +
          '<span class="crd-seg-edge"></span>';
      } else if (s.kind === "grouped") {
        inner = '<span class="crd-seg-grouped mono">' + esc(s.label) + "</span>";
      }
      return '<button class="crd-seg crd-seg-' + s.kind + radiusCls + '" style="flex-basis:' + s.widthPct.toFixed(3) +
        '%" data-act="spine-segment" data-idx="' + s.idx + '" title="' + esc(title) + '">' + inner + "</button>";
    }).join("");

    var gutter = qs(node, ".crd-spine-gutter");
    gutter.innerHTML = plan.markers.map(function (m) {
      var cls = "crd-mark crd-mark-" + m.kind;
      var content = m.kind === "fail" ? '<span class="crd-mark-word mono">FAIL</span>' :
        (m.kind === "now" ? '<span class="crd-mark-word mono">NOW</span>' :
        (m.glyph ? '<span class="crd-mark-emoji" aria-hidden="true">' + m.glyph + "</span>" : ""));
      return '<span class="' + cls + '" style="left:' + m.pct.toFixed(3) + '%" title="' + esc(m.title) + '">' +
        '<span class="crd-mark-tick"></span>' + content + "</span>";
    }).join("");

    qs(node, ".crd-spine-first").textContent = plan.firstMs != null ? fmtClock(plan.firstMs) + " first prompt" : "—";
    qs(node, ".crd-spine-mid").textContent = plan.doneCount + " done · " + plan.runningCount +
      " running · " + plan.pendingCount + " to go";
    qs(node, ".crd-spine-now").textContent = fmtClock(nowMs) + " now";

    qs(node, ".crd-spine").setAttribute("aria-label", plan.ariaLabel);
  }

  // ---- State column panels ----

  function renderDecisions(wrap, session) {
    var decisions = session.decisions || [];
    var open = decisions.filter(function (d) { return d.open; });
    var closed = decisions.filter(function (d) { return !d.open; });
    setPanelCount(wrap, open.length ? open.length + " open" : (decisions.length ? "0 open" : "—"));
    wrap.classList.toggle("crd-tint-awaiting", open.length > 0);

    function renderQ(d, isOpen) {
      var q0 = (d.questions && d.questions[0]) || { q: "", options: [] };
      var opts = (q0.options || []).map(function (o) {
        return '<div class="crd-decision-opt">' + esc(o) + "</div>";
      }).join("");
      var answer = !isOpen && d.answer ? '<div class="crd-decision-answer">Decided: ' + esc(d.answer) + "</div>" : "";
      return '<div class="crd-decision' + (isOpen ? " is-open" : "") + '">' +
        '<div class="crd-decision-q">' + esc(q0.q) + "</div>" +
        (isOpen ? opts : "") + answer + "</div>";
    }

    var html = "";
    if (open.length) html += open.map(function (d) { return renderQ(d, true); }).join("");
    if (open.length) {
      html += '<div class="crd-decision-footrule">View-only — answer in the session itself. ' +
        "The tracker never writes to it.</div>";
    }
    if (closed.length) {
      html += '<div class="crd-decision-divider">Decided earlier</div>' +
        closed.map(function (d) { return renderQ(d, false); }).join("");
    }
    if (!open.length && !closed.length) html = '<div class="crd-empty">No decisions recorded yet.</div>';
    setPanelBody(wrap, html);
  }

  function renderPRs(wrap, session) {
    var prs = session.prs || [];
    setPanelCount(wrap, prs.length || "—");
    if (!prs.length) { setPanelBody(wrap, '<div class="crd-empty">No pull requests yet.</div>'); return; }
    setPanelBody(wrap, prs.map(function (p) {
      var state = p.state === "merged" ? "merged" : (p.state === "closed" ? "closed" : "open");
      // NOTE: the parser never captures a PR's real title (util.py:collect_prs only
      // regex-extracts url/repo/num) — repo/num stands in for it. See REQUIRED ADDITION.
      var label = "#" + esc(p.num || "?") + " · " + esc(p.repo || p.url);
      return '<a class="crd-pr-row" href="' + esc(p.url) + '" target="_blank" rel="noopener">' +
        '<span class="crd-pr-title">' + label + "</span>" +
        (p.agent ? '<span class="crd-tag-agent">agent</span>' : "") +
        '<span class="crd-pr-state crd-pr-' + state + '">' + state + "</span>" +
        "</a>";
    }).join(""));
  }

  function renderLinks(wrap, session) {
    var links = deriveLinks(session);
    setPanelCount(wrap, links.total || "—");
    if (!links.total) { setPanelBody(wrap, '<div class="crd-empty">No links recorded yet.</div>'); return; }
    function row(e) {
      return '<div class="crd-link-row"><a href="' + esc(e.url) + '" target="_blank" rel="noopener" class="crd-link-url mono">' +
        esc(e.url) + "</a>" + (e.agent ? '<span class="crd-tag-agent">agent</span>' : "") +
        '<span class="crd-link-verb">' + esc(e.verb) + "</span></div>";
    }
    var html = "";
    if (links.generated.length) {
      html += '<div class="crd-link-group crd-link-generated"><span>GENERATED HERE</span><span>' +
        links.generated.length + "</span></div>" + links.generated.map(row).join("");
    }
    if (links.worked.length) {
      html += '<div class="crd-link-group crd-link-worked"><span>WORKED ON</span><span>' +
        links.worked.length + " · referenced or fetched</span></div>" + links.worked.map(row).join("");
    }
    html += '<div class="crd-link-footnote">Generated = the session created it. Worked on = it ' +
      "appeared in a tool result or the narration.</div>";
    setPanelBody(wrap, html);
  }

  function renderSummary(wrap, session) {
    var ov = session.overview || {};
    setPanelCount(wrap, "");
    setPanelBody(wrap,
      '<div class="crd-summary-field"><div class="crd-summary-label">Goal</div>' +
      '<div class="crd-summary-body">' + esc(ov.goal || "—") + "</div></div>" +
      '<div class="crd-summary-field"><div class="crd-summary-label">Now</div>' +
      '<div class="crd-summary-body crd-summary-now">' + esc(ov.now || "—") + "</div></div>" +
      '<div class="crd-summary-field"><div class="crd-summary-label">So far</div>' +
      '<div class="crd-summary-body">' + esc(ov.sofar || "—") + "</div></div>"
    );
  }

  function renderPlan(wrap, ctx, session) {
    var notes = session.notes || [];
    setPanelCount(wrap, notes.length || "—");
    var pushWhen = session.push_when || "none";
    var chip = pushWhen === "turn" ? { text: "queued · lands at turn-end", cls: "crd-chip-quiet" } :
      pushWhen === "wake" ? { text: "queued · on wake", cls: "crd-chip-sunken" } :
      { text: "queued · copy it", cls: "crd-chip-sunken" };
    var rows = notes.map(function (n, i) {
      return '<div class="crd-note-row"><div class="crd-note-body">' + esc(n.text) + "</div>" +
        '<span class="crd-note-chip ' + chip.cls + '">' + chip.text + "</span>" +
        '<span class="crd-note-actions">' +
          '<button data-act="note-copy" data-idx="' + i + '">copy</button>' +
          '<button data-act="note-remove" data-idx="' + i + '">remove</button>' +
        "</span></div>";
    }).join("");
    var body = '<div class="crd-plan-head">📝 PLAN ON THE GO · ' + notes.length + " notes</div>" +
      (rows || '<div class="crd-empty">No notes queued.</div>') +
      '<div class="crd-plan-footer">' +
        '<input class="crd-plan-input" type="text" placeholder="Jot the next thing…">' +
        '<button class="crd-btn crd-btn-solid" data-act="note-push">push</button>' +
      "</div>";
    setPanelBody(wrap, body);
  }

  // ---- Evidence column panels ----

  function renderFiles(wrap, session) {
    var files = session.files || [];
    setPanelCount(wrap, files.length || "—");
    if (!files.length) { setPanelBody(wrap, '<div class="crd-empty">No files touched yet.</div>'); return; }
    var rows = files.map(function (f) {
      var isMd = /\.md$/i.test(f.path || "");
      return '<div class="crd-file-row' + (f.agent ? " crd-agent-row" : "") + '" data-act="file-row" data-path="' +
        esc(f.path) + '">' +
        '<span class="crd-file-path mono">' + esc(f.path) + "</span>" +
        (f.created ? '<span class="crd-file-created">+' + (f.ops || 1) + "</span>" :
          '<span class="crd-file-edited">−' + (f.ops || 1) + "</span>") +
        (f.agent ? '<span class="crd-tag-agent">agent</span>' : "") +
        (isMd ? '<span class="crd-tag-md">md</span>' : "") +
        "</div>";
    }).join("");
    setPanelBody(wrap, rows + '<div class="crd-panel-footnote">click for the diff · context expands up/down</div>');
  }

  function renderCommands(wrap, session) {
    var cmds = session.commands || [];
    var failing = cmds.filter(function (c) { return !c.ok; }).length;
    setPanelCount(wrap, cmds.length ? cmds.length + (failing ? " · " + failing + " failing" : "") : "—");
    wrap.classList.toggle("crd-tint-failed", failing > 0);
    if (!cmds.length) { setPanelBody(wrap, '<div class="crd-empty">No commands run yet.</div>'); return; }
    setPanelBody(wrap, cmds.map(function (c) {
      return '<div class="crd-cmd-row" data-act="command-row" data-id="' + esc(c.id) + '">' +
        '<span class="crd-cmd-status ' + (c.ok ? "crd-cmd-ok" : "crd-cmd-fail") + '">' + (c.ok ? "ok" : "fail") + "</span>" +
        '<span class="crd-cmd-text mono">' + esc(c.cmd) + "</span></div>";
    }).join(""));
  }

  function renderAgentsPanel(wrap, ui, session) {
    if (!wrap || !session) return;
    var agentsBg = session.agents_bg || [];
    var shells = session.shells || [];
    var running = agentsBg.filter(function (a) { return a.running; });
    var finishedAgents = agentsBg.filter(function (a) { return !a.running; });
    var totalRows = running.length + (Array.isArray(shells) ? shells.filter(function (s) { return s && s.running; }).length : 0);
    setPanelCount(wrap, (agentsBg.length + (Array.isArray(shells) ? shells.length : 0)) || "—");

    function agentRow(a) {
      return '<div class="crd-agent-row-item"><span class="crd-state-dot ' + (a.running ? "is-working" : "is-done") +
        '"></span><span class="crd-agent-title">' + esc(a.task || a.aid || "background agent") + "</span>" +
        (a.wf ? '<span class="crd-agent-wf mono">' + esc(a.wf) + "</span>" : "") +
        '<button class="crd-open-link" data-act="agent-open" data-id="' + esc(a.aid) + '">open ›</button></div>';
    }
    function shellRow(s) {
      var label = (s && (s.cmd || s.id)) || "shell";
      return '<div class="crd-agent-row-item"><span class="crd-state-dot ' + (s.running ? "is-working" : "is-done") +
        '"></span><span class="crd-agent-title mono">' + esc(label) + "</span>" +
        '<button class="crd-open-link" data-act="shell-open" data-id="' + esc(s.id || s.cmd) + '">open ›</button></div>';
    }

    var runningHtml = running.map(agentRow).join("") +
      (Array.isArray(shells) ? shells.filter(function (s) { return s && s.running; }).map(shellRow).join("") : "");
    var finishedList = finishedAgents.concat(Array.isArray(shells) ? shells.filter(function (s) { return s && !s.running; }) : []);

    var html = runningHtml || "";
    if (finishedList.length) {
      if (ui.agentsShowFinished) {
        html += finishedList.map(function (x) { return x.aid !== undefined ? agentRow(x) : shellRow(x); }).join("");
      } else {
        html += '<button class="crd-show-finished" data-act="agents-show-finished">Show ' + finishedList.length + " finished</button>";
      }
    }
    if (!html) html = '<div class="crd-empty">No agents or shells this session.</div>';
    setPanelBody(wrap, html);
  }

  function renderRunPanel(wrap, session) {
    setPanelCount(wrap, "");
    setPanelBody(wrap,
      '<div class="crd-run-row"><input class="crd-run-input mono" type="text" placeholder="command…">' +
      '<button class="crd-btn crd-btn-solid" data-act="run-submit">run</button></div>' +
      '<div class="crd-panel-footnote">No shell — argv only, against an allowlist. Runs in this session’s directory.</div>'
    );
  }

  function renderTerminalPanel(wrap, session) {
    // REQUIRED ADDITION: whether a Claude CLI is actually attached to a pty's foreground
    // is answered by GET /api/term/attached?tty=<id> (aitracker/term_vt.py:2383), keyed by
    // a terminal id the session detail dict never carries. Absent that signal, the safe
    // and honest default is to hide the panel — matching the doc's own instruction to
    // hide it whenever "not attached".
    var attached = session.term_attached; // not present today; forward-compatible read
    if (!attached) { wrap.style.display = "none"; return; }
    wrap.style.display = "";
    var meta = session.meta || {};
    var ctxWin = session.context || {};
    setPanelCount(wrap, "");
    setPanelBody(wrap,
      '<div class="crd-term-row">' +
        '<button class="crd-btn crd-btn-solid" data-act="terminal-model">model · ' + esc(shortModel(meta.model) || "—") + "</button>" +
        '<button class="crd-btn crd-btn-outline" data-act="terminal-effort">effort · ' + esc(meta.effort || "—") + "</button>" +
        '<span class="crd-term-ctx mono">' + (ctxWin.current != null ? fmtNum(ctxWin.current) : "—") + " / " +
          (ctxWin.limit != null ? fmtNum(ctxWin.limit) : "—") + "</span>" +
      "</div>" +
      '<div class="crd-panel-footnote">Shown only while a Claude CLI is actually in the pty’s foreground.</div>'
    );
  }

  // ---- Conversation timeline ----

  function renderTimeline(node, ui, session) {
    var wrap = ui.panels.timeline;
    var scrollEl = qs(wrap, ".crd-timeline-scroll");
    var filterEl = qs(wrap, ".crd-timeline-filters");
    var degraded = isDegradedTranscript(session);
    filterEl.style.display = degraded ? "none" : "";
    if (degraded) {
      setPanelCount(wrap, "");
      scrollEl.innerHTML = '<div class="crd-degraded">' +
        "This provider’s transcript can’t be read cleanly (an editor-extension log, not a " +
        "structured session file) — there’s nothing reliable to show here." +
        "</div>";
      return;
    }
    renderTimelineEntries(scrollEl, ui, session, false);
  }

  function entryHtml(e) {
    if (e.kind === "prompt") {
      return '<div class="crd-entry crd-entry-prompt"><span class="crd-entry-ts mono">' + fmtClock(e.t) + "</span>" +
        '<div class="crd-bubble crd-bubble-prompt">' + esc(e.text) + "</div></div>";
    }
    if (e.kind === "narration") {
      return '<div class="crd-entry crd-entry-narration" data-todo-text="">' +
        '<span class="crd-entry-ts mono">' + fmtClock(e.t) + "</span>" +
        '<div class="crd-narration-text">' + esc(e.text) + "</div></div>";
    }
    if (e.kind === "ask") {
      var d = e.decision;
      var q0 = (d.questions && d.questions[0]) || { q: "", options: [] };
      var opts = (q0.options || []).map(function (o) { return '<span class="crd-ask-pill">' + esc(o) + "</span>"; }).join("");
      return '<div class="crd-entry crd-entry-ask"><span class="crd-entry-ts mono crd-ts-ask">' + fmtClock(e.t) + "</span>" +
        '<div class="crd-bubble crd-bubble-ask"><div class="crd-ask-q">' + esc(q0.q) + "</div>" +
        '<div class="crd-ask-opts">' + opts + "</div>" +
        '<div class="crd-ask-note">View-only — answer in the session itself.</div></div></div>';
    }
    if (e.kind === "command" || e.kind === "command-fail") {
      var c = e.cmd;
      return '<div class="crd-entry crd-entry-tool' + (e.kind === "command-fail" ? " is-fail" : "") + '">' +
        '<span class="crd-entry-ts mono ' + (e.kind === "command-fail" ? "crd-ts-fail" : "") + '">' + fmtClock(e.t) + "</span>" +
        '<div class="crd-toolrow">' + (e.kind === "command-fail" ? '<span class="crd-tool-fail">fail</span>' : "") +
        '<span class="crd-tool-name mono">' + esc(c.cmd) + "</span></div></div>";
    }
    return "";
  }

  function renderTimelineEntries(scrollEl, ui, session, force) {
    if (!session) return;
    var all = mergeTimeline(session);
    var filtered = ui.timelineFilter === "talk" ?
      all.filter(function (e) { return e.kind === "prompt" || e.kind === "narration"; }) : all;

    if (force || filtered.length !== ui.timelineSeen || !scrollEl.childNodes.length) {
      var wasStuck = ui.timelineStuckBottom;
      var prevScrollTop = scrollEl.scrollTop;
      scrollEl.innerHTML = filtered.length ?
        filtered.map(entryHtml).join("") :
        '<div class="crd-empty">Nothing recorded yet — the first prompt starts the conversation.</div>';
      ui.timelineSeen = filtered.length;
      if (wasStuck) scrollEl.scrollTop = scrollEl.scrollHeight;
      else scrollEl.scrollTop = prevScrollTop;
    }
  }

  function renderSearchResults(node, ui, query) {
    var box = qs(node, ".crd-search-results");
    var q = (query || "").trim().toLowerCase();
    if (!q) { box.innerHTML = ""; return; }
    var session = ui.lastSession || {};
    var terms = q.split(/\s+/);
    function matches(s) { return terms.every(function (t) { return s.toLowerCase().indexOf(t) >= 0; }); }
    var hits = [];
    (session.narrative || []).forEach(function (n) { if (n.text && matches(n.text)) hits.push({ kind: "narration", text: n.text, t: n.t }); });
    (session.requests || []).forEach(function (r) { if (r.text && matches(r.text)) hits.push({ kind: "prompt", text: r.text, t: r.t }); });
    (session.files || []).forEach(function (f) { if (f.path && matches(f.path)) hits.push({ kind: "file", text: f.path, t: f.last }); });
    (session.commands || []).forEach(function (c) { if (c.cmd && matches(c.cmd)) hits.push({ kind: "command", text: c.cmd, t: c.t }); });
    (session.todos || []).forEach(function (t) { if (t.content && matches(t.content)) hits.push({ kind: "todo", text: t.content }); });
    // NOTE: this is client-side only (no fetch, per contract) and therefore limited to
    // the currently-loaded page of narration (server caps /api/session's narrative to
    // NARR_PAGE=60 entries — aitracker/config.py:66, server.py:308-310). Full-history
    // search would need ctx to expose a search call or /api/narration paging — flagged
    // as a REQUIRED ADDITION in the module report.
    if (!hits.length) { box.innerHTML = '<div class="crd-empty">No matches in the loaded window.</div>'; return; }
    box.innerHTML = hits.slice(0, 40).map(function (h) {
      return '<div class="crd-search-hit"><span class="crd-search-kind">' + esc(h.kind) + "</span>" +
        '<span class="crd-search-text">' + esc(h.text.slice(0, 160)) + "</span></div>";
    }).join("");
  }

  // Expose pure functions for testability / reuse by a future self-check.
  window.CR.detail._internal = {
    spineSegments: spineSegments,
    mergeTimeline: mergeTimeline,
    deriveLinks: deriveLinks,
    stateOf: stateOf,
    firstEventTime: firstEventTime
  };
})();
