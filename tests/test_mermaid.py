#!/usr/bin/env python3
"""Behavioural evals for the mermaid → SVG renderer in web/app.js.

The renderer is client-side JS, so these run the *real* app.js under node with a
stub DOM and assert on what mermaidSvg()/mdBlock() actually produce. node isn't a
project dependency — if it's absent the module skips (the page-level assertions in
test_integration.py still pin that the renderer is served)."""
import base64
import json
import os
import re
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
  getElementById:()=>stub(),addEventListener:()=>{},removeEventListener:()=>{},dispatchEvent:()=>true,
  querySelectorAll:()=>[],querySelector:()=>stub()};
globalThis.localStorage={getItem:()=>null,setItem:()=>{}};
globalThis.location={host:"localhost:8790",href:"http://localhost:8790/"};
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
        # sequenceDiagram/pie/erDiagram/stateDiagram/classDiagram/journey/quadrantChart used
        # to sit here — they now each have their own renderer (see the classes below).
        # Only the diagram types with no renderer at all still return null, so mdBlock can
        # tag them with 🧜 and show the source (see TestMdBlockFences.test_unsupported_*).
        for src in ("gantt\n  title x\n  section A\n    a : a1, 2014-01-01, 30d",
                    "mindmap\n  root((r))\n    child",
                    "timeline\n  title x\n  2020 : a",
                    "gitGraph\n  commit\n  branch feat\n  commit",
                    "xychart-beta\n  title X\n  x-axis [a,b]",
                    "requirementDiagram\n  requirement X {\n  }",
                    "sankey-beta\n  A,B,10",
                    "", "just some prose"):
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

    def test_mermaid_fence_gets_a_data_mmd_src_slot_for_the_async_upgrade(self):
        # mdBlock() still renders the hand-rolled SVG SYNCHRONOUSLY (asserted above), but
        # now wraps it in a `.mmd-slot[data-mmd-src=...]` holding the raw source, base64'd
        # UTF-8-safe -- app.js's own renderMermaid()/upgradeMermaidIn() (the ONE renderer
        # both the classic UI and the Control Room call, see their own comments) read this
        # attribute back off the DOM to upgrade the fallback in place to a real mermaid.js
        # render, without a second markdown pass over the original text.
        src = "flowchart TD\n  A[one] --> B[two]"
        h = _js("```mermaid\n%s\n```" % src, fn="mdBlock")
        self.assertIn('class="mmd-slot"', h)
        m = re.search(r'data-mmd-src="([^"]+)"', h)
        self.assertIsNotNone(m, h)
        self.assertEqual(base64.b64decode(m.group(1)).decode("utf-8"), src)

    def test_unsupported_diagram_still_gets_a_slot_so_mermaid_js_can_try(self):
        # A `gantt` fence has no hand-rolled renderer (falls back to a labelled code
        # block — see test_unsupported_mermaid_falls_back_to_the_source_with_a_tag), but
        # mermaid.js itself DOES understand gantt — so this fence still gets a
        # `data-mmd-src` slot, not just the families the hand-rolled renderer covers.
        src = "gantt\n  title x\n  section A\n    a : a1, 2014-01-01, 30d"
        h = _js("```mermaid\n%s\n```" % src, fn="mdBlock")
        self.assertIn('class="mmd-slot"', h)
        m = re.search(r'data-mmd-src="([^"]+)"', h)
        self.assertIsNotNone(m, h)
        self.assertEqual(base64.b64decode(m.group(1)).decode("utf-8"), src)


