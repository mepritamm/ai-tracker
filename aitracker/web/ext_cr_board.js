// Control Room — shell, top bar, session rail, triage strip, 8-tile board.
// Source of truth: design_handoff_control_room/02-shell-and-board.md.
//
// Session-list shape consumed here (verified against the real code, not
// guessed — see the exact key list in the module doc-comment at the bottom
// of this file's report). No fetch() anywhere in this file: all data
// arrives through CR.board.update(state) where state = { sessions, now }.

window.CR = window.CR || {};

(function () {
  'use strict';

  // Mirrors config.LIVE_WINDOW (server) / LIVE (app.js) — same constant,
  // same meaning, per CLAUDE.md's "Liveness is one constant" rule. This file
  // cannot import aitracker/config.py or app.js, so the literal is repeated
  // here; if that constant ever changes, this is one of the two client
  // places (app.js's `LIVE`) that must change with it.
  var LIVE_WINDOW = 300;

  // Sort rank for the board — reproduced verbatim from doc 02 "Sort order".
  var RANK = { awaiting: 0, flagged: 1, working: 2, landed: 3, idle: 4 };

  // ----------------------------------------------------------------------
  // Pure derivations — no DOM, no ctx. Easy to unit-test in isolation.
  // ----------------------------------------------------------------------

  // NOTE: the session-list dict has no `state` field. Verified shape (list
  // dict): registry.all_sessions() (aitracker/registry.py:14-76) yields each
  // provider's list() dict plus pinned/note_count/open_flags/continued_as/
  // continued_from (registry.py:68-74); providers/claude.py's list_sessions()
  // (providers/claude.py:246-284) emits id/project/cwd/title/prompt/source/
  // agent/group/groupLabel/parentId/bg/waiting/ended/mtime; providers/
  // auggie.py's list() (providers/auggie.py:160-168) emits the same key set.
  // `state` here is derived from waiting/open_flags/mtime+ended, mirroring
  // the precedence app.js's own sidebar already uses (waiting > done-if-live
  // > live > idle — aitracker/web/app.js:817-820), with open_flags slotted
  // into RANK's 'flagged' step. The doc's state vocabulary (01-foundations.md)
  // also names a sixth state, "Failing" (a command/test returned non-zero),
  // but that signal only exists in a session's parsed *detail* dict
  // (commands[].exit), never in the list-endpoint shape this module is fed —
  // and RANK itself never includes a 'failing' key either, so no tile in
  // this implementation can ever carry that state. See REQUIRED ADDITIONS
  // in the report for what a real "failing" tile would need.
  function sessionState(s, now) {
    var live = (now - (s.mtime || 0)) < LIVE_WINDOW;
    if (s.waiting) return 'awaiting';
    if (s.open_flags) return 'flagged';
    if (live && !s.ended) return 'working';
    if (live && s.ended) return 'landed';
    return 'idle';
  }

  // Rail ordering — doc 02 "Ordering (decision 2)", reproduced verbatim.
  function railOrder(sessions) {
    function byRecency(a, b) { return b.mtime - a.mtime; }
    var pinned = sessions.filter(function (s) { return s.pinned; }).sort(byRecency);
    var unpinned = sessions.filter(function (s) { return !s.pinned; }).sort(byRecency);
    return { pinned: pinned, unpinned: unpinned };
  }

  // ----------------------------------------------------------------------
  // Rail group-by (decision 2) — a layer ON TOP of railOrder()/railRow(), never
  // a fork of either. Pinned sessions always lead, in their own untouched
  // "📌 Pinned" section (railOrder's own `pinned` bucket, rendered exactly as
  // before by renderSessionRows) — grouping only ever subdivides the UNPINNED
  // bucket, so "pinned leads regardless of grouping" holds by construction in
  // every mode, including 'none'. Persisted the same way cr.boardTileCount /
  // cr.sessionsPageSize already are: a JSON-encoded value under its own key.
  var RAIL_GROUP_MODES = ['directory', 'activeness', '24h', '7d', '30d', 'none'];
  var RAIL_GROUP_LABELS = {
    directory: 'Directory', activeness: 'Activeness',
    '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days', none: 'None'
  };
  function railGroupMode() {
    var raw = null;
    try { raw = JSON.parse(localStorage.getItem('cr.railGroupBy')); } catch (e) { raw = null; }
    return (typeof raw === 'string' && RAIL_GROUP_MODES.indexOf(raw) >= 0) ? raw : 'none';
  }
  function persistRailGroupMode(mode) {
    if (RAIL_GROUP_MODES.indexOf(mode) < 0) mode = 'none';
    try { localStorage.setItem('cr.railGroupBy', JSON.stringify(mode)); } catch (e) {}
    return mode;
  }

  // 'activeness' reuses sessionState() — the ONE state derivation — never a
  // second one; ordered by the same attention-priority the board itself uses
  // (RANK), plus idle last (the rail, unlike the board, does show idle rows).
  var ACTIVENESS_GROUP_ORDER = ['awaiting', 'flagged', 'working', 'landed', 'idle'];
  var ACTIVENESS_GROUP_LABEL = {
    awaiting: 'Waiting on you', flagged: 'Flagged', working: 'Working',
    landed: 'Landed', idle: 'Idle'
  };

  // Splits an already-ordered (newest-first) array of unpinned sessions into
  // named buckets for the chosen mode, preserving each session's relative
  // order within its bucket — the recency ordering railOrder() already
  // established is inherited, never re-sorted. Returns
  // [{ label, sessions }, …], empty buckets omitted; mode 'none' returns the
  // whole array as one label-less bucket (renderSessionRows keeps its
  // original unlabeled-flat rendering in that case).
  function groupUnpinnedSessions(sessions, now, mode) {
    if (mode === 'none' || !mode) return [{ label: null, sessions: sessions }];
    if (mode === 'activeness') {
      var buckets = {};
      sessions.forEach(function (s) {
        var k = sessionState(s, now);
        (buckets[k] = buckets[k] || []).push(s);
      });
      return ACTIVENESS_GROUP_ORDER
        .filter(function (k) { return buckets[k] && buckets[k].length; })
        .map(function (k) { return { label: ACTIVENESS_GROUP_LABEL[k], sessions: buckets[k] }; });
    }
    if (mode === 'directory') {
      var order = [], byDir = {};
      sessions.forEach(function (s) {
        var k = s.cwd || '';
        if (!byDir[k]) { byDir[k] = { label: shortDir(k) || '(no directory)', sessions: [], mtime: 0 }; order.push(k); }
        byDir[k].sessions.push(s);
        byDir[k].mtime = Math.max(byDir[k].mtime, s.mtime || 0);
      });
      order.sort(function (a, b) { return byDir[b].mtime - byDir[a].mtime; });   // freshest directory first
      return order.map(function (k) { return { label: byDir[k].label, sessions: byDir[k].sessions }; });
    }
    // Time-recency modes ('24h' | '7d' | '30d'): each mode's own window is the
    // single split point — "sessions touched within this window" vs. "older
    // than it" — rather than a fixed calendar breakdown, since the owner's
    // six options name three different WINDOW SIZES to group by, not one
    // shared bucket set.
    var span = mode === '24h' ? 86400 : (mode === '7d' ? 7 * 86400 : 30 * 86400);
    var windowLabel = mode === '24h' ? 'Last 24 hours' : (mode === '7d' ? 'Last 7 days' : 'Last 30 days');
    var olderLabel = mode === '24h' ? 'Older than 24 hours' : (mode === '7d' ? 'Older than 7 days' : 'Older than 30 days');
    var recent = [], older = [];
    sessions.forEach(function (s) { ((now - (s.mtime || 0)) < span ? recent : older).push(s); });
    var out = [];
    if (recent.length) out.push({ label: windowLabel, sessions: recent });
    if (older.length) out.push({ label: olderLabel, sessions: older });
    return out;
  }

  // NOTE: doc 02 says "Agent-group tiles span 2 columns and sit last" and its
  // tile-anatomy table lists an "Agent group" row, but boardTiles' own
  // pseudocode never shows how groups are built — it only sorts/caps plain
  // sessions. Reading taken here (same bucketing key app.js's sidebar
  // already uses for its "🤖 Agents · <repo>" row, app.js:750): sessions
  // with `agent === true` are pulled out of individual ranking and folded
  // into one tile per `group` bucket (repo/sandbox), counted only while at
  // least one session in the bucket is non-idle, then appended after the
  // individually-ranked tiles, before the 8-tile cap is applied.
  function agentGroups(sessions, now) {
    var buckets = {};
    var order = [];
    sessions.forEach(function (s) {
      if (!s.agent || !s.group) return;
      if (sessionState(s, now) === 'idle') return;
      var b = buckets[s.group];
      if (!b) {
        b = { kind: 'agent-group', group: s.group, label: s.groupLabel || s.group,
              sessions: [], mtime: 0, pinned: false };
        buckets[s.group] = b;
        order.push(b);
      }
      b.sessions.push(s);
      b.mtime = Math.max(b.mtime, s.mtime || 0);
      b.pinned = b.pinned || !!s.pinned;
    });
    order.sort(function (a, b) { return b.mtime - a.mtime; });
    return order;
  }

  // Config now writes a user preference for the board's tile cap —
  // `cr.boardTileCount`, a JSON-encoded integer 3-8 (localStorage). Read fresh
  // on every call (never cached at mount) so the Config change takes effect on
  // the next 2s poll re-render with no reload. Absent/unparseable/out-of-range
  // always falls back to the hard ceiling of 8 — README decision 2's "the
  // board never renders more than 8 tiles" is never something a stored value
  // can raise, only lower.
  function boardTileCap() {
    var raw = null;
    try { raw = JSON.parse(localStorage.getItem('cr.boardTileCount')); } catch (e) { raw = null; }
    var n = (typeof raw === 'number' && isFinite(raw)) ? Math.round(raw) : 8;
    return Math.max(3, Math.min(8, n));
  }

  // Sessions destination, requirement 1: which session (if any) the tab should
  // seed the detail view with. "Last-opened" reuses the SAME `sid`/localStorage
  // tracking app.js's own pick()/track() already maintain (the live `cur` global
  // when reachable, falling back to the persisted localStorage key of the same
  // name) — not a second, parallel "last opened" concept. It only counts if that
  // session is still among the ones we currently know about (it may have aged out
  // of the 200-cap /api/list window, or the underlying log may be gone). Absent
  // that, "most-recently-active" means the newest-mtime session whose
  // sessionState() isn't 'idle' — i.e. genuinely live/waiting/flagged/just-landed,
  // not merely "exists somewhere in history". Returns null when neither exists,
  // which is requirement 2's "nothing opened yet / nothing active".
  function seedSessionId(sessions, now) {
    var lastSid = (typeof cur !== 'undefined' && cur) ? cur : null;
    if (!lastSid) {
      try { lastSid = localStorage.getItem('sid') || null; } catch (e) { lastSid = null; }
    }
    if (lastSid && sessions.some(function (s) { return s.id === lastSid; })) return lastSid;
    var active = sessions
      .filter(function (s) { return sessionState(s, now) !== 'idle'; })
      .sort(function (a, b) { return (b.mtime || 0) - (a.mtime || 0); });
    return active.length ? active[0].id : null;
  }

  // THE RULE (doc 02 "Sort order — this is the design"; README decision 2):
  // never more than 8 tiles (or fewer, per the user's cr.boardTileCount
  // preference above); pinned group on top, unpinned below, newest first
  // within each group — waiting-on-you outranks everything, including
  // recency; idle sessions never get a tile; agent-group tiles sit last.
  function boardTiles(sessions, now) {
    var individual = sessions
      // Exclude only agents that a group tile will actually represent. An agent
      // session with no `group` (agent:true, group:"") is otherwise dropped by
      // BOTH paths — agentGroups() skips it for lack of a key — and vanishes
      // from the board entirely. Verified live: 950 sessions, 1 working, 0 tiles.
      .filter(function (s) { return !(s.agent && s.group); })
      .map(function (s) { return { kind: 'session', session: s, state: sessionState(s, now) }; })
      .filter(function (t) { return t.state !== 'idle'; })
      .sort(function (a, b) {
        return (RANK[a.state] - RANK[b.state]) ||                                   // claim on attention first
               ((b.session.pinned ? 1 : 0) - (a.session.pinned ? 1 : 0)) ||          // then pinned
               (b.session.mtime - a.session.mtime);                                 // then recency
      });
    var groups = agentGroups(sessions, now);
    var tiles = individual.concat(groups).slice(0, boardTileCap());   // HARD CAP
    if (tiles.length && tiles[0].kind === 'session' && tiles[0].state === 'awaiting') {
      tiles[0].hero = true;   // single highest-ranked awaiting tile spans 2 columns
    }
    return tiles;
  }

  // Triage-strip counts. NOTE: these read the raw fields directly rather
  // than the single derived `state` above, because the three counts are not
  // mutually exclusive the way a per-tile state is — a session can be both
  // "working" and "flagged" at once, and the strip's copy ("Flagged") never
  // says these subtract from each other.
  function triageCounts(sessions, now) {
    var awaiting = 0, working = 0, flagged = 0;
    sessions.forEach(function (s) {
      var live = (now - (s.mtime || 0)) < LIVE_WINDOW;
      if (s.waiting) awaiting++;
      else if (live && !s.ended) working++;
      if (s.open_flags) flagged++;
    });
    return { awaiting: awaiting, working: working, flagged: flagged };
  }

  // NOTE: the list-endpoint shape carries one mtime per session (its latest
  // activity), not a per-minute event log, so a true events/min histogram
  // isn't derivable from this data. Approximation taken: bucket every
  // session's mtime into 18 bins across the last hour (200s/bin) and count
  // sessions landing in each bin — "activity" reads as "how many sessions
  // touched in this window", the closest honest proxy available without a
  // REQUIRED ADDITION to the list endpoint.
  function activityHistogram(sessions, now) {
    var BINS = 18, SPAN = 3600, bins = new Array(BINS).fill(0);
    sessions.forEach(function (s) {
      var age = now - (s.mtime || 0);
      if (age < 0 || age >= SPAN) return;
      var idx = BINS - 1 - Math.floor(age / (SPAN / BINS));
      if (idx >= 0 && idx < BINS) bins[idx]++;
    });
    var peak = bins.reduce(function (m, v) { return Math.max(m, v); }, 0);
    return { bins: bins, peak: peak };
  }

  function ago(seconds) {
    seconds = Math.max(0, Math.floor(seconds));
    if (seconds < 60) return 'just now';
    var m = Math.floor(seconds / 60);
    if (m < 60) return m + 'm';
    var h = Math.floor(m / 60);
    if (h < 24) return h + 'h';
    return Math.floor(h / 24) + 'd';
  }

  // NOTE: "tool" (as in "age · tool" / "project · tool") isn't a field the
  // list dict carries; the nearest available signal is `source`
  // ('' -> Claude Code, 'auggie', 'augment-vscode', 'augment-cursor'). Mapped
  // to a short display label here rather than left as the raw provider id.
  //
  // Round-5 drift (decision 4b): 5a's own board tiles render this label as a
  // lowercase literal ("2m · claude cli"), not the Title-Case product name
  // this used to show -- grep-verified against the prototype HTML itself
  // (30 hits for "claude cli", 4 for "auggie cli", 6 for "augment cursor",
  // all lowercase, all inline text, never CSS text-transform). augment-vscode
  // has no confirmed prototype label of its own (the one 4-hit "claude vs
  // code" string in the source doesn't correspond to any of this app's real
  // provider sources — it names a different product/surface combination than
  // 'augment-vscode' ever is here — so it's not adopted); 'augment vs code'
  // is this map's own extrapolation of the SAME lowercase "<vendor> <surface>"
  // pattern the other three entries actually use.
  var SOURCE_LABEL = { '': 'claude cli', 'auggie': 'auggie cli',
                        'augment-vscode': 'augment vs code', 'augment-cursor': 'augment cursor' };
  function toolLabel(source) { return SOURCE_LABEL[source || ''] || (source || 'unknown'); }

  // The ONE shortening rule for a raw model id (e.g. "claude-opus-4-8" ->
  // "opus 4.8", "claude-opus-5" -> "opus 5", "claude-sonnet-4-5-20250929" ->
  // "sonnet 4.5" -- the trailing 8-digit date stamp some historical ids carry
  // is dropped, never shown). Used by every call site that renders a model
  // (tiles/rail rows here, detail header/agents panel in ext_cr_detail.js via
  // window.CR.board.modelShort below) so there is exactly one mapping, per the
  // owner's standing "never fork an implementation" policy. An id with no
  // recognised family (sonnet/opus/haiku) passes through UNCHANGED -- an
  // unfamiliar future model id must stay visible, never get blanked. Falsy
  // input -> '' (the caller's job to render nothing for that).
  function modelShort(m) {
    if (!m) return '';
    var fam = /sonnet|opus|haiku/i.exec(m);
    if (!fam) return m;
    var rest = m.slice(fam.index + fam[0].length);
    var ver = [];
    var re = /^-(\d{1,2})(?=-|$)/;
    var mm;
    while ((mm = re.exec(rest))) { ver.push(mm[1]); rest = rest.slice(mm[0].length); }
    return fam[0].toLowerCase() + (ver.length ? ' ' + ver.join('.') : '');
  }

  // Decisions 1 & 3: the meaningful TAIL of a long cwd path -- last two path
  // segments, "…/" -prefixed when more was cut -- rather than the head. A
  // repo's basename alone (`project`) can't tell two worktrees of the same
  // repo apart (see providers/claude.py's own worktree bucketing, which keys
  // off the full cwd for exactly this reason), but the full absolute path is
  // usually too long for a compact rail row or tile title. The full path
  // always still rides along in the row's/tile's own `title` tooltip.
  function shortDir(cwd) {
    if (!cwd) return '';
    var parts = String(cwd).replace(/\/+$/, '').split('/').filter(Boolean);
    if (!parts.length) return '';
    var tail = parts.slice(-2).join('/');
    return (parts.length > 2 ? '…/' : '') + tail;
  }

  function initials(s) {
    var t = (s.title || s.project || s.id || '?').trim();
    var parts = t.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return t.slice(0, 2).toUpperCase();
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ----------------------------------------------------------------------
  // Module state (per-mount closure)
  // ----------------------------------------------------------------------

  function createBoard() {
    var root, ctx;
    var els = {};
    // 'auto' | 'open' | 'collapsed'. 'auto' (the default) defers to the
    // view/breakpoint rules in applyRailMode(); 'open'/'collapsed' are an
    // EXPLICIT user toggle and beat those rules. Before this tri-state the
    // mode was only 'open'|'collapsed' and applyRailMode() OR-ed the forced
    // conditions on top, so a click in the detail view (or on the board at
    // 1025-1279px) was written to localStorage and then silently discarded --
    // a visible button, correctly labelled, that did nothing.
    // NOTE the key is 'tracker.rail.mode', not the older 'tracker.rail'. The old
    // key's vocabulary was 'open'|'collapsed' with 'open' as the literal default,
    // so a stored 'open' was indistinguishable from 'never chose' -- and the dead
    // toggle wrote one on every frustrated click. Reading those values as an
    // EXPLICIT 'open' here would hand existing users a 232px rail in the detail
    // view they never asked for. A new key starts everyone at 'auto', which is
    // byte-for-byte the old default behaviour. The stale key is left alone.
    var railMode = (localStorage.getItem('tracker.rail.mode') || 'auto');
    var railOverlayOpen = false;      // < 1024px only: the rail as a slide-in overlay drawer
    var activeFilter = null;          // 'awaiting' | 'working' | 'flagged' | null
    var searchQuery = '';
    var focusedTileId = null;         // preserved across update() re-renders
    var selectedSessionId = null;     // for rail row highlight, set by ctx events if any
    var lastState = { sessions: [], now: Math.floor(Date.now() / 1000) };
    var expandedRailGroup = null;     // which agent-group bucket (by `group` key) is expanded
                                       // in the rail — 'rail:expandAgents' toggles this; own
                                       // state, single-module, per this file's own scope note.
    // STRUCTURAL FIX: the rail + top bar are now mounted once (see buildShell()
    // below) and persist across every view; only the content region swaps. These
    // two track WHICH view is currently showing, fed by boot.js's own
    // 'view:changed' bus event (mount()'s ctx.on below) — never re-derived from
    // DOM visibility, since after this fix the DOM visibility of the persistent
    // rail/topbar no longer changes at all.
    var currentView = 'board';        // 'board' | 'sessions' | 'detail' — drives the rail's
                                       // forced 56px orb mode in detail (doc 03 decision 1)
    var lastTopLevelView = 'board';   // 'board' | 'sessions' — which destination pill stays
                                       // active while drilled into 'detail' (requirement 4)

    // -- Sessions destination: pagination + cross-stack search state --------
    // cr.sessionsPageSize — JSON-encoded int, same convention as cr.boardTileCount
    // (config's tile-cap preference). 10/25/50 only; anything else falls back to 25.
    function readSessionsPageSize() {
      var raw = null;
      try { raw = JSON.parse(localStorage.getItem('cr.sessionsPageSize')); } catch (e) { raw = null; }
      return (raw === 10 || raw === 25 || raw === 50) ? raw : 25;
    }
    var sessionsPageSize = readSessionsPageSize();
    var sessionsPage = 0;              // 0-indexed; reset on a fresh Sessions-tab landing,
                                        // a page-size change, or a new committed search query —
                                        // never merely by a poll re-render (see update()).
    var sessionsSearchQuery = '';      // '' -> browsing; non-empty -> the last COMMITTED query
    var sessionsSearchResults = null;  // null (nothing resolved yet for this query) | Array of
                                        // /api/search hits, server-ranked, used AS-IS (never re-sorted)
    var sessionsSearchLoading = false;
    var sessionsSearchSeq = 0;         // request-sequence guard: a slow response for an older
                                        // query can never overwrite a newer one's results
    var sessionsSearchDebounce = null;

    // -- small DOM helpers ------------------------------------------------

    function h(tag, attrs, children) {
      var el = document.createElement(tag);
      attrs = attrs || {};
      Object.keys(attrs).forEach(function (k) {
        if (k === 'class') el.className = attrs[k];
        else if (k === 'html') el.innerHTML = attrs[k];
        else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), attrs[k]);
        else if (attrs[k] !== null && attrs[k] !== undefined) el.setAttribute(k, attrs[k]);
      });
      (children || []).forEach(function (c) {
        if (c == null) return;
        el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
      });
      return el;
    }

    function icon(name, fallbackPath) {
      if (ctx && typeof ctx.icon === 'function') {
        var svg = ctx.icon(name);
        if (svg) {
          var wrap = document.createElement('span');
          wrap.innerHTML = svg;
          return wrap.firstElementChild || wrap;
        }
      }
      // Minimal inline fallback so the shell still renders if ctx.icon is
      // missing a glyph — not a substitute for the real glyph set.
      var svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svgEl.setAttribute('viewBox', '0 0 24 24');
      svgEl.setAttribute('fill', 'none');
      svgEl.setAttribute('stroke', 'currentColor');
      svgEl.setAttribute('stroke-width', '2');
      svgEl.innerHTML = fallbackPath || '<circle cx="12" cy="12" r="8"/>';
      return svgEl;
    }

    // The rail's brand mark is the PRODUCT logo -- the #brandMark symbol defined
    // once in index.html and shared with the classic dashboard. It used to be
    // icon('spark'), which drew a generic outlined sparkle: a stand-in, not the
    // logo. Colours come from tokens on .cr-rail-brand, so it tints per theme.
    function brandMark() {
      var wrap = document.createElement('span');
      wrap.innerHTML = '<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">'
        + '<use href="#brandMark"/></svg>';
      return wrap.firstElementChild;
    }

    function emoji(char, cls, label) {
      return h('span', { class: 'tn-emo' + (cls ? ' ' + cls : ''), 'aria-hidden': 'true', title: label || null },
        [char]);
    }

    // -- shell (built once) ------------------------------------------------

    // STRUCTURAL FIX (the app-shell-disappears-in-detail bug): previously this
    // function built the rail AND the top bar AND the triage+board grid all as
    // children of `root`, and `root` itself was the element boot.js's showView()
    // hid/showed per view — so navigating into a session hid the rail and top
    // bar along with the board. Now `root` is the PERSISTENT shell (never
    // hidden); the rail (els.rail) and top bar (els.topbar) are built once here
    // and never touched by view switching. Only the three children of
    // els.content — els.viewBoard / els.viewSessions / els.viewDetail — toggle
    // `hidden`, exactly like the old top-level #cr-view-board/#cr-view-detail
    // slots did (same `.cr-view`/[hidden] CSS contract from ext_cr_boot.css,
    // just one level deeper in the DOM).
    function buildShell() {
      // BUG FIX (theme shadowing): this used to also add `tracker-next` here
      // ("defensively", per this file's old header comment) — but `root` (the
      // `#cr-shell` element boot.js hands in) is always a DESCENDANT of
      // #nextRoot, which already carries `tracker-next` (and the JS-toggled
      // `is-dark`). ext_cr.css's `.tracker-next { --surface-raised: #FFFFFF; ... }`
      // rule is unconditional: any element that ALSO carries the bare class
      // re-declares every light-theme custom property directly on itself,
      // shadowing the dark values it would otherwise inherit from #nextRoot —
      // regardless of that element's own ancestry. That is exactly what made
      // `#cr-shell` (and everything under it: rail, top bar, board) render
      // light while `#nextRoot` correctly resolved dark. `.tracker-next .cr-app`
      // below (a descendant selector, not `.tracker-next.cr-app` — see
      // ext_cr_board.css) still matches this element via its #nextRoot
      // ancestor, so `cr-app` alone is enough for this file's own selectors.
      root.classList.add('cr-app');
      root.innerHTML = '';

      els.rail = h('aside', { class: 'cr-rail', role: 'complementary', 'aria-label': 'All sessions' });
      els.main = h('div', { class: 'cr-main' });
      els.topbar = h('header', { class: 'cr-topbar' });

      // The swappable content region + its three slots. Board and Sessions are
      // built inline here (both reuse this module's own rail-ordering/rendering
      // code — see renderSessionRows below); Detail is left an EMPTY slot for
      // CR.detail.mount() to fill, exactly as boot.js used to hand it the whole
      // top-level #cr-view-detail before this fix.
      els.content = h('div', { class: 'cr-content' });
      els.viewBoard = h('div', { class: 'cr-view cr-view--board', id: 'cr-view-board' });
      els.viewSessions = h('div', { class: 'cr-view cr-sessions-view', id: 'cr-view-sessions' });
      els.viewDetail = h('div', { class: 'cr-view', id: 'cr-view-detail' });
      els.viewSessions.hidden = true;
      els.viewDetail.hidden = true;

      els.triage = h('div', { class: 'cr-triage' });
      els.boardScroll = h('div', { class: 'cr-board-scroll' });
      els.board = h('div', { class: 'cr-board', role: 'list', 'aria-label': 'Sessions needing attention' });
      els.capfooter = h('div', { class: 'cr-capfooter' });
      els.boardScroll.appendChild(els.board);
      els.boardScroll.appendChild(els.capfooter);
      els.viewBoard.appendChild(els.triage);
      els.viewBoard.appendChild(els.boardScroll);

      // NOTE: 02-shell-and-board.md never defines what the "Sessions" top-bar
      // destination shows — the doc's only uses of the word "Sessions" are the
      // rail's own "Sessions — N · newest first" group header and the generic
      // "session" prose, never a screen spec. Per the owner's instruction, this
      // is NOT a new design: it is the minimal honest version — the same
      // session list the rail shows, reusing the rail's OWN ordering/grouping
      // (railOrder/agentGroups, via renderSessionRows below) rather than a
      // second implementation.
      els.sessionsHeader = h('div', { class: 'cr-sessions-header' }, ['All sessions']);

      // Its own search box — the persistent rail's search stays local to
      // whatever's already loaded, but this one is shown only while the rail
      // itself is hidden (requirement 2), and it must reach the WHOLE stack
      // (requirement 5), not just the loaded page, so it is wired to
      // scheduleSessionsSearch()/GET /api/search rather than the rail's
      // client-side railRowsFor() filter.
      els.sessionsSearchWrap = h('div', { class: 'cr-rail-search cr-sessions-search' }, [
        icon('search', '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>'),
        (els.sessionsSearchInput = h('input', {
          type: 'text', placeholder: 'Search every session', 'aria-label': 'Search every session',
          oninput: function (e) { scheduleSessionsSearch(e.target.value); }
        })),
      ]);

      els.sessionsList = h('div', { class: 'cr-sessions-list' });

      // Pagination (requirement 4): a page-size selector (10/25/50, persisted)
      // plus next/previous — shared between the browse list and search results
      // (requirement 5's "paginate search results the same way").
      els.sessionsPageLabel = h('span', { class: 'cr-sessions-pager-label' }, ['']);
      els.sessionsPageSizeSelect = h('select', {
        class: 'cr-sessions-pagesize', 'aria-label': 'Sessions per page',
        onchange: function (e) { setSessionsPageSize(parseInt(e.target.value, 10)); }
      }, [10, 25, 50].map(function (n) { return h('option', { value: String(n) }, [n + ' / page']); }));
      els.sessionsPrev = h('button', {
        type: 'button', class: 'cr-sessions-pager-btn',
        onclick: function () { changeSessionsPage(-1); }
      }, ['‹ Prev']);
      els.sessionsNext = h('button', {
        type: 'button', class: 'cr-sessions-pager-btn',
        onclick: function () { changeSessionsPage(1); }
      }, ['Next ›']);
      els.sessionsPager = h('div', { class: 'cr-sessions-pager' },
        [els.sessionsPageLabel, els.sessionsPageSizeSelect, els.sessionsPrev, els.sessionsNext]);

      els.viewSessions.appendChild(els.sessionsHeader);
      els.viewSessions.appendChild(els.sessionsSearchWrap);
      els.viewSessions.appendChild(els.sessionsList);
      els.viewSessions.appendChild(els.sessionsPager);

      els.content.appendChild(els.viewBoard);
      els.content.appendChild(els.viewSessions);
      els.content.appendChild(els.viewDetail);

      els.main.appendChild(els.topbar);
      els.main.appendChild(els.content);

      root.appendChild(els.rail);
      root.appendChild(els.main);

      // < 1024px only (see the media query in the CSS): a scrim behind the
      // overlay-open rail, in front of the board. Created once; visibility
      // is a class toggle, kept in lockstep with cr-rail--overlay-open.
      els.railScrim = h('div', { class: 'cr-rail-scrim', onclick: closeRailOverlay });
      root.appendChild(els.railScrim);

      buildRailShell();
      buildTopBar();
      buildTriageShell();
      applyRailMode();
      bindKeyboard();
      bindResize();
    }

    // -- rail ---------------------------------------------------------------

    function buildRailShell() {
      els.rail.innerHTML = '';

      var header = h('div', { class: 'cr-rail-header' }, [
        h('span', { class: 'cr-rail-brand', title: 'AI Session Tracker' }, [brandMark()]),
        h('div', { class: 'cr-rail-title-group' }, [
          h('span', { class: 'cr-rail-label' }, ['All sessions']),
        ]),
        (els.railCount = h('span', { class: 'cr-rail-count' }, ['0'])),
        (els.railChevron = h('button', {
          class: 'cr-rail-chevron', type: 'button',
          title: 'Collapse session rail', 'aria-label': 'Collapse session rail',
          onclick: toggleRail
        }, [icon('chevron', '<path d="M15 6l-6 6 6 6"/>')])),
      ]);
      els.rail.appendChild(header);

      els.railSearchWrap = h('div', { class: 'cr-rail-search' }, [
        icon('search', '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>'),
        (els.railSearchInput = h('input', {
          type: 'text', placeholder: 'Search', 'aria-label': 'Search sessions',
          oninput: function (e) { searchQuery = e.target.value.toLowerCase(); renderRail(lastState); }
        })),
        h('kbd', {}, ['⌘K']),
      ]);
      els.rail.appendChild(els.railSearchWrap);

      // Decision 2: the rail's group-by control. Persists via cr.railGroupBy
      // (railGroupMode()/persistRailGroupMode() above); renderSessionRows()
      // reads the persisted mode fresh on every render, so this select is the
      // only piece of UI needed — no extra state threaded through here.
      els.railGroupWrap = h('div', { class: 'cr-rail-groupby' }, [
        h('label', { for: 'cr-rail-groupby-select', class: 'cr-rail-groupby-label' }, ['Group by']),
        (els.railGroupSelect = h('select', {
          id: 'cr-rail-groupby-select', class: 'cr-rail-groupby-select', 'aria-label': 'Group sessions by',
          onchange: function (e) {
            persistRailGroupMode(e.target.value);
            renderRail(lastState);
            if (currentView === 'sessions') renderSessionsView(lastState);
          }
        }, RAIL_GROUP_MODES.map(function (m) { return h('option', { value: m }, [RAIL_GROUP_LABELS[m]]); }))),
      ]);
      els.railGroupSelect.value = railGroupMode();
      els.rail.appendChild(els.railGroupWrap);

      els.railList = h('div', { class: 'cr-rail-list' });
      els.rail.appendChild(els.railList);

      els.railFooter = h('div', { class: 'cr-rail-footer' }, ['scroll · 0 more']);
      els.rail.appendChild(els.railFooter);
    }

    function toggleRail() {
      // Requirement 2: the rail is unconditionally hidden while the Sessions
      // tab is showing its no-seed browse list — there is nothing to toggle.
      if (currentView === 'sessions') return;
      // At or below 1024px the rail isn't in-flow (open vs collapsed doesn't
      // apply — doc 02's breakpoint table has it "hidden; rail becomes an
      // overlay"), so the same toggle drives the overlay drawer instead.
      // BLOCKER 4: threshold is `<= 1024` (not `< 1024`) to agree with the
      // CSS's `max-width: 1024px` rail-overlay tier — both files now treat
      // 1024px itself as compact, matching ext_cr_detail.css's own boundary.
      if (window.innerWidth <= 1024) {
        if (railOverlayOpen) closeRailOverlay(); else openRailOverlay();
        return;
      }
      // Flip against what is ACTUALLY on screen, not against the stored mode:
      // under 'auto' the two disagree (detail view and the 1025-1279px tier are
      // collapsed while railMode still reads 'auto'/'open'), and flipping the
      // stored value there produced a no-op first click.
      railMode = els.rail.classList.contains('cr-rail--collapsed') ? 'open' : 'collapsed';
      localStorage.setItem('tracker.rail.mode', railMode);
      applyRailMode();
    }

    function railOverlayLabels() {
      var label = railOverlayOpen ? 'Close session rail' : 'Open session rail';
      [els.railChevron, els.railToggleTop].forEach(function (btn) {
        if (!btn) return;
        btn.setAttribute('title', label);
        btn.setAttribute('aria-label', label);
      });
    }

    function openRailOverlay() {
      railOverlayOpen = true;
      els.rail.classList.add('cr-rail--overlay-open');
      if (els.railScrim) els.railScrim.classList.add('cr-rail-scrim--visible');
      railOverlayLabels();
    }

    // Closes the mobile overlay drawer. Called on: the toggle (chevron / top-bar
    // button), the scrim click, Escape (bindKeyboard), selecting a session
    // (openSession), and a resize back above 1024px (bindResize) — safe to call
    // when already closed.
    function closeRailOverlay() {
      railOverlayOpen = false;
      els.rail.classList.remove('cr-rail--overlay-open');
      if (els.railScrim) els.railScrim.classList.remove('cr-rail-scrim--visible');
      railOverlayLabels();
    }

    function applyRailMode() {
      // Doc 03 "The collapsed orb rail" / README decision 1: in the detail view
      // the rail defaults to the collapsed 56px orb rail (under 'auto' mode);
      // explicit toggles override it, regardless of the board's own
      // open/collapsed preference or breakpoint. `.cr-rail--detail` (56px, see
      // ext_cr_board.css) wins over `.cr-rail--collapsed` (48px, doc 02's rail
      // table — the board's own collapse-toggle width, left as-is) where both.
      var isDetail = (currentView === 'detail');
      // Requirement 2: no last-opened/active session -> the Sessions tab shows
      // the browse list and the rail is hidden outright (not merely collapsed
      // to the 48/56px orb strip — genuinely not present). This is the ONLY
      // view where the rail disappears; board and detail always show it.
      var hideRail = (currentView === 'sessions');
      els.rail.classList.toggle('cr-rail--hidden', hideRail);
      if (els.railToggleTop) els.railToggleTop.hidden = hideRail;
      // BLOCKER 4: lower bound is `>= 1025` (not `>= 1024`) so this in-flow
      // "collapsed icon rail" tier (1025-1279) never overlaps the <=1024
      // rail-overlay tier above — 1024 itself is now overlay-only, agreeing
      // with the CSS's `max-width: 1024px` boundary.
      // The detail view and the 1025-1279px tier collapse the rail BY DEFAULT,
      // but an explicit toggle overrides them -- otherwise the control is dead.
      var autoCollapsed = isDetail || (window.innerWidth < 1280 && window.innerWidth >= 1025);
      var collapsed = (railMode === 'auto') ? autoCollapsed : (railMode === 'collapsed');
      els.rail.classList.toggle('cr-rail--collapsed', collapsed);
      // 56px orb styling is the COLLAPSED detail rail; once the user expands it
      // explicitly the full 232px row rail must win, so --detail comes off too.
      els.rail.classList.toggle('cr-rail--detail', isDetail && collapsed);
      var label = collapsed ? 'Expand session rail' : 'Collapse session rail';
      els.railChevron.setAttribute('title', label);
      els.railChevron.setAttribute('aria-label', label);
      if (els.railToggleTop) {
        els.railToggleTop.setAttribute('title', label);
        els.railToggleTop.setAttribute('aria-label', label);
      }
      if (!hideRail) renderRail(lastState);
    }

    function bindResize() {
      window.addEventListener('resize', function () {
        var underlay = window.innerWidth <= 1024;
        if (!underlay) closeRailOverlay();   // resizing back above 1024px cleans up the overlay + scrim
        applyRailMode();
      });
    }

    // `qOverride` (optional): the Sessions destination's browse mode has no
    // local substring filter of its own (requirement 5's cross-stack search is
    // a completely separate, server-backed box) — it passes '' explicitly so
    // a value left over in the RAIL's own search box (els.railSearchInput,
    // hidden throughout the Sessions destination per requirement 2) can never
    // silently filter a view whose own search input says something different.
    // The rail's own unpaginated call (renderRail) omits it, so its behaviour
    // is unchanged: still filtered by its own live `searchQuery`.
    function railRowsFor(sessions, qOverride) {
      var q = (typeof qOverride === 'string') ? qOverride : searchQuery;
      if (!q) return sessions;
      return sessions.filter(function (s) {
        return ((s.title || '') + ' ' + (s.project || '') + ' ' + (s.prompt || '')).toLowerCase().indexOf(q) >= 0;
      });
    }

    function railRowMeta(s, now) {
      if (s.open_flags) return '🚩 ' + s.open_flags;
      if (s.bg) return '🤖 ' + s.bg;
      return ago(now - (s.mtime || 0));
    }

    // BUG FIX: todoTicks() (the full tick bar) was only ever called from the board
    // tile builder — rail rows showed no progress at all despite todo_total/todo_done
    // being on every session in the list dict. Rail rows are tight (title, directory,
    // model already ride these three lines), so this is a compact "N/M" rather than
    // the tick bar; the current in-progress todo's text rides the row's existing
    // `title` tooltip instead of taking more row space.
    function railTodoLabel(s) {
      if (typeof s.todo_total !== 'number' || !s.todo_total) return '';
      return (s.todo_done || 0) + '/' + s.todo_total;
    }

    // Shared by the rail's own full-row mode AND the Sessions destination
    // (renderSessionsView below) — the owner's instruction is that both render
    // from the SAME ordering/grouping code, not a second copy. Appends group
    // headers + rows + folded agent-group rows into `container`, using the
    // exact same railOrder()/railRow()/agent-bucket logic the rail always had.
    //
    // `opts` (optional) = { page, pageSize } — the Sessions destination's own
    // pagination window over the pinned+unpinned individual sessions (requirement
    // 4). The rail's own unpaginated call (renderRail below) omits it entirely,
    // so its behaviour — and the ordering it produces — is byte-for-byte
    // unchanged from before pagination existed. The folded agent-group rows are
    // deliberately NOT paginated (there are only ever a handful of groups, one
    // per project/sandbox) — they're appended once, on the last page, same as
    // the rail always showed them after every individual session.
    //
    // Returns { total, shown }: `total` is the full pinned+unpinned individual
    // count (unaffected by the page window — the rail's "scroll · N more"
    // footer and the Sessions pager both need the UNWINDOWED total), `shown` is
    // how many individual rows this call actually rendered.
    function renderSessionRows(container, sessions, now, opts) {
      var filtered = railRowsFor(sessions.filter(function (s) { return !s.agent; }), opts ? '' : undefined);
      var order = railOrder(filtered);
      var flat = order.pinned.concat(order.unpinned);   // pinned-first, newest-first within each
      var agentBuckets = {};
      sessions.filter(function (s) { return s.agent && s.group; }).forEach(function (s) {
        var b = agentBuckets[s.group] || (agentBuckets[s.group] = { label: s.groupLabel || s.group, n: 0, live: 0, mtime: 0, sessions: [] });
        b.n++;
        if ((now - (s.mtime || 0)) < LIVE_WINDOW) b.live++;
        b.mtime = Math.max(b.mtime, s.mtime || 0);
        b.sessions.push(s);
      });

      var windowed = flat, isLastPage = true;
      if (opts && opts.pageSize) {
        var startIdx = (opts.page || 0) * opts.pageSize;
        windowed = flat.slice(startIdx, startIdx + opts.pageSize);
        isLastPage = (startIdx + opts.pageSize) >= flat.length;
      }
      var pinnedShown = windowed.filter(function (s) { return s.pinned; });
      var unpinnedShown = windowed.filter(function (s) { return !s.pinned; });

      if (pinnedShown.length) {
        container.appendChild(h('div', { class: 'cr-rail-group-header' },
          ['📌 Pinned — ' + pinnedShown.length + ' · newest first']));
        pinnedShown.forEach(function (s) { container.appendChild(railRow(s, now)); });
      }
      if (unpinnedShown.length || !opts) {
        // Decision 2: pinned already led above, untouched by any mode — this
        // is the "layer on top" of the SAME unpinnedShown rows/order. Mode
        // 'none' renders byte-for-byte what this always rendered (a single
        // "Sessions — N · newest first" header); every other mode replaces
        // that one header with one per sub-group, in groupUnpinnedSessions()'s
        // order, each still just railRow() calls over the SAME rows.
        var groupMode = railGroupMode();
        if (groupMode === 'none') {
          container.appendChild(h('div', { class: 'cr-rail-group-header' },
            ['Sessions — ' + unpinnedShown.length + ' · newest first']));
          unpinnedShown.forEach(function (s) { container.appendChild(railRow(s, now)); });
        } else {
          groupUnpinnedSessions(unpinnedShown, now, groupMode).forEach(function (g) {
            container.appendChild(h('div', { class: 'cr-rail-group-header' },
              [g.label + ' — ' + g.sessions.length]));
            g.sessions.forEach(function (s) { container.appendChild(railRow(s, now)); });
          });
        }
      }

      if (!opts || isLastPage) {
        Object.keys(agentBuckets).forEach(function (g) {
          var b = agentBuckets[g];
          var isOpen = expandedRailGroup === g;
          container.appendChild(h('div', {
            class: 'cr-rail-agentrow' + (isOpen ? ' cr-rail-agentrow--open' : ''),
            tabindex: '0', role: 'button', 'aria-expanded': isOpen ? 'true' : 'false',
            title: '🤖 Agents · ' + b.label, 'aria-label': '🤖 Agents · ' + b.label,
            onclick: function () { ctx && ctx.emit && ctx.emit('rail:expandAgents', { group: g }); },
            onkeydown: function (e) { if (e.key === 'Enter') ctx && ctx.emit && ctx.emit('rail:expandAgents', { group: g }); }
          }, [emoji('🤖', '', null), '🤖 Agents · ' + esc(b.label) + (b.live ? ' (' + b.live + ' live)' : ''),
              h('span', { class: 'cr-rail-agentchevron' }, [icon('chevron', '<path d="M9 6l6 6-6 6"/>')])]));
          if (isOpen) {
            b.sessions.slice().sort(function (a, c) { return (c.mtime || 0) - (a.mtime || 0); })
              .forEach(function (s) { container.appendChild(railRow(s, now)); });
          }
        });
      }

      return { total: flat.length, shown: windowed.length };
    }

    function renderRail(state) {
      if (!els.railList) return;
      var sessions = state.sessions || [], now = state.now;
      els.railCount.textContent = String(sessions.length);

      var scrollTop = els.railList.scrollTop;
      var activeEl = document.activeElement;
      var activeWasSearch = (activeEl === els.railSearchInput);

      var collapsed = els.rail.classList.contains('cr-rail--collapsed');
      els.railList.innerHTML = '';

      var shown;
      if (collapsed) {
        var filtered = railRowsFor(sessions.filter(function (s) { return !s.agent; }));
        var order = railOrder(filtered);
        renderCollapsedOrbs(order, now);
        shown = order.pinned.length + order.unpinned.length;
      } else {
        shown = renderSessionRows(els.railList, sessions, now).total;
      }

      var more = sessions.length - shown;
      els.railFooter.textContent = 'scroll · ' + Math.max(0, more) + ' more';

      els.railList.scrollTop = scrollTop;
      if (activeWasSearch) els.railSearchInput.focus();
    }

    // ------------------------------------------------------------------
    // Sessions destination: cross-stack search (requirement 5).
    //
    // list_sessions(limit=200) never sends the browser more than 200 sessions
    // per provider — measured on this machine: 378 real Claude sessions, so
    // client-side filtering over the loaded `sessions` array would silently
    // miss roughly a third of the history. GET /api/search?q= (registry.
    // search_all -> search_sessions(q, limit=500) per provider) is the
    // existing server-side mechanism that actually covers the whole stack, so
    // this calls that — no new endpoint, no client-side re-filtering of it.
    // ------------------------------------------------------------------

    // A raw hit from /api/search only carries {id, project, title, agent,
    // matches, snippet, inQuery, titleMatch, mtime} — not the full list-dict
    // shape railRow()/sessionState() read (waiting/ended/open_flags/pinned/
    // cwd/source/…). Where the hit's id happens to still be in the locally
    // loaded `sessions` list (true for the large majority — recent/relevant
    // hits are exactly what's likely to be in the 200-cap window), borrow the
    // real fields from there so the row's dot colour / pin marker / flags are
    // accurate; otherwise degrade honestly (no fabricated state) rather than
    // guessing. This is decoration only — it never changes which hits came
    // back or their order.
    function decorateSearchHits(hits, sessions) {
      var byId = {};
      (sessions || []).forEach(function (s) { byId[s.id] = s; });
      return hits.map(function (hit) {
        var known = byId[hit.id];
        return {
          id: hit.id,
          title: hit.title,
          project: hit.project,
          agent: hit.agent,
          mtime: hit.mtime,
          snippet: hit.snippet,
          pinned: known ? !!known.pinned : false,
          waiting: known ? known.waiting : false,
          open_flags: known ? known.open_flags : 0,
          ended: known ? known.ended : false,
          bg: known ? known.bg : '',
          cwd: known ? known.cwd : '',
          source: known ? known.source : '',
        };
      });
    }

    // Debounced so typing doesn't fire a request per keystroke; `sessionsSearchSeq`
    // is the stale-response guard — a slow response for an older query can never
    // overwrite a newer one's results, because it's only applied if its own
    // sequence number is still the latest one issued.
    function scheduleSessionsSearch(raw) {
      clearTimeout(sessionsSearchDebounce);
      sessionsSearchDebounce = setTimeout(function () { commitSessionsSearch(raw); }, 300);
    }
    function commitSessionsSearch(raw) {
      var q = (raw || '').trim();
      sessionsSearchQuery = q;
      sessionsPage = 0;   // a new committed query always starts back at page 1
      if (!q) {
        sessionsSearchResults = null;
        sessionsSearchLoading = false;
        renderSessionsView(lastState);
        return;
      }
      sessionsSearchLoading = true;
      renderSessionsView(lastState);   // paint "Searching…" immediately
      if (typeof fetch !== 'function') { sessionsSearchLoading = false; return; }
      var seq = ++sessionsSearchSeq;
      fetch('/api/search?q=' + encodeURIComponent(q)).then(function (r) {
        return r.json();
      }).then(function (hits) {
        if (seq !== sessionsSearchSeq) return;   // a newer query already superseded this one
        sessionsSearchResults = Array.isArray(hits) ? hits : [];
        sessionsSearchLoading = false;
        renderSessionsView(lastState);
      }).catch(function () {
        if (seq !== sessionsSearchSeq) return;
        sessionsSearchResults = [];
        sessionsSearchLoading = false;
        renderSessionsView(lastState);
      });
    }

    // ------------------------------------------------------------------
    // Sessions destination: pagination (requirement 4). Paginates the browse
    // list the SAME way as search results, per the owner's decision.
    // ------------------------------------------------------------------
    function sessionsTotalCount(sessions) {
      if (sessionsSearchQuery) return (sessionsSearchResults || []).length;
      return railRowsFor(sessions.filter(function (s) { return !s.agent; }), '').length;
    }
    function changeSessionsPage(delta) {
      sessionsPage = Math.max(0, sessionsPage + delta);
      renderSessionsView(lastState);
    }
    function setSessionsPageSize(n) {
      if (n !== 10 && n !== 25 && n !== 50) n = 25;
      sessionsPageSize = n;
      sessionsPage = 0;
      try { localStorage.setItem('cr.sessionsPageSize', JSON.stringify(n)); } catch (e) {}
      renderSessionsView(lastState);
    }
    function updateSessionsPagerUI(total) {
      if (!els.sessionsPageLabel) return;
      var maxPage = Math.max(0, Math.ceil(total / sessionsPageSize) - 1);
      var start = total ? (sessionsPage * sessionsPageSize + 1) : 0;
      var end = Math.min(total, (sessionsPage + 1) * sessionsPageSize);
      els.sessionsPageLabel.textContent = total ? (start + '–' + end + ' of ' + total) : '0 of 0';
      els.sessionsPageSizeSelect.value = String(sessionsPageSize);
      els.sessionsPrev.disabled = (sessionsPage <= 0);
      els.sessionsNext.disabled = (sessionsPage >= maxPage);
    }

    // The Sessions destination's content (requirement 3/4/5): browsing reuses
    // renderSessionRows (same ordering/grouping the rail always used, no second
    // implementation), paginated; searching renders the server's ranked hits
    // AS-IS (no railOrder() re-sort — burying an exact match under unrelated
    // pinned sessions would defeat the point of search), also paginated.
    // Mirrors renderRail's own scroll-position preservation across polls. Only
    // ever touches els.sessionsList's contents — never rebuilds the search
    // input/pager controls themselves, so typing focus survives a poll re-render.
    function renderSessionsView(state) {
      if (!els.sessionsList) return;
      var sessions = state.sessions || [], now = state.now;
      var totalCount = sessionsTotalCount(sessions);
      var maxPage = Math.max(0, Math.ceil(totalCount / sessionsPageSize) - 1);
      if (sessionsPage > maxPage) sessionsPage = maxPage;   // clamp BEFORE rendering/slicing

      var scrollTop = els.sessionsList.scrollTop;
      els.sessionsList.innerHTML = '';

      if (sessionsSearchQuery) {
        var hits = decorateSearchHits(sessionsSearchResults || [], sessions);
        var start = sessionsPage * sessionsPageSize;
        var page = hits.slice(start, start + sessionsPageSize);
        if (sessionsSearchLoading && !hits.length) {
          els.sessionsList.appendChild(h('div', { class: 'cr-sessions-empty' }, ['Searching…']));
        } else if (!page.length) {
          els.sessionsList.appendChild(h('div', { class: 'cr-sessions-empty' },
            ['No sessions match “' + sessionsSearchQuery + '”.']));
        } else {
          page.forEach(function (s) { els.sessionsList.appendChild(railRow(s, now)); });
        }
      } else {
        renderSessionRows(els.sessionsList, sessions, now, { page: sessionsPage, pageSize: sessionsPageSize });
      }

      els.sessionsList.scrollTop = scrollTop;
      updateSessionsPagerUI(totalCount);
    }

    // Requirement 1/2 — deciding what the Sessions pill actually opens. Sets
    // `lastTopLevelView` itself (rather than waiting on the 'view:changed'
    // handler below, which only tracks it for 'board'/'sessions' navigations)
    // so the Sessions pill reads as active even when this routes straight into
    // the detail view, per requirement 4's "the pill you drilled in from stays
    // active" rule.
    function openSessionsDestination() {
      lastTopLevelView = 'sessions';
      updateDestinationActive();
      var seed = seedSessionId(lastState.sessions || [], lastState.now);
      if (seed) {
        openSession(seed);   // ctx.go('detail', seed) — rail stays present (56px detail orb mode)
      } else {
        sessionsPage = 0;    // a fresh landing on the browse list always starts at page 1
        if (ctx && ctx.go) ctx.go('sessions');
      }
    }

    function renderCollapsedOrbs(order, now) {
      order.pinned.forEach(function (s) { els.railList.appendChild(railOrb(s, now)); });
      if (order.pinned.length && order.unpinned.length) {
        els.railList.appendChild(h('div', { class: 'cr-orb-divider' }));
      }
      order.unpinned.forEach(function (s) { els.railList.appendChild(railOrb(s, now)); });
    }

    // BUG FIX: the prototype colour-codes all FIVE states on both rail rows
    // and collapsed orbs (01-foundations.md's state vocabulary) — this used to
    // cover only waiting/live/flagged, with no landed colour anywhere and no
    // flagged colour on rail rows at all. One mapping shared by railRow() and
    // pipClassFor() below, both built on top of the single sessionState()
    // derivation — never a second state derivation. 'idle' maps to '' because
    // both .cr-rail-dot and .cr-orb-pip already default to --state-idle grey.
    var STATE_DOT_CLASS = {
      awaiting: 'is-waiting', working: 'is-live', flagged: 'is-flagged',
      landed: 'is-landed', idle: ''
    };
    function stateDotClass(state) { return STATE_DOT_CLASS[state] || ''; }

    function pipClassFor(s, now) {
      return stateDotClass(sessionState(s, now));
    }

    // Doc 03 "The collapsed orb rail": "Every orb needs `title` and `aria-label`
    // = '<title> — <state word>', e.g. 'Terminal renderer switch — waiting on
    // you'. Initials alone are not an accessible name." Lower-case, matching the
    // doc's own example exactly — a DIFFERENT casing from the tile head's
    // capitalized stateWord() (tile anatomy is a separate context). FIX: the
    // previous label omitted the state word entirely (title + "(pinned)" only),
    // which an earlier audit flagged — that suffix is dropped here since the
    // doc's format has no room for it and the state word is what's required.
    var ORB_STATE_WORD = { awaiting: 'waiting on you', flagged: 'flagged', working: 'working', landed: 'landed', idle: 'idle' };
    function orbStateWord(state) { return ORB_STATE_WORD[state] || state; }

    function railOrb(s, now) {
      var title = s.title || s.project || s.id;
      var label = title + ' — ' + orbStateWord(sessionState(s, now));
      return h('button', {
        class: 'cr-orb' + (s.id === selectedSessionId ? ' cr-orb--selected' : ''),
        type: 'button', title: label, 'aria-label': label,
        onclick: function () { openSession(s.id); }
      }, [
        initials(s),
        h('span', { class: 'cr-orb-pip ' + pipClassFor(s, now) }),
      ]);
    }

    function railRow(s, now) {
      // BUG FIX: dotClass used to only distinguish is-waiting/is-live/default —
      // no flagged, no landed colour. Reuses sessionState() (the single state
      // derivation) and the same STATE_DOT_CLASS map pipClassFor() uses, so the
      // rail row and the collapsed orb never disagree on a session's colour.
      var state = sessionState(s, now);
      var dotClass = stateDotClass(state);
      var name = s.title || s.project || s.id.slice(0, 8);
      // Decision 1: the folder the session runs from, as the meaningful TAIL
      // of `cwd` (shortDir(), shared with the tile title below) — never the
      // full path inline, which would blow past a compact row. The FULL path
      // still rides in the row's own `title` tooltip attribute (titleAttr,
      // unchanged, already carries `s.cwd` in full).
      var dir = shortDir(s.cwd || '');
      // Model rides the SAME line as the directory (both are subordinate,
      // both already truncate with an ellipsis at this row width) rather than
      // a new element — a short form here, e.g. "opus 4.8", with the raw id
      // only in the row's full tooltip (titleAttr below), per the "rail rows
      // are tight" instruction.
      var mdl = modelShort(s.model);
      var dirLine = [dir, mdl].filter(Boolean).join(' · ');
      // `s.snippet` only exists on a decorated search-hit object (never on a
      // real list-dict session) — falls back to the prompt/title tooltip
      // exactly as before whenever it's absent, so this is purely additive.
      var todoLabel = railTodoLabel(s);
      var titleAttr = (s.prompt || s.snippet || s.title || '(no prompt)') + '\n' + (s.cwd || '') +
        (s.model ? '\nModel: ' + s.model : '') +
        (todoLabel ? '\n' + (s.todo_done || 0) + ' of ' + s.todo_total + ' todos done' +
          (s.todo_current ? ' — in progress: ' + s.todo_current : '') : '');
      // Colour never carries meaning alone: the state word (and, for a pinned
      // session, "(pinned)") rides along in aria-label (title keeps the fuller
      // prompt/cwd/snippet tooltip it already had).
      var label = name + (s.pinned ? ' (pinned)' : '') + (dir ? ', ' + dir : '') + ' — ' + orbStateWord(state) +
        (todoLabel ? ', ' + todoLabel + ' todos' : '');
      // Search-result rows (requirement 5's ordering note): the server's
      // ranking is used AS-IS — a pinned hit still shows its 📌 marker inline
      // rather than being pulled into a separate "Pinned" group the way
      // browsing does, which would re-sort exactly what search must not.
      var displayName = (s.pinned ? '📌 ' : '') + (s.agent ? '🤖 ' : '') + name;
      return h('div', {
        class: 'cr-rail-row' + (s.id === selectedSessionId ? ' cr-rail-row--selected' : ''),
        tabindex: '0', role: 'button', title: titleAttr, 'aria-label': label, 'data-id': s.id,
        onclick: function () { openSession(s.id); },
        onkeydown: function (e) { if (e.key === 'Enter') openSession(s.id); }
      }, [
        h('span', { class: 'cr-rail-dot ' + dotClass }),
        h('div', { class: 'cr-rail-titlewrap' }, [
          h('span', { class: 'cr-rail-title' }, [displayName]),
          dirLine ? h('span', { class: 'cr-rail-dir' }, [dirLine]) : null,
        ]),
        h('span', { class: 'cr-rail-meta' },
          [todoLabel ? (todoLabel + ' · ' + railRowMeta(s, now)) : railRowMeta(s, now)]),
      ]);
    }

    function openSession(id) {
      closeRailOverlay();   // selecting a session closes the mobile overlay drawer, if open
      selectedSessionId = id;
      if (ctx && typeof ctx.go === 'function') ctx.go('detail', id);
    }

    // -- top bar --------------------------------------------------------

    // Requirement 4 (active-destination state): reflects `lastTopLevelView`
    // ('board' | 'sessions') rather than `currentView`, so the pill you drilled
    // in FROM stays active while a session's detail view is open — decision 1
    // is that the detail view is reachable "from anywhere," so it isn't itself
    // a fourth destination. Terminals isn't a content-swap view (see buildTopBar
    // above) so it's left out of this active-state bookkeeping.
    function updateDestinationActive() {
      [['board', els.pillBoard], ['sessions', els.pillSessions]].forEach(function (pair) {
        var key = pair[0], btn = pair[1];
        if (!btn) return;
        var isActive = (lastTopLevelView === key);
        btn.classList.toggle('cr-pill--active', isActive);
        if (isActive) btn.setAttribute('aria-current', 'page'); else btn.removeAttribute('aria-current');
      });
    }

    function buildTopBar() {
      els.topbar.innerHTML = '';

      els.railToggleTop = h('button', {
        class: 'cr-rail-toggle', type: 'button',
        title: 'Collapse session rail', 'aria-label': 'Collapse session rail',
        onclick: toggleRail
      }, [icon('panel', '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>')]);
      els.topbar.appendChild(els.railToggleTop);

      // NOTE: "the way back" to the classic dashboard is a `document.body`-
      // level mode switch (`tracker.ui` localStorage + a class toggle on
      // <body>, doc 02 "Mode switching") owned by whatever bootstrap mounts
      // this module — not something this file can perform on its own,
      // since it never touches anything outside its own rootEl. Wired here
      // as a `ctx.emit` so a bootstrap listener can do the actual switch;
      // see REQUIRED ADDITIONS in the report.
      // BLOCKER 1 (phone icon-only compaction): the "‹ " glyph is a bare text
      // node that always stays visible; "Classic dashboard" is wrapped in
      // `.cr-topbar-label` so the phone-tier CSS (ext_cr_board.css) can hide
      // just that redundant text without removing the button. `title`/
      // `aria-label` (new — this button had neither before) keep the full
      // accessible name once the visual label is gone.
      els.topbar.appendChild(h('button', {
        class: 'cr-back', type: 'button',
        title: 'Classic dashboard', 'aria-label': 'Back to classic dashboard',
        onclick: function () { ctx && ctx.emit && ctx.emit('ui:backToClassic'); }
      }, ['‹ ', h('span', { class: 'cr-topbar-label' }, ['Classic dashboard'])]));

      els.topbar.appendChild(h('span', { class: 'cr-divider' }));

      // Three destinations (requirement 3: Board, Sessions, Terminals — the
      // Sessions pill was previously missing entirely). Board and Sessions are
      // real content-region views (ctx.go swaps els.viewBoard/els.viewSessions,
      // same mechanism session navigation already uses); Terminals keeps its
      // existing behaviour (opens the terminals-manage overlay via cr_term.js,
      // not a content swap — that pattern predates this fix and isn't changed
      // here). Same pill markup/class for all three; only Board/Sessions get
      // the active/aria-current treatment, via updateDestinationActive below.
      els.pillBoard = h('button', {
        class: 'cr-pill', type: 'button',
        onclick: function () { ctx && ctx.go && ctx.go('board'); }
      }, ['Board']);
      els.pillSessions = h('button', {
        class: 'cr-pill', type: 'button',
        onclick: openSessionsDestination
      }, ['Sessions']);
      els.terminalsPill = h('button', {
        class: 'cr-pill', type: 'button',
        onclick: function () { ctx && ctx.emit && ctx.emit('nav:terminals'); }
      }, ['Terminals', h('span', { class: 'cr-pill-count' }, [''])]);
      var pills = h('div', { class: 'cr-dest-pills' }, [els.pillBoard, els.pillSessions, els.terminalsPill]);
      els.topbar.appendChild(pills);
      updateDestinationActive();

      els.topbar.appendChild(h('span', { class: 'cr-topbar-spacer' }));

      els.flagCountBtn = h('button', {
        class: 'cr-flagcount', type: 'button', title: 'Open the flag list', 'aria-label': 'Open the flag list',
        onclick: function () { ctx && ctx.emit && ctx.emit('open:flags'); }
      }, [emoji('🚩', 'tn-emo-f'), '0']);
      els.topbar.appendChild(els.flagCountBtn);

      els.topbar.appendChild(h('button', {
        class: 'cr-bell', type: 'button', title: 'Notifications', 'aria-label': 'Notifications',
        onclick: function () { ctx && ctx.emit && ctx.emit('toggle:notifications'); }
      }, [emoji('🔔', '')]));

      // BLOCKER 1: 'Config'/'Help' labels wrapped in `.cr-topbar-label` so the
      // phone-tier CSS can drop to icon-only — `title`/`aria-label` already
      // carry the full text so the accessible name is unaffected.
      els.topbar.appendChild(h('button', {
        class: 'cr-icon-btn', type: 'button', title: 'Config', 'aria-label': 'Config',
        onclick: function () { ctx && ctx.emit && ctx.emit('open:config'); }
      }, [emoji('⚙️', ''), h('span', { class: 'cr-topbar-label' }, ['Config'])]));

      els.topbar.appendChild(h('button', {
        class: 'cr-icon-btn', type: 'button', title: 'Help', 'aria-label': 'Help',
        onclick: function () { ctx && ctx.emit && ctx.emit('open:help'); }
      }, [emoji('❓', ''), h('span', { class: 'cr-topbar-label' }, ['Help'])]));

      buildThemeControl();

      // BLOCKER 1: 'New session' label wrapped in `.cr-topbar-label` so the
      // phone-tier CSS can drop to icon-only. `aria-label` is new — this
      // button previously had none, relying entirely on the (now hideable)
      // text node for its accessible name.
      els.topbar.appendChild(h('button', {
        class: 'cr-newsession', type: 'button', 'aria-label': 'New session',
        onclick: function () { ctx && ctx.emit && ctx.emit('session:new'); }
      }, [icon('spark', '<path d="M12 2l2 7h7l-5.5 4.5L17 21l-5-4-5 4 1.5-7.5L3 9h7z"/>'),
          h('span', { class: 'cr-topbar-label' }, ['New session'])]));
    }

    // BUG FIX (the "no way back to auto" complaint): AUTO used to render as a
    // static, unclickable <span> label — there was no control that ever set
    // the preference back to 'auto' directly. It is now a real third segment,
    // Auto · Light · Dark, in the SAME .cr-theme-seg/button/.is-on pattern the
    // Light/Dark pair already used — not a new pattern, just one more button
    // in the existing one. 01-foundations.md decision 3's own vocabulary
    // ('auto'|'light'|'dark') and its stated highlight rule are kept exactly:
    // while the preference is auto, Auto AND whichever side matches the
    // resolved theme both read "on" — this is deliberately not a
    // one-active-segment control.
    function buildThemeControl() {
      function pref() { return (ctx && ctx.theme && ctx.theme.get) ? ctx.theme.get() : 'auto'; }
      // BUG FIX: this used to snapshot `matchMedia(...).matches` ONCE at mount
      // time into a local `systemDark` var, so this control's own highlight
      // went stale the moment the OS scheme flipped while on auto — even
      // though #nextRoot's real .is-dark class (driven by boot.js's own
      // resolveTheme(), a live read) updated correctly. Delegating to
      // ctx.theme.resolved() (boot.js's real resolveTheme(), re-read fresh on
      // every call) means this button row can never disagree with the theme
      // actually applied to the page. The inline fallback below (same
      // formula) only matters if ctx wiring is ever missing entirely.
      function resolved() {
        if (ctx && ctx.theme && typeof ctx.theme.resolved === 'function') return ctx.theme.resolved();
        var p = pref();
        var sysDark = !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        return (p === 'dark' || (p === 'auto' && sysDark)) ? 'dark' : 'light';
      }
      var wrap = h('div', { class: 'cr-theme' });
      var autoBtn = h('button', { type: 'button', title: 'Follow the system theme' }, ['Auto']);
      var lightBtn = h('button', { type: 'button', title: 'Light theme' }, ['Light']);
      var darkBtn = h('button', { type: 'button', title: 'Dark theme' }, ['Dark']);
      var seg = h('div', { class: 'cr-theme-seg' }, [autoBtn, lightBtn, darkBtn]);
      wrap.appendChild(seg);

      // Colour never carries meaning alone (01-foundations.md contrast
      // floor): `.is-on` (shared, unchanged CSS) paints a raised background +
      // shadow, not just a colour swap, and aria-pressed carries the same
      // state to assistive tech.
      function paint() {
        var r = resolved(), p = pref(), isAuto = (p === 'auto');
        autoBtn.classList.toggle('is-on', isAuto);
        autoBtn.setAttribute('aria-pressed', isAuto ? 'true' : 'false');
        lightBtn.classList.toggle('is-on', r === 'light');
        lightBtn.setAttribute('aria-pressed', r === 'light' ? 'true' : 'false');
        darkBtn.classList.toggle('is-on', r === 'dark');
        darkBtn.setAttribute('aria-pressed', r === 'dark' ? 'true' : 'false');
      }
      // Each segment now just sets its own value directly — Auto being a
      // real, always-present button makes the old "click the already-active
      // side again to fall back to auto" gesture unnecessary (and, with a
      // real Auto button now on screen, actually surprising: clicking Dark
      // while on Dark should stay Dark, not bounce to auto).
      function choose(v) {
        if (ctx && ctx.theme && ctx.theme.set) ctx.theme.set(v);
        paint();
      }
      autoBtn.addEventListener('click', function () { choose('auto'); });
      lightBtn.addEventListener('click', function () { choose('light'); });
      darkBtn.addEventListener('click', function () { choose('dark'); });
      paint();
      els.topbar.appendChild(wrap);
      els.themeRepaint = paint;
    }

    // -- triage strip -----------------------------------------------------

    function buildTriageShell() {
      els.triage.innerHTML = '';
      function cell(key, label) {
        var btn = h('button', {
          class: 'cr-triage-cell cr-triage-cell--' + key, type: 'button',
          onclick: function () { setFilter(key); }
        }, [
          h('span', { class: 'cr-triage-count' }, ['0']),
          h('span', { class: 'cr-triage-label' }, [label]),
        ]);
        els.triage.appendChild(btn);
        els['triageCell_' + key] = btn;
        els['triageCount_' + key] = btn.querySelector('.cr-triage-count');
        return btn;
      }
      cell('awaiting', 'WAITING ON YOU');
      cell('working', 'WORKING');
      cell('flagged', 'FLAGGED');

      els.histWrap = h('div', { class: 'cr-triage-hist' }, [
        (els.histBars = h('div', {
          class: 'cr-triage-hist-bars', role: 'img', 'aria-label': 'Activity, last hour: peak 0 events per minute'
        })),
        h('div', { class: 'cr-triage-hist-foot' }, [
          h('span', {}, ['Activity · last hour']),
          h('span', {}, ['events / min']),
        ]),
      ]);
      els.triage.appendChild(els.histWrap);
    }

    function setFilter(key) {
      activeFilter = (activeFilter === key) ? null : key;
      renderTriage(lastState);
      renderBoard(lastState);
    }

    function renderTriage(state) {
      var sessions = state.sessions || [], now = state.now;
      var counts = triageCounts(sessions, now);
      ['awaiting', 'working', 'flagged'].forEach(function (key) {
        els['triageCount_' + key].textContent = String(counts[key]);
        els['triageCell_' + key].classList.toggle('cr-triage-cell--active', activeFilter === key);
      });

      var hist = activityHistogram(sessions, now);
      els.histBars.innerHTML = '';
      var n = hist.bins.length;
      // Round-5 drift (decision 4c): 5a's own histogram bands its LAST SIX
      // bars through a gradient, only the final bar glowing — replacing the
      // doc's simpler 3-tier-over-last-3 this used to implement. Bar count
      // (18, unchanged) and glow-on-last (unchanged) stand; only the colour
      // assignment for the last six changes.
      //
      // Extracted directly from the prototype HTML (grep-verified, not
      // guessed): its 15-bar board histogram colours its last six bars
      // stone-3(×1) -> wheat-3(×2) -> wheat-4(×2) -> wheat-5(×1, glowing),
      // with plain gray-3 on everything older. But `--ads-wheat-3` and
      // `--ads-wheat-4` are never actually DEFINED anywhere in that 617KB
      // file (only `--ads-gray-3`, `--ads-stone-3`, `--ads-wheat-5`, and
      // `--ads-wheat-8` are) — two of the five named bands are themselves
      // broken references in the source artboard, so they can't be copied
      // literally. This reproduces the INTENT (a 4-stop ramp from neutral to
      // the existing gold glow colour across the same 1-2-2-1 split over the
      // last six bars) using four tokens that already exist in this app's own
      // palette, per the "never raw hex where a token exists" rule:
      // --line-default (stone-3 analog) -> --line-strong (wheat-3 analog) ->
      // --line-agent (wheat-4 analog, still gold-family but distinct from the
      // final glow colour) -> --state-thinking (wheat-5, the pre-existing
      // final-bar colour+glow, unchanged from before this fix).
      hist.bins.forEach(function (v, i) {
        var fromEnd = n - 1 - i;   // 0 = last (newest) bar
        var cls = 'cr-hist-bar';
        var h1 = 4 + (hist.peak ? Math.round((v / hist.peak) * 26) : 0);
        var bar = h('span', { class: cls, style: 'height:' + h1 + 'px' });
        if (fromEnd === 5) bar.style.background = 'var(--line-default)';
        else if (fromEnd === 4 || fromEnd === 3) bar.style.background = 'var(--line-strong)';
        else if (fromEnd === 2 || fromEnd === 1) bar.style.background = 'var(--line-agent)';
        else if (fromEnd === 0) bar.style.background = 'var(--state-thinking)';
        if (fromEnd === 0) bar.classList.add('is-glow');
        els.histBars.appendChild(bar);
      });
      els.histBars.setAttribute('aria-label', 'Activity, last hour: peak ' + hist.peak + ' events per minute');
    }

    // -- board --------------------------------------------------------------

    function tileId(t) { return t.kind === 'session' ? t.session.id : 'group:' + t.group; }

    function passesFilter(t) {
      if (!activeFilter) return true;
      if (t.kind !== 'session') return activeFilter !== 'flagged' ? false : t.session.open_flags > 0;
      if (activeFilter === 'flagged') return !!t.session.open_flags;
      return t.state === activeFilter;
    }

    function renderBoard(state) {
      var sessions = state.sessions || [], now = state.now;
      var allTiles = boardTiles(sessions, now);
      var tiles = allTiles.filter(passesFilter);

      els.board.innerHTML = '';
      if (!tiles.length) {
        els.board.appendChild(h('div', { class: 'cr-board-empty' },
          [activeFilter ? 'Nothing matches that filter right now.' : 'Nothing needs you right now.']));
      } else {
        tiles.forEach(function (t) { els.board.appendChild(t.kind === 'session' ? sessionTile(t, now) : agentGroupTile(t, now)); });
      }

      if (focusedTileId) {
        var el = els.board.querySelector('[data-tile-id="' + cssEscape(focusedTileId) + '"]');
        if (el) el.focus();
      }

      renderCapFooter(sessions, allTiles);
    }

    function cssEscape(s) { return String(s).replace(/[^a-zA-Z0-9_-]/g, '\\$&'); }

    function tileBaseAttrs(t) {
      return {
        tabindex: '0', role: 'listitem', 'data-tile-id': tileId(t),
        onfocus: function () { focusedTileId = tileId(t); },
        onclick: function (e) {
          if (e.target.closest('button,a,input,select,textarea,[role=button]')) return;
          activateTile(t);
        },
        onkeydown: function (e) { if (e.key === 'Enter') activateTile(t); }
      };
    }

    function activateTile(t) {
      if (t.kind === 'session') openSession(t.session.id);
      else ctx && ctx.emit && ctx.emit('rail:expandAgents', { group: t.group });
    }

    // BUG FIX: 01-foundations.md's state vocabulary (~line 169) bakes the flag
    // count into the word itself — "N flags open", singular "1 flag open" —
    // matching the exact pluralisation already used for the tile body line
    // (tileLine below). The static "Flagged" label carried no count.
    function stateWord(state, s) {
      if (state === 'flagged') {
        var n = (s && s.open_flags) || 0;
        return n + ' flag' + (n === 1 ? '' : 's') + ' open';
      }
      return { awaiting: 'Waiting on you', working: 'Working', landed: 'Landed' }[state] || state;
    }
    function stateEmoji(state) {
      return { awaiting: ['⏳', 'tn-emo-a'], working: ['🟡', ''], flagged: ['🚩', 'tn-emo-f'], landed: ['✅', 'tn-emo-d'] }[state] || ['', ''];
    }

    function todoTicks(s) {
      // todo_total/todo_done/todo_current (the in-progress todo's TEXT) are
      // emitted by every provider's list() today — verified: providers/claude.py
      // (list_sessions()), providers/auggie.py (list_auggie()), providers/
      // augment_ext.py all call the same util.todo_summary(). todo_current_index
      // (0-based INT, or null when nothing is in progress) is that same
      // function's newest return value — the shared-seam field this fix
      // consumes for the current-tick highlight. Guarded below so a provider
      // that ever lacks it (or genuinely has nothing in progress) just renders
      // with no tick highlighted, never a crash.
      if (typeof s.todo_total !== 'number' || !s.todo_total) return null;
      var done = s.todo_done || 0, total = s.todo_total;
      var currentIndex = (typeof s.todo_current_index === 'number') ? s.todo_current_index : null;
      var currentLabel = s.todo_current || '';
      var ticks = h('div', {
        class: 'cr-tile-ticks', role: 'img',
        'aria-label': done + ' of ' + total + ' todos done',
        // NOTE: doc 02's todo-ticks section only specifies this count aria-label
        // ("7 of 11 todos done"); it never asks for the in-progress todo's own
        // text in the tile anatomy. Surfaced as a plain tooltip instead — it
        // doesn't touch the mandated aria-label, but the label text is free and
        // otherwise just gets dropped on the floor.
        title: currentLabel ? ('In progress: ' + currentLabel) : null
      });
      for (var i = 0; i < total; i++) {
        var cls = 'cr-tick';
        if (i < done) cls += ' cr-tick--done';
        else if (currentIndex !== null && i === currentIndex) cls += ' cr-tick--current';
        ticks.appendChild(h('span', { class: cls }));
      }
      return h('div', { class: 'cr-tile-todos' }, [ticks,
        h('span', { class: 'cr-tile-todocaption' }, [done + ' of ' + total])]);
    }

    // BUG FIX: pr_num/pr_url/pr_repo/pr_state (Claude-only today, empty for other
    // providers — registry.py's shared list dict) reached the SPA but had zero render
    // call sites. Doc 02's tile anatomy: a Landed tile shows "PR number if any" — quiet,
    // subordinate metadata, so a bare "#123" (linked when pr_url exists), nothing at all
    // when pr_num is empty. Never a placeholder.
    //
    // Split pure decision (prInfo, exported below for tests/test_cr_logic.py) from DOM
    // building (tilePr) — same split boardTiles()/sessionTile() already use.
    function prInfo(s, state) {
      if (state !== 'landed' || !s.pr_num) return null;
      var label = '#' + s.pr_num;
      return {
        label: label,
        url: s.pr_url || null,
        title: (s.pr_repo ? s.pr_repo + ' ' : '') + label + (s.pr_state ? ' · ' + s.pr_state : '')
      };
    }
    function tilePr(s, state) {
      var info = prInfo(s, state);
      if (!info) return null;
      if (info.url) {
        return h('a', {
          class: 'cr-tile-pr', href: info.url, target: '_blank', rel: 'noopener', title: info.title,
          onclick: function (e) { e.stopPropagation(); }
        }, [info.label]);
      }
      return h('span', { class: 'cr-tile-pr', title: info.title }, [info.label]);
    }

    function tileHead(s, state, now) {
      var ew = stateEmoji(state);
      var kids = [
        emoji(ew[0], ew[1]),
        h('span', { class: 'cr-tile-state' }, [stateWord(state, s) + (state === 'awaiting' ? ' · ' + ago(now - (s.mtime || 0)) : '')]),
      ];
      if (s.pinned) kids.push(emoji('📌', '', 'Pinned'));
      var head = h('div', { class: 'cr-tile-head', 'data-state': state }, kids);
      if (state === 'working') {
        var dot = h('span', { class: 'cr-tile-dot is-working' });
        head.insertBefore(dot, head.firstChild);
      }
      // NOTE: 01-foundations.md's state vocabulary bakes the age straight into the
      // "Waiting on you · <age>" word itself; 02's generic tile-anatomy trailing
      // "[age · tool]" would then repeat it for awaiting tiles specifically (the
      // bug this fixed — age was printed twice). The explicit per-state word text
      // wins: trailing meta drops the age for awaiting tiles and shows tool only,
      // every other state keeps the full "age · tool".
      var trailing = (state === 'awaiting') ? toolLabel(s.source)
        : (ago(now - (s.mtime || 0)) + ' · ' + toolLabel(s.source));
      // Model is subordinate metadata, tacked onto the SAME trailing strip
      // rather than a new visual element -- absent whenever the session's
      // last-known model is unknown (never "unknown", never a placeholder).
      var mdl = modelShort(s.model);
      if (mdl) trailing += ' · ' + mdl;
      head.appendChild(h('span', { class: 'cr-tile-meta', title: s.model || null }, [trailing]));
      return head;
    }

    // Decision 3 (revised): the session's NAME (unchanged fallback chain —
    // title -> project -> id fragment) plus the SPAWN DIRECTORY (shortDir() of
    // cwd, decisions 1/3 share the same helper), for every state except
    // 'awaiting' — the "waiting on you" hero/tile is left exactly as it was,
    // per the owner's explicit exception. Where there's no title, this falls
    // back honestly (project, then a short id fragment) rather than showing
    // nothing.
    function tileTitleText(s, state) {
      var name = s.title || s.project || (s.id ? s.id.slice(0, 8) : '(untitled)');
      if (state === 'awaiting') return name;
      var dir = shortDir(s.cwd || '');
      return dir ? (name + ' — ' + dir) : name;
    }

    // Decision 3 (revised): the tile's second line is `s.now_line` — a short
    // "what's happening right now" string a parallel change is adding to the
    // session-list shape — never the original prompt. This used to fall back
    // to `s.prompt` for every non-flagged state (see the removed NOTE that
    // used to sit here: "no live-narration line... prompt used as the best
    // available stand-in for the summary"); the owner explicitly does not
    // want that stand-in shown any more, so an empty/absent now_line now
    // means NO second line at all, never a silent fallback to the prompt.
    // Reconciled with the old flagged-only branch this replaces: flagged's
    // "N flag(s) open" text is already shown on the HEAD line (tileHead's own
    // stateWord()), so repeating it here was pure duplication — round-5's own
    // artboard confirms this: its flagged tile's head line already carries
    // "🚩 2 flags open · 6m" and its body line is a SEPARATE short status
    // phrase ("Pushed note stuck at 'queued'"), never a repeat of the flag
    // count. now_line covers exactly that role for every non-awaiting state,
    // flagged included.
    //
    // 'awaiting' (hero or plain) is untouched — the owner's explicit "leave
    // that state alone" exception — so it alone still shows the prompt.
    function tileLine(s, state) {
      if (state === 'awaiting') {
        return h('div', { class: 'cr-tile-line' }, [s.prompt || '']);
      }
      var nowLine = (typeof s.now_line === 'string') ? s.now_line.trim() : '';
      if (!nowLine) return null;   // no now_line -> no second line at all, never s.prompt
      return h('div', { class: 'cr-tile-line cr-tile-line--now' }, [nowLine]);
    }

    function sessionTile(t, now) {
      var s = t.session, state = t.state;
      var cls = 'cr-tile cr-tile--' + state;
      if (t.hero) cls += ' cr-tile--hero cr-tile--span2';
      var attrs = tileBaseAttrs(t);
      attrs.class = cls;
      attrs.title = (s.prompt || s.title || '(no prompt)') + '\n' + (s.cwd || '') +
        (s.model ? '\nModel: ' + s.model : '');

      var body = [
        tileHead(s, state, now),
        h('div', { class: 'cr-tile-title' }, [tileTitleText(s, state)]),
      ];
      // Round-5 drift (decision 4a): 5a's own non-hero tile anatomy is
      // head -> title -> body only — no "project · tool" sub-line (grep-
      // verified against the artboard's own tile markup: three divs, never
      // four). The hero (awaiting) tile is left exactly as it rendered
      // before — decision 3's explicit exception — sub-line included, since
      // it isn't part of this round-5 density fix.
      if (t.hero) {
        body.push(h('div', { class: 'cr-tile-sub' }, [(s.project || '') + ' · ' + toolLabel(s.source)]));
      }
      var line = tileLine(s, state);
      if (line) body.push(line);
      var ticks = todoTicks(s);
      if (ticks) body.push(ticks);
      var pr = tilePr(s, state);
      if (pr) body.push(pr);

      if (t.hero) {
        // NOTE: files/failing counts the doc's hero side-rail calls for
        // aren't in the list dict either; only `note_count` is available.
        // Rendered honestly with what exists rather than fabricating the
        // other two counters — REQUIRED ADDITION in the report.
        body.push(h('div', { class: 'cr-tile-sidebar' }, [
          h('div', { class: 'cr-tile-counts' }, [emoji('📝', 'tn-emo-n'), (s.note_count || 0) + ' notes']),
          h('button', {
            class: 'cr-tile-action', type: 'button',
            onclick: function (e) { e.stopPropagation(); ctx && ctx.emit && ctx.emit('terminal:open', { id: s.id }); }
          }, ['Open terminal to answer']),
        ]));
        var inner = h('div', { class: 'cr-tile-inner' }, body);
        return h('div', attrs, [inner]);
      }
      return h('div', attrs, body);
    }

    // BUG FIX: doc 02's tile-anatomy table gives the Agent group tile's extras
    // as "`▸` + 🤖 + \"expand\"" — chevron FIRST, then the emoji, no invented
    // "Agent group" head label (that string appears in neither the doc nor the
    // prototype). The title line is plain/secondary-coloured "Agents · <repo>"
    // with no duplicate 🤖 (the head already carries the one emoji), followed
    // by a real sentence describing the group — not "{n} running" — with
    // "expand" as its own trailing line.
    function agentGroupTile(t, now) {
      var attrs = tileBaseAttrs(t);
      attrs.class = 'cr-tile cr-tile--agentgroup';
      attrs.title = '🤖 Agents · ' + t.label;
      var total = t.sessions.length;
      var live = t.sessions.filter(function (s) { return sessionState(s, now) !== 'idle'; }).length;
      var sentence = total + ' background agent' + (total === 1 ? '' : 's') +
        ' running in ' + t.label + (live && live !== total ? ' (' + live + ' active now)' : '') + '.';
      return h('div', attrs, [
        h('div', { class: 'cr-tile-head' }, [
          icon('chevron', '<path d="M9 6l6 6-6 6"/>'),
          emoji('🤖', ''),
        ]),
        h('div', { class: 'cr-tile-title cr-tile-title--agent' }, ['Agents · ' + t.label]),
        h('div', { class: 'cr-tile-line' }, [sentence]),
        h('div', { class: 'cr-tile-agentexpand' }, ['expand']),
      ]);
    }

    function renderCapFooter(sessions, allTiles) {
      els.capfooter.innerHTML = '';
      // BUG FIX / preference support: the "8" in this sentence used to be a
      // literal, but the cap is now a user preference (cr.boardTileCount,
      // clamped 3-8) — the copy's shape is doc 02's "Cap footer" verbatim,
      // only the number is dynamic.
      els.capfooter.appendChild(h('span', { class: 'cr-capfooter-count' }, [allTiles.length + ' of ' + sessions.length]));
      els.capfooter.appendChild(document.createTextNode(
        ' — The board never shows more than ' + boardTileCap() + ' tiles. Everything else lives in the rail — pinned on top, newest first in each group. — '));
      els.capfooter.appendChild(h('button', {
        class: 'cr-capfooter-link', type: 'button',
        onclick: function () { els.railSearchInput && els.railSearchInput.focus(); els.rail.scrollIntoView({ block: 'nearest' }); }
      }, ['Scroll for the rest']));
    }

    // -- keyboard (doc 02 "Keyboard") ---------------------------------------

    function isTypingTarget(e) {
      var t = e.target;
      if (!t) return false;
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable) return true;
      // The terminal's own input (xterm.js's helper textarea, or any future
      // renderer) lives inside #cr-term-root — never steal keys from it.
      var termRoot = document.getElementById('cr-term-root');
      return !!(termRoot && termRoot.contains(t));
    }

    // Gate on the new UI actually being the visible, active mode — not merely
    // "mounted" (root.isConnected is true forever once mount() has run once,
    // even after switching back to classic or navigating to the detail view).
    function isBoardActive() {
      var nextRoot = document.getElementById('nextRoot');
      if (!nextRoot || nextRoot.hidden) return false;
      // STRUCTURAL FIX: `root` is now the PERSISTENT shell (rail + top bar +
      // content), never hidden — checking `root.hidden` here would make j/k/t/
      // ⌘K fire even while the detail or sessions view is showing. The actual
      // "is the board grid the one visible" signal is els.viewBoard, the inner
      // content slot that still toggles `hidden` per view.
      if (!els.viewBoard || els.viewBoard.hidden) return false;
      return true;
    }

    function currentTileEls() { return Array.prototype.slice.call(els.board.querySelectorAll('[data-tile-id]')); }

    function bindKeyboard() {
      document.addEventListener('keydown', function (e) {
        if (!root.isConnected || !isBoardActive()) return;
        if (isTypingTarget(e)) return;
        var mod = e.metaKey || e.ctrlKey;
        if (mod && (e.key === 'k' || e.key === 'K')) {
          e.preventDefault();
          els.railSearchInput.focus();
          return;
        }
        if (e.key === '?') {
          e.preventDefault();
          ctx && ctx.emit && ctx.emit('open:help');
          return;
        }
        if (e.key === 'Escape') {
          if (railOverlayOpen) { closeRailOverlay(); return; }
          if (activeFilter) { setFilter(activeFilter); }
          return;
        }
        var tileEls = currentTileEls();
        if (!tileEls.length) return;
        var idx = tileEls.findIndex(function (el) { return el.getAttribute('data-tile-id') === focusedTileId; });
        if (e.key === 'j') {
          e.preventDefault();
          idx = (idx < 0) ? 0 : Math.min(tileEls.length - 1, idx + 1);
          tileEls[idx].focus();
        } else if (e.key === 'k') {
          e.preventDefault();
          idx = (idx < 0) ? 0 : Math.max(0, idx - 1);
          tileEls[idx].focus();
        } else if (e.key === 't') {
          if (idx >= 0) {
            e.preventDefault();
            var tiles = boardTiles(lastState.sessions || [], lastState.now).filter(passesFilter);
            var t = tiles[idx];
            if (t && t.kind === 'session') ctx && ctx.emit && ctx.emit('terminal:open', { id: t.session.id });
          }
        }
      });
    }

    // -- public surface -------------------------------------------------

    function mount(rootEl, ctxArg) {
      root = rootEl;
      ctx = ctxArg;
      buildShell();
      if (ctx && typeof ctx.on === 'function') {
        ctx.on('session:selected', function (payload) {
          selectedSessionId = payload && payload.id;
          renderRail(lastState);
        });
        ctx.on('theme:changed', function () { els.themeRepaint && els.themeRepaint(); });
        // Config's "Session rail" row writes the SAME key this module owns. Without
        // this subscription railMode is a closure var read once at mount, so picking
        // a mode in Config moved nothing on screen and the next chevron click -- which
        // reads the rendered class, then writes -- silently overwrote the choice. That
        // is the same dead-control bug this whole change exists to remove, so the board
        // has to actually listen rather than assume it is the only writer.
        ctx.on('cr:pref', function (payload) {
          if (!payload || payload.key !== 'tracker.rail.mode') return;
          var v = payload.value;
          railMode = (v === 'open' || v === 'collapsed') ? v : 'auto';
          applyRailMode();
        });
        // Clicking (or Enter-activating) an agent-group row/tile toggles that group's
        // sessions open inline in the rail — own expand state, this module only.
        ctx.on('rail:expandAgents', function (payload) {
          var g = payload && payload.group;
          if (!g) return;
          expandedRailGroup = (expandedRailGroup === g) ? null : g;
          renderRail(lastState);
        });
        // boot.js's own go()/showView() already emit this on every navigation
        // (board/sessions/detail); this is how the persistent rail/topbar learn
        // which content slot is now visible, WITHOUT ever being hidden themselves.
        ctx.on('view:changed', function (payload) {
          var view = (payload && payload.view) || 'board';
          currentView = view;
          if (view === 'board' || view === 'sessions') lastTopLevelView = view;
          updateDestinationActive();
          applyRailMode();   // recomputes the forced 56px orb rail for 'detail'
          if (view === 'sessions') renderSessionsView(lastState);
        });
      }
    }

    function update(state) {
      lastState = state || { sessions: [], now: Math.floor(Date.now() / 1000) };
      var sessions = lastState.sessions || [];
      renderRail(lastState);
      renderTriage(lastState);
      renderBoard(lastState);
      if (currentView === 'sessions') renderSessionsView(lastState);

      var flagTotal = sessions.reduce(function (n, s) { return n + (s.open_flags || 0); }, 0);
      if (els.flagCountBtn) els.flagCountBtn.lastChild.textContent = ' ' + flagTotal;

      // REQUIRED ADDITION: ctx has no terminal-count accessor, so the
      // Terminals pill's "N of M" live count (doc 02 top-bar item 3) cannot
      // be rendered from {sessions, now} alone. Left blank rather than
      // fabricated; see report.
      if (els.terminalsPill && ctx && ctx.terminals && typeof ctx.terminals.count === 'function') {
        var tc = ctx.terminals.count();
        els.terminalsPill.lastChild.textContent = tc.open + ' of ' + tc.total;
      }
    }

    return {
      mount: mount,
      update: update,
      // Structural fix: board.mount(rootEl, ctx) now builds the PERSISTENT
      // shell (rail + top bar) plus all three content slots inside `rootEl`,
      // instead of building just the board's own view. boot.js needs the
      // detail slot's real DOM node to hand to CR.detail.mount() — this is
      // that accessor. Same "expose internals for the bootstrap" pattern as
      // boardTiles/sessionState below, not a new mount contract: mount(root,
      // ctx)/update(state) are unchanged.
      viewSlots: function () { return { board: els.viewBoard, sessions: els.viewSessions, detail: els.viewDetail }; },
      // exposed for tests / a bootstrap that wants the pure derivations directly
      boardTiles: boardTiles,
      sessionState: sessionState,
      railOrder: railOrder,
      agentGroups: agentGroups,
      triageCounts: triageCounts,
      activityHistogram: activityHistogram,
      // Bug 2 fix: pure decision behind the Landed tile's PR render — see prInfo()'s
      // definition above.
      prInfo: prInfo,
      // the ONE model-shortening helper (see its definition above) — exposed
      // so ext_cr_detail.js (loaded after this file) reuses it rather than
      // forking a second mapping.
      modelShort: modelShort,
    };
  }

  window.CR.board = createBoard();
})();
