"""Tests for aitracker.term_vt.Screen -- the pure VT100/xterm emulator for Tier 3.

Every assertion here is pure: bytes in, grid out, no PTY, no server, no browser. Split-feed
correctness (an escape sequence or a UTF-8 character arriving across two feed() calls) is the
single most likely real-world bug, so it gets its own dedicated section.
"""
import base64
import json
import os
import threading
import time
import unittest

from aitracker import config, term_gate, term_vt
from aitracker.term_vt import Screen


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _rows(snap):
    return {r[0]: r for r in snap["rows"]}


def _txt(s, r):
    """The row's text straight off the grid, right-trimmed. Deliberately NOT via snapshot():
    these assertions are about what a painter would draw, not about the diff protocol."""
    return "".join(c[0] for c in s.grid[r]).rstrip()


def _grid(s):
    return [_txt(s, r) for r in range(s.rows)]


def _codes(s, r):
    return [c[1] for c in s.grid[r]]


def _capture(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


class TestBasicText(unittest.TestCase):
    def test_simple_text_and_cursor(self):
        s = Screen(cols=20, rows=5)
        s.feed(b"abc")
        snap = s.snapshot(-1)
        rows = _rows(snap)
        self.assertEqual(rows[0][1], "abc")
        self.assertEqual(snap["cursor"], [0, 3])

    def test_cr_lf_bs(self):
        s = Screen(cols=20, rows=5)
        s.feed(b"hello")
        self.assertEqual((s.cur_r, s.cur_c), (0, 5))
        s.feed(b"\x08\x08")           # BS BS -> col 3
        self.assertEqual(s.cur_c, 3)
        s.feed(b"WO")                 # overwrite l,o -> "helWO"
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "helWO")
        s.feed(b"\r\n")                # CR then LF -> row 1, col 0
        self.assertEqual((s.cur_r, s.cur_c), (1, 0))
        s.feed(b"X")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[1][1], "X")

    def test_tabs(self):
        s = Screen(cols=20, rows=3)
        s.feed(b"a\tb")
        # 'a' at col0 -> cursor 1; TAB -> next stop of 8 -> col8; 'b' at col8 -> cursor 9
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1][0], "a")
        self.assertEqual(rows[0][1][8], "b")
        self.assertEqual(s.cur_c, 9)

    def test_lf_alone_does_not_carriage_return(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"ab\n")   # bare LF: down one row, column unchanged (real VT100 semantics)
        self.assertEqual((s.cur_r, s.cur_c), (1, 2))


class TestCursorMoves(unittest.TestCase):
    def test_cup_and_clear(self):
        s = Screen(cols=20, rows=8)
        s.feed(b"\x1b[2J\x1b[5;10Hx")
        snap = s.snapshot(-1)
        rows = _rows(snap)
        self.assertEqual(rows[4][1][9], "x")
        # every other visible cell on that row is still default blank
        self.assertEqual(rows[4][1][:9], " " * 9)
        # no other row has any non-blank content
        for r, entry in rows.items():
            if r != 4:
                self.assertEqual(entry[1], "")

    def test_cuu_cud_cuf_cub(self):
        s = Screen(cols=20, rows=10)
        s.feed(b"\x1b[5;5H")           # row4,col4 (0-based)
        s.feed(b"\x1b[2A")              # up 2 -> row2
        self.assertEqual(s.cur_r, 2)
        s.feed(b"\x1b[3B")              # down 3 -> row5
        self.assertEqual(s.cur_r, 5)
        s.feed(b"\x1b[2C")              # right 2 -> col6
        self.assertEqual(s.cur_c, 6)
        s.feed(b"\x1b[4D")              # left 4 -> col2
        self.assertEqual(s.cur_c, 2)

    def test_cursor_clamped_to_screen(self):
        s = Screen(cols=10, rows=5)
        s.feed(b"\x1b[100;100H")
        self.assertEqual((s.cur_r, s.cur_c), (4, 9))
        s.feed(b"\x1b[100A")
        self.assertEqual(s.cur_r, 0)


class TestErase(unittest.TestCase):
    def test_el_variants(self):
        s = Screen(cols=10, rows=2)
        s.feed(b"0123456789")
        s.feed(b"\x1b[1;6H\x1b[0K")   # from col5 to end of line
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "01234")

        s2 = Screen(cols=10, rows=2)
        s2.feed(b"0123456789")
        s2.feed(b"\x1b[1;6H\x1b[1K")  # from start to col5 inclusive
        rows2 = _rows(s2.snapshot(-1))
        self.assertEqual(rows2[0][1][:6], " " * 6)
        self.assertEqual(rows2[0][1][6:], "6789")

        s3 = Screen(cols=10, rows=2)
        s3.feed(b"0123456789")
        s3.feed(b"\x1b[1;6H\x1b[2K")  # whole line
        rows3 = _rows(s3.snapshot(-1))
        self.assertEqual(rows3.get(0, [0, "", []])[1], "")

    def test_ed_variants(self):
        s = Screen(cols=5, rows=3)
        s.feed(b"\x1b[1;1HAAAAA\x1b[2;1HBBBBB\x1b[3;1HCCCCC")
        s.feed(b"\x1b[2;3H\x1b[0J")   # cursor to end of screen
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "AAAAA")
        self.assertEqual(rows[1][1], "BB")
        self.assertEqual(rows.get(2, [2, "", []])[1], "")

        s2 = Screen(cols=5, rows=3)
        s2.feed(b"\x1b[1;1HAAAAA\x1b[2;1HBBBBB\x1b[3;1HCCCCC")
        s2.feed(b"\x1b[2;3H\x1b[1J")  # start of screen to cursor
        rows2 = _rows(s2.snapshot(-1))
        self.assertEqual(rows2.get(0, [0, "", []])[1], "")
        self.assertEqual(rows2[1][1][:3], "   ")
        self.assertEqual(rows2[1][1][3:], "BB")
        self.assertEqual(rows2[2][1], "CCCCC")


class TestEraseUsesActiveSgr(unittest.TestCase):
    def test_erase_paints_with_current_background(self):
        s = Screen(cols=10, rows=2)
        s.feed(b"\x1b[44m")     # blue background
        s.feed(b"\x1b[2K")       # erase whole current line under that background
        rows = _rows(s.snapshot(-1))
        # trailing default blanks are normally trimmed to "" -- but these carry a background,
        # so the row must report a run covering the full width, not an empty run list.
        self.assertEqual(rows[0][1], " " * 10)
        self.assertEqual(rows[0][2], [[0, 10, "44"]])


class TestSGR(unittest.TestCase):
    def test_color_carries_and_resets(self):
        s = Screen(cols=20, rows=3)
        s.feed(b"\x1b[31mR\x1b[0mN")
        rows = _rows(s.snapshot(-1))
        text, runs = rows[0][1], rows[0][2]
        self.assertEqual(text, "RN")
        self.assertEqual(runs, [[0, 1, "31"]])   # only R is styled; N carries no run

    def test_bold_and_reverse_combine(self):
        s = Screen(cols=20, rows=3)
        s.feed(b"\x1b[1;7mX")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][2], [[0, 1, "1;7"]])

    def test_256_and_truecolor(self):
        s = Screen(cols=20, rows=3)
        s.feed(b"\x1b[38;5;208mA\x1b[0m\x1b[48;2;10;20;30mB")
        rows = _rows(s.snapshot(-1))
        runs = {tuple(r[:2]): r[2] for r in [rows[0]]}
        text, runlist = rows[0][1], rows[0][2]
        self.assertEqual(text, "AB")
        self.assertEqual(runlist, [[0, 1, "38;5;208"], [1, 2, "48;2;10;20;30"]])

    def test_truncated_extended_color_is_noop_not_leaked_attribute(self):
        # A truncated "38;5" (no palette index) or "38;2" (no RGB) must never fall through and
        # have its leftover numeric sub-param reinterpreted as an ordinary SGR code -- 5 is
        # blink, 2 is dim. This used to leak: \x1b[38;5m turned blink on.
        for seq, attr in ((b"\x1b[38;5mX", "blink"), (b"\x1b[48;5mY", "blink"),
                           (b"\x1b[38;2mX", "dim"), (b"\x1b[48;2mY", "dim")):
            s = Screen(cols=10, rows=2)
            s.feed(seq)
            self.assertFalse(getattr(s, attr), "sequence %r leaked into %s" % (seq, attr))
            self.assertIsNone(s.fg)
            self.assertIsNone(s.bg)
            rows = _rows(s.snapshot(-1))
            self.assertEqual(rows[0][2], [])   # no spurious run at all

        # a partially-given truecolor (only 1 of 3 components) must also be fully swallowed
        s2 = Screen(cols=10, rows=2)
        s2.feed(b"\x1b[38;2;10mZ")
        self.assertIsNone(s2.fg)
        self.assertFalse(s2.dim)
        rows2 = _rows(s2.snapshot(-1))
        self.assertEqual(rows2[0][2], [])

        # a bare "38" (nothing following) must also be a clean no-op
        s3 = Screen(cols=10, rows=2)
        s3.feed(b"\x1b[38mZ")
        self.assertIsNone(s3.fg)
        rows3 = _rows(s3.snapshot(-1))
        self.assertEqual(rows3[0][2], [])

        # a valid extended color followed by a real attribute still works (the good path is
        # not collateral damage from the truncated-path fix)
        s4 = Screen(cols=10, rows=2)
        s4.feed(b"\x1b[38;5;208;1mZ")
        self.assertEqual(s4.fg, "38;5;208")
        self.assertTrue(s4.bold)


class TestAltScreen(unittest.TestCase):
    def test_primary_preserved_across_alt(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"primary1")
        self.assertFalse(s.alt)
        s.feed(b"\x1b[?1049h")
        self.assertTrue(s.alt)
        s.feed(b"\x1b[1;1HALTBUF")
        rows_alt = _rows(s.snapshot(-1))
        self.assertEqual(rows_alt[0][1], "ALTBUF")

        s.feed(b"\x1b[?1049l")
        self.assertFalse(s.alt)
        rows_primary = _rows(s.snapshot(-1))
        self.assertEqual(rows_primary[0][1], "primary1")


