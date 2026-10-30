"""Gateway seam: the OpenRouter launcher + slot file are configurable and EMPTY by default; an unconfigured
OpenRouter launch is a clear GatewayError, never a silent fallback to plain `claude`."""
import base64, glob, os, re, stat, tempfile, unittest
from unittest import mock

from aitracker import config, gateway

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ATTRS = ("GATEWAY", "OPENROUTER_LAUNCHER", "OPENROUTER_SLOTS_FILE")
_ENV = ("OR_MODEL_HIGH", "OR_MODEL_MID", "OR_MODEL_LOW")


class _Base(unittest.TestCase):
    def setUp(self):
        self._saved = {a: getattr(config, a) for a in _ATTRS}
        self.tmp = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if k not in _ENV}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start(); self.addCleanup(p.stop)
        config.OPENROUTER_LAUNCHER = config.OPENROUTER_SLOTS_FILE = ""

    def tearDown(self):
        for a, v in self._saved.items():
            setattr(config, a, v)

    def _file(self, name, text="", mode=0o644):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, mode)
        return p


class TestLauncherConfig(_Base):
    def test_defaults_are_empty(self):
        self.assertEqual(config.resolve_openrouter_launcher({}), "")
        self.assertEqual(config.resolve_openrouter_slots_file({}), "")
        self.assertIn("OPENROUTER_LAUNCHER", config.EDITABLE)
        self.assertIn("OPENROUTER_SLOTS_FILE", config.EDITABLE)

    def test_unset_raises_not_configured(self):
        with self.assertRaises(gateway.GatewayError) as cm:
            gateway.launcher("openrouter")
        self.assertIn("not configured", str(cm.exception))
        self.assertFalse(gateway.openrouter_configured())

    def test_non_executable_raises(self):
        config.OPENROUTER_LAUNCHER = self._file("or-launch", "#!/bin/sh\n", 0o644)
        with self.assertRaises(gateway.GatewayError) as cm:
            gateway.launcher("openrouter")
        self.assertIn("not found or not executable", str(cm.exception))

    def test_executable_path_returned(self):
        p = self._file("or-launch", "#!/bin/sh\n", 0o755)
        config.OPENROUTER_LAUNCHER = p
        self.assertEqual(gateway.launcher("openrouter"), p)
        self.assertTrue(gateway.openrouter_configured())

    def test_bare_name_resolved_via_path(self):
        p = self._file("or-launch", "#!/bin/sh\n", 0o755)
        config.OPENROUTER_LAUNCHER = "or-launch"
        with mock.patch.dict(os.environ, {"PATH": self.tmp}):
            self.assertEqual(gateway.launcher("openrouter"), p)

    def test_relative_path_is_absolutised(self):
        os.makedirs(os.path.join(self.tmp, "bin"))
        p = os.path.join(self.tmp, "bin", "or-launch")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(p, 0o755)
        old = os.getcwd()
        os.chdir(self.tmp)
        try:
            config.OPENROUTER_LAUNCHER = os.path.join("bin", "or-launch")
            # os.getcwd() resolves symlinks (macOS /var -> /private/var), so derive expected from it
            self.assertEqual(gateway.or_launcher()[0], os.path.join(os.getcwd(), "bin", "or-launch"))
        finally:
            os.chdir(old)

    def test_bare_name_missing_raises(self):
        config.OPENROUTER_LAUNCHER = "or-launch"
        with mock.patch.dict(os.environ, {"PATH": self.tmp}):
            with self.assertRaises(gateway.GatewayError):
                gateway.launcher("openrouter")

    def test_anthropic_is_always_plain_claude(self):
        self.assertEqual(gateway.launcher("anthropic"), "claude")
        self.assertEqual(gateway.launcher(""), "claude")
        config.OPENROUTER_LAUNCHER = self._file("or-launch", "#!/bin/sh\n", 0o755)
        self.assertEqual(gateway.launcher("anthropic"), "claude")

    def test_validators_accept_str_and_empty_reject_other(self):
        for k in ("OPENROUTER_LAUNCHER", "OPENROUTER_SLOTS_FILE"):
            self.assertEqual(config.VALIDATORS[k](""), (True, ""))
            self.assertEqual(config.VALIDATORS[k]("/x/y"), (True, "/x/y"))
            self.assertFalse(config.VALIDATORS[k](5)[0])
            self.assertFalse(config.VALIDATORS[k]("x" * 1025)[0])

    def test_apply_overrides_repoints_attrs(self):
        config.apply_overrides({"OPENROUTER_LAUNCHER": " /a/b ", "OPENROUTER_SLOTS_FILE": "/c"})
        self.assertEqual((config.OPENROUTER_LAUNCHER, config.OPENROUTER_SLOTS_FILE), ("/a/b", "/c"))
        config.apply_overrides({})
        self.assertEqual((config.OPENROUTER_LAUNCHER, config.OPENROUTER_SLOTS_FILE), ("", ""))


