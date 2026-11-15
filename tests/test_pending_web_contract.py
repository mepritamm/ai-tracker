"""Page <-> server contract for the pending-work worker (E3 central worry: a card that never shows because
of a field-name mismatch). The JSON fed to the REAL page code is produced by the server's own code:
`pending.run_once` + `pending.load_report` + `pending.item_detail` on a temp git fixture (including a
branch named `<img/src=x/onerror=alert(1)>` and a worktree dir with quotes in its name), `update.update_status`
via `server._update_body` on a fixture clone that is one commit behind, and `schedule.sched_status` via
`server._sched_body` with a faked launchctl. No hand-written report/update/scheduler JSON for those.

Renderers driven under node: classic card / list / item (app.js), the Control Room tile (real page bundle),
the Settings dialog's scheduler + update blocks (ext_cr_dialogs.js).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from aitracker import pending, schedule, server, update
from tests.pending_fixture import make_fixture, requires_git
from tests.test_pending_ui_classic import _PRE
from tests.test_pending_ui_board import (
    _DRIVER as _BOARD_DRIVER, _MID, _PRE as _BOARD_PRE, _REAL_DOM_PREAMBLE, _bundle_js, _extract_marker_json,
    _run_node, NOW, make_session,
)
from tests.test_update_settings_ui import _BODY as _DLG_BODY, _DOM as _DLG_DOM

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "aitracker", "web", "app.js")
_DIALOGS = os.path.join(_ROOT, "aitracker", "web", "ext_cr_dialogs.js")
_HAS_NODE = shutil.which("node") is not None
HOSTILE_BRANCH = "<img/src=x/onerror=alert(1)>"
QUOTE_DIR = "we\"ird'dir"


class _Proc:
    returncode = 0
    stdout = "state = running\n\tlast exit code = 0\n"


class _Shim:
    """Fx wants a TestCase for addCleanup; class-level fixture, so route it to addClassCleanup."""
    def __init__(self, cls):
        self.addCleanup = cls.addClassCleanup


@unittest.skipUnless(_HAS_NODE, "node not available")
@requires_git
class TestPendingWebContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fx = make_fixture(_Shim(cls))
        cls.fx = fx
        wt = fx.worktree("feat")
        with open(os.path.join(wt, "a.txt"), "w") as fh:
            fh.write("edited\n")
        wt2 = fx.worktree(HOSTILE_BRANCH, name=QUOTE_DIR)
        with open(os.path.join(wt2, "a.txt"), "w") as fh:
            fh.write("edited too\n")
        pending.run_once("dry-run")
        report = pending.load_report()
        items = {}
        for it in report["items"] + report["tmp"]:
            d = pending.item_detail(it["id"])
            if d is not None:
                items[it["id"]] = d
        # a clone one commit AHEAD of the remote, then fetched: the checkout under update is exactly one behind
        other = os.path.join(fx.root, "other")
        fx.git(fx.root, "clone", fx.remote, other)
        fx.commit(other, "b.txt", "x", "Upstream thing")
        fx.git(other, "push", "origin", "main")
        fx.git(fx.repo, "fetch", "origin")
        with mock.patch.object(update, "_root", lambda: fx.repo):
            upd = server._update_body(update.update_status())
        optout = os.path.join(fx.root, "optout")
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(schedule, "_read_plist", lambda: {"WorkingDirectory": fx.repo}), \
                mock.patch.object(server, "_optout_path", lambda: optout), \
                mock.patch.object(server, "sched_status", lambda: schedule.sched_status(run=lambda *a, **k: _Proc())):
            sched = server._sched_body()
        cls.data = json.loads(json.dumps({"report": report, "items": items, "update": upd, "sched": sched}))

    # ---- sanity: the fixture really produced what the renderers are expected to show
    def test_server_shapes_are_what_we_think(self):
        d = self.data
        self.assertTrue(d["report"]["card"]["show"])
        self.assertGreaterEqual(d["report"]["card"]["count"], 2)
        branches = [i["branch"] for i in d["report"]["items"]]
        self.assertIn("feat", branches)
        self.assertIn(HOSTILE_BRANCH, branches)
        self.assertTrue(all(i["id"] in d["items"] for i in d["report"]["items"]))
        self.assertEqual(d["update"]["kind"], "git")
        self.assertEqual(d["update"]["behind"], 1)
        self.assertTrue(d["update"]["can_update"])
        self.assertTrue(d["sched"]["installed"])
        self.assertEqual(d["sched"]["last_exit"], 0)

    # ---- classic page: card + list + item ----------------------------------------------------------
    def _classic(self, card_override=None):
        drv = r"""
