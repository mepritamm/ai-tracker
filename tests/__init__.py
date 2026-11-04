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
