#!/usr/bin/env python3
"""Fork lineage: linking a `claude --resume` that got refused and retried with
`--fork-session` (a COPY under a brand-new session id) back to the session it came
from, and surfacing that link at the shared seam so every provider's session-list
and detail dicts carry it.

There is no on-disk fork lineage from Claude Code itself: `parentUuid` is an
intra-session message-chain pointer (each line's parentUuid == the previous line's
uuid, same sessionId), not a fork pointer; `parentSessionId`/`forkedFrom`/
`originalSessionId` do not exist anywhere in the transcript format (verified
against real transcripts). What DOES link a fork to its parent: a forked session
is a logical copy of the parent's message chain, so parent and child share the
SAME `uuid` values on their early messages (an empirical scan of 1686 real
transcripts across 3 repos found 8 genuine fork pairs, sharing 14-508 early uuids
each, zero false positives at a >=3-shared-uuid threshold). See aitracker/store.py's
"fork lineage" section for the full rationale and the resolver itself.
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import uuid as uuidlib
from unittest import mock

from aitracker import config, term_vt
from aitracker import store as store_mod
from aitracker.store import record_fork, resolve_fork_child, fork_parent_of, _load_forks
from aitracker.registry import all_sessions, parse_any
from aitracker.providers import auggie as _auggie
from aitracker.providers import augment_ext as _augment_ext
from aitracker.providers import claude as _claude
from aitracker.term_vt import Screen


def _u():
    return str(uuidlib.uuid4())


def _write_lines(path, lines):
    with open(path, "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")


def _mk_transcript(root, sid, cwd, mtime, uuids, session_id=None, bookkeeping_first=False,
                    subdir="proj"):
    """A realistic-shaped transcript at config.PROJECTS/<subdir>/<sid>.jsonl: one
    line per uuid in `uuids` (real key names -- uuid, parentUuid, sessionId, cwd,
    type, timestamp, entrypoint, gitBranch, isSidechain), optionally preceded by a
    bookkeeping line (type `queue-operation`) that carries no uuid at all -- real
    transcripts have these interspersed. `session_id` lets a test simulate the
    observed fork variant that keeps the PARENT's own sessionId on copied lines
    instead of rewriting it to the new sid."""
    d = os.path.join(root, subdir)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, sid + ".jsonl")
    sess = sid if session_id is None else session_id
    lines = []
    if bookkeeping_first:
        lines.append({"type": "queue-operation", "operation": "enqueue",
                       "timestamp": "2026-01-01T00:00:00.000Z", "sessionId": sess})
    prev = None
    for u in uuids:
        lines.append({
            "type": "user", "isSidechain": False, "uuid": u, "parentUuid": prev,
            "sessionId": sess, "cwd": cwd, "timestamp": "2026-01-01T00:00:00.000Z",
            "entrypoint": "cli", "gitBranch": "main",
            "message": {"role": "user", "content": "hi"},
        })
        prev = u
    _write_lines(p, lines)
    os.utime(p, (mtime, mtime))
    return p


class TestForkFollow(unittest.TestCase):
    def setUp(self):
        self._snap = {k: getattr(config, k) for k in
                      ("PROJECTS", "FORKS_FILE", "TITLES_FILE", "PINS_FILE", "NOTES_FILE",
                       "FLAGS_FILE", "AUGMENT_DIR", "AUGGIE_SESSIONS",
                       "VSCODE_WS_ROOT", "CURSOR_WS_ROOT")}
        config.PROJECTS = tempfile.mkdtemp()
        config.FORKS_FILE = tempfile.mktemp(suffix=".json")
        config.TITLES_FILE = tempfile.mktemp(suffix=".json")
        config.PINS_FILE = tempfile.mktemp(suffix=".json")
        config.NOTES_FILE = tempfile.mktemp(suffix=".json")
        config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.VSCODE_WS_ROOT = tempfile.mkdtemp()
        config.CURSOR_WS_ROOT = tempfile.mkdtemp()
        _auggie._AUGGIE_LIST_CACHE.clear()
        _claude._META_CACHE.clear()

    def tearDown(self):
        for d in (config.PROJECTS, config.AUGMENT_DIR, config.VSCODE_WS_ROOT, config.CURSOR_WS_ROOT):
            shutil.rmtree(d, ignore_errors=True)
        for k, v in self._snap.items():
            setattr(config, k, v)
        _auggie._AUGGIE_LIST_CACHE.clear()
        _claude._META_CACHE.clear()

    # --- record + resolve: the uuid-overlap predicate -----------------------

    def test_record_then_resolve_finds_child(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(6)]
        _mk_transcript(config.PROJECTS, "parent1", "/work/repo", at - 30, parent_uuids)
        record_fork("parent1", "/work/repo", at)
        child_uuids = parent_uuids[:4] + [_u()]
        _mk_transcript(config.PROJECTS, "child1", "/work/repo", at + 2, child_uuids)
        self.assertEqual(resolve_fork_child("parent1"), "child1")

    def test_parent_never_matches_itself(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        p = _mk_transcript(config.PROJECTS, "parentX", "/work/repo", at - 30, parent_uuids)
        record_fork("parentX", "/work/repo", at)
        # a fork never deletes the original -- the parent's OWN transcript is still sitting
        # right there and would otherwise satisfy every criterion (cwd, mtime, its own uuids
        # trivially "overlapping" itself) if it weren't explicitly excluded by sid.
        os.utime(p, (at + 2, at + 2))
        self.assertEqual(resolve_fork_child("parentX"), "")

    def test_different_cwd_not_matched(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "parent2", "/work/repo", at - 30, parent_uuids)
        record_fork("parent2", "/work/repo", at)
        # shares uuids (shouldn't happen for a genuinely unrelated session, but this pins that
        # cwd is still checked as a cheap prefilter, independent of the uuid predicate) in a
        # DIFFERENT cwd -- must not match.
        _mk_transcript(config.PROJECTS, "unrelated2", "/somewhere/else", at + 2, parent_uuids[:4])
        self.assertEqual(resolve_fork_child("parent2"), "")

    def test_unresolved_returns_empty_and_does_not_raise(self):
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "parent5", "/work/repo", time.time() - 30, parent_uuids)
        record_fork("parent5", "/work/repo", time.time())
        self.assertEqual(resolve_fork_child("parent5"), "")           # fork hasn't written yet
        self.assertEqual(resolve_fork_child("never-recorded"), "")    # not a fork parent at all

    def test_memoized_after_first_resolve(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "parent6", "/work/repo", at - 30, parent_uuids)
        record_fork("parent6", "/work/repo", at)
        _mk_transcript(config.PROJECTS, "child6", "/work/repo", at + 2, parent_uuids[:4])
        self.assertEqual(resolve_fork_child("parent6"), "child6")
        # blow PROJECTS away entirely and replace it -- a fresh scan would find nothing
        shutil.rmtree(config.PROJECTS, ignore_errors=True)
        config.PROJECTS = tempfile.mkdtemp()
        self.assertEqual(resolve_fork_child("parent6"), "child6")     # still comes back: memoized

    def test_malformed_lines_do_not_raise(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "parent7", "/work/repo", at - 30, parent_uuids)
        record_fork("parent7", "/work/repo", at)
        d = os.path.join(config.PROJECTS, "proj")
        os.makedirs(d, exist_ok=True)
        # a truncated/garbage first line, then valid lines carrying the shared uuids -- must
        # tolerate and keep reading rather than blow up or give up after line 1.
        p = os.path.join(d, "child7.jsonl")
        with open(p, "w") as fh:
            fh.write("{not json at all\n")
            for u in parent_uuids[:4]:
                fh.write(json.dumps({"type": "user", "uuid": u, "cwd": "/work/repo",
                                      "sessionId": "child7",
                                      "message": {"role": "user", "content": "go"}}) + "\n")
        os.utime(p, (at + 2, at + 2))
        # a completely empty transcript alongside it must not raise either
        empty = os.path.join(d, "empty7.jsonl")
        open(empty, "w").close()
        os.utime(empty, (at + 2, at + 2))
        self.assertEqual(resolve_fork_child("parent7"), "child7")

    def test_fork_parent_of_reverse_lookup(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "parentR", "/work/repo", at - 30, parent_uuids)
        record_fork("parentR", "/work/repo", at)
        _mk_transcript(config.PROJECTS, "childR", "/work/repo", at + 2, parent_uuids[:4])
        self.assertEqual(resolve_fork_child("parentR"), "childR")   # resolve + memoize first
        self.assertEqual(fork_parent_of("childR"), "parentR")
        self.assertEqual(fork_parent_of("nobody"), "")

    # --- the five reproduced defects, pinned as regression tests ------------

    def test_defect1_unrelated_session_same_cwd_after_fork_not_returned(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "dparent1", "/work/repo", at - 30, parent_uuids)
        record_fork("dparent1", "/work/repo", at)
        # an unrelated session that happens to START in the same cwd shortly after the fork --
        # must not be returned, and must not get memoized as a wrong permanent answer.
        _mk_transcript(config.PROJECTS, "unrelated", "/work/repo", at + 2, [_u() for _ in range(5)])
        self.assertEqual(resolve_fork_child("dparent1"), "")
        forks = _load_forks()
        self.assertEqual(forks["dparent1"]["child"], "", "must not memoize the wrong answer")

    def test_defect2_ancient_transcript_touched_after_fork_loses_to_real_child(self):
        at = time.time() - 100
        parent_uuids = [_u() for _ in range(6)]
        _mk_transcript(config.PROJECTS, "dparent2", "/work/repo", at - 30, parent_uuids)
        record_fork("dparent2", "/work/repo", at)
        # an ancient, unrelated transcript in the same cwd -- created long before the fork, but
        # merely APPENDED TO (mtime bumped) just after the fork instant. Old mtime-only logic
        # called this "oldest qualifying" and let it win outright.
        ancient_path = _mk_transcript(config.PROJECTS, "ancient", "/work/repo", at - 999999,
                                       [_u() for _ in range(4)])
        os.utime(ancient_path, (at + 1, at + 1))
        # the real child appears with a LATER mtime than "ancient" -- must still win, because
        # the decision is uuid overlap, not earliest-mtime.
        _mk_transcript(config.PROJECTS, "dchild2", "/work/repo", at + 50, parent_uuids[:4] + [_u()])
        self.assertEqual(resolve_fork_child("dparent2"), "dchild2")

    def test_defect3_session_created_shortly_before_fork_not_returned(self):
        at = time.time()
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "dparent3", "/work/repo", at - 30, parent_uuids)
        record_fork("dparent3", "/work/repo", at)
        # created 3s BEFORE the fork instant (inside the old `at - 5` mtime-tolerance window) --
        # unrelated, no shared uuids, in the same cwd. The old resolver treated the mtime floor
        # AS the decision, so anything inside that tolerance and lacking a later real candidate
        # won outright. Must not be returned now that the decision is uuid overlap, not mtime.
        _mk_transcript(config.PROJECTS, "stale3", "/work/repo", at - 3, [_u() for _ in range(5)])
        self.assertEqual(resolve_fork_child("dparent3"), "")

    def test_defect4_permanent_memoization_gone_real_child_wins_after_stranger(self):
        """The permanent-wrong-answer defect: an unrelated session in the same cwd must not
        get memoized before the real child even shows up, AND once the real child appears on
        a LATER poll, it must still be found (there is no "already decided, stop looking"
        state short of an actual uuid match)."""
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(6)]
        _mk_transcript(config.PROJECTS, "dparent4", "/work/repo", at - 30, parent_uuids)
        record_fork("dparent4", "/work/repo", at)
        _mk_transcript(config.PROJECTS, "stranger4", "/work/repo", at + 1, [_u() for _ in range(5)])
        self.assertEqual(resolve_fork_child("dparent4"), "")   # stranger must not "win"
        _mk_transcript(config.PROJECTS, "dchild4", "/work/repo", at + 5, parent_uuids[:4])
        self.assertEqual(resolve_fork_child("dparent4"), "dchild4")   # the real child is still findable

    def test_defect5_uuid_overlap_matches_even_with_parent_sessionid_variant(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(10)]
        _mk_transcript(config.PROJECTS, "dparent5", "/work/repo", at - 30, parent_uuids)
        record_fork("dparent5", "/work/repo", at)
        # A decoy that would WIN on creation-time ordering alone (it's created first, so an
        # implementation that only checked "found something" -- or that let ordering decide
        # instead of the uuid gate -- could wrongly settle on it) but shares only 1 uuid with
        # the parent, below UUID_MATCH_THRESHOLD. It must be passed over.
        _mk_transcript(config.PROJECTS, "decoy5", "/work/repo", at + 1,
                        parent_uuids[:1] + [_u() for _ in range(4)])
        # the forked copy shares 5 of the parent's early uuids, but its `sessionId` field on
        # those copied lines is still the PARENT's id (the observed fork variant) -- must not
        # matter, since matching is by uuid overlap only, never by sessionId.
        _mk_transcript(config.PROJECTS, "dchild5", "/work/repo", at + 3, parent_uuids[:5],
                       session_id="dparent5")
        self.assertEqual(resolve_fork_child("dparent5"), "dchild5",
                          "the decoy (created first, 1 shared uuid) must lose to the real "
                          "child (created later, 5 shared uuids) -- uuid overlap decides")

    # --- creation-time ordering (the fork-of-a-fork defect) -----------------
    #
    # `st_birthtime` cannot be set with os.utime (unlike mtime), and real per-file creation
    # gaps within a single fast unittest run are microseconds/milliseconds -- far too small
    # to reliably sit on either side of the resolver's 5s floor tolerance the way a REAL
    # fork-vs-ancestor gap would in production (minutes/hours apart). So these tests patch
    # store._creation_time directly: the exact "stat-like accessor" seam the resolver already
    # calls through, giving full deterministic control over both the ordering AND the floor
    # exclusion without depending on real filesystem timing at all.

    def _patch_creation_times(self, times):
        """`times`: {sid: fake creation-time float}. Returns a mock.patch context manager for
        store_mod._creation_time that looks up the fake time by the sid encoded in the path
        (matching real _creation_time's signature: path in, float out)."""
        def fake(path):
            sid = os.path.basename(path)[:-6]
            return times[sid]
        return mock.patch.object(store_mod, "_creation_time", side_effect=fake)

    def test_fork_of_a_fork_grandchild_not_claimed_by_grandparent(self):
        """A forks to B, then B forks to C. Because a fork copies the parent's chain, C
        shares enough early uuids with A TRANSITIVELY (via B) to also clear A's threshold --
        so resolving A's own child has two passing candidates, B and C. B's mtime gets bumped
        (simulating it "staying active") to LATER than C's real mtime -- the exact reported
        repro. mtime must not decide: resolve_fork_child("A") must still return B (the direct
        child, created first), never C (the grandchild), and resolve_fork_child("B") must
        return C -- with A correctly excluded from B's own candidate scan (A predates B's own
        fork instant, so the floor filters it out)."""
        base = time.time()
        a_uuids = [_u() for _ in range(5)]
        b_uuids = a_uuids + [_u()]
        c_uuids = b_uuids + [_u()]
        _mk_transcript(config.PROJECTS, "gpA", "/work/repo", base, a_uuids)
        record_fork("gpA", "/work/repo", base)                # A's own fork instant
        b_path = _mk_transcript(config.PROJECTS, "gpB", "/work/repo", base + 10, b_uuids)
        record_fork("gpB", "/work/repo", base + 1000)         # B's OWN fork instant (later --
                                                                # B ran a while before forking again)
        c_path = _mk_transcript(config.PROJECTS, "gpC", "/work/repo", base + 1010, c_uuids)
        # B "stays active": its REAL mtime is bumped to after C's, exactly as the reported
        # defect describes. The fix must ignore this -- see the mocked creation times below.
        os.utime(b_path, (base + 2000, base + 2000))
        self.assertGreater(os.path.getmtime(b_path), os.path.getmtime(c_path),
                            "sanity: the repro requires B's real mtime to end up later than C's")

        fake_ct = {"gpA": base, "gpB": base + 10, "gpC": base + 1010}
        with self._patch_creation_times(fake_ct):
            self.assertEqual(resolve_fork_child("gpA"), "gpB",
                              "must pick the direct child B, never the grandchild C, and must "
                              "not be fooled by B's bumped mtime")
            self.assertEqual(resolve_fork_child("gpB"), "gpC")

        forks = _load_forks()
        self.assertEqual(forks["gpA"]["child"], "gpB")
        self.assertNotEqual(forks["gpA"]["child"], "gpC", "C must never be claimed by A")

    def test_two_forks_of_one_parent_earlier_created_wins_and_is_stable(self):
        """Two direct forks of the same parent both clear the threshold -- the corollary of
        the same root cause (mtime deciding among multiple passing candidates). The
        earlier-CREATED one must win, and the choice must be the same every time the
        selection is re-run (not an accident of iteration order)."""
        base = time.time()
        p_uuids = [_u() for _ in range(5)]
        q_uuids = p_uuids + [_u()]
        r_uuids = p_uuids + [_u()]
        _mk_transcript(config.PROJECTS, "twoP", "/work/repo", base, p_uuids)
        record_fork("twoP", "/work/repo", base)
        _mk_transcript(config.PROJECTS, "twoQ", "/work/repo", base + 10, q_uuids)   # created first
        _mk_transcript(config.PROJECTS, "twoR", "/work/repo", base + 20, r_uuids)   # created second

        # saved BEFORE the first resolve below, which drops `pre_existing` once it resolves
        # (defect 3's fix: dead weight once resolved) -- needed to restore it afterward so the
        # forced re-scan isn't sabotaged by an unrelated space optimization; see its use below.
        saved_pre_existing = _load_forks()["twoP"].get("pre_existing", [])

        fake_ct = {"twoP": base, "twoQ": base + 10, "twoR": base + 20}
        with self._patch_creation_times(fake_ct):
            self.assertEqual(resolve_fork_child("twoP"), "twoQ",
                              "the earlier-created fork (twoQ) must win over twoR")
            # re-run the underlying selection (not just the memoized lookup) to confirm the
            # policy itself is stable, not merely "whatever got memoized first". Clearing `child`
            # back to "" to force a re-scan would otherwise trip gate 1's "unusable snapshot"
            # refusal now that resolving above dropped `pre_existing` -- restore it, since that
            # refusal is unrelated to what this test is actually probing (tie-break stability).
            def clear_child(f):
                f["twoP"]["child"] = ""
                f["twoP"]["pre_existing"] = saved_pre_existing
            store_mod._update_forks(clear_child)
            self.assertEqual(resolve_fork_child("twoP"), "twoQ",
                              "re-resolving from scratch must reach the same answer")

    def test_mtime_cannot_override_creation_order(self):
        """A candidate whose (real) mtime is bumped to be the EARLIEST of all candidates must
        still lose to the genuinely-earlier-created true child -- mtime must have zero
        influence on the decision now that creation time is what orders candidates."""
        base = time.time()
        p_uuids = [_u() for _ in range(5)]
        true_child_uuids = p_uuids + [_u()]
        decoy_uuids = p_uuids + [_u()]
        _mk_transcript(config.PROJECTS, "mtP", "/work/repo", base, p_uuids)
        record_fork("mtP", "/work/repo", base)
        # true child created FIRST (real and fake creation time both earlier)
        true_path = _mk_transcript(config.PROJECTS, "mtTrue", "/work/repo", base + 10, true_child_uuids)
        # decoy created SECOND, but its mtime is rewritten to be the oldest of the two --
        # if mtime had any influence, the decoy would sort first and win.
        decoy_path = _mk_transcript(config.PROJECTS, "mtDecoy", "/work/repo", base + 20, decoy_uuids)
        os.utime(decoy_path, (1, 1))
        self.assertLess(os.path.getmtime(decoy_path), os.path.getmtime(true_path),
                         "sanity: the decoy's real mtime must be earlier than the true child's")

        fake_ct = {"mtP": base, "mtTrue": base + 10, "mtDecoy": base + 20}   # decoy created LATER
        with self._patch_creation_times(fake_ct):
            self.assertEqual(resolve_fork_child("mtP"), "mtTrue")

    def test_tie_break_is_explicit_and_by_session_id(self):
        """Two candidates with the EXACT SAME creation time (a genuine tie) must resolve
        deterministically -- by session id, not by glob's filesystem-dependent iteration
        order. `tieB` is created before `tieA` in this test's code, so if id were NOT what
        broke the tie, creation-CALL order would favor tieB; the resolver must still pick
        tieA (the lexicographically smaller id), and consistently so."""
        base = time.time()
        p_uuids = [_u() for _ in range(5)]
        b_uuids = p_uuids + [_u()]
        a_uuids = p_uuids + [_u()]
        _mk_transcript(config.PROJECTS, "tieP", "/work/repo", base, p_uuids)
        record_fork("tieP", "/work/repo", base)
        _mk_transcript(config.PROJECTS, "tieB", "/work/repo", base + 10, b_uuids)   # coded first
        _mk_transcript(config.PROJECTS, "tieA", "/work/repo", base + 10, a_uuids)   # coded second

        # saved BEFORE the first resolve below, which drops `pre_existing` once it resolves
        # (defect 3's fix) -- restored below so the forced re-scan isn't sabotaged by that
        # unrelated space optimization; see test_two_forks_of_one_parent_...'s comment for detail.
        saved_pre_existing = _load_forks()["tieP"].get("pre_existing", [])

        fake_ct = {"tieP": base, "tieB": base + 10, "tieA": base + 10}   # exact tie
        with self._patch_creation_times(fake_ct):
            self.assertEqual(resolve_fork_child("tieP"), "tieA")
            def clear_child(f):
                f["tieP"]["child"] = ""
                f["tieP"]["pre_existing"] = saved_pre_existing
            store_mod._update_forks(clear_child)
            self.assertEqual(resolve_fork_child("tieP"), "tieA", "tie-break must be stable")

    # --- widen fallback: gone entirely ---------------------------------------

    def test_widen_fallback_and_its_throttle_state_are_gone(self):
        """The old WIDE (every-project-dir) fallback and its throttle bookkeeping must no
        longer exist at all -- not merely be unreachable."""
        self.assertFalse(hasattr(store_mod, "WIDEN_THROTTLE_SECS"))
        self.assertFalse(hasattr(store_mod, "_last_widen_attempt"))

    def test_child_in_a_different_project_dir_is_never_found(self):
        """A fork always keeps the terminal's cwd, so the child is expected in the parent's
        OWN project directory -- the search no longer widens to every project directory if
        the narrow one comes up empty. A transcript that would otherwise match (right uuids,
        right cwid) but lands in an unrelated project directory must never be returned, and
        the narrow scan finding nothing must not raise or behave differently."""
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "narrowP", "/work/repo", at - 30, parent_uuids,
                        subdir="projA")
        record_fork("narrowP", "/work/repo", at)
        # matches everything (uuids, cwd) but sits in a DIFFERENT project directory
        _mk_transcript(config.PROJECTS, "elsewhereChild", "/work/repo", at + 2,
                        parent_uuids[:4], subdir="projB")
        self.assertEqual(resolve_fork_child("narrowP"), "")
        self.assertEqual(_load_forks()["narrowP"]["child"], "",
                          "must not memoize a wrong answer, and must not find it later either")

    # --- the snapshot (pre_existing) is the deciding factor, not timing -----

    def test_pre_existing_candidate_rejected_even_with_uuid_overlap(self):
        """A session that already existed in the parent's directory BEFORE the fork -- even
        one that (contrived, to isolate the snapshot as the deciding factor) shares enough
        early uuids with the parent to clear the uuid gate, AND was created earlier in real
        wall-clock order than the genuine child (so ordering alone would also have picked it)
        -- must never be returned. Real files, real os.stat.

        Deliberately does NOT backdate peOld's mtime the way `_mk_transcript`'s `mtime` param
        usually does for other tests here: on this machine's filesystem, os.utime with an
        mtime EARLIER than a file's current birthtime drags birthtime down to match (verified
        directly against os.stat -- backdating mtime by 100s lowered st_birthtime by the same
        100s). Backdating peOld here would incidentally also satisfy the OLD `at - 5` floor
        heuristic, making this pass for the wrong reason. Passing a non-backdated mtime keeps
        peOld's REAL birthtime at its actual (recent) creation instant, so the exclusion below
        is provably coming from the pre_existing snapshot, not from a timing coincidence."""
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(6)]
        _mk_transcript(config.PROJECTS, "peP", "/work/repo", at - 30, parent_uuids)
        # already on disk BEFORE record_fork's snapshot is taken -- e.g. a stale leftover from
        # an earlier, unrelated fork of the same parent that shares uuids by construction here.
        # mtime = at + 1 (not backdated) so its REAL birthtime stays at actual creation time.
        _mk_transcript(config.PROJECTS, "peOld", "/work/repo", at + 1, parent_uuids[:4])
        record_fork("peP", "/work/repo", at)   # snapshot now includes peP and peOld
        # the genuine new child, created AFTER the snapshot (and so, in real wall-clock terms,
        # AFTER peOld too -- ordering alone would already prefer peOld here, which is exactly
        # why this only proves the fix if peOld is excluded by the snapshot, not by timing)
        _mk_transcript(config.PROJECTS, "peChild", "/work/repo", at + 2,
                        parent_uuids[:4] + [_u()])
        self.assertEqual(resolve_fork_child("peP"), "peChild",
                          "peOld passes the uuid gate and was created first -- only the "
                          "pre_existing snapshot can be why it loses")

    def test_pre_existing_candidate_rejected_even_when_touched_after_fork(self):
        """The same pre-existing-and-excluded session, but additionally TOUCHED (mtime bumped
        FORWARD, past the fork instant -- a forward bump cannot lower birthtime, only backdating
        can, per the filesystem quirk documented above) after the fork instant -- confirming
        touching a file's mtime, which is exactly what fooled round 1, has zero effect on the
        snapshot-based decision now."""
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(6)]
        _mk_transcript(config.PROJECTS, "ptP", "/work/repo", at - 30, parent_uuids)
        old_path = _mk_transcript(config.PROJECTS, "ptOld", "/work/repo", at + 1,
                                   parent_uuids[:4])
        record_fork("ptP", "/work/repo", at)
        os.utime(old_path, (at + 100, at + 100))   # touched well after the fork instant
        _mk_transcript(config.PROJECTS, "ptChild", "/work/repo", at + 2,
                        parent_uuids[:4] + [_u()])
        self.assertEqual(resolve_fork_child("ptP"), "ptChild")

    # --- the snapshot-empty-vs-snapshot-failed sentinel (defect 1) ----------
    #
    # The reviewer's proof against the pre-fix code: `os.listdir()` for the pre_existing snapshot
    # raised OSError once (a transient EMFILE/NFS-style hiccup), the parent's transcript read fine
    # regardless, and the old code's bare `except OSError: pre_existing = []` silently turned that
    # failure into an empty list -- indistinguishable from a directory that genuinely had nothing
    # in it. With `pre_existing` empty, gate 1 became a no-op and resolution fell back to
    # "earliest-created uuid-passing candidate" -- the ordering heuristic that broke rounds 1-3 --
    # and returned a genuinely PRE-EXISTING stale sibling (`peOldSibling`-shaped) instead of the
    # real child. The fix distinguishes the two cases with a sentinel (`None` == listdir failed,
    # `[]` == listdir succeeded and found nothing) and refuses to resolve at all when it sees the
    # failure sentinel.

    def test_list_jsonl_ids_empty_dir_is_usable_not_failed(self):
        """A genuinely empty (but successfully LISTED) directory must be `[]`, the USABLE case --
        not the `None` failure sentinel. Direct test of the sentinel's other half."""
        empty_dir = tempfile.mkdtemp()
        try:
            self.assertEqual(store_mod._list_jsonl_ids(empty_dir), [],
                              "a directory that exists and is empty must return [], not None")
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    def test_list_jsonl_ids_returns_none_sentinel_after_persistent_listdir_failure(self):
        """A listdir that NEVER succeeds (every retry exhausted) must come back as the `None`
        sentinel -- never a silently-empty `[]`, which is exactly the pre-fix bug (an empty list
        is indistinguishable from "nothing was there", so gate 1 in resolve_fork_child would
        become a no-op instead of refusing to resolve)."""
        with mock.patch.object(store_mod.os, "listdir", side_effect=OSError("EMFILE")) as ld:
            self.assertIsNone(store_mod._list_jsonl_ids("/some/dir"),
                               "a persistently failing listdir must be the None sentinel, not []")
            self.assertEqual(ld.call_count, store_mod._LISTDIR_RETRIES,
                              "must retry a couple of times before giving up, per the brief")

    def test_single_transient_listdir_failure_is_absorbed_by_retry(self):
        """A ONE-TIME transient failure (the reviewer's exact repro shape) must be transparently
        recovered by the retry -- not turned into a lost snapshot. This is the other side of
        defect 1's fix: retrying is what lets a merely-flaky filesystem still produce a correct,
        USABLE pre_existing list instead of unnecessarily falling back to "stay unresolved"."""
        real_listdir = os.listdir
        calls = {"n": 0}

        def flaky(path):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("EMFILE (transient)")
            return real_listdir(path)

        d = tempfile.mkdtemp()
        try:
            open(os.path.join(d, "sibling.jsonl"), "w").close()
            with mock.patch.object(store_mod.os, "listdir", side_effect=flaky):
                result = store_mod._list_jsonl_ids(d)
            self.assertEqual(result, ["sibling"],
                              "one transient failure must be absorbed by retry, not reported as None")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_flaky_listdir_at_record_time_never_returns_the_stale_sibling(self):
        """Integration-level version of the reviewer's exact scenario: `os.listdir` fails on
        EVERY attempt made during the snapshot capture at record_fork time (persistent, not just
        once -- see the two unit tests above for why a single flaky call is instead transparently
        recovered by the retry and must NOT reach this failure path at all). A stale sibling
        (`peOldSibling`-shaped: pre-existing, but sharing enough uuids to clear the uuid gate, and
        created earlier than the real child) sits on disk. Against the PRE-FIX code this returns
        the stale sibling; the fix must instead leave the fork unresolved and mark the record's
        snapshot unusable, never guessing."""
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(6)]
        _mk_transcript(config.PROJECTS, "flakyP", "/work/repo", at - 30, parent_uuids)
        # already on disk before record_fork's snapshot attempt -- shares uuids by construction,
        # so it would clear the uuid gate and (on the pre-fix code) win as "earliest-created".
        _mk_transcript(config.PROJECTS, "peOldSibling", "/work/repo", at - 20, parent_uuids[:4])

        with mock.patch.object(store_mod.os, "listdir", side_effect=OSError("EMFILE")):
            record_fork("flakyP", "/work/repo", at)

        rec = _load_forks()["flakyP"]
        self.assertIsNone(rec.get("pre_existing"),
                           "a listdir that failed on every attempt must record the None sentinel, "
                           "not a silently-empty list")

        _mk_transcript(config.PROJECTS, "flakyChild", "/work/repo", at + 2,
                        parent_uuids[:4] + [_u()])
        self.assertEqual(resolve_fork_child("flakyP"), "",
                          "an unusable snapshot must never resolve -- not to the stale sibling, "
                          "and not even to the genuine child yet -- it must stay unresolved and "
                          "be retried, never guess")
        self.assertEqual(_load_forks()["flakyP"]["child"], "",
                          "must not memoize a wrong (or even accidentally right) answer against "
                          "an unusable snapshot")

    # --- the snapshot is dead weight once resolved / abandoned (defect 3) ---

    def test_pre_existing_dropped_from_record_after_resolution(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "shrinkP", "/work/repo", at - 30, parent_uuids)
        record_fork("shrinkP", "/work/repo", at)
        self.assertIn("pre_existing", _load_forks()["shrinkP"], "present before resolution")
        _mk_transcript(config.PROJECTS, "shrinkC", "/work/repo", at + 2, parent_uuids[:4])
        self.assertEqual(resolve_fork_child("shrinkP"), "shrinkC")
        rec = _load_forks()["shrinkP"]
        self.assertNotIn("pre_existing", rec,
                          "the snapshot is dead weight once resolved -- must be dropped")
        self.assertEqual(rec["child"], "shrinkC", "the resolution itself must be unaffected")

    def test_pre_existing_dropped_from_record_after_give_up(self):
        old_at = time.time() - store_mod.GIVE_UP_SECS - 10
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "shrinkG", "/work/repo", old_at - 30, parent_uuids)
        record_fork("shrinkG", "/work/repo", old_at)
        self.assertIn("pre_existing", _load_forks()["shrinkG"], "present before giving up")
        self.assertEqual(resolve_fork_child("shrinkG"), "")
        rec = _load_forks()["shrinkG"]
        self.assertTrue(rec["abandoned"])
        self.assertNotIn("pre_existing", rec,
                          "dead weight once abandoned too -- must be dropped")

    # --- the round-3 killer: the exact defect shape, at every real gap ------

    def test_round3_killer_grandparent_never_returned_at_any_real_gap(self):
        """THE test that would have caught round 3. A forks to B (a real copy of A's chain,
        so B's early uuids are a superset of A's), then B forks to C (a real copy of B's
        chain, so C's early uuids transitively include A's too) after `gap` REAL seconds
        since B's own creation. The refuted round-3 code returned A -- B's own GRANDPARENT,
        structurally impossible since A predates B -- whenever that gap was small (~<5s,
        because its floor was `at - 5` keyed to B's OWN fork instant). The shipped regression
        test for this shape used a 1000-second gap, which never touches that window and so
        never exercised the bug -- the trap this test is written specifically to avoid.

        Real files, real os.stat, real time.sleep() for the gap -- no mocking. Mocking
        _creation_time is exactly what let the round-3 code's own test suite go green while
        broken, so this one drives the actual code path against real timestamps instead, at
        gaps small enough (0s) and large enough (10s) to bracket the old failure window."""
        for gap in (0, 1, 3, 4.5, 10):
            with self.subTest(gap=gap):
                tag = str(gap).replace(".", "_")
                cwd = "/work/repo-round3-%s" % tag
                subdir = "round3_%s" % tag
                a_sid, b_sid, c_sid = "r3A_%s" % tag, "r3B_%s" % tag, "r3C_%s" % tag

                a_uuids = [_u() for _ in range(6)]
                _mk_transcript(config.PROJECTS, a_sid, cwd, time.time(), a_uuids, subdir=subdir)

                # B is a real fork of A: a logical copy of A's chain, so it carries A's early
                # uuids plus its own new ones -- exactly what makes A wrongly clear B's own
                # uuid gate transitively.
                b_uuids = a_uuids + [_u() for _ in range(3)]
                _mk_transcript(config.PROJECTS, b_sid, cwd, time.time(), b_uuids, subdir=subdir)

                if gap:
                    time.sleep(gap)
                # B forks into C `gap` REAL seconds after B's own creation -- record_fork's
                # snapshot for B is taken NOW, so it captures both a_sid and b_sid as already
                # existing (neither can ever be B's own child), regardless of how small `gap` is.
                record_fork(b_sid, cwd, time.time())

                # C is a real fork of B: copies B's chain (and so, transitively, A's uuids too)
                c_uuids = b_uuids + [_u() for _ in range(3)]
                _mk_transcript(config.PROJECTS, c_sid, cwd, time.time(), c_uuids, subdir=subdir)

                resolved = resolve_fork_child(b_sid)
                self.assertEqual(resolved, c_sid,
                                  "gap=%ss: resolve_fork_child(B) must be C" % gap)
                self.assertNotEqual(resolved, a_sid,
                                     "gap=%ss: must never return A, B's own grandparent" % gap)

    # --- threshold, bookkeeping lines, give-up window, unscanned sids -------

    def test_threshold_pinned_at_three(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(10)]
        _mk_transcript(config.PROJECTS, "parentT", "/work/repo", at - 30, parent_uuids)
        record_fork("parentT", "/work/repo", at)
        _mk_transcript(config.PROJECTS, "under3", "/work/repo", at + 2,
                        parent_uuids[:2] + [_u(), _u(), _u()])
        self.assertEqual(resolve_fork_child("parentT"), "", "2 shared uuids must not match")
        _mk_transcript(config.PROJECTS, "at3", "/work/repo", at + 4,
                        parent_uuids[:3] + [_u(), _u(), _u()])
        self.assertEqual(resolve_fork_child("parentT"), "at3", "3 shared uuids must match")

    def test_bookkeeping_lines_without_uuid_are_skipped_not_raised(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "parentB", "/work/repo", at - 30, parent_uuids,
                        bookkeeping_first=True)
        record_fork("parentB", "/work/repo", at)
        _mk_transcript(config.PROJECTS, "childB", "/work/repo", at + 2, parent_uuids[:4],
                        bookkeeping_first=True)
        self.assertEqual(resolve_fork_child("parentB"), "childB")

    def test_gives_up_after_window_and_stops_scanning(self):
        old_at = time.time() - store_mod.GIVE_UP_SECS - 10
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "parentG", "/work/repo", old_at - 30, parent_uuids)
        record_fork("parentG", "/work/repo", old_at)
        # first call: notices the window already passed and abandons (still one scan attempt)
        self.assertEqual(resolve_fork_child("parentG"), "")
        self.assertTrue(_load_forks()["parentG"]["abandoned"])
        # second call: must fast-path to "" WITHOUT touching glob at all
        with mock.patch.object(store_mod.glob, "glob") as g:
            self.assertEqual(resolve_fork_child("parentG"), "")
            g.assert_not_called()

    def test_unrecorded_sid_never_triggers_a_scan(self):
        with mock.patch.object(store_mod.glob, "glob") as g:
            self.assertEqual(resolve_fork_child("never-recorded-anywhere"), "")
            g.assert_not_called()

    # --- concurrency: the crash/lost-write defects in _save_json / record_fork ---

    def test_concurrent_record_fork_for_different_parents_all_survive(self):
        n = 25
        barrier = threading.Barrier(n)
        errors = []

        def worker(i):
            barrier.wait()   # line every thread up so the read/modify/write windows actually overlap
            try:
                record_fork("cparent-%d" % i, "/work/repo", time.time())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        forks = _load_forks()
        for i in range(n):
            self.assertIn("cparent-%d" % i, forks, "record for parent %d was lost" % i)
        self.assertEqual(len(forks), n)

    def test_save_json_concurrent_writers_do_not_raise_or_lose_the_file(self):
        path = tempfile.mktemp(suffix=".json")
        n = 30
        barrier = threading.Barrier(n)
        errors = []

        def worker(i):
            barrier.wait()
            try:
                store_mod._save_json(path, {"i": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)   # must be complete, parseable JSON -- not truncated/half-written
        self.assertIn("i", data)
        os.remove(path)

    # --- the shared seam: registry.all_sessions() / registry.parse_any() -----

    def test_shared_seam_covers_every_provider(self):
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(5)]
        _mk_transcript(config.PROJECTS, "parentS", "/work/repo", at - 30, parent_uuids)  # the original -- still on disk
        record_fork("parentS", "/work/repo", at)
        _mk_transcript(config.PROJECTS, "childS", "/work/repo", at + 2, parent_uuids[:4])

        sessions = all_sessions()
        by_id = {s["id"]: s for s in sessions}
        self.assertEqual(by_id["parentS"]["continued_as"], "childS")
        self.assertEqual(by_id["parentS"]["continued_from"], "")
        self.assertEqual(by_id["childS"]["continued_from"], "parentS")
        self.assertEqual(by_id["childS"]["continued_as"], "")

        d_parent = parse_any("parentS")
        self.assertEqual(d_parent["continued_as"], "childS")
        self.assertEqual(d_parent["continued_from"], "")

        d_child = parse_any("childS")
        self.assertEqual(d_child["continued_from"], "parentS")
        self.assertEqual(d_child["continued_as"], "")

        # a non-Claude provider (Auggie) has no fork concept and no id of its
        # ever recorded in forks.json -- same code path, "" for both, no
        # per-provider branch.
        json.dump({"sessionId": "a1", "modified": "2026-06-27T05:48:03Z",
                   "customTitle": "Auggie thing", "chatHistory": [
                       {"finishedAt": "2026-06-27T05:47:50Z",
                        "exchange": {"request_message": "hi", "response_text": "hey"}}]},
                  open(os.path.join(config.AUGGIE_SESSIONS, "a1.json"), "w"))
        _auggie._AUGGIE_LIST_CACHE.clear()

        sessions2 = all_sessions()
        auggie_s = next(s for s in sessions2 if s["id"] == "auggie:a1")
        self.assertEqual(auggie_s["continued_as"], "")
        self.assertEqual(auggie_s["continued_from"], "")

        d_auggie = parse_any("auggie:a1")
        self.assertIsNotNone(d_auggie)
        self.assertEqual(d_auggie["continued_as"], "")
        self.assertEqual(d_auggie["continued_from"], "")

    def test_parse_any_unknown_id_still_returns_none(self):
        # registry.parse_any's existing 404 contract must survive the new keys.
        self.assertIsNone(parse_any("does-not-exist"))


