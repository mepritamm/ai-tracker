"""Shared test setup: no test reads the REAL Claude-daemon roster through open_pty.

`term_vt._background_target` asks the provider whether a live daemon REPL hosts a session -- a read
of ~/.claude/daemon/roster.json. Every existing open_pty test uses made-up ids, so the answer is
always "not a background session"; stub it that way once, here. Tests of the feature itself patch
it back per test (`mock.patch.object(term_vt, "_background_target", ...)`), and the roster-reading
original stays reachable as `term_vt._real_background_target`.
"""
from aitracker import term_vt as _term_vt

from aitracker import term_launch as _term_launch

_term_vt._real_background_target = _term_vt._background_target
_term_vt._background_target = lambda sid: ""
_term_launch._real_background_target = _term_launch._background_target
_term_launch._background_target = lambda sid: ""

# Hermetic login shells. Many tests spawn the real `$SHELL -l`; with the user's own dotfiles every
# `make check` ran their ~/.zshrc -- `pyenv rehash` writing into ~/.pyenv -- and a test-teardown kill
# mid-rehash once leaked pyenv's lock, making every terminal on the machine wait 2 minutes. An empty
# ZDOTDIR gives zsh (the macOS default) no user rc files; the system ones still run.
# ponytail: zsh only -- a bash login shell reads ~/.bash_profile via HOME, which tests can't swap
# globally (config paths derive from it). Add a temp HOME for spawned shells if bash users appear.
import atexit as _atexit
import os as _os
import shutil as _shutil
import tempfile as _tempfile

_ZDOTDIR = _tempfile.mkdtemp(prefix="aitracker-test-zdotdir-")
_os.environ["ZDOTDIR"] = _ZDOTDIR
_atexit.register(_shutil.rmtree, _ZDOTDIR, True)
