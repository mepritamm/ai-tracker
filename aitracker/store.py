import fcntl, glob, json, os, time, uuid
from . import config


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save_json(path, obj):
    """Atomic write via a per-call UNIQUE temp name in the same directory. A
    fixed `path + ".tmp"` let concurrent writers step on each other's temp
    file -- of 10 threads calling this concurrently on the same path, 9 raised
    FileNotFoundError out of os.replace (the other 9's tmp file had already
    been renamed away by whichever writer got there first) and only 1 write
    survived. A unique name per call removes that race entirely; os.replace
    keeps the atomic swap-in property. This fixes every caller (flags/titles/
    pins/notes/forks), not just forks -- the weakness was in the shared helper."""
    d = os.path.dirname(path) or "."
    tmp = os.path.join(d, ".%s.%s.tmp" % (os.path.basename(path), uuid.uuid4().hex))
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
    os.replace(tmp, path)


def load_titles():
    return _load_json(config.TITLES_FILE, {})


def load_pins():
    """Session ids the user pinned to the top of the list — read live, like titles."""
    p = _load_json(config.PINS_FILE, [])
    return p if isinstance(p, list) else []


_TSTATUS = {"completed": "completed", "complete": "completed", "done": "completed",
            "in_progress": "in_progress", "started": "in_progress", "pending": "pending"}


