"""SPIKE JETABLE : gestion sur cassures du plus haut/bas 4 h. Stop 3 ATR(5 min). Variantes A (TP 1:1), B (BE à 1,5 ATR puis trailing 3 ATR), C (50 % à +3 ATR puis BE + trailing 3 ATR).
Contrôle : même gestion, sens inverse. Sortie max 24 h. Usage : mgmt_test.py dossier SYMBOLE sortie.json"""
import bisect, json, os, sys
from collections import deque
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
SL, TPA, BE_B, TRAIL = 3.0, 3.0, 1.5, 3.0

def sim(k, side, atr, var, ts, o, h, l, c, sp):
    n = len(ts); risk = SL * atr
    fill = o[k] + sp[k] if side > 0 else o[k]
    stop = fill - side * risk
    tp = fill + side * TPA * atr
    w, real, be_on, half, ext = 1.0, 0.0, False, False, fill
    end = ts[k] + 86400
    for j in range(k, n):
        if ts[j] > end:
            px = c[j-1] if side > 0 else c[j-1] + sp[j-1]
            return real + w * (px - fill) * side / risk
        hit_stop = (l[j] <= stop) if side > 0 else (h[j] + sp[j] >= stop)
        if hit_stop: return real + w * (stop - fill) * side / risk
        if var in ("A", "C"):
            hit_tp = (h[j] >= tp) if side > 0 else (l[j] + sp[j] <= tp)
            if hit_tp:
                if var == "A": return real + w * (tp - fill) * side / risk
                if not half:
                    real += 0.5 * (tp - fill) * side / risk; w = 0.5; half = True; be_on = True
                    stop = fill if side > 0 else fill       # point mort
                    ext = tp
        fav = ((h[j] - fill) if side > 0 else (fill - (l[j] + sp[j])))
        if var == "B" and not be_on and fav >= BE_B * atr:
            be_on = True; stop = fill; ext = h[j] if side > 0 else l[j] + sp[j]
        if be_on and var in ("B", "C"):
            if side > 0:
                ext = max(ext, h[j]); stop = max(stop, ext - TRAIL * atr)
            else:
                ext = min(ext, l[j] + sp[j]); stop = min(stop, ext + TRAIL * atr)
    return None

def main(folder, sym, out):
    (ts, o, h, l, c, sp), _ = R.load_1m(folder)
    n = len(ts)
    bts, bh, bl, bc, cur = [], [], [], [], None
    for i in range(n):
        b = ts[i] // 300 * 300
        if cur != b: bts.append(b); bh.append(h[i]); bl.append(l[i]); bc.append(c[i]); cur = b
        else: bh[-1] = max(bh[-1], h[i]); bl[-1] = min(bl[-1], l[i]); bc[-1] = c[i]
    tr = [0.0] + [max(bh[i] - bl[i], abs(bh[i] - bc[i-1]), abs(bl[i] - bc[i-1])) for i in range(1, len(bts))]
    pc = [0.0]
    for x in tr: pc.append(pc[-1] + x)
    W = 240 * 60
    dq_h, dq_l = deque(), deque(); last_up = last_dn = -10**12; rows = []
    for j in range(n):
        t = ts[j]
        while dq_h and dq_h[0][0] < t - W: dq_h.popleft()
        while dq_l and dq_l[0][0] < t - W: dq_l.popleft()
        if dq_h and dq_h[0][0] <= t - W + 600:
            for side, brk in ((1, h[j] > dq_h[0][1]), (-1, l[j] < dq_l[0][1])):
                last = last_up if side > 0 else last_dn
                if brk and t - last >= 3600:
                    if side > 0: last_up = t
                    else: last_dn = t
                    k = j + 1
                    i5 = bisect.bisect_left(bts, t // 300 * 300) - 1
                    if k < n and ts[k] - t <= 120 and i5 > 15:
                        atr = (pc[i5+1] - pc[i5-13]) / 14
                        if atr > 0:
                            row = {"t": ts[k], "side": side}
                            for var in "ABC":
                                row[var] = sim(k, side, atr, var, ts, o, h, l, c, sp)
                                row[var + "m"] = sim(k, -side, atr, var, ts, o, h, l, c, sp)
                            row["atr"] = atr
                            rows.append(row)
        while dq_h and dq_h[-1][1] <= h[j]: dq_h.pop()
        dq_h.append((t, h[j]))
        while dq_l and dq_l[-1][1] >= l[j]: dq_l.pop()
        dq_l.append((t, l[j]))
    json.dump(rows, open(out, "w")); print(sym, len(rows))
if __name__ == "__main__": main(*sys.argv[1:4])
