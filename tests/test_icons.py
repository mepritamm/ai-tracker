"""Regression tests for the emoji -> inline-SVG icon system.

aitracker/web/index.html carries a hidden sprite of `<symbol id=i-NAME viewBox="0 0
24 24">` entries (alongside the pre-existing `#brandMark` logo symbol), all living
inside ONE `<svg class=brandsprite ...>...</svg>` block. Live code renders an icon as
`<svg ...><use href="#i-NAME"/></svg>`, built by app.js's `ico(name, cls)` helper or
one of the control-room modules' own `icon(name, ...)` / `glyph(name, ...)` /
`svgIcon(ctx, name, ...)` helpers (see aitracker/web/ext_cr_*.js).

THE BUG CLASS this file exists for: a `<use href="#i-NAME">` (or an
ico()/icon()/glyph()/svgIcon() call) naming a symbol that isn't defined renders
NOTHING -- no exception, no console warning, no layout shift. It is invisible to
code review and to the rest of the test suite. Three such bugs occurred during the
emoji -> SVG migration this file was written to guard against.

Stdlib `unittest` only, matching every other test in this suite -- no pytest, no
new dependencies. Run: `python -m unittest discover -s tests` (or `make check`).
"""
import os
import re
import unittest
import xml.etree.ElementTree as ET

from aitracker import page

_AITRACKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker")
_WEB = os.path.join(_AITRACKER, "web")


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _web_names(*exts):
    """Filenames directly under aitracker/web/ (NOT web/vendor/ -- that's
    third-party code: xterm.js, mermaid.min.js, lazily loaded, never uses our
    icon helpers or our comment conventions, and is out of scope everywhere
    below)."""
    return sorted(
        n for n in os.listdir(_WEB)
        if n.endswith(exts) and os.path.isfile(os.path.join(_WEB, n))
    )


# ============================================================================
# 1. No dangling icon references.
# ============================================================================

_DEFINED_RE = re.compile(r'id=i-([a-z0-9-]+)')

# The three call shapes actually used in this repo (app.js's `ico`; ext_cr_*.js's
# own `icon`/`glyph`/`svgIcon`), each captured only when the icon name is a
# LITERAL single- or double-quoted string.
#
# LIMITATION: a name passed through a variable -- `icon(v.glyph)`,
# `svgIcon(ctx, m.glyph)` (both real call sites in ext_cr_detail.js) -- cannot be
# resolved by a text regex and is silently NOT checked by this test. A dangling
# reference reached only through such a variable will not be caught here; it
# would need either a data-flow-aware check or a runtime/DOM assertion instead.
_REF_RE = re.compile(
    r'href="#i-([a-z0-9-]+)"'
    r'|\bico\(\s*(["\'])([a-z0-9-]+)\2'
    r'|\bicon\(\s*(["\'])([a-z0-9-]+)\4'
    r'|\bglyph\(\s*(["\'])([a-z0-9-]+)\6'
    r'|\bsvgIcon\(\s*[A-Za-z_$][\w$]*\s*,\s*(["\'])([a-z0-9-]+)\8'
)


def _referenced_icons():
    """Yield (name, filename, lineno) for every literal-string icon reference
    across aitracker/web/*.js and *.html."""
    for fn in _web_names(".js", ".html"):
        text = _read(fn)
        for m in _REF_RE.finditer(text):
            name = next(g for g in m.groups() if g and re.match(r'^[a-z0-9-]+$', g))
            lineno = text.count("\n", 0, m.start()) + 1
            yield name, fn, lineno


class TestNoDanglingIconReferences(unittest.TestCase):
    def test_every_referenced_icon_is_defined(self):
        defined = set(_DEFINED_RE.findall(_read("index.html")))
        offenders = [(name, fn, ln) for name, fn, ln in _referenced_icons() if name not in defined]
        self.assertEqual(
            offenders, [],
            "Reference to an icon symbol not defined in index.html's sprite -- "
            "this renders NOTHING at runtime, with no error and no console "
            "warning:\n" + "\n".join(
                "  #i-%s referenced at %s:%d" % (name, fn, ln) for name, fn, ln in offenders
            )
        )


