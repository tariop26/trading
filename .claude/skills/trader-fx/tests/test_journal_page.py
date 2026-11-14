import _path  # noqa
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone

import journal
import jstats
import page
from test_jstats import sample_journal
from test_page import (EMOJI_RE, LINK_RE, contrast, css_block, network_violations, read)

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TEMPLATE = os.path.join(SKILL, "journal_template.html")
REPORT = os.path.join(SKILL, "report_template.html")
MARKER = "<!--BRIEFING_JSON-->"
FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b")
NOW = datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc)
DISCLAIMER = "Journal de faits : résultats passés, ni conseil ni prévision."
NBSP = " "


def make_doc(journal_obj=None, capital=100000.0):
    j = sample_journal() if journal_obj is None else journal_obj
    return {"as_of": {"iso": NOW.isoformat(), "paris": "2026-11-20 22:00"},
            "journal": j, "stats": jstats.compute_stats(j, capital=capital, cap_pct=2.0)}


def embedded(html):
    m = re.search(r'<script type="application/json" id="journal">(.*?)</script>', html, re.S)
    return m.group(1) if m else None


STUB = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const json = (html.match(/<script type="application\/json" id="journal">([\s\S]*?)<\/script>/) || [])[1];
const ci = html.lastIndexOf('<script>');
const code = html.slice(ci + 8, html.indexOf('</script>', ci));
const created = []; const attrs = [];
function El(tag) {
  this.tag = tag; this.children = []; this.style = {}; this._text = ''; this.className = '';
  this.classList = { add() {}, remove() {}, toggle() {} };
}
El.prototype.appendChild = function (c) { this.children.push(c); return c; };
El.prototype.append = function (...cs) { cs.forEach(c => this.children.push(c)); };
El.prototype.replaceChildren = function (...cs) { this.children = cs; };
El.prototype.setAttribute = function (k, v) { attrs.push([this.tag, k, String(v)]); };
El.prototype.addEventListener = function () {};
Object.defineProperty(El.prototype, 'textContent', {
  get() { return this._text + this.children.map(c => c instanceof El ? c.textContent : String(c)).join(' '); },
  set(v) { this._text = String(v); this.children = []; } });
