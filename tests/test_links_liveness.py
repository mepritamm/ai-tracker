"""Links-panel noise: a `files`-shape entry (path/ops/created/last/agent) whose LOCAL
path no longer exists on disk is dead noise, not a link worth showing -- ephemeral
subagent transcripts under a tmp dir and deleted project files are the two cases seen
in practice.

THE CONTRACT (revised from a first pass that DROPPED dead entries from `files`
outright): util.annotate_liveness() marks each entry with a boolean `alive` key and
de-dupes the rest -- it never removes anything. `files` stays the session's complete,
honest history, and `counts.created`/`counts.edited` (computed by each provider's own
parse(), untouched by annotate_liveness()) keep reporting the true count even for a
file that was created and later deleted -- a session that created 10 files and
cleaned up 6 still reports "created 10", and the Files panel still lists all 10 (a
dead one dimmed, per ext_cr_detail.js's renderFiles). Only the control room's Links
panel (ext_cr_detail.js's deriveLinks) reads `alive` to skip dead rows entirely --
that is the one place the noise complaint actually lives.

registry.parse_any() applies annotate_liveness() to every provider's `files` list on
its way out (the one seam both the classic dashboard and the control room actually
receive session data through), so the Links panel inherits it with no client-side
change beyond deriveLinks() itself reading the new key.

A REMOTE link (http/https -- a PR URL, a link cited in narration) must be marked
alive UNCONDITIONALLY: this app makes no outbound network requests, ever, so there
must be no existence check, no socket, no DNS lookup, no timeout-based probe for one.
That invariant is the one most likely to regress under a future "improvement" (e.g.
someone "helpfully" adding a HEAD request to detect a 404'd PR) -- see
test_no_network_call_is_ever_made below, which proves it by making socket-creation
itself raise and asserting the annotation still completes.
"""
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from aitracker.util import annotate_liveness, _local_path

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
_HAS_NODE = shutil.which("node") is not None
sys.path.insert(0, _ROOT)


class TestLocalPath(unittest.TestCase):
    """_local_path: the thing annotate_liveness actually stats, or None to skip the
    check (and the network) entirely."""

    def test_bare_path_is_itself(self):
        self.assertEqual(_local_path("/tmp/x/y.py"), "/tmp/x/y.py")

    def test_http_and_https_are_never_local(self):
        self.assertIsNone(_local_path("http://localhost:8080/x"))
        self.assertIsNone(_local_path("https://github.com/acme/widget/pull/42"))

    def test_file_uri_resolves_to_a_path(self):
        self.assertEqual(_local_path("file:///Users/x/y%20z.py"), "/Users/x/y z.py")

    def test_tilde_is_expanded(self):
        # Defect 2: unlike a relative path, `~` is unambiguous regardless of cwd --
        # os.path.expanduser must run unconditionally.
        self.assertEqual(_local_path("~/x.py"), os.path.join(os.path.expanduser("~"), "x.py"))

    def test_relative_path_with_no_cwd_is_unresolvable(self):
        # Defect 2: a relative Claude file_path has no cwd anchoring at the point it's
        # stored (providers/claude.py) -- without a session cwd to anchor it, judging
        # it against the SERVER PROCESS's cwd would be silently wrong, so it must come
        # back None (the same "can't judge it, don't probe it" answer as an http(s) URL).
        self.assertIsNone(_local_path("aitracker/util.py"))
        self.assertIsNone(_local_path("relative/sub/file.py"))

    def test_relative_path_is_anchored_to_the_given_cwd(self):
        # Defect 2, option (c): when the caller (registry.parse_any) hands over the
        # session's own cwd, a relative path resolves against THAT root, not the
        # server's.
        self.assertEqual(_local_path("sub/file.py", cwd="/work/proj"), "/work/proj/sub/file.py")