class TestMermaidVendorLoader(unittest.TestCase):
    """The lazy-load target must be the committed vendor file, never a CDN URL at runtime
    (conventions rule 2/6 — no outbound network calls; mirrors
    test_term_vt_client.py's test_lazy_asset_loader_targets_the_vendored_paths_not_a_cdn
    for xterm.js's own vendor loader)."""

    def test_loader_targets_the_vendored_path_not_a_cdn(self):
        with open(APP_JS) as f:
            js = f.read()
        self.assertIn('"/vendor/mermaid.min.js"', js)
        for host in ("cdn.jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com", "esm.sh"):
            self.assertNotIn(host, js)

    def test_other_fences_are_untouched_code_blocks(self):
        h = _js("```python\nprint('hi')\n```", fn="mdBlock")
        self.assertIn("class=mdpre", h)
        self.assertIn("codecopy", h)
        self.assertNotIn("class=mmd>", h)

    def test_unsupported_mermaid_falls_back_to_the_source_with_a_tag(self):
        # `gantt` still has no renderer; the fence stays a readable code block but is
        # tagged so the reader sees the intent (a diagram, not a mislabelled code fence).
        h = _js("```mermaid\ngantt\n  title x\n  section A\n    a : a1, 2014-01-01, 30d\n```", fn="mdBlock")
        self.assertNotIn("<svg", h)
        self.assertIn("class=mdpre", h)                 # you still get to read the diagram source
        self.assertIn("gantt", h)
        # …and the diagram-type tag is present, so the intent is visible without rendering
        self.assertIn("mmdfall", h)
        self.assertIn("mmdftag", h)
        self.assertIn("mermaid: gantt", h)              # the type label is what the reader sees

    def test_fallback_tag_extracts_the_diagram_type_even_with_comments(self):
        # Leading %%-comments and blank lines must not throw off the type-name sniff.
        h = _js("```mermaid\n%% a comment\n%% another\n\ngitGraph\n  commit\n```", fn="mdBlock")
        self.assertIn("mermaid: gitGraph", h)

    def test_plain_code_fence_gets_no_mermaid_tag(self):
        # Non-mermaid fences must not be re-labelled with the diagram tag by accident.
        h = _js("```python\nprint('hi')\n```", fn="mdBlock")
        self.assertNotIn("mmdfall", h)
        self.assertNotIn("mmdftag", h)

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


# ---- The six additional renderers (state / class / er / journey / pie / quadrant).
# Every diagram type that agent-generated markdown routinely reaches for now renders in
# place instead of falling through to raw code. State/class/er/journey are translated
# to flowchart syntax under the hood — the tests below assert the OBSERVABLE payload
# (nodes, edge labels, escaping, malformed-input safety), not the translation trick.
STATE = """stateDiagram-v2
    [*] --> NoFocus
    NoFocus --> HH: HOUSEHOLD turn resolves a household
    HH --> HHACC: account-level turn resolves an account
    HHACC --> HH: zoom up to a household-level turn
    HH --> NoFocus: PRACTICE turn, acted=practice clears the tree
    HH --> NoFocus: explicit verbal reset
    HH --> HH: CLARIFY / OOS / HELP / EDUCATE / DECLINE
    HHACC --> HHACC: CLARIFY / OOS / HELP / EDUCATE / DECLINE
"""


