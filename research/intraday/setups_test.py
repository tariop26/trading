"""SPIKE JETABLE : 3 familles de setups classiques, règles fixées d'avance (voir message).
S1 MTF pullback : tendance D1 (signals.trend) ; sur H1, la clôture précédente est du mauvais côté de l'EMA20(H1)
   et la barre courante la reprend en clôturant du bon côté avec une bougie dans le sens (reclaim).
S2a compression + cassure : range des 20 H1 précédentes <= 20e centile de ses 500 dernières valeurs ; clôture H1 hors du range.
S2b = S2a dans le sens de la tendance D1.  S2c = fade d'une cassure ratée : la barre dépasse le range mais clôture dedans.
S3 niveaux clés : veille H/B, semaine précédente H/B, SMA50 D1 ; rejet (mèche >= 50 % de la bougie, clôture du bon côté du niveau),
   dans le sens de la tendance D1.
Sortie commune : stop 1,5 ATR(H1,14), cible 2R, 24 h max ; entrée à la minute suivant la clôture.
"""
import bisect, json, math, os, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay2 as R
import signals
UTC = timezone.utc

def hourly(ts, o, h, l, c):
    out, cur = [], None
    for i in range(len(ts)):
        k = ts[i] // 3600 * 3600
        if cur is None or cur[0] != k:
            if cur: out.append(tuple(cur))
            cur = [k, o[i], h[i], l[i], c[i]]
        else:
            cur[2] = max(cur[2], h[i]); cur[3] = min(cur[3], l[i]); cur[4] = c[i]
    if cur: out.append(tuple(cur))
    return out

def sim(m, k, side, risk, ts, o, h, l, c, sp, be=None):
    """R du trade ; stop avant cible si les deux ; 24 h max ; be = fraction de la distance au TP (ex. 0.3)
    à partir de laquelle le stop passe à l'entrée (effet dès la minute suivante). -> (r, kind, minute_de_sortie)."""
    px = o[k]
    if side > 0:
        fill, stop, tgt = px + sp[k], px - risk, px + 2 * risk
    else:
        fill, stop, tgt = px, px + risk, px - 2 * risk
    trig = None if be is None else fill + be * (tgt - fill)
    cur, armed = stop, False
    end = ts[k] + 86400
    j, n = k, len(ts)
    while j < n:
        if ts[j] > end:
            ex = c[j - 1] if side > 0 else c[j - 1] + sp[j - 1]
            return ((ex - fill) if side > 0 else (fill - ex)) / risk, "time", j
        hs, ht = (l[j] <= cur, h[j] >= tgt) if side > 0 else (h[j] + sp[j] >= cur, l[j] + sp[j] <= tgt)
        if hs: return ((cur - fill) if side > 0 else (fill - cur)) / risk, ("be" if armed else "stop"), j
        if ht: return ((tgt - fill) if side > 0 else (fill - tgt)) / risk, "target", j
        if trig is not None and not armed:
            if (side > 0 and h[j] >= trig) or (side < 0 and l[j] + sp[j] <= trig):
                armed, cur = True, fill
        j += 1
    return None

