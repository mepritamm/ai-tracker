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

## `v` is monotonic FOR THE LIFE OF THE OBJECT -- reset and resize included

`v` only ever increases: `ESC c` (RIS), `resize()` and alt-screen switches all bump it and stamp
every row dirty, rather than starting a new counter. A viewer holding `since=N` must never be
told "nothing changed" while the grid is being repainted underneath it, and RIS is exactly what
a user types (`reset`) when the screen already looks wrong.

## `pop_replies()` -- the one thing that flows back TOWARDS the child

Some sequences are questions, not commands: `ESC[6n` asks where the cursor is, `ESC[c` / `ESC[>c`
ask what the terminal is, and a real program (`vim`, every startup) BLOCKS until it gets an
answer. `Screen` owns no file descriptor, so it accumulates the answer in `pending_replies` and
whoever owns the pty drains it with `pop_replies()` after each `feed()` and writes the bytes back
to the master fd -- see `_reader`. A caller that never drains is not corrupted, just mute: the
buffer is capped at `MAX_REPLIES`.

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
- **Wide characters (CJK / emoji double-width) and combining marks**: not implemented -- every
  decoded Unicode code point is treated as exactly one display column, and a combining mark
  (including emoji variation selector U+FE0F) occupies its own cell instead of joining the
  character before it. Columns after such a character visually misalign; this is a known,
  deliberate gap, not a bug, and it is the ONE row on which this emulator still disagrees with
  `pyte` across the real captured streams in `tests/fixtures/`.
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

## The PTY routes below -- an UNRESTRICTED shell, and that is deliberate

`Screen` above is pure and safe by construction: bytes in, grid out, no side effects. Everything
below it is not. `POST /api/term/pty` starts a REAL shell (or `claude --resume <sid>`) on the
machine running this server; `POST /api/term/keys` writes whatever bytes the caller sends straight
into that shell's stdin. There is no allowlist here -- unlike Tier 2 (`term_run.py`), an allowlist
would defeat the entire point of a terminal -- so once a caller can reach these routes they can run
anything this server's own OS user can run.

**The only thing standing between a caller and that shell is `term_gate.guard()`**:
`TRACKER_TERMINAL=1` *and* a configured `TRACKER_AUTH`, plus a same-origin check on POSTs. There is
DELIBERATELY NO loopback / `127.0.0.1` check here, and no `TRACKER_TERMINAL_REMOTE` escape hatch
either -- both appeared in the original plan (docs/terminal-tiers-plan.md Sec 5 rule 4) and both
were removed on an explicit, informed decision, recorded in that same file's ERRATA section: a
loopback check is not a security boundary once `make tunnel` is in the picture, because
`cloudflared` terminates on this machine and dials the server over loopback, so EVERY request that
arrives through the public tunnel also presents `client_address[0] == "127.0.0.1"` and would sail
straight through such a check. Tier 1 demonstrated this concretely with an equivalent forwarder
before Tier 3 was built. Adding the check back "to be safe" would not make anything safer; it would
only make it easier for the next reader to believe there is a network boundary here where there is
none, which is worse than having no check at all.

**What this means concretely.** Anyone who can reach this server's HTTP port AND knows
`TRACKER_AUTH` gets a real, interactive shell as this server's own user -- the same whether they
are on localhost, on the LAN, or on the far end of a Cloudflare tunnel. `TRACKER_AUTH` is not "a
login" here; while `TRACKER_TERMINAL=1` is set, it is the entire perimeter, and it deserves the
seriousness of a root password, not a dashboard password. The user was told this in exactly these
terms and chose it anyway, on the stated grounds that the tunnel URL and the credential are both
rotated regularly. That tradeoff is theirs to make; do not silently "fix" it back.
"""

import base64
import collections
import json
import os
import pty
import select
import signal
import socket
import struct
import threading
import time
import uuid

from . import server, term_gate, term_run
# Circular by design, exactly like term_run's own import of `server` -- see that module's
# docstring comment. server.py's bottom-of-file loader imports this module by name, and this
# module registers its routes back into server.EXTRA_GET/EXTRA_POST. Safe because those two dicts
# are created near the top of server.py, long before the loader runs. term_run is imported for its
# strip_git_env -- the single source of truth for "what git environment must not survive into a
# spawned child" -- reused here rather than duplicated (see strip_git_env's own docstring for why
# duplicating it would be a bug waiting to happen).

TAB_STOP = 8

MAX_PENDING = 4096
"""Hard cap on the unconsumed tail `feed()` will carry across calls (B3).

A legitimate OSC/DCS/SOS/PM/APC string is short -- a title, a termcap query, a sixel frame.
An UNTERMINATED one is not: `_handle_string_seq` finds no BEL/ST, returns None, and every
subsequent byte of the stream is buffered forever with the screen frozen behind it. That is not
hypothetical -- of 447 real binaries under /bin and /usr/bin, four contain a stray DCS
introducer (`/bin/sh` has one at offset 87584), so a plain `cat /bin/sh` in a terminal used to
wedge the emulator permanently and grow `_pending` without bound. Past this many bytes we give
up on the sequence instead of on the stream: the introducer is discarded and parsing resumes as
ordinary text from just after it (see `Screen.resyncs`)."""

MAX_REPLIES = 8192
"""Cap on un-drained DSR/DA reply bytes (B7). The reader loop drains after every `feed()`, so
this only matters if nobody ever calls `pop_replies()` -- a `Screen` used bare in a test, or a
pty whose write side died. Bounded rather than unbounded is the whole point."""


def _blank_row(cols):
    return [(" ", "")] * cols


_Save = collections.namedtuple("_Save", "r c attrs origin")
"""What DECSC (`ESC 7`) actually saves, and what DECRC (`ESC 8`) actually restores.

