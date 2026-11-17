"""SPIKE JETABLE : robustesse de (période N, écart K) autour de (160, 2.8). Même règles que bb_user.py, stop = 1.0 x distance(bande->médiane)."""
import bisect, json, math, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
UTC = timezone.utc
SESS = {"DAX": ("Europe/Berlin", (9, 0), (17, 30)), "NAS100": ("America/New_York", (9, 30), (16, 0)),
        "US30": ("America/New_York", (9, 30), (16, 0))}
GRID_N, GRID_K, KD = (160,), (2.8,), float(os.environ["KD"])

def main(folder, sym, out):
    (ts, o, h, l, c, sp), _ = R.load_1m(folder)
    nmin = len(ts)
    bts, bc, cur = [], [], None
    for i in range(nmin):
        b = ts[i] // 300 * 300
        if cur != b: bts.append(b); bc.append(c[i]); cur = b
        else: bc[-1] = c[i]
    ps, pq = [0.0], [0.0]
    for x in bc: ps.append(ps[-1] + x); pq.append(pq[-1] + x * x)
    ib, p = [0] * nmin, 0                                # dernière barre 5 min complète avant la minute
    for j in range(nmin):
        b = ts[j] // 300 * 300
        while p < len(bts) and bts[p] < b: p += 1
        ib[j] = p - 1
    tz = ZoneInfo(SESS[sym][0]); (oh, om), (ch, cm) = SESS[sym][1], SESS[sym][2]
    first, last = datetime.fromtimestamp(ts[0], UTC).date(), datetime.fromtimestamp(ts[-1], UTC).date()
    days, d = [], first
    while d <= last:
        if d.weekday() < 5:
            T0 = int(datetime(d.year, d.month, d.day, oh, om, tzinfo=tz).astimezone(UTC).timestamp())
            T1 = int(datetime(d.year, d.month, d.day, ch, cm, tzinfo=tz).astimezone(UTC).timestamp())
            k0, k1 = bisect.bisect_left(ts, T0), bisect.bisect_left(ts, T1)
            if k1 - k0 > 60: days.append((d, k0, k1))
        d += timedelta(days=1)
    res = {}
    for N in GRID_N:
        for K in GRID_K:
            bands = [None] * len(bts)
            for i in range(N - 1, len(bts)):
                s, q = ps[i+1] - ps[i+1-N], pq[i+1] - pq[i+1-N]
                m = s / N; v = q / N - m * m
                if v > 0: sd = math.sqrt(v); bands[i] = (m, m + K * sd, m - K * sd)
            def bd(j):
                i = ib[j]
                return bands[i] if i >= 0 and ts[j] // 300 * 300 - bts[i] <= 900 else None
            rows = []
            for d, k0, k1 in days:
                armed = {1: True, -1: True}
                j = k0
                while j < k1:
                    b = bd(j)
                    if b is None: j += 1; continue
                    M, U, L = b
                    if h[j] < U: armed[-1] = True
                    if l[j] + sp[j] > L: armed[1] = True
                    side = 0
                    if armed[-1] and h[j] >= U and not (l[j] + sp[j] <= L): side, entry = -1, U
                    elif armed[1] and l[j] + sp[j] <= L and not (h[j] >= U): side, entry = 1, L
                    if side == 0: j += 1; continue
                    armed[side] = False
                    risk = KD * abs(entry - M); stop = entry - side * risk
                    leg1 = leg2 = None; be = False; j2 = j; done = False
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
                    rows.append((d.year, 0.5 * leg1 + 0.5 * leg2))
                    j = j2 + 1
            res["%d|%.1f" % (N, K)] = rows
            print(sym, N, K, len(rows), flush=True)
    json.dump(res, open(out, "w"))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
