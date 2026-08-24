

class Provider:
    prefix = ""              # id namespace ("" = default/Claude with bare ids)

    def available(self):     # is this tool's data present on the machine?
        return True

    def list(self):          # -> [session summary dicts]
        return []

    def parse(self, sid):    # full id -> detail dict (or None if not found)
        return None

    def search(self, q):     # -> [search result dicts] (optional)
        return []

    def exists(self, sid):   # does this session actually exist?
        # registry.drill() calls this BEFORE any drill-down method, so a bogus id
        # 404s instead of reaching the empty defaults below. The default here is
        # correct but not cheap (a full parse); a provider whose parse() does real
        # work should override with a lighter check (see ClaudeProvider.exists /
        # AuggieProvider.exists — a plain lookup/file-existence check).
        return self.parse(sid) is not None

    def is_bg_agent(self, sid):
        # Is `sid` a "background agent" session in the `claude --bg`/SDK-spawned sense
        # (the concept that makes `claude --resume` refuse without `--fork-session`,
        # see term_gate.resume_argv)? Resolved DIRECTLY for this one sid — never by
        # scanning list()'s top-N-by-mtime output, which would miss anything outside
        # that window (registry.is_bg_agent is the seam; see that function's docstring).
        # Only a provider that has this concept overrides it; everyone else has no
        # background-agent notion at all, so the honest default is False.
        return False

    # --- drill-downs: the click-through views behind the detail panels. Routes reach
    # these through registry.drill(), never through one provider's own session lookup,
    # so a namespaced id can't fall off the seam. registry.drill() checks exists()
    # first and 404s when the session is bogus — so the defaults below are only ever
    # reached for a session that DOES exist, where they mean "the session exists,
    # this tool records nothing here" — an empty modal, not an error. ---

    def output(self, sid, cmd_id):        # a command's captured output
        return {"cmd": "", "out": "", "ok": True}

    def diff(self, sid, target):          # every edit to one file, oldest-first
        return []

    def shell(self, sid, shell_id):       # a background shell's tail
        return {"cmd": "", "out": "", "running": False}

    def agent(self, sid, aid):            # a background agent's transcript
        return {}
