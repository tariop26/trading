import bisect, csv, math, os, sys, statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
UTC = timezone.utc
P = r"C:\Users\m.poirat\trading\2265877.positions.csv"
f = lambda x: float(x) if x else 0.0
pos = []
for r in list(csv.reader(open(P, encoding="utf-8-sig"), delimiter=";"))[1:]:
    if len(r) < 11 or r[1] == "Balance": continue
    pos.append(dict(t_in=datetime.strptime(r[0], "%Y.%m.%d %H:%M:%S"), side=r[1], vol=f(r[2]), pin=f(r[4]),
                    t_out=datetime.strptime(r[6], "%Y.%m.%d %H:%M:%S"), pout=f(r[7]), net=f(r[10]) + f(r[8]) + f(r[9])))
pos.sort(key=lambda x: x["t_in"])
(ts, o, h, l, c, sp), daily = R.load_1m(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fx_data", "XAUUSD"))
print("données :", datetime.fromtimestamp(ts[0], UTC), "->", datetime.fromtimestamp(ts[-1], UTC))
sample = [p for p in pos if datetime(2025, 1, 1) <= p["t_in"] <= datetime(2026, 9, 25)][::7]
def k_at(naive, shift_h):
    T = int((naive - timedelta(hours=shift_h)).replace(tzinfo=UTC).timestamp())
    k = bisect.bisect_left(ts, T); return k if k < len(ts) and ts[k] - T <= 90 else None
print("décalage (h) testé : écart médian entre le prix d'entrée du relevé et nos prix 1 min")
best = None
for sh in range(-3, 10):
    d = []
    for p in sample:
        k = k_at(p["t_in"], sh)
        if k is not None: d.append(min(abs(p["pin"] - o[k]), abs(p["pin"] - c[k])))
    if d:
        m = st.median(d); print("  %+d h : %.2f pts (n=%d)" % (sh, m, len(d)))
        if best is None or m < best[0]: best = (m, sh)
print("meilleur décalage :", best)

def k_ny7(naive):
    T = int(R.server_to_utc(naive).timestamp())
    k = bisect.bisect_left(ts, T); return k if k < len(ts) and ts[k] - T <= 90 else None
d = []
for p in sample:
    k = k_ny7(p["t_in"])
    if k is not None: d.append(min(abs(p["pin"] - o[k]), abs(p["pin"] - c[k])))
print("convention serveur = New York + 7 h : écart médian %.2f pts (n=%d)" % (st.median(d), len(d)))
# par saison pour la convention fixe +3 / +2
for lab, mn, mx in (("avril-octobre 2025", datetime(2025, 4, 7), datetime(2025, 10, 20)), ("décembre-février", datetime(2025, 12, 1), datetime(2026, 2, 28)), ("avril-octobre 2026", datetime(2026, 4, 7), datetime(2026, 9, 25))):
    for sh in (2, 3):
        dd = []
        for p in sample:
            if mn <= p["t_in"] <= mx:
                k = k_at(p["t_in"], sh)
                if k is not None: dd.append(min(abs(p["pin"] - o[k]), abs(p["pin"] - c[k])))
        if dd: print("  %s décalage +%d h : %.2f pts (n=%d)" % (lab, sh, st.median(dd), len(dd)))