class TestSlotsConfig(_Base):
    def _slots(self, text, **env):
        config.OPENROUTER_SLOTS_FILE = self._file("slots.env", text)
        with mock.patch.dict(os.environ, env):
            return gateway.slots()

    def test_unset_is_empty_even_with_env(self):
        with mock.patch.dict(os.environ, {"OR_MODEL_HIGH": "a/b"}):
            self.assertEqual(gateway.slots(), {})

    def test_mid_and_low_default_chain(self):
        self.assertEqual(self._slots("OR_MODEL_HIGH=p/h\n"), {"opus": "p/h", "sonnet": "p/h", "haiku": "p/h"})
        self.assertEqual(self._slots("OR_MODEL_HIGH=p/h\nOR_MODEL_MID=d/m\n"),
                         {"opus": "p/h", "sonnet": "d/m", "haiku": "d/m"})
        self.assertEqual(self._slots("OR_MODEL_HIGH=p/h\nOR_MODEL_MID=d/m\nOR_MODEL_LOW=x/l\n"),
                         {"opus": "p/h", "sonnet": "d/m", "haiku": "x/l"})

    def test_env_var_beats_file_even_empty(self):
        self.assertEqual(self._slots("OR_MODEL_HIGH=p/h\n", OR_MODEL_HIGH="e/h")["opus"], "e/h")
        self.assertEqual(self._slots("OR_MODEL_HIGH=p/h\n", OR_MODEL_HIGH=""), {})   # empty env wins, no default

    def test_whitespace_stripped_and_bad_bytes_tolerated(self):
        self.assertEqual(self._slots('OR_MODEL_HIGH="p/ h"\n')["opus"], "p/h")
        config.OPENROUTER_SLOTS_FILE = os.path.join(self.tmp, "bad.env")
        with open(config.OPENROUTER_SLOTS_FILE, "wb") as f:
            f.write(b"OR_MODEL_HIGH=p/h\n\xff\xfe junk\n")
        self.assertEqual(gateway.slots()["opus"], "p/h")

    def test_no_high_is_empty_and_missing_file_never_raises(self):
        self.assertEqual(self._slots("# nothing\n"), {})
        config.OPENROUTER_SLOTS_FILE = os.path.join(self.tmp, "nope.env")
        self.assertEqual(gateway.slots(), {})

    def test_model_meta_unconfigured_whole_dict(self):
        self.assertEqual(gateway.model_meta("a/b"), {
            "gateway": "openrouter", "model_ladder": ["haiku", "sonnet", "opus"], "model_hints": {},
            "model_slot": None, "openrouter_configured": False})

    def test_model_meta_anthropic_has_no_configured_key(self):
        self.assertEqual(gateway.model_meta("claude-opus-5-5"), {
            "gateway": "anthropic", "model_ladder": ["haiku", "sonnet", "opus", "fable"],
            "model_hints": {}, "model_slot": None})

    def test_model_meta_slot_and_ambiguity(self):
        self._slots("OR_MODEL_HIGH=p/h\nOR_MODEL_MID=d/m\nOR_MODEL_LOW=x/l\n")
        self.assertEqual(gateway.model_meta("d/m")["model_slot"], "sonnet")
        self.assertEqual(gateway.model_meta("d/m:free")["model_slot"], "sonnet")
        self.assertIsNone(gateway.model_meta("other/z")["model_slot"])
        self._slots("OR_MODEL_HIGH=p/h\n")                      # all three slots share one model
        self.assertIsNone(gateway.model_meta("p/h")["model_slot"])


class TestPublicScrub(unittest.TestCase):
    def test_no_vendor_or_poc_names_in_sources(self):
        # base64 so the banned terms never appear in the public source themselves
        pat = re.compile(base64.b64decode(
            "YWR2aXNvcjM2MHxvcGVucm91dGVyLXBvY3xPUEVOUk9VVEVSX1BPQ3xjbGF1ZGUtb3J8XGJQT0NcYg==").decode(), re.I)
        files = (glob.glob(os.path.join(_ROOT, "aitracker", "**", "*.py"), recursive=True)
                 + glob.glob(os.path.join(_ROOT, "aitracker", "web", "*.js"))
                 + [os.path.join(_ROOT, "README.md")])
        hits = []
        for f in files:
            with open(f, encoding="utf-8", errors="replace") as fh:
                hits += ["%s:%d" % (os.path.relpath(f, _ROOT), n)
                         for n, line in enumerate(fh, 1) if pat.search(line)]
        self.assertEqual(hits, [])
        with open(os.path.join(_ROOT, "README.md"), encoding="utf-8") as fh:
            self.assertIn("Model gateway", fh.read())   # the README documents the feature


# ---- P1b: the resume seam, resume_cmd, model_label --------------------------------------------
import json, shlex
from aitracker import registry, term_gate
from aitracker.providers import claude as _claude

_OR_MODEL, _AN_MODEL = "openai/gpt-6.1-sol", "claude-opus-5-5"


