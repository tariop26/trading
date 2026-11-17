import _path  # noqa
import copy
import json
import os
import tempfile
import unittest

import config

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "config.example.json")

EXPECTED = {
    "account": {"currency": "USD", "capital": 100000},
    "risk": {"per_trade_pct": 0.5, "max_total_pct": 2.0},
    "leverage_max": 30,
    "plan": {"stop_atr_mult": 1.5, "target_r": 2.0},
    "ideas": {"max_shown": 5, "max_per_exposure": 2},
    "contracts": {},
    "alerts": {"auto_push": False},
    "intraday": {
        "enabled": True, "symbols": [], "mt5_symbols": {},
        "families": ["session_break", "bb_return", "fractal_break", "engulfing", "rsi_exit"],
        "range_minutes": 30, "break_window_hours": 3,
        "bb_period": 20, "bb_std": 2.0,
        "rsi_period": 14, "rsi_low": 30, "rsi_high": 70,
        "engulfing_min_prior": 3,
        "min_stop_pct": 0.05, "max_stop_daily_atr": 1.0, "min_rr": 1.0,
        "score_per_signal": 2, "score_trend": 1, "window_bars": 4,
        "max_age_minutes": 30, "validity_r": 0.25,
        "max_per_run": 3, "max_per_day": 10, "max_per_exposure": 2,
        "cooldown_minutes": 120, "min_score": None,
    },
}


