#!/usr/bin/env python3
"""Behavioural evals for the mermaid → SVG renderer in web/app.js.

The renderer is client-side JS, so these run the *real* app.js under node with a
stub DOM and assert on what mermaidSvg()/mdBlock() actually produce. node isn't a
project dependency — if it's absent the module skips (the page-level assertions in
test_integration.py still pin that the renderer is served)."""
import json
import os
import shutil
import subprocess
import unittest

APP_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "aitracker", "web", "app.js")
NODE = shutil.which("node")

# Minimal browser stubs: app.js runs `start()` at load and touches the DOM/location.
_HARNESS = r"""
const fs=require("fs");
const stub=()=>new Proxy(function(){},{get:(t,k)=>k===Symbol.toPrimitive?()=>"":stub(),set:()=>true,apply:()=>stub()});
globalThis.document={documentElement:{classList:{contains:()=>false,toggle:()=>{}}},
  getElementById:()=>stub(),addEventListener:()=>{},querySelectorAll:()=>[],querySelector:()=>stub()};
globalThis.localStorage={getItem:()=>null,setItem:()=>{}};
globalThis.location={host:"localhost:8787",href:"http://localhost:8787/"};
globalThis.addEventListener=()=>{};
globalThis.fetch=()=>new Promise(()=>{});
globalThis.window=globalThis;
try{ (0,eval)(fs.readFileSync(process.argv[2],"utf8")); }catch(e){ console.error("load:",e.message); }
const src=fs.readFileSync(process.argv[3],"utf8");
const out=(process.argv[4]==="mdBlock"?mdBlock(src):mermaidSvg(src));
process.stdout.write(JSON.stringify(out===null||out===undefined?null:out));
"""


def _js(src, fn="mermaidSvg"):
    """Run app.js's `fn` over `src` in node; returns the string result (or None)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        h, s = os.path.join(d, "h.js"), os.path.join(d, "in.mmd")
        with open(h, "w") as f:
            f.write(_HARNESS)
        with open(s, "w") as f:
            f.write(src)
        r = subprocess.run([NODE, h, APP_JS, s, fn], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        assert "load:" not in r.stderr, r.stderr          # app.js must evaluate cleanly
        return json.loads(r.stdout or "null")


FLOW = """flowchart TD
    U["Advisor utterance<br/>'add contact ZZ Plate'"]
    U --> STRIP["_strip_household_id_ref"]
    STRIP --> EX[<b>FieldExtractor.analyze</b>]
    EX -->|"phone = '12345678'"| ARB
    ARB{arbitrate<br/>per field}
    ARB -->|parser BOUND| R1[bind the parsed value]
    R1 --> OUT(("staged args"))
    classDef fix fill:#14532d,stroke:#22c55e,color:#fff
    class R1 fix
