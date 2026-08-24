"""Path-traversal guard, moved to the shared seam (aitracker.util.safe_path_component)
and applied to every provider that joins a URL-sourced sid into a filesystem path or
a glob pattern: Auggie (`auggie:<id>`), the Augment VSCode/Cursor extension
(`augment-vscode:<ws>:<uuid>` / `augment-cursor:<ws>:<uuid>`), and Claude (bare sid,
reaches a glob.glob() lookup in find_session()).

Each class below proves ONE call site is closed. Reverting the fix under test (and
only that fix) in a scratch copy of the repo turns the corresponding test RED —
verified manually outside this file per the task's non-negotiable, not re-checked
by CI here.
"""
import json
import os
import shutil
import tempfile
import unittest

from aitracker import config, registry
from aitracker.util import safe_path_component
from aitracker.providers import auggie as A
from aitracker.providers.augment_ext import AugmentVscodeProvider


# --------------------------------------------------------------- the shared helper

class TestSafePathComponent(unittest.TestCase):
    """Direct unit tests of the seam itself — every provider's traversal guard now
    reduces to this one function, so this is where the reject/accept contract lives."""

    def test_rejects_empty_and_none_and_nul(self):
        self.assertIsNone(safe_path_component(""))
        self.assertIsNone(safe_path_component(None))
        self.assertIsNone(safe_path_component("a\x00b"))

    def test_rejects_separators_and_traversal(self):
        for bad in ("../x", "a/b", "a\\b", "..", "../../etc/passwd"):
            self.assertIsNone(safe_path_component(bad), bad)

    def test_rejects_glob_metacharacters(self):
        # a glob.glob()-based lookup (Claude's find_session) would otherwise honour
        # these and disclose an arbitrary sibling session instead of 404ing.
        for bad in ("*", "?", "[a]", "sid*", "s?d", "s[1]d"):
            self.assertIsNone(safe_path_component(bad), bad)

    def test_accepts_a_normal_uuid_like_id(self):
        self.assertEqual(safe_path_component("15a16aa9-d46e-45dc-9613-c0630aae6760"),
                          "15a16aa9-d46e-45dc-9613-c0630aae6760")
        self.assertEqual(safe_path_component("s1"), "s1")


# ------------------------------------------------------------------------- Auggie

class _AuggieEnv(unittest.TestCase):
    def setUp(self):
        self._snap = (config.AUGMENT_DIR, config.AUGGIE_SESSIONS)
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        A._AUGGIE_LIST_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(config.AUGMENT_DIR, ignore_errors=True)
        (config.AUGMENT_DIR, config.AUGGIE_SESSIONS) = self._snap
        A._AUGGIE_LIST_CACHE.clear()


class TestAuggieUsesSharedSeam(_AuggieEnv):
    """auggie.py's own _safe_session_id must be a thin alias, not a second
    implementation — this reproduces the original traversal payload shape end to
    end through the real read path (_load_auggie), not just the helper in isolation."""

    def test_traversal_id_cannot_read_a_planted_json_outside_the_sessions_dir(self):
        # planted OUTSIDE AUGGIE_SESSIONS, at AUGMENT_DIR/secret.json
        secret = os.path.join(config.AUGMENT_DIR, "secret.json")
        with open(secret, "w") as fh:
            json.dump({"sessionId": "secret", "SECRET": "LEAKED-IF-READABLE"}, fh)

        traversal_id = "../secret"  # AUGGIE_SESSIONS/../secret.json == AUGMENT_DIR/secret.json
        d, f = A._load_auggie(traversal_id)
        self.assertIsNone(d, "traversal id must not resolve to the planted file")
        self.assertIsNone(f)
        self.assertFalse(A.AuggieProvider().exists("auggie:" + traversal_id))

    def test_auggie_local_alias_delegates_to_the_shared_helper(self):
        # same reject set as the shared helper, proving there is no second copy of
        # the logic drifting from it
        for bad in ("../x", "a/b", "a\\b", "a\x00b", "..", "*", "?"):
            self.assertIsNone(A._safe_session_id(bad), bad)
        self.assertEqual(A._safe_session_id("s1"), "s1")


# ------------------------------------------------------------------- Augment ext

