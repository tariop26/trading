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
import make_sample_fixture
import page
import test_briefing as tb

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
TEMPLATE = os.path.join(os.path.dirname(HERE), "report_template.html")
DISCLAIMER = ("Liste de graphiques qui ont matché une règle. Pas un conseil. "
              "Données Yahoo, retardées.")
MARKER = "<!--BRIEFING_JSON-->"
FORBIDDEN_WORDS = tb.FORBIDDEN_WORDS
IDEAS_NOTE = ("Idées de plan mécaniques, issues des règles ci-dessous. À valider, pas des "
              "conseils. Prix de référence : dernière clôture.")
OVER_CAP_BANNER = ("Risque cumulé au-dessus du plafond : n'ouvrez pas toutes ces idées en "
                   "même temps.")      # the fallback when max_ideas_within_cap is absent
NBSP = "\u00a0"
RISK_NOTE = ("Le risque au stop vaut pour l'entrée affichée, sans écart d'ouverture ni "
             "glissement.")
VOID = "Stop déjà franchi depuis la clôture : plan caduc."
REACHED = "Cible déjà atteinte depuis la clôture."
NEW_LABELS = (("breakdown_20d", "Cassure du plus bas 20 j"),
              ("bear_flag", "Drapeau baissier"),
              ("lose_ma20", "Perte de la moyenne 20 j"),
              ("overbought", "Surachat"),
              ("overbought_reject", "Rejet depuis le surachat"))
