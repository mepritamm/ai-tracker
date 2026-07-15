"""ai-tracker CLI: serve the dashboard, or run the self-check."""
import os
import sys

from . import __version__
from .server import run

HELP = """ai-tracker — live dashboard for AI coding sessions (Claude Code, Auggie, …).

Usage: ai-tracker [--serve | --selfcheck | --version | --help]
Env:   PORT   (default 8787)
"""


def _selfcheck():
    import unittest
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    suite = unittest.TestLoader().discover(os.path.join(here, "tests"), top_level_dir=here)
    ok = unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()
    if ok:
        print("selfcheck ok")
    sys.exit(0 if ok else 1)


def main():
    if "--version" in sys.argv or "-v" in sys.argv:
        print("ai-tracker", __version__)
        return
    if "--help" in sys.argv or "-h" in sys.argv:
        print(HELP.strip())
        return
    if "--selfcheck" in sys.argv:
        _selfcheck()
        return
    port = int(os.environ.get("PORT", 8787))
    run(port=port)   # run() picks the next free port if this one is busy, and opens the browser
