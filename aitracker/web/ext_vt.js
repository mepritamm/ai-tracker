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
    var padX = 20, padY = 16;   // approx the pane's own CSS padding; harmless if pane isn't padded yet
    var rect = pane.getBoundingClientRect();
    var innerW = rect.width || pane.clientWidth || (80 * cell.w + padX);
    var innerH = rect.height || pane.clientHeight || (24 * cell.h + padY);
    var cols = Math.max(20, Math.min(300, Math.floor(innerW / cell.w)));
    var rows = Math.max(6, Math.min(120, Math.floor(innerH / cell.h)));
    return { cols: cols, rows: rows, cellW: cell.w, cellH: cell.h };
  }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
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
    this._sized = false;
    this._onStatusChange = null;
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

    container.innerHTML = "";
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
    var zoomEl = document.createElement("div");
    zoomEl.className = "vtzoom";
    var zoomOut = document.createElement("span");
    zoomOut.textContent = "A−"; zoomOut.title = "Smaller (Ctrl/Cmd -)";
    var zoomIn = document.createElement("span");
    zoomIn.textContent = "A+"; zoomIn.title = "Larger (Ctrl/Cmd +)";
    zoomEl.appendChild(zoomOut);
    zoomEl.appendChild(zoomIn);
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
    pane.appendChild(zoomEl);
    pane.appendChild(input);
    container.appendChild(pane);

    this.pane = pane; this.rowsEl = rowsEl; this.cursorEl = cursorEl; this.input = input;
    this.newOutEl = newOutEl; this.scrollbarEl = scrollbarEl; this.scrollThumbEl = scrollThumbEl;

    var self = this;
    this._scrollHistoryDebounced = debounce(function (offset) { self._scrollHistory(offset); }, 30);
    // No preventDefault here (requirement 2's whole point): blocking the mousedown default is
    // what stops native text selection from ever starting. Focusing the capture textarea on the
    // same event still routes the next keystroke to the PTY without touching the emerging
    // selection -- selection anchoring is driven by the browser off the ORIGINAL mousedown target
    // (a .vtrow text node now that the input no longer overlays the pane), not by DOM focus.
    pane.addEventListener("mousedown", function () { input.focus(); });
    pane.addEventListener("wheel", function (ev) { self._onWheel(ev); }, { passive: false });
    newOutEl.addEventListener("click", function () { self._scrollToBottom(); input.focus(); });
    zoomOut.addEventListener("click", function () { self._zoom(-1); input.focus(); });
    zoomIn.addEventListener("click", function () { self._zoom(1); input.focus(); });
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
    this.cursorEl.style.transform = "translate(" + (c * this.cellW) + "px," + (r * this.cellH) + "px)";
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

  // ===== the modal (reuses app.css's .overlay/.modal/.mh/.mb/.x — no second modal system) =====
  var overlay = null, modalTitleEl = null, modalStatusEl = null, modalBodyEl = null;
  var activeTerm = null, activeTty = null, activeSid = null;

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

  function openVT(sid, mode) {
    if (!sid) return;
    var mount = document.getElementById("ext_vt");
    if (!mount) return;
    if (!overlay) buildOverlay(mount);
    if (activeTerm) { activeTerm.destroy(); activeTerm = null; }
    activeTty = null;
    activeSid = sid;

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
          if (activeSid !== sid) return;          // superseded by a later open() while this was in flight
          if (!res.ok || !res.j || !res.j.tty) {
            modalStatusEl.textContent = "";
            modalBodyEl.innerHTML = '<div class="empty vtempty">' + esc(
              (res.j && res.j.error) ||
              (res.status === 403
                ? "in-browser terminal is disabled — set TRACKER_TERMINAL=1 and TRACKER_AUTH"
                : "failed to start terminal")
            ) + "</div>";
            return;
          }
          activeTty = res.j.tty;
          modalStatusEl.textContent = "tty " + activeTty;
          var term = new Terminal(modalBodyEl, activeTty);
          term._onStatusChange = function (s) { if (activeTerm === term) modalStatusEl.textContent = "tty " + activeTty + " · " + s; };
          activeTerm = term;
          term.attach();
        })
        .catch(function (e) {
          if (activeSid !== sid) return;
          modalStatusEl.textContent = "";
          modalBodyEl.innerHTML = '<div class="empty vtempty">failed to reach the server: ' + esc(String(e)) + "</div>";
        });
    });
  }

  function closeVT() {
    if (overlay) overlay.style.display = "none";
    if (activeTerm) { activeTerm.destroy(); activeTerm = null; }
    activeTty = null; activeSid = null;
  }

  function openNewTab() {
    if (!activeTty) return;
    var url = location.origin + location.pathname + "?tty=" + encodeURIComponent(activeTty);
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
    var tty = new URLSearchParams(location.search).get("tty");
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
    var term = new Terminal(mount, tty);
    var status = document.createElement("div");
    status.className = "vtfullstatus";
    status.textContent = "tty " + tty + " · connecting…";
    mount.appendChild(status);
    term._onStatusChange = function (s) { status.textContent = "tty " + tty + " · " + s; };
    term.attach();
    window.addEventListener("resize", debounce(function () { term.measureAndResize(); }, 150));
  })();
})();
