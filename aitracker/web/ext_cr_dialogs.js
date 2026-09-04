/* cr_dialogs.js — Control Room dialog system: the modal host, Help, Config, the
 * file-diff/output/text pop-out, the narration-diagram pop-out, the cross-session
 * flag list, the terminals-at-cap dialog, toast notifications + the desktop-permission
 * nudge, and the three shared state components (emptyState/errorState/degraded) that
 * sibling modules (board, detail, terminal) reuse instead of forking their own.
 *
 * Doc: design_handoff_control_room/04-coverage-and-help.md (source of truth for every
 * string, colour and layout below). NO FETCHING, with ONE narrow exception: every dialog
 * is fed by the payload its opener passes to CR.dialogs.open(name, payload) and none of
 * them call fetch() — except the Config dialog's Board/Terminal/Server rows, which are now
 * real, writable server settings (POST /api/config) and so read their own live state via
 * GET /api/config the moment they open, entirely inside renderConfig()/its own helpers
 * (fetchServerConfig/postConfigValue below). Every other dialog in this file is still fed
 * purely by its opener's payload.
 *
 * NOTE: foundations doc 01 writes tokens as `--surface-raised` etc. The shared contract
 * for this build renames that layer `--ads-*` (confirmed against the prototype's own
 * `.ads-label` / `--ads-line-default` naming, which this file's author independently
 * grepped for — never read as a design source). Every colour/shadow/font rule below
 * reads `var(--ads-<name>, <doc-01 light value>)` — the fallback keeps this module
 * legible before aitracker/web/cr.css finishes defining the real tokens, it is not a
 * substitute for them.
 */
