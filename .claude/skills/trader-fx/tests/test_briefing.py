import _path  # noqa
import contextlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from datetime import date, datetime, timezone

import briefing
import config
import data
import fx
import signals

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
DAY = 86400
DISCLAIMER = ("Liste de graphiques qui ont matché une règle. Pas un conseil. "
              "Données Yahoo, retardées.")
SPEC_KEYS = {"as_of", "market_state", "counts", "data_age", "calendar", "strength",
             "swing", "daily_context", "day_plan", "trade_ideas", "warnings",
             "disclaimer"}
IDEA_KEYS = {"reference", "account", "ideas", "skipped", "total_risk_usd",
             "total_risk_pct", "max_total_pct", "over_cap", "max_ideas_within_cap",
             "ties_at_cutoff", "total_leverage"}
DEFAULT_CONFIG_PATH = fx.DEFAULT_CONFIG

SAT = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)   # Sat 10:00 New York
TUE = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)   # Tue 10:00 New York


def series(closes, end=date(2026, 11, 9), gmtoffset=0, age_s=None):
    """One bar per calendar day ending on `end`, 00:00 UTC, +-0.1% high/low."""
    n = len(closes)
    t_end = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp())
    bars = [(t_end - (n - 1 - i) * DAY, c, c * 1.001, c * 0.999, c)
            for i, c in enumerate(closes)]
    return data.Series(bars=bars, gmtoffset=gmtoffset, age_s=age_s)


def flat(n=55, base=1.0):
    return [base] * n


def breakout(n=55, base=1.0):
    c = flat(n, base)
    c[-1] = base * 1.2
    return c


def cal(status="ok", events=None, reason=None):
    return {"status": status, "events": events or [], "reason": reason}


def event(utc, currency="USD", impact="High", title="CPI m/m"):
    return {"utc": utc, "time_paris": "14:30", "time_ny": "08:30",
            "date_paris": utc[:10], "date_ny": utc[:10], "currency": currency,
            "title": title, "impact": impact, "forecast": "0.3%", "previous": "0.6%"}


UNIVERSE = [("EURUSD=X", "EUR/USD"), ("GBPUSD=X", "GBP/USD"),
            ("AUDUSD=X", "AUD/USD"), ("USDJPY=X", "USD/JPY")]


FRI = date(2026, 11, 13)


def all_breakouts(end=date(2026, 11, 9)):
    return {s: series(breakout(), end=end) for s, _ in UNIVERSE}


def short_only(n=55, base=1.0):
    """Overbought yesterday, a small drop today: 'overbought_reject' and no long rule."""
    c = flat(n - 2, base)
    return c + [base * 1.05, base * 1.04]


# whole words that must never appear (the control texts prove the regex is not vacuous)
FORBIDDEN_WORDS = r"(?i)\b(achat|acheter|vente|vendre|buy|sell|gagnant|profit)\b"

OTHERS = [("GC=F", "Or"), ("CL=F", "Petrole"), ("^FCHI", "CAC 40"), ("^GSPC", "S&P 500"),
          ("SI=F", "Argent"), ("^GDAXI", "DAX"), ("HG=F", "Cuivre"), ("^N225", "Nikkei")]


def many_ideas_config(**risk):
    cfg = config.defaults()
    cfg["ideas"]["max_shown"] = 10
    cfg["ideas"]["max_per_exposure"] = 5
    cfg["risk"].update(risk)
    return cfg


