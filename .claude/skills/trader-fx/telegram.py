"""Send one Telegram message. Standard library only.

The Bot API address contains the token, so no reason ever carries an address, an exception text
or a response body: only "HTTP <code>" or "erreur réseau (<exception type>)". The text goes out
as plain text (no parse_mode), so characters such as "<" and "&" stay as they are.
"""
import json
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; trader-fx-alerts/1.0)"
TIMEOUT = 20
RETRY_DEFAULT_S = 5
RETRY_MAX_S = 30


def _http_post(url, payload, timeout):
    """-> (status, body). A network failure is (0, <exception type name>)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                          "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - the body is optional
            body = ""
        e.close()
        return e.code, body
    except Exception as e:  # noqa: BLE001 - report the type only, never the text
        return 0, type(e).__name__


def _retry_after(body):
    try:
        value = json.loads(body)["parameters"]["retry_after"]
    except (ValueError, KeyError, TypeError):
        return RETRY_DEFAULT_S
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return RETRY_DEFAULT_S
    return min(value, RETRY_MAX_S)


def send_message(token, chat_id, text, *, http_post=None, sleep=time.sleep):
    """-> (sent, reason). One more try after a 429 or a 5xx, at most two posts in all."""
    post = http_post or _http_post
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    payload = {"chat_id": chat_id, "text": text}
    status, body = 0, ""
    for attempt in (1, 2):
        try:
            status, body = post(url, payload, TIMEOUT)
        except Exception as e:  # noqa: BLE001 - an injected transport may raise: type only
            return False, "erreur réseau (%s)" % type(e).__name__
        if status == 200:
            return True, None
        if status == 0:
            return False, "erreur réseau (%s)" % body
        if attempt == 1 and (status == 429 or 500 <= status < 600):
            sleep(_retry_after(body) if status == 429 else RETRY_DEFAULT_S)
            continue
        break
    return False, "HTTP %d" % status