class TestAugmentExtTraversal(unittest.TestCase):
    """augment_ext._parse() splits `sid` into a workspace id and a task uuid and
    joins the workspace id straight into a filesystem path (aug_dir, ws_json)
    without sanitising it first — the same class of hole Auggie had, just narrower
    (the escaped directory must exist and hold the expected Augment.vscode-augment
    structure to yield anything back)."""

    def setUp(self):
        self._orig_vs = config.VSCODE_WS_ROOT
        self.root = tempfile.mkdtemp()
        config.VSCODE_WS_ROOT = self.root

        # a real workspace so a successful escape has something to land on
        self.legit_ws = os.path.join(self.root, "wshash1")
        aug = os.path.join(self.legit_ws, "Augment.vscode-augment",
                            "augment-user-assets", "task-storage", "tasks")
        os.makedirs(aug)
        with open(os.path.join(self.legit_ws, "workspace.json"), "w") as f:
            json.dump({"folder": "file:///repo/one"}, f)
        with open(os.path.join(aug, "root-uuid.json"), "w") as f:
            json.dump({"uuid": "root-uuid", "name": "a real task"}, f)

        # sibling directory OUTSIDE the configured workspaceStorage root, holding
        # the same on-disk shape a traversal payload would need to reach
        self.outside = tempfile.mkdtemp()
        aug2 = os.path.join(self.outside, "Augment.vscode-augment",
                             "augment-user-assets", "task-storage", "tasks")
        os.makedirs(aug2)
        with open(os.path.join(self.outside, "workspace.json"), "w") as f:
            json.dump({"folder": "file:///should/not/be/reachable"}, f)
        with open(os.path.join(aug2, "leaked-uuid.json"), "w") as f:
            json.dump({"uuid": "leaked-uuid", "name": "SECRET-LEAKED-IF-READABLE"}, f)

    def tearDown(self):
        config.VSCODE_WS_ROOT = self._orig_vs
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.outside, ignore_errors=True)

    def test_ws_component_cannot_traverse_out_of_workspace_storage_root(self):
        p = AugmentVscodeProvider()
        rel = os.path.relpath(self.outside, self.root)
        traversal_sid = "augment-vscode:%s:leaked-uuid" % rel
        self.assertIsNone(p.parse(traversal_sid),
                           "a ../-laden workspace component must not resolve outside VSCODE_WS_ROOT")
        self.assertFalse(p.exists(traversal_sid))
        self.assertIsNone(registry.parse_any(traversal_sid))

    def test_uuid_component_with_separators_is_also_rejected(self):
        p = AugmentVscodeProvider()
        self.assertIsNone(p.parse("augment-vscode:wshash1:../../leaked-uuid"))

    def test_legit_id_still_resolves(self):
        # regression guard: the fix must not break the normal path
        p = AugmentVscodeProvider()
        d = p.parse("augment-vscode:wshash1:root-uuid")
        self.assertIsNotNone(d)
        self.assertEqual(d["overview"]["goal"], "a real task")


# ------------------------------------------------------------------------- Claude

class TestClaudeGlobSid(unittest.TestCase):
    """ClaudeProvider.find_session() feeds `sid` straight into glob.glob(), which
    (unlike a plain os.path.join) also honours `*`/`?`/`[...]` — so a bare
    sid="*" matches ANY session under ANY project dir, disclosing an arbitrary
    session's content without knowing its id. `..` in sid is also a real
    filesystem escape, not just glob disclosure, once the glob's `*` project
    segment has matched some real directory to back out of."""

    def setUp(self):
        self._proj = config.PROJECTS
        config.PROJECTS = tempfile.mkdtemp()
        self.projA = os.path.join(config.PROJECTS, "projA")
        self.projB = os.path.join(config.PROJECTS, "projB")
        os.makedirs(self.projA)
        os.makedirs(self.projB)
        with open(os.path.join(self.projA, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl"), "w") as f:
            f.write('{"sessionId":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}\n')
        with open(os.path.join(self.projB, "SECRET-session.jsonl"), "w") as f:
            f.write('{"sessionId":"SECRET-session","leak":"LEAKED-IF-READABLE"}\n')

    def tearDown(self):
        shutil.rmtree(config.PROJECTS, ignore_errors=True)
        config.PROJECTS = self._proj

    def test_star_sid_does_not_disclose_an_arbitrary_sibling_session(self):
        from aitracker.providers.claude import find_session
        self.assertIsNone(find_session("*"))

    def test_glob_class_sid_is_rejected(self):
        from aitracker.providers.claude import find_session
        self.assertIsNone(find_session("SECRET-sessio?"))
        self.assertIsNone(find_session("[S]ECRET-session"))

    def test_traversal_sid_cannot_escape_projects_root(self):
        from aitracker.providers.claude import find_session
        outside = tempfile.mkdtemp()
        try:
            with open(os.path.join(outside, "outside.jsonl"), "w") as f:
                f.write('{"sessionId":"outside","leak":"LEAKED-IF-READABLE"}\n')
            rel = os.path.relpath(outside, self.projA)
            self.assertIsNone(find_session(os.path.join(rel, "outside")))
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_legit_uuid_sid_still_resolves(self):
        from aitracker.providers.claude import find_session
        self.assertIsNotNone(find_session("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))

    def test_reaches_through_provider_and_registry(self):
        from aitracker.providers.claude import ClaudeProvider
        p = ClaudeProvider()
        self.assertIsNone(p.parse("*"))
        self.assertFalse(p.exists("*"))
        self.assertIsNone(registry.parse_any("*"))


if __name__ == "__main__":
    unittest.main()