(function () {
  'use strict';
  window.CR = window.CR || {};

  var _ctx = null;
  var _root = null;      // the `.cr` root element passed to mount()
  var _layer = null;     // dialog-layer host, appended once inside _root
  var _toastHost = null;
  var _stack = [];        // [{name, el, backdrop, opener, trapCleanup, onClose}]
  var _idSeq = 0;

  // ---------------------------------------------------------------------------
  // small utilities
  // ---------------------------------------------------------------------------

  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    attrs = attrs || {};
    for (var k in attrs) {
      if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
      var v = attrs[k];
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'text') el.textContent = v;
      else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'aria-hidden' || k.indexOf('aria-') === 0 || k.indexOf('data-') === 0 || k === 'role' || k === 'for' || k === 'tabindex') el.setAttribute(k, v);
      else el.setAttribute(k, v);
    }
    (children || []).forEach(function (c) {
      if (c == null) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }

  // FIX 4: this used to redeclare its own esc() here — an exact second copy of
  // ext_cr_detail.js's, itself a copy of app.js's global `esc()` (app.js:7) plus quote
  // escaping. Neither call site below (mdLite()'s markdown-lite body, a plain digit count)
  // interpolates into an HTML attribute, so nothing here actually needs the quote
  // handling — this file now falls through to app.js's own top-level `esc()`, reachable
  // by bare name like every other app.js top-level declaration (no local shadow left to
  // block it). ext_cr_detail.js keeps the one quote-escaping esc() Control Room still
  // needs (its attribute-interpolation call sites genuinely require it); REQUIRED
  // ADDITION: app.js's `esc()` should absorb `"`/`'` escaping so even that copy can go.

  // Minimal, deliberately dumb markdown-lite for copy that lives INSIDE this module's
  // own dialogs (Help lede, degraded-state copy). This is NOT capability #31 (full
  // markdown rendering of narration/prompts/todos/files) — that renderer belongs to
  // the detail module (doc 03) and every consumer, this one included, should call the
  // SAME implementation rather than fork a second one. See REQUIRED ADDITION in the
  // handoff report: `ctx.markdown(text) -> HTMLElement` (or a `CR.md` shared global).
  function mdLite(s) {
    var out = esc(s || '')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\n\n+/g, '</p><p>')
      .replace(/\n/g, '<br>');
    return '<p>' + out + '</p>';
  }

  function icon(name, cls) {
    if (_ctx && typeof _ctx.icon === 'function') {
      // ctx.icon(name) returns an SVG STRING, not a DOM node (see ext_cr_boot.js's
      // icon()) — wrap it to get a real element, matching cr_board.js's icon().
      var svg = _ctx.icon(name);
      if (svg) {
        var wrap = document.createElement('span');
        wrap.innerHTML = svg;
        var node = wrap.firstElementChild;
        if (node) { if (cls) node.classList.add(cls); return node; }
      }
    }
    return fallbackGlyph(name, cls);
  }

  // FIX 5: this table used to carry all 13 of ext_cr_boot.js's GLYPHS entries (pixel-
  // identical, verified by reading that file) just to add one extra key, 'close', that
  // boot's table lacks. icon() above already tries ctx.icon(name) — backed by boot's
  // table — FIRST for every name, so the duplicated entries were only ever reached as a
  // fallback for 'close' itself, or in the (untested-in-practice) case ctx is missing
  // entirely, in which case nothing beyond 'close' had a real local path to fall to
  // anyway. Trimmed to the one key this file actually owns. REQUIRED ADDITION: boot's
  // GLYPHS/icon() should absorb 'close' so this fallback table can go away completely.
  var GLYPH_PATHS = {
    close: 'M6 6l12 12M18 6L6 18'
  };
  function fallbackGlyph(name, cls) {
    var d = GLYPH_PATHS[name] || GLYPH_PATHS.close;
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '16');
    svg.setAttribute('height', '16');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('class', 'cr-glyph' + (cls ? ' ' + cls : ''));
    var p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', d);
    p.setAttribute('fill', 'none');
    p.setAttribute('stroke', 'currentColor');
    p.setAttribute('stroke-width', '1.75');
    p.setAttribute('stroke-linecap', 'round');
    p.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(p);
    return svg;
  }

  function copyBtn(getText) {
    var btn = h('button', { class: 'cr-copybtn', type: 'button', 'aria-label': 'Copy' },
      [icon('panel'), h('span', { text: 'Copy' })]);
    btn.addEventListener('click', function () {
      var text = getText();
      var done = function () {
        btn.classList.add('is-done');
        btn.querySelector('span').textContent = 'Copied';
        setTimeout(function () {
          btn.classList.remove('is-done');
          btn.querySelector('span').textContent = 'Copy';
        }, 1400);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, done);
      } else {
        var ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(ta);
        done();
      }
    });
    return btn;
  }

  function emoji(ch, cls, label) {
    return h('span', { class: 'cr-emo tn-emo' + (cls ? ' ' + cls : ''), 'aria-hidden': 'true', title: label || null }, [ch]);
  }

  // ---------------------------------------------------------------------------
  // shared state components — exported so board/detail/terminal reuse rather than fork
  // ---------------------------------------------------------------------------

  // CR.dialogs.emptyState({title, body, icon}) -> HTMLElement
  // Doc 04 "Two different empties" — the "nothing yet" case: dashed --ads-line-default box.
  function emptyState(opts) {
    opts = opts || {};
    return h('div', { class: 'cr-state cr-state-empty', role: 'note' }, [
      h('div', { class: 'cr-state-title' }, [opts.title || 'Nothing here yet']),
      h('div', { class: 'cr-state-body' }, [opts.body || 'It will fill in as it works.']),
    ]);
  }

  // CR.dialogs.errorState({title, body}) -> HTMLElement
  // Doc 04 "Two different empties" — the "something broke" case: --ads-surface-failed + line-failed.
  function errorState(opts) {
    opts = opts || {};
    return h('div', { class: 'cr-state cr-state-error', role: 'alert' }, [
      h('div', { class: 'cr-state-title' }, [emoji('⚠️', 'tn-emo-f'), ' ', opts.title || "Couldn't read this"]),
      h('div', { class: 'cr-state-body' }, [opts.body || 'Everything before the failure is shown.']),
    ]);
  }

  // CR.dialogs.degraded({panelLabel, providerLabel, pill, message, readable, footer}) -> HTMLElement
  // Doc 04 "Degraded provider" card — an explanation, not an empty panel.
  function degraded(opts) {
    opts = opts || {};
    var panelLabel = opts.panelLabel || 'NARRATION';
    var providerLabel = opts.providerLabel || '';
    var pill = opts.pill || 'NOT ON DISK';
    var message = opts.message ||
      "This tool's chat transcript isn't stored anywhere the tracker can read. The tracker " +
      "is stdlib-only, so it can't decode a proprietary/binary store.";
    var readable = opts.readable ||
      'What IS readable is shown in full: todos and files touched. Nothing is being hidden ' +
      'or approximated.';
    var footer = opts.footer || 'Empty because it cannot exist — not because something broke.';
    return h('div', { class: 'cr-degraded', role: 'note' }, [
      h('div', { class: 'cr-degraded-head' }, [
        h('span', { class: 'cr-degraded-label' }, [panelLabel]),
        h('span', { class: 'cr-degraded-provider' }, [providerLabel]),
      ]),
      h('div', { class: 'cr-degraded-rule' }),
      h('div', { class: 'cr-degraded-pill' }, [pill]),
      h('div', { class: 'cr-degraded-msg' }, [message]),
      h('div', { class: 'cr-degraded-readable' }, [readable]),
      h('div', { class: 'cr-degraded-footer' }, [footer]),
    ]);
  }

  // A dashed, dismissible "turn on desktop alerts" row. Callers (board's top bar owns
  // placement) mount the returned element wherever they like; shown once, ever, unless
  // localStorage is cleared. Never call this on first paint — wait for the first
  // notify-worthy event.
  function notificationNudge() {
    if (localStorage.getItem('cr.notif.nudgeDismissed') === '1') return null;
    if (!('Notification' in window) || Notification.permission !== 'default') return null;
    var row = h('div', { class: 'cr-nudge', role: 'note' }, [
      emoji('🔔', 'tn-emo'),
      h('span', { class: 'cr-nudge-text' }, [
        'Desktop alerts are off. Turn them on to hear about finished agents while this tab is in the background.',
      ]),
      h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Allow' }),
      h('button', { class: 'cr-nudge-x', type: 'button', 'aria-label': 'Dismiss', html: '&times;' }),
    ]);
    row.querySelector('.cr-btn').addEventListener('click', function () {
      Notification.requestPermission().then(function () {
        localStorage.setItem('cr.notif.nudgeDismissed', '1');
        row.remove();
      });
    });
    row.querySelector('.cr-nudge-x').addEventListener('click', function () {
      localStorage.setItem('cr.notif.nudgeDismissed', '1');
      row.remove();
    });
    return row;
  }

  // CR.dialogs.showNudgeIfNeeded() — Fix 1c: notificationNudge() was fully built to
  // spec but had ZERO call sites, so it never appeared. This mounts it (floating,
  // bottom-left, clear of the toast stack at bottom-right) the first time this module
  // is asked to — the
  // caller (ext_cr_boot.js) calls it right when it has a real notify-worthy event
  // (a session landing), satisfying "never on first paint". Idempotent per page life:
  // notificationNudge() itself already returns null once dismissed/granted/denied, and
  // _nudgeAttempted stops this from re-querying/re-inserting on every later completion.
  var _nudgeAttempted = false;
  function showNudgeIfNeeded() {
    if (_nudgeAttempted || !_root) return;
    _nudgeAttempted = true;
    var el = notificationNudge();
    if (!el) return;
    el.classList.add('cr-nudge-float');
    _root.appendChild(el);
  }

  // ---------------------------------------------------------------------------
  // toast notifications (capability #51) — a stack in the corner, plus a real
  // Notification() when the tab is backgrounded.
  // ---------------------------------------------------------------------------

  // toast(opts) — opts is EITHER a bare string (used as the title) OR an object.
  // NOTE (Fix 1a — payload contract): ext_cr_boot.js's ~20 confirmation emitters
  // (rename/note/flag/etc.) call `ctx.emit('notify', {text: "..."})`; this function
  // used to read only `opts.title`/`opts.meta`, so every one of those rendered as a
  // blank-bodied generic "Finished" toast. `opts.text` is now accepted as an alias for
  // `opts.title` — the ONE shape going forward is {title, meta} (meta optional, mono
  // submeta line per doc 04's Toast spec), with `text` kept only for that existing
  // caller population and a bare string tolerated too.
  function toast(opts) {
    if (typeof opts === 'string') opts = { title: opts };
    opts = opts || {};
    if (!_toastHost) return;
    var title = opts.title || opts.text || 'Finished';
    var dismissed = false;
    var timer = null;
    var el = h('div', { class: 'cr-toast', role: 'status' }, [
      emoji(opts.icon || '✅', opts.iconClass || 'tn-emo-d'),
      h('div', { class: 'cr-toast-body' }, [
        h('div', { class: 'cr-toast-title' }, [title]),
        opts.meta ? h('div', { class: 'cr-toast-meta' }, [opts.meta]) : null,
      ]),
      opts.actionLabel ? h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: opts.actionLabel }) : null,
      h('button', { class: 'cr-toast-x', type: 'button', 'aria-label': 'Dismiss', html: '&times;' }),
    ]);
    function dismiss() { if (dismissed) return; dismissed = true; clearTimeout(timer); el.remove(); }
    var actionBtn = el.querySelector('.cr-btn');
    if (actionBtn) actionBtn.addEventListener('click', function () { if (opts.onAction) opts.onAction(); dismiss(); });
    el.querySelector('.cr-toast-x').addEventListener('click', dismiss);
    function arm() { timer = setTimeout(dismiss, opts.duration || 8000); }
    function disarm() { clearTimeout(timer); }
    el.addEventListener('mouseenter', disarm);
    el.addEventListener('mouseleave', function () { if (!document.hidden) arm(); });
    el.addEventListener('focusin', disarm);
    el.addEventListener('focusout', function () { if (!document.hidden) arm(); });
    _toastHost.appendChild(el);
    if (!document.hidden) arm(); // "never auto-dismiss while [the tab is] focused" — see NOTE below

    // FIX 3 (real bug, reported twice): this used to also raise `new Notification(...)`
    // here whenever the tab was hidden (soundOn-gated as of FIX 2 above) — but this
    // function is the SAME toast() called for every routine confirmation on the bus
    // (rename/note/flag/run-command/etc., ~20 call sites in ext_cr_boot.js), not just
    // real completions. A desktop Notification carries the OS's own notification sound
    // by default, so backgrounding the tab and, say, renaming a session or resolving a
    // flag popped an audible alert — exactly the "sound every time" complaint, and
    // exactly the classic dashboard's app.js toast() (~app.js:1139) never does this: it
    // is purely a visual banner, full stop. The ONE place a real completion is allowed
    // to raise a desktop Notification is app.js's own notifyDone() (app.js ~1152,
    // soundOn-gated, called unchanged via ext_cr_boot.js's wrapper for every genuine
    // running->done transition) — already independent of this function entirely, so
    // deleting this block loses no real-completion alert, only the spurious ones this
    // function was never supposed to raise.
    return dismiss;
  }
  // NOTE: doc 04 reads "Auto-dismiss 8s; pause on hover; never auto-dismiss while
  // focused." The most consistent reading with "Desktop notification — only when the
  // tab is backgrounded" (the very next bullet) is PAGE focus, not element focus — a
  // toast should sit still while you're actively looking at the tab. Implemented that
  // way: the arm()/disarm() pair above also keys off document.hidden.

  // ---------------------------------------------------------------------------
  // focus trap + dialog host
  // ---------------------------------------------------------------------------

  var FOCUSABLE = 'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

  function trapFocus(container) {
    function within(list) { return Array.prototype.slice.call(container.querySelectorAll(FOCUSABLE)).filter(function (n) { return n.offsetParent !== null || n === document.activeElement; }); }
    function onKeydown(e) {
      if (e.key !== 'Tab') return;
      var f = within();
      if (!f.length) { e.preventDefault(); return; }
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    container.addEventListener('keydown', onKeydown);
    return function () { container.removeEventListener('keydown', onKeydown); };
  }

  function topEntry() { return _stack[_stack.length - 1] || null; }

  function onDocKeydown(e) {
    if (e.key !== 'Escape') return;
    var top = topEntry();
    if (!top) return;
    e.preventDefault();
    close();
  }

  // CR.dialogs.mount(rootEl, ctx)
  function mount(rootEl, ctx) {
    _ctx = ctx;
    _root = rootEl;
    _layer = h('div', { class: 'cr-dialog-layer', 'aria-hidden': 'true' });
    _toastHost = h('div', { class: 'cr-toast-host', 'aria-live': 'polite' });
    _root.appendChild(_layer);
    _root.appendChild(_toastHost);
    document.addEventListener('keydown', onDocKeydown);
    if (ctx && typeof ctx.on === 'function') {
      // Shared bus convention (documented in the handoff report): any module can raise
      // a toast without depending on this module directly by emitting 'notify'.
      ctx.on('notify', function (payload) { toast(payload || {}); });
      ctx.on('dialog:open', function (payload) { open((payload && payload.name) || '', payload && payload.data); });
      ctx.on('dialog:close', function () { close(); });
    }
  }

  function buildChrome(name, title, emo, contextStr, wide, emoCls) {
    var titleId = 'cr-dlg-title-' + (++_idSeq);
    var backdrop = h('div', { class: 'cr-backdrop' });
    var panel = h('div', {
      class: 'cr-dialog' + (wide ? ' cr-dialog-wide' : ''),
      role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId,
      'data-cr-dialog': name,
    });
    var head = h('div', { class: 'cr-dialog-head' }, [
      h('div', { class: 'cr-dialog-heading' }, [
        // emoCls: role variant per doc 01's emoji table (e.g. 'tn-emo-f' for
        // the flags 🚩 dialog) — defaults to the base tint when omitted.
        emo ? emoji(emo, emoCls || null) : null,
        h('h2', { id: titleId, class: 'cr-dialog-title' }, [title]),
      ]),
      h('div', { class: 'cr-dialog-context' }, [contextStr || '']),
      h('button', { class: 'cr-dialog-close', type: 'button', 'aria-label': 'Close (Esc)' }, [icon('close')]),
    ]);
    var body = h('div', { class: 'cr-dialog-body' });
    panel.appendChild(head);
    panel.appendChild(body);
    head.querySelector('.cr-dialog-close').addEventListener('click', close);
    backdrop.addEventListener('mousedown', function (e) { if (e.target === backdrop) close(); });
    return { backdrop: backdrop, panel: panel, body: body };
  }

  // CR.dialogs.open(name, payload)
  //
  // Ground-truth check against the sibling modules already on disk (cr_detail.js,
  // cr_term.js) found several dialogs opened MORE THAN ONCE for the same name in
  // quick succession, with progressively richer payloads — e.g. "directory-picker"
  // opens immediately with {loading:true}, then again once GET /api/term/cwds
  // resolves; "manage-terminals" opens with an empty list then again with real
  // data or an error. Re-opening the same name while it's already the topmost
  // dialog updates it in place (via the builder's own `update`) instead of
  // stacking a second copy on top of itself.
  function open(name, payload) {
    var top = topEntry();
    if (top && top.name === name && typeof top.update === 'function') {
      top.update(payload || {});
      return;
    }
    var builder = REGISTRY[name];
    if (!builder) { return; }
    var opener = document.activeElement;
    var built = builder(payload || {});
    if (!built) return;
    var wrap = h('div', { class: 'cr-dialog-wrap' }, [built.backdrop, built.panel]);
    _layer.appendChild(wrap);
    _layer.setAttribute('aria-hidden', 'false');
    var untrap = trapFocus(built.panel);
    var entry = { name: name, wrap: wrap, panel: built.panel, opener: opener, untrap: untrap, update: built.update };
    _stack.push(entry);
    // Focus the first focusable control, else the panel itself.
    var f = built.panel.querySelector(FOCUSABLE);
    (f || built.panel).focus({ preventScroll: true });
    if (!f) built.panel.setAttribute('tabindex', '-1');
    if (_ctx && typeof _ctx.emit === 'function') _ctx.emit('dialog:opened', { name: name });
  }

  // CR.dialogs.close() — closes the topmost dialog only.
  function close() {
    var entry = _stack.pop();
    if (!entry) return;
    entry.untrap();
    entry.wrap.remove();
    if (!_stack.length) _layer.setAttribute('aria-hidden', 'true');
    if (entry.opener && typeof entry.opener.focus === 'function') {
      try { entry.opener.focus({ preventScroll: true }); } catch (e) {}
    }
    if (_ctx && typeof _ctx.emit === 'function') _ctx.emit('dialog:closed', { name: entry.name });
  }

  // CR.dialogs.update(state) — forwarded to the topmost dialog's own updater, if any.
  function update(state) {
    var top = topEntry();
    if (top && typeof top.update === 'function') top.update(state);
  }

  // ---------------------------------------------------------------------------
  // Help dialog
  // ---------------------------------------------------------------------------

  // The 60-item capability map (doc 04). This is the data structure Help's Per-tool
  // tab renders FROM — see the REQUIRED ADDITION in the report: ideally a Python
  // self-check asserts against this same list so Help can never drift from what
  // actually shipped; today only this JS copy exists.
  var CAPABILITIES = [
    [1, 'Every session, all tools, newest first', 'board'], [2, 'Source badge (7 sources)', 'board'],
    [3, 'Live dot + 5-minute live window', 'board'], [4, 'Waiting-on-answer end-state', 'board'],
    [5, 'Just-completed end-state', 'board'], [6, '"N live" filter', 'board'],
    [7, 'Flag count badge + red edge', 'board'], [8, 'Notes count badge', 'board'],
    [9, 'Cross-session flag list', 'dialogs'], [10, 'Search sessions, name matches first', 'board'],
    [11, 'Rename a session', 'detail'], [12, 'Pin above recency', 'board'],
    [13, 'Agents · repo collapsible group', 'board'], [14, 'In-transcript agents running badge', 'board+detail'],
    [15, 'New terminal / new Claude session', 'terminal'], [16, 'Manage terminals + live count', 'terminal'],
    [17, 'Notification bell', 'board'], [18, 'Theme toggle', 'board+dialogs+terminal'],
    [19, "Idle sessions don't bury live ones", 'board'], [20, 'Progress ring -> progress spine', 'detail'],
    [21, 'Stat chips (7)', 'detail'], [22, 'State / Activity split', 'detail'],
    [23, 'Panels collapse to header, persisted', 'detail'], [24, 'Waiting-on-you header state', 'detail'],
    [25, 'Summary Goal / Now / So far', 'detail'], [26, 'Decisions & open questions', 'detail'],
    [27, "Narration, its own words", 'detail'], [28, 'Narration prev/next + jump-to-latest', 'detail'],
    [29, 'Live follow / hold your place', 'detail'], [30, 'Unbounded history, page on scroll', 'detail'],
    [31, 'Markdown rendering', 'detail'], [32, 'Mermaid -> SVG, 8 families', 'detail'],
    [33, 'Copy per code block', 'detail'], [34, 'Prompts, incl. slash commands', 'detail'],
    [35, 'Files + diff per edit', 'detail+dialogs'], [36, 'Up/down context expansion', 'dialogs'],
    [37, 'Expand all', 'dialogs'], [38, 'Diff <> Rendered markdown', 'dialogs'],
    [39, 'Open in new tab', 'dialogs'], [40, 'Files written by agents, tagged', 'detail'],
    [41, 'Commands with pass/fail', 'detail'], [42, 'Pull requests, created only', 'detail'],
    [43, 'merged/closed badges', 'detail'], [44, 'Agent-opened PRs attributed', 'detail'],
    [45, 'Links, generated vs worked on (new panel)', 'detail'], [46, 'Plan on the go: add/copy/push/remove', 'detail'],
    [47, 'Delivery chips (turn-end / on wake / copy it)', 'detail'], [48, 'Background agents & shells', 'detail'],
    [49, 'Re-run collapse', 'detail'], [50, 'Show N finished', 'detail'],
    [51, 'Toast + sound + desktop notification', 'dialogs'], [52, 'Fork lineage banner + back-link', 'detail'],
    [53, 'Search within the session', 'detail'], [54, 'Command runner + constraint stated', 'detail'],
    [55, 'Model / effort switchers', 'terminal+detail'], [56, 'Context readout', 'terminal+detail'],
    [57, 'Open / resume / external terminal', 'detail+terminal'], [58, 'Degraded provider messaging', 'dialogs'],
    [59, 'Config dialog (new)', 'dialogs'], [60, 'Progress spine (new)', 'detail'],
  ];
  var OWNER_LABEL = { board: 'Board', detail: 'Detail', terminal: 'Terminal', dialogs: 'Dialogs' };

  var STATE_ROWS = [
    ['Waiting on you', 'orange', 'Waiting on you · <age>', 'none'],
    ['Working', 'wheat', 'Working', 'dot pulse, 2.4s'],
    ['Flagged', 'rust', 'N flags open', 'none'],
    ['Failing', 'brick', 'fail + command name', 'none'],
    ['Landed', 'forest', 'Landed', 'none'],
    ['Idle', 'grey', 'counted, not listed', 'none'],
  ];

  // Coverage tab's colour legend — round 5's final artboard (`5c`, the authoritative
  // one per the owner's ruling; the docs were written from round 4 and never caught
  // up). 5c draws exactly five rows: Waiting on you/orange, Working now/wheat, Your
  // flags/rust, Evidence/dusk, Failures/brick. This is a COLOUR legend, not a literal
  // board-state reference — "Evidence" is the detail view's own Evidence column
  // (ext_cr_detail.js's "Evidence" eyebrow), tinted with --text-dusk, not a session
  // status word — which is why it's a separate list from STATE_ROWS above (that one
  // stays a real per-state reference for the States tab: When/Word shown/Motion,
  // none of which "Evidence" has an honest answer for).
  //
  // Judgement call: Landed and Idle are genuine states the board renders (see
  // ext_cr_board.css's .cr-rail-dot.is-landed / default idle grey, and STATE_ROWS
  // above) but 5c's five rows don't mention them. Dropping them here would make this
  // legend incomplete versus what the UI actually shows a viewer, so they're kept as
  // two extra rows AFTER 5c's five, rather than silently carrying over the previous
  // (wrong) wording for them.
  var LEGEND_ROWS = [
    ['Waiting on you', 'orange', 'Waiting on you · <age>'],
    ['Working now', 'wheat', 'Working'],
    ['Your flags', 'rust', 'N flags open'],
    ['Evidence', 'dusk', 'Evidence'],
    ['Failures', 'brick', 'fail + command name'],
    ['Landed', 'forest', 'Landed'],
    ['Idle', 'grey', 'counted, not listed'],
  ];

  // Providers actually registered in aitracker/registry.py (4, matching "4 tools" in
  // the stat block) and where each is known — from the project README — to degrade.
  //
  // Fix 3: each entry now also carries `ids` — the REAL source/provider identifier(s)
  // a session can carry (aitracker/web/app.js's own SRC map: "auggie", "augment-vscode",
  // "augment-cursor", plus Claude's own cli/claude-desktop/sdk-cli/claude-vscode/"" —
  // registry.py's unprefixed provider is the fallback). The audit's "live path silently
  // skipped Auggie" finding was a caller pattern-matching a display NAME (or a fuzzy
  // /augment/i.test() that a literal "auggie" string never trips, so it fell through to
  // a default) instead of the real value — providerNoteFor() below is the single correct
  // lookup so every consumer (this dialog's Per-tool tab, ext_cr_detail.js's degraded()
  // callers) shares one answer instead of re-deriving it.
  var PROVIDER_NOTES = [
    { name: 'Claude Code', ids: ['', 'cli', 'claude-desktop', 'sdk-cli', 'claude-vscode'], ok: 'Full support, incl. background agents & shells and PR attribution.' },
    { name: 'Auggie', ids: ['auggie'], ok: 'Full narration/todos/files/commands.', degraded: 'No background-work model — capability 48 shows empty-because-it-cannot-exist, not broken.' },
    { name: 'Augment (VS Code)', ids: ['augment-vscode'], degraded: 'Chat transcript lives in a per-workspace LevelDB the tracker cannot decode — narration degrades honestly; todos and files still read in full.' },
    { name: 'Augment (Cursor)', ids: ['augment-cursor'], degraded: 'Same LevelDB limitation as Augment (VS Code).' },
  ];

  // CR.dialogs.providerNoteFor(source) -> the matching PROVIDER_NOTES entry, or null if
  // `source` isn't one of the four known providers. `source` is the session's real
  // meta.source/source value (case-insensitive) — never a display name.
  function providerNoteFor(source) {
    var key = String(source == null ? '' : source).toLowerCase();
    for (var i = 0; i < PROVIDER_NOTES.length; i++) {
      if (PROVIDER_NOTES[i].ids.indexOf(key) !== -1) return PROVIDER_NOTES[i];
    }
    return null;
  }

  var HELP_SHORTCUTS = [
    ['?', 'Open Help'], ['Esc', 'Close the topmost dialog'], ['⌘K / Ctrl+K', 'Search sessions'],
  ];
  // Sibling modules can add their own rows (e.g. terminal's PTY key bindings, board's
  // rail shortcuts) without reaching into this file — see CR.dialogs.addHelpShortcuts.
  function addHelpShortcuts(rows) {
    (rows || []).forEach(function (r) { HELP_SHORTCUTS.push(r); });
  }

  var TERMINAL_REFERENCE = [
    ['Scrollback', 'Mouse wheel; full-screen programs get arrow keys instead.'],
    ['Copy', 'Cmd+C / Ctrl+Shift+C — plain Ctrl+C always sends SIGINT.'],
    ['Native selection', 'Hold Shift to force a browser selection even under mouse tracking.'],
    ['Modified keys', 'Ctrl/Shift/Alt/Meta + arrows, Home/End, Insert/Delete/PgUp/PgDn, F1–F12.'],
    ['Alt+Enter', 'Sends newline-without-submit, not a submit.'],
    ['Ctrl+Space', 'Sends NUL.'],
    ['Mouse reporting', 'Press/drag/release/wheel forwarded to any program that asks for it.'],
    ['Renderer switch', 'Toolbar ☀️/🌙 and a renderer control — xterm (default) or grid, per terminal.'],
    ['Model / effort', '/model <name> and /effort <level> typed into the CLI when it is in the foreground.'],
  ];

  function helpCoverageTab() {
    var wrap = h('div', { class: 'cr-help-tab' });
    wrap.appendChild(h('h3', { class: 'cr-serif-h3' }, ['What this app can see, and what it can’t.']));
    wrap.appendChild(h('p', { class: 'cr-lede' }, [
      'It reads the session logs your tools already write. Nothing is sent anywhere, and it never writes into a session.',
    ]));
    wrap.appendChild(h('div', { class: 'cr-stat-row' }, [
      h('div', { class: 'cr-stat cr-stat-forest' }, [h('div', { class: 'cr-stat-num' }, [String(CAPABILITIES.length)]), h('div', { class: 'cr-stat-label' }, ['capabilities'])]),
      h('div', { class: 'cr-stat cr-stat-neutral' }, [h('div', { class: 'cr-stat-num' }, [String(PROVIDER_NOTES.length)]), h('div', { class: 'cr-stat-label' }, ['tools'])]),
      h('div', { class: 'cr-stat cr-stat-dusk' }, [h('div', { class: 'cr-stat-num' }, ['0']), h('div', { class: 'cr-stat-label' }, ['bytes leaving'])]),
    ]));
    // NOTE (Fix 5, supersedes a prior NOTE here): doc 04's Coverage-tab copy literally
    // said "58 capabilities" while the capability map below it enumerates 60 rows (2
    // marked New: the Config dialog and the progress spine, both genuinely shipped —
    // see docs 03/04) — an audit caught Help disagreeing with what shipped, which is
    // exactly the drift "Generate the capability table from the same data structure the
    // tests assert against" (doc 04) exists to prevent. Reconciled by deriving the stat
    // from CAPABILITIES.length (60) instead of repeating the doc's stale literal;
    // tests/test_capability_table.py pins this number so the two can't drift again.
    var table = h('table', { class: 'cr-state-table' });
    table.appendChild(h('thead', {}, [h('tr', {}, [h('th', {}, ['State']), h('th', {}, ['Colour']), h('th', {}, ['Word shown'])])]));
    var tbody = h('tbody');
    LEGEND_ROWS.forEach(function (r) {
      tbody.appendChild(h('tr', {}, [
        h('td', {}, [r[0]]),
        h('td', {}, [h('span', { class: 'cr-swatch cr-swatch-' + r[1] }), ' ' + r[1]]),
        h('td', { class: 'cr-mono' }, [r[2]]),
      ]));
    });
    table.appendChild(tbody);
    wrap.appendChild(table);

    wrap.appendChild(h('div', { class: 'cr-seccards' }, [
      h('div', { class: 'cr-seccard cr-seccard-brick' }, [
        h('div', { class: 'cr-seccard-title' }, [emoji('⚠️', 'tn-emo-f'), ' Read this before you expose the server']),
        h('ul', {}, [
          h('li', {}, ['The in-browser terminal is an unrestricted shell, reachable wherever the server is — no allowlist applies to it.']),
          h('li', {}, ['Treat TRACKER_AUTH with the seriousness you’d give a root password, and rotate it if you expose it publicly.']),
          h('li', {}, ['"Local only" on the ↗ external-terminal buttons is best-effort, not a guarantee — a tunnel terminates locally too.']),
        ]),
      ]),
      h('div', { class: 'cr-seccard cr-seccard-forest' }, [
        h('div', { class: 'cr-seccard-title' }, [emoji('✅', 'tn-emo-d'), ' What is actually confined']),
        h('ul', {}, [
          h('li', {}, ['cat and ls in the command runner are confined to the session’s own directory — they can’t read your keys.']),
          h('li', {}, ['The command runner has no shell: argv is shlex.split and execvp’d, so shell metacharacters are never operators.']),
          h('li', {}, ['git’s known config-driven exec vectors (external diff/textconv, fsmonitor, hooksPath, pager, editor) are neutralised.']),
        ]),
      ]),
    ]));
    // NOTE (fixes a prior wrong claim here): that prior note said no section titled
    // "Read this before you expose the server" exists anywhere in the source material —
    // true of the docs (README/doc 04), but FALSE of the actual prototype: the sentence
    // is verbatim in the design file's `4e` artboard (the discarded full-page-Help
    // exploration) as the eyebrow over this exact pair of cards, and the owner's
    // ruling makes the artboards authoritative over the docs. `5c` (the final, in-scope
    // Help/Config-as-dialogs artboard) doesn't redraw this heading itself, so `4e` fills
    // in the detail per the ruling's own allowance for that. Adopted verbatim above as
    // the brick card's title, replacing the old "If you expose this beyond localhost"
    // wording. The list content itself still has no verbatim doc/prototype source, so
    // it stays the README-derived copy ("What these features do and don't guarantee",
    // README.md:104-108) it always was.

    wrap.appendChild(h('div', { class: 'cr-help-footer' }, [
      emoji('🧩', 'tn-emo'),
      h('span', {}, ['Your tool isn’t listed? A provider is two functions.']),
      h('a', { class: 'cr-link', href: '#', text: 'Read' }),
    ]));
    return wrap;
  }

  function helpStatesTab() {
    var wrap = h('div', { class: 'cr-help-tab' });
    wrap.appendChild(h('h3', { class: 'cr-serif-h3' }, ['Six states, one word each.']));
    var table = h('table', { class: 'cr-state-table' });
    table.appendChild(h('thead', {}, [h('tr', {}, [h('th', {}, ['State']), h('th', {}, ['When']), h('th', {}, ['Word shown']), h('th', {}, ['Motion'])])]));
    var tbody = h('tbody');
    var WHEN = ['Unanswered AskUserQuestion / ask-user', 'Active within the live window', 'You raised a flag',
      'A command/test returned non-zero', 'Last turn completed inside the live window', 'Untouched 5+ minutes'];
    STATE_ROWS.forEach(function (r, i) {
      tbody.appendChild(h('tr', {}, [
        h('td', {}, [h('span', { class: 'cr-swatch cr-swatch-' + r[1] }), ' ' + r[0]]),
        h('td', {}, [WHEN[i]]),
        h('td', { class: 'cr-mono' }, [r[2]]),
        h('td', {}, [r[3]]),
      ]));
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    wrap.appendChild(h('p', { class: 'cr-lede' }, ['Waiting outranks everything, including recency.']));
    return wrap;
  }

  function helpKeyboardTab() {
    var wrap = h('div', { class: 'cr-help-tab' });
    wrap.appendChild(h('h3', { class: 'cr-serif-h3' }, ['Keyboard']));
    var table = h('table', { class: 'cr-kbd-table' });
    HELP_SHORTCUTS.forEach(function (r) {
      table.appendChild(h('tr', {}, [h('td', {}, [h('kbd', { class: 'cr-kbd' }, [r[0]])]), h('td', {}, [r[1]])]));
    });
    wrap.appendChild(table);
    return wrap;
  }

  function helpTerminalTab() {
    var wrap = h('div', { class: 'cr-help-tab' });
    wrap.appendChild(h('h3', { class: 'cr-serif-h3' }, ['Terminal reference']));
    var table = h('table', { class: 'cr-kbd-table' });
    TERMINAL_REFERENCE.forEach(function (r) {
      table.appendChild(h('tr', {}, [h('td', { class: 'cr-mono' }, [r[0]]), h('td', {}, [r[1]])]));
    });
    wrap.appendChild(table);
    return wrap;
  }

  function helpPerToolTab() {
    var wrap = h('div', { class: 'cr-help-tab' });
    wrap.appendChild(h('h3', { class: 'cr-serif-h3' }, ['Per-tool coverage']));
    PROVIDER_NOTES.forEach(function (p) {
      var card = h('div', { class: 'cr-provider-card' + (p.degraded ? ' is-degraded' : '') }, [
        h('div', { class: 'cr-provider-name' }, [p.name]),
        p.ok ? h('div', { class: 'cr-provider-note' }, [emoji('✅', 'tn-emo-d'), ' ' + p.ok]) : null,
        p.degraded ? h('div', { class: 'cr-provider-note cr-provider-degraded' }, [emoji('⏳', 'tn-emo-a'), ' ' + p.degraded]) : null,
      ]);
      wrap.appendChild(card);
    });
    wrap.appendChild(h('p', { class: 'cr-help-note' }, [
      esc(CAPABILITIES.length) + ' capabilities tracked across ' + PROVIDER_NOTES.length + ' providers — generated from the same list this dialog’s Coverage tab counts from.',
    ]));
    return wrap;
  }

  var HELP_TABS = [
    ['coverage', 'Coverage', helpCoverageTab],
    ['states', 'States', helpStatesTab],
    ['keyboard', 'Keyboard', helpKeyboardTab],
    ['terminal', 'Terminal', helpTerminalTab],
    ['per-tool', 'Per-tool', helpPerToolTab],
  ];

  function renderHelp(payload) {
    // Header subtitle: 5c gives Help a bare "?" (not "ai-tracker" — that was never
    // this dialog's real subtitle, just a placeholder left over before the artboard
    // was consulted).
    var chrome = buildChrome('help', 'Help', '❓', '?', false);
    chrome.panel.classList.add('cr-dialog-help');
    var tabs = h('div', { class: 'cr-tabpills', role: 'tablist' });
    var pane = h('div', { class: 'cr-tabpane' });
    var active = (payload && payload.tab) || 'coverage';
    function renderActive() {
      pane.innerHTML = '';
      var entry = HELP_TABS.filter(function (t) { return t[0] === active; })[0] || HELP_TABS[0];
      pane.appendChild(entry[2]());
      Array.prototype.forEach.call(tabs.children, function (btn) {
        var on = btn.getAttribute('data-tab') === active;
        btn.classList.toggle('is-active', on);
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    }
    HELP_TABS.forEach(function (t) {
      var btn = h('button', { class: 'cr-tabpill', type: 'button', role: 'tab', 'data-tab': t[0], text: t[1] });
      btn.addEventListener('click', function () { active = t[0]; renderActive(); });
      tabs.appendChild(btn);
    });
    chrome.body.appendChild(tabs);
    chrome.body.appendChild(pane);
    renderActive();
    return { backdrop: chrome.backdrop, panel: chrome.panel };
  }

  // ---------------------------------------------------------------------------
  // Config dialog — real parameters only (aitracker/config.py)
  // ---------------------------------------------------------------------------

  var CFG_PREF_KEYS = {
    theme: null, // routed through ctx.theme, not localStorage, to avoid a second source of truth
    // Fix 2a: the rail's REAL key is 'tracker.rail.mode' (a raw string
    // 'auto'|'open'|'collapsed' — see readRailPref/writeRailPref below), not a JSON
    // boolean under 'cr.railOpen'. Reset to defaults must clear the key the rail
    // actually reads, or it silently resets everything EXCEPT the rail. The two dead
    // predecessors are listed after it so a stray value from an earlier build still
    // gets cleared.
    railMode: 'tracker.rail.mode',
    railLegacy: 'tracker.rail',
    railOpen: 'cr.railOpen',
    cardsFolded: 'cr.cardsFolded',
    // The owner's call (see the board-tile-count decision in the PR that wired this row up):
    // a 3–8 slider, NOT 04's original 3–12 spec — 3–8 never exceeds the handoff README's
    // "board never renders more than 8 tiles" cap, so both docs are satisfied at once.
    // Client-side preference ONLY (never a server config.json key) — ext_cr_board.js reads
    // this SAME key and clamps to 3..8 on its own side; the two must agree on both the key
    // name and the value shape: a bare JSON-encoded integer (`JSON.stringify(n)`, i.e. the
    // string "3".."8"), read back with `JSON.parse(localStorage.getItem(key))`. Unset ->
    // the board's own default (8, matching the previous fixed behaviour) applies.
    boardTiles: 'cr.boardTileCount',
    pollMs: 'cr.pollIntervalMs',
    desktopNotif: 'cr.notif.enabled',
    sound: 'cr.notif.sound',
    // Doc 04 capability #21's 7-chip stat row (files, commands, reads, commits, tests,
    // tokens, branch) in the session-detail header, restored opt-in / default OFF.
    // Client-side preference ONLY, and the reader (ext_cr_detail.js) is already wired to
    // this EXACT contract, fixed — do not change key, value shape, or event name here:
    // key holds the raw string "1" (show); "0" or absent means hide. NOT JSON-encoded
    // like readPref/writePref's booleans, so it gets its own read/write pair below
    // (readStatChipsPref/writeStatChipsPref) instead of routing through readPref/writePref.
    statChips: 'tracker.next.statchips',
  };

  // Env-var chip text for each server config.json key (config.py's EDITABLE/VALIDATORS
  // universe, plus AUTH which is displayed but never posted) — purely cosmetic labelling,
  // matches the exact env var name each key falls back to per config.py's own _ENV_NAME.
  var _ENVCHIP = {
    LIVE_WINDOW: null,   // never had an env var of its own — config.json > built-in default
    TERM_RENDERER: 'TRACKER_TERM_RENDERER',
    MAX_TERMS: 'TRACKER_MAX_TERMS',
    TERMINAL: 'TRACKER_TERMINAL',
    TERM_APP: 'TRACKER_TERM_APP',
    TERM_ALLOW: 'TRACKER_TERM_ALLOW',
    PORT: 'PORT',
    HOST: 'HOST',
  };

  function readPref(key, dflt) {
    try {
      var raw = localStorage.getItem(key);
      if (raw == null) return dflt;
      return JSON.parse(raw);
    } catch (e) { return dflt; }
  }
  function writePref(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {}
    if (_ctx && typeof _ctx.emit === 'function') _ctx.emit('cr:pref', { key: key, value: val });
  }

  // Fix 2a — the session rail (ext_cr_board.js) reads/writes the RAW STRING key
  // 'tracker.rail.mode' (never JSON, never a boolean). Config must write that SAME
  // key/vocabulary, not a parallel 'cr.railOpen' boolean nothing reads.
  // The vocabulary is TRI-state — 'auto' | 'open' | 'collapsed', default 'auto'
  // — and must stay in lockstep with applyRailMode() in ext_cr_board.js. 'auto'
  // defers to the view/breakpoint rules (collapsed in the detail view and on the
  // board at 1025-1279px, open otherwise); 'open'/'collapsed' are an explicit
  // user choice that overrides them. Two-stating it here would silently destroy
  // 'auto' the first time anyone touched this row.
  function readRailPref() {
    try {
      var v = localStorage.getItem('tracker.rail.mode');
      return (v === 'open' || v === 'collapsed') ? v : 'auto';
    } catch (e) { return 'auto'; }
  }
  function writeRailPref(mode) {
    if (mode !== 'open' && mode !== 'collapsed') mode = 'auto';
    try { localStorage.setItem('tracker.rail.mode', mode); } catch (e) {}
    if (_ctx && typeof _ctx.emit === 'function') _ctx.emit('cr:pref', { key: 'tracker.rail.mode', value: mode });
  }

  // Detail-header stat chips (doc 04 capability #21) — live-applied via a dedicated
  // 'cr:statchips' CustomEvent on window, which ext_cr_detail.js listens for to re-render
  // without a reload, the same way writeRailPref emits for the rail's own listener. Both
  // read and write are wrapped in try/catch: localStorage can throw (private windows,
  // blocked site data) and that must never break the dialog. Absent or unreadable => OFF.
  function readStatChipsPref() {
    try { return localStorage.getItem(CFG_PREF_KEYS.statChips) === '1'; } catch (e) { return false; }
  }
  function writeStatChipsPref(on) {
    try { localStorage.setItem(CFG_PREF_KEYS.statChips, on ? '1' : '0'); } catch (e) {}
    window.dispatchEvent(new CustomEvent('cr:statchips', { detail: { on: on } }));
  }

  function cfgRow(label, envVar, sub, control, restart) {
    // `control` may be a single element or an array (e.g. [control, statusBadge()]) --
    // [].concat() flattens either shape into a flat child list without treating a bare
    // DOM node as iterable.
    return h('div', { class: 'cr-cfg-row' }, [
      h('div', { class: 'cr-cfg-row-label' }, [
        h('div', { class: 'cr-cfg-row-name' }, [label, envVar ? h('code', { class: 'cr-envchip' }, [envVar]) : null]),
        h('div', { class: 'cr-cfg-row-sub' }, [
          sub,
          restart ? h('span', { class: 'cr-restart-note' }, [' — takes effect on restart']) : null,
        ]),
      ]),
      h('div', { class: 'cr-cfg-row-control' }, [].concat(control)),
    ]);
  }

  function segmented(options, value, onChange) {
    var wrap = h('div', { class: 'cr-segmented', role: 'radiogroup' });
    options.forEach(function (opt) {
      var btn = h('button', {
        class: 'cr-seg-btn' + (opt[0] === value ? ' is-active' : ''),
        type: 'button', role: 'radio', 'aria-checked': opt[0] === value ? 'true' : 'false', text: opt[1],
      });
      btn.addEventListener('click', function () {
        Array.prototype.forEach.call(wrap.children, function (b) { b.classList.remove('is-active'); b.setAttribute('aria-checked', 'false'); });
        btn.classList.add('is-active'); btn.setAttribute('aria-checked', 'true');
        onChange(opt[0]);
      });
      wrap.appendChild(btn);
    });
    return wrap;
  }

  function toggleCtl(value, onChange) {
    var btn = h('button', { class: 'cr-toggle' + (value ? ' is-on' : ''), type: 'button', role: 'switch', 'aria-checked': value ? 'true' : 'false' }, [h('span', { class: 'cr-toggle-knob' })]);
    btn.addEventListener('click', function () {
      var v = !btn.classList.contains('is-on');
      btn.classList.toggle('is-on', v);
      btn.setAttribute('aria-checked', v ? 'true' : 'false');
      onChange(v);
    });
    return btn;
  }

  function sliderCtl(min, max, value, onChange, suffix) {
    var out = h('span', { class: 'cr-slider-val cr-mono' }, [String(value) + (suffix || '')]);
    var input = h('input', { class: 'cr-slider', type: 'range', min: min, max: max, value: value });
    input.addEventListener('input', function () {
      out.textContent = input.value + (suffix || '');
      onChange(Number(input.value));
    });
    return h('div', { class: 'cr-slider-wrap' }, [input, out]);
  }

  function readonlyField(text) {
    return h('span', { class: 'cr-readonly cr-mono' }, [text]);
  }

  // ---------------------------------------------------------------------------
  // Config dialog: server-backed controls (POST /api/config). This is the ONE
  // exception to this module's own "no fetch()" rule stated at the top of the file —
  // that rule predates a write route existing at all (Fix 2f's own comment below
  // verified there was NO /api/config route when it was written). A dialog that can
  // now WRITE a server setting has to read the value it's editing live too, both to
  // show the real current state on open and to reflect what the server actually
  // accepted after a save (never just echo back what the user typed) -- kept
  // entirely local to renderConfig()/its helpers, every other dialog in this file
  // is still fed purely by its opener's payload.
  // ---------------------------------------------------------------------------

  function fetchServerConfig(cb) {
    fetch('/api/config').then(function (r) { return r.json(); })
      .then(function (d) { cb(d || {}); })
      .catch(function () { cb(null); });
  }

  function postConfigValue(key, value, cb) {
    fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key, value: value }),
    }).then(function (r) { return r.json().then(function (d) { cb(r.ok, d); }); })
      .catch(function (e) { cb(false, { error: String((e && e.message) || e) }); });
  }

  // Tunnel section (aitracker/config.py's "Tunnel management" -- see its module comment for
  // the full design). Three routes, deliberately separate from the config.json ones above:
  // GET /api/tunnel never carries the raw user/pass, only whether each is set -- so a plain
  // dialog-open fetch (same "read live the moment it opens" pattern as fetchServerConfig)
  // can't leak a credential just by happening. The raw value only ever comes back from GET
  // /api/tunnel/reveal, called exactly once per explicit "Show" click (see renderConfig's
  // Tunnel section below) -- never on open, never cached past that click.
  function fetchTunnelPublic(cb) {
    fetch('/api/tunnel').then(function (r) { return r.json(); })
      .then(function (d) { cb(d || null); })
      .catch(function () { cb(null); });
  }

  function fetchTunnelReveal(cb) {
    fetch('/api/tunnel/reveal').then(function (r) { return r.json(); })
      .then(function (d) { cb(d || null); })
      .catch(function () { cb(null); });
  }

  function postTunnelValue(key, value, cb) {
    fetch('/api/tunnel', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key, value: value }),
    }).then(function (r) { return r.json().then(function (d) { cb(r.ok, d); }); })
      .catch(function (e) { cb(false, { error: String((e && e.message) || e) }); });
  }

  // A visible, honest saved/failed state next to the control it belongs to -- mirrors
  // this file's existing Copy/Copied transient-state pattern (see copyBtn above).
  function statusBadge() {
    return h('span', { class: 'cr-cfg-status', 'aria-live': 'polite' });
  }
  function showStatus(el, ok, msg) {
    clearTimeout(el._crStatusT);
    el.textContent = ok ? 'Saved' : ('Failed' + (msg ? ' — ' + msg : ''));
    el.classList.toggle('is-saved', ok);
    el.classList.toggle('is-failed', !ok);
    el._crStatusT = setTimeout(function () {
      el.textContent = '';
      el.classList.remove('is-saved', 'is-failed');
    }, ok ? 1800 : 5000);
  }

  // A slider whose LABEL updates continuously while dragging (so the number tracks the
  // thumb) but whose onCommit only fires once the drag/keystroke is committed ('change') --
  // unlike sliderCtl (used for pure client-side prefs), this one is meant to sit in front
  // of a POST /api/config call and must not fire one per drag tick.
  function sliderCtlCommit(min, max, value, onCommit, suffix) {
    var out = h('span', { class: 'cr-slider-val cr-mono' }, [String(value) + (suffix || '')]);
    var input = h('input', { class: 'cr-slider', type: 'range', min: min, max: max, value: value });
    input.addEventListener('input', function () { out.textContent = input.value + (suffix || ''); });
    input.addEventListener('change', function () { onCommit(Number(input.value)); });
    return h('div', { class: 'cr-slider-wrap' }, [input, out]);
  }

  function textFieldCtl(value, onCommit, opts) {
    opts = opts || {};
    var inp = h('input', {
      class: 'cr-textfield cr-cfg-textfield', type: opts.type || 'text',
      min: opts.min != null ? opts.min : null, max: opts.max != null ? opts.max : null,
    });
    inp.value = value == null ? '' : String(value);
    inp.addEventListener('change', function () {
      onCommit(opts.type === 'number' ? Number(inp.value) : inp.value);
    });
    return inp;
  }

  function textareaCtl(value, onCommit, placeholder) {
    var ta = h('textarea', { class: 'cr-textfield cr-cfg-textarea cr-mono', rows: 4, placeholder: placeholder || '' });
    ta.value = value || '';
    ta.addEventListener('change', function () { onCommit(ta.value); });
    return ta;
  }

  // Config's payload contract (documented in the handoff report): the caller (bootstrap)
  // supplies `payload.server` with values it already had lying around (GET /api/term/list's
  // maxTerms/terminalEnabled) — used here ONLY as an instant, no-flash first paint. The
  // real, current, WRITABLE state for every config.json-backed row comes from GET
  // /api/config, fetched the moment this dialog opens (see the "one exception to no
  // fetch()" note above fetchServerConfig) and merged over the payload defaults the instant
  // it lands — `srv` below is reassigned in place, never a fresh object, so closures that
  // already captured it keep seeing the latest merge.
  function renderConfig(payload) {
    var srv = (payload && payload.server) || {};
    // Header subtitle: 5c gives Config the real server address (its mock shows
    // "localhost:8790") — not "ai-tracker". The honest source for that on THIS page
    // is the page's own location, not a guessed/invented config field or a request:
    // this dialog is always served BY the tracker it's showing settings for, so
    // location.host already IS that address.
    var subtitle = (window.location && window.location.host) || '';
    var chrome = buildChrome('config', 'Config', '⚙️', subtitle, true);
    chrome.panel.classList.add('cr-dialog-config');

    var sections = ['Interface', 'Board', 'Terminal', 'Notifications', 'Server', 'Tunnel', 'Data files'];
    var nav = h('div', { class: 'cr-cfg-nav' });
    var body = h('div', { class: 'cr-cfg-body' });
    var active = 'Interface';
    // Tunnel section's own state -- local to THIS renderConfig() call, so it starts fresh
    // every time the dialog opens. `tunnel` is the masked snapshot (GET /api/tunnel);
    // `tunnelRevealed` is null until "Show" is clicked and is never written back to
    // anything that outlives this dialog instance -- closing/reopening always starts
    // masked again, satisfying "the revealed value must not persist across dialog
    // close/reopen" (the security requirement this feature was built under).
    var tunnel = {};
    var tunnelRevealed = null;

    // A generic editable row for a server config.json key: renders whatever `ctlFn(value,
    // onCommit)` builds, POSTs on commit, shows an honest Saved/Failed badge, and rolls the
    // control back to the server's last-known-good value on failure (never leaves the UI
    // showing a value the server rejected as if it had been accepted).
    function serverRow(label, key, sub, ctlFn) {
      var meta = srv.cfg && srv.cfg[key];
      var value = meta ? meta.value : undefined;
      var status = statusBadge();
      var restart = (meta && meta.restart) || false;
      var ctl = ctlFn(value, function (newVal) {
        postConfigValue(key, newVal, function (ok, resp) {
          if (ok) {
            if (srv.cfg && srv.cfg[key]) srv.cfg[key].value = resp.value;
            showStatus(status, true);
          } else {
            showStatus(status, false, (resp && resp.error) || 'request failed');
            renderSection();   // snap every control in this section back to last-known-good
          }
        });
      });
      return cfgRow(label, _ENVCHIP[key] || null, sub, [ctl, status], restart);
    }

    function renderSection() {
      body.innerHTML = '';
      Array.prototype.forEach.call(nav.children, function (b) { b.classList.toggle('is-active', b.textContent === active); });
      if (active === 'Interface') {
        var themeVal = (_ctx && _ctx.theme && _ctx.theme.get) ? _ctx.theme.get() : 'auto';
        body.appendChild(cfgRow('Theme', null, 'Follows prefers-color-scheme unless overridden.',
          segmented([['auto', 'Auto'], ['light', 'Light'], ['dark', 'Dark']], themeVal, function (v) {
            if (_ctx && _ctx.theme && _ctx.theme.set) _ctx.theme.set(v);
          })));
        // Tri-state, drawn with the same `segmented` control as Theme above: a
        // two-state switch cannot express 'auto' and would collapse it away on
        // first touch, leaving no way back to the default.
        body.appendChild(cfgRow('Session rail', null, 'Auto collapses it inside a session and on narrow screens; Open and Collapsed override that.',
          segmented([['auto', 'Auto'], ['open', 'Open'], ['collapsed', 'Collapsed']], readRailPref(), function (v) { writeRailPref(v); })));
        body.appendChild(cfgRow('Cards start folded', null, 'Every detail-view panel starts collapsed except Conversation.',
          toggleCtl(readPref(CFG_PREF_KEYS.cardsFolded, true), function (v) { writePref(CFG_PREF_KEYS.cardsFolded, v); })));
        // Doc 04 capability #21, restored opt-in / default OFF — see the CFG_PREF_KEYS.statChips
        // comment above for the fixed key/value/event contract this row writes to.
        body.appendChild(cfgRow('Session stat chips', null, 'Shows a row of quick stats — files, commands, reads, commits, tests, tokens, branch — at the top of the session detail header. Off by default.',
          toggleCtl(readStatChipsPref(), function (v) { writeStatChipsPref(v); })));
        // Fix (drift 4): 5c draws this as ONE row — "Desktop notifications + sound" —
        // not two separate toggles. Combined here, but both underlying preferences
        // still get set on every flip: `desktopNotif` (this dialog's own pref, read by
        // the permission-nudge logic) AND the REAL sound switch. That real switch is
        // `soundOn`/`toggleSound()` (app.js globals, same `soundOff` localStorage key
        // the classic bell and ext_cr_boot.js's `toggle:notifications` handler already
        // share) -- NOT the disconnected `cr.notif.sound` pref this row used to write
        // only to itself, which nothing else ever read. That was a real gap, not a
        // deliberate second source of truth: fixed by routing through the same global
        // toggleSound() so this control now drives the one real sound switch the rest
        // of the app already has, instead of a shadow copy of it.
        body.appendChild(cfgRow('Desktop notifications + sound', null, 'Only while the tab is in the background.',
          toggleCtl(
            (typeof soundOn !== 'undefined') ? soundOn : readPref(CFG_PREF_KEYS.sound, true),
            function (v) {
              writePref(CFG_PREF_KEYS.desktopNotif, v);
              writePref(CFG_PREF_KEYS.sound, v);
              if (typeof soundOn !== 'undefined' && soundOn !== v && typeof toggleSound === 'function') toggleSound();
            }
          )));
      } else if (active === 'Board') {
        // The owner's decision: a 3–8 slider (not 04's original 3–12 spec) — 3–8 never
        // exceeds the handoff README's "board never renders more than 8 tiles" cap, so
        // both docs are satisfied. Client-side preference ONLY (localStorage, NOT
        // config.json) — ext_cr_board.js reads this same key and clamps to 3..8 itself.
        body.appendChild(cfgRow('Board tiles', null, 'How many session tiles the board shows before "+N more" — never more than 8 (handoff README decision 2).',
          sliderCtl(3, 8, readPref(CFG_PREF_KEYS.boardTiles, 8), function (v) { writePref(CFG_PREF_KEYS.boardTiles, v); })));
        // Fix 2b — this is the SAME poll() /api/session timer app.js's track() already
        // runs (2s by default, and the project's hard rule keeps that the default) —
        // ext_cr_boot.js re-arms that one timer at the chosen cadence instead of adding a
        // second loop. It does not touch the separate 5s /api/list (board/rail) poll.
        body.appendChild(cfgRow('Poll interval', null, 'How often the open session’s detail view re-polls the server. (The board/rail list poll stays fixed at 5s.)',
          segmented([[1000, '1s'], [2000, '2s'], [5000, '5s']], readPref(CFG_PREF_KEYS.pollMs, 2000), function (v) { writePref(CFG_PREF_KEYS.pollMs, v); })));
        body.appendChild(serverRow('Live window', 'LIVE_WINDOW',
          'How long a session with no new activity still counts as "live" before it shows as done.',
          function (value, onCommit) {
            return sliderCtlCommit(30, 1800, value != null ? value : 300, onCommit, 's');
          }));
      } else if (active === 'Terminal') {
        body.appendChild(serverRow('Terminal renderer', 'TERM_RENDERER',
          'Default for newly-opened terminals — already switchable live per-terminal from its own toolbar.',
          function (value, onCommit) {
            return segmented([['xterm', 'xterm'], ['grid', 'grid']], value || 'xterm', onCommit);
          }));
        body.appendChild(serverRow('Max terminals', 'MAX_TERMS', 'Clamped to 1–64.',
          function (value, onCommit) {
            return sliderCtlCommit(1, 64, value != null ? value : 12, onCommit, '');
          }));
        body.appendChild(serverRow('Terminal enabled', 'TERMINAL',
          'The kill-switch. ON means the tracker can start real shell processes on this machine, not just read logs — turn it OFF if you only want the read-only dashboard.',
          function (value, onCommit) {
            return toggleCtl(value !== false, onCommit);
          }));
        body.appendChild(serverRow('External terminal app', 'TERM_APP', 'Terminal or iTerm, for the ↗ external-terminal buttons.',
          function (value, onCommit) {
            return segmented([['Terminal', 'Terminal'], ['iTerm', 'iTerm']], value || 'Terminal', onCommit);
          }));
        body.appendChild(serverRow('Command allowlist', 'TERM_ALLOW',
          'One argv prefix per line; replaces the default set outright. Leave empty to use the built-in default set.',
          function (value, onCommit) {
            return textareaCtl(value || '', function (text) { onCommit(text); }, 'default set (leave empty)');
          }));
      } else if (active === 'Notifications') {
        // Fix (drift 4): this tab used to carry its own second copy of the two toggles
        // now combined into the Interface tab's single "Desktop notifications + sound"
        // row -- a real, functioning duplicate control, not just repeated copy. Removed
        // rather than mirrored; the tab itself stays (5c's own Config nav still lists
        // it) since nothing here calls for deleting the nav entry, only the duplication.
        body.appendChild(h('p', { class: 'cr-help-note' }, [
          'Desktop notifications + sound now lives on the Interface tab — one row, one setting.',
        ]));
      } else if (active === 'Server') {
        body.appendChild(cfgRow('Auth', 'TRACKER_AUTH',
          'Never displayed — only whether it is set. Env-only, deliberately not editable here: writing a password typed into a browser into a plaintext file on a server that may be tunneled is a real security regression, not a convenience. Set TRACKER_AUTH and restart to change it.',
          readonlyField(srv.authSet ? 'set' : 'not set'), true));
        // Doc 04 (§ Config → Server) specs Port/Host as "mono fields, read-only display" —
        // no POST /api/config path for either. Rebinding a live listening socket's bind
        // host/port from a dashboard field is a write surface the spec never sanctioned,
        // so these render via the same readonlyField() helper the Auth row above uses,
        // never textFieldCtl()/serverRow() (which would wire them to postConfigValue()).
        body.appendChild(cfgRow('Port', 'PORT', 'Rebinding a live listening socket isn’t attempted — this reflects what the server is running with now.',
          readonlyField(String((srv.cfg && srv.cfg.PORT && srv.cfg.PORT.value != null) ? srv.cfg.PORT.value : 8790))));
        body.appendChild(cfgRow('Host', 'HOST', 'Same as Port — read-only.',
          readonlyField(String((srv.cfg && srv.cfg.HOST && srv.cfg.HOST.value) || '127.0.0.1'))));
      } else if (active === 'Tunnel') {
        // The one-line, always-visible disclosure the security review this feature was
        // built under calls for: never hidden behind the reveal action, never a lecture.
        body.appendChild(h('p', { class: 'cr-help-note cr-tunnel-disclosure' }, [
          'Stored in plain text on this machine (', h('code', {}, ['config.json']),
          ', permissions locked to you only) — the share URL below carries it too. Treat both like a password.',
        ]));

        body.appendChild(cfgRow('Tunnel URL', null,
          'Not discoverable from here — a Cloudflare quick tunnel (`make tunnel`) mints a new address every run. Paste the one it printed.',
          (function () {
            var status = statusBadge();
            var ctl = textFieldCtl(tunnel.url || '', function (v) {
              postTunnelValue('TUNNEL_URL', v, function (ok, resp) {
                if (ok) { tunnel.url = resp.value; if (tunnelRevealed) tunnelRevealed = null; showStatus(status, true); renderSection(); }
                else { showStatus(status, false, (resp && resp.error) || 'request failed'); renderSection(); }
              });
            }, { type: 'text' });
            ctl.classList.add('cr-cfg-textfield-wide');
            return [ctl, status];
          })()));

        var shown = !!tunnelRevealed;
        function maskedRow(label, key, sub) {
          var setFlag = key === 'user' ? tunnel.user_set : tunnel.pass_set;
          if (!shown) {
            return cfgRow(label, null, sub, readonlyField(setFlag ? '••••••••' : 'not set'), true);
          }
          var status = statusBadge();
          var ctl = textFieldCtl(tunnelRevealed[key] || '', function (v) {
            postTunnelValue(key === 'user' ? 'TUNNEL_USER' : 'TUNNEL_PASS', v, function (ok, resp) {
              if (ok) {
                tunnelRevealed[key] = v;
                if (key === 'user') tunnel.user_set = !!v; else tunnel.pass_set = !!v;
                // the restart command / share URL below embed this value -- keep them
                // in sync with what was just saved, not the pre-edit reveal snapshot.
                tunnelRevealed.restart_cmd = (resp && resp.restart_cmd) || tunnelRevealed.restart_cmd;
                showStatus(status, true, 'restart required to apply');
                renderSection();
              } else {
                showStatus(status, false, (resp && resp.error) || 'request failed');
              }
            });
          }, { type: 'text' });
          return cfgRow(label, null, sub, [ctl, status], true);
        }
        body.appendChild(maskedRow('Username', 'user', 'Same credential as TRACKER_AUTH — masked until you click Show.'));
        body.appendChild(maskedRow('Password', 'pass', 'Editing here only stages the value — it takes effect once you restart with the command below.'));

        var showBtn = h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: shown ? 'Hide' : 'Show' });
        showBtn.addEventListener('click', function () {
          if (tunnelRevealed) { tunnelRevealed = null; renderSection(); return; }
          fetchTunnelReveal(function (rev) {
            if (!rev) return;
            tunnelRevealed = rev;
            renderSection();
          });
        });
        body.appendChild(h('div', { class: 'cr-tunnel-showrow' }, [showBtn]));

        // Both blocks below embed the raw credential (the restart command needs it to be
        // useful; the share URL IS it, in userinfo form) -- gated behind the SAME reveal
        // action as the fields above, never computed or shown before "Show" is clicked.
        if (tunnelRevealed) {
          body.appendChild(h('div', { class: 'cr-tunnel-block' }, [
            h('div', { class: 'cr-tunnel-block-label' }, ['Restart command — required for a new username/password to take effect']),
            h('div', { class: 'cr-tunnel-cmdrow' }, [
              h('code', { class: 'cr-mono cr-tunnel-cmd' }, [tunnelRevealed.restart_cmd || '']),
              copyBtn(function () { return tunnelRevealed.restart_cmd || ''; }),
            ]),
            h('div', { class: 'cr-tunnel-block-note' }, [
              'Started the server directly instead of via ', h('code', {}, ['make tunnel']), '? The equivalent is ',
              h('code', {}, ['TRACKER_AUTH="user:pass" python3 -m aitracker']), '.',
            ]),
          ]));
          body.appendChild(h('div', { class: 'cr-tunnel-block' }, [
            h('div', { class: 'cr-tunnel-block-label' }, ['Share URL — for your own notes; the credential rides in the URL’s user:pass@host form, never a query string']),
            h('div', { class: 'cr-tunnel-cmdrow' }, [
              h('code', { class: 'cr-mono cr-tunnel-cmd' }, [tunnelRevealed.share_url || '(set a Tunnel URL above first)']),
              copyBtn(function () { return tunnelRevealed.share_url || ''; }),
            ]),
          ]));
        }
      } else if (active === 'Data files') {
        var df = srv.dataFiles || {};
        ['flags', 'titles', 'pins', 'notes'].forEach(function (k) {
          body.appendChild(cfgRow(k[0].toUpperCase() + k.slice(1), null, 'Read live — edits outside the app are picked up on the next poll.',
            readonlyField(df[k] || (k + '.json'))));
        });
      }
    }
    sections.forEach(function (s) {
      var btn = h('button', { class: 'cr-cfg-nav-btn' + (s === active ? ' is-active' : ''), type: 'button', text: s });
      btn.addEventListener('click', function () { active = s; renderSection(); });
      nav.appendChild(btn);
    });
    renderSection();

    // The live read: merges GET /api/config's per-key {value, overridden, restart} onto
    // `srv.cfg` and re-renders whichever section is showing once it lands. A failed fetch
    // (offline, a 401 race) leaves `srv.cfg` unset -- serverRow's controls then render with
    // `value` undefined, which every ctlFn above already treats as "use the built-in
    // default", same honest degrade this dialog already used before this feature existed.
    fetchServerConfig(function (cfg) {
      if (!cfg) return;
      srv.cfg = cfg;
      srv.authSet = !!cfg.AUTH_SET;
      renderSection();
    });
    // Tunnel section's own live read -- see fetchTunnelPublic's comment for why this is
    // the masked snapshot only, never the raw credential.
    fetchTunnelPublic(function (t) {
      if (!t) return;
      tunnel = t;
      if (active === 'Tunnel') renderSection();
    });

    var main = h('div', { class: 'cr-cfg-main' }, [nav, body]);
    chrome.body.appendChild(main);
    chrome.body.appendChild(h('div', { class: 'cr-cfg-footer' }, [
      // Rows without an env-var chip are plain browser preferences — saved to this browser
      // the moment you change them. Rows WITH an env-var chip are now REAL server settings
      // (config.json > env var > built-in default — see config.py): a change here saves
      // immediately and, for everything except Port/Host, applies live, no restart. Auth
      // stays the one exception — env-only, never writable from here (see its own row).
      h('p', { class: 'cr-cfg-footer-note' }, [
        'Rows without an env-var chip are plain browser preferences — saved to this browser the moment you change them. Rows with an env-var chip are real server settings: saving writes ',
        h('code', {}, ['config.json']),
        ' and applies immediately — except Port and Host, which only take effect on the next ',
        h('code', {}, ['make serve']),
        '. The Server tab’s Auth row stays env-only and is never writable from here — the Tunnel tab is the one deliberate exception, since it edits that same credential and always requires a restart to take effect (see its own disclosure line).',
      ]),
      h('div', { class: 'cr-cfg-actions' }, [
        h('button', {
          // "Reset to defaults" clears only the browser preferences it always has (there is
          // no bulk-clear route for server keys — each is reset individually via its own
          // control if you dial it back to the built-in value shown when unoverridden).
          class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Reset to defaults', onclick: function () {
            Object.keys(CFG_PREF_KEYS).forEach(function (k) { var key = CFG_PREF_KEYS[k]; if (key) { try { localStorage.removeItem(key); } catch (e) {} } });
            renderSection();
          },
        }),
        h('button', { class: 'cr-btn cr-btn-solid', type: 'button', text: 'Apply', onclick: close }),
      ]),
    ]));
    return { backdrop: chrome.backdrop, panel: chrome.panel };
  }

  // ---------------------------------------------------------------------------
  // File-diff / command-output / narration-text pop-out (one component, three modes)
  // ---------------------------------------------------------------------------

  function diffLineRow(line) {
    var cls = 'cr-diffline';
    var prefix = ' ';
    if (line.type === 'add') { cls += ' is-add'; prefix = '+'; }
    else if (line.type === 'del') { cls += ' is-del'; prefix = '−'; }
    return h('div', { class: cls }, [
      h('span', { class: 'cr-diffline-no' }, [line.no != null ? String(line.no) : '']),
      h('span', { class: 'cr-diffline-prefix' }, [prefix]),
      h('span', { class: 'cr-diffline-text' }, [line.text || '']),
    ]);
  }

  function renderDiffPopout(payload) {
    payload = payload || {};
    var mode = payload.mode || 'diff'; // 'diff' | 'output' | 'text'
    var title = mode === 'diff' ? (payload.path || 'diff') : mode === 'output' ? (payload.title || 'output') : (payload.title || 'narration');
    var chrome = buildChrome('diff', title, null, payload.contextStr || '', true);
    chrome.panel.classList.add('cr-dialog-popout');

    var toolbar = h('div', { class: 'cr-popout-toolbar' });
    if (mode === 'diff') {
      var base = (payload.path || '').split('/');
      toolbar.appendChild(h('span', { class: 'cr-popout-path cr-mono' }, [
        base.slice(0, -1).join('/') + (base.length > 1 ? '/' : ''), h('strong', {}, [base[base.length - 1] || '']),
      ]));
      toolbar.appendChild(h('span', { class: 'cr-popout-stat cr-mono cr-plus' }, ['+' + (payload.additions || 0)]));
      toolbar.appendChild(h('span', { class: 'cr-popout-stat cr-mono cr-minus' }, ['−' + (payload.deletions || 0)]));
    }
    var viewMode = 'diff'; // vs 'rendered'
    var body = h('div', { class: 'cr-popout-body cr-mono' });
    function paintBody() {
      body.innerHTML = '';
      if (mode === 'diff' && viewMode === 'diff') {
        if (payload.expandAboveLabel !== false) {
          body.appendChild(h('div', { class: 'cr-context-bar', onclick: function () { if (payload.onExpandAbove) payload.onExpandAbove(); } }, ['↑ expand ' + (payload.aboveCount || 0) + ' lines above']));
        }
        (payload.lines || []).forEach(function (l) { body.appendChild(diffLineRow(l)); });
        if (payload.belowCount) {
          body.appendChild(h('div', { class: 'cr-context-bar', onclick: function () { if (payload.onExpandBelow) payload.onExpandBelow(); } }, ['↓ expand ' + payload.belowCount + ' lines below']));
        }
      } else if (mode === 'diff' && viewMode === 'rendered') {
        // NOTE: "Rendered" needs the shared markdown renderer (capability 31, owned by
        // the detail module) to be faithful for a .md file's diff. Absent that shared
        // seam on ctx today, this falls back to mdLite() — flagged as REQUIRED ADDITION.
        var pre = h('div', { class: 'cr-rendered-md' });
        pre.innerHTML = mdLite((payload.lines || []).map(function (l) { return l.text; }).join('\n'));
        body.appendChild(pre);
      } else if (mode === 'output') {
        var pre2 = h('pre', { class: 'cr-outputtext' }, [payload.text || '']);
        body.appendChild(pre2);
      } else {
        var textWrap = h('div', { class: 'cr-rendered-md' });
        textWrap.innerHTML = mdLite(payload.text || '');
        body.appendChild(textWrap);
      }
    }
    if (mode === 'diff') {
      toolbar.appendChild(segmented([['diff', 'Diff'], ['rendered', 'Rendered']], viewMode, function (v) { viewMode = v; paintBody(); }));
    }
    toolbar.appendChild(h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Expand all', onclick: function () { if (payload.onExpandAll) payload.onExpandAll(); } }));
    toolbar.appendChild(h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'New tab', onclick: function () {
      if (payload.onNewTab) { payload.onNewTab(); return; }
      var w = window.open('', '_blank');
      if (w) { w.document.title = title; w.document.body.style.cssText = 'font-family:monospace;white-space:pre-wrap;padding:16px'; w.document.body.textContent = payload.text || (payload.lines || []).map(function (l) { return l.text; }).join('\n'); }
    } }));
    if (payload.index != null && payload.total != null) {
      toolbar.appendChild(h('span', { class: 'cr-popout-nav cr-mono' }, [
        h('button', { class: 'cr-navbtn', type: 'button', 'aria-label': 'Previous', onclick: function () { if (payload.onPrev) payload.onPrev(); } }, [icon('chevron', 'cr-rot-180')]),
        '‹ ' + payload.index + ' of ' + payload.total + ' ›',
        h('button', { class: 'cr-navbtn', type: 'button', 'aria-label': 'Next', onclick: function () { if (payload.onNext) payload.onNext(); } }, [icon('chevron')]),
      ]));
    }
    chrome.body.appendChild(toolbar);
    chrome.body.appendChild(body);
    paintBody();
    return { backdrop: chrome.backdrop, panel: chrome.panel };
  }

  // ---------------------------------------------------------------------------
  // Narration pop-out with a rendered diagram
  // ---------------------------------------------------------------------------

  // payload: {time, nodes:[{label, active}], edges:[[fromIdx,toIdx]], family, onPrev, onNext, onLatest}
  function renderNarrationDiagram(payload) {
    payload = payload || {};
    var chrome = buildChrome('narration-diagram', (payload.time || '') + ' · narration', null, '', true);
    chrome.panel.classList.add('cr-dialog-popout');
    var toolbar = h('div', { class: 'cr-popout-toolbar' }, [
      h('button', { class: 'cr-navbtn', type: 'button', 'aria-label': 'Previous', onclick: function () { if (payload.onPrev) payload.onPrev(); } }, [icon('chevron', 'cr-rot-180')]),
      h('button', { class: 'cr-navbtn', type: 'button', 'aria-label': 'Next', onclick: function () { if (payload.onNext) payload.onNext(); } }, [icon('chevron')]),
      h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Jump to latest', onclick: function () { if (payload.onLatest) payload.onLatest(); } }),
    ]);
    var card = h('div', { class: 'cr-diagram-card' });
    var nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    // Fix 4: a missing/short `nodes` array degrades to an honest empty state instead of
    // an empty (and confusing-looking) diagram card — nothing here can throw either way,
    // since a node missing `.label` already renders as a blank pill (h()'s child-append
    // skips a null/undefined child), but zero nodes deserves a real message.
    if (!nodes.length) {
      card.appendChild(emptyState({ title: 'No narration steps to diagram', body: 'This entry has nothing to draw yet.' }));
    } else {
      var row = h('div', { class: 'cr-diagram-row' });
      nodes.forEach(function (n) {
        n = n || {};
        row.appendChild(h('span', { class: 'cr-diagram-pill' + (n.active ? ' is-active' : '') }, [n.label || '']));
      });
      card.appendChild(row);
    }
    var caption = h('div', { class: 'cr-diagram-caption' }, [
      (payload.family || 'stateDiagram-v2') + ' · drawn locally in plain SVG, no mermaid.js',
    ]);
    chrome.body.appendChild(toolbar);
    chrome.body.appendChild(card);
    chrome.body.appendChild(h('div', { class: 'cr-divider' }));
    chrome.body.appendChild(caption);
    return { backdrop: chrome.backdrop, panel: chrome.panel };
  }

  // ---------------------------------------------------------------------------
  // Cross-session flag list
  // ---------------------------------------------------------------------------

  // payload: {flags:[{id, session, sessionTitle, text, resolved}], onOpen, onResolve, onReopen, onDelete}
  function renderFlagsList(payload) {
    payload = payload || {};
    var chrome = buildChrome('flags', 'Flags', '🚩', (payload.flags || []).length + ' total', false, 'tn-emo-f');
    var list = h('div', { class: 'cr-flag-list' });
    function paint() {
      list.innerHTML = '';
      var flags = payload.flags || [];
      if (!flags.length) { list.appendChild(emptyState({ title: 'No flags raised', body: 'Flag anything from a session’s header to see it here.' })); return; }
      flags.forEach(function (f) {
        var row = h('div', { class: 'cr-flag-row' + (f.resolved ? ' is-resolved' : '') }, [
          h('button', { class: 'cr-flag-session', type: 'button', onclick: function () { if (payload.onOpen) payload.onOpen(f); } }, [f.sessionTitle || f.session]),
          h('div', { class: 'cr-flag-text' }, [f.text]),
          h('div', { class: 'cr-flag-actions' }, [
            f.resolved
              ? h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Reopen', onclick: function () { if (payload.onReopen) payload.onReopen(f); paint(); } })
              : h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Resolve', onclick: function () { if (payload.onResolve) payload.onResolve(f); paint(); } }),
            h('button', { class: 'cr-btn cr-btn-quiet cr-btn-danger', type: 'button', text: 'Delete', onclick: function () { if (payload.onDelete) payload.onDelete(f); paint(); } }),
          ]),
        ]);
        list.appendChild(row);
      });
    }
    paint();
    chrome.body.appendChild(list);
    return { backdrop: chrome.backdrop, panel: chrome.panel, update: function (state) { if (state && state.flags) { payload.flags = state.flags; paint(); } } };
  }

  // ---------------------------------------------------------------------------
  // Manage terminals / terminals-at-the-cap (doc 04's "Terminals at the cap" spec)
  //
  // Ground truth: cr_term.js's real "☰ Manage terminals" button and its cap-hit
  // path both call `ctx.dialog("manage-terminals", {...})` — NOT the "terminals-
  // cap" name this file originally guessed from the doc's section title alone.
  // It calls with the RAW `/api/term/list` shape ({tty, cmd, cwd, started,
  // session, mode} per row, config.py/term_vt.py), not the {title, project, age}
  // shape this file assumed — so title/project/age are derived here instead.
  // It's also opened multiple times in a row (loading -> data, or -> error) for
  // the SAME name, which open()'s same-name update path (above) now folds into
  // one dialog rather than stacking duplicates.
  // ---------------------------------------------------------------------------

  function timeAgo(unixSeconds) {
    if (!unixSeconds) return '';
    var s = Math.max(0, Math.floor(Date.now() / 1000 - unixSeconds));
    if (s < 60) return s + 's';
    var m = Math.floor(s / 60);
    if (m < 60) return m + 'm';
    var hr = Math.floor(m / 60);
    if (hr < 24) return hr + 'h';
    return Math.floor(hr / 24) + 'd';
  }
  function cwdTail(cwd) {
    if (!cwd) return '';
    var parts = String(cwd).replace(/\/+$/, '').split('/');
    return parts[parts.length - 1] || String(cwd);
  }

  // payload: {terminals:[{tty,cmd,cwd,started,session,mode}], max, onPeek(t), onKill(t), onCloseAll(), error}
  function renderManageTerminals(payload) {
    payload = payload || {};
    var chrome = buildChrome('manage-terminals', 'Manage terminals', null, '', false);
    var titleEl = chrome.panel.querySelector('.cr-dialog-title');
    function paint() {
      chrome.body.innerHTML = '';
      if (payload.error) {
        chrome.body.appendChild(errorState({ title: "Couldn't list terminals", body: payload.error }));
        return;
      }
      var terms = payload.terminals || [];
      var max = payload.max || terms.length;
      var atCap = !!(max && terms.length >= max);
      chrome.panel.classList.toggle('cr-dialog-cap', atCap);
      titleEl.textContent = atCap
        ? (terms.length + ' of ' + max + ' running — free a slot')
        : ('Manage terminals — ' + terms.length + ' of ' + max + ' running');
      if (!terms.length) {
        chrome.body.appendChild(emptyState({ title: 'No terminals running', body: 'Open one from the top bar’s + New terminal / + New Claude session.' }));
        return;
      }
      var list = h('div', { class: 'cr-termcap-list' });
      terms.forEach(function (t) {
        list.appendChild(h('div', { class: 'cr-termcap-row' }, [
          h('div', {}, [
            h('div', { class: 'cr-termcap-title' }, [t.title || t.session || cwdTail(t.cwd) || t.tty]),
            h('div', { class: 'cr-termcap-meta cr-mono' }, [cwdTail(t.cwd) + ' · ' + timeAgo(t.started)]),
          ]),
          h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'peek', onclick: function () { if (payload.onPeek) payload.onPeek(t); } }),
          h('button', { class: 'cr-btn cr-btn-quiet cr-btn-danger', type: 'button', text: '✕ kill', onclick: function () { if (payload.onKill) payload.onKill(t); } }),
        ]));
      });
      chrome.body.appendChild(list);
      var confirmRow = h('div', { class: 'cr-inline-confirm', hidden: true }, [
        h('span', {}, ['Kill every running terminal? This cannot be undone.']),
        h('button', { class: 'cr-btn cr-btn-solid cr-btn-danger', type: 'button', text: 'Close all', onclick: function () { if (payload.onCloseAll) payload.onCloseAll(); } }),
        h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Cancel', onclick: function () { confirmRow.hidden = true; closeAllBtn.hidden = false; } }),
      ]);
      var closeAllBtn = h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Close all', onclick: function () { closeAllBtn.hidden = true; confirmRow.hidden = false; } });
      chrome.body.appendChild(h('div', { class: 'cr-cfg-footer' }, [
        h('p', { class: 'cr-cfg-footer-note' }, ['Closing this dialog detaches; ✕ kills.']),
        closeAllBtn,
        confirmRow,
      ]));
    }
    paint();
    return { backdrop: chrome.backdrop, panel: chrome.panel, update: function (p) { payload = p || {}; paint(); } };
  }

  // ---------------------------------------------------------------------------
  // Directory picker — cr_term.js's "+ New terminal" / "+ New Claude session".
  // Opened first with {loading:true}, then again with {cwds, note} once GET
  // /api/term/cwds resolves — folded via the same-name update path.
  // payload: {mode, title, loading, cwds:[path,...], note, onPick(path)}
  // ---------------------------------------------------------------------------

  function renderDirectoryPicker(payload) {
    payload = payload || {};
    var chrome = buildChrome('directory-picker', payload.title || 'Choose a directory', null, '', false);
    var titleEl = chrome.panel.querySelector('.cr-dialog-title');
    function paint() {
      titleEl.textContent = payload.title || 'Choose a directory';
      chrome.body.innerHTML = '';
      if (payload.loading) chrome.body.appendChild(emptyState({ title: 'Loading recent directories…', body: '' }));
      if (payload.note) chrome.body.appendChild(h('p', { class: 'cr-help-note' }, [payload.note]));
      var cwds = payload.cwds || [];
      if (cwds.length) {
        var list = h('div', { class: 'cr-flag-list' });
        cwds.forEach(function (p) {
          list.appendChild(h('button', {
            class: 'cr-btn cr-btn-quiet cr-fullrow', type: 'button', text: p,
            onclick: function () { if (payload.onPick) payload.onPick(p); close(); },
          }));
        });
        chrome.body.appendChild(list);
      }
      var input = h('input', { class: 'cr-textfield', type: 'text', placeholder: '/path/to/project' });
      var go = h('button', {
        class: 'cr-btn cr-btn-solid', type: 'button', text: 'Start',
        onclick: function () { if (input.value.trim() && payload.onPick) payload.onPick(input.value.trim()); close(); },
      });
      chrome.body.appendChild(h('div', { class: 'cr-textfield-row' }, [input, go]));
    }
    paint();
    return { backdrop: chrome.backdrop, panel: chrome.panel, update: function (p) { payload = p || {}; paint(); } };
  }

  // ---------------------------------------------------------------------------
  // Model / effort switchers (capability #55).
  //
  // Two call shapes exist in the sibling modules today: cr_term.js's own toolbar
  // calls `ctx.dialog("model"|"effort", {current, ladder, onPick})` — everything
  // this dialog needs. cr_detail.js's Evidence-panel mirror calls
  // `ctx.dialog("modelSwitcher"|"effortPicker", {sessionId})` — no ladder, no
  // onPick, because picking a model/effort means POSTing /api/term/inject, which
  // only cr_term.js is wired to do. Per "NO FETCHING", this dialog cannot make
  // that call itself, so the sessionId-only shape falls back to emitting
  // 'cr:model-pick' / 'cr:effort-pick' on the bus — see REQUIRED ADDITION in the
  // report: something needs to listen and perform the actual inject.
  // ---------------------------------------------------------------------------

  var DEFAULT_EFFORT_LADDER = ['low', 'medium', 'high', 'xhigh', 'max']; // README.md:95 — the CLI's own set

  function renderLadderPicker(kind) {
    return function (payload) {
      payload = payload || {};
      var ladder = payload.ladder || (kind === 'effort' ? DEFAULT_EFFORT_LADDER : null);
      var chrome = buildChrome(kind, kind === 'effort' ? 'Effort' : 'Model', null, payload.current || '', false);
      function pick(val) {
        if (payload.onPick) { payload.onPick(val); close(); return; }
        if (_ctx && typeof _ctx.emit === 'function') {
          _ctx.emit(kind === 'effort' ? 'cr:effort-pick' : 'cr:model-pick', { sessionId: payload.sessionId, value: val });
        }
        close();
      }
      if (ladder) {
        var list = h('div', { class: 'cr-flag-list' });
        ladder.forEach(function (v) {
          list.appendChild(h('button', {
            class: 'cr-btn cr-fullrow' + (v === payload.current ? ' cr-btn-solid' : ' cr-btn-quiet'),
            type: 'button', text: v, onclick: function () { pick(v); },
          }));
        });
        chrome.body.appendChild(list);
      } else {
        var input = h('input', { class: 'cr-textfield', type: 'text', placeholder: 'model name' });
        chrome.body.appendChild(h('div', { class: 'cr-textfield-row' }, [
          input,
          h('button', { class: 'cr-btn cr-btn-solid', type: 'button', text: 'Switch', onclick: function () { if (input.value.trim()) pick(input.value.trim()); } }),
        ]));
        chrome.body.appendChild(h('p', { class: 'cr-help-note' }, ['No fixed model list is known client-side — type the exact name /model accepts.']));
      }
      return { backdrop: chrome.backdrop, panel: chrome.panel };
    };
  }

  // ---------------------------------------------------------------------------
  // Fork lineage (capability #52) — cr_term.js's real payload: {sid, continuedAs,
  // continuedFrom, onOpen(targetSid)}, read off the shared session-detail dict's
  // continued_as/continued_from fields (registry.py — every provider).
  // ---------------------------------------------------------------------------

  function renderForkLineage(payload) {
    payload = payload || {};
    var chrome = buildChrome('fork-lineage', 'Fork lineage', '🔀', payload.sid || '', false);
    var body = chrome.body;
    function linkRow(label, targetSid) {
      body.appendChild(h('p', {}, [
        label + ' ',
        h('button', { class: 'cr-link cr-linklike', type: 'button', text: targetSid, onclick: function () { if (payload.onOpen) payload.onOpen(targetSid); close(); } }),
        '.',
      ]));
    }
    if (payload.continuedAs) linkRow('This session continues as', payload.continuedAs);
    if (payload.continuedFrom) linkRow('Continued from', payload.continuedFrom);
    if (!payload.continuedAs && !payload.continuedFrom) {
      body.appendChild(emptyState({ title: 'No fork lineage', body: 'This session was not forked and has no known continuation.' }));
    }
    return { backdrop: chrome.backdrop, panel: chrome.panel };
  }

  // ---------------------------------------------------------------------------
  // Rename session (capability #11) — cr_detail.js payload: {sessionId, currentTitle}.
  // POST /api/title already exists (server.py) but per "NO FETCHING" this dialog
  // emits 'cr:rename' on the bus rather than writing it itself — see the report.
  // ---------------------------------------------------------------------------

  function renderRenameSession(payload) {
    payload = payload || {};
    var chrome = buildChrome('rename', 'Rename session', '✎', payload.sessionId || '', false);
    var input = h('input', { class: 'cr-textfield', type: 'text', value: payload.currentTitle || '' });
    chrome.body.appendChild(input);
    chrome.body.appendChild(h('div', { class: 'cr-cfg-actions', style: 'margin-top:12px' }, [
      h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Cancel', onclick: close }),
      h('button', {
        class: 'cr-btn cr-btn-solid', type: 'button', text: 'Save',
        onclick: function () {
          var title = input.value.trim();
          if (_ctx && typeof _ctx.emit === 'function') _ctx.emit('cr:rename', { sessionId: payload.sessionId, title: title });
          close();
        },
      }),
    ]));
    return { backdrop: chrome.backdrop, panel: chrome.panel };
  }

  // ---------------------------------------------------------------------------
  // Drill-down pop-outs opened with only an id — cr_detail.js's real payloads for
  // fileDiff/commandOutput/agentTranscript/shellTail are {sessionId, path|cmdId|
  // agentId|shellId} with NO content. registry.py's own drill() vocabulary
  // ("output","diff","shell","agent") names exactly what each needs fetched from
  // /api/diff | /api/output | /api/shell | /api/agent — routes that already
  // exist. Per "NO FETCHING" this module cannot call them itself, so it renders a
  // loading placeholder and asks for the content over the bus as 'cr:drill-
  // request'; whoever owns the fetch re-opens the SAME dialog name with the
  // content filled in ({lines,...} for diff, {text} for the rest), which
  // open()'s same-name update path upgrades in place. See REQUIRED ADDITION.
  // ---------------------------------------------------------------------------

  var DRILL_ID_KEY = { diff: 'path', output: 'cmdId', agent: 'agentId', shell: 'shellId' };
  var DRILL_TITLE = { diff: 'diff', output: 'output', agent: 'agent transcript', shell: 'shell' };

  function renderDrillPopout(kind) {
    return function (payload) {
      payload = payload || {};
      var hasContent = kind === 'diff' ? Array.isArray(payload.lines) : (typeof payload.text === 'string');
      if (hasContent) {
        var mode = kind === 'diff' ? 'diff' : 'output';
        var merged = {}; for (var k in payload) merged[k] = payload[k]; merged.mode = mode;
        return renderDiffPopout(merged);
      }
      var idVal = payload[DRILL_ID_KEY[kind]];
      var chrome = buildChrome(kind, DRILL_TITLE[kind] + (idVal ? ': ' + idVal : ''), null, payload.sessionId || '', true);
      chrome.panel.classList.add('cr-dialog-popout');
      chrome.body.appendChild(emptyState({
        title: 'Loading ' + DRILL_TITLE[kind] + '…',
        body: 'Fetching the content for this pop-out.',
      }));
      if (_ctx && typeof _ctx.emit === 'function') {
        _ctx.emit('cr:drill-request', { kind: kind, sessionId: payload.sessionId, arg: idVal });
      }
      return {
        backdrop: chrome.backdrop, panel: chrome.panel,
        update: function (richer) {
          richer = richer || {};
          if (richer.error) {
            var oldBodyErr = chrome.panel.querySelector('.cr-dialog-body');
            oldBodyErr.innerHTML = '';
            oldBodyErr.appendChild(errorState({
              title: "Couldn't load this " + DRILL_TITLE[kind],
              body: String(richer.error),
            }));
            return;
          }
          var richHas = kind === 'diff' ? Array.isArray(richer.lines) : (typeof richer.text === 'string');
          if (!richHas) return;
          var mode2 = kind === 'diff' ? 'diff' : 'output';
          var merged2 = {}; for (var k2 in richer) merged2[k2] = richer[k2]; merged2.mode = mode2;
          var rebuilt = renderDiffPopout(merged2);
          var newBody = rebuilt.panel.querySelector('.cr-dialog-body');
          var oldBody = chrome.panel.querySelector('.cr-dialog-body');
          oldBody.innerHTML = '';
          while (newBody.firstChild) oldBody.appendChild(newBody.firstChild);
        },
      };
    };
  }

  // ---------------------------------------------------------------------------
  // registry + public API
  // ---------------------------------------------------------------------------

  var REGISTRY = {
    help: renderHelp,
    config: renderConfig,
    flags: renderFlagsList,
    'manage-terminals': renderManageTerminals,
    'terminals-cap': renderManageTerminals, // alias: doc 04's own section title for this dialog
    'directory-picker': renderDirectoryPicker,
    model: renderLadderPicker('model'),
    effort: renderLadderPicker('effort'),
    'fork-lineage': renderForkLineage,
    rename: renderRenameSession,
    'file-diff': renderDrillPopout('diff'),
    'command-output': renderDrillPopout('output'),
    'agent-transcript': renderDrillPopout('agent'),
    'shell-tail': renderDrillPopout('shell'),
    diff: renderDiffPopout,       // generic rich pop-out for a caller that already holds full content
    'narration-diagram': renderNarrationDiagram,
  };

  window.CR.dialogs = {
    mount: mount,
    open: open,
    close: close,
    update: update,
    emptyState: emptyState,
    errorState: errorState,
    degraded: degraded,
    toast: toast,
    notificationNudge: notificationNudge,
    showNudgeIfNeeded: showNudgeIfNeeded,
    providerNoteFor: providerNoteFor,
    addHelpShortcuts: addHelpShortcuts,
    // Exposed so a role="dialog" surface built outside this module's own open()/close()
    // (currently: ext_cr_term.js's terminal overlay) can wire the SAME Tab-cycling focus
    // trap every dialog built via open() already gets — instead of forking a second
    // implementation. Returns the untrap cleanup fn, exactly like the internal call site
    // above (open()) uses it.
    trapFocus: trapFocus,
    CAPABILITIES: CAPABILITIES, // exposed read-only — tests/test_capability_table.py asserts against this directly
  };
})();
