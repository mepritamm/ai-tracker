// cr_term.js — Control Room skin for the terminal surface (doc 05-terminal-and-dialogs.md).
//
// This is NEW CHROME over the EXISTING terminal subsystem (aitracker/web/ext_vt.js,
// aitracker/web/ext_launch.js, aitracker/term_vt.py, aitracker/term_launch.py). It must not
// duplicate that subsystem's transport (the SSE/raw-byte stream), resize logic (computeColsRows,
// the ResizeObserver dance) or buffer handling (the grid model / xterm.js Terminal instance) —
// see this file's own ExtVT `mountInto` seam comment below for that shared core. Everything
// else here talks to server endpoints ext_vt.js/ext_launch.js
// ALREADY call directly from client code (POST /api/term/pty, /api/term/open, /api/term/close,
// /api/term/inject, GET /api/term/list, /api/term/cwds, /api/term/attached, GET /api/session) —
// using a public REST route directly is not "duplicating ext_vt.js", it's the same pattern
// ext_launch.js itself already uses for its own picker and native-launch buttons.
//
// window.CR.term is built once via mount(rootEl, ctx) and stays inert until open(sessionId, opts)
// is called — that is the ONLY place the lazy xterm.js load may be triggered, and even then only
// indirectly, through whatever ext_vt.js does internally (see _attachEngine below). Nothing here
// ever inserts a <script src="/vendor/xterm.js"> tag itself.
(function () {
  window.CR = window.CR || {};

  // ===== hard-coded CLI ladders — mirrors ext_vt.js's own MODEL_LADDER/EFFORT_LADDER exactly.
  // These are the CLI's OWN slash-command vocabulary (not discoverable from any API), so this is
  // the one place a client is allowed to know them; duplicating the literal array is not the kind
  // of duplication the brief warns about (that is about transport/resize/buffer engines) — see
  // ext_vt.js's own comment on MODEL_LADDER for the provenance.
  var MODEL_LADDER = ["haiku", "sonnet", "opus", "fable"];
  var EFFORT_LADDER = ["low", "medium", "high", "xhigh", "max"];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }
  function fmtTok(n) {
    // FIX 3: doc 05's status-bar section shows raw comma-grouped digits ("128,412"), never an
    // abbreviated "128.4k" — the doc's point is a real number. toLocaleString comma-groups without
    // pulling in a dependency. The "never invent a %" behaviour this doc also calls out lives
    // entirely in _syncStatusBar's own st.ctx.pct !== null gate, untouched by this change.
    n = n || 0;
    return Math.round(n).toLocaleString("en-US");
  }
  function localOnly() {
    return location.hostname === "localhost" || location.hostname === "127.0.0.1";
  }
  function isClaudeId(sid) {
    return !!sid && !/^(auggie|augment-vscode|augment-cursor):/.test(sid);
  }
  function j(r) {
    return r.json().catch(function () { return {}; }).then(function (body) {
      return { ok: r.ok, status: r.status, j: body };
    });
  }
  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  var root = null;      // rootEl passed to mount()
  var ctx = null;
  var el = {};           // DOM refs, filled by _build()
  var pollTimer = null;
  var pollGen = 0;       // supersede guard — same idiom as ext_vt.js's own openGen

  // ===== module state — everything the chrome renders from ================================
  var st = {
    open: false,
    sessionId: null,
    mode: null,          // "cwd" | "resume" — how the CURRENT inline pane was opened
    tty: null,
    renderer: "xterm",   // server-owned default; the FIRST attach response is the real source
    forked: false,
    notice: null,
    engineHandle: null,  // whatever _attachEngine() returned, or null while degraded
    attached: false,     // is a Claude CLI foreground on this pty right now
    model: null,
    effort: null,
    ctx: null,           // {current, limit, pct} | null — readContextUsage() shape
    cumulative: 0,
    running: [],         // GET /api/term/list terminals[]
    maxRunning: null,
    cwd: null,
    resumeCmd: null,
  };

  // ===== tiny non-blocking toast — replaces the old code's alert()s (rule 10 forbids alert) ===
  var toastTimer = null;
  function showToast(msg) {
    if (!el.toast) return;
    el.toast.textContent = msg;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.toast.hidden = true; }, 4000);
  }

  // ===== build DOM once ======================================================================
  function _build() {
    var overlay = document.createElement("div");
    overlay.className = "cr-term-overlay";

    var shell = document.createElement("div");
    shell.className = "cr-term-shell";
    shell.setAttribute("role", "dialog");
    shell.setAttribute("aria-label", "Terminal");
    overlay.appendChild(shell);

    // ---- head: eyebrow + cwd + resume cmd | Config Help close ----
    var head = document.createElement("div");
    head.className = "cr-term-head";
    head.innerHTML =
      '<div class="cr-term-head-info">' +
        '<div class="cr-term-eyebrow">Terminal</div>' +
        '<div class="cr-term-cwd" data-el="cwd"></div>' +
        '<div class="cr-term-resumecmd" data-el="resumecmd" hidden></div>' +
      '</div>' +
      '<div class="cr-term-head-actions">' +
        '<button type="button" class="cr-term-headpill" data-action="config">' +
          '<span class="cr-emo tn-emo" aria-hidden="true">⚙️</span>Config</button>' +
        '<button type="button" class="cr-term-headpill" data-action="help">' +
          '<span class="cr-emo tn-emo" aria-hidden="true">❓</span>Help</button>' +
        '<button type="button" class="cr-term-close" data-action="close" title="Close — detaches, does not kill" aria-label="Close terminal — detaches, does not kill">✕</button>' +
      '</div>';
    shell.appendChild(head);

    // ---- control bar — every button from doc 05's table, nothing dropped ----
    var bar = document.createElement("div");
    bar.className = "cr-term-controlbar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "Terminal controls");
    bar.innerHTML =
      '<div class="cr-term-group" data-group="primary">' +
        '<button type="button" class="cr-term-btn cr-term-btn-solid" data-action="open-here">Open terminal here</button>' +
        '<button type="button" class="cr-term-btn cr-term-btn-outline" data-action="resume-here" hidden>Resume terminal here</button>' +
      '</div>' +
      '<div class="cr-term-divider"></div>' +
      '<div class="cr-term-group" data-group="external">' +
        '<button type="button" class="cr-term-btn cr-term-btn-ghost" data-action="ext-terminal" title="Open an external Terminal/iTerm window, cd\'d here — this machine only" hidden>↗ External terminal</button>' +
        '<button type="button" class="cr-term-btn cr-term-btn-ghost" data-action="ext-resume" title="Resume via claude --resume in an external Terminal/iTerm window — this machine only" hidden>↗ External resume</button>' +
      '</div>' +
      '<div class="cr-term-divider"></div>' +
      '<div class="cr-term-group" data-group="windows">' +
        '<button type="button" class="cr-term-btn cr-term-btn-ghost" data-action="new-tab" disabled>⤢ New tab</button>' +
        '<button type="button" class="cr-term-btn cr-term-btn-ghost" data-action="new-terminal">+ New terminal</button>' +
        '<button type="button" class="cr-term-btn cr-term-btn-ghost" data-action="new-claude">+ New Claude session</button>' +
      '</div>' +
      '<div class="cr-term-divider"></div>' +
      '<div class="cr-term-group" data-group="manage">' +
        '<button type="button" class="cr-term-btn cr-term-btn-ghost cr-term-btn-manage" data-action="manage">' +
          '<span class="cr-emo" aria-hidden="true">☰</span> Manage terminals' +
          '<span class="cr-term-badge" data-el="badge" hidden>0</span>' +
        '</button>' +
      '</div>' +
      '<div class="cr-term-right">' +
        '<div class="cr-term-seg" role="group" aria-label="Renderer">' +
          '<button type="button" data-renderer="xterm" aria-pressed="true">xterm.js</button>' +
          '<button type="button" data-renderer="grid" aria-pressed="false">grid</button>' +
        '</div>' +
        '<button type="button" class="cr-term-themebtn" data-action="theme">' +
          '<span class="cr-emo tn-emo" aria-hidden="true">☀️</span>Theme</button>' +
      '</div>';
    shell.appendChild(bar);

    // ---- fork / notice banner (conditional) — owned by the MOUNT POINT, per doc 05's
    // "Behaviour that must survive the redesign": a renderer switch must leave it on screen. ----
    var notice = document.createElement("div");
    notice.className = "cr-term-notice";
    notice.hidden = true;
    notice.innerHTML =
      '<span class="cr-term-notice-text" data-el="noticetext"></span>' +
      '<button type="button" class="cr-term-notice-link" data-action="lineage">See lineage</button>';
    shell.appendChild(notice);

    // ---- PTY pane — dark in both themes ----
    var frame = document.createElement("div");
    frame.className = "cr-term-paneframe";
    var pane = document.createElement("div");
    pane.className = "cr-term-pane";
    pane.innerHTML =
      '<div class="cr-term-pane-placeholder" data-el="placeholder">No terminal open yet.</div>' +
      '<div class="cr-term-pane-blank" data-el="blank" hidden>' +
        'Switched to xterm.js — this pane goes blank until the next write; it has no server-side ' +
        'scrollback to repaint from.</div>';
    frame.appendChild(pane);
    shell.appendChild(frame);

    // ---- status bar ----
    var status = document.createElement("div");
    status.className = "cr-term-statusbar";
    status.hidden = true;
    status.innerHTML =
      '<div class="cr-term-ctxreadout" data-el="ctxreadout"></div>' +
      '<div class="cr-term-status-right">' +
        '<button type="button" class="cr-term-pill cr-term-pill-model" data-action="model" hidden data-el="modelpill">model</button>' +
        '<button type="button" class="cr-term-pill cr-term-pill-effort" data-action="effort" hidden data-el="effortpill">effort</button>' +
        '<button type="button" class="cr-term-iconbtn" data-action="copy">⧉ Copy</button>' +
        '<button type="button" class="cr-term-iconbtn cr-term-kill" data-action="kill">■ Kill</button>' +
      '</div>';
    shell.appendChild(status);

    // ---- footnote + dialog triggers ----
    // NOTE: doc 05's layout diagram lists a bottom "footnote + dialog triggers" row distinct
    // from the header's Config/Help pills. Read as a small, DYNAMIC behavioural disclaimer (the
    // renderer-parity caveats doc 05's last section calls out: wide-character width / true colour
    // for xterm vs. server-backed scrollback for grid) rather than a second copy of Config/Help.
    var foot = document.createElement("div");
    foot.className = "cr-term-foot";
    foot.innerHTML = '<span class="cr-term-footnote" data-el="footnote"></span>';
    shell.appendChild(foot);

    var toast = document.createElement("div");
    toast.className = "cr-term-toast";
    toast.hidden = true;
    frame.appendChild(toast);

    overlay.addEventListener("click", function (ev) { if (ev.target === overlay) close(); });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && overlay.classList.contains("is-open")) close();
    });

    root.appendChild(overlay);

    el = {
      overlay: overlay, shell: shell,
      cwd: head.querySelector('[data-el="cwd"]'),
      resumecmd: head.querySelector('[data-el="resumecmd"]'),
      primaryGroup: bar.querySelector('[data-group="primary"]'),
      openHere: bar.querySelector('[data-action="open-here"]'),
      resumeHere: bar.querySelector('[data-action="resume-here"]'),
      extTerminal: bar.querySelector('[data-action="ext-terminal"]'),
      extResume: bar.querySelector('[data-action="ext-resume"]'),
      newTab: bar.querySelector('[data-action="new-tab"]'),
      newTerminal: bar.querySelector('[data-action="new-terminal"]'),
      newClaude: bar.querySelector('[data-action="new-claude"]'),
      manageBtn: bar.querySelector('[data-action="manage"]'),
      badge: bar.querySelector('[data-el="badge"]'),
      rendererSeg: bar.querySelector(".cr-term-seg"),
      themeBtn: bar.querySelector('[data-action="theme"]'),
      notice: notice,
      noticeText: notice.querySelector('[data-el="noticetext"]'),
      pane: pane,
      placeholder: pane.querySelector('[data-el="placeholder"]'),
      blank: pane.querySelector('[data-el="blank"]'),
      status: status,
      ctxreadout: status.querySelector('[data-el="ctxreadout"]'),
      modelPill: status.querySelector('[data-el="modelpill"]'),
      effortPill: status.querySelector('[data-el="effortpill"]'),
      copyBtn: status.querySelector('[data-action="copy"]'),
      killBtn: status.querySelector('[data-action="kill"]'),
      footnote: foot.querySelector('[data-el="footnote"]'),
      toast: toast,
    };

    _wireStaticHandlers();
  }

  function _wireStaticHandlers() {
    el.overlay.querySelectorAll("[data-action]").forEach(function (btn) {
      btn.addEventListener("click", function () { _onAction(btn.getAttribute("data-action")); });
    });
    el.rendererSeg.querySelectorAll("[data-renderer]").forEach(function (btn) {
      btn.addEventListener("click", function () { _setRenderer(btn.getAttribute("data-renderer")); });
    });
  }

  function _onAction(action) {
    switch (action) {
      case "close": close(); return;
      case "config": ctx.dialog("config", {}); return;
      case "help": ctx.dialog("help", {}); return;
      case "open-here": _openInline(st.sessionId, "cwd"); return;
      case "resume-here": _openInline(st.sessionId, "resume"); return;
      case "ext-terminal": _openExternal("cwd"); return;
      case "ext-resume": _openExternal("resume"); return;
      case "new-tab": _openNewTab(); return;
      case "new-terminal": _openDirectoryPicker("cwd"); return;
      case "new-claude": _openDirectoryPicker("new"); return;
      case "manage": _openManageDialog(); return;
      case "theme": _cycleTheme(); return;
      case "model": _openModelDialog(); return;
      case "effort": _openEffortDialog(); return;
      case "copy": _copyPane(); return;
      case "kill": _killCurrent(); return;
      case "lineage": _openLineageDialog(); return;
    }
  }

  // ===== the seam this module relies on — window.ExtVT.mountInto(container, target, opts) =====
  // (doc 05; ext_vt.js's own `mountInto` header comment carries the full contract). It renders a
  // live terminal INSIDE `.cr-term-pane` instead of ext_vt.js's own body-level "vtmodal" overlay,
  // and hands back a handle synchronously:
  //
  //   window.ExtVT.mountInto(container, target, opts) -> {
  //     tty, renderer,              // "grid" | "xterm" — filled in once resolution finishes; see
  //                                 // _openInline's own onForked comment for why nothing here may
  //                                 // read these synchronously
  //     forked, notice,             // the same {forked, notice} fields POST /api/term/pty returns
  //     setRenderer(next),          // switches the live renderer in place (repaint-vs-blank
  //                                 // caveat from doc 05's last section is the engine's to honour)
  //     setTheme({background, foreground, cursor}),   // drives THIS mount's colours — see FIX 1's
  //                                 // _applyDarkTheme below for how this file uses it to force
  //                                 // the PTY pane dark in both app themes
  //     copyBuffer(),               // -> string; the ⧉ Copy button's action (_copyPane below)
  //     focus(), destroy(),
  //     onStatus(cb), onNotice(cb), onForked(cb),
  //   }
  //   `target` is `{session, mode}` to dedupe-or-spawn exactly like openVT() already does, or
  //   `{tty}` to attach to an EXISTING pty without spawning ("peek", done in-place instead of in a
  //   new tab) — nothing in this file calls the {tty} form today; _peekTerminal below still opens
  //   a new tab.
  //
  // `_attachEngine` still guards on `window.ExtVT && typeof mountInto === "function"` rather than
  // calling it unconditionally — not because the seam might be missing (ext_vt.js's own IIFE
  // always assigns it, unconditionally, at the bottom of that file) but as a defensive fallback
  // for the one failure mode that could actually leave it undefined: a throw earlier in the same
  // concatenated <script> tag (page.py inlines every ext_*.js into ONE tag; an exception in any
  // one of them aborts every script after it). See _openInline's own fallback branch below for
  // what happens in that case.
  function _attachEngine(container, target, opts) {
    if (window.ExtVT && typeof window.ExtVT.mountInto === "function") {
      return window.ExtVT.mountInto(container, target, opts);
    }
    return null;
  }

  // ===== FIX 1: force the PTY pane dark in both app themes (doc 05 "Layout") =================
  // mountInto()'s `opts` argument only ever reads `opts.renderer` (see the seam comment above) —
  // passing {theme:"dark"} there, as this file used to, was silently ignored. The grid renderer's
  // palette instead comes from var(--app)/var(--text)/var(--ring2) (ext_vt.css:94,106), which flip
  // with the CLASSIC dashboard's <html>.light class — a class ext_cr_boot.js deliberately never
  // touches — so a user who had ever set classic to light mode saw this inline pane render light,
  // contradicting the doc. Fixed caller-side via the handle's real setTheme(), called once the
  // handle actually resolves (see _openInline's onForked below) and again after any renderer
  // switch (see _setRenderer below). The values are the SAME frozen dark literals ext_cr_term.css
  // already uses for this pane/status bar — not a second, invented palette:
  //   background #12100E — cr_term.css's own frozen --surface-inverse (.cr-term-pane's background)
  //   foreground #E4D8CA — cr_term.css's own frozen --text-primary (.cr-term-pane's color)
  //   cursor     #E5CB79 — the one frozen accent literal in that file (.cr-term-ctxbarfill)
  var DARK_PANE_THEME = { background: "#12100E", foreground: "#E4D8CA", cursor: "#E5CB79" };
  function _applyDarkTheme(handle) {
    if (handle && typeof handle.setTheme === "function") handle.setTheme(DARK_PANE_THEME);
  }

  // ===== open / close ========================================================================
  function open(sessionId, opts) {
    opts = opts || {};
    if (!root) return;
    st.open = true;
    st.sessionId = sessionId;
    el.overlay.classList.add("is-open");
    _resetPaneChrome();
    _loadHeaderInfo(sessionId);
    _refreshRunningList();
    _startPoll();
    var mode = opts.mode || "cwd";
    if (mode === "resume" || mode === "cwd") {
      _openInline(sessionId, mode);
    }
  }

  function close() {
    st.open = false;
    el.overlay.classList.remove("is-open");
    _stopPoll();
    engineGen++;   // supersede guard: no in-flight _openInline resolution may touch state after this
    if (st.engineHandle && typeof st.engineHandle.destroy === "function") {
      // Detaches only — per doc 05 "Closing a dialog detaches, it does not kill." The pty (if
      // any) keeps running server-side; only ✕ Kill (below) actually ends it.
      st.engineHandle.destroy();
    }
    st.engineHandle = null;
    st.tty = null;
    st.mode = null;
    _resetPaneChrome();
    if (ctx && typeof ctx.emit === "function") ctx.emit("cr:term-closed", { sessionId: st.sessionId });
  }

  function _resetPaneChrome() {
    el.placeholder.hidden = false;
    el.placeholder.textContent = "No terminal open yet.";
    el.blank.hidden = true;
    el.notice.hidden = true;
    el.status.hidden = true;
    el.newTab.disabled = true;
    st.forked = false;
    st.notice = null;
    st.attached = false;
    st.model = null;
    st.effort = null;
    st.ctx = null;
    st.cumulative = 0;
    _syncStatusBar();
  }

  // ===== "Open terminal here" / "Resume terminal here" — inline, dedupe-on-session+mode ======
  //
  // mountInto() returns its handle SYNCHRONOUSLY, but resolving which tty to attach to is a
  // network round trip (a list scan, or a spawn) — tty/renderer/forked/notice start out null/
  // false and are filled in on the SAME object once that resolves (ext_vt.js's own mountInto()
  // header comment). Reading them right after the call — the bug this replaces — always saw the
  // pre-resolution values, so the pane stayed blank forever.
  //
  // ext_vt.js's finish()/fail() give exactly one reliable "done" signal: finish() ALWAYS calls
  // fireForked() (whether forked is true or false) after tty/renderer/notice are set on the
  // handle; fail() never does. So onForked doubles as "resolution succeeded, safe to read the
  // handle now" — there is no separate onReady/onError in the contract, and none is needed.
  // onStatus fires the whole time, including a failure's message (fail()'s only path out is
  // fireStatus), so a failed resolve just leaves the placeholder showing that reason instead of
  // blanking out. Once attached, a LATER status change (e.g. a dropped/reconnecting SSE stream)
  // is surfaced as a toast instead of silently overwriting the (now hidden) placeholder text.
  // onNotice is a running stream, not a one-shot — it stays subscribed for the pane's lifetime.
  var engineGen = 0;   // supersede guard: a stale handle's async callbacks must not touch state
                        // for whatever session/mode is open NOW — same idiom as pollGen above.
  function _openInline(sid, mode) {
    if (!sid) return;
    // Destroy any previous inline engine BEFORE attaching a new one. Calling _openInline again
    // without going through close() first — e.g. "Open terminal here" then "Resume terminal
    // here" on the SAME overlay, both routed here directly by _onAction — used to leak the old
    // handle's live pty/xterm instance and SSE stream instead of tearing it down.
    if (st.engineHandle && typeof st.engineHandle.destroy === "function") st.engineHandle.destroy();
    st.engineHandle = null;
    st.tty = null;
    st.mode = mode;
    var gen = ++engineGen;
    el.placeholder.hidden = false;
    el.placeholder.textContent = "connecting…";
    el.status.hidden = true;
    el.newTab.disabled = true;
    // FIX 1: theme is applied via handle.setTheme() below once the handle resolves (onForked) —
    // mountInto() ignores an opts.theme key, so none is passed here.
    var handle = _attachEngine(el.pane, { session: sid, mode: mode }, {});
    if (handle) {
      st.engineHandle = handle;
      // Loading state: the placeholder stays up (whatever text onStatus reports) until onForked
      // says the resolve finished — never read handle.tty/renderer/forked synchronously here.
      if (typeof handle.onStatus === "function") {
        handle.onStatus(function (text) {
          if (gen !== engineGen) return;
          if (st.tty) { showToast(text); return; }   // already attached — a later status is a
                                                       // reconnect, not "still connecting"
          // FIX 2: mountInto()'s fail() path (ext_vt.js) forwards only res.j.error as a plain
          // string — never the HTTP status or the `terminals` list the 429 body actually carries
          // (term_vt.py open_pty) — so this is the one structured signal available caller-side
          // without editing ext_vt.js. The text matched is the server's own stable message, not a
          // guessed heuristic: term_vt.py's open_pty returns exactly
          // "too many running terminals (max %d)" at 429, and fail() passes it through verbatim.
          if (typeof text === "string" && text.indexOf("too many running terminals") === 0) {
            el.placeholder.textContent = text;
            _openCapDialog(function () { _openInline(sid, mode); });
            return;
          }
          el.placeholder.textContent = text;
        });
      }
      if (typeof handle.onNotice === "function") {
        handle.onNotice(function (n) {
          if (gen !== engineGen) return;
          st.notice = (n && n.text) || null;
          _syncNotice();
        });
      }
      if (typeof handle.onForked === "function") {
        handle.onForked(function () {
          if (gen !== engineGen) return;
          el.placeholder.hidden = true;
          st.tty = handle.tty || null;
          st.renderer = handle.renderer === "grid" ? "grid" : "xterm";
          st.forked = !!handle.forked;
          st.notice = handle.notice || null;
          _syncRendererSeg();
          _syncNotice();
          el.status.hidden = false;
          el.newTab.disabled = !st.tty;
          _applyDarkTheme(handle);   // FIX 1: doc 05 — the PTY pane stays dark in both app themes
        });
      }
      return;
    }
    // Fallback: this file's _attachEngine() couldn't find window.ExtVT.mountInto — see that
    // function's own comment for the one real way that happens (a script-load failure earlier in
    // the same concatenated <script> tag), since mountInto itself always ships in ext_vt.js.
    // Delegate to the classic, fully-working floating terminal so the feature is not dead even
    // then.
    el.placeholder.hidden = false;
    el.placeholder.textContent =
      "This build's terminal engine isn't wired into the new chrome yet — opening the classic " +
      "terminal window instead.";
    if (window.ExtVT && typeof window.ExtVT.open === "function") {
      window.ExtVT.open(sid, mode);
    } else {
      showToast("In-browser terminal unavailable.");
    }
  }

  // ===== External terminal / External resume — POST /api/term/open, exactly ext_launch.js =====
  var extAllowed = null, extProbing = null;
  function _probeExternal() {
    if (!extProbing) {
      extProbing = post("/api/term/open", { session: "" })
        .then(function (r) { extAllowed = r.status !== 403; _syncControlVisibility(); })
        .catch(function () { extAllowed = false; _syncControlVisibility(); });
    }
    return extProbing;
  }
  function _openExternal(mode) {
    if (!st.sessionId) return;
    post("/api/term/open", { session: st.sessionId, mode: mode }).then(j).then(function (res) {
      if (!res.ok || (res.j && res.j.error)) {
        if (res.status === 403) { extAllowed = false; _syncControlVisibility(); }
        showToast((res.j && res.j.error) || "Failed to open terminal.");
        return;
      }
      showToast((mode === "resume" ? "Resuming in terminal" : "Terminal opened") + " — this machine only");
    }).catch(function (e) { showToast("Failed to open terminal: " + e); });
  }

  // ===== ⤢ New tab — same query-string scheme ext_vt.js's own openNewTab()/peekTerm() build ===
  function _openNewTab() {
    if (!st.tty) return;
    var url = location.origin + location.pathname + "?tty=" + encodeURIComponent(st.tty) +
      "&sid=" + encodeURIComponent(st.sessionId || "") +
      "&mode=" + encodeURIComponent(st.mode || "") +
      "&renderer=" + encodeURIComponent(st.renderer || "grid") +
      "&forked=" + (st.forked ? "1" : "0") +
      (st.notice ? "&notice=" + encodeURIComponent(st.notice) : "");
    var w = window.open(url, "_blank");
    if (!w) showToast("Popup blocked — allow popups for this page to open a new tab.");
  }

  // ===== + New terminal / + New Claude session — directory picker dialog, then open a tab =====
  function _openDirectoryPicker(mode) {
    ctx.dialog("directory-picker", {
      mode: mode,
      title: (mode === "new" ? "New Claude session" : "New terminal") + " — choose a directory",
      loading: true,
      onPick: function (path) { _pickDirectory(path, mode); },
    });
    fetch("/api/term/cwds").then(j).then(function (res) {
      var note = null;
      if (!res.ok) {
        note = res.status === 404
          ? "recent directories aren't available on this server yet — type a path below"
          : "couldn't load recent directories — type a path below";
      }
      ctx.dialog("directory-picker", {
        mode: mode,
        title: (mode === "new" ? "New Claude session" : "New terminal") + " — choose a directory",
        cwds: (res.j && res.j.cwds) || [],
        note: note,
        onPick: function (path) { _pickDirectory(path, mode); },
      });
    }).catch(function () {
      ctx.dialog("directory-picker", {
        mode: mode,
        title: (mode === "new" ? "New Claude session" : "New terminal") + " — choose a directory",
        cwds: [],
        note: "couldn't load recent directories — type a path below",
        onPick: function (path) { _pickDirectory(path, mode); },
      });
    });
  }
  function _pickDirectory(raw, mode) {
    var path = (raw == null ? "" : String(raw)).trim();
    if (!path) { showToast("Choose or type a directory first."); return; }
    post("/api/term/pty", { cwd: path, cols: 100, rows: 30, mode: mode }).then(j).then(function (res) {
      if (!res.ok || !res.j || !res.j.tty) {
        // FIX 2: 429 is the server's real structured cap-reached signal — term_vt.py's open_pty
        // returns {error, terminals} at status 429 when config.MAX_TERMS is hit — not a guessed
        // string match (this call hits /api/term/pty directly, so the status code is right here).
        if (res.status === 429) {
          _openCapDialog(function () { _pickDirectory(path, mode); });
          return;
        }
        showToast((res.j && res.j.error) ||
          (res.status === 404 ? "Opening a terminal at a chosen directory isn't available yet." :
           res.status === 403 ? "In-browser terminal is disabled." : "Failed to open a terminal there."));
        return;
      }
      showToast((mode === "new" ? "Starting a new Claude session" : "Terminal opened") + " — " + path);
      var url = location.origin + location.pathname + "?tty=" + encodeURIComponent(res.j.tty) +
        "&mode=" + encodeURIComponent(mode) +
        "&renderer=" + encodeURIComponent(res.j.renderer || "grid") +
        "&forked=" + (res.j.forked ? "1" : "0") +
        (res.j.notice ? "&notice=" + encodeURIComponent(res.j.notice) : "");
      var w = window.open(url, "_blank");
      if (!w) showToast("Popup blocked — allow popups for this page to open a new tab.");
    }).catch(function (e) { showToast("Failed to reach the server: " + e); });
  }

  // ===== FIX 2: cap-reached dialog — doc 05, "Cap reached": "killing one immediately opens the
  // terminal you asked for." Reuses the SAME "manage-terminals" dialog and {terminals, max, onPeek,
  // onKill, onCloseAll, error} payload contract ☰ Manage terminals already uses below (renderManage-
  // Terminals derives its own "N of max running — free a slot" header purely from
  // terminals.length >= max — see that function's own comment — so no separate "atCap" flag needs
  // threading through here). The one difference: this onKill also closes the dialog and replays
  // `retry` — the original action the user asked for — once the kill confirms, instead of just
  // refreshing the list in place.
  function _openCapDialog(retry) {
    fetch("/api/term/list").then(j).then(function (res) {
      if (!res.ok) {
        ctx.dialog("manage-terminals", {
          error: (res.j && res.j.error) ||
            (res.status === 403 ? "in-browser terminal is disabled" :
             res.status === 404 ? "managing terminals isn't available on this server yet" :
             "couldn't list the running terminals"),
        });
        return;
      }
      st.running = (res.j && res.j.terminals) || [];
      st.maxRunning = res.j && res.j.max;
      _syncBadge();
      ctx.dialog("manage-terminals", {
        terminals: st.running,
        max: st.maxRunning,
        onPeek: _peekTerminal,
        onKill: function (t) {
          _killTerminal(t).then(function () {
            if (window.CR.dialogs && typeof window.CR.dialogs.close === "function") window.CR.dialogs.close();
            if (typeof retry === "function") retry();
          }).catch(function () { showToast("Failed to kill terminal."); });
        },
        onCloseAll: _closeAllTerminals,
      });
    }).catch(function (e) {
      ctx.dialog("manage-terminals", { error: "failed to reach the server: " + e });
    });
  }

  // ===== ☰ Manage terminals — dialog owned by CR.dialogs; this file supplies data + actions ===
  function _openManageDialog() {
    fetch("/api/term/list").then(j).then(function (res) {
      if (!res.ok) {
        ctx.dialog("manage-terminals", {
          error: (res.j && res.j.error) ||
            (res.status === 403 ? "in-browser terminal is disabled" :
             res.status === 404 ? "managing terminals isn't available on this server yet" :
             "couldn't list the running terminals"),
        });
        return;
      }
      st.running = (res.j && res.j.terminals) || [];
      st.maxRunning = res.j && res.j.max;
      _syncBadge();
      ctx.dialog("manage-terminals", {
        terminals: st.running,
        max: st.maxRunning,
        onPeek: _peekTerminal,
        onKill: _killTerminal,
        onCloseAll: _closeAllTerminals,
      });
    }).catch(function (e) {
      ctx.dialog("manage-terminals", { error: "failed to reach the server: " + e });
    });
  }
  function _peekTerminal(t) {
    // Peek opens the terminal in its own tab — nothing is killed. Same URL scheme as
    // ext_vt.js's own peekTerm(); a peeked terminal keeps its full context bar and fork chip.
    var url = location.origin + location.pathname + "?tty=" + encodeURIComponent(t.tty) +
      "&sid=" + encodeURIComponent(t.session || "") +
      "&mode=" + encodeURIComponent(t.mode || "") +
      "&forked=" + (t.forked ? "1" : "0");
    var w = window.open(url, "_blank");
    if (!w) showToast("Popup blocked — allow popups for this page to open a new tab.");
  }
  function _killTerminal(t) {
    return post("/api/term/close", { tty: t.tty }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      _refreshRunningList();
      return r;
    });
  }
  function _closeAllTerminals(terminals) {
    return Promise.all((terminals || []).map(function (t) {
      return post("/api/term/close", { tty: t.tty }).catch(function () {});
    })).then(function () { _refreshRunningList(); });
  }
  function _refreshRunningList() {
    fetch("/api/term/list").then(j).then(function (res) {
      if (!res.ok) return;
      st.running = (res.j && res.j.terminals) || [];
      st.maxRunning = res.j && res.j.max;
      _syncBadge();
    }).catch(function () {});
  }
  function _syncBadge() {
    if (!el.badge) return;
    var n = st.running.length;
    el.badge.hidden = n === 0;
    el.badge.textContent = String(n);
  }

  // ===== renderer segmented control =========================================================
  function _setRenderer(next) {
    if (next === st.renderer) return;
    st.renderer = next;
    _syncRendererSeg();
    if (st.engineHandle && typeof st.engineHandle.setRenderer === "function") {
      st.engineHandle.setRenderer(next);
      _applyDarkTheme(st.engineHandle);   // FIX 1: setRenderer() rebuilds the engine — reapply
    }
    // Doc 05: "Switching TO xterm shows a blank pane until the next write — say so in the UI, do
    // not fake a repaint." Grid, conversely, repaints in full immediately.
    // NOTE (FIX 5): ideally this clears itself once the pty actually writes fresh output, but the
    // mountInto handle's callback contract (onStatus/onNotice/onForked — see the seam comment
    // above _attachEngine) has no "output/activity" signal, only status-text/notice/resolution
    // events — so there is no way to detect that moment without editing ext_vt.js. It stays
    // cleared only by _resetPaneChrome() or another manual renderer switch, same as before.
    el.blank.hidden = next !== "xterm";
    _updateFootnote();
  }
  function _syncRendererSeg() {
    el.rendererSeg.querySelectorAll("[data-renderer]").forEach(function (btn) {
      var active = btn.getAttribute("data-renderer") === st.renderer;
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  // ===== theme — CR's own Light/Dark, duplicated here per doc 05 (the terminal overlay covers
  // the top bar). The PTY pane itself never light-themes regardless of this toggle — see FIX 1's
  // _applyDarkTheme above for how the live engine is kept forced-dark via handle.setTheme(). =====
  function _cycleTheme() {
    if (!ctx || !ctx.theme) return;
    var cur = ctx.theme.get ? ctx.theme.get() : "dark";
    ctx.theme.set(cur === "light" ? "dark" : "light");
  }
  function _syncThemeBtn() {
    if (!el.themeBtn || !ctx || !ctx.theme) return;
    var cur = ctx.theme.get ? ctx.theme.get() : "dark";
    var icon = el.themeBtn.querySelector(".cr-emo");
    if (icon) icon.textContent = cur === "light" ? "🌙" : "☀️";
  }

  // ===== model / effort — dialogs own the picker UI; this file performs the actual inject,
  // via the SAME public route ContextBar._pickModel/_pickEffort already use directly. ========
  function _openModelDialog() {
    ctx.dialog("model", {
      current: st.model,
      ladder: MODEL_LADDER,
      onPick: function (name) { _injectSlash("/model " + name, "Couldn't switch model"); },
    });
  }
  function _openEffortDialog() {
    ctx.dialog("effort", {
      current: st.effort,
      ladder: EFFORT_LADDER,
      onPick: function (level) { _injectSlash("/effort " + level, "Couldn't switch effort"); },
    });
  }
  function _injectSlash(text, failLabel) {
    if (!st.tty) { showToast(failLabel + ": no terminal attached"); return; }
    post("/api/term/inject", { tty: st.tty, text: text, submit: true, clear_first: true })
      .then(j).then(function (res) {
        if (res.ok && res.j && res.j.ok === true) return;
        var reason = (res.j && res.j.error) ||
          (res.status === 404 ? "that route isn't available in this build yet" :
           res.status === 400 ? "the terminal rejected that request" :
           "the terminal didn't confirm the switch");
        showToast(failLabel + " — " + reason);
      }).catch(function () { showToast("Couldn't reach the server — the switch wasn't sent"); });
  }

  // ===== ⧉ Copy — uses the mounted engine's real handle.copyBuffer() (see the seam comment above
  // _attachEngine) when one is attached. The selection-only fallback below is for the one case
  // where there is no engine handle at all — the classic-overlay fallback path in _openInline
  // above, which never returns a handle to this file. ==========================================
  function _copyPane() {
    if (st.engineHandle && typeof st.engineHandle.copyBuffer === "function") {
      Promise.resolve(st.engineHandle.copyBuffer()).then(function (text) {
        if (text) return navigator.clipboard.writeText(text);
      }).then(function () { showToast("Copied."); }).catch(function () { showToast("Couldn't copy."); });
      return;
    }
    var sel = window.getSelection ? window.getSelection().toString() : "";
    if (!sel) { showToast("Nothing selected to copy."); return; }
    navigator.clipboard.writeText(sel).then(function () { showToast("Copied selection."); })
      .catch(function () { showToast("Couldn't copy."); });
  }

  // ===== ■ Kill — POST /api/term/close, the same SIGKILL-the-process-group route the manage
  // panel's ✕ uses. This is a REAL kill, unlike closing the terminal screen (close(), above). ===
  function _killCurrent() {
    if (!st.tty) { showToast("No terminal attached."); return; }
    var tty = st.tty;
    post("/api/term/close", { tty: tty }).then(function (r) {
      if (!r.ok) { showToast("Failed to kill terminal."); return; }
      showToast("Terminal killed.");
      close();
    }).catch(function (e) { showToast("Failed to reach the server: " + e); });
  }

  // ===== fork lineage — reads the SAME d.continued_as/d.continued_from fields app.js's own
  // renderForkLinks() already reads off GET /api/session (registry.py, every provider). No new
  // endpoint: this is exactly the shared session-detail dict conventions rule 3/4 already ships.
  function _openLineageDialog() {
    if (!st.sessionId) return;
    fetch("/api/session?id=" + encodeURIComponent(st.sessionId)).then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || d.error) return;
        ctx.dialog("fork-lineage", {
          sid: st.sessionId,
          continuedAs: d.continued_as || null,
          continuedFrom: d.continued_from || null,
          onOpen: function (targetSid) { if (ctx.go) ctx.go("detail", targetSid); },
        });
      }).catch(function () {});
  }

  // ===== header info: cwd + resume command, from the session-detail dict =====================
  function _loadHeaderInfo(sid) {
    fetch("/api/session?id=" + encodeURIComponent(sid)).then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || d.error || st.sessionId !== sid) return;
        var m = d.meta || {};
        st.cwd = m.cwd || m.project || null;
        el.cwd.textContent = st.cwd || "";
        var resumable = isClaudeId(sid);
        el.resumeHere.hidden = !resumable;
        el.extResume.hidden = !resumable || !localOnly();
        if (resumable) {
          st.resumeCmd = "claude --resume " + sid;
          el.resumecmd.textContent = st.resumeCmd;
          el.resumecmd.hidden = false;
        } else {
          el.resumecmd.hidden = true;
        }
        _syncControlVisibility();
      }).catch(function () {});
  }
  function _syncControlVisibility() {
    var local = localOnly();
    el.extTerminal.hidden = !local || extAllowed === false;
    el.extResume.hidden = !local || extAllowed === false || !isClaudeId(st.sessionId);
    if (local && extAllowed === null) _probeExternal();
  }

  // ===== status bar readout ==================================================================
  function _readContextUsage(d) {
    var c = d && d.context;
    if (!c || typeof c.current !== "number" || !(c.current >= 0)) return null;
    var limit = (typeof c.limit === "number" && c.limit > 0) ? c.limit : null;
    var pct = (typeof c.pct === "number") ? c.pct : null;
    return { current: c.current, limit: limit, pct: pct };
  }
  function _matchLadderModel(raw) {
    if (!raw) return null;
    var low = String(raw).toLowerCase();
    for (var i = 0; i < MODEL_LADDER.length; i++) {
      if (low.indexOf(MODEL_LADDER[i]) !== -1) return MODEL_LADDER[i];
    }
    return null;
  }
  function _applySessionData(d) {
    var meta = (d && d.meta) || {};
    st.model = _matchLadderModel(meta.model);
    st.effort = (typeof meta.effort === "string" && meta.effort) ? meta.effort : null;
    st.ctx = _readContextUsage(d);
    st.cumulative = (d && d.tokens) ? ((d.tokens.in | 0) + (d.tokens.out | 0)) : 0;
    _syncStatusBar();
  }
  function _syncStatusBar() {
    // Model/effort only ever appear while a Claude CLI is actually foreground on this pty
    // (doc 05: "A slash command must never land on a bash prompt.") — never derived from `mode`.
    el.modelPill.hidden = !st.attached;
    el.effortPill.hidden = !st.attached;
    // Hide "Open terminal here" / "Resume terminal here" once a terminal is actually attached
    if (el.primaryGroup) el.primaryGroup.hidden = st.attached;
    if (st.attached) {
      el.modelPill.textContent = "model · " + (st.model || "—");
      el.effortPill.textContent = "effort · " + (st.effort || "—");
    }
    var html = "";
    if (st.ctx) {
      html += '<span class="cr-term-ctxused">context ' + esc(fmtTok(st.ctx.current)) + "</span>";
      // Doc 05: "A percentage bar appears beside the context number ONLY when the tool records a
      // context limit." Claude never does, so this stays hidden for every Claude session today.
      if (st.ctx.pct !== null) {
        var pct = Math.max(0, Math.min(100, st.ctx.pct));
        html += '<span class="cr-term-ctxbarwrap"><span class="cr-term-ctxbarfill" style="width:' +
          pct + '%"></span></span><span>' + Math.round(st.ctx.pct) + "%</span>";
      }
    }
    if (st.cumulative > 0) {
      html += '<span class="cr-term-ctxcum">cumulative ' + esc(fmtTok(st.cumulative)) + "</span>";
    }
    el.ctxreadout.innerHTML = html;
    var hasAnything = st.attached || !!st.ctx || st.cumulative > 0;
    el.status.hidden = !(st.tty && hasAnything);
  }

  // ===== notice banner ========================================================================
  function _syncNotice() {
    el.notice.hidden = !st.notice;
    if (st.notice) el.noticeText.textContent = st.notice;
  }

  // ===== footnote — dynamic renderer-parity disclaimer, per doc 05's closing section ==========
  function _updateFootnote() {
    if (!el.footnote) return;
    if (st.renderer === "xterm") {
      el.footnote.textContent =
        "xterm.js — correct wide-character width and true colour; no server-backed scrollback.";
    } else {
      el.footnote.textContent =
        "Built-in grid — repaints in full on attach, server-backed scrollback; no true colour.";
    }
  }

  // ===== polling — mirrors ContextBar.start()'s own cadence/endpoints (2s, folded into ONE
  // timer), only while a terminal screen is actually open. This is the same "extra round trip
  // while a panel is active" precedent ext_vt.js's own ContextBar already established; it is not
  // a NEW per-panel poll on top of the app's main /api/session cycle. =========================
  function _startPoll() {
    _stopPoll();
    var gen = ++pollGen;
    function tick() {
      if (gen !== pollGen || !st.open || !st.sessionId) return;
      fetch("/api/session?id=" + encodeURIComponent(st.sessionId))
        .then(function (r) { return r.json(); })
        .then(function (d) { if (gen === pollGen && d && !d.error) _applySessionData(d); })
        .catch(function () {});
      if (st.tty) {
        fetch("/api/term/attached?tty=" + encodeURIComponent(st.tty))
          .then(function (r) { return r.ok ? r.json() : { claude_attached: false }; })
          .then(function (jj) {
            if (gen !== pollGen) return;
            st.attached = !!(jj && jj.claude_attached);
            _syncStatusBar();
          }).catch(function () { if (gen === pollGen) { st.attached = false; _syncStatusBar(); } });
      }
      _refreshRunningList();
    }
    tick();
    pollTimer = setInterval(tick, 2000);
  }
  function _stopPoll() {
    pollGen++;
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  // ===== theme-change reactivity (ctx event bus, per shared contract) ========================
  // Internal bus event is 'theme:changed' (matches cr_board.js's listener) — the
  // document-level 'themechange' CustomEvent is a SEPARATE, classic-facing signal
  // (ext_vt.js depends on it) that ext_cr_boot.js still dispatches alongside this.
  function _wireThemeReactivity() {
    if (ctx && typeof ctx.on === "function") {
      ctx.on("theme:changed", _syncThemeBtn);
    }
  }

  // Close (detach, not kill — same as the ✕ button) when the whole Control Room UI is left for
  // classic — otherwise this overlay's inline engine keeps its SSE stream open indefinitely
  // after the user has navigated away from the new UI entirely.
  function _wireLifecycle() {
    if (ctx && typeof ctx.on === "function") {
      ctx.on("ui:modeChanged", function (payload) {
        if (payload && payload.mode !== "next" && st.open) close();
      });
    }
  }

  // ===== public module surface ===============================================================
  window.CR.term = {
    mount: function (rootEl, ctxIn) {
      root = rootEl;
      ctx = ctxIn;
      _build();
      _updateFootnote();
      _syncThemeBtn();
      _wireThemeReactivity();
      _wireLifecycle();
    },
    open: open,
    close: close,
    // Public entry points for the board's "Terminals" nav item and "+ New session" action
    // (cr_board.js emits 'nav:terminals' / 'session:new'; ext_cr_boot.js bridges those bus
    // events to these two methods). Thin wrappers over the same private handlers the
    // toolbar's own ☰/+ buttons already call.
    openManage: function () { _openManageDialog(); },
    openPicker: function (mode) { _openDirectoryPicker(mode === "new" ? "new" : "cwd"); },
    // Cheap, idempotent — called on the host's 2s poll. NOTE: the exact shape of the host-level
    // `state` object isn't specified by the shared contract beyond "cheap, idempotent"; this
    // module treats it defensively as an OPTIONAL supplement (e.g. a fresh session-list array for
    // label lookups elsewhere) and never lets its absence break anything, since this file already
    // runs its own terminal-scoped poll (see _startPoll) for everything it strictly needs.
    update: function (state) {
      if (!st.open) return;
      if (state && Array.isArray(state.sessions)) {
        // no-op placeholder: nothing in this module currently needs the session list directly,
        // but the hook is honoured so a future dialog payload (e.g. resolving a peeked terminal's
        // session title) can read it without a new contract change.
      }
    },
  };
})();
