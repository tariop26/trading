"""SPIKE JETABLE : effets de calendrier sur barres 1 min. Hypothèses fixées avant les résultats.
C1 jour de la semaine : clôture 21:00 UTC veille -> clôture 21:00 UTC du jour (brut, t-stat, par période).
C2 tournant de mois : acheté à la clôture de l'avant-dernier jour ouvré, sorti à la clôture du 3e jour ouvré du mois suivant.
C3 emploi US (1er vendredi, 08:30 New York) : on suit (ou on contre) le sens du mouvement 08:25->08:35, sortie 10:30 New York.
Seuil fixé : |t| >= 3,3 (≈70 tests) ET même signe en exploration (<=2022) et confirmation (>=2023).
Pas de financement des positions nocturnes. Usage : python -I calendar_test.py dossier SYMBOLE
"""
import bisect, math, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
UTC = timezone.utc
NY = ZoneInfo("America/New_York")


def tstat(x):
    n = len(x)
    if n < 20:
        return None
    m = sum(x) / n
    sd = math.sqrt(sum((q - m) ** 2 for q in x) / (n - 1))
    return m, (m / (sd / math.sqrt(n)) if sd else 0.0), n


def split(rows):
    return ([v for d, v in rows if d.year <= 2022], [v for d, v in rows if d.year >= 2023], [v for d, v in rows])


def line(sym, label, rows, cost=0.0):
    out = []
    for lab, x in zip(("expl", "conf", "tout"), split(rows)):
        s = tstat(x)
        out.append("%s n/a" % lab if s is None else "%s %6.1f pb t=%5.2f (n=%d)" % (lab, s[0] * 1e4, s[1], s[2]))
    flag = ""
    a, b, c = (tstat(x) for x in split(rows))
    if a and b and c and abs(c[1]) >= 3.3 and a[0] * b[0] > 0:
        flag = "  <== SEUIL"
    print("%-7s %-30s %s | coût %.1f pb%s" % (sym, label, " | ".join(out), cost * 1e4, flag), flush=True)


def main(folder, sym):
    (ts, o, h, l, c, sp), _ = R.load_1m(folder)

    def at(T):
        k = bisect.bisect_left(ts, T)
        return k if k < len(ts) and ts[k] - T <= 300 else None

    def U(d, hh, mm=0, tz=UTC):
        return int(datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(UTC).timestamp())

    first, last = datetime.fromtimestamp(ts[0], UTC).date(), datetime.fromtimestamp(ts[-1], UTC).date()
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    wk = [d for d in days if d.weekday() < 5]
    close_k = {}
    for d in wk:
        k = at(U(d, 21))
        if k is not None:
            close_k[d] = k
    cd = sorted(close_k)
    # ---- rendements brut jour par jour (clôture à clôture)
    daily = []
    for d0, d1 in zip(cd, cd[1:]):
        if (d1 - d0).days > 4:
            continue
        k1, k2 = close_k[d0], close_k[d1]
        daily.append((d1, (o[k2] - o[k1]) / o[k1], sp[k1] / o[k1]))
    avg_cost = sum(x[2] for x in daily) / len(daily)
    names = ["lun", "mar", "mer", "jeu", "ven"]
    for w in range(5):
        rows = [(d, g) for d, g, _ in daily if d.weekday() == w]
        line(sym, "C1 %s (brut, long)" % names[w], rows, avg_cost)
    # ---- tournant de mois
    by_month = {}
    for d in cd:
        by_month.setdefault((d.year, d.month), []).append(d)
    keys = sorted(by_month)
    rows, base = [], []
    for (y, m), nxt in zip(keys, keys[1:]):
        a, b = by_month[(y, m)], by_month[nxt]
        if len(a) < 5 or len(b) < 5 or (nxt[0] * 12 + nxt[1]) - (y * 12 + m) != 1:
            continue
        k1, k2 = close_k[a[-2]], close_k[b[2]]
        rows.append((b[2], (o[k2] - o[k1]) / o[k1]))
    for i in range(len(cd) - 4):
        k1, k2 = close_k[cd[i]], close_k[cd[i + 4]]
        if (cd[i + 4] - cd[i]).days <= 7:
            base.append((cd[i + 4], (o[k2] - o[k1]) / o[k1]))
    bm = sum(v for _, v in base) / len(base)
    line(sym, "C2 tournant de mois (brut)", rows, avg_cost)
    line(sym, "C2 exces vs fenetre 4 j", [(d, v - bm) for d, v in rows], avg_cost)
    # ---- emploi US
    rows_f, rows_m = [], []
    for d in wk:
        if d.weekday() != 4 or d.day > 7:
            continue
        k0, k1, k2 = at(U(d, 8, 25, NY)), at(U(d, 8, 35, NY)), at(U(d, 10, 30, NY))
        if None in (k0, k1, k2) or not (k0 < k1 < k2):
            continue
        move = o[k1] - o[k0]
        if move == 0:
            continue
        sgn = 1 if move > 0 else -1
        g = (o[k2] - o[k1]) / o[k1]
        cost = sp[k1] / o[k1] + sp[k2] / o[k1]
        rows_f.append((d, sgn * g - cost))
        rows_m.append((d, -sgn * g - cost))
    line(sym, "C3 NFP suivre (net)", rows_f)
    line(sym, "C3 NFP contrer (net)", rows_m)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
