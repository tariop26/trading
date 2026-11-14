"""Currency strength and signal clusters for the forex scan (stdlib only)."""
import math

CURRENCIES = ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD")


def pair_currencies(symbol):
    """'EURUSD=X' -> ('EUR', 'USD'); None if not a forex pair XXXYYY=X."""
    if not isinstance(symbol, str) or not symbol.endswith("=X"):
        return None
    body = symbol[:-2]
    if len(body) != 6 or not body.isalpha():
        return None
    body = body.upper()
    return body[:3], body[3:]


def _log_return(closes, n):
    if len(closes) < n + 1:
        return None
    a, b = closes[-1 - n], closes[-1]
    if not a or not b or a <= 0 or b <= 0:
        return None
    return math.log(b / a)


def currency_strength(closes_by_symbol, windows=(1, 5, 20)):
    out = {}
    for n in windows:
        sums = {}
        counts = {}
        for symbol, closes in closes_by_symbol.items():
            ccys = pair_currencies(symbol)
            if ccys is None or any(c not in CURRENCIES for c in ccys):
                continue
            r = _log_return(closes, n)
            if r is None:
                continue
            base, quote = ccys
            for ccy, sign in ((base, 1.0), (quote, -1.0)):
                sums[ccy] = sums.get(ccy, 0.0) + sign * r * 100.0
                counts[ccy] = counts.get(ccy, 0) + 1
        rows = [{"ccy": c, "score": sums[c] / counts[c]} for c in sums]
        rows.sort(key=lambda row: -row["score"])
        out["%dd" % n] = rows
    return out


def clusters(hits):
    pairs = []
    for hit in hits:
        ccys = pair_currencies(hit.get("symbol"))
        if ccys is not None:
            pairs.append(ccys)
    of = len(pairs)
    counts = {}
    for ccys in pairs:
        for c in set(ccys):
            counts[c] = counts.get(c, 0) + 1
    rows = [
        {"ccy": c, "count": k, "of": of}
        for c, k in counts.items()
        if k >= 3 and k / of >= 0.5
    ]
    rows.sort(key=lambda row: (-row["count"], row["ccy"]))
    return rows