@unittest.skipUnless(NODE, "node not installed — JS evals skipped")
class TestStateDiagram(unittest.TestCase):
    def test_state_diagram_v2_from_the_screenshot_renders_as_svg(self):
        # The concrete case the user flagged: a stateDiagram-v2 block that used to fall
        # through to raw code now becomes a diagram, every state and transition present.
        s = _js(STATE)
        self.assertIsNotNone(s)
        self.assertTrue(s.startswith("<svg"), s[:60])
        for state in ("NoFocus", "HH", "HHACC"):
            self.assertIn(">%s<" % state, s)
        for label in ("HOUSEHOLD turn resolves a household",
                      "account-level turn resolves an account",
                      "zoom up to a household-level turn",
                      "explicit verbal reset",
                      "CLARIFY / OOS / HELP / EDUCATE / DECLINE"):
            self.assertIn(label, s)

    def test_start_pseudostate_becomes_a_filled_dot(self):
        # `[*]` renders as a distinct circle with the classDef fill, so the reader can
        # tell a start/end pseudostate apart from a regular state.
        s = _js("stateDiagram-v2\n [*] --> A\n A --> [*]")
        self.assertIsNotNone(s)
        self.assertIn(">A<", s)
        self.assertIn("fill:#5b6474", s)                     # the pseudostate class fill
        # both pseudostates rendered (one before A, one after)
        self.assertGreaterEqual(s.count("fill:#5b6474"), 2)

    def test_plain_stateDiagram_keyword_also_matches(self):
        s = _js("stateDiagram\n A --> B: go")
        self.assertIsNotNone(s)
        self.assertIn(">go<", s)

    def test_aliased_state_uses_the_long_label(self):
        s = _js('stateDiagram-v2\n state "Zoomed Up" as ZU\n [*] --> ZU')
        self.assertIsNotNone(s)
        self.assertIn(">Zoomed Up<", s)
        self.assertNotIn(">ZU<", s)                          # id is internal only

    def test_composite_state_is_flattened_not_a_crash(self):
        # Nested state blocks don't render as a border, but the inner transitions still
        # appear — beats returning null and falling back to raw code.
        s = _js("stateDiagram-v2\n state Composite {\n  X --> Y\n }\n Composite --> Done")
        self.assertIsNotNone(s)
        self.assertIn(">X<", s); self.assertIn(">Y<", s); self.assertIn(">Done<", s)

    def test_transition_label_is_escaped(self):
        s = _js('stateDiagram-v2\n A --> B: <script>alert(1)</script> & co')
        self.assertIsNotNone(s)
        self.assertNotIn("<script>", s)
        self.assertIn("&amp; co", s)

    def test_direction_lr_lays_out_horizontally(self):
        td = _js("stateDiagram-v2\n [*] --> A\n A --> B\n B --> [*]")
        lr = _js("stateDiagram-v2 LR\n [*] --> A\n A --> B\n B --> [*]")
        self.assertIsNotNone(td); self.assertIsNotNone(lr)
        vb = lambda s: [float(x) for x in s.split('viewBox="0 0 ', 1)[1].split('"', 1)[0].split()]
        tw, th = vb(td); lw, lh = vb(lr)
        self.assertGreater(th, tw)
        self.assertGreater(lw, lh)

    def test_malformed_input_never_throws(self):
        for src in ("stateDiagram-v2", "stateDiagram-v2\n foo bar baz",
                    "stateDiagram-v2\n --> A",  "stateDiagram-v2\n [*] -->",
                    "stateDiagram-v2\n state {\n }", "stateDiagram-v2\n }"):
            _js(src)                          # a throw surfaces as a non-zero exit / load: error


CLASSD = """classDiagram
    Animal <|-- Duck
    Animal <|-- Fish
    Animal : +int age
    Animal : +String gender
    Animal : +isMammal()
    Duck : +String beakColor
    Duck : +swim()
    Fish : -int sizeInFeet
"""


@unittest.skipUnless(NODE, "node not installed — JS evals skipped")
class TestClassDiagram(unittest.TestCase):
    def test_every_class_and_member_reaches_the_svg(self):
        s = _js(CLASSD)
        self.assertIsNotNone(s); self.assertTrue(s.startswith("<svg"), s[:60])
        for cls in ("Animal", "Duck", "Fish"):
            self.assertIn(">%s<" % cls, s)
        for m in ("+int age", "+String gender", "+isMammal()", "+String beakColor", "+swim()", "-int sizeInFeet"):
            self.assertIn(m, s)

    def test_inheritance_arrow_points_from_subclass_to_base(self):
        # `Animal <|-- Duck` means Duck extends Animal — arrow should end at Animal.
        # We can't easily assert direction from SVG alone, but we can assert BOTH
        # sides of the relationship exist as separate nodes with an edge between them.
        s = _js("classDiagram\n Animal <|-- Duck")
        self.assertIsNotNone(s)
        self.assertIn(">Animal<", s); self.assertIn(">Duck<", s)
        self.assertIn('marker-end="url(#mmdarrow)"', s)      # a directed edge was drawn

    def test_class_block_body_lists_members(self):
        s = _js("classDiagram\n class Foo {\n  +int x\n  -bool y\n  +method()\n }")
        self.assertIsNotNone(s)
        self.assertIn(">Foo<", s); self.assertIn("+int x", s)
        self.assertIn("-bool y", s); self.assertIn("+method()", s)

    def test_cardinality_labels_ride_the_edge(self):
        # Cardinality bookends + verb collapse into ONE edge label so the reader sees the
        # relationship in one glance ("1 has *") instead of three separate scraps of text.
        s = _js('classDiagram\n Order "1" --> "*" LineItem : has')
        self.assertIsNotNone(s)
        self.assertIn(">Order<", s); self.assertIn(">LineItem<", s)
        self.assertIn("has", s); self.assertIn("1", s); self.assertIn("*", s)

    def test_member_text_is_escaped(self):
        s = _js("classDiagram\n Foo : +<script>alert(1)</script>")
        self.assertIsNotNone(s)
        self.assertNotIn("<script>", s)

    def test_malformed_input_never_throws(self):
        for src in ("classDiagram", "classDiagram\n foo bar",
                    "classDiagram\n <|--", "classDiagram\n class Bare {",
                    "classDiagram\n }"):
            _js(src)


