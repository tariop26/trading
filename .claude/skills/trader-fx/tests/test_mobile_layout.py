import _path  # noqa
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import page
from test_page import STUB, TEMPLATE, read, sample

SECTIONS = (("s-ideas", "Idées"), ("s-resume", "Résumé"), ("s-force", "Devises"),
            ("s-cal", "Calendrier"), ("s-swing", "Setups"), ("s-plan", "Niveaux"))
MOBILE = re.compile(r"@media \(max-width: 640px\) \{(.*?)\n  \}\n", re.S)


def narrow_css():
    return MOBILE.search(read(TEMPLATE)).group(1)


class TestJumpNav(unittest.TestCase):
    def setUp(self):
        self.t = read(TEMPLATE)

    def test_the_nav_has_one_anchor_per_section_and_every_target_exists(self):
        nav = re.search(r'<nav class="jump" aria-label="Sections">(.*?)</nav>', self.t, re.S)
        self.assertIsNotNone(nav)
        links = re.findall(r'<a href="#(s-[a-z]+)">([^<]+)</a>', nav.group(1))
        self.assertEqual(tuple(links), SECTIONS)
        for target, _ in SECTIONS:
            self.assertEqual(self.t.count('<section id="%s"' % target), 1, target)

    def test_the_nav_is_hidden_on_a_wide_screen_and_sticky_on_a_phone(self):
        self.assertRegex(self.t, r"(?m)^  \.jump \{ display: none;")
        css = narrow_css()
        self.assertRegex(css, r"\.jump \{[^}]*display: flex")
        self.assertRegex(css, r"\.jump \{[^}]*position: sticky")
        self.assertRegex(css, r"\.jump \{[^}]*top: 0")
        self.assertRegex(css, r"\.jump a \{[^}]*min-height: 44px")

    def test_sections_keep_clear_of_the_sticky_nav_when_jumped_to(self):
        self.assertIn("scroll-margin-top", narrow_css())


class TestPhoneCss(unittest.TestCase):
    def setUp(self):
        self.css = narrow_css()

    def test_the_summary_is_two_columns(self):
        self.assertRegex(self.css, r"\.stats \{[^}]*repeat\(2, minmax\(0, 1fr\)\)")

    def test_the_currency_strength_panels_swipe_one_at_a_time(self):
        self.assertRegex(self.css, r"\.strength \{[^}]*overflow-x: auto")
        self.assertRegex(self.css, r"\.strength \{[^}]*scroll-snap-type: x mandatory")
        self.assertRegex(self.css, r"\.strength \.panel \{[^}]*scroll-snap-align: start")
        self.assertRegex(self.css, r"\.swipe-hint \{[^}]*display: block")
        self.assertRegex(read(TEMPLATE), r"(?m)^  \.swipe-hint \{ display: none;")

    def test_an_idea_shows_entry_stop_target_side_by_side(self):
        self.assertRegex(self.css, r"\.nums \{[^}]*repeat\(3, minmax\(0, 1fr\)\)")

    def test_folds_are_easy_to_tap(self):
        self.assertRegex(self.css, r"\.fold > summary \{[^}]*min-height: 44px")

    def test_the_text_is_never_inflated_by_the_phone(self):
        self.assertRegex(read(TEMPLATE), r"html \{[^}]*-webkit-text-size-adjust: 100%")

    def test_the_busy_tables_show_only_what_a_phone_needs(self):
        # each rule hides columns by position; the columns are still in the page
        for table, columns in ((".t-swing", (2, 5, 8)), (".t-levels", ()), (".t-sessions", (4, 5)),
                               (".t-cal", (3,))):          # the date stays: "14:30" alone is ambiguous
            self.assertIn("table%s" % table, self.css, table)
            for n in columns:
                self.assertRegex(self.css, r"table%s td:nth-child\(%d\)[^{]*\{[^}]*display: none" % (re.escape(table), n),
                                 (table, n))

    def test_the_levels_cards_use_two_columns(self):
        self.assertRegex(self.css, r"table\.t-levels tr \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)")

    def test_the_phone_rules_keep_to_the_charter(self):
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", self.css))
        self.assertNotRegex(self.css, r"border-(left|right)\s*:")
        self.assertNotRegex(self.css, r"(box|text)-shadow")


NARROW_STUB = STUB.replace("matches: false", "matches: true")
TREE = r"""
function ser(e) {
  return e instanceof El ? { tag: e.tag, cls: e.className, attrs: e.attrs, kids: e.children.map(ser) } : String(e);
}
fs.writeFileSync(process.env.TREE_FILE,
  JSON.stringify(Object.entries(byId).map(([k, e]) => [k, ser(e)])));
"""


def text_of(node):
    return node if isinstance(node, str) else " ".join(text_of(k) for k in node["kids"])


