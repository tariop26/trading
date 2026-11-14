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


FONTS_HREF_PREFIX = "https://fonts.googleapis.com/"
SVG_NS = "http://www.w3.org/2000/svg"
LINK_RE = re.compile(r"<link\b[^>]*>", re.I)


def network_violations(t):
    """What breaks the Artifact network rule: at most ONE external resource, a stylesheet
    <link> to fonts.googleapis.com. Returns a list of problems (empty = fine)."""
    bad = []
    for word in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource",
                 "importScripts"):
        if word in t:
            bad.append(word)
    if re.search(r"<script[^>]*\ssrc\s*=", t, re.I):
        bad.append("script src")
    if re.search(r"@import", t, re.I):
        bad.append("@import")
    if re.search(r"url\(\s*['\"]?(https?:)?//", t, re.I):
        bad.append("url(//)")
    links = LINK_RE.findall(t)
    if len(links) > 1:
        bad.append("more than one <link>")
    rest = t
    for link in links:
        m = re.search(r'\shref\s*=\s*"([^"]*)"', link)
        ok = (m and m.group(1).startswith(FONTS_HREF_PREFIX)
              and re.search(r'\srel\s*=\s*"stylesheet"', link))
        if not ok:
            bad.append("link is not a fonts.googleapis.com stylesheet: " + link)
        rest = rest.replace(link, "")
    for m in re.finditer(r"(https?://[^\s\"'<>)]*)", rest):
        if m.group(1) != SVG_NS:
            bad.append("url " + m.group(1))
    return bad


def hex_lum(h):
    h = h.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = sorted((hex_lum(a), hex_lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def css_block(t, selector):
    """Declarations of the first rule whose selector is exactly `selector`, as a dict."""
    m = re.search(r"(?:^|[\s{}])" + re.escape(selector) + r"\s*\{([^}]*)\}", t)
    if not m:
        return None
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    return dict((k.strip(), v.strip()) for k, v in
                re.findall(r"(--[\w-]+|[\w-]+)\s*:\s*([^;]+);", body))


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
        self.assertEqual(network_violations(self.t), [])

    def test_network_rule_allows_only_the_one_fonts_stylesheet(self):
        # exactly one external resource: the Google Fonts stylesheet link
        self.assertEqual(len(LINK_RE.findall(self.t)), 1)
        self.assertEqual(self.t.count(FONTS_HREF_PREFIX), 1)
        # the rule itself must bite: a second link, another host, a script src, @import,
        # fetch(, another URL each make it fail
        for extra in ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X">',
                      '<link rel="preconnect" href="https://fonts.gstatic.com">',
                      '<link rel="stylesheet" href="https://example.com/a.css">',
                      '<script src="a.js"></script>', "<style>@import 'a.css';</style>",
                      "<script>fetch('x')</script>", '<a href="https://example.com/">x</a>',
                      "<style>a{background:url(https://example.com/i.png)}</style>"):
            self.assertNotEqual(network_violations(self.t + extra), [], extra)
        wrong_host = self.t.replace(FONTS_HREF_PREFIX, "https://evil.example/")
        self.assertNotEqual(network_violations(wrong_host), [])
        # no link at all is fine for the rule itself, and the svg namespace is allowed
        self.assertEqual(network_violations('<svg xmlns="http://www.w3.org/2000/svg"></svg>'), [])

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


LIGHT_BLOCK = ":root"
DARK_MEDIA_BLOCK = ':root:not([data-theme="light"])'
DARK_ATTR_BLOCK = ':root[data-theme="dark"]'
SURFACE_TOKENS = ("--bg", "--surface", "--ink", "--muted", "--line")
# the main emoji ranges: pictographs, dingbats, misc symbols, misc technical, selectors
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿"
                      "️‍⃣]")


