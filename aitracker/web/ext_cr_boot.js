// ext_cr_boot.js — Control Room bootstrap: opt-in entry, UI-mode switch, theme
// resolution, the ctx surface every CR.* module receives, and data plumbing.
//
// Concatenated into the SAME top-level <script> as app.js and every other
// web/ext_*.js (see aitracker/page.py's build_page(): app.js first, then every
// ext_*.css/js sorted by filename, glued into one <style>/<script>). That means:
//   - `cur`, `sessions`, `listNow`, `termCount`, `flags`, `soundOn`, `$`, `esc`,
//     `ago`, `md`, `pick`, `track`, `poll`, `loadSide`, `toggleSound`,
//     `resolveFlag`/`delFlag`/`flagAction`, `EXT`, `SIDE_EXT` are app.js's REAL
//     globals, reachable here via the shared script scope — not a guess at
//     their shape (same note ext_launch.js/ext_run.js/ext_vt.js already carry).
//   - Everything below lives in an IIFE so a bare `const`/`let` here can't
//     collide with app.js's or another ext_*.js's top-level bindings.
//   - page.py globs files alphabetically: ext_cr_board.js sorts BEFORE this
//     file, but ext_cr_boot.js sorts BEFORE ext_cr_detail.js / ext_cr_dialogs.js
//     / ext_cr_term.js. So this file cannot assume any window.CR.* module is
//     attached yet at its own top-level execution time, in EITHER direction.
//     Fix: every module-touching action (mounting, wiring) is deferred with
//     `setTimeout(fn, 0)`, which always runs after the entire concatenated
//     <script> — every sibling file included — has finished executing.
//
// Recon note: the sibling view/dialog/terminal modules already exist on disk
// (as cr_board.js / cr_dialogs.js / cr_term.js / cr.css, pending the
// orchestrator's rename to ext_cr_*) and were read before writing this file,
// so the ctx surface below is wired to the REAL events/methods those files
// already call — not just the abstract contract in this task's brief. See the
// end-of-task report for the concrete list of mismatches found between them.

window.CR = window.CR || {};

