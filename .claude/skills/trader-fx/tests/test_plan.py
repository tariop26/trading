import _path  # noqa
import copy
import re
import unittest
from unittest import mock

import config as cfgmod
import plan

MINUS = "−"
FORBIDDEN = re.compile(
    r"\b(achat|acheter|vente|vendre|buy|sell|gagnant|profit)\b", re.IGNORECASE)


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
                          "rr": 2.0, "atr": 1.0, "decimals": 2})
        p = plan.make_plan(a, "baissier", cfg())
        self.assertEqual((p["stop"], p["target"], p["rr"]), (101.5, 97.0, 2.0))

    def test_forex_rounding_directions(self):
        # entry 1.08123 (on the grid), ATR 0.0098392 -> raw stop 1.0664712 -> floor 1.06647;
        # distance 0.01476 -> target 1.08123 + 2 * 0.01476 = 1.11075 (from the ROUNDED stop)
        a = an("EURUSD=X", last=1.08123, atr_pct=0.91)
        atr = 1.08123 * 0.91 / 100
        p = plan.make_plan(a, "haussier", cfg())
        raw_stop = 1.08123 - 1.5 * atr
        self.assertEqual(p["stop"], 1.06647)
        self.assertLessEqual(p["stop"], raw_stop)
        self.assertLess(raw_stop - p["stop"], 1e-5)
        self.assertEqual(p["target"], 1.11075)
        self.assertEqual(round(p["target"] - p["reference_price"], 5),
                         round(2 * (p["reference_price"] - p["stop"]), 5))
        pb = plan.make_plan(a, "baissier", cfg())
        raw_stop_b = 1.08123 + 1.5 * atr
        self.assertEqual(pb["stop"], 1.09599)
        self.assertGreaterEqual(pb["stop"], raw_stop_b)
        self.assertLess(pb["stop"] - raw_stop_b, 1e-5)
        self.assertEqual(pb["target"], 1.05171)
        self.assertEqual(round(pb["stop"], 5), pb["stop"])

    def test_forex_exact_values(self):
        # atr = 1.2345 * 0.5 / 100 = 0.0061725 ; 1.5*atr = 0.00925875
        a = an("EURUSD=X", last=1.2345, atr_pct=0.5)
        p = plan.make_plan(a, "haussier", cfg())
        self.assertEqual(p["stop"], 1.22524)    # 1.22524125 floored ; distance 0.00926
        self.assertEqual(p["target"], 1.25302)  # 1.2345 + 2 * 0.00926
        p = plan.make_plan(a, "baissier", cfg())
        self.assertEqual(p["stop"], 1.24376)    # 1.24375875 ceiled ; distance 0.00926
        self.assertEqual(p["target"], 1.21598)  # 1.2345 - 2 * 0.00926

    def test_jpy_quote_rounds_to_three_decimals(self):
        a = an("USDJPY=X", last=150.123, atr_pct=0.5)
        p = plan.make_plan(a, "haussier", cfg())
        self.assertEqual(p["decimals"], 3)
        # atr 0.7506150 ; stop 150.123-1.1259225=148.9970775 -> 148.997 ; distance 1.126
        self.assertEqual(p["stop"], 148.997)
        self.assertEqual(p["target"], 152.375)  # 150.123 + 2.252
        p = plan.make_plan(a, "baissier", cfg())
        self.assertEqual(p["stop"], 151.249)    # 151.2489225 ceiled ; distance 1.126
        self.assertEqual(p["target"], 147.871)  # 150.123 - 2.252

    def test_non_forex_rounds_to_two_decimals_above_100(self):
        a = an("GC=F", last=2034.57, atr_pct=0.8)
        # atr 16.27656 ; stop 2034.57-24.41484=2010.15516 -> 2010.15 ; distance 24.42
        # target 2034.57+48.84=2083.41
        p = plan.make_plan(a, "haussier", cfg())
        self.assertEqual(p["decimals"], 2)
        self.assertEqual((p["stop"], p["target"]), (2010.15, 2083.41))
        # baissier: stop 2058.98484 -> 2058.99 ; distance 24.42 ; target 1985.73
        p = plan.make_plan(a, "baissier", cfg())
        self.assertEqual((p["stop"], p["target"]), (2058.99, 1985.73))
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
                                    "max_total_pct", "over_cap", "max_ideas_within_cap",
                                    "ties_at_cutoff", "total_leverage"})
        self.assertEqual(out["account"], {"currency": "USD", "capital": 100000,
                                          "risk_per_trade_usd": 500.0,
                                          "leverage_max": 30})
        idea = out["ideas"][0]
        self.assertEqual(list(idea), ["rank", "symbol", "name", "side", "score",
                                      "setups", "trend", "reference_price", "stop",
                                      "target", "rr", "atr", "decimals", "size", "why",
                                      "last_bar_date", "since_close"])
        self.assertEqual(idea["decimals"], 2)
        self.assertEqual(idea["last_bar_date"], "2026-11-13")
        self.assertIsNone(idea["since_close"])
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

    def test_non_positive_stop_or_target_is_skipped_without_sizing(self):
        reason = "plan impossible : stop ou cible sous zéro"
        # haussier: atr 80 % of 100 -> stop 100 - 1.5 * 80 = -20
        with mock.patch.object(plan.sizing, "size_idea", return_value=ok_size()) as m:
            out = plan.build_trade_ideas(
                [an("^A", setups=["breakout_20d"], atr_pct=80.0)], cfg())
        self.assertEqual(out["ideas"], [])
        self.assertEqual(out["skipped"], [{"symbol": "^A", "reason": reason}])
        m.assert_not_called()
        # baissier: last 3.0, atr 4 %, mult 5, target_r 5 -> target 3 - 5 * 0.6 = 0.0
        c = cfg(plan={"stop_atr_mult": 5.0, "target_r": 5.0})
        with mock.patch.object(plan.sizing, "size_idea", return_value=ok_size()) as m:
            out = plan.build_trade_ideas(
                [an("NG=F", short=["breakdown_20d"], last=3.0, atr_pct=4.0)], c)
        self.assertEqual(out["ideas"], [])
        self.assertEqual(out["skipped"], [{"symbol": "NG=F", "reason": reason}])
        m.assert_not_called()

    def test_non_positive_last_is_atr_unavailable(self):
        for last in (0, 0.0, -5.0):
            self.assertIsNone(plan.make_plan(an("^X", last=last), "haussier", cfg()))
        with mock.patch.object(plan.sizing, "size_idea", return_value=ok_size()) as m:
            out = plan.build_trade_ideas(
                [an("^A", setups=["breakout_20d"], last=0),
                 an("^B", setups=["breakout_20d"], last=-5.0)], cfg())
        self.assertEqual(out["skipped"],
                         [{"symbol": "^A", "reason": "ATR indisponible"},
                          {"symbol": "^B", "reason": "ATR indisponible"}])
        m.assert_not_called()

    def test_analysis_without_last_key_does_not_raise(self):
        a = an("EURUSD=X", setups=["breakout_20d"])
        del a["last"]
        b = an("USDJPY=X", setups=["breakout_20d"], last=150.0)
        out = plan.build_trade_ideas([a, b], cfg())
        self.assertEqual(out["skipped"],
                         [{"symbol": "EURUSD=X", "reason": "ATR indisponible"}])
        self.assertEqual([i["symbol"] for i in out["ideas"]], ["USDJPY=X"])

    def test_early_drops_keep_input_order_with_impossible_plan(self):
        analyses = [an("^Z", setups=["bull_flag"], atr_pct=80.0),
                    an("^Y", setups=["bull_flag"], short=["bear_flag"]),
                    an("^X", setups=["bull_flag"], atr_pct=None),
                    an("^V", setups=["bull_flag"])]
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual([s["symbol"] for s in out["skipped"]], ["^Z", "^Y", "^X"])
        self.assertEqual([i["symbol"] for i in out["ideas"]], ["^V"])

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
                         [{"symbol": "^F", "reason": "au-delà des 5 idées affichées (score 2)"},
                          {"symbol": "^G", "reason": "au-delà des 5 idées affichées (score 2)"}])
        self.assertEqual(out["ties_at_cutoff"], 2)      # ^E (score 2) is the last shown
        out = plan.build_trade_ideas(analyses, cfg(ideas={"max_shown": 2}))
        self.assertEqual(out["skipped"][0]["reason"], "au-delà des 2 idées affichées (score 2)")
        self.assertEqual(out["ties_at_cutoff"], 0)      # ^B (score 3) is the last shown

    def test_too_wide_and_to_confirm_occupy_slots(self):
        analyses = [an("^%s" % c, setups=["breakout_20d"]) for c in "ABC"]
        sizes = iter([status_size("too_wide"), status_size("to_confirm"), ok_size()])
        with mock.patch.object(plan.sizing, "size_idea",
                               side_effect=lambda *a, **k: next(sizes)):
            out = plan.build_trade_ideas(analyses, cfg(ideas={"max_shown": 2}))
        self.assertEqual([i["size"]["status"] for i in out["ideas"]],
                         ["too_wide", "to_confirm"])
        self.assertEqual(out["skipped"],
                         [{"symbol": "^C", "reason": "au-delà des 2 idées affichées (score 2)"}])
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
                    an("^B", short=["lose_ma20", "overbought_reject"], trend="down", rsi=80),
                    an("^C", setups=["bull_flag"], short=["bear_flag"]),
                    an("^D", setups=["bull_flag"], atr_pct=None),
                    an("^E", setups=["bull_flag"], atr_pct=80.0),
                    an("USDJPY=X", setups=["breakout_20d"], trend="down", rsi=75)]
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertTrue(out["ideas"] and out["skipped"])
        text = repr(out)
        # negative controls: the regex really matches whole forbidden words...
        self.assertIsNotNone(FORBIDDEN.search("un achat"))
        self.assertIsNotNone(FORBIDDEN.search("la vente"))
        self.assertIsNotNone(FORBIDDEN.search("BUY now"))
        # ...and not legitimate words that merely contain them
        self.assertIsNone(FORBIDDEN.search("surachat"))
        self.assertIsNone(FORBIDDEN.search("survente"))
        self.assertIsNone(FORBIDDEN.search(text))