class TestCharte4884(unittest.TestCase):
    def setUp(self):
        self.t = read(TEMPLATE)
        self.light = css_block(self.t, LIGHT_BLOCK)
        self.dark_media = css_block(self.t, DARK_MEDIA_BLOCK)
        self.dark_attr = css_block(self.t, DARK_ATTR_BLOCK)

    def test_brand_tokens_exist_on_bare_root(self):
        for token, value in (("--color-dark", "#1A3330"), ("--color-dark-hover", "#142926"),
                             ("--color-mid", "#2A5446"), ("--color-cream", "#F5F1E8"),
                             ("--color-card", "#FAFAF5"), ("--color-gold", "#C9A84C"),
                             ("--color-gold-hover", "#B08A30"), ("--color-danger", "#C0392B")):
            self.assertEqual(self.light.get(token, "").upper(), value, token)

    def test_light_theme_maps_brand_colours_to_the_surface_tokens(self):
        for token, value in (("--bg", "#F5F1E8"), ("--surface", "#FAFAF5"),
                             ("--ink", "#1A2B27"), ("--muted", "#4A6E60"),
                             ("--line", "#DDD9CC")):
            self.assertEqual(self.light.get(token, "").upper(), value, token)

    def test_dark_blocks_redefine_the_surface_tokens_and_agree(self):
        self.assertIsNotNone(self.dark_media)
        self.assertIsNotNone(self.dark_attr)
        for token in SURFACE_TOKENS:
            self.assertIn(token, self.dark_media, token)
            self.assertNotEqual(self.dark_media[token], self.light[token], token)
        self.assertEqual(self.dark_media.get("--bg", "").upper(), "#142926")
        self.assertEqual(self.dark_media.get("--surface", "").upper(), "#1A3330")
        self.assertEqual(self.dark_media, self.dark_attr)
        self.assertEqual(self.dark_attr.get("color-scheme"), "dark")

    def test_every_token_used_is_defined_on_bare_root(self):
        used = set(re.findall(r"var\((--[\w-]+)", self.t))
        self.assertEqual(sorted(used - set(self.light)), [])
        for token in self.dark_attr:
            if token.startswith("--"):
                self.assertIn(token, self.light)

    def test_no_raw_colours_outside_the_token_blocks(self):
        css = re.search(r"<style>(.*?)</style>", self.t, re.S).group(1)
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for sel in (LIGHT_BLOCK, DARK_MEDIA_BLOCK, DARK_ATTR_BLOCK):
            css = re.sub(r"(?:^|(?<=[\s{}]))" + re.escape(sel) + r"\s*\{[^}]*\}", "", css,
                         count=1)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", css))
        self.assertIsNone(re.search(r"\brgba?\(", css))

    def test_header_band_is_pine_green_in_both_themes(self):
        for block in (self.dark_media, self.dark_attr):
            self.assertNotIn("--color-dark", block)
        rule = css_block(self.t, "header")
        self.assertEqual(rule.get("background-color"), "var(--color-dark)")
        image = rule.get("background-image", "")
        self.assertIn("radial-gradient", image)
        self.assertIn("var(--glow)", image)
        self.assertEqual(css_block(self.t, ":root")["--glow"].replace(" ", ""),
                         "rgba(201,168,76,0.07)")

    def test_header_carries_the_mountain_mark_overline_and_h1(self):
        m = re.search(r"<header>(.*?)</header>", self.t, re.S)
        self.assertIsNotNone(m)
        header = m.group(1)
        self.assertIn("<svg", header)
        self.assertIn('aria-hidden="true"', header)
        self.assertIn('stroke="currentColor"', header)
        self.assertIn('viewBox="0 0 120 100"', header)
        self.assertIn("M 12 90", header)             # the path of mountain-mark.svg
        self.assertIn("4884 · DATA", header)
        self.assertIn('id="asof"', header)
        self.assertIn('id="banners"', header)
        self.assertEqual(css_block(self.t, ".mark").get("color"), "var(--color-gold)")

    def test_h1_emphasises_only_the_word_marches(self):
        self.assertEqual(len(re.findall(r"<h1[ >]", self.t)), 1)
        self.assertIn("<h1>Briefing <em>marchés</em></h1>", self.t)
        self.assertEqual(self.t.count("<em>"), 1)
        em = css_block(self.t, "h1 em")
        self.assertEqual(em.get("color"), "var(--color-gold)")
        self.assertEqual(em.get("font-style"), "normal")

    def test_overline_is_gold_uppercase_montserrat(self):
        rule = css_block(self.t, ".overline")
        self.assertEqual(rule.get("color"), "var(--color-gold)")
        self.assertEqual(rule.get("text-transform"), "uppercase")
        self.assertEqual(rule.get("letter-spacing"), "0.15em")
        self.assertEqual(rule.get("font-weight"), "700")
        self.assertIn("var(--font-head)", rule.get("font-family", ""))

    def test_fonts_are_montserrat_headings_and_inter_body_with_fallbacks(self):
        head = self.light.get("--font-head", "")
        text = self.light.get("--font-text", "")
        self.assertTrue(head.startswith('"Montserrat"'), head)
        self.assertTrue(text.startswith('"Inter"'), text)
        for stack in (head, text):
            self.assertIn('system-ui, -apple-system, "Segoe UI", sans-serif', stack)
        self.assertNotIn("monospace", self.t)
        self.assertNotIn("--font-num", self.t)
        link = LINK_RE.search(self.t).group(0)
        self.assertIn("family=Inter:wght@300;400;500;600", link)
        self.assertIn("family=Montserrat:wght@400;500;600;700;800;900", link)
        self.assertIn("display=swap", link)
        # beside the title, before the style
        self.assertLess(self.t.index("<title>"), self.t.index(link))
        self.assertLess(self.t.index(link), self.t.index("<style>"))
        self.assertIn("tabular-nums", self.t)
        self.assertIn("var(--font-head)", css_block(self.t, "h1, h2, h3").get("font-family", ""))
        self.assertIn("var(--font-text)", css_block(self.t, "body").get("font-family", ""))

    def test_pills_and_tags_follow_the_badge_style(self):
        for sel in (".pill", ".tag"):
            rule = css_block(self.t, sel)
            self.assertEqual(rule.get("text-transform"), "uppercase", sel)
            self.assertEqual(rule.get("letter-spacing"), "0.1em", sel)
            self.assertEqual(rule.get("font-weight"), "700", sel)
            self.assertEqual(rule.get("font-size"), "0.72rem", sel)
            self.assertEqual(rule.get("border-radius"), "50px", sel)
            self.assertIn("var(--font-head)", rule.get("font-family", ""), sel)

    def test_cards_have_a_border_no_shadow_and_no_side_accent(self):
        self.assertIsNone(re.search(r"border-(left|right|inline-start|inline-end)\s*:", self.t))
        self.assertNotIn("box-shadow", self.t)
        panel = css_block(self.t, ".panel")
        self.assertEqual(panel.get("border-radius"), "16px")
        self.assertIn("1px solid var(--line)", panel.get("border", ""))
        self.assertEqual(css_block(self.t, ".scroll").get("border-radius"), "10px")

    def test_no_gradient_except_the_gold_glow(self):
        self.assertNotIn("linear-gradient", self.t)
        self.assertNotIn("conic-gradient", self.t)
        self.assertEqual(self.t.count("radial-gradient"), 1)

    def test_strength_bars_green_stronger_gold_weaker(self):
        self.assertEqual(css_block(self.t, ".fill.pos").get("background"), "var(--pos)")
        self.assertEqual(css_block(self.t, ".fill.neg").get("background"), "var(--neg)")
        self.assertEqual(self.light["--pos"].upper(), "#2A5446")
        self.assertEqual(self.light["--neg"].upper(), "#C9A84C")
        self.assertEqual(self.dark_attr["--neg"].upper(), "#C9A84C")
        # the track keeps its centre axis and the signed number stays in the row
        self.assertIn(".track::before", self.t)
        self.assertIn('h("span", "val num", signed(v, 2))', self.t)

    def test_no_emoji_characters(self):
        self.assertIsNone(EMOJI_RE.search(self.t), EMOJI_RE.findall(self.t))
        # the checker bites
        self.assertIsNotNone(EMOJI_RE.search("x \U0001F4C8"))
        self.assertIsNotNone(EMOJI_RE.search("x ⚠️"))
        self.assertIsNone(EMOJI_RE.search("4884 · DATA − ’ é"))

    def test_the_six_french_headings_and_ids_are_kept(self):
        for hid, label in (("h-resume", "Résumé"), ("h-force", "Force des devises"),
                           ("h-cal", "Calendrier"), ("h-swing", "Setups swing"),
                           ("h-plan", "Plan du jour"), ("h-warn", "Avertissements")):
            self.assertIn('<h2 id="%s">%s</h2>' % (hid, label), self.t)
        for kept in ("plage en cours", "Chaque colonne a sa propre échelle",
                     "Briefing produit il y a", "Ce briefing date de plus de"):
            self.assertIn(kept, self.t)

    def test_artifact_rules_still_hold(self):
        self.assertIn('<meta name="claude:viewport-fit-sides" content="cover">', self.t)
        body = css_block(self.t, "body")
        self.assertEqual(body.get("background"), "var(--bg)")
        self.assertEqual(body.get("padding-left"), "max(16px, env(safe-area-inset-left, 0px))")
        self.assertEqual(body.get("padding-right"), "max(16px, env(safe-area-inset-right, 0px))")
        self.assertEqual(css_block(self.t, ".scroll").get("overflow-x"), "auto")


