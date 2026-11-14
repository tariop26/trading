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

import briefing
import fx
import page
import test_briefing as tb

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
TEMPLATE = os.path.join(os.path.dirname(HERE), "report_template.html")
DISCLAIMER = ("Liste de graphiques qui ont matché une règle. Pas un conseil. "
              "Données Yahoo, retardées.")
MARKER = "<!--BRIEFING_JSON-->"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def sample():
    return json.loads(read(os.path.join(FIX, "briefing_sample.json")))


def embedded(html):
    m = re.search(r'<script type="application/json" id="briefing">(.*?)</script>', html, re.S)
    return m.group(1) if m else None


class TestRender(unittest.TestCase):
    def test_render_page_embeds_json_and_escapes_script_close(self):
        b = sample()
        b["swing"]["hits"][0]["name"] = "</script><b>x</b> <!-- y"
        html = page.render_page(b, TEMPLATE)
        self.assertNotIn(MARKER, html)
        raw = embedded(html)
        self.assertIsNotNone(raw)
        self.assertNotIn("</", raw)
        self.assertIn("<\\/script>", raw)
        # the escape is valid JSON and round-trips
        self.assertEqual(json.loads(raw), b)
        self.assertEqual(html.count('id="briefing"'), 1)

    def test_render_page_keeps_accents_readable(self):
        html = page.render_page(sample(), TEMPLATE)
        self.assertIn("matché une règle", embedded(html))

    def test_render_page_requires_marker(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.html")
            with open(p, "w", encoding="utf-8") as f:
                f.write("<title>x</title>")
            with self.assertRaises(ValueError):
                page.render_page(sample(), p)

    def test_page_has_no_html_head_body_wrappers(self):
        html = page.render_page(sample(), TEMPLATE)
        self.assertIsNone(re.search(r"</?(html|head|body)[\s>]", html, re.I))


class TestTemplate(unittest.TestCase):
    def setUp(self):
        self.t = read(TEMPLATE)

    def test_template_has_all_sections_and_disclaimer(self):
        for s in ("Résumé", "Force des devises", "Calendrier", "Setups swing",
                  "Plan du jour", "Avertissements"):
            self.assertIn(s, self.t)
        self.assertIn(DISCLAIMER, self.t)
        self.assertIn(MARKER, self.t)
        self.assertEqual(self.t.count("<title>"), 1)
        self.assertIn("Briefing Marchés", self.t)

    def test_template_makes_no_network_calls(self):
        for bad in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource",
                    "importScripts"):
            self.assertNotIn(bad, self.t)
        self.assertIsNone(re.search(r"<script[^>]*\ssrc\s*=", self.t, re.I))
        self.assertIsNone(re.search(r"<link[^>]*\shref\s*=", self.t, re.I))
        self.assertIsNone(re.search(r"@import", self.t, re.I))
        self.assertIsNone(re.search(r"url\(\s*['\"]?(https?:)?//", self.t, re.I))
        for m in re.finditer(r"(https?://[^\s\"'<>)]*)", self.t):
            self.assertEqual(m.group(1), "http://www.w3.org/2000/svg")

    def test_template_theme_and_layout_rules(self):
        t = self.t
        self.assertIn("prefers-color-scheme: dark", t)
        self.assertIn(':root:not([data-theme="light"])', t)
        self.assertIn(':root[data-theme="dark"]', t)
        self.assertEqual(t.count("color-scheme: dark;"), 2)
        self.assertRegex(t, r"body\s*\{[^}]*background:")
        self.assertIn("overflow-x: auto", t)
        self.assertIn("max(16px", t)

    def test_template_has_no_forbidden_words(self):
        self.assertIsNone(re.search(r"(?i)\b(achat|acheter|buy|gagnant|profit)\b", self.t))

    def test_template_shows_na_for_missing_values(self):
        self.assertIn("n/a", self.t)