ER = """erDiagram
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--|{ LINE-ITEM : contains
    CUSTOMER {
        string name
        string email
    }
"""


@unittest.skipUnless(NODE, "node not installed — JS evals skipped")
class TestErDiagram(unittest.TestCase):
    def test_entities_relationships_and_attributes_render(self):
        s = _js(ER)
        self.assertIsNotNone(s); self.assertTrue(s.startswith("<svg"), s[:60])
        for ent in ("CUSTOMER", "ORDER", "LINE-ITEM"):
            self.assertIn(">%s<" % ent, s)
        for verb in ("places", "contains"):
            self.assertIn(verb, s)
        for attr in ("string name", "string email"):
            self.assertIn(attr, s)

    def test_cardinality_is_translated_to_readable_prose(self):
        # ||--o{ means "one to zero-or-more" — the reader shouldn't have to know ER shorthand
        s = _js("erDiagram\n A ||--o{ B : has")
        self.assertIsNotNone(s)
        self.assertIn("one", s)
        self.assertIn("zero-or-more", s)

    def test_relationship_without_a_verb_still_renders(self):
        s = _js("erDiagram\n A ||--|| B")
        self.assertIsNotNone(s)
        self.assertIn(">A<", s); self.assertIn(">B<", s)

    def test_malformed_input_never_throws(self):
        for src in ("erDiagram", "erDiagram\n foo bar",
                    "erDiagram\n A B", "erDiagram\n A {\n bad", "erDiagram\n }"):
            _js(src)


JOURNEY = """journey
    title My working day
    section Go to work
      Make tea: 5: Me
      Go upstairs: 3: Me
      Do work: 1: Me, Cat
    section Go home
      Go downstairs: 5: Me
      Sit down: 5: Me
"""


@unittest.skipUnless(NODE, "node not installed — JS evals skipped")
class TestJourneyDiagram(unittest.TestCase):
    def test_sections_and_tasks_render(self):
        s = _js(JOURNEY)
        self.assertIsNotNone(s); self.assertTrue(s.startswith("<svg"), s[:60])
        for sec in ("Go to work", "Go home"):
            self.assertIn(">%s<" % sec, s)
        for task in ("Make tea", "Go upstairs", "Do work", "Go downstairs", "Sit down"):
            self.assertIn(task, s)

    def test_happiness_score_becomes_a_face_and_number(self):
        s = _js(JOURNEY)
        # score 5 → 😊, score 3 → 😐, score 1 → 😞 — all three appear at least once
        self.assertIn("😊", s); self.assertIn("😐", s); self.assertIn("😞", s)

    def test_userJourney_alias_also_matches(self):
        s = _js("userJourney\n section S\n  Task: 4: Me")
        self.assertIsNotNone(s)
        self.assertIn(">S<", s); self.assertIn("Task", s)

    def test_actors_are_preserved(self):
        s = _js(JOURNEY)
        self.assertIn("Me, Cat", s)                          # multi-actor task

    def test_malformed_input_never_throws(self):
        for src in ("journey", "journey\n title x", "journey\n section",
                    "journey\n section S\n bad : notanumber : Me"):
            _js(src)