Position ALONE is the bug B5 fixes: DECSC saves the graphic rendition and the origin-mode flag
too, so a TUI that does `ESC 7`, paints a coloured status bar, then `ESC 8` expects its previous
colour back -- restoring only (r, c) leaves the status bar's background smeared across everything
it writes next. xterm's `?1049` is defined in terms of DECSC/DECRC, so it inherits this.
"""


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
        # One save slot PER BUFFER, indexed by int(self.alt) -- xterm keeps a separate saved
        # cursor for the normal and the alternate screen, and sharing one slot means a TUI that
        # does ESC 7 inside the alt screen silently overwrites the position `?1049l` will later
        # restore the primary screen to. Each entry is the full DECSC record (see `_save_cursor`),
        # not just a position: DECSC saves the SGR attributes and origin mode too.
        self._saves = [None, None]

        self.cur_r = 0
        self.cur_c = 0
        self.pending_wrap = False

        self.scroll_top = 0
        self.scroll_bot = rows - 1

        self.autowrap = True
        self.cursor_visible = True
        self.origin_mode = False    # DECOM (`?6`): row params are relative to the scroll region

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

        self._pending = b""    # unconsumed tail bytes across feed() calls (bounded: MAX_PENDING)
        self.resyncs = 0       # how many times an over-long unterminated sequence was abandoned
        self.pending_replies = bytearray()   # DSR/DA answers owed to the child; see pop_replies

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
                    if n - i > MAX_PENDING:
                        # Not "more is coming" -- this sequence has no terminator in a whole
                        # MAX_PENDING of stream, so waiting for one freezes the screen forever
                        # (B3). Abandon the introducer, keep the stream: resume the parse right
                        # after `ESC <type>` as ordinary text.
                        self.resyncs += 1
                        i += 2 if n - i >= 2 else 1
                        continue
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

    def pop_replies(self):
        """Bytes the terminal owes the child, drained (B7).

        A `Screen` is an output device with one narrow input duct: some sequences are QUESTIONS
        (`ESC[6n` "where is the cursor?", `ESC[>c` "what are you?") and a real program BLOCKS
        waiting for the answer -- `vim` sends both on startup. Answering is not the parser's job
        to perform (it owns no fd), so it accumulates the answer here and whoever owns the pty
        writes it back after each `feed()`; see `_reader`. Returns b"" when nothing is owed.
        """
        out = bytes(self.pending_replies)
        del self.pending_replies[:]
        return out

    def _reply(self, data):
        if len(self.pending_replies) + len(data) <= MAX_REPLIES:
            self.pending_replies += data

    def snapshot(self, since):
        """Rows changed since version `since`, plus cursor + alt-screen flag."""
        rows_out = []
        for r in range(self.rows):
            if self.row_v[r] > since:
                rows_out.append(self._row_entry(r))
        return {"v": self.v, "rows": rows_out, "cursor": [self.cur_r, self.cur_c], "alt": self.alt}

    def resize(self, cols, rows):
        """Change the grid dimensions in place, preserving whatever fits from the top-left.

        The PTY side of a resize is `TIOCSWINSZ` (see term_vt's `_set_winsize`); this is the
        Screen-side half of the same operation, and both must happen together or the emulator's
        idea of the grid's shape silently diverges from the real pty's. Not a real xterm's resize
        semantics (a real terminal reflows text and can scroll its viewport) -- this is the same
        kind of deliberate simplification as the "wide characters" gap documented above: each
        existing row is cropped or space-padded to the new column count, rows beyond the new row
        count are dropped and short grids are padded with blank rows, the cursor and scroll region
        are clamped into the new bounds, and every row is marked dirty so the next `snapshot()`
        (at ANY `since`) redraws the whole grid rather than trying to describe a resize as a diff.
        """
        if cols == self.cols and rows == self.rows:
            return

        def _resized(grid):
            out = []
            for r in range(rows):
                if r < len(grid):
                    row = grid[r]
                    row = row[:cols] if cols <= len(row) else row + _blank_row(cols - len(row))
                else:
                    row = _blank_row(cols)
                out.append(row)
            return out

        self.primary = _resized(self.primary)
        if self.alt_grid is not None:
            self.alt_grid = _resized(self.alt_grid)
        self.grid = self.alt_grid if self.alt else self.primary

        self.cols, self.rows = cols, rows
        self.cur_r = min(self.cur_r, rows - 1)
        self.cur_c = min(self.cur_c, cols - 1)
        self.pending_wrap = False
        self.scroll_top, self.scroll_bot = 0, rows - 1
        for k, save in enumerate(self._saves):
            if save is not None:
                self._saves[k] = save._replace(r=min(save.r, rows - 1), c=min(save.c, cols - 1))

        self.v += 1
        self.row_v = [self.v] * rows

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
            self._save_cursor()
            return 2
        if b1 == 0x38:   # '8' DECRC
            self._restore_cursor()
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
            if 0x30 <= b <= 0x3F or 0x20 <= b <= 0x2F or b == 0x00:
                # NUL inside a CSI is IGNORED, exactly as xterm ignores it (B6). Treating it as
                # a stray byte instead ends the sequence early and leaves the real final byte to
                # be printed: `ESC[3<NUL>mB` rendered a literal "m" into the grid -- the only
                # path by which escape residue ever reached cell text. The NUL is stripped from
                # the parameter bytes below so it cannot poison the int() parse either.
                j += 1
                continue
            if 0x40 <= b <= 0x7E:
                final = b
                params_raw = bytes(data[i + 2:j]).replace(b"\x00", b"")
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
        marker = params_raw[:1]
        private = marker in (b"?", b">", b"<", b"=")
        body = params_raw[1:] if private else params_raw
        try:
            text = body.decode("ascii", errors="ignore")
        except Exception:
            text = ""
        params = self._parse_params(text)

        if private:
            if marker == b">" and final == "c":
                # Secondary DA. `vim` asks this on startup and waits for the answer -- see
                # pop_replies. "xterm, patch level 136, no firmware version" is the shape every
                # client already knows how to ignore.
                self._reply(b"\x1b[>0;136;0c")
            elif marker == b"?":
                self._dispatch_private(params, final)
            return

        if final == "c":                       # primary DA -- "VT100 with advanced video"
            if not params or params[0] == 0:
                self._reply(b"\x1b[?1;2c")
            return
        if final == "n":                       # DSR
            self._device_status(params[0] if params else 0)
            return
        if final == "G":                       # CHA -- absolute column
            n = params[0] if params and params[0] else 1
            self.cur_c = min(max(n - 1, 0), self.cols - 1)
            self.pending_wrap = False
            return
        if final == "d":                       # VPA -- absolute row
            n = params[0] if params and params[0] else 1
            self.cur_r = self._abs_row(n - 1)
            self.pending_wrap = False
            return
        if final in ("E", "F"):                # CNL / CPL -- n lines down/up, column 0
            n = params[0] if params and params[0] else 1
            if final == "E":
                self.cur_r = min(self.rows - 1, self.cur_r + n)
            else:
                self.cur_r = max(0, self.cur_r - n)
            self.cur_c = 0
            self.pending_wrap = False
            return
        if final == "@":                       # ICH -- insert blanks, shift the rest right
            self._insert_chars(params[0] if params and params[0] else 1)
            return
        if final == "P":                       # DCH -- delete chars, shift the rest left
            self._delete_chars(params[0] if params and params[0] else 1)
            return
        if final == "X":                       # ECH -- erase in place, no shifting
            self._erase_chars(params[0] if params and params[0] else 1)
            return
        if final in ("L", "M"):                # IL / DL -- inside the scroll region only
            n = params[0] if params and params[0] else 1
            self._insert_lines(n) if final == "L" else self._delete_lines(n)
            return
        if final in ("S", "T"):                # SU / SD -- scroll the region, cursor unmoved
            n = params[0] if params and params[0] else 1
            if self.scroll_top <= self.scroll_bot:
                self._scroll_up(n) if final == "S" else self._scroll_down(n)
            return
        if final == "Z":                       # CBT -- back-tab
            n = params[0] if params and params[0] else 1
            for _ in range(n):
                self.cur_c = max(0, ((self.cur_c - 1) // TAB_STOP) * TAB_STOP)
            self.pending_wrap = False
            return
        if final == "s":                       # ANSI.SYS save cursor (same slot as DECSC)
            self._save_cursor()
            return
        if final == "u":                       # ANSI.SYS restore cursor (same slot as DECRC)
            self._restore_cursor()
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
            self.cur_r = self._abs_row(row - 1)
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
            self._home()
        # any other final byte: no-op, consumed

    def _home(self):
        """Cursor to the home position -- the top of the SCROLL REGION under origin mode."""
        self.cur_r = self.scroll_top if self.origin_mode else 0
        self.cur_c = 0
        self.pending_wrap = False

    def _abs_row(self, row0):
        """Turn a 0-based absolute row parameter (CUP's first, VPA's only) into a grid row.

        Under DECOM (`?6h`) row 1 means the FIRST ROW OF THE SCROLL REGION, not of the screen,
        and the cursor may not be addressed outside that region at all -- which is the whole
        reason a pager can set a region and then address "line 1" without knowing where its
        region starts.
        """
        if self.origin_mode:
            return min(max(self.scroll_top + row0, self.scroll_top), self.scroll_bot)
        return min(max(row0, 0), self.rows - 1)

    def _device_status(self, mode, private=False):
        """DSR: the child asked a question and is BLOCKING on the answer (B7)."""
        if mode == 6:      # CPR -- cursor position report, 1-based, origin-mode relative
            r = self.cur_r - self.scroll_top if self.origin_mode else self.cur_r
            self._reply(b"\x1b[%s%d;%dR" % (b"?" if private else b"", r + 1, self.cur_c + 1))
        elif mode == 5 and not private:
            self._reply(b"\x1b[0n")            # "terminal OK"

    def _dispatch_private(self, params, final):
        if final == "n":                                  # DECDSR, e.g. `ESC[?6n`
            self._device_status(params[0] if params else 0, private=True)
            return
        if final not in ("h", "l"):
            return
        set_ = final == "h"
        for code in params:
            if code == 1049:
                if set_:
                    self._enter_alt()
                else:
                    self._leave_alt()
            elif code == 6:                               # DECOM -- origin mode
                self.origin_mode = set_
                self._home()                              # setting or resetting DECOM homes
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

    # -- insert / delete within one line (ICH, DCH, ECH) ------------------
    #
    # All three shift or fill WITHIN THE CURRENT LINE ONLY -- never across the row boundary --
    # and the cells they vacate are filled with the CURRENTLY ACTIVE SGR, exactly like erase
    # (see the module docstring's "Erase uses the currently-active SGR" section). Filling with a
    # hard default instead would punch unstyled holes into a TUI's coloured status line every
    # time it edits one in place.

    def _insert_chars(self, n):
        r, c = self.cur_r, self.cur_c
        n = min(n, self.cols - c)
        if n <= 0:
            return
        row = self.grid[r]
        blank = (" ", self._cur_code)
        self.grid[r] = row[:c] + [blank] * n + row[c:self.cols - n]
        self._dirty(r)
        self.pending_wrap = False

    def _delete_chars(self, n):
        r, c = self.cur_r, self.cur_c
        n = min(n, self.cols - c)
        if n <= 0:
            return
        row = self.grid[r]
        blank = (" ", self._cur_code)
        self.grid[r] = row[:c] + row[c + n:self.cols] + [blank] * n
        self._dirty(r)
        self.pending_wrap = False

    def _erase_chars(self, n):
        r, c = self.cur_r, self.cur_c
        n = min(n, self.cols - c)
        if n <= 0:
            return
        blank = (" ", self._cur_code)
        row = self.grid[r]
        for k in range(c, c + n):
            row[k] = blank
        self._dirty(r)
        self.pending_wrap = False

    # -- insert / delete whole lines (IL, DL) ------------------------------

    def _insert_lines(self, n):
        """IL: push `n` blank lines in at the cursor row, INSIDE THE SCROLL REGION.

        The region, not the screen, is the boundary that matters: a pager with a fixed status
        line at the bottom sets `DECSTBM` and then inserts lines above it, and an IL that
        shifted the whole screen would push that status line off the end of the world.
        """
        top, bot = self.scroll_top, self.scroll_bot
        r = self.cur_r
        if not (top <= r <= bot):
            return
        n = min(n, bot - r + 1)
        if n <= 0:
            return
        block = self.grid[r:bot + 1]
        self.grid[r:bot + 1] = [_blank_row(self.cols) for _ in range(n)] + block[:len(block) - n]
        for k in range(r, bot + 1):
            self._dirty(k)
        self.cur_c = 0
        self.pending_wrap = False

    def _delete_lines(self, n):
        """DL: drop `n` lines at the cursor row, pulling the rest of the REGION up."""
        top, bot = self.scroll_top, self.scroll_bot
        r = self.cur_r
        if not (top <= r <= bot):
            return
        n = min(n, bot - r + 1)
        if n <= 0:
            return
        block = self.grid[r:bot + 1]
        self.grid[r:bot + 1] = block[n:] + [_blank_row(self.cols) for _ in range(n)]
        for k in range(r, bot + 1):
            self._dirty(k)
        self.cur_c = 0
        self.pending_wrap = False

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

    # -- DECSC / DECRC (and their `CSI s` / `CSI u` aliases) ----------------

    def _attrs(self):
        return (self.bold, self.dim, self.italic, self.underline,
                self.blink, self.reverse, self.strike, self.fg, self.bg)

    def _save_cursor(self):
        self._saves[int(self.alt)] = _Save(self.cur_r, self.cur_c, self._attrs(), self.origin_mode)

    def _restore_cursor(self):
        save = self._saves[int(self.alt)]
        if save is None:
            # DECRC with nothing saved homes the cursor and clears attributes, per DEC.
            self.origin_mode = False
            self._reset_attrs()
            self._recompute_code()
            self._home()
            return
        self.origin_mode = save.origin
        self.cur_r = min(max(save.r, 0), self.rows - 1)
        self.cur_c = min(max(save.c, 0), self.cols - 1)
        (self.bold, self.dim, self.italic, self.underline,
         self.blink, self.reverse, self.strike, self.fg, self.bg) = save.attrs
        self._recompute_code()
        self.pending_wrap = False

    # -- alt screen ----------------------------------------------------------

    def _enter_alt(self):
        """`?1049h` == DECSC, switch to the alternate buffer, clear it.

        The clear is not optional and the buffer must be FRESH: keeping the previous alt grid
        around means the next TUI to start (or the same one restarted) paints on top of the last
        one's leftovers, and every cell it never writes shows the previous program's output --
        which reads as a corrupted screen, not as a stale cache.
        """
        if self.alt:
            return
        self._save_cursor()                                    # into the PRIMARY slot
        self.alt_grid = [_blank_row(self.cols) for _ in range(self.rows)]
        self.grid = self.alt_grid
        self.alt = True
        self.cur_r, self.cur_c = 0, 0
        self.pending_wrap = False
        for r in range(self.rows):
            self._dirty(r)

    def _leave_alt(self):
        """`?1049l` == switch back to the primary buffer, then DECRC.

        DECRC, not "put the cursor back": xterm's 1049 is DEFINED in terms of DECSC/DECRC, so it
        restores the graphic rendition as well. Restoring position alone leaves whatever colour
        the TUI happened to be painting with active over the shell prompt that comes back.
        """
        if not self.alt:
            return
        self.grid = self.primary
        self.alt = False
        self.alt_grid = None                                   # drop it -- see _enter_alt
        self._saves[1] = None                                  # the alt buffer's slot dies with it
        self._restore_cursor()                                 # from the PRIMARY slot
        for r in range(self.rows):
            self._dirty(r)

    # -- RIS full reset --------------------------------------------------

    def _reset(self):
        """`ESC c` -- everything back to power-on state EXCEPT the version counter (B4).

        `self.v` is the diff protocol's clock, and a viewer holding `since=N` asks "what changed
        after N?". Rewinding `v` to 0 makes every row's stamp <= that viewer's `since` forever,
        so it is told "nothing changed" while the grid is being completely repainted underneath
        it -- the one failure the protocol must never produce, and RIS is exactly what a user
        types (`reset`) when the screen already looks wrong. So `v` survives, and every row is
        stamped dirty so a viewer at ANY `since` gets the full repaint.
        """
        cols, rows, v, replies = self.cols, self.rows, self.v, self.pending_replies
        self.__init__(cols, rows)
        self.v = v
        self.pending_replies = replies
        for r in range(rows):
            self._dirty(r)


# ============================================================================================
# Tier 3's PTY session table + the four routes. See the module docstring above ("The PTY routes
# below") for the security stance -- read it before touching anything past this line.
# ============================================================================================

DEFAULT_COLS, DEFAULT_ROWS = 100, 30
MIN_COLS, MAX_COLS = 20, 500
MIN_ROWS, MAX_ROWS = 5, 200

MAX_PTYS = 4            # concurrent shells -- each pins a Screen grid + a reader thread
MAX_STREAMS = 24         # concurrent SSE /api/term/screen connections, across all PTYs -- see
                          # term_run.stream's docstring for the thread-exhaustion measurement this
                          # cap exists to prevent (same ThreadingHTTPServer, same failure mode).
IDLE_TIMEOUT = 1800       # seconds of no keystrokes AND no viewers before a PTY is reaped (30 min)
_REAP_LINGER = 600        # seconds a FINISHED pty's record (its final rc) lingers in PTYS before
                          # being dropped, mirroring term_run._reap_old's 10-minute window.

PTYS = {}                # id -> Pty
_STREAMS = 0              # open SSE connections across all PTYs; guarded by _LOCK
_LOCK = threading.Lock()


def _clamp_int(v, lo, hi, default):
    """`int(v)` clamped to [lo, hi], or `default` if `v` isn't an int-like value at all. Used for
    cols/rows from the client -- never trust a browser-supplied size directly into a struct.pack."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _is_claude(sid):
    """True when `sid` belongs to the unprefixed (Claude) provider.

    Mirrors term_launch._is_claude's logic exactly (registry.PROVIDERS' prefixes are the single
    source of truth for this) but is its own copy rather than a shared import: the three terminal
    tiers are deliberately file-disjoint past Step 0 (docs/terminal-tiers-plan.md Sec 6: "After
    Step 0 there is no shared file between the three tiers"), so this five-line predicate is
    duplicated on purpose rather than becoming the one cross-tier coupling.
    """
    from .registry import PROVIDERS
    for p in PROVIDERS:
        if p.prefix and sid.startswith(p.prefix):
            return False
    return True


def _set_winsize(fd, rows, cols):
    """`TIOCSWINSZ` -- without this a TUI renders at its compiled-in default (usually 80x24)
    forever, no matter how big the browser's pane actually is. Called on create AND on every
    resize (rule 1) -- best effort, exactly like term_run._set_winsize."""
    try:
        import fcntl
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


class Pty:
    """One live (or just-finished) PTY session: the master fd, the child pid, and the `Screen`
    that turns its output into a grid.

    `lock` guards `screen` -- `feed()` (from the reader thread) and `snapshot()` (from a viewer's
    SSE loop) must never run concurrently, since both mutate/read the same grid and version
    counter. Everything else here (`viewers`, `done`, `rc`, `last_active`) is only ever touched
    under the MODULE-level `_LOCK`, exactly like term_run.Job's fields.
    """

    def __init__(self, tid=None, pid=0, fd=-1, screen=None, cwd="", cmd=""):
        self.id = tid or uuid.uuid4().hex[:12]
        self.pid = pid
        self.fd = fd
        self.screen = screen
        self.cwd = cwd
        self.cmd = cmd
        self.viewers = 0           # open SSE /api/term/screen connections; guarded by _LOCK
        self.done = False
        self.rc = None
        self.ended = 0.0           # time.time() when finish() ran; 0.0 while still live
        self.started = time.time()
        self.last_active = self.started   # last keystroke, or last viewer leaving -- idle clock
        self.lock = threading.Lock()      # guards `screen` only

    def touch(self):
        self.last_active = time.time()

    def kill(self):
        """SIGKILL the whole process group, not just `pid`.

        pty.fork() makes the child a session leader, so signalling the bare pid was only ever
        clean by accident (the kernel's own SIGHUP to the foreground group happened to take
        grandchildren down with it). A grandchild that ignores SIGHUP -- an ordinary TUI's worker
        thread/process, a watcher -- survives a bare `kill` and keeps running after the PTY is
        marked dead. See term_run.Job.kill's docstring for the fuller account and
        TestProcessGroupKill below for the reproduction this guards against.
        """
        if self.pid > 0 and not self.done:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                os.kill(self.pid, signal.SIGKILL)     # belt, if getpgid already failed
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def finish(self):
        """Close the master fd and reap the child -- always called from the reader thread, so
        `waitpid()` happens exactly once and nothing is left as a zombie."""
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1
        if self.pid > 0:
            try:
                _, status = os.waitpid(self.pid, 0)
                self.rc = -os.WTERMSIG(status) if os.WIFSIGNALED(status) else os.WEXITSTATUS(status)
            except (ChildProcessError, OSError):
                pass
        self.done = True
        self.ended = time.time()


def spawn(cwd, argv, cols, rows):
    """pty.fork() + execvp in `cwd`, sized to (cols, rows) from the very first ioctl (rule 1).

    No shell anywhere on the "resume" path: argv is `["claude", "--resume", sid]`, executed
    directly by execvp, exactly like term_run's own no-shell policy. The "cwd" (plain shell) path
    IS a shell -- the user's own login shell -- because an interactive terminal that cannot run a
    shell is not a terminal; that is the feature this tier exists to provide, not a gap in it.

    Child setup below mirrors term_run.spawn()'s almost line for line -- see that function's own
    comments for why each piece is there (strip_git_env, PAGER/GIT_EDITOR hardening). The only
    difference: COLUMNS/LINES are set to the REAL negotiated size instead of term_run's fixed
    120x30, since a Screen already tracks the true size and there is no reason to lie to the child
    about it.
    """
    pid, fd = pty.fork()
    if pid == 0:                                        # child
        try:
            os.chdir(cwd or "/")
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLUMNS"] = str(cols)
            os.environ["LINES"] = str(rows)
            # Inherited GIT_* would silently retarget a `git` invocation at another repository --
            # see term_run.strip_git_env's docstring for the concrete failure this closes.
            term_run.strip_git_env(os.environ)
            os.environ["GIT_TERMINAL_PROMPT"] = "0"
            os.execvp(argv[0], argv)                     # <-- the only exec on this path
        except Exception:
            pass
        os._exit(127)                                    # execvp only returns on failure
    _set_winsize(fd, rows, cols)
    screen = Screen(cols=cols, rows=rows)
    pt = Pty(pid=pid, fd=fd, screen=screen, cwd=cwd, cmd=" ".join(argv))
    t = threading.Thread(target=_reader, args=(pt,), daemon=True)
    t.start()
    return pt


def _reader(pt):
    """Drain the pty into `pt.screen` via `feed()` until EOF, or until the idle timeout fires with
    nobody attached. Owns the reap: the thread that reads the fd is the thread that `waitpid()`s
    it, so there is exactly one waitpid per child and never a zombie (mirrors term_run._reader).

    The idle check lives in this loop (rather than a separate timer thread) because `select`'s own
    timeout already wakes this thread once a second regardless of PTY activity -- a second thread
    would be more machinery than the bound is worth, exactly the reasoning term_run._reap_old uses
    for not running a background sweep.
    """
    try:
        while True:
            if pt.viewers <= 0 and (time.time() - pt.last_active) > IDLE_TIMEOUT:
                pt.kill()
                break
            try:
                r, _, _ = select.select([pt.fd], [], [], 1.0)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                data = os.read(pt.fd, 65536)
            except OSError:                              # EIO == child closed the pty (exited)
                break
            if not data:
                break
            with pt.lock:
                pt.screen.feed(data)
                reply = pt.screen.pop_replies()
            if reply:
                # The child asked the terminal a question (`ESC[6n`, `ESC[>c`) and is BLOCKING on
                # the answer -- `vim` sends both while starting up. Screen owns no fd, so this
                # loop is the reply channel; without it the emulator is write-only and a TUI
                # simply hangs. Best effort: a failed write here means the pty is already gone,
                # which the next read reports properly.
                try:
                    os.write(pt.fd, reply)
                except OSError:
                    pass
            pt.touch()
    finally:
        pt.finish()


def _live_count():
    return sum(1 for p in PTYS.values() if not p.done)


def _reap():
    """Drop finished PTYs older than `_REAP_LINGER` so PTYS cannot grow without bound. Called from
    EVERY route, not just `open_pty()` -- see term_run._reap_old's docstring for why an
    open-once-only sweep leaves a pinned record for the life of the process."""
    cut = time.time() - _REAP_LINGER
    for tid in [t.id for t in PTYS.values() if t.done and t.ended < cut]:
        PTYS.pop(tid, None)


def _peer_gone(handler):
    """True once the SSE client has closed its end. See term_run._peer_gone's docstring for why a
    failed write alone is not a reliable detector (the first send after a peer vanishes lands in
    the kernel buffer; only the SECOND write raises) -- same reasoning, same technique, here."""
    try:
        r, _, _ = select.select([handler.connection], [], [], 0)
        return bool(r) and handler.connection.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


def _write(handler, text):
    """One SSE write+flush inside the repo's BrokenPipeError/ConnectionResetError guard
    (conventions rule 8). Returns False once this client is gone."""
    try:
        handler.wfile.write(text.encode())
        handler.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionResetError):
        return False


