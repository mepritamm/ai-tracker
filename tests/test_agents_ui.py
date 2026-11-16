"""Static source assertions for the Config dialog's Agents section (S7). Every sentence is
server-written; the poller is module-level, not owned by the dialog DOM."""
import os
import re
import shutil
import subprocess
import time
import unittest
from unittest import mock

_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "aitracker", "web", "ext_cr_dialogs.js")


def _src():
    with open(_JS, encoding="utf-8") as f:
        return f.read()


def _agents_code(s):
    a = s.index("var _agentJobTimer")
    return s[a:s.index("function renderConfig(")]


class AgentsUiTest(unittest.TestCase):
    def test_section_listed_and_dispatched(self):
        s = _src()
        self.assertRegex(s, r"var sections = \[[^\]]*'Terminal', 'Agents'")
        self.assertIn("active === 'Agents'", s)
        self.assertRegex(s, r"active === 'Agents'\) \{\s*var agEl = agentsBlock\(\); if \(agEl\) body\.appendChild\(agEl\)")

    def test_b_n2_both_outside_renderings_show_out_of_date_text(self):
        code = _agents_code(_src())
        lines = [l for l in code.splitlines() if "o.title" in l]
        self.assertEqual(len(lines), 2, lines)          # the warning and the job view
        for l in lines:
            self.assertIn("o.out_of_date_text", l)

    def test_routes_referenced(self):
        code = _agents_code(_src())
        self.assertIn("'/api/agents'", code)
        self.assertIn("'/api/agents/run'", code)

    def test_no_server_text_hardcoded(self):
        code = _agents_code(_src())
        for phrase in ("will be stopped", "continue, re-read", "updates itself", "out of date"):
            self.assertNotIn(phrase, code)

    def test_poller_is_module_scope(self):
        s = _src()
        a = s.index("var _agentJobTimer")
        self.assertLess(a, s.index("function agentsBlock"))
        self.assertLess(a, s.index("function agentWatchJob"))
        # declared at IIFE scope: two-space indent, not inside agentsBlock
        self.assertRegex(s, r"\n  var _agentJobTimer = null, _agentToasted = null, _agentWatchId = null;")

    def test_poller_survives_a_failed_poll_and_restarts_for_a_new_job(self):
        code = _agents_code(_src())
        self.assertRegex(code, r"if \(!r\.ok\) return;")
        self.assertRegex(code, r"_agentWatchId === id\) return;")

    def test_toasts_server_summary(self):
        self.assertIn("toast({ title: j.summary", _agents_code(_src()))

    def test_no_session_storage(self):
        self.assertNotIn("sessionStorage", _agents_code(_src()))

    def test_confirm_flow(self):
        code = _agents_code(_src())
        self.assertIn("cr-update-confirm cr-agents-confirm", code)
        self.assertIn("needs_confirm", code)
        self.assertRegex(code, r"\{ tty: c\.tty, session: c\.session \}")
        self.assertIn("agentWatchJob(", code)

    def test_confirm_sends_every_shown_copy(self):
        code = _agents_code(_src())
        self.assertRegex(code, r"\(plan\.stop \|\| \[\]\)\.map\(function \(c\) \{ return \{ tty: c\.tty, session: c\.session \}")

    def test_every_field_the_ui_reads_is_emitted_by_the_server(self):
        """Field fit: each `x.field` the Agents code reads is a key of the dict the server really emits
        (agent_cli's own functions, fake term_vt/provider rows). A renamed server key goes red here."""
        from aitracker import agent_cli as ac
        from aitracker.providers import claude as _claude
        code = _agents_code(_src())
        reads = {}
        for var, name in re.findall(r"(?<![\w.])(a|c|o|i|j|job|plan|st)\.([a-z_]+)", code):
            reads.setdefault({"j": "job"}.get(var, var), set()).add(name)

        def cand(tty, sid, **kw):
            d = {"tty": tty, "session": sid, "relabelled": "", "target": sid, "pid": 5, "version": "2.1.1",
                 "status": "busy", "cwd": "/w", "title": "T", "cols": 80, "rows": 24, "folder": True, "thin": False,
                 "daemon": False, "job_short": "", "needs_slot": False, "stoppable": True, "reason": "",
                 "command": ["claude --resume " + sid], "dup_group": [], "primary": True}
            d.update(kw)
            return d

        class TV:
            def upgrade_candidates(self):
                return [cand("a", "S1", relabelled="R" * 12),
                        cand("b", "S2", dup_group=["b", "c"], primary=True),
                        cand("c", "S2", dup_group=["b", "c"], primary=False),
                        cand("d", "S3", stoppable=False, reason="why", command=[])]

        outside = [{"id": "Z", "pid": 9, "version": "2.0.0", "kind": "interactive", "job": "", "host": "tui",
                    "state": "idle", "status_raw": "idle", "cwd": "/o", "title": "O", "model": ""}]
        with mock.patch.object(ac, "_agent_tv", lambda: TV()), \
             mock.patch.object(ac, "session_state", lambda sid, status=None: "busy"), \
             mock.patch.object(_claude.ClaudeProvider, "running", lambda s: outside), \
             mock.patch.dict(ac._AGENT_VERSIONS, {"claude": {"version": "2.1.325", "checked_at": time.time()}}):
            status = ac.agent_status()
            plan = ac.agent_plan_upgrade("claude")
        self.assertIsNotNone(plan)
        item = ac._agent_item(cand("a", "S1"), "prompted", "detail")
        job = {"id": 1, "agent": "claude", "action": "upgrade", "state": "done", "step": "s", "started": 0,
               "finished": 1, "old": "1", "new": "2", "output": "o", "items": [item],
               "outside": plan["outside"], "summary": "sum"}

        def keys(rows):
            return set().union(*[set(r) for r in rows]) if rows else set()
        emitted = {"agents": keys(status["agents"]), "st": set(status), "plan": set(plan),
                   "c": keys(plan["stop"]) | keys(plan["cannot_stop"]), "o": keys(plan["outside"]),
                   "i": keys(job["items"]), "job": set(job)}
        emitted["a"] = emitted.pop("agents")
        self.assertTrue(plan["stop"] and plan["cannot_stop"] and plan["outside"], plan)
        for var, names in reads.items():
            missing = names - emitted[var]
            self.assertFalse(missing, "the UI reads %s.%s but the server emits only %s"
                             % (var, sorted(missing), sorted(emitted[var])))
        self.assertIn("out_of_date_text", reads["o"])
        self.assertTrue(set(reads) >= {"a", "c", "o", "i", "job", "plan", "st"}, reads)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_node_check(self):
        r = subprocess.run(["node", "--check", _JS], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
