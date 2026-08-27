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
//   A CONCURRENT agent (a separate worktree, mid-build as this file is being written) is adding a
//   `mouse` field to the same SSE frame: `"mouse": {"mode": 0, "sgr": false}` — `mode` is 0
//   (tracking off) or the DEC private-mode number in effect (1000 press/release, 1002
//   press/release+drag, 1003 all motion); `sgr` is whether `?1006` (SGR extended coordinates) is
//   also on. Read defensively the same way, defaulting to `{mode: 0, sgr: false}` in the
//   constructor so nothing here breaks if term_vt.py in this worktree doesn't emit it yet.
//
// ===== FOCUS REPORTING (this session): `msg.focus_events` ===============================
//   term_vt.Screen.snapshot() gained a `focus_events` boolean — DEC private mode `?1004`,
//   tracked and published exactly like `bracketed_paste`/`mouse` above. Read defensively in
//   _applyPatch, defaulting to false in the constructor. While on, the capture textarea's own
//   focus/blur listeners (already wired for the `vtfocused` CSS class) additionally send
//   `ESC[I` (focus) / `ESC[O` (blur) — the terminal equivalent of the `mouse` field driving
//   _onMouseMove/_sendMouseReport. While off: unchanged, nothing sent, byte-for-byte today's
//   behaviour.
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

  // ===== SGR runs -> CSS classes + inline colour style (see the contract comment above the IIFE) =
  // Mirrors ext_run.js's sgrClass() numeric ranges 1:1 so Tier 2 and Tier 3 render the same
  // colours from the same SGR codes -- but as an ABSOLUTE mapping (one run in, one {cls, style}
  // pair out), not a delta/reset walk over a byte stream, because a Screen run already IS the
  // resolved state for that span.
  //
  // 256-colour (38;5;N / 48;5;N) and true-colour (38;2;R;G;B / 48;2;R;G;B) SUPPORT: term_vt.py's
  // SGR parser (Screen._sgr, term_vt.py) already resolves these into the run's code string
  // verbatim -- e.g. "38;5;208" or "7;48;2;10;20;30" -- CONFIRMED by reading Screen._sgr and
  // Screen._recompute_code there before writing this. The 16-colour codes stay on the existing
  // vtf*/vtg* CSS-class path untouched; 256-colour indices 0-15 are mapped onto THOSE SAME
  // classes (one set of CSS rules, not a second copy -- see _stdColorClass below) so they render
  // identically to the plain 16-colour codes. Indices 16-255 and full RGB have no fixed class
  // (16.7M possible colours), so they produce an inline `style` string instead -- built ONLY from
  // validated integers (see _byte255 below), never from the raw SGR text, so a malformed or
  // out-of-range sequence can never inject anything into the markup _paintRow assembles from this
  // (see _paintRow's own comment for how `style` lands in the attribute).
  function _byte255(tok) {
    // Strict: digits only (no sign, no leading "+", no trailing junk) and in [0, 255] -- anything
    // else means the sequence is malformed/out-of-range and this colour must be dropped rather
    // than guessed at.
    if (!/^\d+$/.test(tok)) return null;
    var v = parseInt(tok, 10);
    return (v >= 0 && v <= 255) ? v : null;
  }
  // xterm-256 palette indices 0-15 reuse the SAME class tokens the plain 30-37/90-97 (fg) and
  // 40-47 (bg) SGR codes already use -- see the CSS comment above .vtf30 for the rule this must
  // stay in sync with. `isBg` picks the 40../100.. family instead of 30../90...
  function _stdColorClass(idx, isBg) {
    var base = idx < 8 ? (isBg ? 40 : 30) + idx : (isBg ? 100 : 90) + (idx - 8);
    return (isBg ? "vtg" : "vtf") + base;
  }
  // xterm's 6x6x6 colour cube (indices 16-231): each of the 3 axes is a "level" 0-5, converted to
  // an 8-bit component with the standard xterm formula -- 0 stays 0, levels 1-5 map to
  // 95/135/175/215/255 (55 + 40*level), NOT a linear 0..255 spread.
  function _cubeLevel(l) { return l === 0 ? 0 : 55 + 40 * l; }
  function _256Rgb(idx) {
    if (idx <= 231) {
      var i = idx - 16;
      return [_cubeLevel(Math.floor(i / 36)), _cubeLevel(Math.floor(i / 6) % 6), _cubeLevel(i % 6)];
    }
    var v = 8 + 10 * (idx - 232);   // 232-255: 24-step greyscale ramp, 8..238
    return [v, v, v];
  }
  function sgrRunClass(sgr) {
    var out = [], style = "";
    var parts = (sgr || "").split(";");
    var n = parts.length;
    var i = 0;
    while (i < n) {
      var p = parts[i];
      if (p !== "") {
        var v = parseInt(p, 10);              // classes come from parsed integers only
        if (isFinite(v)) {
          if (v === 1) out.push("vtb");
          else if (v === 3) out.push("vti");
          else if (v === 4) out.push("vtu");
          else if (v === 7) out.push("vtr");
          else if ((v >= 30 && v <= 37) || (v >= 90 && v <= 97)) out.push("vtf" + v);
          // BOTH ranges here -- not just 40-47 -- because term_vt.py's Screen._sgr (confirmed by
          // reading it) stores a direct aixterm bright-background code (100-107) VERBATIM in the
          // run's sgr string, exactly like it does for the 90-97 bright-foreground codes on the
          // line above; it does NOT normalise 100-107 through the 48;5;N extended-colour form.
          // This branch used to stop at 47, so a program emitting `\x1b[100m` directly (not via
          // 48;5;8) got no background class at all -- a second, independent way for the SAME
          // bright-background-invisible bug to happen, on top of the 48;5;N low-index path
          // _stdColorClass below already handles.
          else if ((v >= 40 && v <= 47) || (v >= 100 && v <= 107)) out.push("vtg" + v);
          else if (v === 38 || v === 48) {
            // Extended (256-colour / truecolor) fg (38) or bg (48) -- mirrors Screen._sgr's own
            // handling of the SAME truncated/malformed forms it has to defend against (see the
            // comment there): a truncated "38;5" with no index, "38;2" with <3 RGB components, or
            // an unrecognised colour-space id must still consume whatever sub-params it DID see so
            // they can never fall through and be reinterpreted as unrelated SGR codes.
            var isBg = (v === 48);
            if (i + 1 < n) {
              var mode = parseInt(parts[i + 1], 10);
              if (mode === 5 && i + 2 < n) {
                var idx = _byte255(parts[i + 2]);
                if (idx !== null) {
                  if (idx < 16) out.push(_stdColorClass(idx, isBg));
                  else {
                    var rgb = _256Rgb(idx);
                    style += (isBg ? "background-color:rgb(" : "color:rgb(") + rgb.join(",") + ");";
                  }
                }
                i += 2;
              } else if (mode === 2 && i + 4 < n) {
                var r = _byte255(parts[i + 2]), g = _byte255(parts[i + 3]), b = _byte255(parts[i + 4]);
                if (r !== null && g !== null && b !== null) {
                  style += (isBg ? "background-color:rgb(" : "color:rgb(") + r + "," + g + "," + b + ");";
                }
                i += 4;
              } else if (mode === 2 || mode === 5) {
                i = n - 1;           // incomplete extended sequence -- swallow the malformed tail
              } else {
                i += 1;              // unrecognised colour-space id -- consume just it
              }
            }
            // else: 38/48 was the final token with nothing after it -- no-op, nothing to consume
          }
        }
      }
      i++;
    }
    return { cls: out.join(" "), style: style };
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
      // Ctrl+Space -> NUL. FLAGGED: this is the plain ASCII C0 convention (Ctrl+@ = NUL), NOT
      // something xterm's own ctlseqs document specifies -- the researcher could not confirm
      // Ctrl+Space, Ctrl+2..8 or Ctrl+/ against that primary source. Only this one (unambiguous,
      // universally relied on) is implemented; the others are deliberately left unguessed.
      if (k === " ") return "\x00";
    }
    // Meta/Alt prefix (readline's Alt+<letter> word-motion convention, e.g. Alt+b -> ESC b) only
    // makes sense for a PLAIN ASCII character. `ev.key.length === 1` alone is not that test: on
    // macOS, Option is `altKey`, and Option+key produces a COMPOSED character -- Option+2 arrives
    // as `{altKey: true, key: "€"}` ("€" is a single UTF-16 code unit, so `.length` is
    // still 1), and prefixing that with ESC corrupts a character the user simply typed. AltGr on
    // European layouts (@, #, €, ~, \\ on many keyboards) has the same failure mode. Restrict
    // to the printable ASCII range so only a real plain-ASCII Alt+<char> takes this path; anything
    // else returns null and falls through to the textarea, which _onInput reads correctly (see the
    // comment above keyToBytes about why composed input is read off the textarea, not here).
    //
    // AltGr on Windows/Linux reports BOTH `ctrlKey` and `altKey` set -- that is already excluded
    // by this line's own `!ev.ctrlKey` guard, independent of the ASCII check added here.
    if (ev.altKey && !ev.ctrlKey && !ev.metaKey && /^[\x20-\x7e]$/.test(ev.key)) return "\x1b" + ev.key;

    // ===== modifier-aware cursor/nav/function keys =====
    // xterm ctlseqs (invisible-island.net/xterm/ctlseqs/ctlseqs.html), Patch #411: modified cursor
    // keys, PC-style Home/End, the tilde-numbered keys and the function keys all carry a modifier
    // parameter Pm = 1 + 1*Shift + 2*Alt + 4*Ctrl + 8*Meta. Pm is only APPENDED when a modifier is
    // actually held -- Pm === 1 (nothing held) must still emit the plain form the program already
    // expects; sending ";1" unconditionally would break every unmodified arrow press.
    var pm = 1 + (ev.shiftKey ? 1 : 0) + (ev.altKey ? 2 : 0) + (ev.ctrlKey ? 4 : 0) + (ev.metaKey ? 8 : 0);
    var plain = (pm === 1);

    switch (ev.key) {
      case "Enter":
        // Plain Enter stays unmodified \r. Alt+Enter is the standard Meta encoding (ESC prefix) --
        // what Claude Code reads as "insert a newline, don't submit". Shift+Enter and Ctrl+Enter
        // have no portable xterm encoding of their own for Enter, so both fall back to plain \r
        // rather than inventing one.
        if (ev.altKey && !ev.ctrlKey && !ev.metaKey) return "\x1b\r";
        return "\r";
      case "Backspace": return "\x7f";
      case "Tab": return ev.shiftKey ? "\x1b[Z" : "\t";
      case "Escape": return "\x1b";
      case "ArrowUp": return plain ? "\x1b[A" : "\x1b[1;" + pm + "A";
      case "ArrowDown": return plain ? "\x1b[B" : "\x1b[1;" + pm + "B";
      case "ArrowRight": return plain ? "\x1b[C" : "\x1b[1;" + pm + "C";
      case "ArrowLeft": return plain ? "\x1b[D" : "\x1b[1;" + pm + "D";
      case "Home": return plain ? "\x1b[H" : "\x1b[1;" + pm + "H";
      case "End": return plain ? "\x1b[F" : "\x1b[1;" + pm + "F";
      case "PageUp": return plain ? "\x1b[5~" : "\x1b[5;" + pm + "~";
      case "PageDown": return plain ? "\x1b[6~" : "\x1b[6;" + pm + "~";
      case "Delete": return plain ? "\x1b[3~" : "\x1b[3;" + pm + "~";
      case "Insert": return plain ? "\x1b[2~" : "\x1b[2;" + pm + "~";
      // Function keys -- NEW: previously fell through to `return null` and were swallowed
      // entirely. Plain F1-F4 use SS3 (\x1bO<letter>); modified substitutes CSI for SS3 with an
      // explicit leading "1" (\x1b[1;Pm<letter>). Plain and modified F5-F12 both use the
      // tilde form, same shape as the tilde keys above.
      case "F1": return plain ? "\x1bOP" : "\x1b[1;" + pm + "P";
      case "F2": return plain ? "\x1bOQ" : "\x1b[1;" + pm + "Q";
      case "F3": return plain ? "\x1bOR" : "\x1b[1;" + pm + "R";
      case "F4": return plain ? "\x1bOS" : "\x1b[1;" + pm + "S";
      case "F5": return plain ? "\x1b[15~" : "\x1b[15;" + pm + "~";
      case "F6": return plain ? "\x1b[17~" : "\x1b[17;" + pm + "~";
      case "F7": return plain ? "\x1b[18~" : "\x1b[18;" + pm + "~";
      case "F8": return plain ? "\x1b[19~" : "\x1b[19;" + pm + "~";
      case "F9": return plain ? "\x1b[20~" : "\x1b[20;" + pm + "~";
      case "F10": return plain ? "\x1b[21~" : "\x1b[21;" + pm + "~";
      case "F11": return plain ? "\x1b[23~" : "\x1b[23;" + pm + "~";
      case "F12": return plain ? "\x1b[24~" : "\x1b[24;" + pm + "~";
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

  // ===== shared pane-resize watcher (Terminal + XtermTerminal) =====
  // BUG this closes: .vtctxbar (ContextBar) starts hidden and later flips to display:"" the first
  // time /api/session polling returns usage data -- an async, POST-ATTACH layout change. Both
  // .vttermwrap (which holds the toolbar+pane) and .vtctxbar are flex:0/1 SIBLINGS inside the same
  // flex-column container (.mb.vtmb in the modal, `mount` in the standalone tab -- see openVT's and
  // bootStandalone's own DOM-assembly comments), so that flip shrinks .vttermwrap via ordinary
  // flexbox, which in turn shrinks .vtpane (flex:1 1 auto inside .vttermwrap's own flex column).
  // Neither renderer's explicit resize triggers (attach()'s one-shot rAF, the debounced `window`
  // resize listener) fire for a sibling's height change -- only an observer on the pane itself
  // does, and it's correct to observe the PANE regardless of which ancestor's flex recalculation
  // caused the change: a ResizeObserver reports the target's own border box, however it moved.
  // One tiny helper so Terminal (grid) and XtermTerminal (canvas) share this instead of each
  // wiring/tearing down its own ResizeObserver. `fn` must already be debounced by the caller (see
  // debounce() above) -- this stays a thin observe/dispose wrapper, not a second debouncer.
  function observePane(pane, fn) {
    if (!window.ResizeObserver) return function () { };
    var ro = new ResizeObserver(fn);
    ro.observe(pane);
    return function () { ro.disconnect(); };
  }

  // ===== shared zoom toolbar: ITS OWN flex row, ABOVE the pane -- never an overlay on top of
  // terminal output. LAYOUT-BUG FIX (see ext_vt.css's .vttoolbar comment for the full story): the
  // A-/A+ controls used to be absolutely positioned inside .vtpane's top-right corner, overlapping
  // row 0's real content. Both renderers (Terminal below and XtermTerminal further down) build
  // this the same way and append it as a sibling BEFORE their own pane, so the fix covers both
  // paths from one place rather than being reimplemented per-renderer. =====
  function buildToolbar(onZoomOut, onZoomIn, onAfterZoom, mouseToggle, rendererSwitch) {
    var bar = document.createElement("div");
    bar.className = "vttoolbar";
    // ===== theme flipper (this session): the terminal opens in a full-screen .overlay (app.css,
    // z-index 50) that COVERS app.js's own #themebtn in the top bar, so a user with a terminal
    // open has no way to flip dark/light -- this button is the per-terminal escape hatch. It does
    // NOT reimplement theme logic: it calls the exact same global toggleTheme() the top-bar button
    // calls, so app.js's setTheme() stays the single owner of the class toggle/persistence/meta-
    // color/the "themechange" event this button (and XtermTerminal's live re-theme, see that
    // class's own constructor/destroy) listen for. Built once here so both renderers get it from
    // one place, same as the mouse/renderer switches above.
    var themeBtn = document.createElement("span");
    themeBtn.className = "vtzoombtn vtthemebtn";
    themeBtn.title = "Toggle dark/light theme";
    themeBtn.setAttribute("role", "switch");
    themeBtn.setAttribute("tabindex", "0");
    function renderThemeBtn() {
      // Mirrors app.js's own setTheme() convention exactly: "🌙" while light (tap for dark),
      // "☀️" while dark (tap for light) -- read live off <html>'s class rather than cached, since
      // this can be re-rendered long after the button was built (top-bar toggle, another pane's
      // toggle, or this same button).
      var light = document.documentElement.classList.contains("light");
      themeBtn.textContent = light ? "🌙" : "☀️";
      themeBtn.setAttribute("aria-pressed", light ? "true" : "false");
    }
    function activateThemeBtn() {
      toggleTheme();   // app.js global -- flips the class, persists it, fires "themechange"
      onAfterZoom();   // refocus the capture textarea, exactly like the zoom/mouse buttons above
    }
    themeBtn.addEventListener("click", activateThemeBtn);
    themeBtn.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); activateThemeBtn(); }
    });
    // Document-level listener so this button stays in sync when theme is flipped some OTHER way
    // (the top-bar button, or a second open terminal's own theme button) -- same "leaks past this
    // element's own DOM teardown unless explicitly removed" situation Terminal.prototype's own
    // _onDocMouseUp comment describes. `bar.disposeThemeBtn` is exposed exactly like
    // `bar.refreshMouseToggle` above so each owning class (Terminal/XtermTerminal) can save it and
    // call it from its own destroy() -- see those constructors/destroy methods.
    document.addEventListener("themechange", renderThemeBtn);
    bar.disposeThemeBtn = function () { document.removeEventListener("themechange", renderThemeBtn); };
    renderThemeBtn();
    bar.appendChild(themeBtn);
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
    // ===== mouse-reporting toggle (this session) ===========================================
    // Commit 4bc3e08 added mouse forwarding: once a TUI (Claude Code's own included) turns on
    // `?1000`/`?1002`/`?1003` tracking, every drag inside the pane became a mouse report instead
    // of a native text selection. Shift+drag still works (XTSHIFTESCAPE, see the Terminal class's
    // own _mouseGate) but that escape hatch isn't discoverable and isn't what most users want by
    // default -- this button is the visible, PER-TERMINAL fix: default OFF, flip it on only when
    // you actually want clicks/drags to reach the program running inside the pane.
    // `mouseToggle` is a tiny renderer-agnostic interface (not a DOM/class check) so this ONE
    // function serves both Terminal (a real gate wired into _mouseGate below) and XtermTerminal
    // (permanently inert -- xterm.js owns its own mouse handling; see that constructor's call site
    // for why forwarding through here would fight it instead of helping it):
    //   getEnabled()   -> current on/off state to render
    //   setEnabled(v)  -> called on a real (non-inert) click/tap
    //   isMeaningful() -> whether toggling would currently do anything; false dims the button and
    //                     makes it a no-op (requirement: offer it only when it's meaningful, but
    //                     never hide it -- no host/viewport gate, see ext_vt.css's .vtmousebtn).
    var mouseBtn = document.createElement("span");
    mouseBtn.className = "vtzoombtn vtmousebtn";
    mouseBtn.setAttribute("role", "switch");
    mouseBtn.setAttribute("tabindex", "0");
    function renderMouseBtn() {
      var on = mouseToggle.getEnabled();
      var meaningful = mouseToggle.isMeaningful();
      mouseBtn.textContent = on ? "🖱 on" : "🖱 off";   // "🖱 on" / "🖱 off"
      mouseBtn.setAttribute("aria-pressed", on ? "true" : "false");
      mouseBtn.classList.toggle("vtmouseon", on);
      mouseBtn.classList.toggle("vtmouseinert", !meaningful);
      mouseBtn.title = !meaningful
        ? "Mouse reporting has no effect right now — nothing running here has asked for mouse tracking."
        : (on
          ? "Mouse reporting is ON: clicks and drags go to the program running here. Shift+drag still selects text. Tap to turn off."
          : "Mouse reporting is OFF: dragging selects text like a normal terminal. Tap to turn it on so clicks reach the program (Shift+drag always selects text either way).");
    }
    function activateMouseToggle() {
      if (!mouseToggle.isMeaningful()) return;   // inert: nothing running here wants mouse tracking
      mouseToggle.setEnabled(!mouseToggle.getEnabled());
      renderMouseBtn();
      onAfterZoom();   // refocus the capture textarea, exactly like a zoom click does
    }
    mouseBtn.addEventListener("click", activateMouseToggle);
    // Keyboard activation (Enter/Space) alongside tap/click -- the tap path itself needs no special
    // handling: a `click` fires for a tap on any element with no touch-action interference, same as
    // the pre-existing A-/A+ buttons above, which are usable on phone today with this exact pattern.
    mouseBtn.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); activateMouseToggle(); }
    });
    renderMouseBtn();
    bar.appendChild(mouseBtn);
    // Exposed so the owner can re-render when meaningfulness changes out from under the click --
    // e.g. Terminal's own _applyPatch calls this after a fresh `mouse.mode` arrives over SSE.
    bar.refreshMouseToggle = renderMouseBtn;

    // ===== renderer switch (this session): xterm.js is now the DEFAULT renderer, with the
    // built-in grid painter (`Terminal`, above) kept available ON DEMAND -- see config.TERM_
    // RENDERER for the server-side default. This button is what makes that switch reachable, per
    // terminal, from the UI. The server still owns the DEFAULT: `rendererSwitch.getActive()`
    // starts at whatever openVT()/bootStandalone() read off the server a few lines below this
    // file's own header comment ("SECOND RENDER PATH") -- this control is a later, EXPLICIT
    // per-terminal user override layered on top, same category as the mouse-reporting toggle just
    // above and the A-/A+ zoom controls, so it does NOT violate conventions rule 5 ("server owns
    // policy, client renders it"): the user is choosing among renderers the server already
    // exposed, not deciding what a FRESH terminal opens with next time.
    // `rendererSwitch` mirrors `mouseToggle`'s own tiny renderer-agnostic shape:
    //   getActive()      -> "grid" | "xterm", whichever is live right now
    //   switchTo(target) -> destroy the current terminal, build `target` against the SAME tty,
    //                       re-wire the ContextBar to it (see openVT/bootStandalone's own
    //                       switch functions for exactly how)
    // Switching TO xterm leaves the pane BLANK until the program's next write -- GET /api/term/raw
    // only tees bytes emitted after the stream opens, so there is no repaint of whatever was
    // already on screen (see this file's "SECOND RENDER PATH" header comment and XtermTerminal's
    // own "KNOWN GAPS" comment). Switching to grid repaints immediately from the server's retained
    // Screen. That asymmetry is spelled out in the title/aria-label below, not hidden (this file's
    // own brief, requirement 6) -- a user who lands on a blank xterm pane has an honest reason why.
    var rendererBtn = document.createElement("span");
    rendererBtn.className = "vtzoombtn vtrendererbtn";
    rendererBtn.setAttribute("role", "switch");
    rendererBtn.setAttribute("tabindex", "0");
    function renderRendererBtn() {
      var isXterm = rendererSwitch.getActive() === "xterm";
      rendererBtn.textContent = isXterm ? "▤ xterm" : "▦ grid";
      rendererBtn.setAttribute("aria-pressed", isXterm ? "true" : "false");
      rendererBtn.setAttribute("aria-label", isXterm
        ? "Renderer: xterm.js. Tap to switch to the built-in grid renderer."
        : "Renderer: built-in grid. Tap to switch to xterm.js.");
      rendererBtn.classList.toggle("vtrendererxterm", isXterm);
      rendererBtn.title = isXterm
        ? "Renderer: xterm.js. Tap to switch to the built-in grid renderer — it repaints instantly from the current screen (server-retained), unlike the switch below."
        : "Renderer: built-in grid. Tap to switch to xterm.js — the pane goes BLANK until the program next writes anything (no repaint of what's already on screen; xterm.js has no server-side scrollback to repaint FROM).";
    }
    function activateRendererSwitch() {
      var next = rendererSwitch.getActive() === "xterm" ? "grid" : "xterm";
      rendererSwitch.switchTo(next);
      // No renderRendererBtn()/onAfterZoom() call here, unlike the mouse toggle above: switchTo
      // destroys THIS terminal (and this toolbar along with it, via its own container.innerHTML =
      // "") and builds a fresh one, whose own buildToolbar call renders its OWN button already in
      // the correct state and focuses the new terminal on attach -- see openVT's
      // switchActiveRenderer / bootStandalone's mountRenderer. Touching `rendererBtn` here would
      // just be poking an already-detached element.
    }
    rendererBtn.addEventListener("click", activateRendererSwitch);
    rendererBtn.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); activateRendererSwitch(); }
    });
    renderRendererBtn();
    bar.appendChild(rendererBtn);
    return bar;
  }

  // Fallback rendererSwitch for a Terminal/XtermTerminal built with no third constructor arg (e.g.
  // a hand-rolled test double that only exercises the older 2-arg shape). Reports "grid" so the
  // button still renders something sane, and switching is a harmless no-op rather than a throw.
  var _noopRendererSwitch = { getActive: function () { return "grid"; }, switchTo: function () { } };

  // ===== Terminal: one live grid + key capture, mounted into any container =====
  // Third constructor arg is the renderer-switch interface -- see buildToolbar's own comment. It
  // used to be read via `arguments[2]` instead of a named parameter, because this file's own
  // signature `function Terminal(container, ttyId) {` was pinned VERBATIM by a couple dozen
  // existing assertions in tests/test_term_vt_client.py (each locating this constructor's body by
  // searching for that exact string) -- a third named parameter would have shifted that literal
  // and broken every one of them for a change that had nothing to do with what they were actually
  // pinning. `_function_body` there now matches by PREFIX (see its own docstring), so the
  // signature is free to grow again; the named parameter replaces the old `arguments[2]` read.
  function Terminal(container, ttyId, rendererSwitch) {
    rendererSwitch = rendererSwitch || _noopRendererSwitch;
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
    this.mouse = { mode: 0, sgr: false };  // msg.mouse -- see the header comment's caveat; default
                                            // (tracking off) preserves today's native-selection/
                                            // scrollback behaviour until the server sends otherwise.
    // ---- user-facing mouse-reporting toggle (this session; see buildToolbar's own comment) ----
    // Default OFF: even once a program turns tracking on (this.mouse.mode above), plain dragging
    // keeps selecting text like it did before commit 4bc3e08 -- the user has to opt in via the
    // toolbar button before clicks/drags start reaching the program. PER-INSTANCE, deliberately
    // NOT persisted (no new JSON state file) -- same choice as `_fontPx`/`_linePx` below: a fresh
    // terminal always starts predictable (native selection), never silently inherits a stale
    // "reporting on" state from a previous pane/session.
    this.mouseReportingEnabled = false;
    this.focusEvents = false;              // msg.focus_events -- see the header comment's "FOCUS
                                            // REPORTING" section; default (off) sends nothing on
                                            // focus/blur, byte-for-byte today's behaviour.
    this._mouseButtonDown = null;          // which button (0/1/2, ctlseqs numbering) is currently
                                            // held, for mode 1002's drag-only motion gate; null
                                            // when nothing is down.
    this._lastMouseCell = null;            // {row, col} of the last motion report sent, so a drag
                                            // is throttled to one report per CELL change, not per
                                            // pixel (see _onMouseMove).
    // ---- send ordering + motion coalescing (see _send/_sendMotion below) ----
    this._sendChain = Promise.resolve();   // every send is queued onto this ONE promise chain, so
                                            // bytes reach /api/term/keys in production order even
                                            // though postKeys() fires independent fetch()es.
    this._sendTimers = [];                 // outstanding setTimeout ids from _sendWithTimeout below
                                            // (see that function's comment); destroy() clears every
                                            // one still pending so no timer outlives this terminal.
    this._pendingMotion = null;            // newest not-yet-flushed motion report, or null.
    this._motionRAFPending = false;        // an rAF flush is already scheduled for it.
    this._motionRAFHandle = null;          // requestAnimationFrame()'s own id for that scheduled
                                            // flush, or null -- kept ONLY so destroy() can
                                            // cancelAnimationFrame() it; see _sendMotion/destroy.
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
      function () { input.focus(); },
      {
        getEnabled: function () { return self.mouseReportingEnabled; },
        setEnabled: function (v) { self.mouseReportingEnabled = v; },
        isMeaningful: function () { return self.mouse.mode !== 0; }
      },
      rendererSwitch
    );
    this._refreshMouseToggle = toolbarEl.refreshMouseToggle;   // called from _applyPatch below
    this._disposeThemeBtn = toolbarEl.disposeThemeBtn;   // called from destroy() below
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

    // Re-measure whenever the pane's OWN box changes for a reason none of this class's other
    // triggers cover -- most notably .vtctxbar flipping visible after attach (see observePane's
    // own comment, just above buildToolbar, for the full mechanism). measureAndResize() already
    // re-POSTs /api/term/resize when cols/rows actually change, so the server pty stays in sync
    // for free; debounced the same way XtermTerminal debounces its own resize work (150ms).
    this._resizeDebounced = debounce(function () { self.measureAndResize(); }, 150);
    this._disposePaneObserver = observePane(pane, this._resizeDebounced);

    this._scrollHistoryDebounced = debounce(function (offset) { self._scrollHistory(offset); }, 30);
    // No preventDefault here (requirement 2's whole point): blocking the mousedown default is
    // what stops native text selection from ever starting. Focusing the capture textarea on the
    // same event still routes the next keystroke to the PTY without touching the emerging
    // selection -- selection anchoring is driven by the browser off the ORIGINAL mousedown target
    // (a .vtrow text node now that the input no longer overlays the pane), not by DOM focus.
    // _onMouseDown/_onMouseMove/_onMouseUp run AFTER focus() unconditionally fires, and are
    // themselves a no-op (see _mouseGate) unless a program has actually turned mouse tracking on
    // and Shift isn't held -- so this line's own native-selection behaviour is untouched whenever
    // there's nothing to forward.
    pane.addEventListener("mousedown", function (ev) { input.focus(); self._onMouseDown(ev); });
    pane.addEventListener("mousemove", function (ev) { self._onMouseMove(ev); });
    pane.addEventListener("mouseup", function (ev) { self._onMouseUp(ev); });
    pane.addEventListener("wheel", function (ev) { self._onWheel(ev); }, { passive: false });
    // ===== outside-pane release fallback (stuck-drag fix) ==================================
    // The three listeners above are wired on `pane` only. A press-inside/drag-outside/
    // release-outside sequence (a very ordinary drag -- the pointer crosses the pane's edge before
    // the button comes up) then never fires `pane`'s own "mouseup", so `_mouseButtonDown` sticks:
    // every later plain hover reads as `dragging` (see _onMouseMove) with a stale button and the
    // `+32` bit, until the user happens to press inside the pane again. No pointer capture is used
    // here (setPointerCapture needs pointer events, a bigger surface change than this fix calls
    // for) -- instead, a single document-level "mouseup" catches any release the pane itself
    // didn't see. `pane.contains(ev.target)` skips a release that DID land inside the pane: the
    // pane's own listener is earlier in the bubble path (pane is a descendant of document) and
    // already ran by the time this one fires, so acting again here would double-send the release.
    this._onDocMouseUp = function (ev) {
      if (self._mouseButtonDown === null) return;   // no drag in progress -- nothing to clean up
      if (pane.contains(ev.target)) return;          // pane's own mouseup listener already handled it
      self._onMouseUp(ev);                            // clamped coords via _mouseCell; also clears
                                                        // _mouseButtonDown/_lastMouseCell when the
                                                        // gate (_mouseGate) allows the send
      // Belt-and-suspenders: a release ANYWHERE must end the drag, even on the rare path where the
      // gate above declined to send (e.g. Shift got pressed mid-drag) and so left state untouched.
      self._mouseButtonDown = null;
      self._lastMouseCell = null;
    };
    document.addEventListener("mouseup", this._onDocMouseUp);
    newOutEl.addEventListener("click", function () { self._scrollToBottom(); input.focus(); });
    // `?1004` focus reporting (this.focusEvents, read off every SSE frame -- see the header
    // comment's "FOCUS REPORTING" section): while a program has asked for it, focus/blur on the
    // capture textarea ALSO forward ESC[I / ESC[O to the PTY, on top of the pre-existing
    // vtfocused class toggle. Off (the default): nothing extra sent, unchanged from before.
    input.addEventListener("focus", function () {
      self.focused = true; pane.classList.add("vtfocused");
      if (self.focusEvents) self._send("\x1b[I");
    });
    input.addEventListener("blur", function () {
      self.focused = false; pane.classList.remove("vtfocused");
      if (self.focusEvents) self._send("\x1b[O");
    });
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
    if (msg.mouse !== undefined && msg.mouse) {
      if (typeof msg.mouse.mode === "number") this.mouse.mode = msg.mouse.mode;
      if (msg.mouse.sgr !== undefined) this.mouse.sgr = !!msg.mouse.sgr;
      // The toolbar toggle's "meaningful" state (see buildToolbar) tracks this.mouse.mode -- a
      // program can turn tracking on/off mid-session, so the button's dim/inert look must follow
      // the SSE stream, not just react to the user's own clicks.
      if (this._refreshMouseToggle) this._refreshMouseToggle();
    }
    if (msg.focus_events !== undefined) this.focusEvents = !!msg.focus_events;
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
      var sgrOut = sgrRunClass(run[2]);
      var cls = sgrOut.cls, style = sgrOut.style;   // style: built ONLY from validated integers by
                                                     // sgrRunClass (never from raw SGR text) --
                                                     // safe to place verbatim in the attribute below.
      var glyphs = s < text.length ? text.slice(s, Math.min(e, text.length)) : "";
      var tailPad = Math.max(0, e - Math.max(s, text.length));        // the part of this run past text.length
      var chunk = esc(glyphs) + esc(_padSpaces(tailPad));
      if (cls || style) {
        html += "<span" + (cls ? ' class="' + cls + '"' : "") + (style ? ' style="' + style + '"' : "") + ">" + chunk + "</span>";
      } else {
        html += chunk;
      }
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
  // ===== send ordering =====================================================================
  // postKeys() issues an independent fetch() per call with no sequencing of its own -- two sends
  // in flight at once can land at the server out of order over the network (a PRE-EXISTING latent
  // bug, not new here). For keystrokes that means fast typing can transpose characters; for mouse
  // it means a release can land before its press, which `?1003` any-motion tracking turns from a
  // rare race into a routine one (many more sends per second). Every discrete send -- keystrokes,
  // pasted/composed text, mouse press/release, wheel-as-arrows/mouse-report -- goes through
  // `_send`, below, which enqueues onto this ONE promise chain (`_enqueue`), so bytes reach
  // /api/term/keys in the order they were PRODUCED, not the order their fetch()es happen to
  // resolve. This is also what makes fast typing safe, not just mouse: it is the same ordering
  // fix either way, chained once here rather than solved per call site.
  //
  // MOTION ORDERING GUARANTEE: coalesced motion reports (the motion-coalescing path further
  // below) are only appended to the chain when their rAF callback fires -- strictly LATER than
  // when they were produced. Left alone, that lets a discrete event produced AFTER a pending
  // motion reach the chain BEFORE that motion's rAF fires -- reordering, say, a release ahead of
  // the motion that preceded it. `_send` closes that gap: it flushes any pending motion into the
  // chain FIRST (`_flushMotion`, which calls `_enqueue` directly -- NOT `_send` again, so there is
  // no `_send` -> `_flushMotion` -> `_send` recursion), and only THEN enqueues its own bytes. A
  // pending motion can therefore never be overtaken by a later discrete event. When the motion's
  // own rAF callback eventually fires, `_pendingMotion` is already null (the discrete flush
  // consumed it), so that callback's own `_flushMotion` call is a no-op -- the same report is
  // never enqueued twice. `_enqueue` is the ONE place that appends to `_sendChain`; both `_send`
  // and `_flushMotion` go through it.
  //
  // A rejected send (e.g. a network hiccup) must not wedge the chain forever -- the `.catch()`
  // swallows the failure inside the chain itself, so the NEXT queued `.then()` still runs.
  //
  // That covers a send that SETTLES (resolves or rejects). It does nothing for one that never
  // settles at all -- observed for real: a `POST /api/term/keys` hung for ~5 minutes under
  // Chrome's background-tab network throttling (a control `curl` to the same endpoint returned in
  // 17ms), which would otherwise wedge every later keystroke behind it permanently, with no error
  // and no recovery short of reopening the terminal. `_sendWithTimeout`, below, bounds each queued
  // send so the chain always advances even then.
  Terminal.prototype._enqueue = function (s) {
    var self = this;
    this._sendChain = this._sendChain.then(function () {
      return self._sendWithTimeout(s);
    }).catch(function () { });
  };
  // SEND TIMEOUT: races the real postKeys() promise against a timer, so a request that never
  // settles cannot block `_sendChain` forever -- see `_enqueue`'s comment above for the observed
  // hang this fixes. 5000ms: this is a LOCALHOST server (a healthy request here is single-digit
  // milliseconds, per the 17ms control curl above), so 5s is already an enormous margin above any
  // real response time and fires only on a genuinely wedged request.
  //
  // ORDERING TRADE-OFF (read before touching this): `_sendChain`'s own `.then()` chaining means
  // send N+1's `_sendWithTimeout` call -- and so its `postKeys()` fetch -- is only ISSUED after
  // send N's promise settles, real response or timeout alike, so sends are still produced onto the
  // wire in order during ordinary typing. But once a send times out, its underlying fetch() is
  // simply abandoned in flight (there is no cheap way to actually cancel it without adding
  // AbortController plumbing this file doesn't otherwise need) while the NEXT queued send's
  // fetch() starts immediately. That means the timed-out request and the one after it CAN now be
  // in flight on the network at the same time, and could in principle land at the server out of
  // order. This is the SAME class of hazard this file's own header comment above already
  // documents as pre-existing and latent (independent fetch()es have no ordering guarantee of
  // their own) -- not a new one, just a somewhat likelier occurrence of the old one -- and it is a
  // strictly better trade than every later keystroke hanging forever behind one dead request.
  //
  // The timed-out payload is DROPPED, exactly like an ordinarily-rejected send already is: this
  // function's synthesized timeout rejection is swallowed by the very same `.catch(function () {
  // })` in `_enqueue` above that already swallows a real network rejection. There is no retry --
  // a retried keystroke would be a DUPLICATED keystroke, which is worse than a dropped one.
  Terminal.prototype._sendWithTimeout = function (s) {
    var self = this;
    return new Promise(function (resolve, reject) {
      var settled = false;
      var timer = setTimeout(function () {
        if (settled) return;
        settled = true;
        var idx = self._sendTimers.indexOf(timer);
        if (idx !== -1) self._sendTimers.splice(idx, 1);
        reject(new Error("term send timed out"));
      }, 5000);
      self._sendTimers.push(timer);
      postKeys(self.ttyId, s).then(
        function (v) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          var idx = self._sendTimers.indexOf(timer);
          if (idx !== -1) self._sendTimers.splice(idx, 1);
          resolve(v);
        },
        function (e) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          var idx = self._sendTimers.indexOf(timer);
          if (idx !== -1) self._sendTimers.splice(idx, 1);
          reject(e);
        }
      );
    });
  };
  Terminal.prototype._flushMotion = function () {
    if (this._pendingMotion === null) return;   // nothing pending, or already flushed -- no-op,
                                                  // which is what makes a late rAF callback safe
    var s = this._pendingMotion;
    this._pendingMotion = null;
    this._enqueue(s);
  };
  Terminal.prototype._send = function (s) {
    this._flushMotion();   // any pending motion must reach the chain before this discrete event
    this._enqueue(s);
  };

  // ===== motion coalescing =================================================================
  // Only MOUSE MOTION reports (`?1003` any-motion, or `?1002` drag) are safe to coalesce: the
  // remote program only ever cares about the CURRENT pointer position, so dropping a superseded
  // motion report loses nothing it would have acted on differently. A press, a release, a wheel
  // report, and every keystroke are DISCRETE events -- each one is a state transition the remote
  // program must see individually (miss a button-up and it thinks the button is still held), so
  // none of those ever go through this path; they call `_send` directly. Motion is batched to at
  // most one flush per animation frame: the newest pending report wins, any superseded one is
  // silently dropped. The eventual rAF callback flushes through `_flushMotion` (NOT `_send` --
  // that would set up the `_send` -> `_flushMotion` -> `_send` recursion described in the ordering
  // comment above `_send`); see that comment for how a discrete event produced in the meantime can
  // still flush this same motion report first, and why the rAF callback below never sends it twice.
  Terminal.prototype._sendMotion = function (s) {
    this._pendingMotion = s;
    if (this._motionRAFPending) return;
    this._motionRAFPending = true;
    var self = this;
    // The id is kept on `self` (not just a local var) so destroy() -- called from OUTSIDE this
    // closure, possibly before this callback ever fires -- can cancelAnimationFrame() it. Nulled
    // here the instant the callback actually runs, BEFORE _flushMotion: once a frame has fired,
    // its id is spent (the browser will never call this callback again for it), so there is
    // nothing left for a later destroy() to cancel -- leaving the old id sitting in
    // _motionRAFHandle would risk destroy() cancelling a DIFFERENT, newer frame if that id were
    // ever reused. Only one rAF is ever outstanding at a time (guarded by _motionRAFPending
    // above), so this null/(re)assign pair never races a second in-flight frame.
    this._motionRAFHandle = requestAnimationFrame(function () {
      self._motionRAFPending = false;
      self._motionRAFHandle = null;
      self._flushMotion();
    });
  };
  Terminal.prototype.destroy = function () {
    if (this._disposeThemeBtn) { this._disposeThemeBtn(); this._disposeThemeBtn = null; }
    // See the constructor's own comment on observePane -- a ResizeObserver, like the document-
    // level listeners below, outlives its element unless explicitly disconnected.
    if (this._disposePaneObserver) { this._disposePaneObserver(); this._disposePaneObserver = null; }
    if (this.es) { this.es.close(); this.es = null; }
    // A motion flush scheduled via _sendMotion (see above) must never fire after teardown -- that
    // was a real stray POST /api/term/keys for an already-destroyed terminal (proven by executing
    // this exact sequence: schedule motion, destroy(), fire the pending rAF). Cancel the scheduled
    // frame outright, and ALSO clear the coalescing state so that even if cancellation somehow
    // failed to prevent the callback (or a motion was left pending with no rAF scheduled at all),
    // _flushMotion has nothing to send: _pendingMotion is null. See _sendMotion's own comment for
    // why _motionRAFHandle is never stale/pointing at a since-fired frame here.
    if (this._motionRAFHandle !== null) {
      cancelAnimationFrame(this._motionRAFHandle);
      this._motionRAFHandle = null;
    }
    this._motionRAFPending = false;
    this._pendingMotion = null;
    // Same reasoning, for the send-timeout timers from _sendWithTimeout (see that function's own
    // comment): a timer left running past destroy() would fire into a promise chain nobody is
    // waiting on any more -- harmless in itself, but still a live timer this terminal no longer
    // owns. Clear every one still pending; a timer that already fired and was removed from this
    // array is naturally skipped.
    for (var ti = 0; ti < this._sendTimers.length; ti++) clearTimeout(this._sendTimers[ti]);
    this._sendTimers = [];
    // See the constructor's "outside-pane release fallback" comment -- this is a document-level
    // listener, so it leaks past this terminal's own DOM teardown unless explicitly removed here
    // (same pattern as ContextBar's own `_onDocClick`, below).
    if (this._onDocMouseUp) { document.removeEventListener("mouseup", this._onDocMouseUp); this._onDocMouseUp = null; }
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

  // ===== mouse reporting: forwarded to the PTY only when a running program has actually turned
  // tracking on (`this.mouse.mode`, read off every SSE frame in _applyPatch above -- see the
  // header comment for the exact {mode, sgr} contract term_vt.Screen.snapshot() sends). Every
  // entry point below (mousedown/mousemove/mouseup/_onWheel) shares ONE gate, _mouseGate, checked
  // in this order:
  //   1. this.mouse.mode === 0 (tracking off) -> do exactly what the code already did: native
  //      selection, wheel = scrollback/alt-screen arrows. Nothing below this file's pre-existing
  //      behaviour changes.
  //   2. ev.shiftKey -> ALSO the pre-existing behaviour. This is XTSHIFTESCAPE's documented
  //      default (shiftEscape = 0): holding Shift lets the user make a native selection even while
  //      an app has mouse tracking on. It is the user's only escape hatch and must exist.
  //   3. this.viewingHistory -> never report. The grid on screen is a FROZEN scrollback snapshot
  //      (see the constructor's own scrollback-view comment); its row/col do not correspond to the
  //      live screen's, so there is nothing coherent to report coordinates against.
  //   4. otherwise -> the caller preventDefault()s, encodes, and sends.
  Terminal.prototype._mouseGate = function (ev) {
    if (this.mouse.mode === 0) return false;
    if (ev.shiftKey) return false;
    if (this.viewingHistory) return false;
    // 4. the user's own toolbar toggle (this session, see buildToolbar's comment and the
    //    constructor's `mouseReportingEnabled` field) -- default OFF: even once a program has
    //    asked for tracking, native drag-select stays the default until the user explicitly flips
    //    the toolbar button on. Checked with a strict `=== false` (never a plain falsy `!`): every
    //    REAL Terminal instance always initializes this field explicitly in its constructor, so
    //    `undefined` never occurs there.
    //
    //    tests/test_term_vt_exec.py's `makeSelf()` (a hand-built test double this file does not
    //    own) now ALSO initializes this field to a real boolean (`false`, matching this
    //    constructor's own default) rather than leaving it `undefined` -- see that file's
    //    TestMouseReportingToggleGateExecuted, which exercises this exact line by routing through
    //    the REAL extracted `getEnabled`/`setEnabled` closures, not a hand-poked field. That makes
    //    a plain `!this.mouseReportingEnabled` safe for makeSelf()'s callers today. It is kept
    //    strict anyway: tests/test_term_vt_client.py's TestMouseReportingToggle (a file also
    //    outside this task's ownership) pins this exact `=== false` source line by literal text
    //    (`test_mousegate_still_consults_mode_shift_and_viewinghistory_in_order` /
    //    `test_reaches_the_browser`), so relaxing the comparison here would need a matching edit
    //    there in the same change -- judged not worth doing one-sided.
    if (this.mouseReportingEnabled === false) return false;
    return true;
  };

  // Coordinates are 1-based, top-left is 1,1 (ctlseqs p.49). Derived from rowsEl's own
  // getBoundingClientRect() -- NOT the pane's: .vtpane is padded (8px 10px) and its border box is
  // offset from where rows actually start, so using the pane's rect would reintroduce exactly the
  // off-by-one-cell bug _layoutCursor's own comment describes fixing (see computeColsRows and the
  // cursor-origin comment above). Clamped to the live grid's own bounds.
  Terminal.prototype._mouseCell = function (ev) {
    var rect = this.rowsEl.getBoundingClientRect();
    var col = Math.floor((ev.clientX - rect.left) / this.cellW) + 1;
    var row = Math.floor((ev.clientY - rect.top) / this.cellH) + 1;
    col = Math.max(1, Math.min(this.cols, col));
    row = Math.max(1, Math.min(this.rows, row));
    return { row: row, col: col };
  };

  // Button encoding (ctlseqs p.49-52): base button (left=0, middle=1, right=2, from
  // this._mouseButtonDown -- the button a mousedown/mousemove/mouseup event is actually reporting
  // on, not necessarily ev.button, which is unreliable mid-drag). Modifiers ADD: Meta=8, Ctrl=16,
  // and motion/drag ADDS 32. Shift=4 is deliberately NOT encoded here: `_mouseGate` bypasses mouse
  // reporting entirely whenever Shift is held (the user's native-selection escape hatch, see that
  // function's own comment), so a Shift-held event never reaches this function at all -- there is
  // no live path that would exercise a Shift bit, so none is added.
  Terminal.prototype._mouseButtonCode = function (ev, isMotion) {
    var code = (this._mouseButtonDown !== null) ? this._mouseButtonDown : 0;
    if (ev.metaKey) code += 8;
    if (ev.ctrlKey) code += 16;
    if (isMotion) code += 32;
    return code;
  };

  // SGR (`sgr === true`, `?1006`): press/motion end the sequence in 'M'; release is the SAME
  // triplet ending in lowercase 'm', carrying `pb` UNCHANGED -- the real button number, not a
  // fixed placeholder. That final-character/real-button distinction is the entire reason SGR
  // exists over the legacy scheme, which cannot say which button came up (see the `else` branch).
  // Legacy (`sgr === false`): `\x1b[M` + 3 raw bytes (32+Pb, 32+col, 32+row); the 1-byte-per-field
  // encoding cannot represent a coordinate above 223 (32+224 overflows a byte), so both axes are
  // clamped rather than corrupting the frame, and release is ALWAYS reported as button 3 -- X10
  // tracking has no way to say which button was released.
  // `isMotion` (default false = a discrete press/release/wheel report) routes the encoded bytes
  // through `_sendMotion`'s coalescing instead of `_send`'s direct enqueue -- see that function's
  // own comment for why motion alone is safe to coalesce and everything else here is not.
  Terminal.prototype._sendMouseReport = function (pb, cell, isRelease, isMotion) {
    var s;
    if (this.mouse.sgr) {
      s = "\x1b[<" + pb + ";" + cell.col + ";" + cell.row + (isRelease ? "m" : "M");
    } else {
      var legacyCol = Math.min(223, cell.col), legacyRow = Math.min(223, cell.row);
      var legacyPb = isRelease ? 3 : pb;
      s = "\x1b[M" + String.fromCharCode(32 + legacyPb, 32 + legacyCol, 32 + legacyRow);
    }
    if (isMotion) this._sendMotion(s); else this._send(s);
  };

  Terminal.prototype._onMouseDown = function (ev) {
    if (!this._mouseGate(ev)) return;
    ev.preventDefault();
    this._mouseButtonDown = ev.button;   // ctlseqs numbering (left=0, middle=1, right=2) matches
                                          // ev.button's own for the primary three buttons.
    var cell = this._mouseCell(ev);
    this._lastMouseCell = cell;          // seed the drag-throttle baseline at the press point
    this._sendMouseReport(this._mouseButtonCode(ev, false), cell, false);
  };

  Terminal.prototype._onMouseMove = function (ev) {
    if (!this._mouseGate(ev)) return;
    var dragging = this._mouseButtonDown !== null;
    // Which modes want motion at all: 1000 never does (press/release only); 1002 only while a
    // button is held (drag); 1003 always. An unrecognized mode value reports nothing -- safer
    // than guessing which of these three it most resembles.
    if (this.mouse.mode === 1000) return;
    if (this.mouse.mode === 1002 && !dragging) return;
    if (this.mouse.mode !== 1002 && this.mouse.mode !== 1003) return;
    var cell = this._mouseCell(ev);
    // Throttle to one report per CELL change, not per pixel -- otherwise a single drag floods the
    // PTY with hundreds of writes.
    if (this._lastMouseCell && this._lastMouseCell.row === cell.row && this._lastMouseCell.col === cell.col) return;
    this._lastMouseCell = cell;
    ev.preventDefault();
    this._sendMouseReport(this._mouseButtonCode(ev, true), cell, false, true);   // isMotion=true
  };

  Terminal.prototype._onMouseUp = function (ev) {
    if (!this._mouseGate(ev)) return;
    ev.preventDefault();
    var cell = this._mouseCell(ev);
    this._sendMouseReport(this._mouseButtonCode(ev, false), cell, true);
    this._mouseButtonDown = null;
    this._lastMouseCell = null;
  };

  // ===== mouse wheel: scrollback on the primary screen, arrow keys on the alt screen ==========
  // Full-screen programs (vim/less/top/…) own the alt screen and read arrow keys for their own
  // scrolling/navigation -- forwarding wheel-as-history there instead of as arrows is exactly the
  // "every full-screen program feels broken" bug the plan calls out.
  Terminal.prototype._onWheel = function (ev) {
    if (this._mouseGate(ev)) {
      // Wheel buttons (ctlseqs p.49-52): button 4 (up) / 5 (down) = base 0/1 + 64. Replaces
      // scrollback/alt-arrow forwarding entirely while a program owns mouse tracking -- see
      // _mouseGate's own comment for the gating order this shares with every other mouse entry
      // point.
      ev.preventDefault();
      var wcell = this._mouseCell(ev);
      var wcode = (ev.deltaY < 0 ? 0 : 1) + 64;
      if (ev.metaKey) wcode += 8;
      if (ev.ctrlKey) wcode += 16;
      this._sendMouseReport(wcode, wcell, false);
      return;
    }
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

  // Third constructor arg -- see Terminal's own constructor comment just above: now a named
  // parameter here too, for the same reason (the test helper that used to demand a fixed literal
  // now matches by prefix instead).
  function XtermTerminal(container, ttyId, rendererSwitch) {
    rendererSwitch = rendererSwitch || _noopRendererSwitch;
    this.ttyId = ttyId;
    this.es = null;
    this.term = null;
    this.fitAddon = null;
    this._onStatusChange = null;
    this._fontSize = 12.5;   // matches .vtpane's default font-size in ext_vt.css
    // Guards _build() firing after a mid-load destroy(): attach() defers _build() behind
    // _loadXtermAssets()'s promise, and if destroy() runs while that ~480KB asset load is still
    // in flight (e.g. the user switches renderers again before it resolves), destroy() completes
    // as a clean no-op against a still-null this.term/this._disposePaneObserver -- then the
    // deferred _build() would fire anyway and build a real xterm.js Terminal, ResizeObserver and
    // window listener on an already-destroyed instance, none of which anything would ever clean
    // up. Same pattern as ContextBar._destroyed (see that class's constructor/destroy).
    this._destroyed = false;
    var self = this;
    this._resizeDebounced = debounce(function () { self._doResize(); }, 150);

    container.innerHTML = "";
    var toolbarEl = buildToolbar(
      function () { self._zoom(-1); },
      function () { self._zoom(1); },
      function () { self.focus(); },
      {
        // xterm.js owns mouse handling entirely inside its own <canvas> -- this file has no
        // `mouse.mode` equivalent for this renderer (no JSON envelope at all; see this class's own
        // header comment) and forwarding/gating clicks ourselves here would fight xterm.js's own
        // handling instead of helping it ("xterm.js handles its own mouse; do not fight it"). The
        // toggle is therefore permanently inert on this renderer -- still shown (never hidden, per
        // the no-host/no-viewport-gate requirement), always dimmed, a no-op on tap/click.
        getEnabled: function () { return false; },
        setEnabled: function () { },
        isMeaningful: function () { return false; }
      },
      rendererSwitch
    );
    this._disposeThemeBtn = toolbarEl.disposeThemeBtn;   // called from destroy() below
    var pane = document.createElement("div");
    pane.className = "vtpane vtxpane";
    container.appendChild(toolbarEl);
    container.appendChild(pane);
    this.pane = pane;
    this.container = container;
    // Live re-theme: _xtermTheme() is only read ONCE, by _build() below, at construction time --
    // xterm.js takes an explicit JS colour object, not CSS, so an already-open pane has no other
    // way to pick up a theme flip (from this toolbar's own button, the top-bar button, or another
    // pane's button). Bound here (not in _build()) so the listener exists for the ENTIRE lifetime
    // of this instance, including the window between attach() and the deferred _build() actually
    // running -- self._onThemeChange checks `self.term` itself and is a no-op until _build() sets
    // it. Removed in destroy() below; see that method's own comment for why.
    this._onThemeChange = function () { if (self.term) self.term.options.theme = _xtermTheme(); };
    document.addEventListener("themechange", this._onThemeChange);
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
    // Bail out if destroy() already ran while attach()'s asset load was still pending -- see the
    // constructor's own comment on `this._destroyed` for the leak this closes.
    if (this._destroyed) return;
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
    // See observePane's own comment (just above buildToolbar) for the sibling-flex mechanism this
    // covers -- shared with the grid Terminal class instead of each renderer wiring/tearing down
    // its own ResizeObserver.
    this._disposePaneObserver = observePane(this.pane, self._resizeDebounced);
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
    // Set FIRST, unconditionally: covers both paths -- _build() already ran (this cleans up what
    // it created, below) and _build() is still pending behind attach()'s asset-load promise (this
    // makes that deferred call a no-op instead of building a leak onto a destroyed instance).
    this._destroyed = true;
    // Both are document-level listeners (see the constructor's own comments) -- neither is cleaned
    // up by container.innerHTML = "" or any other DOM teardown, so both must be removed explicitly
    // here or every terminal open leaks one more "themechange" handler for the life of the tab.
    if (this._disposeThemeBtn) { this._disposeThemeBtn(); this._disposeThemeBtn = null; }
    if (this._onThemeChange) { document.removeEventListener("themechange", this._onThemeChange); this._onThemeChange = null; }
    if (this.es) { this.es.close(); this.es = null; }
    if (this._disposePaneObserver) { this._disposePaneObserver(); this._disposePaneObserver = null; }
    window.removeEventListener("resize", this._resizeDebounced);
    if (this.term) { this.term.dispose(); this.term = null; }
  };

  // ===== the modal (reuses app.css's .overlay/.modal/.mh/.mb/.x — no second modal system) =====
  var overlay = null, modalTitleEl = null, modalStatusEl = null, modalBodyEl = null;
  var activeTerm = null, activeTty = null, activeSid = null, activeMode = null, activeBar = null;
  var activeRenderer = null;   // "grid" | "xterm" -- server-owned (see openVT below), never guessed
  var activeTermWrap = null;   // dedicated wrap div holding ONLY the current terminal's own
                                // toolbar+pane -- see switchActiveRenderer's own comment for why
                                // this can't just be modalBodyEl itself.
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
    modalTitleEl.textContent = "TERMINAL";
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

  // Wires a modal terminal's status callback -- shared by openVT's initial build AND
  // switchActiveRenderer's rebuild below, so the two never drift into two slightly different
  // copies of the same "starting…" suppression logic.
  function _wireModalStatus(term) {
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
  }

  // ===== renderer switch (modal): destroys the CURRENT Terminal/XtermTerminal and rebuilds the
  // OTHER one against the SAME tty -- both renderers read/write through the server's shared PTYS
  // table (term_vt.py), so the pty itself is untouched; only which client renders it changes. Set
  // as the `switchTo` half of the interface handed to buildToolbar's switch button (see that
  // function's own comment). `activeRenderer`'s INITIAL value (a few lines up in openVT, from
  // `res.j.renderer`) is never touched here -- this only ever runs LATER, from an explicit click.
  function switchActiveRenderer(renderer) {
    if (!activeTerm || !activeTermWrap || renderer === activeRenderer) return;
    // destroy() closes the old terminal's SSE stream and clears its own timers/document-level
    // listeners (Terminal.prototype.destroy / XtermTerminal.prototype.destroy) -- see this file's
    // header brief, requirement 3, for why that matters here specifically: leaving it running
    // would leak a second live stream against the same tty.
    activeTerm.destroy();
    activeRenderer = renderer;
    var Cls = renderer === "xterm" ? XtermTerminal : Terminal;
    var term = new Cls(activeTermWrap, activeTty, {
      getActive: function () { return activeRenderer; },
      switchTo: switchActiveRenderer
    });
    _wireModalStatus(term);
    activeTerm = term;
    // Re-wire, don't destroy: the ContextBar's polling/dropdown state has nothing to do with which
    // renderer is on screen -- only its getInput() callback (used by _focusTerminal) needs to stop
    // pointing at the terminal that was just destroyed above. See this file's header brief,
    // requirement 4 ("re-wire ... rather than leaving it pointing at a destroyed one").
    if (activeBar) activeBar.getInput = function () { return term; };
    term.attach();
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

    modalTitleEl.textContent = "TERMINAL — " + (mode === "resume" ? "resume · " : "") + sid;
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
          // "grid", same as config.TERM_RENDERER's own server-side fallback. This is the ONE place
          // the INITIAL choice is made -- switchActiveRenderer (above) is a later, explicit user
          // override layered on top, never a second vote on this line.
          activeRenderer = (res.j.renderer === "xterm") ? "xterm" : "grid";
          modalStatusEl.textContent = "tty " + activeTty;
          // The terminal's own toolbar+pane live in a DEDICATED wrap, never directly in
          // modalBodyEl: Terminal/XtermTerminal's constructor does `container.innerHTML = ""` on
          // whatever it's given, and a later renderer switch (switchActiveRenderer) rebuilds THIS
          // wrap alone -- handing it modalBodyEl directly would also wipe the ContextBar's own
          // .el and the fork-chip/notice chrome that live alongside it as modalBodyEl's siblings.
          var wrap = document.createElement("div");
          wrap.className = "vttermwrap";
          modalBodyEl.appendChild(wrap);
          activeTermWrap = wrap;
          var Cls = activeRenderer === "xterm" ? XtermTerminal : Terminal;
          var term = new Cls(wrap, activeTty, {
            getActive: function () { return activeRenderer; },
            switchTo: switchActiveRenderer
          });
          // `starting` (true only for mode="resume" panes still recovering from a refused
          // `claude --resume`) is server-owned and read straight off this POST response, seeded
          // BEFORE term.attach() ever opens the EventSource below -- see Terminal's own `starting`
          // field comment. Only meaningful for the grid renderer: xterm's /api/term/raw stream
          // carries no JSON envelope at all, so it has no `starting` key to read (deliberately out
          // of scope -- see XtermTerminal.prototype._openStream's comment). Never set on a
          // renderer switch (switchActiveRenderer never touches it): the pty being rebuilt against
          // is already running, not freshly resuming.
          if (activeRenderer === "grid") {
            term.starting = !!res.j.starting;
            term.pane.classList.toggle("vtstarting", term.starting);
            if (term.starting) modalStatusEl.textContent = "tty " + activeTty + " · starting…";
          }
          _wireModalStatus(term);
          activeTerm = term;
          // Built AFTER the Terminal/XtermTerminal (both do container.innerHTML = "" in their own
          // constructor, now confined to `wrap` above) so the bar's own DOM survives — appended as
          // a sibling of `wrap` inside the same flex-column .vtmb, so it docks to the bottom
          // without any CSS shuffling, and stays untouched by a later renderer switch too.
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
    activeTermWrap = null;
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
    document.title = "TERMINAL — AI Tracker";
    var mount = document.getElementById("ext_vt");
    if (!mount) return;
    // The mount lives inside .app, which .vt-standalone hides with display:none -- and a
    // display:none ancestor removes the whole subtree from rendering no matter that we are
    // position:fixed. Reparent to <body> so the fullscreen layout actually has a box; without
    // this the standalone tab renders a correct DOM at 0x0 and the user sees a black screen.
    document.body.appendChild(mount);
    mount.classList.add("vtfull");

    // curTerm/curBar/curRenderer/termWrap/statusEl are mutable across a renderer switch (see
    // mountRenderer below) -- plain `var term`/`bar` locals inside a one-shot boot() can't be
    // reassigned by a switch button that outlives that single call.
    var curTerm = null, curBar = null, curRenderer = null, termWrap = null, statusEl = null;

    // Re-renders the standalone status line from scratch -- shared by boot()'s own initial
    // "connecting…" placeholder and by every term._onStatusChange callback wired in
    // mountRenderer, so the fork-chip-splicing logic isn't maintained as two near-identical copies
    // (the original shape of this code, before the renderer switch, was exactly that).
    function renderStandaloneStatus(s) {
      statusEl.innerHTML = "";   // clear before adding spans to avoid HTML injection
      var statusText = "tty " + tty;
      if (standaloneForked) statusText += " · ⑂ fork";
      statusText += " · " + s;
      var parts = statusText.split(" · ");
      for (var i = 0; i < parts.length; i++) {
        if (i > 0) statusEl.appendChild(document.createTextNode(" · "));
        if (i === 1 && standaloneForked) {
          var chip = document.createElement("span");
          chip.className = "vtstatus-fork";
          chip.setAttribute("title", "This terminal is a copy of a background agent — the original is still running separately");
          chip.textContent = "⑂ fork";
          statusEl.appendChild(chip);
        } else {
          statusEl.appendChild(document.createTextNode(parts[i]));
        }
      }
    }

    // Destroys the CURRENT terminal (if any) and builds `renderer` against the SAME tty, inside
    // the dedicated `termWrap` (never `mount` directly -- see boot()'s own comment below for why).
    // This is both what boot() calls for the very first mount AND the `switchTo` half of the
    // interface handed to buildToolbar's switch button, so the initial build and every later
    // switch share one code path instead of two that could drift apart.
    function mountRenderer(renderer) {
      if (curTerm) { curTerm.destroy(); curTerm = null; }   // see this file's header brief,
                                                              // requirement 3: closes the old SSE
                                                              // stream and clears its own timers/
                                                              // document-level listeners.
      curRenderer = renderer;
      var Cls = renderer === "xterm" ? XtermTerminal : Terminal;
      var term = new Cls(termWrap, tty, {
        getActive: function () { return curRenderer; },
        switchTo: mountRenderer
      });
      curTerm = term;
      if (curBar) {
        // Re-wire, don't destroy -- same reasoning as openVT's own switchActiveRenderer (requirement
        // 4): the ContextBar's polling/dropdown state has nothing to do with which renderer is on
        // screen, only its getInput() callback needs to stop pointing at the destroyed terminal.
        curBar.getInput = function () { return term; };
      } else if (sid) {
        // First mount only (mountRenderer's earlier calls, if any, already built curBar above).
        // Appended AFTER the Terminal/XtermTerminal (whose constructor does
        // container.innerHTML = "", now confined to termWrap) so the bar's own DOM survives a
        // later switch -- see termWrap's own comment in boot().
        curBar = new ContextBar(mount, sid, tty, mode, function () { return term; });
        curBar.start();
      }
      term._onStatusChange = function (s) {
        if (curTerm !== term) return;
        renderStandaloneStatus(s);
      };
      term.attach();
    }

    function boot(renderer) {
      // The term's own toolbar+pane live in a DEDICATED wrap, never directly in `mount`: both
      // Terminal and XtermTerminal's constructors do `container.innerHTML = ""` on whatever
      // they're given, and a later renderer switch (mountRenderer, above) rebuilds THIS wrap
      // alone -- handing it `mount` directly would also wipe the notice banner and the status
      // line below, both of which are `mount`'s other children.
      termWrap = document.createElement("div");
      termWrap.className = "vttermwrap";
      mount.appendChild(termWrap);

      // Created (and pre-rendered) BEFORE mountRenderer() runs, but not yet appended to `mount`:
      // XtermTerminal.prototype.attach calls _onStatusChange SYNCHRONOUSLY the instant attach() is
      // called (before any async asset loading) -- so `statusEl` must already exist and be
      // wireable the moment mountRenderer() below calls term.attach(). Mutating a still-detached
      // node is harmless; it's appended for real once the notice banner (if any) has taken its
      // spot ahead of it, so the final DOM order stays pane -> context bar -> notice -> status,
      // matching the order this code built in before the renderer switch existed.
      statusEl = document.createElement("div");
      statusEl.className = "vtfullstatus";
      renderStandaloneStatus("connecting…");

      mountRenderer(renderer);   // builds the terminal into termWrap, and the context bar right after it

      // Build notice element if present (same as modal, but in standalone context)
      if (standaloneNotice) {
        var noticeEl = document.createElement("div");
        noticeEl.className = "vtnotice";
        var noticeText = document.createElement("span");
        noticeText.textContent = standaloneNotice;  // textContent escapes HTML
        noticeEl.appendChild(noticeText);
        mount.appendChild(noticeEl);
      }

      mount.appendChild(statusEl);
      window.addEventListener("resize", debounce(function () { if (curTerm) curTerm.measureAndResize(); }, 150));
    }

    if (rendererParam === "grid" || rendererParam === "xterm") {
      boot(rendererParam);
    } else {
      fetch("/api/term/renderer").then(function (r) { return r.json(); })
        .then(function (j) { boot((j && j.renderer === "xterm") ? "xterm" : "grid"); })
        // Deliberately "grid", not xterm (the server's own DEFAULT) -- this only fires when
        // GET /api/term/renderer itself is unreachable, which is a different situation from
        // "unset", exactly like config.TERM_RENDERER's own garbage-value fallback (see its comment
        // in config.py, "An unrecognised value is a DIFFERENT question from 'unset'"): grid is the
        // safer renderer here (repaint on reconnect, server-backed scrollback, mid-session
        // notices), so a client that can't even ask the server what to use should land on the safe
        // choice rather than the now-riskier default. Keep this in sync with that reasoning --
        // don't "fix" it to match the unset default without re-reading it.
        .catch(function () { boot("grid"); });
    }
  })();
})();