# --- the ONE call site: term_vt._retry_with_fork feeding store.record_fork -------------------
#
# Everything above tests the lineage LIBRARY in isolation. These tests instead pin the WIRING:
# that the one moment term_vt.py actually knows a fork happened (_retry_with_fork, after a
# refused `claude --resume` is retried with --fork-session) calls store.record_fork with the
# ORIGINAL session id and the pty's own cwd -- not that record_fork/resolve_fork_child work in
# the abstract, which the tests above already cover.
#
# Same technique test_term_vt.py's own TestRetryWithFork uses: `_fork_child` and
# `threading.Thread` are both faked, so nothing here ever forks or execs a real process --
# `store.record_fork` is the only additional fake, since it is the one new thing under test.

def _bare_retry_pty(tid="fk", cwd="/work/repo"):
    """A `Pty` with no real process behind it -- mirrors test_term_vt.py's own `_bare_pty`
    helper, kept local here since these two test modules are independently ownable."""
    return term_vt.Pty(tid=tid, pid=0, fd=-1, screen=Screen(cols=80, rows=24), cwd=cwd)


class TestRetryWithForkRecordsLineage(unittest.TestCase):
    def test_retry_records_original_sid_and_pty_cwd(self):
        pt = _bare_retry_pty(cwd="/work/repo")
        calls = []
        with mock.patch.object(term_vt, "_fork_child", return_value=(4242, 99)), \
             mock.patch.object(term_vt.threading, "Thread"), \
             mock.patch.object(term_vt.store, "record_fork",
                                side_effect=lambda *a: calls.append(a)):
            before = time.time()
            term_vt._retry_with_fork(pt, "original-sid", 80, 24)
            after = time.time()
        self.assertEqual(len(calls), 1)
        # 4 positional args now -- record_fork gained a `snapshot` parameter (defect 2's fix:
        # the snapshot must be captured BEFORE _fork_child's exec and handed in explicitly,
        # never re-derived by record_fork itself on this call path).
        parent_sid, cwd, at, snapshot = calls[0]
        # the ORIGINAL session id -- not pt.id (the tty id) and not any id the fake fork made up
        self.assertEqual(parent_sid, "original-sid")
        # the pty's own cwd, VERBATIM -- resolve_fork_child compares this with no normalization
        self.assertEqual(cwd, "/work/repo")
        self.assertTrue(before - 1 <= at <= after + 1, "must be a plausible unix-epoch timestamp")
        # a real dict from store.capture_fork_snapshot, not None/omitted -- proves _retry_with_fork
        # captures it itself rather than letting record_fork fall back to its own default capture
        self.assertIsInstance(snapshot, dict)
        self.assertIn("pre_existing", snapshot)

    def test_snapshot_captured_before_fork_child_exec_excludes_the_child(self):
        """THE defect-2 regression test: prove `store.capture_fork_snapshot` is called BEFORE
        `_fork_child`'s exec, not after, by making the stubbed `_fork_child` itself write the
        child's transcript to disk as a side effect -- simulating a fast-writing real child, the
        exact race defect 2 describes. If the snapshot were instead captured AFTER the exec (the
        pre-fix ordering), the child's own sid would already be on disk by capture time and would
        wrongly appear in `pre_existing`, permanently excluding the real child from ever
        resolving. `_fork_child` is stubbed (nothing in this suite forks a real process); unlike
        the other wiring tests in this class, `store.record_fork`/`capture_fork_snapshot` are left
        REAL here (not mocked) so the actual record written to forks.json is what gets inspected."""
        snap = {k: getattr(config, k) for k in ("PROJECTS", "FORKS_FILE")}
        config.PROJECTS = tempfile.mkdtemp()
        config.FORKS_FILE = tempfile.mktemp(suffix=".json")
        try:
            parent_uuids = [_u() for _ in range(5)]
            _mk_transcript(config.PROJECTS, "snapParent", "/work/repo", time.time() - 30,
                            parent_uuids)

            def fake_fork_child(cwd, argv, cols, rows):
                # the real child "writing its own transcript" as part of exec/startup -- must
                # happen strictly AFTER the snapshot for the child to ever be resolvable
                _mk_transcript(config.PROJECTS, "snapChild", "/work/repo", time.time(),
                                parent_uuids[:4])
                return (4242, 99)

            pt = _bare_retry_pty(cwd="/work/repo")
            with mock.patch.object(term_vt, "_fork_child", side_effect=fake_fork_child), \
                 mock.patch.object(term_vt.threading, "Thread"):
                term_vt._retry_with_fork(pt, "snapParent", 80, 24)

            rec = _load_forks()["snapParent"]
            self.assertNotIn("snapChild", rec.get("pre_existing") or [],
                              "the snapshot must have been taken BEFORE the child's transcript "
                              "existed on disk -- if it had run after the exec (the pre-fix "
                              "ordering), the child would already be wrongly captured as "
                              "pre-existing and could never resolve")
            # follow through: with the ordering correct, the child must actually be resolvable
            self.assertEqual(resolve_fork_child("snapParent"), "snapChild")
        finally:
            shutil.rmtree(config.PROJECTS, ignore_errors=True)
            for k, v in snap.items():
                setattr(config, k, v)

    def test_abandon_path_does_not_record_a_fork(self):
        """`_retry_with_fork`'s abandon branch (pt.closing already set -- the pty was closed
        while the fork was in flight) must NEVER call record_fork: there is no surviving pty for
        the recorded lineage to ever be surfaced against."""
        pt = _bare_retry_pty()
        pt.closing = True
        with mock.patch.object(term_vt, "_fork_child", return_value=(999999, 999998)), \
             mock.patch.object(term_vt.threading, "Thread"), \
             mock.patch.object(term_vt.store, "record_fork") as record_fork:
            term_vt._retry_with_fork(pt, "abandoned-sid", 80, 24)
        record_fork.assert_not_called()
        self.assertFalse(pt.forked, "the abandoned retry must not be swapped in")

    def test_capture_failure_records_unusable_sentinel_and_refuses_not_self_captures(self):
        """THE reviewer's reproduction, end-to-end against the REAL functions: when the
        pre-exec `capture_fork_snapshot` call raises, `_retry_with_fork` must NOT let
        `fork_snapshot` fall back to bare `None` -- to `record_fork`, `snapshot=None` means
        "self-capture", and self-capturing here would run AFTER `_fork_child`'s exec
        (simulated below by writing the child's transcript to disk only once the fake
        `_fork_child` runs -- the exec's real side effect), re-opening the exact race the
        pre-exec capture exists to close. The fix instead passes an explicit "capture
        failed" sentinel, so the record honestly refuses to resolve rather than silently
        excluding the child forever. `_fork_child` is stubbed (nothing here forks a real
        process); `store.record_fork`/`resolve_fork_child` are left REAL, like the sibling
        ordering test above, since the actual record written to forks.json is what's under
        test."""
        snap = {k: getattr(config, k) for k in ("PROJECTS", "FORKS_FILE")}
        config.PROJECTS = tempfile.mkdtemp()
        config.FORKS_FILE = tempfile.mktemp(suffix=".json")
        try:
            parent_uuids = [_u() for _ in range(5)]
            _mk_transcript(config.PROJECTS, "failParent", "/work/repo", time.time() - 30,
                            parent_uuids)

            capture_calls = []

            def failing_capture(parent_sid):
                capture_calls.append(parent_sid)
                raise RuntimeError("listdir exploded")

            def fake_fork_child(cwd, argv, cols, rows):
                # the child "writing its own transcript" as part of exec/startup -- must
                # happen strictly AFTER the (failed) pre-exec capture attempt, exactly like
                # the reviewer's reproduction of the race.
                _mk_transcript(config.PROJECTS, "failChild", "/work/repo", time.time(),
                                parent_uuids[:4])
                return (4242, 99)

            pt = _bare_retry_pty(cwd="/work/repo")
            with mock.patch.object(term_vt.store, "capture_fork_snapshot",
                                    side_effect=failing_capture), \
                 mock.patch.object(term_vt, "_fork_child", side_effect=fake_fork_child), \
                 mock.patch.object(term_vt.threading, "Thread"):
                term_vt._retry_with_fork(pt, "failParent", 80, 24)

            self.assertEqual(
                len(capture_calls), 1,
                "capture_fork_snapshot must be attempted exactly once per fork -- a bare "
                "`None` fallback would let record_fork's own self-capture retry it a second "
                "time, AFTER the exec, which is the exact bug this test guards against")

            forks = _load_forks()
            self.assertIn("failParent", forks,
                           "record_fork must still have written a record -- the capture "
                           "failure must not abort recording the fork entirely")
            rec = forks["failParent"]
            self.assertIsNone(
                rec.get("pre_existing"),
                "a failed pre-exec capture must record the unusable sentinel (pre_existing: "
                "None), not a real listing -- a real listing taken post-exec could have "
                "wrongly captured 'failChild' as pre-existing and excluded it forever")

            # the refuse-gate: must stay unresolved (retried later, eventually abandoned)
            # rather than silently and permanently excluding the real child.
            self.assertEqual(resolve_fork_child("failParent"), "")
        finally:
            shutil.rmtree(config.PROJECTS, ignore_errors=True)
            for k, v in snap.items():
                setattr(config, k, v)

    def test_record_fork_exception_does_not_break_the_retry(self):
        """A bookkeeping failure must never turn the user-visible recovery (the fork retry
        itself) into a crash -- the call is wrapped precisely so an exception here stays local."""
        pt = _bare_retry_pty()
        with mock.patch.object(term_vt, "_fork_child", return_value=(4242, 99)), \
             mock.patch.object(term_vt.threading, "Thread") as Thread, \
             mock.patch.object(term_vt.store, "record_fork",
                                side_effect=RuntimeError("disk full")):
            term_vt._retry_with_fork(pt, "sid-that-breaks-recording", 80, 24)   # must not raise
        # the fork itself still completed despite the bookkeeping failure
        self.assertTrue(pt.forked)
        self.assertEqual((pt.pid, pt.fd), (4242, 99))
        Thread.assert_called_once()


