/* cr_dialogs.js — Control Room dialog system: the modal host, Help, Config, the
 * file-diff/output/text pop-out, the narration-diagram pop-out, the cross-session
 * flag list, the terminals-at-cap dialog, toast notifications + the desktop-permission
 * nudge, and the three shared state components (emptyState/errorState/degraded) that
 * sibling modules (board, detail, terminal) reuse instead of forking their own.
 *
 * Doc: design_handoff_control_room/04-coverage-and-help.md (source of truth for every
 * string, colour and layout below). NO FETCHING — every dialog is fed by the payload its
 * opener passes to CR.dialogs.open(name, payload); this module never calls fetch().
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

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

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

  // 24px grid, currentColor, ~1.75px stroke — used only when ctx.icon(name) has nothing
  // for that name. Covers the glyph set doc 01 lists as "not emoji".
  var GLYPH_PATHS = {
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
    send: 'M3 11l18-8-8 18-2-8-8-2z',
    close: 'M6 6l12 12M18 6L6 18',
    spark: 'M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z',
  };
  function fallbackGlyph(name, cls) {
    var d = GLYPH_PATHS[name] || GLYPH_PATHS.spark;
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

  // ---------------------------------------------------------------------------
  // toast notifications (capability #51) — a stack in the corner, plus a real
  // Notification() when the tab is backgrounded.
  // ---------------------------------------------------------------------------

  function toast(opts) {
    opts = opts || {};
    if (!_toastHost) return;
    var dismissed = false;
    var timer = null;
    var el = h('div', { class: 'cr-toast', role: 'status' }, [
      emoji(opts.icon || '✅', opts.iconClass || 'tn-emo-d'),
      h('div', { class: 'cr-toast-body' }, [
        h('div', { class: 'cr-toast-title' }, [opts.title || 'Finished']),
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

    if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
      try { new Notification(opts.title || 'Finished', { body: opts.meta || '' }); } catch (e) {}
    }
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

  function buildChrome(name, title, emo, contextStr, wide) {
    var titleId = 'cr-dlg-title-' + (++_idSeq);
    var backdrop = h('div', { class: 'cr-backdrop' });
    var panel = h('div', {
      class: 'cr-dialog' + (wide ? ' cr-dialog-wide' : ''),
      role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId,
      'data-cr-dialog': name,
    });
    var head = h('div', { class: 'cr-dialog-head' }, [
      h('div', { class: 'cr-dialog-heading' }, [
        emo ? emoji(emo, null) : null,
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

  // Providers actually registered in aitracker/registry.py (4, matching "4 tools" in
  // the stat block) and where each is known — from the project README — to degrade.
  var PROVIDER_NOTES = [
    { name: 'Claude Code', ok: 'Full support, incl. background agents & shells and PR attribution.' },
    { name: 'Auggie', ok: 'Full narration/todos/files/commands.', degraded: 'No background-work model — capability 48 shows empty-because-it-cannot-exist, not broken.' },
    { name: 'Augment (VS Code)', degraded: 'Chat transcript lives in a per-workspace LevelDB the tracker cannot decode — narration degrades honestly; todos and files still read in full.' },
    { name: 'Augment (Cursor)', degraded: 'Same LevelDB limitation as Augment (VS Code).' },
  ];

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
      h('div', { class: 'cr-stat cr-stat-forest' }, [h('div', { class: 'cr-stat-num' }, ['58']), h('div', { class: 'cr-stat-label' }, ['capabilities'])]),
      h('div', { class: 'cr-stat cr-stat-neutral' }, [h('div', { class: 'cr-stat-num' }, ['4']), h('div', { class: 'cr-stat-label' }, ['tools'])]),
      h('div', { class: 'cr-stat cr-stat-dusk' }, [h('div', { class: 'cr-stat-num' }, ['0']), h('div', { class: 'cr-stat-label' }, ['bytes leaving'])]),
    ]));
    // NOTE: doc 04's Coverage-tab copy is literal ("58 capabilities · 4 tools · 0 bytes
    // leaving") even though the capability map below it enumerates 60 rows (2 are
    // explicitly marked New: the Config dialog and the progress spine). Fidelity rule
    // says copy is final, so the stat block keeps the doc's literal "58" rather than
    // deriving len(CAPABILITIES); the state->colour table and per-tool grid below DO
    // derive from the live data structure, per the doc's explicit instruction to do so.
    var table = h('table', { class: 'cr-state-table' });
    table.appendChild(h('thead', {}, [h('tr', {}, [h('th', {}, ['State']), h('th', {}, ['Colour']), h('th', {}, ['Word shown'])])]));
    var tbody = h('tbody');
    STATE_ROWS.forEach(function (r) {
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
        h('div', { class: 'cr-seccard-title' }, [emoji('⚠️', 'tn-emo-f'), ' If you expose this beyond localhost']),
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
    // NOTE: doc 04 asks for "verbatim copy from the 'Read this before you expose the
    // server' list" but no section by that exact heading exists in README.md or doc 04
    // itself — the closest verbatim source is README's "What these features do and
    // don't guarantee" bullets (README.md:104-108), quoted near-verbatim above.

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
    var chrome = buildChrome('help', 'Help', '❓', 'ai-tracker', false);
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
    railOpen: 'cr.railOpen',
    cardsFolded: 'cr.cardsFolded',
    boardTiles: 'cr.boardTileCount',
    pollMs: 'cr.pollIntervalMs',
    desktopNotif: 'cr.notif.enabled',
    sound: 'cr.notif.sound',
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

  function cfgRow(label, envVar, sub, control, restart) {
    return h('div', { class: 'cr-cfg-row' }, [
      h('div', { class: 'cr-cfg-row-label' }, [
        h('div', { class: 'cr-cfg-row-name' }, [label, envVar ? h('code', { class: 'cr-envchip' }, [envVar]) : null]),
        h('div', { class: 'cr-cfg-row-sub' }, [
          sub,
          restart ? h('span', { class: 'cr-restart-note' }, [' — needs a restart']) : null,
        ]),
      ]),
      h('div', { class: 'cr-cfg-row-control' }, [control]),
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

  // Config's payload contract (documented in the handoff report): the caller
  // (bootstrap) supplies `payload.server` with the values it already fetched from
  // existing routes (GET /api/term/renderer, GET /api/term/list) or embedded at page-
  // build time — this module never fetches. Missing fields render as "unknown".
  function renderConfig(payload) {
    var srv = (payload && payload.server) || {};
    var chrome = buildChrome('config', 'Config', '⚙️', 'ai-tracker', true);
    chrome.panel.classList.add('cr-dialog-config');

    var sections = ['Interface', 'Board', 'Terminal', 'Notifications', 'Server', 'Data files'];
    var nav = h('div', { class: 'cr-cfg-nav' });
    var body = h('div', { class: 'cr-cfg-body' });
    var active = 'Interface';

    function renderSection() {
      body.innerHTML = '';
      Array.prototype.forEach.call(nav.children, function (b) { b.classList.toggle('is-active', b.textContent === active); });
      if (active === 'Interface') {
        var themeVal = (_ctx && _ctx.theme && _ctx.theme.get) ? _ctx.theme.get() : 'auto';
        body.appendChild(cfgRow('Theme', null, 'Follows prefers-color-scheme unless overridden.',
          segmented([['auto', 'Auto'], ['light', 'Light'], ['dark', 'Dark']], themeVal, function (v) {
            if (_ctx && _ctx.theme && _ctx.theme.set) _ctx.theme.set(v);
          })));
        body.appendChild(cfgRow('Session rail', null, 'Open by default; collapses to 48px orbs.',
          toggleCtl(readPref(CFG_PREF_KEYS.railOpen, true), function (v) { writePref(CFG_PREF_KEYS.railOpen, v); })));
        body.appendChild(cfgRow('Cards start folded', null, 'Every detail-view panel starts collapsed except Conversation.',
          toggleCtl(readPref(CFG_PREF_KEYS.cardsFolded, true), function (v) { writePref(CFG_PREF_KEYS.cardsFolded, v); })));
        body.appendChild(cfgRow('Desktop notifications', null, 'Ask once; shows the permission nudge if not yet granted.',
          toggleCtl(readPref(CFG_PREF_KEYS.desktopNotif, true), function (v) { writePref(CFG_PREF_KEYS.desktopNotif, v); })));
        body.appendChild(cfgRow('Sound', null, 'Plays alongside the toast and desktop notification.',
          toggleCtl(readPref(CFG_PREF_KEYS.sound, true), function (v) { writePref(CFG_PREF_KEYS.sound, v); })));
      } else if (active === 'Board') {
        body.appendChild(cfgRow('Board tiles', null, 'Default 8. Decision 2 caps the board at 8 regardless of this slider — raising it only affects how many can appear before the cap wins.',
          sliderCtl(3, 12, readPref(CFG_PREF_KEYS.boardTiles, 8), function (v) { writePref(CFG_PREF_KEYS.boardTiles, v); })));
        body.appendChild(cfgRow('Poll interval', null, 'How often the board/rail re-poll /api/list.',
          segmented([[1000, '1s'], [2000, '2s'], [5000, '5s']], readPref(CFG_PREF_KEYS.pollMs, 2000), function (v) { writePref(CFG_PREF_KEYS.pollMs, v); })));
        body.appendChild(cfgRow('Live window', null,
          'Fixed at ' + (srv.liveWindowSec != null ? Math.round(srv.liveWindowSec / 60) : 5) + ' min server-side (config.py LIVE_WINDOW) — not yet configurable; see Help.',
          readonlyField((srv.liveWindowSec != null ? Math.round(srv.liveWindowSec / 60) : 5) + ' min')));
      } else if (active === 'Terminal') {
        body.appendChild(cfgRow('Terminal renderer', 'TRACKER_TERM_RENDERER', 'Startup default only — already switchable live per-terminal from its own toolbar.',
          readonlyField(srv.termRenderer || 'xterm')));
        body.appendChild(cfgRow('Max terminals', 'TRACKER_MAX_TERMS', 'Clamped to 1–64.',
          readonlyField(String(srv.maxTerms != null ? srv.maxTerms : 12))));
        body.appendChild(cfgRow('Terminal enabled', 'TRACKER_TERMINAL', 'Turns the tracker from a read-only viewer into something that can start processes.', restartFlag(true),
          true));
        body.appendChild(cfgRow('External terminal app', 'TRACKER_TERM_APP', 'Terminal or iTerm, for the ↗ external-terminal buttons.',
          readonlyField(srv.termApp || 'Terminal')));
        body.appendChild(cfgRow('Command allowlist', 'TRACKER_TERM_ALLOW', 'One argv prefix per line; replaces the default set outright.',
          readonlyField((srv.termAllow || []).length ? (srv.termAllow.length + ' entries') : 'default set')));
      } else if (active === 'Notifications') {
        body.appendChild(cfgRow('Desktop notifications', null, 'Mirrors the Interface tab toggle.',
          toggleCtl(readPref(CFG_PREF_KEYS.desktopNotif, true), function (v) { writePref(CFG_PREF_KEYS.desktopNotif, v); })));
        body.appendChild(cfgRow('Sound', null, 'Mirrors the Interface tab toggle.',
          toggleCtl(readPref(CFG_PREF_KEYS.sound, true), function (v) { writePref(CFG_PREF_KEYS.sound, v); })));
      } else if (active === 'Server') {
        body.appendChild(cfgRow('Auth', 'TRACKER_AUTH', 'Never displayed — only whether it is set. Treat it like a root password.',
          readonlyField(srv.authSet ? 'set' : 'not set'), true));
        body.appendChild(cfgRow('Port', 'PORT', 'Read-only display.', readonlyField(String(srv.port != null ? srv.port : 8790)), true));
        body.appendChild(cfgRow('Host', 'HOST', 'Read-only display.', readonlyField(srv.host || '127.0.0.1'), true));
      } else if (active === 'Data files') {
        var df = srv.dataFiles || {};
        ['flags', 'titles', 'pins', 'notes'].forEach(function (k) {
          body.appendChild(cfgRow(k[0].toUpperCase() + k.slice(1), null, 'Read live — edits outside the app are picked up on the next poll.',
            readonlyField(df[k] || (k + '.json'))));
        });
      }
    }
    function restartFlag(on) {
      return h('span', { class: 'cr-restart-badge' }, [on ? 'on' : 'off']);
    }
    sections.forEach(function (s) {
      var btn = h('button', { class: 'cr-cfg-nav-btn' + (s === active ? ' is-active' : ''), type: 'button', text: s });
      btn.addEventListener('click', function () { active = s; renderSection(); });
      nav.appendChild(btn);
    });
    renderSection();

    var main = h('div', { class: 'cr-cfg-main' }, [nav, body]);
    chrome.body.appendChild(main);
    chrome.body.appendChild(h('div', { class: 'cr-cfg-footer' }, [
      h('p', { class: 'cr-cfg-footer-note' }, [
        'Rows with an env-var name are read from the process. Editing one writes an override the server picks up; the two marked *needs a restart* take effect on the next ',
        h('code', {}, ['make serve']), '.',
      ]),
      h('div', { class: 'cr-cfg-actions' }, [
        h('button', { class: 'cr-btn cr-btn-quiet', type: 'button', text: 'Reset to defaults', onclick: function () {
          Object.keys(CFG_PREF_KEYS).forEach(function (k) { var key = CFG_PREF_KEYS[k]; if (key) { try { localStorage.removeItem(key); } catch (e) {} } });
          renderSection();
        } }),
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
    var row = h('div', { class: 'cr-diagram-row' });
    (payload.nodes || []).forEach(function (n) {
      row.appendChild(h('span', { class: 'cr-diagram-pill' + (n.active ? ' is-active' : '') }, [n.label]));
    });
    card.appendChild(row);
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
    var chrome = buildChrome('flags', 'Flags', '🚩', (payload.flags || []).length + ' total', false);
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
    addHelpShortcuts: addHelpShortcuts,
    CAPABILITIES: CAPABILITIES, // exposed read-only for a future shared self-check
  };
})();