class TestScrollRegion(unittest.TestCase):
    def test_only_region_rows_scroll(self):
        s = Screen(cols=10, rows=6)
        for r in range(6):
            s.feed(("\x1b[%d;1H%s" % (r + 1, chr(ord("A") + r))).encode())
        s.feed(b"\x1b[2;5r")     # region = rows 1..4 (0-based)
        s.feed(b"\x1b[5;1H")     # cursor to row4 (0-based) = scroll_bot
        s.feed(b"\n\n\n")        # three scroll-ups
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows.get(0, [0, "A", []])[1], "A")     # untouched, above region
        self.assertEqual(rows.get(5, [5, "F", []])[1], "F")     # untouched, below region
        self.assertEqual(rows[1][1], "E")                        # shifted up 3: B,C,D,E -> E
        self.assertEqual(rows.get(2, [2, "", []])[1], "")
        self.assertEqual(rows.get(3, [3, "", []])[1], "")
        self.assertEqual(rows.get(4, [4, "", []])[1], "")

    def test_reverse_index_scrolls_down_at_top(self):
        s = Screen(cols=5, rows=4)
        s.feed(b"\x1b[1;1HAAAAA\x1b[2;1HBBBBB\x1b[3;1HCCCCC\x1b[4;1HDDDDD")
        s.feed(b"\x1b[2;3r")      # region rows 1..2 (0-based)
        s.feed(b"\x1b[2;1H")       # cursor to row1 = scroll_top
        s.feed(b"\x1bM")           # RI -> scroll region down
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "AAAAA")   # unaffected
        self.assertEqual(rows.get(1, [1, "", []])[1], "")   # blank inserted at top of region
        self.assertEqual(rows[2][1], "BBBBB")   # shifted down
        self.assertEqual(rows[3][1], "DDDDD")   # unaffected


class TestAutowrap(unittest.TestCase):
    def test_wraps_at_right_margin(self):
        s = Screen(cols=5, rows=3)
        s.feed(b"ABCDE")
        self.assertEqual((s.cur_r, s.cur_c), (0, 4))
        self.assertTrue(s.pending_wrap)
        s.feed(b"F")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "ABCDE")
        self.assertEqual(rows[1][1], "F")
        self.assertEqual((s.cur_r, s.cur_c), (1, 1))

    def test_no_wrap_when_decawm_off(self):
        s = Screen(cols=5, rows=3)
        s.feed(b"\x1b[?7l")
        s.feed(b"ABCDEF")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "ABCDF")   # F overwrote E at the last column
        self.assertEqual(s.cur_r, 0)             # never moved to row 1


class TestCursorVisibility(unittest.TestCase):
    def test_dectcem(self):
        s = Screen(cols=10, rows=3)
        self.assertTrue(s.cursor_visible)
        s.feed(b"\x1b[?25l")
        self.assertFalse(s.cursor_visible)
        s.feed(b"\x1b[?25h")
        self.assertTrue(s.cursor_visible)


class TestSnapshotScreenStateFields(unittest.TestCase):
    """`cursor_visible`, `bracketed_paste` and `bell` -- the parity-integration gap: the client
    (`ext_vt.js`) already reads these three off every SSE snapshot; this class pins that the
    server actually puts them there, and that a bell/mode change alone never bumps `v` (that
    counter is reserved for row content -- see the module docstring's "`v` is monotonic")."""

    def test_dectcem_flows_into_snapshot(self):
        s = Screen(cols=10, rows=3)
        self.assertTrue(s.snapshot(-1)["cursor_visible"])
        s.feed(b"\x1b[?25l")
        self.assertFalse(s.snapshot(-1)["cursor_visible"])
        s.feed(b"\x1b[?25h")
        self.assertTrue(s.snapshot(-1)["cursor_visible"])

    def test_bracketed_paste_flips_in_snapshot(self):
        s = Screen(cols=10, rows=3)
        self.assertFalse(s.snapshot(-1)["bracketed_paste"])
        s.feed(b"\x1b[?2004h")
        self.assertTrue(s.snapshot(-1)["bracketed_paste"])
        s.feed(b"\x1b[?2004l")
        self.assertFalse(s.snapshot(-1)["bracketed_paste"])

    def test_bell_increments_and_holds_steady_between_bells(self):
        s = Screen(cols=10, rows=3)
        self.assertEqual(s.snapshot(-1)["bell"], 0)
        s.feed(b"\x07")
        self.assertEqual(s.snapshot(-1)["bell"], 1)
        # a snapshot with no bell fed in between must not change the count
        self.assertEqual(s.snapshot(-1)["bell"], 1)
        s.feed(b"\x07\x07\x07")
        self.assertEqual(s.snapshot(-1)["bell"], 4)

    def test_bell_survives_alt_screen_round_trip(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"\x07\x07")
        self.assertEqual(s.bell, 2)
        s.feed(b"\x1b[?1049h")   # enter alt
        self.assertEqual(s.bell, 2)
        s.feed(b"\x07")
        self.assertEqual(s.bell, 3)
        s.feed(b"\x1b[?1049l")   # leave alt -- must not reset the counter
        self.assertEqual(s.bell, 3)

    def test_bell_survives_ris(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"\x07\x07")
        self.assertEqual(s.bell, 2)
        s.feed(b"\x1bc")         # RIS -- bell is a client-event stream, not screen state
        self.assertEqual(s.bell, 2)
        s.feed(b"\x07")
        self.assertEqual(s.bell, 3)

    def test_ris_resets_cursor_visible_and_bracketed_paste(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"\x1b[?25l\x1b[?2004h")
        self.assertFalse(s.cursor_visible)
        self.assertTrue(s.bracketed_paste)
        s.feed(b"\x1bc")
        self.assertTrue(s.cursor_visible)
        self.assertFalse(s.bracketed_paste)

    def test_bell_alone_does_not_bump_v(self):
        s = Screen(cols=10, rows=3)
        v1 = s.v
        s.feed(b"\x07\x07\x07")
        self.assertEqual(s.v, v1)

    def test_dectcem_toggle_alone_does_not_bump_v(self):
        s = Screen(cols=10, rows=3)
        v1 = s.v
        s.feed(b"\x1b[?25l")
        self.assertEqual(s.v, v1)
        s.feed(b"\x1b[?25h")
        self.assertEqual(s.v, v1)

    def test_bracketed_paste_toggle_alone_does_not_bump_v(self):
        s = Screen(cols=10, rows=3)
        v1 = s.v
        s.feed(b"\x1b[?2004h")
        self.assertEqual(s.v, v1)
        s.feed(b"\x1b[?2004l")
        self.assertEqual(s.v, v1)


class TestSnapshotVersioning(unittest.TestCase):
    def test_only_changed_rows_returned_and_v_bumps(self):
        s = Screen(cols=20, rows=5)
        s.feed(b"abc")
        snap1 = s.snapshot(-1)
        v1 = snap1["v"]
        self.assertTrue(v1 > 0)

        s.feed(b"\x1b[3;1Hxyz")   # only row 2 (0-based) touched
        snap2 = s.snapshot(v1)
        self.assertEqual(len(snap2["rows"]), 1)
        self.assertEqual(snap2["rows"][0][0], 2)
        self.assertGreater(snap2["v"], v1)

        # nothing changed since the latest v -> empty rows, cursor/alt still present
        snap3 = s.snapshot(snap2["v"])
        self.assertEqual(snap3["rows"], [])
        self.assertIn("cursor", snap3)
        self.assertIn("alt", snap3)

    def test_pure_cursor_move_does_not_bump_v(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"hi")
        v1 = s.v
        s.feed(b"\x1b[1;1H")   # cursor move only, no grid write
        self.assertEqual(s.v, v1)


class TestSplitFeeds(unittest.TestCase):
    def test_csi_split_across_calls(self):
        s = Screen(cols=20, rows=5)
        s.feed(b"\x1b[3")
        s.feed(b"1mR")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][2], [[0, 1, "31"]])

    def test_csi_split_right_after_esc(self):
        s = Screen(cols=20, rows=5)
        s.feed(b"\x1b")
        s.feed(b"[5;10Hx")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[4][1][9], "x")

    def test_utf8_multibyte_split_across_calls(self):
        s = Screen(cols=20, rows=3)
        chunk = "café".encode("utf-8")   # 'é' is 2 bytes: 0xc3 0xa9
        split_at = len("caf".encode("utf-8")) + 1  # split inside the 2-byte char
        s.feed(chunk[:split_at])
        s.feed(chunk[split_at:])
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "café")

    def test_osc_terminator_split_across_calls(self):
        s = Screen(cols=20, rows=3)
        s.feed(b"\x1b]0;hello")
        s.feed(b"\x07AFTER")
        self.assertEqual(s.title, "hello")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "AFTER")


class TestResize(unittest.TestCase):
    """Screen.resize -- the Screen-side half of Tier 3's TIOCSWINSZ rule."""

    def test_grow_pads_and_shrink_crops(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"abcdefghij")            # fills row 0 exactly
        s.resize(20, 3)
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "abcdefghij")   # preserved, not corrupted by the grow
        self.assertEqual(s.cols, 20)
        s.resize(5, 3)
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "abcde")         # cropped to the new width, not wrapped

    def test_row_count_changes(self):
        s = Screen(cols=10, rows=5)
        s.feed(b"row0\r\nrow1\r\nrow2")
        s.resize(10, 2)                   # shrink rows: row 2 is gone
        self.assertEqual(s.rows, 2)
        snap = s.snapshot(-1)
        self.assertEqual(len(snap["rows"]), 2)
        s.resize(10, 5)                   # grow back: new rows are blank, not garbage
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[2][1], "")
        self.assertEqual(rows[2][2], [])

    def test_cursor_and_scroll_region_clamped(self):
        s = Screen(cols=20, rows=10)
        s.feed(b"\x1b[3;8r")              # scroll region rows 3-8
        s.feed(b"\x1b[9;15H")             # cursor at row 9 (0-based 8), col 15 (0-based 14)
        s.resize(10, 5)
        self.assertLess(s.cur_r, 5)
        self.assertLess(s.cur_c, 10)
        self.assertEqual((s.scroll_top, s.scroll_bot), (0, 4))

    def test_resize_forces_full_redraw_on_next_snapshot(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"hi")
        v0 = s.snapshot(-1)["v"]
        snap_before = s.snapshot(v0)
        self.assertEqual(snap_before["rows"], [])     # nothing changed since v0 yet
        s.resize(20, 3)
        snap_after = s.snapshot(v0)
        self.assertEqual(len(snap_after["rows"]), 3)  # every row redrawn, not just the resized one

    def test_noop_when_dimensions_unchanged(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"x")
        v0 = s.v
        s.resize(10, 3)
        self.assertEqual(s.v, v0)          # no spurious version bump / dirty-all


