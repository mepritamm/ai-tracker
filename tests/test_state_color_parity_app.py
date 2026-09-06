"""Cross-view colour parity between the classic dashboard (app.css) and the control room
(ext_cr.css), for the session-state palette: waiting-on-you, working/live, landed/done,
flagged, failing, pinned.

Classic defines DARK as the default (bare `:root`), LIGHT as the override (`html.light`).
The control room is the other way around: LIGHT is the default (`.tracker-next`), DARK is
the override (`.tracker-next.is-dark`). This file resolves both sides' custom properties
(following `var(--x)` aliases the way a browser would) and asserts the two views land on
the SAME hex per theme -- the parity tests/test_state_colors.py and tests/test_view_parity.py
already established for PINNED, extended here to the other five states plus the two new
control-room-only tokens (--state-working, --glow-working) the sibling board/rail/detail
work consumes.

Idiom: static CSS-source checks against the assembled page (aitracker.page.build_page()),
same as tests/test_state_colors.py -- no node needed, this is pure custom-property text.

Every assertion here is proven load-bearing (not a tautology matching a comment) by rsync'ing
this repo to a throwaway /tmp copy without .git, reverting exactly one colour there, and
confirming the corresponding test goes RED against that copy -- see
scripts/_prove_state_color_parity.sh-equivalent steps recorded in the PR description; this
file itself only needs to pass against the real, fixed worktree.
"""
import re
import unittest

from aitracker.page import build_page


def _style_block(html):
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    assert m, "served page has no <style> block"
    return m.group(1)


