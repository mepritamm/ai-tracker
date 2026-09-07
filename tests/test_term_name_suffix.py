"""Regression tests for the terminal name suffix feature (and its load-bearing prerequisite,
"has this session-less terminal spawned a real Claude session yet").

THE CHANGE UNDER TEST:

  1. aitracker/term_vt.py -- `_MODE_SUFFIX = {"cwd": "-terminal", "new": "-new",
     "resume": "-resume"}` and every `_live_list()` row now carries `"suffix":
     _MODE_SUFFIX.get(p.mode, "")`, always present, "" for an unknown/empty mode.

  2. aitracker/term_vt.py -- `Pty.spawned` latches the session a `cwd`/`new` terminal goes
     on to CREATE; `_live_list()` reports `p.spawned or p.session` so the row follows the
     real session once one exists.

  3. aitracker/providers/claude.py -- `newest_session_in_cwd(cwd, after_ts, exclude=())`
     is the join `resolve_spawned()` uses to find that new session. THE POINT OF THIS FILE:
     it must match on the session's own START time (`sm["first"]`), never on file mtime --
     a session that started well before `after_ts` but is still being appended to (mtime ==
     now) must NOT be reported as "the session this terminal just spawned". Getting this
     wrong puts the wrong name on a live dashboard row.

  4. aitracker/web/ext_cr_dialogs.js and aitracker/web/ext_vt.js both render `t.suffix`
     onto the terminal row name -- checked here as a source-text parity assertion, the same
     idiom tests/test_view_parity.py uses to keep a capability from landing in only one
     front-end.

Real on-disk shape confirmed before writing the fixtures below: a line in an actual
~/.claude/projects/*/*.jsonl session file carries `cwd` and `timestamp` together, e.g.
`{"...,"cwd":"/some/path","sessionId":"...","timestamp":"2026-08-28T16:47:56.492Z",...}`,
and an SDK-spawned agent transcript carries `"entrypoint":"sdk-cli"` on that same kind of
line. The fixtures below reuse exactly that shape rather than inventing one (conventions
rule 7 / CLAUDE.md's "confirm the real log shape" rule).
"""
import datetime as dt
import json
import os
import shutil
import tempfile
import time
import unittest

from aitracker import config, term_vt
from aitracker.providers import claude as claude_provider


def _iso(epoch):
    """epoch -> the same millisecond-precision 'Z' ISO shape real Claude Code transcripts use,
    parseable by util._ts_epoch (`fromisoformat` after `Z` -> `+00:00`)."""
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _write_session(path, cwd=None, first_epoch=None, sdk_cli=False, no_timestamp=False):
    """One real-shaped session file: a single line carrying cwd+timestamp together (the shape
    confirmed above), optionally an sdk-cli entrypoint, optionally with no parseable
    `timestamp` at all (to model `sm['first'] == 0.0`, the 'unknown start' sentinel)."""
    row = {"type": "summary", "sessionId": os.path.basename(path)[:-6]}
    if cwd is not None:
        row["cwd"] = cwd
    if not no_timestamp:
        row["timestamp"] = _iso(first_epoch)
    if sdk_cli:
        row["entrypoint"] = "sdk-cli"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return path


