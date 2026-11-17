"""SPIKE JETABLE : stratégie utilisateur. Reverse sur touche de la bande de Bollinger 5 min (160, 2.8).
Entrée limite sur la bande ; TP1 (50 %) à la bande médiane puis stop au point mort ; TP2 (50 %) à la bande opposée ;
stop initial = k x distance(bande -> médiane), k in {0.5, 1.0} ; heures de bourse ; clôture forcée en fin de séance.
Bandes recalculées à chaque clôture 5 min (dernière barre complète) ; spread : achat à l'ask, vente au bid."""
import bisect, json, math, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
UTC = timezone.utc
SESS = {"DAX": ("Europe/Berlin", (9, 0), (17, 30)), "NAS100": ("America/New_York", (9, 30), (16, 0)),
        "US30": ("America/New_York", (9, 30), (16, 0))}
N, K = 160, 2.8

def run(folder, sym, out):
    (ts, o, h, l, c, sp), _ = R.load_1m(folder)
    # barres 5 min : clôtures
    bts, bc = [], []
    cur = None
    for i in range(len(ts)):
        b = ts[i] // 300 * 300
        if cur is None or cur != b:
            bts.append(b); bc.append(c[i]); cur = b
        else:
            bc[-1] = c[i]
    ps, pq = [0.0], [0.0]
    for x in bc: ps.append(ps[-1] + x); pq.append(pq[-1] + x * x)
    def band(i):                              # i = index de la dernière barre 5 min complète
        if i < N - 1: return None
        s, q = ps[i+1] - ps[i+1-N], pq[i+1] - pq[i+1-N]
        m = s / N; v = q / N - m * m
        if v <= 0: return None
        sd = math.sqrt(v); return m, m + K * sd, m - K * sd
    tz = ZoneInfo(SESS[sym][0]); (oh, om), (ch, cm) = SESS[sym][1], SESS[sym][2]
    first, last = datetime.fromtimestamp(ts[0], UTC).date(), datetime.fromtimestamp(ts[-1], UTC).date()
    trades = []
    d = first
    while d <= last:
        if d.weekday() < 5:
            T0 = int(datetime(d.year, d.month, d.day, oh, om, tzinfo=tz).astimezone(UTC).timestamp())
            T1 = int(datetime(d.year, d.month, d.day, ch, cm, tzinfo=tz).astimezone(UTC).timestamp())
            k0, k1 = bisect.bisect_left(ts, T0), bisect.bisect_left(ts, T1)
            if k1 - k0 > 60:
                for kd in (0.5, 1.0):
                    j = k0
                    armed = {1: True, -1: True}          # une entrée par excursion : réarmé quand le prix revient dans les bandes
                    while j < k1:
                        i = bisect.bisect_left(bts, ts[j] // 300 * 300) - 1       # dernière barre complète avant la minute
                        bd = band(i) if i >= 0 and ts[j] // 300 * 300 - bts[i] <= 900 else None
                        if bd is None: j += 1; continue
                        M, U, L = bd
                        if h[j] < U: armed[-1] = True
                        if l[j] + sp[j] > L: armed[1] = True
                        side = 0
                        if armed[-1] and h[j] >= U and not (l[j] + sp[j] <= L): side, entry = -1, U
                        elif armed[1] and l[j] + sp[j] <= L and not (h[j] >= U): side, entry = +1, L
                        if side == 0: j += 1; continue
                        armed[side] = False
                        D = abs(entry - M); risk = kd * D
                        stop = entry - side * risk
                        leg1 = leg2 = None; be = False; j2 = j
                        code = ""
                        while j2 < k1:
                            i2 = bisect.bisect_left(bts, ts[j2] // 300 * 300) - 1
                            b2 = band(i2) if i2 >= 0 else None
                            if b2 is None: j2 += 1; continue
                            M2, U2, L2 = b2
                            stp = entry if be else stop
                            if side > 0:
                                if l[j2] <= stp:
                                    if leg1 is None: leg1 = leg2 = -1.0; code = "SL"
                                    else: leg2 = 0.0; code = "TP1+BE"
                                    break
                                if leg1 is None and h[j2] >= M2: leg1 = (M2 - entry) / risk; be = True
                                if leg1 is not None and h[j2] >= U2: leg2 = (U2 - entry) / risk; code = "TP1+TP2"; break
                            else:
                                if h[j2] + sp[j2] >= stp:
                                    if leg1 is None: leg1 = leg2 = -1.0; code = "SL"
                                    else: leg2 = 0.0; code = "TP1+BE"
                                    break
                                if leg1 is None and l[j2] + sp[j2] <= M2: leg1 = (entry - M2) / risk; be = True
                                if leg1 is not None and l[j2] + sp[j2] <= L2: leg2 = (entry - L2) / risk; code = "TP1+TP2"; break
                            j2 += 1
                        if code == "":                                     # fin de séance
                            px = c[min(j2, k1) - 1] if side > 0 else c[min(j2, k1) - 1] + sp[min(j2, k1) - 1]
                            rr = ((px - entry) if side > 0 else (entry - px)) / risk
                            if leg1 is None: leg1 = leg2 = rr; code = "FIN"
                            else: leg2 = rr; code = "TP1+FIN"
                        trades.append({"d": d.isoformat(), "kd": kd, "side": side, "code": code, "r": 0.5 * leg1 + 0.5 * leg2})
                        j = j2 + 1
        d += timedelta(days=1)
    json.dump({"symbol": sym, "trades": trades}, open(out, "w"))
    print(sym, len(trades))

if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3])