# ============================================================================
# 2. The sprite is well-formed XML with no duplicate ids.
# ============================================================================

# HTML permits unquoted attribute values (`id=i-flag`, `class=ico`), which is
# valid HTML but NOT valid XML. Quote every such bare value before parsing so
# this test is robust to that convention rather than brittle against it.
_UNQUOTED_ATTR_RE = re.compile(r'(\s[a-zA-Z_:][-a-zA-Z0-9_:.]*)=([^\s"\'>/][^\s>/]*)')


class TestSpriteWellFormed(unittest.TestCase):
    def _sprite_block(self):
        html = _read("index.html")
        start = html.index("<svg class=brandsprite")
        end = html.index("</svg>", start) + len("</svg>")
        return html[start:end]

    def test_sprite_is_well_formed_xml_with_no_duplicate_ids(self):
        sprite = self._sprite_block()
        xmlish = _UNQUOTED_ATTR_RE.sub(r'\1="\2"', sprite)
        try:
            root = ET.fromstring(xmlish)
        except ET.ParseError as e:
            self.fail("Icon sprite is not well-formed XML (even after quoting bare "
                      "HTML attribute values): %s" % e)

        ids = [el.get("id") for el in root.iter() if el.get("id") is not None]
        self.assertGreater(len(ids), 0, "sprite parsed but no <symbol id=...> found -- check the extraction")
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(dupes, [], "Duplicate symbol id(s) in the icon sprite: %s" % dupes)


# ============================================================================
# 3. No emoji in live code.
# ============================================================================

def _strip_comments(text, kind):
    """Blank out comments in `text`, replacing removed characters with spaces
    (newlines kept) so line numbers computed against the result still line up
    with the original file.

    kind: 'js' (// line comments + /* ... */ block comments, multi-line-aware --
    a `*/` on a LATER line correctly ends a comment opened earlier), 'html'
    (<!-- ... --> only), 'py' (# to end of line only).

    This is a character scanner, not a real lexer: it doesn't know about string
    literals, so a literal `//` or `#` inside a string is (rarely, and not
    anywhere in this codebase today) misread as a comment start. Good enough for
    an emoji sweep; not a general-purpose comment stripper.
    """
    out = list(text)
    n = len(text)
    i = 0
    if kind == "py":
        while i < n:
            if text[i] == "#":
                while i < n and text[i] != "\n":
                    out[i] = " "
                    i += 1
            else:
                i += 1
    elif kind == "html":
        while i < n:
            if text[i:i + 4] == "<!--":
                end = text.find("-->", i + 4)
                end = end + 3 if end != -1 else n
                for j in range(i, end):
                    if text[j] != "\n":
                        out[j] = " "
                i = end
            else:
                i += 1
    else:  # js / css
        while i < n:
            two = text[i:i + 2]
            if two == "//":
                while i < n and text[i] != "\n":
                    out[i] = " "
                    i += 1
            elif two == "/*":
                end = text.find("*/", i + 2)
                end = end + 2 if end != -1 else n
                for j in range(i, end):
                    if text[j] != "\n":
                        out[j] = " "
                i = end
            else:
                i += 1
    return "".join(out)


# Unicode ranges scanned for "pictographic" candidates. Deliberately NOT every
# symbol-ish block: an earlier, broader pass (any Unicode category So/Sm above
# U+2000) flagged dozens of ordinary UI typography that has nothing to do with
# emoji -- arrows in diagram labels, x-as-multiplication-sign run counts,
# en/em dashes, curly quotes, the degree/percent-adjacent math symbols, etc.
# These ranges are the ones that actually contain either (a) a symbol from the
# task's own kept-typographic-symbol list, or (b) a real emoji block -- i.e.
# exactly where a leftover emoji could plausibly hide.
_PICTOGRAPHIC_RANGES = (
    (0x2190, 0x21FF),   # Arrows
    (0x2300, 0x23FF),   # Miscellaneous Technical
    (0x2580, 0x25FF),   # Block Elements + Geometric Shapes
    (0x2600, 0x27BF),   # Miscellaneous Symbols + Dingbats
    (0x2900, 0x297F),   # Supplemental Arrows-B
    (0x2980, 0x29FF),   # Miscellaneous Mathematical Symbols-B
    (0x2B00, 0x2BFF),   # Miscellaneous Symbols and Arrows
    (0xFF00, 0xFFEF),   # Halfwidth and Fullwidth Forms
    (0x1F000, 0x1FFFF),  # the modern emoji astral blocks (emoticons, transport,
                          # supplemental symbols & pictographs, ...)
)
_PICTOGRAPHIC_SPECIALS = "‹›·"  # ‹ › · (outside the ranges above)

