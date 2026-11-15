"""Fixture for the in-app Update tests: a temp bare `remote.git` holding a STUB `aitracker/` package,
a `checkout` clone (what the "running dashboard" is), and a `second` clone that pushes new commits.
config._HERE / CONFIG_FILE / PENDING_LOCK are patched to temp; nothing outside one mkdtemp is touched.
Never fetches, execs or restarts anything real. Import `make_update_fixture(testcase)`."""
import atexit
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from aitracker import config

requires_git = unittest.skipUnless(shutil.which("git"), "git not installed")
_ID = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]

STUB = {
    "aitracker/__init__.py": '__version__ = "9.0.0"\n',
    "aitracker/server.py": "VALUE = 1\n",
    "aitracker/cli.py": "VALUE = 1\n",
    "aitracker/config.py": (
        "def apply_overrides(o):\n"
        "    return None\n"),
    "aitracker/page.py": (
        "import os\n"
        "_HERE = os.path.dirname(os.path.abspath(__file__))\n"
        "def build_page():\n"
        "    return open(os.path.join(_HERE, 'web', 'app.css')).read()\n"),
    "aitracker/web/app.css": "body{}\n",
}


_TEMPLATE = []          # [root]: remote.git + checkout + second with the stub package pushed; built once, copied per test


def _template(fx):
    if not _TEMPLATE:
        root = os.path.realpath(tempfile.mkdtemp(prefix="update-tpl-"))
        atexit.register(shutil.rmtree, root, True)
        remote, second, repo = (os.path.join(root, n) for n in ("remote.git", "second", "checkout"))
        fx.git(root, "init", "--bare", "-b", "main", remote)
        fx.git(root, "clone", "-q", remote, second)
        for rel, text in STUB.items():
            fx.write(second, rel, text)
        fx.git(second, "add", "-A")
        fx.git(second, "commit", "-q", "-m", "stub package")
        fx.git(second, "push", "-q", "-u", "origin", "main")
        fx.git(root, "clone", "-q", remote, repo)
        _TEMPLATE.append(root)
    return _TEMPLATE[0]


class UFx:
    def __init__(self, tc):
        self.tc = tc
        env = mock.patch.dict(os.environ)
        env.start()
        tc.addCleanup(env.stop)
        for k in [k for k in os.environ if k.startswith("GIT_")]:
            del os.environ[k]
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="update-fx-"))
        tc.addCleanup(shutil.rmtree, self.root, True)
        j = lambda *p: os.path.join(self.root, *p)
        self.remote, self.repo, self.second = j("remote.git"), j("checkout"), j("second")
        self.cfg = j("config.json")
        self.lock = j("pending.lock")
        tpl = _template(self)
        for n, dst in (("remote.git", self.remote), ("second", self.second), ("checkout", self.repo)):
            shutil.copytree(os.path.join(tpl, n), dst, symlinks=True)
        for clone in (self.second, self.repo):
            self.git(clone, "remote", "set-url", "origin", self.remote)
        for k, v in (("_HERE", os.path.join(self.repo, "aitracker")), ("CONFIG_FILE", self.cfg),
                     ("PENDING_LOCK", self.lock)):
            p = mock.patch.object(config, k, v)
            p.start()
            tc.addCleanup(p.stop)

    def git(self, cwd, *args, check=True):
        p = subprocess.run(["git", *_ID, "-C", cwd, *args], capture_output=True, text=True)
        if check and p.returncode:
            raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
        return p.stdout.strip()

    def write(self, base, rel, text):
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def push_change(self, rel="aitracker/server.py", text="VALUE = 2\n", msg="upstream change", delete=False):
        """Commit one change in `second` and push it. Returns the new sha. The checkout does NOT see it until fetched."""
        if delete:
            self.git(self.second, "rm", "-q", rel)
        else:
            self.write(self.second, rel, text)
            self.git(self.second, "add", rel)
        self.git(self.second, "commit", "-q", "-m", msg)
        self.git(self.second, "push", "-q", "origin", "main")
        return self.git(self.second, "rev-parse", "HEAD")

    def head(self):
        return self.git(self.repo, "rev-parse", "HEAD")


def make_update_fixture(tc):
    return UFx(tc)