class _ProjectsDirCase(unittest.TestCase):
    """Common fixture: a temp config.PROJECTS with one project subdir, restored after --
    same pattern tests/test_claude_detail_ended.py uses for the same late-bound path."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)

    def tearDown(self):
        config.PROJECTS = self._pdir_snap
        shutil.rmtree(self.pdir, ignore_errors=True)

    def _path(self, sid):
        return os.path.join(self.sdir, sid + ".jsonl")


# ---------------------------------------------------------------------------------------
# (a) _MODE_SUFFIX and _live_list()'s "suffix" field.
# ---------------------------------------------------------------------------------------

class TestModeSuffixTable(unittest.TestCase):
    def test_the_three_real_modes_map_to_the_documented_suffixes(self):
        self.assertEqual(term_vt._MODE_SUFFIX, {
            "cwd": "-terminal", "new": "-new", "resume": "-resume",
        })


class TestLiveListSuffixField(unittest.TestCase):
    """Fake Pty objects dropped straight into term_vt.PTYS, same technique test_term_vt.py's
    TestRoutes/TestLiveList use -- PTYS is restored in tearDown so nothing leaks into any
    other test module sharing this process."""

    def setUp(self):
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        for pt in list(term_vt.PTYS.values()):
            pt.kill()          # safe no-op for these placeholders: pid=0 (see Pty.kill's guard)
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def _row(self, tid):
        return {r["tty"]: r for r in term_vt._live_list()}[tid]

    def test_each_real_mode_gets_its_own_suffix_in_the_live_list_row(self):
        for tid, mode, want in (
            ("m-cwd", "cwd", "-terminal"),
            ("m-new", "new", "-new"),
            ("m-resume", "resume", "-resume"),
        ):
            term_vt.PTYS[tid] = term_vt.Pty(tid=tid, cwd="/tmp/x")
            term_vt.PTYS[tid].mode = mode
        for tid, mode, want in (
            ("m-cwd", "cwd", "-terminal"),
            ("m-new", "new", "-new"),
            ("m-resume", "resume", "-resume"),
        ):
            self.assertEqual(self._row(tid)["suffix"], want)

    def test_unknown_mode_yields_empty_string_suffix_never_missing_never_none(self):
        term_vt.PTYS["m-bogus"] = term_vt.Pty(tid="m-bogus", cwd="/tmp/x")
        term_vt.PTYS["m-bogus"].mode = "some-future-mode"
        row = self._row("m-bogus")
        self.assertIn("suffix", row)
        self.assertEqual(row["suffix"], "")
        self.assertIsNotNone(row["suffix"])

    def test_empty_mode_also_yields_empty_string_suffix(self):
        term_vt.PTYS["m-empty"] = term_vt.Pty(tid="m-empty", cwd="/tmp/x")
        self.assertEqual(term_vt.PTYS["m-empty"].mode, "")   # Pty.__init__'s own default
        row = self._row("m-empty")
        self.assertIn("suffix", row)
        self.assertEqual(row["suffix"], "")


# ---------------------------------------------------------------------------------------
# (e) _live_list() prefers p.spawned over p.session.
# ---------------------------------------------------------------------------------------

class TestLiveListPrefersSpawnedOverSession(unittest.TestCase):
    def setUp(self):
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def _row(self):
        return {r["tty"]: r for r in term_vt._live_list()}["p1"]

    def test_falls_back_to_session_when_spawned_is_unset(self):
        pt = term_vt.Pty(tid="p1", cwd="/tmp/x")
        pt.session = "sess-original"
        term_vt.PTYS["p1"] = pt
        self.assertEqual(self._row()["session"], "sess-original")

    def test_prefers_spawned_once_the_latch_is_set(self):
        pt = term_vt.Pty(tid="p1", cwd="/tmp/x")
        pt.session = "sess-original"
        pt.spawned = "sess-newly-created"
        term_vt.PTYS["p1"] = pt
        self.assertEqual(self._row()["session"], "sess-newly-created")

    def test_plain_cwd_shell_with_neither_reports_empty_string(self):
        term_vt.PTYS["p1"] = term_vt.Pty(tid="p1", cwd="/tmp/x")
        self.assertEqual(self._row()["session"], "")


# ---------------------------------------------------------------------------------------
# (b) THE IMPORTANT ONE -- newest_session_in_cwd must key off session START time, never mtime.
# ---------------------------------------------------------------------------------------

class TestNewestSessionInCwdRejectsMtimeFalsePositive(_ProjectsDirCase):
    def test_a_long_running_session_touched_after_after_ts_is_not_mistaken_for_a_new_one(self):
        cwd = "/tmp/some/project"
        after_ts = time.time() - 100000.0

        # DELIBERATELY INVERTED mtime ordering -- do not "tidy" this back to mtime tracking
        # start time. If the old (real) session's mtime were left *earlier* than the new
        # session's mtime, an mtime-ranking implementation would still pick the new session
        # by coincidence and this test would pass against BOTH a correct (start-time) and a
        # broken (mtime) implementation, proving nothing. To actually discriminate between
        # the two, the old session must have the LATER mtime -- which is also the realistic
        # case: a session started hours ago that is still being actively appended to has an
        # mtime of right now, newer than a session created a minute ago and since gone quiet.
        #
        # old-still-running: started well BEFORE after_ts, but its mtime is bumped to
        # roughly NOW -- the latest mtime of the two files -- simulating a long-running
        # session still being appended to at the moment the caller polls.
        old_path = self._path("old-still-running")
        _write_session(old_path, cwd=cwd, first_epoch=after_ts - 500)
        os.utime(old_path, (time.time(), time.time()))

        # new-real-session: genuinely STARTED after after_ts, but its mtime is EARLIER than
        # old-still-running's (while still > after_ts, so it survives the cheap mtime
        # pre-filter in newest_session_in_cwd) -- e.g. it was written once and has since
        # gone quiet.
        new_path = self._path("new-real-session")
        _write_session(new_path, cwd=cwd, first_epoch=after_ts + 20)
        os.utime(new_path, (after_ts + 10, after_ts + 10))

        got = claude_provider.newest_session_in_cwd(cwd, after_ts)
        self.assertEqual(got, "new-real-session",
                          "must match on start time, not on mtime -- ranking by mtime here "
                          "would wrongly return 'old-still-running', since it has the LATER "
                          "mtime of the two despite starting first")

    def test_only_the_old_session_present_yields_no_match_at_all(self):
        cwd = "/tmp/some/project"
        after_ts = time.time() - 100000.0
        old_path = self._path("old-still-running")
        _write_session(old_path, cwd=cwd, first_epoch=after_ts - 500)
        os.utime(old_path, (after_ts + 50, after_ts + 50))

        self.assertEqual(claude_provider.newest_session_in_cwd(cwd, after_ts), "")


# ---------------------------------------------------------------------------------------
# (c) exclude is honoured; an sdk-cli background-agent transcript is never returned.
# ---------------------------------------------------------------------------------------

class TestNewestSessionInCwdExcludeAndSdkCli(_ProjectsDirCase):
    def test_excluded_id_is_skipped_in_favour_of_the_next_best_survivor(self):
        cwd = "/tmp/proj"
        after_ts = time.time() - 100000.0
        newer = self._path("claimed-newer")
        _write_session(newer, cwd=cwd, first_epoch=after_ts + 50)
        older = self._path("unclaimed-older")
        _write_session(older, cwd=cwd, first_epoch=after_ts + 10)

        got = claude_provider.newest_session_in_cwd(cwd, after_ts, exclude=("claimed-newer",))
        self.assertEqual(got, "unclaimed-older")

    def test_excluding_the_only_candidate_yields_no_match(self):
        cwd = "/tmp/proj"
        after_ts = time.time() - 100000.0
        only = self._path("only-one")
        _write_session(only, cwd=cwd, first_epoch=after_ts + 10)

        self.assertEqual(
            claude_provider.newest_session_in_cwd(cwd, after_ts, exclude=("only-one",)), "")

    def test_sdk_cli_background_agent_transcript_is_never_returned(self):
        cwd = "/tmp/proj"
        after_ts = time.time() - 100000.0
        agent = self._path("bg-agent")
        _write_session(agent, cwd=cwd, first_epoch=after_ts + 10, sdk_cli=True)

        self.assertEqual(claude_provider.newest_session_in_cwd(cwd, after_ts), "",
                          "an sdk-cli agent transcript must never be mistaken for the human "
                          "session a terminal is polling for")

    def test_sdk_cli_transcript_is_skipped_even_when_a_real_human_session_also_qualifies(self):
        cwd = "/tmp/proj"
        after_ts = time.time() - 100000.0
        agent = self._path("bg-agent")
        _write_session(agent, cwd=cwd, first_epoch=after_ts + 90, sdk_cli=True)  # newest by start
        human = self._path("human-session")
        _write_session(human, cwd=cwd, first_epoch=after_ts + 10)

        self.assertEqual(claude_provider.newest_session_in_cwd(cwd, after_ts), "human-session")


# ---------------------------------------------------------------------------------------
# (d) A session with an unknown/unparseable start (first == 0.0) is not returned.
# ---------------------------------------------------------------------------------------

class TestNewestSessionInCwdUnknownStart(_ProjectsDirCase):
    def test_unparseable_start_is_excluded_even_though_cwd_and_mtime_match(self):
        cwd = "/tmp/proj"
        after_ts = time.time() - 100000.0
        bad = self._path("no-timestamp")
        _write_session(bad, cwd=cwd, no_timestamp=True)
        os.utime(bad, (after_ts + 30, after_ts + 30))   # mtime alone would look like a match

        self.assertEqual(claude_provider.newest_session_in_cwd(cwd, after_ts), "")

    def test_unknown_start_does_not_shadow_a_genuinely_new_session_in_the_same_cwd(self):
        cwd = "/tmp/proj"
        after_ts = time.time() - 100000.0
        bad = self._path("no-timestamp")
        _write_session(bad, cwd=cwd, no_timestamp=True)
        os.utime(bad, (after_ts + 30, after_ts + 30))
        good = self._path("real-new-session")
        _write_session(good, cwd=cwd, first_epoch=after_ts + 15)

        self.assertEqual(claude_provider.newest_session_in_cwd(cwd, after_ts), "real-new-session")


# ---------------------------------------------------------------------------------------
# (f) PARITY -- both front-ends render the server-owned `t.suffix` field.
# ---------------------------------------------------------------------------------------

class TestSuffixRenderedInBothFrontEnds(unittest.TestCase):
    """Static source-text check, same idiom tests/test_view_parity.py already uses to catch a
    capability fixed in only one UI: conventions rule 4/5 says a capability lives on the
    shared shape and must be read by every renderer, never re-derived or landed in only one."""

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _read(self, name):
        with open(os.path.join(self._ROOT, "aitracker", "web", name), encoding="utf-8") as fh:
            return fh.read()

    def test_control_room_dialog_renders_suffix(self):
        src = self._read("ext_cr_dialogs.js")
        self.assertIn("t.suffix", src)

    def test_classic_dashboard_renders_suffix(self):
        src = self._read("ext_vt.js")
        self.assertIn("t.suffix", src)


if __name__ == "__main__":
    unittest.main()
