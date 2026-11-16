import _path  # noqa
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import page
from test_page import STUB, TEMPLATE, css_block, read, sample

MOBILE_RULE = re.compile(r"@media \(max-width: 640px\) \{(.*?)\n  \}\n", re.S)


class TestStandaloneDocument(unittest.TestCase):
    """The published page is a file of its own: a phone needs a doctype, a charset and a viewport
    (the Artifact wrapper adds them, GitHub Pages does not)."""

    def test_standalone_adds_the_document_skeleton_once(self):
        out = page.standalone(page.render_page(sample(), TEMPLATE))
        self.assertTrue(out.startswith("<!doctype html>\n<html lang=\"fr\">\n<head>\n"))
        self.assertEqual(out.count("<!doctype html>"), 1)
        self.assertEqual(out.count('<meta charset="utf-8">'), 1)
        self.assertEqual(out.count('<meta name="viewport" content="width=device-width, initial-scale=1">'), 1)
        self.assertEqual(out.count('<html lang="fr">'), 1)

    def test_the_skeleton_comes_before_the_template_head_elements(self):
        out = page.standalone(page.render_page(sample(), TEMPLATE))
        for needle in ("<title>", "<style>", "<main>"):
            self.assertLess(out.index('<meta name="viewport"'), out.index(needle), needle)
        self.assertLess(out.index('<meta charset="utf-8">'), out.index("<title>"))

    def test_the_template_and_the_artifact_page_have_no_skeleton_of_their_own(self):
        raw = page.render_page(sample(), TEMPLATE)
        self.assertNotIn("<!doctype", raw.lower())
        self.assertNotIn('name="viewport"', raw)
        self.assertNotIn("<html", raw.lower())

    def test_standalone_leaves_a_complete_document_alone(self):
        once = page.standalone(page.render_page(sample(), TEMPLATE))
        self.assertEqual(page.standalone(once), once)

    def test_standalone_keeps_the_page_body_byte_for_byte(self):
        raw = page.render_page(sample(), TEMPLATE)
        self.assertTrue(page.standalone(raw).endswith(raw))

    def test_the_embedded_json_survives(self):
        out = page.standalone(page.render_page(sample(), TEMPLATE))
        self.assertEqual(out.count('<script type="application/json" id="briefing">'), 1)


class TestNarrowScreenCss(unittest.TestCase):
    def setUp(self):
        self.t = read(TEMPLATE)
        m = MOBILE_RULE.search(self.t)
        self.assertIsNotNone(m, "no @media (max-width: 640px) block")
        self.css = m.group(1)

    def test_tables_become_cards_without_sideways_scrolling(self):
        self.assertRegex(self.css, r"table,\s*tbody,\s*tr,\s*td\s*\{[^}]*display:\s*block")
        self.assertRegex(self.css, r"\.scroll\s*\{[^}]*overflow-x:\s*visible")
        self.assertRegex(self.css, r"td::before\s*\{[^}]*content:\s*attr\(data-label\)")

    def test_the_header_row_is_hidden_visually_but_kept_for_screen_readers(self):
        block = re.search(r"thead\s*\{([^}]*)\}", self.css).group(1)
        self.assertIn("position: absolute", block)
        self.assertIn("clip: rect(0 0 0 0)", block)
        self.assertNotIn("display: none", block)

    def test_the_card_rules_keep_to_the_charter(self):
        # same constraints as the whole page: tokens only, no side border, no shadow, no emoji
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", self.css))
        self.assertNotRegex(self.css, r"border-(left|right)\s*:")
        self.assertNotRegex(self.css, r"(box|text)-shadow")
        self.assertIn("var(--surface)", self.css)
        self.assertIn("var(--line)", self.css)
        self.assertIn("var(--muted)", self.css)

    def test_a_value_that_is_several_elements_stays_on_the_right(self):
        # a cell with a price and a tag: the label is pushed left, everything else packs right
        self.assertRegex(self.css, r"td\s*\{[^}]*justify-content:\s*flex-end")
        self.assertRegex(self.css, r"td::before\s*\{[^}]*margin-right:\s*auto")

    def test_the_wide_screen_rules_are_untouched(self):
        self.assertEqual(css_block(self.t, ".scroll").get("overflow-x"), "auto")
        self.assertEqual(css_block(self.t, "td.wrap").get("white-space"), "normal")

    def test_the_card_layout_starts_at_640px_and_nowhere_else(self):
        self.assertEqual(self.t.count("@media (max-width: 640px)"), 1)     # the script asks the same width
        self.assertNotIn("min-width: 641px", self.t)


TREE_STUB = STUB + r"""
function ser(e) {
  return e instanceof El ? { tag: e.tag, attrs: e.attrs, kids: e.children.map(ser) } : String(e);
}
fs.writeFileSync(process.env.TREE_FILE,
  JSON.stringify(Object.entries(byId).map(([k, e]) => [k, ser(e)])));
"""


def text_of(node):
    if isinstance(node, str):
        return node
    return " ".join(text_of(k) for k in node["kids"])


def walk(node, tag):
    if isinstance(node, str):
        return
    if node["tag"] == tag:
        yield node
    for kid in node["kids"]:
        yield from walk(kid, tag)


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestCellLabels(unittest.TestCase):
    def tables(self):
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "stub.js")
            with open(stub, "w", encoding="utf-8") as f:
                f.write(TREE_STUB)
            hp = os.path.join(d, "p.html")
            with open(hp, "w", encoding="utf-8") as f:
                f.write(page.render_page(sample(), TEMPLATE))
            tree = os.path.join(d, "tree.json")
            r = subprocess.run(["node", stub, hp], capture_output=True, text=True, encoding="utf-8",
                               env=dict(os.environ, TREE_FILE=tree, TAGS_FILE=os.path.join(d, "t.json")))
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(tree, encoding="utf-8") as f:
                roots = json.load(f)
        return [t for _, root in roots for t in walk(root, "table")]

    def test_every_cell_carries_the_label_of_its_column(self):
        tables = self.tables()
        self.assertGreaterEqual(len(tables), 3)
        cells = 0
        for table in tables:
            head = next(walk(table, "thead"))
            labels = [text_of(th) for th in walk(head, "th")]
            self.assertTrue(all(labels), labels)
            for body in walk(table, "tbody"):
                for row in walk(body, "tr"):
                    tds = list(walk(row, "td"))
                    self.assertEqual(len(tds), len(labels))
                    for td, label in zip(tds, labels):
                        self.assertEqual(td["attrs"].get("data-label"), label)
                        cells += 1
        self.assertGreaterEqual(cells, 20)


if __name__ == "__main__":
    unittest.main()
