import shlex
import subprocess
import tempfile
import threading
import unittest
import uuid
from unittest import mock

from aitracker import config, term_gate, term_vt
from tests import test_folder_terminal as tft


class PtyPromptArgv(unittest.TestCase):
    def test_prompt_appended(self):
        self.assertEqual(term_vt._with_prompt(["claude"], "do the thing"), ["claude", "do the thing"])

    def test_rejected_prompts_leave_argv(self):
        for p in (None, "", "   ", 5, "-x", "  --print hi", "a" * 4001):
            self.assertEqual(term_vt._with_prompt(["claude"], p), ["claude"], repr(p)[:20])

    def test_cap_boundary_and_shell_quoting(self):
        self.assertEqual(len(term_vt._with_prompt(["claude"], "a" * 4000)), 2)
        self.assertEqual(shlex.split(shlex.join(term_vt._with_prompt(["claude"], "it's $x; rm"))),
                         ["claude", "it's $x; rm"])

    def test_control_characters_rejected(self):
        for p in ("a\x15rm -rf ~", "x\x03", "a\x1b[201~b", "a\x7fb", "line1\nline2", "tab\there"):
            self.assertEqual(term_vt._with_prompt(["claude"], p), ["claude"], repr(p))


class OpenPtyRoutePrompt(unittest.TestCase):
    """Drives the real open_pty route (mode "new" + prompt) with the typing step stubbed."""

    def setUp(self):
        self._t0, self._a0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._tmpdir = tempfile.mkdtemp()
        tft._stub_kill(self)
        self.spawned = []
        self._watched = threading.Event()
        self.addCleanup(self._restore)

    def _restore(self):
        config.TERMINAL, config.AUTH = self._t0, self._a0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def _open(self, body, or_launcher=None):
        pt = term_vt.Pty(tid="fo1", pid=42424, fd=99, cwd=self._tmpdir)
        pt.folder, pt.session, pt.mode, pt.shell_cmd, pt.startup_done = True, "", "cwd", "sh", True
        term_vt.PTYS["fo1"] = pt
        h = tft._FakeHandler()
        with mock.patch.object(term_gate, "session_cwd", return_value=self._tmpdir), \
             mock.patch.object(term_vt.gateway, "launcher", return_value="claude") \
             if or_launcher is None else mock.patch.object(term_vt.gateway, "or_launcher",
                                                            return_value=(or_launcher, "")), \
             mock.patch.object(term_vt, "_fg_pgid", side_effect=lambda p: p.pid), \
             mock.patch.object(term_vt, "_inject_argv", return_value=(True, "")) as inj, \
             mock.patch.object(term_vt, "_start_backstop", return_value=False), \
             mock.patch.object(term_vt, "resolve_spawned"), \
             mock.patch.object(term_vt, "spawn", side_effect=self._fake_spawn), \
             mock.patch.object(term_vt, "_login_watch",
                               side_effect=lambda pt, sid: self._watched.set()) as self.watch:
            term_vt.open_pty(h, None, dict(body, cols=80, rows=24))
        return h.calls[-1], inj

    def _fake_spawn(self, cwd, argv, cols, rows):
        # No real claude is ever forked: a login open (dedicated pty) lands here.
        self.spawned.append(list(argv))
        return term_vt.Pty(tid="dd1", pid=42425, fd=98, cwd=self._tmpdir)

    def _assert_dedicated_login(self, obj):
        self.assertEqual(len(self.spawned), 1)
        argv = self.spawned[0]
        self.assertEqual(argv[1], "--session-id")
        self.assertEqual(argv[3], "/login")
        self.assertEqual(uuid.UUID(argv[2]).version, 4)
        self.assertFalse(obj["folder"])
        pt = term_vt.PTYS["dd1"]
        self.assertTrue(pt.overflow)
        self.assertEqual(pt.spawned, argv[2])
        self.assertTrue(self._watched.wait(2))
        self.watch.assert_called_once()
        self.assertEqual(self.watch.call_args[0], (pt, argv[2]))
        return argv

    def test_new_mode_prompt_reaches_the_injected_argv(self):
        (obj, code), inj = self._open({"session": "", "mode": "new", "cwd": self._tmpdir, "prompt": "do it"})
        self.assertEqual(code, 200, obj)
        inj.assert_called_once()
        self.assertEqual(inj.call_args[0][1], ["claude", "do it"])

    def test_new_mode_without_prompt_is_a_bare_launcher(self):
        (obj, code), inj = self._open({"session": "", "mode": "new", "cwd": self._tmpdir})
        self.assertEqual(code, 200, obj)
        self.assertEqual(inj.call_args[0][1], ["claude"])

    def test_login_prompt_pin_anthropic_launcher(self):
        # A login open is a dedicated pty on a server-chosen session id; nothing is typed into the folder shell.
        for gw in ("anthropic", None):
            self.spawned.clear()
            body = {"session": "", "mode": "new", "cwd": self._tmpdir, "prompt": "/login"}
            if gw:
                body["gateway"] = gw
            (obj, code), inj = self._open(body)
            self.assertEqual(code, 200, obj)
            inj.assert_not_called()
            argv = self._assert_dedicated_login(obj)
            self.assertEqual(argv[0], "claude")
            self.assertEqual(obj["tty"], "dd1")

    def test_login_prompt_anthropic_override_beats_openrouter_default(self):
        # No launcher mock: the real gateway.launcher decides. An OpenRouter default must not win.
        body = {"session": "", "mode": "new", "cwd": self._tmpdir, "gateway": "anthropic", "prompt": "/login"}
        with mock.patch.object(config, "GATEWAY", "openrouter"):
            (obj, code), inj = self._open(body, or_launcher="/opt/or/claude-or")
        self.assertEqual(code, 200, obj)
        inj.assert_not_called()
        self._assert_dedicated_login(obj)

    def test_login_prompt_pin_openrouter_launcher(self):
        body = {"session": "", "mode": "new", "cwd": self._tmpdir, "gateway": "openrouter", "prompt": "/login"}
        (obj, code), inj = self._open(body, or_launcher="/opt/or/claude-or")
        self.assertEqual(code, 200, obj)
        self.assertEqual(inj.call_args[0][1], ["/opt/or/claude-or", "/login"])
        self.assertEqual(self.spawned, [])
        self.watch.assert_not_called()


class InjectArgvQuoting(unittest.TestCase):
    PROMPT = "it's a \"q\" $HOME `id` !! \\ $(rm x); done"

    def test_typed_bytes_reproduce_the_prompt_exactly(self):
        pt = term_vt.Pty(tid="qP", pid=555, fd=9)
        typed = []
        with mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True), \
             mock.patch.object(term_vt, "_fg_pgid", return_value=555), \
             mock.patch.object(term_vt, "_inject_write", side_effect=lambda p, d: typed.append(d) or True), \
             mock.patch.object(term_vt, "INJECT_KEY_GAP", 0):
            ok, why = term_vt._inject_argv(pt, ["claude", self.PROMPT])
        self.assertTrue(ok, why)
        line = typed[0].decode()
        self.assertEqual(shlex.split(line), ["claude", self.PROMPT])
        out = subprocess.run(["/bin/sh", "-c", "printf '%s\\0' " + line.replace("claude", "", 1)],
                             capture_output=True, text=True, timeout=10).stdout
        self.assertEqual(out, self.PROMPT + "\0")


if __name__ == "__main__":
    unittest.main()
