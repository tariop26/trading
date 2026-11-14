import _path  # noqa
import copy
import unittest

import jstats


def tr(tid, symbol, side, source, setups, entry, exit_, pnl, r, tags=(), res="courtier"):
    return {
        "id": tid, "symbol": symbol, "name": symbol, "side": side, "status": "closed",
        "source": source, "idea": {"setups": list(setups)} if source == "idee" else None,
        "entry": {"time": entry + ":00+00:00", "price": 1.0, "lots": 1.0, "units": 100000, "size": None},
        "exit": {"time": exit_ + ":00+00:00", "price": 1.0, "reason": "manuel"},
        "result": {"pnl_usd": pnl, "r": r, "source": res},
        "tags": list(tags), "note": "", "history": [],
    }


def sample_journal():
    """8 closed trades + 1 open one, Nov 2026 (Paris = UTC+1). Every expected figure below was
    computed by hand from these lines."""
    trades = [
        tr("A", "EURJPY=X", "baissier", "idee", ["breakdown_20d"],
           "2026-11-16T08:30", "2026-11-16T14:00", 450.35, 0.94),
        tr("B", "EURUSD=X", "haussier", "hors_plan", [],
           "2026-11-17T14:00", "2026-11-17T18:00", -500.0, -1.0),
        tr("C", "GBPUSD=X", "haussier", "idee", ["breakout_20d", "reclaim_ma20", "oversold"],
           "2026-11-18T01:00", "2026-11-18T10:00", 800.0, 1.6),
        tr("D", "EURJPY=X", "baissier", "idee", ["breakdown_20d"],
           "2026-11-18T21:00", "2026-11-19T09:00", 0.0, 0.0, tags=["entree_tardive"]),
        tr("E", "USDJPY=X", "haussier", "idee", ["bull_flag"],
           "2026-11-19T12:00", "2026-11-19T16:00", 300.0, 0.6, res="estime"),
        tr("F", "EURUSD=X", "baissier", "idee", ["lose_ma20"],
           "2026-11-19T23:30", "2026-11-20T08:00", -250.0, -0.5,
           tags=["stop_deplace", "entree_tardive"]),
        tr("G", "GBPUSD=X", "haussier", "idee", ["breakout_20d"],
           "2026-11-20T10:00", "2026-11-20T15:00", 200.0, None),
        tr("H", "EURUSD=X", "haussier", "hors_plan", [],
           "2026-11-20T14:00", "2026-11-20T20:00", -100.0, -0.2, tags=["hors_plan_taille"]),
    ]
    open_trade = dict(trades[0], id="I", status="open", exit=None, result=None)
    return {"v": 1, "trades": trades + [open_trade]}


def by_key(groups):
    return {g["key"]: g for g in groups}


class TestClassify(unittest.TestCase):
    def test_boundaries_of_the_flat_zone(self):
        def c(r, pnl=0.0):
            t = tr("x", "EURUSD=X", "haussier", "hors_plan", [], "2026-11-16T08:00",
                   "2026-11-16T09:00", pnl, r)
            return jstats.classify(t)
        self.assertEqual((c(0.04), c(-0.04)), ("equilibre", "equilibre"))
        self.assertEqual((c(0.05), c(-0.05)), ("positif", "negatif"))     # |r| < 0.05 only
        self.assertEqual((c(None, 10.0), c(None, -10.0), c(None, 0.0)),
                         ("positif", "negatif", "equilibre"))

    def test_an_open_trade_is_not_classified(self):
        self.assertIsNone(jstats.classify(sample_journal()["trades"][-1]))