const byId = {};
const document = {
  getElementById(id) {
    if (id === 'journal') return { textContent: json };
    return byId[id] || (byId[id] = new El('div'));
  },
  createElement(t) { created.push(t); return new El(t); },
  createElementNS(ns, t) { created.push(t); return new El(t); },
  createTextNode(s) { return String(s); },
  querySelector() { return new El('div'); },
  querySelectorAll() { return []; },
  documentElement: new El('html'),
  addEventListener() {},
};
const win = { matchMedia: () => ({ matches: false, addEventListener() {} }) };
new Function('document', 'window', code)(document, win);
process.stdout.write(Object.values(byId).map(e => e.textContent).join('\n'));
fs.writeFileSync(process.env.OUT_FILE, JSON.stringify({ created, attrs }));
"""


class TestRenderPage(unittest.TestCase):
    def test_embed_json_script_id_defaults_to_briefing_and_validates(self):
        self.assertIn('id="briefing"', page.embed_json({"a": 1}))
        self.assertIn('id="journal"', page.embed_json({"a": 1}, script_id="journal"))
        for bad in ("", "Bad", "a b", 'x"y', "a1", "x>"):
            with self.assertRaises(ValueError, msg=bad):
                page.embed_json({"a": 1}, script_id=bad)

    def test_render_page_escapes_a_script_close_in_the_journal(self):
        doc = make_doc()
        doc["journal"]["trades"][0]["note"] = "</script><b>x</b> <!-- y"
        html = page.render_page(doc, TEMPLATE, script_id="journal")
        raw = embedded(html)
        self.assertIsNotNone(raw)
        self.assertNotIn("</", raw)
        self.assertEqual(json.loads(raw), doc)
        self.assertNotIn(MARKER, html)
        self.assertEqual(html.count('id="journal"'), 1)


class TestTemplate(unittest.TestCase):
    def setUp(self):
        self.t = read(TEMPLATE)

    def test_structure_headings_title_and_disclaimer(self):
        self.assertEqual(self.t.count("<title>"), 1)
        self.assertIn("<title>Journal de trading</title>", self.t)
        self.assertIsNone(re.search(r"</?(html|head|body)[\s>]", self.t, re.I))
        self.assertIn(MARKER, self.t)
        for s in ("Résumé", "Trades ouverts", "Statistiques", "Trades clôturés", "Réussite et R",
                  "Par règle et par sens", "Par paire, session et jour", "Erreurs",
                  "Capital et drawdown"):
            self.assertIn(s, self.t)
        self.assertIn(DISCLAIMER, self.t)
        self.assertIn("claude:viewport-fit-sides", self.t)
        self.assertIn("max(16px, env(safe-area-inset-left, 0px))", self.t)

    def test_network_rule(self):
        self.assertEqual(network_violations(self.t), [])
        self.assertEqual(len(LINK_RE.findall(self.t)), 1)

    def test_charter_tokens_are_the_ones_of_the_briefing_page(self):
        r = read(REPORT)
        for sel in (":root", ':root:not([data-theme="light"])', ':root[data-theme="dark"]'):
            self.assertEqual(css_block(self.t, sel), css_block(r, sel), sel)
        self.assertIn("color-scheme: dark", self.t)

    def test_no_raw_colours_outside_the_token_blocks(self):
        css = re.search(r"<style>(.*?)</style>", self.t, re.S).group(1)
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for sel in (":root", ':root:not([data-theme="light"])', ':root[data-theme="dark"]'):
            css = css.replace(sel, "", 1)
        stripped = re.sub(r"\{[^{}]*--[\w-]+\s*:[^{}]*\}", "{}", css)
        literals = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", stripped)
        self.assertEqual(literals, [])

    def test_charter_rules_no_emoji_side_border_shadow(self):
        self.assertIsNone(EMOJI_RE.search(self.t))
        self.assertNotRegex(self.t, r"border-(left|right)\s*:")
        self.assertNotRegex(self.t, r"(box|text)-shadow")
        self.assertNotIn("innerHTML", self.t)
        self.assertIn("Montserrat", self.t)
        self.assertIn("Inter", self.t)

    def test_every_pair_used_reaches_the_contrast_thresholds_in_both_themes(self):
        light = css_block(self.t, ":root")
        dark = dict(light, **css_block(self.t, ':root[data-theme="dark"]'))
        for name, tok in (("light", light), ("dark", dark)):
            self.assertGreaterEqual(contrast(tok["--ink"], tok["--surface"]), 4.5, name)
            self.assertGreaterEqual(contrast(tok["--muted"], tok["--surface"]), 4.5, name)
            self.assertGreaterEqual(contrast(tok["--muted"], tok["--bg"]), 4.5, name)
            self.assertGreaterEqual(contrast(tok["--pos"], tok["--surface"]), 3.0, name)  # the curve

    def test_vocabulary_filter_works_and_the_template_is_clean(self):
        self.assertTrue(FORBIDDEN.search("un achat"))
        self.assertTrue(FORBIDDEN.search("Sell the rip"))
        self.assertFalse(FORBIDDEN.search("survente"))
        self.assertFalse(FORBIDDEN.search("surachat"))
        self.assertIsNone(FORBIDDEN.search(self.t))

    def test_no_backspace_characters(self):
        for path in (TEMPLATE, os.path.join(HERE, "test_journal_page.py")):
            with open(path, "rb") as f:
                self.assertEqual(f.read().count(bytes([8])), 0, path)


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestScriptRuns(unittest.TestCase):
    def render(self, doc):
        """(stdout text of the render, tags created, attribute log)."""
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "stub.js")
            with open(stub, "w", encoding="utf-8") as f:
                f.write(STUB)
            hp = os.path.join(d, "p.html")
            with open(hp, "w", encoding="utf-8") as f:
                f.write(page.render_page(doc, TEMPLATE, script_id="journal"))
            out = os.path.join(d, "out.json")
            r = subprocess.run(["node", stub, hp], capture_output=True, text=True, encoding="utf-8",
                               env=dict(os.environ, OUT_FILE=out))
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, encoding="utf-8") as f:
                log = json.load(f)
            return r.stdout, log["created"], log["attrs"]

    def test_summary_figures(self):
        text, _, _ = self.render(make_doc())
        self.assertIn("2026-11-20 22:00", text)
        for want in ("Trades clôturés", "Trades ouverts", "+1.44 R", "+900.35 USD", "50.0 %", "0.21",
                     "1 résultat(s) estimé(s), hors frais"):
            self.assertIn(want, text)
        self.assertIn("échantillon trop petit pour conclure", text)

    def test_open_trade_row(self):
        j = journal.empty_journal()
        t = journal.open_trade(j, symbol="EURJPY=X", name="EUR/JPY", side="baissier", price=176.70,
                               lots=0.45, stop=178.408, target=173.161,
                               when_utc=datetime(2026, 11, 16, 8, 30, tzinfo=timezone.utc),
                               prices={"USDJPY=X": 159.875})
        text, _, _ = self.render(make_doc(j))
        for want in (t["id"], "EURJPY=X", "Baissier", "2026-11-16 09:30", "176.700", "178.408",
                     "173.161", "0.45 lot (45" + NBSP + "000 unités)", "480.75"):
            self.assertIn(want, text)

    def test_open_trade_with_unknown_risk_and_a_contract(self):
        j = journal.empty_journal()
        journal.open_trade(j, symbol="GBPZAR=X", name="GBP/ZAR", side="haussier", price=22.0, lots=0.1,
                           stop=21.8, when_utc=NOW)
        journal.open_trade(j, symbol="^FCHI", name="CAC 40", side="haussier", price=8000.0, size=4.5,
                           stop=7900.0, when_utc=NOW, risk_usd=495.0)
        text, _, _ = self.render(make_doc(j))
        self.assertIn("inconnu", text)
        self.assertIn("taille 4.5", text)

    def test_the_five_statistics_families_with_n_and_few_marks(self):
        text, _, _ = self.render(make_doc())
        for want in ("Réussite et R", "Par règle et par sens", "Par paire, session et jour", "Erreurs",
                     "Capital et drawdown", "breakdown_20d", "Cassure du plus bas 20 j", "hors plan",
                     "Sydney", "vendredi", "entree_tardive", "peu de trades",
                     "Un trade compte dans chacune de ses règles"):
            self.assertIn(want, text)
        self.assertIn("haussier".capitalize(), text)

    def test_closed_trades_show_source_and_r(self):
        text, _, _ = self.render(make_doc())
        self.assertIn("estimé, hors frais", text)
        self.assertIn("courtier", text)
        self.assertIn("+0.94", text)
        self.assertIn("n/a", text)               # trade G has no R
        for bad in ("undefined", "NaN", "null", "None"):
            self.assertNotIn(bad, text)

    def test_equity_curve_has_one_point_per_closed_trade_plus_the_start(self):
        _, created, attrs = self.render(make_doc())
        self.assertIn("svg", created)
        polylines = [a for a in attrs if a[0] == "polyline" and a[1] == "points"]
        self.assertEqual(len(polylines), 1)
        self.assertEqual(len(polylines[0][2].split()), 9)          # 8 closed trades + the start

    def test_no_curve_without_two_points(self):
        j = journal.empty_journal()
        _, created, _ = self.render(make_doc(j))
        self.assertNotIn("svg", created)

    def test_empty_journal_and_missing_stats_do_not_throw(self):
        text, _, _ = self.render(make_doc(journal.empty_journal()))
        self.assertIn("Aucun trade enregistré pour l'instant.", text)
        doc = make_doc()
        del doc["stats"]
        self.render(doc)
        self.render({"journal": {"v": 1, "trades": [None, 3, "x", {}]}})
        self.render({})

    def test_hostile_text_is_not_executed(self):
        j = sample_journal()
        j["trades"][0]["note"] = "<img src=x onerror=alert(1)>"
        j["trades"][0]["tags"] = ["</script><script>alert(1)</script>"]
        j["trades"][1]["symbol"] = "<b>X</b>"
        _, created, _ = self.render(make_doc(j))
        for tag in ("img", "script", "b"):
            self.assertNotIn(tag, created)

    def test_rendered_page_has_no_forbidden_words(self):
        text, _, _ = self.render(make_doc())
        self.assertIsNone(FORBIDDEN.search(text))


class TestPageCommand(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.jpath = os.path.join(self.dir, "journal.json")
        self.out = os.path.join(self.dir, "journal.html")

    def run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = journal.main(list(args) + ["--journal", self.jpath],
                                {"now": lambda: NOW, "fetch_rate": lambda s: None})
        return code, buf.getvalue()

    def test_page_command_writes_the_page(self):
        journal.save_journal(self.jpath, sample_journal())
        code, text = self.run_cli("page", "--out", self.out)
        self.assertEqual(code, 0, text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        html = read(self.out)
        raw = json.loads(embedded(html))
        self.assertEqual(raw["stats"]["n_closed"], 8)
        self.assertEqual(len(raw["journal"]["trades"]), 9)
        self.assertEqual(raw["as_of"]["iso"], NOW.isoformat())
        self.assertEqual(raw["as_of"]["paris"], "2026-11-20 22:00")
        self.assertIn("Journal de trading", html)

    def test_page_command_on_an_empty_journal_and_on_errors(self):
        code, _ = self.run_cli("page", "--out", self.out)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(self.out))
        with open(self.jpath, "w", encoding="utf-8") as f:
            f.write("{")
        before = read(self.out)
        code, text = self.run_cli("page", "--out", self.out)
        self.assertEqual(code, 1)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(read(self.out), before)


if __name__ == "__main__":
    unittest.main()
