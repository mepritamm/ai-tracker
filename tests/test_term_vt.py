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
        self.assertEqual(set(payload.keys()), {"v", "rows", "cursor", "alt"})

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


if __name__ == "__main__":
    unittest.main()