# Plain typographic symbols that are deliberately kept and are NOT emoji --
# given exhaustively by the task, verified still accurate against this checkout.
_KEPT_TYPOGRAPHIC = set("✓✗▾▸▶○◆⚙⎇✎⧉⇕↑↓✕☰⌕＋⚠▍✦‹›⤒⤢◧⌨⬇↩●·")

# Additional plain symbols found by actually running this scan against the repo
# (see the ranges above) that are equally non-emoji but weren't in the task's
# list -- same treatment, spelled out here instead of silently widening the
# whitelist: arrows used as plain diagram/UI notation (breadcrumbs, "external ↗"
# hints, mermaid-style edges), the Mac "⌘" key glyph in keyboard-shortcut hints,
# and geometric-shape glyphs used as plain button/indicator icons. Each was
# checked against its actual call site below to confirm it's live UI chrome, not
# a leftover emoji.
_KEPT_TYPOGRAPHIC |= set("←→↗⇒")     # plain arrows (app.js, ext_cr_term.js, ext_cr_dialogs.js, ...)
_KEPT_TYPOGRAPHIC |= set("⌘")        # Command-key glyph (ext_cr_board.js/_dialogs.js kbd hints)
_KEPT_TYPOGRAPHIC |= set("▼◐◑■▤▦")   # geometric-shape button/indicator glyphs (ext_vt.js, index.html)
# ⧖ (U+29D6) is the server's "waiting" status prefix on now_line, emitted by
# providers/claude.py + providers/auggie.py and stripped by app.js's prefix regex.
# It replaced the ⏳ EMOJI: it is a mathematical symbol from the same block as the
# already-kept ⧉ (U+29C9), monochrome and font-driven, so it is a standard symbol
# and not a pictograph. Keep it in lockstep with that regex in app.js.
_KEPT_TYPOGRAPHIC |= set("⧖")


def _is_pictographic(ch):
    if ch in _PICTOGRAPHIC_SPECIALS:
        return True
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _PICTOGRAPHIC_RANGES)


# ICO_EMOJI and ICO_TEXT (app.js) are the deliberate glyph sources for the
# "emoji" and "text" ICON_STYLEs -- ICO_EMOJI is REQUIRED to contain actual
# emoji, and ICO_TEXT deliberately packs in the same kind of plain typographic
# symbols this file already whitelists via _KEPT_TYPOGRAPHIC above (just too
# many, all on one line, to spell out individually there). Both are data this
# sweep was never meant to catch, not a leftover the SVG-icon migration missed.
# Blank just those two literals (space-preserving-newlines, so line numbers
# elsewhere in the file stay correct) before scanning; everywhere else in
# app.js, and every other file, is still scanned in full.
_ICO_GLYPH_MAP_LITERAL_RE = re.compile(r'const\s+(?:ICO_EMOJI|ICO_TEXT)\s*=\s*\{.*?\}\s*;', re.DOTALL)


def _blank_ico_glyph_map_literals(text):
    out = text
    while True:
        m = _ICO_GLYPH_MAP_LITERAL_RE.search(out)
        if not m:
            return out
        start, end = m.span()
        blanked = "".join(c if c == "\n" else " " for c in out[start:end])
        out = out[:start] + blanked + out[end:]