class TestReadList(unittest.TestCase):
    def test_read_list_skips_comments_and_names(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write("# comment\n\nEURUSD=X|EUR/USD\n  GC=F  \n^FCHI | CAC 40 \n#X|y\n")
            self.assertEqual(briefing.read_list(p),
                             [("EURUSD=X", "EUR/USD"), ("GC=F", "GC=F"), ("^FCHI", "CAC 40")])


    def test_read_list_ignores_a_utf8_bom(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.txt")
            with open(p, "w", encoding="utf-8-sig") as f:
                f.write("EURUSD=X|EUR/USD\nGC=F|Or\n")
            with open(p, "rb") as f:
                self.assertTrue(f.read().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(briefing.read_list(p), [("EURUSD=X", "EUR/USD"), ("GC=F", "Or")])

    def test_read_list_upper_cases_symbols_not_names(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write("eurusd=x|eur/usd\n gc=f \n^fchi|Cac 40\n")
            self.assertEqual(briefing.read_list(p),
                             [("EURUSD=X", "eur/usd"), ("GC=F", "GC=F"), ("^FCHI", "Cac 40")])


H = 3600
D9 = int(datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp())    # the close date
D10 = D9 + DAY


def hseries(bars):
    """1 h bars (ts, o, h, l, c)."""
    return data.Series(bars=list(bars), gmtoffset=0)


def bar(ts, high, low, close):
    return (ts, close, high, low, close)


class TestSinceClose(unittest.TestCase):
    LONG = {"side": "haussier", "stop": 1.17565, "target": 1.2487,
            "last_bar_date": "2026-11-09", "decimals": 5}
    SHORT = {"side": "baissier", "stop": 1.22, "target": 1.15, "last_bar_date": "2026-11-09",
             "decimals": 5}

    def test_last_is_rounded_to_the_idea_decimals(self):
        s = hseries([bar(D10 + H, 1.21, 1.18, 1.1890980017757904)])
        got = briefing.since_close(self.LONG, s)
        self.assertEqual(got["last"], 1.1891)
        self.assertEqual(repr(got["last"]), "1.1891")
        got = briefing.since_close(dict(self.LONG, decimals=3), s)
        self.assertEqual(got["last"], 1.189)
        got = briefing.since_close(dict(self.LONG, decimals=2), s)
        self.assertEqual(got["last"], 1.19)
        # the crossings are decided on the raw bars, not on the rounded close
        s = hseries([bar(D10 + H, 1.21, 1.17565, 1.1890980017757904)])
        self.assertTrue(briefing.since_close(self.LONG, s)["stop_crossed"])

    def test_last_stays_a_raw_float_when_the_idea_has_no_usable_decimals(self):
        s = hseries([bar(D10 + H, 1.21, 1.18, 1.1890980017757904)])
        for idea in (dict(self.LONG, decimals=None), {k: v for k, v in self.LONG.items()
                                                      if k != "decimals"},
                     dict(self.LONG, decimals="5"), dict(self.LONG, decimals=-1)):
            self.assertEqual(briefing.since_close(idea, s)["last"], 1.1890980017757904)

    def test_none_without_bars_after_the_close(self):
        self.assertIsNone(briefing.since_close(self.LONG, None))
        self.assertIsNone(briefing.since_close(self.LONG, hseries([])))
        # bars on the close date itself (and before) are ignored, even if they cross
        s = hseries([bar(D9 - DAY + 5 * H, 1.30, 1.10, 1.2),
                     bar(D9 + 23 * H, 1.30, 1.10, 1.2)])
        self.assertIsNone(briefing.since_close(self.LONG, s))
        self.assertIsNone(briefing.since_close(dict(self.LONG, last_bar_date=None), s))

    def test_weekend_run_has_no_bar_after_friday(self):
        fri = dict(self.LONG, last_bar_date="2026-11-13")
        t_fri = int(datetime(2026, 11, 13, 20, tzinfo=timezone.utc).timestamp())
        s = hseries([bar(t_fri - k * H, 1.21, 1.19, 1.2) for k in range(5)])
        self.assertIsNone(briefing.since_close(fri, s))

    def test_haussier_neither_crossed(self):
        s = hseries([bar(D9 + 20 * H, 1.30, 1.10, 1.2),           # ignored: close date
                     bar(D10 + 1 * H, 1.21, 1.18, 1.205),
                     bar(D10 + 3 * H, 1.215, 1.19, 1.212),
                     bar(D10 + 2 * H, 1.22, 1.185, 1.201)])
        self.assertEqual(briefing.since_close(self.LONG, s),
                         {"last": 1.212, "stop_crossed": False, "target_crossed": False})

    def test_haussier_stop_crossed_and_touch_counts(self):
        s = hseries([bar(D10 + H, 1.21, 1.17565, 1.19)])          # low == stop
        self.assertEqual(briefing.since_close(self.LONG, s),
                         {"last": 1.19, "stop_crossed": True, "target_crossed": False})

    def test_haussier_target_crossed(self):
        s = hseries([bar(D10 + H, 1.25, 1.20, 1.249), bar(D10 + 2 * H, 1.2487, 1.24, 1.245)])
        self.assertEqual(briefing.since_close(self.LONG, s),
                         {"last": 1.245, "stop_crossed": False, "target_crossed": True})

    def test_baissier_uses_the_mirror_tests(self):
        s = hseries([bar(D10 + H, 1.221, 1.18, 1.2)])
        self.assertEqual(briefing.since_close(self.SHORT, s),
                         {"last": 1.2, "stop_crossed": True, "target_crossed": False})
        s = hseries([bar(D10 + H, 1.21, 1.149, 1.16)])
        self.assertEqual(briefing.since_close(self.SHORT, s),
                         {"last": 1.16, "stop_crossed": False, "target_crossed": True})
        s = hseries([bar(D10 + H, 1.21, 1.16, 1.17)])
        self.assertEqual(briefing.since_close(self.SHORT, s),
                         {"last": 1.17, "stop_crossed": False, "target_crossed": False})

    def test_build_briefing_fills_since_close_from_the_hourly_bars(self):
        hourly = {"EURUSD=X": hseries([bar(D10 + H, 1.21, 1.17, 1.18)])}
        b = briefing.build_briefing(UNIVERSE[:1], all_breakouts(), [], hourly, cal(), TUE)
        idea = b["trade_ideas"]["ideas"][0]
        self.assertEqual(idea["last_bar_date"], "2026-11-09")
        self.assertEqual(idea["since_close"],
                         {"last": 1.18, "stop_crossed": True, "target_crossed": False})
        line = TestSummary.idea_block(briefing.render_summary(b))[1]
        self.assertTrue(line.endswith("risque 487.00 USD  stop déjà franchi"), line)
        hourly = {"EURUSD=X": hseries([bar(D10 + H, 1.30, 1.17, 1.18)])}
        b = briefing.build_briefing(UNIVERSE[:1], all_breakouts(), [], hourly, cal(), TUE)
        line = TestSummary.idea_block(briefing.render_summary(b))[1]
        self.assertTrue(line.endswith("  stop déjà franchi  cible déjà atteinte"), line)
        hourly = {"EURUSD=X": hseries([bar(D10 + H, 1.21, 1.19, 1.2)])}
        b = briefing.build_briefing(UNIVERSE[:1], all_breakouts(), [], hourly, cal(), TUE)
        line = TestSummary.idea_block(briefing.render_summary(b))[1]
        self.assertNotIn("franchi", line)
        self.assertNotIn("atteinte", line)


class TestAccountAndContracts(unittest.TestCase):
    def test_account_source_in_the_json(self):
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE)
        self.assertEqual(b["trade_ideas"]["account"]["source"], "default")
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE,
                                    config=config.defaults(), config_source="file")
        self.assertEqual(b["trade_ideas"]["account"]["source"], "file")
        self.assertEqual(json.loads(json.dumps(b))["trade_ideas"]["account"]["source"], "file")

    def test_summary_header_says_when_the_defaults_are_used(self):
        cfg = config.defaults()
        cfg["account"]["capital"] = 25000
        cfg["risk"]["per_trade_pct"] = 0.25
        cfg["leverage_max"] = 20
        b = briefing.build_briefing(UNIVERSE[:1], all_breakouts(), [], {}, cal(), TUE,
                                    config=cfg, config_source="file")
        head = TestSummary.idea_block(briefing.render_summary(b))[0]
        self.assertEqual(head, "Idées de trade (1), plan mécanique à valider. Compte 25000 USD, "
                               "risque 0.25 % par idée (62.50 USD), levier max 20:1")
        self.assertNotIn("défaut", head)
        b = briefing.build_briefing(UNIVERSE[:1], all_breakouts(), [], {}, cal(), TUE)
        head = TestSummary.idea_block(briefing.render_summary(b))[0]
        self.assertTrue(head.endswith("levier max 30:1 (valeurs par défaut)"), head)

    def test_contracts_keys_that_match_nothing_warn(self):
        cfg = config.defaults()
        cfg["contracts"] = {"GC=F": {"usd_per_point": 100, "step": 0.01, "min": 0.01},
                            "GCF": {"usd_per_point": 100, "step": 0.01, "min": 0.01},
                            "EURUSD=X": {"usd_per_point": 1, "step": 1, "min": 1}}
        universe = UNIVERSE + [("GC=F", "Or")]
        daily = all_breakouts()
        daily["GC=F"] = series(breakout())
        b = briefing.build_briefing(universe, daily, [], {}, cal(), TUE, config=cfg)
        warn = [w for w in b["warnings"] if w.startswith("contracts : ")]
        self.assertEqual(warn, [
            "contracts : GCF ne correspond à aucun instrument analysé ou est une paire "
            "forex : ignorée.",
            "contracts : EURUSD=X ne correspond à aucun instrument analysé ou est une paire "
            "forex : ignorée."])
        cfg["contracts"] = {"GC=F": {"usd_per_point": 100, "step": 0.01, "min": 0.01}}
        b = briefing.build_briefing(universe, daily, [], {}, cal(), TUE, config=cfg)
        self.assertFalse(any(w.startswith("contracts") for w in b["warnings"]))


class TestBuild(unittest.TestCase):
    def test_build_briefing_has_all_spec_keys(self):
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE)
        self.assertEqual(set(b), SPEC_KEYS)
        self.assertEqual(b["disclaimer"], DISCLAIMER)
        self.assertEqual(b["market_state"], "open")
        self.assertEqual(set(b["as_of"]), {"iso", "paris", "new_york"})
        self.assertEqual(b["as_of"]["new_york"], "2026-11-10 10:00")
        self.assertEqual(b["as_of"]["paris"], "2026-11-10 16:00")
        self.assertEqual(set(b["strength"]), {"windows"})
        self.assertEqual(set(b["strength"]["windows"]), {"1d", "5d", "20d"})
        self.assertEqual(set(b["swing"]), {"hits", "clusters"})
        self.assertEqual(set(b["day_plan"]), {"sessions", "levels", "events_24h"})
        self.assertEqual(set(b["calendar"]), {"status", "events", "reason"})
        json.dumps(b)  # serialisable

    def test_daily_context_covers_every_analysed_symbol(self):
        daily = {"EURUSD=X": series(breakout()), "GBPUSD=X": series(neutral()),
                 "AUDUSD=X": series(breakout()), "USDJPY=X": series(neutral())}
        b = briefing.build_briefing(UNIVERSE, daily, [], {}, cal(), TUE)
        analyses = briefing.analyze_universe(UNIVERSE, daily, TUE)
        self.assertEqual(set(b["daily_context"]), {a["symbol"] for a in analyses})
        self.assertEqual(len(b["daily_context"]), 4)
        # symbols without a rule are covered too
        self.assertIn("GBPUSD=X", b["daily_context"])
        self.assertNotIn("GBPUSD=X", [h["symbol"] for h in b["swing"]["hits"]])
        ref = signals.analyze("EURUSD=X", "EUR/USD", daily["EURUSD=X"], TUE)
        ctx = b["daily_context"]["EURUSD=X"]
        self.assertEqual(set(ctx), {"name", "last", "atr_pct", "trend"})
        self.assertEqual(ctx["name"], "EUR/USD")
        for k in ("last", "atr_pct", "trend"):
            self.assertEqual(ctx[k], ref[k])
        json.dumps(b["daily_context"])

    def test_calendar_carries_its_reason(self):
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {},
                                    cal("unavailable", reason="this week: boom"), TUE)
        self.assertEqual(b["calendar"]["reason"], "this week: boom")
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE)
        self.assertIsNone(b["calendar"]["reason"])
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {},
                                    {"status": "ok", "events": []}, TUE)
        self.assertIsNone(b["calendar"]["reason"])

    def test_hits_are_only_symbols_with_setups(self):
        daily = {"EURUSD=X": series(breakout()), "GBPUSD=X": series(neutral()),
                 "AUDUSD=X": series(breakout()), "USDJPY=X": series(neutral())}
        b = briefing.build_briefing(UNIVERSE, daily, [], {}, cal(), TUE)
        self.assertEqual([h["symbol"] for h in b["swing"]["hits"]],
                         ["EURUSD=X", "AUDUSD=X"])
        h = b["swing"]["hits"][0]
        for k in ("symbol", "name", "last", "rsi", "atr_pct", "trend", "setups"):
            self.assertIn(k, h)
        self.assertIn("breakout_20d", h["setups"])
        self.assertEqual(b["counts"]["scanned"], 4)

    def test_counts_say_partial(self):
        daily = {s: series(breakout()) for s in ("EURUSD=X", "GBPUSD=X", "AUDUSD=X")}
        failed = [{"symbol": "USDJPY=X", "reason": "no data"}]
        b = briefing.build_briefing(UNIVERSE, daily, failed, {}, cal(), TUE)
        self.assertEqual(b["counts"], {"requested": 4, "fetched": 3, "scanned": 3,
                                       "failed": failed, "last_bar_date": "2026-11-09"})
        s = briefing.render_summary(b)
        self.assertIn("Reçus : 3 sur 4 (1 en échec)", s)
        self.assertIn("USDJPY=X", s)
        self.assertTrue(any("USDJPY=X" in w for w in b["warnings"]))

    def test_arithmetic_error_excludes_only_that_symbol(self):
        daily = all_breakouts()
        daily["GBPUSD=X"] = series(flat(54) + [0.0])   # last close 0: division by zero
        b = briefing.build_briefing(UNIVERSE, daily, [], {}, cal(), TUE)
        self.assertEqual(b["counts"]["scanned"], 3)
        self.assertEqual(b["counts"]["fetched"], 4)
        self.assertNotIn("GBPUSD=X", [h["symbol"] for h in b["swing"]["hits"]])
        self.assertIn("GBPUSD=X : analyse impossible (ZeroDivisionError)", b["warnings"])
        # not mislabelled as "fewer than 30 sessions"
        self.assertFalse(any("30 séances" in w and "GBPUSD=X" in w for w in b["warnings"]))
        self.assertIn("Analysés : 3 (moins de 30 séances : 1)", briefing.render_summary(b))

    def test_analyze_universe_reports_errors_when_asked(self):
        daily = {"EURUSD=X": series(breakout()), "GBPUSD=X": series(flat(54) + [0.0])}
        errors = []
        out = briefing.analyze_universe(UNIVERSE[:2], daily, TUE, errors)
        self.assertEqual([a["symbol"] for a in out], ["EURUSD=X"])
        self.assertEqual(errors, [("GBPUSD=X", "ZeroDivisionError")])
        # without the errors list it just skips the symbol
        self.assertEqual(len(briefing.analyze_universe(UNIVERSE[:2], daily, TUE)), 1)

    def test_under_30_sessions_counted_not_scanned(self):
        daily = all_breakouts()
        daily["USDJPY=X"] = series(flat(20))
        b = briefing.build_briefing(UNIVERSE, daily, [], {}, cal(), TUE)
        self.assertEqual(b["counts"]["fetched"], 4)
        self.assertEqual(b["counts"]["scanned"], 3)
        self.assertTrue(any("USDJPY=X" in w and "30" in w for w in b["warnings"]))
        self.assertNotIn("USDJPY=X", [h["symbol"] for h in b["swing"]["hits"]])

    def test_saturday_run_is_closed_weekend_and_warns(self):
        b = briefing.build_briefing(UNIVERSE, all_breakouts(FRI), [], {}, cal(), SAT)
        self.assertEqual(b["market_state"], "closed_weekend")
        self.assertTrue(any("week-end" in w for w in b["warnings"]))
        self.assertFalse(any(s["active"] for s in b["day_plan"]["sessions"]))
        # last closes are Friday's
        self.assertEqual({h["last_bar_date"] for h in b["swing"]["hits"]}, {"2026-11-13"})
        self.assertIn("fermé", briefing.render_summary(b))

    def test_open_day_has_active_session_and_no_weekend_warning(self):
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE)
        self.assertTrue(any(s["active"] for s in b["day_plan"]["sessions"]))
        self.assertFalse(any("week-end" in w for w in b["warnings"]))

    def test_calendar_unavailable_adds_warning_and_runs(self):
        b = briefing.build_briefing(
            UNIVERSE, all_breakouts(), [], {},
            cal("unavailable", reason="this week: HTTP 500"), TUE)
        self.assertEqual(b["calendar"]["status"], "unavailable")
        self.assertEqual(b["calendar"]["events"], [])
        self.assertEqual(b["day_plan"]["events_24h"], [])
        self.assertTrue(any("HTTP 500" in w for w in b["warnings"]))
        s = briefing.render_summary(b)
        self.assertIn("indisponible", s)

    def test_calendar_partial_warns_too(self):
        b = briefing.build_briefing(
            UNIVERSE, all_breakouts(), [], {},
            cal("partial", reason="next week: pas encore publié (HTTP 404)"), TUE)
        self.assertTrue(any("pas encore publié" in w for w in b["warnings"]))

    def test_calendar_events_filtered_and_24h_window(self):
        evs = [event("2026-11-10T18:00:00+00:00", "USD"),
               event("2026-11-10T18:00:00+00:00", "CNY"),
               event("2026-11-10T18:00:00+00:00", "EUR", impact="Low"),
               event("2026-11-12T13:30:00+00:00", "EUR", title="later"),
               event("2026-11-10T10:00:00+00:00", "GBP", title="past")]
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(events=evs), TUE)
        ccys = [(e["currency"], e["title"]) for e in b["calendar"]["events"]]
        self.assertNotIn(("CNY", "CPI m/m"), ccys)
        self.assertEqual(len(b["calendar"]["events"]), 3)  # USD, later EUR, past GBP
        self.assertEqual([e["currency"] for e in b["day_plan"]["events_24h"]], ["USD"])
        self.assertIn("utc", b["calendar"]["events"][0])
        self.assertIn("CPI m/m", briefing.render_summary(b))

    def test_stale_cache_sets_data_age_and_warning(self):
        daily = all_breakouts()
        daily["EURUSD=X"] = series(breakout(), age_s=7200.0)
        daily["GBPUSD=X"] = series(breakout(), age_s=3600.0)
        b = briefing.build_briefing(UNIVERSE, daily, [], {}, cal(), TUE)
        self.assertEqual(b["data_age"], 7200)
        self.assertTrue(any("périmé" in w for w in b["warnings"]))
        fresh = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE)
        self.assertIsNone(fresh["data_age"])

    def test_extra_warnings_are_kept(self):
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE,
                                    extra_warnings=["horaire manquant"])
        self.assertIn("horaire manquant", b["warnings"])

    def test_alert_symbols_hits_plus_majors_without_duplicates(self):
        out = briefing.alert_symbols([{"symbol": "EURUSD=X"}, {"symbol": "GC=F"}])
        self.assertEqual(out[0], "EURUSD=X")
        self.assertEqual(out[1], "GC=F")
        self.assertEqual(len(out), len(set(out)))
        for m in ("EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X",
                  "USDCAD=X", "NZDUSD=X"):
            self.assertIn(m, out)
        self.assertEqual(len(out), 8)

    def test_day_plan_levels_cover_hits_and_majors_with_asia_range(self):
        daily = {"EURUSD=X": series(breakout()), "GC=F": series(breakout(), gmtoffset=-18000),
                 "NZDUSD=X": series(flat())}
        universe = [("EURUSD=X", "EUR/USD"), ("GC=F", "Or"), ("NZDUSD=X", "NZD/USD")]
        t0 = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp())
        hourly = {"EURUSD=X": data.Series(
            bars=[(t0 + h * 3600, 1.0, 1.01 + h * 0.001, 0.99, 1.0) for h in range(10)],
            gmtoffset=0)}
        b = briefing.build_briefing(universe, daily, [], hourly, cal(), TUE)
        lv = {r["symbol"]: r for r in b["day_plan"]["levels"]}
        self.assertEqual(set(lv), {"EURUSD=X", "GC=F", "NZDUSD=X"})  # majors w/o data skipped
        for k in ("prev_high", "prev_low", "week_high", "week_low", "asia_high", "asia_low"):
            self.assertIn(k, lv["EURUSD=X"])
        self.assertIsNotNone(lv["EURUSD=X"]["asia_high"])
        self.assertIsNone(lv["GC=F"]["asia_high"])
        self.assertIsNone(lv["NZDUSD=X"]["asia_low"])
        self.assertIs(lv["EURUSD=X"]["asia_complete"], True)   # TUE is 15:00 UTC
        self.assertIsNone(lv["GC=F"]["asia_complete"])
        self.assertIsNone(lv["NZDUSD=X"]["asia_complete"])

    def test_day_plan_asia_complete_false_while_the_range_forms(self):
        daily = {"EURUSD=X": series(breakout())}
        t0 = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp())
        hourly = {"EURUSD=X": data.Series(
            bars=[(t0 + h * 3600, 1.0, 1.01, 0.99, 1.0) for h in range(10)], gmtoffset=0)}
        early = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)
        b = briefing.build_briefing([("EURUSD=X", "EUR/USD")], daily, [], hourly, cal(), early)
        row = b["day_plan"]["levels"][0]
        self.assertIsNotNone(row["asia_high"])
        self.assertIs(row["asia_complete"], False)

    def test_strength_uses_forex_pairs_only(self):
        daily = all_breakouts()
        daily["GC=F"] = series(breakout())
        b = briefing.build_briefing(UNIVERSE + [("GC=F", "Or")], daily, [], {}, cal(), TUE)
        ccys = {r["ccy"] for r in b["strength"]["windows"]["5d"]}
        self.assertEqual(ccys, {"EUR", "USD", "GBP", "AUD", "JPY"})

    def test_strength_ignores_the_in_progress_bar(self):
        # the last (today's) bar is a huge move that must not count
        closes = flat(55)
        s = series(closes + [5.0], end=date(2026, 11, 10))  # dated today in UTC
        b = briefing.build_briefing([("EURUSD=X", "EUR/USD")], {"EURUSD=X": s}, [], {},
                                    cal(), TUE)
        score = {r["ccy"]: r["score"] for r in b["strength"]["windows"]["1d"]}
        self.assertLess(abs(score["EUR"]), 1.0)


