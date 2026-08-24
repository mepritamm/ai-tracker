"""Tier 3's pure VT100/xterm screen emulator: bytes in, changed-row grid out.

`Screen` has NO pty, NO server, NO browser dependency -- it is a self-contained state machine
that turns a byte stream (whatever a PTY would hand you) into a 2-D character grid plus cursor
and mode state, and reports only the rows that changed since a given version. That is the whole
point of building it first: it is fully unit-testable, and the PTY/route/JS plumbing that another
agent adds on top of it is mechanical.

## The `snapshot(since)` contract -- read this before writing a client against it

    Screen(cols, rows).snapshot(since) -> {
        "v": int,                    # current version counter (monotonic, bumps on any row change)
        "rows": [[row_index, text, runs], ...],   # only rows whose content changed after `since`
        "cursor": [row, col],        # always current, regardless of `since` -- 0-based
        "alt": bool,                 # True while the alternate screen buffer is active
    }

- Pass `since=-1` for a full redraw (every row, since every row's stamp is >= 0). Pass the `v`
  you last received to get only what changed since then.
- `row_index` is 0-based.
- `text` is the row's characters (each character occupies exactly one display column -- see
  "wide characters" below), right-trimmed of any *trailing* cells that are both a plain space
  AND carry no SGR styling. Trailing cells that are styled (e.g. a colour-filled blank block at
  the end of a status line) are NOT trimmed, because a `runs` entry may reference them -- the
  painter must pad any un-covered columns after `text` with the row's background colour, not
  assume blank-uncolored.
- `runs` is a list of `[start_col, end_col, code]` (end exclusive, both 0-based), only for
  stretches of the row that carry NON-default SGR styling. A column not covered by any run is
  plain/default styling. `code` is a semicolon-joined SGR parameter string -- exactly what you'd
  place between `ESC[` and `m` to reproduce that cell's style -- built in this FIXED order:
  attribute codes present from {1 bold, 2 dim, 3 italic, 4 underline, 5 blink, 7 reverse,
  9 strike}, then the foreground code (`30`-`37`, `90`-`97`, `38;5;N`, or `38;2;R;G;B`), then the
  background code (`40`-`47`, `100`-`107`, `48;5;N`, or `48;2;R;G;B`). `code` is never empty --
  an empty/default style never produces a run.

## Explicitly out of scope -- accepted and consumed, never left to corrupt the stream

These are parsed just far enough to find their terminator and are then silently discarded; they
never reach the grid and never leave dangling bytes for the next character to inherit:

- **Mouse reporting** (private CSI modes `?1000`-`?1006`): consumed as unknown private DEC modes
  (no-op set/reset).
- **Bracketed paste** (`?2004`): same -- consumed as an unknown private DEC mode.
- **Sixel / other graphics** (DCS `ESC P ... ST`, and the sibling string types SOS `ESC X`, PM
  `ESC ^`, APC `ESC _`): the whole string is scanned for its terminator (`ESC \\` or `BEL`) and
  thrown away as one unit, so binary payload inside it (which can legitimately contain bytes
  that look like other escape codes) does not desync the parser.
- **Wide characters (CJK / emoji double-width)**: not implemented -- every decoded Unicode code
  point is treated as exactly one display column. A double-width character will visually misalign
  the columns after it; this is a known, deliberate gap, not a bug.
- **Every OSC beyond title-set** (`ESC ] 0 ;` / `ESC ] 2 ;`, terminated by `BEL` or `ESC \\`):
  the title text is captured onto `self.title` (not part of `snapshot()` -- it's outside the
  documented contract but harmless to expose); any other OSC number is consumed and discarded.

## Erase uses the currently-active SGR, not a hard default

`EL`/`ED` fill erased cells with a space carrying the CURRENTLY ACTIVE style, exactly like a real
terminal -- this is what lets a TUI set a background colour and then clear-to-paint it. A blank
row is therefore not always `text=""` with no runs: if the erase happened under an active
background colour, the erased cells are styled blanks and will show up as a run over otherwise
empty `text` (see the `runs`-vs-trailing-trim rule above). A fresh, never-erased cell (from
`__init__` or from growing past what was ever written) is always plain default.

## Split reads are load-bearing, not an edge case

A real PTY read can split ANY multi-byte unit -- an escape sequence, a UTF-8 character -- at any
byte boundary. `feed()` keeps unconsumed trailing bytes in `self._pending` and re-prepends them to
the next call, so an escape sequence or a UTF-8 code point split across two `feed()` calls parses
identically to one that arrived whole. Malformed UTF-8 is decoded with `errors="replace"` rather
than raising.
"""