def _scan_for_emoji(path, kind):
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    if kind == "js" and os.path.basename(path) == "app.js":
        raw = _blank_ico_glyph_map_literals(raw)
    stripped = _strip_comments(raw, kind)
    offenders = []
    for lineno, line in enumerate(stripped.splitlines(), start=1):
        for ch in line:
            if _is_pictographic(ch) and ch not in _KEPT_TYPOGRAPHIC:
                offenders.append((os.path.basename(path), lineno, ch))
    return offenders


class TestNoEmojiInLiveCode(unittest.TestCase):
    def test_no_pictographic_emoji_outside_comments(self):
        offenders = []
        for fn in _web_names(".js", ".css", ".html"):
            kind = "html" if fn.endswith(".html") else "js"
            offenders += _scan_for_emoji(os.path.join(_WEB, fn), kind)
        server_py = os.path.join(_AITRACKER, "server.py")
        if os.path.exists(server_py):
            offenders += _scan_for_emoji(server_py, "py")

        self.assertEqual(
            offenders, [],
            "Pictographic character(s) found outside comments (leftover emoji "
            "the SVG-icon migration should have replaced):\n" + "\n".join(
                "  %s:%d: %r (U+%04X)" % (fn, ln, ch, ord(ch)) for fn, ln, ch in offenders
            )
        )


# ============================================================================
# 4. The assembled page actually contains the sprite and the helper.
# ============================================================================

class TestBuiltPageCarriesIcons(unittest.TestCase):
    def test_build_page_inlines_sprite_and_ico_helper(self):
        html = page.build_page()
        self.assertIn("<symbol id=i-", html, "assembled page lost the icon sprite during inlining")
        self.assertIn("function ico(", html, "assembled page lost the ico() helper during inlining")


