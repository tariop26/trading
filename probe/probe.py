"""THROWAWAY spike: can GitHub Actions runners reach the data sources the alert runner needs?

Reads three public endpoints (Yahoo v8 chart on query2 and query1, the economic calendar feed)
and, only if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID exist in the environment, sends one test
message. It prints one line per probe and never prints a secret (the Telegram URL holds the
token, so errors are reported by type and HTTP status only). Standard library only.
Exit code is always 0: the verdict is read from the log.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; trader-fx-probe/0.1)"
YAHOO = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
SYMBOLS = ("EURUSD=X", "GC=F", "^FCHI")
CALENDAR = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
LINES = []


def say(line):
    LINES.append(line)
    print(line, flush=True)


def get(url, timeout=20):
    """-> (http status or None, body text or '', seconds, error type or None)."""
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), time.time() - t0, None
    except urllib.error.HTTPError as e:
        e.close()
        return e.code, "", time.time() - t0, None
    except Exception as e:  # noqa: BLE001 - report the type only
        return None, "", time.time() - t0, type(e).__name__


def probe_yahoo():
    ok = 0
    for host in YAHOO:
        for sym in SYMBOLS:
            path = "/v8/finance/chart/%s?range=5d&interval=1h" % urllib.request.quote(sym, safe="")
            status, body, secs, err = get(host + path)
            bars, last = 0, None
            if status == 200:
                try:
                    res = json.loads(body)["chart"]["result"][0]
                    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
                    bars, last = len(closes), closes[-1] if closes else None
                except (ValueError, KeyError, IndexError, TypeError):
                    status = "200 but unreadable body"
            say("YAHOO %s %-9s status=%s bars=%s last=%s %.1fs%s" % (
                host.split("//")[1].split(".")[0], sym, status, bars, last, secs,
                " error=%s" % err if err else ""))
            if status == 200 and bars:
                ok += 1
    return ok


def probe_calendar():
    status, body, secs, err = get(CALENDAR)
    events = None
    if status == 200:
        try:
            events = len(json.loads(body))
        except ValueError:
            status = "200 but not JSON"
    say("CALENDAR status=%s events=%s %.1fs%s" % (status, events, secs,
                                                  " error=%s" % err if err else ""))
    return status == 200 and bool(events)


def probe_telegram():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        say("TELEGRAM skipped: secrets TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
        return None
    text = "Test trader-fx : GitHub Actions peut vous écrire. Aucune action requise."
    body = json.dumps({"chat_id": chat, "text": text}).encode("utf-8")
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendMessage" % token, data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status, err = r.status, None
    except urllib.error.HTTPError as e:
        status, err = e.code, None
        e.close()
    except Exception as e:  # noqa: BLE001 - never echo the URL (it contains the token)
        status, err = None, type(e).__name__
    say("TELEGRAM status=%s%s" % (status, " error=%s" % err if err else ""))
    return status == 200


def main():
    say("probe started %s UTC, python %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
                                              sys.version.split()[0]))
    yahoo_ok = probe_yahoo()
    cal_ok = probe_calendar()
    tg_ok = probe_telegram()
    verdict = "YAHOO %d/%d probes ok; CALENDAR %s; TELEGRAM %s" % (
        yahoo_ok, len(YAHOO) * len(SYMBOLS), "ok" if cal_ok else "FAILED",
        "not tested" if tg_ok is None else "ok" if tg_ok else "FAILED")
    say("VERDICT " + verdict)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Probe trader-fx\n\n```\n" + "\n".join(LINES) + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
