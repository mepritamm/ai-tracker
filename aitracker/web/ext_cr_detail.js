// cr_detail.js — Control Room detail view (doc 03-detail-view.md).
//
// Namespace: window.CR.detail = { mount(root, ctx), update(state) }.
// Almost no network calls here (contract rule 5) — everything is derived from the
// `session` detail dict the bootstrap already fetched from /api/session
// (aitracker/registry.py:parse_any -> aitracker/providers/claude.py:parse_session
// / aitracker/providers/auggie.py, whichever's return dict, shared shape). The ONE
// exception (design-audit FIX 4a): loadOlderNarration() below fetches the EXISTING
// `/api/narration?id=&offset=&limit=` route (server.py:313-333) to page in history
// past the server's NARR_PAGE=60 cap on /api/session — the same route+shape
// aitracker/web/app.js's own narrState paging already uses (app.js:1264-1271, read
// not edited). No other network call is added anywhere else in this file.
//
// Real detail-dict key paths this file relies on (verified by reading the
// providers, not guessed):
//   meta            aitracker/providers/claude.py:976 {cwd,gitBranch,version,sessionId,
//                   entrypoint,aiTitle,customTitle,model,effort,title}
//                   aitracker/providers/auggie.py:382 {cwd,title,source,entrypoint,gitBranch,model}
//   todos[]         {content,status,activeForm} — aitracker/store.py:67-70 (load_tasks) and
//                   aitracker/providers/claude.py:892-893 (in-transcript TodoWrite fallback).
//                   started_at/ended_at (snake_case, epoch SECONDS or null) are stamped by
//                   claude.py:1209-1210 via util._ts_epoch — read via parseEpochSec() below,
//                   not parseT()/Date.parse (which expects the ISO `.t` strings used elsewhere
//                   in this file). Confirmed on a live /api/session payload: ended_at is
//                   populated whenever a todo completed, but started_at is only set when the
//                   transcript recorded an explicit TaskUpdate to "in_progress" — many real
//                   sessions never do, so started_at is None there and the honest equal-width
//                   fallback below is what actually renders for them (correct, not a bug).
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
//   a generic "links" array for the Links panel                (deriveLinks below)
//   PR title text                                              (prs[] carries url/repo/num only)
//   terminal pty-attached signal for the Terminal controls panel (GET /api/term/attached,
//     keyed by a `tty` id the session detail dict never carries)
//   a triage-queue position ("1 of 4 needing attention") for the back-line hint