STUB = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const json = (html.match(/<script type="application\/json" id="briefing">([\s\S]*?)<\/script>/) || [])[1];
const code = (html.match(/<script>([\s\S]*?)<\/script>/) || [])[1];
function El(tag) {
  this.tag = tag; this.children = []; this.attrs = {}; this.style = {}; this._text = '';
  this.className = '';
  this.classList = { add() {}, remove() {}, toggle() {} };
}
El.prototype.appendChild = function (c) { this.children.push(c); return c; };
El.prototype.append = function (...cs) { cs.forEach(c => this.children.push(c)); };
El.prototype.replaceChildren = function (...cs) { this.children = cs; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
El.prototype.addEventListener = function () {};
Object.defineProperty(El.prototype, 'textContent', {
  get() { return this._text + this.children.map(c => c instanceof El ? c.textContent : String(c)).join(' '); },
  set(v) { this._text = String(v); this.children = []; } });
const byId = {};
const document = {
  getElementById(id) {
    if (id === 'briefing') return { textContent: process.argv[3] ? fs.readFileSync(process.argv[3], 'utf8') : json };
    return byId[id] || (byId[id] = new El('div'));
  },
  createElement(t) { return new El(t); },
  createElementNS(ns, t) { return new El(t); },
  createTextNode(s) { return String(s); },
  querySelector() { return new El('div'); },
  querySelectorAll() { return []; },
  documentElement: new El('html'),
  addEventListener() {},
};
const win = { matchMedia: () => ({ matches: false, addEventListener() {} }) };
new Function('document', 'window', code)(document, win);
process.stdout.write(Object.values(byId).map(e => e.textContent).join('\n'));
"""


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestInlineScriptRuns(unittest.TestCase):
    """Runs the inline script in node with a minimal DOM stub: it must not throw on
    the sample, on a minimal briefing and on empty parts."""

    def run_node(self, briefing_obj=None):
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "stub.js")
            with open(stub, "w", encoding="utf-8") as f:
                f.write(STUB)
            html = page.render_page(sample() if briefing_obj is None else briefing_obj,
                                    TEMPLATE)
            hp = os.path.join(d, "p.html")
            with open(hp, "w", encoding="utf-8") as f:
                f.write(html)
            r = subprocess.run(["node", stub, hp], capture_output=True, text=True,
                               encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

    def test_script_renders_sample(self):
        out = self.run_node()
        self.assertIn("EURUSD=X", out)
        self.assertIn("CPI m/m", out)
        self.assertIn("2026-11-10 16:00", out)   # Paris
        self.assertIn("2026-11-10 10:00", out)   # New York
        for bad in ("undefined", "NaN", "null", "None"):
            self.assertNotIn(bad, out)

    def test_script_tags_an_asia_range_still_forming(self):
        b = sample()
        b["day_plan"]["levels"][0]["asia_complete"] = False
        self.assertIn("plage en cours", self.run_node(b))

    def test_script_has_no_forming_tag_for_a_complete_or_unknown_range(self):
        b = sample()
        b["day_plan"]["levels"][0]["asia_complete"] = True
        self.assertNotIn("plage en cours", self.run_node(b))
        del b["day_plan"]["levels"][0]["asia_complete"]
        self.assertNotIn("plage en cours", self.run_node(b))
        self.assertNotIn("plage en cours", self.run_node())   # the sample itself

    def test_page_from_real_build_briefing_shows_the_calendar_reason(self):
        b = briefing.build_briefing(
            tb.UNIVERSE, tb.all_breakouts(), [], {},
            tb.cal("unavailable", reason="this week: boom"), tb.TUE)
        b["warnings"] = []   # the same text is also a warning: isolate the calendar block
        out = self.run_node(b)
        self.assertIn("this week: boom", out)
        self.assertIn("indisponible", out)

    def test_script_survives_empty_parts(self):
        b = sample()
        b["calendar"] = {"status": "unavailable", "events": []}
        b["swing"] = {"hits": [], "clusters": []}
        b["day_plan"] = {"sessions": [], "levels": [], "events_24h": []}
        b["strength"] = {"windows": {}}
        b["warnings"] = []
        out = self.run_node(b)
        for bad in ("undefined", "NaN", "null"):
            self.assertNotIn(bad, out)

    def test_script_shows_na_for_null_values(self):
        b = sample()
        b["swing"]["hits"][0]["trend"] = None
        b["swing"]["hits"][0]["rsi"] = None
        b["day_plan"]["levels"][0]["asia_high"] = None
        out = self.run_node(b)
        self.assertIn("n/a", out)
        for bad in ("undefined", "NaN", "null"):
            self.assertNotIn(bad, out)

    def test_script_survives_minimal_object(self):
        out = self.run_node({"disclaimer": DISCLAIMER})
        self.assertNotIn("undefined", out)


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fx.main(argv, {})
    return code, out.getvalue()


class TestPageCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_page_command_missing_json_returns_1(self):
        out = os.path.join(self.tmp.name, "o.html")
        code, text = run_main(["page", "--in", os.path.join(self.tmp.name, "nope.json"),
                               "--out", out])
        self.assertEqual(code, 1)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertFalse(os.path.exists(out))

    def test_page_command_invalid_json_returns_1(self):
        src = os.path.join(self.tmp.name, "b.json")
        with open(src, "w", encoding="utf-8") as f:
            f.write("{not json")
        code, text = run_main(["page", "--in", src,
                               "--out", os.path.join(self.tmp.name, "o.html")])
        self.assertEqual(code, 1)
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_page_command_writes_html(self):
        src = os.path.join(FIX, "briefing_sample.json")
        out = os.path.join(self.tmp.name, "sub", "o.html")
        code, text = run_main(["page", "--in", src, "--out", out])
        self.assertEqual(code, 0)
        self.assertEqual(len(text.strip().splitlines()), 1)
        html = read(out)
        self.assertEqual(json.loads(embedded(html)), sample())
        self.assertIn("Force des devises", html)

    def test_page_defaults(self):
        args = fx.build_parser().parse_args(["page"])
        self.assertEqual(args.inp, "trader/fx/briefing.json")
        self.assertEqual(args.out, "trader/fx/briefing.html")

    def test_brief_still_has_its_defaults(self):
        args = fx.build_parser().parse_args(["brief"])
        self.assertEqual(args.out, "trader/fx/briefing.json")


class TestSampleFixture(unittest.TestCase):
    def test_sample_covers_the_page_cases(self):
        b = sample()
        self.assertGreaterEqual(len(b["swing"]["hits"]), 1)
        self.assertGreaterEqual(len(b["calendar"]["events"]), 1)
        self.assertEqual(set(b["strength"]["windows"]), {"1d", "5d", "20d"})
        self.assertGreaterEqual(len(b["day_plan"]["levels"]), 1)
        self.assertGreaterEqual(len(b["warnings"]), 2)
        self.assertEqual(b["disclaimer"], DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
