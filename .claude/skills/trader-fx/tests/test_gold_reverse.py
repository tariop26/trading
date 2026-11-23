import _path  # noqa
import math
import re
import unittest
from datetime import datetime, timezone

import gold_reverse as gr

FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b|—")
START = int(datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc).timestamp())   # a Monday


def wave(hours=480, mid=3550.0, amp=48.0, period=48):
    """Hourly bars oscillating between about 3502 and 3598 (lows near 3500, highs near 3600)."""
    bars = []
    for i in range(hours):
        c = mid + amp * math.sin(2 * math.pi * i / period)
        bars.append((START + i * 3600, c, c + 2.0, c - 2.0, c))
    return bars


class TestLevels(unittest.TestCase):
    def setUp(self):
        self.bars = wave()
        self.now = START + len(self.bars) * 3600

    def test_server_day_is_new_york_plus_7(self):
        # 21:59 UTC on Monday 23/11 (winter) is 23:59 server time: still Monday
        self.assertEqual(str(gr.server_day(datetime(2026, 11, 23, 21, 59, tzinfo=timezone.utc).timestamp())),
                         "2026-11-23")
        self.assertEqual(str(gr.server_day(datetime(2026, 11, 23, 22, 0, tzinfo=timezone.utc).timestamp())),
                         "2026-11-24")

    def test_swing_zones_need_two_touches(self):
        h4 = gr.reversal.to_h4(self.bars)
        zones = gr.swing_zones(h4, gr.atr(h4))
        self.assertTrue(zones)
        self.assertTrue(all(n >= 2 for _p, n in zones))
        self.assertTrue(any(abs(p - 3500) < 10 for p, _n in zones), zones)
        self.assertTrue(any(abs(p - 3600) < 10 for p, _n in zones), zones)

    def test_confluence_is_merged_on_the_round_number(self):
        levels, atr_h4, price = gr.candidate_levels(self.bars, self.now)
        low = [l for l in levels if abs(l["price"] - 3500) < 1]
        self.assertEqual(len(low), 1, levels)
        self.assertEqual(low[0]["price"], 3500.0)
        self.assertIn("chiffre rond", low[0]["reasons"])
        self.assertTrue(any(r.startswith("swing H4 touché") for r in low[0]["reasons"]), low[0])
        self.assertTrue(any("veille" in r for l in levels for r in l["reasons"]))
        self.assertTrue(any("semaine dernière" in r for l in levels for r in l["reasons"]))

    def test_plan_long_and_short(self):
        p = gr.plan(3500.0, 3520.0, 20.0, 500.0)
        self.assertEqual((p["side"], p["entry"], p["stop"], p["target"]), ("haussier", 3500.0, 3488.0, 3524.0))
        self.assertEqual(p["lots"], 0.41)                       # 500 / (12 x 100) = 0.416 -> 0.41
        self.assertAlmostEqual(p["risk"], 492.0)
        s = gr.plan(3600.0, 3590.0, 20.0, 500.0)
        self.assertEqual((s["side"], s["stop"], s["target"]), ("baissier", 3612.0, 3576.0))
        self.assertIsNone(gr.plan(3500.0, 3500.0, 20.0, 500.0))
        self.assertEqual(gr.plan(3500.0, 3520.0, 20.0, 5.0)["lots"], 0)


class TestAlerts(unittest.TestCase):
    def near_support(self):
        bars = wave(hours=468)                              # ends on the way down, near the lows
        return bars, START + len(bars) * 3600

    def test_alert_when_price_approaches_a_level_once_a_day(self):
        bars, now = self.near_support()
        levels, a, price = gr.candidate_levels(bars, now)
        found, log = gr.alerts(bars, now, 500.0, "baissière", set(), "2026-11-14")
        self.assertTrue(found, (price, a, [l["price"] for l in levels]))
        key, text = found[0]
        self.assertTrue(key.startswith("setupD|"))
        self.assertIn("Setup D, or H4", text)
        self.assertIn("non validé par backtest", text)
        self.assertIn("Ordre limite", text)
        self.assertIsNone(FORBIDDEN.search(text), text)
        again, _ = gr.alerts(bars, now, 500.0, "baissière", {k for k, _ in found}, "2026-11-14")
        self.assertEqual([k for k, _ in again if k in {k for k, _ in found}], [])

    def test_counter_trend_is_flagged(self):
        bars, now = self.near_support()
        found, _ = gr.alerts(bars, now, 500.0, "baissière", set(), "d")
        supports = [t for _k, t in found if "support" in t]
        self.assertTrue(supports)
        self.assertIn("Contre la tendance D1 baissière", supports[0])

    def test_news_blocks_and_short_history_is_said(self):
        bars, now = self.near_support()
        self.assertEqual(gr.alerts(bars, now, 500.0, None, set(), "d", news_block=True)[0], [])
        found, log = gr.alerts(bars[:20], now, 500.0, None, set(), "d")
        self.assertEqual(found, [])
        self.assertIn("pas assez de barres", log[0])

    def test_at_most_two_per_run(self):
        bars, now = self.near_support()
        found, _ = gr.alerts(bars, now, 500.0, None, set(), "d")
        self.assertLessEqual(len(found), gr.MAX_PER_RUN)


if __name__ == "__main__":
    unittest.main()
