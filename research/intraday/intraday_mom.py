"""SPIKE JETABLE : momentum intraday, règles fixées d'avance.
A (Gao et al.) : r1 = clôture veille -> ouverture+30 min ; position = sens de r1 pendant les 30 dernières minutes.
B : r = ouverture -> ouverture+30 min ; position = sens de r de ouverture+30 min à la clôture.
Coût : un spread par aller-retour (achat à l'ask, vente au bid). Usage : intraday_mom.py dossier SYMBOLE
"""
import bisect, math, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R

SESS = {"DAX": [("DAX Xetra 09:00-17:30", "Europe/Berlin", (9, 0), (17, 30))],
        "NAS100": [("NY 09:30-16:00", "America/New_York", (9, 30), (16, 0))],
        "US30": [("NY 09:30-16:00", "America/New_York", (9, 30), (16, 0))],
        "XAUUSD": [("Londres 08:00-16:30", "Europe/London", (8, 0), (16, 30)),
                   ("NY 09:30-16:00", "America/New_York", (9, 30), (16, 0))]}
UTC = timezone.utc

def run(folder, sym):
    (ts, o, h, l, c, sp), _ = R.load_1m(folder)
    def at(T):
        k = bisect.bisect_left(ts, T)
        return k if k < len(ts) and ts[k] - T <= 300 else None
    first, last = datetime.fromtimestamp(ts[0], UTC).date(), datetime.fromtimestamp(ts[-1], UTC).date()
    for label, tzname, (oh, om), (ch, cm) in SESS[sym]:
        tz = ZoneInfo(tzname)
        rows = {"A": [], "B": []}
        prev_close = None
        d = first
        while d <= last:
            if d.weekday() < 5:
                def T(hh, mm): return int(datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(UTC).timestamp())
                to, t30, tc30, tc = T(oh, om), T(oh, om) + 1800, T(ch, cm) - 1800, T(ch, cm)
                ko, k30, kc30, kc = at(to), at(t30), at(tc30), at(tc)
                if None not in (ko, k30, kc30, kc):
                    po, p30, pc30, pc = o[ko], o[k30], o[kc30], o[kc]
                    if prev_close:
                        r1 = p30 / prev_close - 1
                        if r1:
                            s = 1 if r1 > 0 else -1
                            net = (pc - pc30 - sp[kc30]) / pc30 if s > 0 else (pc30 - pc - sp[kc]) / pc30
                            rows["A"].append((d, net, (pc / pc30 - 1)))
                    rb = p30 / po - 1
                    if rb:
                        s = 1 if rb > 0 else -1
                        net = (pc - p30 - sp[k30]) / p30 if s > 0 else (p30 - pc - sp[kc]) / p30
                        rows["B"].append((d, net, (pc / p30 - 1)))
                    prev_close = pc
                else:
                    prev_close = None
            d += timedelta(days=1)
        for name in ("A", "B"):
            for lab, lo, hi in (("2018-2022", 2000, 2022), ("2023-2026", 2023, 2100), ("TOUT", 2000, 2100)):
                v = [(n, raw) for dd, n, raw in rows[name] if lo <= dd.year <= hi]
                if len(v) < 20:
                    print("%-6s %-22s %s %-10s n=%d (insuffisant)" % (sym, label, name, lab, len(v))); continue
                x = [a for a, _ in v]; raw = [b for _, b in v]
                m = sum(x) / len(x); sd = math.sqrt(sum((q - m) ** 2 for q in x) / (len(x) - 1))
                t = m / (sd / math.sqrt(len(x))) if sd else 0
                print("%-6s %-22s %s %-10s n=%4d  net %6.2f pb/trade  t=%5.2f  Sharpe %5.2f  gagnants %4.1f%%  derive(temoin) %6.2f pb" % (
                    sym, label, name, lab, len(x), m * 1e4, t, m / sd * math.sqrt(252) if sd else 0,
                    100.0 * sum(1 for q in x if q > 0) / len(x), sum(raw) / len(raw) * 1e4))

if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
