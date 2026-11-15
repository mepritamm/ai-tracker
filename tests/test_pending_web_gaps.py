"""UI-side gaps from the plan's H8 test plan (T9-T13), hand-built fixtures where the server shape is not the point:
read-only visitors get nothing (no list, no item, no fetch), hostile strings are escaped in the card, list rows,
item modal and Control Room tile, the dialog's scheduler Reinstall round-trip and its scan-now refusal text.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tests.test_pending_ui_classic import _PRE, _APP
from tests.test_pending_ui_board import (
    _DRIVER as _BOARD_DRIVER, _MID, _PRE as _BOARD_PRE, _REAL_DOM_PREAMBLE, _bundle_js, _extract_marker_json,
    _run_node, NOW, make_session,
)
from tests.test_update_settings_ui import _BODY as _DLG_BODY, _DOM as _DLG_DOM, _sched

_DIALOGS = os.path.join(os.path.dirname(_APP), "ext_cr_dialogs.js")
IMG = "<img src=x onerror=1>"
QPATH = "/w/a\"b'c"

_DRV = r"""
(async function () {
  var HOSTILE = JSON.parse(process.env.GAPS_IN);
  var rep = { items: [{ id: "h1", label: HOSTILE.img, path: HOSTILE.path, branch: HOSTILE.img, verdict: "pending" }],
              tmp: [], running: false, card: { show: true, title: HOSTILE.img, summary: HOSTILE.img, as_of: HOSTILE.img } };
  var item = { title: HOSTILE.img, when: HOSTILE.img, md: "**Branch** `" + HOSTILE.img + "` " + HOSTILE.path + "\n\n" + HOSTILE.img,
               resume: { cwd: HOSTILE.path, prompt: HOSTILE.img } };
  ROUTES["/api/pending"] = () => okJson(rep);
  ROUTES["/api/pending/item"] = () => okJson(item);
  var txt = (e) => (e.textContent || "") + (e.children || []).map(txt).join("  ");

  // read-only visitors: no fetch, no list, no item, no modal, no card
  trackerReadOnly = true;
  CALLS.length = 0; pendingAt = 0; pendingCache = null;
  // no awaits between setting the flag and the calls: app.js's own startup poll resets trackerReadOnly from the stub's headers
  var ro = [loadPending(), openPendingItem("h1")]; openPendingList(rep);
  pendingCache = rep; renderPendingSide();
  OUT.ro_card_hidden = $("pendside").hidden === true && $("pendside").innerHTML === "";
  await Promise.all(ro); await flush();
  OUT.ro_fetches = CALLS.filter((c) => c.url.indexOf("/api/pending") === 0).length; OUT.ro_urls = CALLS.map((c) => c.url);
  OUT.ro_modal_open = $("msgmodal").style.display === "flex";

  // hostile strings, writable page
  trackerReadOnly = false;
  renderPendingSide();
  OUT.card_html = $("pendside").innerHTML;
  openPendingList(rep);
  var row = find($("msgbody"), (e) => (e.className || "").indexOf("pendrow") >= 0);
  OUT.row_text = txt(row);
  OUT.list_summary_title = $("msgtitle").textContent;
  window.ExtLaunch = { openAt: () => Promise.resolve({ ok: true }) };
  await openPendingItem("h1");
  OUT.item_title = $("msgtitle").textContent;
  OUT.item_body = $("msgbody").innerHTML;
  find($("msgbody"), (e) => e.textContent === "Copy prompt").onclick(); await flush();
  OUT.clip = CLIP.slice();
  console.log("@@OUT@@" + JSON.stringify(OUT));
})().catch((e) => { console.log("@@ERR@@" + (e && e.stack || e)); });
"""


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestClassicReadOnlyAndHostile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(_APP, encoding="utf-8") as fh:
            src = fh.read()
        env = dict(os.environ, GAPS_IN=json.dumps({"img": IMG, "path": QPATH}))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "h.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_PRE + src + "\n" + _DRV)
            p = subprocess.run(["node", path], capture_output=True, text=True, timeout=60, env=env)
        if "@@OUT@@" not in p.stdout:
            raise AssertionError("harness failed rc=%s\n%s\n%s" % (p.returncode, p.stdout[-2000:], p.stderr[-2000:]))
        cls.O = json.loads(p.stdout.split("@@OUT@@", 1)[1].strip().splitlines()[0])

    def test_read_only_visitor_gets_nothing(self):
        self.assertEqual(self.O["ro_fetches"], 0, self.O["ro_urls"])
        self.assertFalse(self.O["ro_modal_open"])
        self.assertTrue(self.O["ro_card_hidden"])

    def test_card_escapes_every_field(self):
        h = self.O["card_html"]
        self.assertNotIn("<img", h)
        self.assertIn("&lt;img", h)

    def test_list_row_and_titles_are_text_not_markup(self):
        self.assertIn(IMG, self.O["row_text"])
        self.assertIn(QPATH, self.O["row_text"])
        self.assertEqual(self.O["item_title"], IMG)            # textContent: shown literally, never parsed

    def test_item_markdown_body_is_escaped(self):
        b = self.O["item_body"]
        self.assertNotIn("<img", b)
        self.assertIn("&lt;img", b)

    def test_copy_prompt_copies_the_literal_server_prompt(self):
        self.assertEqual(self.O["clip"], [IMG])


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestBoardTileHostile(unittest.TestCase):
    def test_tile_shows_hostile_card_as_text(self):
        card = {"show": True, "title": IMG, "summary": IMG, "as_of": IMG}
        drv = _BOARD_DRIVER.replace("pendingCache = { card: { show: true, title: 'Pending work', summary: '3 items', as_of: '2026-11-01' } };",
                                    "pendingCache = { card: %s };" % json.dumps(card))
        self.assertIn(json.dumps(card), drv)
        drv = drv.replace("__o.text = ts[0] ? allTextIn(ts[0]) : '';",
                          "__o.text = ts[0] ? allTextIn(ts[0]) : ''; __o.html = JSON.stringify((function w(n) { return [n.innerHTML].concat((n._children || []).map(w)); })(ts[0]));")
        sess = [make_session("s%d" % i, NOW - 10 - i, title="T%d" % i, waiting=True, ended=False) for i in range(3)]
        drv = drv.replace("__SESSIONS__", json.dumps(sess)).replace("__NOW__", str(NOW)).replace("__MARK__", json.dumps("===GAPS==="))
        rc, out, err = _run_node("\n".join([_REAL_DOM_PREAMBLE, _BOARD_PRE, _bundle_js(), drv, _MID]))
        if rc != 0:
            raise AssertionError("node failed (%d)\n%s\n%s" % (rc, out, err))
        o = _extract_marker_json(out, "===GAPS===")
        self.assertIn(IMG, o["text"])
        self.assertNotIn("<img", o["html"])


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestDialogSchedulerGaps(unittest.TestCase):
    def _run(self, scen):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.js")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(_DLG_DOM + _DLG_BODY)
            proc = subprocess.run(["node", p, _DIALOGS, json.dumps(scen)], capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node exited %d\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_reinstall_posts_install_and_stays_installed(self):
        inst = _sched(installed=True, last_exit=0, root="/x", root_exists=True)
        r = self._run(dict(tab="Board", sched=inst, clicks=["Reinstall"],
                           afterPost={"install": {"installed": True, "last_exit": 0, "root": "/y", "root_exists": True}}))
        self.assertEqual(r["posts"], [["/api/scheduler", {"action": "install"}]])
        self.assertEqual(r["after_Reinstall"]["buttons"], ["Reinstall", "Uninstall", "Scan now"])
        self.assertIn("runs from /y", r["after_Reinstall"]["text"])

    def test_install_reinstall_uninstall_round_trip(self):
        r = self._run(dict(tab="Board", sched=_sched(), clicks=["Install", "Reinstall", "Uninstall"], afterPost={
            "install": {"installed": True, "last_exit": 0, "root": "/x", "root_exists": True},
            "uninstall": {"installed": False, "opted_out": True}}))
        self.assertEqual([p[1]["action"] for p in r["posts"]], ["install", "install", "uninstall"])
        self.assertEqual(r["after_Install"]["buttons"], ["Reinstall", "Uninstall", "Scan now"])
        self.assertEqual(r["after_Uninstall"]["buttons"], ["Install", "Scan now"])
        self.assertIn("Turned off", r["after_Uninstall"]["text"])

    def _scan(self, reply, with_lp=True):
        body = _DLG_BODY.replace(
            "if (url === '/api/pending/run') { posts.push([url, body]); return json({started: true}); }",
            "if (url === '/api/pending/run') { posts.push([url, body]); return json(SCEN.runReply.body, SCEN.runReply.ok); }")
        self.assertIn("SCEN.runReply", body)
        body = body.replace("const SRC =", "if (SCEN.lp) window.loadPending = () => { posts.push(['loadPending']); };\nconst SRC =", 1)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.js")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(_DLG_DOM + body)
            proc = subprocess.run(["node", p, _DIALOGS, json.dumps(dict(tab="Board", sched=_sched(), clicks=["Scan now"],
                                   afterPost={}, runReply=reply, lp=with_lp))], capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node exited %d\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_dialog_scan_now_refusal_shows_server_error_or_fallback_and_success_reloads(self):
        r = self._scan({"ok": False, "body": {"error": "scan refused: tmp checkout"}})
        self.assertIn("scan refused: tmp checkout", r["after_Scan now"]["text"])
        self.assertNotIn(["loadPending"], r["posts"])
        r = self._scan({"ok": False, "body": {}})
        self.assertIn("scan refused", r["after_Scan now"]["text"])
        r = self._scan({"ok": True, "body": {"started": True}})
        self.assertIn(["loadPending"], r["posts"])
        self.assertNotIn("scan refused", r["after_Scan now"]["text"])
        r = self._scan({"ok": True, "body": {"started": True}}, with_lp=False)     # absent loadPending: no throw
        self.assertEqual(r["posts"], [["/api/pending/run", {}]])


if __name__ == "__main__":
    unittest.main()