def neutral(n=55):
    """A slow oscillation around 1.0: no rule of either side fires (RSI 39, no state)."""
    return [1.0 + 0.01 * math.sin(i / 3.0) for i in range(n)]


class TestTradeIdeas(unittest.TestCase):
    def test_trade_ideas_key_and_shape(self):
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE)
        keys = list(b)
        self.assertEqual(keys.index("trade_ideas"), keys.index("day_plan") + 1)
        self.assertEqual(keys.index("warnings"), keys.index("trade_ideas") + 1)
        ti = b["trade_ideas"]
        self.assertEqual(set(ti), IDEA_KEYS)
        self.assertEqual(ti["reference"], "last_close")
        self.assertEqual(ti["account"], {"currency": "USD", "capital": 100000,
                                         "risk_per_trade_usd": 500.0, "leverage_max": 30,
                                         "source": "default"})
        self.assertEqual(ti["max_total_pct"], 2.0)
        self.assertTrue(ti["ideas"])
        idea = ti["ideas"][0]
        self.assertEqual(set(idea), {"rank", "symbol", "name", "side", "score", "setups",
                                     "trend", "reference_price", "stop", "target", "rr",
                                     "atr", "decimals", "size", "why", "last_bar_date",
                                     "since_close"})
        self.assertEqual(idea["last_bar_date"], "2026-11-09")
        self.assertIsNone(idea["since_close"])          # no 1 h bars given
        self.assertEqual(idea["rank"], 1)
        self.assertEqual(idea["side"], "haussier")
        self.assertEqual(set(idea["size"]), {"status", "lots", "units", "size", "risk_usd",
                                             "leverage", "pip_value_usd_per_lot",
                                             "limited_by", "note"})
        self.assertIsInstance(ti["skipped"], list)
        json.dumps(b)

    def test_has_setup(self):
        self.assertFalse(briefing.has_setup({"setups": [], "setups_short": []}))
        self.assertTrue(briefing.has_setup({"setups": ["breakout_20d"], "setups_short": []}))
        self.assertTrue(briefing.has_setup({"setups": [], "setups_short": ["breakdown_20d"]}))
        self.assertTrue(briefing.has_setup({"setups": ["a"], "setups_short": ["b"]}))
        self.assertFalse(briefing.has_setup({"setups": []}))          # key may be missing
        self.assertTrue(briefing.has_setup({"setups": [], "setups_short": ["overbought"]}))
        self.assertIs(briefing.has_setup({"setups": [], "setups_short": []}), False)

    def test_hits_include_short_only_setups(self):
        daily = {"EURUSD=X": series(short_only()), "GBPUSD=X": series(neutral()),
                 "AUDUSD=X": series(breakout()), "USDJPY=X": series(neutral())}
        b = briefing.build_briefing(UNIVERSE, daily, [], {}, cal(), TUE)
        hits = {h["symbol"]: h for h in b["swing"]["hits"]}
        self.assertEqual(list(hits), ["EURUSD=X", "AUDUSD=X"])
        self.assertEqual(hits["EURUSD=X"]["setups"], [])
        self.assertIn("overbought_reject", hits["EURUSD=X"]["setups_short"])
        self.assertIsInstance(hits["AUDUSD=X"]["setups_short"], list)
        # and it becomes a bearish idea
        sides = {i["symbol"]: i["side"] for i in b["trade_ideas"]["ideas"]}
        self.assertEqual(sides["EURUSD=X"], "baissier")

    def test_flat_series_is_now_a_hit_because_of_the_overbought_state(self):
        """Documents the inherited rsi() behaviour: RSI 100 on a flat series."""
        b = briefing.build_briefing(UNIVERSE[:1], {"EURUSD=X": series(flat())}, [], {},
                                    cal(), TUE)
        self.assertEqual([h["symbol"] for h in b["swing"]["hits"]], ["EURUSD=X"])
        self.assertEqual(b["swing"]["hits"][0]["setups"], [])
        self.assertEqual(b["swing"]["hits"][0]["setups_short"], ["overbought"])
        self.assertEqual(b["trade_ideas"]["ideas"], [])     # a state is not a trigger

    def test_saturday_run_still_gives_ideas_with_the_weekend_warning(self):
        b = briefing.build_briefing(UNIVERSE, all_breakouts(FRI), [], {}, cal(), SAT)
        self.assertEqual(b["market_state"], "closed_weekend")
        self.assertEqual(b["trade_ideas"]["reference"], "last_close")
        self.assertTrue(b["trade_ideas"]["ideas"])
        self.assertTrue(any("week-end" in w for w in b["warnings"]))

    def test_none_config_means_the_defaults(self):
        a = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE)
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE,
                                    config=config.defaults())
        self.assertEqual(a["trade_ideas"], b["trade_ideas"])

    def test_custom_config_changes_sizes(self):
        base = briefing.build_briefing(UNIVERSE[:1], all_breakouts(), [], {}, cal(), TUE)
        cfg = config.defaults()
        cfg["risk"]["per_trade_pct"] = 1.0
        big = briefing.build_briefing(UNIVERSE[:1], all_breakouts(), [], {}, cal(), TUE,
                                      config=cfg)
        i0, i1 = base["trade_ideas"]["ideas"][0], big["trade_ideas"]["ideas"][0]
        self.assertEqual((i0["size"]["status"], i1["size"]["status"]), ("ok", "ok"))
        self.assertEqual(big["trade_ideas"]["account"]["risk_per_trade_usd"], 1000.0)
        self.assertLessEqual(i1["size"]["risk_usd"], 1000.0)
        self.assertGreater(i1["size"]["risk_usd"], 1.8 * i0["size"]["risk_usd"])
        self.assertGreater(i1["size"]["lots"], 1.8 * i0["size"]["lots"])