class TestForksMemo(unittest.TestCase):
    """Direct, unit-level pin on `_load_forks`'s memo itself — as opposed to
    `TestListDoesNoPerSessionFileReads` below, which only proves forks.json isn't
    re-read PER SESSION inside all_sessions(). That integration test (and every other
    test in this file) stays fully green even if the memo's hit-check is disabled
    entirely -- e.g. `_FORKS_CACHE[0] == key` replaced with `if False:` -- because
    none of them assert the fast path is actually TAKEN, only that invalidation
    correctly happens when it should (which stays true with the memo a no-op). These
    tests pin the other half: that N successive reads of an UNCHANGED forks.json cost
    one real parse, not N, for both the file-exists and the file-never-existed case."""

    def setUp(self):
        self._snap = {"FORKS_FILE": config.FORKS_FILE}
        config.FORKS_FILE = tempfile.mktemp(suffix=".json")
        store_mod._FORKS_CACHE = (None, {})

    def tearDown(self):
        if os.path.exists(config.FORKS_FILE):
            os.remove(config.FORKS_FILE)
        for k, v in self._snap.items():
            setattr(config, k, v)
        store_mod._FORKS_CACHE = (None, {})

    def _count_loader_calls(self, n_calls):
        """Run `_load_forks()` `n_calls` times and return how many of those calls
        actually reached the underlying `_load_json` loader for FORKS_FILE -- counting
        through whatever memoization store.py has, the same technique
        `TestListDoesNoPerSessionFileReads._count_forks_reads` uses."""
        calls = []
        real_load_json = store_mod._load_json

        def counting_load_json(path, default):
            if path == config.FORKS_FILE:
                calls.append(path)
            return real_load_json(path, default)

        with mock.patch.object(store_mod, "_load_json", side_effect=counting_load_json):
            for _ in range(n_calls):
                store_mod._load_forks()
        return len(calls)

    def test_unchanged_existing_file_is_parsed_once_not_n_times(self):
        """THE test that catches `if False:` at the hit-check (the reviewer's exact
        reproduction): with a real forks.json on disk that is never modified, 5
        successive `_load_forks()` calls must perform the underlying open+json.parse
        exactly ONCE. Disabling the memo makes this 5 -- this must fail in that case."""
        store_mod._save_json(config.FORKS_FILE, {"someparent": {"child": "somechild"}})
        store_mod._FORKS_CACHE = (None, {})   # start cold, as a real process would
        n_parses = self._count_loader_calls(5)
        self.assertEqual(n_parses, 1,
                          "5 successive load_forks() calls against an UNCHANGED file "
                          "must parse it once, not 5 -- the memo hit-check is either "
                          "disabled or never actually taken")

    def test_unchanged_absent_file_never_calls_the_loader(self):
        """The no-file case must ALSO memoize: with forks.json never created, 5
        successive `_load_forks()` calls must never call the underlying loader at all
        -- each is satisfied by a stat confirming nothing has changed."""
        self.assertFalse(os.path.exists(config.FORKS_FILE))
        n_parses = self._count_loader_calls(5)
        self.assertEqual(n_parses, 0,
                          "5 successive load_forks() calls against a file that never "
                          "existed must never call the loader -- the absent case must "
                          "memoize too")

    def test_load_forks_returns_the_real_content_from_the_memo(self):
        """Guards against a degenerate 'memoize but always answer {}' implementation:
        the memoized value must be the actual parsed content, and repeat calls must
        hand back the SAME cached object (not a fresh equal-but-different one)."""
        store_mod._save_json(config.FORKS_FILE, {"p1": {"child": "c1"}})
        store_mod._FORKS_CACHE = (None, {})
        first = store_mod._load_forks()
        second = store_mod._load_forks()
        self.assertEqual(first, {"p1": {"child": "c1"}})
        self.assertIs(second, first, "second call must return the SAME cached dict object")

    def test_newly_appearing_forks_file_is_observed_promptly(self):
        """The absent-state memo must not get stuck: once forks.json is created after
        earlier calls saw it as absent, the very next call must see the new content --
        never a stale cached {} left over from when the file didn't exist yet."""
        self.assertFalse(os.path.exists(config.FORKS_FILE))
        self.assertEqual(store_mod._load_forks(), {}, "starts absent")
        self.assertEqual(store_mod._load_forks(), {}, "still absent, still memoized-empty")
        store_mod._save_json(config.FORKS_FILE, {"newp": {"child": "newc"}})
        self.assertEqual(store_mod._load_forks(), {"newp": {"child": "newc"}},
                          "a newly-appearing forks.json must be observed on the very "
                          "next call, not stuck behind the earlier absent-state memo")