"""


@unittest.skipUnless(NODE, "node not installed — JS evals skipped")
class TestMermaidRender(unittest.TestCase):
    def test_flowchart_becomes_svg_with_every_node_and_edge(self):
        s = _js(FLOW)
        self.assertIsNotNone(s)
        self.assertTrue(s.startswith("<svg"), s[:60])
        for label in ("Advisor utterance", "_strip_household_id_ref", "FieldExtractor.analyze",
                      "arbitrate", "per field", "bind the parsed value", "staged args"):
            self.assertIn(label, s, label)
        self.assertIn("parser BOUND", s)                     # edge label drawn
        self.assertIn("phone = '12345678'", s)
        self.assertEqual(5, s.count('marker-end="url(#mmdarrow)"'))  # one head per arrow
        self.assertIn("<defs>", s)

    def test_html_in_labels_is_structure_not_markup(self):
        s = _js(FLOW)
        self.assertNotIn("<b>", s)                           # <b>/<i> stripped, not emitted
        self.assertIn(">FieldExtractor.analyze<", s)
        # <br/> splits one node label into two <text> lines rather than a literal "<br/>"
        self.assertNotIn("br/", s)
        self.assertIn(">Advisor utterance<", s)
        self.assertIn(">'add contact ZZ Plate'<", s)         # …and the wrapping quotes are stripped

    def test_classdef_colours_reach_the_node_they_were_assigned(self):
        s = _js(FLOW)
        # inline style, not fill=: the .mmdn stylesheet rule outranks a presentation attribute
        self.assertIn('style="fill:#14532d;stroke:#22c55e;"', s)   # class fix → R1's rect
        self.assertIn('style="fill:#fff"', s)                      # …and its text colour
        self.assertEqual(1, s.count("fill:#14532d"))               # only the assigned node

    def test_label_text_is_escaped(self):
        s = _js('flowchart TD\n  A["<script>alert(1)</script> & co"] --> B')
        self.assertIsNotNone(s)
        self.assertNotIn("<script>", s)
        self.assertIn("&amp; co", s)

    def test_direction_lr_lays_out_horizontally(self):
        td = _js("flowchart TD\n A[one] --> B[two]")
        lr = _js("flowchart LR\n A[one] --> B[two]")
        self.assertIsNotNone(td)
        self.assertIsNotNone(lr)
        vb = lambda s: [float(x) for x in s.split('viewBox="0 0 ', 1)[1].split('"', 1)[0].split()]
        tw, th = vb(td)
        lw, lh = vb(lr)
        self.assertGreater(th, tw)          # TD stacks: taller than wide
        self.assertGreater(lw, lh)          # LR flows: wider than tall

    def test_unsupported_diagram_types_return_null(self):
        # sequenceDiagram used to sit here — it now has its own renderer (TestSequenceDiagram).
        for src in ("pie title X\n  \"a\": 5", "gantt\n  title x",
                    "erDiagram\n  A ||--o{ B : has", "", "just some prose"):
            self.assertIsNone(_js(src), src[:20])

    def test_malformed_input_never_throws(self):
        for src in ("flowchart TD", "flowchart TD\n  -->", "flowchart TD\n  A[unclosed --> B",
                    "flowchart TD\n  A --> B --> C --> A", "graph\n  A-->B"):
            _js(src)     # a throw surfaces as a non-zero exit / load: error in _js

    def test_cycles_terminate(self):
        s = _js("flowchart LR\n A --> B\n B --> C\n C --> A")
        self.assertIsNotNone(s)
        for n in ("A", "B", "C"):
            self.assertIn(">%s<" % n, s)


@unittest.skipUnless(NODE, "node not installed — JS evals skipped")
class TestMdBlockFences(unittest.TestCase):
    """The capability lands on mdBlock — the one fenced-markdown seam every surface
    (narration, todos, requests, notes, agent/shell output, .md file view) renders through."""

    def test_mermaid_fence_renders_a_diagram(self):
        h = _js("intro\n\n```mermaid\nflowchart TD\n  A[one] --> B[two]\n```\n\nafter", fn="mdBlock")
        self.assertIn("<div class=mmd><svg", h)
        self.assertNotIn("mdpre", h)                    # replaced the code block, not added to it
        self.assertIn("<p class=mdp>intro</p>", h)      # surrounding markdown still renders
        self.assertIn("after", h)

    def test_other_fences_are_untouched_code_blocks(self):
        h = _js("```python\nprint('hi')\n```", fn="mdBlock")
        self.assertIn("class=mdpre", h)
        self.assertIn("codecopy", h)
        self.assertNotIn("class=mmd>", h)

    def test_unsupported_mermaid_falls_back_to_the_source(self):
        # `gantt` isn't supported; the fence stays a readable code block instead of vanishing.
        h = _js("```mermaid\ngantt\n  title x\n```", fn="mdBlock")
        self.assertNotIn("<svg", h)
        self.assertIn("class=mdpre", h)                 # you still get to read the diagram source
        self.assertIn("gantt", h)

    def test_sequence_fence_renders_a_diagram(self):
        h = _js("intro\n\n```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n\nafter", fn="mdBlock")
        self.assertIn("<div class=mmd><svg", h)
        self.assertNotIn("mdpre", h)                    # the fence became a diagram, not a code block
        self.assertIn("<p class=mdp>intro</p>", h)      # surrounding markdown still renders
        self.assertIn(">A<", h)
        self.assertIn(">B<", h)
        self.assertIn(">hi<", h)


# ---- Sequence-diagram renderer (_mermaidSeqSvg): the sibling that lets `sequenceDiagram`
# fences render inline instead of falling through to code. Same shared seam (mermaidSvg) —
# mdBlock dispatches by diagram type, so every markdown surface (narration, notes, .md view,
# agent/shell output) inherits both flowchart AND sequence support without a second wiring.
SEQ = """sequenceDiagram
    participant C as Caller (BFF)
    participant G as graph_run_turn
    participant CP as Checkpointer
    C->>G: utterance + thread_id
    G->>G: state = {utterance}
    Note over G: usage=None resets accumulator
    G->>CP: get_state(config)
    alt first turn of this thread
      CP-->>G: empty
      G->>G: seed SessionContext
    else existing thread
      CP-->>G: restores SessionContext
    end
    G-->>C: TurnTrace