class TestSummary(unittest.TestCase):
    FORBIDDEN = FORBIDDEN_WORDS

    def test_summary_under_41_lines_and_no_forbidden_words(self):
        # a big universe with many hits and many warnings
        syms = ["%s%s=X" % (a, b) for a in ("EUR", "GBP", "AUD", "NZD", "USD", "CAD")
                for b in ("JPY", "CHF", "SEK", "NOK", "PLN", "MXN")]
        universe = [(s, s[:3] + "/" + s[3:6]) for s in syms]
        universe += [("GC=F", "Or"), ("CL=F", "Petrole"), ("^FCHI", "CAC 40"),
                     ("^GSPC", "S&P 500")]
        universe += OTHERS[4:]
        daily = {s: series(breakout()) for s, _ in universe}
        evs = [event("2026-11-10T%02d:00:00+00:00" % (16 + i % 8), "USD",
                     title="Event %d" % i) for i in range(20)]
        b = briefing.build_briefing(universe, daily,
                                    [{"symbol": "X%d=X" % i, "reason": "r"} for i in range(30)],
                                    {}, cal("partial", evs, "next week: HTTP 404"), TUE,
                                    extra_warnings=["w%d" % i for i in range(12)],
                                    config=many_ideas_config(max_total_pct=10))
        self.assertEqual(len(b["trade_ideas"]["ideas"]), 10)
        s = briefing.render_summary(b)
        self.assertEqual(len(self.idea_block(s)), 8)
        self.assertLessEqual(len(s.splitlines()), 40)
        self.assertEqual(s.splitlines()[-1], DISCLAIMER)
        self.assertNotRegex(s, self.FORBIDDEN)
        self.assertIn("ont matché une règle", s)
        self.assertIn("Dernière barre : 2026-11-09", s)
        self.assertIn(DISCLAIMER, s)

    def test_summary_worst_case_with_every_new_suffix_still_fits(self):
        syms = ["%s%s=X" % (a, b) for a in ("EUR", "GBP", "AUD", "NZD", "USD", "CAD")
                for b in ("JPY", "CHF", "SEK", "NOK", "PLN", "MXN")]
        universe = [(s, s[:3] + "/" + s[3:6]) for s in syms] + OTHERS
        daily = {s: series(breakout()) for s, _ in universe}
        cfg = many_ideas_config(max_total_pct=0.5)
        cfg["account"]["capital"] = 123456789.5
        cfg["contracts"] = {"TYPO%d" % i: {"usd_per_point": 1, "step": 1, "min": 1}
                            for i in range(6)}
        b = briefing.build_briefing(universe, daily,
                                    [{"symbol": "X%d=X" % i, "reason": "r"} for i in range(30)],
                                    {}, cal("partial", [event("2026-11-10T%02d:00:00+00:00"
                                                              % (16 + i % 8), "USD",
                                                              title="Event %d" % i)
                                                        for i in range(20)], "HTTP 404"),
                                    TUE, extra_warnings=["w%d" % i for i in range(12)],
                                    config=cfg)
        ti = b["trade_ideas"]
        self.assertTrue(ti["over_cap"])
        for i in ti["ideas"]:
            i["since_close"] = {"last": 1.0, "stop_crossed": True, "target_crossed": True}
        ti["ideas"][0]["size"] = {"status": "to_confirm", "lots": None, "units": None,
                                  "size": None, "risk_usd": None, "leverage": None,
                                  "pip_value_usd_per_lot": None, "limited_by": None,
                                  "note": "x"}
        ti["ideas"][1]["size"] = {"status": "ok", "lots": 9999.99, "units": 999999000,
                                  "size": None, "risk_usd": 617283.94, "leverage": 29.99,
                                  "pip_value_usd_per_lot": 10.0, "limited_by": "levier",
                                  "note": None}
        ti["total_leverage"] = 29.99
        s = briefing.render_summary(b)
        lines = s.splitlines()
        self.assertLessEqual(len(lines), 40)
        self.assertEqual(max(len(l) for l in lines) <= 150, True, max(lines, key=len))
        block = self.idea_block(s)
        self.assertEqual(len(block), 8)
        self.assertIn("risque prévu", block[1])
        self.assertTrue(block[-1].startswith("  Risque cumulé : "))
        self.assertIn(": dépassé, au plus ", block[-1])
        self.assertIn("levier cumulé ×", block[-1])
        self.assertTrue(block[0].startswith("Idées de trade (10), plan mécanique à valider. "
                                            "Compte 123456789.50 USD"), block[0])
        self.assertNotRegex(s, FORBIDDEN_WORDS)
        self.assertRegex(s + " vendre", FORBIDDEN_WORDS)       # the scan can fail
        self.assertNotRegex(json.dumps(b, ensure_ascii=False), FORBIDDEN_WORDS)

    def test_summary_always_prints_the_last_bar_date(self):
        daily = {"EURUSD=X": series(breakout(), end=date(2026, 11, 6)),
                 "GBPUSD=X": series(flat(), end=date(2026, 11, 9)),
                 "AUDUSD=X": series(flat(), end=date(2026, 11, 5)),
                 "USDJPY=X": series(flat(), end=date(2026, 11, 9))}
        b = briefing.build_briefing(UNIVERSE, daily, [], {}, cal(), TUE)   # a Tuesday
        self.assertEqual(b["market_state"], "open")
        lines = briefing.render_summary(b).splitlines()
        self.assertEqual([l for l in lines if l.startswith("Dernière barre")],
                         ["Dernière barre : 2026-11-09"])

    def test_summary_last_bar_line_when_nothing_is_analysed(self):
        b = briefing.build_briefing(UNIVERSE[:1], {"EURUSD=X": series(flat(20))}, [], {},
                                    cal(), TUE)
        self.assertIn("Dernière barre : n/a", briefing.render_summary(b))

    def test_summary_small_case_content(self):
        daily = {"EURUSD=X": series(breakout()), "GBPUSD=X": series(neutral()),
                 "AUDUSD=X": series(neutral()), "USDJPY=X": series(neutral())}
        b = briefing.build_briefing(UNIVERSE, daily, [], {}, cal(), TUE)
        s = briefing.render_summary(b)
        self.assertNotRegex(s, self.FORBIDDEN)
        self.assertIn("Reçus : 4 sur 4 (0 en échec)", s)
        self.assertIn("1 sur 4 analysés ont matché une règle", s)
        self.assertIn("EURUSD=X", s)
        self.assertNotIn("None", s)
        self.assertIn(DISCLAIMER, s)

    def test_summary_shows_na_for_missing_trend(self):
        daily = {"EURUSD=X": series(breakout(40))}  # 40 sessions: trend is None
        b = briefing.build_briefing([("EURUSD=X", "EUR/USD")], daily, [], {}, cal(), TUE)
        self.assertIsNone(b["swing"]["hits"][0]["trend"])
        s = briefing.render_summary(b)
        self.assertIn("n/a", s)
        self.assertNotIn("None", s)

    def test_summary_mentions_usd_cluster_when_dominant(self):
        b = briefing.build_briefing(UNIVERSE, all_breakouts(), [], {}, cal(), TUE)
        self.assertEqual(b["swing"]["clusters"][0]["ccy"], "USD")
        s = briefing.render_summary(b)
        self.assertRegex(s, r"4 des 4 signaux .*USD")

    def test_summary_groups_hits_by_family(self):
        universe = UNIVERSE[:3] + [("GC=F", "Or"), ("^FCHI", "CAC 40")]
        daily = {s: series(breakout()) for s, _ in universe}
        s = briefing.render_summary(
            briefing.build_briefing(universe, daily, [], {}, cal(), TUE))
        for label in ("Forex", "Matières premières", "Indices"):
            self.assertIn(label, s)

    def test_summary_real_fixtures(self):
        def load(name):
            with open(os.path.join(FIX, name), encoding="utf-8") as f:
                return data.parse_chart(f.read(), name)
        daily = {"EURUSD=X": load("eurusd_1d.json"), "GC=F": load("gc_1d.json"),
                 "^FCHI": load("fchi_1d.json")}
        universe = [("EURUSD=X", "EUR/USD"), ("GC=F", "Or"), ("^FCHI", "CAC 40")]
        b = briefing.build_briefing(universe, daily, [], {"EURUSD=X": load("eurusd_1h.json")},
                                    cal(), SAT)
        self.assertEqual(b["market_state"], "closed_weekend")
        self.assertEqual(b["counts"]["scanned"], 3)
        for r in b["day_plan"]["levels"]:
            self.assertIsNone(r["asia_high"])  # no Asia bar on Saturday
        self.assertLessEqual(len(briefing.render_summary(b).splitlines()), 40)

    # ---- idea block

    @staticmethod
    def idea_block(summary):
        """Lines from the idea header to the cumulated-risk line (inclusive)."""
        lines = summary.splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith("Idées de trade"))
        if lines[start] == "Idées de trade : aucune":
            return [lines[start]]
        end = next(i for i, l in enumerate(lines) if l.startswith("  Risque cumulé"))
        return lines[start:end + 1]

    def three_idea_briefing(self, **risk):
        cfg = config.defaults()
        cfg["risk"].update(risk)
        cfg["contracts"] = {"GC=F": {"usd_per_point": 100, "step": 0.01, "min": 0.01}}
        universe = [("EURUSD=X", "EUR/USD"), ("GC=F", "Or"), ("^FCHI", "CAC 40")]
        daily = {s: series(breakout()) for s, _ in universe}
        return briefing.build_briefing(universe, daily, [], {}, cal(), TUE, config=cfg)

    def test_summary_idea_block(self):
        b = self.three_idea_briefing()
        ti = b["trade_ideas"]
        self.assertEqual(len(ti["ideas"]), 3)
        s = briefing.render_summary(b)
        block = self.idea_block(s)
        self.assertEqual(block[0], "Idées de trade (3), plan mécanique à valider. Compte "
                                   "100000 USD, risque 0.5 % par idée (500.00 USD), "
                                   "levier max 30:1 (valeurs par défaut)")
        self.assertEqual(len(block), 5)
        by_symbol = {i["symbol"]: i for i in ti["ideas"]}
        for line, idea in zip(block[1:4], ti["ideas"]):
            self.assertTrue(line.startswith("  %d. %s haussier  entrée " % (idea["rank"],
                                                                         idea["symbol"])), line)
            self.assertIn("  stop ", line)
            self.assertIn("  cible ", line)
            self.assertLessEqual(len(line), 150)
        eur = next(l for l in block if " EURUSD=X " in l)
        gold = next(l for l in block if " GC=F " in l)
        fchi = next(l for l in block if " ^FCHI " in l)
        e = by_symbol["EURUSD=X"]
        self.assertEqual(e["decimals"], 5)
        self.assertEqual(
            eur.split(". ", 1)[1],
            "EURUSD=X haussier  entrée %.5f  stop %.5f  cible %.5f  %.2f lot  risque %.2f USD" % (
                e["reference_price"], e["stop"], e["target"], e["size"]["lots"],
                e["size"]["risk_usd"]))
        g = by_symbol["GC=F"]
        self.assertIn("  entrée %.*f  stop %.*f  cible %.*f  " % (
            g["decimals"], g["reference_price"], g["decimals"], g["stop"],
            g["decimals"], g["target"]), gold)
        self.assertIn("  taille %s  risque %.2f USD" % (g["size"]["size"], g["size"]["risk_usd"]),
                      gold)
        self.assertTrue(fchi.endswith("  taille à confirmer  risque prévu 500.00 USD"), fchi)
        self.assertEqual(fchi.count("risque"), 1)
        lev = sum(i["size"]["leverage"] for i in ti["ideas"] if i["size"]["status"] == "ok")
        self.assertEqual(ti["total_leverage"], round(lev, 2))
        self.assertEqual(
            block[-1],
            "  Risque cumulé : %.2f USD (%.2f %%) sur 2.0 %% autorisés · levier cumulé ×%.2f" % (
                ti["total_risk_usd"], ti["total_risk_pct"], ti["total_leverage"]))
        self.assertFalse(ti["over_cap"])
        self.assertNotIn("dépassé", block[-1])

    def test_summary_idea_block_pinned_forex_line(self):
        """Literal values worked by hand: last 1.2, ATR 1.3523810 %, stop 1.5 ATR below."""
        b = briefing.build_briefing(UNIVERSE[:1], all_breakouts(), [], {}, cal(), TUE)
        block = self.idea_block(briefing.render_summary(b))
        idea = b["trade_ideas"]["ideas"][0]
        # distance 1.2 - 1.17565 = 0.02435 ; target 1.2 + 2 * 0.02435 = 1.24870
        self.assertEqual(idea["reference_price"], 1.2)
        self.assertEqual(idea["stop"], 1.17565)
        self.assertEqual(idea["target"], 1.2487)
        self.assertTrue(block[1].startswith(
            "  1. EURUSD=X haussier  entrée 1.20000  stop 1.17565  cible 1.24870  "), block[1])
        self.assertEqual(block[1].split("cible 1.24870  ")[1], "0.20 lot  risque 487.00 USD")

    def test_summary_over_cap_suffix(self):
        b = self.three_idea_briefing(max_total_pct=1.0)
        ti = b["trade_ideas"]
        self.assertTrue(ti["over_cap"])
        self.assertEqual(ti["max_ideas_within_cap"], 2)
        last = self.idea_block(briefing.render_summary(b))[-1]
        self.assertTrue(last.startswith("  Risque cumulé : "))
        self.assertIn(" sur 1.0 % autorisés : dépassé, au plus 2 idées ouvertes en même temps"
                      " · levier cumulé ×", last)
        self.assertTrue(last.endswith(" · levier cumulé ×%.2f" % ti["total_leverage"]), last)
        b = self.three_idea_briefing(max_total_pct=0.5)
        self.assertEqual(b["trade_ideas"]["max_ideas_within_cap"], 1)
        last = self.idea_block(briefing.render_summary(b))[-1]
        self.assertIn(" sur 0.5 % autorisés : dépassé, au plus 1 idée ouverte en même temps"
                      " · levier cumulé ×", last)

    def test_summary_zero_ideas_is_one_line(self):
        daily = {s: series(neutral()) for s, _ in UNIVERSE}
        b = briefing.build_briefing(UNIVERSE, daily, [], {}, cal(), TUE)
        self.assertEqual(b["trade_ideas"]["ideas"], [])
        s = briefing.render_summary(b)
        self.assertEqual([l for l in s.splitlines() if "Idées de trade" in l],
                         ["Idées de trade : aucune"])
        self.assertNotIn("Risque cumulé", s)

    def test_summary_too_wide_and_precision_with_a_crafted_idea(self):
        b = self.three_idea_briefing()
        ideas = b["trade_ideas"]["ideas"]
        wide = next(i for i in ideas if i["symbol"] == "EURUSD=X")
        wide["size"] = {"status": "too_wide", "lots": None, "units": None, "size": None,
                        "risk_usd": None, "leverage": None, "pip_value_usd_per_lot": None,
                        "limited_by": None, "note": "stop trop large pour le risque fixé"}
        wide["reference_price"], wide["stop"], wide["target"] = 1e-05, 5e-06, 2.5e-05
        wide["decimals"] = 6
        line = next(l for l in self.idea_block(briefing.render_summary(b))
                    if " EURUSD=X " in l)
        self.assertTrue(line.endswith("  stop trop large"), line)
        self.assertNotIn("risque", line)
        self.assertNotIn("e-", line)
        self.assertIn("entrée 0.000010  stop 0.000005  cible 0.000025", line)

    def test_summary_more_than_six_ideas_adds_an_others_line(self):
        universe = UNIVERSE + OTHERS
        daily = {s: series(breakout()) for s, _ in universe}
        b = briefing.build_briefing(universe, daily, [], {}, cal(), TUE,
                                    config=many_ideas_config(max_total_pct=10))
        n = len(b["trade_ideas"]["ideas"])
        self.assertGreater(n, 6)
        block = self.idea_block(briefing.render_summary(b))
        self.assertEqual(len(block), 8)
        self.assertTrue(block[0].startswith(
            "Idées de trade (%d), plan mécanique à valider. Compte 100000 USD, " % n), block[0])
        self.assertEqual(block[-2], "  ... et %d autres (voir briefing.json)" % (n - 5))
        self.assertTrue(block[-1].startswith("  Risque cumulé : "))

    def test_summary_six_ideas_fit_without_others_line(self):
        universe = UNIVERSE + OTHERS
        daily = {s: series(breakout()) for s, _ in universe}
        cfg = many_ideas_config(max_total_pct=10)
        cfg["ideas"]["max_shown"] = 6
        b = briefing.build_briefing(universe, daily, [], {}, cal(), TUE, config=cfg)
        self.assertEqual(len(b["trade_ideas"]["ideas"]), 6)
        block = self.idea_block(briefing.render_summary(b))
        self.assertEqual(len(block), 8)
        self.assertFalse(any("autres" in l for l in block))

    def test_summary_prints_the_rules_of_a_short_only_hit(self):
        b = briefing.build_briefing(UNIVERSE[:1], {"EURUSD=X": series(short_only())}, [], {},
                                    cal(), TUE)
        s = briefing.render_summary(b)
        self.assertEqual(b["swing"]["hits"][0]["setups"], [])
        self.assertIn("overbought_reject", [l for l in s.splitlines() if "RSI" in l][0])

    def test_summary_and_json_have_no_forbidden_words(self):
        # negative control: the regex must catch a whole word and spare a substring
        self.assertRegex("un achat", FORBIDDEN_WORDS)
        self.assertRegex("Sell the rip", FORBIDDEN_WORDS)
        self.assertNotRegex("surachat", FORBIDDEN_WORDS)
        self.assertNotRegex("ventes", FORBIDDEN_WORDS)
        self.assertEqual(FORBIDDEN_WORDS.count(chr(8)), 0)     # a backspace, not \b
        universe = UNIVERSE + OTHERS
        daily = {s: series(breakout()) for s, _ in universe}
        daily["EURUSD=X"] = series(short_only())
        b = briefing.build_briefing(universe, daily, [], {}, cal(), TUE,
                                    config=many_ideas_config(max_total_pct=10))
        sides = {i["side"] for i in b["trade_ideas"]["ideas"]}
        self.assertEqual(sides, {"haussier", "baissier"})
        self.assertNotRegex(briefing.render_summary(b), FORBIDDEN_WORDS)
        self.assertNotRegex(json.dumps(b, ensure_ascii=False, indent=2), FORBIDDEN_WORDS)

        def keys(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    yield k
                    yield from keys(v)
            elif isinstance(x, list):
                for v in x:
                    yield from keys(v)
        bad = [k for k in keys(b["trade_ideas"])
               if re.search(r"gain|loss|profit|pnl|perte", k, re.I)]
        self.assertEqual(bad, [])


# ------------------------------------------------------------------- fx.main

class Recorder:
    def __init__(self, daily, hourly=None, failed=(), calendar=None):
        self.daily, self.hourly = daily, hourly or {}
        self.failed, self.calendar = list(failed), calendar or cal()
        self.calls = []

    def fetch_bars(self, symbols, interval, rng, **kw):
        self.calls.append((list(symbols), interval, rng, kw))
        if interval == data.DAILY[0]:
            return ({s: self.daily[s] for s in symbols if s in self.daily},
                    list(self.failed))
        return {s: self.hourly[s] for s in symbols if s in self.hourly}, []

    def fetch_calendar(self):
        return self.calendar

    def deps(self):
        return {"fetch_bars": self.fetch_bars, "fetch_calendar": self.fetch_calendar}


def run_main(argv, deps):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = fx.main(argv, deps)
    return code, out.getvalue()


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.list = os.path.join(self.tmp.name, "l.txt")
        with open(self.list, "w", encoding="utf-8") as f:
            f.write("# t\n" + "\n".join("%s|%s" % u for u in UNIVERSE) + "\n")
        self.out = os.path.join(self.tmp.name, "sub", "briefing.json")
        # never read a real trader/fx/config.json from the working directory
        patcher = mock.patch.object(fx, "DEFAULT_CONFIG",
                                    os.path.join(self.tmp.name, "no_such_config.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def argv(self, *extra):
        return ["brief", "--list", self.list, "--out", self.out,
                "--now", "2026-11-10 10:00"] + list(extra)

    def test_main_writes_briefing_json_and_returns_0(self):
        rec = Recorder(all_breakouts())
        code, text = run_main(self.argv(), rec.deps())
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(set(b), SPEC_KEYS)
        self.assertEqual(b["counts"]["fetched"], 4)
        self.assertIn("Reçus : 4 sur 4 (0 en échec)", text)
        self.assertLessEqual(len(text.splitlines()), 40)
        # daily for everyone, then hourly for hits + majors only
        (syms1, i1, r1, kw1), (syms2, i2, r2, kw2) = rec.calls
        self.assertEqual((i1, r1), data.DAILY)
        self.assertEqual((i2, r2), data.HOURLY)
        self.assertEqual(syms1, [s for s, _ in UNIVERSE])
        self.assertEqual(len(syms2), len(set(syms2)))
        self.assertEqual(kw1["ttl_s"], data.TTL_DAILY)
        self.assertEqual(kw2["ttl_s"], data.TTL_INTRADAY)
        self.assertEqual(kw1["cache_dir"], "trader/fx/cache")
        self.assertTrue(kw1["use_cache"])

    def test_workers_3_is_passed_for_daily_and_hourly(self):
        rec = Recorder(all_breakouts())
        run_main(self.argv(), rec.deps())
        self.assertEqual([c[3]["workers"] for c in rec.calls], [3, 3])

    def test_piped_stdout_is_utf8(self):
        """Subprocess with stdout piped: `brief --now yesterday` prints one accented
        line ("doit être au format") and exits 1 before any network call."""
        script = os.path.join(os.path.dirname(HERE), "fx.py")
        env = dict(os.environ)
        env.pop("PYTHONIOENCODING", None)
        env.pop("PYTHONUTF8", None)
        r = subprocess.run([sys.executable, script, "brief", "--now", "yesterday"],
                           capture_output=True, env=env, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 1)
        self.assertIn("être".encode("utf-8"), r.stdout)
        self.assertIn("être", r.stdout.decode("utf-8"))

    def test_no_cache_flag_is_passed_down(self):
        rec = Recorder(all_breakouts())
        run_main(self.argv("--no-cache"), rec.deps())
        self.assertFalse(rec.calls[0][3]["use_cache"])
        self.assertFalse(rec.calls[1][3]["use_cache"])

    def test_main_returns_1_and_writes_nothing_when_no_symbol_fetched(self):
        failed = [{"symbol": s, "reason": "no data"} for s, _ in UNIVERSE]
        rec = Recorder({}, failed=failed)
        code, text = run_main(self.argv(), rec.deps())
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_main_json_flag_prints_json(self):
        rec = Recorder(all_breakouts())
        code, text = run_main(self.argv("--json"), rec.deps())
        self.assertEqual(code, 0)
        self.assertEqual(set(json.loads(text)), SPEC_KEYS)
        self.assertTrue(os.path.exists(self.out))

    def test_main_saturday_and_calendar_down_still_produces(self):
        rec = Recorder(all_breakouts(), calendar=cal("unavailable", reason="this week: boom"))
        argv = ["brief", "--list", self.list, "--out", self.out, "--now", "2026-11-14 10:00"]
        code, text = run_main(argv, rec.deps())
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(b["market_state"], "closed_weekend")
        self.assertEqual(b["calendar"]["status"], "unavailable")
        self.assertIn("boom", " ".join(b["warnings"]))

    def test_missing_hourly_data_adds_a_warning(self):
        rec = Recorder(all_breakouts())
        run_main(self.argv(), rec.deps())
        with open(self.out, encoding="utf-8") as f:
            b = json.load(f)
        self.assertTrue(any("1 h" in w for w in b["warnings"]))

    def test_missing_list_returns_1(self):
        rec = Recorder(all_breakouts())
        code, text = run_main(["brief", "--list", os.path.join(self.tmp.name, "nope.txt"),
                               "--out", self.out], rec.deps())
        self.assertEqual(code, 1)
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_list_in_cp1252_returns_1_with_one_line(self):
        bad = os.path.join(self.tmp.name, "cp.txt")
        with open(bad, "wb") as f:
            f.write("EURUSD=X|Euro étalon\n".encode("cp1252"))
        rec = Recorder(all_breakouts())
        code, text = run_main(["brief", "--list", bad, "--out", self.out], rec.deps())
        self.assertEqual(code, 1)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertIn("Liste illisible", text)
        self.assertNotIn("Traceback", text)
        self.assertEqual(rec.calls, [])

    def test_bad_now_returns_1(self):
        rec = Recorder(all_breakouts())
        code, text = run_main(self.argv()[:-2] + ["--now", "yesterday"], rec.deps())
        self.assertEqual(code, 1)

    def test_now_is_new_york_time(self):
        self.assertEqual(
            fx.parse_now("2026-11-14 10:00"),
            datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(
            fx.parse_now("2026-07-14 10:00"),
            datetime(2026, 7, 14, 14, 0, tzinfo=timezone.utc))

    def test_duplicate_symbols_across_lists_are_requested_once(self):
        other = os.path.join(self.tmp.name, "o.txt")
        with open(other, "w", encoding="utf-8") as f:
            f.write("EURUSD=X|dup\nGC=F|Or\n")
        rec = Recorder(all_breakouts())
        run_main(["brief", "--list", self.list, "--list", other, "--out", self.out,
                  "--now", "2026-11-10 10:00"], rec.deps())
        syms = rec.calls[0][0]
        self.assertEqual(syms.count("EURUSD=X"), 1)
        self.assertIn("GC=F", syms)

    # ---- configuration

    def write_config(self, obj, name="config.json"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        return path

    def test_main_config_error_returns_1_and_writes_nothing(self):
        bad = [({"risk": {"per_trade": 1}}, "per_trade"),                  # unknown key
               ({"account": {"capital": "100000"}}, "account.capital"),    # capital as text
               ({"account": {"currency": "EUR"}}, "USD")]                  # not USD
        for obj, needle in bad:
            with self.subTest(config=obj):
                rec = Recorder(all_breakouts())
                code, text = run_main(self.argv("--config", self.write_config(obj)),
                                      rec.deps())
                self.assertEqual(code, 1)
                self.assertEqual(len(text.strip().splitlines()), 1)
                self.assertIn(needle, text)
                self.assertNotIn("Traceback", text)
                self.assertFalse(os.path.exists(self.out))
                self.assertEqual(rec.calls, [])          # no network call

    def test_main_explicit_config_path_must_exist(self):
        missing = os.path.join(self.tmp.name, "absent", "my_config.json")
        rec = Recorder(all_breakouts())
        code, text = run_main(self.argv("--config", missing), rec.deps())
        self.assertEqual(code, 1)
        self.assertEqual(text.strip().splitlines(),
                         ["Fichier de configuration introuvable : %s." % missing])
        self.assertEqual(rec.calls, [])                  # no network call
        self.assertFalse(os.path.exists(self.out))

    def test_main_absent_default_config_gives_the_defaults(self):
        self.assertFalse(os.path.exists(fx.DEFAULT_CONFIG))
        rec = Recorder(all_breakouts())
        code, text = run_main(self.argv(), rec.deps())
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(b["trade_ideas"]["account"]["source"], "default")
        self.assertIn("(valeurs par défaut)", text)

    def test_main_real_config_file_is_source_file(self):
        rec = Recorder(all_breakouts())
        code, text = run_main(self.argv("--config", self.write_config({})), rec.deps())
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(b["trade_ideas"]["account"]["source"], "file")
        self.assertNotIn("valeurs par défaut", text)

    def test_main_config_is_checked_before_the_lists(self):
        rec = Recorder(all_breakouts())
        code, text = run_main(
            ["brief", "--list", os.path.join(self.tmp.name, "nope.txt"), "--out", self.out,
             "--config", self.write_config({"bogus": 1})], rec.deps())
        self.assertEqual(code, 1)
        self.assertIn("bogus", text)
        self.assertNotIn("Liste illisible", text)

    def test_main_unreadable_config_returns_1_with_one_line(self):
        path = os.path.join(self.tmp.name, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        rec = Recorder(all_breakouts())
        code, text = run_main(self.argv("--config", path), rec.deps())
        self.assertEqual(code, 1)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_main_passes_the_loaded_config_down(self):
        path = self.write_config({"account": {"capital": 50000}})
        rec = Recorder(all_breakouts())
        code, _ = run_main(self.argv("--config", path), rec.deps())
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(b["trade_ideas"]["account"]["capital"], 50000)
        self.assertEqual(b["trade_ideas"]["account"]["risk_per_trade_usd"], 250.0)
        self.assertEqual(b["trade_ideas"]["account"]["source"], "file")

    def test_main_writes_trade_ideas_and_prints_the_block(self):
        rec = Recorder(all_breakouts())
        code, text = run_main(self.argv(), rec.deps())
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as f:
            b = json.load(f)
        self.assertTrue(b["trade_ideas"]["ideas"])
        self.assertIn("plan mécanique à valider. Compte 100000 USD", text)

    def test_main_saturday_still_gives_ideas_with_the_weekend_warning(self):
        rec = Recorder(all_breakouts())
        argv = ["brief", "--list", self.list, "--out", self.out, "--now", "2026-11-14 10:00"]
        code, text = run_main(argv, rec.deps())
        self.assertEqual(code, 0)
        with open(self.out, encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(b["market_state"], "closed_weekend")
        self.assertEqual(b["trade_ideas"]["reference"], "last_close")
        self.assertTrue(b["trade_ideas"]["ideas"])
        self.assertTrue(any("week-end" in w for w in b["warnings"]))
        self.assertIn("Idées de trade (", text)

    def test_alert_list_includes_short_only_hits(self):
        # GBPUSD=X is not first among the majors: it leads the list only as a hit
        daily = {"EURUSD=X": series(neutral()), "GBPUSD=X": series(short_only()),
                 "AUDUSD=X": series(neutral()), "USDJPY=X": series(neutral())}
        rec = Recorder(daily)
        run_main(self.argv(), rec.deps())
        self.assertEqual(rec.calls[1][0][0], "GBPUSD=X")


class TestMainDefaultConfig(unittest.TestCase):
    def test_main_default_config_path_is_trader_fx_config_json(self):
        self.assertEqual(DEFAULT_CONFIG_PATH, "trader/fx/config.json")
        self.assertEqual(fx.build_parser().parse_args(["brief"]).config,
                         "trader/fx/config.json")
        self.assertEqual(
            fx.build_parser().parse_args(["brief", "--config", "x.json"]).config, "x.json")

    def test_main_reads_trader_fx_config_json_from_the_working_directory(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "trader", "fx"))
            with open(os.path.join(d, "trader", "fx", "config.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"risk": {"per_trade_pct": 1.0}}, f)
            lst = os.path.join(d, "l.txt")
            with open(lst, "w", encoding="utf-8") as f:
                f.write("\n".join("%s|%s" % u for u in UNIVERSE) + "\n")
            out = os.path.join(d, "briefing.json")
            here = os.getcwd()
            os.chdir(d)
            try:
                code, _ = run_main(["brief", "--list", lst, "--out", out,
                                    "--now", "2026-11-10 10:00"],
                                   Recorder(all_breakouts()).deps())
            finally:
                os.chdir(here)
            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as f:
                b = json.load(f)
            self.assertEqual(b["trade_ideas"]["account"]["risk_per_trade_usd"], 1000.0)


if __name__ == "__main__":
    unittest.main()
