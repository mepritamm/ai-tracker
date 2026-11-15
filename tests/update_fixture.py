"""Fixture for the in-app Update tests: a temp bare `remote.git` holding a STUB `aitracker/` package,
a `checkout` clone (what the "running dashboard" is), and a `second` clone that pushes new commits.
config._HERE / CONFIG_FILE / PENDING_LOCK are patched to temp; nothing outside one mkdtemp is touched.
Never fetches, execs or restarts anything real. Import `make_update_fixture(testcase)`."""
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
        self.git(self.root, "init", "--bare", "-b", "main", self.remote)
        self.git(self.root, "clone", "-q", self.remote, self.second)
        for rel, text in STUB.items():
            self.write(self.second, rel, text)
        self.git(self.second, "add", "-A")
        self.git(self.second, "commit", "-q", "-m", "stub package")
        self.git(self.second, "push", "-q", "-u", "origin", "main")
        self.git(self.root, "clone", "-q", self.remote, self.repo)
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
