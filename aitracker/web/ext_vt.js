// Tier 3 — in-browser terminal: grid painter, key capture, the modal, and the standalone-tab
// mode. Registers into EXT and mounts into #ext_vt, exactly like ext_launch.js/ext_run.js;
// concatenated into the same top-level <script> as app.js, so `cur`, `EXT`, `esc` and `toast`
// below are the real globals from app.js, not a guess at their shape (see ext_launch.js's own
// header comment for the same note).
//
// Exposes window.ExtVT = {open(sid, mode), manage()} so ext_launch.js's buttons — the detail
// pane's "…here" pair and the sidebar's "Manage terminals" — can drive this module without
// either file reaching into the other's internals.
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

  // ===== shared notice banner, owned by the MOUNT POINT (not by either renderer) ==============
  // ONE implementation of "raise a .vtnotice banner above the terminal", replacing what used to be
  // THREE near-copies of the same build-a-div-with-a-textContent-span logic: Terminal.prototype.
  // _displayNotice (grid only), openVT's open-time `res.j.notice` block, and bootStandalone's
  // `?notice=` block. Living at the mount means BOTH renderers inherit it (conventions rule 4):
  // the grid Terminal forwards its JSON frame's `notices` array and XtermTerminal forwards
  // /api/term/raw's named `event: notice` frames, through the SAME `term._onNotice` callback --
  // mirroring the `term._onStatusChange` precedent both renderers already fire and both mounts
  // already render.
  //
  // `container` is the mount's own flex COLUMN (.mb.vtmb in the modal, #ext_vt.vtfull in the
  // standalone tab) -- one level further out than the old _displayNotice, which inserted before
  // .vtpane inside .vttermwrap. No CSS change is needed for that move: .vtnotice is already
  // `flex: 0 0 auto` (ext_vt.css) and both containers are already flex columns.
  //
  // Consequences of the mount owning this, both deliberate:
  //   - The `seq` dedupe lives HERE, once, instead of once per renderer. A transport reconnect
  //     (EventSource auto-retry) makes the server replay from seq 0 on both routes; `highestSeq`
  //     is what stops an already-displayed banner being raised a second time.
  //   - A RENDERER SWITCH no longer re-flashes the banners. destroy() used to drop both the
  //     elements and the seq tracker, so the rebuilt renderer's first frame re-showed everything;
  //     now the banners simply stay on screen, untouched, exactly like the ContextBar the two
  //     switch paths deliberately re-wire rather than destroy.
  //
  // Insertion point: after the LAST banner already shown, else before `container.firstChild` --
  // so banners stay in arrival order AND always sit above the .vttermwrap/.vtctxbar/.vtfullstatus
  // siblings, whether they were raised before those existed (open time) or long after (streamed).
  // `insertBefore(el, null)` is a plain append, which is the empty-container case.
  //
  // show() returns TRUE when the DOM actually changed, so the caller can hand the terminal one
  // measureAndResize(). observePane()'s ResizeObserver already covers this (a banner shrinks the
  // pane exactly like .vtctxbar appearing does), but it returns a no-op when window.ResizeObserver
  // is absent -- so the explicit call is the belt to that braces.
  var NOTICE_MAX = 3;   // cap on stacked banners, oldest evicted -- see _displayNotice's history
  function createNoticeBanner(container) {
    var els = [], highestSeq = -1;
    return {
      show: function (notice) {
        var text = (notice && typeof notice.text === "string") ? notice.text : "";
        if (!text) return false;
        // A notice with no `seq` (the open-time advisory relayed on POST /api/term/pty's response
        // or in the ?notice= link) is never deduped -- it has no position in the stream at all.
        var seq = (notice && typeof notice.seq === "number") ? (notice.seq | 0) : null;
        if (seq !== null) {
          if (seq <= highestSeq) return false;
          highestSeq = seq;
        }
        var el = document.createElement("div");
        el.className = "vtnotice";
        var span = document.createElement("span");
        span.textContent = text;   // textContent escapes HTML -- notice text is server-supplied
        el.appendChild(span);
        var last = els.length ? els[els.length - 1] : null;
        container.insertBefore(el, last ? last.nextSibling : container.firstChild);
        els.push(el);
        while (els.length > NOTICE_MAX) {
          var oldest = els.shift();
          if (oldest && oldest.parentNode) oldest.parentNode.removeChild(oldest);
        }
        return true;
      },
      // Resets the seq tracker too: clear() marks a NEW pty (openVT/closeVT), whose seqs restart
      // at 1 -- never a renderer switch, which deliberately leaves both the banners and the
      // tracker alone (see this helper's header).
      clear: function () {
        for (var i = 0; i < els.length; i++) {
          if (els[i] && els[i].parentNode) els[i].parentNode.removeChild(els[i]);
        }
        els = []; highestSeq = -1;
      }
    };
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
    // Fired once per {seq, text} notice read off this renderer's SSE frames; the MOUNT renders it
    // (see createNoticeBanner above -- the dedupe, the 3-banner cap and the DOM all live there,
    // shared with XtermTerminal, which fires the same callback off /api/term/raw's named `notice`
    // event). Same shape/precedent as _onStatusChange just above.
    this._onNotice = null;
    // Guards attach()'s deferred frame firing after a destroy(): attach() does its first measure
    // and opens the EventSource inside a requestAnimationFrame, so a closeVT()/renderer switch
    // landing in that gap used to run the callback ANYWAY -- opening a stream on an already-
    // destroyed terminal that nothing would ever close (destroy() had already seen a null
    // this.es), pinning the server's `pt.viewers > 0` so the pty could never be idle-reaped.
    // Same pattern (and same reason) as XtermTerminal._destroyed -- see that constructor.
    this._destroyed = false;
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
      // Bail out if destroy() already ran between attach() and this frame -- see the
      // constructor's own comment on `this._destroyed` for the leaked EventSource this closes.
      if (self._destroyed) return;
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
    // Async notices: forwarded UP to the mount, which raises the banner (createNoticeBanner
    // above). This renderer only reads them off its JSON frame -- the dedupe-by-seq, the 3-banner
    // cap and the DOM are the mount's, shared with XtermTerminal, which forwards the identical
    // {seq, text} objects off /api/term/raw's named `notice` event. `Array.isArray` stays the
    // defensive read it always was: an older server sends nothing and the key is simply absent.
    var notices = msg.notices;
    if (Array.isArray(notices) && this._onNotice) {
      for (var k = 0; k < notices.length; k++) this._onNotice(notices[k]);
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

  // The grid renderer's private `_displayNotice` used to live here -- it is now `createNoticeBanner`
  // (above, module level), owned by the MOUNT so XtermTerminal inherits it too. See that helper's
  // header for the seq dedupe, the 3-banner cap and the renderer-switch consequence.

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
    // Set FIRST, unconditionally: attach()'s deferred rAF may still be queued at this point, and
    // this is what makes it a no-op instead of opening an SSE stream on a destroyed terminal --
    // see the constructor's own comment on `this._destroyed`. Mirrors XtermTerminal.destroy().
    this._destroyed = true;
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
    // Notice banners are deliberately NOT torn down here any more: they belong to the MOUNT
    // (createNoticeBanner above), which clears them when the pty itself goes away (closeVT /
    // openVT) -- NOT when one renderer is swapped for the other against the same live pty. See
    // that helper's header for why surviving the switch is the right behaviour.
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
  // ONE shared implementation for BOTH renderers (conventions rule 4): the capability is "flash
  // the pane when the terminal rings", and the visual half of that -- toggle `.vtbell`, let the
  // existing @keyframes vtbellflash rule (ext_vt.css) do the pulse -- is identical regardless of
  // which renderer is asking. Only the TRIGGER differs, and it has to: the grid Terminal below
  // derives it from the SSE snapshot's server-owned `msg.bell` counter (`_applyPatch`, further
  // down), because its screen is parsed server-side and has no BEL byte of its own to observe;
  // XtermTerminal derives it from xterm.js's own `onBell` event (see that class's `_build`),
  // because it never sees a parsed snapshot at all, only the raw byte stream xterm.js consumes
  // itself. Neither renderer could use the other's trigger, so this is one function fed by two
  // sources, not two competing implementations of the flash itself. `.vtbell` (ext_vt.css) is
  // scoped to the bare `.vtpane` class, which both renderers' panes carry (grid: "vtpane";
  // XtermTerminal: "vtpane vtxpane") -- so no CSS change was needed to reach the xterm pane too.
  //
  // Burst safety: re-adding a class the element already has is a DOM no-op and does not restart
  // a running CSS animation, so a program spamming BEL never stacks overlapping `vtbellflash`
  // animations -- there is only ever the one `.vtbell` class, present or absent. Each call's own
  // setTimeout independently tries to remove it 180ms after THAT call; removing an already-absent
  // class is equally a no-op, so whichever timeout fires last is simply the one that clears it.
  function _flashBellPane(pane) {
    if (!pane) return;
    pane.classList.add("vtbell");
    setTimeout(function () { pane.classList.remove("vtbell"); }, 180);
  }

  Terminal.prototype._flashBell = function () {
    _flashBellPane(this.pane);
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
  //   - (CLOSED -- no longer a gap, kept as a pointer.) MID-SESSION SERVER NOTICES now raise the
  //     same styled `.vtnotice` banner the grid renderer does, including full REPLAY for a tab
  //     that attaches after the note fired. `/api/term/raw` still has no JSON envelope, so the
  //     channel is a NAMED `event: notice` frame on that same connection (term_vt.py's
  //     `_raw_stream_body`, per-viewer `since_notice` cursor), consumed by `_openStream`'s
  //     `addEventListener("notice", …)` below and forwarded up through `_onNotice` to the mount's
  //     `createNoticeBanner` -- one banner implementation for both renderers, not two. The
  //     `_feed_note()` inline "[ai-tracker] note: …" tee still happens as well; that is the
  //     terminal's own scrollback record, unrelated to the banner.
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
    this._onNotice = null;        // see Terminal's own _onNotice comment -- the SAME callback both
                                   // renderers fire and both mounts render (createNoticeBanner).
    this._onNoticeEvent = null;   // the addEventListener("notice", ...) handler on `this.es`,
                                   // kept only so _closeStream below can remove it by reference.
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
    // Wired BEFORE the first fit() below (moved up from its old spot next to onData further down)
    // so that fit()'s OWN initial resize -- and any _correctFitOverflow() correction it triggers --
    // POSTs the corrected size to the server immediately, not just from the next resize onward.
    term.onResize(function (sz) { postResize(self.ttyId, sz.cols, sz.rows); });
    try { fit.fit(); } catch (e) { }
    this._correctFitOverflow();

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
    // onResize is wired earlier, above -- before the initial fit.fit() call -- see that call
    // site's own comment for why.

    // Bell: confirmed against this vendored build that `onBell` is a plain, ungated getter on the
    // PUBLIC Terminal class (`get onBell(){return this._core.onBell}` -- unlike the handful of
    // genuinely-proposed getters elsewhere in the same class, it never calls `_checkProposedApi()`
    // first, so no `allowProposedApi` option is needed here), and that it actually fires off a
    // real BEL byte (`this._register(this._inputHandler.onRequestBell((()=>this._onBell.fire())))`
    // in the core terminal). `.onBell()` returns a Disposable (same VS Code-style Emitter every
    // other `term.onX` in this class already relies on) -- stored and disposed in destroy() below,
    // alongside this class's other listeners, per its teardown discipline. `_flashBellPane` is the
    // SAME function the grid renderer's `_flashBell` calls -- see its own comment for why one
    // shared implementation is correct here despite the two renderers' different triggers.
    this._disposeBell = term.onBell(function () { _flashBellPane(self.pane); });

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
    this._correctFitOverflow();   // fit()'s proposed row count can still render taller than it
                                   // estimated -- see that method's own comment -- so every resize
                                   // path (window resize, zoom, sibling flex change via
                                   // observePane), not just first mount, needs this same check.
  };

  // FitAddon.fit() (called just above, and in _build's initial call) proposes a row count from ITS
  // OWN fractional cell-height estimate (see vendor/addon-fit.js's proposeDimensions(): it reads
  // term._core._renderService.dimensions.css.cell.height, which is `canvas.height / CURRENT rows`
  // -- a value that shifts every time rows change, not a fixed per-row size). But every row the
  // renderer actually paints lands on a WHOLE device pixel (dimensions.device.cell.height is
  // floor()'d in xterm.js's own _updateDimensions -- confirmed against vendor/xterm.js), so the row
  // count fit() proposes can render taller than fit()'s own fractional estimate implied, and
  // `.vtpane { overflow: hidden }` (ext_vt.css) silently clips the surplus off the bottom row.
  // Verified live: at 1280x1600 the mismatch reached +1.4px -- enough to clip the last row's text.
  // The error is per-row and accumulates linearly with row count, so it's invisible in a short
  // terminal and only bites once the pane is tall (e.g. many background agents pushing the TUI's
  // footer down into the marginal last row that was always being clipped).
  //
  // Fix: re-measure the ACTUAL rendered geometry from the DOM right after fit() runs, and correct
  // down by a row if it overflows. This vendored build of xterm.js ships ONLY the DomRenderer (no
  // canvas/WebGL path -- confirmed against vendor/xterm.js: `t.DomRenderer=` is the sole renderer
  // class exported; neither `CanvasRenderer` nor `WebglAddon` appears anywhere in the bundle), so
  // `.xterm-screen` -- the element the renderer sizes to exactly rows*cellHeight on every resize,
  // synchronously (DomRenderer.prototype.handleResize -> _updateDimensions sets its style.height
  // directly, off term.resize()'s own synchronous event chain -- no rAF wait needed before reading
  // it back) -- is a real, always-present DOM node. Measuring it is the same discipline
  // computeColsRows() already uses for the grid renderer (actual rendered pixels, not an internal
  // estimate); it's also a public DOM class, not a private `_core` reach-in, so it survives an
  // xterm.js upgrade that only touches internals.
  XtermTerminal.prototype._correctFitOverflow = function () {
    var term = this.term, pane = this.pane;
    if (!term || !pane) return;
    // Bounded to 2 iterations, never an unbounded loop. Each iteration shrinks `.xterm-screen`
    // itself (one fewer row => smaller rows*cellHeight); it does NOT touch `.vtpane`'s own box,
    // whose size is driven by its flex ancestors (see observePane's comment above, just before
    // buildToolbar) -- so the term.resize() below cannot change what the ResizeObserver watching
    // the pane sees, cannot re-trigger _doResize through that path, and so cannot oscillate. Two
    // iterations is cushion for a rare multi-pixel accumulated error; one is the expected case.
    for (var i = 0; i < 2; i++) {
      if (term.rows <= 1) return;   // never resize below 1 row
      var screenEl = pane.querySelector(".xterm-screen");
      if (!screenEl) return;   // future xterm.js build changed its DOM shape -- fail safe, no-op
      var cs = getComputedStyle(pane);
      var paneContentBottom = pane.getBoundingClientRect().bottom - (parseFloat(cs.paddingBottom) || 0);
      var screenBottom = screenEl.getBoundingClientRect().bottom;
      if (screenBottom <= paneContentBottom + 0.5) return;   // fits (0.5px slack for subpixel noise)
      term.resize(term.cols, term.rows - 1);   // onResize (wired in _build, BEFORE the first
                                                // fit()) POSTs the corrected size to the server --
                                                // the same sync path any other resize takes.
    }
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
    self._closeStream();
    if (self._onStatusChange) self._onStatusChange("connecting…");
    self.es = new EventSource("/api/term/raw?tty=" + encodeURIComponent(self.ttyId));
    self.es.onopen = function () { if (self._onStatusChange) self._onStatusChange("connected"); };
    self.es.onmessage = function (ev) {
      if (!self.term) return;
      try { self.term.write(_b64ToBytes(ev.data)); } catch (e) { }
    };
    // The notice channel this renderer used to lack entirely (it was a documented parked gap in
    // this class's header until now). `/api/term/raw` emits `event: notice\ndata: {"seq":<int>,
    // "text":"<str>"}` on THIS SAME connection -- verified on the wire against
    // term_vt._raw_stream_body -- so there is no second EventSource to double-count pt.viewers
    // with. It MUST be a named-event listener: `onmessage` above runs every UNNAMED frame through
    // _b64ToBytes and writes the result into xterm.js as terminal bytes, and a named event is
    // inert to it. Forwarded straight up to the mount, unparsed of meaning: the seq dedupe (which
    // is what makes EventSource's own auto-retry -- the server replays from seq 0 -- not re-raise
    // a banner already on screen) belongs to createNoticeBanner, once, for both renderers.
    self._onNoticeEvent = function (ev) {
      if (!self._onNotice) return;
      var n = null;
      try { n = JSON.parse(ev.data); } catch (e) { return; }   // malformed frame: ignore, never throw
      self._onNotice(n);
    };
    self.es.addEventListener("notice", self._onNoticeEvent);
    self.es.onerror = function () { if (self._onStatusChange) self._onStatusChange("reconnecting…"); };
  };

  // Closes `this.es` AND removes the named-event listener wired onto it above. One helper because
  // both callers need both halves: _openStream (which replaces the stream) and destroy(). Removing
  // the listener by reference is belt-and-braces over close() -- a closed EventSource dispatches
  // nothing -- but it is the same teardown discipline every other listener in this class follows,
  // and it is what keeps `_onNoticeEvent` from pinning this instance through a stale handler.
  XtermTerminal.prototype._closeStream = function () {
    if (!this.es) { this._onNoticeEvent = null; return; }
    if (this._onNoticeEvent) this.es.removeEventListener("notice", this._onNoticeEvent);
    this._onNoticeEvent = null;
    this.es.close();
    this.es = null;
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
    // The onBell subscription (see _build's own comment) -- disposed explicitly here rather than
    // left to term.dispose() below, matching every other listener this method tears down by hand.
    if (this._disposeBell) { this._disposeBell.dispose(); this._disposeBell = null; }
    this._closeStream();   // closes the SSE stream AND removes its "notice" listener -- see above
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
  var modalForkChip = null;      // fork chip in the modal header
  var modalNotices = null;       // this mount's createNoticeBanner (see that helper) -- renders
                                  // BOTH the open-time advisory and every streamed {seq, text}
                                  // notice, from whichever renderer is currently attached.

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
    // Both attributes, same text -- see the standalone chip's own comment (renderStandaloneStatus).
    modalForkChip.setAttribute("aria-label", "This terminal is a copy of a background agent — the original is still running separately");
    modalForkChip.setAttribute("title", "This terminal is a copy of a background agent — the original is still running separately");
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
    // The mount owns the notice banners, not the renderer -- built here, once, against the modal's
    // own flex COLUMN, so it survives every renderer switch inside it (see createNoticeBanner).
    modalNotices = createNoticeBanner(modalBodyEl);

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

  // The effort ladder is likewise HARDCODED, low -> high, mirroring MODEL_LADDER's own reasoning
  // above -- this is the CLI's OWN slash-command ladder for `/effort`, not anything discoverable
  // from a session log or any API. CONFIRMED (high confidence) against the installed Claude Code
  // CLI 2.1.247: its own `/effort` usage string is generated from exactly this five-entry array,
  // `claude --help` documents `--effort <level>` with the same five, and the official docs list
  // the same five with "high" as the default. Deliberately excludes "ultracode" and "auto", which
  // `/effort` also accepts but are NOT effort levels -- "ultracode" is an alias for xhigh plus an
  // orchestration flag, "auto" is a thinking mode, and the docs explicitly say not to pass it as
  // an effort value. If the CLI ever renames/adds a tier, this literal array is the one place to
  // update.
  var EFFORT_LADDER = ["low", "medium", "high", "xhigh", "max"];

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
    // Whether a Claude CLI is actually listening for "/model ..."/"/effort ..." on THIS pty RIGHT
    // NOW — the server's own answer (GET /api/term/attached, term_vt.py's _foreground_is_claude),
    // NEVER `mode`. `mode` ("resume"/"new"/"cwd" — how this terminal was OPENED) used to gate this
    // directly, and that was wrong in both directions: a `cwd`-mode plain shell where the user
    // later typed `claude` themselves has one listening, with no way to tell from `mode` alone —
    // this was the reported regression ("the model picker has been removed entirely") — and a
    // `resume`/`new` pane whose `claude` has since exited to a bash prompt would keep showing the
    // switcher, ready to type a slash command into bash instead. Starts false/unknown until the
    // first poll answers (see start()/_setAttached() below) — conventions rule 5: the server owns
    // this policy, this file only renders it.
    this.attached = false;
    this.modelDropdownOpen = false;
    this.effortDropdownOpen = false;
    this.currentModel = null;
    this.currentEffort = null;
    this._hasUsage = false;   // does the usage readout currently have anything to show — see
                               // _syncBarVisibility() below, which this and `attached` jointly
                               // gate the WHOLE bar's visibility on.
    this._pollStop = null;
    this._destroyed = false;

    var self = this;
    var bar = document.createElement("div");
    bar.className = "vtctxbar";
    this.el = bar;

    // Both switchers are always BUILT now (unlike the old mode-gated version) — `attached` is
    // dynamic, so a picker that doesn't exist yet could never later appear when the answer flips
    // true mid-session. Grouped under one wrapper (.vtswitchers) so both toggle together as one
    // unit as `attached` changes — see _setAttached() below.
    var switchers = document.createElement("span");
    switchers.className = "vtswitchers";
    switchers.style.display = "none";
    bar.appendChild(switchers);
    this.switchersEl = switchers;

    // ---- model switcher. Each picker's wrap is its OWN position:relative anchor — see
    // ext_vt.css's .vtswitcher comment for why that's neither .vtctxbar (a single shared anchor
    // there would stack both dropdowns at one hardcoded offset again) nor the <button> itself
    // (nesting the dropdown's clickable items inside a native <button> puts interactive content
    // inside interactive content). ----
    var modelWrap = document.createElement("span");
    modelWrap.className = "vtswitcher";
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
    modelWrap.appendChild(btn);
    modelWrap.appendChild(dd);
    switchers.appendChild(modelWrap);
    this.modelBtn = btn; this.modelDd = dd;

    // preventDefault on mousedown, not just handling click: a <button> takes native DOM focus
    // on mousedown in most browsers, and this bar must never steal keyboard focus from the
    // terminal's own capture textarea — not even for the instant between mousedown and click.
    btn.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (self.modelDropdownOpen) self._closeModelDropdown(); else self._openModelDropdown();
      self._focusTerminal();
    });
    dd.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
    dd.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var name = ev.target && ev.target.getAttribute && ev.target.getAttribute("data-model");
      if (!name) return;
      self._pickModel(name);
    });

    // ---- effort switcher: mirrors the model switcher exactly, same idioms, same focus-safety
    // pattern (see EFFORT_LADDER's own comment above for the ladder's provenance). ----
    var effortWrap = document.createElement("span");
    effortWrap.className = "vtswitcher";
    var ebtn = document.createElement("button");
    ebtn.type = "button";
    ebtn.className = "vteffortbtn";
    ebtn.textContent = "effort ▾";
    ebtn.title = "Switch reasoning effort — types /effort <level> into the CLI";
    var edd = document.createElement("div");
    edd.className = "vteffortdd";
    EFFORT_LADDER.forEach(function (level) {
      var item = document.createElement("div");
      item.className = "vteffortitem";
      item.textContent = level;
      item.setAttribute("data-effort", level);
      edd.appendChild(item);
    });
    effortWrap.appendChild(ebtn);
    effortWrap.appendChild(edd);
    switchers.appendChild(effortWrap);
    this.effortBtn = ebtn; this.effortDd = edd;

    // Same preventDefault-on-mousedown pattern as the model button above — a picker that steals
    // focus breaks typing into the terminal.
    ebtn.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
    ebtn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (self.effortDropdownOpen) self._closeEffortDropdown(); else self._openEffortDropdown();
      self._focusTerminal();
    });
    edd.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
    edd.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var level = ev.target && ev.target.getAttribute && ev.target.getAttribute("data-effort");
      if (!level) return;
      self._pickEffort(level);
    });

    // One document-level click listener closes whichever dropdown is open when the click lands
    // outside the bar — registered unconditionally now that both switchers always exist (only
    // their CONTAINER's visibility is conditional, via _setAttached()).
    this._onDocClick = function (ev) {
      if (bar.contains(ev.target)) return;
      self._closeModelDropdown();
      self._closeEffortDropdown();
    };
    document.addEventListener("click", this._onDocClick);

    var readout = document.createElement("div");
    readout.className = "vtctxreadout";
    bar.appendChild(readout);
    this.readoutEl = readout;

    // Nothing to show yet (attached unknown, no data fetched) — stay invisible rather than
    // showing an empty docked strip; _setAttached()/_renderReadout() reveal it once there's real
    // content (see _syncBarVisibility()).
    bar.style.display = "none";

    container.appendChild(bar);
  }

  ContextBar.prototype._focusTerminal = function () {
    var input = this.getInput && this.getInput();
    if (input) { try { input.focus(); } catch (e) { } }
  };

  ContextBar.prototype._openModelDropdown = function () {
    this._closeEffortDropdown();   // never two dropdowns open at once
    this.modelDropdownOpen = true;
    this.modelDd.classList.add("show");
    var items = this.modelDd.children;
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("cur", items[i].getAttribute("data-model") === this.currentModel);
    }
  };
  ContextBar.prototype._closeModelDropdown = function () {
    this.modelDropdownOpen = false;
    if (this.modelDd) this.modelDd.classList.remove("show");
  };

  ContextBar.prototype._openEffortDropdown = function () {
    this._closeModelDropdown();   // never two dropdowns open at once
    this.effortDropdownOpen = true;
    this.effortDd.classList.add("show");
    var items = this.effortDd.children;
    // Marking `.cur` only ever finds a match when currentEffort is a real EFFORT_LADDER entry —
    // an out-of-ladder value (see _applySessionData's own comment) simply marks nothing, exactly
    // the "show it as-is, don't crash, don't mark anything current" guard the spec asked for.
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("cur", items[i].getAttribute("data-effort") === this.currentEffort);
    }
  };
  ContextBar.prototype._closeEffortDropdown = function () {
    this.effortDropdownOpen = false;
    if (this.effortDd) this.effortDd.classList.remove("show");
  };

  // Sends "/model <name>" via the inject route:
  //   POST /api/term/inject {tty, text, submit: true, clear_first: true} -> {ok: true, ...}
  // A 404/400 (or any non-ok response) surfaces a toast rather than failing silently, per the spec.
  ContextBar.prototype._pickModel = function (name) {
    this._closeModelDropdown();
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

  // Mirrors _pickModel exactly — same inject contract ("/effort <level>" instead of
  // "/model <name>"), same toast-on-failure handling, see that function's own comment.
  ContextBar.prototype._pickEffort = function (level) {
    this._closeEffortDropdown();
    this._focusTerminal();
    fetch("/api/term/inject", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tty: this.ttyId, text: "/effort " + level, submit: true, clear_first: true })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
    }).then(function (res) {
      if (res.ok && res.j && res.j.ok === true) return;
      var reason = (res.j && res.j.error) ||
        (res.status === 404 ? "the effort-switch route isn't available in this build yet" :
         res.status === 400 ? "the terminal rejected that request" :
         "the terminal didn't confirm the switch");
      if (typeof toast === "function") toast("Couldn't switch effort", reason);
    }).catch(function () {
      if (typeof toast === "function") toast("Couldn't reach the server", "the effort switch wasn't sent");
    });
  };

  ContextBar.prototype._applySessionData = function (d) {
    var meta = (d && d.meta) || {};
    this.currentModel = _matchLadderModel(meta.model);
    if (this.modelBtn) this.modelBtn.textContent = (this.currentModel || "model") + " ▾";

    // Unlike the model label (a heuristic string-match against MODEL_LADDER — see
    // _matchLadderModel's own comment), meta.effort is a clean literal straight off the
    // transcript's own top-level `effort` field (aitracker/providers/claude.py); Auggie sessions
    // simply omit the key. Still guarded against a value outside EFFORT_LADDER (a future CLI
    // tier, or "auto"/"ultracode" — not effort levels at all, see EFFORT_LADDER's own comment):
    // shown as-is rather than crashing; _openEffortDropdown's `.cur` match then simply finds no
    // item, so nothing gets marked current.
    this.currentEffort = (typeof meta.effort === "string" && meta.effort) ? meta.effort : null;
    if (this.effortBtn) this.effortBtn.textContent = (this.currentEffort || "effort") + " ▾";

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
    // data) — a visible-but-empty docked strip is worse than no strip. `attached` is now dynamic
    // (see _setAttached() below), so this is re-evaluated from both sides via _syncBarVisibility.
    this._hasUsage = !!usage;
    this._syncBarVisibility();
  };

  // The server's own answer to "is a Claude CLI listening on this pty right now" (GET
  // /api/term/attached — term_vt.py's attached()/_foreground_is_claude) — polled alongside
  // /api/session in start() below, on the SAME 2s cycle, never a second timer. Reactive: flips
  // the switchers' visibility live if Claude exits mid-session (hide) or the user launches
  // `claude` inside a plain shell terminal (show) — see ContextBar's own constructor comment for
  // the false-negative/false-positive this replaces (mode as a proxy for "Claude is listening").
  ContextBar.prototype._setAttached = function (attached) {
    if (this._destroyed || this.attached === attached) return;
    this.attached = attached;
    if (this.switchersEl) this.switchersEl.style.display = attached ? "" : "none";
    // A stale open dropdown pointing at a pty that no longer has Claude listening would let a
    // queued click type into whatever's there now instead — close both defensively.
    if (!attached) { this._closeModelDropdown(); this._closeEffortDropdown(); }
    this._syncBarVisibility();
  };

  // Whole-bar visibility: shown when there's EITHER a live switcher OR usage data to show,
  // hidden (not just left empty) when there's neither — the same "no empty chrome" rule
  // _renderReadout always followed, now covering the switcher's own dynamic state too.
  ContextBar.prototype._syncBarVisibility = function () {
    if (this.el) this.el.style.display = (this.attached || this._hasUsage) ? "" : "none";
  };

  ContextBar.prototype.start = function () {
    var self = this;
    function tick() {
      if (self._destroyed) return;
      fetch("/api/session?id=" + encodeURIComponent(self.sid))
        .then(function (r) { return r.json(); })
        .then(function (d) { if (!self._destroyed && d && !d.error) self._applySessionData(d); })
        .catch(function () { });
      // Folded into the SAME 2s poll cycle as the session fetch above — one timer, two fetches —
      // rather than a second independent setInterval. A 404 (dead tty) or any network failure is
      // treated as "not attached", mirroring the server's own conservative default
      // (_foreground_is_claude: any failure there reports False too): hiding the switchers is the
      // harmless failure, leaving a stale one visible would type a slash command into whatever's
      // now listening on this pty instead.
      fetch("/api/term/attached?tty=" + encodeURIComponent(self.ttyId))
        .then(function (r) { return r.ok ? r.json() : { claude_attached: false }; })
        .then(function (j) { if (!self._destroyed) self._setAttached(!!(j && j.claude_attached)); })
        .catch(function () { if (!self._destroyed) self._setAttached(false); });
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

  // ===== ONE terminal row, shared by the cap block AND the "Manage terminals" panel ==========
  // Both need exactly the same thing: a running terminal identified by session-or-command ·
  // project · age, with action buttons on the right. They differ only in WHICH actions (the cap
  // block offers one kill; the manager offers peek + kill) and in what those actions then do --
  // never in what a row IS.
  // Landing it once is conventions rule 4: a second hand-rolled copy of this markup is precisely
  // how the divergences this file's header brief catalogues got in.
  //
  // `t` is one entry of the SERVER's terminal list -- the 429 body's `terminals` array from
  // POST /api/term/pty, or GET /api/term/list's, which are the same shape by construction (both
  // come from term_vt.py's single `_live_list()`). `actions` is an ordered list of
  // {text, title, aria, onClick}; every button gets the shared .vtcapx class, so one CSS rule and
  // one latch selector (`querySelectorAll(".vtcapx")`) cover both callers.
  function buildTermRow(t, now, actions) {
    var row = document.createElement("div");
    row.className = "vtcaprow";
    var mins = Math.max(0, Math.round((now - (t.started || now)) / 60));
    var label = document.createElement("span");
    label.className = "vtcaplabel";
    // Session identity: `t.session` is the Claude session id this terminal is running under --
    // "" for a plain shell, always present and never undefined (term_vt._live_list's own
    // contract). Three "claude --resume <uuid>" rows used to render character-for-character
    // identical, because the uuid was the only thing that differed and nothing here showed it in
    // full -- exactly the bug the user's screenshot caught. Resolved against `sessions`, the
    // REAL global array from app.js (see this file's header comment: concatenated into the same
    // top-level <script>, so this is the sidebar's own list, already polled every 2s and held in
    // memory) -- no new fetch, no new server route. Conventions rule 5 ("server owns policy") is
    // about thresholds/labels/ranking the client would otherwise re-derive; a session's title is
    // just data the client already holds, and app.js's own narration-jump helper resolves the
    // identical id -> title -> id.slice(0,8) chain for the same reason (app.js's `label` closure,
    // ~line 1067). A session with no match in that list yet (sidebar hasn't polled, or the
    // session isn't in scope) falls back to the short id, matching that same convention -- never
    // the raw 36-char uuid.
    var identity = "";
    if (t.session) {
      var list = (typeof sessions !== "undefined" && sessions) || [];
      var hit = null;
      for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].id === t.session) { hit = list[i]; break; }
      }
      identity = (hit && (hit.title || hit.project)) || t.session.slice(0, 8);
    }
    // cwd: the LEADING segment of a long path is the part every terminal in the SAME project
    // shares (/Users/<name>/Documents/...) -- and the part a leading-anchored ellipsis was
    // truncating the row DOWN TO, telling the user nothing. The TRAILING segment is what
    // actually names the project, same formula as app.js's own `base()` helper (already used
    // elsewhere in this app to name a file by its trailing path segment) -- computed inline
    // rather than calling `base()` itself, because unlike `cur`/`EXT`/`esc`/`toast` (this file's
    // documented, always-present app.js globals -- see the header comment) `base` is not one of
    // them, and every OTHER app.js-only reference in this file (`toast`) is guarded with
    // `typeof ... === "function"` before use for exactly that reason. The untruncated path and
    // the raw command still reach the user via the tooltip below.
    var cwdTail = (t.cwd || "").split("/").pop() || (t.cwd || "");
    label.textContent = (identity || (t.cmd || "shell")) + "  ·  " + cwdTail + "  ·  " + mins + "m";
    label.title = t.tty + "  ·  " + (t.cmd || "shell") + "  ·  " + (t.cwd || "");
    row.appendChild(label);
    (actions || []).forEach(function (a) {
      var b = document.createElement("button");
      b.className = "vtcapx";
      b.textContent = a.text;
      b.title = a.title;
      // Icon-only controls (the ✕) would otherwise announce as "✕" and nothing else -- give every
      // action a real accessible name naming the terminal it acts on.
      b.setAttribute("aria-label", a.aria || a.title);
      b.onclick = a.onClick;
      row.appendChild(b);
    });
    return row;
  }

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
      // The row itself comes from the SHARED row builder above -- this block contributes only
      // the one action it needs and what that action does.
      wrap.appendChild(buildTermRow(t, now, [{
        text: "✕",
        title: "kill this terminal",
        aria: "kill this terminal — " + (t.cmd || "shell"),
        onClick: function () {
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
        }
      }]));
    });
    modalBodyEl.innerHTML = "";
    modalBodyEl.appendChild(wrap);
  }

  // Wires a modal terminal's mount-facing callbacks -- shared by openVT's initial build AND
  // switchActiveRenderer's rebuild below, so the two never drift into two slightly different
  // copies of the same "starting…" suppression logic, and so BOTH renderers' notices reach the
  // one banner stack this mount owns.
  function _wireModalTerm(term) {
    // Notices: whichever renderer is attached forwards the same {seq, text} object here (grid off
    // its JSON frame's `notices`, xterm off /api/term/raw's named `notice` event) and the MOUNT
    // decides what to draw. show() returns true only when it actually added a banner (a replayed
    // seq after an EventSource reconnect returns false), and a banner shrinks the pane -- so the
    // terminal renegotiates its row count exactly then. observePane's ResizeObserver would catch
    // this too; the explicit call is the fallback for browsers without ResizeObserver.
    term._onNotice = function (n) {
      if (activeTerm !== term) return;
      if (modalNotices && modalNotices.show(n)) term.measureAndResize();
    };
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
    _wireModalTerm(term);
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
    // A NEW pty is about to be opened, whose notice `seq`s restart at 1 -- so the banner stack and
    // its dedupe high-water mark both reset here. (The innerHTML wipe above already detached the
    // old elements; clear() is what stops the tracker from suppressing the new pty's seq 1..N.)
    // Deliberately NOT done on a renderer switch -- see createNoticeBanner's header.
    if (modalNotices) modalNotices.clear();
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
          // The OPEN-TIME advisory goes through the SAME banner stack every streamed notice uses
          // (createNoticeBanner) -- it just carries no `seq`, so it is never deduped against them.
          // Nothing to remove in the absent case: the clear() at the top of openVT already did it.
          if (activeNotice) modalNotices.show({ text: activeNotice });
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
          _wireModalTerm(term);
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
    // The pty is gone, so the banners go with it -- and the seq tracker resets for the next one.
    if (modalNotices) modalNotices.clear();
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

  // ===== "Manage terminals" panel ===========================================================
  // Until now the ONLY way to see or close a running terminal was to hit the concurrency cap and
  // be shown renderCapBlock's list as a consolation prize. This is that same list, on purpose,
  // any time: GET /api/term/list (live terminals, oldest first, plus the server's own `max`).
  // The rows come from the SHARED row builder above -- the cap block and this panel cannot drift
  // into two different ideas of what a terminal row is (conventions rule 4).
  //
  // The overlay is built on <body>, NEVER inside #ext_launch_side/.side: .side gets
  // `transform:translateX(...)` at max-width:600px (app.css's phone drawer), and a transformed
  // ancestor becomes the containing block for any position:fixed descendant -- which is exactly
  // what .overlay is. Same trap, same fix, as ext_launch.js's directory picker (see buildPicker's
  // comment there) and as this file's own modal, whose #ext_vt mount already sits outside .side.
  var mgrOverlay = null, mgrStatusEl = null, mgrBodyEl = null;
  // Inline two-step confirm for "Close all" (see renderManagerBody): closing every terminal
  // SIGKILLs real running Claude sessions and cannot be undone, so the first click only arms the
  // button. Reset on open, on close, and on every refresh, so the armed state can never survive a
  // dismissal OR an unrelated redraw (a row's ✕ goes through refreshManager too -- redrawing
  // ALREADY ARMED would turn the user's next "let me arm it" click into a confirmed kill-all).
  var mgrConfirmAll = false;
  // When it was armed. The arm handler re-renders SYNCHRONOUSLY, so the confirm button exists
  // before the SECOND click of a double-click is dispatched -- measured live, one double-click on
  // "Close all" killed three terminals with the confirmation never being read. The confirm path
  // therefore ignores anything arriving within this window of the arm.
  var mgrArmedAt = 0;
  // 500ms: exactly the platform double-click threshold (the macOS and Windows defaults both sit
  // at 500ms), so every pair of clicks the OS itself would call a double-click is rejected, while
  // a user who actually READS the one-line warning is far past it before deciding.
  var _ARM_GUARD_MS = 500;
  function _armGuardActive() { return Date.now() - mgrArmedAt < _ARM_GUARD_MS; }

  function buildManager() {
    mgrOverlay = document.createElement("div");
    mgrOverlay.className = "overlay";
    mgrOverlay.id = "vtmgrmodal";
    mgrOverlay.addEventListener("click", function (ev) { if (ev.target === mgrOverlay) closeManager(); });

    var modal = document.createElement("div");
    modal.className = "modal vtmgrmodal";

    var mh = document.createElement("div");
    mh.className = "mh";
    var title = document.createElement("span");
    title.className = "fn";
    title.textContent = "TERMINALS";
    mgrStatusEl = document.createElement("span");
    mgrStatusEl.className = "pp";
    var x = document.createElement("span");
    x.className = "x";
    x.textContent = "✕";
    x.title = "Close this panel — every terminal keeps running";
    x.setAttribute("aria-label", "Close this panel — every terminal keeps running");
    x.addEventListener("click", closeManager);
    mh.appendChild(title);
    mh.appendChild(mgrStatusEl);
    mh.appendChild(x);

    mgrBodyEl = document.createElement("div");
    mgrBodyEl.className = "mb vtmgrmb";

    modal.appendChild(mh);
    modal.appendChild(mgrBodyEl);
    mgrOverlay.appendChild(modal);
    document.body.appendChild(mgrOverlay);

    // Same convention as this file's own modal-Escape listener and ext_launch.js's picker: acts
    // only while THIS overlay is the one showing, so it never fights app.js's document-level
    // Escape handler (diffmodal/msgmodal/bgdrawer) or the terminal modal's.
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      if (!mgrOverlay || mgrOverlay.style.display !== "flex") return;
      closeManager();
    });
  }

  function closeManager() {
    if (mgrOverlay) mgrOverlay.style.display = "none";
    mgrConfirmAll = false;
  }

  function openManager() {
    // On a phone the button that opens this only exists INSIDE the open sidebar drawer (.side,
    // z-index 60) -- the shared .overlay is z-index 50, so left open the drawer would sit on top
    // of the panel. Every other place that leaves the drawer closes it first; so does this.
    if (typeof closeDrawer === "function") closeDrawer();
    if (!mgrOverlay) buildManager();
    mgrConfirmAll = false;
    mgrOverlay.style.display = "flex";
    refreshManager();
  }

  function refreshManager() {
    if (!mgrBodyEl) return;
    // Disarm on EVERY refresh, not just on open/close. Killing one row goes
    // closeOneFromManager -> _refreshAfterReap -> here -> renderManagerBody, and a panel that came
    // back already armed (with the latch released) hands the user's next footer click straight to
    // "kill everything". This is the one place all three redraw paths pass through.
    mgrConfirmAll = false;
    mgrStatusEl.textContent = "loading…";
    mgrBodyEl.innerHTML = '<div class="empty vtempty">loading…</div>';
    fetch("/api/term/list")
      .then(function (r) {
        return r.json().catch(function () { return {}; })
          .then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
      })
      .then(function (res) {
        if (!res.ok) {
          mgrStatusEl.textContent = "";
          mgrBodyEl.innerHTML = '<div class="empty vtempty">' + esc(
            (res.j && res.j.error) ||
            (res.status === 403
              ? "in-browser terminal is disabled — set TRACKER_TERMINAL=1 and TRACKER_AUTH"
              : res.status === 404
                ? "managing terminals isn't available on this server yet"
                : "couldn't list the running terminals")
          ) + "</div>";
          return;
        }
        renderManagerBody((res.j && res.j.terminals) || [], res.j && res.j.max);
      })
      .catch(function (e) {
        mgrStatusEl.textContent = "";
        mgrBodyEl.innerHTML = '<div class="empty vtempty">failed to reach the server: ' + esc(String(e)) + "</div>";
      });
  }

  function renderManagerBody(terminals, max) {
    var now = Date.now() / 1000;
    // The cap is the SERVER's number (conventions rule 5) -- read straight off the response and
    // rendered, never a constant in this file. Omitted entirely if the server didn't send one,
    // rather than substituting a guess.
    mgrStatusEl.textContent = terminals.length + (max ? " of " + max : "") + " running";
    mgrBodyEl.innerHTML = "";
    var wrap = document.createElement("div");
    wrap.className = "empty vtempty vtmgr";
    if (!terminals.length) {
      var none = document.createElement("div");
      none.className = "vtcaphead";
      none.textContent = "no terminals running — use “+ New terminal” to start one.";
      wrap.appendChild(none);
      mgrBodyEl.appendChild(wrap);
      return;
    }
    var head = document.createElement("div");
    head.className = "vtcaphead";
    // Say plainly what ✕ does HERE, because it is not what ✕ does on the modal: this one is
    // POST /api/term/close, which SIGKILLs the whole process group; the modal's merely detaches
    // the viewer and leaves the terminal running.
    head.textContent = "Peek opens a terminal in its own tab. ✕ kills it — SIGKILLs the whole "
      + "process group, unlike closing a terminal window, which only stops watching it.";
    wrap.appendChild(head);
    terminals.forEach(function (t) {
      wrap.appendChild(buildTermRow(t, now, [
        {
          text: "peek",
          title: "open this terminal in its own tab — nothing is killed",
          aria: "peek at " + (t.cmd || "shell"),
          onClick: function () { peekTerm(t); }
        },
        {
          text: "✕",
          title: "kill this terminal — SIGKILLs its process group, it does not just stop watching",
          aria: "kill this terminal — " + (t.cmd || "shell"),
          onClick: function () { closeOneFromManager(t); }
        }
      ]));
    });

    var foot = document.createElement("div");
    foot.className = "vtmgrfoot";
    var all = document.createElement("button");
    all.className = "vtcapx vtmgrall";
    if (mgrConfirmAll) {
      var warn = document.createElement("span");
      warn.className = "vtmgrwarn";
      warn.textContent = "are you sure — this kills " + terminals.length + " running terminal"
        + (terminals.length === 1 ? "" : "s") + ", including any Claude session inside them. It cannot be undone.";
      var cancel = document.createElement("button");
      cancel.className = "vtcapx";
      cancel.textContent = "Cancel";
      cancel.title = "Leave every terminal running";
      cancel.setAttribute("aria-label", "Cancel — leave every terminal running");
      // Guarded too, so an accidental double-click doesn't silently DISARM the panel either --
      // the second click is swallowed whole and the user is left looking at the warning they were
      // meant to read, which is the entire point of the two-step.
      cancel.onclick = function () {
        if (_armGuardActive()) return;
        mgrConfirmAll = false; renderManagerBody(terminals, max);
      };
      all.textContent = "Yes, kill all " + terminals.length;
      all.title = "Confirm: kill every one of these terminals now";
      all.setAttribute("aria-label", "Confirm killing all " + terminals.length + " terminals");
      all.onclick = function () {
        // THE data-loss guard. Without it the second click of a double-click on "Close all" lands
        // on this button (it is created synchronously, inside the first click's own handler) and
        // kills every terminal with the warning never displayed for a single frame.
        if (_armGuardActive()) return;
        closeAll(terminals);
      };
      // The keyboard twin of the same hazard: a HELD Enter auto-repeats keydown at ~30ms once the
      // OS repeat delay elapses, and each repeat activates the focused button -- so the timing
      // guard alone would only postpone the kill past 500ms, not prevent it. A repeat is never a
      // deliberate second decision, so it never activates this button at all.
      all.addEventListener("keydown", function (ev) {
        if (ev.repeat) ev.preventDefault();
      });
      // Confirm FIRST, Cancel last: defence in depth for the double-click above. `.vtmgrall`
      // pins `all` rightward with margin-left:auto, so with Cancel appended after it the
      // destructive button no longer occupies the hit area the "Close all" button just vacated --
      // the harmless Cancel does. (A CSS `order:` would keep the visual Cancel/Confirm order and
      // still move the box; this file cannot touch ext_vt.css this round.)
      foot.appendChild(warn);
      foot.appendChild(all);
      foot.appendChild(cancel);
    } else {
      all.textContent = "Close all";
      all.title = "Kill every running terminal — asks you to confirm first";
      all.setAttribute("aria-label", "Close all terminals — asks you to confirm first");
      all.onclick = function () {
        mgrConfirmAll = true;
        mgrArmedAt = Date.now();
        renderManagerBody(terminals, max);
      };
      foot.appendChild(all);
    }
    wrap.appendChild(foot);
    mgrBodyEl.appendChild(wrap);
    // Arming blows away the focused node (mgrBodyEl.innerHTML = ""), which drops keyboard focus
    // to <body> and loses a keyboard user's place entirely. Put it on the control the warning is
    // asking about. Safe ONLY because of the two guards above -- landing focus on a live kill
    // button while a held Enter repeats is exactly the hazard `ev.repeat` refuses.
    if (mgrConfirmAll) { try { all.focus(); } catch (e) {} }
  }

  function peekTerm(t) {
    // Peek opens the terminal in ITS OWN TAB rather than attaching it inside this panel: the
    // ?tty= standalone route already attaches to an EXISTING pty, whereas openVT() can only
    // CREATE one -- attaching in place would be brand-new machinery for no gain, and a new tab
    // is also exactly what the modal's own "⤢ New tab" does. Same URL scheme openNewTab() builds
    // above. `session`/`mode` come from GET /api/term/list (empty strings for a plain shell, never
    // missing), so a peeked terminal gets its FULL context bar instead of the degraded bare-?tty=
    // one. `forked` likewise, so a peeked --fork-session terminal keeps its `⑂ fork` chip instead
    // of silently losing it -- the value is the LIVE Pty.forked, so a late backstop retry shows up
    // here even though the original POST /api/term/pty response could not carry it.
    // No `renderer` param on purpose: the list carries none, and bootStandalone() already
    // falls back to GET /api/term/renderer -- the server picks it, this file never guesses.
    var url = location.origin + location.pathname + "?tty=" + encodeURIComponent(t.tty) +
      "&sid=" + encodeURIComponent(t.session || "") +
      "&mode=" + encodeURIComponent(t.mode || "") +
      "&forked=" + (t.forked ? "1" : "0");
    var w = window.open(url, "_blank");
    if (!w) alert("Popup blocked — allow popups for this page to open a new tab.");
  }

  // The existing route -- no bulk variant was added server-side for "close all"; looping this one
  // is the smaller diff and the server already does the only dangerous part exactly once per tty.
  function closeTty(tty) {
    return fetch("/api/term/close", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tty: tty })
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r;
    });
  }

  // A pty leaves the list when the READER THREAD notices EOF, not when /api/term/close returns --
  // the same lag the cap block gives 250ms for before retrying (see its comment). Refreshing on
  // the response alone can therefore redraw a row for a terminal that is already dead. Give it the
  // same beat, from ONE place, so the two callers can't disagree about how long that is.
  var _REAP_SETTLE_MS = 250;

  function _refreshAfterReap() {
    setTimeout(refreshManager, _REAP_SETTLE_MS);
  }

  // Same whole-panel latch discipline as the cap block's: one destructive click at a time, so a
  // double-tap can't fire two kills against a list that is about to be redrawn under it.
  function _latchManager(disabled) {
    if (!mgrBodyEl) return;
    Array.prototype.forEach.call(mgrBodyEl.querySelectorAll(".vtcapx"),
                                 function (b) { b.disabled = disabled; });
  }

  function closeOneFromManager(t) {
    _latchManager(true);
    closeTty(t.tty)
      .then(function () {
        // Guarded like every other toast() in this file: `toast` lives in app.js, and this module
        // is also loaded by the standalone ?tty= tab, so it must never be the thing that throws.
        if (typeof toast === "function") toast("Terminal closed", t.cmd || t.tty);
        // Re-fetch instead of splicing the local array: the SERVER owns which ptys are alive, and
        // another tab (or the reaper) may have changed the list since it was drawn.
        _refreshAfterReap();
      })
      .catch(function (e) {
        _latchManager(false);
        if (typeof toast === "function") toast("Couldn't close that terminal", String(e));
      });
  }

  function closeAll(terminals) {
    mgrConfirmAll = false;
    _latchManager(true);
    // Sequential, not Promise.all: a dozen simultaneous SIGKILL+reap cycles on one server thread
    // pool is needless, and a serial chain gives a deterministic failure count to report.
    var failures = 0;
    var chain = Promise.resolve();
    terminals.forEach(function (t) {
      chain = chain.then(function () {
        return closeTty(t.tty).catch(function () { failures++; });
      });
    });
    chain.then(function () {
      if (typeof toast === "function") {
        if (failures) toast("Some terminals could not be closed", failures + " of " + terminals.length + " failed");
        else toast("Closed all terminals", terminals.length + " killed");
      }
      _refreshAfterReap();
    });
  }

  window.ExtVT = { open: openVT, manage: openManager };

  // ===== render hook: participates in the normal 2s poll like every other ext module, and is
  // what genuinely puts #ext_vt to use (the modal is built as its child, not appended to
  // document.body) — see buildOverlay(mount) above. =====
  // The standalone tab's own document.title, set once by bootStandalone() below and RE-ASSERTED
  // from render() on every poll. app.js's own render() unconditionally does
  // `document.title = title + " · tracker"` from the polled session (app.js ~1098), and it keeps
  // polling in this tab too -- so a title written only at boot is clobbered ~2s later and every
  // ⤢-opened tab ends up wearing the sidebar session's name instead of its own. EXT hooks run at
  // the very END of that same render (app.js ~1330), so this re-assert is the last write of each
  // tick and wins without app.js needing to know this mode exists.
  var standaloneTitle = null;

  function render(d) {
    if (document.documentElement.classList.contains("vt-standalone")) {
      if (standaloneTitle && document.title !== standaloneTitle) document.title = standaloneTitle;
      return;   // that mode owns #ext_vt itself
    }
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
    // Identify WHICH session this tab is, exactly like the modal's own header does
    // (modalTitleEl, in openVT) -- multiple standalone tabs are the whole point of the "⤢ New
    // tab" button, and a constant title makes them indistinguishable in the tab strip. `sid` is
    // optional on a bare ?tty= link (see above), so fall back to the tty, which always exists by
    // this line. Stored on `standaloneTitle` (see its declaration above render()) rather than
    // only written here, because app.js's poll rewrites document.title every 2s.
    standaloneTitle = "TERMINAL — " + (mode === "resume" ? "resume · " : "") + (sid || "tty " + tty);
    document.title = standaloneTitle;
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
    // This mount's own createNoticeBanner (see that helper) -- built in boot() against `mount`,
    // outliving every renderer switch mountRenderer performs, exactly like curBar does.
    var curNotices = null;

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
          // Both attributes, same text: `title` is the hover tooltip, `aria-label` is what a
          // screen reader announces instead of the bare "⑂ fork" glyph. The modal's own chip
          // (buildOverlay) carries the same pair -- neither site may set just one.
          chip.setAttribute("title", "This terminal is a copy of a background agent — the original is still running separately");
          chip.setAttribute("aria-label", "This terminal is a copy of a background agent — the original is still running separately");
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
      // Notices: identical wiring to the modal's own _wireModalTerm -- the renderer forwards the
      // {seq, text} object, the MOUNT dedupes/caps/draws it (createNoticeBanner). Hoisted here for
      // the same reason _onStatusChange is: both renderers, and every later switch, run this path.
      term._onNotice = function (n) {
        if (curTerm !== term) return;
        if (curNotices && curNotices.show(n)) term.measureAndResize();
      };
      term._onStatusChange = function (s) {
        if (curTerm !== term) return;
        // Same suppression the modal's _wireModalTerm applies, hoisted here so the two mount
        // points don't drift: while a mode="resume" pane is still coming up (server-owned
        // `starting`, tracked per SSE frame in _applyPatch) the refused-resume child's stream
        // drop would otherwise flash "reconnecting…" into this status line even though the
        // server recovers on its own seconds later. One steady "starting…" instead.
        if (term.starting) { renderStandaloneStatus("starting…"); return; }
        renderStandaloneStatus(s);
      };
      term.attach();
    }

    function boot(renderer) {
      // The notice banner goes in FIRST, so it lands ABOVE the terminal -- exactly where the
      // modal puts it (the shared helper's own insertion rule now guarantees that for both mounts
      // alike; it inserts before the container's first child when no banner is up yet). It used to
      // be appended AFTER mountRenderer(), i.e. below the pane AND below the
      // context bar, so the identical server message rendered at opposite ends of the two mount
      // points. The old "matching the order this code built in before the renderer switch
      // existed" note on statusEl below documents history, not a requirement; the one REAL
      // constraint it also states -- statusEl must exist before mountRenderer() calls attach() --
      // is untouched here. The banner itself is no longer built inline: `mount` gets its own
      // createNoticeBanner (the SAME helper the modal uses, and the same one every streamed
      // {seq, text} notice from either renderer lands in via mountRenderer's `_onNotice` above),
      // and the ?notice= advisory is just its first, seq-less entry. Created BEFORE termWrap so
      // "first child of `mount`" and "above the terminal" are the same position.
      curNotices = createNoticeBanner(mount);
      if (standaloneNotice) curNotices.show({ text: standaloneNotice });

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
      // node is harmless; it's appended for real last of all, so the final DOM order is
      // notice -> pane -> context bar -> status, matching the modal's own top-to-bottom order.
      statusEl = document.createElement("div");
      statusEl.className = "vtfullstatus";
      renderStandaloneStatus("connecting…");

      mountRenderer(renderer);   // builds the terminal into termWrap, and the context bar right after it

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