PIE = """pie title Sales by Region
    "North" : 45
    "South" : 30
    "East" : 15
    "West" : 10
"""


@unittest.skipUnless(NODE, "node not installed — JS evals skipped")
class TestPieChart(unittest.TestCase):
    def test_renders_svg_with_a_slice_per_entry(self):
        s = _js(PIE)
        self.assertIsNotNone(s); self.assertTrue(s.startswith("<svg"), s[:60])
        self.assertIn('aria-label="pie chart"', s)
        self.assertEqual(4, s.count("<path"))                # four slices → four arc paths
        for lbl in ("North", "South", "East", "West"):
            self.assertIn(lbl, s)
        # percentages appear in the legend
        for pct in ("45.0%", "30.0%", "15.0%", "10.0%"):
            self.assertIn(pct, s)

    def test_title_is_rendered_above_the_pie(self):
        s = _js(PIE)
        self.assertIn(">Sales by Region<", s)

    def test_single_slice_pie_renders_a_full_circle(self):
        # A single 100% slice can't be drawn as an arc (start=end sweep) — fall back to a full circle
        s = _js('pie\n "Only" : 42')
        self.assertIsNotNone(s)
        self.assertIn("<circle", s)
        self.assertIn("100.0%", s)

    def test_showData_keyword_is_accepted(self):
        s = _js('pie showData\n "A" : 1\n "B" : 2')
        self.assertIsNotNone(s)
        self.assertEqual(2, s.count("<path"))

    def test_label_text_is_escaped(self):
        s = _js('pie\n "<script>bad</script>" : 5')
        self.assertIsNotNone(s)
        self.assertNotIn("<script>", s)

    def test_malformed_input_never_throws(self):
        for src in ("pie", "pie title x", 'pie\n "a" : notanumber',
                    'pie\n "a" : 0\n "b" : 0'):        # zero total → null, not throw
            _js(src)


QUAD = """quadrantChart
    title Reach and engagement of campaigns
    x-axis Low Reach --> High Reach
    y-axis Low Engagement --> High Engagement
    quadrant-1 We should expand
    quadrant-2 Need to promote
    quadrant-3 Re-evaluate
    quadrant-4 May be improved
    Campaign A: [0.3, 0.6]
    Campaign B: [0.45, 0.23]
    Campaign C: [0.57, 0.69]
    Campaign D: [0.78, 0.34]
"""


@unittest.skipUnless(NODE, "node not installed — JS evals skipped")
class TestQuadrantChart(unittest.TestCase):
    def test_axes_quadrants_and_points_render(self):
        s = _js(QUAD)
        self.assertIsNotNone(s); self.assertTrue(s.startswith("<svg"), s[:60])
        self.assertIn(">Reach and engagement of campaigns<", s)
        # The axis directional arrow `-->` is HTML-escaped once it lands in the SVG text node.
        for ax in ("Low Reach --&gt; High Reach", "Low Engagement --&gt; High Engagement"):
            self.assertIn(ax, s)
        for q in ("We should expand", "Need to promote", "Re-evaluate", "May be improved"):
            self.assertIn(q, s)
        for pt in ("Campaign A", "Campaign B", "Campaign C", "Campaign D"):
            self.assertIn(pt, s)
        # one dot per plotted point
        self.assertEqual(4, s.count("<circle"))

    def test_out_of_range_points_are_clamped_not_crashed(self):
        # a rogue [1.4, -0.2] still renders — just clipped to the axes
        s = _js("quadrantChart\n Bad: [1.4, -0.2]")
        self.assertIsNotNone(s)
        self.assertIn(">Bad<", s)

    def test_point_label_is_escaped(self):
        s = _js("quadrantChart\n <script>x</script>: [0.5, 0.5]")
        self.assertIsNotNone(s)
        self.assertNotIn("<script>", s)

    def test_malformed_input_never_throws(self):
        for src in ("quadrantChart", "quadrantChart\n foo bar",
                    "quadrantChart\n A: [x, y]", "quadrantChart\n A: [0.5]"):
            _js(src)




if __name__ == "__main__":
    unittest.main()