# --------------------------------------------------------------------------- routes

def open_pty(handler, parsed, body):
    """POST /api/term/pty {session, cols, rows, mode} -> {tty}.

    `mode` follows term_launch's own naming (`"cwd"` = a plain login shell in the session's
    working directory; `"resume"` = `claude --resume <sid>`) so the two buttons this route serves
    stay consistent with Tier 1's. `"resume"` is refused for a non-Claude session id, exactly like
    term_launch.open_terminal -- see `_is_claude`.
    """
    if not term_gate.guard(handler):
        return
    if not isinstance(body, dict):      # do_POST accepts ANY JSON value, "a string" included
        return handler._json({"error": "bad body: expected a JSON object"}, 400)
    sid = body.get("session") or ""
    if not sid:
        return handler._json({"error": "session required"}, 400)
    mode = body.get("mode", "cwd")
    if mode not in ("cwd", "resume"):
        return handler._json({"error": "bad mode"}, 400)
    if mode == "resume" and not _is_claude(sid):
        return handler._json({"error": "resume is Claude-only"}, 400)
    cwd = term_gate.session_cwd(sid)
    if not cwd:
        return handler._json({"error": "session not found or its cwd no longer exists"}, 404)
    with _LOCK:
        _reap()
        if _live_count() >= MAX_PTYS:
            return handler._json({"error": "too many running terminals (max %d)" % MAX_PTYS}, 429)
    cols = _clamp_int(body.get("cols"), MIN_COLS, MAX_COLS, DEFAULT_COLS)
    rows = _clamp_int(body.get("rows"), MIN_ROWS, MAX_ROWS, DEFAULT_ROWS)
    if mode == "resume":
        argv = ["claude", "--resume", sid]
    else:
        argv = [os.environ.get("SHELL", "/bin/bash"), "-l"]
    try:
        pt = spawn(cwd, argv, cols, rows)
    except OSError as e:
        return handler._json({"error": "spawn failed: %s" % e}, 500)
    with _LOCK:
        PTYS[pt.id] = pt
    handler._json({"tty": pt.id})