def load_tasks(sid):
    """Current tasks for a session from ~/.claude/tasks/<sid>/<n>.json — the
    TaskCreate/TaskUpdate store that replaced in-transcript TodoWrite. Files are
    updated in place, so this reflects live status. Sorted by numeric id."""
    d = os.path.join(config.TASKS_DIR, sid)
    try:
        files = [f for f in os.listdir(d) if f.endswith(".json")]
    except OSError:
        return []

    def key(f):
        try:
            return int(f[:-5])
        except ValueError:
            return 1 << 30
    out = []
    for f in sorted(files, key=key):
        try:
            t = json.load(open(os.path.join(d, f), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        subj = isinstance(t, dict) and (t.get("subject") or t.get("content"))
        if not subj:
            continue
        out.append({"content": subj,
                    "status": _TSTATUS.get((t.get("status") or "").lower(), "pending"),
                    "activeForm": t.get("activeForm") or subj,
                    "desc": t.get("description") or ""})
    return out


def load_flags():
    try:
        with open(config.FLAGS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def save_flags(flags):
    # ponytail: full rewrite, no locking — fine for a single-user local tool.
    _save_json(config.FLAGS_FILE, flags)


def load_notes():
    """Per-session note stacks: {session_id: [{"text": …, "pushed": bool}, …]} — read live.
    `pushed` means "queued for delivery into the live session"; the drain (/api/notes/next)
    pops the oldest pushed note. Bare strings (the pre-push format) upgrade on read."""
    d = _load_json(config.NOTES_FILE, {})
    if not isinstance(d, dict):
        return {}
    return {sid: [n if isinstance(n, dict) else {"text": n, "pushed": False}
                  for n in stack]
            for sid, stack in d.items() if isinstance(stack, list)}


def save_notes(notes):
    _save_json(config.NOTES_FILE, notes)


# --- fork lineage -----------------------------------------------------------
#
# When a `claude --resume <sid>` is refused (the CLI considers that session a
# background agent) and gets retried with `--fork-session`, the retry re-execs
# with the SAME sid and Claude Code never reports the new one — a fork is a full
# copy under a brand-new session id, and nothing on disk names the parent from
# the child's side: `parentUuid` is an intra-session message-chain pointer (each
# line's parentUuid == the previous line's uuid, same sessionId), not a fork
# pointer, and `parentSessionId`/`forkedFrom`/`originalSessionId` do not exist
# anywhere in the transcript format (verified against real transcripts).
#
# What DOES link them: a forked session is a logical copy of the parent's
# message chain, so parent and child share the SAME `uuid` values on their
# early messages (an empirical scan of 1686 real transcripts across 3 repos
# found 8 genuine fork pairs, sharing 14-508 early uuids each, zero false
# positives at a >=3-shared-uuid threshold). `uuid` is a random UUID4 per
# message, so an unrelated session cannot reproduce them by chance. This is
# NOT established: whether `--continue` or compaction can also duplicate
# uuids -- if that turns out to happen, the threshold may need revisiting.
# uuid-overlap is therefore the EXACT gate: a candidate that fails it is never
# eligible, no matter anything else about it.
#
# THREE ROUNDS of this resolver picked the child from among multiple
# uuid-passing candidates by ordering them on a timestamp (oldest mtime, then
# creation time with an "at - 5s" tolerance floor) and taking the first. All
# three were wrong, because a timestamp is a GUESS about which candidate is
# the child, never a fact:
#   - Round 1 (oldest mtime): an unrelated session in the same cwd, merely
#     touched again after the fork, outranked the real child and got
#     memoized as the wrong answer permanently.
#   - Round 2 (mtime among threshold-passers): a fork-of-a-fork (A forks to
#     B, B forks to C) transitively shares enough of A's early uuids for C to
#     also clear A's own gate, so resolving A's child has two candidates, B
#     and C -- and B staying active (appended to) after C is created gives B
#     a LATER mtime than C, so mtime picked the grandchild.
#   - Round 3 (creation-time ordering + an "at - 5s" floor): same
#     fork-of-a-fork shape, but resolving B's OWN child. A's early uuids are
#     a strict subset of B's (B is a copy of A's chain), so A clears B's
#     uuid gate too; the "at - 5s" floor was keyed to B's own fork-into-C
#     instant, so whenever B forked again within ~5s of B's own creation, A
#     also cleared the floor; A was created before C, so earliest-created
#     handed back A -- B's own GRANDPARENT, structurally impossible (A
#     predates B) yet returned. Reproduced on real files at gap=0.00s.
#
# THE FIX: replace the guess with an exact fact. At the moment a parent
# forks, `record_fork` snapshots the set of session ids that ALREADY EXIST in
# the parent's project directory (`pre_existing`, captured at the same
# instant as the uuid fingerprint, the one moment the parent's own transcript
# is guaranteed readable). A file present in that snapshot cannot be the
# child, full stop -- this is set MEMBERSHIP, not order, so it structurally
# excludes every failure above: ancestors, unrelated older sessions,
# touched-mtime files, and pre-fork siblings were all already present at
# snapshot time, whatever their timestamps say later. Eligibility is now:
# NOT in `pre_existing`, AND uuid-overlap >= UUID_MATCH_THRESHOLD -- both
# exact. A belt-and-braces creation-time floor (candidate ct >= the parent
# TRANSCRIPT's own ct, captured in the same snapshot) additionally rejects
# anything that would predate its own parent. Creation time now plays only
# ONE remaining role, and it is a stated POLICY choice, not a correctness
# claim: breaking a tie among multiple genuinely-new, uuid-passing candidates
# (e.g. the user forks the same parent twice in one window) -- earliest
# created wins, ties broken explicitly by session id. See _creation_time()
# and its use at the bottom of resolve_fork_child().
#
# TWO FOLLOW-ON HARDENINGS to that same snapshot:
#
# 1. "empty" vs "failed" must never collapse to the same value. A directory
#    listing can come back empty two ways -- genuinely empty (a legitimate,
#    USABLE snapshot: the fix above is still fully load-bearing), or the
#    `os.listdir()` call itself failing (EMFILE, an NFS hiccup, ...). The
#    latter is UNUSABLE: silently treating it as `[]` turns gate 1 into a
#    no-op and resolution falls straight back to the ordering heuristic that
#    broke rounds 1-3. `_list_jsonl_ids()` returns `None` -- never `[]` -- on
#    a failure (after a couple of cheap retries, since the failure this
#    guards against is transient), and `resolve_fork_child` refuses to
#    resolve at all when it sees that sentinel, staying unresolved and
#    retrying on the next poll rather than guessing. The failure is logged,
#    not swallowed, matching this codebase's `"[ai-tracker] <component>: ..."`
#    print style (term_vt.py uses it throughout).
#
# 2. The snapshot's WHOLE POINT is "what existed before the fork could
#    possibly have written its own transcript" -- so it must be captured
#    BEFORE that fork's `execvp`, not after. `capture_fork_snapshot()` is
#    the piece callers use to do that: term_vt._retry_with_fork calls it
#    immediately before `_fork_child()`, then hands the result to
#    `record_fork()` (see both functions' docstrings). Captured any later,
#    a fast-writing child could land IN its own snapshot and be permanently
#    excluded as "pre-existing" -- the snapshot would be exact but for the
#    wrong instant.
#
# Once a fork resolves (or is abandoned), `pre_existing` is dead weight --
# up to ~20KB per record for a directory with hundreds of sessions, kept
# forever for no reason once it has done its one job. Both `resolve_fork_
# child`'s memoizing branch and its give-up branch drop it from the record
# at that point.
#
# The search is intentionally NARROW: only the parent's own project
# directory (a fork keeps the terminal's cwd, so that's where the child is
# expected). There is no widen-to-every-project-dir fallback -- the snapshot
# is only meaningful for the one directory it was taken in, and a
# snapshot-less wide scan would just be the same guesswork that kept
# failing, at the cost of hundreds of extra glob() calls over a session. If
# the child never appears in the parent's own directory, resolution stays
# empty and the give-up window (GIVE_UP_SECS) eventually closes it out -- an
# honest "don't know" beats a confident wrong answer.


UUID_MATCH_THRESHOLD = 3   # verified zero-false-positive floor across 8 real fork pairs
                            # (14-508 shared early uuids observed per genuine pair)

GIVE_UP_SECS = 15 * 60     # a fork that hasn't written a matching transcript within 15 minutes
                            # of the retry is not coming (the real gap is sub-second — process
                            # spawn + first write). 15 minutes is generous slack for a slow disk
                            # or a loaded machine while still making sure an abandoned parent
                            # stops costing anything (a re-glob + re-open of every candidate on
                            # every ~2-5s poll) well within a normal session.


def _load_forks():
    d = _load_json(config.FORKS_FILE, {})
    return d if isinstance(d, dict) else {}


def _update_forks(mutate):
    """Read-modify-write forks.json serialized behind an exclusive flock, so
    concurrent callers (record_fork for N different parents, resolve_fork_child
    memoizing a match or a give-up) don't lose each other's write. `_save_json`'s
    unique-temp-name fix only stops writers from clobbering each other's temp
    FILE; without this lock, two interleaved read/modify/write cycles can each
    read the same old dict and the later os.replace silently discards the
    earlier writer's change (observed: 10 concurrent record_fork calls for 10
    different parents, only some survived).

    `mutate(forks_dict)` mutates the dict in place; returning False skips the
    save (the various already-recorded/already-resolved no-op cases), so an
    unnecessary rewrite doesn't happen while holding the lock.

    flock is POSIX-only, which matches this project's footprint elsewhere
    (the Makefile, term_vt's PTY handling) -- no cross-platform fallback."""
    lock_path = config.FORKS_FILE + ".lock"
    lockfh = open(lock_path, "a")
    try:
        fcntl.flock(lockfh.fileno(), fcntl.LOCK_EX)
        try:
            forks = _load_forks()
            if mutate(forks) is not False:
                _save_json(config.FORKS_FILE, forks)
        finally:
            fcntl.flock(lockfh.fileno(), fcntl.LOCK_UN)
    finally:
        lockfh.close()


def _find_transcript(sid):
    """The one file config.PROJECTS/*/<sid>.jsonl for a KNOWN session id --
    globbing on the filename itself, not a scan of every file's contents."""
    matches = glob.glob(os.path.join(config.PROJECTS, "*", sid + ".jsonl"))
    return matches[0] if matches else ""


def _scan_early(path, max_lines=20):
    """One pass over the first ~max_lines JSON lines of a transcript: the cwd
    off the first line that has one, and the uuid of every line that has one.
    Bookkeeping lines (`type` of `mode` / `queue-operation` / `last-prompt`)
    carry no uuid, and not every line carries a cwd either -- lines missing a
    key are skipped rather than assumed to have it. Tolerates a malformed/
    truncated line (a transcript that's still being written)."""
    cwd = ""
    uuids = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for _ in range(max_lines):
                line = fh.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict):
                    continue
                if not cwd and o.get("cwd"):
                    cwd = o["cwd"]
                if o.get("uuid"):
                    uuids.append(o["uuid"])
    except OSError:
        pass
    return cwd, uuids


def _creation_time(path):
    """The best available CREATION time for `path`: `st_birthtime` where the platform
    provides it -- IT IS populated and meaningful on this machine's APFS volume; an
    empirical check found a real fork child's birthtime within 0.5s of its first
    post-fork message timestamp. `st_birthtime` doesn't exist on every platform's stat
    result (e.g. most Linux filesystems), so this falls back to `st_mtime` there. That
    fallback is WEAKER: mtime is last-MODIFIED, not created, so an unrelated or ancestor
    session that merely gets touched again after the fork instant can still sort ahead
    of the true child on such a platform -- there is simply no more accurate signal
    available there. A single `os.stat()` call feeds both, so this costs nothing extra
    over the old getmtime()-only version."""
    st = os.stat(path)
    bt = getattr(st, "st_birthtime", None)
    return bt if bt is not None else st.st_mtime


_LISTDIR_RETRIES = 3
"""How many times `_list_jsonl_ids` tries `os.listdir()` before giving up and
reporting failure. The failure this guards against (EMFILE, an NFS-style
hiccup) is transient, and the call is cheap, so a couple of immediate retries
clear it without perceptibly delaying record_fork's caller -- see the module
comment's "empty vs failed" section for why giving up must produce `None`,
never a silent `[]`."""

_LISTDIR_RETRY_DELAY = 0.05  # seconds between retries -- short enough that even
                              # all _LISTDIR_RETRIES of them together are imperceptible
                              # against a fork the user is actively watching land


def _list_jsonl_ids(dir_path):
    """The bare session ids (no `.jsonl`) of every transcript currently in
    `dir_path`, or `None` if the listing itself failed after retries -- the
    sentinel `record_fork`'s snapshot depends on to distinguish "genuinely
    empty directory" (a perfectly usable snapshot) from "couldn't find out"
    (not usable at all; see the module comment above). Never returns `[]` on
    a failure. Logs rather than swallowing the failure, once every attempt is
    exhausted, in this codebase's existing `"[ai-tracker] <component>: ..."`
    print style (term_vt.py uses it throughout)."""
    exc = None
    for attempt in range(_LISTDIR_RETRIES):
        try:
            return [f[:-len(".jsonl")] for f in os.listdir(dir_path) if f.endswith(".jsonl")]
        except OSError as e:
            exc = e
            if attempt + 1 < _LISTDIR_RETRIES:
                time.sleep(_LISTDIR_RETRY_DELAY)
    print("[ai-tracker] store: pre_existing snapshot listdir failed for %r after %d attempt(s): %r"
          % (dir_path, _LISTDIR_RETRIES, exc))
    return None


def capture_fork_snapshot(parent_sid):
    """Capture, right now, the THREE facts resolve_fork_child needs and can
    never safely reconstruct later (see the module comment above): the
    parent's own early-uuid fingerprint (`parent_uuids`), the parent
    transcript's own creation time (`parent_ct`, the belt-and-braces "a child
    cannot predate its parent" floor), and — the fix's core piece — the exact
    SET of session ids already sitting in the parent's project directory at
    this instant (`pre_existing`, via `_list_jsonl_ids` -- `None` if that
    listing itself failed, never a silent `[]`).

    MUST be called before the fork's own `execvp` wherever one is about to
    happen (see term_vt._retry_with_fork's call site comment): this is the
    one moment the parent's transcript is guaranteed to exist and be
    readable AND the one moment a "what already exists" snapshot can still
    distinguish a pre-fork sibling from the actual child -- captured any
    later, a fast-writing child could land IN this very snapshot and be
    permanently excluded as "pre-existing".

    Degrades safely when the parent transcript can't be found or read (a
    race with the file not being flushed yet, or something stranger): fields
    come back falsy/`None` rather than raising, and resolve_fork_child treats
    an empty fingerprint, or an unusable `pre_existing`, as "nothing safe to
    match against yet" and stays unresolved (never guesses) until the
    give-up window closes it out."""
    path = _find_transcript(parent_sid)
    _, parent_uuids = _scan_early(path) if path else ("", [])
    parent_dir = os.path.dirname(path) if path else ""
    pre_existing = _list_jsonl_ids(parent_dir) if parent_dir else None
    parent_ct = None
    if path:
        try:
            parent_ct = _creation_time(path)
        except OSError:
            parent_ct = None
    return {
        "parent_uuids": parent_uuids,
        "parent_dir": parent_dir,
        "pre_existing": pre_existing,
        "parent_ct": parent_ct,
    }


def record_fork(parent_sid, cwd, at, snapshot=None):
    """Record that `parent_sid` forked (via --fork-session) at unix time `at`,
    while the terminal's cwd was `cwd`. Idempotent — the retry path may call
    this more than once for the same parent (e.g. if the tracker restarts), so
    an existing record is left untouched rather than overwritten: that would
    either duplicate work or, worse, wipe out an already-fingerprinted or
    already-resolved record.

    `snapshot` has a three-way contract:
      - omitted (`None`): "no snapshot supplied, please self-capture" — this
        function calls `capture_fork_snapshot(parent_sid)` itself, synchronously,
        right here. Fine for a caller with no exec race to worry about (every
        direct `record_fork(sid, cwd, at)` call in this project's own test
        suite relies on this fallback for convenience) — but production's
        fork-retry path (term_vt._retry_with_fork) never relies on it, because
        self-capturing here would run AFTER the fork's own exec, reopening the
        exact pre-exec-vs-post-exec race the snapshot-before-exec design exists
        to close.
      - a dict: MUST be `capture_fork_snapshot(parent_sid)`'s return value,
        captured BEFORE the fork's own exec by the caller that knows when that
        is (term_vt._retry_with_fork does exactly this — see its call site
        comment). Used as given, never re-captured.
      - a dict with `pre_existing: None`: an explicit "the pre-exec capture
        failed" sentinel (also produced by term_vt._retry_with_fork, in its
        `except` branch). Still used as given — NOT treated as "omitted" — so
        `resolve_fork_child`'s refuse-gate (see its docstring) correctly leaves
        the fork unresolved instead of silently self-capturing post-exec."""
    def mutate(forks):
        if parent_sid in forks:
            return False
        snap = snapshot if snapshot is not None else capture_fork_snapshot(parent_sid)
        forks[parent_sid] = {
            "at": at,
            "cwd": cwd,
            "child": "",
            "abandoned": False,
            "parent_uuids": snap.get("parent_uuids") or [],
            "parent_dir": snap.get("parent_dir") or "",
            "pre_existing": snap.get("pre_existing"),   # None == unusable snapshot; [] == genuinely empty
            "parent_ct": snap.get("parent_ct"),
        }
    _update_forks(mutate)


def resolve_fork_child(parent_sid):
    """The session id `parent_sid` forked into, or "" if it isn't a recorded
    fork parent at all, the fork hasn't matched anything yet, or resolution
    was abandoned (see GIVE_UP_SECS).

    FAST PATHS (single dict lookup, no filesystem I/O): not a recorded fork
    parent; already abandoned; already memoized.

    Otherwise a candidate must pass TWO EXACT gates (module comment above has
    the full rationale/evidence):
      1. NOT a member of `pre_existing` — the snapshot of session ids that
         already existed in the parent's directory at fork time. This is the
         fix: a file that was already there cannot be the child, whatever its
         timestamps say, so this alone rules out ancestors, unrelated older
         sessions, and touched-mtime files that fooled three prior rounds.
         `pre_existing` itself is a SENTINEL, not just a list: `None` means
         the snapshot's own `os.listdir()` failed at record time (see
         `_list_jsonl_ids`) and there is nothing safe to check membership
         against, so this function REFUSES to resolve at all in that case —
         stays unresolved and is retried on the next poll — rather than
         treating a failed listing as an empty one and letting gate 1 become
         a silent no-op (which is exactly what fell back to the ordering
         heuristic that broke rounds 1-3). A genuinely empty directory (`[]`,
         listdir succeeded and found nothing) is fully usable and does NOT
         trigger this refusal.
      2. UUID-overlap with the parent's fingerprint >= UUID_MATCH_THRESHOLD.
    Both are exact facts, never a guess. A belt-and-braces floor additionally
    requires the candidate's own creation time to be at-or-after the PARENT
    TRANSCRIPT's creation time (`parent_ct`) — a child cannot predate its
    parent. Among candidates that pass all of that, the one picked is the
    EARLIEST-CREATED (see _creation_time), tie-broken explicitly by session
    id — this ordering is now only a POLICY choice for a genuinely ambiguous
    case (the same parent forked twice in one window), never load-bearing for
    excluding an ancestor or a stranger; that job belongs to gate 1.

    The search is narrowed to the parent's own project directory (a fork
    keeps the terminal's cwd, so that's the expected location) and does NOT
    widen to every project directory — see the module comment for why a
    widen fallback was removed rather than fixed: the snapshot is only
    meaningful for the directory it was taken in. If the parent's own
    directory was never captured (or the child hasn't shown up there yet),
    resolution stays "" and is retried on the next poll until GIVE_UP_SECS.

    MEMOIZED once resolved (or abandoned): later calls are a single dict
    lookup, no re-scan. This is called once per session on every ~2s poll
    (registry.all_sessions()/parse_any()), so an unmemoized scan -- or a scan
    that never gives up on a parent that will never resolve -- would be a
    real performance bug."""
    forks = _load_forks()
    rec = forks.get(parent_sid)
    if not isinstance(rec, dict):
        return ""                        # not a fork parent — no I/O beyond the one read above
    if rec.get("abandoned"):
        return ""                        # gave up already — no I/O beyond the one read above
    child = rec.get("child")
    if child:
        return child                     # memoized — no filesystem scan

    at = rec.get("at", 0)
    if time.time() - at > GIVE_UP_SECS:
        def give_up(f):
            r = f.get(parent_sid)
            if not isinstance(r, dict) or r.get("child") or r.get("abandoned"):
                return False
            r["abandoned"] = True
            r.pop("pre_existing", None)   # dead weight once resolution has given up (defect 3)
        _update_forks(give_up)
        return ""

    parent_uuids = set(rec.get("parent_uuids") or [])
    if not parent_uuids:
        return ""   # no fingerprint captured at record time — nothing safe to match against yet

    parent_dir = rec.get("parent_dir") or ""
    if not parent_dir or not os.path.isdir(parent_dir):
        return ""   # nowhere safe to look yet — no widen fallback (see module comment); retried later

    pre_existing_field = rec.get("pre_existing")
    if pre_existing_field is None:
        return ""   # snapshot listdir failed at record time — unusable; never guess (see gate 1 above)
    pre_existing = set(pre_existing_field)
    parent_ct = rec.get("parent_ct")
    cwd = rec.get("cwd", "")

    candidates = []                      # (creation_time, sid, path) for every file that survives both gates
    for path in glob.glob(os.path.join(parent_dir, "*.jsonl")):
        sid = os.path.basename(path)[:-len(".jsonl")]
        if sid == parent_sid or sid in pre_existing:
            continue                     # gate 1 (exact): never the parent itself, never something that pre-dates the fork
        try:
            ct = _creation_time(path)
        except OSError:
            continue
        if parent_ct is not None and ct < parent_ct:
            continue                     # belt-and-braces: a child cannot be older than its own parent transcript
        candidates.append((ct, sid, path))
    # Earliest-created candidate first; ties broken EXPLICITLY by session id so the
    # answer is stable across runs rather than an unstated side effect of glob's
    # filesystem-dependent order. This ordering is a POLICY tie-break among candidates
    # that already cleared both exact gates -- see the module comment's fork-of-a-fork
    # example for why it is not, itself, what makes the answer correct.
    candidates.sort(key=lambda t: (t[0], t[1]))

    for _, sid, path in candidates:
        c_cwd, c_uuids = _scan_early(path)
        if cwd and c_cwd != cwd:
            continue                     # cheap prefilter (avoids the set-intersection below) — still not the decision
        if len(parent_uuids.intersection(c_uuids)) >= UUID_MATCH_THRESHOLD:
            def set_child(f, _sid=sid):
                r = f.get(parent_sid)
                if not isinstance(r, dict) or r.get("child"):
                    return False
                r["child"] = _sid
                r.pop("pre_existing", None)   # dead weight once resolved (defect 3) -- up to ~20KB/record
            _update_forks(set_child)
            return sid

    return ""                            # not written yet, or nothing matched — retried later (until give-up)


def fork_parent_of(child_sid):
    """Reverse of resolve_fork_child: the recorded fork parent that has
    ALREADY resolved to this session id, or "". Only looks at what's already
    memoized in forks.json — it never itself triggers a directory scan, so
    it's as cheap as the (tiny) record is small."""
    for parent_sid, rec in _load_forks().items():
        if isinstance(rec, dict) and rec.get("child") == child_sid:
            return parent_sid
    return ""
