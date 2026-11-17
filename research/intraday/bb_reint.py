"""SPIKE JETABLE : entrée à la réintégration (BB 160, 2.8, barres 5 min), stop au-delà de l'extrême de la mèche.
Signal : une barre 5 min dont la clôture est revenue dans la bande après une excursion (extrême = max/min des highs/lows
de l'excursion, bandes de la barre précédente). Entrée au marché à la minute suivante. TP1 50 % médiane -> BE ; TP2 50 % bande opposée.
Un trade à la fois ; fin de séance : sortie au marché."""
import bisect, json, math, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
UTC = timezone.utc
SESS = {"DAX": ("Europe/Berlin", (9, 0), (17, 30)), "NAS100": ("America/New_York", (9, 30), (16, 0)),
        "US30": ("America/New_York", (9, 30), (16, 0))}
N, K = 160, 2.8

def main(folder, sym, out):
    (ts, o, h, l, c, sp), _ = R.load_1m(folder)
    nmin = len(ts)
    bts, bh, bl, bc, cur = [], [], [], [], None          # barres 5 min complètes
    for i in range(nmin):
        b = ts[i] // 300 * 300
        if cur != b: bts.append(b); bh.append(h[i]); bl.append(l[i]); bc.append(c[i]); cur = b
        else: bh[-1] = max(bh[-1], h[i]); bl[-1] = min(bl[-1], l[i]); bc[-1] = c[i]
    ps, pq = [0.0], [0.0]
    for x in bc: ps.append(ps[-1] + x); pq.append(pq[-1] + x * x)
    bands = [None] * len(bts)
    for i in range(N - 1, len(bts)):
        s, q = ps[i+1] - ps[i+1-N], pq[i+1] - pq[i+1-N]
        m = s / N; v = q / N - m * m
        if v > 0: sd = math.sqrt(v); bands[i] = (m, m + K * sd, m - K * sd)
    ib, p = [0] * nmin, 0
    for j in range(nmin):
        b = ts[j] // 300 * 300
        while p < len(bts) and bts[p] < b: p += 1
        ib[j] = p - 1
    def bd(j):
        i = ib[j]
        return bands[i] if i >= 0 and ts[j] // 300 * 300 - bts[i] <= 900 else None
    tz = ZoneInfo(SESS[sym][0]); (oh, om), (ch, cm) = SESS[sym][1], SESS[sym][2]
    first, last = datetime.fromtimestamp(ts[0], UTC).date(), datetime.fromtimestamp(ts[-1], UTC).date()
    rows = []
    d = first
    while d <= last:
        if d.weekday() < 5:
            T0 = int(datetime(d.year, d.month, d.day, oh, om, tzinfo=tz).astimezone(UTC).timestamp())
            T1 = int(datetime(d.year, d.month, d.day, ch, cm, tzinfo=tz).astimezone(UTC).timestamp())
            k0, k1 = bisect.bisect_left(ts, T0), bisect.bisect_left(ts, T1)
            if k1 - k0 > 60:
                i0, i1 = bisect.bisect_left(bts, T0), bisect.bisect_left(bts, T1)
                ext_up = ext_dn = None
                free_ts = 0
                for i in range(max(i0, 1), i1):
                    pb = bands[i - 1]
                    if pb is None or bts[i] - bts[i - 1] > 900: ext_up = ext_dn = None; continue
                    M, U, L = pb
                    if bh[i] >= U: ext_up = bh[i] if ext_up is None else max(ext_up, bh[i])
                    if bl[i] <= L: ext_dn = bl[i] if ext_dn is None else min(ext_dn, bl[i])
                    side, ext = 0, None
                    if ext_up is not None and bc[i] < U: side, ext = -1, ext_up; ext_up = None
                    elif ext_dn is not None and bc[i] > L: side, ext = 1, ext_dn; ext_dn = None
                    if side == 0: continue
                    tsig = bts[i] + 300
                    if tsig < free_ts: continue
                    k = bisect.bisect_left(ts, tsig)
                    if k >= k1 or ts[k] - tsig > 120: continue
                    entry = o[k] + sp[k] if side > 0 else o[k]
                    stop = ext - 0.0 if side > 0 else ext + sp[k]
                    risk = (entry - stop) if side > 0 else (stop - entry)
                    if risk <= 0: continue
                    be = False; leg1 = leg2 = None; j2 = k; done = False
                    while j2 < k1:
                        b2 = bd(j2)
                        if b2 is None: j2 += 1; continue
                        M2, U2, L2 = b2; stp = entry if be else stop
                        if side > 0:
                            if l[j2] <= stp:
                                if leg1 is None: leg1 = leg2 = -1.0
                                else: leg2 = 0.0
                                done = True; break
                            if leg1 is None and h[j2] >= M2: leg1 = (M2 - entry) / risk; be = True
                            if leg1 is not None and h[j2] >= U2: leg2 = (U2 - entry) / risk; done = True; break
                        else:
                            if h[j2] + sp[j2] >= stp:
                                if leg1 is None: leg1 = leg2 = -1.0
                                else: leg2 = 0.0
                                done = True; break
                            if leg1 is None and l[j2] + sp[j2] <= M2: leg1 = (entry - M2) / risk; be = True
                            if leg1 is not None and l[j2] + sp[j2] <= L2: leg2 = (entry - L2) / risk; done = True; break
                        j2 += 1
                    if not done:
                        e = min(j2, k1) - 1
                        px = c[e] if side > 0 else c[e] + sp[e]
                        rr = ((px - entry) if side > 0 else (entry - px)) / risk
                        if leg1 is None: leg1 = leg2 = rr
                        else: leg2 = rr
                    free_ts = ts[min(j2, nmin - 1)]
                    rows.append((d.year, 0.5 * leg1 + 0.5 * leg2, risk / sp[k] if sp[k] > 0 else 99.0, side))
        d += timedelta(days=1)
    json.dump(rows, open(out, "w"))
    print(sym, len(rows))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