def keys(handler, parsed, body):
    """POST /api/term/keys {tty, data} (data: base64) -> {ok: true}.

    Writes raw bytes to the PTY's stdin -- this IS the "unrestricted shell" surface described in
    the module docstring: whatever bytes arrive here are typed at a real shell (or `claude
    --resume`) as this server's own OS user, with no allowlist and no interpretation.
    """
    if not term_gate.guard(handler):
        return
    if not isinstance(body, dict):
        return handler._json({"error": "bad body: expected a JSON object"}, 400)
    tid = body.get("tty") or ""
    with _LOCK:
        _reap()
        pt = PTYS.get(tid)
    if pt is None or pt.done:
        return handler._json({"error": "no such terminal"}, 404)
    try:
        data = base64.b64decode(body.get("data") or "", validate=False)
    except Exception:
        return handler._json({"error": "bad base64"}, 400)
    pt.touch()
    try:
        os.write(pt.fd, data)
    except OSError as e:
        return handler._json({"error": "write failed: %s" % e}, 500)
    handler._json({"ok": True})


def resize_pty(handler, parsed, body):
    """POST /api/term/resize {tty, cols, rows} -> {ok: true}.

    Rule 1: `TIOCSWINSZ` on the real pty AND a matching `Screen.resize()` -- without both, either
    the child's own idea of the terminal size never changes (it keeps wrapping at whatever size it
    started at), or the Screen's grid silently disagrees with what the pty is actually producing.
    """
    if not term_gate.guard(handler):
        return
    if not isinstance(body, dict):
        return handler._json({"error": "bad body: expected a JSON object"}, 400)
    tid = body.get("tty") or ""
    with _LOCK:
        _reap()
        pt = PTYS.get(tid)
    if pt is None or pt.done:
        return handler._json({"error": "no such terminal"}, 404)
    cols = _clamp_int(body.get("cols"), MIN_COLS, MAX_COLS, pt.screen.cols)
    rows = _clamp_int(body.get("rows"), MIN_ROWS, MAX_ROWS, pt.screen.rows)
    pt.touch()
    _set_winsize(pt.fd, rows, cols)
    with pt.lock:
        pt.screen.resize(cols, rows)
    handler._json({"ok": True})