def _strip_comments(css):
    """Remove /* ... */ CSS comments before parsing declarations -- several tokens
    below are documented with a comment that itself contains a colon-separated
    prose sentence naming the very token it precedes (e.g. "/* --state-working:
    canonical ... */"), which a comment-blind regex would happily swallow as if it
    were the real declaration, running right past the ';' inside the comment's own
    prose and into the real declaration on the next line."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _extract_declarations(css, selector):
    """Merge every top-level `<selector> { ... }` block's flat `--token: value;`
    declarations into one dict (later occurrences win, matching source-order cascade
    for same-specificity rules). `selector` must match literally (e.g. ':root',
    'html.light', '.tracker-next', '.tracker-next.is-dark') immediately followed by
    optional whitespace and '{' -- this deliberately does NOT match '.tracker-next'
    as a prefix of '.tracker-next.is-dark' (no whitespace-only gap between them), nor
    as a prefix of a descendant selector like '.tracker-next .tn-emo'. `css` must
    already be comment-stripped (see `_strip_comments`)."""
    out = {}
    pattern = re.compile(re.escape(selector) + r"\s*\{")
    pos = 0
    while True:
        m = pattern.search(css, pos)
        if not m:
            break
        start = m.end()
        depth = 1
        i = start
        while depth > 0:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        block = css[start:i - 1]
        # last declaration in a minified block has no trailing ';' before '}', so
        # a value ends at either a ';' or end-of-block.
        for dm in re.finditer(r"(--[\w-]+)\s*:\s*([^;{}]+?)\s*(?:;|$)", block):
            out[dm.group(1)] = dm.group(2).strip()
        pos = i
    return out


def _srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hexcolor):
    hexcolor = hexcolor.lstrip("#")
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def _contrast(hex_a, hex_b):
    """Real WCAG relative-luminance contrast ratio between two OPAQUE hex colours."""
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _parse_color(value):
    """Parse a resolved CSS colour value -- `#rrggbb` or `rgba(r,g,b,a)` -- into
    an (r, g, b, a) float tuple (a=1.0 for a solid hex). Needed because several
    badge backgrounds in this file (--amber-bg/--red-bg/--green-bg) are
    translucent rgba() washes, not solid hex, so a straight `_contrast()` call
    against them would be comparing text to a colour that never actually
    touches the screen on its own -- it has to be composited over whatever
    sits beneath it first (see `_composite` below)."""
    value = value.strip()
    m = re.match(r"^#([0-9a-fA-F]{6})$", value)
    if m:
        h = m.group(1)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return (float(r), float(g), float(b), 1.0)
    m = re.match(r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$",
                 value)
    if m:
        r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (r, g, b, a)
    raise AssertionError("don't know how to parse colour value: %r" % value)


def _composite(fg_value, bg_hex):
    """Alpha-composite a (possibly translucent) `fg_value` colour over a solid
    `bg_hex` backdrop, returning the resulting solid `#rrggbb`. An opaque
    fg_value is returned unchanged (as its own hex)."""
    r, g, b, a = _parse_color(fg_value)
    if a >= 1.0:
        return "#%02x%02x%02x" % (round(r), round(g), round(b))
    bg = bg_hex.lstrip("#")
    br, bgc, bb = (int(bg[i:i + 2], 16) for i in (0, 2, 4))
    cr = r * a + br * (1 - a)
    cg = g * a + bgc * (1 - a)
    cb = b * a + bb * (1 - a)
    return "#%02x%02x%02x" % (round(cr), round(cg), round(cb))


def _resolve(token, table, _seen=None):
    """Resolve a custom property to its literal value, following one level (or
    more) of `var(--other)` aliasing within the SAME table."""
    if _seen is None:
        _seen = set()
    if token in _seen:
        raise AssertionError("cycle resolving " + token)
    _seen.add(token)
    if token not in table:
        raise AssertionError("%s not defined in this theme's table (have: %s)"
                              % (token, sorted(table)))
    val = table[token]
    m = re.match(r"^var\((--[\w-]+)\)$", val)
    if m:
        return _resolve(m.group(1), table, _seen)
    return val


class StateColorParityTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        css = _style_block(build_page())
        stripped = _strip_comments(css)
        # Classic: dark is the bare :root DEFAULT, light is the html.light OVERRIDE.
        cls.app_dark = _extract_declarations(stripped, ":root")
        cls.app_light = _extract_declarations(stripped, "html.light")
        # Control room: light is the bare .tracker-next DEFAULT, dark is the
        # .tracker-next.is-dark OVERRIDE. Inverted defaults vs. classic -- the
        # documented trap this whole file exists to guard against.
        cls.cr_light = _extract_declarations(stripped, ".tracker-next")
        cls.cr_dark = _extract_declarations(stripped, ".tracker-next.is-dark")

    # ---- five states: classic token must resolve to the same hex as the
    # ---- control room's token, per theme ----------------------------------

    STATE_PAIRS = [
        # (label, classic token, control-room token, light hex, dark hex)
        ("waiting-on-you", "--st-awaiting", "--state-awaiting", "#E58F3C", "#E58F3C"),
        ("working/live", "--st-working", "--state-working", "#1C9163", "#29D398"),
        ("landed/done", "--st-landed", "--state-done", "#3B5747", "#8FB187"),
        ("flagged", "--st-flagged", "--state-flagged", "#C27950", "#C27950"),
        ("failing", "--st-failed", "--state-failed", "#C0553A", "#D2735A"),
    ]

    def test_state_hexes_match_between_classic_and_control_room(self):
        for label, classic_tok, cr_tok, light_hex, dark_hex in self.STATE_PAIRS:
            with self.subTest(state=label, theme="light"):
                classic_val = _resolve(classic_tok, self.app_light)
                cr_val = _resolve(cr_tok, self.cr_light)
                self.assertEqual(classic_val.upper(), light_hex.upper(),
                                  "%s light classic token drifted" % label)
                self.assertEqual(cr_val.upper(), light_hex.upper(),
                                  "%s light control-room token drifted" % label)
                self.assertEqual(classic_val.upper(), cr_val.upper(),
                                  "%s light: classic/control-room mismatch" % label)
            with self.subTest(state=label, theme="dark"):
                classic_val = _resolve(classic_tok, self.app_dark)
                cr_val = _resolve(cr_tok, self.cr_dark)
                self.assertEqual(classic_val.upper(), dark_hex.upper(),
                                  "%s dark classic token drifted" % label)
                self.assertEqual(cr_val.upper(), dark_hex.upper(),
                                  "%s dark control-room token drifted" % label)
                self.assertEqual(classic_val.upper(), cr_val.upper(),
                                  "%s dark: classic/control-room mismatch" % label)

    # ---- pinned parity must still hold (pre-existing, guard against regression) ----

    def test_pinned_parity_still_holds(self):
        for theme, app_table, cr_table, expected in (
            ("light", self.app_light, self.cr_light, "#395D6A"),
            ("dark", self.app_dark, self.cr_dark, "#A8C0C9"),
        ):
            with self.subTest(theme=theme):
                classic_val = _resolve("--pin-blue", app_table)
                cr_val = _resolve("--state-pinned", cr_table)
                self.assertEqual(classic_val.upper(), expected.upper())
                self.assertEqual(cr_val.upper(), expected.upper())
                self.assertEqual(classic_val.upper(), cr_val.upper())

    # ---- new control-room-only tokens: must exist in BOTH palettes ----------------

    def test_state_working_defined_in_both_cr_palettes(self):
        self.assertIn("--state-working", self.cr_light)
        self.assertIn("--state-working", self.cr_dark)
        # Light value is #1C9163, not the original #1F9D6B -- that hex measured only 2.82:1
        # against classic's light --side (#efe8d8), below the WCAG 1.4.11 non-text 3:1 floor
        # for a state indicator; #1C9163 (same ~156° hue, darkened) clears it at 3.26:1.
        self.assertEqual(_resolve("--state-working", self.cr_light).upper(), "#1C9163")
        self.assertEqual(_resolve("--state-working", self.cr_dark).upper(), "#29D398")

    def test_state_working_light_clears_contrast_floor_against_classic_side(self):
        """WCAG 1.4.11 non-text contrast floor (3:1) for the working-state indicator against
        classic's light --side (#efe8d8) -- the surface it actually renders on (sidebar dot,
        header ring). The original #1F9D6B measured 2.82:1 here (below the floor); this pins
        the corrected #1C9163 at >=3:1, computed with the real WCAG relative-luminance formula
        (not eyeballed), so a future edit can't silently drift the token back under the floor."""
        working = _resolve("--st-working", self.app_light)
        side = _resolve("--side", self.app_light)
        self.assertEqual(working.upper(), "#1C9163")
        self.assertEqual(side.upper(), "#EFE8D8")
        ratio = _contrast(working, side)
        self.assertGreaterEqual(ratio, 3.0,
                                 "working-state light colour %s only %.2f:1 against --side %s "
                                 "(WCAG 1.4.11 non-text floor is 3:1)" % (working, ratio, side))
        # the old, wrong value must actually fail this same check (proves the assertion is
        # load-bearing, not a tautology -- #1F9D6B really was below the floor)
        old_ratio = _contrast("#1F9D6B", side)
        self.assertLess(old_ratio, 3.0,
                         "sanity check failed: the pre-fix #1F9D6B unexpectedly clears 3:1 "
                         "(%.2f:1) -- the floor-crossing premise for this test is wrong" % old_ratio)

    def test_working_not_confusable_with_landed(self):
        # The regression this change could cause: working is now green too, so it must
        # stay clearly distinct from --state-done/--st-landed's own (muted) green in
        # BOTH themes -- never the same hex, in either the control room or classic.
        for theme, cr_table, app_table in (
            ("light", self.cr_light, self.app_light),
            ("dark", self.cr_dark, self.app_dark),
        ):
            with self.subTest(theme=theme):
                working = _resolve("--state-working", cr_table).upper()
                done = _resolve("--state-done", cr_table).upper()
                self.assertNotEqual(working, done,
                                     "control-room working/landed collide in " + theme)
                st_working = _resolve("--st-working", app_table).upper()
                st_landed = _resolve("--st-landed", app_table).upper()
                self.assertNotEqual(st_working, st_landed,
                                     "classic working/landed collide in " + theme)

    def test_glow_working_defined_in_both_cr_palettes(self):
        self.assertIn("--glow-working", self.cr_light)
        self.assertIn("--glow-working", self.cr_dark)
        # not empty / not a bare copy of --glow-agent-soft's exact string (must be its own,
        # slightly-stronger value per palette, not just an alias hiding a missing definition)
        light_val = self.cr_light["--glow-working"]
        dark_val = self.cr_dark["--glow-working"]
        self.assertTrue(light_val)
        self.assertTrue(dark_val)
        self.assertNotEqual(light_val, self.cr_light.get("--glow-agent-soft"))
        self.assertNotEqual(dark_val, self.cr_dark.get("--glow-agent-soft"))

    def test_glow_working_rgb_matches_state_working_rgb(self):
        """Item 4: the test above only proved --glow-working is non-empty and distinct from
        --glow-agent-soft -- it never checked the embedded rgb triplet actually matches
        --state-working's own hex. That let exactly this drift happen once already: the RGB
        went 31,157,107 -> 28,145,99 when --state-working's hex was corrected, and a test that
        only asserts "non-empty and != --glow-agent-soft" would stay green even if
        --glow-working's rgba() had been left on the OLD triplet. Assert real equality, per
        palette, resolved dynamically (never hardcoded) so a future hex change that forgets to
        update the paired glow goes red here."""
        rgb_re = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*[,)]")
        for theme, table in (("light", self.cr_light), ("dark", self.cr_dark)):
            state_hex = _resolve("--state-working", table).lstrip("#")
            state_rgb = tuple(int(state_hex[i:i + 2], 16) for i in (0, 2, 4))
            glow_val = table["--glow-working"]
            m = rgb_re.search(glow_val)
            self.assertIsNotNone(m, "--glow-working (%s) has no rgba(...) triplet: %r"
                                  % (theme, glow_val))
            glow_rgb = tuple(int(x) for x in m.groups())
            with self.subTest(theme=theme):
                self.assertEqual(glow_rgb, state_rgb,
                                  "--glow-working's embedded rgb %s (%s) doesn't match "
                                  "--state-working's rgb %s (from %s) -- the glow and the dot "
                                  "have drifted apart" % (glow_rgb, glow_val, state_rgb, state_hex))

    def test_st_working_rgb_matches_st_working_hex(self):
        """Same pairing, classic side: app.css's @keyframes pulseDot builds
        rgba(var(--st-working-rgb),alpha) because custom properties can't be computed
        from a hex inside a bare @keyframes rule -- --st-working-rgb has to be hand-kept in
        step with --st-working's own hex. Pin that equality per theme so a future edit to one
        without the other goes red instead of silently pulsing the wrong colour."""
        rgb_re = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$")
        for theme, table in (("light", self.app_light), ("dark", self.app_dark)):
            working_hex = _resolve("--st-working", table).lstrip("#")
            working_rgb = tuple(int(working_hex[i:i + 2], 16) for i in (0, 2, 4))
            rgb_val = table["--st-working-rgb"]
            m = rgb_re.match(rgb_val)
            self.assertIsNotNone(m, "--st-working-rgb (%s) isn't a bare r,g,b triplet: %r"
                                  % (theme, rgb_val))
            pinned_rgb = tuple(int(x) for x in m.groups())
            with self.subTest(theme=theme):
                self.assertEqual(pinned_rgb, working_rgb,
                                  "--st-working-rgb %s doesn't match --st-working's rgb %s "
                                  "(from %s)" % (pinned_rgb, working_rgb, working_hex))

    # ---- classic state consumers must point at the new state tokens, never at the
    # ---- shared --gold/--green/--green2/--red tokens (those still serve non-state UI) ----

    def test_classic_consumers_use_state_tokens_not_shared_tokens(self):
        css = _style_block(build_page())
        self.assertIn(".sitem.waiting{border-left:3px solid var(--st-awaiting);"
                      "background:var(--amber-bg)}", css)
        self.assertIn(".sitem.done{border-left:3px solid var(--st-landed)}", css)
        self.assertIn(".sitem.flagged{border-left:3px solid var(--st-flagged)}", css)
        self.assertIn(".dot.live{background:var(--st-working);animation:pulseDot 1.8s infinite}",
                      css)
        # and never the old shared tokens on these specific rules
        self.assertNotIn(".sitem.waiting{border-left:3px solid var(--gold)", css)
        self.assertNotIn(".sitem.done{border-left:3px solid var(--green2)}", css)
        self.assertNotIn(".sitem.flagged{border-left:3px solid var(--red)}", css)
        self.assertNotIn(".dot.live{background:var(--green);", css)

    def test_shared_tokens_still_used_elsewhere_not_repurposed_away(self):
        # Guards against a blanket-redefine of --gold/--green/--green2/--red themselves
        # (which would repaint unrelated badges/links/mermaid UI). These tokens must still
        # appear on OTHER, non-state rules untouched by this change.
        # NOTE: `.statusbadge.done{color:var(--green2);...}` used to be asserted HERE as
        # correct -- it was actually the item-2 regression this file exists to catch (the
        # badge disagreed with its own row's --st-landed border). See
        # test_row_badges_match_their_own_row_border_dot_family below for the corrected assertion;
        # --green2 itself is still very much alive elsewhere (the ring/chip/todo uses below).
        css = _style_block(build_page())
        self.assertIn(".sitem.agentrow .nm{color:var(--gold)}", css)
        self.assertIn(".flagbadge{", css)
        self.assertIn(".chip.good b{color:var(--green2)}", css)
        self.assertIn(".t-completed .ic{color:var(--green2)}", css)

    def _rule_block(self, css, selector):
        """The declaration text of the first top-level `<selector>{...}` rule."""
        m = re.search(re.escape(selector) + r"\{([^{}]*)\}", css)
        self.assertIsNotNone(m, "rule %r not found" % selector)
        return m.group(1)

    def test_row_badges_match_their_own_row_border_dot_family(self):
        # Item 2 of the (original) adversarial review: each state used to show TWO different
        # colours on the SAME row -- the row's own border-left (repointed to --st-* earlier)
        # disagreed with the badge inside that same row (still on the old shared
        # --green2/--red/--amber tokens). A LATER adversarial pass found that pointing the
        # badge foreground at the exact same --st-* DOT token regressed light-theme text
        # contrast below 4.5:1 (a dot colour is tuned for the 3:1 non-text floor, not text).
        # So border/badge no longer share the identical hex: border stays on the dot token,
        # badge foreground moves to that state's dedicated TEXT variant (--st-*-text) -- this
        # asserts the two are still the same STATE FAMILY (paired, documented tokens) rather
        # than having drifted back to an unrelated shared token like --green2/--red/--amber.
        ROW_BADGE_PAIRS = [
            # (label, row border selector, badge selector, dot token, badge text token)
            ("done", ".sitem.done", ".statusbadge.done", "--st-landed", "--st-landed"),
            ("flagged", ".sitem.flagged", ".flagbadge", "--st-flagged", "--st-flagged-text"),
            ("waiting", ".sitem.waiting", ".statusbadge.waiting", "--st-awaiting", "--st-awaiting-text"),
        ]
        css = _style_block(build_page())
        for label, border_sel, badge_sel, dot_tok, text_tok in ROW_BADGE_PAIRS:
            with self.subTest(state=label):
                border_block = self._rule_block(css, border_sel)
                self.assertIn("border-left:3px solid var(%s)" % dot_tok, border_block,
                              "%s row border isn't on %s" % (label, dot_tok))
                badge_block = self._rule_block(css, badge_sel)
                bm = re.search(r"color:var\((--[\w-]+)\)", badge_block)
                self.assertIsNotNone(bm, "%s badge has no color:var(--...)" % label)
                self.assertEqual(bm.group(1), text_tok,
                                  "%s badge colour token (%s) doesn't match the expected text "
                                  "variant (%s) of its row's dot token (%s)"
                                  % (label, bm.group(1), text_tok, dot_tok))
                # both must actually be defined per theme (test_state_tokens_defined_in_both_
                # classic_theme_blocks covers this generically; re-asserted here so a failure
                # in THIS test names the exact state/token, not just "some token missing").
                for theme, table in (("light", self.app_light), ("dark", self.app_dark)):
                    with self.subTest(state=label, theme=theme):
                        self.assertIn(dot_tok, table)
                        self.assertIn(text_tok, table)

    def test_failbadge_matches_st_failed_text_not_shared_red(self):
        # Item 1: .failbadge was the one classic failing-state consumer still hardcoded to
        # the shared --red (#f85149 dark / #c53d2c light) instead of the failing-state family.
        # It must now use --st-failed-text (the TEXT-on-surface variant -- see the contrast
        # tests below for why not the bare --st-failed dot colour), and must not be --red.
        css = _style_block(build_page())
        block = self._rule_block(css, ".failbadge")
        m = re.search(r"color:var\((--[\w-]+)\)", block)
        self.assertIsNotNone(m, ".failbadge has no color:var(--...)")
        self.assertEqual(m.group(1), "--st-failed-text",
                          ".failbadge colour token is %s, not --st-failed-text" % m.group(1))
        self.assertNotIn("color:var(--red)", block)
        for theme, app_table, cr_table in (
            ("light", self.app_light, self.cr_light),
            ("dark", self.app_dark, self.cr_dark),
        ):
            with self.subTest(theme=theme):
                self.assertEqual(_resolve("--st-failed", app_table),
                                  _resolve("--state-failed", cr_table))

    def test_state_tokens_defined_in_both_classic_theme_blocks(self):
        # A token given its only definition in one theme block silently borrows the other
        # theme's value when that theme is active -- the exact bug class test_state_colors.py
        # already guards against on the control-room side.
        for tok in ("--st-awaiting", "--st-working", "--st-landed", "--st-flagged",
                    "--st-failed", "--st-awaiting-text", "--st-flagged-text",
                    "--st-failed-text"):
            self.assertIn(tok, self.app_light, tok + " missing from classic light theme")
            self.assertIn(tok, self.app_dark, tok + " missing from classic dark theme")

    # ---- ITEM 1 (severe): every badge foreground must clear 4.5:1 against its REAL
    # ---- composited background, in BOTH themes -------------------------------------------

    def test_badge_foregrounds_clear_text_contrast_floor_both_themes(self):
        """The regression this whole item exists to catch: a previous fix pointed badge
        foregrounds at the --st-* DOT colours, which are only tuned for the 3:1 non-text
        floor. Measured against the badges' REAL composited backgrounds (some of them
        rgba() washes, one of them DOUBLE-composited because .sitem.waiting also washes the
        whole row in the same --amber-bg the badge itself repeats), light-theme contrast
        dropped to ~1.6-2.8:1 -- well under the 4.5:1 WCAG text floor. This resolves every
        token dynamically from the assembled CSS (never hardcodes a hex) so it stays
        load-bearing against future edits to any of the tokens involved."""
        for theme, table in (("light", self.app_light), ("dark", self.app_dark)):
            side = _resolve("--side", table)

            # .statusbadge.waiting: DOUBLE-composited -- .sitem.waiting washes the row in
            # --amber-bg, then .statusbadge.waiting washes AGAIN in the same --amber-bg.
            amber_bg = _resolve("--amber-bg", table)
            row_bg = _composite(amber_bg, side)
            waiting_badge_bg = _composite(amber_bg, row_bg)
            waiting_fg = _resolve("--st-awaiting-text", table)
            ratio = _contrast(waiting_fg, waiting_badge_bg)
            with self.subTest(theme=theme, badge="statusbadge.waiting"):
                self.assertGreaterEqual(
                    ratio, 4.5,
                    ".statusbadge.waiting (%s) only %.2f:1 -- fg %s on real bg %s"
                    % (theme, ratio, waiting_fg, waiting_badge_bg))

            # .flagbadge: background is --chipbg, a SOLID hex (not translucent) -- no
            # compositing needed, but still resolved dynamically rather than hardcoded.
            chipbg = _resolve("--chipbg", table)
            flagged_fg = _resolve("--st-flagged-text", table)
            ratio = _contrast(flagged_fg, _composite(chipbg, side))
            with self.subTest(theme=theme, badge="flagbadge"):
                self.assertGreaterEqual(
                    ratio, 4.5,
                    ".flagbadge (%s) only %.2f:1 -- fg %s on bg %s"
                    % (theme, ratio, flagged_fg, chipbg))

            # .failbadge: single-composited -- --red-bg over --side (no row-level wash for
            # a failing state the way .sitem.waiting has one).
            red_bg = _resolve("--red-bg", table)
            fail_badge_bg = _composite(red_bg, side)
            failed_fg = _resolve("--st-failed-text", table)
            ratio = _contrast(failed_fg, fail_badge_bg)
            with self.subTest(theme=theme, badge="failbadge"):
                self.assertGreaterEqual(
                    ratio, 4.5,
                    ".failbadge (%s) only %.2f:1 -- fg %s on real bg %s"
                    % (theme, ratio, failed_fg, fail_badge_bg))

            # .statusbadge.done: single-composited -- --green-bg over --side. Kept on the
            # bare --st-landed dot colour (no separate text token) -- must still clear 4.5:1.
            green_bg = _resolve("--green-bg", table)
            done_badge_bg = _composite(green_bg, side)
            done_fg = _resolve("--st-landed", table)
            ratio = _contrast(done_fg, done_badge_bg)
            with self.subTest(theme=theme, badge="statusbadge.done"):
                self.assertGreaterEqual(
                    ratio, 4.5,
                    ".statusbadge.done (%s) only %.2f:1 -- fg %s on real bg %s"
                    % (theme, ratio, done_fg, done_badge_bg))

    def test_badge_foreground_regression_is_load_bearing(self):
        """Sanity check that the test above is not a tautology: the OLD (regressed) light-theme
        foregrounds -- the bare --st-* dot colours -- really do fail the 4.5:1 floor against
        the same real backgrounds. If this ever stops failing, the premise for the fix (and the
        test above) is wrong."""
        side = _resolve("--side", self.app_light)
        amber_bg = _resolve("--amber-bg", self.app_light)
        row_bg = _composite(amber_bg, side)
        waiting_badge_bg = _composite(amber_bg, row_bg)
        old_waiting_ratio = _contrast(_resolve("--st-awaiting", self.app_light), waiting_badge_bg)
        self.assertLess(old_waiting_ratio, 4.5,
                         "sanity check failed: the pre-fix --st-awaiting dot colour "
                         "unexpectedly clears 4.5:1 (%.2f:1) against the real waiting-badge "
                         "background -- the regression premise is wrong" % old_waiting_ratio)

        chipbg = _resolve("--chipbg", self.app_light)
        old_flagged_ratio = _contrast(_resolve("--st-flagged", self.app_light),
                                       _composite(chipbg, side))
        self.assertLess(old_flagged_ratio, 4.5,
                         "sanity check failed: the pre-fix --st-flagged dot colour "
                         "unexpectedly clears 4.5:1 (%.2f:1) against .flagbadge's real "
                         "background -- the regression premise is wrong" % old_flagged_ratio)

        red_bg = _resolve("--red-bg", self.app_light)
        old_failed_ratio = _contrast(_resolve("--st-failed", self.app_light),
                                      _composite(red_bg, side))
        self.assertLess(old_failed_ratio, 4.5,
                         "sanity check failed: the pre-fix --st-failed dot colour "
                         "unexpectedly clears 4.5:1 (%.2f:1) against .failbadge's real "
                         "background -- the regression premise is wrong" % old_failed_ratio)

    # ---- ITEM 2: .nowbanner.done must use the SAME landed token as the row/badge -----------

    def test_nowbanner_done_uses_landed_token_not_shared_green(self):
        """classic disagreed with ITSELF about "landed": .sitem.done/.statusbadge.done use the
        muted --st-landed, but .nowbanner.done (toggled by the exact same `!live && !d.waiting`
        semantic in app.js) still used the bright, shared --green/--green2 -- one completed
        session showing two different greens on one page."""
        css = _style_block(build_page())
        block = self._rule_block(css, ".nowbanner.done")
        self.assertIn("var(--st-landed)", block,
                      ".nowbanner.done doesn't reference --st-landed at all: %r" % block)
        self.assertNotIn("var(--green)", block,
                         ".nowbanner.done still uses the shared --green: %r" % block)
        self.assertNotIn("var(--green2)", block,
                         ".nowbanner.done still uses the shared --green2: %r" % block)

        dot_block = self._rule_block(css, ".nowbanner.done .dot")
        self.assertIn("background:var(--st-landed)", dot_block)
        self.assertNotIn("var(--green)", dot_block)

        lbl_block = self._rule_block(css, ".nowbanner.done .lbl")
        self.assertIn("color:var(--st-landed)", lbl_block)
        self.assertNotIn("var(--green2)", lbl_block)

    def test_nowbanner_done_lbl_clears_text_contrast_floor(self):
        """.lbl's text sits on the .nowbanner.done gradient background (--green-deep to
        --blue-deep) -- check --st-landed against BOTH gradient endpoints, both themes, since
        the gradient means the real render is somewhere between them."""
        for theme, table in (("light", self.app_light), ("dark", self.app_dark)):
            landed = _resolve("--st-landed", table)
            for end in ("--green-deep", "--blue-deep"):
                bg = _resolve(end, table)
                ratio = _contrast(landed, bg)
                with self.subTest(theme=theme, gradient_end=end):
                    self.assertGreaterEqual(
                        ratio, 4.5,
                        ".nowbanner.done .lbl (%s) only %.2f:1 against gradient end %s (%s)"
                        % (theme, ratio, end, bg))


if __name__ == "__main__":
    unittest.main()