def run(folder, sym, out):
    (ts, o, h, l, c, sp), daily = R.load_1m(folder)
    hb = hourly(ts, o, h, l, c)
    dates = [d[0] for d in daily]
    dcl = [d[4] for d in daily]
    cs = [0.0]
    for x in dcl: cs.append(cs[-1] + x)
    weeks = defaultdict(lambda: [-1e18, 1e18])
    for d, _o, hh, ll, _c in daily:
        wk = d.isocalendar()[:2]
        weeks[wk][0] = max(weeks[wk][0], hh); weeks[wk][1] = min(weeks[wk][1], ll)
    n = len(hb)
    ema, atr, a = [0.0] * n, [None] * n, None
    k20 = 2 / 21
    for i in range(n):
        ema[i] = hb[i][4] if i == 0 else ema[i-1] + k20 * (hb[i][4] - ema[i-1])
        if i > 0:
            tr = max(hb[i][2] - hb[i][3], abs(hb[i][2] - hb[i-1][4]), abs(hb[i][3] - hb[i-1][4]))
            a = tr if a is None else (a * 13 + tr) / 14 if i >= 14 else (a * (i - 1) + tr) / i
            atr[i] = a if i >= 14 else None
    rng20 = [None] * n
    for i in range(20, n):
        rng20[i] = max(x[2] for x in hb[i-20:i]) - min(x[3] for x in hb[i-20:i])
    trades, busy = [], defaultdict(int)       # busy[variante] = ts libre
    def ctx(T):
        today = R.server_date(datetime.fromtimestamp(T, UTC))
        idx = bisect.bisect_left(dates, today)             # jours complets = dates < today
        if idx < 51: return None
        closes_last, ma20, ma50 = dcl[idx-1], (cs[idx]-cs[idx-20])/20, (cs[idx]-cs[idx-50])/50
        tr = "up" if (closes_last > ma50 and ma20 > ma50) else "down" if (closes_last < ma50 and ma20 < ma50) else "mixed"
        pd = daily[idx-1]; pw = (datetime.combine(today, datetime.min.time()) - timedelta(days=7)).isocalendar()[:2]
        pwk = weeks.get(pw)
        return tr, pd[2], pd[3], (pwk[0], pwk[1]) if pwk else None, ma50
    def emit(var, i, side, T):
        if T < busy[var] or atr[i] is None or atr[i] <= 0: return
        k = bisect.bisect_left(ts, T)
        if k >= len(ts) or ts[k] - T > 300: return
        risk = 1.5 * atr[i]
        r = sim(None, k, side, risk, ts, o, h, l, c, sp)
        if r is None: return
        m = sim(None, k, -side, risk, ts, o, h, l, c, sp)
        rb = sim(None, k, side, risk, ts, o, h, l, c, sp, be=0.3)
        mb = sim(None, k, -side, risk, ts, o, h, l, c, sp, be=0.3)
        busy[var] = ts[r[2]]
        trades.append({"v": var, "at": datetime.fromtimestamp(T, UTC).isoformat(), "side": side,
                       "r": r[0], "k": r[1], "mirror": m[0] if m else None,
                       "rbe": rb[0] if rb else None, "kbe": rb[1] if rb else None, "mbe": mb[0] if mb else None})
    hist = []
    for i in range(520, n - 1):
        T = hb[i][0] + 3600                                  # clôture de la barre i
        if hb[i+1][0] - hb[i][0] > 7200:                      # trou (week-end) : pas d'entrée sur barre isolée
            pass
        cx = ctx(T)
        if cx is None or atr[i] is None: continue
        trend, pdh, pdl, pw, ma50 = cx
        o_, h_, l_, c_ = hb[i][1:5]
        # S1
        if trend in ("up", "down"):
            if trend == "up" and hb[i-1][4] < ema[i-1] and c_ > ema[i] and c_ > o_: emit("S1 MTF pullback", i, +1, T)
            if trend == "down" and hb[i-1][4] > ema[i-1] and c_ < ema[i] and c_ < o_: emit("S1 MTF pullback", i, -1, T)
        # S2
        if rng20[i] is not None:
            past = sorted(x for x in rng20[i-500:i] if x is not None)
            thr = past[int(len(past) * 0.2)] if len(past) > 100 else None
            if thr is not None and rng20[i] <= thr:
                hi20 = max(x[2] for x in hb[i-20:i]); lo20 = min(x[3] for x in hb[i-20:i])
                brk = +1 if c_ > hi20 else -1 if c_ < lo20 else 0
                if brk: 
                    emit("S2a compression+cassure", i, brk, T)
                    if (brk > 0 and trend == "up") or (brk < 0 and trend == "down"): emit("S2b cassure dans la tendance D1", i, brk, T)
                else:
                    if h_ > hi20 and c_ <= hi20: emit("S2c fade cassure ratée", i, -1, T)
                    if l_ < lo20 and c_ >= lo20: emit("S2c fade cassure ratée", i, +1, T)
        # S3
        if trend in ("up", "down"):
            rg = h_ - l_
            if rg > 0:
                sup = [pdl, ma50] + ([pw[1]] if pw else [])
                res = [pdh, ma50] + ([pw[0]] if pw else [])
                if trend == "up":
                    for L in sup:
                        if l_ <= L <= min(o_, c_) and (min(o_, c_) - l_) >= 0.5 * rg: emit("S3 rejet niveau clé (tendance D1)", i, +1, T); break
                else:
                    for L in res:
                        if max(o_, c_) <= L <= h_ and (h_ - max(o_, c_)) >= 0.5 * rg: emit("S3 rejet niveau clé (tendance D1)", i, -1, T); break
    json.dump({"symbol": sym, "trades": trades}, open(out, "w"))
    print(sym, "trades", len(trades), dict((v, sum(1 for t in trades if t["v"] == v)) for v in sorted({t["v"] for t in trades})))

if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3])
