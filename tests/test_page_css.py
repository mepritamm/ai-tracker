"""Regression test: the assembled page's CSS is syntactically valid and complete.

When aitracker/page.py's build_page() inlines app.css plus every ext_*.css into
ONE <style> block, a CSS syntax error (particularly an unclosed comment or a
stray comment terminator like -`*`/ inside a token list) silently kills every rule
AFTER it in that block, blanking entire views. This test catches four classes of errors:

1. PREMATURE-COMMENT-TERMINATORS: a sequence like `--surface-*/` (the telltale of
   a token list accidentally closing a CSS comment).
2. UNBALANCED-COMMENTS: a `/*` without a matching `*/` or vice versa, or nesting
   that goes negative (stray `*/` outside a comment).
3. UNBALANCED-BRACES: `{` and `}` counts do not match (per-file granularity).
4. MISSING-SELECTORS: a CSS rule from a source file did not survive to the
   assembled output (indicating an earlier parse error swallowed it).
"""
import os
import re
import unittest

_AITRACKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker")
_WEB = os.path.join(_AITRACKER, "web")


def _read_page():
    """Import and run build_page() to get the assembled HTML."""
    import sys
    sys.path.insert(0, os.path.dirname(_AITRACKER))
    from aitracker import page
    return page.build_page()


def _extract_style_content(html):
    """Extract the text inside the <style>...</style> HTML tag."""
    # Match <style>...</style>, handling DOTALL to span newlines.
    style_pattern = re.compile(r'<style>(.*?)</style>', re.DOTALL)
    match = style_pattern.search(html)

    if not match:
        raise ValueError("No <style> tag found in assembled page")

    return match.group(1)


