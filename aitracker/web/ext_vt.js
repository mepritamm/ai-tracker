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

    container.innerHTML = "";
    var pane = document.createElement("div");
    pane.className = "vtpane";
    var rowsEl = document.createElement("div");
    rowsEl.className = "vtrows";
    var cursorEl = document.createElement("div");
    cursorEl.className = "vtcursor";
    var input = document.createElement("textarea");
    input.className = "vtinput";
    input.setAttribute("autocomplete", "off");
    input.setAttribute("autocapitalize", "off");
    input.setAttribute("autocorrect", "off");
    input.setAttribute("spellcheck", "false");
    input.setAttribute("aria-label", "Terminal input");
    pane.appendChild(rowsEl);
    pane.appendChild(cursorEl);
    pane.appendChild(input);
    container.appendChild(pane);

    this.pane = pane; this.rowsEl = rowsEl; this.cursorEl = cursorEl; this.input = input;

    var self = this;
    pane.addEventListener("mousedown", function (ev) { ev.preventDefault(); input.focus(); });
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
    var rows = msg.rows || [];
    for (var i = 0; i < rows.length; i++) {
      var entry = rows[i];
      var r = entry[0] | 0;
      if (r < 0 || r >= this.grid.length) continue;   // a resize raced the stream -- drop stale rows
      this.grid[r] = { text: String(entry[1] || ""), runs: entry[2] || [] };
      this._paintRow(r);
    }
    if (msg.cursor && msg.cursor.length === 2) {
      this.cursor = [msg.cursor[0] | 0, msg.cursor[1] | 0];
      this._layoutCursor();
    }
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
    var row = this.grid[r], el = this.rowEls[r];
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

  Terminal.prototype._onKeyDown = function (ev) {
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
    if (v) { this._send(v); this.input.value = ""; }
  };
  Terminal.prototype._send = function (s) {
    postKeys(this.ttyId, s);
  };
  Terminal.prototype.destroy = function () {
    if (this.es) { this.es.close(); this.es = null; }
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