def screen_stream(handler, parsed):
    """GET /api/term/screen?tty=<id> -> SSE of `Screen.snapshot(since)` payloads, one connection
    per viewer.

    Two accounting jobs happen here, both under `_LOCK`, mirroring term_run.stream()'s almost
    exactly -- see that function's docstring for the thread-exhaustion measurement `MAX_STREAMS`
    prevents (unbounded SSE connections each pin a ThreadingHTTPServer thread; enough of them and
    the whole dashboard, not just this panel, stops answering ANY request) and for the
    premature-teardown bug the per-PTY viewer refcount fixes (closing one of two open tabs on the
    same session must not cut the other one off).

    The one deliberate difference from Tier 2: `term_run.stream()` kills its job the instant the
    LAST viewer disconnects, because a finished one-shot command has nothing left to show anyone.
    A PTY here is a persistent shell -- the whole point of `tty` being a stable id the client can
    reattach to is that closing every tab and coming back later finds the SAME session still
    running -- so the last viewer leaving only calls `pt.touch()`, starting the `IDLE_TIMEOUT`
    clock, rather than killing anything. `_reader()` is what actually reaps an abandoned PTY.
    """
    global _STREAMS
    if not term_gate.guard(handler):
        return
    from urllib.parse import parse_qs
    tid = parse_qs(parsed.query).get("tty", [""])[0]
    with _LOCK:
        _reap()
        pt = PTYS.get(tid)
        busy = pt is not None and _STREAMS >= MAX_STREAMS
        if pt is not None and not busy:
            _STREAMS += 1
            pt.viewers += 1
            pt.touch()
    if pt is None:                                       # returns fast, holds no thread
        return handler._json({"error": "no such terminal", "tty": tid}, 404)
    if busy:
        return handler._json({"error": "too many open screen streams (max %d)" % MAX_STREAMS}, 429)
    try:
        _screen_stream_body(handler, pt)
    finally:
        with _LOCK:
            _STREAMS -= 1
            pt.viewers -= 1
            pt.touch()                                   # last-viewer-leaves starts the idle clock


