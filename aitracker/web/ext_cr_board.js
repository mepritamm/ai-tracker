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

  // THE RULE (doc 02 "Sort order — this is the design"; README decision 2):
  // never more than 8 tiles; pinned group on top, unpinned below, newest
  // first within each group — waiting-on-you outranks everything, including
  // recency; idle sessions never get a tile; agent-group tiles sit last.
  function boardTiles(sessions, now) {
    var individual = sessions
      .filter(function (s) { return !s.agent; })
      .map(function (s) { return { kind: 'session', session: s, state: sessionState(s, now) }; })
      .filter(function (t) { return t.state !== 'idle'; })
      .sort(function (a, b) {
        return (RANK[a.state] - RANK[b.state]) ||                                   // claim on attention first
               ((b.session.pinned ? 1 : 0) - (a.session.pinned ? 1 : 0)) ||          // then pinned
               (b.session.mtime - a.session.mtime);                                 // then recency
      });
    var groups = agentGroups(sessions, now);
    var tiles = individual.concat(groups).slice(0, 8);   // HARD CAP
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
  var SOURCE_LABEL = { '': 'Claude Code', 'auggie': 'Auggie',
                        'augment-vscode': 'VS Code', 'augment-cursor': 'Cursor' };
  function toolLabel(source) { return SOURCE_LABEL[source || ''] || (source || 'unknown'); }

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
    var railMode = (localStorage.getItem('tracker.rail') || 'open');   // 'open' | 'collapsed'
    var railOverlayOpen = false;      // < 1024px only: the rail as a slide-in overlay drawer
    var activeFilter = null;          // 'awaiting' | 'working' | 'flagged' | null
    var searchQuery = '';
    var focusedTileId = null;         // preserved across update() re-renders
    var selectedSessionId = null;     // for rail row highlight, set by ctx events if any
    var lastState = { sessions: [], now: Math.floor(Date.now() / 1000) };
    var expandedRailGroup = null;     // which agent-group bucket (by `group` key) is expanded
                                       // in the rail — 'rail:expandAgents' toggles this; own
                                       // state, single-module, per this file's own scope note.

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

    function emoji(char, cls, label) {
      return h('span', { class: 'tn-emo' + (cls ? ' ' + cls : ''), 'aria-hidden': 'true', title: label || null },
        [char]);
    }

    // -- shell (built once) ------------------------------------------------

    function buildShell() {
      root.classList.add('tracker-next', 'cr-app');
      root.innerHTML = '';

      els.rail = h('aside', { class: 'cr-rail', role: 'complementary', 'aria-label': 'All sessions' });
      els.main = h('div', { class: 'cr-main' });
      els.topbar = h('header', { class: 'cr-topbar' });
      els.triage = h('div', { class: 'cr-triage' });
      els.boardScroll = h('div', { class: 'cr-board-scroll' });
      els.board = h('div', { class: 'cr-board', role: 'list', 'aria-label': 'Sessions needing attention' });
      els.capfooter = h('div', { class: 'cr-capfooter' });
      els.boardScroll.appendChild(els.board);
      els.boardScroll.appendChild(els.capfooter);
      els.main.appendChild(els.topbar);
      els.main.appendChild(els.triage);
      els.main.appendChild(els.boardScroll);

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
        h('span', { class: 'cr-rail-brand' }, [icon('spark', '<path d="M12 2l2 7h7l-5.5 4.5L17 21l-5-4-5 4 1.5-7.5L3 9h7z"/>')]),
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

      els.railList = h('div', { class: 'cr-rail-list' });
      els.rail.appendChild(els.railList);

      els.railFooter = h('div', { class: 'cr-rail-footer' }, ['scroll · 0 more']);
      els.rail.appendChild(els.railFooter);
    }

    function toggleRail() {
      // Below 1024px the rail isn't in-flow (open vs collapsed doesn't apply —
      // doc 02's breakpoint table has it "hidden; rail becomes an overlay"),
      // so the same toggle drives the overlay drawer instead.
      if (window.innerWidth < 1024) {
        if (railOverlayOpen) closeRailOverlay(); else openRailOverlay();
        return;
      }
      railMode = (railMode === 'open') ? 'collapsed' : 'open';
      localStorage.setItem('tracker.rail', railMode);
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
      var collapsed = (railMode === 'collapsed') || (window.innerWidth < 1280 && window.innerWidth >= 1024);
      els.rail.classList.toggle('cr-rail--collapsed', collapsed);
      var label = collapsed ? 'Expand session rail' : 'Collapse session rail';
      els.railChevron.setAttribute('title', label);
      els.railChevron.setAttribute('aria-label', label);
      if (els.railToggleTop) {
        els.railToggleTop.setAttribute('title', label);
        els.railToggleTop.setAttribute('aria-label', label);
      }
      renderRail(lastState);
    }

    function bindResize() {
      window.addEventListener('resize', function () {
        var underlay = window.innerWidth < 1024;
        if (!underlay) closeRailOverlay();   // resizing back above 1024px cleans up the overlay + scrim
        applyRailMode();
      });
    }

    function railRowsFor(sessions) {
      var q = searchQuery;
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

    function renderRail(state) {
      if (!els.railList) return;
      var sessions = state.sessions || [], now = state.now;
      els.railCount.textContent = String(sessions.length);

      var scrollTop = els.railList.scrollTop;
      var activeEl = document.activeElement;
      var activeWasSearch = (activeEl === els.railSearchInput);

      var collapsed = els.rail.classList.contains('cr-rail--collapsed');
      els.railList.innerHTML = '';

      var filtered = railRowsFor(sessions.filter(function (s) { return !s.agent; }));
      var order = railOrder(filtered);
      var agentBuckets = {};
      sessions.filter(function (s) { return s.agent && s.group; }).forEach(function (s) {
        var b = agentBuckets[s.group] || (agentBuckets[s.group] = { label: s.groupLabel || s.group, n: 0, live: 0, mtime: 0, sessions: [] });
        b.n++;
        if ((now - (s.mtime || 0)) < LIVE_WINDOW) b.live++;
        b.mtime = Math.max(b.mtime, s.mtime || 0);
        b.sessions.push(s);
      });

      if (collapsed) {
        renderCollapsedOrbs(order, now);
      } else {
        if (order.pinned.length) {
          els.railList.appendChild(h('div', { class: 'cr-rail-group-header' },
            ['📌 Pinned — ' + order.pinned.length + ' · newest first']));
          order.pinned.forEach(function (s) { els.railList.appendChild(railRow(s, now)); });
        }
        els.railList.appendChild(h('div', { class: 'cr-rail-group-header' },
          ['Sessions — ' + order.unpinned.length + ' · newest first']));
        order.unpinned.forEach(function (s) { els.railList.appendChild(railRow(s, now)); });

        Object.keys(agentBuckets).forEach(function (g) {
          var b = agentBuckets[g];
          var isOpen = expandedRailGroup === g;
          els.railList.appendChild(h('div', {
            class: 'cr-rail-agentrow' + (isOpen ? ' cr-rail-agentrow--open' : ''),
            tabindex: '0', role: 'button', 'aria-expanded': isOpen ? 'true' : 'false',
            title: '🤖 Agents · ' + b.label, 'aria-label': '🤖 Agents · ' + b.label,
            onclick: function () { ctx && ctx.emit && ctx.emit('rail:expandAgents', { group: g }); },
            onkeydown: function (e) { if (e.key === 'Enter') ctx && ctx.emit && ctx.emit('rail:expandAgents', { group: g }); }
          }, [emoji('🤖', '', null), '🤖 Agents · ' + esc(b.label) + (b.live ? ' (' + b.live + ' live)' : ''),
              h('span', { class: 'cr-rail-agentchevron' }, [icon('chevron', '<path d="M9 6l6 6-6 6"/>')])]));
          if (isOpen) {
            b.sessions.slice().sort(function (a, c) { return (c.mtime || 0) - (a.mtime || 0); })
              .forEach(function (s) { els.railList.appendChild(railRow(s, now)); });
          }
        });
      }

      var shown = collapsed ? order.pinned.length + order.unpinned.length : filtered.length;
      var more = sessions.length - shown;
      els.railFooter.textContent = 'scroll · ' + Math.max(0, more) + ' more';

      els.railList.scrollTop = scrollTop;
      if (activeWasSearch) els.railSearchInput.focus();
    }

    function renderCollapsedOrbs(order, now) {
      order.pinned.forEach(function (s) { els.railList.appendChild(railOrb(s, now)); });
      if (order.pinned.length && order.unpinned.length) {
        els.railList.appendChild(h('div', { class: 'cr-orb-divider' }));
      }
      order.unpinned.forEach(function (s) { els.railList.appendChild(railOrb(s, now)); });
    }

    function pipClassFor(s, now) {
      var st = sessionState(s, now);
      if (st === 'awaiting') return 'is-waiting';
      if (st === 'flagged') return 'is-flagged';
      if (st === 'working') return 'is-live';
      return '';
    }

    function railOrb(s, now) {
      var label = (s.title || s.project || s.id) + (s.pinned ? ' (pinned)' : '');
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
      var live = (now - (s.mtime || 0)) < LIVE_WINDOW;
      var dotClass = s.waiting ? 'is-waiting' : (live ? 'is-live' : '');
      var titleAttr = (s.prompt || s.title || '(no prompt)') + '\n' + (s.cwd || '');
      return h('div', {
        class: 'cr-rail-row' + (s.id === selectedSessionId ? ' cr-rail-row--selected' : ''),
        tabindex: '0', role: 'button', title: titleAttr, 'data-id': s.id,
        onclick: function () { openSession(s.id); },
        onkeydown: function (e) { if (e.key === 'Enter') openSession(s.id); }
      }, [
        h('span', { class: 'cr-rail-dot ' + dotClass }),
        h('span', { class: 'cr-rail-title' }, [(s.agent ? '🤖 ' : '') + (s.title || s.project || s.id.slice(0, 8))]),
        h('span', { class: 'cr-rail-meta' }, [railRowMeta(s, now)]),
      ]);
    }

    function openSession(id) {
      closeRailOverlay();   // selecting a session closes the mobile overlay drawer, if open
      selectedSessionId = id;
      if (ctx && typeof ctx.go === 'function') ctx.go('detail', id);
    }

    // -- top bar --------------------------------------------------------

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
      els.topbar.appendChild(h('button', {
        class: 'cr-back', type: 'button',
        onclick: function () { ctx && ctx.emit && ctx.emit('ui:backToClassic'); }
      }, ['‹ Classic dashboard']));

      els.topbar.appendChild(h('span', { class: 'cr-divider' }));

      var pills = h('div', { class: 'cr-dest-pills' }, [
        h('button', { class: 'cr-pill cr-pill--active', type: 'button', 'aria-current': 'page' }, ['Board']),
        (els.terminalsPill = h('button', {
          class: 'cr-pill', type: 'button',
          onclick: function () { ctx && ctx.emit && ctx.emit('nav:terminals'); }
        }, ['Terminals', h('span', { class: 'cr-pill-count' }, [''])])),
      ]);
      els.topbar.appendChild(pills);

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

      els.topbar.appendChild(h('button', {
        class: 'cr-icon-btn', type: 'button', title: 'Config', 'aria-label': 'Config',
        onclick: function () { ctx && ctx.emit && ctx.emit('open:config'); }
      }, [emoji('⚙️', ''), 'Config']));

      els.topbar.appendChild(h('button', {
        class: 'cr-icon-btn', type: 'button', title: 'Help', 'aria-label': 'Help',
        onclick: function () { ctx && ctx.emit && ctx.emit('open:help'); }
      }, [emoji('❓', ''), 'Help']));

      buildThemeControl();

      els.topbar.appendChild(h('button', {
        class: 'cr-newsession', type: 'button',
        onclick: function () { ctx && ctx.emit && ctx.emit('session:new'); }
      }, [icon('spark', '<path d="M12 2l2 7h7l-5.5 4.5L17 21l-5-4-5 4 1.5-7.5L3 9h7z"/>'), 'New session']));
    }

    function buildThemeControl() {
      var systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      function pref() { return (ctx && ctx.theme && ctx.theme.get) ? ctx.theme.get() : 'auto'; }
      function resolved() {
        var p = pref();
        return (p === 'dark' || (p === 'auto' && systemDark)) ? 'dark' : 'light';
      }
      var wrap = h('div', { class: 'cr-theme' });
      var autoLabel = h('span', { class: 'cr-theme-auto' }, ['auto']);
      var lightBtn = h('button', { type: 'button' }, ['Light']);
      var darkBtn = h('button', { type: 'button' }, ['Dark']);
      var seg = h('div', { class: 'cr-theme-seg' }, [lightBtn, darkBtn]);
      wrap.appendChild(autoLabel);
      wrap.appendChild(seg);

      function paint() {
        var r = resolved(), p = pref();
        lightBtn.classList.toggle('is-on', r === 'light');
        darkBtn.classList.toggle('is-on', r === 'dark');
        autoLabel.setAttribute('data-dim', p === 'auto' ? '0' : '1');
      }
      function choose(side) {
        var current = resolved();
        var explicit = pref() !== 'auto';
        if (explicit && current === side) {
          if (ctx && ctx.theme && ctx.theme.set) ctx.theme.set('system');
        } else if (ctx && ctx.theme && ctx.theme.set) {
          ctx.theme.set(side);
        }
        paint();
      }
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
      hist.bins.forEach(function (v, i) {
        var isLast3 = i >= n - 3;
        // NOTE: doc 02 wants THREE tiers — oldest (`--line-subtle`/`--state-idle`),
        // middle neutral, newest three (wheat + glow on the last bar) — but only
        // pins exact colours for the oldest tier (the default below) and the
        // newest three; it gives no cut point for where "middle" starts. Splitting
        // the remaining bars evenly in half is the sensible reading, not literal
        // doc text.
        var isMiddle = !isLast3 && i >= Math.floor((n - 3) / 2);
        var cls = 'cr-hist-bar';
        var h1 = 4 + (hist.peak ? Math.round((v / hist.peak) * 26) : 0);
        var bar = h('span', { class: cls, style: 'height:' + h1 + 'px' });
        if (isLast3) bar.style.background = 'var(--state-thinking)';
        else if (isMiddle) bar.style.background = 'var(--line-default)';
        if (i === n - 1) bar.classList.add('is-glow');
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

    function stateWord(state) {
      return { awaiting: 'Waiting on you', working: 'Working', flagged: 'Flagged', landed: 'Landed' }[state] || state;
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

    function tileHead(s, state, now) {
      var ew = stateEmoji(state);
      var kids = [
        emoji(ew[0], ew[1]),
        h('span', { class: 'cr-tile-state' }, [stateWord(state) + (state === 'awaiting' ? ' · ' + ago(now - (s.mtime || 0)) : '')]),
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
      head.appendChild(h('span', { class: 'cr-tile-meta' }, [trailing]));
      return head;
    }

    function tileLine(s, state) {
      if (state === 'flagged') {
        return h('div', { class: 'cr-tile-line' }, [(s.open_flags || 0) + ' flag' + (s.open_flags === 1 ? '' : 's') + ' open']);
      }
      // NOTE: doc 02's Landed row also wants a "PR number if any" (`.cr-tile-pr`
      // is styled in ext_cr_board.css but deliberately never instantiated here) —
      // verified against registry.all_sessions() and every provider's list()
      // (providers/claude.py's list_sessions(), providers/auggie.py's
      // list_auggie(), providers/augment_ext.py): none of them put a PR field on
      // the session-LIST dict. PR discovery (collect_prs/pr_create_ids/
      // note_pr_states) only runs inside claude.py's per-session PARSE/detail
      // path, and this module fetches nothing beyond {sessions, now}. Left
      // unrendered rather than inventing a field or adding a fetch; the CSS rule
      // stands as documentation of the still-open gap.
      //
      // No live-narration line or run summary exists in the list dict either
      // (only `prompt`, the session's opening ask) — used as the best available
      // stand-in for "the summary" the doc calls for.
      return h('div', { class: 'cr-tile-line' }, [s.prompt || '']);
    }

    function sessionTile(t, now) {
      var s = t.session, state = t.state;
      var cls = 'cr-tile cr-tile--' + state;
      if (t.hero) cls += ' cr-tile--hero cr-tile--span2';
      var attrs = tileBaseAttrs(t);
      attrs.class = cls;
      attrs.title = (s.prompt || s.title || '(no prompt)') + '\n' + (s.cwd || '');

      var body = [
        tileHead(s, state, now),
        h('div', { class: 'cr-tile-title' }, [s.title || s.project || s.id.slice(0, 8)]),
        h('div', { class: 'cr-tile-sub' }, [(s.project || '') + ' · ' + toolLabel(s.source)]),
        tileLine(s, state),
      ];
      var ticks = todoTicks(s);
      if (ticks) body.push(ticks);

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

    function agentGroupTile(t, now) {
      var attrs = tileBaseAttrs(t);
      attrs.class = 'cr-tile cr-tile--agentgroup';
      attrs.title = '🤖 Agents · ' + t.label;
      return h('div', attrs, [
        h('div', { class: 'cr-tile-head' }, [emoji('🤖', ''), h('span', { class: 'cr-tile-state' }, ['Agent group'])]),
        h('div', { class: 'cr-tile-title' }, ['🤖 Agents · ' + t.label]),
        h('div', { class: 'cr-tile-agentexpand' }, [icon('chevron', '<path d="M9 6l6 6-6 6"/>'), t.sessions.length + ' running', ' · expand']),
      ]);
    }

    function renderCapFooter(sessions, allTiles) {
      els.capfooter.innerHTML = '';
      els.capfooter.appendChild(h('span', { class: 'cr-capfooter-count' }, [allTiles.length + ' of ' + sessions.length]));
      els.capfooter.appendChild(document.createTextNode(
        ' — The board never shows more than 8 tiles. Everything else lives in the rail — pinned on top, newest first in each group. — '));
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
      if (root.hidden) return false; // board view itself isn't the one showing (e.g. detail is up)
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
        // Clicking (or Enter-activating) an agent-group row/tile toggles that group's
        // sessions open inline in the rail — own expand state, this module only.
        ctx.on('rail:expandAgents', function (payload) {
          var g = payload && payload.group;
          if (!g) return;
          expandedRailGroup = (expandedRailGroup === g) ? null : g;
          renderRail(lastState);
        });
      }
    }

    function update(state) {
      lastState = state || { sessions: [], now: Math.floor(Date.now() / 1000) };
      var sessions = lastState.sessions || [];
      renderRail(lastState);
      renderTriage(lastState);
      renderBoard(lastState);

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
      // exposed for tests / a bootstrap that wants the pure derivations directly
      boardTiles: boardTiles,
      sessionState: sessionState,
      railOrder: railOrder,
      agentGroups: agentGroups,
      triageCounts: triageCounts,
      activityHistogram: activityHistogram,
    };
  }

  window.CR.board = createBoard();
})();
