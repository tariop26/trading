"""Static HTML page of the briefing. Standard library only.

The template holds a marker; render_page() replaces it with the briefing JSON in a
<script type="application/json"> block. The page makes no network call: the inline
script of the template draws every section from that embedded JSON.
"""
import json

MARKER = "<!--BRIEFING_JSON-->"
BACKSLASH = chr(92)


def embed_json(briefing):
    """The briefing as a <script type="application/json"> block, safe inside HTML.

    "</" becomes "<" + backslash + "/", and "<!--" becomes backslash + "u003c!--";
    both stay valid JSON, so JSON.parse gives back the original strings.
    """
    raw = json.dumps(briefing, ensure_ascii=False)
    raw = raw.replace("<!--", BACKSLASH + "u003c!--")
    raw = raw.replace("</", "<" + BACKSLASH + "/")
    return '<script type="application/json" id="briefing">%s</script>' % raw


def render_page(briefing, template_path):
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    if MARKER not in template:
        raise ValueError("marqueur %s absent du gabarit %s" % (MARKER, template_path))
    return template.replace(MARKER, embed_json(briefing), 1)
