// Tier 3 — in-browser terminal: grid painter, key capture, the modal, and the standalone-tab
// mode. Registers into EXT and mounts into #ext_vt, exactly like ext_launch.js/ext_run.js;
// concatenated into the same top-level <script> as app.js, so `cur`, `EXT`, `esc` and `toast`
// below are the real globals from app.js, not a guess at their shape (see ext_launch.js's own
// header comment for the same note).
//
// Exposes window.ExtVT = {open(sid, mode)} so ext_launch.js's two buttons can drive this module
// without either file reaching into the other's internals.
//
// ===== SERVER CONTRACT THIS FILE ASSUMES (term_vt.py did not exist yet when this was written —
// reconcile against the real Screen.snapshot()) =====================================
//   POST /api/term/pty    {session, cols, rows, mode: "cwd"|"resume"} -> {tty: "<id>"}
//     NOTE: the plan's own route table only lists {session, cols, rows}, but the plan's PROSE
//     requires distinguishing "claude --resume <sid>" from a plain shell, and there is no way to
//     convey that without an extra field. `mode` is added here on top of the documented shape;
//     term_vt.py's route must read it (or this needs reconciling some other way).
//   POST /api/term/keys   {tty, data: <base64 of UTF-8 bytes>} -> {ok:true}
//   POST /api/term/resize {tty, cols, rows} -> {ok:true}
//   GET  /api/term/screen?tty=<id> -> SSE, unnamed "message" events (no `event:` field assumed),
//     one JSON object per event: {v, rows: [[row_index, "text", runs], ...], cursor: [r, c], alt}
//     - Each SSE connection is assumed to start from "nothing sent yet", so the FIRST event on a
//       fresh connection carries every currently-populated row (a reconnect therefore repaints
//       cleanly with no stale cells left behind — this file never sends a `since` parameter).
//     - CONFIRMED against the real Screen.snapshot() (term_vt.py, another worktree): `text` is
//       RIGHT-TRIMMED, not padded — trailing cells that are both a plain space and default-styled
//       are dropped, so a 100-col row showing "hi" arrives as `text="hi"`, not "hi" + 98 spaces.
//       This file pads back out to `cols` when painting (see _paintRow) and never assumes a run
//       stops at `text.length` — a run may extend past it (an erased-but-still-styled tail, e.g.
//       a background colour on a cleared line), and that padding must render with THAT run's
//       style, not as plain default blank.
//     - `runs` is assumed to be a list of half-open column ranges over `text`:
//         [[start_col, end_col, sgr], ...]
//       where `sgr` is the ABSOLUTE set of SGR parameters active for that run, written the same
//       way they'd appear inside `ESC[<sgr>m` — a semicolon-separated list of integers, e.g.
//       "1;31" for bold red, "" for no attributes. This is a snapshot of resolved cell state,
//       not a byte-stream to replay, so (unlike ext_run.js's sgrClass, which walks a live ANSI
//       stream and needs reset/toggle semantics) there is no "reset" concept here — each run
//       just says what's active over that span. An empty/absent `runs` array means "plain text,
//       one run covering the whole row".
//     - `cursor` is [row, col], both 0-based. `alt` is a bool (alt-screen active).
// The SGR decoding is isolated in ONE function, sgrRunClass(), below — that's the piece that
// must match term_vt.Screen.snapshot() once it exists.
//
// ===== PARITY EXTENSIONS (this session) ================================================
//   GET /api/term/scrollback?tty=<id>&offset=<N>&rows=<M> -> {"rows": [[i, text, runs], ...],
//     "total": int, "offset": int}
//   Same row/run encoding as the /api/term/screen contract above (right-trimmed text, runs are
//   half-open [start, end, sgr] ranges). `i` is the row index WITHIN the returned view (0..M-1),
//   never an absolute history line number. offset=0 means "the live viewport"; offset=N means "N
//   lines scrolled back from there". The server clamps the requested offset — the response's
//   `offset` is the clamped value and is what this file trusts, never the value it asked for.
//   `total` sizes the scrollbar.
//
//   Two fields below are read DEFENSIVELY because the term_vt.py in this worktree does not emit
//   them yet (confirmed by reading Screen.snapshot() / _set_private_mode() / the C0 dispatcher
//   there before writing this): `msg.cursor_visible` (DECTCEM `?25` — Screen tracks
//   `self.cursor_visible` internally but snapshot() only returns v/rows/cursor/alt today) and
//   `msg.bell` (a monotonic count of BEL bytes seen — BEL is currently consumed as a no-op C0
//   control and never surfaces anywhere in snapshot()). Both default to "assume visible" / "never
//   rang" until the server adds them; this file picks them up with no further client change once
//   it does. Bracketed-paste state (`?2004`) is in the same boat — `_set_private_mode` treats it
//   as a no-op private mode, so there is currently NO server signal for whether the running
//   program wants pasted text wrapped in `ESC[200~ … ESC[201~`. Read defensively as
//   `msg.bracketed_paste` (default false) rather than guessing a value with no server backing.
//
// ===== CONTEXT BAR (this session): two more contracts =================================
//   POST /api/term/inject {tty, text, submit: true, clear_first: true} -> {ok: true, ...}
//     Waits for the terminal to go quiet, types `text`, then sends Enter separately (re-sending
//     it if the TUI swallows it). May not exist yet in this worktree — a non-2xx/non-{ok:true}
//     response surfaces a toast (see ContextBar.prototype._pickModel below), never silently.
//   GET /api/session?id=<sid> gains a `context` field. CONFIRMED (reconciled with the server
//   agent mid-build -- the first draft of this file guessed `{used, limit}` with an
//   auto-computed percentage; that guess is gone, this is the real, shipped shape):
//     d.context = { current: <int|null, LATEST turn's usage only (in + cache_read +
//                             cache_creation) -- "am I about to run out", not a running total>,
//                   limit:   <int|null, the context window size, ONLY when the tool's own logs
//                             state one -- Claude Code sessions never do (context_management is
//                             null throughout), so this is routinely null for exactly the
//                             sessions the terminal is most used with>,
//                   pct:     <float|null, SERVER-COMPUTED, only when both of the above are known
//                             and limit > 0 -- never fabricated here, never re-derived from
//                             current/limit by this file> }
//   See readContextUsage() below, the ONE function that reads it.
//   `d.tokens = {in, out}` (the session-CUMULATIVE total, monotonically increasing -- a
//   DIFFERENT number with a different meaning) already ships today in every provider and is
//   read directly in ContextBar.prototype._applySessionData, not through readContextUsage().
//
// ===== SECOND RENDER PATH (this session): TRACKER_TERM_RENDERER =========================
//   POST /api/term/pty's response gained a `renderer` key ("grid"|"xterm", server-owned -- see
//   config.TERM_RENDERER / term_vt.py's big comment above raw_stream()). GET /api/term/renderer
//   -> {"renderer": ...} serves the same value for a reconnecting standalone ?tty= tab, which
//   never calls /api/term/pty again. GET /api/term/raw?tty=<id> is the xterm.js counterpart to
//   /api/term/screen: SSE of `data: <base64 of raw PTY bytes>\n\n`, no JSON envelope, no
//   since/versioning -- see XtermTerminal below (search "SECOND, switchable render path") for the
//   client half and its own documented gaps vs. the grid renderer.
(function () {
  var esc = window.esc || function (s) { return (s || "").replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; }); };

  // ===== SGR runs -> CSS classes (see the contract comment above the IIFE) =====
  // Mirrors ext_run.js's sgrClass() numeric ranges 1:1 so Tier 2 and Tier 3 render the same
  // colours from the same SGR codes -- but as an ABSOLUTE mapping (one run in, one class string
  // out), not a delta/reset walk over a byte stream, because a Screen run already IS the
  // resolved state for that span.
  function sgrRunClass(sgr) {
    var out = [];
    (sgr || "").split(";").forEach(function (p) {
      if (p === "") return;
      var n = parseInt(p, 10);              // classes come from parsed integers only
      if (!isFinite(n)) return;
      if (n === 1) out.push("vtb");
      else if (n === 3) out.push("vti");
      else if (n === 4) out.push("vtu");
      else if (n === 7) out.push("vtr");
      else if ((n >= 30 && n <= 37) || (n >= 90 && n <= 97)) out.push("vtf" + n);
      else if (n >= 40 && n <= 47) out.push("vtg" + n);
    });
    return out.join(" ");
  }

  // ===== key capture =====================================================
  // Control/navigation keys are handled here on keydown (preventDefault so they never reach the
  // textarea's value). Printable text — including dead keys, IME composition and paste — is
  // deliberately NOT handled here; it's read back off the textarea's `input` event instead
  // (see Terminal.prototype._onInput), which is the only way to get composed/pasted Unicode
  // right without re-implementing keyboard layouts.
  function keyToBytes(ev) {
    if (ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      var k = ev.key;
      if (/^[a-zA-Z]$/.test(k)) return String.fromCharCode(k.toUpperCase().charCodeAt(0) & 0x1f);
      if (k === "[") return "\x1b";
      if (k === "]") return "\x1d";
      if (k === "\\") return "\x1c";
      if (k === "^") return "\x1e";
      if (k === "_") return "\x1f";
    }
    if (ev.altKey && !ev.ctrlKey && !ev.metaKey && ev.key.length === 1) return "\x1b" + ev.key;
    switch (ev.key) {
      case "Enter": return "\r";
      case "Backspace": return "\x7f";
      case "Tab": return ev.shiftKey ? "\x1b[Z" : "\t";
      case "Escape": return "\x1b";
      case "ArrowUp": return "\x1b[A";
      case "ArrowDown": return "\x1b[B";
      case "ArrowRight": return "\x1b[C";
      case "ArrowLeft": return "\x1b[D";
      case "Home": return "\x1b[H";
      case "End": return "\x1b[F";
      case "PageUp": return "\x1b[5~";
      case "PageDown": return "\x1b[6~";
      case "Delete": return "\x1b[3~";
      case "Insert": return "\x1b[2~";
    }
    return null;   // not ours: let the browser handle it (Cmd+C/V, plain chars, dead keys, …)
  }

  function b64utf8(s) {
    return btoa(unescape(encodeURIComponent(s)));
  }
  function postKeys(tty, s) {
    return fetch("/api/term/keys", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tty: tty, data: b64utf8(s) })
    });
  }
  function postResize(tty, cols, rows) {
    return fetch("/api/term/resize", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tty: tty, cols: cols, rows: rows })
    }).catch(function () { });
  }
  function fetchScrollback(tty, offset, rows) {
    return fetch("/api/term/scrollback?tty=" + encodeURIComponent(tty) + "&offset=" + offset + "&rows=" + rows)
      .then(function (r) { return r.json(); });
  }

  // ===== sizing: report ACTUAL rendered cols/rows, not a guess =====
  var _measureCanvas = null;
  function cellSize(pane) {
    var cs = getComputedStyle(pane);
    if (!_measureCanvas) _measureCanvas = document.createElement("canvas");
    var ctx = _measureCanvas.getContext("2d");
    ctx.font = (cs.fontStyle !== "normal" ? cs.fontStyle + " " : "") + (cs.fontWeight || "400") + " " + cs.fontSize + " " + cs.fontFamily;
    var w = ctx.measureText("MMMMMMMMMM").width / 10;
    var h = parseFloat(cs.lineHeight);
    if (!h || isNaN(h)) h = parseFloat(cs.fontSize) * 1.3;
    return { w: Math.max(1, w), h: Math.max(1, h) };
  }
  function computeColsRows(pane) {
    var cell = cellSize(pane);
    // The pane is PADDED (.vtpane: 8px 10px), so its border box is wider/taller than the area the
    // rows are actually drawn in. Read the real padding off the computed style -- one source of
    // truth with the CSS, and it survives a padding change -- then use it TWICE:
    //   1. subtract it here. cols/rows used to be measured against the *unpadded* box (padX/padY
    //      were declared and then never subtracted), overcounting by ~2 cols / ~1 row, so the PTY
    //      believed in a bottom row that overflow:hidden was clipping -- exactly the row the
    //      cursor usually sits on.
    //   2. hand back the top/left padding as padX/padY, so _layoutCursor can put the absolutely
    //      positioned .vtcursor on the same origin as the in-flow .vtrows. See _layoutCursor.
    var cs = getComputedStyle(pane);
    var padL = parseFloat(cs.paddingLeft) || 0, padT = parseFloat(cs.paddingTop) || 0;
    var padX = padL + (parseFloat(cs.paddingRight) || 0);
    var padY = padT + (parseFloat(cs.paddingBottom) || 0);
    var rect = pane.getBoundingClientRect();
    var innerW = (rect.width || pane.clientWidth || (80 * cell.w + padX)) - padX;
    var innerH = (rect.height || pane.clientHeight || (24 * cell.h + padY)) - padY;
    var cols = Math.max(20, Math.min(300, Math.floor(innerW / cell.w)));
    var rows = Math.max(6, Math.min(120, Math.floor(innerH / cell.h)));
    return { cols: cols, rows: rows, cellW: cell.w, cellH: cell.h, padX: padL, padY: padT };
  }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  // ===== shared zoom toolbar: ITS OWN flex row, ABOVE the pane -- never an overlay on top of
  // terminal output. LAYOUT-BUG FIX (see ext_vt.css's .vttoolbar comment for the full story): the
  // A-/A+ controls used to be absolutely positioned inside .vtpane's top-right corner, overlapping
  // row 0's real content. Both renderers (Terminal below and XtermTerminal further down) build
  // this the same way and append it as a sibling BEFORE their own pane, so the fix covers both
  // paths from one place rather than being reimplemented per-renderer. =====
  function buildToolbar(onZoomOut, onZoomIn, onAfterZoom) {
    var bar = document.createElement("div");
    bar.className = "vttoolbar";
    var zoomOut = document.createElement("span");
    zoomOut.className = "vtzoombtn";
    zoomOut.textContent = "A−"; zoomOut.title = "Smaller (Ctrl/Cmd -)";
    var zoomIn = document.createElement("span");
    zoomIn.className = "vtzoombtn";
    zoomIn.textContent = "A+"; zoomIn.title = "Larger (Ctrl/Cmd +)";
    zoomOut.addEventListener("click", function () { onZoomOut(); onAfterZoom(); });
    zoomIn.addEventListener("click", function () { onZoomIn(); onAfterZoom(); });
    bar.appendChild(zoomOut);
    bar.appendChild(zoomIn);
    return bar;
  }

  // ===== Terminal: one live grid + key capture, mounted into any container =====
  function Terminal(container, ttyId) {
    this.ttyId = ttyId;
    this.cols = 0; this.rows = 0;
    this.grid = []; this.rowEls = [];
    this.cursor = [0, 0];
    this.alt = false;
    this.version = 0;
    this.es = null;
    this.composing = false;
    this.cellW = 7.2; this.cellH = 17;
    this.padX = 0; this.padY = 0;          // .vtpane's real padding; filled by measureAndResize
    this._sized = false;
    this._onStatusChange = null;
    // `starting`: true only while a mode="resume" pane is still coming up after the server's
    // refused-resume auto-recovery (see openVT, which seeds this off the POST /api/term/pty
    // response before this pane's EventSource even opens, and _applyPatch below, which tracks the
    // SSE stream's own per-frame `starting` key once it's open). Server-owned (conventions rule 5).
    this.starting = false;
    this.focused = false;
    this.cursorVisible = true;             // DECTCEM ?25 -- see the header comment's caveat
    this.bracketedPaste = false;           // ?2004 -- see the header comment's caveat
    this._bellSeen = null;                 // msg.bell baseline -- see the header comment's caveat
    this._fontPx = null; this._linePx = null;   // null == use the CSS default, unzoomed
    // ---- scrollback view state: `this.grid` above stays the LIVE model always (fed by every SSE
    // patch, unconditionally); `this.historyGrid`/`viewingHistory` is a separate, frozen snapshot
    // painted INSTEAD of the live grid while scrolled back, so a live diff arriving mid-scroll
    // never yanks the view back down -- see _applyPatch and _paintRow below. ----
    this.viewingHistory = false;
    this.historyGrid = null;
    this.scrollOffset = 0;
    this.scrollTotal = 0;
    this.pendingNewOutput = false;
    this._scrollReqSeq = 0;
    // ---- async notices streamed via SSE frames (server sends {seq, text} for each notice) ----
    this._noticeHighestSeq = -1;           // tracks highest seq seen to dedup re-sent frames
    this._noticeEls = [];                  // array of displayed notice <div> elements (stacked)

    container.innerHTML = "";
    var self = this;
    var toolbarEl = buildToolbar(
      function () { self._zoom(-1); },
      function () { self._zoom(1); },
      function () { input.focus(); }
    );
    var pane = document.createElement("div");
    pane.className = "vtpane";
    var rowsEl = document.createElement("div");
    rowsEl.className = "vtrows";
    var cursorEl = document.createElement("div");
    cursorEl.className = "vtcursor";
    var newOutEl = document.createElement("div");
    newOutEl.className = "vtnewout";
    newOutEl.textContent = "▼ new output";
    var scrollbarEl = document.createElement("div");
    scrollbarEl.className = "vtscrollbar";
    var scrollThumbEl = document.createElement("div");
    scrollThumbEl.className = "vtscrollthumb";
    scrollbarEl.appendChild(scrollThumbEl);
    // Deliberately NOT covering the pane (that was v1's whole selection blocker): a tiny,
    // off-screen textarea still captures every keystroke/paste/IME composition, but leaves the
    // real .vtrow text nodes underneath free for the browser's native mouse selection.
    var input = document.createElement("textarea");
    input.className = "vtinput";
    input.setAttribute("autocomplete", "off");
    input.setAttribute("autocapitalize", "off");
    input.setAttribute("autocorrect", "off");
    input.setAttribute("spellcheck", "false");
    input.setAttribute("aria-label", "Terminal input");
    pane.appendChild(rowsEl);
    pane.appendChild(cursorEl);
    pane.appendChild(scrollbarEl);
    pane.appendChild(newOutEl);
    pane.appendChild(input);
    container.appendChild(toolbarEl);
    container.appendChild(pane);

    this.pane = pane; this.rowsEl = rowsEl; this.cursorEl = cursorEl; this.input = input;
    this.newOutEl = newOutEl; this.scrollbarEl = scrollbarEl; this.scrollThumbEl = scrollThumbEl;

    this._scrollHistoryDebounced = debounce(function (offset) { self._scrollHistory(offset); }, 30);
    // No preventDefault here (requirement 2's whole point): blocking the mousedown default is
    // what stops native text selection from ever starting. Focusing the capture textarea on the
    // same event still routes the next keystroke to the PTY without touching the emerging
    // selection -- selection anchoring is driven by the browser off the ORIGINAL mousedown target
    // (a .vtrow text node now that the input no longer overlays the pane), not by DOM focus.
    pane.addEventListener("mousedown", function () { input.focus(); });
    pane.addEventListener("wheel", function (ev) { self._onWheel(ev); }, { passive: false });
    newOutEl.addEventListener("click", function () { self._scrollToBottom(); input.focus(); });
    input.addEventListener("focus", function () { self.focused = true; pane.classList.add("vtfocused"); });
    input.addEventListener("blur", function () { self.focused = false; pane.classList.remove("vtfocused"); });
    input.addEventListener("keydown", function (ev) { self._onKeyDown(ev); });
    input.addEventListener("input", function () { self._onInput(); });
    input.addEventListener("compositionstart", function () { self.composing = true; });
    input.addEventListener("compositionend", function () { self.composing = false; });
    try { input.focus(); } catch (e) { }
  }

  Terminal.prototype._resetGrid = function (cols, rows) {
    this.cols = cols; this.rows = rows;
    this.grid = []; this.rowEls = [];
    this.rowsEl.innerHTML = "";
    var frag = document.createDocumentFragment();
    for (var i = 0; i < rows; i++) {
      this.grid.push({ text: "", runs: [] });
      var el = document.createElement("div");
      el.className = "vtrow";
      frag.appendChild(el);
      this.rowEls.push(el);
    }
    this.rowsEl.appendChild(frag);
    this._applyRowSizing();   // freshly-created rows must match any active font zoom immediately
  };

  Terminal.prototype.measureAndResize = function () {
    var m = computeColsRows(this.pane);
    this.cellW = m.cellW; this.cellH = m.cellH;
    this.padX = m.padX; this.padY = m.padY;
    if (!this._sized || m.cols !== this.cols || m.rows !== this.rows) {
      this._sized = true;
      this._resetGrid(m.cols, m.rows);
      postResize(this.ttyId, m.cols, m.rows);
    }
    this._layoutCursor();
    return m;
  };

  Terminal.prototype.attach = function () {
    var self = this;
    requestAnimationFrame(function () {
      self.measureAndResize();
      self._openStream();
    });
  };

  Terminal.prototype._openStream = function () {
    var self = this;
    if (self.es) self.es.close();
    if (self._onStatusChange) self._onStatusChange("connecting…");
    self.es = new EventSource("/api/term/screen?tty=" + encodeURIComponent(self.ttyId));
    self.es.onopen = function () { if (self._onStatusChange) self._onStatusChange("connected"); };
    self.es.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      self._applyPatch(msg);
    };
    self.es.onerror = function () { if (self._onStatusChange) self._onStatusChange("reconnecting…"); };
  };

  Terminal.prototype._applyPatch = function (msg) {
    if (!msg) return;
    if (typeof msg.v === "number") this.version = msg.v;
    if (msg.alt !== undefined) { this.alt = !!msg.alt; this.pane.classList.toggle("vtalt", this.alt); }
    // Defensive reads for fields the server doesn't emit yet -- see the header comment. Both no-op
    // (stay at their existing value) until term_vt.py starts sending them.
    if (msg.cursor_visible !== undefined) this.cursorVisible = !!msg.cursor_visible;
    if (msg.bracketed_paste !== undefined) this.bracketedPaste = !!msg.bracketed_paste;
    if (typeof msg.bell === "number") {
      if (this._bellSeen !== null && msg.bell !== this._bellSeen) this._flashBell();
      this._bellSeen = msg.bell;
    }
    // `starting`: absent key (older server, or the standalone raw page which never sends this
    // envelope shape at all) is treated as "not starting" -- never let a missing field wedge the
    // pane in a starting state forever. While starting the server withholds `rows` entirely, so
    // there's nothing to paint here either way; the moment it flips false the very next frame
    // carries every withheld row (the server doesn't advance our version cursor while starting),
    // so that arrives and paints itself via the normal row loop below -- no refetch, no reopening
    // the stream. We do force one header refresh on the false-edge, since _onStatusChange (see
    // openVT) was suppressing real connection status text the whole time we were starting.
    var wasStarting = this.starting;
    this.starting = (msg.starting !== undefined) ? !!msg.starting : false;
    this.pane.classList.toggle("vtstarting", this.starting);
    if (wasStarting && !this.starting && this._onStatusChange) this._onStatusChange("connected");
    var rows = msg.rows || [];
    for (var i = 0; i < rows.length; i++) {
      var entry = rows[i];
      var r = entry[0] | 0;
      if (r < 0 || r >= this.grid.length) continue;   // a resize raced the stream -- drop stale rows
      this.grid[r] = { text: String(entry[1] || ""), runs: entry[2] || [] };
    }
    if (msg.cursor && msg.cursor.length === 2) {
      this.cursor = [msg.cursor[0] | 0, msg.cursor[1] | 0];
    }
    // Async notices: process if present (server sends [{"seq": <int>, "text": "<str>"}, ...])
    // Defensively handle missing/malformed notices (older server sends nothing, or key absent).
    var notices = msg.notices;
    if (Array.isArray(notices)) {
      for (var k = 0; k < notices.length; k++) {
        var notice = notices[k];
        var seq = (typeof notice.seq === "number") ? (notice.seq | 0) : -1;
        var text = (typeof notice.text === "string") ? notice.text : "";
        // Dedupe: skip if we've already seen this seq or higher
        if (seq > this._noticeHighestSeq) {
          this._noticeHighestSeq = seq;
          this._displayNotice(text);
        }
      }
    }
    // The single most infuriating thing a terminal can do (requirement 1): while the user is
    // scrolled back into history, a live SSE diff must NEVER repaint the screen out from under
    // them. `this.grid` above is still kept current either way (so the live view is correct and
    // instant the moment they return to it) -- only the DOM paint and cursor layout are gated.
    if (this.viewingHistory) {
      if (rows.length) { this.pendingNewOutput = true; this._updateNewOutputBadge(); }
      return;
    }
    for (var j = 0; j < rows.length; j++) this._paintRow(rows[j][0] | 0);
    this._layoutCursor();
  };

  // `text` arrives RIGHT-TRIMMED (see the contract comment at the top of this file) — it may be
  // shorter than `this.cols`. We always rebuild the row's ENTIRE innerHTML from scratch here
  // (never patch/append a prefix into existing markup), so a row that shrank can never leave a
  // previous longer render's glyphs sitting to its right — replacing innerHTML wholesale IS the
  // fix for that ghosting class of bug. What still has to be done explicitly is padding the
  // output out to the full `cols` width, because nothing else provides that: a run may extend
  // past `text.length` (an erased-but-still-styled tail, e.g. a background colour on a cleared
  // line) and that padding must carry THAT run's style, not be assumed blank/default.
  function _padSpaces(n) {
    return n > 0 ? new Array(n + 1).join(" ") : "";
  }
  Terminal.prototype._paintRow = function (r) {
    // Paints from the live model normally, or from the frozen scrollback snapshot while the user
    // is scrolled back (see the constructor's scrollback-view comment) -- the two callers
    // (_applyPatch for live, _paintHistory below for scrollback) never need their own copy of the
    // run/pad/escape logic below, which is exactly what keeps that logic in ONE place.
    var row = (this.viewingHistory ? this.historyGrid : this.grid)[r], el = this.rowEls[r];
    if (!row || !el) return;
    var text = row.text || "";
    var cols = this.cols;
    var runs = (row.runs && row.runs.length) ? row.runs : [[0, text.length, ""]];
    var html = "", pos = 0;
    for (var i = 0; i < runs.length; i++) {
      var run = runs[i];
      var s = Math.max(0, run[0] | 0), e = Math.max(0, run[1] | 0);   // NOT clamped to text.length —
      if (e <= s) continue;                                          // a run may extend past it
      if (s > pos) { html += esc(_padSpaces(s - pos)); pos = s; }     // gap before this run: default blank
      var cls = sgrRunClass(run[2]);
      var glyphs = s < text.length ? text.slice(s, Math.min(e, text.length)) : "";
      var tailPad = Math.max(0, e - Math.max(s, text.length));        // the part of this run past text.length
      var chunk = esc(glyphs) + esc(_padSpaces(tailPad));
      html += cls ? ('<span class="' + cls + '">' + chunk + '</span>') : chunk;
      pos = e;
    }
    if (pos < cols) html += esc(_padSpaces(cols - pos));   // pad the rest of the row width, unstyled
    el.innerHTML = html;
  };

  Terminal.prototype._layoutCursor = function () {
    // DECTCEM (?25, defensive -- see header comment) and "no live cursor while viewing frozen
    // scrollback" both collapse to the same thing: hide the synthetic cursor element.
    this.cursorEl.style.visibility = (this.cursorVisible && !this.viewingHistory) ? "" : "hidden";
    // The row's rendered text is right-trimmed and shorter than `cols` far more often than not
    // (an empty line, a line right after a clear, …) — the cursor is routinely at a column past
    // `text.length` and must still land inside the pane rather than falling off the end, so we
    // clamp to `cols - 1` (the pane's own width), never to the current row's text length.
    var r = Math.max(0, Math.min(this.rows - 1, this.cursor[0]));
    var c = Math.max(0, Math.min(Math.max(0, this.cols - 1), this.cursor[1]));
    this.cursorEl.style.width = this.cellW + "px";
    this.cursorEl.style.height = this.cellH + "px";
    // .vtcursor is position:absolute inside .vtpane, so its top:0/left:0 origin is the pane's
    // PADDING box -- while .vtrows sits in normal flow at the CONTENT box, one padding further in.
    // Without adding that padding back the cursor drew 8px above and 10px left of the cell it
    // marks (visibly floating between the line above and the character before the real one).
    this.cursorEl.style.transform =
      "translate(" + (this.padX + c * this.cellW) + "px," + (this.padY + r * this.cellH) + "px)";
  };

  // Display an async notice streamed from the server. Maintains a stacked list of up to 3 notices
  // to avoid filling the pane; older notices are removed when a 4th arrives. Text is escaped
  // via textContent to prevent XSS. MOVED OUT OF THE PANE (inserted as siblings, not children)
  // to prevent consuming the pane's vertical space and clipping rows. measureAndResize() is
  // called whenever the notice list changes so the terminal renegotiates its row count.
  Terminal.prototype._displayNotice = function (text) {
    if (!text) return;
    if (!this.pane || !this.pane.parentNode) return;   // guard: terminal destroyed or pane not ready
    var maxNotices = 3;   // cap on displayed notices to prevent flooding the pane
    // Create a new notice element
    var el = document.createElement("div");
    el.className = "vtnotice";
    var span = document.createElement("span");
    span.textContent = text;   // textContent escapes HTML
    el.appendChild(span);
    // Add to the DOM as a sibling BEFORE .vtpane (outside the pane, not a child of it)
    this.pane.parentNode.insertBefore(el, this.pane);
    this._noticeEls.push(el);
    // Remove oldest notices if we exceed the cap
    while (this._noticeEls.length > maxNotices) {
      var oldest = this._noticeEls.shift();
      if (oldest && oldest.parentNode) oldest.parentNode.removeChild(oldest);
    }
    // Renegotiate rows because the pane is now shorter (notices consume space in the container)
    this.measureAndResize();
  };

  // Copy/paste/zoom are page-level UI actions, not terminal input -- they are intercepted here,
  // BEFORE the generic "any key returns to the live view" rule below, and each returns early
  // without reaching keyToBytes. Copy in particular MUST run first: _scrollToBottom() repaints
  // every row's innerHTML from scratch (see _paintRow), which destroys whatever DOM text nodes
  // the browser's live Selection was anchored to -- jumping to live before copying would silently
  // copy nothing.
  Terminal.prototype._onKeyDown = function (ev) {
    var k = ev.key;
    var copyCombo = (ev.metaKey && !ev.ctrlKey && !ev.altKey && (k === "c" || k === "C")) ||
                     (ev.ctrlKey && ev.shiftKey && !ev.metaKey && !ev.altKey && (k === "c" || k === "C"));
    if (copyCombo) {
      // Plain Ctrl+C (no Shift, no Meta) never reaches this branch -- it falls through to
      // keyToBytes below unconditionally, which is what makes it ALWAYS send SIGINT (\x03),
      // selection or not. That is the one thing this file must never get wrong.
      var sel = window.getSelection ? window.getSelection().toString() : "";
      ev.preventDefault();
      ev.stopPropagation();
      if (sel) this._copyText(sel);
      // no selection: nothing to copy, and neither Cmd+C nor Ctrl+Shift+C is a control code --
      // swallow it either way rather than falling into the ctrl-letter SIGINT-alike mapping below
      // (which would otherwise turn Ctrl+Shift+C into an accidental interrupt).
      return;
    }
    var pasteCombo = (ev.metaKey && !ev.ctrlKey && !ev.altKey && (k === "v" || k === "V")) ||
                      (ev.ctrlKey && ev.shiftKey && !ev.metaKey && !ev.altKey && (k === "v" || k === "V"));
    if (pasteCombo) {
      ev.preventDefault();
      ev.stopPropagation();
      if (this.viewingHistory) this._scrollToBottom();   // pasted text is about to hit the shell
      this._pasteFromClipboard();
      return;
    }
    if ((ev.metaKey || ev.ctrlKey) && !ev.shiftKey && !ev.altKey && (k === "+" || k === "=" || k === "-" || k === "_")) {
      ev.preventDefault();
      ev.stopPropagation();
      this._zoom(k === "-" || k === "_" ? -1 : 1);
      return;
    }
    // Requirement 1: any OTHER key, while scrolled into history, returns to the live view first --
    // like a real terminal (Shift+End's own "scroll to bottom" falls out of this for free: it's
    // just another key). Runs AFTER the intercepts above, on purpose (see the comment before this
    // function).
    if (this.viewingHistory) this._scrollToBottom();

    var bytes = keyToBytes(ev);
    if (bytes === null) return;             // printable/dead-key/IME: let it land in the textarea
    ev.preventDefault();
    // Deliberate fix for the Escape/close conflict (requirement 4): every key handled here,
    // Escape included, is stopped from bubbling to document — so app.js's own document-level
    // Escape handler (closeDiff/closeMsg/closeBgDrawer) and this file's own modal-Escape listener
    // (below) never see it while the terminal has focus. Escape only closes the modal when focus
    // is elsewhere (e.g. the user tabbed to the ✕ button first) — see the document keydown
    // listener near ExtVT's modal code.
    ev.stopPropagation();
    this._send(bytes);
  };
  Terminal.prototype._onInput = function () {
    if (this.composing) return;
    var v = this.input.value;
    if (v) {
      if (this.viewingHistory) this._scrollToBottom();   // e.g. a native right-click paste
      this._send(v);
      this.input.value = "";
    }
  };
  Terminal.prototype._send = function (s) {
    postKeys(this.ttyId, s);
  };
  Terminal.prototype.destroy = function () {
    if (this.es) { this.es.close(); this.es = null; }
    // Clean up any displayed notices and reset the sequence tracker
    var hadNotices = this._noticeEls.length > 0;
    for (var i = 0; i < this._noticeEls.length; i++) {
      var el = this._noticeEls[i];
      if (el && el.parentNode) el.parentNode.removeChild(el);
    }
    this._noticeEls = [];
    this._noticeHighestSeq = -1;
    // Renegotiate rows if notices were removed (the pane will expand to fill the space)
    if (hadNotices) this.measureAndResize();
  };
  // Generic focus entry point shared with XtermTerminal (see that class's own .focus) -- so
  // ContextBar's getInput() callback can hand back the TERMINAL object itself, one interface for
  // either renderer, instead of a DOM node whose shape differs between the two.
  Terminal.prototype.focus = function () {
    try { this.input.focus(); } catch (e) { }
  };

  // ===== mouse wheel: scrollback on the primary screen, arrow keys on the alt screen ==========
  // Full-screen programs (vim/less/top/…) own the alt screen and read arrow keys for their own
  // scrolling/navigation -- forwarding wheel-as-history there instead of as arrows is exactly the
  // "every full-screen program feels broken" bug the plan calls out.
  Terminal.prototype._onWheel = function (ev) {
    ev.preventDefault();   // never let it fall through to the page behind the modal
    var linesPerTick = Math.max(1, Math.round(Math.abs(ev.deltaY) / (this.cellH || 17)));
    if (this.alt) {
      var n = Math.min(3, linesPerTick);   // cap so a big trackpad flick doesn't spam the PTY
      var one = ev.deltaY > 0 ? "\x1b[B" : "\x1b[A", s = "";
      for (var i = 0; i < n; i++) s += one;
      this._send(s);
      return;
    }
    var next = ev.deltaY < 0 ? this.scrollOffset + linesPerTick : Math.max(0, this.scrollOffset - linesPerTick);
    this.scrollOffset = next;   // optimistic, so several quick ticks accumulate before the fetch lands
    if (next <= 0) { this._scrollToBottom(); return; }
    this.viewingHistory = true;   // freeze the live paint (see _applyPatch) as soon as scrolling starts,
    this._updateNewOutputBadge(); // even before the fetch below resolves
    this._scrollHistoryDebounced(next);
  };

  Terminal.prototype._scrollHistory = function (offset) {
    var self = this;
    if (offset <= 0) { this._scrollToBottom(); return; }
    var seq = ++this._scrollReqSeq;
    fetchScrollback(this.ttyId, offset, this.rows).then(function (data) {
      if (seq !== self._scrollReqSeq) return;   // superseded by a newer scroll / a return-to-live
      if (!data || !(data.offset > 0)) { self._scrollToBottom(); return; }   // clamped to the bottom
      self.viewingHistory = true;
      self.scrollOffset = data.offset;
      self.scrollTotal = data.total || 0;
      self._paintHistory(data.rows || []);
      self._updateScrollbar();
    }).catch(function () { });
  };

  Terminal.prototype._paintHistory = function (rows) {
    var view = [];
    for (var i = 0; i < this.rows; i++) view.push({ text: "", runs: [] });
    for (var j = 0; j < rows.length; j++) {
      var entry = rows[j];
      var r = entry[0] | 0;
      if (r < 0 || r >= this.rows) continue;
      view[r] = { text: String(entry[1] || ""), runs: entry[2] || [] };
    }
    this.historyGrid = view;
    this.viewingHistory = true;
    for (var r2 = 0; r2 < this.rows; r2++) this._paintRow(r2);
    this._layoutCursor();   // hides the live cursor -- see _layoutCursor's viewingHistory guard
  };

  Terminal.prototype._scrollToBottom = function () {
    this._scrollReqSeq++;   // invalidate any in-flight scrollback fetch
    if (!this.viewingHistory && this.scrollOffset === 0) return;
    this.viewingHistory = false;
    this.historyGrid = null;
    this.scrollOffset = 0;
    this.scrollTotal = 0;
    this.pendingNewOutput = false;
    for (var r = 0; r < this.rows; r++) this._paintRow(r);
    this._layoutCursor();
    this._updateNewOutputBadge();
    this._updateScrollbar();
  };

  Terminal.prototype._updateNewOutputBadge = function () {
    if (this.newOutEl) this.newOutEl.classList.toggle("show", this.viewingHistory && this.pendingNewOutput);
  };

  Terminal.prototype._updateScrollbar = function () {
    if (!this.scrollbarEl) return;
    if (!this.viewingHistory || this.scrollTotal <= this.rows) { this.scrollbarEl.classList.remove("show"); return; }
    this.scrollbarEl.classList.add("show");
    var total = this.scrollTotal;
    var thumbPct = Math.max(8, (this.rows / total) * 100);
    var topPct = Math.max(0, Math.min(100 - thumbPct, ((total - this.rows - this.scrollOffset) / total) * 100));
    this.scrollThumbEl.style.height = thumbPct + "%";
    this.scrollThumbEl.style.top = topPct + "%";
  };

  // ===== selection / copy / paste =====================================================
  Terminal.prototype._copyText = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () { _fallbackCopy(text); });
    } else {
      _fallbackCopy(text);
    }
  };
  function _fallbackCopy(text) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.focus(); ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (e) { /* clipboard just isn't available here -- nothing more to do */ }
  }

  Terminal.prototype._pasteFromClipboard = function () {
    var self = this;
    if (!navigator.clipboard || !navigator.clipboard.readText) {
      if (typeof toast === "function") toast("Clipboard paste isn't available", "the browser blocked it (needs HTTPS/localhost + a user gesture)");
      return;
    }
    navigator.clipboard.readText().then(function (text) {
      if (!text) return;
      // Bracketed paste (?2004): wrap so a multi-line paste lands as one atomic block instead of
      // being executed line-by-line by the shell. `bracketedPaste` mirrors the server's snapshot
      // stream (see the header comment) -- it is always false today because term_vt.py doesn't
      // emit that field yet, so this wraps automatically the moment it does.
      self._send(self.bracketedPaste ? ("\x1b[200~" + text + "\x1b[201~") : text);
    }).catch(function () {
      if (typeof toast === "function") toast("Couldn't read the clipboard", "allow clipboard access for this page and try again");
    });
  };

  // ===== bell: a brief visual flash, no audio (requirement 3) ==========================
  Terminal.prototype._flashBell = function () {
    var self = this;
    this.pane.classList.add("vtbell");
    setTimeout(function () { self.pane.classList.remove("vtbell"); }, 180);
  };

  // ===== font size: a small in-pane control, or Ctrl/Cmd +/- (requirement 3) ===========
  // Recomputes cols/rows and re-POSTs /api/term/resize afterwards via measureAndResize() -- a
  // real terminal reflows on a font change exactly like it does on a window resize.
  Terminal.prototype._zoom = function (dir) {
    var cs = getComputedStyle(this.pane);
    var curFs = this._fontPx || parseFloat(cs.fontSize);
    var curLh = this._linePx || parseFloat(cs.lineHeight);
    var ratio = curLh / (curFs || 1);
    var newFs = Math.max(8, Math.min(28, curFs + dir));
    if (newFs === curFs) return;
    this._fontPx = newFs;
    this._linePx = Math.round(newFs * ratio);
    this.pane.style.fontSize = this._fontPx + "px";
    this.pane.style.lineHeight = this._linePx + "px";
    this._applyRowSizing();
    this.measureAndResize();
  };
  Terminal.prototype._applyRowSizing = function () {
    if (!this._linePx) return;   // still the CSS default -- nothing to override per-row
    for (var i = 0; i < this.rowEls.length; i++) {
      this.rowEls[i].style.height = this._linePx + "px";
      this.rowEls[i].style.lineHeight = this._linePx + "px";
    }
  };

  // ===== XtermTerminal: the SECOND, switchable render path =============================
  // Hands raw PTY bytes (GET /api/term/raw, base64-framed) straight to vendored xterm.js instead
  // of painting term_vt.Screen's parsed rows -- see term_vt.py's big comment above raw_stream()
  // and config.py's TERM_RENDERER for the full story of why TWO renderer implementations coexist
  // (a deliberate, documented exception to conventions rule 4). Chosen server-side per the
  // TRACKER_TERM_RENDERER env var; ext_vt.js never decides this itself (conventions rule 5) --
  // openVT()/bootStandalone() below just read what the server already picked and construct
  // either this class or `Terminal` above. Exposes the SAME public interface `Terminal` does
  // (attach/measureAndResize/destroy/focus/_onStatusChange) so neither call site needs an
  // if/else past the point of picking which constructor to use.
  //
  // KNOWN GAPS vs the grid (`Terminal`) renderer -- read before assuming parity:
  //   - NO repaint of a PTY's pre-existing screen content on attach/reconnect. `/api/term/raw`
  //     only tees bytes emitted AFTER the SSE connection opens (there is no raw-byte scrollback
  //     server-side, unlike Screen's parsed grid+history) -- opening a second tab, or reconnecting,
  //     against a session that already has output on screen starts on a BLANK xterm.js buffer
  //     until the next write. See raw_stream()'s own docstring for the same note server-side.
  //   - NO custom "▼ new output" badge or the grid renderer's own scrollbar indicator -- xterm.js
  //     has its own internal scrollback buffer and its own (invisible-until-scrolled) viewport,
  //     used as-is; there is no server round trip for history here at all (no scrollback route is
  //     called), so behaviour while scrolled back is entirely xterm.js's own, not this file's.
  //   - The zoom control changes xterm's `fontSize` option + re-fits; xterm.js's internal row
  //     metrics are not pixel-identical to the grid painter's CSS line-height, so the two panes'
  //     exact row count at the "same" zoom step can differ by one row.
  //   - Selection copy-on-Ctrl+C is reimplemented here (xterm.js sends \x03 for a plain Ctrl+C
  //     UNCONDITIONALLY by default, selection or not -- there is no built-in copy-on-select/
  //     copy-on-Ctrl+C) via `attachCustomKeyEventHandler`, mirroring Terminal's own copyCombo
  //     check as closely as the two input models allow.
  var _xtermAssetsPromise = null;
  function _loadXtermAssets() {
    if (_xtermAssetsPromise) return _xtermAssetsPromise;
    _xtermAssetsPromise = new Promise(function (resolve, reject) {
      if (window.Terminal && window.FitAddon) { resolve(); return; }   // already loaded (2nd open)
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/vendor/xterm.css";
      document.head.appendChild(link);
      var s1 = document.createElement("script");
      s1.src = "/vendor/xterm.js";
      s1.onload = function () {
        var s2 = document.createElement("script");
        s2.src = "/vendor/addon-fit.js";
        s2.onload = function () { resolve(); };
        s2.onerror = function () { reject(new Error("failed to load /vendor/addon-fit.js")); };
        document.head.appendChild(s2);
      };
      s1.onerror = function () { reject(new Error("failed to load /vendor/xterm.js")); };
      document.head.appendChild(s1);
    });
    return _xtermAssetsPromise;
  }

  function _b64ToBytes(b64) {
    var bin = atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  // xterm.js takes an explicit JS colour theme, not CSS -- read the app's own custom properties
  // once so both light/dark themes (app.css's html.light) carry straight over instead of a second,
  // hardcoded palette drifting from the SGR classes in ext_vt.css.
  function _xtermTheme() {
    var cs = getComputedStyle(document.documentElement);
    function v(name, fallback) { var val = cs.getPropertyValue(name); return val ? val.trim() : fallback; }
    return {
      background: v("--app", "#0c0f15"), foreground: v("--text", "#e6edf3"),
      cursor: v("--ring2", "#29d398"), selectionBackground: "rgba(76,141,255,.35)",
    };
  }

  function XtermTerminal(container, ttyId) {
    this.ttyId = ttyId;
    this.es = null;
    this.term = null;
    this.fitAddon = null;
    this._onStatusChange = null;
    this._fontSize = 12.5;   // matches .vtpane's default font-size in ext_vt.css
    var self = this;
    this._resizeDebounced = debounce(function () { self._doResize(); }, 150);

    container.innerHTML = "";
    var toolbarEl = buildToolbar(
      function () { self._zoom(-1); },
      function () { self._zoom(1); },
      function () { self.focus(); }
    );
    var pane = document.createElement("div");
    pane.className = "vtpane vtxpane";
    container.appendChild(toolbarEl);
    container.appendChild(pane);
    this.pane = pane;
    this.container = container;
  }

  XtermTerminal.prototype.attach = function () {
    var self = this;
    if (self._onStatusChange) self._onStatusChange("loading xterm.js…");
    _loadXtermAssets().then(function () { self._build(); }, function (err) {
      if (self._onStatusChange) self._onStatusChange("failed to load xterm.js" + (err ? ": " + err.message : ""));
      if (typeof toast === "function") toast("Couldn't load the xterm renderer", String(err && err.message || err));
    });
  };

  XtermTerminal.prototype._build = function () {
    var self = this;
    var term = new window.Terminal({
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: this._fontSize,
      cursorBlink: true,
      scrollback: 5000,
      theme: _xtermTheme(),
    });
    var fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(this.pane);
    this.term = term; this.fitAddon = fit;
    try { fit.fit(); } catch (e) { }

    // Ctrl+C/Cmd+C copies the selection instead of sending SIGINT -- see this class's own header
    // comment ("Selection copy-on-Ctrl+C is reimplemented here") for why xterm.js needs this at
    // all: it sends \x03 for a plain Ctrl+C UNCONDITIONALLY otherwise, selection or not. Mirrors
    // Terminal.prototype._onKeyDown's copyCombo check; the Ctrl/Cmd +/- zoom shortcut is folded
    // into the same handler since both need to run BEFORE xterm's own key handling.
    term.attachCustomKeyEventHandler(function (ev) {
      if (ev.type !== "keydown") return true;
      var k = ev.key;
      var copyCombo = (ev.metaKey && !ev.ctrlKey && !ev.altKey && (k === "c" || k === "C")) ||
                       (ev.ctrlKey && ev.shiftKey && !ev.metaKey && !ev.altKey && (k === "c" || k === "C"));
      if (copyCombo && term.hasSelection()) {
        var sel = term.getSelection();
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(sel).catch(function () { _fallbackCopy(sel); });
        } else {
          _fallbackCopy(sel);
        }
        return false;   // swallow -- do not also send \x03
      }
      if ((ev.metaKey || ev.ctrlKey) && !ev.shiftKey && !ev.altKey && (k === "+" || k === "=" || k === "-" || k === "_")) {
        self._zoom(k === "-" || k === "_" ? -1 : 1);
        return false;
      }
      return true;
    });

    term.onData(function (data) { postKeys(self.ttyId, data); });
    term.onResize(function (sz) { postResize(self.ttyId, sz.cols, sz.rows); });

    window.addEventListener("resize", self._resizeDebounced);
    this._ro = null;
    if (window.ResizeObserver) {
      this._ro = new ResizeObserver(function () { self._resizeDebounced(); });
      this._ro.observe(this.pane);
    }
    try { term.focus(); } catch (e) { }
    this._openStream();
  };

  XtermTerminal.prototype._doResize = function () {
    if (!this.fitAddon) return;
    try { this.fitAddon.fit(); } catch (e) { }   // onResize above POSTs /api/term/resize itself
  };

  XtermTerminal.prototype._zoom = function (dir) {
    var newFs = Math.max(8, Math.min(28, this._fontSize + dir));
    if (newFs === this._fontSize) return;
    this._fontSize = newFs;
    if (this.term) { this.term.options.fontSize = newFs; this._doResize(); }
  };

  XtermTerminal.prototype._openStream = function () {
    // No `starting` handling here, deliberately: /api/term/raw is a raw byte stream with no JSON
    // envelope, so it has no `starting` key to read -- that asymmetry with Terminal's grid-path
    // _openStream (below) is intentional, not an oversight.
    var self = this;
    if (self.es) self.es.close();
    if (self._onStatusChange) self._onStatusChange("connecting…");
    self.es = new EventSource("/api/term/raw?tty=" + encodeURIComponent(self.ttyId));
    self.es.onopen = function () { if (self._onStatusChange) self._onStatusChange("connected"); };
    self.es.onmessage = function (ev) {
      if (!self.term) return;
      try { self.term.write(_b64ToBytes(ev.data)); } catch (e) { }
    };
    self.es.onerror = function () { if (self._onStatusChange) self._onStatusChange("reconnecting…"); };
  };

  // Same public name as Terminal.prototype.measureAndResize -- called identically by openVT's
  // window-resize handler and bootStandalone's, regardless of which renderer is active.
  XtermTerminal.prototype.measureAndResize = function () { this._doResize(); };

  XtermTerminal.prototype.focus = function () {
    if (this.term) { try { this.term.focus(); } catch (e) { } }
  };

  XtermTerminal.prototype.destroy = function () {
    if (this.es) { this.es.close(); this.es = null; }
    if (this._ro) { this._ro.disconnect(); this._ro = null; }
    window.removeEventListener("resize", this._resizeDebounced);
    if (this.term) { this.term.dispose(); this.term = null; }
  };

  // ===== the modal (reuses app.css's .overlay/.modal/.mh/.mb/.x — no second modal system) =====
  var overlay = null, modalTitleEl = null, modalStatusEl = null, modalBodyEl = null;
  var activeTerm = null, activeTty = null, activeSid = null, activeMode = null, activeBar = null;
  var activeRenderer = null;   // "grid" | "xterm" -- server-owned (see openVT below), never guessed
  var activeForked = false, activeNotice = null;   // forked/notice from POST /api/term/pty response
  var openGen = 0;   // bumped by every openVT(); an in-flight open whose generation is stale has
                      // been superseded. Supersedes the older `activeSid !== sid` test, which could
                      // not see a SAME-session supersede (two opens for one sid, or two modes):
                      // both responses passed it, both attached, and the first terminal's SSE was
                      // never closed -- so pt.viewers never returned to 0 and the server could not
                      // idle-reap that pty for the life of the tab. A counter cannot miss a case
                      // the way an identity comparison can.
  var modalForkChip = null, modalNoticeEl = null;   // UI elements for forked status and notice

  function buildOverlay(mount) {
    overlay = document.createElement("div");
    overlay.className = "overlay";
    overlay.id = "vtmodal";
    overlay.addEventListener("click", function (ev) { if (ev.target === overlay) closeVT(); });

    var modal = document.createElement("div");
    modal.className = "modal vtmodal";

    var mh = document.createElement("div");
    mh.className = "mh";
    modalTitleEl = document.createElement("span");
    modalTitleEl.className = "fn";
    modalTitleEl.textContent = "Terminal";
    // Fork chip: appended after title, shown conditionally when forked=true
    modalForkChip = document.createElement("span");
    modalForkChip.className = "vtforkchip";
    modalForkChip.setAttribute("aria-label", "This terminal is a copy of a background agent — the original is still running separately");
    modalForkChip.textContent = "⑂ fork";
    modalForkChip.style.display = "none";
    modalStatusEl = document.createElement("span");
    modalStatusEl.className = "pp";
    var newTabBtn = document.createElement("span");
    newTabBtn.className = "mdbtn";
    newTabBtn.title = "Open this same terminal in its own tab";
    newTabBtn.textContent = "⤢ New tab";
    newTabBtn.addEventListener("click", openNewTab);
    var xBtn = document.createElement("span");
    xBtn.className = "x";
    xBtn.title = "Close";
    xBtn.textContent = "✕";
    xBtn.addEventListener("click", closeVT);
    mh.appendChild(modalTitleEl);
    mh.appendChild(modalForkChip);
    mh.appendChild(modalStatusEl);
    mh.appendChild(newTabBtn);
    mh.appendChild(xBtn);

    modalBodyEl = document.createElement("div");
    modalBodyEl.className = "mb vtmb";

    modal.appendChild(mh);
    modal.appendChild(modalBodyEl);
    overlay.appendChild(modal);
    mount.appendChild(overlay);

    window.addEventListener("resize", debounce(function () {
      if (activeTerm && overlay.style.display === "flex") activeTerm.measureAndResize();
    }, 150));
  }

  // Registered once, after app.js's own document-level Escape handler (this file loads later —
  // see page.py's sorted ext_*.js concatenation). Only ever fires when the terminal's own input
  // did NOT consume the key (its keydown handler stops propagation for every key it handles,
  // Escape included — see Terminal.prototype._onKeyDown above).
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    if (!overlay || overlay.style.display !== "flex") return;
    closeVT();
  });

  // ===== context bar: docked to the bottom of the terminal pane, in both the modal and the
  // standalone ?tty= view (ContextBar is instantiated from openVT() below and from
  // bootStandalone() at the end of this file — same component, two mount points). Two controls,
  // mirroring a reference implementation the user pointed at:
  //   1. a model switcher — picking an entry types "/model <name>" into the running CLI. There
  //      is no API for this: /model is a CLI slash command, not server-tracked state, so the
  //      only way to "set" it is to type it, exactly the way a person would.
  //   2. a context-window usage readout — see readContextUsage() below for the wire contract
  //      this assumes (a PARALLEL agent is adding the field it reads).
  // ======================================================================================

  // The model ladder is HARDCODED, on purpose — mirroring the reference implementation, which
  // does the same thing. This is the CLI's OWN slash-command ladder, not anything this app can
  // discover from a session log or any API; if the CLI ever renames/adds a tier, this literal
  // array is the one place to update.
  var MODEL_LADDER = ["haiku", "sonnet", "opus", "fable"];

  // Best-effort "which model is this" label for the switcher button/dropdown. There is no live,
  // CLI-reported "current model" anywhere this app can read — meta.model (set in
  // aitracker/providers/claude.py from the last transcript message's `message.model`) is only a
  // snapshot of what generated the LAST reply, so this is a heuristic label, not a guarantee —
  // it goes stale the instant /model is used without a further assistant message following it.
  function _matchLadderModel(raw) {
    if (!raw) return null;
    var low = String(raw).toLowerCase();
    for (var i = 0; i < MODEL_LADDER.length; i++) {
      if (low.indexOf(MODEL_LADDER[i]) !== -1) return MODEL_LADDER[i];
    }
    return null;
  }

  function fmtTok(n) {
    n = n || 0;
    if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, "") + "m";
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
    return String(n);
  }

  // ===== context-window usage: isolated in this ONE function because its wire shape comes from
  // the shared session-detail dict served by GET /api/session (aitracker/providers/claude.py &
  // auggie.py — NOT this worktree's files), landed by a PARALLEL agent. CONFIRMED CONTRACT (see
  // the header comment at the top of this file for the full reconciliation note):
  //   d.context = { current: <int|null, LATEST turn's usage only, not a running total>,
  //                 limit:   <int|null, present only when the tool's own logs state a window
  //                           size — routinely null for Claude sessions>,
  //                 pct:     <float|null, SERVER-COMPUTED, present only when both of the above
  //                           are known and limit > 0> }
  // `current` is REQUIRED for anything to render — null (an Auggie/augment_ext session with no
  // readable usage, or simply before this field existed) means "nothing to show", not a
  // placeholder or a zero. `pct` gates the bar/percentage as an ENHANCEMENT on top of `current`,
  // never the other way round: this file never computes its own percentage from current/limit —
  // that would be exactly the "invent a denominator" the spec forbids, and it is also simply
  // wrong for the common case (Claude sessions carry a `current` with no `limit` at all).
  function readContextUsage(d) {
    var c = d && d.context;
    if (!c || typeof c.current !== "number" || !(c.current >= 0)) return null;
    var limit = (typeof c.limit === "number" && c.limit > 0) ? c.limit : null;
    var pct = (typeof c.pct === "number") ? c.pct : null;   // server's number, verbatim
    return { current: c.current, limit: limit, pct: pct };
  }

  // ===== ContextBar: one instance per open terminal (modal or standalone), destroyed with it. ==
  function ContextBar(container, sid, ttyId, mode, getInput) {
    this.sid = sid; this.ttyId = ttyId; this.getInput = getInput;
    // Only a Claude CLI is listening for "/model ..." — mode is "resume"|"new" for that, "cwd"
    // for a plain shell. Typing a slash command at a bash prompt would just leave junk on the
    // line, so the switcher is never merely disabled outside those two modes — it isn't built.
    this.showSwitcher = (mode === "resume" || mode === "new");
    this.dropdownOpen = false;
    this.currentModel = null;
    this._pollStop = null;
    this._destroyed = false;

    var self = this;
    var bar = document.createElement("div");
    bar.className = "vtctxbar";
    this.el = bar;

    if (this.showSwitcher) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "vtmodelbtn";
      btn.textContent = "model ▾";
      btn.title = "Switch model — types /model <name> into the CLI";
      var dd = document.createElement("div");
      dd.className = "vtmodeldd";
      MODEL_LADDER.forEach(function (name) {
        var item = document.createElement("div");
        item.className = "vtmodelitem";
        item.textContent = name;
        item.setAttribute("data-model", name);
        dd.appendChild(item);
      });
      bar.appendChild(btn);
      bar.appendChild(dd);
      this.modelBtn = btn; this.modelDd = dd;

      // preventDefault on mousedown, not just handling click: a <button> takes native DOM focus
      // on mousedown in most browsers, and this bar must never steal keyboard focus from the
      // terminal's own capture textarea — not even for the instant between mousedown and click.
      btn.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        if (self.dropdownOpen) self._closeDropdown(); else self._openDropdown();
        self._focusTerminal();
      });
      dd.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
      dd.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var name = ev.target && ev.target.getAttribute && ev.target.getAttribute("data-model");
        if (!name) return;
        self._pickModel(name);
      });
      this._onDocClick = function (ev) {
        if (!self.dropdownOpen || bar.contains(ev.target)) return;
        self._closeDropdown();
      };
      document.addEventListener("click", this._onDocClick);
    }

    var readout = document.createElement("div");
    readout.className = "vtctxreadout";
    bar.appendChild(readout);
    this.readoutEl = readout;

    // Nothing to show yet (no switcher, no data fetched) — stay invisible rather than showing an
    // empty docked strip; _renderReadout() reveals it the moment there's real content.
    bar.style.display = this.showSwitcher ? "" : "none";

    container.appendChild(bar);
  }

  ContextBar.prototype._focusTerminal = function () {
    var input = this.getInput && this.getInput();
    if (input) { try { input.focus(); } catch (e) { } }
  };

  ContextBar.prototype._openDropdown = function () {
    this.dropdownOpen = true;
    this.modelDd.classList.add("show");
    var items = this.modelDd.children;
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("cur", items[i].getAttribute("data-model") === this.currentModel);
    }
  };
  ContextBar.prototype._closeDropdown = function () {
    this.dropdownOpen = false;
    if (this.modelDd) this.modelDd.classList.remove("show");
  };

  // Sends "/model <name>" via the inject route another agent is building in parallel:
  //   POST /api/term/inject {tty, text, submit: true, clear_first: true} -> {ok: true, ...}
  // That route may not exist yet in this worktree — a 404/400 (or any non-ok response) surfaces
  // a toast rather than failing silently, per the spec.
  ContextBar.prototype._pickModel = function (name) {
    this._closeDropdown();
    this._focusTerminal();
    fetch("/api/term/inject", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tty: this.ttyId, text: "/model " + name, submit: true, clear_first: true })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
    }).then(function (res) {
      if (res.ok && res.j && res.j.ok === true) return;
      var reason = (res.j && res.j.error) ||
        (res.status === 404 ? "the model-switch route isn't available in this build yet" :
         res.status === 400 ? "the terminal rejected that request" :
         "the terminal didn't confirm the switch");
      if (typeof toast === "function") toast("Couldn't switch model", reason);
    }).catch(function () {
      if (typeof toast === "function") toast("Couldn't reach the server", "the model switch wasn't sent");
    });
  };

  ContextBar.prototype._applySessionData = function (d) {
    var meta = (d && d.meta) || {};
    this.currentModel = _matchLadderModel(meta.model);
    if (this.modelBtn) this.modelBtn.textContent = (this.currentModel || "model") + " ▾";

    var usage = readContextUsage(d);
    // Session-CUMULATIVE total (all turns, all time, monotonically increasing) — a DIFFERENT
    // number from `usage.current` (latest-turn occupancy) with a different meaning. This field
    // already ships today for every provider (aitracker/providers/claude.py, auggie.py,
    // augment_ext.py), unlike `d.context` above, so it's read directly here rather than through
    // readContextUsage(). Labelled "Σ" in the readout so the two are never misread as one figure.
    var cumulative = (d && d.tokens) ? ((d.tokens.in | 0) + (d.tokens.out | 0)) : 0;
    this._renderReadout(usage, cumulative);
  };

  // Leads with `current` (shown whenever present, on its own for the common Claude-session case
  // where there's no honest denominator) and treats the bar/percentage as an ENHANCEMENT layered
  // on top, gated strictly on `usage.pct` being non-null — never on `usage.limit` alone, and
  // never computed here (see readContextUsage's comment). Renders nothing at all when `current`
  // is null: no empty chrome, no "0", no placeholder bar.
  ContextBar.prototype._renderReadout = function (usage, cumulative) {
    var el = this.readoutEl;
    if (el) {
      if (!usage) {
        el.innerHTML = "";
      } else {
        var html = '<span class="vtctxused" title="tokens in context right now">' + esc(fmtTok(usage.current)) + '</span>';
        if (usage.pct !== null) {
          var barPct = Math.max(0, Math.min(100, usage.pct));            // defensive clamp for the bar's CSS width only
          var pctLabel = Math.round(usage.pct);                          // the printed number is still the server's own pct
          var title = fmtTok(usage.current) + (usage.limit !== null ? (" / " + fmtTok(usage.limit) + " tokens") : "") + " (" + pctLabel + "%)";
          html += '<span class="vtctxbarwrap" title="' + esc(title) + '">' +
                    '<span class="vtctxbarfill" style="width:' + barPct + '%"></span>' +
                  '</span>' +
                  '<span class="vtctxpct">' + pctLabel + '%</span>';
        }
        if (cumulative > 0) {
          html += '<span class="vtctxcum" title="cumulative tokens, this session">Σ ' + esc(fmtTok(cumulative)) + '</span>';
        }
        el.innerHTML = html;
      }
    }
    // Hide the whole bar when it would have nothing to show at all (no switcher AND no usage
    // data) — a visible-but-empty docked strip is worse than no strip.
    this.el.style.display = (this.showSwitcher || !!usage) ? "" : "none";
  };

  ContextBar.prototype.start = function () {
    var self = this;
    function tick() {
      if (self._destroyed) return;
      fetch("/api/session?id=" + encodeURIComponent(self.sid))
        .then(function (r) { return r.json(); })
        .then(function (d) { if (!self._destroyed && d && !d.error) self._applySessionData(d); })
        .catch(function () { });
    }
    tick();
    var timer = setInterval(tick, 2000);   // mirrors app.js's own 2s poll cadence
    this._pollStop = function () { clearInterval(timer); };
  };

  ContextBar.prototype.destroy = function () {
    this._destroyed = true;
    if (this._pollStop) { this._pollStop(); this._pollStop = null; }
    if (this._onDocClick) { document.removeEventListener("click", this._onDocClick); this._onDocClick = null; }
    if (this.el && this.el.parentNode) this.el.parentNode.removeChild(this.el);
  };

  // The cap is a slot problem, not a wall: show what is holding the slots and let the user free
  // one. `j` is the 429 body from POST /api/term/pty -- {error, terminals:[{tty,cmd,cwd,started}]}.
  // The error text and the cap number are the SERVER's (conventions rule 5); nothing here
  // re-derives them. Closing a row re-runs openVT(sid, mode), so a successful reclaim lands
  // straight in the terminal the user asked for.
  function renderCapBlock(sid, mode, j, gen) {
    var now = Date.now() / 1000;
    var wrap = document.createElement("div");
    wrap.className = "empty vtempty vtcap";
    var head = document.createElement("div");
    head.className = "vtcaphead";
    head.textContent = j.error + " — close one to free a slot:";
    wrap.appendChild(head);
    j.terminals.forEach(function (t) {
      var row = document.createElement("div");
      row.className = "vtcaprow";
      var mins = Math.max(0, Math.round((now - (t.started || now)) / 60));
      var label = document.createElement("span");
      label.className = "vtcaplabel";
      label.textContent = (t.cmd || "shell") + "  ·  " + (t.cwd || "") + "  ·  " + mins + "m";
      label.title = t.tty;
      var x = document.createElement("button");
      x.className = "vtcapx";
      x.textContent = "✕";
      x.title = "kill this terminal";
      x.onclick = function () {
        // Latch the WHOLE block, not just this button. Freeing two slots is the natural move when
        // you want headroom, but each click schedules its own retry and each retry calls openVT
        // again -- and openVT's destroy() only closes the client's SSE, it never kills the pty it
        // is replacing. Two clicks would therefore attach two terminals, orphan the first one
        // viewer-less for the full 30-minute IDLE_TIMEOUT, and recreate the exact cap this block
        // exists to clear. One click, one retry.
        var unlatch = function () {
          Array.prototype.forEach.call(wrap.querySelectorAll(".vtcapx"),
                                       function (b) { b.disabled = false; });
        };
        Array.prototype.forEach.call(wrap.querySelectorAll(".vtcapx"),
                                     function (b) { b.disabled = true; });
        fetch("/api/term/close", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tty: t.tty })
        }).then(function (r) {
          if (!r.ok) { unlatch(); return; }
          // The slot frees on the reader thread noticing EOF, not on this response, so give it a
          // beat before retrying rather than racing straight into another 429. Re-check on the
          // way in: in those 250ms the user may have closed the modal (don't re-open it behind
          // their back) or opened anything else at all (don't hijack it back to this one). The
          // generation check covers both a different session and a different mode on the same
          // one, which is exactly the case an `activeSid` comparison cannot see.
          setTimeout(function () {
            if (gen !== openGen) return;
            if (!overlay || overlay.style.display === "none") return;
            openVT(sid, mode);
          }, 250);
        }).catch(unlatch);
      };
      row.appendChild(label);
      row.appendChild(x);
      wrap.appendChild(row);
    });
    modalBodyEl.innerHTML = "";
    modalBodyEl.appendChild(wrap);
  }

  function openVT(sid, mode) {
    if (!sid) return;
    var mount = document.getElementById("ext_vt");
    if (!mount) return;
    if (!overlay) buildOverlay(mount);
    if (activeTerm) { activeTerm.destroy(); activeTerm = null; }
    if (activeBar) { activeBar.destroy(); activeBar = null; }
    activeTty = null;
    activeSid = sid;
    activeMode = mode;
    var gen = ++openGen;             // this open's identity; see openGen's declaration above

    modalTitleEl.textContent = "Terminal — " + (mode === "resume" ? "resume · " : "") + sid;
    modalStatusEl.textContent = "connecting…";
    modalBodyEl.innerHTML = "";
    overlay.style.display = "flex";

    // Build the real pane first so we can measure its ACTUAL rendered size (requirement 5) and
    // ask the server for a pty of that size, rather than guessing a default and resizing after.
    var probePane = document.createElement("div");
    probePane.className = "vtpane";
    modalBodyEl.appendChild(probePane);
    requestAnimationFrame(function () {
      var m = computeColsRows(probePane);
      modalBodyEl.innerHTML = "";
      fetch("/api/term/pty", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: sid, cols: m.cols, rows: m.rows, mode: mode })
      }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; }); })
        .then(function (res) {
          if (gen !== openGen) {
            // Superseded by a later open() while this was in flight — generation, not `activeSid`,
            // because a same-session supersede (two opens for one sid, or two modes) leaves
            // activeSid equal and would slip through. Dropping the response used to LEAK the pty
            // the server had already spawned for us: live, viewer-less and invisible until
            // IDLE_TIMEOUT — or, in the same-sid case, forever, since a second attach overwrote
            // the first terminal without closing its SSE, pinning pt.viewers above 0 so the idle
            // reap could never fire. Harmless-looking until you arrive here from the capacity
            // block, where the user is actively trying to free slots and would silently gain a
            // hidden one instead. Now that /api/term/close exists, handing it back is one call.
            // Fire-and-forget: nothing is left to render.
            if (res.ok && res.j && res.j.tty) {
              fetch("/api/term/close", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ tty: res.j.tty })
              }).catch(function () {});
            }
            return;
          }
          if (!res.ok || !res.j || !res.j.tty) {
            modalStatusEl.textContent = "";
            // 429 is the one failure the user can actually fix from here: the server tells us
            // WHICH terminals hold the slots, so offer a ✕ per row that frees one and retries,
            // instead of a dead-end string. Everything else stays a plain message.
            if (res.status === 429 && res.j && res.j.terminals && res.j.terminals.length) {
              renderCapBlock(sid, mode, res.j, gen);
              return;
            }
            modalBodyEl.innerHTML = '<div class="empty vtempty">' + esc(
              (res.j && res.j.error) ||
              (res.status === 403
                ? "in-browser terminal is disabled — set TRACKER_TERMINAL=1 and TRACKER_AUTH"
                : "failed to start terminal")
            ) + "</div>";
            return;
          }
          activeTty = res.j.tty;
          // Defensive reads for forked/notice fields — may not exist yet in this worktree if the
          // server agent's work is not merged yet. Default to sensible no-op values.
          activeForked = !!res.j.forked;
          activeNotice = (typeof res.j.notice === "string") ? res.j.notice : null;
          // Update fork chip display
          if (modalForkChip) modalForkChip.style.display = activeForked ? "" : "none";
          // Create and display notice if present
          if (activeNotice) {
            if (!modalNoticeEl) {
              modalNoticeEl = document.createElement("div");
              modalNoticeEl.className = "vtnotice";
            }
            modalNoticeEl.innerHTML = "";   // clear any previous content
            var noticeText = document.createElement("span");
            noticeText.textContent = activeNotice;  // textContent escapes HTML
            modalNoticeEl.appendChild(noticeText);
            if (!modalNoticeEl.parentNode) modalBodyEl.insertBefore(modalNoticeEl, modalBodyEl.firstChild);
          } else if (modalNoticeEl && modalNoticeEl.parentNode) {
            modalNoticeEl.parentNode.removeChild(modalNoticeEl);
          }
          // Server-owned (conventions rule 5): the client reads which renderer to build off the
          // response `open_pty()` already sent, never decides it locally -- see term_vt.py's
          // TRACKER_TERM_RENDERER switch comment. An unrecognized/missing value falls back to
          // "grid", same as config.TERM_RENDERER's own server-side fallback.
          activeRenderer = (res.j.renderer === "xterm") ? "xterm" : "grid";
          modalStatusEl.textContent = "tty " + activeTty;
          var Cls = activeRenderer === "xterm" ? XtermTerminal : Terminal;
          var term = new Cls(modalBodyEl, activeTty);
          // `starting` (true only for mode="resume" panes still recovering from a refused
          // `claude --resume`) is server-owned and read straight off this POST response, seeded
          // BEFORE term.attach() ever opens the EventSource below -- see Terminal's own `starting`
          // field comment. Only meaningful for the grid renderer: xterm's /api/term/raw stream
          // carries no JSON envelope at all, so it has no `starting` key to read (deliberately out
          // of scope -- see XtermTerminal.prototype._openStream's comment).
          if (activeRenderer === "grid") {
            term.starting = !!res.j.starting;
            term.pane.classList.toggle("vtstarting", term.starting);
            if (term.starting) modalStatusEl.textContent = "tty " + activeTty + " · starting…";
          }
          term._onStatusChange = function (s) {
            if (activeTerm !== term) return;
            // Suppress the connecting/connected/reconnecting churn while starting -- in particular
            // this is where the refused resume child's SSE drop would otherwise flash
            // "reconnecting…" into the header even though the server recovers on its own a couple
            // seconds later (the whole point of this change). One steady "starting…" instead, no
            // matter what status string actually came in.
            if (term.starting) { modalStatusEl.textContent = "tty " + activeTty + " · starting…"; return; }
            modalStatusEl.textContent = "tty " + activeTty + " · " + s;
          };
          activeTerm = term;
          // Built AFTER the Terminal/XtermTerminal (both do container.innerHTML = "" in their own
          // constructor) so the bar's own DOM survives — appended as a sibling of .vtpane inside
          // the same flex-column .vtmb, so it docks to the bottom without any CSS shuffling.
          // getInput hands back the TERMINAL OBJECT itself (both classes expose .focus()), not a
          // raw DOM node -- see Terminal.prototype.focus / XtermTerminal.prototype.focus.
          activeBar = new ContextBar(modalBodyEl, sid, activeTty, mode, function () { return term; });
          activeBar.start();
          term.attach();
        })
        .catch(function (e) {
          if (gen !== openGen) return;   // same generation test as the success path: a superseded
                                          // failure must not overwrite the current modal either.
                                          // Nothing to hand back here -- no pty was ever created.
          modalStatusEl.textContent = "";
          modalBodyEl.innerHTML = '<div class="empty vtempty">failed to reach the server: ' + esc(String(e)) + "</div>";
        });
    });
  }

  function closeVT() {
    // Dismissing counts as a supersede, so bump the generation. The old `activeSid !== sid` guard
    // got this for free -- closeVT nulls activeSid -- and switching to a counter would silently
    // lose it: an open still in flight when the user hits Escape would pass `gen === openGen`,
    // attach a terminal and an SSE behind a now-hidden overlay, and leave a live pty pinned by a
    // viewer nobody can see. The in-flight response instead takes openVT's supersede branch and
    // hands its pty back.
    openGen++;
    if (overlay) overlay.style.display = "none";
    if (activeTerm) { activeTerm.destroy(); activeTerm = null; }
    if (activeBar) { activeBar.destroy(); activeBar = null; }
    activeTty = null; activeSid = null; activeMode = null; activeRenderer = null;
    activeForked = false; activeNotice = null;
    if (modalForkChip) modalForkChip.style.display = "none";
    if (modalNoticeEl && modalNoticeEl.parentNode) modalNoticeEl.parentNode.removeChild(modalNoticeEl);
  }

  function openNewTab() {
    if (!activeTty) return;
    // sid/mode/renderer are carried into the new tab's own URL (this app's own scheme, not a
    // server contract) purely so bootStandalone() below can build its own ContextBar/Terminal
    // there too — the standalone view otherwise only knows the tty id. `renderer` is a value the
    // SERVER already chose (see openVT's res.j.renderer) being relayed forward, not decided here
    // — bootStandalone() also has its own fallback (GET /api/term/renderer) for a bookmarked
    // ?tty= link with no renderer param at all. `forked` and `notice` are similarly relayed so
    // the new tab can display the same fork chip and advisory notice as the opening modal.
    var url = location.origin + location.pathname + "?tty=" + encodeURIComponent(activeTty) +
      "&sid=" + encodeURIComponent(activeSid || "") + "&mode=" + encodeURIComponent(activeMode || "") +
      "&renderer=" + encodeURIComponent(activeRenderer || "grid") +
      "&forked=" + (activeForked ? "1" : "0") +
      (activeNotice ? "&notice=" + encodeURIComponent(activeNotice) : "");
    var w = window.open(url, "_blank");
    if (!w) alert("Popup blocked — allow popups for this page to open a new tab.");
  }

  window.ExtVT = { open: openVT };

  // ===== render hook: participates in the normal 2s poll like every other ext module, and is
  // what genuinely puts #ext_vt to use (the modal is built as its child, not appended to
  // document.body) — see buildOverlay(mount) above. =====
  function render(d) {
    if (document.documentElement.classList.contains("vt-standalone")) return;   // that mode owns #ext_vt itself
    var mount = document.getElementById("ext_vt");
    if (!mount) return;
    if (!overlay) buildOverlay(mount);
    if (activeTerm && activeSid && cur !== activeSid && overlay.style.display === "flex") {
      // the sidebar switched sessions while a terminal is open -- the tty keeps running
      // server-side (this tier has no client-driven kill route), just stop implying it's "this"
      // session's terminal.
      modalStatusEl.textContent = "tty " + activeTty + " (opened from another session)";
    }
  }
  EXT.push(render);

  // ===== standalone tab: ?tty=<id> (or #tty=<id>) takes over #ext_vt full-window and hides the
  // rest of the baked SPA via CSS (ext_vt.css's .vt-standalone rules) -- no server round-trip to
  // create a NEW pty, this attaches to the SAME tty id the opening modal already created. =====
  (function bootStandalone() {
    var qs = new URLSearchParams(location.search);
    var tty = qs.get("tty");
    // sid/mode are this app's own addition to the URL (see openNewTab() above) -- the ORIGINAL
    // plan's ?tty= contract only carried the tty id, which is all the terminal itself needs, but
    // the context bar needs to know which session this tty belongs to (for /api/session polling)
    // and whether it's a Claude CLI (for the model switcher). Both are optional: a bare ?tty=
    // link (e.g. one bookmarked before this change) still opens the terminal fine, just without
    // the context bar.
    var sid = qs.get("sid") || "";
    var mode = qs.get("mode") || "";
    // `renderer` is this app's own URL addition too (see openNewTab() above), relaying a value
    // the SERVER already picked -- never guessed here. A bare ?tty= link with no renderer param
    // (bookmarked before this change, or typed by hand) falls back to GET /api/term/renderer
    // below rather than silently assuming "grid" -- the server is still the one deciding.
    var rendererParam = qs.get("renderer") || "";
    // Defensive reads for forked/notice: may not be present in bookmarked ?tty= links from
    // before this session, or if generated by other means. Defaults to sensible no-op values.
    var standaloneForked = qs.get("forked") === "1";
    var standaloneNotice = qs.get("notice") || null;
    if (!tty) {
      var m = /[?&#]tty=([^&]+)/.exec(location.hash);
      if (m) tty = decodeURIComponent(m[1]);
    }
    if (!tty) return;
    document.documentElement.classList.add("vt-standalone");
    document.title = "Terminal — AI Tracker";
    var mount = document.getElementById("ext_vt");
    if (!mount) return;
    // The mount lives inside .app, which .vt-standalone hides with display:none -- and a
    // display:none ancestor removes the whole subtree from rendering no matter that we are
    // position:fixed. Reparent to <body> so the fullscreen layout actually has a box; without
    // this the standalone tab renders a correct DOM at 0x0 and the user sees a black screen.
    document.body.appendChild(mount);
    mount.classList.add("vtfull");

    function boot(renderer) {
      var Cls = renderer === "xterm" ? XtermTerminal : Terminal;
      var term = new Cls(mount, tty);
      var bar = null;
      if (sid) {
        // Appended AFTER the Terminal/XtermTerminal (whose constructor does
        // container.innerHTML = "") and BEFORE the status line below, so DOM order is
        // pane -> context bar -> status -- the bar docks directly under the pane, with the
        // tty/connection status as the very bottom line.
        bar = new ContextBar(mount, sid, tty, mode, function () { return term; });
        bar.start();
      }
      // Build notice element if present (same as modal, but in standalone context)
      if (standaloneNotice) {
        var noticeEl = document.createElement("div");
        noticeEl.className = "vtnotice";
        var noticeText = document.createElement("span");
        noticeText.textContent = standaloneNotice;  // textContent escapes HTML
        noticeEl.appendChild(noticeText);
        mount.appendChild(noticeEl);
      }
      // Build status line with fork indicator if present
      var status = document.createElement("div");
      status.className = "vtfullstatus";
      var statusContent = "tty " + tty;
      if (standaloneForked) statusContent += " · ⑂ fork";
      statusContent += " · connecting…";
      status.innerHTML = "";   // clear before adding spans to avoid HTML injection
      var parts = statusContent.split(" · ");
      for (var i = 0; i < parts.length; i++) {
        if (i > 0) status.appendChild(document.createTextNode(" · "));
        if (i === 1 && standaloneForked) {
          var chip = document.createElement("span");
          chip.className = "vtstatus-fork";
          chip.setAttribute("title", "This terminal is a copy of a background agent — the original is still running separately");
          chip.textContent = "⑂ fork";
          status.appendChild(chip);
        } else {
          status.appendChild(document.createTextNode(parts[i]));
        }
      }
      mount.appendChild(status);
      term._onStatusChange = function (s) {
        status.innerHTML = "";   // clear before adding new content
        var statusText = "tty " + tty;
        if (standaloneForked) statusText += " · ⑂ fork";
        statusText += " · " + s;
        var parts = statusText.split(" · ");
        for (var i = 0; i < parts.length; i++) {
          if (i > 0) status.appendChild(document.createTextNode(" · "));
          if (i === 1 && standaloneForked) {
            var chip = document.createElement("span");
            chip.className = "vtstatus-fork";
            chip.setAttribute("title", "This terminal is a copy of a background agent — the original is still running separately");
            chip.textContent = "⑂ fork";
            status.appendChild(chip);
          } else {
            status.appendChild(document.createTextNode(parts[i]));
          }
        }
      };
      term.attach();
      window.addEventListener("resize", debounce(function () { term.measureAndResize(); }, 150));
    }

    if (rendererParam === "grid" || rendererParam === "xterm") {
      boot(rendererParam);
    } else {
      fetch("/api/term/renderer").then(function (r) { return r.json(); })
        .then(function (j) { boot((j && j.renderer === "xterm") ? "xterm" : "grid"); })
        .catch(function () { boot("grid"); });
    }
  })();
})();