(async function () {
  var IN = JSON.parse(process.env.CONTRACT_IN);
  ROUTES["/api/pending"] = () => okJson(IN.report);
  ROUTES["/api/pending/item"] = () => {
    var u = CALLS[CALLS.length - 1].url, id = decodeURIComponent(u.split("id=")[1]);
    return IN.items[id] ? okJson(IN.items[id]) : { ok: false, headers: { get: () => null }, json: () => Promise.resolve({}) };
  };
  trackerReadOnly = false;
  await loadPending(); await flush();
  OUT.card_html = $("pendside").innerHTML; OUT.card_hidden = $("pendside").hidden;
  if ($("pendside").onclick) $("pendside").onclick(); else openPendingList(pendingCache);
  OUT.list_title = $("msgtitle").textContent; OUT.list_when = $("msgwhen").textContent;
  var rows = []; (function walk(e) { if ((e.className || "").indexOf("pendrow") >= 0) rows.push(e); (e.children || []).forEach(walk); })($("msgbody"));
  var txt = (e) => (e.textContent || "") + (e.children || []).map(txt).join("  ");
  OUT.rows = rows.map(txt);
  OUT.row_ids = {};
  var launched = []; window.ExtLaunch = { openAt: (c, m, p) => { launched.push([c, m, p]); return Promise.resolve({ ok: true }); } };
  OUT.item = {};
  for (var id of Object.keys(IN.items)) {
    await openPendingItem(id);
    var res = find($("msgbody"), (e) => e.textContent === "Resume"), cp = find($("msgbody"), (e) => e.textContent === "Copy prompt");
    launched.length = 0; CLIP.length = 0;
    res && res.onclick(); cp && cp.onclick(); await flush();
    OUT.item[id] = { title: $("msgtitle").textContent, when: $("msgwhen").textContent, body: $("msgbody").innerHTML,
                     has_resume: !!res, has_copy: !!cp, launched: launched.slice(), clip: CLIP.slice() };
  }
  console.log("@@OUT@@" + JSON.stringify(OUT));
})().catch((e) => { console.log("@@ERR@@" + (e && e.stack || e)); });
"""
        with open(_APP, encoding="utf-8") as fh:
            src = fh.read()
        data = json.loads(json.dumps(self.data))
        if card_override:
            data["report"]["card"].update(card_override)
        env = dict(os.environ, CONTRACT_IN=json.dumps(data))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "h.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_PRE + src + "\n" + drv)
            p = subprocess.run(["node", path], capture_output=True, text=True, timeout=60, env=env)
        if "@@OUT@@" not in p.stdout:
            raise AssertionError("harness failed rc=%s\n%s\n%s" % (p.returncode, p.stdout[-2000:], p.stderr[-2000:]))
        return json.loads(p.stdout.split("@@OUT@@", 1)[1].strip().splitlines()[0])

    def test_classic_card_list_and_item_render_the_servers_shape(self):
        o, d = self._classic(), self.data
        card = d["report"]["card"]
        self.assertFalse(o["card_hidden"])
        self.assertIn(card["summary"], o["card_html"])
        self.assertIn(card["title"], o["card_html"])
        self.assertIn("as of " + card["as_of"], o["card_html"])
        self.assertEqual(o["list_title"], "Pending work")
        self.assertEqual(o["list_when"], card["summary"])
        rows = d["report"]["items"] + d["report"]["tmp"]
        self.assertEqual(len(o["rows"]), len(rows))
        for it, text in zip(rows, o["rows"]):
            self.assertIn(it.get("label") or it.get("reason") or it["verdict"], text)       # server-chosen status text
            self.assertIn(it["path"], text)
            if it.get("branch"):
                self.assertIn(it["branch"], text)
        for iid, det in d["items"].items():
            got = o["item"][iid]
            self.assertEqual(got["title"], det["title"])
            self.assertEqual(got["when"], det["when"])
            self.assertTrue(got["has_resume"] and got["has_copy"])
            self.assertEqual(got["launched"], [[det["resume"]["cwd"], "new", det["resume"]["prompt"]]])
            self.assertEqual(got["clip"], [det["resume"]["prompt"]])
        feat = next(i for i in d["report"]["items"] if i["branch"] == "feat")
        self.assertIn("a.txt", o["item"][feat["id"]]["body"])               # the live git status the server fenced

    def test_hostile_branch_and_quoted_path_are_escaped_in_list_and_item(self):
        o, d = self._classic(), self.data
        hostile = next(i for i in d["report"]["items"] if i["branch"] == HOSTILE_BRANCH)
        self.assertIn('"', hostile["path"])
        self.assertIn("'", hostile["path"])
        # rows are built with textContent: the literal strings are shown, never parsed
        self.assertTrue(any(HOSTILE_BRANCH in r and hostile["path"] in r for r in o["rows"]))
        body = o["item"][hostile["id"]]["body"]                              # md() output: innerHTML
        self.assertNotIn("<img", body)
        self.assertNotIn("onerror=alert(1)>", body.replace("&gt;", ""))
        self.assertIn("&lt;img", body)
        self.assertNotIn("<img", o["card_html"])

    # ---- Control Room tile -----------------------------------------------------------------------
    def _board(self, card_override=None):
        drv = _BOARD_DRIVER.replace("pendingCache = { card: { show: true, title: 'Pending work', summary: '3 items', as_of: '2026-11-01' } };",
                                    "pendingCache = JSON.parse(process.env.CONTRACT_IN).report;")
        self.assertIn("process.env.CONTRACT_IN", drv)
        drv = drv.replace("__o.text = ts[0] ? allTextIn(ts[0]) : '';",
                          "__o.text = ts[0] ? allTextIn(ts[0]) : ''; __o.tileHtml = JSON.stringify(ts[0] && ts[0]._children.map(function (c) { return c.innerHTML; }));")
        sess = [make_session("s%d" % i, NOW - 10 - i, title="T%d" % i, waiting=True, ended=False) for i in range(3)]
        drv = drv.replace("__SESSIONS__", json.dumps(sess)).replace("__NOW__", str(NOW)).replace("__MARK__", json.dumps("===CONTRACT==="))
        data = json.loads(json.dumps(self.data))
        if card_override:
            data["report"]["card"].update(card_override)
        with mock.patch.dict(os.environ, {"CONTRACT_IN": json.dumps(data)}):
            rc, out, err = _run_node("\n".join([_REAL_DOM_PREAMBLE, _BOARD_PRE, _bundle_js(), drv, _MID]))
        if rc != 0:
            raise AssertionError("node failed (%d)\n%s\n%s" % (rc, out, err))
        return _extract_marker_json(out, "===CONTRACT===")

    def test_board_tile_renders_the_servers_card(self):
        o, card = self._board(), self.data["report"]["card"]
        self.assertTrue(o["firstIsPending"])
        self.assertIn(card["title"], o["text"])
        self.assertIn(card["summary"], o["text"])
        self.assertIn("as of " + card["as_of"], o["text"])
        self.assertEqual(o["opened"], 1)

    def test_one_card_two_renderers_show_identical_text(self):
        card = self.data["report"]["card"]
        classic, board = self._classic()["card_html"], self._board()["text"]
        for part in (card["title"], card["summary"], "as of " + card["as_of"]):
            self.assertIn(part, classic)
            self.assertIn(part, board)

    def test_one_card_show_false_hides_both(self):
        # the REAL server report with only card.show forced false (the one field the server owns)
        self.assertTrue(self._classic()["card_hidden"] is False)
        self.assertTrue(self._classic({"show": False})["card_hidden"])
        self.assertEqual(self._board_tiles({"show": False}), 0)
        self.assertEqual(self._board_tiles(), 1)

    def _board_tiles(self, card_override=None):
        drv = r"""
