

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

    # --- drill-downs: the click-through views behind the detail panels. Routes reach
    # these through registry.drill(), never through one provider's own session lookup,
    # so a namespaced id can't fall off the seam. Returning None means "no such
    # session" (the route 404s); the defaults below mean "the session exists, this
    # tool records nothing here" — an empty modal, not an error. ---

    def output(self, sid, cmd_id):        # a command's captured output
        return {"cmd": "", "out": "", "ok": True}

    def diff(self, sid, target):          # every edit to one file, oldest-first
        return []

    def shell(self, sid, shell_id):       # a background shell's tail
        return {"cmd": "", "out": "", "running": False}

    def agent(self, sid, aid):            # a background agent's transcript
        return {}
