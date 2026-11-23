import _path  # noqa
import re
import unittest

import reversal as rv

DAY = 86400
FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b|—")


def daily(closes, spread=10.0, start=0):
    """Daily bars around each close: high = close + spread, low = close - spread."""
    return [(start + i * DAY, c, c + spread, c - spread, c) for i, c in enumerate(closes)]


def downtrend(n=60, top=1000.0, step=5.0):
    return daily([top - i * step for i in range(n)])


class TestTrendAndSwings(unittest.TestCase):
    def test_trend_needs_50_sessions_and_reads_the_means(self):
        self.assertIsNone(rv.trend(downtrend(40)))
        self.assertEqual(rv.trend(downtrend()), "baissière")
        self.assertEqual(rv.trend(daily([500 + i * 5 for i in range(60)])), "haussière")
        self.assertEqual(rv.trend(daily([500] * 60)), "neutre")

    def test_fractal_swings_are_confirmed_two_bars_later(self):
        highs = [10, 11, 15, 12, 11, 13, 20, 14]
        bars = [(i, 0, h, h - 5, h - 1) for i, h in enumerate(highs)]
        got = [(t, k, p) for t, k, p in rv.swings(bars) if k == "haut"]
        self.assertEqual(got, [(2, "haut", 15)])            # 20 at index 6 has only 1 bar after it
        self.assertEqual(rv.swings(bars[:3]), [])

    def test_bascule_follows_the_trend(self):
        closes = [1000 - i * 5 for i in range(55)] + [740, 760, 750, 735, 730]   # a bounce at 760
        bars = daily(closes)
        b = rv.bascule(bars, "baissière")
        self.assertEqual(b, {"haut": 770.0, "bas": None})
        self.assertEqual(set(rv.bascule(bars, "neutre")), {"haut", "bas"})
        self.assertIsNone(rv.bascule(bars, "haussière")["haut"])


class TestZones(unittest.TestCase):
    def test_zones_and_extensions(self):
        bars = downtrend()
        z = rv.zones(bars)
        self.assertEqual(z["atr"], 20.0)
        last20 = [b[4] for b in bars[-20:]]
        self.assertEqual(z["haut_20j"], max(last20) + 10)
        self.assertEqual(z["bas_5j"], bars[-1][4] - 10)
        mean = sum(last20) / 20
        self.assertAlmostEqual(z["ext_basse"], mean - 60)
        self.assertAlmostEqual(z["ext_haute"], mean + 60)
        self.assertIsNone(rv.zones(bars[:10]))


class TestSar(unittest.TestCase):
    def test_sar_rises_under_an_uptrend_then_reverses(self):
        bars = [(i, 0, 100 + i * 2 + 1, 100 + i * 2 - 1, 100 + i * 2) for i in range(10)]
        bars += [(10, 0, 112, 100, 101)]                  # a crash through the SAR
        s = rv.psar(bars)
        sides = [x[2] for x in s]
        self.assertEqual(sides[:-1], ["haussier"] * 9)
        self.assertEqual(sides[-1], "baissier")
        rising = [x[1] for x in s[:-1]]
        self.assertEqual(rising, sorted(rising))
        self.assertTrue(all(x[1] < bars[i + 1][3] for i, x in enumerate(s[:-1])))
        self.assertEqual(s[-1][1], 119)                   # reversal: SAR jumps to the extreme point

    def test_first_steps_by_hand(self):
        bars = [(0, 0, 10, 8, 9), (1, 0, 11, 9, 10), (2, 0, 12, 10, 11)]
        s = rv.psar(bars)
        self.assertEqual(s[0], (1, 8, "haussier"))        # SAR = lowest low, EP = 11
        # 8 + 0.02 x (11 - 8) = 8.06, then capped by the two previous lows (9 and 8): 8
        self.assertAlmostEqual(s[1][1], 8)

    def test_sar_state_flags_the_flip(self):
        bars = [(i, 0, 100 + i * 2 + 1, 100 + i * 2 - 1, 100 + i * 2) for i in range(10)]
        self.assertFalse(rv.sar_state(bars)["flipped"])
        bars += [(10, 0, 112, 100, 101)]
        st = rv.sar_state(bars)
        self.assertTrue(st["flipped"])
        self.assertEqual(st["side"], "baissier")
        self.assertIsNone(rv.sar_state(bars[:1]))


class TestH4AndCompleteness(unittest.TestCase):
    def test_hourly_to_h4_buckets(self):
        hourly = [(h * 3600, 1 + h, 2 + h, 0 + h, 1.5 + h) for h in range(9)]   # 00:00 .. 08:00
        h4 = rv.to_h4(hourly)
        self.assertEqual([b[0] for b in h4], [0, 4 * 3600, 8 * 3600])
        self.assertEqual(h4[0], (0, 1, 5, 0, 4.5))
        done = rv.completed(h4, 8 * 3600 + 1800, rv.H4)
        self.assertEqual(len(done), 2)                    # the 08:00 bucket is not over

    def test_levels_ignore_the_session_in_progress(self):
        bars = downtrend()
        now = bars[-1][0] + DAY // 2                      # the last daily bar is not over
        lv = rv.levels(bars, [], now)
        self.assertEqual(lv["close"], bars[-2][4])
        self.assertIsNone(lv["sar_h4"])


class TestMessages(unittest.TestCase):
    def setUp(self):
        closes = [1000 - i * 5 for i in range(55)] + [740, 760, 750, 735, 730]
        self.bars = daily(closes)
        self.lv = rv.levels(self.bars, [], self.bars[-1][0] + DAY)

    def test_fmt_is_french(self):
        self.assertEqual(rv.fmt(25456.2), "25 456")
        self.assertEqual(rv.fmt(1.10964), "1,11")
        self.assertEqual(rv.fmt(None), "n.d.")

    def test_morning_message(self):
        text = rv.morning_message([("Nasdaq 100 (NAS100)", self.lv), ("DAX 40 (GER40)", None)])
        self.assertIn("Nasdaq 100 (NAS100) : tendance D1 baissière, clôture 730", text)
        self.assertIn("bascule au-dessus de 770", text)
        self.assertIn("SAR D1", text)
        self.assertIn("DAX 40 (GER40) : données indisponibles.", text)
        self.assertIsNone(FORBIDDEN.search(text))
        self.assertLess(len(text), 4096)

    def test_live_alerts(self):
        got = dict(rv.live_alerts("^NDX", "Nasdaq 100", self.lv, 775.0, "2026-11-23"))
        self.assertIn("reverse|^NDX|bascule-haut|2026-11-23", got)
        self.assertIn("au-dessus du dernier swing haut D1 (770,00)", got["reverse|^NDX|bascule-haut|2026-11-23"])
        quiet = dict(rv.live_alerts("^NDX", "Nasdaq 100", self.lv, 745.0, "2026-11-23"))
        self.assertNotIn("reverse|^NDX|bascule-haut|2026-11-23", quiet)
        z = self.lv["zones"]
        near = dict(rv.live_alerts("^NDX", "Nasdaq 100", self.lv, z["bas_20j"] + 1, "2026-11-23"))
        self.assertIn("reverse|^NDX|zone-bas_20j|2026-11-23", near)
        for text in list(got.values()) + list(near.values()):
            self.assertIsNone(FORBIDDEN.search(text), text)
        self.assertEqual(rv.live_alerts("^NDX", "x", None, 1.0, "d"), [])


if __name__ == "__main__":
    unittest.main()