class TestOverall(unittest.TestCase):
    def setUp(self):
        self.s = jstats.compute_stats(sample_journal())

    def test_counts_and_warning(self):
        self.assertEqual((self.s["n_closed"], self.s["n_open"]), (8, 1))
        self.assertEqual(self.s["sample_warning"], "échantillon trop petit pour conclure")

    def test_overall_figures(self):
        o = self.s["overall"]
        self.assertEqual((o["n"], o["positive"], o["negative"], o["flat"]), (8, 4, 3, 1))
        self.assertEqual(o["win_rate"], 0.5)
        self.assertEqual(o["avg_r_positive"], 1.0467)      # (0.94 + 1.6 + 0.6) / 3, G has no R
        self.assertEqual(o["avg_r_negative"], -0.5667)     # (-1.0 - 0.5 - 0.2) / 3
        self.assertEqual(o["expectancy_r"], 0.2057)        # 1.44 / 7
        self.assertEqual(o["total_r"], 1.44)
        self.assertEqual(o["pnl_usd"], 900.35)
        self.assertEqual((o["n_estimated"], o["n_no_r"]), (1, 1))

    def test_by_side(self):
        g = by_key(self.s["by_side"])
        self.assertEqual([x["key"] for x in self.s["by_side"]], ["haussier", "baissier"])
        h = g["haussier"]
        self.assertEqual((h["n"], h["win_rate"], h["avg_r"], h["total_r"], h["pnl_usd"], h["few"]),
                         (5, 0.6, 0.25, 1.0, 700.0, False))
        b = g["baissier"]
        self.assertEqual((b["n"], b["win_rate"], b["avg_r"], b["total_r"], b["pnl_usd"], b["few"]),
                         (3, 0.3333, 0.1467, 0.44, 200.35, True))

    def test_by_rule_counts_a_trade_in_each_of_its_rules_and_skips_states(self):
        keys = [x["key"] for x in self.s["by_rule"]]
        self.assertEqual(keys, ["breakdown_20d", "breakout_20d", "hors plan",
                                "bull_flag", "lose_ma20", "reclaim_ma20"])
        self.assertNotIn("oversold", keys)
        g = by_key(self.s["by_rule"])
        self.assertEqual((g["breakdown_20d"]["n"], g["breakdown_20d"]["win_rate"],
                          g["breakdown_20d"]["avg_r"], g["breakdown_20d"]["pnl_usd"]),
                         (2, 0.5, 0.47, 450.35))
        self.assertEqual((g["breakout_20d"]["n"], g["breakout_20d"]["avg_r"],
                          g["breakout_20d"]["total_r"], g["breakout_20d"]["pnl_usd"]),
                         (2, 1.6, 1.6, 1000.0))                       # G has no R: excluded from avg
        self.assertEqual((g["hors plan"]["n"], g["hors plan"]["win_rate"], g["hors plan"]["avg_r"],
                          g["hors plan"]["total_r"], g["hors plan"]["pnl_usd"]),
                         (2, 0.0, -0.6, -1.2, -600.0))
        self.assertEqual((g["reclaim_ma20"]["n"], g["reclaim_ma20"]["pnl_usd"]), (1, 800.0))
        self.assertTrue(g["reclaim_ma20"]["few"])

    def test_by_symbol(self):
        keys = [x["key"] for x in self.s["by_symbol"]]
        self.assertEqual(keys, ["EURUSD=X", "EURJPY=X", "GBPUSD=X", "USDJPY=X"])
        g = by_key(self.s["by_symbol"])
        self.assertEqual((g["EURUSD=X"]["n"], g["EURUSD=X"]["win_rate"], g["EURUSD=X"]["avg_r"],
                          g["EURUSD=X"]["total_r"], g["EURUSD=X"]["pnl_usd"]),
                         (3, 0.0, -0.5667, -1.7, -850.0))
        self.assertEqual((g["GBPUSD=X"]["n"], g["GBPUSD=X"]["pnl_usd"]), (2, 1000.0))

    def test_by_session_in_the_fixed_order(self):
        keys = [x["key"] for x in self.s["by_session"]]
        self.assertEqual(keys, ["Sydney", "Tokyo", "London", "New York"])
        g = by_key(self.s["by_session"])
        self.assertEqual((g["Sydney"]["n"], g["Sydney"]["win_rate"], g["Sydney"]["avg_r"],
                          g["Sydney"]["total_r"], g["Sydney"]["pnl_usd"]),
                         (2, 0.0, -0.25, -0.5, -250.0))
        self.assertEqual((g["London"]["n"], g["London"]["win_rate"], g["London"]["avg_r"],
                          g["London"]["total_r"], g["London"]["pnl_usd"]),
                         (3, 1.0, 0.77, 1.54, 950.35))
        self.assertEqual((g["New York"]["n"], g["New York"]["pnl_usd"]), (2, -600.0))
        self.assertEqual((g["Tokyo"]["n"], g["Tokyo"]["pnl_usd"]), (1, 800.0))

    def test_by_weekday_in_paris_time(self):
        keys = [x["key"] for x in self.s["by_weekday"]]
        self.assertEqual(keys, ["lundi", "mardi", "mercredi", "jeudi", "vendredi"])
        g = by_key(self.s["by_weekday"])
        # F entered Thursday 23:30 UTC = Friday 00:30 in Paris
        self.assertEqual((g["vendredi"]["n"], g["vendredi"]["win_rate"], g["vendredi"]["avg_r"],
                          g["vendredi"]["total_r"], g["vendredi"]["pnl_usd"]),
                         (3, 0.3333, -0.35, -0.7, -150.0))
        self.assertEqual((g["mercredi"]["n"], g["mercredi"]["avg_r"], g["mercredi"]["pnl_usd"]),
                         (2, 0.8, 800.0))
        self.assertEqual((g["jeudi"]["n"], g["lundi"]["n"], g["mardi"]["n"]), (1, 1, 1))

    def test_errors_by_tag(self):
        e = self.s["errors"]
        self.assertEqual([x["tag"] for x in e], ["entree_tardive", "hors_plan_taille", "stop_deplace"])
        self.assertEqual((e[0]["n"], e[0]["avg_r"], e[0]["total_r"]), (2, -0.25, -0.5))
        self.assertEqual((e[1]["n"], e[1]["avg_r"], e[1]["total_r"]), (1, -0.2, -0.2))
        self.assertEqual((e[2]["n"], e[2]["avg_r"], e[2]["total_r"]), (1, -0.5, -0.5))

    def test_equity_curve_drawdown_and_streak(self):
        q = self.s["equity"]
        self.assertEqual((q["start"], q["end"], q["cap_pct"]), (100000.0, 100900.35, 2.0))
        self.assertEqual([p["trade_id"] for p in q["points"]], list("ABCDEFGH"))   # by exit time
        self.assertEqual([p["equity"] for p in q["points"]],
                         [100450.35, 99950.35, 100750.35, 100750.35, 101050.35,
                          100800.35, 101000.35, 100900.35])
        self.assertEqual(q["max_drawdown_usd"], 500.0)       # 100450.35 -> 99950.35
        self.assertEqual(q["max_drawdown_pct"], round(500.0 / 100450.35 * 100, 4))
        # the flat trade D breaks the runs; B, F, H are three runs of 1: the worst one wins the tie
        self.assertEqual(q["worst_streak"], {"n": 1, "r": -1.0})


