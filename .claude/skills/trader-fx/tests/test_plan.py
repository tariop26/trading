import _path  # noqa
import copy
import re
import unittest
from unittest import mock

import config as cfgmod
import plan

MINUS = "−"


def cfg(**over):
    c = copy.deepcopy(cfgmod.defaults())
    for section, values in over.items():
        if isinstance(values, dict):
            c[section].update(values)
        else:
            c[section] = values
    return c


def an(symbol, setups=(), short=(), trend=None, rsi=50.0, last=100.0, atr_pct=1.0):
    return {"symbol": symbol, "name": "Nom " + symbol, "last": last, "rsi": rsi,
            "atr_pct": atr_pct, "trend": trend, "setups": list(setups),
            "setups_short": list(short), "levels": {}, "last_bar_date": "2026-11-13"}


def ok_size(risk=500.0):
    return {"status": "ok", "lots": None, "units": None, "size": 1.0,
            "risk_usd": risk, "leverage": 1.0, "pip_value_usd_per_lot": None,
            "limited_by": "risque", "note": None}


def status_size(status):
    s = ok_size(None)
    s["status"] = status
    s["size"] = None
    s["limited_by"] = None
    return s


class TestClassify(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(plan.classify(an("X", setups=["breakout_20d"])),
                         ("haussier", ["breakout_20d"], None))
        self.assertEqual(plan.classify(an("X", short=["breakdown_20d"])),
                         ("baissier", ["breakdown_20d"], None))
        self.assertEqual(
            plan.classify(an("X", setups=["bull_flag"], short=["lose_ma20"])),
            (None, [], "signaux contradictoires"))
        self.assertEqual(plan.classify(an("X", setups=["oversold"])), (None, [], None))
        self.assertEqual(plan.classify(an("X", short=["overbought"])), (None, [], None))
        self.assertEqual(plan.classify(an("X")), (None, [], None))

    def test_classify_keeps_states_out_of_triggers_and_tolerates_missing_short(self):
        a = an("X", setups=["oversold", "oversold_bounce"])
        del a["setups_short"]
        self.assertEqual(plan.classify(a), ("haussier", ["oversold_bounce"], None))

    def test_trigger_tuples(self):
        self.assertEqual(plan.LONG_TRIGGERS,
                         ("breakout_20d", "bull_flag", "reclaim_ma20", "oversold_bounce"))
        self.assertEqual(plan.SHORT_TRIGGERS,
                         ("breakdown_20d", "bear_flag", "lose_ma20", "overbought_reject"))


class TestScore(unittest.TestCase):
    def test_score_long_and_short(self):
        a = an("X", setups=["breakout_20d"], trend="up", rsi=25)
        pts, why = plan.score(a, "haussier", ["breakout_20d"])
        self.assertEqual(pts, 4)
        self.assertEqual(why, ["+2 cassure du plus haut 20 j", "+1 tendance haussière",
                               "+1 RSI sous 30 (survente)"])

        a = an("X", setups=["breakout_20d"], trend="down", rsi=77)
        pts, why = plan.score(a, "haussier", ["breakout_20d"])
        self.assertEqual(pts, 0)
        self.assertEqual(why[1], MINUS + "1 tendance baissière (à contre-sens)")
        self.assertEqual(why[2], MINUS + "1 RSI déjà au-dessus de 70")

        a = an("X", short=["breakdown_20d", "lose_ma20"], trend="down", rsi=75)
        pts, why = plan.score(a, "baissier", ["breakdown_20d", "lose_ma20"])
        self.assertEqual(pts, 6)
        self.assertEqual(why[-2:], ["+1 tendance baissière",
                                    "+1 RSI au-dessus de 70 (surachat)"])

    def test_counter_trend_and_rsi_lines_for_short(self):
        a = an("X", short=["breakdown_20d"], trend="up", rsi=20)
        pts, why = plan.score(a, "baissier", ["breakdown_20d"])
        self.assertEqual(pts, 0)
        self.assertEqual(why, ["+2 cassure du plus bas 20 j",
                               MINUS + "1 tendance haussière (à contre-sens)",
                               MINUS + "1 RSI déjà sous 30"])

    def test_mixed_none_trend_and_rsi_zero_points(self):
        for trend in ("mixed", None):
            a = an("X", setups=["bull_flag"], trend=trend, rsi=50)
            pts, why = plan.score(a, "haussier", ["bull_flag"])
            self.assertEqual(pts, 2)
            self.assertEqual(len(why), 1)
        a = an("X", setups=["bull_flag"], rsi=None)
        self.assertEqual(plan.score(a, "haussier", ["bull_flag"])[0], 2)

    def test_rsi_boundaries_are_strict(self):
        for rsi in (30, 70):
            a = an("X", setups=["bull_flag"], rsi=rsi)
            self.assertEqual(plan.score(a, "haussier", ["bull_flag"])[0], 2)


class TestExposures(unittest.TestCase):
    def test_exposures(self):
        self.assertEqual(plan.exposures("EURUSD=X", "haussier"),
                         [("EUR", "+"), ("USD", "-")])
        self.assertEqual(plan.exposures("USDJPY=X", "baissier"),
                         [("USD", "-"), ("JPY", "+")])
        self.assertEqual(plan.exposures("GC=F", "haussier"), [("GC=F", "+")])
        self.assertEqual(plan.exposures("GC=F", "baissier"), [("GC=F", "-")])


class TestMakePlan(unittest.TestCase):
    def test_make_plan_both_sides(self):
        a = an("^X", last=100.0, atr_pct=1.0)
        self.assertEqual(plan.make_plan(a, "haussier", cfg()),
                         {"reference_price": 100.0, "stop": 98.5, "target": 103.0,
                          "rr": 2.0, "atr": 1.0})
        p = plan.make_plan(a, "baissier", cfg())
        self.assertEqual((p["stop"], p["target"], p["rr"]), (101.5, 97.0, 2.0))

    def test_forex_rounding_directions(self):
        # entry 1.08123, ATR 0.00987 -> stop 1.08123-0.014805=1.066425 -> floor 1.06642
        # target 1.08123+2*0.014805=1.11084 (exact) ; use values that are not on the grid
        a = an("EURUSD=X", last=1.08123, atr_pct=0.91)
        atr = 1.08123 * 0.91 / 100
        p = plan.make_plan(a, "haussier", cfg())
        raw_stop, raw_target = 1.08123 - 1.5 * atr, 1.08123 + 3.0 * atr
        self.assertEqual(p["stop"], int(raw_stop * 1e5) / 1e5)
        self.assertLessEqual(p["stop"], raw_stop)
        self.assertEqual(p["target"], int(raw_target * 1e5) / 1e5)
        self.assertLessEqual(p["target"], raw_target)
        pb = plan.make_plan(a, "baissier", cfg())
        raw_stop_b, raw_target_b = 1.08123 + 1.5 * atr, 1.08123 - 3.0 * atr
        self.assertGreaterEqual(pb["stop"], raw_stop_b)
        self.assertGreaterEqual(pb["target"], raw_target_b)
        self.assertLess(pb["stop"] - raw_stop_b, 1e-5)
        self.assertLess(pb["target"] - raw_target_b, 1e-5)
        self.assertEqual(round(pb["stop"], 5), pb["stop"])

    def test_forex_exact_values(self):
        # atr = 1.2345 * 0.5 / 100 = 0.0061725 ; 1.5*atr = 0.00925875 ; 3*atr = 0.0185175
        a = an("EURUSD=X", last=1.2345, atr_pct=0.5)
        p = plan.make_plan(a, "haussier", cfg())
        self.assertEqual(p["stop"], 1.22524)    # 1.22524125 floored
        self.assertEqual(p["target"], 1.25301)  # 1.2530175 floored
        p = plan.make_plan(a, "baissier", cfg())
        self.assertEqual(p["stop"], 1.24376)    # 1.24375875 ceiled
        self.assertEqual(p["target"], 1.21599)  # 1.2159825 ceiled

    def test_jpy_quote_rounds_to_three_decimals(self):
        a = an("USDJPY=X", last=150.123, atr_pct=0.5)
        p = plan.make_plan(a, "haussier", cfg())
        # atr 0.7506150 ; stop 150.123-1.1259225=148.9970775 -> 148.997
        self.assertEqual(p["stop"], 148.997)
        # target 150.123+2.251845=152.374845 -> 152.374
        self.assertEqual(p["target"], 152.374)
        p = plan.make_plan(a, "baissier", cfg())
        self.assertEqual(p["stop"], 151.249)    # 151.2489225 ceiled
        self.assertEqual(p["target"], 147.872)  # 147.871155 ceiled

    def test_non_forex_rounds_to_two_decimals(self):
        a = an("GC=F", last=2034.57, atr_pct=0.8)
        # atr 16.27656 ; stop 2034.57-24.41484=2010.15516 -> 2010.15
        # target 2034.57+48.82968=2083.39968 -> 2083.39
        p = plan.make_plan(a, "haussier", cfg())
        self.assertEqual((p["stop"], p["target"]), (2010.15, 2083.39))
        # baissier: stop 2058.98484 -> 2058.99 ; target 1985.74032 -> 1985.75
        p = plan.make_plan(a, "baissier", cfg())
        self.assertEqual((p["stop"], p["target"]), (2058.99, 1985.75))
        self.assertEqual(p["atr"], 16.27656)

    def test_missing_or_zero_atr_returns_none(self):
        for atr in (None, 0, 0.0, -1.0):
            self.assertIsNone(plan.make_plan(an("X", atr_pct=atr), "haussier", cfg()))
        self.assertIsNone(plan.make_plan(an("X", last=None), "haussier", cfg()))

    def test_config_values_are_used(self):
        c = cfg(plan={"stop_atr_mult": 2.0, "target_r": 3.0})
        p = plan.make_plan(an("^X", last=100.0, atr_pct=1.0), "haussier", c)
        self.assertEqual((p["stop"], p["target"], p["rr"]), (98.0, 106.0, 3.0))


class TestBuildTradeIdeas(unittest.TestCase):
    def test_empty_input(self):
        out = plan.build_trade_ideas([], cfg())
        self.assertEqual(out["ideas"], [])
        self.assertEqual(out["skipped"], [])
        self.assertEqual(out["total_risk_usd"], 0.0)
        self.assertEqual(out["total_risk_pct"], 0.0)
        self.assertIs(out["over_cap"], False)
        self.assertEqual(out["reference"], "last_close")
        self.assertEqual(out["max_total_pct"], 2.0)

    def test_structure(self):
        a = [an("^X", setups=["breakout_20d", "oversold"], short=["overbought"],
                trend="up", rsi=25, last=100.0, atr_pct=1.0)]
        with mock.patch.object(plan.sizing, "size_idea", return_value=ok_size()):
            out = plan.build_trade_ideas(a, cfg())
        self.assertEqual(set(out), {"reference", "account", "ideas", "skipped",
                                    "total_risk_usd", "total_risk_pct",
                                    "max_total_pct", "over_cap"})
        self.assertEqual(out["account"], {"currency": "USD", "capital": 100000,
                                          "risk_per_trade_usd": 500.0,
                                          "leverage_max": 30})
        idea = out["ideas"][0]
        self.assertEqual(list(idea), ["rank", "symbol", "name", "side", "score",
                                      "setups", "trend", "reference_price", "stop",
                                      "target", "rr", "atr", "size", "why"])
        self.assertEqual(idea["rank"], 1)
        self.assertEqual(idea["side"], "haussier")
        self.assertEqual(idea["setups"], ["breakout_20d", "oversold", "overbought"])
        self.assertEqual(idea["trend"], "up")
        self.assertEqual((idea["reference_price"], idea["stop"], idea["target"],
                          idea["rr"], idea["atr"]), (100.0, 98.5, 103.0, 2.0, 1.0))
        self.assertEqual(idea["score"], 4)
        self.assertEqual(idea["size"], ok_size())
        self.assertEqual(len(idea["why"]), 3)

    def test_real_sizing_integration(self):
        a = [an("EURUSD=X", setups=["breakout_20d"], last=1.1, atr_pct=0.5)]
        out = plan.build_trade_ideas(a, cfg())
        size = out["ideas"][0]["size"]
        self.assertEqual(size["status"], "ok")
        self.assertLessEqual(size["risk_usd"], 500.0)

    def test_prices_passed_to_sizing(self):
        analyses = [an("EURUSD=X", setups=["breakout_20d"], last=1.1),
                    an("USDJPY=X", last=150.0), an("GC=F", last=2000.0)]
        with mock.patch.object(plan.sizing, "size_idea", return_value=ok_size()) as m:
            plan.build_trade_ideas(analyses, cfg())
        args = m.call_args[0]
        self.assertEqual(args[0], "EURUSD=X")
        self.assertEqual(args[3], {"EURUSD=X": 1.1, "USDJPY=X": 150.0})
        self.assertEqual(args[4], cfg())

    def test_atr_missing_or_zero_is_skipped(self):
        analyses = [an("^A", setups=["breakout_20d"], atr_pct=None),
                    an("^B", setups=["breakout_20d"], atr_pct=0),
                    an("^C", setups=["breakout_20d"], last=None)]
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual(out["ideas"], [])
        self.assertEqual(out["skipped"],
                         [{"symbol": s, "reason": "ATR indisponible"}
                          for s in ("^A", "^B", "^C")])

    def test_contradictory_is_skipped_and_order(self):
        analyses = [an("^Z", setups=["bull_flag"], short=["bear_flag"]),
                    an("^Y", setups=["bull_flag"], atr_pct=None),
                    an("^W", setups=["oversold"]),
                    an("^V", setups=["bull_flag"])]
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual([i["symbol"] for i in out["ideas"]], ["^V"])
        self.assertEqual(out["skipped"],
                         [{"symbol": "^Z", "reason": "signaux contradictoires"},
                          {"symbol": "^Y", "reason": "ATR indisponible"}])

    def test_ranking_order_and_tie_break(self):
        analyses = [
            an("^D", setups=["bull_flag"]),                                   # 2
            an("^C", setups=["bull_flag"], trend="up", rsi=25),               # 4, 1 trigger
            an("^B", setups=["bull_flag", "breakout_20d"]),                   # 4, 2 triggers
            an("^A", setups=["bull_flag"], trend="up", rsi=25),               # 4, 1 trigger
            an("^E", short=["breakdown_20d", "bear_flag", "lose_ma20"]),      # 6
        ]
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual([i["symbol"] for i in out["ideas"]],
                         ["^E", "^B", "^A", "^C", "^D"])
        self.assertEqual([i["rank"] for i in out["ideas"]], [1, 2, 3, 4, 5])
        again = plan.build_trade_ideas(list(reversed(analyses)), cfg())
        self.assertEqual([i["symbol"] for i in again["ideas"]],
                         ["^E", "^B", "^A", "^C", "^D"])

    def test_diversification_caps_the_same_exposure(self):
        analyses = [an(s, setups=["breakout_20d"])
                    for s in ("USDJPY=X", "USDCHF=X", "USDCAD=X")]
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual([i["symbol"] for i in out["ideas"]],
                         ["USDCAD=X", "USDCHF=X"])
        self.assertEqual(out["skipped"],
                         [{"symbol": "USDJPY=X", "reason": "corrélée à USDCAD=X"}])

    def test_diversification_opposite_sign_is_not_correlated(self):
        analyses = [an("USDJPY=X", setups=["breakout_20d"]),
                    an("USDCHF=X", setups=["breakout_20d"]),
                    an("EURUSD=X", setups=["breakout_20d"]),   # -USD, not +USD
                    an("USDCAD=X", short=["breakdown_20d"])]   # -USD
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual(len(out["ideas"]), 4)
        self.assertEqual(out["skipped"], [])

    def test_max_shown_limit(self):
        analyses = [an("^%s" % c, setups=["breakout_20d"] * 1,
                       trend="up" if i < 2 else None) for i, c in enumerate("ABCDEFG")]
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual(len(out["ideas"]), 5)
        self.assertEqual(out["skipped"],
                         [{"symbol": "^F", "reason": "au-delà des 5 idées affichées"},
                          {"symbol": "^G", "reason": "au-delà des 5 idées affichées"}])
        out = plan.build_trade_ideas(analyses, cfg(ideas={"max_shown": 2}))
        self.assertEqual(out["skipped"][0]["reason"], "au-delà des 2 idées affichées")

    def test_too_wide_and_to_confirm_occupy_slots(self):
        analyses = [an("^%s" % c, setups=["breakout_20d"]) for c in "ABC"]
        sizes = iter([status_size("too_wide"), status_size("to_confirm"), ok_size()])
        with mock.patch.object(plan.sizing, "size_idea",
                               side_effect=lambda *a, **k: next(sizes)):
            out = plan.build_trade_ideas(analyses, cfg(ideas={"max_shown": 2}))
        self.assertEqual([i["size"]["status"] for i in out["ideas"]],
                         ["too_wide", "to_confirm"])
        self.assertEqual(out["skipped"],
                         [{"symbol": "^C", "reason": "au-delà des 2 idées affichées"}])
        # too_wide counts 0, to_confirm counts the planned 500
        self.assertEqual(out["total_risk_usd"], 500.0)

    def _run(self, sizes):
        analyses = [an("^%s" % c, setups=["breakout_20d"]) for c in "ABCDE"[:len(sizes)]]
        it = iter(sizes)
        with mock.patch.object(plan.sizing, "size_idea",
                               side_effect=lambda *a, **k: next(it)):
            return plan.build_trade_ideas(analyses, cfg())

    def test_total_risk_and_over_cap(self):
        out = self._run([ok_size(500.0)] * 5)
        self.assertEqual(out["total_risk_usd"], 2500.0)
        self.assertEqual(out["total_risk_pct"], 2.5)
        self.assertEqual(out["max_total_pct"], 2.0)
        self.assertIs(out["over_cap"], True)

        out = self._run([ok_size(500.0)] * 3 + [status_size("to_confirm")])
        self.assertEqual(out["total_risk_usd"], 2000.0)
        self.assertEqual(out["total_risk_pct"], 2.0)
        self.assertIs(out["over_cap"], False)   # equal to the cap is not over it

        out = self._run([ok_size(500.0)] * 4 + [status_size("to_confirm")])
        self.assertEqual(out["total_risk_usd"], 2500.0)
        self.assertIs(out["over_cap"], True)

        out = self._run([ok_size(500.0)] * 3)
        self.assertEqual(out["total_risk_usd"], 1500.0)
        self.assertEqual(out["total_risk_pct"], 1.5)
        self.assertIs(out["over_cap"], False)

    def test_total_risk_uses_real_risk_of_ok_ideas(self):
        out = self._run([ok_size(123.45), ok_size(100.0)])
        self.assertEqual(out["total_risk_usd"], 223.45)
        self.assertEqual(out["total_risk_pct"], 0.22)

    def test_no_forbidden_vocabulary(self):
        analyses = [an("^A", setups=["reclaim_ma20", "oversold_bounce"], trend="up", rsi=20),
                    an("^B", short=["lose_ma20", "overbought_reject"], trend="down", rsi=80)]
        out = plan.build_trade_ideas(analyses, cfg())
        text = repr(out).lower()
        # whole words only: "surachat" (overbought) is legitimate vocabulary
        self.assertIsNone(re.search(
            r"(achat|acheter|vente|vendre|buy|sell|gagnant|profit)", text))


if __name__ == "__main__":
    unittest.main()
