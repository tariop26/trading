"""Rapport du rejeu : python -I report.py sortie1.json sortie2.json ...  (SPIKE JETABLE)

Périodes : exploration 2016-2022, confirmation 2023-2026 (aucun paramètre retouché entre les deux).
"""
import json
import math
import statistics as st
import sys
from collections import defaultdict


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def mean_ci(v):
    if len(v) < 2:
        return (v[0] if v else float("nan"), float("nan"), float("nan"))
    s = st.stdev(v) / math.sqrt(len(v))
    m = st.mean(v)
    return m, m - 1.96 * s, m + 1.96 * s


def period(t):
    return "2016-2022 (exploration)" if int(t["at"][:4]) <= 2022 else "2023-2026 (confirmation)"


def table(title, trades, key):
    groups = defaultdict(list)
    for t in trades:
        ks = key(t)
        for k in (ks if isinstance(ks, list) else [ks]):
            groups[k].append(t)
    print("\n== %s" % title)
    print("%-26s %7s %6s %7s %8s %19s %7s %7s" % (
        "groupe", "alertes", "pris", "cible%", "R moyen", "IC95 R moyen", "miroir", "temps%"))
    for k in sorted(groups):
        ts = groups[k]
        f = [t for t in ts if t["res"].get("filled")]
        if not f:
            print("%-26s %7d %6d" % (k, len(ts), 0))
            continue
        rs = [t["res"]["r"] for t in f]
        mr = [t["mirror"]["r"] for t in f if t["mirror"].get("filled")]
        wins = sum(1 for t in f if t["res"]["exit"] == "target")
        m, lo, hi = mean_ci(rs)
        print("%-26s %7d %6d %6.1f%% %8.3f %8.3f ; %6.3f %7.3f %6.0f%%" % (
            k, len(ts), len(f), 100.0 * wins / len(f), m, lo, hi,
            st.mean(mr) if mr else float("nan"),
            100.0 * sum(1 for t in f if t["res"]["exit"] == "time") / len(f)))


def paired(title, trades):
    f = [t for t in trades if t["res"].get("filled") and t["mirror"].get("filled")]
    if len(f) < 2:
        return
    d = [t["res"]["r"] - t["mirror"]["r"] for t in f]
    m, lo, hi = mean_ci(d)
    days = defaultdict(float)
    for t in f:
        days[t["at"][:10]] += t["res"]["r"]
    dm, dlo, dhi = mean_ci(list(days.values()))
    print("%-34s n=%5d  signal-miroir %.3f [%.3f ; %.3f]   R/jour %.2f [%.2f ; %.2f] sur %d jours" % (
        title, len(f), m, lo, hi, dm, dlo, dhi, len(days)))


if __name__ == "__main__":
    allt = []
    for path in sys.argv[1:]:
        doc = json.load(open(path, encoding="utf-8"))
        for t in doc["trades"]:
            t["sym"] = doc["symbol"]
        allt += doc["trades"]
        print("%s : %d alertes ; diagnostic %s" % (doc["symbol"], len(doc["trades"]), doc["diag"]))
    table("par symbole", allt, lambda t: t["sym"])
    table("par période", allt, period)
    table("par symbole et période", allt, lambda t: "%s %s" % (t["sym"], period(t)[:9]))
    table("par famille principale (toutes périodes)", allt, lambda t: t["primary"])
    table("famille principale, confirmation 2023-2026",
          [t for t in allt if int(t["at"][:4]) >= 2023], lambda t: t["primary"])
    table("par sens", allt, lambda t: t["side"])
    table("par année", allt, lambda t: t["at"][:4])
    print("\n== écart signal - miroir (appariés) et R par jour d'alerte")
    paired("tous", allt)
    for sym in sorted({t["sym"] for t in allt}):
        paired(sym, [t for t in allt if t["sym"] == sym])
    paired("exploration 2016-2022", [t for t in allt if int(t["at"][:4]) <= 2022])
    paired("confirmation 2023-2026", [t for t in allt if int(t["at"][:4]) >= 2023])
