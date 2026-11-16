"""Static HTML page of the briefing. Standard library only.

The template holds a marker; render_page() replaces it with the briefing JSON in a
<script type="application/json"> block. The page makes no network call: the inline
script of the template draws every section from that embedded JSON.
"""
import json
import re

MARKER = "<!--BRIEFING_JSON-->"
BACKSLASH = chr(92)


def embed_json(briefing, script_id="briefing"):
    """The document as a <script type="application/json"> block, safe inside HTML.

    `script_id` is the id of the block; it holds lowercase letters and hyphens only (ValueError
    otherwise), so it can never break out of the attribute.

    "</" becomes "<" + backslash + "/", and "<!--" becomes backslash + "u003c!--";
    both stay valid JSON, so JSON.parse gives back the original strings.
    """
    if not isinstance(script_id, str) or not re.fullmatch(r"[a-z-]+", script_id):
        raise ValueError("script_id invalide : %r" % (script_id,))
    raw = json.dumps(briefing, ensure_ascii=False)
    raw = raw.replace("<!--", BACKSLASH + "u003c!--")
    raw = raw.replace("</", "<" + BACKSLASH + "/")
    return '<script type="application/json" id="%s">%s</script>' % (script_id, raw)


def render_page(briefing, template_path, script_id="briefing"):
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    if MARKER not in template:
        raise ValueError("marqueur %s absent du gabarit %s" % (MARKER, template_path))
    return template.replace(MARKER, embed_json(briefing, script_id), 1)


SKELETON = ('<!doctype html>\n<html lang="%s">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n')


def standalone(html, lang="fr"):
    """The page as a document of its own, for a host that serves the file as is (GitHub Pages).

    The template is written for the Artifact wrapper, which adds the doctype, the charset and the
    viewport meta itself; served bare, a phone would draw it at desktop width, shrunk. The skeleton
    opens <html> and <head>; the template's own <title>, <link>, <meta> and <style> then fall in the
    head and <main> starts the body. A page that already has a doctype is returned unchanged."""
    if not isinstance(lang, str) or not re.fullmatch(r"[a-z]{2}(-[A-Za-z]+)?", lang):
        raise ValueError("lang invalide : %r" % (lang,))
    if html.lstrip()[:9].lower() == "<!doctype":
        return html
    return SKELETON % lang + html