class TestOutOfScopeConsumed(unittest.TestCase):
    def test_mouse_reporting_modes_are_noop(self):
        s = Screen(cols=20, rows=3)
        s.feed(b"\x1b[?1000h\x1b[?1002h\x1b[?1006habc\x1b[?1000l\x1b[?1006ldef")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "abcdef")

    def test_bracketed_paste_is_noop(self):
        s = Screen(cols=20, rows=3)
        s.feed(b"\x1b[?2004hpasted\x1b[?2004l")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "pasted")

    def test_sixel_dcs_consumed_without_corrupting_stream(self):
        s = Screen(cols=20, rows=3)
        # DCS ... ST, with a payload full of bytes that could look like other sequences
        payload = b"q\"1;1;100;100#0;2;0;0;0#0!100~~\x1b[31m"
        s.feed(b"\x1bP" + payload + b"\x1b\\AFTER")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "AFTER")
        self.assertEqual(rows[0][2], [])   # the fake "\x1b[31m" inside the DCS body must NOT apply

    def test_osc_beyond_title_discarded(self):
        s = Screen(cols=20, rows=3)
        s.feed(b"\x1b]52;c;bm9pc2U=\x07AFTER")
        rows = _rows(s.snapshot(-1))
        self.assertEqual(rows[0][1], "AFTER")
        self.assertEqual(s.title, "")   # unrelated OSC must not clobber title

    def test_title_set_osc0_and_osc2(self):
        s = Screen(cols=20, rows=3)
        s.feed(b"\x1b]0;window title\x07")
        self.assertEqual(s.title, "window title")
        s.feed(b"\x1b]2;icon title\x1b\\")
        self.assertEqual(s.title, "icon title")


class _FakeHeaders:
    def __init__(self, headers=None):
        self._h = dict(headers or {})

    def get(self, key, default=""):
        return self._h.get(key, default)


class _FakeHandler:
    """Stands in for the real Handler: records the one _json() call a route makes."""

    def __init__(self, headers=None):
        self.headers = _FakeHeaders(headers)
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


class _Q:
    """Stands in for urlparse's result -- only `.query` is used by screen_stream."""

    def __init__(self, q):
        self.query = q


def _drain(pt, timeout=10.0):
    """Wait for the reader thread to finish the PTY (it owns the waitpid)."""
    end = time.time() + timeout
    while not pt.done and time.time() < end:
        time.sleep(0.02)
    return pt