(function () {
  'use strict';

  // ----------------------------------------------------------------------
  // Tiny event bus — ctx.on / ctx.emit
  // ----------------------------------------------------------------------
  var bus = {};
  function on(name, fn) {
    if (typeof fn !== 'function') return;
    (bus[name] = bus[name] || []).push(fn);
  }
  function emit(name, payload) {
    var fns = bus[name];
    if (!fns) return;
    fns.slice().forEach(function (fn) {
      try { fn(payload); } catch (e) { console.error('[CR] listener for', name, 'threw', e); }
    });
  }

  // ----------------------------------------------------------------------
  // Glyphs — 01-foundations.md "Glyphs needed (not emoji)": spark, search,
  // chevron, check, alert, bell, branch, panel, redo, edit, clock, stop, send.
  // 24x24, stroke=currentColor, fill=none, no icon font/package. Path data
  // matches cr_dialogs.js's own GLYPH_PATHS fallback set exactly (verified by
  // reading that file) so the primary glyph and its degrade-path fallback are
  // pixel-identical, not two competing drawings of the same icon.
  // ----------------------------------------------------------------------
  var GLYPHS = {
    spark: 'M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z',
    search: 'M10.5 3a7.5 7.5 0 1 0 4.66 13.4l4.72 4.72 1.42-1.42-4.72-4.72A7.5 7.5 0 0 0 10.5 3zm0 2a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11z',
    chevron: 'M8 5l7 7-7 7',
    check: 'M4 12.5l5 5L20 7',
    alert: 'M12 3l10 18H2L12 3zm0 6v5m0 3.2h.01',
    bell: 'M12 3a5 5 0 0 0-5 5v3.4L5 15v1.5h14V15l-2-3.6V8a5 5 0 0 0-5-5zM9.5 19a2.5 2.5 0 0 0 5 0',
    branch: 'M6 3v9a4 4 0 0 0 4 4h4M6 3a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm12 4a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm-6 13a2 2 0 1 1 0-4 2 2 0 0 1 0 4z',
    panel: 'M4 5h16v14H4zM9 5v14',
    redo: 'M8 8h9v-4l5 5-5 5v-4H8a4 4 0 1 0 0 8h5v2H8a6 6 0 1 1 0-12z',
    edit: 'M4 20l1-5L16 4l4 4L9 19l-5 1z',
    clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 4v5l4 2',
    stop: 'M6 6h12v12H6z',
    send: 'M3 11l18-8-8 18-2-8-8-2z'
  };
  function icon(name) {
    var d = GLYPHS[name];
    if (!d) return '';
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
      '<path d="' + d + '"/></svg>';
  }

  // ----------------------------------------------------------------------
  // Theme resolution (01-foundations.md "Theme resolution (decision 3)")
  // localStorage key/values match the doc EXACTLY: 'tracker.theme' =
  // 'auto' | 'light' | 'dark' (default 'auto'). NOTE: the task brief that
  // commissioned this file described the key as tracker.theme with values
  // light|dark|"system"; 01-foundations.md's own fenced code block (and the
  // sibling cr.css already on disk, which documents the same reasoning)
  // names the third value 'auto', not 'system' — reproducing the doc + the
  // real token file over the paraphrase, per this project's own
  // "where they disagree, the doc wins" rule.
  // ----------------------------------------------------------------------
  function getThemePref() {
    try { return localStorage.getItem('tracker.theme') || 'auto'; } catch (e) { return 'auto'; }
  }
  function setThemePref(v) {
    if (v !== 'light' && v !== 'dark' && v !== 'auto') v = 'auto';
    try { localStorage.setItem('tracker.theme', v); } catch (e) {}
    applyTheme();
  }
  function systemPrefersDark() {
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }
  function resolveTheme() {
    var pref = getThemePref();
    return (pref === 'dark' || (pref === 'auto' && systemPrefersDark())) ? 'dark' : 'light';
  }
  function applyTheme() {
    var root = document.getElementById('nextRoot');
    var resolved = resolveTheme();
    if (root) root.classList.toggle('is-dark', resolved === 'dark');
    // Re-dispatch the SAME CustomEvent app.js's own setTheme() fires (app.js:3), so
    // ext_vt.js's live xterm re-theme listener picks it up too — WITHOUT touching
    // classic's own <html>.light class or its `localStorage.theme` key (that would
    // change the classic dashboard's independent theme choice, which this module
    // must leave completely alone per its brief).
    document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: resolved } }));
    // Internal ctx bus uses ONE name, 'theme:changed' (cr_board.js's original
    // name — cr_term.js's listener was updated to match, see ext_cr_term.js's
    // _wireThemeReactivity). The document-level 'themechange' CustomEvent above
    // is a SEPARATE, classic-facing signal that ext_vt.js depends on and is
    // left untouched.
    emit('theme:changed', { theme: resolved });
  }
  if (window.matchMedia) {
    var mql = window.matchMedia('(prefers-color-scheme: dark)');
    var onSystemChange = function () { if (getThemePref() === 'auto') applyTheme(); };
    if (mql.addEventListener) mql.addEventListener('change', onSystemChange);
    else if (mql.addListener) mql.addListener(onSystemChange); // Safari <14 fallback
  }

  // ----------------------------------------------------------------------
  // UI-mode switch (02-shell-and-board.md "Mode switching")
  // localStorage key: 'tracker.ui' = 'classic' | 'next' (default 'classic').
  // No reload: both roots stay in the DOM, `hidden` toggles which is shown —
  // a reload would drop the terminal's open PTY streams.
  // ----------------------------------------------------------------------
  var CLASSIC_SIBLINGS = ['.app', 'footer.foot', '#toasts', '#diffmodal', '#msgmodal'];
  function getUiMode() {
    try { return localStorage.getItem('tracker.ui') || 'classic'; } catch (e) { return 'classic'; }
  }
  function setUiMode(mode) {
    mode = (mode === 'next') ? 'next' : 'classic';
    try { localStorage.setItem('tracker.ui', mode); } catch (e) {}
    var nextRoot = document.getElementById('nextRoot');
    var isNext = mode === 'next';
    if (nextRoot) nextRoot.hidden = !isNext;
    CLASSIC_SIBLINGS.forEach(function (sel) {
      var el = document.querySelector(sel);
      if (el) el.hidden = isNext;
    });
    if (isNext) {
      ensureMounted();
      applyTheme();
      // "immediately triggers a data refresh rather than waiting for the next
      // poll tick" — reuse app.js's OWN fetch functions (same pollBusy/sideBusy
      // guards) instead of a second fetch loop; see the data-plumbing note below.
      if (typeof loadSide === 'function') loadSide();
      if (typeof cur !== 'undefined' && cur && typeof poll === 'function') poll();
      showView(state.view);
    }
    emit('ui:modeChanged', { mode: mode });
  }

  // ----------------------------------------------------------------------
  // View containers + navigation — ctx.go('board' | 'detail', sessionId)
  // ----------------------------------------------------------------------
  var state = { view: 'board', sid: '' };
  var els = {};

  function buildRoots() {
    var root = document.getElementById('nextRoot');
    if (!root || els.viewBoard) return;
    els.viewBoard = document.createElement('div');
    els.viewBoard.id = 'cr-view-board';
    els.viewBoard.className = 'cr-view';
    els.viewDetail = document.createElement('div');
    els.viewDetail.id = 'cr-view-detail';
    els.viewDetail.className = 'cr-view';
    els.viewDetail.hidden = true;
    els.dialogsRoot = document.createElement('div');
    els.dialogsRoot.id = 'cr-dialogs-root';
    els.termRoot = document.createElement('div');
    els.termRoot.id = 'cr-term-root';
    root.appendChild(els.viewBoard);
    root.appendChild(els.viewDetail);
    root.appendChild(els.dialogsRoot);
    root.appendChild(els.termRoot);
  }

  function showView(view) {
    view = (view === 'detail') ? 'detail' : 'board';
    state.view = view;
    if (els.viewBoard) els.viewBoard.hidden = (view !== 'board');
    if (els.viewDetail) els.viewDetail.hidden = (view !== 'detail');
  }

  function go(view, sessionId) {
    if (sessionId) {
      state.sid = sessionId;
      // Reuses app.js's own pick(): sets #sid, restarts the shared 2s poll
      // (`track()`), persists localStorage.sid — the SAME session tracking
      // classic uses, so switching UI mode never loses "what am I looking at".
      if (typeof pick === 'function') pick(sessionId);
      emit('session:selected', { id: sessionId });
    }
    showView(view);
    if (view === 'board') {
      if (typeof loadSide === 'function') loadSide();
    } else if (state.sid && typeof poll === 'function') {
      poll();
    }
    emit('view:changed', { view: view, id: state.sid });
  }

  // ----------------------------------------------------------------------
  // ctx.terminals.count() — REQUIRED by cr_board.js's Terminals pill (its own
  // comment: "ctx has no terminal-count accessor ... left blank rather than
  // fabricated"). `open` rides the EXISTING X-Server-Now-style header
  // (X-Term-Count, already parsed into app.js's `termCount` global on every
  // 5s /api/list poll — zero extra cost). `total` is config.MAX_TERMS, which
  // has no header exposure; the only place it's served is GET /api/term/list's
  // body (an EXISTING endpoint ext_vt.js/ext_launch.js/cr_term.js already
  // call the same way). NOTE: this is the one deliberate exception to "no new
  // round-trips" in this file — a SINGLE one-time fetch of an existing route
  // to learn a static config value, cached forever after, never a poll.
  // ----------------------------------------------------------------------
  var termsMax = null;
  function fetchTermsMax() {
    if (termsMax !== null || typeof fetch !== 'function') return;
    fetch('/api/term/list').then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j && typeof j.max === 'number') termsMax = j.max; })
      .catch(function () {});
  }

  // ----------------------------------------------------------------------
  // ctx.dialog(name, payload) — cr_term.js calls this as a plain ctx method
  // (`ctx.dialog("config", {})`); cr_dialogs.js listens for it as a BUS event
  // (`ctx.on('dialog:open', ...)`). Bridge both: the method just emits.
  // ----------------------------------------------------------------------
  function dialog(name, payload) {
    emit('dialog:open', { name: name, data: payload });
  }

  // ----------------------------------------------------------------------
  // ctx.fmt — thin formatting reuse, never a re-derived threshold (LIVE stays
  // server-owned; this only reuses app.js's existing "N ago" string builder).
  // ----------------------------------------------------------------------
  var fmt = {
    relTime: function (sec) {
      return (typeof ago === 'function') ? ago(sec) : Math.max(0, Math.round(sec)) + 's ago';
    }
  };
  // ctx.markdown — dialogs.js's own comment names this as a REQUIRED ADDITION
  // ("ctx.markdown(text) -> HTMLElement ... every consumer should call the
  // SAME implementation rather than fork a second one"); it is not actually
  // called anywhere yet, but wiring it now means the detail module (doc 03,
  // not yet on disk) gets it for free instead of a second markdown-lite fork.
  // Reuses app.js's OWN `md()` (the narration/prompt renderer), not a new one.
  function markdown(text) {
    var d = document.createElement('div');
    d.innerHTML = (typeof md === 'function') ? md(text || '') : esc(text || '');
    return d;
  }

  // ----------------------------------------------------------------------
  // The ctx object every CR.* module's mount(rootEl, ctx) receives.
  // ----------------------------------------------------------------------
  var ctx = {
    on: on,
    emit: emit,
    go: go,
    theme: { get: getThemePref, set: setThemePref },
    icon: icon,
    dialog: dialog,
    markdown: markdown,
    fmt: fmt,
    terminals: {
      count: function () {
        return {
          open: (typeof termCount === 'number') ? termCount : 0,
          total: (termsMax !== null) ? termsMax : (typeof sessions !== 'undefined' ? sessions.length : 0)
        };
      }
    }
  };

  // ----------------------------------------------------------------------
  // Cross-module bridge events. These are the ACTUAL events cr_board.js /
  // cr_term.js emit (verified by reading both files, not guessed from the
  // abstract brief) that nothing else in the codebase currently handles.
  // ----------------------------------------------------------------------
  on('ui:backToClassic', function () { setUiMode('classic'); });

  on('open:help', function () { dialog('help', {}); });
  on('open:config', function () { dialog('config', {}); });

  on('open:flags', function () {
    dialog('flags', buildFlagsPayload());
  });

  on('toggle:notifications', function () {
    // Reuses the SAME `soundOff` localStorage key + toggleSound()/checkCompletions()
    // machinery classic's bell already drives — one notification setting for the
    // whole app, not a second parallel on/off no code actually reads.
    if (typeof toggleSound === 'function') {
      toggleSound();
      emit('notify', { text: 'Notification sound: ' + (typeof soundOn !== 'undefined' && soundOn ? 'on' : 'off') });
    }
  });

  on('terminal:open', function (payload) {
    var id = payload && payload.id;
    if (id && window.CR.term && typeof window.CR.term.open === 'function') {
      window.CR.term.open(id, { mode: 'cwd' });
    } else {
      emit('notify', { text: 'Terminal isn’t available right now.' });
    }
  });

  on('nav:terminals', function () {
    // cr_term.js exports openManage() on CR.term for exactly this bridge (see
    // ext_cr_term.js's public module surface) — guarded in case term failed to
    // mount, so this degrades honestly instead of throwing.
    var term = window.CR.term;
    if (term && typeof term.openManage === 'function') { term.openManage(); }
    else { emit('notify', { text: 'Managing terminals from here isn’t wired up yet.' }); }
  });

  on('session:new', function () {
    // cr_term.js exports openPicker(mode) on CR.term for exactly this bridge
    // (see ext_cr_term.js's public module surface).
    var term = window.CR.term;
    if (term && typeof term.openPicker === 'function') { term.openPicker('new'); }
    else { emit('notify', { text: 'Starting a new session from here isn’t wired up yet — use the classic dashboard’s "+ New Claude session" for now.' }); }
  });

  // ----------------------------------------------------------------------
  // Drill-down pop-outs — cr_detail.js opens 'file-diff'/'command-output'/
  // 'agent-transcript'/'shell-tail' with only an id (no content); cr_dialogs.js
  // renders a loading state and emits 'cr:drill-request' ({kind, sessionId,
  // arg}) asking someone to fetch the real content and re-open the SAME dialog
  // name (its open() upgrades a same-name dialog in place via the builder's
  // own `update`). This is the "someone" — using the EXISTING drill routes,
  // no new endpoints. Response shapes reverse-engineered from app.js's own
  // classic modals (openDiff/openCmd/openShell/openAgent), which already
  // consume these same routes successfully.
  // ----------------------------------------------------------------------
  var DRILL_DIALOG_NAME = { diff: 'file-diff', output: 'command-output', agent: 'agent-transcript', shell: 'shell-tail' };
  var DRILL_URL = {
    diff: function (sid, arg) { return '/api/diff?id=' + encodeURIComponent(sid) + '&file=' + encodeURIComponent(arg || ''); },
    output: function (sid, arg) { return '/api/output?id=' + encodeURIComponent(sid) + '&cmd=' + encodeURIComponent(arg || ''); },
    agent: function (sid, arg) { return '/api/agent?id=' + encodeURIComponent(sid) + '&agent=' + encodeURIComponent(arg || ''); },
    shell: function (sid, arg) { return '/api/shell?id=' + encodeURIComponent(sid) + '&shell=' + encodeURIComponent(arg || ''); },
  };
  // Turns one edit-op's unified-diff text (op.diff, e.g. "+foo\n-bar\n baz") into
  // the {type:'add'|'del'|null, no, text}[] shape cr_dialogs.js's diffLineRow()
  // renders. Hunk/file headers (@@, +++, ---) are dropped, matching app.js's own
  // _afterLines() filter for the same raw text.
  function parseDiffOpLines(diffText) {
    var out = [];
    (diffText || '').split('\n').forEach(function (l) {
      if (/^(@@|\+\+\+|---)/.test(l)) return;
      var type = null, text = l;
      if (l.charAt(0) === '+') { type = 'add'; text = l.slice(1); }
      else if (l.charAt(0) === '-') { type = 'del'; text = l.slice(1); }
      else if (l.charAt(0) === ' ') { text = l.slice(1); }
      out.push({ type: type, no: out.length + 1, text: text });
    });
    return out;
  }
  on('cr:drill-request', function (payload) {
    var kind = payload && payload.kind;
    var name = DRILL_DIALOG_NAME[kind];
    var urlFn = DRILL_URL[kind];
    if (!name || !urlFn || typeof fetch !== 'function') return;
    var sid = payload.sessionId, arg = payload.arg;
    fetch(urlFn(sid, arg)).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    }).then(function (d) {
      if (!d || d.error) { dialog(name, { error: (d && d.error) || 'not found' }); return; }
      if (kind === 'diff') {
        var ops = d.ops || [];
        var lastOp = ops.length ? ops[ops.length - 1] : null;
        var lines = lastOp ? parseDiffOpLines(lastOp.diff) : [];
        var adds = 0, dels = 0;
        lines.forEach(function (l) { if (l.type === 'add') adds++; else if (l.type === 'del') dels++; });
        dialog(name, {
          path: d.file || arg, lines: lines, additions: adds, deletions: dels,
          expandAboveLabel: false, belowCount: 0,
        });
      } else if (kind === 'output' || kind === 'shell') {
        dialog(name, { text: d.out || '(no output captured)' });
      } else { // agent
        dialog(name, { text: d.narration || '(no narration recorded)' });
      }
    }).catch(function () {
      dialog(name, { error: 'couldn’t reach the server' });
    });
  });

  // ----------------------------------------------------------------------
  // Rename — the ONLY write cr_dialogs.js's rename dialog performs is emitting
  // 'cr:rename' on the bus (per its own "NOTE" comment); this bridges it to the
  // EXISTING POST /api/title route, the same one classic's renameSession()
  // already uses, then refreshes via the shared poll loops (no second fetch
  // loop introduced).
  // ----------------------------------------------------------------------
  on('cr:rename', function (payload) {
    var sid = payload && payload.sessionId;
    if (!sid || typeof fetch !== 'function') return;
    fetch('/api/title', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: sid, title: payload.title || '' }),
    }).then(function (r) { return r.ok; }).then(function (ok) {
      emit('notify', { text: ok ? 'Renamed.' : 'Couldn’t rename that session.' });
      if (typeof loadSide === 'function') loadSide();
      if (ok && typeof cur !== 'undefined' && sid === cur && typeof poll === 'function') poll();
    }).catch(function () {
      emit('notify', { text: 'Couldn’t reach the server — the rename wasn’t saved.' });
    });
  });

  // ----------------------------------------------------------------------
  // Detail-view actions — cr_detail.js only ever emits an intent + a payload,
  // never touches fetch()/DOM itself (its own contract rule); this is where
  // each of those intents meets an EXISTING route or classic helper, per the
  // same "server owns the write, this file bridges it" pattern as cr:rename
  // and cr:drill-request above. No second poll loop: every branch refreshes
  // through loadSide()/poll(), the same two loops app.js already runs.
  // ----------------------------------------------------------------------

  // Flag an issue — same POST /api/flags body shape as classic's addFlag(),
  // just sourced from the payload's sessionId instead of the global `cur`
  // (the detail view can flag a session that isn't the currently-tracked
  // one). `project` is looked up from the SAME `sessions` list addFlag()
  // reads from, not re-derived.
  on('cr:flag-create', function (payload) {
    var sid = payload && payload.sessionId;
    var note = ((payload && payload.note) || '').trim();
    if (!sid || !note || typeof fetch !== 'function') return;
    var sess = (typeof sessions !== 'undefined' && Array.isArray(sessions)) ? sessions : [];
    var s = null;
    for (var i = 0; i < sess.length; i++) { if (sess[i].id === sid) { s = sess[i]; break; } }
    fetch('/api/flags', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: sid, project: (s && s.project) || '', note: note, context: payload.context || '' }),
    }).then(function (r) { return r.ok; }).then(function (ok) {
      emit('notify', { text: ok ? 'Flag added.' : 'Couldn’t add that flag.' });
      if (typeof loadFlags === 'function') loadFlags();
    }).catch(function () {
      emit('notify', { text: 'Couldn’t reach the server — the flag wasn’t saved.' });
    });
  });

  // Queue a note — same POST /api/notes body shape as classic's addNote();
  // the payload always carries fresh text (never an index into an existing
  // queued note), so this is the create route, not /api/notes/push.
  on('cr:note-push', function (payload) {
    var sid = payload && payload.sessionId;
    var text = ((payload && payload.text) || '').trim();
    if (!sid || !text || typeof fetch !== 'function') return;
    fetch('/api/notes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: sid, text: text }),
    }).then(function (r) { return r.ok; }).then(function (ok) {
      emit('notify', { text: ok ? 'Note added.' : 'Couldn’t add that note.' });
      if (typeof loadSide === 'function') loadSide();
      if (ok && typeof cur !== 'undefined' && sid === cur && typeof poll === 'function') poll();
    }).catch(function () {
      emit('notify', { text: 'Couldn’t reach the server — the note wasn’t saved.' });
    });
  });

  // Remove a queued note — same POST /api/notes/delete body shape as
  // classic's removeNote().
  on('cr:note-remove', function (payload) {
    var sid = payload && payload.sessionId;
    var idx = payload && payload.index;
    if (!sid || typeof idx !== 'number' || typeof fetch !== 'function') return;
    fetch('/api/notes/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: sid, index: idx }),
    }).then(function (r) { return r.ok; }).then(function (ok) {
      emit('notify', { text: ok ? 'Note removed.' : 'Couldn’t remove that note.' });
      if (typeof loadSide === 'function') loadSide();
      if (ok && typeof cur !== 'undefined' && sid === cur && typeof poll === 'function') poll();
    }).catch(function () {
      emit('notify', { text: 'Couldn’t reach the server — the note wasn’t removed.' });
    });
  });

  // Run a command — the SAME POST /api/term/run + GET /api/term/stream (SSE)
  // pair ext_run.js's own embedded runner already drives from the classic
  // sidebar; this is not a second implementation of that runner, just a second
  // CALLER of the same route. cr_detail.js's "Run a command" panel has no
  // output pane of its own (a REQUIRED ADDITION, not invented here — see the
  // report), so progress/result surfaces through the existing toast/notify
  // path instead of a fabricated inline stream view.
  on('cr:run-command', function (payload) {
    var sid = payload && payload.sessionId;
    var argv = ((payload && payload.argv) || '').trim();
    if (!sid || !argv || typeof fetch !== 'function') return;
    fetch('/api/term/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: sid, cmd: argv }),
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
    }).then(function (res) {
      if (!res.ok || !res.j || !res.j.job) {
        emit('notify', {
          text: (res.j && res.j.error) ||
            (res.status === 404 ? 'Running commands isn’t available on this server.' :
              res.status === 403 ? 'Running commands is disabled.' : 'Couldn’t start that command.')
        });
        return;
      }
      emit('notify', { text: 'Running: ' + argv });
      if (typeof EventSource !== 'function') return;
      var es = new EventSource('/api/term/stream?job=' + encodeURIComponent(res.j.job));
      es.addEventListener('end', function (ev) {
        var d = {};
        try { d = JSON.parse(ev.data); } catch (e) {}
        es.close();
        emit('notify', { text: argv + (d.rc === 0 ? ' — done' : ' — exit ' + d.rc) });
        if (typeof cur !== 'undefined' && sid === cur && typeof poll === 'function') poll();
      });
      es.onerror = function () { es.close(); };
    }).catch(function () {
      emit('notify', { text: 'Couldn’t reach the server to run that command.' });
    });
  });

  // Resume this session in a terminal — the SAME window.CR.term.open(id, opts)
  // entry point 'terminal:open' already bridges to above, just with mode
  // 'resume' instead of 'cwd' (open()'s own opts.mode branch already handles
  // both — see ext_cr_term.js).
  on('session:resume', function (payload) {
    var id = payload && payload.id;
    if (id && window.CR.term && typeof window.CR.term.open === 'function') {
      window.CR.term.open(id, { mode: 'resume' });
    } else {
      emit('notify', { text: 'Terminal isn’t available right now.' });
    }
  });

  // Open externally — the SAME POST /api/term/open route (and the SAME
  // request shape) ext_launch.js's own openTerm()/ext_cr_term.js's own
  // _openExternal() already call for their "↗ External …" buttons — not a
  // new endpoint, just a third caller of an existing one. Resume when the
  // session is Claude's own (mirrors ext_launch.js's isClaudeId check),
  // otherwise a plain cwd shell.
  on('session:openExternal', function (payload) {
    var id = payload && payload.id;
    if (!id || typeof fetch !== 'function') return;
    var resumable = !/^(auggie|augment-vscode|augment-cursor):/.test(id);
    fetch('/api/term/open', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: id, mode: resumable ? 'resume' : 'cwd' }),
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
    }).then(function (res) {
      if (!res.ok || (res.j && res.j.error)) {
        emit('notify', { text: (res.j && res.j.error) || 'Couldn’t open an external terminal.' });
        return;
      }
      emit('notify', { text: (resumable ? 'Resuming' : 'Terminal opened') + ' in an external window — this machine only.' });
    }).catch(function () {
      emit('notify', { text: 'Couldn’t reach the server to open an external terminal.' });
    });
  });

  // Terminal model/effort controls from the detail view — REQUIRED ADDITION,
  // not wired here: cr_term.js's own model/effort switch (_openModelDialog/
  // _openEffortDialog) only knows about whichever pty its OWN overlay
  // currently has open (st.tty/st.sessionId), and nothing in the shared
  // session-detail dict says whether some OTHER, already-attached terminal
  // exists for this session id to target instead. There is no existing route
  // that answers "find the terminal attached to session X" — attached-ness is
  // only checked by tty (GET /api/term/attached?tty=), and a tty id is never
  // part of the session detail dict. Until that seam exists, this stays an
  // honest no-op notice rather than a fabricated lookup. (In practice this is
  // unreachable today: cr_detail.js's renderTerminalPanel keeps the whole
  // panel hidden — `session.term_attached` is never set anywhere in the
  // codebase — so the button this would fire from is never on screen.)
  on('cr:term-controls-request', function () {
    emit('notify', { text: 'Model/effort switching needs an already-open terminal for this session — there’s no way to find one from here yet.' });
  });

  // cr:model-pick / cr:effort-pick — the Defect 3 re-grep turned these up: cr_dialogs.js's own
  // model/effort picker (ctx.dialog("model"|"effort", …)) falls back to emitting these on the bus
  // ONLY when its payload carries no `onPick` (see cr_dialogs.js's renderLadderPicker "pick()").
  // Today nothing calls it that way — cr_term.js's _openModelDialog/_openEffortDialog are the only
  // callers of ctx.dialog("model"|"effort", …), and both always supply a real onPick — so this is
  // unreachable in practice, exactly like cr:term-controls-request just above. Wired to the same
  // honest notice anyway, for the same reason: a currently-dead branch is still a REAL bus event
  // with no listener, and closing that gap costs nothing once the pattern already exists.
  on('cr:model-pick', function () {
    emit('notify', { text: 'Switching the model needs an already-open terminal for this session — there’s no way to find one from here yet.' });
  });
  on('cr:effort-pick', function () {
    emit('notify', { text: 'Switching effort needs an already-open terminal for this session — there’s no way to find one from here yet.' });
  });

  // Stop — REQUIRED ADDITION, not wired: there is no server route that stops
  // "whatever this session is doing" as a general action. The only kill-style
  // routes that exist are POST /api/term/kill (needs a `job` id from a run
  // this file itself just started — see cr:run-command above, not a bare
  // sessionId) and POST /api/term/close (needs a `tty` id). Neither can be
  // reached from just {sessionId}. Left disabled at the source in
  // ext_cr_detail.js (the phone-bar Stop button carries `disabled` + a title
  // explaining why) rather than wired to an endpoint that doesn't answer the
  // actual question asked.
  on('cr:stop', function () {
    emit('notify', { text: 'Stopping a session isn’t supported yet — there’s no server route for it.' });
  });

  // ----------------------------------------------------------------------
  // Cross-session flags payload — adapts app.js's OWN `flags`/`sessions`
  // globals (already kept fresh every 5s by loadSide()'s trailing
  // loadFlags() call) into cr_dialogs.js's renderFlagsList(payload) shape:
  // {flags:[{id, session, sessionTitle, text, resolved}], onOpen, onResolve,
  // onReopen, onDelete}. Deliberately calls the lower-level `flagAction(path,
  // id)` for resolve/delete rather than classic's `delFlag()` — that one
  // wraps a native confirm(), which this task's hard rules forbid adding and
  // which would look completely out of place popping over the new UI.
  // ----------------------------------------------------------------------
  function buildFlagsPayload() {
    var list = (typeof flags !== 'undefined' && Array.isArray(flags)) ? flags : [];
    var sess = (typeof sessions !== 'undefined' && Array.isArray(sessions)) ? sessions : [];
    return {
      flags: list.map(function (f) {
        var s = null;
        for (var i = 0; i < sess.length; i++) { if (sess[i].id === f.session) { s = sess[i]; break; } }
        return {
          id: f.id,
          session: f.session,
          sessionTitle: (s && (s.title || s.project)) || f.project || (f.session || '').slice(0, 8),
          text: f.note,
          resolved: f.resolved
        };
      }),
      onOpen: function (f) { go('detail', f.session); },
      onResolve: function (f) { if (typeof flagAction === 'function') flagAction('/api/flags/resolve', f.id); },
      onReopen: function (f) { if (typeof flagAction === 'function') flagAction('/api/flags/resolve', f.id); },
      onDelete: function (f) { if (typeof flagAction === 'function') flagAction('/api/flags/delete', f.id); }
    };
  }

  // ----------------------------------------------------------------------
  // Mounting — LAZY, on first entry into 'next' mode (not at page load).
  //
  // NOTE: cr_board.js's bindKeyboard() attaches a `document`-level keydown
  // listener the moment CR.board.mount() runs, and that listener is gated
  // only on `root.isConnected` — never on whether #nextRoot is actually
  // visible or which UI mode is active. Mounting eagerly at page load would
  // mean j/k/t/?/Ctrl+K get captured (silently, against an invisible board)
  // even for a user who never opens Control Room at all. Lazy mount confines
  // that exposure to "has opened Control Room at least once this page load" —
  // it does not fully fix it (there's no unmount path back to classic-only
  // capture), which is flagged in the report as cr_board.js's gap, not
  // patched here since that file is out of this task's scope.
  // ----------------------------------------------------------------------
  var mounted = false;
  function placeholder(rootEl, label) {
    if (!rootEl) return;
    var box = document.createElement('div');
    box.className = 'cr-placeholder';
    box.textContent = 'The ' + label + ' view isn’t available in this build yet.';
    rootEl.appendChild(box);
  }
  function safeMount(name, rootEl) {
    var mod = window.CR && window.CR[name];
    if (mod && typeof mod.mount === 'function') {
      try { mod.mount(rootEl, ctx); return; } catch (e) { console.error('[CR] mount', name, 'threw', e); }
    }
    placeholder(rootEl, name);
  }
  function ensureMounted() {
    if (mounted) return;
    mounted = true;
    buildRoots();
    safeMount('dialogs', els.dialogsRoot);
    safeMount('term', els.termRoot);
    safeMount('board', els.viewBoard);
    safeMount('detail', els.viewDetail);
    fetchTermsMax();
  }

  // ----------------------------------------------------------------------
  // Data plumbing — reuse app.js's OWN poll loops instead of a second one.
  //
  // NOTE (deliberate reinterpretation of the brief): app.js already exposes
  // exactly the extension seam this task's "no new round-trips" rule wants —
  // EXT (pushed fn(d), called at the end of every 2s render(d)) and SIDE_EXT
  // (pushed fn(), called at the end of every 5s loadSide()) — the SAME hooks
  // ext_launch.js/ext_run.js/ext_vt.js already use. Pushing into them means
  // CR.board/CR.detail get updated on the classic poll's own results with
  // ZERO extra fetches, rather than a parallel loop that merely matches
  // cadence while doubling requests. This also trivially satisfies "only
  // poll for whichever UI mode is visible": there is only ever one loop.
  // ----------------------------------------------------------------------
  if (typeof SIDE_EXT !== 'undefined' && SIDE_EXT && SIDE_EXT.push) {
    SIDE_EXT.push(function () {
      if (getUiMode() !== 'next' || !mounted) return;
      var now = (typeof listNow === 'number') ? listNow : Date.now() / 1000;
      var list = (typeof sessions !== 'undefined' && Array.isArray(sessions)) ? sessions : [];
      if (window.CR.board && typeof window.CR.board.update === 'function') {
        try { window.CR.board.update({ sessions: list, now: now }); } catch (e) { console.error('[CR] board.update threw', e); }
      }
      if (window.CR.dialogs && typeof window.CR.dialogs.update === 'function') {
        try { window.CR.dialogs.update({ flags: buildFlagsPayload().flags, sessions: list, now: now }); } catch (e) { console.error('[CR] dialogs.update threw', e); }
      }
      if (window.CR.term && typeof window.CR.term.update === 'function') {
        try { window.CR.term.update({ sessions: list }); } catch (e) { console.error('[CR] term.update threw', e); }
      }
    });
  }
  if (typeof EXT !== 'undefined' && EXT && EXT.push) {
    EXT.push(function (d) {
      if (getUiMode() !== 'next' || !mounted) return;
      if (!d || d.error) return;
      if (window.CR.detail && typeof window.CR.detail.update === 'function') {
        try { window.CR.detail.update({ session: d, now: d.now }); } catch (e) { console.error('[CR] detail.update threw', e); }
      }
    });
  }

  // ----------------------------------------------------------------------
  // Keyboard.
  //
  // NOTE: cr_board.js already binds ⌘K/Ctrl+K (focus rail search), j/k (tile
  // focus), t (open terminal for the focused tile), ? (ctx.emit('open:help')),
  // and Escape (clear the active triage filter) globally on `document` inside
  // its own mount() — verified by reading that file, not assumed. Binding the
  // SAME keys again here would double-fire them (e.g. two stacked Help
  // dialogs from one `?` press). So this file deliberately does NOT rebind
  // them; '?' already reaches Help through the 'open:help' bridge above. The
  // one shortcut genuinely uncovered by any module is Esc-closes-a-dialog,
  // which cr_dialogs.js's own mount() also already binds on `document`. There
  // is therefore nothing left for this file to bind without duplicating a
  // sibling's own listener.
  // ----------------------------------------------------------------------

  // ----------------------------------------------------------------------
  // The classic entry button + first-run panel (02-shell-and-board.md
  // "The opt-in entry"). Copy reproduced verbatim from the doc.
  // ----------------------------------------------------------------------
  var frScrim = null;
  function buildFirstRun() {
    if (frScrim) return;
    frScrim = document.createElement('div');
    // `tracker-next` (+ live `is-dark`) directly on this element: it is
    // appended to <body>, not inside #nextRoot (which is still hidden here —
    // classic mode hasn't switched yet), so it needs its own token scope
    // rather than inheriting one from a hidden ancestor.
    frScrim.className = 'cr-scrim tracker-next' + (resolveTheme() === 'dark' ? ' is-dark' : '');
    frScrim.hidden = true;
    frScrim.innerHTML =
      '<div class="cr-firstrun" role="dialog" aria-modal="true" aria-labelledby="crFrHeading">' +
        '<div class="cr-firstrun-preview" aria-hidden="true">' +
          '<div class="cr-firstrun-tiles">' +
            '<div class="cr-firstrun-tile is-wide"></div>' +
            '<div class="cr-firstrun-tile"></div>' +
            '<div class="cr-firstrun-tile"></div>' +
            '<div class="cr-firstrun-tile"></div>' +
          '</div>' +
        '</div>' +
        '<div class="cr-firstrun-copy">' +
          '<h2 id="crFrHeading">A board that answers one question first: who needs you?</h2>' +
          '<p>Same data, same 2-second poll, same read-only promise. Sessions become tiles ranked by their claim on your attention, and the session view keeps a collapsed rail so switching stays one click.</p>' +
          '<ul class="cr-firstrun-checks">' +
            '<li>' + icon('check') + '<span>Every panel you use today is still here — nothing was removed.</span></li>' +
            '<li>' + icon('check') + '<span>Follows your system theme, and you can flip it any time.</span></li>' +
            '<li>' + icon('check') + '<span>One click back to the classic dashboard, any time, no reload.</span></li>' +
          '</ul>' +
          '<div class="cr-firstrun-actions">' +
            '<button type="button" class="cr-firstrun-open" id="crFrOpen">Open the board</button>' +
            '<button type="button" class="cr-firstrun-skip" id="crFrSkip">Not now</button>' +
          '</div>' +
          '<p class="cr-firstrun-foot">Inside the new experience the header carries ← Classic dashboard.</p>' +
        '</div>' +
      '</div>';
    document.body.appendChild(frScrim);
    frScrim.addEventListener('click', function (e) { if (e.target === frScrim) hideFirstRun(); });
    document.getElementById('crFrOpen').addEventListener('click', function () { hideFirstRun(); setUiMode('next'); });
    document.getElementById('crFrSkip').addEventListener('click', function () { hideFirstRun(); });
    on('theme:changed', function (payload) {
      frScrim.classList.toggle('is-dark', payload && payload.theme === 'dark');
    });
  }
  function hideFirstRun() { if (frScrim) frScrim.hidden = true; }
  function markSeen() { try { localStorage.setItem('tracker.next.seen', '1'); } catch (e) {} }
  function seenFirstRun() { try { return localStorage.getItem('tracker.next.seen') === '1'; } catch (e) { return false; } }

  function wireEntryButton() {
    var btn = document.getElementById('tryNext');
    if (!btn) return;
    btn.addEventListener('click', function () {
      if (seenFirstRun()) { setUiMode('next'); return; }
      buildFirstRun();
      markSeen(); // "Show once" (doc) — never reappears after the first click, either button.
      frScrim.hidden = false;
    });
  }

  // ----------------------------------------------------------------------
  // One-shot ?ui=next / ?ui=classic query override (persists thereafter).
  // ----------------------------------------------------------------------
  function applyQueryOverride() {
    try {
      var qp = new URLSearchParams(location.search).get('ui');
      if (qp === 'next' || qp === 'classic') localStorage.setItem('tracker.ui', qp);
    } catch (e) {}
  }

  // ----------------------------------------------------------------------
  // Init — deferred past the end of the whole concatenated <script> (see the
  // file-order note at the top) so every sibling ext_cr_*.js has already run.
  // ----------------------------------------------------------------------
  function init() {
    buildRoots();
    wireEntryButton();
    applyQueryOverride();
    if (getUiMode() === 'next') setUiMode('next'); // mounts, themes, refreshes, shows
  }
  setTimeout(init, 0);
})();