class ConfigTests(unittest.TestCase):
    def assertRejects(self, cfg, keyword):
        with self.assertRaises(config.ConfigError) as ctx:
            config.validate(cfg)
        msg = str(ctx.exception)
        self.assertIn(keyword, msg)
        self.assertNotIn("\n", msg)
        self.assertTrue(msg[0].isupper(), msg)
        self.assertTrue(msg.endswith("."), msg)

    def test_defaults_match_the_spec(self):
        self.assertEqual(config.defaults(), EXPECTED)
        self.assertEqual(config.DEFAULTS, EXPECTED)
        d = config.defaults()
        d["risk"]["per_trade_pct"] = 99
        d["contracts"]["X"] = {}
        self.assertEqual(config.DEFAULTS, EXPECTED)
        self.assertEqual(config.defaults(), EXPECTED)

    def test_validate_defaults_roundtrip(self):
        self.assertEqual(config.validate({}), EXPECTED)

    def test_missing_file_gives_defaults(self):
        missing = os.path.join(tempfile.gettempdir(), "no-such-dir-xyz", "config.json")
        self.assertEqual(config.load_config(missing), EXPECTED)
        self.assertEqual(config.load_config(None), EXPECTED)
        self.assertEqual(config.load_config(""), EXPECTED)

    def test_partial_override_keeps_other_defaults(self):
        got = config.validate({"risk": {"per_trade_pct": 1}})
        want = copy.deepcopy(EXPECTED)
        want["risk"]["per_trade_pct"] = 1
        self.assertEqual(got, want)

    def test_validate_does_not_mutate_input(self):
        cfg = {"risk": {"per_trade_pct": 1}}
        config.validate(cfg)
        self.assertEqual(cfg, {"risk": {"per_trade_pct": 1}})

    def test_rejects(self):
        self.assertRejects({"account": {"currency": "EUR"}}, "devise de compte non gérée : USD seulement")
        self.assertRejects({"account": {"currency": "EUR"}}, "account.currency")
        self.assertRejects({"account": {"capital": 0}}, "account.capital")
        self.assertRejects({"account": {"capital": -5}}, "account.capital")
        self.assertRejects({"account": {"capital": "100000"}}, "account.capital")
        self.assertRejects({"account": {"capital": True}}, "account.capital")
        self.assertRejects({"account": {"capital": float("nan")}}, "account.capital")
        self.assertRejects({"account": {"capital": float("inf")}}, "account.capital")
        self.assertRejects({"risk": {"per_trade_pct": 0}}, "risk.per_trade_pct")
        self.assertRejects({"risk": {"per_trade_pct": 2.5}}, "risk.per_trade_pct")
        self.assertRejects({"risk": {"per_trade_pct": True}}, "risk.per_trade_pct")
        self.assertRejects({"risk": {"per_trade_pct": 1.5, "max_total_pct": 1}}, "risk.max_total_pct")
        self.assertRejects({"risk": {"max_total_pct": 0.3}}, "risk.max_total_pct")
        self.assertRejects({"risk": {"max_total_pct": 11}}, "risk.max_total_pct")
        self.assertRejects({"leverage_max": 0}, "leverage_max")
        self.assertRejects({"leverage_max": 501}, "leverage_max")
        self.assertRejects({"plan": {"stop_atr_mult": 0.4}}, "plan.stop_atr_mult")
        self.assertRejects({"plan": {"stop_atr_mult": 5.1}}, "plan.stop_atr_mult")
        self.assertRejects({"plan": {"target_r": 0.9}}, "plan.target_r")
        self.assertRejects({"plan": {"target_r": 5.1}}, "plan.target_r")
        self.assertRejects({"ideas": {"max_shown": 0}}, "ideas.max_shown")
        self.assertRejects({"ideas": {"max_shown": 11}}, "ideas.max_shown")
        self.assertRejects({"ideas": {"max_shown": 2.5}}, "ideas.max_shown")
        self.assertRejects({"ideas": {"max_per_exposure": 0}}, "ideas.max_per_exposure")
        self.assertRejects({"ideas": {"max_per_exposure": 6}}, "ideas.max_per_exposure")
        self.assertRejects({"ideas": {"max_per_exposure": 1.5}}, "ideas.max_per_exposure")

    def test_rejects_unknown_keys(self):
        self.assertRejects({"colour": 1}, "clé inconnue")
        self.assertRejects({"colour": 1}, "colour")
        self.assertRejects({"risk": {"per_trade": 1}}, "clé inconnue")
        self.assertRejects({"risk": {"per_trade": 1}}, "risk.per_trade")
        self.assertRejects({"_note": "x"}, "clé inconnue")

    def test_alerts_section_defaults_and_booleans(self):
        self.assertIs(config.validate({})["alerts"]["auto_push"], False)
        self.assertIs(config.validate({"alerts": {}})["alerts"]["auto_push"], False)
        self.assertIs(config.validate({"alerts": {"auto_push": True}})["alerts"]["auto_push"], True)
        self.assertIs(config.validate({"alerts": {"auto_push": False}})["alerts"]["auto_push"], False)

    def test_alerts_section_rejects(self):
        for bad in ("yes", 1, 0, None):
            self.assertRejects({"alerts": {"auto_push": bad}}, "alerts.auto_push")
        self.assertRejects({"alerts": 3}, "alerts")
        self.assertRejects({"alerts": {"foo": True}}, "alerts.foo")

    def test_rejects_non_object_section(self):
        self.assertRejects({"risk": 1}, "risk")
        self.assertRejects({"account": []}, "account")
        self.assertRejects({"contracts": []}, "contracts")

    def test_rejects_bad_contracts(self):
        ok = {"usd_per_point": 1.1, "step": 0.1, "min": 0.1}
        no_step = {"usd_per_point": 1.1, "min": 0.1}
        neg = {"usd_per_point": -1, "step": 0.1, "min": 0.1}
        zero_min = {"usd_per_point": 1.1, "step": 0.1, "min": 0}
        extra = dict(ok, note="x")
        self.assertRejects({"contracts": {"^FCHI": no_step}}, "contracts.^FCHI.step")
        self.assertRejects({"contracts": {"^FCHI": neg}}, "contracts.^FCHI.usd_per_point")
        self.assertRejects({"contracts": {"^FCHI": zero_min}}, "contracts.^FCHI.min")
        self.assertRejects({"contracts": {"^FCHI": extra}}, "contracts.^FCHI.note")
        self.assertRejects({"contracts": {"^FCHI": 3}}, "contracts.^FCHI")
        self.assertRejects({"contracts": {"^FCHI": dict(ok, step=True)}}, "contracts.^FCHI.step")

    def test_accepts_a_valid_contract_table(self):
        table = {"^FCHI": {"usd_per_point": 1.1, "step": 0.1, "min": 0.1}}
        got = config.validate({"contracts": table})
        self.assertEqual(got["contracts"], table)
        # contracts is taken whole, defaults are not merged into it
        got = config.validate({"contracts": {}})
        self.assertEqual(got["contracts"], {})

    def test_accepts_boundaries(self):
        got = config.validate({
            "risk": {"per_trade_pct": 2, "max_total_pct": 10},
            "leverage_max": 500,
            "plan": {"stop_atr_mult": 0.5, "target_r": 5},
            "ideas": {"max_shown": 10, "max_per_exposure": 1},
        })
        self.assertEqual(got["risk"]["max_total_pct"], 10)
        self.assertEqual(got["ideas"]["max_shown"], 10)

    def _tmp(self, content, mode="w", **kw):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.addCleanup(os.remove, path)
        with open(path, mode, **kw) as fh:
            fh.write(content)
        return path

    def test_load_valid_file_with_bom(self):
        path = self._tmp(json.dumps({"leverage_max": 10}), mode="w", encoding="utf-8-sig")
        self.assertEqual(config.load_config(path)["leverage_max"], 10)

    def test_invalid_json_and_non_object_file_raise(self):
        for content in ("{not json", "[1, 2]", "42", ""):
            path = self._tmp(content)
            with self.assertRaises(config.ConfigError) as ctx:
                config.load_config(path)
            self.assertNotIn("\n", str(ctx.exception))
            self.assertTrue(str(ctx.exception).endswith("."))

    def test_undecodable_file_raises(self):
        path = self._tmp("", mode="w")
        with open(path, "wb") as fh:
            fh.write(b"\xff\xfe\x00\xd8{")
        with self.assertRaises(config.ConfigError):
            config.load_config(path)

    def test_directory_path_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(config.ConfigError):
                config.load_config(d)

    def test_invalid_values_in_file_raise(self):
        path = self._tmp(json.dumps({"leverage_max": 0}))
        with self.assertRaises(config.ConfigError):
            config.load_config(path)

    def test_example_file_is_valid(self):
        with open(EXAMPLE, encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertEqual(set(raw) - set(config.DEFAULTS), set())
        for section, value in config.DEFAULTS.items():
            if isinstance(value, dict) and section != "contracts":
                self.assertEqual(set(raw[section]) - set(value), set(), section)
        cfg = config.load_config(EXAMPLE)
        self.assertIn("^FCHI", cfg["contracts"])
        self.assertIn("GC=F", cfg["contracts"])
        self.assertEqual(cfg["contracts"]["^FCHI"], {"usd_per_point": 1.1, "step": 0.1, "min": 0.1})
        self.assertEqual(cfg["contracts"]["GC=F"], {"usd_per_point": 100.0, "step": 0.01, "min": 0.01})

    def test_intraday_defaults(self):
        got = config.validate({})["intraday"]
        self.assertEqual(got, EXPECTED["intraday"])
        self.assertEqual(config.DEFAULTS["intraday"], EXPECTED["intraday"])
        self.assertEqual(config.INTRADAY_FAMILIES,
                         ("session_break", "bb_return", "fractal_break", "engulfing", "rsi_exit"))
        self.assertEqual(tuple(got["families"]), config.INTRADAY_FAMILIES)

    def test_intraday_partial_override_and_no_mutation(self):
        cfg = {"intraday": {"enabled": False, "symbols": ["EURUSD=X"],
                            "mt5_symbols": {"EURUSD=X": "EURUSD.r"}, "min_score": 5}}
        snapshot = copy.deepcopy(cfg)
        got = config.validate(cfg)["intraday"]
        self.assertFalse(got["enabled"])
        self.assertEqual(got["symbols"], ["EURUSD=X"])
        self.assertEqual(got["mt5_symbols"], {"EURUSD=X": "EURUSD.r"})
        self.assertEqual(got["min_score"], 5)
        self.assertEqual(got["range_minutes"], 30)
        self.assertEqual(cfg, snapshot)

    def test_intraday_unknown_key_refused(self):
        self.assertRejects({"intraday": {"xxx": 1}}, "clé inconnue intraday.xxx")

    def test_intraday_not_an_object(self):
        self.assertRejects({"intraday": []}, "intraday")

    def test_intraday_bounds(self):
        bad = {
            "range_minutes": [0, 14, 135, 150, 45.5, True, "30", None],
            "break_window_hours": [0.5, 7, True, "3"],
            "bb_period": [4, 101, 20.5, True],
            "bb_std": [0.5, 4.5, True],
            "rsi_period": [4, 51, 14.5, True],
            "rsi_low": [4, 51, True],
            "rsi_high": [49, 96, True],
            "engulfing_min_prior": [0, 7, 3.5, True],
            "min_stop_pct": [0, -0.1, 1.5, True],
            "max_stop_daily_atr": [0, -1, 5.5, True],
            "min_rr": [0.4, 5.5, True],
            "score_per_signal": [0, 6, 2.5, True],
            "score_trend": [-1, 4, 1.5, True],
            "window_bars": [0, 13, 4.5, True],
            "max_age_minutes": [14, 121, 30.5, True],
            "validity_r": [0, -0.25, 1.5, True],
            "max_per_run": [0, 11, 3.5, True],
            "max_per_day": [0, 51, 10.5, True],
            "max_per_exposure": [0, 6, 2.5, True],
            "cooldown_minutes": [-1, 721, 120.5, True],
        }
        for key, values in bad.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertRejects({"intraday": {key: value}}, f"intraday.{key}")

    def test_intraday_accepts_boundaries(self):
        good = {
            "range_minutes": [15, 120], "break_window_hours": [1, 6, 2.5],
            "bb_period": [5, 100], "bb_std": [1, 4], "rsi_period": [5, 50],
            "rsi_low": [5, 50], "rsi_high": [50, 95], "engulfing_min_prior": [1, 6],
            "min_stop_pct": [0.0001, 1], "max_stop_daily_atr": [0.1, 5],
            "min_rr": [0.5, 5], "score_per_signal": [1, 5], "score_trend": [0, 3],
            "window_bars": [1, 12], "max_age_minutes": [15, 120],
            "validity_r": [0.01, 1], "max_per_run": [1, 10], "max_per_day": [1, 50],
            "max_per_exposure": [1, 5], "cooldown_minutes": [0, 720],
        }
        for key, values in good.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    got = config.validate({"intraday": {key: value}})["intraday"]
                    self.assertEqual(got[key], value)

    def test_intraday_range_minutes_multiple_of_15(self):
        for value in (15, 30, 45, 60, 75, 90, 105, 120):
            self.assertEqual(
                config.validate({"intraday": {"range_minutes": value}})["intraday"]["range_minutes"],
                value)
        for value in (20, 25, 40, 100):
            self.assertRejects({"intraday": {"range_minutes": value}}, "intraday.range_minutes")

    def test_intraday_families_must_be_known_and_non_empty(self):
        ok = config.validate({"intraday": {"families": ["engulfing", "session_break"]}})
        self.assertEqual(ok["intraday"]["families"], ["engulfing", "session_break"])
        for bad in ([], ["nope"], ["engulfing", "nope"], ["engulfing", "engulfing"],
                    "engulfing", None, [1], [["engulfing"]], ("engulfing",)):
            with self.subTest(bad=bad):
                self.assertRejects({"intraday": {"families": bad}}, "intraday.families")

    def test_intraday_symbols_must_be_non_empty_strings(self):
        ok = config.validate({"intraday": {"symbols": ["EURUSD=X", "GC=F"]}})
        self.assertEqual(ok["intraday"]["symbols"], ["EURUSD=X", "GC=F"])
        for bad in ("EURUSD=X", None, [""], ["  "], [1], ["EURUSD=X", None], {"a": "b"}):
            with self.subTest(bad=bad):
                self.assertRejects({"intraday": {"symbols": bad}}, "intraday.symbols")

    def test_intraday_mt5_symbols_must_map_str_to_non_empty_str(self):
        ok = config.validate({"intraday": {"mt5_symbols": {"^FCHI": "FRA40", "any-key": "X"}}})
        self.assertEqual(ok["intraday"]["mt5_symbols"], {"^FCHI": "FRA40", "any-key": "X"})
        for bad in ({"A": ""}, {"A": "  "}, {"A": 1}, {"A": None}, ["A"], "A", None):
            with self.subTest(bad=bad):
                self.assertRejects({"intraday": {"mt5_symbols": bad}}, "intraday.mt5_symbols")

    def test_intraday_min_score_accepts_none_and_int_but_not_float(self):
        for value in (None, 0, 3, -2, 7):
            got = config.validate({"intraday": {"min_score": value}})["intraday"]["min_score"]
            self.assertEqual(got, value)
        for bad in (3.5, 3.0, True, False, "3", [3]):
            with self.subTest(bad=bad):
                self.assertRejects({"intraday": {"min_score": bad}}, "intraday.min_score")

    def test_intraday_enabled_must_be_bool(self):
        for bad in (1, 0, "true", None, "yes"):
            with self.subTest(bad=bad):
                self.assertRejects({"intraday": {"enabled": bad}}, "intraday.enabled")
        self.assertFalse(config.validate({"intraday": {"enabled": False}})["intraday"]["enabled"])


if __name__ == "__main__":
    unittest.main()