def walk(node, tag=None):
    if isinstance(node, str):
        return
    if tag is None or node["tag"] == tag:
        yield node
    for kid in node["kids"]:
        yield from walk(kid, tag)


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestFolds(unittest.TestCase):
    def tree(self, stub, doc=None):
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "stub.js")
            with open(sp, "w", encoding="utf-8") as f:
                f.write(stub + TREE)
            hp = os.path.join(d, "p.html")
            with open(hp, "w", encoding="utf-8") as f:
                f.write(page.render_page(sample() if doc is None else doc, TEMPLATE))
            tp = os.path.join(d, "tree.json")
            r = subprocess.run(["node", sp, hp], capture_output=True, text=True, encoding="utf-8",
                               env=dict(os.environ, TREE_FILE=tp, TAGS_FILE=os.path.join(d, "t.json")))
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(tp, encoding="utf-8") as f:
                return dict(json.load(f))

    def folds(self, roots, section):
        return [d for d in walk(roots[section], "details")]

    def summary(self, details):
        return text_of(next(walk(details, "summary")))

    def test_on_a_wide_screen_every_fold_is_open(self):
        roots = self.tree(STUB)
        count = 0
        for section in ("ideas", "calendar", "swing", "plan"):
            for d in self.folds(roots, section):
                self.assertIn("open", d["attrs"], (section, self.summary(d)))
                count += 1
        self.assertGreaterEqual(count, 4)

    def test_on_a_phone_every_fold_starts_closed(self):
        roots = self.tree(NARROW_STUB)
        count = 0
        for section in ("ideas", "calendar", "swing", "plan"):
            for d in self.folds(roots, section):
                self.assertNotIn("open", d["attrs"], (section, self.summary(d)))
                count += 1
        self.assertGreaterEqual(count, 4)

    def test_each_idea_keeps_its_plan_visible_and_folds_the_details(self):
        roots = self.tree(NARROW_STUB)
        cards = [a for a in walk(roots["ideas"], "article")]
        self.assertGreaterEqual(len(cards), 1)
        for card in cards:
            folds = [d for d in walk(card, "details")]
            self.assertEqual(len(folds), 1)
            self.assertEqual(self.summary(folds[0]), "Détails et pourquoi")
            inside = text_of(folds[0])
            self.assertIn("Rapport", inside)
            # the plan (entry, stop, target) stays outside the fold
            outside = text_of(card).replace(inside, "")
            for label in ("Entrée", "Stop", "Cible"):
                self.assertIn(label, outside)

    def test_the_calendar_keeps_the_next_24_hours_visible_and_folds_the_rest(self):
        b = sample()
        in24 = {(e["utc"], e["currency"], e["title"]) for e in b["day_plan"]["events_24h"]}
        events = b["calendar"]["events"]
        others = [e for e in events if (e["utc"], e["currency"], e["title"]) not in in24]
        self.assertTrue(others and in24, "the sample must have events inside and outside 24 h")
        roots = self.tree(NARROW_STUB, b)
        folds = self.folds(roots, "calendar")
        self.assertEqual([self.summary(f) for f in folds],
                         ["Autres annonces de la semaine (%d)" % len(others)])
        visible = [t for t in walk(roots["calendar"], "table")]
        self.assertEqual(len(visible), 2)                       # the 24 h table, and the folded one
        rows_in_fold = sum(1 for _ in walk(folds[0], "tr")) - 1   # minus the header row
        self.assertEqual(rows_in_fold, len(others))

    def test_a_calendar_without_events_outside_24h_has_no_fold(self):
        b = sample()
        keys = {(e["utc"], e["currency"], e["title"]) for e in b["day_plan"]["events_24h"]}
        b["calendar"]["events"] = [e for e in b["calendar"]["events"]
                                   if (e["utc"], e["currency"], e["title"]) in keys]
        self.assertEqual(self.folds(self.tree(NARROW_STUB, b), "calendar"), [])

    def test_the_swing_families_and_the_levels_are_folded_with_their_counts(self):
        roots = self.tree(NARROW_STUB)
        swing = [self.summary(f) for f in self.folds(roots, "swing")]
        self.assertTrue(swing and all(re.fullmatch(r".+ \(\d+\)", s) for s in swing), swing)
        plan = [self.summary(f) for f in self.folds(roots, "plan")]
        self.assertIn("Niveaux à surveiller", " ".join(plan))

    def test_the_tables_carry_their_layout_class(self):
        roots = self.tree(NARROW_STUB)
        classes = {t["cls"] for sec in roots.values() for t in walk(sec, "table")}
        for needed in ("t-cal", "t-swing", "t-levels", "t-sessions"):
            self.assertIn(needed, classes)

    def test_a_swipe_hint_follows_the_strength_panels(self):
        roots = self.tree(STUB)
        hints = [n for n in walk(roots["force"]) if n["cls"] == "note swipe-hint"]
        self.assertEqual(len(hints), 1)
        self.assertIn("glisser", text_of(hints[0]))

    def test_the_full_text_is_still_there_whatever_the_screen(self):
        wide = " ".join(text_of(r) for r in self.tree(STUB).values())
        narrow = " ".join(text_of(r) for r in self.tree(NARROW_STUB).values())
        self.assertEqual(wide, narrow)


if __name__ == "__main__":
    unittest.main()
