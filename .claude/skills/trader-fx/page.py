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
