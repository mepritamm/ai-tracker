#!/usr/bin/env python3
"""make check/test -> run every tests/test_*.py module as its own subprocess, in parallel.

Replaces a single `python3 -m unittest discover -s tests -t .` process (which runs ~2700 tests
serially) with one subprocess per test MODULE, fanned out over a small thread pool -- the pool
only waits on subprocess I/O, so plain threads (not multiprocessing) are enough here even though
each unittest run itself is CPU-bound; the parallelism is across processes, not within one.

JOBS (env var, default 4) bounds concurrency. Deliberately conservative, NOT os.cpu_count(): the
full gate has previously been OOM-killed running too much of this suite at once (see project
memory "full-gate-oom-killed") -- 4 leaves headroom on an 8-core machine instead of racing every
core's worth of interpreters + their imports at once.

Stdlib only (concurrent.futures, subprocess, glob) -- no new dependency, same as every other
script here. Not itself covered by tests/ (same exemption as scripts/bundle.py: this is tooling,
not app logic) -- verified by hand instead: see the task notes for the before/after-breakage run.

One deliberate wrinkle: `python -m unittest discover` builds ONE suite out of every TestCase in
every module, so a helper module that defines no TestCase of its own but is imported for its
logic by another module (tests/test_selfcheck.py's `_run()`, called from tests/test_tracker.py's
own test_selfcheck_passes -- "make check"'s actual "selfcheck ok" signal comes from THAT module,
not from running test_selfcheck.py by itself) still gets exercised under discover. Running each
module as its OWN subprocess loses that: `python -m unittest tests.test_selfcheck` alone finds
zero tests and modern unittest (3.12+) treats "no tests collected" as its own error (exit 5,
"NO TESTS RAN") -- not a real failure, just this splitting strategy's own blind spot for a
module that is intentionally test-free on its own. _is_benign_empty_module below recognizes
exactly that shape and does not fail the gate over it.
"""
import concurrent.futures
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = int(os.environ.get("JOBS", "4"))


def _discover_modules():
    paths = sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py")))
    return ["tests." + os.path.splitext(os.path.basename(p))[0] for p in paths]


def _run_module(module):
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", module],
        cwd=ROOT, capture_output=True, text=True,
    )
    return module, proc.returncode, proc.stdout, proc.stderr


# The ONE module known to define no TestCase of its own by design -- see this file's own module
# docstring. Deliberately a short, explicit allow-list, not inferred from the exit-code shape
# alone: without naming it, ANY module that happens to collect zero tests (e.g. a test method
# accidentally renamed without its `test_` prefix) would also exit 5 with "NO TESTS RAN" and get
# silently waved through as "benign" instead of failing the gate like it should.
BENIGN_EMPTY_MODULES = {"tests.test_selfcheck"}


def _is_benign_empty_module(module, code, combined):
    """True only for a module that is BOTH named in BENIGN_EMPTY_MODULES AND shows the exact
    "collected nothing, nothing else went wrong" shape (its logic is exercised via import from
    another module's TestCase, under the real `discover` run). Any other module hitting this
    exit-code shape is a real "no tests collected" problem and must still fail the gate -- a real
    import error (a traceback, a different exit code) fails it too, regardless of the name."""
    return (
        module in BENIGN_EMPTY_MODULES
        and code == 5
        and "NO TESTS RAN" in combined
        and "Traceback" not in combined
    )


def main():
    modules = _discover_modules()
    failures = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=JOBS) as pool:
        for module, code, out, err in pool.map(_run_module, modules):
            combined = (out or "") + (err or "")
            if code != 0 and _is_benign_empty_module(module, code, combined):
                print("--- %s: no tests of its own (exercised via another module's import) ---" % module)
            elif code != 0:
                failures.append(module)
                print("--- FAIL: %s ---" % module)
                print(combined)
            elif combined.strip():
                # Preserve stdout a passing module prints directly -- e.g. tests/test_tracker.py's
                # test_selfcheck_passes calls tests/test_selfcheck.py's _run(), whose own
                # "selfcheck ok" print is `make check`'s existing gate signal and must still reach
                # the terminal, not just this script's own belt-and-suspenders line at the end.
                print(combined, end="" if combined.endswith("\n") else "\n")

    if failures:
        print("FAILED (%d/%d modules): %s" % (len(failures), len(modules), ", ".join(failures)))
        sys.exit(1)

    print("selfcheck ok")
    sys.exit(0)


if __name__ == "__main__":
    main()