TAB_STOP = 8


def _blank_row(cols):
    return [(" ", "")] * cols


class Screen:
    """A VT100/xterm-ish terminal screen. `feed(bytes)` is the only mutator; `snapshot(since)`
    is the only reader that matters to a caller (see module docstring for its exact shape)."""

    def __init__(self, cols=100, rows=30):
        self.cols = cols
        self.rows = rows

        self.primary = [_blank_row(cols) for _ in range(rows)]
        self.alt_grid = None
        self.grid = self.primary
        self.alt = False
        self._primary_cursor = (0, 0)
        self._primary_cursor_save = None

        self.cur_r = 0
        self.cur_c = 0
        self.pending_wrap = False

        self.scroll_top = 0
        self.scroll_bot = rows - 1

        self.autowrap = True
        self.cursor_visible = True

        self.title = ""

        # current SGR attribute state
        self.bold = self.dim = self.italic = self.underline = False
        self.blink = self.reverse = self.strike = False
        self.fg = None
        self.bg = None
        self._cur_code = ""

        self.v = 0
        self.row_v = [0] * rows
        self._bumped = False   # has this feed() call already bumped self.v?

        self._pending = b""    # unconsumed tail bytes across feed() calls

    # ---------------------------------------------------------------- public

    def feed(self, data):
        """Parse ANSI and mutate the grid. The only entry point."""
        if self._pending:
            data = self._pending + data
            self._pending = b""
        self._bumped = False

        n = len(data)
        i = 0
        while i < n:
            b = data[i]
            if b == 0x1B:  # ESC
                consumed = self._handle_escape(data, i)
                if consumed is None:      # incomplete -- need more bytes
                    self._pending = bytes(data[i:])
                    return
                i += consumed
            elif b < 0x20:
                i += self._handle_control(b)
            else:
                consumed = self._handle_text(data, i, n)
                if consumed is None:      # incomplete UTF-8 char -- need more bytes
                    self._pending = bytes(data[i:])
                    return
                i += consumed

    def snapshot(self, since):
        """Rows changed since version `since`, plus cursor + alt-screen flag."""
        rows_out = []
        for r in range(self.rows):
            if self.row_v[r] > since:
                rows_out.append(self._row_entry(r))
        return {"v": self.v, "rows": rows_out, "cursor": [self.cur_r, self.cur_c], "alt": self.alt}

    # ------------------------------------------------------------- internals

    def _row_entry(self, r):
        cells = self.grid[r]
        end = self.cols
        while end > 0 and cells[end - 1] == (" ", ""):
            end -= 1
        text = "".join(c[0] for c in cells[:end])
        runs = []
        if end:
            run_start = 0
            run_code = cells[0][1]
            for c in range(1, end):
                code = cells[c][1]
                if code != run_code:
                    if run_code:
                        runs.append([run_start, c, run_code])
                    run_start = c
                    run_code = code
            if run_code:
                runs.append([run_start, end, run_code])
        return [r, text, runs]

    def _dirty(self, r):
        if not self._bumped:
            self.v += 1
            self._bumped = True
        self.row_v[r] = self.v

    # -- control characters (C0, < 0x20) --------------------------------

    def _handle_control(self, b):
        if b == 0x08:          # BS
            self.cur_c = max(0, self.cur_c - 1)
            self.pending_wrap = False
        elif b == 0x09:        # TAB
            self.cur_c = min(self.cols - 1, ((self.cur_c // TAB_STOP) + 1) * TAB_STOP)
            self.pending_wrap = False
        elif b in (0x0A, 0x0B, 0x0C):  # LF, VT, FF -- all "index"
            self._index()
        elif b == 0x0D:        # CR
            self.cur_c = 0
            self.pending_wrap = False
        # BEL and any other C0 control: no-op, consumed
        return 1

    # -- printable text / UTF-8 decode -----------------------------------

    def _handle_text(self, data, i, n):
        b0 = data[i]
        if b0 < 0x80:
            length = 1
        elif 0xC0 <= b0 <= 0xDF:
            length = 2
        elif 0xE0 <= b0 <= 0xEF:
            length = 3
        elif 0xF0 <= b0 <= 0xF7:
            length = 4
        else:
            length = 1   # stray continuation/invalid byte -- decode alone, replaced below
        if i + length > n:
            return None  # incomplete -- ask for more
        chunk = bytes(data[i:i + length])
        text = chunk.decode("utf-8", errors="replace")
        for ch in text or "�":
            self._put_char(ch)
        return length

    def _put_char(self, ch):
        if self.pending_wrap:
            self._index()
            self.cur_c = 0
            self.pending_wrap = False
        self.grid[self.cur_r][self.cur_c] = (ch, self._cur_code)
        self._dirty(self.cur_r)
        if self.cur_c == self.cols - 1:
            if self.autowrap:
                self.pending_wrap = True
            # else: stay put, next char overwrites the last column
        else:
            self.cur_c += 1

    # -- escape sequences --------------------------------------------------

    def _handle_escape(self, data, i):
        """Returns bytes consumed starting at data[i] (i.e. including the ESC byte), or None if
        more data is needed before this sequence can be parsed."""
        n = len(data)
        if i + 1 >= n:
            return None
        b1 = data[i + 1]

        if b1 == 0x5B:  # '[' -- CSI
            return self._handle_csi(data, i)
        if b1 in (0x5D, 0x50, 0x58, 0x5E, 0x5F):  # ']' OSC, 'P' DCS, 'X' SOS, '^' PM, '_' APC
            return self._handle_string_seq(data, i, b1)
        if b1 == 0x44:   # 'D' IND
            self._index()
            return 2
        if b1 == 0x4D:   # 'M' RI
            self._reverse_index()
            return 2
        if b1 == 0x45:   # 'E' NEL
            self._index()
            self.cur_c = 0
            self.pending_wrap = False
            return 2
        if b1 == 0x37:   # '7' DECSC
            self._primary_cursor_save = (self.cur_r, self.cur_c)
            return 2
        if b1 == 0x38:   # '8' DECRC
            saved = self._primary_cursor_save
            if saved:
                self.cur_r, self.cur_c = saved
                self.pending_wrap = False
            return 2
        if b1 == 0x63:   # 'c' RIS -- full reset
            self._reset()
            return 2
        if b1 in (0x28, 0x29, 0x2A, 0x2B):  # '(' ')' '*' '+' charset designators -- 3 bytes total
            if i + 2 >= n:
                return None
            return 3
        # unrecognized ESC + byte: consume defensively so we never get stuck
        return 2

    def _handle_string_seq(self, data, i, kind):
        """OSC/DCS/SOS/PM/APC: `ESC <kind> ... (BEL | ESC \\)`. Consumed as one unit; only OSC
        0/2 (title-set) is inspected, everything else -- including sixel payload inside a DCS --
        is discarded without being interpreted."""
        n = len(data)
        j = i + 2
        while j < n:
            if data[j] == 0x07:              # BEL terminator
                body = bytes(data[i + 2:j])
                end = j + 1
                self._consume_string_seq(kind, body)
                return end - i
            if data[j] == 0x1B and j + 1 < n and data[j + 1] == 0x5C:  # ST = ESC \
                body = bytes(data[i + 2:j])
                end = j + 2
                self._consume_string_seq(kind, body)
                return end - i
            if data[j] == 0x1B and j + 1 >= n:
                return None   # might be the start of ST -- need one more byte to know
            j += 1
        return None  # terminator not found yet -- need more data

    def _consume_string_seq(self, kind, body):
        if kind == 0x5D:  # ']' OSC
            try:
                text = body.decode("utf-8", errors="replace")
            except Exception:
                return
            head, sep, rest = text.partition(";")
            if sep and head in ("0", "2"):
                self.title = rest
        # DCS/SOS/PM/APC (sixel etc.): discarded, nothing to extract

    # -- CSI: ESC [ params intermediates final --------------------------

    def _handle_csi(self, data, i):
        n = len(data)
        j = i + 2
        while j < n:
            b = data[j]
            if 0x30 <= b <= 0x3F or 0x20 <= b <= 0x2F:
                j += 1
                continue
            if 0x40 <= b <= 0x7E:
                final = b
                params_raw = bytes(data[i + 2:j])
                self._dispatch_csi(params_raw, chr(final))
                return j - i + 1
            # stray byte outside the CSI grammar -- bail out, consume through here
            self._dispatch_csi(bytes(data[i + 2:j]), chr(b) if b < 0x80 else "?")
            return j - i + 1
        return None  # final byte not seen yet -- need more data

    @staticmethod
    def _parse_params(raw):
        if not raw:
            return []
        out = []
        for part in raw.split(";"):
            try:
                out.append(int(part) if part != "" else 0)
            except ValueError:
                out.append(0)
        return out

    def _dispatch_csi(self, params_raw, final):
        private = params_raw[:1] in (b"?", b">", b"<", b"=")
        body = params_raw[1:] if private else params_raw
        try:
            text = body.decode("ascii", errors="ignore")
        except Exception:
            text = ""
        params = self._parse_params(text)

        if private:
            self._dispatch_private(params, final)
            return

        if final in ("A", "B", "C", "D"):
            n = params[0] if params and params[0] else 1
            if final == "A":
                self.cur_r = max(0, self.cur_r - n)
            elif final == "B":
                self.cur_r = min(self.rows - 1, self.cur_r + n)
            elif final == "C":
                self.cur_c = min(self.cols - 1, self.cur_c + n)
            elif final == "D":
                self.cur_c = max(0, self.cur_c - n)
            self.pending_wrap = False
        elif final in ("H", "f"):
            row = params[0] if len(params) >= 1 and params[0] else 1
            col = params[1] if len(params) >= 2 and params[1] else 1
            self.cur_r = min(max(row - 1, 0), self.rows - 1)
            self.cur_c = min(max(col - 1, 0), self.cols - 1)
            self.pending_wrap = False
        elif final == "J":
            self._erase_display(params[0] if params else 0)
        elif final == "K":
            self._erase_line(params[0] if params else 0)
        elif final == "m":
            self._sgr(params)
        elif final == "r":
            top = params[0] if len(params) >= 1 and params[0] else 1
            bot = params[1] if len(params) >= 2 and params[1] else self.rows
            top0 = min(max(top - 1, 0), self.rows - 1)
            bot0 = min(max(bot - 1, 0), self.rows - 1)
            if top0 < bot0:
                self.scroll_top, self.scroll_bot = top0, bot0
            else:
                self.scroll_top, self.scroll_bot = 0, self.rows - 1
            self.cur_r, self.cur_c = 0, 0
            self.pending_wrap = False
        # any other final byte: no-op, consumed

    def _dispatch_private(self, params, final):
        if final not in ("h", "l"):
            return
        set_ = final == "h"
        for code in params:
            if code == 1049:
                if set_:
                    self._enter_alt()
                else:
                    self._leave_alt()
            elif code == 7:
                self.autowrap = set_
            elif code == 25:
                self.cursor_visible = set_
            # 1000-1006 (mouse), 2004 (bracketed paste), and any other private mode: no-op

    # -- erase -----------------------------------------------------------

    def _erase_line(self, mode):
        r = self.cur_r
        blank = (" ", self._cur_code)
        row = self.grid[r]
        if mode == 0:
            for c in range(self.cur_c, self.cols):
                row[c] = blank
        elif mode == 1:
            for c in range(0, self.cur_c + 1):
                row[c] = blank
        else:  # 2 or anything else
            for c in range(self.cols):
                row[c] = blank
        self._dirty(r)

    def _erase_display(self, mode):
        blank = (" ", self._cur_code)
        if mode == 0:
            for c in range(self.cur_c, self.cols):
                self.grid[self.cur_r][c] = blank
            self._dirty(self.cur_r)
            for r in range(self.cur_r + 1, self.rows):
                self.grid[r] = [blank] * self.cols
                self._dirty(r)
        elif mode == 1:
            for r in range(0, self.cur_r):
                self.grid[r] = [blank] * self.cols
                self._dirty(r)
            for c in range(0, self.cur_c + 1):
                self.grid[self.cur_r][c] = blank
            self._dirty(self.cur_r)
        else:  # 2 or 3: whole screen
            for r in range(self.rows):
                self.grid[r] = [blank] * self.cols
                self._dirty(r)

    # -- SGR ---------------------------------------------------------------

    def _reset_attrs(self):
        self.bold = self.dim = self.italic = self.underline = False
        self.blink = self.reverse = self.strike = False
        self.fg = None
        self.bg = None

    def _recompute_code(self):
        parts = []
        if self.bold:
            parts.append("1")
        if self.dim:
            parts.append("2")
        if self.italic:
            parts.append("3")
        if self.underline:
            parts.append("4")
        if self.blink:
            parts.append("5")
        if self.reverse:
            parts.append("7")
        if self.strike:
            parts.append("9")
        if self.fg:
            parts.append(self.fg)
        if self.bg:
            parts.append(self.bg)
        self._cur_code = ";".join(parts)

    def _sgr(self, params):
        if not params:
            params = [0]
        i = 0
        ln = len(params)
        while i < ln:
            p = params[i]
            if p == 0:
                self._reset_attrs()
            elif p == 1:
                self.bold = True
            elif p == 2:
                self.dim = True
            elif p == 3:
                self.italic = True
            elif p == 4:
                self.underline = True
            elif p == 5:
                self.blink = True
            elif p == 7:
                self.reverse = True
            elif p == 9:
                self.strike = True
            elif p == 22:
                self.bold = self.dim = False
            elif p == 23:
                self.italic = False
            elif p == 24:
                self.underline = False
            elif p == 25:
                self.blink = False
            elif p == 27:
                self.reverse = False
            elif p == 29:
                self.strike = False
            elif 30 <= p <= 37:
                self.fg = str(p)
            elif p == 38 or p == 48:
                # Extended (256-color / truecolor) fg (38) or bg (48). A truncated form --
                # "38;5" with no index, "38;2" with 0-2 of the 3 RGB components, or "38" with
                # nothing after it -- must still consume whatever sub-params it DID see, so
                # they can never fall through and be reinterpreted as ordinary attribute codes
                # (5 = blink, 2 = dim -- a truncated "38;5" would otherwise silently turn on
                # blink and leak into every character written after it).
                if i + 1 < ln:
                    mode = params[i + 1]
                    if mode == 5 and i + 2 < ln:
                        code = "%d;5;%d" % (p, params[i + 2])
                        i += 2
                    elif mode == 2 and i + 4 < ln:
                        code = "%d;2;%d;%d;%d" % (p, params[i + 2], params[i + 3], params[i + 4])
                        i += 4
                    elif mode in (2, 5):
                        code = None            # incomplete -- no-op, but still consume below
                        i = ln - 1              # swallow the rest of this malformed tail
                    else:
                        code = None            # unrecognised colour-space id -- consume just it
                        i += 1
                    if code is not None:
                        if p == 38:
                            self.fg = code
                        else:
                            self.bg = code
                # else: 38/48 was the final param with nothing after it -- no-op, nothing to consume
            elif p == 39:
                self.fg = None
            elif 40 <= p <= 47:
                self.bg = str(p)
            elif p == 49:
                self.bg = None
            elif 90 <= p <= 97:
                self.fg = str(p)
            elif 100 <= p <= 107:
                self.bg = str(p)
            # any other SGR code: ignored
            i += 1
        self._recompute_code()

    # -- index / reverse-index / scrolling ---------------------------------

    def _index(self):
        if self.cur_r == self.scroll_bot:
            self._scroll_up(1)
        elif self.cur_r < self.rows - 1:
            self.cur_r += 1
        self.pending_wrap = False

    def _reverse_index(self):
        if self.cur_r == self.scroll_top:
            self._scroll_down(1)
        elif self.cur_r > 0:
            self.cur_r -= 1
        self.pending_wrap = False

    def _scroll_up(self, count):
        top, bot = self.scroll_top, self.scroll_bot
        region = self.grid[top:bot + 1]
        region = region[count:] + [_blank_row(self.cols) for _ in range(count)]
        self.grid[top:bot + 1] = region
        for r in range(top, bot + 1):
            self._dirty(r)

    def _scroll_down(self, count):
        top, bot = self.scroll_top, self.scroll_bot
        region = self.grid[top:bot + 1]
        region = [_blank_row(self.cols) for _ in range(count)] + region[:-count or None]
        self.grid[top:bot + 1] = region
        for r in range(top, bot + 1):
            self._dirty(r)

    # -- alt screen ----------------------------------------------------------

    def _enter_alt(self):
        if self.alt:
            return
        self._primary_cursor = (self.cur_r, self.cur_c)
        if self.alt_grid is None:
            self.alt_grid = [_blank_row(self.cols) for _ in range(self.rows)]
        self.grid = self.alt_grid
        self.alt = True
        self.cur_r, self.cur_c = 0, 0
        self.pending_wrap = False
        for r in range(self.rows):
            self._dirty(r)

    def _leave_alt(self):
        if not self.alt:
            return
        self.grid = self.primary
        self.alt = False
        self.cur_r, self.cur_c = self._primary_cursor
        self.pending_wrap = False
        for r in range(self.rows):
            self._dirty(r)

    # -- RIS full reset --------------------------------------------------

    def _reset(self):
        cols, rows = self.cols, self.rows
        self.__init__(cols, rows)
