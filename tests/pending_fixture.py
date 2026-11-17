"""Shared fixture for the pending-work tests: a temp bare `remote.git` + `repo` (all git state lives in
one mkdtemp), config paths patched to temp, aging via os.utime. Never touches real repos, ~/.claude
or the real gh. Import `make_fixture(testcase)`; skip the module with `@requires_git`."""
import atexit
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from aitracker import config

requires_git = unittest.skipUnless(shutil.which("git"), "git not installed")
_ID = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
_CFG = ("PENDING_FILE", "PENDING_LOG", "PENDING_LOCK", "JOBS_DIR", "SCRATCH_ROOT", "LIVE_SESSIONS_DIR",
        "PROJECTS", "CONFIG_FILE", "TITLES_FILE")


_TEMPLATE = []          # [root]: a bare remote.git + repo with one pushed commit, built once per process


def _template(fx):
    """Build the base remote+repo once and reuse it by copying (git init/commit/push cost ~8 subprocesses a test).
    Only the origin URL inside the copy has to be repointed."""
    if not _TEMPLATE:
        root = os.path.realpath(tempfile.mkdtemp(prefix="pending-tpl-"))
        atexit.register(shutil.rmtree, root, True)
        fx.git(root, "init", "--bare", "-b", "main", os.path.join(root, "remote.git"))
        fx.git(root, "init", "-b", "main", os.path.join(root, "repo"))
        fx.commit(os.path.join(root, "repo"), "a.txt", "one")
        fx.git(os.path.join(root, "repo"), "remote", "add", "origin", os.path.join(root, "remote.git"))
        fx.git(os.path.join(root, "repo"), "push", "-u", "origin", "main")
        _TEMPLATE.append(root)
    return _TEMPLATE[0]