class TestEdgeCases(unittest.TestCase):
    def test_empty_journal(self):
        s = jstats.compute_stats({"v": 1, "trades": []})
        self.assertEqual((s["n_closed"], s["n_open"]), (0, 0))
        self.assertEqual(s["overall"]["n"], 0)
        self.assertIsNone(s["overall"]["win_rate"])
        self.assertIsNone(s["overall"]["expectancy_r"])
        for k in ("by_rule", "by_side", "by_symbol", "by_session", "by_weekday", "errors"):
            self.assertEqual(s[k], [])
        self.assertEqual(s["equity"]["points"], [])
        self.assertEqual((s["equity"]["start"], s["equity"]["end"]), (100000.0, 100000.0))
        self.assertEqual(s["equity"]["max_drawdown_usd"], 0.0)
        self.assertEqual(s["equity"]["worst_streak"], {"n": 0, "r": 0.0})
        self.assertEqual(s["sample_warning"], "échantillon trop petit pour conclure")

    def test_thirty_trades_remove_the_warning(self):
        trades = [tr("T%d" % i, "EURUSD=X", "haussier", "hors_plan", [],
                     "2026-11-16T08:00", "2026-11-16T09:%02d" % i, 10.0, 0.5) for i in range(30)]
        s = jstats.compute_stats({"v": 1, "trades": trades})
        self.assertEqual(s["n_closed"], 30)
        self.assertIsNone(s["sample_warning"])

    def test_a_trade_without_r_is_counted_but_excluded_from_the_means(self):
        j = {"v": 1, "trades": [
            tr("a", "EURUSD=X", "haussier", "hors_plan", [], "2026-11-16T08:00", "2026-11-16T09:00",
               100.0, None),
            tr("b", "EURUSD=X", "haussier", "hors_plan", [], "2026-11-16T08:00", "2026-11-16T10:00",
               -50.0, None)]}
        o = jstats.compute_stats(j)["overall"]
        self.assertEqual((o["n"], o["positive"], o["negative"], o["n_no_r"]), (2, 1, 1, 2))
        self.assertIsNone(o["avg_r_positive"])
        self.assertIsNone(o["avg_r_negative"])
        self.assertIsNone(o["expectancy_r"])
        self.assertEqual((o["total_r"], o["pnl_usd"]), (0.0, 50.0))

    def test_weekday_uses_paris_time_across_midnight_and_dst(self):
        def day(entry):
            j = {"v": 1, "trades": [tr("x", "EURUSD=X", "haussier", "hors_plan", [], entry,
                                        entry[:11] + "23:59", 1.0, 0.1)]}
            return jstats.compute_stats(j)["by_weekday"][0]["key"]
        self.assertEqual(day("2026-11-20T23:30"), "samedi")   # Friday 23:30 UTC, winter: 00:30 Saturday
        self.assertEqual(day("2026-07-17T23:30"), "samedi")   # summer: 01:30 Saturday
        self.assertEqual(day("2026-07-17T22:30"), "samedi")   # summer: 00:30 Saturday
        self.assertEqual(day("2026-07-17T21:30"), "vendredi")  # summer: 23:30 Friday

    def test_stats_do_not_mutate_the_journal(self):
        j = sample_journal()
        before = copy.deepcopy(j)
        jstats.compute_stats(j)
        self.assertEqual(j, before)

    def test_longest_run_of_negatives_and_its_total(self):
        rs = [-0.5, -0.5, 1.0, -1.0, -0.2, -0.3]
        trades = [tr("T%d" % i, "EURUSD=X", "haussier", "hors_plan", [],
                     "2026-11-16T08:00", "2026-11-16T09:%02d" % i, r * 100, r)
                  for i, r in enumerate(rs)]
        w = jstats.compute_stats({"v": 1, "trades": trades})["equity"]["worst_streak"]
        # runs of 2: (-0.5, -0.5) = -1.0 and (-1.0, -0.2, -0.3) is a run of 3 = -1.5: the longest wins
        self.assertEqual(w, {"n": 3, "r": -1.5})


if __name__ == "__main__":
    unittest.main()