class TestContrast(unittest.TestCase):
    """Every text/background pair shipped reaches 4.5:1 (3:1 for the graphic bars) in the
    light and in the dark theme."""

    def setUp(self):
        t = read(TEMPLATE)
        light = css_block(t, LIGHT_BLOCK)
        dark = dict(light)
        dark.update(css_block(t, DARK_ATTR_BLOCK))
        self.themes = {"light": light, "dark": dark}

    def check(self, fg, bg, minimum=4.5):
        for name, tok in self.themes.items():
            a, b = tok[fg], tok[bg]
            self.assertTrue(a.startswith("#") and b.startswith("#"), (fg, bg, name))
            self.assertGreaterEqual(contrast(a, b), minimum, "%s on %s (%s)" % (fg, bg, name))

    def test_text_pairs(self):
        for fg, bg in (("--ink", "--bg"), ("--ink", "--surface"), ("--muted", "--bg"),
                       ("--muted", "--surface"), ("--tag-ink", "--surface"),
                       ("--tag-ink", "--bg"), ("--warn-ink", "--warn-bg"),
                       ("--band-ink", "--color-dark"), ("--band-muted", "--color-dark"),
                       ("--color-gold", "--color-dark"),
                       ("--band-warn-ink", "--band-warn-bg"),
                       ("--band-stale-ink", "--band-stale-bg"), ("--focus", "--bg")):
            self.check(fg, bg)

    def test_graphic_pairs_need_three_to_one(self):
        self.check("--pos", "--surface", 3.0)
        self.check("--neg-edge", "--surface", 3.0)

    def test_bars_differ_in_lightness_not_hue_alone(self):
        for name, tok in self.themes.items():
            self.assertGreaterEqual(contrast(tok["--pos"], tok["--neg"]), 1.7, name)

    def test_the_contrast_helper_is_right(self):
        self.assertAlmostEqual(contrast("#000000", "#FFFFFF"), 21.0, places=1)
        self.assertLess(contrast("#C9A84C", "#FAFAF5"), 3.0)   # why gold is never text on light


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
