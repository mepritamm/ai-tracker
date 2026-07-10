"""Assemble the single self-contained HTML page from web/ assets (inlined at serve time)."""
import os

_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def build_page():
    def read(name):
        with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
            return fh.read()
    html = read("index.html")
    return html.replace("__CSS__", read("app.css")).replace("__JS__", read("app.js"))