class Fx:
    def __init__(self, tc):
        self.tc = tc
        # a commit hook runs the suite with GIT_DIR / GIT_INDEX_FILE set: scrub them so the temp repos are isolated
        env = mock.patch.dict(os.environ)
        env.start()
        tc.addCleanup(env.stop)
        for k in [k for k in os.environ if k.startswith("GIT_")]:
            del os.environ[k]
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="pending-fx-"))
        tc.addCleanup(shutil.rmtree, self.root, True)
        j = lambda *p: os.path.join(self.root, *p)
        self.remote, self.repo = j("remote.git"), j("repo")
        self.paths = {"PENDING_FILE": j("pending.json"), "PENDING_LOG": j("pending.log"),
                      "PENDING_LOCK": j("pending.lock"), "JOBS_DIR": j("jobs"), "SCRATCH_ROOT": j("scratch"),
                      "LIVE_SESSIONS_DIR": j("sessions"), "PROJECTS": j("projects"), "CONFIG_FILE": j("config.json"),
                      "TITLES_FILE": j("titles.json")}
        for k in ("JOBS_DIR", "SCRATCH_ROOT", "LIVE_SESSIONS_DIR", "PROJECTS"):
            os.makedirs(self.paths[k])
        for k, v in self.paths.items():
            p = mock.patch.object(config, k, v)
            p.start()
            tc.addCleanup(p.stop)
        # the registry would read the REAL ~/.claude: replace it
        from aitracker import pending
        self.cwds = set()
        p = mock.patch.object(pending, "all_cwds", lambda: set(self.cwds))
        p.start()
        tc.addCleanup(p.stop)
        self.other = []
        p = mock.patch.object(pending, "other_sessions", lambda: list(self.other))
        p.start()
        tc.addCleanup(p.stop)
        tpl = _template(self)
        shutil.copytree(os.path.join(tpl, "remote.git"), self.remote, symlinks=True)
        shutil.copytree(os.path.join(tpl, "repo"), self.repo, symlinks=True)
        self.git(self.repo, "remote", "set-url", "origin", self.remote)
        p = mock.patch.object(pending, "_nice", lambda: [])      # one fewer exec per git call; test_pending_nice covers _nice
        p.start()
        tc.addCleanup(p.stop)
        self.cwds.add(self.repo)
        self.fake_gh({})        # never the real gh: default fake answers "no merged PR"

    def git(self, cwd, *args, check=True):
        p = subprocess.run(["git", *_ID, "-C", cwd, *args], capture_output=True, text=True)
        if check and p.returncode:
            raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
        return p.stdout.strip()

    def commit(self, cwd, name, text, msg=None):
        with open(os.path.join(cwd, name), "w") as fh:
            fh.write(text)
        self.git(cwd, "add", name)
        self.git(cwd, "commit", "-m", msg or "c " + name)
        return self.git(cwd, "rev-parse", "HEAD")

    def worktree(self, branch, base="origin/main", name=None, detach=False):
        path = os.path.join(self.root, name or branch)
        if detach:
            self.git(self.repo, "worktree", "add", "--detach", path, base)
        else:
            self.git(self.repo, "worktree", "add", "-b", branch, path, base)
        return path

    def age(self, path, days):
        """Back-date a worktree: its dir and its admin files (what last_activity reads)."""
        t = os.stat(path).st_mtime - days * 86400 - 60
        targets = [path]
        try:
            with open(os.path.join(path, ".git")) as fh:
                adm = fh.read().split(":", 1)[1].strip()
        except (OSError, IndexError):
            adm = os.path.join(path, ".git") if os.path.isdir(os.path.join(path, ".git")) else None
        if adm:
            targets += [os.path.join(adm, f) for f in ("HEAD", "index", os.path.join("logs", "HEAD"))]
        for tgt in targets:
            if os.path.exists(tgt):
                os.utime(tgt, (t, t))

    def age_tree(self, path, days):
        t = os.stat(path).st_mtime - days * 86400 - 60
        for dp, dns, fns in os.walk(path, topdown=False):
            for n in dns + fns:
                os.utime(os.path.join(dp, n), (t, t), follow_symlinks=False)
            os.utime(dp, (t, t))

    def job(self, jid, state, cwd=None, **kw):
        d = os.path.join(self.paths["JOBS_DIR"], jid)
        os.makedirs(os.path.join(d, "tmp"), exist_ok=True)
        with open(os.path.join(d, "state.json"), "w") as fh:
            json.dump(dict({"state": state, "cwd": cwd or self.repo}, **kw), fh)
        return d

    def live(self, pid, cwd):
        with open(os.path.join(self.paths["LIVE_SESSIONS_DIR"], "%d.json" % pid), "w") as fh:
            json.dump({"pid": pid, "cwd": cwd}, fh)

    def fake_gh(self, table, log=None):
        """Install an executable fake `gh` in a temp bin dir on PATH. `table`: {branch: [pr dicts]}
        returned for `pr list --head <branch>`; "__exit__": N makes it fail; "__sleep__": s makes it
        sleep. Every call appends one JSON line {argv, env_keys} to `log`."""
        bin_dir = os.path.join(self.root, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        self.gh_log = log or os.path.join(self.root, "gh.log")
        self.gh_table = os.path.join(self.root, "gh-table.json")
        with open(self.gh_table, "w") as fh:
            json.dump(table, fh)
        script = os.path.join(bin_dir, "gh")
        with open(script, "w") as fh:
            fh.write("#!%s\nimport json,os,sys,time\n"
                     "t=json.load(open(%r))\n"
                     "open(%r,'a').write(json.dumps({'argv':sys.argv[1:],'env':sorted(os.environ)})+'\\n')\n"
                     "if t.get('__sleep__'): time.sleep(t['__sleep__'])\n"
                     "if t.get('__exit__'): sys.exit(t['__exit__'])\n"
                     "a=sys.argv[1:]\n"
                     "b=a[a.index('--head')+1] if '--head' in a else ''\n"
                     "print(json.dumps(t.get(b, [])))\n" % (sys.executable, self.gh_table, self.gh_log))
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        p = mock.patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ.get("PATH", "")})
        p.start()
        self.tc.addCleanup(p.stop)
        return script

    def gh_calls(self):
        try:
            with open(self.gh_log) as fh:
                return [json.loads(x) for x in fh if x.strip()]
        except OSError:
            return []


def make_fixture(tc):
    return Fx(tc)
