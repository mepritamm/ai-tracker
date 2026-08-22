"""Assemble the single self-contained HTML page from web/ assets (inlined at serve time)."""
import os

_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def build_page():
    def read(name):
        with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
            return fh.read()
    def read_ext(suffix):
        # ponytail: sorted glob so the baked page is byte-stable across restarts
        names = sorted(n for n in os.listdir(_WEB) if n.startswith("ext_") and n.endswith(suffix))
        return "\n".join(read(n) for n in names)
    html = read("index.html")
    return (html.replace("__CSS__", read("app.css") + read_ext(".css"))
                .replace("__JS__", read("app.js") + read_ext(".js")))
