"""Tests for aitracker.term_vt.Screen -- the pure VT100/xterm emulator for Tier 3.

Every assertion here is pure: bytes in, grid out, no PTY, no server, no browser. Split-feed
correctness (an escape sequence or a UTF-8 character arriving across two feed() calls) is the
single most likely real-world bug, so it gets its own dedicated section.
"""
import unittest

from aitracker.term_vt import Screen


def _rows(snap):
    return {r[0]: r for r in snap["rows"]}


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


if __name__ == "__main__":
    unittest.main()