try {
  var __r = JSON.parse(process.env.CONTRACT_IN).report;
  var root = makeReal('div'); root.isConnected = true; docBody.appendChild(root);
  window.CR.board.mount(root, { emit: function () {}, readOnly: function () { return false; } });
  window.CR.board.update({ sessions: __SESSIONS__, now: __NOW__, pending: __r });
  console.log("===CT===");
  console.log(JSON.stringify(queryAllReal(root, '.cr-tile--pending').length));
} catch (e) { console.error('DRIVER-THREW: ' + (e && e.stack || e)); process.exit(1); }
"""
        sess = [make_session("s%d" % i, NOW - 10 - i, title="T%d" % i, waiting=True, ended=False) for i in range(3)]
        drv = drv.replace("__SESSIONS__", json.dumps(sess)).replace("__NOW__", str(NOW))
        data = json.loads(json.dumps(self.data))
        if card_override:
            data["report"]["card"].update(card_override)
        with mock.patch.dict(os.environ, {"CONTRACT_IN": json.dumps(data)}):
            rc, out, err = _run_node("\n".join([_REAL_DOM_PREAMBLE, _BOARD_PRE, _bundle_js(), drv, _MID]))
        if rc != 0:
            raise AssertionError("node failed (%d)\n%s\n%s" % (rc, out, err))
        return _extract_marker_json(out, "===CT===")

    # ---- Settings dialog: scheduler + update blocks ----------------------------------------------
    def _dialog(self, tab, **scen):
        dom = _DLG_DOM.replace("set innerHTML(v){", "set innerHTML(v){ if(v) (global.__IH=global.__IH||[]).push(String(v));")
        body = _DLG_BODY.replace("out.posts = posts;", "out.posts = posts; out.ih = global.__IH || [];")
        s = dict(tab=tab, clicks=[], afterPost={}, **scen)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.js")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(dom + body)
            proc = subprocess.run(["node", p, _DIALOGS, json.dumps(s)], capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node exited %d\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_dialog_scheduler_block_renders_the_servers_body(self):
        s = self.data["sched"]
        r = self._dialog("Board", sched=s)
        self.assertIn("Installed (launchd)", r["before"]["text"])
        self.assertIn("last exit 0", r["before"]["text"])
        self.assertIn("runs from " + s["root"], r["before"]["text"])
        self.assertEqual(r["before"]["buttons"], ["Reinstall", "Uninstall", "Scan now"])

    def test_dialog_update_block_renders_the_servers_body(self):
        u = self.data["update"]
        r = self._dialog("Server", update=u)
        t = r["before"]["text"]
        self.assertIn("main @ " + u["head"][:7] + " — " + u["head_subject"], t)
        self.assertIn("1 behind " + u["upstream"], t)
        self.assertIn("No local changes", t)
        self.assertEqual(r["before"]["buttons"], ["Check for updates", "Update and restart"])
        self.assertEqual(r["before"]["disabled"], [])

    def test_dialog_hostile_strings_reach_text_nodes_only(self):
        u = dict(self.data["update"], branch=HOSTILE_BRANCH, head_subject="<img src=x onerror=1>",
                 dirty=[' M "q\'.py'], can_update=False, reason='bad "reason" <b>')
        s = dict(self.data["sched"], root='/p"ath/<i>', root_exists=True)
        ru = self._dialog("Server", update=u)
        rs = self._dialog("Board", sched=s)
        self.assertIn(HOSTILE_BRANCH, ru["before"]["text"])
        self.assertIn("<img src=x onerror=1>", ru["before"]["text"])
        self.assertIn('bad "reason" <b>', ru["before"]["text"])
        self.assertIn('/p"ath/<i>', rs["before"]["text"])
        for r in (ru, rs):
            for html in r["ih"]:
                for bad in ("<img", "onerror", "<i>", "<b>"):
                    self.assertNotIn(bad, html)


if __name__ == "__main__":
    unittest.main()