def _wait_for(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


class TestClampAndIsClaude(unittest.TestCase):
    def test_clamp_int_within_bounds(self):
        self.assertEqual(term_vt._clamp_int(80, 20, 500, 100), 80)

    def test_clamp_int_clamps_out_of_range(self):
        self.assertEqual(term_vt._clamp_int(5, 20, 500, 100), 20)
        self.assertEqual(term_vt._clamp_int(99999, 20, 500, 100), 500)

    def test_clamp_int_falls_back_on_garbage(self):
        self.assertEqual(term_vt._clamp_int("nope", 20, 500, 100), 100)
        self.assertEqual(term_vt._clamp_int(None, 20, 500, 100), 100)

    def test_is_claude_true_for_unprefixed_id(self):
        self.assertTrue(term_vt._is_claude("170670c5-f8c1-4ac9-90aa-a1706021166a"))

    def test_is_claude_false_for_a_provider_prefix(self):
        from aitracker.registry import PROVIDERS
        prefixed = [p for p in PROVIDERS if p.prefix]
        if not prefixed:
            self.skipTest("no prefixed provider registered")
        self.assertFalse(term_vt._is_claude(prefixed[0].prefix + "some-id"))


class TestSpawnAndScreen(unittest.TestCase):
    """Real pty.fork() + a real Screen -- the feasibility spike for Tier 3's plumbing."""

    def setUp(self):
        self._ptys = []
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"        # test_..._keys_route goes through guard()

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        for pt in self._ptys:
            pt.kill()
            _drain(pt, 5)

    def _spawn(self, argv, cwd=None, cols=80, rows=24):
        pt = term_vt.spawn(cwd or os.getcwd(), argv, cols, rows)
        self._ptys.append(pt)
        return pt

    def test_spawn_feed_keys_snapshot_shows_the_echo(self):
        """THE load-bearing one: a real shell, real keystrokes written through the `keys` route,
        and the resulting output showing up in Screen.snapshot() -- proving the pty -> reader
        thread -> Screen.feed() -> snapshot() pipeline actually works end to end."""
        shell = os.environ.get("SHELL", "/bin/bash")
        pt = self._spawn([shell, "-l"])
        term_vt.PTYS[pt.id] = pt
        h = _FakeHandler()
        payload = base64.b64encode(b"echo hi-from-tier3\n").decode()
        term_vt.keys(h, None, {"tty": pt.id, "data": payload})
        self.assertEqual(h.calls[-1], ({"ok": True}, 200))

        def seen():
            with pt.lock:
                snap = pt.screen.snapshot(-1)
            return any("hi-from-tier3" in r[1] for r in snap["rows"])

        self.assertTrue(_wait_for(seen, 10), "echo never showed up in the Screen snapshot")
        del term_vt.PTYS[pt.id]

    def test_resize_applies_tiocswinsz_and_the_screen(self):
        pt = self._spawn(["cat"])
        self.assertEqual((pt.screen.cols, pt.screen.rows), (80, 24))
        term_vt._set_winsize(pt.fd, 40, 120)
        with pt.lock:
            pt.screen.resize(120, 40)
        self.assertEqual((pt.screen.cols, pt.screen.rows), (120, 40))
        import fcntl
        import struct as _struct
        import termios
        packed = fcntl.ioctl(pt.fd, termios.TIOCGWINSZ, _struct.pack("HHHH", 0, 0, 0, 0))
        got_rows, got_cols = _struct.unpack("HHHH", packed)[:2]
        self.assertEqual((got_rows, got_cols), (40, 120))

    def test_no_zombie_left_behind(self):
        pt = self._spawn(["echo", "bye"])
        _drain(pt)
        self.assertIsNotNone(pt.rc)            # the reader thread reaped it
        with self.assertRaises(ChildProcessError):
            os.waitpid(pt.pid, 0)              # a second waitpid finds nothing

    def test_kill_stops_a_running_child(self):
        pt = self._spawn(["sleep", "30"])
        time.sleep(0.3)
        pt.kill()
        _drain(pt)
        self.assertTrue(pt.done)
        self.assertEqual(pt.rc, -9)            # SIGKILL, reported as a negative signal number


class TestProcessGroupKill(unittest.TestCase):
    def test_kill_reaches_a_grandchild_that_ignores_sighup(self):
        """Signalling one pid was clean only by ACCIDENT -- see Pty.kill's docstring. A grandchild
        that ignores SIGHUP (an ordinary TUI worker/watcher) survives a bare `kill` and keeps
        running after the PTY is marked dead; killpg reaches the whole process group."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            pidfile = os.path.join(td, "grandchild.pid")
            script = os.path.join(td, "escaper.py")
            with open(script, "w") as f:
                f.write(
                    "import os, signal, sys, time\n"
                    "if os.fork() == 0:\n"
                    "    signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
                    "    open(%r, 'w').write(str(os.getpid()))\n"
                    "    time.sleep(60)\n"
                    "    os._exit(0)\n"
                    "time.sleep(60)\n" % pidfile)
            pt = term_vt.spawn(td, ["python3", script], 80, 24)
            try:
                self.assertTrue(_wait_for(lambda: os.path.exists(pidfile), 10),
                                 "grandchild never started")
                with open(pidfile) as f:
                    gpid = int(f.read())
                try:
                    pt.kill()
                    _drain(pt, 10)

                    def gone():
                        try:
                            os.kill(gpid, 0)
                            return False
                        except ProcessLookupError:
                            return True

                    self.assertTrue(_wait_for(gone, 5), "grandchild %d survived the kill" % gpid)
                finally:
                    try:
                        os.kill(gpid, 9)
                    except OSError:
                        pass
            finally:
                pt.kill()
                _drain(pt, 5)


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._session_cwd0 = term_gate.session_cwd

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        # kill only -- no _drain(): most PTYS here are fake placeholders (pid=0, never spawned,
        # so `done` never flips) and draining each would burn its whole timeout for nothing. A
        # real spawned pty's reader thread is a daemon and reaps itself off-thread; kill() alone
        # is enough to stop it running, and this loop does not need to wait for that to finish.
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)
        term_gate.session_cwd = self._session_cwd0

    def test_routes_are_registered(self):
        from aitracker import server
        self.assertIs(server.EXTRA_POST["/api/term/pty"], term_vt.open_pty)
        self.assertIs(server.EXTRA_POST["/api/term/keys"], term_vt.keys)
        self.assertIs(server.EXTRA_POST["/api/term/resize"], term_vt.resize_pty)
        self.assertIs(server.EXTRA_GET["/api/term/screen"], term_vt.screen_stream)

    def test_pty_403s_when_terminal_disabled(self):
        config.TERMINAL = False
        h = _FakeHandler()
        term_vt.open_pty(h, None, {"session": "x", "cols": 80, "rows": 24})
        self.assertEqual(h.calls[-1][1], 403)
        self.assertFalse(term_gate.allowed())

    def test_pty_400s_a_non_dict_body(self):
        h = _FakeHandler()
        term_vt.open_pty(h, None, "not a dict")
        self.assertEqual(h.calls[-1][1], 400)

    def test_pty_400s_missing_session(self):
        h = _FakeHandler()
        term_vt.open_pty(h, None, {})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)
        self.assertIn("session", obj["error"])

    def test_pty_400s_bad_mode(self):
        term_gate.session_cwd = lambda sid: "/tmp"
        h = _FakeHandler()
        term_vt.open_pty(h, None, {"session": "x", "mode": "sudo"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)
        self.assertIn("mode", obj["error"])

    def test_pty_400s_resume_for_a_non_claude_session(self):
        from aitracker.registry import PROVIDERS
        prefixed = [p for p in PROVIDERS if p.prefix]
        if not prefixed:
            self.skipTest("no prefixed provider registered")
        term_gate.session_cwd = lambda sid: "/tmp"
        h = _FakeHandler()
        term_vt.open_pty(h, None, {"session": prefixed[0].prefix + "x", "mode": "resume"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)
        self.assertIn("Claude-only", obj["error"])

    def test_pty_404s_when_session_has_no_cwd(self):
        h = _FakeHandler()
        term_vt.open_pty(h, None, {"session": "no-such-session-id"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 404)

    def test_fifth_concurrent_pty_gets_429(self):
        for i in range(term_vt.MAX_PTYS):
            term_vt.PTYS["fake%d" % i] = term_vt.Pty(tid="fake%d" % i)  # pid 0, done False
        term_gate.session_cwd = lambda sid: "/tmp"
        h = _FakeHandler()
        term_vt.open_pty(h, None, {"session": "x"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 429)
        self.assertIn("too many", obj["error"])

    def test_open_pty_spawns_a_real_shell_and_registers_it(self):
        term_gate.session_cwd = lambda sid: "/tmp"
        h = _FakeHandler()
        term_vt.open_pty(h, None, {"session": "x", "cols": 40, "rows": 10, "mode": "cwd"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 200)
        self.assertIn(obj["tty"], term_vt.PTYS)
        pt = term_vt.PTYS[obj["tty"]]
        self.assertEqual((pt.screen.cols, pt.screen.rows), (40, 10))

    def test_pty_new_mode_spawns_claude_with_no_args(self):
        """mode="new" on a Claude session id produces argv == ["claude"]."""
        term_gate.session_cwd = lambda sid: "/tmp"
        h = _FakeHandler()

        # Patch spawn() to capture the argv without actually spawning
        spawn_argv = []
        original_spawn = term_vt.spawn
        def capture_spawn(cwd, argv, cols, rows):
            spawn_argv.append(argv)
            # Return a fake Pty to allow the route to complete
            return term_vt.Pty(tid="test-pty-new")

        term_vt.spawn = capture_spawn
        try:
            term_vt.open_pty(h, None, {"session": "claude-sid", "mode": "new", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]
            self.assertEqual(code, 200)
            self.assertEqual(spawn_argv, [["claude"]])
        finally:
            term_vt.spawn = original_spawn

    def test_pty_new_mode_accepted_for_non_claude_session(self):
        """mode="new" is accepted for a non-Claude session id (e.g., auggie:xxx).

        Unlike "resume" which requires Claude, "new" merely borrows the session's cwd
        to start a fresh conversation, so it is valid for any session type.
        """
        from aitracker.registry import PROVIDERS
        prefixed = [p for p in PROVIDERS if p.prefix]
        if not prefixed:
            self.skipTest("no prefixed provider registered")

        term_gate.session_cwd = lambda sid: "/tmp"
        h = _FakeHandler()

        # Patch spawn() to avoid actual process spawning
        original_spawn = term_vt.spawn
        term_vt.spawn = lambda cwd, argv, cols, rows: term_vt.Pty(tid="test-pty-auggie")
        try:
            # Use a non-Claude session id (prefixed)
            non_claude_sid = prefixed[0].prefix + "x"
            term_vt.open_pty(h, None, {"session": non_claude_sid, "mode": "new"})
            obj, code = h.calls[-1]
            self.assertEqual(code, 200, "mode=new should be accepted for non-Claude sessions")
        finally:
            term_vt.spawn = original_spawn

    def test_pty_resume_still_rejected_for_non_claude_session_after_new_mode_added(self):
        """Verify that mode="resume" still rejects non-Claude sessions (proving we narrowed nothing).

        This is a regression test to ensure that adding mode="new" didn't accidentally
        weaken the guard on mode="resume".
        """
        from aitracker.registry import PROVIDERS
        prefixed = [p for p in PROVIDERS if p.prefix]
        if not prefixed:
            self.skipTest("no prefixed provider registered")

        term_gate.session_cwd = lambda sid: "/tmp"
        h = _FakeHandler()
        non_claude_sid = prefixed[0].prefix + "x"
        term_vt.open_pty(h, None, {"session": non_claude_sid, "mode": "resume"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)
        self.assertIn("Claude-only", obj["error"])

    def test_keys_404s_an_unknown_tty(self):
        h = _FakeHandler()
        term_vt.keys(h, None, {"tty": "nope", "data": ""})
        self.assertEqual(h.calls[-1][1], 404)

    def test_keys_400s_bad_base64(self):
        term_vt.PTYS["p1"] = term_vt.Pty(tid="p1", pid=0, fd=-1)
        h = _FakeHandler()
        term_vt.keys(h, None, {"tty": "p1", "data": "not-valid-base64!!"})
        self.assertEqual(h.calls[-1][1], 400)

    def test_resize_404s_an_unknown_tty(self):
        h = _FakeHandler()
        term_vt.resize_pty(h, None, {"tty": "nope", "cols": 80, "rows": 24})
        self.assertEqual(h.calls[-1][1], 404)

    def test_screen_404s_an_unknown_tty(self):
        h = _FakeHandler()
        term_vt.screen_stream(h, _Q("tty=nope"))
        self.assertEqual(h.calls[-1][1], 404)


class _StreamHandler(_FakeHandler):
    """A handler backed by one end of a real socketpair, so screen_stream() can run its SSE loop
    and _peer_gone() can see the client actually go away. Mirrors term_run's own _StreamHandler."""

    def __init__(self):
        import socket as _s
        _FakeHandler.__init__(self)
        self.connection, self.peer = _s.socketpair()
        self.wfile = self.connection.makefile("wb")

    def send_response(self, code):
        pass

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass

    def close_peer(self):
        try:
            self.peer.close()
        except OSError:
            pass

    def close(self):
        self.close_peer()
        for sock in (self.wfile, self.connection):
            try:
                sock.close()
            except OSError:
                pass


class TestStreamAccounting(unittest.TestCase):
    """MAX_STREAMS (thread exhaustion) and the per-PTY viewer refcount (premature teardown)."""

    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        term_vt._STREAMS = 0

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        # kill only -- see TestRoutes.tearDown's comment: draining fake (pid=0) placeholders
        # would burn the full timeout on each one for nothing.
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)
        term_vt._STREAMS = 0

    def test_stream_429s_past_max_streams(self):
        term_vt.PTYS["p1"] = term_vt.Pty(tid="p1")
        term_vt._STREAMS = term_vt.MAX_STREAMS
        h = _FakeHandler()
        term_vt.screen_stream(h, _Q("tty=p1"))
        obj, code = h.calls[-1]
        self.assertEqual(code, 429)
        self.assertIn("too many", obj["error"])
        self.assertEqual(term_vt.PTYS["p1"].viewers, 0)       # a refused viewer takes no slot
        self.assertEqual(term_vt._STREAMS, term_vt.MAX_STREAMS)

    def test_unknown_tty_holds_no_stream_slot(self):
        h = _FakeHandler()
        term_vt.screen_stream(h, _Q("tty=nope"))
        self.assertEqual(h.calls[-1][1], 404)
        self.assertEqual(term_vt._STREAMS, 0)

    def test_one_viewer_leaving_does_not_kill_the_pty_for_the_other(self):
        """Deterministic reproduction of the bug Tier 2 shipped first: two viewers on one PTY,
        close only the first, and the second must NOT be cut off. Unlike Tier 2's one-shot jobs,
        the PTY must also survive the LAST viewer leaving (it is a persistent shell a client is
        meant to reattach to) -- see screen_stream's docstring for why that difference is
        deliberate."""
        pt = term_vt.spawn(os.getcwd(), ["sleep", "30"], 80, 24)
        term_vt.PTYS[pt.id] = pt
        a, b = _StreamHandler(), _StreamHandler()
        ta = threading.Thread(target=term_vt.screen_stream, args=(a, _Q("tty=" + pt.id)))
        tb = threading.Thread(target=term_vt.screen_stream, args=(b, _Q("tty=" + pt.id)))
        ta.daemon = tb.daemon = True
        ta.start(); tb.start()
        try:
            self.assertTrue(_wait_for(lambda: pt.viewers >= 2, 5),
                             "both viewers should be counted")
            a.close_peer()
            ta.join(5)
            self.assertFalse(ta.is_alive())
            self.assertTrue(_wait_for(lambda: pt.viewers == 1, 5))
            self.assertFalse(pt.done, "the surviving viewer was cut off")
            self.assertTrue(tb.is_alive(), "viewer B ended early")
            b.close_peer()
            tb.join(5)
            self.assertTrue(_wait_for(lambda: pt.viewers == 0, 5))
            time.sleep(0.3)
            self.assertFalse(pt.done, "the PTY must survive its last viewer leaving")
        finally:
            pt.kill()
            _drain(pt, 5)
            a.close(); b.close()
        self.assertEqual(term_vt._STREAMS, 0)

    def test_finished_stream_releases_its_slot(self):
        pt = term_vt.Pty(tid="done1")
        pt.done, pt.rc = True, 0
        term_vt.PTYS["done1"] = pt
        h = _StreamHandler()
        term_vt.screen_stream(h, _Q("tty=done1"))
        self.assertEqual(term_vt._STREAMS, 0)
        self.assertEqual(pt.viewers, 0)
        h.close()