class TestAnnotateLiveness(unittest.TestCase):
    """annotate_liveness: the liveness marker itself, in isolation from any provider."""

    def setUp(self):
        # A REAL file on disk, created and removed by this test -- not a mocked
        # filesystem -- so "alive" and "dead" are proven against the real
        # os.path.exists this code actually calls.
        self.dir = tempfile.mkdtemp()
        self.alive_path = os.path.join(self.dir, "alive.py")
        with open(self.alive_path, "w") as fh:
            fh.write("x = 1\n")
        self.dead_path = os.path.join(self.dir, "dead.py")
        with open(self.dead_path, "w") as fh:
            fh.write("y = 2\n")
        os.remove(self.dead_path)   # existed a moment ago; gone now -- the exact
                                     # "ephemeral subagent transcript" shape in practice

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_existing_local_path_is_marked_alive(self):
        out = annotate_liveness([{"path": self.alive_path, "ops": 1, "created": True}])
        self.assertEqual([f["path"] for f in out], [self.alive_path])
        self.assertTrue(out[0]["alive"])

    def test_missing_local_path_stays_present_but_marked_dead(self):
        """THE key regression guard: a dead entry is NOT dropped -- it is still in
        `files`, just marked alive=False."""
        out = annotate_liveness([{"path": self.dead_path, "ops": 1, "created": True}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["path"], self.dead_path)
        self.assertFalse(out[0]["alive"])

    def test_mixed_alive_and_dead_both_survive(self):
        out = annotate_liveness([
            {"path": self.alive_path, "ops": 1, "created": True},
            {"path": self.dead_path, "ops": 1, "created": True},
        ])
        by_path = {f["path"]: f for f in out}
        self.assertEqual(len(out), 2)
        self.assertTrue(by_path[self.alive_path]["alive"])
        self.assertFalse(by_path[self.dead_path]["alive"])

    def test_https_link_marked_alive_and_never_checked(self):
        out = annotate_liveness([
            {"path": "https://github.com/acme/widget/pull/42", "ops": 1, "created": True},
            {"path": self.dead_path, "ops": 1, "created": True},
        ])
        by_path = {f["path"]: f for f in out}
        self.assertTrue(by_path["https://github.com/acme/widget/pull/42"]["alive"])
        self.assertFalse(by_path[self.dead_path]["alive"])

    def test_duplicate_paths_collapse_to_one(self):
        out = annotate_liveness([
            {"path": self.alive_path, "ops": 1, "created": False, "last": "2026-01-01T00:00:00Z"},
            {"path": self.alive_path, "ops": 2, "created": True, "last": "2026-01-02T00:00:00Z"},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ops"], 3)                          # merged
        self.assertTrue(out[0]["created"])                          # sticky: created wins
        self.assertEqual(out[0]["last"], "2026-01-02T00:00:00Z")    # latest wins
        self.assertTrue(out[0]["alive"])

    def test_normalized_duplicate_paths_collapse_too(self):
        weird = os.path.join(self.dir, ".", "alive.py")
        out = annotate_liveness([
            {"path": self.alive_path, "ops": 1, "created": True},
            {"path": weird, "ops": 1, "created": False},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ops"], 2)

    def test_no_path_key_is_skipped_not_crashed(self):
        out = annotate_liveness([{"ops": 1, "created": True}])
        self.assertEqual(out, [])

    def test_no_network_call_is_ever_made(self):
        """The hard invariant: even if opening a socket would explode, annotating a
        list mixing local dead/alive paths with remote https links must still
        complete and produce the right answer -- proving nothing here reaches the
        network, not just that it happens not to today."""
        files = [
            {"path": self.alive_path, "ops": 1, "created": True},
            {"path": self.dead_path, "ops": 1, "created": True},
            {"path": "https://github.com/acme/widget/pull/7", "ops": 1, "created": True},
        ]
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network touched!")):
            out = annotate_liveness(files)
        by_path = {f["path"]: f for f in out}
        self.assertEqual(len(out), 3)
        self.assertTrue(by_path[self.alive_path]["alive"])
        self.assertFalse(by_path[self.dead_path]["alive"])
        self.assertTrue(by_path["https://github.com/acme/widget/pull/7"]["alive"])

    def test_one_stat_per_unique_path(self):
        """Performance: repeats of the SAME path must cost one os.path.exists call,
        not one per entry -- a session can carry ~100 file entries with plenty of
        repeats across main-session and background-agent activity."""
        files = [{"path": self.alive_path, "ops": 1, "created": False} for _ in range(5)]
        files += [{"path": self.dead_path, "ops": 1, "created": False} for _ in range(5)]
        real_exists = os.path.exists
        calls = []

        def counting_exists(p):
            calls.append(p)
            return real_exists(p)

        with mock.patch("aitracker.util.os.path.exists", side_effect=counting_exists):
            out = annotate_liveness(files)
        self.assertEqual(sorted(calls), sorted([self.alive_path, self.dead_path]))  # exactly one each
        self.assertEqual(len(out), 2)  # both survive, deduped, neither dropped

    # ---- Defect 1: a non-string `path` must not raise -------------------------------
    # providers/claude.py stores a model-authored tool_use's raw `file_path` behind only
    # a truthiness guard (`if fp:`), so a malformed value -- a list, dict, or number --
    # reaches this function. Before the fix, `_local_path`'s `.startswith()` call on
    # such a value raised AttributeError, which registry.parse_any() propagated straight
    # into a 500 on /api/session (also search_session and term_gate).

    def test_non_string_list_path_does_not_raise(self):
        out = annotate_liveness([{"path": ["a", "b"], "ops": 1, "created": True}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["path"], ["a", "b"])
        self.assertTrue(out[0]["alive"], "can't judge it -- pass it through as alive, don't hide it")

    def test_non_string_dict_path_does_not_raise(self):
        out = annotate_liveness([{"path": {"weird": 1}, "ops": 1}])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["alive"])

    def test_non_string_int_path_does_not_raise(self):
        out = annotate_liveness([{"path": 42, "ops": 1}])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["alive"])

    def test_non_string_path_mixed_with_real_paths_does_not_raise(self):
        """The exact shape that crashed the route: one malformed entry sitting
        alongside normal live/dead ones in the same `files` list."""
        out = annotate_liveness([
            {"path": self.alive_path, "ops": 1, "created": True},
            {"path": ["a", "b"], "ops": 1, "created": True},
            {"path": self.dead_path, "ops": 1, "created": True},
        ])
        self.assertEqual(len(out), 3)
        by_id = {repr(f["path"]): f for f in out}
        self.assertTrue(by_id[repr(self.alive_path)]["alive"])
        self.assertFalse(by_id[repr(self.dead_path)]["alive"])
        self.assertTrue(by_id[repr(["a", "b"])]["alive"])

    def test_duplicate_non_string_paths_collapse_without_a_typeerror(self):
        """A list/dict `path` is unhashable -- the dedupe key must not be the raw
        value itself, or two such entries would raise TypeError on the dict lookup."""
        out = annotate_liveness([
            {"path": ["a", "b"], "ops": 1},
            {"path": ["a", "b"], "ops": 2},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ops"], 3)

    # ---- Defect 2: relative and `~` paths must be judged against the right root -----

    def test_tilde_path_is_expanded_and_judged_for_real(self):
        # A real file under a temp HOME, not a mocked filesystem -- proves
        # os.path.expanduser is actually applied, not just documented.
        with mock.patch.dict(os.environ, {"HOME": self.dir}):
            alive_out = annotate_liveness([{"path": "~/alive.py"}])
            dead_out = annotate_liveness([{"path": "~/dead.py"}])
        self.assertTrue(alive_out[0]["alive"])
        self.assertFalse(dead_out[0]["alive"])

    def test_relative_path_without_cwd_is_not_silently_marked_dead(self):
        """Before the fix: a relative path was resolved against the SERVER PROCESS's
        cwd, so a real project file could be judged dead purely because the server
        happened not to be running from that directory. Without a cwd to anchor it,
        it must be treated as unknown/alive, never guessed at as dead."""
        out = annotate_liveness([{"path": "some/relative/file.py"}])  # no cwd given
        self.assertTrue(out[0]["alive"])

    def test_relative_path_anchored_to_session_cwd_is_judged_correctly(self):
        """When the caller supplies the session's own cwd (registry.parse_any passes
        meta.cwd), a relative path is judged against the RIGHT root -- strictly better
        than leaving it unresolved."""
        sub = os.path.join(self.dir, "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "real.py"), "w") as fh:
            fh.write("z = 1\n")
        alive_out = annotate_liveness([{"path": "sub/real.py"}], cwd=self.dir)
        dead_out = annotate_liveness([{"path": "sub/missing.py"}], cwd=self.dir)
        self.assertTrue(alive_out[0]["alive"])
        self.assertFalse(dead_out[0]["alive"])

    def test_relative_and_absolute_equivalent_collapse_when_cwd_given(self):
        """With cwd anchoring, a relative path and its absolute equivalent now
        genuinely resolve to the same normalized filesystem path and collapse into
        one row -- see the corrected annotate_liveness docstring."""
        out = annotate_liveness([
            {"path": os.path.join(self.dir, "alive.py"), "ops": 1, "created": True},
            {"path": "alive.py", "ops": 1, "created": False},
        ], cwd=self.dir)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ops"], 2)
        self.assertTrue(out[0]["alive"])


class TestRegistrySeamDoesNotTouchCounts(unittest.TestCase):
    """THE regression this revision exists to fix: registry.parse_any() must NOT
    recompute counts.created/counts.edited off liveness, and must NOT drop entries
    from `files`. A session that created-then-deleted a file must keep reporting the
    true created count and keep showing that file in the Files panel."""

    def setUp(self):
        import aitracker.config as config
        from aitracker import registry
        from aitracker.providers import claude as C
        self.config = config
        self.registry = registry
        self._snap = config.PROJECTS
        config.PROJECTS = tempfile.mkdtemp()
        self.proj_dir = os.path.join(config.PROJECTS, "proj")
        os.makedirs(self.proj_dir)
        self._C = C
        C._META_CACHE.clear()

    def tearDown(self):
        self.config.PROJECTS = self._snap
        self._C._META_CACHE.clear()

    def _write_session(self, sid, created_paths, still_alive_paths):
        """A synthetic Claude transcript that Writes N files, only some of which
        remain on disk by the time parse_any() runs -- the "created 10, cleaned up 6"
        shape from the bug report."""
        import json
        rows = [{"type": "user", "cwd": "/tmp/proj", "message": {"role": "user", "content": "go"}}]
        content = []
        for i, p in enumerate(created_paths):
            content.append({"type": "tool_use", "id": "w%d" % i, "name": "Write",
                             "input": {"file_path": p, "content": "x\n"}})
        rows.append({"type": "assistant", "timestamp": "2026-06-22T10:00:00Z",
                     "message": {"content": content}})
        with open(os.path.join(self.proj_dir, sid + ".jsonl"), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        for p in still_alive_paths:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write("x\n")

    def test_counts_created_survives_dead_files(self):
        workdir = tempfile.mkdtemp()
        created = [os.path.join(workdir, "f%d.py" % i) for i in range(10)]
        kept_alive = created[:4]   # 6 of the 10 are "cleaned up" -- never written for real
        self._write_session("csess", created, kept_alive)
        self._C._META_CACHE.clear()

        d = self.registry.parse_any("csess")
        self.assertEqual(d["counts"]["created"], 10,
                          "counts.created must reflect the TRUE history, not just what's still on disk")
        self.assertEqual(len(d["files"]), 10, "dead files must NOT be dropped from `files`")
        alive_flags = sorted(f["alive"] for f in d["files"])
        self.assertEqual(alive_flags, [False] * 6 + [True] * 4)
        shutil.rmtree(workdir, ignore_errors=True)


class TestMalformedFilePathDoesNotBreakTheRoute(unittest.TestCase):
    """Defect 1, proven end-to-end: a malformed model-authored `file_path` (Claude
    stores `inp.get("file_path")` behind only a truthiness guard -- providers/
    claude.py) must not 500 the real /api/session route. Also exercises Defect 2's
    cwd-anchoring through the full registry.parse_any() seam, not just the unit
    function."""

    def setUp(self):
        import aitracker.config as config
        from aitracker import registry, server as _server
        from aitracker.providers import claude as C
        self.config = config
        self.registry = registry
        self._C = C
        self._snap = config.PROJECTS
        config.PROJECTS = tempfile.mkdtemp()
        self.proj_dir = os.path.join(config.PROJECTS, "proj")
        os.makedirs(self.proj_dir)
        self.workdir = tempfile.mkdtemp()
        self._C._META_CACHE.clear()
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.config.PROJECTS = self._snap
        self._C._META_CACHE.clear()
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def _write_session(self, sid, cwd, tool_inputs):
        rows = [{"type": "user", "cwd": cwd, "message": {"role": "user", "content": "go"}}]
        content = [
            {"type": "tool_use", "id": "w%d" % i, "name": "Write", "input": inp}
            for i, inp in enumerate(tool_inputs)
        ]
        rows.append({"type": "assistant", "timestamp": "2026-06-22T10:00:00Z",
                     "message": {"content": content}})
        with open(os.path.join(self.proj_dir, sid + ".jsonl"), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def test_non_string_file_path_does_not_500_the_session_route(self):
        # `input` is model-authored JSON, so `file_path` can be a list/dict. Two
        # separate crashes came out of that: AttributeError ('list' has no
        # 'startswith') in annotate_liveness, and -- once that was guarded --
        # TypeError ("cannot use 'list' as a dict key") in the provider itself,
        # which keys `files`/`reads` BY the path. Both surfaced as a 500 here.
        # Contract: drop the malformed entry at ingestion (the trust boundary).
        # A non-string path names no file, so keeping it would only push
        # "[object Object]" into the Files and Links panels downstream.
        self._write_session("badpath", self.workdir, [
            {"file_path": ["not", "a", "string"], "content": "x\n"},
        ])
        status, body = self._get("/api/session?id=badpath")
        self.assertEqual(status, 200, body)
        d = json.loads(body)
        self.assertEqual(d["files"], [])

    def test_non_string_file_path_does_not_break_unit_function_either(self):
        self._write_session("badpath2", self.workdir, [
            {"file_path": {"weird": "shape"}, "content": "x\n"},
        ])
        d = self.registry.parse_any("badpath2")
        self.assertEqual(d["files"], [])

    def test_a_good_path_still_survives_alongside_a_malformed_one(self):
        """Dropping the malformed entry must not drop the session's real files too."""
        real = os.path.join(self.workdir, "real_one.py")
        with open(real, "w") as fh:
            fh.write("y = 2\n")
        self._write_session("badpath3", self.workdir, [
            {"file_path": {"weird": "shape"}, "content": "x\n"},
            {"file_path": real, "content": "y = 2\n"},
        ])
        d = self.registry.parse_any("badpath3")
        self.assertEqual([f["path"] for f in d["files"]], [real])
        self.assertTrue(d["files"][0]["alive"])

    def test_relative_file_path_anchored_to_session_cwd_through_the_full_seam(self):
        """A relative file_path (no cwd anchoring at write time in providers/claude.py)
        must be judged against the SESSION's cwd (carried on meta.cwd), not the
        server process's -- proven through registry.parse_any(), the real seam."""
        os.makedirs(os.path.join(self.workdir, "sub"))
        with open(os.path.join(self.workdir, "sub", "real.py"), "w") as fh:
            fh.write("z = 1\n")
        self._write_session("relsess", self.workdir, [
            {"file_path": "sub/real.py", "content": "z = 1\n"},
            {"file_path": "sub/ghost.py", "content": "z = 2\n"},
        ])
        d = self.registry.parse_any("relsess")
        by_path = {f["path"]: f for f in d["files"]}
        self.assertTrue(by_path["sub/real.py"]["alive"])
        self.assertFalse(by_path["sub/ghost.py"]["alive"])


# --------------------------------------------------------------------------------
# JS: ext_cr_detail.js's deriveLinks() must skip alive=False `files` entries.
# --------------------------------------------------------------------------------

def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
    if not matches:
        raise AssertionError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


# Minimal browser environment for bundle execution -- same stub idiom as
# tests/test_cr_logic.py / tests/test_cr_rail_toggle.py (never a hand-retyped
# paraphrase of deriveLinks() itself: this runs the REAL exported function, reached
# via window.CR.detail._internal.deriveLinks, exactly as the app ships it).
_JS_PREAMBLE = r"""
globalThis.window = globalThis;

function makeEl() {
  var self = {
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {}, setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, append() {}, remove() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; }, querySelectorAll: () => [self],
    closest: function() { return self; }, firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", hidden: false, focus() {}, click() {}
  };
  return self;
}
var stubEl = makeEl();
window.document = {
  createElement: () => makeEl(), createTextNode: () => makeEl(),
  getElementById: () => stubEl, querySelector: () => stubEl, querySelectorAll: () => [stubEl],
  addEventListener() {}, dispatchEvent() {},
  documentElement: stubEl, body: stubEl, head: stubEl, readyState: "complete"
};
const _localStorage = {};
window.localStorage = {
  getItem: (k) => (k in _localStorage) ? _localStorage[k] : null,
  setItem: (k, v) => { _localStorage[k] = v; },
  removeItem: (k) => { delete _localStorage[k]; }
};
window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
window.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve(""), headers: { get: () => null } });
window.setInterval = () => 0; window.setTimeout = () => 0; window.clearInterval = () => {}; window.clearTimeout = () => {};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: () => Promise.resolve() } };
window.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts && opts.detail; } };
window.Event = window.CustomEvent;
window.requestAnimationFrame = () => 0;
window.getComputedStyle = () => ({ getPropertyValue: () => "" });
window.getSelection = () => ({ toString: () => "" });
window.addEventListener = () => {}; window.removeEventListener = () => {}; window.dispatchEvent = () => {};
process.on("unhandledRejection", () => {});

try {
"""

_JS_MID = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""

_JS_TAIL = r"""
var session = {
  files: [
    { path: "/tmp/alive.py", created: true, alive: true, last: "2026-01-02T00:00:00.000Z" },
    { path: "/tmp/dead.py", created: true, alive: false, last: "2026-01-02T00:00:00.000Z" },
    { path: "/tmp/legacy-no-flag.py", created: true, last: "2026-01-02T00:00:00.000Z" }
  ],
  prs: [], narrative: [], requests: [], commands: []
};
var links = window.CR.detail._internal.deriveLinks(session);
var urls = links.generated.map(function (e) { return e.url; });
console.log("===LINKS_JSON_START===" + JSON.stringify(urls));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestDeriveLinksSkipsDeadEntries(unittest.TestCase):

    def test_dead_file_entries_are_not_in_the_links_panel(self):
        bundle = _extract_script_content(_read_page())
        js = "\n".join([_JS_PREAMBLE, bundle, _JS_MID, _JS_TAIL])
        returncode, stdout, stderr = _run_node(js)
        self.assertEqual(returncode, 0, stderr)
        marker = "===LINKS_JSON_START==="
        idx = stdout.find(marker)
        self.assertGreaterEqual(idx, 0, stdout)
        import json
        urls = json.loads(stdout[idx + len(marker):].strip())
        self.assertIn("/tmp/alive.py", urls)
        self.assertNotIn("/tmp/dead.py", urls, "deriveLinks must skip alive:false files entries")
        self.assertIn("/tmp/legacy-no-flag.py", urls,
                      "an entry with no `alive` key (older/synthetic data) must default to shown")


if __name__ == "__main__":
    unittest.main()