"""


@unittest.skipUnless(NODE, "node not installed — JS evals skipped")
class TestSequenceDiagram(unittest.TestCase):
    def test_renders_svg_with_every_participant_and_message(self):
        s = _js(SEQ)
        self.assertIsNotNone(s)
        self.assertTrue(s.startswith("<svg"), s[:60])
        self.assertIn('aria-label="sequence diagram"', s)
        # participants are drawn top AND bottom (mirror) — exactly twice each, using the `as` label
        for lab in ("Caller (BFF)", "graph_run_turn", "Checkpointer"):
            self.assertEqual(2, s.count(">%s<" % lab), lab)
        # every message text present
        for t in ("utterance + thread_id", "state = {utterance}", "get_state(config)",
                  "empty", "seed SessionContext", "restores SessionContext", "TurnTrace"):
            self.assertIn(t, s)
        self.assertIn("<defs>", s)

    def test_message_arrow_kinds_map_to_the_right_marker(self):
        # ->> is a filled solid arrow (mmsarrow); -->> is filled dashed
        s = _js("sequenceDiagram\n A->>B: req\n B-->>A: resp")
        self.assertIsNotNone(s)
        self.assertIn("mmsm dash", s)                            # the return arrow is dashed
        self.assertEqual(2, s.count('marker-end="url(#mmsarrow)"'))  # both use the filled head
        # -x is the terminator "x"; -) is async open-arc
        s2 = _js("sequenceDiagram\n A-xB: lost\n A-)B: async")
        self.assertIsNotNone(s2)
        self.assertIn('marker-end="url(#mmsarrowx)"', s2)
        self.assertIn('marker-end="url(#mmsarrowc)"', s2)

    def test_note_over_becomes_a_yellow_note_box(self):
        s = _js(SEQ)
        self.assertIn("class=mmsnote", s)
        self.assertIn("usage=None resets accumulator", s)

    def test_note_scopes_left_and_right_of(self):
        s = _js("sequenceDiagram\n participant A\n Note left of A: L\n Note right of A: R")
        self.assertIsNotNone(s)
        self.assertEqual(2, s.count("class=mmsnote"))
        self.assertIn(">L<", s)
        self.assertIn(">R<", s)

    def test_alt_block_renders_with_title_tab_and_else_divider(self):
        s = _js(SEQ)
        self.assertIn('class="mmsblk d0"', s)                    # depth-0 block box
        self.assertIn("ALT", s)                                   # kind uppercased in the tab
        self.assertIn("first turn of this thread", s)             # its condition preserved
        self.assertIn("class=mmsblkls", s)                        # the else divider
        self.assertIn("ELSE  existing thread", s)                 # else's condition preserved

    def test_self_message_uses_a_bracket_path_not_a_line(self):
        s = _js("sequenceDiagram\n A->>A: recurse")
        self.assertIsNotNone(s)
        self.assertIn('<path class="mmsm"', s)                    # self-loop is a path
        self.assertIn(">recurse<", s)

    def test_participants_are_auto_declared_on_first_use(self):
        s = _js("sequenceDiagram\n A->>B: hi")
        self.assertIsNotNone(s)
        self.assertEqual(2, s.count(">A<"))                       # header + footer
        self.assertEqual(2, s.count(">B<"))

    def test_message_text_is_escaped(self):
        s = _js("sequenceDiagram\n A->>B: <script>alert(1)</script> & co")
        self.assertIsNotNone(s)
        self.assertNotIn("<script>", s)
        self.assertIn("&amp; co", s)

    def test_lifelines_span_every_participant(self):
        s = _js(SEQ)
        # one dashed lifeline per participant column (C, G, CP)
        self.assertEqual(3, s.count("class=mmsll"))

    def test_nested_blocks_get_distinct_depth_classes(self):
        s = _js("sequenceDiagram\n A->>B: x\n opt outer\n loop inner\n A->>B: y\n end\n end")
        self.assertIsNotNone(s)
        self.assertIn('class="mmsblk d0"', s)   # outer opt
        self.assertIn('class="mmsblk d1"', s)   # inner loop

    def test_autonumber_and_activate_are_ignored_not_fatal(self):
        s = _js("sequenceDiagram\n autonumber\n activate A\n A->>B: x\n deactivate A")
        self.assertIsNotNone(s)
        self.assertIn(">x<", s)

    def test_malformed_input_never_throws(self):
        for src in ("sequenceDiagram", "sequenceDiagram\n foo bar baz",
                    "sequenceDiagram\n A->>",  "sequenceDiagram\n Note over : empty",
                    "sequenceDiagram\n alt\n end\n end",  "sequenceDiagram\n end\n end",
                    "sequenceDiagram\n loop", "sequenceDiagram\n participant"):
            _js(src)                     # a throw surfaces as a non-zero exit / load: error


if __name__ == "__main__":
    unittest.main()