class TestWireFormat(unittest.TestCase):
    """The two integration bugs neither TestRoutes nor TestStreamAccounting can see on their own:
    a named `event:` frame that EventSource.onmessage silently swallows, and a shared (rather
    than per-viewer) `since` that would starve whichever viewer attached second. The client half
    of this wire format is already built and committed, so this shape is FIXED -- these tests
    exist to keep the server from drifting away from it."""

    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        term_vt._STREAMS = 0

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)
        term_vt._STREAMS = 0

    def test_stream_frames_carry_no_event_name(self):
        pt = term_vt.Pty(tid="fmt1")
        pt.screen = Screen(cols=10, rows=2)
        pt.screen.feed(b"hi")
        term_vt.PTYS["fmt1"] = pt
        h = _StreamHandler()
        t = threading.Thread(target=term_vt.screen_stream, args=(h, _Q("tty=fmt1")))
        t.daemon = True
        t.start()
        try:
            self.assertTrue(_wait_for(lambda: pt.viewers >= 1, 5))
            h.peer.settimeout(3)
            captured = h.peer.recv(65536)
        finally:
            h.close_peer()
            t.join(5)
            h.close()
        # EventSource.onmessage only fires for UNNAMED events -- a stray `event: <name>` line
        # here would go permanently, silently dark on the client with no error anywhere.
        self.assertIn(b"data: ", captured)
        self.assertNotIn(b"event:", captured)
        payload = json.loads(captured.split(b"data: ", 1)[1].split(b"\n\n", 1)[0])
        self.assertEqual(
            set(payload.keys()),
            {"v", "rows", "cursor", "alt", "cursor_visible", "bracketed_paste", "bell"},
        )

    def test_second_viewer_attaching_to_a_live_tty_gets_a_full_repaint(self):
        pt = term_vt.Pty(tid="fmt2")
        pt.screen = Screen(cols=10, rows=2)
        pt.screen.feed(b"AAAAAAAAAA")           # fills row 0 -- unmistakable in a captured frame
        term_vt.PTYS["fmt2"] = pt

        a = _StreamHandler()
        ta = threading.Thread(target=term_vt.screen_stream, args=(a, _Q("tty=fmt2")))
        ta.daemon = True
        ta.start()
        b = None
        tb = None
        try:
            self.assertTrue(_wait_for(lambda: pt.viewers >= 1, 5))
            a.peer.settimeout(3)
            first = a.peer.recv(65536)
            self.assertIn(b"AAAAAAAAAA", first)     # viewer A's `since` has now moved past 0

            # A second viewer, attaching AFTER A has already "seen" and consumed this content,
            # must still get its own full repaint -- `since` is per-connection, not shared, or
            # whichever viewer attaches second would starve on an empty diff forever.
            b = _StreamHandler()
            tb = threading.Thread(target=term_vt.screen_stream, args=(b, _Q("tty=fmt2")))
            tb.daemon = True
            tb.start()
            self.assertTrue(_wait_for(lambda: pt.viewers >= 2, 5))
            b.peer.settimeout(3)
            second = b.peer.recv(65536)
            self.assertIn(b"AAAAAAAAAA", second)
        finally:
            a.close_peer()
            ta.join(5)
            a.close()
            if b is not None:
                b.close_peer()
                tb.join(5)
                b.close()


class TestIdleTimeout(unittest.TestCase):
    """No keystrokes AND no viewers for IDLE_TIMEOUT -> the reader thread reaps the PTY."""

    def test_idle_pty_is_reaped(self):
        real_timeout = term_vt.IDLE_TIMEOUT
        term_vt.IDLE_TIMEOUT = 0.2
        try:
            pt = term_vt.spawn(os.getcwd(), ["sleep", "30"], 80, 24)
            try:
                self.assertTrue(_drain(pt, 5).done, "idle PTY with no viewers was never reaped")
                self.assertIsNotNone(pt.rc)
            finally:
                pt.kill()
        finally:
            term_vt.IDLE_TIMEOUT = real_timeout

    def test_active_viewer_prevents_idle_reap(self):
        real_timeout = term_vt.IDLE_TIMEOUT
        term_vt.IDLE_TIMEOUT = 0.2
        try:
            pt = term_vt.spawn(os.getcwd(), ["sleep", "30"], 80, 24)
            pt.viewers = 1                     # simulate an attached viewer, no route needed
            try:
                time.sleep(0.6)
                self.assertFalse(pt.done, "a PTY with an active viewer must not be idle-reaped")
            finally:
                pt.viewers = 0
                pt.kill()
                _drain(pt, 5)
        finally:
            term_vt.IDLE_TIMEOUT = real_timeout