def _strip_css_comments_and_strings(css):
    """Remove CSS comments and quoted strings, returning only structural content.

    This is a simple stripper, not a full CSS parser. It processes input
    sequentially:
      - Strips /* ... */ comments.
      - Strips quoted strings (both single and double quotes).
      - Handles escaped quotes inside strings.

    Limitations:
      - Does NOT handle @supports() or other CSS structures with `{` in values.
      - If CSS uses /* */ inside a string literal (rare), it will not handle that.

    For the purpose of this test, counting braces in the result is reliable
    because we only care about structural braces, not braces in string content.
    """
    result = []
    i = 0
    while i < len(css):
        # Check for comment start.
        if i + 1 < len(css) and css[i:i+2] == '/*':
            # Find comment end.
            end = css.find('*/', i + 2)
            if end != -1:
                i = end + 2
            else:
                # Unclosed comment; skip to end of input.
                i = len(css)
            continue

        # Check for string start (double quote).
        if css[i] == '"':
            result.append(' ')  # Replace string with space to preserve offsets approximately.
            i += 1
            while i < len(css):
                if css[i] == '\\':
                    i += 2  # Skip escaped character.
                elif css[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue

        # Check for string start (single quote).
        if css[i] == "'":
            result.append(' ')
            i += 1
            while i < len(css):
                if css[i] == '\\':
                    i += 2  # Skip escaped character.
                elif css[i] == "'":
                    i += 1
                    break
                else:
                    i += 1
            continue

        # Regular character.
        result.append(css[i])
        i += 1

    return ''.join(result)


def _extract_selector_from_file(filepath):
    """Extract a distinctive class selector from a CSS file for validation.

    Scans the file for the first occurrence of a rule starting with a `.` (class
    selector) and returns just the selector text (up to the `{`).
    """
    with open(filepath, encoding='utf-8') as fh:
        content = fh.read()

    # Find the first class selector rule (lines starting with .).
    # Pattern: optional whitespace, then `.`, then non-whitespace chars, then whitespace, then `{`.
    pattern = re.compile(r'^\s*(\.[^{]+?)\s*\{', re.MULTILINE)
    match = pattern.search(content)

    if match:
        return match.group(1).strip()
    return None


def _extract_media_blocks(css, query_substr):
    """Return the body text of every top-level `@media (...)` block whose
    condition contains `query_substr` (e.g. "max-width: 480px").

    Not a full CSS parser: only matches simple single-condition media
    queries (`@media (COND) {`), which is what this codebase uses for every
    breakpoint. Brace-depth is tracked manually so a block's own nested
    rules don't truncate the match early.
    """
    blocks = []
    for m in re.finditer(r'@media\s*\(([^)]*)\)\s*\{', css):
        if query_substr not in m.group(1):
            continue
        start = m.end()
        depth = 1
        i = start
        while i < len(css) and depth > 0:
            if css[i] == '{':
                depth += 1
            elif css[i] == '}':
                depth -= 1
            i += 1
        blocks.append(css[start:i - 1])
    return blocks


class TestPageCSS(unittest.TestCase):
    """Test that the assembled page's CSS is syntactically valid and complete."""

    def test_no_premature_comment_terminators(self):
        """Detect `-*/` sequences that would close a comment prematurely.

        The telltale of this bug is the presence of `--*` followed immediately
        by `/` (e.g., `--surface-*/` inside a comment), which terminates the
        comment early and silently breaks all subsequent rules.

        This test:
          1. Builds the page and extracts the assembled CSS.
          2. Scans for the `-*/` sequence.
          3. Also scans each source *.css file individually to pinpoint the
             offender.
        """
        html = _read_page()
        assembled_css = _extract_style_content(html)

        # Check for premature terminators in the assembled CSS.
        if '-*/' in assembled_css:
            # Find the offending file by scanning sources.
            offenders = []
            for name in sorted(os.listdir(_WEB)):
                if not name.endswith('.css'):
                    continue
                path = os.path.join(_WEB, name)
                with open(path, encoding='utf-8') as fh:
                    content = fh.read()
                if '-*/' in content:
                    # Find the line number.
                    for line_num, line in enumerate(content.split('\n'), 1):
                        if '-*/' in line:
                            offenders.append(f"{name}:{line_num}: {line.strip()}")

            self.fail(
                "Found premature comment terminators (-*/) that would close CSS "
                "comments early and break all subsequent rules:\n" +
                "\n".join(f"  {o}" for o in offenders)
            )

    def test_comments_are_balanced(self):
        """Verify every `/*` has a matching `*/` and nesting never goes negative."""
        html = _read_page()
        assembled_css = _extract_style_content(html)

        # Walk through the CSS and count comment open/close.
        depth = 0
        i = 0
        while i < len(assembled_css):
            if i + 1 < len(assembled_css) and assembled_css[i:i+2] == '/*':
                depth += 1
                i += 2
            elif i + 1 < len(assembled_css) and assembled_css[i:i+2] == '*/':
                depth -= 1
                if depth < 0:
                    context_start = max(0, i - 40)
                    context = assembled_css[context_start:i+20]
                    self.fail(
                        f"Stray `*/` found (no matching `/*` before it) at offset {i}. "
                        f"Context: ...{context}..."
                    )
                i += 2
            else:
                i += 1

        self.assertEqual(
            depth, 0,
            f"Unbalanced CSS comments: {depth} more `/*` than `*/` "
            f"(unclosed comment)"
        )

    def test_braces_balanced(self):
        """Verify `{` and `}` counts match in the assembled CSS and per-file."""
        html = _read_page()
        assembled_css = _extract_style_content(html)

        # Strip comments and strings so we only count structural braces.
        clean_css = _strip_css_comments_and_strings(assembled_css)

        open_count = clean_css.count('{')
        close_count = clean_css.count('}')

        self.assertEqual(
            open_count, close_count,
            f"Unbalanced braces in assembled CSS: {open_count} `{{` vs {close_count} `}}`"
        )

        # Also check each source file individually.
        failed_files = []
        for name in sorted(os.listdir(_WEB)):
            if not name.endswith('.css'):
                continue
            path = os.path.join(_WEB, name)
            with open(path, encoding='utf-8') as fh:
                content = fh.read()

            clean = _strip_css_comments_and_strings(content)
            o_count = clean.count('{')
            c_count = clean.count('}')

            if o_count != c_count:
                failed_files.append(f"{name}: {o_count} `{{` vs {c_count} `}}`")

        self.assertEqual(
            failed_files, [],
            f"Unbalanced braces in source files:\n" +
            "\n".join(f"  {f}" for f in failed_files)
        )

    def test_expected_selectors_survive(self):
        """Assert selectors from each ext_cr_*.css file appear in assembled CSS.

        This is the regression guard: if an upstream CSS syntax error swallows a
        later file's rules, this test catches it. For each ext_cr_*.css file, we
        extract a distinctive class selector and verify it appears in the
        assembled <style> block.

        Discovery is dynamic: the test globs for ext_cr_*.css files, so it works
        as files are added without requiring a hardcoded selector list that rots.
        """
        html = _read_page()
        assembled_css = _extract_style_content(html)

        missing = []
        for name in sorted(os.listdir(_WEB)):
            if not (name.startswith('ext_cr_') and name.endswith('.css')):
                continue

            path = os.path.join(_WEB, name)
            selector = _extract_selector_from_file(path)

            if selector is None:
                # File has no class selectors; skip it.
                continue

            # Verify the selector appears in the assembled CSS.
            # (We search the raw assembled CSS, not the stripped version, so we
            # catch cases where the selector is in a comment due to parse errors.)
            if selector not in assembled_css:
                missing.append(f"{name}: selector `{selector}` not found in assembled CSS")

        self.assertEqual(
            missing, [],
            f"Selectors from ext_cr_*.css files are missing from assembled CSS. "
            f"This indicates an upstream CSS syntax error broke the file parsing. "
            f"Missing:\n" +
            "\n".join(f"  {m}" for m in missing)
        )

    def test_timeline_chip_row_has_phone_escape(self):
        """The detail view's TIMELINE chip row must not clip at phone width.

        `.crd-timeline-filters` (prompts/narration/tools/results + all/talk
        only + the pop-out button, 7 controls) is a `display:flex` group
        with no `flex-wrap` of its own. Unwrapped, it runs ~437px wide --
        wider than the ~336px of usable width a 390px phone column leaves
        after `.crd-columns` and `.crd-panel-head` padding -- so without an
        escape hatch the rightmost chips become unreachable: the exact
        top-bar defect this project already shipped once, recurring here.

        Pins the fix to the phone tier specifically (inside a
        `max-width: 480px` block, not merely present somewhere in the file)
        so a future edit that drops `flex-wrap` or moves the rule out of
        that breakpoint regresses this test instead of shipping silently.
        """
        html = _read_page()
        assembled_css = _extract_style_content(html)

        phone_blocks = _extract_media_blocks(assembled_css, "max-width: 480px")
        self.assertTrue(
            phone_blocks,
            "No `@media (max-width: 480px)` block found in assembled CSS"
        )

        escaped = False
        for block in phone_blocks:
            rule_match = re.search(r'\.cr\s+\.crd-timeline-filters\s*\{([^}]*)\}', block)
            if rule_match and re.search(r'flex-wrap\s*:\s*wrap', rule_match.group(1)):
                escaped = True
                break

        self.assertTrue(
            escaped,
            "`.cr .crd-timeline-filters` has no `flex-wrap: wrap` inside a "
            "`max-width: 480px` block -- the timeline chip row can overflow "
            "unreachably on phone."
        )


if __name__ == "__main__":
    unittest.main()
