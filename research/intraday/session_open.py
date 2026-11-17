"""SPIKE JETABLE : effets d'ouverture de session, 3 hypothèses fixées d'avance.
H1 devises : EURUSD/GBPUSD vendus 07:00-13:00 UTC puis achetés 13:00-21:00 UTC ; USDJPY acheté 00:00-07:00 UTC.
H2 indices : acheté de la clôture cash à l'ouverture cash suivante (sans financement CFD).
H3 plage d'ouverture Londres (08:00-08:30 Londres) : première clôture 15 min hors plage entre 08:45 et 12:00, tenue jusqu'à 16:30 Londres.
Coût : un spread par aller-retour. Usage : session_open.py dossier SYMBOLE
"""
import bisect, math, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
UTC = timezone.utc

def report(sym, label, rows):
    for lab, lo, hi in (("exploration", 0, 2022), ("confirmation", 2023, 9999), ("TOUT", 0, 9999)):
        x = [n for d, n in rows if lo <= d.year <= hi]
        if len(x) < 30:
            print("%-7s %-34s %-12s n=%d (insuffisant)" % (sym, label, lab, len(x))); continue
        m = sum(x) / len(x); sd = math.sqrt(sum((q - m) ** 2 for q in x) / (len(x) - 1))
        print("%-7s %-34s %-12s n=%4d net %6.2f pb  t=%5.2f  Sharpe %5.2f  gagnants %4.1f%%" % (
            sym, label, lab, len(x), m * 1e4, m / (sd / math.sqrt(len(x))) if sd else 0,
            m / sd * math.sqrt(252) if sd else 0, 100.0 * sum(1 for q in x if q > 0) / len(x)))

def main(folder, sym):
    (ts, o, h, l, c, sp), _ = R.load_1m(folder)
    def at(T):
        k = bisect.bisect_left(ts, T)
        return k if k < len(ts) and ts[k] - T <= 300 else None
    def trade(k1, k2, side):          # side +1 acheteur, -1 vendeur ; prix = bid
        p1, p2 = o[k1], o[k2]
        return ((p2 - p1 - sp[k1]) / p1) if side > 0 else ((p1 - p2 - sp[k2]) / p1)
    first, last = datetime.fromtimestamp(ts[0], UTC).date(), datetime.fromtimestamp(ts[-1], UTC).date()
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    def U(d, hh, mm=0, tz=UTC):
        return int(datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(UTC).timestamp())

    if sym in ("EURUSD", "GBPUSD", "USDJPY"):
        wins = {"EURUSD": [("vendu Europe 07-13 UTC", 7, 13, -1), ("acheté US 13-21 UTC", 13, 21, +1)],
                "GBPUSD": [("vendu Europe 07-13 UTC", 7, 13, -1), ("acheté US 13-21 UTC", 13, 21, +1)],
                "USDJPY": [("acheté Tokyo 00-07 UTC", 0, 7, +1)]}[sym]
        for label, a, b, side in wins:
            rows = []
            for d in (x for x in days if x.weekday() < 5):
                k1, k2 = at(U(d, a)), at(U(d, b))
                if k1 is not None and k2 is not None and k2 > k1:
                    rows.append((d, trade(k1, k2, side)))
            report(sym, "H1 " + label, rows)
    if sym in ("DAX", "NAS100", "US30"):
        tzn, (oh, om), (ch, cm) = {"DAX": ("Europe/Berlin", (9, 0), (17, 30)),
                                   "NAS100": ("America/New_York", (9, 30), (16, 0)),
                                   "US30": ("America/New_York", (9, 30), (16, 0))}[sym]
        tz = ZoneInfo(tzn); rows = []
        wk = [x for x in days if x.weekday() < 5]
        for d0, d1 in zip(wk, wk[1:]):
            if (d1 - d0).days > 4: continue
            k1, k2 = at(U(d0, ch, cm, tz)), at(U(d1, oh, om, tz))
            if k1 is not None and k2 is not None and k2 > k1:
                rows.append((d1, trade(k1, k2, +1)))
        report(sym, "H2 nuit (clôture -> ouverture)", rows)
    if sym in ("EURUSD", "GBPUSD", "XAUUSD"):
        tz = ZoneInfo("Europe/London"); rows = []
        for d in (x for x in days if x.weekday() < 5):
            ks, ke, kx = at(U(d, 8, 0, tz)), at(U(d, 8, 30, tz)), at(U(d, 16, 30, tz))
            if None in (ks, ke, kx) or not (ks < ke < kx): continue
            hi, lo = max(h[ks:ke]), min(l[ks:ke])
            for mins in range(15, 211, 15):          # 08:45 ... 12:00 Londres
                T = U(d, 8, 30, tz) + mins * 60
                k = at(T)
                if k is None or k >= kx: break
                px = o[k]                              # dernier prix connu à T (clôture de la barre précédente)
                if px > hi: rows.append((d, trade(k, kx, +1))); break
                if px < lo: rows.append((d, trade(k, kx, -1))); break
        report(sym, "H3 cassure plage Londres 08:00-08:30", rows)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