class TestListDoesNoPerSessionFileReads(unittest.TestCase):
    """`/api/list` is `all_sessions()` and the SPA polls it every few seconds, so any
    file read done ONCE PER SESSION scales with the user's transcript count and pushes
    the endpoint past the poll interval -- at which point polls overlap, exhaust the
    browser's 6-socket-per-host budget and starve every other request on the page
    (measured: 36-60s responses; the in-browser terminal's keystroke POSTs stopped
    reaching the PTY entirely).

    These are I/O-COUNT assertions, deliberately not timing assertions -- a wall-clock
    threshold would be flaky on a different machine, while "how many times did we open
    this file" is the actual behaviour that regressed and is identical everywhere.

    Two per-session reads are pinned here, both found by profiling one real
    `all_sessions()` over 950 sessions (1900 of its 3963 total `open()` calls were the
    same 826-byte `forks.json`):
      1. the fork-lineage loops (`registry.all_sessions`) -- `resolve_fork_child` and
         `fork_parent_of` each re-read `forks.json` per session;
      2. `providers/augment_ext._list` -- scanned every task file TWICE per workspace.
    (2) lives here rather than in `test_augment_ext.py` because it is the same defect
    class as (1) and this suite owns the `/api/list` cost contract."""

    def setUp(self):
        self._snap = {k: getattr(config, k) for k in
                      ("PROJECTS", "FORKS_FILE", "TITLES_FILE", "PINS_FILE", "NOTES_FILE",
                       "FLAGS_FILE", "AUGMENT_DIR", "AUGGIE_SESSIONS",
                       "VSCODE_WS_ROOT", "CURSOR_WS_ROOT")}
        config.PROJECTS = tempfile.mkdtemp()
        config.FORKS_FILE = tempfile.mktemp(suffix=".json")
        config.TITLES_FILE = tempfile.mktemp(suffix=".json")
        config.PINS_FILE = tempfile.mktemp(suffix=".json")
        config.NOTES_FILE = tempfile.mktemp(suffix=".json")
        config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.VSCODE_WS_ROOT = tempfile.mkdtemp()
        config.CURSOR_WS_ROOT = tempfile.mkdtemp()
        _auggie._AUGGIE_LIST_CACHE.clear()
        _claude._META_CACHE.clear()

    def tearDown(self):
        for d in (config.PROJECTS, config.AUGMENT_DIR, config.VSCODE_WS_ROOT, config.CURSOR_WS_ROOT):
            shutil.rmtree(d, ignore_errors=True)
        for k, v in self._snap.items():
            setattr(config, k, v)
        _auggie._AUGGIE_LIST_CACHE.clear()
        _claude._META_CACHE.clear()

    def _count_forks_reads(self, n_sessions):
        """Run one all_sessions() over `n_sessions` Claude transcripts and return how
        many times forks.json was actually opened and parsed."""
        shutil.rmtree(config.PROJECTS, ignore_errors=True)
        os.makedirs(config.PROJECTS, exist_ok=True)
        _claude._META_CACHE.clear()
        for i in range(n_sessions):
            _mk_transcript(config.PROJECTS, "sess%02d" % i, "/work/repo",
                            time.time() - i, [_u() for _ in range(3)])
        # count real I/O at the lowest shared seam (`_load_json`), filtered to
        # forks.json -- this counts through ANY memoization store.py may add, so the
        # assertion stays honest whichever way the redundancy is removed.
        reads = []
        real_load_json = store_mod._load_json

        def counting_load_json(path, default):
            if path == config.FORKS_FILE:
                reads.append(path)
            return real_load_json(path, default)

        with mock.patch.object(store_mod, "_load_json", side_effect=counting_load_json):
            sessions = all_sessions()
        self.assertEqual(len(sessions), n_sessions)      # the listing itself still works
        return len(reads)

    def test_forks_file_is_not_read_once_per_session(self):
        """THE regression this class exists for. `resolve_fork_child()` and
        `fork_parent_of()` were each called per session from `all_sessions()`, and each
        one re-read + re-parsed forks.json from disk -- 2 x N file reads per poll.

        The assertion is scale-freedom, not a magic number: quadrupling the session
        count must not increase the number of forks.json reads at all. Before the fix
        this went 8 -> 32; after it, it is a small constant either way."""
        few = self._count_forks_reads(4)
        many = self._count_forks_reads(16)
        self.assertEqual(
            few, many,
            "forks.json reads must not scale with the session count: %d sessions caused "
            "%d reads but %d sessions caused %d. all_sessions() must load the fork map "
            "ONCE and reuse it, not re-read it inside a per-session loop." % (4, few, 16, many))
        self.assertLessEqual(
            many, 4,
            "one /api/list should read forks.json a handful of times at most, got %d" % many)

    def test_fork_that_resolves_mid_call_gets_both_ends_stamped_in_that_same_response(self):
        """Guard on the shape of the fix, not on the old bug: hoisting the fork map out
        of the loop must NOT be done by taking one snapshot and reusing it blindly.
        `resolve_fork_child()` WRITES when it first resolves a parent, so a snapshot
        taken before the `continued_as` loop is already out of date by the time the
        `continued_from` loop runs -- and the child would render with a dangling
        'forked from' for a whole poll cycle. Both ends must appear in the SAME
        response, exactly as they did when every lookup re-read the file."""
        at = time.time() - 1
        parent_uuids = [_u() for _ in range(6)]
        _mk_transcript(config.PROJECTS, "liveParent", "/work/repo", at - 60, parent_uuids)
        record_fork("liveParent", "/work/repo", at)
        # the child appears only AFTER the record -- so this all_sessions() call is the
        # one that both resolves it and has to report it.
        _mk_transcript(config.PROJECTS, "liveChild", "/work/repo", at + 2, parent_uuids[:5])
        self.assertEqual(_load_forks()["liveParent"].get("child", ""), "",
                          "precondition: the fork must still be UNRESOLVED going in")

        by_id = {s["id"]: s for s in all_sessions()}
        self.assertEqual(by_id["liveParent"]["continued_as"], "liveChild")
        self.assertEqual(
            by_id["liveChild"]["continued_from"], "liveParent",
            "the fork resolved during this very call, so the child's continued_from must "
            "be stamped in this response too -- a stale pre-loop snapshot loses it")

    def test_augment_ext_list_reads_each_task_file_once(self):
        """`providers/augment_ext._list()` built an `allmap` that nothing in its loop
        body ever read, then iterated `_iter_tasks()` a SECOND time -- so every task
        file on disk was opened and json-parsed twice on every /api/list. Measured on
        real data: 665 Augment tasks, 1330 opens, ~40% of the warm endpoint cost."""
        from tests.test_augment_ext import _mk_workspace
        tasks = [{"uuid": "task%02d" % i, "name": "task %d" % i, "lastUpdated": 1_700_000_000_000}
                 for i in range(8)]
        _mk_workspace(config.VSCODE_WS_ROOT, "wsAAA", "file:///repo/aug", tasks=tasks)

        opens = []
        real_open = open

        def counting_open(path, *a, **k):
            p = str(path)
            if "task-storage" in p:
                opens.append(p)
            return real_open(path, *a, **k)

        with mock.patch("builtins.open", side_effect=counting_open):
            listed = _augment_ext._list("vscode", "augvs:", "augment-vscode")

        self.assertEqual(len(listed), len(tasks))        # same sessions as before
        self.assertEqual(
            len(opens), len(tasks),
            "each Augment task file must be opened exactly once per list(): expected %d "
            "opens for %d tasks, got %d (a second _iter_tasks() pass doubles the I/O)"
            % (len(tasks), len(tasks), len(opens)))


if __name__ == "__main__":
    unittest.main()