OLD_LABELS = (("breakout_20d", "Cassure du plus haut 20 j"),
              ("bull_flag", "Drapeau haussier"),
              ("reclaim_ma20", "Reprise de la moyenne 20 j"),
              ("oversold", "Survente"),
              ("oversold_bounce", "Rebond depuis la survente"))


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
        # FORBIDDEN_WORDS is a RAW string with a real \b (a previous test typed a backspace
        # and matched nothing): it must catch a whole word and spare a substring
        self.assertEqual(FORBIDDEN_WORDS.count(chr(8)), 0)
        self.assertIn(r"\b(achat|acheter|vente|vendre|buy|sell|gagnant|profit)\b",
                      FORBIDDEN_WORDS)
        self.assertRegex("un achat", FORBIDDEN_WORDS)
        self.assertRegex("Sell the rip", FORBIDDEN_WORDS)
        self.assertRegex("on peut vendre", FORBIDDEN_WORDS)
        self.assertNotRegex("surachat", FORBIDDEN_WORDS)
        self.assertNotRegex("ventes", FORBIDDEN_WORDS)
        self.assertNotRegex("Surachat, Rejet depuis le surachat", FORBIDDEN_WORDS)
        self.assertIsNone(re.search(FORBIDDEN_WORDS, self.t))
        self.assertIsNotNone(re.search(FORBIDDEN_WORDS, self.t + " <p>un achat</p>"))
        self.assertIsNone(re.search(FORBIDDEN_WORDS, page.render_page(sample(), TEMPLATE)))

    def test_template_never_injects_html(self):
        for word in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                     "createContextualFragment", "eval(", "new Function"):
            self.assertNotIn(word, self.t, word)

    def test_ideas_section_is_between_header_and_resume(self):
        t = self.t
        for marker in ("</header>", 'id="s-ideas"', 'id="s-resume"'):
            self.assertEqual(t.count(marker), 1, marker)
        self.assertLess(t.index("</header>"), t.index('id="s-ideas"'))
        self.assertLess(t.index('id="s-ideas"'), t.index('id="s-resume"'))
        self.assertIn('<section id="s-ideas" aria-labelledby="h-ideas">', t)
        self.assertIn('<h2 id="h-ideas">Trades potentiels</h2>', t)
        self.assertIn('<div id="ideas"></div>', t)
        main = re.search(r"<main>(.*)</main>", t, re.S).group(1)
        self.assertIn('id="s-ideas"', main)
        self.assertIn(IDEAS_NOTE, t)
        self.assertIn('section(renderIdeas, b, "ideas");', t)

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

    def test_the_seven_headings_include_trades_potentiels(self):
        self.assertIn('<h2 id="h-ideas">Trades potentiels</h2>', self.t)
        self.assertEqual(len(re.findall(r"<h2[ >]", self.t)), 7)

    def test_idea_cards_follow_the_charter(self):
        # a card is a .panel (1px border, 16px radius, no shadow, no side accent)
        self.assertIn('["article", "panel idea"]', self.t)
        panel = css_block(self.t, ".panel")
        self.assertEqual(panel.get("border-radius"), "16px")
        self.assertIn("1px solid var(--line)", panel.get("border", ""))
        idea = css_block(self.t, ".idea")
        self.assertEqual(idea.get("overflow-wrap"), "anywhere")
        self.assertEqual(idea.get("min-width"), "0")
        self.assertEqual(idea.get("font-variant-numeric"), "tabular-nums")
        # one column at 400px: the grid never asks for more than the available width
        grid = css_block(self.t, ".ideas")
        self.assertEqual(grid.get("display"), "grid")
        self.assertEqual(grid.get("grid-template-columns"),
                         "repeat(auto-fit, minmax(min(100%, 16rem), 1fr))")
        for sel in (".idea-head", ".facts", ".nums", ".why", ".skipped", ".callout", ".total"):
            self.assertIsNotNone(css_block(self.t, sel), sel)
        self.assertNotIn("box-shadow", self.t)
        self.assertIsNone(re.search(r"border-(left|right|inline-start|inline-end)\s*:", self.t))
        # the side is a word, the dot only reinforces it
        self.assertEqual(css_block(self.t, ".pill.up::before").get("background"), "var(--pos)")
        self.assertEqual(css_block(self.t, ".pill.down::before").get("background"),
                         "var(--neg-edge)")
        for word in ("Haussier", "Baissier"):
            self.assertIn('"%s"' % word, self.t)

    def test_new_text_pairs_are_token_pairs_and_reach_4_5_to_1(self):
        """Each new text style names its colour and its ground as tokens, and the pair
        reaches 4.5:1 in both themes (the tokens are defined in both blocks)."""
        t = self.t
        light = css_block(t, LIGHT_BLOCK)
        dark = dict(light)
        dark.update(css_block(t, DARK_ATTR_BLOCK))
        pairs = (  # (selector, colour token, ground token): the ground is the card or page
            (".idea-title", "--ink", "--surface"),
            (".idea-head .rank", "--muted", "--surface"),
            (".idea-head .name", "--muted", "--surface"),
            (".why", "--ink", "--surface"),
            (".size-msg", "--ink", "--surface"),
            (".callout", "--warn-ink", "--warn-bg"),
            (".total", "--ink", "--bg"),
            (".skipped", "--ink", "--bg"),
            (".void", "--band-stale-ink", "--band-stale-bg"),
        )
        for selector, fg, bg in pairs:
            rule = css_block(t, selector)
            self.assertIsNotNone(rule, selector)
            self.assertEqual(rule.get("color"), "var(%s)" % fg, selector)
            for name, tok in (("light", light), ("dark", dark)):
                self.assertGreaterEqual(contrast(tok[fg], tok[bg]), 4.5,
                                        "%s %s on %s (%s)" % (selector, fg, bg, name))
        self.assertEqual(css_block(t, ".callout").get("background"), "var(--warn-bg)")
        self.assertEqual(css_block(t, ".void").get("background"), "var(--band-stale-bg)")
        self.assertIn("var(--band-stale-line)", css_block(t, ".void").get("border", ""))
        self.assertEqual(css_block(t, ".void").get("font-weight"), "700")
        self.assertIn("var(--warn-line)", css_block(t, ".callout").get("border", ""))
        self.assertEqual(css_block(t, ".panel").get("background"), "var(--surface)")
        # the two dots are graphics: 3:1 against the card
        for fg in ("--pos", "--neg-edge"):
            for name, tok in (("light", light), ("dark", dark)):
                self.assertGreaterEqual(contrast(tok[fg], tok["--surface"]), 3.0,
                                        "%s (%s)" % (fg, name))


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
// the code is the LAST <script>: hostile text in the JSON block may itself contain "<script>"
const ci = html.lastIndexOf('<script>');
const code = html.slice(ci + 8, html.indexOf('</script>', ci));
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
const created = [];
const document = {
  getElementById(id) {
    if (id === 'briefing') return { textContent: process.argv[3] ? fs.readFileSync(process.argv[3], 'utf8') : json };
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
if (process.env.TAGS_FILE) { fs.writeFileSync(process.env.TAGS_FILE, JSON.stringify(created)); }
"""


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestInlineScriptRuns(unittest.TestCase):
    """Runs the inline script in node with a minimal DOM stub: it must not throw on
    the sample, on a minimal briefing and on empty parts."""

    def run_node(self, briefing_obj=None, tags=False):
        """Stdout of the render; with tags=True, (stdout, tags of every element created)."""
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "stub.js")
            with open(stub, "w", encoding="utf-8") as f:
                f.write(STUB)
            html = page.render_page(sample() if briefing_obj is None else briefing_obj,
                                    TEMPLATE)
            hp = os.path.join(d, "p.html")
            with open(hp, "w", encoding="utf-8") as f:
                f.write(html)
            tags_path = os.path.join(d, "tags.json")
            env = dict(os.environ, TAGS_FILE=tags_path)
            r = subprocess.run(["node", stub, hp], capture_output=True, text=True,
                               encoding="utf-8", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            if tags:
                return r.stdout, json.loads(read(tags_path))
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

    # ---- « Trades potentiels »

    @staticmethod
    def idea(b, symbol):
        return next(i for i in b["trade_ideas"]["ideas"] if i["symbol"] == symbol)

    @staticmethod
    def px(idea, v):
        """The plan's own decimals, carried by the idea."""
        return "%.*f" % (idea["decimals"], v)

    def test_ideas_heading_and_note(self):
        out = self.run_node()
        self.assertIn(IDEAS_NOTE, out)
        # the note is part of the section: once, before the first card
        self.assertEqual(out.count(IDEAS_NOTE), 1)

    def test_sample_has_the_three_idea_cases(self):
        b = sample()
        ti = b["trade_ideas"]
        self.assertEqual(sorted(i["size"]["status"] for i in ti["ideas"]),
                         ["ok", "to_confirm", "too_wide"])
        self.assertEqual(self.idea(b, "EURUSD=X")["size"]["status"], "ok")
        self.assertEqual({i["side"] for i in ti["ideas"]}, {"haussier", "baissier"})
        self.assertEqual(len(ti["skipped"]), 2)
        self.assertTrue(ti["over_cap"])
        self.assertTrue(any(not h["setups"] and h["setups_short"]
                            for h in b["swing"]["hits"]))   # a short-only hit

    def test_idea_card_shows_the_four_numbers_and_why(self):
        b = sample()
        eur = self.idea(b, "EURUSD=X")
        eur["size"].update(lots=1.0, units=100000, risk_usd=487.0, leverage=1.19,
                           pip_value_usd_per_lot=10.0)
        eur["rr"] = 2.0
        out, tags = self.run_node(b, tags=True)
        self.assertEqual(tags.count("article"), 3)       # one card per idea
        for text in ("N° %d" % eur["rank"], "EURUSD=X", "EUR/USD", "Haussier",
                     "Entrée", "Stop", "Cible", "Taille",
                     self.px(eur, eur["reference_price"]),
                     self.px(eur, eur["stop"]), self.px(eur, eur["target"]),
                     "1.00 lot (100" + NBSP + "000 unités)",
                     "Risque au stop (USD)", "487.00", "1:2", "×1.19",
                     "Valeur du pip par lot", "10.00 USD"):
            self.assertIn(text, out)
        for line in eur["why"]:
            self.assertIn(line, out)
        # the rule tags use the same label dictionary as the swing table
        self.assertIn("Cassure du plus haut 20 j", out)
        self.assertIn("Surachat", out)
        # a bearish idea says so with the word
        self.assertIn("Baissier", out)
        self.assertEqual(out.count("Haussier"), 2)
        self.assertEqual(out.count("Baissier"), 1)

    def test_idea_card_for_a_contract_instrument_has_a_size_and_no_pip_value(self):
        b = sample()
        b["trade_ideas"]["ideas"] = [{
            "rank": 1, "symbol": "GC=F", "name": "Or", "side": "haussier", "score": 3,
            "setups": ["bull_flag"], "trend": "up", "reference_price": 4012.5,
            "stop": 3950.25, "target": 4136.75, "rr": 2.5, "atr": 41.5,
            "size": {"status": "ok", "lots": None, "units": None, "size": 0.08,
                     "risk_usd": 498.0, "leverage": 0.321, "pip_value_usd_per_lot": None,
                     "limited_by": "risque", "note": None},
            "why": ["+2 drapeau haussier"]}]
        b["trade_ideas"]["skipped"] = []
        out = self.run_node(b)
        for text in ("GC=F", "Taille 0.08", "498.00", "1:2.5", "×0.321",
                     "4012.50", "3950.25", "4136.75", "Drapeau haussier"):
            self.assertIn(text, out)
        self.assertNotIn("taille 0.08", out)      # the word is not repeated in the value
        self.assertNotIn("Valeur du pip par lot", out)
        self.assertNotIn("unités", out)
        self.assertNotIn("lot (", out)

    def test_plan_prices_keep_the_decimals_of_the_plan(self):
        b = sample()
        b["trade_ideas"]["skipped"] = []
        b["trade_ideas"]["ideas"] = [{
            "rank": 1, "symbol": "USDJPY=X", "name": "USD/JPY", "side": "baissier",
            "score": 2, "setups": ["lose_ma20"], "trend": None,
            "reference_price": 151.84, "stop": 152.607, "target": 150.306, "rr": 2.0,
            "atr": 0.51,
            "size": {"status": "ok", "lots": 0.5, "units": 50000, "size": None,
                     "risk_usd": 255.0, "leverage": 0.5, "pip_value_usd_per_lot": 6.5867,
                     "limited_by": "risque", "note": None},
            "why": []}]
        out = self.run_node(b)
        for text in ("151.840", "152.607", "150.306", "0.50 lot (50" + NBSP + "000 unités)",
                     "6.59 USD", "Perte de la moyenne 20 j", "Baissier"):
            self.assertIn(text, out)
        self.assertNotIn("Pourquoi", out)         # no why lines, no empty list
        # other instruments: 2 decimals, never 3
        b["trade_ideas"]["ideas"][0].update(symbol="CL=F", reference_price=74.256,
                                            stop=74.89, target=73.0)
        out = self.run_node(b)
        for text in ("74.26", "74.89", "73.00"):
            self.assertIn(text, out)
        self.assertNotIn("73.000", out)

    def test_idea_with_a_leverage_limit_says_so(self):
        b = sample()
        eur = self.idea(b, "EURUSD=X")
        eur["size"]["limited_by"] = "levier"
        self.assertIn("Taille limitée par le levier maximal", self.run_node(b))
        eur["size"]["limited_by"] = "risque"
        self.assertNotIn("Taille limitée par le levier maximal", self.run_node(b))

    def test_to_confirm_and_too_wide_messages(self):
        b = sample()
        out, tags = self.run_node(b, tags=True)
        confirm = self.idea(b, "^FCHI")["size"]
        wide = self.idea(b, "CL=F")["size"]
        self.assertEqual((confirm["status"], wide["status"]), ("to_confirm", "too_wide"))
        self.assertEqual(out.count("Taille à confirmer chez le courtier"), 1)   # once
        self.assertEqual(confirm["note"], "taille à confirmer chez le courtier : renseigner "
                                          "contracts dans trader/fx/config.json")
        self.assertIn("renseigner contracts dans trader/fx/config.json", out)
        self.assertNotIn("taille à confirmer chez le courtier :", out)
        self.assertIn("Risque prévu : 500.00 USD", out)
        self.assertIn("Stop trop large pour le risque fixé", out)
        # the planned risk belongs to the to_confirm idea only, so the displayed figures
        # add up to the cumulated total
        self.assertEqual(out.count("Risque prévu"), 1)
        shown = [float(m) for m in re.findall(r"Risque au stop \(USD\)\s+(\d+\.\d\d)", out)]
        planned = [float(m) for m in re.findall(r"Risque prévu : (\d+\.\d\d) USD", out)]
        self.assertAlmostEqual(sum(shown) + sum(planned),
                               b["trade_ideas"]["total_risk_usd"], places=2)
        # no size, no lots for either
        self.assertEqual(out.count("Risque au stop (USD)"), 1)   # the ok idea only
        self.assertNotIn("Risque maximal", out)

    def test_total_risk_line_and_over_cap_banner(self):
        b = sample()
        ti = b["trade_ideas"]
        self.assertEqual((ti["over_cap"], ti["max_ideas_within_cap"]), (True, 1))
        out = self.run_node(b)
        self.assertIn("Risque cumulé : 997.24 USD (1.00 %) sur 0.75 % autorisés"
                      " · levier cumulé ×0.74", out)
        self.assertEqual(out.count("Risque cumulé au-dessus du plafond : au plus 1 idée "
                                   "ouverte en même temps."), 1)
        self.assertNotIn(OVER_CAP_BANNER, out)
        ti.update(total_risk_usd=2500.0, total_risk_pct=2.5, max_total_pct=2.0,
                  max_ideas_within_cap=4)
        out = self.run_node(b)
        self.assertIn("Risque cumulé : 2500.00 USD (2.50 %) sur 2 % autorisés", out)
        self.assertEqual(out.count("Risque cumulé au-dessus du plafond : au plus 4 idées "
                                   "ouvertes en même temps."), 1)
        # an older briefing without the key keeps the old sentence
        del ti["max_ideas_within_cap"]
        out = self.run_node(b)
        self.assertEqual(out.count(OVER_CAP_BANNER), 1)
        # only a real true counts: the text "false" does not raise the banner
        ti["over_cap"] = "false"
        self.assertNotIn(OVER_CAP_BANNER, self.run_node(b))
        ti["over_cap"] = False
        self.assertNotIn(OVER_CAP_BANNER, self.run_node(b))

    def test_skipped_ideas_listed_with_reason(self):
        b = sample()
        out = self.run_node(b)
        self.assertIn("Idées écartées", out)
        self.assertIn("GBPUSD=X", out)
        self.assertIn("corrélée à EURUSD=X", out)
        b["trade_ideas"]["skipped"] = [{"symbol": "AUDUSD=X", "reason": "ATR indisponible"},
                                       {"symbol": "USDJPY=X",
                                        "reason": "signaux contradictoires"}]
        out = self.run_node(b)
        for text in ("AUDUSD=X", "ATR indisponible", "USDJPY=X", "signaux contradictoires"):
            self.assertIn(text, out)
        self.assertNotIn("corrélée à EURUSD=X", out)
        b["trade_ideas"]["skipped"] = []
        self.assertNotIn("Idées écartées", self.run_node(b))

    def test_zero_ideas_message(self):
        b = sample()
        b["trade_ideas"]["ideas"] = []
        b["trade_ideas"]["skipped"] = []
        b["trade_ideas"].update(total_risk_usd=0.0, total_risk_pct=0.0, over_cap=False)
        out, tags = self.run_node(b, tags=True)
        self.assertIn("Aucune idée de trade sur cette analyse.", out)
        self.assertNotIn("article", tags)
        self.assertNotIn("Risque cumulé", out)
        self.assertIn(IDEAS_NOTE, out)
        self.assertNotIn("Section indisponible", out)

    def test_old_briefing_without_trade_ideas_does_not_break(self):
        b = sample()
        del b["trade_ideas"]
        out = self.run_node(b)
        self.assertIn("Aucune idée de trade sur cette analyse.", out)
        self.assertNotIn("Section indisponible", out)
        self.assertIn("EURUSD=X", out)            # the rest of the page is intact
        for bad in ("undefined", "NaN", "null"):
            self.assertNotIn(bad, out)
        for junk in (None, [], "x", 3, {"ideas": "x"}, {"ideas": None, "skipped": 5},
                     {"ideas": [None, 3, "x", {}], "skipped": [None, {}]}):
            b["trade_ideas"] = junk
            out = self.run_node(b)
            self.assertIn("EURUSD=X", out)
            for bad in ("undefined", "NaN", "null"):
                self.assertNotIn(bad, out, repr(junk))

    def test_idea_with_missing_fields_shows_na(self):
        b = sample()
        b["trade_ideas"]["ideas"] = [{"rank": 1, "symbol": "EURUSD=X", "side": "haussier"}]
        b["trade_ideas"]["skipped"] = []
        out = self.run_node(b)
        self.assertIn("n/a", out)
        self.assertIn("Haussier", out)
        self.assertNotIn("Section indisponible", out)
        for bad in ("undefined", "NaN", "null"):
            self.assertNotIn(bad, out)

    def test_hostile_text_in_idea_fields_is_not_executed(self):
        evil_img = "<img src=x onerror=alert(1)>"
        evil_script = "</script><script>alert(2)</script><!-- x"
        b = sample()
        eur = self.idea(b, "EURUSD=X")
        eur["symbol"] = evil_img
        eur["name"] = evil_script
        eur["why"] = [evil_img, evil_script]
        eur["setups"] = [evil_img]
        b["trade_ideas"]["ideas"][-1]["size"]["note"] = evil_img + evil_script
        b["trade_ideas"]["skipped"] = [{"symbol": evil_script, "reason": evil_img}]
        html = page.render_page(b, TEMPLATE)
        self.assertEqual(html.count("</script>"), 2)        # the JSON block and the code
        self.assertNotIn("</", embedded(html))
        self.assertNotIn("<!--", embedded(html))
        out, tags = self.run_node(b, tags=True)
        for tag in ("img", "script", "b", "iframe", "svg"):
            self.assertNotIn(tag, tags)
        self.assertIn("article", tags)    # the recorder does see the elements that are made
        # the hostile strings are shown as text, never interpreted
        self.assertIn(evil_img, out)
        self.assertIn(evil_script, out)

    def test_new_setup_labels_in_swing_table(self):
        b = sample()
        b["trade_ideas"]["ideas"] = []          # isolate the swing table from the idea cards
        b["trade_ideas"]["skipped"] = []
        hit = b["swing"]["hits"][0]
        hit["setups"] = ["breakout_20d"]
        hit["setups_short"] = [code for code, _ in NEW_LABELS]
        out = self.run_node(b)
        for code, label in NEW_LABELS + OLD_LABELS[:1]:
            self.assertIn(label, out, code)
        self.assertNotIn("breakdown_20d", out)      # a known code never shows raw
        # existing labels are unchanged
        hit["setups"] = [code for code, _ in OLD_LABELS]
        hit["setups_short"] = []
        out = self.run_node(b)
        for code, label in OLD_LABELS:
            self.assertIn(label, out, code)
        # an unknown code is shown as is (as before)
        hit["setups"] = ["mystery_rule"]
        self.assertIn("mystery_rule", self.run_node(b))

    def test_short_only_hit_of_the_sample_shows_its_labels(self):
        b = sample()
        b["trade_ideas"]["ideas"] = []
        b["trade_ideas"]["skipped"] = []
        short_only = [h for h in b["swing"]["hits"] if not h["setups"]]
        self.assertTrue(short_only)
        out = self.run_node(b)
        self.assertIn(short_only[0]["symbol"], out)
        self.assertIn("Rejet depuis le surachat", out)

    # ---- final wave: account line, close date, since_close, cap, ties, cosmetics

    def test_account_line(self):
        b = sample()
        out = self.run_node(b)
        self.assertEqual(out.count("Compte : 100" + NBSP + "000 USD · risque par idée 0.5 % "
                                   "(500.00 USD) · levier max 30:1 (valeurs par défaut)"), 1)
        acc = b["trade_ideas"]["account"]
        acc.update(source="file", capital=1234567, risk_per_trade_usd=3086.42, leverage_max=20)
        out = self.run_node(b)
        self.assertIn("Compte : 1" + NBSP + "234" + NBSP + "567 USD · risque par idée 0.25 % "
                      "(3086.42 USD) · levier max 20:1", out)
        self.assertNotIn("valeurs par défaut", out)
        for acc in ({}, {"capital": None, "risk_per_trade_usd": "x"}, {"capital": 50000}):
            b["trade_ideas"]["account"] = acc
            out = self.run_node(b)
            self.assertNotIn("Section indisponible", out)
            for bad in ("undefined", "NaN", "null"):
                self.assertNotIn(bad, out, repr(acc))
        self.assertIn("Compte : 50" + NBSP + "000 USD", out)
        b["trade_ideas"]["account"] = {}
        self.assertNotIn("Compte :", self.run_node(b))

    def test_entry_shows_the_close_date_and_the_risk_note(self):
        b = sample()
        out = self.run_node(b)
        eur = self.idea(b, "EURUSD=X")
        self.assertIn("Entrée %s clôture du 2026-11-09" % self.px(eur, eur["reference_price"]),
                      out)
        self.assertEqual(out.count("clôture du 2026-11-09"), 3)
        self.assertEqual(out.count(RISK_NOTE), 1)
        for i in b["trade_ideas"]["ideas"]:
            del i["last_bar_date"]
        out = self.run_node(b)
        self.assertNotIn("clôture du", out)

    def test_prices_use_the_decimals_of_the_idea(self):
        b = sample()
        b["trade_ideas"]["skipped"] = []
        b["trade_ideas"]["ideas"] = [{
            "rank": 1, "symbol": "NG=F", "name": "Gaz", "side": "haussier", "score": 2,
            "setups": ["bull_flag"], "trend": None, "reference_price": 3.0123,
            "stop": 2.8993, "target": 3.2383, "rr": 2.0, "atr": 0.0753, "decimals": 4,
            "size": {"status": "ok", "lots": None, "units": None, "size": 3.5,
                     "risk_usd": 395.5, "leverage": 0.105, "pip_value_usd_per_lot": None,
                     "limited_by": "risque", "note": None},
            "why": [], "last_bar_date": "2026-11-09", "since_close": None}]
        out = self.run_node(b)
        for text in ("3.0123", "2.8993", "3.2383", "Taille 3.5"):
            self.assertIn(text, out)
        self.assertNotIn("3.01 ", out)
        b["trade_ideas"]["ideas"][0]["decimals"] = "x"       # junk: the old heuristic (2)
        out = self.run_node(b)
        self.assertIn("Entrée 3.01 clôture du 2026-11-09 Stop 2.90 Cible 3.24", out)

    def test_since_close_lines(self):
        b = sample()
        out = self.run_node(b)
        eur = self.idea(b, "EURUSD=X")
        self.assertIn("Dernier cours 1 h : %s" % self.px(eur, eur["since_close"]["last"]), out)
        self.assertIn("Dernier cours 1 h : 8110.00", out)
        self.assertEqual(out.count(VOID), 1)                  # ^FCHI only
        self.assertNotIn(REACHED, out)
        fchi = self.idea(b, "^FCHI")
        fchi["since_close"]["target_crossed"] = True
        out, tags = self.run_node(b, tags=True)
        self.assertEqual(out.count(REACHED), 1)
        for i in b["trade_ideas"]["ideas"]:
            i["since_close"] = None
        out = self.run_node(b)
        for text in ("Dernier cours 1 h", VOID, REACHED):
            self.assertNotIn(text, out)
        for junk in ("x", 3, [], {"last": "x", "stop_crossed": "true"}):
            fchi["since_close"] = junk
            out = self.run_node(b)
            self.assertNotIn(VOID, out)
            for bad in ("undefined", "NaN", "null", "Section indisponible"):
                self.assertNotIn(bad, out, repr(junk))

    def test_void_banner_is_a_distinct_element(self):
        out, tags = self.run_node(sample(), tags=True)
        self.assertIn(VOID, out)
        self.assertIn('h("p", "void", MSG_VOID)', read(TEMPLATE))

    def test_total_leverage_and_ties_note(self):
        b = sample()
        ti = b["trade_ideas"]
        out = self.run_node(b)
        self.assertEqual(out.count("1 autre idée a le même score que la dernière affichée ; "
                                   "à score égal, l'ordre est alphabétique."), 1)
        ti["ties_at_cutoff"] = 3
        out = self.run_node(b)
        self.assertIn("3 autres idées ont le même score que la dernière affichée ; à score "
                      "égal, l'ordre est alphabétique.", out)
        for v in (0, None, "2", -1):
            ti["ties_at_cutoff"] = v
            self.assertNotIn("même score", self.run_node(b), repr(v))
        for v in (0, 0.0, None, "1", -2):
            ti["total_leverage"] = v
            self.assertNotIn("levier cumulé", self.run_node(b), repr(v))

    def test_size_cosmetics(self):
        b = sample()
        eur = self.idea(b, "EURUSD=X")
        eur["size"].update(lots=2.5, units=250000, pip_value_usd_per_lot=0.0067)
        out = self.run_node(b)
        self.assertIn("2.50 lots (250" + NBSP + "000 unités)", out)
        self.assertIn("0.0067 USD", out)
        eur["size"].update(lots=1.99, units=199000, pip_value_usd_per_lot=0.01)
        out = self.run_node(b)
        self.assertIn("1.99 lot (199" + NBSP + "000 unités)", out)
        self.assertIn("Valeur du pip par lot 0.01 USD", out)
        self.assertIn("0.62 lot (62" + NBSP + "000 unités)", self.run_node())

    def test_taille_cell_only_for_an_ok_size(self):
        b = sample()
        b["trade_ideas"]["ideas"] = [self.idea(b, "CL=F")]          # too_wide
        b["trade_ideas"]["skipped"] = []
        out = self.run_node(b)
        self.assertIn("Stop trop large pour le risque fixé", out)
        self.assertNotIn("Taille", out)
        b = sample()
        b["trade_ideas"]["ideas"] = [self.idea(b, "^FCHI")]         # to_confirm
        out = self.run_node(b)
        self.assertEqual(out.count("Taille"), 1)                   # the headline only
        self.assertNotIn("Taille n/a", out)

    def test_to_confirm_note_other_than_contracts_is_kept_whole(self):
        b = sample()
        fchi = self.idea(b, "^FCHI")
        fchi["size"]["note"] = ("conversion de devise impossible : taux en USD introuvable "
                                "pour ZAR")
        out = self.run_node(b)
        self.assertIn("conversion de devise impossible : taux en USD introuvable pour ZAR", out)

    def test_rendered_sample_has_no_forbidden_words(self):
        out = self.run_node()
        self.assertIsNone(re.search(FORBIDDEN_WORDS, out))
        self.assertIsNotNone(re.search(FORBIDDEN_WORDS, out + " un achat"))
        # no gain figure: a card carries a risk, never a potential gain
        gain = r"(?i)\b(gains?|gagner|profits?)\b"
        self.assertIsNone(re.search(gain, out))
        self.assertIsNotNone(re.search(gain, out + " un gain de"))


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

    def test_sample_fixture_has_the_real_key_set(self):
        """The fixture is compared with a fresh build_briefing, so it cannot drift again."""
        fresh = briefing.build_briefing(tb.UNIVERSE, tb.all_breakouts(), [], {}, tb.cal(),
                                        tb.TUE)
        b = sample()
        self.assertEqual(set(b), set(fresh))
        self.assertEqual(list(b), list(fresh))
        for key in ("as_of", "counts", "calendar", "strength", "swing", "day_plan",
                    "trade_ideas"):
            self.assertEqual(set(b[key]), set(fresh[key]), key)
        self.assertEqual(set(b["trade_ideas"]["account"]), set(fresh["trade_ideas"]["account"]))
        idea, real = b["trade_ideas"]["ideas"][0], fresh["trade_ideas"]["ideas"][0]
        self.assertEqual(set(idea), set(real))
        for i in b["trade_ideas"]["ideas"]:
            self.assertEqual(set(i["size"]), set(real["size"]))
            self.assertEqual(set(i), set(real))
        self.assertEqual(set(b["swing"]["hits"][0]), set(fresh["swing"]["hits"][0]))
        self.assertEqual(set(b["day_plan"]["levels"][0]), set(fresh["day_plan"]["levels"][0]))
        self.assertIn("last_bar_date", b["counts"])
        self.assertIn("reason", b["calendar"])
        self.assertIn("setups_short", b["swing"]["hits"][0])
        # the key-set check bites
        broken = dict(b)
        del broken["trade_ideas"]
        self.assertNotEqual(set(broken), set(fresh))

    def test_sample_fixture_is_what_the_generator_produces(self):
        with open(os.path.join(FIX, "briefing_sample.json"), encoding="utf-8") as f:
            committed = json.load(f)
        self.assertEqual(committed, json.loads(json.dumps(make_sample_fixture.build_sample())))

    def test_sample_fixture_covers_the_idea_cases(self):
        b = sample()
        ti = b["trade_ideas"]
        self.assertEqual(len(ti["ideas"]), 3)
        self.assertEqual(sorted(i["size"]["status"] for i in ti["ideas"]),
                         ["ok", "to_confirm", "too_wide"])
        ok = next(i for i in ti["ideas"] if i["size"]["status"] == "ok")
        self.assertIsNotNone(ok["size"]["lots"])            # an ok forex idea
        self.assertEqual(len(ti["skipped"]), 2)
        self.assertTrue(ti["over_cap"])
        self.assertGreater(ti["ties_at_cutoff"], 0)
        self.assertEqual(ti["account"]["source"], "default")
        self.assertTrue(any((i["since_close"] or {}).get("stop_crossed") for i in ti["ideas"]))
        self.assertTrue(any(h["symbol"] == "^GDAXI" for h in b["swing"]["hits"]))
        self.assertTrue(any(not h["setups"] and h["setups_short"]
                            for h in b["swing"]["hits"]))   # a short-only hit


if __name__ == "__main__":
    unittest.main()
