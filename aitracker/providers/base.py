

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