def _screen_stream_body(handler, pt):
    """The SSE loop itself. Polls Screen state under `pt.lock` (`feed()` from the reader thread
    and `snapshot()` from here must never run concurrently) and sends only what changed since the
    last send -- rule 3, never a whole grid except the very first message (`since=-1`, per
    `Screen.snapshot`'s own documented contract). A poll that produced no new rows but a moved
    cursor (e.g. arrow-key navigation with nothing printed) still counts as a change: the cursor
    and `alt` fields are always current in `snapshot()`'s output regardless of `since`, so this
    loop tracks them itself to decide whether there is anything worth sending.

    The wire format is FIXED by the already-built, already-committed client and must not drift:

    * Every data frame is a PLAIN, UNNAMED `data: <json>\\n\\n` line -- never `event: <name>`.
      The client's `EventSource.onmessage` only fires for unnamed events; one named `event:`
      frame and the terminal goes permanently, silently dark. (Tier 2's `term_run.stream()` right
      next door DOES send `event: end` -- that pattern is Tier 2-only, deliberately not mirrored
      here.) The `: ping\\n\\n` heartbeat is a comment line, not a `data:`/`event:` frame, so
      EventSource ignores it for free -- that one is safe as-is.
    * The JSON object carries EXACTLY the four keys `Screen.snapshot()` returns -- `v`, `rows`,
      `cursor`, `alt` -- verbatim, unpadded. No wrapping, no extra keys, ever.
    * `since` is a LOCAL variable of this call, i.e. per-viewer: two viewers on the same `tty`
      (the deliberately-supported "New tab, same session" case) each start their own SSE
      connection, each running its own `_screen_stream_body()`, each with its own `since = -1` --
      so each gets its own full repaint on attach, and neither one's progress starves the other's.
    * There is no special "the PTY ended" frame. If the PTY's last output changed the grid, that
      change is sent as an ordinary data frame in the same iteration `done` is observed (the
      snapshot and the done/rc flags are read together under one lock, so nothing after the last
      byte is ever lost) -- then the loop just returns and the SSE connection closes. A client
      that wants to know "did the shell exit" reads that from the connection closing, not from a
      distinguished payload shape.

    Returns on client disconnect or once the PTY has finished; the caller owns the stream slot and
    the viewer refcount, so this never kills anything and never mutates PTYS.
    """
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")       # no Content-Length: body is open-ended
        handler.end_headers()
    except (BrokenPipeError, ConnectionResetError):
        return
    since = -1
    last_cursor, last_alt = None, None
    quiet = time.time()
    while True:
        with pt.lock:
            snap = pt.screen.snapshot(since)
            done = pt.done
        cursor = tuple(snap["cursor"])
        changed = snap["rows"] or since == -1 or cursor != last_cursor or snap["alt"] != last_alt
        if changed:
            since = snap["v"]
            last_cursor, last_alt = cursor, snap["alt"]
            if not _write(handler, "data: %s\n\n" % json.dumps(snap)):
                return
            quiet = time.time()
        if done:
            return
        if _peer_gone(handler):                          # instant: the tab closed
            return
        if time.time() - quiet > 10:                     # heartbeat: keeps proxies from idling us
            quiet = time.time()
            if not _write(handler, ": ping\n\n"):
                return
        time.sleep(0.05)


server.EXTRA_POST["/api/term/pty"] = open_pty
server.EXTRA_POST["/api/term/keys"] = keys
server.EXTRA_POST["/api/term/resize"] = resize_pty
server.EXTRA_GET["/api/term/screen"] = screen_stream