class _Transcripts(_Base):
    """A temp config.PROJECTS holding <sid>.jsonl files; config.PROJECTS restored in tearDown."""

    def setUp(self):
        super().setUp()
        self._projects0 = config.PROJECTS
        config.PROJECTS = os.path.join(self.tmp, "projects")
        os.makedirs(os.path.join(config.PROJECTS, "proj"))
        _claude._META_CACHE.clear()
        self.launcher = self._file("or-launch", "#!/bin/sh\n", 0o755)

    def tearDown(self):
        config.PROJECTS = self._projects0
        _claude._META_CACHE.clear()
        super().tearDown()

    def _session(self, sid, *models, pad=0):
        """Assistant lines for each model in order; `pad` appends one user line of that many bytes."""
        with open(os.path.join(config.PROJECTS, "proj", sid + ".jsonl"), "w") as f:
            for m in models:
                f.write(json.dumps({"type": "assistant", "cwd": "/tmp", "message": {
                    "model": m, "role": "assistant", "content": [{"type": "text", "text": "hi"}]}}) + "\n")
            if pad:
                f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "x" * pad}}) + "\n")


class TestResumeLauncher(_Transcripts):
    def test_resume_does_not_full_parse_when_tail_has_model(self):
        config.OPENROUTER_LAUNCHER = self.launcher
        self._session("s-or", _OR_MODEL)
        boom = AssertionError("full parse on the resume path")
        with mock.patch.object(registry, "parse_any", side_effect=boom), \
             mock.patch.object(_claude, "parse_session", side_effect=boom):
            self.assertEqual(term_gate.resume_argv("s-or"), [self.launcher, "--resume", "s-or"])

    def test_resume_latest_model_wins(self):
        config.OPENROUTER_LAUNCHER = self.launcher
        self._session("s-a", _OR_MODEL, _AN_MODEL)
        self._session("s-b", _AN_MODEL, _OR_MODEL)
        self.assertEqual(term_gate.resume_argv("s-a")[0], "claude")
        self.assertEqual(term_gate.resume_argv("s-b")[0], self.launcher)

    def test_resume_giant_tail_falls_back_to_full_parse(self):
        config.OPENROUTER_LAUNCHER = self.launcher
        self._session("s-big", _OR_MODEL, pad=120000)
        self.assertEqual(term_gate.resume_argv("s-big")[0], self.launcher)

    def test_resume_missing_session_or_lookup_error_is_claude(self):
        config.OPENROUTER_LAUNCHER = self.launcher
        self.assertEqual(term_gate.resume_argv("no-such-sid")[0], "claude")
        self._session("s-or", _OR_MODEL)
        with mock.patch.object(_claude, "_tail_scan", side_effect=RuntimeError("lookup failed")):
            self.assertEqual(term_gate.resume_argv("s-or")[0], "claude")


class TestResumeSeamErrors(_Transcripts):
    def test_openrouter_resume_unconfigured_raises(self):
        self._session("s-or", _OR_MODEL)
        with self.assertRaises(gateway.GatewayError) as cm:
            term_gate.resume_argv("s-or")
        self.assertIn("not configured", str(cm.exception))

    def test_anthropic_resume_unconfigured_is_plain_claude(self):
        self._session("s-a", _AN_MODEL)
        self.assertEqual(term_gate.resume_argv("s-a"), ["claude", "--resume", "s-a"])


class TestResumeCmd(_Base):
    class _Prov:
        def __init__(self, model, prefix=""):
            self._m, self.prefix = model, prefix

        def parse(self, sid):
            return {"id": sid, "meta": {"model": self._m}}

    def _meta(self, model, sid="zz-1", prefix=""):
        with mock.patch.object(registry, "provider_for", lambda s: self._Prov(model, prefix)):
            return registry.parse_any(sid)["meta"]

    def test_resume_cmd_follows_config(self):
        self.assertIsNone(self._meta(_OR_MODEL)["resume_cmd"])
        p = self._file("or launch", "#!/bin/sh\n", 0o755)
        config.OPENROUTER_LAUNCHER = p
        self.assertEqual(self._meta(_OR_MODEL)["resume_cmd"], shlex.quote(p) + " --resume zz-1")
        self.assertEqual(self._meta(_AN_MODEL)["resume_cmd"], "claude --resume zz-1")

    def test_resume_cmd_expands_tilde(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, "bin"))
        p = os.path.join(home, "bin", "or-launch")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(p, 0o755)
        with mock.patch.dict(os.environ, {"HOME": home}):
            config.OPENROUTER_LAUNCHER = "~/bin/or-launch"
            self.assertEqual(self._meta(_OR_MODEL)["resume_cmd"],
                             shlex.quote(os.path.abspath(p)) + " --resume zz-1")

    def test_resume_cmd_only_for_unprefixed_provider(self):
        self.assertNotIn("resume_cmd", self._meta(_AN_MODEL, sid="zz:1", prefix="zz:"))


class TestSessionListModelLabel(_Transcripts):
    def test_all_sessions_carries_model_label(self):
        self._session("s-or", _OR_MODEL)
        rows = {s["id"]: s for s in registry.all_sessions()}
        self.assertEqual(rows["s-or"]["model_label"], "gpt-6.1-sol (OpenRouter)")


if __name__ == "__main__":
    unittest.main()
