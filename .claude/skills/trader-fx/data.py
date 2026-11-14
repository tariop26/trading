"""Yahoo Finance v8 chart bars with a small on-disk cache. Standard library only.

fetch_bars() never raises for a bad symbol: failures come back in the second
element of the result, so one broken pair does not stop the briefing.
"""
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

# (ts_utc, open, high, low, close)
Bar = tuple

PAUSE = 0.3
BACKOFF = 5.0
TTL_DAILY = 21600
TTL_INTRADAY = 600
DAILY = ("1d", "6mo")
HOURLY = ("1h", "5d")

UA = "Mozilla/5.0 (compatible; trader-fx/1.0)"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")


class DataError(Exception):
    pass


@dataclass
class Series:
    bars: list
    gmtoffset: int
    age_s: "float | None" = None


# ---------------------------------------------------------------- network

def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def chart_path(sym, interval, rng):
    return "/v8/finance/chart/%s?range=%s&interval=%s" % (
        urllib.parse.quote(sym, safe=""), rng, interval)


def yahoo_get(path, http_get, sleep):
    """GET a Yahoo path. query2 first, query1 on a 429 or 5xx, and one more round
    after BACKOFF seconds if a 429 was seen. A 4xx other than 429 is final, unless
    its body is Yahoo's JSON error, which the caller parses."""
    last = "no answer"
    for attempt in (0, 1):
        saw_429 = False
        for host in YAHOO_HOSTS:
            try:
                return http_get(host + path)
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
                body = ""
                try:
                    if 400 <= e.code < 500 and e.code != 429:
                        body = e.read().decode("utf-8", "replace")
                except Exception:
                    body = ""
                finally:
                    e.close()
                if e.code == 429:
                    saw_429 = True
                    continue
                if e.code >= 500:
                    continue
                if body.strip().startswith("{"):
                    return body
                raise DataError("Yahoo answered %s" % last)
            except (urllib.error.URLError, OSError) as e:
                last = str(getattr(e, "reason", e))
                continue
        if attempt == 0 and saw_429:
            sleep(BACKOFF)
            continue
        break
    raise DataError("Yahoo answered %s" % last)


# ---------------------------------------------------------------- parsing

def _num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def parse_chart(text, sym):
    """Yahoo v8 chart JSON -> Series. Any bar with a null price is dropped."""
    try:
        doc = json.loads(text)
        chart = doc["chart"]
    except (ValueError, KeyError, TypeError):
        raise DataError("no data: unreadable answer for %s" % sym)
    if not isinstance(chart, dict):
        raise DataError("no data: unreadable answer for %s" % sym)
    result = chart.get("result")
    if not result:
        err = chart.get("error")
        desc = err.get("description") if isinstance(err, dict) else None
        raise DataError("no data: %s" % (desc or "empty answer for %s" % sym))
    try:
        r = result[0]
        ts = r["timestamp"]
        q = r["indicators"]["quote"][0]
        cols = [q["open"], q["high"], q["low"], q["close"]]
    except (KeyError, IndexError, TypeError):
        raise DataError("no data: no bars for %s" % sym)
    bars = []
    for i, t in enumerate(ts):
        try:
            px = [c[i] for c in cols]
        except IndexError:
            break
        if _num(t) and all(_num(p) for p in px):
            bars.append((int(t), float(px[0]), float(px[1]), float(px[2]), float(px[3])))
    if not bars:
        raise DataError("no data: no usable bars for %s" % sym)
    meta = r.get("meta")
    off = meta.get("gmtoffset") if isinstance(meta, dict) else 0
    return Series(bars=bars, gmtoffset=int(off) if _num(off) else 0)


# ---------------------------------------------------------------- cache

def cache_path(cache_dir, sym, interval, rng):
    name = re.sub(r"[^A-Za-z0-9._-]", "_", "%s_%s_%s" % (sym, interval, rng))
    return os.path.join(cache_dir, name + ".json")


def read_cache(path):
    """-> (fetched_at, Series) or None for a missing, empty or corrupt file."""
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        fetched_at = c["fetched_at"]
        gmtoffset = c["gmtoffset"]
        raw = c["bars"]
        if not (_num(fetched_at) and _num(gmtoffset) and isinstance(raw, list) and raw):
            return None
        bars = []
        for b in raw:
            if not (isinstance(b, list) and len(b) == 5 and all(_num(x) for x in b)):
                return None
            bars.append((int(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4])))
        return float(fetched_at), Series(bars=bars, gmtoffset=int(gmtoffset))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_cache(path, fetched_at, series):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": fetched_at, "gmtoffset": series.gmtoffset,
                       "bars": [list(b) for b in series.bars]}, f)
        os.replace(tmp, path)
    except OSError:
        pass  # a cache that cannot be written is not an error


# ---------------------------------------------------------------- public

def fetch_bars(symbols, interval, rng, *, cache_dir, ttl_s, use_cache=True,
               now=None, http_get=None, sleep=time.sleep, workers=1):
    """-> ({symbol: Series}, [{"symbol", "reason"}]), both in input order.

    A fresh cache file (younger than ttl_s) is used without any request. After a
    network failure a stale cache is still returned, with Series.age_s set to its
    age. use_cache=False neither reads nor falls back to the cache.

    workers=1 (default) is sequential: PAUSE seconds between two real requests.
    workers>1 fetches with that many threads; each task sleeps PAUSE before its own
    real request (never for a cache hit), so http_get and sleep must be usable from
    several threads at once. Results never depend on completion order."""
    http_get = http_get or _http_get
    now = time.time() if now is None else now

    def one(sym, pause):
        """-> ("ok", Series) or ("fail", reason), and whether a request was made."""
        path = cache_path(cache_dir, sym, interval, rng) if cache_dir else None
        cached = read_cache(path) if (path and use_cache) else None
        if cached and 0 <= now - cached[0] <= ttl_s:
            return ("ok", cached[1]), False
        if pause:
            sleep(PAUSE)
        try:
            series = parse_chart(yahoo_get(chart_path(sym, interval, rng), http_get, sleep), sym)
        except DataError as e:
            if cached:
                cached[1].age_s = max(0.0, now - cached[0])
                return ("ok", cached[1]), True
            return ("fail", str(e)), True
        if path:
            write_cache(path, now, series)
        return ("ok", series), True

    symbols = list(symbols)
    if workers > 1 and len(symbols) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = [r for r, _ in pool.map(lambda sym: one(sym, True), symbols)]
    else:
        results, requested = [], False
        for sym in symbols:
            r, did = one(sym, requested)
            results.append(r)
            requested = requested or did
    out, failed = {}, []
    for sym, (kind, value) in zip(symbols, results):
        if kind == "ok":
            out[sym] = value
        else:
            failed.append({"symbol": sym, "reason": value})
    return out, failed