(function () {
  window.CR = window.CR || {};

  // Mirrors config.LIVE_WINDOW (server) / LIVE (app.js) — same constant, same
  // meaning, per CLAUDE.md's "Liveness is one constant" rule. app.js's `LIVE`
  // IS reachable here: page.py concatenates every web/*.js file into ONE
  // <script> tag, app.js first (page.py: read("app.js") + read_ext(".js")),
  // so its top-level `const LIVE = 300` sits in the same script-level scope
  // this IIFE closes over — verified by reading page.py, not assumed (an
  // earlier version of this comment claimed app.js wasn't reachable; that was
  // false). Derived from it with a safe literal fallback only for the
  // (currently never-exercised) case this file is ever loaded standalone.
  var LIVE_WINDOW = (typeof LIVE !== 'undefined') ? LIVE : 300;

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

  // todos[i].started_at / ended_at are epoch SECONDS (a number), the same convention as
  // session.mtime/now (aitracker/util.py:_ts_epoch) -- NOT an ISO string like the `.t`
  // fields elsewhere in this file, so they are never run through parseT()/Date.parse.
  function parseEpochSec(v) {
    return (typeof v === "number" && !isNaN(v)) ? v * 1000 : null;
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
  // display name the doc's "model · sonnet" chip wants. The ONE shortening rule
  // lives in ext_cr_board.js's modelShort (loaded before this file — page.py's
  // read_ext() sorts ext_ files alphabetically, "ext_cr_board" < "ext_cr_detail")
  // and is reused here rather than forked a second time, per the owner's
  // standing policy. Same try/catch-delegate-to-another-module pattern as
  // providerNote() below; the inline fallback (family name only, no version) is
  // only ever exercised if board.js somehow isn't mounted yet.
  function shortModel(m) {
    try {
      var fn = window.CR && window.CR.board && window.CR.board.modelShort;
      if (typeof fn === "function") return fn(m) || "";
    } catch (e) {}
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

  // ============================== markdown rendering (capability #31, FIX 1) ==============================
  // SECURITY: mdHtml() is the ONLY function in this file that turns session-authored
  // text into HTML, and it does so by delegating to ctx.markdown(text) — never by
  // interpolating raw text into innerHTML itself. ctx.markdown (ext_cr_boot.js:259)
  // wraps app.js's OWN `md()` inline-markdown renderer (app.js:10-17), which escapes
  // first (`let h=esc(s)`) and only ever adds closed, safe tags (<code>/<strong>/<em>/
  // <a target=_blank rel=noopener>) — so the string this returns is exactly as safe
  // as calling esc() was. Every field NOT explicitly named by the doc's capability
  // #31 list (narration, prompts, todos, notes, agent output, .md files) is left on
  // plain esc() in this file — e.g. decision questions/options and the Summary
  // Goal/Now/So-far fields aren't named there, so they're deliberately left alone.
  function mdHtml(ctx, text) {
    if (ctx && typeof ctx.markdown === "function") {
      try { return ctx.markdown(text).innerHTML; } catch (e) {}
    }
    return esc(text); // ctx.markdown absent (older bootstrap) — old esc()-only behaviour
  }

  // ============================== shared empty/error/degraded states (FIX 5, FIX 6) ==============================
  // Calls the SAME components board/terminal are told to reuse (ext_cr_dialogs.js
  // "shared state components — exported so board/detail/terminal reuse rather than
  // fork", :160-208) instead of forking a second empty-panel div or a second degraded-
  // provider paragraph. Those return a real HTMLElement (built via dialogs.js's own
  // `h()`), which this file's string-built panels can't append directly — .outerHTML
  // gets the markup those functions already produced (all closed tags, no user text
  // interpolated raw; same trust level as mdHtml above). Falls back to the plain
  // `.crd-empty` div this file used before if CR.dialogs isn't loaded yet.
  function sharedStateHtml(name, opts, fallbackText) {
    try {
      var fn = window.CR && window.CR.dialogs && window.CR.dialogs[name];
      if (typeof fn === "function") {
        var node = fn(opts);
        if (node && node.outerHTML) return node.outerHTML;
      }
    } catch (e) {}
    return '<div class="crd-empty">' + esc(fallbackText || (opts && opts.title) || "") + "</div>";
  }
  function emptyHtml(title, body) {
    return sharedStateHtml("emptyState", { title: title, body: body }, title);
  }
  function errorHtml(title, body) {
    return sharedStateHtml("errorState", { title: title, body: body }, title);
  }

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

  // FIX 8: the Config dialog's "Cards start folded" toggle writes `cr.cardsFolded`
  // as a JSON boolean (ext_cr_dialogs.js CFG_PREF_KEYS.cardsFolded = 'cr.cardsFolded',
  // written via that module's writePref() -> localStorage.setItem(key,
  // JSON.stringify(val)) — read, not forked, with the same JSON.parse). This is the
  // DEFAULT for a panel with no stored per-session state yet; existing per-panel/
  // per-session state (getCollapsed above) always overrides it once it exists.
  function defaultFolded() {
    try {
      var raw = localStorage.getItem("cr.cardsFolded");
      if (raw == null) return true; // key absent -> preserve today's behaviour
      return JSON.parse(raw) !== false;
    } catch (e) { return true; }
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
  // todos[i].started_at / todos[i].ended_at (snake_case, epoch seconds — see parseEpochSec
  // above and claude.py:1209-1210) drive the `hasTimes` branch below when every active todo
  // carries a started_at; this function falls back to an honest equal-width split among
  // active/pending todos otherwise — never fabricating a per-todo duration.
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
      activeIdx.every(function (i) { return parseEpochSec(todos[i].started_at) != null; });

    var segs = [];
    if (hasTimes) {
      out.timeAccurate = true;
      var spentTotal = 0, spentByIdx = {};
      activeIdx.forEach(function (i) {
        var t = todos[i];
        var started = parseEpochSec(t.started_at);
        var ended = t.ended_at != null ? parseEpochSec(t.ended_at) : nowMs;
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
        // FIX (design-audit drift 7): 5b's prompt marker tooltip reads "You asked · <clock>".
        title: "You asked · " + fmtClock(t) });
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

  // Merges narration + prompts (+ decisions + commands + tool activity) into one
  // chronological list. Pure: (session) -> [{kind, t, ...}] newest-first (defect 1 —
  // matches curNarr/narrState/navFirst's "index 0 = newest" convention elsewhere).
  //
  // FIX (design-audit drift 8 — "the biggest gap"): 5b's timeline shows generic
  // tool-call rows — "Edit · aitracker/web/ext_vt.js · 0.4s · +118 −31" — for every
  // file the session touched, not just its shell commands. Before this fix,
  // mergeTimeline only ever folded in requests/narrative/decisions/commands[], so
  // file edits/writes/reads and Task-tool dispatches never appeared here at all —
  // most of what an agent actually DOES was invisible in the one view built to show
  // exactly that.
  //
  // What's populated from real fields (verified against parse_session, claude.py
  // 978-985) and what genuinely is not available:
  //   files[]  {path, ops, last, created, agent?} — "last" is the aggregate row's
  //            OWN timestamp (one row per path, not one per edit), so this emits
  //            ONE tool-call row per touched file at its last-touched time, tool
  //            name Write/Edit from `created`, target = the full path, and `ops`
  //            (the op COUNT, not a line diff) as the only real count available.
  //   reads[]  {path, t} — no op count at all; renders name+target only.
  //   agents[] {t, type, desc} — Task-tool dispatches; renders Task + its desc/type.
  //   NOT available anywhere on the detail dict, for any of the three: a duration
  //   (no per-op start/end pair — only one aggregate "last" timestamp per file, and
  //   none at all for a Task dispatch) or a diff line-count ("+118 −31" — `ops` is
  //   an edit-call tally, not lines added/removed; no such field exists). Rendered
  //   as name + target + whatever count IS real (ops, when present) — see the
  //   `// NOTE:` on entryHtml's "tool" case below for exactly what's omitted.
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
    (session.files || []).forEach(function (f, i) {
      var t = parseT(f.last);
      out.push({ kind: "tool", t: t == null ? 0 : t, verb: f.created ? "Write" : "Edit",
        target: f.path, count: f.ops ? (f.ops + (f.ops === 1 ? " op" : " ops")) : "",
        agent: !!f.agent, key: "f" + i });
    });
    (session.reads || []).forEach(function (r, i) {
      var t = parseT(r.t);
      out.push({ kind: "tool", t: t == null ? 0 : t, verb: "Read", target: r.path, count: "", agent: false, key: "rd" + i });
    });
    (session.agents || []).forEach(function (a, i) {
      var t = parseT(a.t);
      out.push({ kind: "tool", t: t == null ? 0 : t, verb: "Task",
        target: (a.desc || a.type || "background agent"), count: "", agent: true, key: "ag" + i });
    });
    // FIX (defect 1): newest-first, matching the rest of the app — the server's own
    // narrative[::-1] (claude.py:1269), classic's curNarr/narrState prepend-on-arrival
    // (app.js:1391), and navFirst's own "index 0 = newest" comment (app.js:1591).
    out.sort(function (a, b) { return b.t - a.t; });
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

  // ============================== narration diagrams (FIX 2, capabilities #32/#33) ==============================
  // Detects a fenced ```mermaid block inside one narration entry's text and reduces it
  // to the doc's "node pill" shape — 03-detail-view.md's "Rendered diagram" timeline
  // entry, and 04's narration-diagram pop-out (ext_cr_dialogs.js:908 renderNarrationDiagram,
  // read not edited, payload {time, nodes:[{label,active}], edges, family, onPrev, onNext,
  // onLatest}). The fence-tag test and the 8-family keyword dispatch mirror app.js's OWN
  // mermaid detection (mdBlock's `/^mermaid$/i` fence-tag check, mermaidSvg's family
  // dispatch — app.js:25-33,111-120, read not edited), so this recognises exactly the 8
  // families the doc/Help capability list claims.
  //
  // It deliberately does NOT reuse app.js's geometry renderers (_mermaidSvgFlow et al) —
  // those build full SVG node/edge layout, not the flat label list the pills dialog
  // wants — and the RULES forbid adding mermaid.js, so this is a SIMPLE label
  // extractor: split each body line on the run of mermaid "edge glyph" characters
  // (-=.<>|*{}ox — covers -->, ->>, <|--, ||--o{, etc. across all 8 families) and keep
  // the bracketed label (or bare id) on each side. This is a best-effort approximation
  // of 8 different grammars, not a full mermaid parser — same spirit as deriveLinks()
  // above, not a second markdown/diagram implementation of app.js's own renderer.
  // "active" marks the LAST distinct node seen (read as "the state the diagram left
  // off on") — there is no real signal for which node is "current" in narration text,
  // so this is a judgment call, not a derived fact.
  var MMD_FENCE_RE = /```\s*mermaid[ \t]*\r?\n([\s\S]*?)```/i;
  var MMD_FAMILY_RE = [
    [/^sequenceDiagram\b/i, "sequenceDiagram"],
    [/^stateDiagram(?:-v2)?\b/i, "stateDiagram-v2"],
    [/^classDiagram(?:-v2)?\b/i, "classDiagram"],
    [/^erDiagram\b/i, "erDiagram"],
    [/^(?:journey|userJourney)\b/i, "journey"],
    [/^pie\b/i, "pie"],
    [/^quadrantChart\b/i, "quadrantChart"],
    [/^(?:flowchart|graph)\b/i, "flowchart"]
  ];
  var MMD_EDGE_RE = /[<>|*{}]*[-=.]{1,4}[<>|*{}ox]*/;
  var MMD_SKIP_RE = /^(subgraph|end|direction|classDef|class|style|click|note|activate|deactivate|autonumber|accTitle|accDescr)\b/i;

  function extractDiagram(text) {
    if (!text || text.indexOf("```") === -1) return null;
    var fm = MMD_FENCE_RE.exec(text);
    if (!fm) return null;
    var lines = fm[1].replace(/\r/g, "").split("\n")
      .map(function (l) { return l.replace(/%%.*$/, "").trim(); })
      .filter(Boolean);
    if (!lines.length) return null;
    var family = null;
    for (var i = 0; i < MMD_FAMILY_RE.length; i++) {
      if (MMD_FAMILY_RE[i][0].test(lines[0])) { family = MMD_FAMILY_RE[i][1]; break; }
    }
    if (!family) return null; // not one of the 8 recognised families — no fabricated diagram

    var order = [], seen = {};
    function push(raw) {
      raw = (raw || "").trim();
      if (!raw) return;
      var bm = /[\[\(\{]\s*"?([^\]\)\}"]*)"?\s*[\]\)\}]/.exec(raw);
      var label = bm ? bm[1].trim() : raw.replace(/^["']+|["']+$/g, "").trim();
      if (!label) label = raw.split(/\s+/)[0];
      label = label.split(/\s+/).slice(0, 5).join(" ");
      if (label.length > 40) label = label.slice(0, 40) + "…";
      if (!label || label === "*") return;
      if (!seen[label]) { seen[label] = true; order.push(label); }
    }
    lines.slice(1).forEach(function (l) {
      if (MMD_SKIP_RE.test(l)) return;
      var m2 = MMD_EDGE_RE.exec(l);
      if (m2 && m2[0].length >= 2) {
        push(l.slice(0, m2.index));
        push(l.slice(m2.index + m2[0].length).split(":")[0]);
      } else {
        push(l.split(":")[0]);
      }
    });
    if (!order.length) return null;

    return {
      family: family,
      nodes: order.map(function (label, i) { return { label: label, active: i === order.length - 1 }; }),
      prefix: text.slice(0, fm.index),
      suffix: text.slice(fm.index + fm[0].length),
      // Raw mermaid source (no fences) -- NOT used by the label/pill extraction above,
      // but needed by renderMermaid() (app.js, shared with the classic UI's mdBlock())
      // to draw the REAL diagram rather than the flat pill-list approximation. Kept
      // alongside the derived `nodes` rather than replacing them: nodes stay the
      // fallback rendered instantly and reused by ext_cr_dialogs.js's pop-out today.
      src: fm[1]
    };
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

  // FIX (design-audit drift 1): 5b has NO files/commands/reads/commits/tests/branch/
  // tokens stat-chip row under the goal — the token count is folded into the
  // metadata line instead (renderHeader below builds it: project · branch · elapsed ·
  // tokens, matching 5b's "ai-tracker · term-tiers · 41m · 128,412 tokens"). The old
  // 7-chip statChips() row is gone outright, per the ruling ("the row must go"); the
  // per-panel counts already visible in each STATE/EVIDENCE panel header (Files'
  // "18", Commands' "42 · 1 failing", PRs' "2 · 1 merged", …) still carry files/
  // commands/tests/commits visibility — only the bare "reads" count and the branch
  // NAME as a standalone chip lose their old header-level home; branch itself still
  // reappears in the metaline below.
  function fmtTokens(session) {
    var tokTotal = ((session.tokens && session.tokens.in) || 0) + ((session.tokens && session.tokens.out) || 0);
    return tokTotal ? fmtNum(tokTotal) + " tokens" : "";
  }

  // FIX 5: the old ad-hoc `isDegradedTranscript` (meta.source/entrypoint sniffed for
  // "augment" but not "auggie") is gone — replaced by providerNote() below, which
  // reads ext_cr_dialogs.js's own PROVIDER_NOTES table via its public
  // providerNoteFor(source), instead of re-deriving the same augment/auggie split
  // a second time in this file.

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
    var defCollapsed = opts.defaultCollapsed === false ? false : defaultFolded();
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
            // FIX (design-audit drift 2): 5b collapses actions to ONE inline row —
            // Open terminal (solid) · Resume (outline) · Queue a note, right-aligned
            // at the end of THIS row (margin-left:auto), not a second action block
            // below the header. Search/Flag/External aren't in 5b's row at all (the
            // whole round 5 detail view drops them — verified across 5a/5b/5c/5d, not
            // just this artboard); per the owner's "don't drop a capability" rule
            // they're kept reachable here as small icon buttons rather than removed,
            // see the module report for exactly where they landed.
            '<span class="crd-row1-actions">' +
              '<button class="crd-iconbtn" data-act="toggle-search" title="Search this session" aria-label="Search this session"><span class="crd-ico"></span></button>' +
              '<button class="crd-iconbtn crd-flagbtn" data-act="toggle-flag" title="Flag an issue" aria-label="Flag an issue"><span class="crd-ico"></span><span class="crd-flag-badge" hidden></span></button>' +
              '<button class="crd-btn crd-btn-solid" data-act="open-terminal">Open terminal</button>' +
              '<button class="crd-btn crd-btn-outline" data-act="resume">Resume</button>' +
              '<button class="crd-btn crd-btn-ai" data-act="toggle-note">Queue a note</button>' +
              '<button class="crd-btn crd-btn-bare" data-act="external" hidden>External</button>' +
            "</span>" +
          "</div>" +
          '<div class="crd-id-row2">' +
            '<h1 class="crd-goal"></h1>' +
            '<button class="crd-rename" data-act="rename" title="Rename" aria-label="Rename session"></button>' +
            '<span class="crd-pill crd-pill-pinned" hidden><span class="tn-emo" aria-hidden="true">📌</span> Pinned</span>' +
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
      // "Queue a note" (design-audit drift 2, new in 5b): opens this small card
      // instead of a dialog (dialogs aren't ours to add to). Submitting calls the
      // SAME 'cr:note-push' emit the Plan panel (renderPlan) and the phone bottom
      // bar already use — a third entry point onto one push path, not a second one.
      '<div class="crd-card crd-notecard" hidden>' +
        '<input class="crd-note-queue-input" type="text" placeholder="Queue a note for this session…">' +
        '<button class="crd-btn crd-btn-solid" data-act="note-queue-send">Queue</button>' +
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
      // FIX (defect 1): the timeline is now newest-first (mergeTimeline sorts
      // descending), matching curNarr/app.js's "index 0 = newest" convention
      // (navFirst's own comment) and the server's own narrative[::-1]. "Stuck to
      // latest" therefore means pinned at the TOP of the scroll now, not the bottom.
      timelineStuckLatest: true,
      timelineFilter: "all",
      // FIX (defect 2): each of the four legend words is now its own toggle,
      // additive on top of the all/talk preset — see timelineEntryVisible() below.
      timelineKindsOn: {},
      agentsShowFinished: false,
      searchOpen: false,
      flagOpen: false,
      noteOpen: false
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
    // FIX (design-audit drift 3): 5b renders fork lineage as a small card at the
    // BOTTOM of the Evidence column (after Terminal controls), not a full-width
    // banner between the header and the spine — see renderForkBanner().
    var forkCard = el(
      '<div class="crd-forkcard" hidden>' +
        '<div class="crd-fork-head"><span class="crd-ico crd-fork-ico"></span>' +
          '<span class="crd-fork-label"></span></div>' +
        '<div class="crd-fork-body"></div>' +
        '<button class="crd-fork-link" data-act="fork-open"></button>' +
      "</div>"
    );
    evidenceBody.appendChild(forkCard);
    ui.forkCard = forkCard;

    // Conversation timeline: single panel, starts expanded (doc: the only exception).
    var timelineWrap = el(
      '<section class="crd-panel crd-timeline-panel" data-panel="timeline">' +
        '<header class="crd-panel-head" data-act="toggle-panel" data-panel="timeline" data-col="convo">' +
          '<span class="crd-chevron">▾</span>' +
          '<span class="crd-panel-label">TIMELINE</span>' +
          // FIX (defect 2): the four words are real, individually-selectable filter
          // chips now (data-act="timeline-filter" data-mode="kind", same delegation
          // + .is-active convention the all/talk preset buttons already use) instead
          // of static legend text. See timelineEntryVisible()/TIMELINE_KIND_MAP.
          '<span class="crd-timeline-filters">' +
            '<span class="crd-timeline-kinds">' +
              '<button data-act="timeline-filter" data-mode="kind" data-kind="prompts">prompts</button>' +
              '<button data-act="timeline-filter" data-mode="kind" data-kind="narration">narration</button>' +
              '<button data-act="timeline-filter" data-mode="kind" data-kind="tools">tools</button>' +
              '<button data-act="timeline-filter" data-mode="kind" data-kind="results">results</button>' +
            "</span>" +
            '<span class="crd-timeline-presets">' +
              '<button class="is-active" data-act="timeline-filter" data-mode="all">all</button>' +
              '<button data-act="timeline-filter" data-mode="talk">talk only</button>' +
              // FIX (defect 3): panel-level pop-out — opens the newest entry of
              // whatever's currently visible, same as the "⤒ latest" convo-nav button.
              '<button class="crd-timeline-popout" data-act="timeline-popout" title="Pop out the newest entry" aria-label="Pop out the newest entry">⤢</button>' +
            "</span>" +
          "</span>" +
        "</header>" +
        '<div class="crd-panel-body">' +
          '<div class="crd-timeline-scroll"></div>' +
          '<div class="crd-timeline-live" hidden></div>' +
          '<div class="crd-timeline-foot mono">older turns page in as you scroll — history is unbounded</div>' +
        "</div>" +
      "</section>"
    );
    convoBody.appendChild(timelineWrap);
    ui.panels.timeline = timelineWrap;

    var scrollEl = qs(timelineWrap, ".crd-timeline-scroll");
    scrollEl.addEventListener("scroll", function () {
      // FIX (defect 1): newest-first now means the newest entry sits at the TOP of
      // the scroll box, so "stuck to the latest entry" is pinned at scrollTop≈0 —
      // the inverse of the old oldest-first "stuck to the bottom" check.
      var atTop = scrollEl.scrollTop < 40;
      ui.timelineStuckLatest = atTop;
      // FIX 4a (order flipped by defect 1): older history is now at the BOTTOM of
      // the loaded window (oldest = smallest t = sorted last), so paging it in
      // fires near the bottom of the scroll box, not the top.
      var nearBottom = scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 60;
      if (nearBottom) loadOlderNarration(ctx, ui, node);
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
        // FIX (design-audit drift 2): "Queue a note" (new in 5b) opens this small
        // card; submitting calls the SAME 'cr:note-push' emit renderPlan()'s own
        // push button and the phone bottom bar's send button already use — a third
        // entry point onto one existing path, not a second note-adding mechanism.
        case "toggle-note":
          ui.noteOpen = !ui.noteOpen;
          qs(node, ".crd-notecard").hidden = !ui.noteOpen;
          if (ui.noteOpen) qs(node, ".crd-note-queue-input").focus();
          break;
        case "note-queue-send": {
          var qInput = qs(node, ".crd-note-queue-input");
          var qText = qInput && qInput.value.trim();
          if (!qText) return;
          ctx.emit("cr:note-push", { sessionId: sid, text: qText });
          qInput.value = "";
          ui.noteOpen = false;
          qs(node, ".crd-notecard").hidden = true;
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
          // FIX (defect 2): "kind" chips (prompts/narration/tools/results) are
          // independent, additive toggles; the "all"/"talk" buttons are the two
          // shipped presets and reset any custom chip selection back to a clean
          // slate (same shape as before — see updateTimelineFilterButtons/
          // timelineEntryVisible for how the two combine).
          var mode = t.getAttribute("data-mode");
          if (mode === "kind") {
            var kind = t.getAttribute("data-kind");
            ui.timelineKindsOn = ui.timelineKindsOn || {};
            ui.timelineKindsOn[kind] = !ui.timelineKindsOn[kind];
          } else {
            ui.timelineFilter = mode;
            ui.timelineKindsOn = {};
          }
          updateTimelineFilterButtons(timelineWrap, ui);
          // A filter swap replaces the whole visible set (not an incremental
          // arrival at one end), so no top-growth scroll compensation applies.
          renderTimelineEntries(scrollEl, ui, ui.lastSession, true, ctx, { noTopGrowth: true });
          break;
        }
        case "timeline-popout":
          openLatestTimelineEntry(ui);
          break;
        case "timeline-entry-open": {
          var ekey = t.getAttribute("data-key");
          openTimelineEntryByKey(ui, ekey);
          break;
        }
        case "narration-diagram": {
          var dkey = t.getAttribute("data-key");
          var didx = -1;
          (ui.diagramEntries || []).forEach(function (d, i) { if (d.key === dkey) didx = i; });
          if (didx >= 0) openNarrationDiagram(ctx, ui, didx);
          break;
        }
        case "convo-latest":
          // FIX (defect 1): newest is at the TOP now (newest-first), not the bottom.
          ui.timelineStuckLatest = true;
          scrollEl.scrollTop = 0;
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
          // FIX 1: route through app.js's own copyNote(idx) (app.js ~1804) instead of a
          // bare navigator.clipboard.writeText().catch(()=>{}) — that silently did nothing
          // on a denied/unavailable Clipboard API. copyNote() reads the SAME note (by the
          // SAME index) off app.js's `lastData`, which ctx.go()->pick() keeps pointed at
          // whatever session this view has open, so it's the same note `n` above resolves.
          // It already has its own navigator.clipboard + execCommand-textarea fallback.
          // Its own toast() call writes into the classic #toasts div, which CR mode hides
          // (ext_cr_boot.js's notifyDone wrapper documents the same gotcha) — so also emit
          // the 'notify' bus event this module's other confirmations use, for a toast that
          // is actually visible in Control Room.
          if (n && typeof copyNote === "function") {
            copyNote(idx2);
            ctx.emit("notify", { text: "Note copied" });
          }
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

    // FIX 7: j/k session navigation. ext_cr_board.js's own bindKeyboard() already
    // implements j/k, but its isBoardActive() deliberately returns false while detail
    // is showing (cr_board.js — not ours to edit), so it never fires here. Mirrors the
    // SAME guard shape locally (isTypingTarget/an isActive check) instead of forking
    // board's private helpers, and gets the CURRENT triage order from board's own
    // PUBLIC surface — CR.board.boardTiles(sessions, now), exported specifically "for
    // tests / a bootstrap that wants the pure derivations directly" — over the exact
    // `sessions`/`listNow` globals boot.js itself reads to feed board.update()
    // (ext_cr_boot.js's SIDE_EXT push; app.js:692,698 declares them). Not a forked
    // copy of boardTiles' ranking.
    document.addEventListener("keydown", function (e) {
      if (!root.isConnected || !isDetailActive(root)) return;
      if (isTypingTarget(e)) return;
      if (e.key === "j") { e.preventDefault(); stepSession(ctx, ui, 1); }
      else if (e.key === "k") { e.preventDefault(); stepSession(ctx, ui, -1); }
    });

    root._crDetail = { node: node, ui: ui };
  };

  function isTypingTarget(e) {
    var t = e.target;
    if (!t) return false;
    if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) return true;
    var termRoot = document.getElementById("cr-term-root"); // never steal keys from the terminal
    return !!(termRoot && termRoot.contains(t));
  }

  function isDetailActive(root) {
    var nextRoot = document.getElementById("nextRoot");
    if (!nextRoot || nextRoot.hidden) return false;
    return !root.hidden; // root is boot.js's #cr-view-detail; .hidden toggles with showView()
  }

  function stepSession(ctx, ui, dir) {
    if (!window.CR.board || typeof window.CR.board.boardTiles !== "function") return;
    var list = (typeof sessions !== "undefined" && Array.isArray(sessions)) ? sessions : [];
    if (!list.length) return;
    var nowSec = (typeof listNow === "number") ? listNow : Math.floor(Date.now() / 1000);
    var tiles = window.CR.board.boardTiles(list, nowSec).filter(function (t) { return t.kind === "session"; });
    if (!tiles.length) return;
    var idx = -1;
    tiles.forEach(function (t, i) { if (t.session.id === ui.sid) idx = i; });
    var next = idx < 0 ? 0 : Math.max(0, Math.min(tiles.length - 1, idx + dir));
    var target = tiles[next] && tiles[next].session;
    if (target && target.id !== ui.sid && ctx && typeof ctx.go === "function") ctx.go("detail", target.id);
  }

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
        var def = key === "timeline" ? false : defaultFolded(); // FIX 8: cr.cardsFolded pref
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

    renderTimeline(node, ui, session, ctx);
    renderLiveEntry(node, session, nowSec); // FIX 3
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
    // FIX (design-audit drift 1): 5b's metaline is "project · branch · elapsed ·
    // tokens" (its own mock: "ai-tracker · term-tiers · 41m · 128,412 tokens") — no
    // full cwd path, and the elapsed figure matches the SAME "since first prompt"
    // value the spine shows (firstEventTime), not "idle since last activity"; the
    // token total that used to live in the stat-chip row is folded in here instead.
    var firstMs = firstEventTime(session);
    var elapsedStr = firstMs != null ? fmtAge(Math.max(0, nowSec - firstMs / 1000)) : null;
    // Model tacks onto the SAME metadata line, subordinate to project/branch/
    // elapsed/tokens — never its own visual element. Empty means render
    // nothing (no "unknown"), handled by the existing .filter(Boolean).
    var modelBit = shortModel(meta.model) || null;
    var metaBits = [proj || null, meta.gitBranch || null, elapsedStr, fmtTokens(session) || null, modelBit].filter(Boolean);
    var metaEl = qs(node, ".crd-metaline");
    metaEl.textContent = metaBits.join(" · ");
    metaEl.title = meta.model || "";

    var st = stateOf(session, nowSec);
    var pill = qs(node, ".crd-pill-state");
    pill.className = "crd-pill crd-pill-state crd-state-" + st.cls;
    // Glyph needs its own tinted span (doc 01 table: ⏳ awaiting -> tn-emo-a,
    // ✅ done -> tn-emo-d) so plain textContent won't do — it can't parse the
    // wrapper markup. st.word/st.age are still escaped since they land in HTML now.
    var glyph = st.cls === "awaiting" ? '<span class="tn-emo-a" aria-hidden="true">⏳</span> ' :
      (st.cls === "failed" ? "" : (st.cls === "done" ? '<span class="tn-emo-d" aria-hidden="true">✅</span> ' : ""));
    pill.innerHTML = glyph + esc(st.word) + (st.age ? " · " + esc(st.age) : "");

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

    // FIX (design-audit drift 2): search/flag are demoted to small icon buttons in
    // the row1 actions cluster (see the SKELETON comment) rather than the old
    // full-label pill buttons — icoEls indices still map search first, flag second.
    var icoEls = qsa(node, ".crd-row1-actions .crd-iconbtn .crd-ico");
    if (icoEls[0]) icoEls[0].innerHTML = svgIcon(ctx, "search", "⌕");
    if (icoEls[1]) icoEls[1].innerHTML = svgIcon(ctx, "alert", "⚠");

    // REQUIRED ADDITION: session.open_flags (unresolved-flag count) is not on the
    // detail dict (see stateOf's note above) — shows "—" rather than a fabricated 0.
    var flagCount = session.open_flags;
    var flagBtn = qs(node, '[data-act="toggle-flag"]');
    var flagTitle = "Flag an issue" + (flagCount ? " · " + flagCount + " open" : "");
    flagBtn.title = flagTitle;
    flagBtn.setAttribute("aria-label", flagTitle);
    var flagBadge = qs(flagBtn, ".crd-flag-badge");
    flagBadge.hidden = !flagCount;
    flagBadge.textContent = flagCount || "";
    qs(node, ".crd-flagcard .crd-flag-count").textContent = flagCount ?
      flagCount + " open flag" + (flagCount === 1 ? "" : "s") + " on this session" :
      "Open-flag count needs the board's flag store wired into this view (not yet on /api/session).";

    var isLocalhost = /^(localhost|127\.0\.0\.1)/.test(location.hostname);
    qs(node, '[data-act="external"]').hidden = !isLocalhost;
  }

  // FIX (design-audit drift 3): 5b renders fork lineage as a small card at the
  // BOTTOM of the Evidence column ("Forked" / "You're on the copy; the original is
  // still running." / "Open the original"), not a full-width banner between the
  // header and the spine. Copy for the continued_from direction is 5b's, verbatim;
  // continued_as (this session forked ONWARD, no equivalent in the mock) gets the
  // same card shape with a symmetric, equally short line rather than the old
  // doc-derived paragraph.
  // FIX 3: names the target session, the same way app.js's renderForkLinks() does
  // (app.js ~1195, its inner `label(id)`). That `label` is a `const` closed over inside
  // renderForkLinks() itself — a function-local binding, not a top-level app.js
  // declaration — so it is NOT reachable from here the way a top-level app.js function
  // would be (per this module's own contract comment above). Reimplemented as
  // forkSessionLabel() below, reading the SAME top-level `sessions` array app.js's
  // label() reads (app.js:821, a bare top-level `let`, which — like a top-level function —
  // is directly reachable from every Control Room module). REQUIRED ADDITION for app.js:
  // hoist `label` out of renderForkLinks() into a top-level function (e.g.
  // `function forkSessionLabel(id)`) so both call sites share one implementation instead
  // of two copies of the same one-liner.
  function forkSessionLabel(id) {
    var list = (typeof sessions !== "undefined" && sessions) || [];
    var hit = null;
    for (var i = 0; i < list.length; i++) { if (list[i].id === id) { hit = list[i]; break; } }
    return hit ? (hit.title || hit.project || id.slice(0, 8)) : id.slice(0, 8);
  }

  function renderForkBanner(node, ctx, session, ui) {
    var card = ui.forkCard || qs(node, ".crd-forkcard");
    if (!card) return;
    if (session.continued_as) {
      card.hidden = false;
      qs(card, ".crd-fork-ico").innerHTML = svgIcon(ctx, "branch", "⑂");
      qs(card, ".crd-fork-label").textContent = "Forked";
      qs(card, ".crd-fork-body").textContent =
        "You're on the original; a fresh copy continued the work — " +
        forkSessionLabel(session.continued_as) + ".";
      qs(card, ".crd-fork-link").textContent = "Open the copy";
      ui.forkTarget = session.continued_as;
    } else if (session.continued_from) {
      card.hidden = false;
      qs(card, ".crd-fork-ico").innerHTML = svgIcon(ctx, "branch", "⑂");
      qs(card, ".crd-fork-label").textContent = "Forked";
      qs(card, ".crd-fork-body").textContent =
        "You're on the copy; the original — " + forkSessionLabel(session.continued_from) +
        " — is still running.";
      qs(card, ".crd-fork-link").textContent = "Open the original";
      ui.forkTarget = session.continued_from;
    } else {
      card.hidden = true;
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
        // FIX (design-audit drift 7): 5b lays the running segment out
        // space-between — dot+"running" on the LEFT, elapsed time on the RIGHT —
        // not one centred, concatenated string.
        inner = '<span class="crd-seg-running-label"><span class="crd-seg-dot"></span>' +
          '<span class="crd-seg-running-word mono">running</span></span>' +
          (s.elapsedMs != null ? '<span class="crd-seg-running-elapsed mono">' + esc(fmtDurMs(s.elapsedMs)) + "</span>" : "") +
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
      // Doc 01 emoji table: ⏳ (ask) -> tn-emo-a, 🤖/💬 (agent/prompt) -> base tn-emo.
      var glyphCls = m.kind === "ask" ? "tn-emo-a" : "tn-emo";
      var content = m.kind === "fail" ? '<span class="crd-mark-word mono">FAIL</span>' :
        (m.kind === "now" ? '<span class="crd-mark-word mono">NOW</span>' :
        (m.glyph ? '<span class="crd-mark-emoji ' + glyphCls + '" aria-hidden="true">' + m.glyph + "</span>" : ""));
      return '<span class="' + cls + '" style="left:' + m.pct.toFixed(3) + '%" title="' + esc(m.title) + '">' +
        '<span class="crd-mark-tick"></span>' + content + "</span>";
    }).join("");

    qs(node, ".crd-spine-first").textContent = plan.firstMs != null ? fmtClock(plan.firstMs) + " first prompt" : "—";
    qs(node, ".crd-spine-mid").textContent = plan.doneCount + " done · " + plan.runningCount +
      " running · " + plan.pendingCount + " to go";
    // FIX (design-audit drift 7): 5b's footer right cell is the literal word "now",
    // no clock time (the clock already appears on the NOW spine marker above it).
    qs(node, ".crd-spine-now").textContent = "now";

    // Check if spine is showing time-proportional segments (not equal-width fallback)
    var hasTimedSegments = plan.segments.some(function (s) { return s.elapsedMs !== null; });
    // Check if timings are approximate (from name matching, not exact id join)
    var isApproximate = session.todo_times_approximate === true;

    // Update hint text if showing approximate timings
    var hintEl = qs(node, ".crd-spine-hint");
    if (hintEl) {
      if (isApproximate && hasTimedSegments) {
        hintEl.textContent = "segment width = inferred time · click to jump the chat there";
      } else {
        hintEl.textContent = "segment width = time actually spent · click to jump the chat there";
      }
    }

    // Update aria-label to include approximate indicator
    var finalAriaLabel = plan.ariaLabel;
    if (isApproximate && hasTimedSegments) {
      finalAriaLabel += " Timings are inferred.";
    }
    qs(node, ".crd-spine").setAttribute("aria-label", finalAriaLabel);
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
    if (!open.length && !closed.length) html = emptyHtml("No decisions recorded yet", "This session hasn't raised any questions. It will fill in as it works.");
    setPanelBody(wrap, html);
  }

  function renderPRs(wrap, session) {
    // FIX 9c: the doc says PRs merely *referenced* are excluded — only ones this
    // session CREATED are listed. deriveLinks() right below already uses `p.created`
    // for exactly this distinction; this panel just wasn't applying the same filter.
    var prs = (session.prs || []).filter(function (p) { return p.created; });
    setPanelCount(wrap, prs.length || "—");
    if (!prs.length) { setPanelBody(wrap, emptyHtml("No pull requests yet", "This session hasn't opened any. It will fill in as it works.")); return; }
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
    if (!links.total) { setPanelBody(wrap, emptyHtml("No links recorded yet", "Nothing generated or referenced yet. It will fill in as it works.")); return; }
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
      // FIX 1 (capability #31: markdown rendering names "notes" explicitly).
      return '<div class="crd-note-row"><div class="crd-note-body">' + mdHtml(ctx, n.text) + "</div>" +
        '<span class="crd-note-chip ' + chip.cls + '">' + chip.text + "</span>" +
        '<span class="crd-note-actions">' +
          '<button data-act="note-copy" data-idx="' + i + '">copy</button>' +
          '<button data-act="note-remove" data-idx="' + i + '">remove</button>' +
        "</span></div>";
    }).join("");
    var body = '<div class="crd-plan-head"><span class="tn-emo-n" aria-hidden="true">📝</span> PLAN ON THE GO · ' + notes.length + " notes</div>" +
      (rows || emptyHtml("No notes queued", "Jot one below — it'll queue for delivery.")) +
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
    if (!files.length) { setPanelBody(wrap, emptyHtml("No files touched yet", "This session hasn't created or edited any. It will fill in as it works.")); return; }
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
    // FIX (design-audit drift 5): 5b keeps the Commands panel on its normal neutral
    // background and colours only the count text ("1 failing") — no full-panel red
    // tint. Toggle the tint on the count element alone, not the whole panel.
    qs(wrap, ".crd-panel-count").classList.toggle("crd-count-failing", failing > 0);
    if (!cmds.length) { setPanelBody(wrap, emptyHtml("No commands yet", "This session hasn't run any. It will fill in as it works.")); return; }
    setPanelBody(wrap, cmds.map(function (c) {
      return '<div class="crd-cmd-row" data-act="command-row" data-id="' + esc(c.id) + '">' +
        '<span class="crd-cmd-status ' + (c.ok ? "crd-cmd-ok" : "crd-cmd-fail") + '">' + (c.ok ? "ok" : "fail") + "</span>" +
        '<span class="crd-cmd-text mono">' + esc(c.cmd) + "</span></div>";
    }).join(""));
  }

  // FIX 9d: "Re-runs of an identical task collapse into one row tagged ×N, opening
  // the latest." Grouping key is the task text — the one field agents_bg entries
  // (not shells, whose shape is opaque here, see the NOTE below) carry that
  // identifies "the same task" across dispatches. Only agents_bg is grouped;
  // shells render individually as before.
  function groupAgentReruns(list) {
    var order = [], byKey = {};
    list.forEach(function (a) {
      var key = (a.task || "").trim() || ("#" + (a.aid || a.id || order.length));
      var g = byKey[key];
      if (!g) { g = { items: [] }; byKey[key] = g; order.push(g); }
      g.items.push(a);
    });
    return order.map(function (g) {
      var items = g.items.slice().sort(function (x, y) { return (parseT(y.ts) || 0) - (parseT(x.ts) || 0); });
      var runningItem = items.filter(function (x) { return x.running; })[0];
      var latest = runningItem || items[0];
      return { latest: latest, count: items.length, running: !!runningItem };
    });
  }

  function renderAgentsPanel(wrap, ui, session) {
    if (!wrap || !session) return;
    var agentsBg = session.agents_bg || [];
    var shells = session.shells || [];
    var grouped = groupAgentReruns(agentsBg);
    var runningGroups = grouped.filter(function (g) { return g.running; });
    var finishedGroups = grouped.filter(function (g) { return !g.running; });
    var runningShells = Array.isArray(shells) ? shells.filter(function (s) { return s && s.running; }) : [];
    var finishedShells = Array.isArray(shells) ? shells.filter(function (s) { return s && !s.running; }) : [];
    setPanelCount(wrap, (agentsBg.length + (Array.isArray(shells) ? shells.length : 0)) || "—");

    function agentRow(g) {
      var a = g.latest;
      // doc: "worktree (wt/wc-audit) or ×N" — one slot, mutually exclusive.
      var tag = g.count > 1 ? '<span class="crd-agent-wf mono">×' + g.count + "</span>" :
        (a.wf ? '<span class="crd-agent-wf mono">' + esc(a.wf) + "</span>" : "");
      // This background agent's OWN model (its own separate transcript —
      // parse_agents() in providers/claude.py — genuinely can and does differ
      // from the parent session's meta.model, which is exactly why the owner
      // called this surface out specifically). Empty -> no chip at all.
      var modelTag = a.model ? '<span class="crd-agent-model mono" title="' + esc(a.model) + '">' +
        esc(shortModel(a.model)) + "</span>" : "";
      return '<div class="crd-agent-row-item"><span class="crd-state-dot ' + (g.running ? "is-working" : "is-done") +
        '"></span><span class="crd-agent-title">' + esc(a.task || a.aid || "background agent") + "</span>" +
        tag + modelTag + '<button class="crd-open-link" data-act="agent-open" data-id="' + esc(a.aid) + '">open ›</button></div>'; // "opening the latest"
    }
    function shellRow(s) {
      var label = (s && (s.cmd || s.id)) || "shell";
      return '<div class="crd-agent-row-item"><span class="crd-state-dot ' + (s.running ? "is-working" : "is-done") +
        '"></span><span class="crd-agent-title mono">' + esc(label) + "</span>" +
        '<button class="crd-open-link" data-act="shell-open" data-id="' + esc(s.id || s.cmd) + '">open ›</button></div>';
    }

    var runningHtml = runningGroups.map(agentRow).join("") + runningShells.map(shellRow).join("");
    var finishedList = finishedGroups.concat(finishedShells);

    var html = runningHtml || "";
    if (finishedList.length) {
      if (ui.agentsShowFinished) {
        html += finishedList.map(function (x) { return x.latest ? agentRow(x) : shellRow(x); }).join("");
      } else {
        html += '<button class="crd-show-finished" data-act="agents-show-finished">Show ' + finishedList.length + " finished</button>";
      }
    }
    if (!html) {
      // FIX 5: Auggie's PROVIDER_NOTES.degraded IS about this panel specifically
      // ("No background-work model — capability 48 shows empty-because-it-cannot-
      // exist, not broken") — an honest-degradation card, not the generic "nothing
      // yet" empty state Claude Code (which DOES have this feature) gets.
      var note = providerNote(session);
      html = (note && note.name === "Auggie" && note.degraded) ?
        sharedStateHtml("degraded", {
          panelLabel: "AGENTS & SHELLS",
          providerLabel: note.name,
          message: note.degraded,
          readable: "What IS readable is shown in full: todos, files, and commands for this session.",
          footer: "Empty because it cannot exist — not because something broke."
        }, note.degraded) :
        emptyHtml("No agents or shells this session", "Background work will show up here once it starts.");
    }
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

  // FIX 5: session -> the matching ext_cr_dialogs.js PROVIDER_NOTES row, via that
  // module's OWN public `providerNoteFor(source)` (exported at window.CR.dialogs —
  // read, not forked). `source` is meta.source/meta.entrypoint, same field the old
  // ad-hoc isDegradedTranscript() sniffed — see providerNoteFor's own doc comment
  // in ext_cr_dialogs.js confirming that's the expected input.
  function providerNote(session) {
    try {
      var fn = window.CR && window.CR.dialogs && window.CR.dialogs.providerNoteFor;
      if (typeof fn !== "function") return null;
      var meta = session.meta || {};
      return fn(meta.source || meta.entrypoint || "");
    } catch (e) { return null; }
  }

  function renderTimeline(node, ui, session, ctx) {
    var wrap = ui.panels.timeline;
    var scrollEl = qs(wrap, ".crd-timeline-scroll");
    var filterEl = qs(wrap, ".crd-timeline-filters");
    var note = providerNote(session);
    // FIX 5: Auggie's PROVIDER_NOTES.degraded is about capability 48 (background
    // agents — handled in renderAgentsPanel below), NOT narration: its own `ok` field
    // says "Full narration/todos/files/commands." Only the two Augment-extension
    // rows are narration-degraded — excluded explicitly rather than by sniffing text.
    var narrDegraded = !!(note && note.degraded && note.name !== "Auggie");
    filterEl.style.display = narrDegraded ? "none" : "";
    if (narrDegraded) {
      setPanelCount(wrap, "");
      scrollEl.innerHTML = sharedStateHtml("degraded", {
        panelLabel: "NARRATION",
        providerLabel: note.name,
        message: note.degraded,
        readable: "What IS readable is shown in full: todos and files touched. Nothing is being hidden or approximated.",
        footer: "Empty because it cannot exist — not because something broke."
      }, note.degraded);
      return;
    }
    renderTimelineEntries(scrollEl, ui, session, false, ctx);
  }

  // FIX (defect 3): every entry is clickable to pop out — the SAME data-act
  // delegation the rest of this file uses, just naming this entry's merge key so
  // the click handler can find it in ui.timelineEntries (the current filtered,
  // newest-first list) and hand it to openTimelineEntry(). Nested data-act
  // elements (e.g. the diagram "expand" button) still win on their own click
  // since Element.closest() returns the nearest match, not this outer one.
  function entryOpenAttrs(e) {
    return ' data-act="timeline-entry-open" data-key="' + esc(e.key) + '"';
  }

  function entryHtml(e, ctx, diagram) {
    if (e.kind === "prompt") {
      return '<div class="crd-entry crd-entry-prompt"' + entryOpenAttrs(e) + '><span class="crd-entry-ts mono">' + fmtClock(e.t) + "</span>" +
        '<div class="crd-bubble crd-bubble-prompt">' + mdHtml(ctx, e.text) + "</div></div>";
    }
    if (e.kind === "narration") {
      if (diagram) {
        // FIX 2 + mermaid vendoring: prose around the fence still renders as markdown;
        // the fence itself becomes the doc's diagram card. The card's own render slot
        // (`.mmd-slot`) shows the node-pill row INSTANTLY (same as before), then
        // app.js's shared renderMermaid() — called from renderTimelineEntries() below,
        // right after this HTML lands in the DOM — upgrades it in place to the real
        // mermaid.js SVG. If that upgrade never happens (asset still loading, load
        // failed, or mermaid throws on this source) the pill row is exactly what stays:
        // it is the FALLBACK now, not a second permanent renderer. The "expand" button
        // still opens the SAME dialog ext_cr_dialogs.js already ships
        // (narration-diagram) — see openNarrationDiagram()'s own comment for what that
        // pop-out would need to draw the real diagram too.
        var pre = diagram.prefix && diagram.prefix.trim() ? '<div class="crd-narration-text">' + mdHtml(ctx, diagram.prefix) + "</div>" : "";
        var suf = diagram.suffix && diagram.suffix.trim() ? '<div class="crd-narration-text">' + mdHtml(ctx, diagram.suffix) + "</div>" : "";
        var pills = diagram.nodes.map(function (n) {
          return '<span class="cr-diagram-pill' + (n.active ? " is-active" : "") + '">' + esc(n.label) + "</span>";
        }).join("");
        var b64 = _mmdEncodeSrc(diagram.src || "");
        return '<div class="crd-entry crd-entry-narration crd-entry-diagram" data-todo-text=""' + entryOpenAttrs(e) + '>' +
          '<span class="crd-entry-ts mono">' + fmtClock(e.t) + "</span>" +
          '<div class="crd-narration-body">' + pre +
          '<div class="cr-diagram-card crd-diagram-inline">' +
            '<div class="cr-diagram-render mmd-slot" data-mmd-src="' + b64 + '">' +
              '<div class="cr-diagram-row">' + pills + "</div>" +
            "</div>" +
            '<div class="cr-diagram-caption">' + esc(diagram.family) +
              '<button class="crd-open-link crd-diagram-expand" data-act="narration-diagram" data-key="' + esc(e.key) + '">expand ›</button>' +
            "</div></div>" + suf + "</div></div>";
      }
      return '<div class="crd-entry crd-entry-narration" data-todo-text=""' + entryOpenAttrs(e) + '>' +
        '<span class="crd-entry-ts mono">' + fmtClock(e.t) + "</span>" +
        '<div class="crd-narration-text">' + mdHtml(ctx, e.text) + "</div></div>";
    }
    if (e.kind === "ask") {
      var d = e.decision;
      var q0 = (d.questions && d.questions[0]) || { q: "", options: [] };
      var opts = (q0.options || []).map(function (o) { return '<span class="crd-ask-pill">' + esc(o) + "</span>"; }).join("");
      // FIX (design-audit drift 6): 5b's ask bubble carries a mini-header
      // ("⏳ It asked you · still open") above the question — only while it's
      // still open; a closed decision doesn't claim to still be open. 5b's
      // view-only copy also drops "itself" and adds the "never writes" clause.
      var miniHead = d.open ? '<div class="crd-ask-minihead"><span class="tn-emo-a" aria-hidden="true">⏳</span>' +
        '<span class="crd-ask-minihead-label">It asked you · still open</span></div>' : "";
      return '<div class="crd-entry crd-entry-ask"' + entryOpenAttrs(e) + '><span class="crd-entry-ts mono crd-ts-ask">' + fmtClock(e.t) + "</span>" +
        '<div class="crd-bubble crd-bubble-ask">' + miniHead + '<div class="crd-ask-q">' + esc(q0.q) + "</div>" +
        '<div class="crd-ask-opts">' + opts + "</div>" +
        '<div class="crd-ask-note">View-only — answer in the session. The tracker never writes to it.</div></div></div>';
    }
    if (e.kind === "command" || e.kind === "command-fail") {
      var c = e.cmd;
      return '<div class="crd-entry crd-entry-tool' + (e.kind === "command-fail" ? " is-fail" : "") + '"' + entryOpenAttrs(e) + '>' +
        '<span class="crd-entry-ts mono ' + (e.kind === "command-fail" ? "crd-ts-fail" : "") + '">' + fmtClock(e.t) + "</span>" +
        '<div class="crd-toolrow">' + (e.kind === "command-fail" ? '<span class="crd-tool-fail">fail</span>' : "") +
        '<span class="crd-tool-name mono">' + esc(c.cmd) + "</span></div></div>";
    }
    // FIX (design-audit drift 8): a generic tool-call row — file edit/write/read or a
    // Task-tool dispatch (see mergeTimeline's own comment for exactly which fields
    // are real vs. unavailable). NOTE: no duration and no diff line-count (+/-) exist
    // anywhere on the detail dict for these — only `verb` (Write/Edit/Read/Task),
    // `target` (the full path or task desc) and, for a file row, `count` (an edit-op
    // TALLY, not a line diff) are ever rendered; a session with the design's exact
    // "0.4s · +118 −31" duration/diff pair would need the parser to start recording
    // per-op timestamps and line counts, which it does not today.
    if (e.kind === "tool") {
      return '<div class="crd-entry crd-entry-tool"' + entryOpenAttrs(e) + '>' +
        '<span class="crd-entry-ts mono">' + fmtClock(e.t) + "</span>" +
        '<div class="crd-toolrow"><span class="crd-tool-verb mono">' + esc(e.verb) + "</span>" +
        '<span class="crd-tool-name mono">' + esc(e.target) + "</span>" +
        (e.agent ? '<span class="crd-tag-agent">agent</span>' : "") +
        (e.count ? '<span class="crd-tool-count mono">' + esc(e.count) + "</span>" : "") +
        "</div></div>";
    }
    return "";
  }

  // FIX 4a: accumulates narration past the server's NARR_PAGE=60 cap on /api/session,
  // the same shape classic app.js's own narrState does (app.js:1446 + 1255-1271, read
  // not edited): `fresh` is the newest-first page /api/session ships every poll;
  // `total` is `session.narrative_total` (server.py:309, ALREADY emitted, just unread
  // by this file before now). New arrivals since the last poll are detected as
  // `total - acc.total` and prepended from `fresh` (still newest-first); older pages
  // only ever come from loadOlderNarration()'s explicit fetch, never re-derived here.
  function ensureNarrAccumulator(ui, session) {
    var sid = ui.sid;
    var fresh = session.narrative || [];
    var total = session.narrative_total != null ? session.narrative_total : fresh.length;
    var acc = ui.narrAcc;
    if (!acc || acc.sid !== sid) {
      acc = ui.narrAcc = { sid: sid, items: fresh.slice(), total: total, loading: false, error: null };
    } else {
      var delta = total - acc.total;
      if (delta > 0) acc.items = fresh.slice(0, delta).concat(acc.items);
      else if (!acc.items.length) acc.items = fresh.slice();
      acc.total = total;
    }
    acc.exhausted = acc.items.length >= acc.total;
    return acc;
  }

  // FIX 4a: real paging — fetches the EXISTING `/api/narration?id=&offset=&limit=`
  // route (server.py:313-333) for the next 60 older entries, exactly the route+shape
  // classic app.js's own narrState.more() already calls (app.js:1264-1271, read not
  // edited). This is the only network call this module makes (see the file-header
  // note) — everything else stays derived from the /api/session payload the
  // bootstrap already fetched.
  function loadOlderNarration(ctx, ui, node) {
    var acc = ui.narrAcc;
    if (!acc || acc.loading || acc.exhausted) return;
    var sid = ui.sid;
    var scrollEl = qs(node, ".crd-timeline-scroll");
    acc.loading = true;
    acc.error = null;
    renderOlderStatus(node, acc);
    fetch("/api/narration?id=" + encodeURIComponent(sid) + "&offset=" + acc.items.length + "&limit=60")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (ui.sid !== sid || ui.narrAcc !== acc) return; // navigated away mid-fetch
        acc.loading = false;
        if (!j) { acc.error = "Couldn't load older turns — try scrolling again."; renderOlderStatus(node, acc); return; }
        acc.items = acc.items.concat(j.items || []);
        if (j.total != null) acc.total = j.total;
        acc.exhausted = acc.items.length >= acc.total || !(j.items && j.items.length);
        renderOlderStatus(node, acc);
        // FIX (defect 1): older entries now sort to the BOTTOM of the newest-first
        // list (smaller t = further down), i.e. strictly AFTER whatever the reader
        // was already looking at — nothing above the viewport moves, so (unlike the
        // old oldest-first order, where older pages used to be prepended above the
        // reader and needed the scrollTop compensation that used to live here)
        // no adjustment is needed; { noTopGrowth: true } tells the render path not
        // to apply its usual "new content landed above" compensation either.
        renderTimelineEntries(scrollEl, ui, ui.lastSession, true, ctx, { noTopGrowth: true });
      })
      .catch(function () {
        if (ui.sid !== sid || ui.narrAcc !== acc) return;
        acc.loading = false;
        acc.error = "Couldn't load older turns — try scrolling again.";
        renderOlderStatus(node, acc);
      });
  }

  // FIX 6: a genuinely-detectable failure (the /api/narration fetch above failing)
  // gets the "something broke" treatment (CR.dialogs.errorState), not silence.
  function renderOlderStatus(node, acc) {
    var wrap = ui_findTimelineOlderEl(node);
    if (!wrap) return;
    if (acc.error) { wrap.hidden = false; wrap.innerHTML = errorHtml("Couldn't load older turns", acc.error); return; }
    if (acc.loading) { wrap.hidden = false; wrap.innerHTML = '<div class="crd-timeline-loading mono">loading older turns…</div>'; return; }
    wrap.hidden = true; wrap.innerHTML = "";
  }
  function ui_findTimelineOlderEl(node) {
    var scrollEl = qs(node, ".crd-timeline-scroll");
    if (!scrollEl) return null;
    var el2 = scrollEl.querySelector(".crd-timeline-older");
    if (!el2) {
      el2 = document.createElement("div");
      el2.className = "crd-timeline-older";
      el2.hidden = true;
      // FIX (defect 1): older history now lives at the BOTTOM of the newest-first
      // list (was the top, back when the list was oldest-first) — append, don't
      // insertBefore(firstChild).
      scrollEl.appendChild(el2);
    }
    return el2;
  }

  // ---- FIX (defect 2): the four legend words are individually-selectable, additive
  // filter chips now, layered on top of the existing all/talk preset. ----
  var TIMELINE_KIND_KEYS = ["prompts", "narration", "tools", "results"];
  var TIMELINE_KIND_MAP = {
    prompts: ["prompt"],
    narration: ["narration"],
    tools: ["tool"],
    // "results" = the outcome of something the session ran — both a passing and a
    // failing command are "a result".
    results: ["command", "command-fail"]
  };
  // NOTE (defect 2, ask's home): `ask` (a decision/open question) deliberately maps
  // to NONE of the four chips. It's arguably conversational, but "talk only" is
  // shipped, tested behaviour that excludes ask today (:kind==="prompt"||"narration"
  // only) — folding it into the narration or prompts bucket would make toggling
  // that chip silently start showing decisions under "talk only", changing behaviour
  // the owner explicitly said not to touch. So ask stays exactly where it already
  // was: visible only under the "all" preset (no chips active), same as before this
  // fix. A fifth "questions" chip would be the clean way to make it independently
  // selectable, if that's ever wanted — not invented here since it wasn't asked for.

  function timelineActiveKinds(ui) {
    return TIMELINE_KIND_KEYS.filter(function (k) { return ui.timelineKindsOn && ui.timelineKindsOn[k]; });
  }

  // Pure predicate: (entry, ui) -> visible? Exposed via _internal for testing.
  function timelineEntryVisible(e, ui) {
    var active = timelineActiveKinds(ui);
    if (active.length) {
      for (var i = 0; i < active.length; i++) {
        if (TIMELINE_KIND_MAP[active[i]].indexOf(e.kind) >= 0) return true;
      }
      return false;
    }
    // No chip active — defer to the existing, unchanged all/talk preset.
    return ui.timelineFilter === "talk" ? (e.kind === "prompt" || e.kind === "narration") : true;
  }

  function updateTimelineFilterButtons(wrap, ui) {
    var active = timelineActiveKinds(ui);
    qsa(wrap, ".crd-timeline-filters button[data-mode]").forEach(function (b) {
      var mode = b.getAttribute("data-mode");
      if (mode === "kind") {
        b.classList.toggle("is-active", active.indexOf(b.getAttribute("data-kind")) >= 0);
      } else {
        b.classList.toggle("is-active", !active.length && ui.timelineFilter === mode);
      }
    });
  }

  // Parity (Auggie / augment-*): names what's actually missing instead of a bare
  // "nothing recorded yet" — the owner's own complaint about the old degraded-state
  // handling elsewhere in this file (renderAgentsPanel's providerNote branch).
  var TIMELINE_KIND_NOUN = { prompts: "prompts", narration: "narration", tools: "tool activity", results: "command results" };
  function timelineEmptyMessage(ui) {
    var active = timelineActiveKinds(ui);
    if (active.length) {
      var nouns = active.map(function (k) { return TIMELINE_KIND_NOUN[k] || k; });
      return emptyHtml("No " + nouns.join(" or ") + " recorded",
        "This session hasn't produced any yet — some providers (Auggie, Augment) never will, since they carry no commands/tools data.");
    }
    if (ui.timelineFilter === "talk") return emptyHtml("No prompts or narration recorded yet", "Talk-only shows just what was said.");
    return emptyHtml("Nothing recorded yet", "The first prompt starts the conversation.");
  }

  function renderTimelineEntries(scrollEl, ui, session, force, ctx, opts) {
    if (!session) return;
    ensureNarrAccumulator(ui, session);
    var sessionForTimeline = Object.assign({}, session, { narrative: ui.narrAcc.items });
    var all = mergeTimeline(sessionForTimeline); // newest-first (defect 1)

    // FIX 2: index every diagram-bearing narration entry. Sorted ASCENDING here,
    // independent of `all`'s own (now newest-first, defect 1) order — this list's
    // consumer, openNarrationDiagram()/ext_cr_dialogs.js's narration-diagram
    // pop-out, assumes onLatest = the LAST index and onNext steps toward newer;
    // re-sorting keeps that contract true regardless of which order the timeline
    // itself renders in.
    var diagramEntries = [], diagramByKey = {};
    all.forEach(function (e) {
      if (e.kind !== "narration") return;
      var d = extractDiagram(e.text);
      if (!d) return;
      diagramByKey[e.key] = d;
      // `src` (the raw mermaid source) rides along here too, unused by THIS module's own
      // pill dialog today, but harmless -- it's what ext_cr_dialogs.js's narration-diagram
      // pop-out owner needs to draw the real diagram there as well (see
      // openNarrationDiagram()'s own comment).
      diagramEntries.push({ key: e.key, t: e.t, family: d.family, nodes: d.nodes, src: d.src });
    });
    diagramEntries.sort(function (a, b) { return a.t - b.t; });
    ui.diagramEntries = diagramEntries;

    // FIX (defect 2): the four chips (additive) win over the all/talk preset when
    // any is active; otherwise the preset behaves exactly as it did before.
    var filtered = all.filter(function (e) { return timelineEntryVisible(e, ui); });
    // FIX (defect 3): the pop-out/nav path reads this — always the current
    // filtered, newest-first list, so index 0 is "the newest visible entry".
    ui.timelineEntries = filtered;

    if (force || filtered.length !== ui.timelineSeen || !scrollEl.childNodes.length) {
      var wasStuck = ui.timelineStuckLatest;
      var prevScrollTop = scrollEl.scrollTop;
      var heightBefore = scrollEl.scrollHeight;
      var olderEl = scrollEl.querySelector(".crd-timeline-older"); // preserved across the repaint below
      scrollEl.innerHTML = filtered.length ?
        filtered.map(function (e) { return entryHtml(e, ctx, diagramByKey[e.key]); }).join("") :
        "";
      if (!filtered.length) scrollEl.innerHTML = timelineEmptyMessage(ui);
      if (olderEl) scrollEl.appendChild(olderEl); // FIX (defect 1): older status lives at the bottom now
      // Upgrade every diagram card just painted from its instant node-pill fallback to
      // the real mermaid.js render -- app.js's shared upgradeMermaidIn()/renderMermaid(),
      // the SAME function the classic UI's markdown modals call (app.js is concatenated
      // ahead of this file into one <script> tag by page.py's build_page(), so it's a
      // reachable global here, not a re-implementation).
      if (typeof upgradeMermaidIn === "function") upgradeMermaidIn(scrollEl);
      ui.timelineSeen = filtered.length;
      // FIX (defect 1): newest-first means fresh entries are prepended at the TOP
      // now, not appended at the bottom — so a reader who isn't stuck-to-latest
      // needs the opposite compensation the old oldest-first code never needed.
      // Callers that instead grew the BOTTOM (paging older history in) pass
      // {noTopGrowth:true} so this doesn't double-compensate — see loadOlderNarration.
      if (wasStuck) scrollEl.scrollTop = 0;
      else if (opts && opts.noTopGrowth) scrollEl.scrollTop = prevScrollTop;
      else scrollEl.scrollTop = prevScrollTop + (scrollEl.scrollHeight - heightBefore);
    }
  }

  // FIX (defect 3): "the timeline doesn't pop out like it is used to pop out for
  // the narration." Builds the {title, when, text} the classic modal expects from
  // whatever kind of merged-timeline entry was clicked; no new markdown renderer —
  // openText() below still does mdBlock() itself, same as openMsg()/openReq().
  function timelineEntryModalPayload(e) {
    var when = (typeof ago === "function" && e.t) ? ago(Math.max(0, (Date.now() - e.t) / 1000)) : fmtClock(e.t);
    if (e.kind === "prompt") return { title: "Prompt", when: when, text: e.text || "" };
    if (e.kind === "narration") return { title: "Narration", when: when, text: e.text || "" };
    if (e.kind === "ask") {
      var d = e.decision || {};
      var q0 = (d.questions && d.questions[0]) || { q: "", options: [] };
      var lines = [];
      if (q0.q) lines.push("**" + q0.q + "**");
      (q0.options || []).forEach(function (o) { lines.push("- " + o); });
      if (!d.open && d.answer) lines.push("\n**Decided:** " + d.answer);
      else if (d.open) lines.push("\n_View-only — answer in the session itself; the tracker never writes to it._");
      return { title: "Decision", when: when, text: lines.join("\n") };
    }
    if (e.kind === "command" || e.kind === "command-fail") {
      var c = e.cmd || {};
      return { title: "Command", when: when, text: "```\n" + (c.cmd || "") + "\n```\n\n" + (c.ok ? "✓ ok" : "✗ failed") };
    }
    // "tool": file edit/write/read or a Task-tool dispatch (mergeTimeline's own
    // comment names exactly which fields are real for these — no duration/diff
    // exists to show, same honesty rule as entryHtml's own tool row).
    var parts = ["**" + esc(e.verb || "Tool") + "** " + esc(e.target || "")];
    if (e.count) parts.push(e.count);
    if (e.agent) parts.push("via agent");
    return { title: e.verb || "Tool", when: when, text: parts.join(" · ") };
  }

  // Copies openMsg()'s own shape exactly (app.js:1618) — _setNav registers the
  // SAME prev/next/latest nav the classic modal already drives, over
  // ui.timelineEntries (the CURRENT filtered, newest-first list), not a second
  // navigation mechanism; openText is the SAME generic modal opener narration/
  // prompts/todos already use, not a Control-Room-native dialog.
  function openTimelineEntry(ui, idx) {
    if (typeof openText !== "function" || typeof _setNav !== "function") return;
    var list = ui.timelineEntries || [];
    var e = list[idx];
    if (!e) return;
    _setNav(function (i) { openTimelineEntry(ui, i); }, idx, list.length,
      { len: function () { return (ui.timelineEntries || []).length; }, live: true });
    var payload = timelineEntryModalPayload(e);
    openText(payload.title, payload.when, payload.text);
  }

  function openTimelineEntryByKey(ui, key) {
    var list = ui.timelineEntries || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].key === key) { openTimelineEntry(ui, i); return; }
    }
  }

  function openLatestTimelineEntry(ui) {
    var list = ui.timelineEntries || [];
    if (list.length) openTimelineEntry(ui, 0); // index 0 = newest (defect 1)
  }

  // FIX 2: opens ext_cr_dialogs.js's existing narration-diagram pop-out (read, not
  // edited -- it is owned by another agent right now) with the payload shape its
  // renderNarrationDiagram expects — {time, nodes:[{label,active}], edges, family,
  // onPrev, onNext, onLatest} — PLUS one extra field, `src` (the raw mermaid source),
  // which that function does not read today. It's included anyway, harmlessly, for
  // whoever next wires the pop-out to the real mermaid.js render: as things stand the
  // pop-out only ever draws the node-pill approximation (renderNarrationDiagram builds
  // its `.cr-diagram-card` straight from `nodes`, never calls app.js's shared
  // renderMermaid()/upgradeMermaidIn()) — see this module's own report for exactly
  // what that owner would need to change. `edges` stays omitted: renderNarrationDiagram
  // never reads it either.
  function openNarrationDiagram(ctx, ui, idx) {
    var list = ui.diagramEntries || [];
    var entry = list[idx];
    if (!entry || !ctx || typeof ctx.dialog !== "function") return;
    ctx.dialog("narration-diagram", {
      time: fmtClock(entry.t),
      nodes: entry.nodes,
      family: entry.family,
      src: entry.src,
      onPrev: idx > 0 ? function () { openNarrationDiagram(ctx, ui, idx - 1); } : null,
      onNext: idx < list.length - 1 ? function () { openNarrationDiagram(ctx, ui, idx + 1); } : null,
      onLatest: list.length ? function () { openNarrationDiagram(ctx, ui, list.length - 1); } : null
    });
  }

  // FIX 3: the live pinned entry. "live" is derived from data that actually exists on
  // the detail dict — idle age vs LIVE_WINDOW (the same constant/threshold every other
  // liveness check in this file uses) and session.overview.now (overview.py's own
  // synthesis of "what it's doing right now": a running background agent, an
  // in-progress todo, or the latest narration line — overview.py:20-38). Rendered as
  // its OWN fixed element below the scrolling entries (not inside .crd-timeline-scroll,
  // not part of mergeTimeline's sorted list), so re-painting it on every poll never
  // reflows the scrollable history above — satisfies the doc's "layout-stable, never
  // reflow" rule by construction rather than by a diffing trick.
  function renderLiveEntry(node, session, nowSec) {
    var wrap = ui_findLiveEl(node);
    if (!wrap) return;
    var idle = nowSec - (session.mtime || 0);
    var ov = session.overview || {};
    var live = idle < LIVE_WINDOW && !!ov.now;
    wrap.hidden = !live;
    if (!live) { wrap.innerHTML = ""; return; }
    // FIX (design-audit drift 4): 5b's live entry reads "Now · <clock>" (the real,
    // ticking wall-clock time) instead of the literal word "LIVE", plus a small
    // active-file tag top-right. REQUIRED ADDITION: there's no "file it's touching
    // right now" field on the detail dict — session.files[] (already sorted
    // newest-`last`-first by the parser) is the closest honest proxy, shown only
    // while that top file's OWN `last` is itself inside LIVE_WINDOW, never a stale one.
    var topFile = (session.files || [])[0];
    var fileTag = "";
    if (topFile) {
      var fileMs = parseT(topFile.last);
      if (fileMs != null && (nowSec - fileMs / 1000) < LIVE_WINDOW) fileTag = basename(topFile.path);
    }
    // NOTE: ov.now isn't in FIX 1's markdown list (that names "narration", the
    // narrative[].text field in the timeline — ov.now is a synthesized status string
    // that sometimes embeds a glyph prefix "⚙"/"▶" ahead of a narration snippet), so
    // it stays on plain esc() here, matching the same call already made for the
    // Session summary panel's "Now" field below.
    wrap.innerHTML =
      '<div class="crd-live-head">' +
        '<span class="crd-seg-dot" aria-hidden="true"></span>' + // reuses the spine's own pulsing-dot style (incl. its reduced-motion variant)
        '<span class="crd-live-badge mono">' + esc("Now · " + fmtClock(nowSec * 1000)) + "</span>" +
        (fileTag ? '<span class="crd-live-file mono">' + esc(fileTag) + "</span>" : "") +
      "</div>" +
      '<div class="crd-live-text">' + esc(ov.now) + "</div>";
  }
  function ui_findLiveEl(node) { return qs(node, ".crd-timeline-live"); }

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
    firstEventTime: firstEventTime,
    extractDiagram: extractDiagram,
    groupAgentReruns: groupAgentReruns,
    // defect 2 / defect 3 additions, exposed the same way as everything above:
    timelineEntryVisible: timelineEntryVisible,
    TIMELINE_KIND_MAP: TIMELINE_KIND_MAP,
    timelineEntryModalPayload: timelineEntryModalPayload,
    openTimelineEntry: openTimelineEntry
  };
})();
