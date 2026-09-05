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

  // Sort rank for the board — doc 02 "Sort order" gives awaiting/flagged/working/
  // landed/idle verbatim but is silent on 'failing' (01-foundations.md's state
  // table names six states; doc 02's own RANK object only ever had five). Slotted
  // between flagged and working: 01's table lists Failing right after Flagged, and
  // both are "something is actively wrong" states that outrank plain 'working' —
  // awaiting/flagged keep their original 0/1 values (no reshuffle above 'failing'),
  // working/landed/idle each shift down by one to make room.
  var RANK = { awaiting: 0, flagged: 1, failing: 2, working: 3, landed: 4, idle: 5 };

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
  // `state` here is derived from waiting/open_flags/fail_cmd/mtime+ended, mirroring
  // the precedence app.js's own sidebar already uses (waiting > done-if-live
  // > live > idle — aitracker/web/app.js:817-820), with open_flags slotted
  // into RANK's 'flagged' step. The doc's state vocabulary (01-foundations.md)
  // also names a sixth state, "Failing" (a command/test returned non-zero) —
  // that signal is computed today ONLY inside a session's parsed *detail* dict
  // (parse_session()'s `counts.errors`/`counts.tests_failed`, providers/claude.py),
  // never emitted into the list-endpoint shape (list_sessions()) this module is
  // fed, so this board has no live source for it yet (a REQUIRED ADDITION: thread
  // a `fail_cmd` string — the failing command's name, ''/absent when nothing is
  // failing — into the list dict the same way `open_flags`/`pr_num`/`note_count`
  // already are). Wired defensively ahead of that addition, same pattern this file
  // already uses for pr_num et al: the check below is a no-op today (no provider
  // ever sets `fail_cmd`) and lights up the instant one does, with zero risk to
  // any session that doesn't carry the field.
  function sessionState(s, now) {
    var live = (now - (s.mtime || 0)) < LIVE_WINDOW;
    if (s.waiting) return 'awaiting';
    if (s.open_flags) return 'flagged';
    if (live && s.fail_cmd) return 'failing';
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
  // individually-ranked tiles, before the board tile cap (boardTileCap()) is applied.
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

  // GAP CLOSE (rail parity, requirement/task 2): classic's collapseAgents()
  // (app.js) folds re-runs of the SAME agent task (same prompt, falling back
  // to title/id) into one row, newest run's fields winning, with `_runs`
  // counting how many were folded — otherwise a task re-executed a dozen
  // times floods an expanded "🤖 Agents · <repo>" bucket with a dozen
  // near-identical rows instead of one. Ported here (rail's agent-bucket
  // expansion, below, had no equivalent — every run rendered its own row)
  // rather than shared, since app.js is out of this file's ownership for this
  // task; same Object.assign-style semantics (a plain-object copy stands in
  // for the spread/Map original, order preserved via a parallel array since
  // insertion order on string keys is reliable here).
  function collapseAgentRuns(arr) {
    var by = {}, order = [];
    arr.forEach(function (s) {
      var key = s.prompt || s.title || s.id;
      var g = by[key];
      if (!g) {
        g = {};
        Object.keys(s).forEach(function (k) { g[k] = s[k]; });
        g._runs = 1;
        by[key] = g;
        order.push(g);
      } else {
        var runs = g._runs + 1;
        if ((s.mtime || 0) >= (g.mtime || 0)) { Object.keys(s).forEach(function (k) { g[k] = s[k]; }); }
        g._runs = runs;
      }
    });
    return order;
  }

  // Config now writes a user preference for the board's tile cap —
  // `cr.boardTileCount`, a JSON-encoded integer 3-12 (localStorage). Read fresh
  // on every call (never cached at mount) so the Config change takes effect on
  // the next 2s poll re-render with no reload. Absent/unparseable/out-of-range
  // always falls back to the default of 8. Ceiling is 12 per doc 04
  // ("Board tiles | slider 3-12, default 8") — the owner ruled doc 04's 3-12
  // wins over doc 02's "never more than 8 tiles" line, which is superseded.
  function boardTileCap() {
    var raw = null;
    try { raw = JSON.parse(localStorage.getItem('cr.boardTileCount')); } catch (e) { raw = null; }
    var n = (typeof raw === 'number' && isFinite(raw)) ? Math.round(raw) : 8;
    return Math.max(3, Math.min(12, n));
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
  // never more than boardTileCap() tiles — default 8, user-adjustable 3-12 per
  // doc 04 (owner-ruled to supersede doc 02's flat "never more than 8");
  // pinned group on top, unpinned below, newest first within each group —
  // waiting-on-you outranks everything, including recency; idle sessions
  // never get a tile; agent-group tiles sit last.
  function boardTiles(sessions, now) {
    var individual = sessions
      // Exclude only agents that a group tile will actually represent (agent:true
      // WITH a non-empty `group` — a real `claude --bg` agent whose session isn't
      // sdk-cli-sourced gets group:"" from providers/claude.py's _agent_group(),
      // since that helper only buckets sdk-cli sessions). The bug this predicate
      // fixes: a naive `!s.agent` here would drop every agent session from
      // `individual`, and agentGroups() below independently skips anything with
      // no `group` key (`if (!s.agent || !s.group) return;`) — so a plain `!s.agent`
      // filter would strand agent:true/group:"" sessions in neither path, vanishing
      // from the board entirely (live-verified once: 950 sessions, 1 working, 0
      // tiles). Chosen fix here is "include individually when non-idle": this
      // exact `!(s.agent && s.group)` predicate keeps an ungrouped agent session
      // in `individual` (only agent+group together are excluded), so it gets
      // ranked and tiled exactly like any other session — smaller diff than
      // building a second "(no group)" bucket path through agentGroups().
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
  // than the single derived `state` above, because the four counts are not
  // mutually exclusive the way a per-tile state is — a session can be both
  // "working" and "flagged" at once, and the strip's copy ("Flagged") never
  // says these subtract from each other. PINNED (owner addition, not in doc
  // 02's three-cell table) counts every pinned session regardless of
  // liveness/state, same as the other three counting across ALL sessions —
  // not just what the 8-tile board happens to show.
  function triageCounts(sessions, now) {
    var awaiting = 0, working = 0, flagged = 0, pinned = 0;
    sessions.forEach(function (s) {
      var live = (now - (s.mtime || 0)) < LIVE_WINDOW;
      if (s.waiting) awaiting++;
      else if (live && !s.ended) working++;
      if (s.open_flags) flagged++;
      if (s.pinned) pinned++;
    });
    return { awaiting: awaiting, working: working, flagged: flagged, pinned: pinned };
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

  // "tool" (as in "age · tool" / "project · tool") isn't a field the list
  // dict carries; the nearest available signal is `source`. This used to
  // maintain its own 4-entry SOURCE_LABEL map — a second, incomplete copy of
  // app.js's real one (SRC/srcLabel, app.js:818-819, all 7 known source ids:
  // '', 'cli', 'claude-desktop', 'sdk-cli', 'claude-vscode', 'auggie',
  // 'augment-vscode', 'augment-cursor') — so claude-desktop/sdk-cli/
  // claude-vscode sessions rendered their raw internal id on their tile.
  // `srcLabel` IS reachable here: page.py concatenates every web/*.js file
  // into ONE <script> tag, app.js first (page.py: read("app.js") +
  // read_ext(".js")), so its top-level `const srcLabel` sits in the same
  // script-level scope this IIFE closes over — verified by reading page.py.
  //
  // Round-5 drift (decision 4b): 5a's own board tiles render this label as an
  // all-lowercase, no-parens literal ("2m · claude cli"), never the Title-
  // Case + icon-glyph form app.js's SRC map uses for the classic dashboard —
  // grep-verified against the prototype HTML itself (30 hits for "claude
  // cli", 4 for "auggie cli", 6 for "augment vs code", 6 for "augment
  // cursor", all lowercase, all inline text, never CSS text-transform). Kept
  // as a TRANSFORM applied over the real map's output, not a second
  // hand-written table: strip SRC's leading icon glyph, drop parens,
  // lowercase, then two small CONTENT-driven (never source-id-keyed)
  // fixups — a bare vendor-less word gets a "claude " prefix (every
  // Claude-family SRC label omits the vendor, since SRC is this app's own
  // map and Claude is its default/implied vendor; Auggie/Augment already
  // spell theirs), and the one vendor word with no surface of its own
  // ("auggie") gets " cli" appended. '' falls back to the 'cli' entry
  // (srcLabel('') itself resolves to '' — SRC has no '' key, only 'cli').
  function toolLabel(source) {
    if (typeof srcLabel !== 'function') return source || 'unknown';
    var label = srcLabel(source || 'cli').replace(/^\S+\s*/, '').toLowerCase().replace(/[()]/g, '');
    if (!label) return source || 'unknown';
    if (label.indexOf('aug') !== 0) label = 'claude ' + label;
    else if (label === 'auggie') label += ' cli';
    return label;
  }

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
    // 1024-1279px) was written to localStorage and then silently discarded --
    // a visible button, correctly labelled, that did nothing.
    // NOTE the key is 'tracker.rail.mode', not the older 'tracker.rail'. The old
    // key's vocabulary was 'open'|'collapsed' with 'open' as the literal default,
    // so a stored 'open' was indistinguishable from 'never chose' -- and the dead
    // toggle wrote one on every frustrated click. Reading those values as an
    // EXPLICIT 'open' here would hand existing users a 300px rail in the detail
    // view they never asked for. A new key starts everyone at 'auto', which is
    // byte-for-byte the old default behaviour. The stale key is left alone.
    var railMode = (localStorage.getItem('tracker.rail.mode') || 'auto');
    var railOverlayOpen = false;      // < 1024px only: the rail as a slide-in overlay drawer
    var activeFilter = null;          // 'awaiting' | 'working' | 'flagged' | 'pinned' | null
    var searchQuery = '';
    // GAP CLOSE (rail parity): mirrors classic's `liveOnly` (app.js) — the
    // rail had no equivalent of the sidebar's "N live ✕" click-to-filter.
    var railLiveOnly = false;
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

    function glyph(name, cls, label) {
      return h('span', { class: 'tn-emo' + (cls ? ' ' + cls : ''), 'aria-hidden': 'true', title: label || null },
        [icon(name)]);
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
        // GAP CLOSE (rail parity): a real <button> now (was a bare <span>) so
        // it can toggle railLiveOnly, mirroring classic's clickable "N live"
        // pill (app.js `livecount`) — title/aria-label are set live in
        // renderRail() since the label depends on the current toggle state.
        (els.railCount = h('button', { class: 'cr-rail-count', type: 'button', onclick: toggleRailLiveOnly }, ['0'])),
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
      // Below 1024px the rail isn't in-flow (open vs collapsed doesn't
      // apply — doc 02's breakpoint table has it "hidden; rail becomes an
      // overlay"), so the same toggle drives the overlay drawer instead.
      // Threshold is `< 1024` (not `<= 1024`) so it agrees with the CSS's
      // `max-width: 1023px` rail-overlay tier — 1024px itself belongs to
      // the wider "2 columns, docked/collapsed rail" tier per the doc.
      if (window.innerWidth < 1024) {
        if (railOverlayOpen) closeRailOverlay(); else openRailOverlay();
        return;
      }
      // Flip against what is ACTUALLY on screen, not against the stored mode:
      // under 'auto' the two disagree (detail view and the 1024-1279px tier are
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
    // (openSession), and a resize back to >= 1024px (bindResize) — safe to call
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
      // Lower bound is `>= 1024` (not `>= 1025`) so this in-flow "collapsed
      // icon rail" tier (1024-1279, doc 02's breakpoint table) sits directly
      // against the `< 1024` rail-overlay tier above with no gap and no
      // overlap — 1024px itself is docked/collapsed, not overlay, per the
      // doc's own table (a prior "BLOCKER 4" pass had shifted this to
      // `>= 1025` to match the CSS's now-superseded `<=1024` overlay
      // boundary; the owner's docs-win ruling supersedes that).
      // The detail view and the 1024-1279px tier collapse the rail BY DEFAULT,
      // but an explicit toggle overrides them -- otherwise the control is dead.
      var autoCollapsed = isDetail || (window.innerWidth < 1280 && window.innerWidth >= 1024);
      var collapsed = (railMode === 'auto') ? autoCollapsed : (railMode === 'collapsed');
      els.rail.classList.toggle('cr-rail--collapsed', collapsed);
      // 56px orb styling is the COLLAPSED detail rail; once the user expands it
      // explicitly the full 300px row rail must win, so --detail comes off too.
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
        var underlay = window.innerWidth < 1024;
        if (!underlay) closeRailOverlay();   // resizing back to >= 1024px cleans up the overlay + scrim
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

    // GAP CLOSE (rail parity, owner ruling): this used to `return` on the FIRST
    // truthy of flags/bg/age, so a flagged row silently LOST its age and a row
    // with background agents lost it too -- the classic sidebar (app.js
    // sessionRow) shows the flag badge, the agent chip AND the age together.
    // Doc 02's "one trailing slot" row anatomy is superseded by the owner's
    // "absolute feature parity with the old default view, including the
    // information present in there". Returns the parts joined, never one.
    function railRowMeta(s, now) {
      // Resolved with the icon conversion: the glyphs are ELEMENTS now, so this
      // builds an ARRAY and concat()s -- never .join(), which would stringify a
      // glyph span into "[object HTMLSpanElement]" (the exact trap the icon
      // branch's own merge notes call out).
      var groups = [];
      if (s.open_flags) groups.push([glyph('flag', 'tn-emo-f'), ' ' + s.open_flags + ' flag' + (s.open_flags !== 1 ? 's' : '')]);
      if (s.note_count) groups.push([glyph('note', ''), ' ' + s.note_count]);
      if (s.bg) groups.push([glyph('agent', ''), ' ' + s.bg]);
      groups.push([ago(now - (s.mtime || 0))]);
      var out = [];
      groups.forEach(function (g, i) {
        if (i) out.push(' · ');
        out = out.concat(g);
      });
      return out;
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
          [glyph('pin'), 'Pinned — ' + pinnedShown.length + ' · newest first']));
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
            title: 'Agents · ' + b.label, 'aria-label': 'Agents · ' + b.label,
            onclick: function () { ctx && ctx.emit && ctx.emit('rail:expandAgents', { group: g }); },
            onkeydown: function (e) { if (e.key === 'Enter') ctx && ctx.emit && ctx.emit('rail:expandAgents', { group: g }); }
          }, [glyph('agent', '', null), 'Agents · ' + esc(b.label) + (b.live ? ' (' + b.live + ' live)' : ''),
              h('span', { class: 'cr-rail-agentchevron' }, [icon('chevron', '<path d="M9 6l6 6-6 6"/>')])]));
          if (isOpen) {
            collapseAgentRuns(b.sessions).sort(function (a, c) { return (c.mtime || 0) - (a.mtime || 0); })
              .forEach(function (s) { container.appendChild(railRow(s, now)); });
          }
        });
      }

      return { total: flat.length, shown: windowed.length };
    }

    function renderRail(state) {
      if (!els.railList) return;
      var sessions = state.sessions || [], now = state.now;
      // GAP CLOSE (rail parity): classic's "N live ✕" pill (app.js's
      // `livecount`) filters the WHOLE sidebar to live sessions on click; the
      // rail's count was display-only. Isolated to this file's two rail-only
      // call sites below (renderSessionRows' OTHER caller, the Sessions
      // destination at line ~1085ish, is untouched — the owner's instruction
      // is not to alter that view) — `baseSessions` stands in for `sessions`
      // in both branches, same as classic's own `shown=liveOnly?...:sessions`.
      var baseSessions = railLiveOnly
        ? sessions.filter(function (s) { return (now - (s.mtime || 0)) < LIVE_WINDOW; })
        : sessions;
      // innerHTML is safe here: the only interpolated value is a NUMBER (a count),
      // never a session-derived string. The clear-the-filter affordance is an icon.
      if (railLiveOnly) els.railCount.innerHTML = baseSessions.length + ' live ' + ico('close');
      else els.railCount.textContent = String(sessions.length);
      els.railCount.classList.toggle('cr-rail-count--on', railLiveOnly);
      var railCountLabel = railLiveOnly ? 'Showing live only — click to show all' : 'Click to show live sessions only';
      els.railCount.title = railCountLabel;
      els.railCount.setAttribute('aria-label', railCountLabel);

      var scrollTop = els.railList.scrollTop;
      var activeEl = document.activeElement;
      var activeWasSearch = (activeEl === els.railSearchInput);

      var collapsed = els.rail.classList.contains('cr-rail--collapsed');
      els.railList.innerHTML = '';

      var shown;
      if (collapsed) {
        var filtered = railRowsFor(baseSessions.filter(function (s) { return !s.agent; }));
        var order = railOrder(filtered);
        renderCollapsedOrbs(order, now);
        shown = order.pinned.length + order.unpinned.length;
      } else {
        shown = renderSessionRows(els.railList, baseSessions, now).total;
      }

      var more = baseSessions.length - shown;
      els.railFooter.textContent = 'scroll · ' + Math.max(0, more) + ' more';

      els.railList.scrollTop = scrollTop;
      if (activeWasSearch) els.railSearchInput.focus();
    }

    function toggleRailLiveOnly() {
      railLiveOnly = !railLiveOnly;
      renderRail(lastState);
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
      // GAP CLOSE (rail parity, owner ruling): the classic sidebar's meta line is
      // `project · source · age` (app.js sessionRow's `bits`), and its row carries a
      // waiting/done status badge. The rail had NONE of the three. Mirrored here
      // field-for-field, reusing what already exists rather than re-deriving:
      //   - project: classic shows s.project when a custom title replaced it,
      //     else the short id -- the exact same ternary, not an approximation.
      //   - source: this file's OWN toolLabel() (used by the tiles already),
      //     which wraps app.js's srcLabel/SRC map. Never a second copy of it.
      //   - status: app.js's own end-state rule verbatim -- "waiting on your
      //     answer" wins even while still live, and "done" is gated to the live
      //     window so stale idle sessions don't flood the rail with checkmarks.
      // Both `waiting` and `ended` ride the SHARED list dict (claude.py and
      // auggie.py both emit them), so this lights up for both providers.
      var projLabel = s.title ? (s.project || '') : (s.id || '').slice(0, 8);
      var srcLabelText = toolLabel(s.source);
      var isLiveRow = (now - (s.mtime || 0)) < LIVE_WINDOW;
      // Icon conversion: no literal emoji here -- the badge renders through the
      // shared sprite (glyph/'hourglass'/'check'), same as every other icon in
      // this file, so it follows ICON_STYLE (icons/emoji/text) like the rest.
      var statusKind = s.waiting ? 'waiting' : ((s.ended && isLiveRow) ? 'done' : '');
      // GAP CLOSE: flag_text rides the row's existing tooltip too — same reasoning as
      // tileHead() above. '' when null/absent, so an unflagged row's tooltip is
      // byte-for-byte unchanged.
      // GAP CLOSE (rail parity, requirement/task 2): the classic sidebar shows
      // a visible 📝N note badge on every row (app.js's sessionRow()); doc 02's
      // own row anatomy caps trailing metadata at ONE slot ("age, or 🚩 count,
      // or agent count") with no room for a second badge, so the note count
      // rides the tooltip instead of a new visible element — reachable, same
      // as flag_text already was, without widening the row or adding a second
      // always-on badge doc 02 never specified.
      var titleAttr = (s.prompt || s.snippet || s.title || '(no prompt)') + '\n' + (s.cwd || '') +
        (s.model ? '\nModel: ' + s.model : '') +
        (todoLabel ? '\n' + (s.todo_done || 0) + ' of ' + s.todo_total + ' todos done' +
          (s.todo_current ? ' — in progress: ' + s.todo_current : '') : '') +
        (s.flag_text ? '\nFlags: ' + s.flag_text : '') +
        (s.note_count ? '\nNotes: ' + s.note_count + ' note' + (s.note_count === 1 ? '' : 's') : '');
      // Colour never carries meaning alone: the state word (and, for a pinned
      // session, "(pinned)") rides along in aria-label (title keeps the fuller
      // prompt/cwd/snippet tooltip it already had).
      var label = name + (s.pinned ? ' (pinned)' : '') + (dir ? ', ' + dir : '') + ' — ' + orbStateWord(state) +
        (todoLabel ? ', ' + todoLabel + ' todos' : '');
      // Search-result rows (requirement 5's ordering note): the server's
      // ranking is used AS-IS — pinned and agent states are shown via dot
      // colour and UI elements, not as inline prefixes, to keep the title
      // clean and avoid duplicate visual indicators.
      var displayName = name;
      // GAP CLOSE (rail parity): the classic sidebar's row carries an inline
      // pin toggle (pin icon, togglePin()) and rename control (edit icon,
      // renameSession()) — the rail only ever DISPLAYED pinned state (the dot
      // colour + aria-label above), with no way to pin/unpin or rename a
      // session anywhere in this UI. Mirrors classic exactly: same
      // `stopPropagation` (so clicking either button opens nothing), same
      // title/on-state semantics.
      var actions = h('div', { class: 'cr-rail-actions' }, [
        h('button', {
          class: 'cr-rail-pin' + (s.pinned ? ' cr-rail-pin--on' : ''), type: 'button',
          title: s.pinned ? 'Unpin' : 'Pin to top', 'aria-label': s.pinned ? 'Unpin' : 'Pin to top',
          onclick: function (e) { e.stopPropagation(); toggleSessionPin(s.id); }
        }, [glyph('pin', '')]),
        h('button', {
          class: 'cr-rail-rename', type: 'button',
          title: 'Rename', 'aria-label': 'Rename this session',
          onclick: function (e) {
            e.stopPropagation();
            if (ctx && typeof ctx.dialog === 'function') ctx.dialog('rename', { sessionId: s.id, currentTitle: s.title || '' });
          }
        }, [glyph('edit', '')]),
      ]);
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
        statusKind ? h('span', {
          class: 'cr-rail-status cr-rail-status--' + statusKind,
          title: statusKind === 'waiting'
            ? 'waiting for your answer — respond in the session'
            : 'completed its last run',
        }, [glyph(statusKind === 'waiting' ? 'hourglass' : 'check', ''),
            ' ' + (statusKind === 'waiting' ? 'answer' : 'done')]) : null,
        h('span', { class: 'cr-rail-meta' },
          // GAP CLOSE (rail parity): `s._runs` only exists on a row folded by
          // collapseAgentRuns() above (a re-run collapsed into one row) —
          // classic's own `×N` badge (app.js: `s._runs>1`), absent everywhere
          // else, same as todoLabel already was. railRowMeta() can return icon
          // elements (glyph()), not just strings, so this stays an array
          // `.concat()` rather than a `.join()` — a naive string join would
          // stringify a DOM node instead of rendering it.
          // The project name and source label are the classic sidebar's own
          // meta line (app.js sessionRow's `bits`), added here for parity.
          (s._runs > 1 ? ['×' + s._runs + ' · '] : [])
            .concat(todoLabel ? [todoLabel + ' · '] : [])
            .concat(projLabel ? [projLabel + ' · '] : [])
            .concat(srcLabelText ? [srcLabelText + ' · '] : [])
            .concat(railRowMeta(s, now))),
        actions,
      ]);
    }

    // GAP CLOSE (rail parity): classic's togglePin() (app.js) POSTs the
    // existing /api/pin route directly from its sidebar module — no bus
    // event/bridge exists for it (unlike cr:rename, which cr_dialogs.js +
    // ext_cr_boot.js already wire end-to-end). Adding a NEW 'cr:pin-toggle'
    // bridge would mean editing ext_cr_boot.js, which is outside this file's
    // ownership for this task — so this calls the SAME already-shipped
    // /api/pin route directly, exactly like this file already does for
    // /api/search (see doSearch below); optimistic local update + re-render
    // (rail/board/triage all read `pinned` off the same session objects) so
    // the toggle reflects immediately rather than waiting on the next 2s poll.
    function toggleSessionPin(id) {
      var s = null;
      (lastState.sessions || []).some(function (x) { if (x.id === id) { s = x; return true; } return false; });
      if (!s || typeof fetch !== 'function') return;
      var next = !s.pinned;
      fetch('/api/pin', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session: id, pinned: next }),
      }).then(function (r) { return r.ok; }).then(function (ok) {
        if (!ok) return;
        s.pinned = next;
        renderRail(lastState);
        renderBoard(lastState);
        renderTriage(lastState);
      });
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
      }, [glyph('flag', 'tn-emo-f'), '0']);
      els.topbar.appendChild(els.flagCountBtn);

      els.topbar.appendChild(h('button', {
        class: 'cr-bell', type: 'button', title: 'Notifications', 'aria-label': 'Notifications',
        onclick: function () { ctx && ctx.emit && ctx.emit('toggle:notifications'); }
      }, [glyph('bell', '')]));

      // BLOCKER 1: 'Config'/'Help' labels wrapped in `.cr-topbar-label` so the
      // phone-tier CSS can drop to icon-only — `title`/`aria-label` already
      // carry the full text so the accessible name is unaffected.
      els.topbar.appendChild(h('button', {
        class: 'cr-icon-btn', type: 'button', title: 'Config', 'aria-label': 'Config',
        onclick: function () { ctx && ctx.emit && ctx.emit('open:config'); }
      }, [glyph('gear', ''), h('span', { class: 'cr-topbar-label' }, ['Config'])]));

      els.topbar.appendChild(h('button', {
        class: 'cr-icon-btn', type: 'button', title: 'Help', 'aria-label': 'Help',
        onclick: function () { ctx && ctx.emit && ctx.emit('open:help'); }
      }, [glyph('help', ''), h('span', { class: 'cr-topbar-label' }, ['Help'])]));

      buildThemeControl();

      // BLOCKER 1: 'New session' label wrapped in `.cr-topbar-label` so the
      // phone-tier CSS can drop to icon-only. `aria-label` is new — this
      // button previously had none, relying entirely on the (now hideable)
      // text node for its accessible name. `title` (doc 02: "icon-only
      // controls need a `title` and an `aria-label` sourced from the same
      // string") was missing entirely — added here, same text as aria-label.
      els.topbar.appendChild(h('button', {
        class: 'cr-newsession', type: 'button', title: 'New session', 'aria-label': 'New session',
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
      cell('pinned', 'PINNED');

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
      ['awaiting', 'working', 'flagged', 'pinned'].forEach(function (key) {
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

    function passesFilter(t, now) {
      if (!activeFilter) return true;
      // PINNED (owner addition): not a per-tile `state` value, so it needs its
      // own branch, same shape as the 'flagged' special-case below. An
      // agent-group tile has no `.session` (it aggregates several), but DOES
      // carry its own `.pinned` (agentGroups() ORs every member's pinned flag
      // onto the group) — read straight off `t` for a group, off `t.session`
      // for an individual session tile.
      if (activeFilter === 'pinned') return t.kind === 'session' ? !!t.session.pinned : !!t.pinned;
      // TWO BUGS on the line this replaces, both in the group-tile branch:
      //   1. It read `t.session.open_flags` -- but an agent-group tile has NO
      //      `.session`; it aggregates several under `.sessions` (plural, see
      //      agentGroups()). So the 'flagged' filter threw a TypeError the
      //      moment any group tile was on the board.
      //   2. Every other filter returned a flat `false`, so the sessions folded
      //      into a group were invisible to the 'awaiting'/'working' filters --
      //      while triageCounts() counts those same sessions in the strip. That
      //      is a cell reading a non-zero count that renders an empty board.
      // A group passes when ANY member session matches, which is the same
      // question the strip's own count asked.
      if (t.kind !== 'session') {
        var when = (typeof now === 'number') ? now : ((lastState && lastState.now) || 0);
        return (t.sessions || []).some(function (m) {
          return activeFilter === 'flagged'
            ? !!m.open_flags
            : sessionState(m, when) === activeFilter;
        });
      }
      if (activeFilter === 'flagged') return !!t.session.open_flags;
      return t.state === activeFilter;
    }

    function renderBoard(state) {
      var sessions = state.sessions || [], now = state.now;
      var allTiles = boardTiles(sessions, now);
      var tiles = allTiles.filter(function (t) { return passesFilter(t, now); });

      // A8: mirrors renderRail()'s / renderSessionsView()'s own scroll-position
      // preservation across a poll re-render — same pattern (snapshot scrollTop
      // of the actual overflow:auto container before clearing its content,
      // restore it after), not a second one. The board's scrolling element is
      // els.boardScroll (`.cr-board-scroll`, `overflow-y:auto` in
      // ext_cr_board.css) — a parent of els.board, the grid whose innerHTML
      // this function replaces — because els.board itself has no overflow of
      // its own. Doc 02's keyboard section calls re-render scroll/focus loss
      // "the single most likely regression."
      var scrollTop = els.boardScroll.scrollTop;

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

      els.boardScroll.scrollTop = scrollTop;

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
    // 01-foundations.md's state table gives Failing's word as `"fail" + command
    // name` — rendered here as "fail: <command>" (colon-joined, matching the
    // "N flags open"/"Waiting on you · <age>" convention of always spelling the
    // dynamic part out in full, never a bare label). `s.fail_cmd` is the same
    // (currently unwired server-side, see sessionState()'s note) command-name
    // field that gates 'failing' in sessionState() in the first place, so this
    // branch is only ever reached when there's a real command name to show.
    function stateWord(state, s) {
      if (state === 'flagged') {
        var n = (s && s.open_flags) || 0;
        return n + ' flag' + (n === 1 ? '' : 's') + ' open';
      }
      if (state === 'failing') return 'fail: ' + (s && s.fail_cmd);
      return { awaiting: 'Waiting on you', working: 'Working', landed: 'Landed' }[state] || state;
    }
    function stateIcon(state) {
      return { awaiting: ['hourglass', 'tn-emo-a'], working: ['working', ''], flagged: ['flag', 'tn-emo-f'], failing: ['x', 'tn-emo-f'], landed: ['check', 'tn-emo-d'] }[state] || ['', ''];
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
      var ew = stateIcon(state);
      // GAP CLOSE: flag_text (registry.py's list dict, s.flag_text) is the unresolved
      // flag's own text — the badge above already carries the COUNT (stateWord's "N
      // flags open"); the text rides the same `title` tooltip mechanism every other
      // tile/row metadatum already uses here (see attrs.title below, railRow's
      // titleAttr). null (no open flag) means no `title` attribute at all — h()
      // skips null/undefined attrs, so there's never a stray empty tooltip.
      // Extended (truncation follow-up) to 'failing': the tile's own text now
      // ellipsizes at width (ext_cr_board.css .cr-tile-state), so the full
      // fail_cmd string needs the same title-tooltip escape hatch flag_text
      // already had, or a long command name would be unrecoverably clipped.
      var flagTitle = (state === 'flagged' && s.flag_text) ? s.flag_text
        : (state === 'failing' && s.fail_cmd) ? stateWord(state, s) : null;
      var kids = [
        glyph(ew[0], ew[1]),
        h('span', { class: 'cr-tile-state', title: flagTitle }, [stateWord(state, s) + (state === 'awaiting' ? ' · ' + ago(now - (s.mtime || 0)) : '')]),
      ];
      if (s.pinned) kids.push(glyph('pin', '', 'Pinned'));
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
      // Doc 02 tile-anatomy table / 01-foundations.md ~line 271: EVERY 'Working'
      // tile gets the --line-agent border plus --glow-agent-soft + --shadow-raised
      // — unconditional, not gated on live background agents. (`.cr-tile--working`
      // in ext_cr_board.css now carries border+glow directly; the owner reversed
      // the prior "only when s.bg > 0" restriction that used to live here.)
      var attrs = tileBaseAttrs(t);
      attrs.class = cls;
      attrs.title = (s.prompt || s.title || '(no prompt)') + '\n' + (s.cwd || '') +
        (s.model ? '\nModel: ' + s.model : '');

      var body = [
        tileHead(s, state, now),
        h('div', { class: 'cr-tile-title' }, [tileTitleText(s, state)]),
      ];
      // Doc 02 tile-anatomy table: EVERY tile gets a "project · tool" sub-line
      // (mono 10.5px, muted) between the title and the live/summary line — not
      // just the hero. The owner reversed the prior round-5 "hero only" drift
      // (which had cited the artboard's three-div markup over the doc); the
      // doc wins now, restored to all states.
      body.push(h('div', { class: 'cr-tile-sub' }, [(s.project || '') + ' · ' + toolLabel(s.source)]));
      var line = tileLine(s, state);
      if (line) body.push(line);
      var ticks = todoTicks(s);
      if (ticks) body.push(ticks);
      var pr = tilePr(s, state);
      if (pr) body.push(pr);

      if (t.hero) {
        // Item 1: 5a's hero splits HORIZONTALLY — the main column (head/title/
        // sub/line/ticks/pr, `body` above) at `flex:1` beside a `flex:0 0 124px`
        // side rail, separated by a vertical border-left — not a vertical stack.
        // `body` is wrapped in its own `.cr-tile-main` column so `.cr-tile-inner`
        // itself can switch to a row flex (ext_cr_board.css) with the sidebar as
        // a true sibling column, matching 5a's own two-column markup exactly.
        var main = h('div', { class: 'cr-tile-main' }, body);
        // NOTE: files/failing counts the doc's hero side-rail calls for
        // aren't in the list dict either; only `note_count` is available.
        // Rendered honestly with what exists rather than fabricating the
        // other two counters — REQUIRED ADDITION in the report.
        var sidebar = h('div', { class: 'cr-tile-sidebar' }, [
          h('div', { class: 'cr-tile-counts' }, [glyph('note', 'tn-emo-n'), (s.note_count || 0) + ' notes']),
          h('button', {
            class: 'cr-tile-action', type: 'button',
            onclick: function (e) { e.stopPropagation(); ctx && ctx.emit && ctx.emit('terminal:open', { id: s.id }); }
          }, ['Open terminal to answer']),
        ]);
        var inner = h('div', { class: 'cr-tile-inner' }, [main, sidebar]);
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
      attrs.title = 'Agents · ' + t.label;
      var total = t.sessions.length;
      var live = t.sessions.filter(function (s) { return sessionState(s, now) !== 'idle'; }).length;
      var sentence = total + ' background agent' + (total === 1 ? '' : 's') +
        ' running in ' + t.label + (live && live !== total ? ' (' + live + ' active now)' : '') + '.';
      return h('div', attrs, [
        h('div', { class: 'cr-tile-head' }, [
          icon('chevron', '<path d="M9 6l6 6-6 6"/>'),
          glyph('agent', ''),
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
      // clamped 3-12 per doc 04) — the copy's shape is doc 02's "Cap footer"
      // verbatim, only the number is dynamic.
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
          if (!payload) return;
          // Config's "Board tiles" row writes cr.boardTileCount, which boardTileCap()
          // reads fresh on every call -- but nothing repainted on the write, so the
          // slider moved a number in localStorage and left the board untouched until
          // some unrelated poll happened to redraw it. That is the identical
          // dead-control bug the rail-mode branch below exists to fix, so the cap
          // gets the same treatment: repaint the board (and its cap footer) now.
          if (payload.key === 'cr.boardTileCount') {
            if (lastState) renderBoard(lastState);
            return;
          }
          if (payload.key !== 'tracker.rail.mode') return;
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