# ============================================================================
# 5. ICO_EMOJI and ICO_TEXT (the style-switch glyph maps) cover every sprite icon,
#    exactly -- no gaps, no stragglers.
# ============================================================================
#
# ICON_STYLE lets a user switch the whole app to "emoji" or "text" glyphs instead
# of the SVG sprite. ico(name, cls) looks the name up in ICO_EMOJI/ICO_TEXT for
# those styles and falls back to the SVG <use> only for the default "icons"
# style -- so a name missing from one of these maps renders NOTHING (or the
# wrong glyph) the moment someone switches style, with no error anywhere.
#
# This is regex-parsed from source (a literal `"key":"value"` scan of the
# `const ICO_EMOJI={...};` / `const ICO_TEXT={...};` object literals in app.js),
# not a JS evaluator -- it only sees entries written as literal quoted
# key:value pairs, which is how both maps are actually authored.
_MAP_LITERAL_RE = re.compile(r'const\s+(ICO_EMOJI|ICO_TEXT)\s*=\s*\{(.*?)\}\s*;')
_MAP_ENTRY_RE = re.compile(r'"([a-z0-9-]+)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _parse_icon_glyph_map(js_text, const_name):
    """Return {name: glyph} for `const <const_name>={...};` in app.js, or None
    if that const isn't found at all."""
    m = re.search(r'const\s+' + const_name + r'\s*=\s*\{(.*?)\}\s*;', js_text, re.DOTALL)
    if m is None:
        return None
    return dict(_MAP_ENTRY_RE.findall(m.group(1)))


def _sprite_icon_names():
    """Every `id=i-NAME` symbol in the index.html sprite (excludes #brandMark,
    which isn't `i-`-prefixed)."""
    return set(_DEFINED_RE.findall(_read("index.html")))


class TestGlyphMapsCoverEverySpriteIcon(unittest.TestCase):
    def test_both_maps_cover_every_sprite_icon_and_nothing_else(self):
        js = _read("app.js")
        sprite = _sprite_icon_names()
        self.assertGreater(len(sprite), 0, "no sprite icons found -- check the extraction")

        for const_name in ("ICO_EMOJI", "ICO_TEXT"):
            glyphs = _parse_icon_glyph_map(js, const_name)
            self.assertIsNotNone(glyphs, "no `const %s={...};` object literal found in app.js" % const_name)
            keys = set(glyphs)

            missing = sorted(sprite - keys)
            self.assertEqual(
                missing, [],
                "Sprite icon(s) missing from %s -- switching to that icon style will "
                "render nothing (or fall through wrong) for: %s" % (const_name, ", ".join(missing))
            )

            extra = sorted(keys - sprite)
            self.assertEqual(
                extra, [],
                "%s has entry/entries for name(s) not in the icon sprite (dead or "
                "misspelled): %s" % (const_name, ", ".join(extra))
            )


# ============================================================================
# 6. No glyph-map entry is empty.
# ============================================================================

class TestNoEmptyGlyphMapEntry(unittest.TestCase):
    def test_every_map_value_is_a_non_empty_string(self):
        js = _read("app.js")
        offenders = []
        for const_name in ("ICO_EMOJI", "ICO_TEXT"):
            glyphs = _parse_icon_glyph_map(js, const_name) or {}
            for name, glyph in glyphs.items():
                if not isinstance(glyph, str) or glyph == "":
                    offenders.append("%s[%r] = %r" % (const_name, name, glyph))
        self.assertEqual(
            offenders, [],
            "Empty glyph-map entry -- renders a blank where an icon should be:\n" +
            "\n".join("  " + o for o in offenders)
        )


# ============================================================================
# 7. Every static icon in index.html is tagged with a matching data-ico, so the
#    boot-time style switch can find and convert it.
# ============================================================================
#
# applyIconStyle() converts already-rendered static markup by selecting
# `svg.ico[data-ico]` / `span.ico-glyph[data-ico]` and re-rendering from the
# name in that attribute. An `<svg class=ico>` with no `data-ico` (or one whose
# value doesn't match its own `<use href="#i-NAME">`) silently never converts:
# it stays whatever it was rendered as, forever, no matter what style the user
# picks.
#
# Explicitly EXCLUDED (by construction of the regex, since neither ever
# actually carries `class=ico`, but spelled out here since the task called it
# out): the sprite's own `<symbol id=i-NAME>` definitions (a `<symbol>`, not an
# `<svg class=ico>`), and the product logo (`<svg><use href="#brandMark"/>`,
# which is not `#i-`-prefixed and is never `class=ico`).
_STATIC_ICON_RE = re.compile(r'<svg\s+([^>]*\bclass=ico\b[^>]*)>\s*<use href="#i-([a-z0-9-]+)"')
_DATA_ICO_ATTR_RE = re.compile(r'\bdata-ico=([a-z0-9-]+)\b')


class TestStaticIconsTaggedAndConsistent(unittest.TestCase):
    def test_every_static_ico_svg_carries_a_matching_data_ico(self):
        html = _read("index.html")
        untagged, mismatched = [], []
        n = 0
        for m in _STATIC_ICON_RE.finditer(html):
            n += 1
            attrs, use_name = m.groups()
            lineno = html.count("\n", 0, m.start()) + 1
            dm = _DATA_ICO_ATTR_RE.search(attrs)
            if dm is None:
                untagged.append((use_name, lineno))
            elif dm.group(1) != use_name:
                mismatched.append((use_name, dm.group(1), lineno))
        self.assertGreater(n, 0, "no static `<svg class=ico>...<use href=#i-...>` icons found -- check the regex")
        self.assertEqual(
            untagged, [],
            "Static icon(s) with no data-ico attribute -- applyIconStyle() can never "
            "convert them when the user switches icon style:\n" + "\n".join(
                "  #i-%s at index.html:%d has no data-ico" % (name, ln) for name, ln in untagged
            )
        )
        self.assertEqual(
            mismatched, [],
            "Static icon(s) whose data-ico doesn't match their own #i-NAME -- "
            "applyIconStyle() would convert them to the WRONG icon:\n" + "\n".join(
                "  index.html:%d: <use href=#i-%s> but data-ico=%s" % (ln, use, dat)
                for use, dat, ln in mismatched
            )
        )


# ============================================================================
# 8. --ico-scale is actually wired: defined once, driving the base .ico rule,
#    and no new icon rule quietly reintroduces a fixed size that ignores it.
# ============================================================================

_CSS_RULE_RE = re.compile(r'([^{}]+)\{([^{}]*)\}')


def _css_rules(text):
    """Yield (selector_text, body_text) for every rule in a CSS file, including
    ones nested inside an @media block. Text scan, not a real CSS parser: it
    finds every innermost {...} pair -- an @media's own wrapping brace can
    never itself complete a match (its own body always contains a further
    nested `{` before the first `}`), so only actual rule bodies come out."""
    return _CSS_RULE_RE.findall(text)


# A selector is treated as "an icon svg rule" only if it targets `svg` (as the
# element itself, or the rightmost part of a descendant selector) AND mentions
# one of the icon-system's own class conventions: the shared `.ico` class, or
# one of the Control Room rail/detail/tracker-next icon-wrapper prefixes
# (`cr-`, `crd-`, `tn-`) that the codebase actually uses for icon containers.
# This deliberately does NOT flag `.ring svg` (app.css) -- a raw, non-icon
# progress-donut <svg> with no `class=ico`/sprite `<use>` involved at all -- or
# similar decorative/diagram svg elsewhere; those were never part of the icon
# system and the scale knob was never meant to touch them.
_ICON_SELECTOR_HINT_RE = re.compile(r'\.(ico\b|cr-[\w-]+|crd-[\w-]+|tn-[\w-]+)')


class TestIconScaleWired(unittest.TestCase):
    def test_ico_scale_variable_defined_and_drives_base_rule(self):
        css = _read("app.css")
        self.assertRegex(css, r'--ico-scale\s*:', "--ico-scale is not defined in app.css")

        bodies = [body for sel, body in _css_rules(css)
                  if ".ico" in [p.strip() for p in sel.split(",")]]
        self.assertTrue(bodies, "no base `.ico{...}` rule found in app.css")
        body = bodies[0]
        w = re.search(r'width:\s*([^;]+);', body)
        h = re.search(r'height:\s*([^;]+);', body)
        self.assertIsNotNone(w, "base .ico rule has no width")
        self.assertIn("var(--ico-scale)", w.group(1), "base .ico rule's width doesn't reference --ico-scale")
        self.assertIsNotNone(h, "base .ico rule has no height")
        self.assertIn("var(--ico-scale)", h.group(1), "base .ico rule's height doesn't reference --ico-scale")

    def test_no_icon_svg_rule_hardcodes_a_px_width_without_ico_scale(self):
        offenders = []
        for fn in _web_names(".css"):
            text = _read(fn)
            for sel, body in _css_rules(text):
                for part in (p.strip() for p in sel.split(",")):
                    if part != "svg" and not part.endswith(" svg"):
                        continue
                    if not _ICON_SELECTOR_HINT_RE.search(part):
                        continue
                    if ".cr-rail-brand" in part:
                        continue  # documented exception: the product logo inside the
                                  # CR rail, deliberately unscaled
                    if re.search(r'width:\s*\d+px', body) and "var(--ico-scale)" not in body:
                        offenders.append("%s: `%s { %s }`" % (fn, part, body.strip()))
        self.assertEqual(
            offenders, [],
            "Icon <svg> rule sets a hardcoded px width without var(--ico-scale) -- it "
            "will silently ignore ICON_SCALE:\n" + "\n".join(offenders)
        )


# ============================================================================
# 9. The assembled page carries the style/scale machinery, not just the sprite.
# ============================================================================

class TestBuiltPageCarriesIconConfig(unittest.TestCase):
    def test_build_page_inlines_style_and_scale_machinery(self):
        html = page.build_page()
        self.assertIn("applyIconStyle", html, "assembled page lost applyIconStyle()")
        self.assertIn("--ico-scale", html, "assembled page lost the --ico-scale variable")
        self.assertIn("localStorage.iconStyle", html,
                      "assembled page lost the pre-paint restore of the cached icon style")


if __name__ == "__main__":
    unittest.main()