def lev_size(risk, leverage):
    s = ok_size(risk)
    s["leverage"] = leverage
    return s


class TestFinalWave(unittest.TestCase):
    """Tick by magnitude, rounded entry, strict sides, stop floor, guard, cutoff ties,
    cents cap, max_ideas_within_cap, total_leverage, aligned labels."""

    def run_sizes(self, sizes, config=None):
        letters = "ABCDEFGHIJ"[:len(sizes)]
        analyses = [an("^%s" % c, setups=["breakout_20d"]) for c in letters]
        it = iter(sizes)
        c = config or cfg(ideas={"max_shown": 10, "max_per_exposure": 5})
        with mock.patch.object(plan.sizing, "size_idea",
                               side_effect=lambda *a, **k: next(it)):
            return plan.build_trade_ideas(analyses, c)

    # ---- B1 decimals / tick

    def test_decimals_by_instrument_and_magnitude(self):
        for symbol, last, decimals in (("NG=F", 3.0, 4), ("GC=F", 2000.0, 2),
                                       ("USDJPY=X", 150.0, 3), ("EURUSD=X", 1.1, 5),
                                       ("CL=F", 71.4, 3), ("^X", 100.0, 2),
                                       ("^X", 99.99, 3), ("^X", 10.0, 3), ("^X", 9.99, 4),
                                       ("EURJPY=X", 162.0, 3), ("USDZAR=X", 18.2, 5)):
            p = plan.make_plan(an(symbol, last=last, atr_pct=1.0), "haussier", cfg())
            self.assertEqual(p["decimals"], decimals, symbol + " %s" % last)
            for k in ("reference_price", "stop", "target"):
                self.assertEqual(round(p[k], decimals), p[k], (symbol, k))

    def test_idea_carries_decimals(self):
        out = plan.build_trade_ideas([an("NG=F", setups=["bull_flag"], last=3.0123,
                                         atr_pct=2.5)], cfg())
        self.assertEqual(out["ideas"][0]["decimals"], 4)
        self.assertIsInstance(out["ideas"][0]["decimals"], int)

    # ---- B2 rounding and consistency

    def test_entry_rounded_to_the_nearest_tick_and_sizing_uses_the_rounded_plan(self):
        # last 1.234567 -> entry 1.23457 (nearest) ; raw stop from the UNROUNDED last:
        # 1.234567 - 1.5 * 0.006172835 = 1.2253077 -> floor 1.22530 ; distance 0.00927
        # target 1.23457 + 2 * 0.00927 = 1.25311
        a = an("EURUSD=X", setups=["breakout_20d"], last=1.234567, atr_pct=0.5)
        with mock.patch.object(plan.sizing, "size_idea", return_value=ok_size()) as m:
            out = plan.build_trade_ideas([a], cfg())
        idea = out["ideas"][0]
        self.assertEqual((idea["reference_price"], idea["stop"], idea["target"]),
                         (1.23457, 1.2253, 1.25311))
        args = m.call_args[0]
        self.assertEqual((args[0], args[1], args[2]), ("EURUSD=X", 1.23457, 1.2253))
        # rounded DOWN to the nearest tick too
        p = plan.make_plan(an("EURUSD=X", last=1.234563, atr_pct=0.5), "haussier", cfg())
        self.assertEqual(p["reference_price"], 1.23456)

    def test_stop_comes_from_the_unrounded_last(self):
        # last 150.1234 -> entry 150.123 ; baissier raw stop 150.1234 + 1.1259255
        # = 151.2493255 -> ceil 151.250 (from 150.123 it would be 151.249) ; distance 1.127
        # target 150.123 - 2.254 = 147.869
        p = plan.make_plan(an("USDJPY=X", last=150.1234, atr_pct=0.5), "baissier", cfg())
        self.assertEqual((p["reference_price"], p["stop"], p["target"]),
                         (150.123, 151.25, 147.869))

    def test_target_consistent_with_rounded_entry_and_stop(self):
        cases = (  # symbol, last, atr_pct, side, (entry, stop, target)
            ("NG=F", 3.0123, 2.5, "haussier", (3.0123, 2.8993, 3.2383)),
            ("NG=F", 3.0123, 2.5, "baissier", (3.0123, 3.1253, 2.7863)),
            ("USDJPY=X", 150.123, 0.5, "haussier", (150.123, 148.997, 152.375)),
            ("USDJPY=X", 150.123, 0.5, "baissier", (150.123, 151.249, 147.871)),
            ("GC=F", 2034.57, 0.8, "baissier", (2034.57, 2058.99, 1985.73)),
        )
        for symbol, last, atr_pct, side, want in cases:
            p = plan.make_plan(an(symbol, last=last, atr_pct=atr_pct), side, cfg())
            self.assertEqual((p["reference_price"], p["stop"], p["target"]), want,
                             (symbol, side))

    def test_rounding_invariants_sweep(self):
        import random
        rng = random.Random(1114)
        for i in range(3000):
            symbol, base = (("EURUSD=X", 1.1), ("USDJPY=X", 150.0), ("NG=F", 3.0),
                            ("CL=F", 70.0), ("GC=F", 2000.0))[i % 5]
            last = base * rng.uniform(0.8, 1.2)
            side = ("haussier", "baissier")[i % 2]
            c = cfg(plan={"stop_atr_mult": rng.choice([0.5, 1.0, 1.5, 3.0]),
                          "target_r": rng.choice([1.0, 1.5, 2.0, 3.7])})
            p = plan.make_plan(an(symbol, last=last, atr_pct=rng.uniform(0.2, 4.0)), side, c)
            tick = 10 ** -p["decimals"]
            e, s, t = p["reference_price"], p["stop"], p["target"]
            self.assertLessEqual(abs(e - last), tick / 2 + 1e-12)
            d = abs(e - s)
            want = c["plan"]["target_r"] * d
            # target rounded TOWARD the entry: never further than target_r * d, less
            # than one tick closer
            self.assertLessEqual(abs(t - e), want + 1e-9)
            self.assertGreater(abs(t - e), want - tick - 1e-9)
            if side == "haussier":
                self.assertLess(s, e)
                self.assertLess(e, t)
            else:
                self.assertLess(t, e)
                self.assertLess(e, s)

    # ---- B3 strict sides

    def test_target_equal_to_entry_after_rounding_is_dropped(self):
        # last 1.100004, ATR 0.0001 % -> raw stop 1.1000024 -> floor 1.10000 = entry:
        # distance 0, target 1.1 = entry -> impossible plan, never sized
        a = an("EURUSD=X", setups=["breakout_20d"], last=1.100004, atr_pct=0.0001)
        p = plan.make_plan(a, "haussier", cfg())
        self.assertEqual((p["reference_price"], p["stop"], p["target"]), (1.1, 1.1, 1.1))
        with mock.patch.object(plan.sizing, "size_idea", return_value=ok_size()) as m:
            out = plan.build_trade_ideas([a], cfg())
        self.assertEqual(out["ideas"], [])
        self.assertEqual(out["skipped"],
                         [{"symbol": "EURUSD=X",
                           "reason": "plan impossible : stop ou cible sous zéro"}])
        m.assert_not_called()

    # ---- B4 stop-distance floor

    def test_min_stop_pct_constant(self):
        self.assertEqual(plan.MIN_STOP_PCT, 0.15)

    def test_stop_in_the_noise_is_dropped(self):
        reason = "ATR trop faible : stop dans le bruit ou l'écart de cotation"
        analyses = [an("^K", setups=["bull_flag"], atr_pct=0.11),        # d 0.17 % kept
                    an("EURUSD=X", setups=["breakout_20d"], last=1.1, atr_pct=0.05),
                    an("^C", setups=["bull_flag"], short=["bear_flag"]),
                    an("USDHKD=X", short=["breakdown_20d"], last=7.8, atr_pct=0.02)]
        with mock.patch.object(plan.sizing, "size_idea", return_value=ok_size()) as m:
            out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual(out["skipped"],
                         [{"symbol": "EURUSD=X", "reason": reason},
                          {"symbol": "^C", "reason": "signaux contradictoires"},
                          {"symbol": "USDHKD=X", "reason": reason}])
        self.assertEqual([i["symbol"] for i in out["ideas"]], ["^K"])
        self.assertEqual([c[0][0] for c in m.call_args_list], ["^K"])   # never sized

    # ---- B5 per-symbol guard

    def test_arithmetic_error_in_sizing_drops_only_that_symbol(self):
        real = plan.sizing.size_idea

        def flaky(symbol, *a, **k):
            if symbol == "^B":
                raise ZeroDivisionError("boom")
            return real(symbol, *a, **k)
        analyses = [an("^A", setups=["bull_flag"]), an("^B", setups=["bull_flag"]),
                    an("^C", setups=["bull_flag"], atr_pct=None)]
        with mock.patch.object(plan.sizing, "size_idea", side_effect=flaky):
            out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual(out["skipped"],
                         [{"symbol": "^B", "reason": "calcul impossible (ZeroDivisionError)"},
                          {"symbol": "^C", "reason": "ATR indisponible"}])
        self.assertEqual([i["symbol"] for i in out["ideas"]], ["^A"])

    def test_arithmetic_error_in_planning_drops_only_that_symbol(self):
        real = plan.make_plan

        def flaky(a, side, config):
            if a["symbol"] == "^A":
                raise OverflowError("big")
            return real(a, side, config)
        with mock.patch.object(plan, "make_plan", side_effect=flaky):
            out = plan.build_trade_ideas(
                [an("^A", setups=["bull_flag"]), an("^B", setups=["bull_flag"])], cfg())
        self.assertEqual(out["skipped"],
                         [{"symbol": "^A", "reason": "calcul impossible (OverflowError)"}])
        self.assertEqual([i["symbol"] for i in out["ideas"]], ["^B"])

    # ---- B6 display limit reason and ties

    def test_ties_at_cutoff(self):
        analyses = [an("^%s" % c, setups=["breakout_20d"]) for c in "FEDCBA"]
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual([i["symbol"] for i in out["ideas"]], ["^A", "^B", "^C", "^D", "^E"])
        self.assertEqual(out["skipped"],
                         [{"symbol": "^F", "reason": "au-delà des 5 idées affichées (score 2)"}])
        self.assertEqual(out["ties_at_cutoff"], 1)
        # a lower score below the cutoff is not a tie
        analyses[0] = an("^F", setups=["breakout_20d"], trend="down")      # score 1
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual(out["skipped"][0]["reason"], "au-delà des 5 idées affichées (score 1)")
        self.assertEqual(out["ties_at_cutoff"], 0)
        self.assertEqual(plan.build_trade_ideas([], cfg())["ties_at_cutoff"], 0)

    def test_correlated_skips_are_not_ties(self):
        analyses = [an(s, setups=["breakout_20d"]) for s in ("USDJPY=X", "USDCHF=X", "USDCAD=X")]
        out = plan.build_trade_ideas(analyses, cfg())
        self.assertEqual(out["ties_at_cutoff"], 0)

    # ---- B7 cumulated risk in cents

    def test_over_cap_exactly_at_the_cap_is_false(self):
        out = self.run_sizes([ok_size(500.0)] * 4)
        self.assertEqual(out["total_risk_usd"], 2000.0)
        self.assertIs(out["over_cap"], False)
        self.assertEqual(out["max_ideas_within_cap"], 4)
        # 0.7 % x 4 to_confirm against a 2.8 % cap: equal in cents (floats differ)
        c = cfg(risk={"per_trade_pct": 0.7, "max_total_pct": 2.8},
                ideas={"max_shown": 10, "max_per_exposure": 5})
        self.assertNotEqual(4 * (100000 * 0.7 / 100) / 100000 * 100, 2.8)   # the old trap
        out = self.run_sizes([status_size("to_confirm")] * 4, c)
        self.assertEqual(out["total_risk_usd"], 2800.0)
        self.assertIs(out["over_cap"], False)
        self.assertEqual(out["max_ideas_within_cap"], 4)

    def test_over_cap_one_cent_above_is_true(self):
        out = self.run_sizes([ok_size(500.0)] * 3 + [ok_size(500.01)])
        self.assertEqual(out["total_risk_usd"], 2000.01)
        self.assertIs(out["over_cap"], True)
        self.assertEqual(out["max_ideas_within_cap"], 3)

    def test_max_ideas_within_cap_with_mixed_statuses(self):
        sizes = [ok_size(400.0), status_size("to_confirm"), status_size("too_wide"),
                 ok_size(300.0), ok_size(450.0)]
        # cap 1 % = 1000 ; counted risks 500, 450, 400, 300 (too_wide excluded)
        c = cfg(risk={"max_total_pct": 1.0}, ideas={"max_shown": 10, "max_per_exposure": 5})
        out = self.run_sizes(list(sizes), c)
        self.assertEqual(out["total_risk_usd"], 1650.0)
        self.assertIs(out["over_cap"], True)
        self.assertEqual(out["max_ideas_within_cap"], 2)      # 500 + 450 <= 1000 < +400
        out = self.run_sizes(list(sizes))                     # cap 2 %
        self.assertIs(out["over_cap"], False)
        self.assertEqual(out["max_ideas_within_cap"], 4)      # the four counted ideas
        out = self.run_sizes([status_size("too_wide")] * 2)
        self.assertEqual((out["max_ideas_within_cap"], out["over_cap"]), (0, False))
        self.assertEqual(plan.build_trade_ideas([], cfg())["max_ideas_within_cap"], 0)

    def test_max_ideas_within_cap_uses_the_largest_risks_not_the_smallest(self):
        # cap 0.7 % of 100 000 = 700 ; counted risks 500 (to_confirm, at the per-trade
        # budget), 300, 300: the two largest (500 + 300 = 800) do not fit, 500 alone does
        # -> 1. A k-smallest implementation (300 + 300 = 600 <= 700) would answer 2.
        c = cfg(risk={"per_trade_pct": 0.5, "max_total_pct": 0.7},
                ideas={"max_shown": 10, "max_per_exposure": 5})
        sizes = [ok_size(300.0), status_size("to_confirm"), ok_size(300.0)]
        out = self.run_sizes(list(sizes), c)
        self.assertEqual(out["total_risk_usd"], 1100.0)
        self.assertEqual(out["max_ideas_within_cap"], 1)
        self.assertIs(out["over_cap"], True)
        counted = 3
        self.assertEqual(out["over_cap"] is False, out["max_ideas_within_cap"] == counted)
        # everything fits: 1.2 % cap -> all three counted, not over the cap
        c = cfg(risk={"per_trade_pct": 0.5, "max_total_pct": 1.2},
                ideas={"max_shown": 10, "max_per_exposure": 5})
        out = self.run_sizes(list(sizes), c)
        self.assertEqual(out["max_ideas_within_cap"], 3)
        self.assertIs(out["over_cap"], False)
        self.assertEqual(out["over_cap"] is False, out["max_ideas_within_cap"] == counted)

    def test_displayed_money_rounds_a_half_cent_tie_upward(self):
        # capital 25 at 0.5 % -> budget 0.125 (exact tie): a to_confirm idea counts at it
        c = cfg(account={"capital": 25}, risk={"per_trade_pct": 0.5, "max_total_pct": 5.0},
                ideas={"max_shown": 10, "max_per_exposure": 5})
        out = self.run_sizes([status_size("to_confirm")], c)
        self.assertEqual(out["account"]["risk_per_trade_usd"], 0.13)
        self.assertEqual(out["total_risk_usd"], 0.13)
        self.assertIs(out["over_cap"], False)

    def test_over_cap_false_exactly_when_all_counted_ideas_fit(self):
        import random
        rng = random.Random(2811)
        for _ in range(400):
            n = rng.randint(1, 10)
            sizes = []
            for _ in range(n):
                r = rng.random()
                if r < 0.15:
                    sizes.append(status_size("too_wide"))
                elif r < 0.35:
                    sizes.append(status_size("to_confirm"))
                else:
                    sizes.append(ok_size(round(rng.uniform(1.0, 500.0), 2)))
            counted = sum(1 for s in sizes if s["status"] != "too_wide")
            c = cfg(risk={"max_total_pct": rng.choice([0.5, 1.0, 1.5, 2.0, 2.8, 4.0])},
                    ideas={"max_shown": 10, "max_per_exposure": 5})
            out = self.run_sizes(sizes, c)
            self.assertEqual(out["over_cap"] is False,
                             out["max_ideas_within_cap"] == counted)
            self.assertLessEqual(out["max_ideas_within_cap"], counted)

    def test_total_leverage(self):
        out = self.run_sizes([lev_size(500.0, 1.234), status_size("to_confirm"),
                              lev_size(400.0, 2.5), status_size("too_wide")])
        self.assertEqual(out["total_leverage"], 3.73)
        out = self.run_sizes([status_size("to_confirm")])
        self.assertEqual(out["total_leverage"], 0.0)
        self.assertEqual(plan.build_trade_ideas([], cfg())["total_leverage"], 0.0)

    # ---- B9 labels aligned with the page

    def test_why_labels_match_the_page_chips(self):
        a = an("^A", setups=["reclaim_ma20", "oversold_bounce"])
        _, why = plan.score(a, "haussier", ["reclaim_ma20", "oversold_bounce"])
        self.assertEqual(why, ["+2 reprise de la moyenne 20 j",
                               "+2 rebond depuis la survente"])


if __name__ == "__main__":
    unittest.main()