class TestEviction(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def _stale(self):
        pt = term_vt.Pty(tid="stale")
        pt.done = True
        pt.ended = time.time() - 1200          # older than the 10-minute linger window
        term_vt.PTYS["stale"] = pt

    def test_every_route_sweeps_finished_ptys(self):
        for call in (lambda h: term_vt.keys(h, None, {"tty": "nope", "data": ""}),
                     lambda h: term_vt.resize_pty(h, None, {"tty": "nope"}),
                     lambda h: term_vt.screen_stream(h, _Q("tty=nope"))):
            self._stale()
            self.assertIn("stale", term_vt.PTYS)
            call(_FakeHandler())
            self.assertNotIn("stale", term_vt.PTYS)


class TestAbsoluteAddressing(unittest.TestCase):
    """CHA/VPA/CNL/CPL -- the finals `top` uses for almost every cell it paints.

    Discarding `d` silently is why the process table used to land entirely on row 0: `top`
    addresses rows with VPA and columns with CHA, and an ignored VPA leaves the cursor wherever
    the previous row's text left it.
    """

    def test_vpa_moves_the_row_and_leaves_the_column(self):
        # THE minimal repro from the adversarial review: this used to render on row 0.
        s = Screen(cols=40, rows=5)
        s.feed(b"\x1b[2dLINE-TWO")
        self.assertEqual(_txt(s, 0), "")
        self.assertEqual(_txt(s, 1), "LINE-TWO")

    def test_vpa_keeps_the_column(self):
        s = Screen(cols=40, rows=5)
        s.feed(b"ABCD\x1b[3dX")            # col stays at 4, row becomes 2
        self.assertEqual(_txt(s, 2), "    X")

    def test_vpa_defaults_and_clamps(self):
        s = Screen(cols=10, rows=4)
        s.feed(b"\x1b[3;1H\x1b[d")          # bare VPA == row 1
        self.assertEqual(s.cur_r, 0)
        s.feed(b"\x1b[99d")
        self.assertEqual(s.cur_r, 3)

    def test_cha_moves_the_column_and_leaves_the_row(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1b[2;1HAB\x1b[10GZ")
        self.assertEqual(s.cur_r, 1)
        self.assertEqual(_txt(s, 1), "AB       Z")
        s.feed(b"\x1b[G")                   # bare CHA == column 1
        self.assertEqual(s.cur_c, 0)
        s.feed(b"\x1b[99G")
        self.assertEqual(s.cur_c, 19)

    def test_cnl_and_cpl_go_to_column_zero(self):
        s = Screen(cols=20, rows=8)
        s.feed(b"\x1b[3;9Hx\x1b[2E")        # CNL 2: row 2 -> 4, column -> 0
        self.assertEqual((s.cur_r, s.cur_c), (4, 0))
        s.feed(b"\x1b[3;9Hx\x1b[2F")        # CPL 2: row 2 -> 0, column -> 0
        self.assertEqual((s.cur_r, s.cur_c), (0, 0))

    def test_cnl_cpl_clamp_at_the_screen_edges(self):
        s = Screen(cols=10, rows=4)
        s.feed(b"\x1b[99E")
        self.assertEqual(s.cur_r, 3)
        s.feed(b"\x1b[99F")
        self.assertEqual(s.cur_r, 0)


class TestInsertDeleteChars(unittest.TestCase):
    """ICH/DCH/ECH: shift or fill WITHIN the line, vacated cells carry the ACTIVE SGR."""

    def test_dch_deletes_and_pulls_the_rest_left(self):
        # THE second minimal repro: a shell line-edit that used to leave a stray "d" behind.
        s = Screen(cols=40, rows=3)
        s.feed(b"echo hello world\x08\x08\x08\x08\x08Bworld"
               b"\x08\x08\x08\x08\x08\x08\x1b[1Pworld")
        self.assertEqual(_txt(s, 0), "echo hello world")

    def test_ich_inserts_blanks_and_pushes_right(self):
        s = Screen(cols=10, rows=2)
        s.feed(b"ABCDEF\x1b[1;3H\x1b[2@")
        self.assertEqual(_txt(s, 0), "AB  CDEF")

    def test_ich_truncates_at_the_right_margin_never_wraps(self):
        s = Screen(cols=6, rows=2)
        s.feed(b"ABCDEF\x1b[1;1H\x1b[2@")
        self.assertEqual(_txt(s, 0), "  ABCD")
        self.assertEqual(_txt(s, 1), "")           # nothing spilled onto the next row

    def test_dch_beyond_the_line_just_clears_the_tail(self):
        s = Screen(cols=6, rows=2)
        s.feed(b"ABCDEF\x1b[1;3H\x1b[99P")
        self.assertEqual(_txt(s, 0), "AB")

    def test_ech_erases_in_place_without_shifting(self):
        s = Screen(cols=10, rows=2)
        s.feed(b"ABCDEFGH\x1b[1;3H\x1b[3X")
        self.assertEqual(_txt(s, 0), "AB   FGH")   # F..H did NOT move left
        self.assertEqual(s.cur_c, 2)               # ECH does not move the cursor

    def test_vacated_cells_carry_the_active_sgr(self):
        """The same rule EL/ED already follow -- a TUI editing its own coloured status line in
        place must not punch unstyled holes in it."""
        # ICH/ECH vacate cells at the cursor; DCH vacates them at the RIGHT MARGIN.
        for seq, col in ((b"\x1b[3@", 0), (b"\x1b[3P", 7), (b"\x1b[3X", 0)):
            s = Screen(cols=10, rows=2)
            s.feed(b"ABCDEFGH\x1b[1;1H\x1b[41m" + seq)
            self.assertIn("41", _codes(s, 0)[col], seq)


class TestInsertDeleteLines(unittest.TestCase):
    """IL/DL/SU/SD operate on the SCROLL REGION, never on the whole screen."""

    def _six(self):
        s = Screen(cols=6, rows=6)
        for r in range(6):
            s.feed(("\x1b[%d;1H%s" % (r + 1, chr(ord("A") + r))).encode())
        return s

    def test_il_pushes_down_only_inside_the_region(self):
        s = self._six()
        s.feed(b"\x1b[2;5r\x1b[3;1H\x1b[L")     # region rows 1..4, cursor row 2, insert 1
        self.assertEqual(_grid(s), ["A", "B", "", "C", "D", "F"])   # E fell off, F untouched

    def test_dl_pulls_up_only_inside_the_region(self):
        s = self._six()
        s.feed(b"\x1b[2;5r\x1b[2;1H\x1b[M")     # region rows 1..4, cursor row 1, delete 1
        self.assertEqual(_grid(s), ["A", "C", "D", "E", "", "F"])

    def test_il_dl_are_noops_outside_the_region(self):
        s = self._six()
        s.feed(b"\x1b[2;5r\x1b[6;1H\x1b[L")     # cursor below the region
        self.assertEqual(_grid(s), ["A", "B", "C", "D", "E", "F"])
        s.feed(b"\x1b[1;1H\x1b[M")               # cursor above the region
        self.assertEqual(_grid(s), ["A", "B", "C", "D", "E", "F"])

    def test_il_dl_move_the_cursor_to_column_zero(self):
        s = self._six()
        s.feed(b"\x1b[3;5H\x1b[L")
        self.assertEqual(s.cur_c, 0)
        s.feed(b"\x1b[3;5H\x1b[M")
        self.assertEqual(s.cur_c, 0)

    def test_su_and_sd_scroll_the_region_without_moving_the_cursor(self):
        s = self._six()
        s.feed(b"\x1b[2;5r\x1b[1;3H\x1b[2S")     # SU 2 inside rows 1..4
        self.assertEqual(_grid(s), ["A", "D", "E", "", "", "F"])
        self.assertEqual((s.cur_r, s.cur_c), (0, 2))
        s.feed(b"\x1b[1S")                        # a bare SU is 1 line
        self.assertEqual(_grid(s), ["A", "E", "", "", "", "F"])
        s.feed(b"\x1b[2T")                        # SD 2 puts blanks back at the region top
        self.assertEqual(_grid(s), ["A", "", "", "E", "", "F"])


class TestBackTab(unittest.TestCase):
    def test_cbt_walks_back_over_tab_stops(self):
        s = Screen(cols=40, rows=2)
        s.feed(b"\x1b[1;21H\x1b[Z")      # col 20 -> previous stop at 16
        self.assertEqual(s.cur_c, 16)
        s.feed(b"\x1b[2Z")                # two more stops -> 0
        self.assertEqual(s.cur_c, 0)

    def test_cbt_from_a_tab_stop_goes_to_the_previous_one(self):
        s = Screen(cols=40, rows=2)
        s.feed(b"\x1b[1;9H\x1b[Z")        # col 8 IS a stop -> 0
        self.assertEqual(s.cur_c, 0)
        s.feed(b"\x1b[Z")                  # already home: stays
        self.assertEqual(s.cur_c, 0)


class TestOriginMode(unittest.TestCase):
    """DECOM (`?6`): row addressing becomes relative to the scroll region."""

    def test_cup_and_vpa_are_region_relative_under_decom(self):
        s = Screen(cols=10, rows=8)
        s.feed(b"\x1b[3;6r\x1b[?6h")       # region rows 2..5 (0-based)
        self.assertEqual(s.cur_r, 2)        # setting DECOM homes to the region top
        s.feed(b"\x1b[1;1HX")
        self.assertEqual(_txt(s, 2), "X")
        s.feed(b"\x1b[2dY")
        self.assertEqual(_txt(s, 3), " Y")

    def test_decom_clamps_addressing_inside_the_region(self):
        s = Screen(cols=10, rows=8)
        s.feed(b"\x1b[3;6r\x1b[?6h\x1b[99;1HZ")
        self.assertEqual(_txt(s, 5), "Z")   # clamped to the region bottom, not row 7

    def test_resetting_decom_restores_absolute_addressing(self):
        s = Screen(cols=10, rows=8)
        s.feed(b"\x1b[3;6r\x1b[?6h\x1b[?6l")
        self.assertEqual((s.cur_r, s.cur_c), (0, 0))
        s.feed(b"\x1b[1;1HQ")
        self.assertEqual(_txt(s, 0), "Q")

    def test_cpr_is_region_relative_under_decom(self):
        s = Screen(cols=10, rows=8)
        s.feed(b"\x1b[3;6r\x1b[?6h\x1b[2;3H\x1b[6n")
        self.assertEqual(s.pop_replies(), b"\x1b[2;3R")


class TestSaveRestoreCursor(unittest.TestCase):
    """DECSC/DECRC and their `CSI s` / `CSI u` aliases save ATTRIBUTES, not just a position."""

    def test_decsc_decrc_round_trip_the_sgr(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1b[31m\x1b[2;5H\x1b7")      # save under red, at row1 col4
        s.feed(b"\x1b[0m\x1b[1;1Hplain")
        s.feed(b"\x1b8X")
        self.assertEqual((s.cur_r, s.cur_c), (1, 5))
        self.assertEqual(_codes(s, 1)[4], "31")

    def test_csi_s_and_u_use_the_same_slot(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1b[3;7H\x1b[s\x1b[1;1H\x1b[u")
        self.assertEqual((s.cur_r, s.cur_c), (2, 6))

    def test_alt_and_primary_have_independent_save_slots(self):
        """A TUI doing ESC 7 inside the alt screen must not clobber the position `?1049l`
        restores the primary screen to."""
        s = Screen(cols=20, rows=6)
        s.feed(b"\x1b[4;9H\x1b7")               # DECSC in the PRIMARY buffer: row3 col8
        s.feed(b"\x1b[?1049h")
        s.feed(b"\x1b[2;3H\x1b7")               # DECSC in the ALT buffer: must not clobber it
        s.feed(b"\x1b[6;1H\x1b8")
        self.assertEqual((s.cur_r, s.cur_c), (1, 2))    # alt's own save works
        s.feed(b"\x1b[?1049l\x1b[1;1H\x1b8")
        self.assertEqual((s.cur_r, s.cur_c), (3, 8),
                         "the alt buffer's DECSC overwrote the primary buffer's save slot")


class TestAltScreenRestoresEverything(unittest.TestCase):
    def test_1049l_restores_the_sgr_not_just_the_position(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1b[32m\x1b[?1049h\x1b[41mALT\x1b[?1049l")
        s.feed(b"\x1b[1;1Hafter")
        self.assertEqual(_codes(s, 0)[0], "32", "the alt screen's background leaked out with it")

    def test_reentering_alt_starts_from_a_clean_buffer(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1b[?1049hFIRST-RUN\x1b[?1049l")
        s.feed(b"\x1b[?1049h")
        self.assertEqual(_grid(s), ["", "", "", ""], "stale alt content survived the round trip")

    def test_primary_content_still_survives_the_round_trip(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1b[1;1Hprimary\x1b[?1049hALT\x1b[?1049l")
        self.assertEqual(_txt(s, 0), "primary")


class TestNulInsideCsi(unittest.TestCase):
    def test_nul_inside_a_csi_is_ignored_not_printed(self):
        """The only path by which escape residue ever reached cell text: the NUL ended the
        sequence early and the real final byte was printed as a character."""
        s = Screen(cols=10, rows=2)
        s.feed(b"A\x1b[3\x00mB")
        self.assertEqual(_txt(s, 0), "AB")
        self.assertEqual(_codes(s, 0)[1], "3")   # ...and the SGR still took effect

    def test_nul_does_not_corrupt_a_multi_param_csi(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"\x1b[\x002;\x004H*")
        self.assertEqual(_txt(s, 1), "   *")


class TestDeviceReports(unittest.TestCase):
    """DSR/DA: a real `vim` BLOCKS on these at startup. See Screen.pop_replies."""

    def test_cpr_reports_the_1_based_cursor_position(self):
        s = Screen(cols=20, rows=6)
        s.feed(b"\x1b[3;7H\x1b[6n")
        self.assertEqual(s.pop_replies(), b"\x1b[3;7R")
        self.assertEqual(s.pop_replies(), b"")   # drained, not repeated

    def test_dsr_5_reports_terminal_ok(self):
        s = Screen(cols=20, rows=6)
        s.feed(b"\x1b[5n")
        self.assertEqual(s.pop_replies(), b"\x1b[0n")

    def test_primary_and_secondary_da(self):
        s = Screen(cols=20, rows=6)
        s.feed(b"\x1b[c")
        self.assertEqual(s.pop_replies(), b"\x1b[?1;2c")
        s.feed(b"\x1b[>c")
        self.assertTrue(s.pop_replies().startswith(b"\x1b[>"))

    def test_replies_never_reach_the_grid(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1b[6n\x1b[>c\x1b[5n")
        self.assertEqual(_grid(s), ["", "", "", ""])

    def test_undrained_replies_stay_bounded(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1b[6n" * 20000)
        self.assertLessEqual(len(s.pending_replies), term_vt.MAX_REPLIES)


class TestUnterminatedStringSequence(unittest.TestCase):
    """B3: an OSC/DCS with no terminator used to buffer the whole rest of the stream forever."""

    def test_pending_never_exceeds_the_cap(self):
        s = Screen(cols=20, rows=4)
        for _ in range(20):
            s.feed(b"\x1bP" + b"x" * 20000)
        self.assertLessEqual(len(s._pending), term_vt.MAX_PENDING)

    def test_the_screen_keeps_working_after_an_abandoned_sequence(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1bP" + b"\x00" * (term_vt.MAX_PENDING + 100))
        self.assertGreaterEqual(s.resyncs, 1)
        s.feed(b"\x1b[2J\x1b[1;1HALIVE")
        self.assertEqual(_txt(s, 0), "ALIVE")

    def test_a_short_unterminated_sequence_is_still_buffered_for_the_next_feed(self):
        """The cap must not break the split-read contract: a real OSC arriving in two pieces
        still has to parse identically to one that arrived whole."""
        s = Screen(cols=20, rows=4)
        s.feed(b"\x1b]0;my-ti")
        self.assertEqual(s.resyncs, 0)
        s.feed(b"tle\x07done")
        self.assertEqual(s.title, "my-title")
        self.assertEqual(_txt(s, 0), "done")

    def test_real_bin_sh_bytes_do_not_wedge_the_screen(self):
        """/bin/sh carries a stray DCS introducer; `cat /bin/sh` used to kill the tty for good."""
        if not os.path.exists("/bin/sh"):
            self.skipTest("no /bin/sh")
        with open("/bin/sh", "rb") as f:
            blob = f.read()
        s = Screen(cols=80, rows=24)
        worst = 0
        for i in range(0, len(blob), 4096):
            s.feed(blob[i:i + 4096])
            worst = max(worst, len(s._pending))
        self.assertLessEqual(worst, term_vt.MAX_PENDING)
        v_before = s.v
        s.feed(b"\x1b[2J\x1b[1;1Hstill-here")
        self.assertEqual(_txt(s, 0), "still-here")
        self.assertGreater(s.v, v_before)


class TestVersionIsMonotonic(unittest.TestCase):
    """B4: `v` is the diff protocol's clock. Rewinding it strands every attached viewer."""

    def test_ris_does_not_rewind_v(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"one\x1b[2;1Htwo")
        since = s.snapshot(-1)["v"]
        s.feed(b"\x1bc")
        self.assertGreaterEqual(s.v, since)

    def test_ris_repaints_every_row_for_a_viewer_holding_an_old_since(self):
        s = Screen(cols=20, rows=4)
        s.feed(b"one\x1b[2;1Htwo")
        since = s.snapshot(-1)["v"]
        s.feed(b"\x1bcfresh")
        snap = s.snapshot(since)
        self.assertEqual(sorted(r[0] for r in snap["rows"]), [0, 1, 2, 3])
        self.assertEqual(_txt(s, 0), "fresh")

    def test_ris_still_resets_everything_else(self):
        s = Screen(cols=20, rows=6)
        s.feed(b"\x1b[41m\x1b[2;5r\x1b[?7l\x1b[?1049h\x1bc")
        self.assertEqual(s._cur_code, "")
        self.assertEqual((s.scroll_top, s.scroll_bot), (0, 5))
        self.assertTrue(s.autowrap)
        self.assertFalse(s.alt)
        self.assertEqual(_grid(s), [""] * 6)

    def test_v_is_monotonic_across_reset_resize_and_alt_switches(self):
        s = Screen(cols=20, rows=4)
        seen = []
        for step in (b"hello", b"\x1bc", b"after", b"\x1b[?1049h", b"\x1b[?1049l", b"\x1bc"):
            s.feed(step)
            seen.append(s.v)
            s.resize(s.cols + 1, s.rows)
            seen.append(s.v)
        self.assertEqual(seen, sorted(seen), "v went backwards: %r" % (seen,))


class TestReaderAnswersDeviceReports(unittest.TestCase):
    """B7's other half: `Screen` accumulates the answer, `_reader` writes it back to the pty.

    Without this the emulator is write-only, and any program that asks the terminal a question
    and waits for the reply -- `vim` does, on startup -- simply hangs.
    """

    _PROG = (
        "import os,sys,tty\n"
        "tty.setraw(0)\n"
        "os.write(1, b'\\x1b[6n')\n"
        "buf = b''\n"
        "while not buf.endswith(b'R'):\n"
        "    ch = os.read(0, 1)\n"
        "    if not ch: sys.exit(1)\n"
        "    buf += ch\n"
        "os.write(1, b'CPR=' + buf[2:-1] + b'\\r\\n')\n"
    )

    def test_a_child_blocked_on_cpr_gets_its_answer(self):
        import sys as _sys
        pt = term_vt.spawn(os.getcwd(), [_sys.executable, "-c", self._PROG], 80, 24)
        try:
            def answered():
                with pt.lock:
                    return any("CPR=" in r[1] for r in pt.screen.snapshot(-1)["rows"])
            self.assertTrue(_wait_for(answered, 15),
                            "the child never received a cursor position report")
            with pt.lock:
                text = " ".join(r[1] for r in pt.screen.snapshot(-1)["rows"])
            self.assertIn("CPR=1;1", text)   # 1-based, and the query itself printed nothing
        finally:
            pt.kill()
            _drain(pt, 5)


class TestRealCapturedStreams(unittest.TestCase):
    """The gap every hand-written test above missed: NOTHING here was ever fed a real program's
    bytes. These three fixtures are verbatim `pty.fork()` captures -- vim, zsh's line editor and
    ncurses' own `tput` output -- and each one's grid was diffed row-by-row against `pyte` (a
    third-party emulator used as an oracle in a throwaway venv; it is deliberately NOT a
    dependency of anything shipped) until the differing-row count reached zero."""

    def test_tput_capture_exercises_every_newly_added_final(self):
        """236 bytes of real terminfo output: VPA, CHA, ECH, DCH, ICH, IL, DL and CBT, each
        emitted by ncurses rather than typed by hand."""
        s = Screen(cols=80, rows=24)
        s.feed(_capture("vt_tput.bin"))
        self.assertEqual([(i, t) for i, t in enumerate(_grid(s)) if t], [
            (0, "ROW-ZERO"),
            (2, "        VPA-ROW-TWO"),      # VPA kept the column CHA/text had left it at
            (4, "          CHA-COL-TEN"),
            (6, "aaa    aaa"),               # ECH 4 erased in place, nothing shifted
            (8, "01456789"),                 # two DCH pulled the tail left
            (10, "X   YZ"),                  # ICH 3 pushed YZ right
            (12, "L12"), (14, "L13"), (15, "L14"),   # IL 1 opened a gap at row 13
            (16, "M17"), (17, "M18"),               # DL 1 removed M16
            (20, "                CBT"),     # CBT from column 20 -> the stop at 16
            (22, "DONE"),
        ])
        self.assertEqual(s._pending, b"")
        self.assertEqual(s.resyncs, 0)

    def test_vim_capture_renders_the_file_and_the_edits(self):
        """A real `vim -u NONE README.md` session (open, dd, dd, o, p, i, 5x, :q!) with its
        `ESC[6n` / `ESC[>c` queries answered live from `pop_replies()`. Carries a real DCS
        (`ESC P zz ESC \\`), real DECSTBM traffic and real IL/DL."""
        blob = _capture("vt_vim.bin")
        cut = blob.rfind(b"\x1b[?1049l")     # everything up to leaving the alt screen
        self.assertGreater(cut, 0)
        s = Screen(cols=80, rows=24)
        for i in range(0, cut, 64):          # 64-byte reads: split-feed correctness, for real
            s.feed(blob[i:min(i + 64, cut)])
        self.assertTrue(s.alt)
        self.assertEqual(_txt(s, 0), "# AI Session Tracker")
        self.assertEqual(_txt(s, 10), "INSERTED LINE")   # the `o` command's IL
        self.assertEqual(_txt(s, 11), ">>")              # `0i>>>` then `5x`
        self.assertEqual(_txt(s, 17), "</p>")
        for r in range(24):                              # no escape residue anywhere
            self.assertNotIn("\x1b", _txt(s, r))
            self.assertNotIn("zz", _txt(s, r), "the DCS payload leaked into the grid")
        s.feed(blob[cut:])
        self.assertFalse(s.alt)
        self.assertIsNone(s.alt_grid)
        self.assertEqual(s._cur_code, "")
        self.assertEqual(s._pending, b"")
        self.assertEqual(s.resyncs, 0)

    def test_zsh_line_edit_capture_leaves_no_deleted_characters_behind(self):
        """A real zsh line editor moving mid-line and deleting with `ESC[P` -- the shape that
        used to leave the deleted characters on screen."""
        s = Screen(cols=80, rows=24)
        s.feed(_capture("vt_zsh.bin"))
        self.assertEqual([t for t in _grid(s) if t.strip()],
                         ["$ echo XYZha beta gamma", "XYZha beta gamma", "$ exit"])


class TestScrollbackBasic(unittest.TestCase):
    """Feed more lines than a small screen holds; scrolled-off rows must show up in `history()`,
    oldest first, with their SGR runs intact -- and the live grid keeps only what's left."""

    def _fill(self, s, lines):
        for text in lines:
            s.feed(text)

    def test_scrolled_off_rows_land_in_history_in_order_with_sgr_intact(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"\x1b[31mL0\x1b[0m\r\n")   # L0 written in red, then reset
        s.feed(b"L1\r\n")
        s.feed(b"L2\r\n")
        s.feed(b"L3\r\n")
        s.feed(b"L4\r\n")                  # by now L0, L1, L2 have scrolled off the top

        self.assertEqual(s.scrollback_len, 3)
        self.assertEqual(list(s.scrollback), [
            ("L0", [[0, 2, "31"]]),
            ("L1", []),
            ("L2", []),
        ])
        # live grid keeps exactly what's left
        self.assertEqual(_txt(s, 0), "L3")
        self.assertEqual(_txt(s, 1), "L4")

    def test_history_offset_and_count_select_the_right_window(self):
        s = Screen(cols=10, rows=3)
        for text in (b"\x1b[31mL0\x1b[0m\r\n", b"L1\r\n", b"L2\r\n", b"L3\r\n", b"L4\r\n"):
            s.feed(text)
        h = s.history(1, 3)
        self.assertEqual(h["total"], 3)
        self.assertEqual(h["offset"], 1)
        self.assertEqual(h["rows"], [
            [0, "L0", [[0, 2, "31"]]],
            [1, "L1", []],
            [2, "L2", []],
        ])
        # a smaller count returns just the bottom-most slice of the same history
        h2 = s.history(1, 1)
        self.assertEqual(h2["rows"], [[0, "L2", []]])


class TestScrollbackAltScreenExcluded(unittest.TestCase):
    def test_alt_screen_scrolling_never_enters_history(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"\x1b[?1049h")               # enter alt
        for i in range(6):                   # scrolls repeatedly on the alt buffer
            s.feed(("A%d\r\n" % i).encode())
        self.assertEqual(s.scrollback_len, 0)
        s.feed(b"\x1b[?1049l")                # leave alt
        self.assertEqual(s.scrollback_len, 0)

    def test_primary_scrolling_before_and_after_alt_still_counts(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"P0\r\nP1\r\nP2\r\nP3\r\n")   # one primary scroll before alt
        before = s.scrollback_len
        self.assertGreater(before, 0)
        s.feed(b"\x1b[?1049h")
        s.feed(b"X0\r\nX1\r\nX2\r\nX3\r\n")   # alt scrolling: must not add
        self.assertEqual(s.scrollback_len, before)
        s.feed(b"\x1b[?1049l")
        self.assertEqual(s.scrollback_len, before)


class TestScrollbackMidRegionNotHistory(unittest.TestCase):
    def test_scroll_region_not_starting_at_row_zero_is_a_redraw_not_history(self):
        s = Screen(cols=10, rows=5)
        s.feed(b"\x1b[2;5r")     # DECSTBM: region rows 2..5 (1-based) -> scroll_top = 1
        s.feed(b"\x1b[5;1H")     # cursor to the bottom of that region
        for i in range(6):
            s.feed(("M%d\r\n" % i).encode())
        self.assertEqual(s.scrollback_len, 0)

    def test_scroll_region_starting_at_row_zero_does_enter_history(self):
        s = Screen(cols=10, rows=5)
        s.feed(b"\x1b[1;3r")     # region rows 1..3 (1-based) -> scroll_top = 0: this IS the top
        s.feed(b"\x1b[3;1H")     # cursor to the bottom of that region
        for i in range(6):
            s.feed(("N%d\r\n" % i).encode())
        self.assertGreater(s.scrollback_len, 0)


class TestScrollbackCap(unittest.TestCase):
    def test_cap_holds_and_drops_the_oldest(self):
        original = term_vt.SCROLLBACK_MAX
        term_vt.SCROLLBACK_MAX = 5
        try:
            s = Screen(cols=10, rows=1)   # every extra line forces a scroll
            for i in range(12):
                s.feed(("L%02d\r\n" % i).encode())
            self.assertEqual(s.scrollback_len, 5)
            self.assertEqual([t for t, _ in s.scrollback],
                              ["L07", "L08", "L09", "L10", "L11"])
        finally:
            term_vt.SCROLLBACK_MAX = original


class TestScrollbackOffsetClamping(unittest.TestCase):
    def setUp(self):
        self.s = Screen(cols=10, rows=3)
        for text in (b"L0\r\n", b"L1\r\n", b"L2\r\n", b"L3\r\n", b"L4\r\n"):
            self.s.feed(text)
        self.assertEqual(self.s.scrollback_len, 3)

    def test_offset_zero_returns_nothing(self):
        h = self.s.history(0, 5)
        self.assertEqual(h, {"rows": [], "total": 3, "offset": 0})

    def test_negative_offset_clamps_to_zero(self):
        h = self.s.history(-7, 5)
        self.assertEqual(h["rows"], [])
        self.assertEqual(h["offset"], 0)

    def test_offset_beyond_retained_clamps_to_the_oldest_available(self):
        h = self.s.history(999, 2)
        self.assertEqual(h["offset"], 3)                  # clamped down to `total`
        self.assertEqual(h["rows"], [[0, "L0", []]])       # only the oldest row exists that far back

    def test_offset_within_range_is_used_unclamped(self):
        h = self.s.history(2, 5)
        self.assertEqual(h["offset"], 2)

    def test_zero_count_returns_nothing_but_still_reports_total_and_offset(self):
        h = self.s.history(2, 0)
        self.assertEqual(h["rows"], [])
        self.assertEqual(h["total"], 3)
        self.assertEqual(h["offset"], 2)


class TestScrollbackDoesNotTouchVersioning(unittest.TestCase):
    """The load-bearing guarantee: scrolling into history must be invisible to the `v`/`row_v`
    diff protocol -- see the module docstring's warning about a version-counter rewind freezing
    viewers forever. `history()` must never move that needle."""

    def test_v_and_row_v_are_unchanged_by_any_number_of_history_calls(self):
        s = Screen(cols=10, rows=3)
        for text in (b"L0\r\n", b"L1\r\n", b"L2\r\n", b"L3\r\n", b"L4\r\n"):
            s.feed(text)
        v_before = s.v
        row_v_before = list(s.row_v)
        for offset, count in [(0, 3), (1, 3), (2, 1), (999, 5), (-1, 3), (1, 0)]:
            s.history(offset, count)
        self.assertEqual(s.v, v_before)
        self.assertEqual(s.row_v, row_v_before)

    def test_live_snapshot_since_is_identical_whether_or_not_history_was_read_in_between(self):
        s = Screen(cols=10, rows=3)
        s.feed(b"L0\r\nL1\r\nL2\r\nL3\r\n")
        since = s.v
        s.feed(b"\x1b[3;1HZZ")               # one more live change, row 2 (0-based)
        snap_without = s.snapshot(since)

        s2 = Screen(cols=10, rows=3)
        s2.feed(b"L0\r\nL1\r\nL2\r\nL3\r\n")
        since2 = s2.v
        self.assertEqual(since, since2)
        s2.history(1, 3)                     # interleave a scrollback read -- must not matter
        s2.feed(b"\x1b[3;1HZZ")
        snap_with = s2.snapshot(since2)

        self.assertEqual(snap_without, snap_with)


class TestScrollbackAcrossResize(unittest.TestCase):
    def test_resize_does_not_corrupt_or_drop_history(self):
        s = Screen(cols=10, rows=3)
        for text in (b"L0\r\n", b"L1\r\n", b"L2\r\n", b"L3\r\n", b"L4\r\n"):
            s.feed(text)
        before = list(s.scrollback)
        s.resize(20, 6)
        self.assertEqual(list(s.scrollback), before)
        self.assertEqual(s.scrollback_len, 3)
        # still readable correctly after the resize
        h = s.history(1, 3)
        self.assertEqual(h["rows"], [[0, "L0", []], [1, "L1", []], [2, "L2", []]])


class TestScrollbackAcrossReset(unittest.TestCase):
    def test_ris_keeps_scrollback_real_xterm_behaviour(self):
        """`ESC c` (RIS) clears the visible grid and cursor state but real xterm does NOT
        discard terminal history -- see the module docstring's "Scrollback" section for why
        `_reset()` deliberately preserves `self.scrollback` alongside `v`/`pending_replies`."""
        s = Screen(cols=10, rows=3)
        for text in (b"K0\r\n", b"K1\r\n", b"K2\r\n", b"K3\r\n", b"K4\r\n"):
            s.feed(text)
        before = list(s.scrollback)
        self.assertGreater(len(before), 0)
        s.feed(b"\x1bc")                     # RIS
        self.assertEqual(list(s.scrollback), before)
        self.assertEqual(s.scrollback_len, len(before))
        # and the grid really was reset underneath it
        self.assertEqual(_txt(s, 0), "")


class TestScrollbackRealCapture(unittest.TestCase):
    """The same lesson TestRealCapturedStreams exists for: hand-written escape sequences pass
    hand-written tests. Feed a real captured zsh session through a screen too small to hold it
    and check the resulting scrollback against what a real terminal would retain."""

    def test_real_zsh_capture_scrolled_lines_land_in_history(self):
        s = Screen(cols=80, rows=2)          # small enough that the capture overflows it
        s.feed(_capture("vt_zsh.bin"))
        self.assertEqual(s.scrollback_len, 2)
        self.assertEqual([t for t, _ in s.scrollback],
                          ["$ echo XYZha beta gamma", "XYZha beta gamma"])
        # what's left on screen is exactly the tail the real fixture ends with
        self.assertEqual(_txt(s, 0), "$ exit")
        h = s.history(1, 2)
        self.assertEqual(h["total"], 2)
        self.assertEqual([r[1] for r in h["rows"]],
                          ["$ echo XYZha beta gamma", "XYZha beta gamma"])


class TestScrollbackRoute(unittest.TestCase):
    """GET /api/term/scrollback -- same guard/registration pattern as TestRoutes above."""

    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def test_route_is_registered(self):
        from aitracker import server
        self.assertIs(server.EXTRA_GET["/api/term/scrollback"], term_vt.term_scrollback)

    def test_404s_an_unknown_tty(self):
        h = _FakeHandler()
        term_vt.term_scrollback(h, _Q("tty=nope"))
        self.assertEqual(h.calls[-1][1], 404)

    def test_403s_when_terminal_disabled(self):
        config.TERMINAL = False
        h = _FakeHandler()
        term_vt.term_scrollback(h, _Q("tty=whatever"))
        self.assertEqual(h.calls[-1][1], 403)

    def test_returns_history_for_a_known_tty(self):
        screen = Screen(cols=10, rows=3)
        for text in (b"L0\r\n", b"L1\r\n", b"L2\r\n", b"L3\r\n", b"L4\r\n"):
            screen.feed(text)
        term_vt.PTYS["p1"] = term_vt.Pty(tid="p1", screen=screen)
        h = _FakeHandler()
        term_vt.term_scrollback(h, _Q("tty=p1&offset=1&rows=3"))
        obj, code = h.calls[-1]
        self.assertEqual(code, 200)
        self.assertEqual(obj["total"], 3)
        self.assertEqual(obj["offset"], 1)
        self.assertEqual([r[1] for r in obj["rows"]], ["L0", "L1", "L2"])

    def test_missing_query_params_default_to_no_rows(self):
        screen = Screen(cols=10, rows=3)
        for text in (b"L0\r\n", b"L1\r\n", b"L2\r\n", b"L3\r\n", b"L4\r\n"):
            screen.feed(text)
        term_vt.PTYS["p1"] = term_vt.Pty(tid="p1", screen=screen)
        h = _FakeHandler()
        term_vt.term_scrollback(h, _Q("tty=p1"))
        obj, code = h.calls[-1]
        self.assertEqual(code, 200)
        self.assertEqual(obj["rows"], [])            # offset defaulted to 0

    def test_reads_a_finished_pty_without_404ing(self):
        """Unlike `keys`/`resize`, a finished PTY's history is still legitimately readable."""
        screen = Screen(cols=10, rows=3)
        screen.feed(b"L0\r\nL1\r\nL2\r\nL3\r\n")
        pt = term_vt.Pty(tid="p1", screen=screen)
        pt.done = True
        pt.ended = time.time()          # else _reap() (called by every route) drops it on sight
        term_vt.PTYS["p1"] = pt
        h = _FakeHandler()
        term_vt.term_scrollback(h, _Q("tty=p1&offset=1&rows=3"))
        self.assertEqual(h.calls[-1][1], 200)


if __name__ == "__main__":
    unittest.main()
