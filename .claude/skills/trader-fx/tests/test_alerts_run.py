import _path  # noqa
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import alert_checks
import alert_state
import alerts_run
import intraday_run
from intraday_helpers import make_bars, utc

NOW = datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc)
TODAY = "2026-11-16"
SINCE = "2026-11-16T10:00:00+00:00"
SECRET_CONFIG = '{"account": {"currency": "USD", "capital": 250000}}'
FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b")
FORBIDDEN_SIGNAL = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell|prévision|gagnant|profit)\b"
                              r"|à prendre")
SIGNAL_NOW = utc(2026, 11, 16, 8, 52)              # the 08:30 bar closed at 08:45
SIGNAL_BAR = "2026-11-16T08:30:00+00:00"


def ts(h, m=0):
    return int(datetime(2026, 11, 16, h, m, tzinfo=timezone.utc).timestamp())


def bar(h, m, low, high):
    return (ts(h, m), (low + high) / 2, high, low, (low + high) / 2)


def rules_doc(*rules, v=1):
    return {"v": v, "updated": "2026-11-16T09:00:00+00:00", "rules": list(rules)}


def rule(kind="stop", level=1.095, trade="T", symbol="EURUSD=X", side="haussier"):
    return {"id": "%s-%s" % (trade, kind), "trade_id": trade, "symbol": symbol, "type": kind,
            "side": side, "level": level, "decimals": 5, "since": SINCE}


def idea(symbol="AUDUSD=X", side="baissier", rank=1):
    return {"rank": rank, "symbol": symbol, "name": "AUD/USD", "side": side, "score": 3,
            "setups": ["breakdown_20d"], "reference_price": 0.68069, "stop": 0.69005,
            "target": 0.66197, "rr": 2.0, "decimals": 5, "since_close": None,
            "size": {"status": "ok", "lots": 0.53, "units": 53000, "size": None, "risk_usd": 496.08}}


def briefing_doc(*ideas, market_state="open"):
    return {"market_state": market_state,
            "trade_ideas": {"account": {"capital": 100000, "risk_per_trade_usd": 500.0,
                                        "source": "file"}, "ideas": list(ideas)}}


def event(h=13, m=25, currency="USD", title="Core CPI m/m"):
    return {"utc": datetime(2026, 11, 16, h, m, tzinfo=timezone.utc).isoformat(),
            "currency": currency, "title": title, "impact": "High", "time_paris": "%02d:%02d" % (h + 1, m)}


class Harness(unittest.TestCase):
    """A temporary folder, fake sources and a fake Telegram; run() returns (exit code, output)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.alerts = os.path.join(self.dir, "alerts.json")
        self.state = os.path.join(self.dir, "alerts_state.json")
        self.config = os.path.join(self.dir, "config.json")
        self.gh_output = os.path.join(self.dir, "gh_output.txt")
        self.sent, self.calls = [], []
        self.bars = {"EURUSD=X": [bar(10, 5, 1.099, 1.101)]}
        self.bars15 = {}                            # served when interval == "15m"
        self.bars_fail = False
        self.events = []
        self.briefing = briefing_doc(idea())
        self.send_script = []                       # (ok, reason) answers; default (True, None)
        self.env = {"TELEGRAM_BOT_TOKEN": "tok-SECRET", "TELEGRAM_CHAT_ID": "42",
                    "GITHUB_OUTPUT": self.gh_output}

    def write_alerts(self, doc):
        with open(self.alerts, "w", encoding="utf-8") as f:
            json.dump(doc, f) if not isinstance(doc, str) else f.write(doc)

    def deps(self, now=NOW):
        def fetch_bars(symbols, interval, rng, **kw):
            self.calls.append(("bars", tuple(symbols), interval, rng))
            if self.bars_fail:
                return {}, [{"symbol": s, "reason": "HTTP 500"} for s in symbols]
            source = self.bars15 if interval == "15m" else self.bars
            return ({s: SimpleNamespace(bars=source[s]) for s in symbols if s in source},
                    [{"symbol": s, "reason": "x"} for s in symbols if s not in source])

        def fetch_calendar():
            self.calls.append(("calendar",))
            return {"status": "ok", "events": self.events, "reason": None}

        def brief(config_path):
            self.calls.append(("brief", config_path))
            return self.briefing

        def send(token, chat, text):
            self.calls.append(("send", token, chat))
            self.sent.append(text)
            return self.send_script.pop(0) if self.send_script else (True, None)

        return {"fetch_bars": fetch_bars, "fetch_calendar": fetch_calendar, "brief": brief,
                "send": send, "now": lambda: now, "env": self.env}

    def run_main(self, *extra, now=NOW):
        argv = ["--state", self.state, "--alerts", self.alerts, "--config", self.config] + list(extra)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = alerts_run.main(argv, self.deps(now))
        self.output = out.getvalue() + err.getvalue()
        return code

    def state_bytes(self):
        with open(self.state, "rb") as f:
            return f.read()

    def saved_state(self):
        with open(self.state, encoding="utf-8") as f:
            return json.load(f)

    def prefixes(self):
        return [t.split(" :")[0].split(" dans")[0] for t in self.sent]

    def london_break_setup(self, with_idea=False):
        """A real Londres session break on EURUSD=X: the 08:00 and 08:15 bars form the range, the
        08:30 bar closes at 1.1020, above it. Use with now=SIGNAL_NOW (08:52 UTC)."""
        flat = (1.1000, 1.1004, 1.0996, 1.1000)
        self.bars15 = {"EURUSD=X": make_bars(utc(2026, 11, 16, 7, 0), [
            flat, flat, flat, flat,                                    # 07:00 .. 07:45
            (1.1000, 1.1010, 1.0990, 1.1005),                          # 08:00
            (1.1005, 1.1012, 1.0995, 1.1000),                          # 08:15
            (1.1005, 1.1025, 1.1000, 1.1020)])}                        # 08:30, closes at 08:45
        self.briefing = briefing_doc(idea()) if with_idea else briefing_doc()
        self.briefing["daily_context"] = {"EURUSD=X": {"name": "EUR/USD", "last": 1.102,
                                                      "atr_pct": 0.6, "trend": "up"}}

    def signal_texts(self):
        return [t for t in self.sent if t.startswith("Signal en séance")]

    def bars15_calls(self):
        return [c for c in self.calls if c[0] == "bars" and c[2] == "15m"]


class TestFullRun(Harness):
    def full_setup(self):
        self.write_alerts(rules_doc(rule("stop", 1.095), rule("cible", 1.11)))
        self.bars = {"EURUSD=X": [bar(10, 5, 1.099, 1.101), bar(10, 10, 1.094, 1.1)]}
        self.events = [event(13, 25)]

    def test_full_run_sends_stops_then_events_then_ideas_in_order_and_marks_them(self):
        self.full_setup()
        self.assertEqual(self.run_main(), 0, self.output)
        self.assertEqual(len(self.sent), 3)
        self.assertTrue(self.sent[0].startswith("Stop touché : EUR/USD haussier, trade T."), self.sent[0])
        self.assertTrue(self.sent[1].startswith("Annonce à fort impact dans 25 min"), self.sent[1])
        self.assertTrue(self.sent[2].startswith("Idée de trade, en formation"), self.sent[2])
        st = self.saved_state()
        self.assertEqual(st["rules_fired"], [alert_checks.rule_key(rule("stop", 1.095))])
        self.assertEqual(st["events_sent"], [alert_checks.event_key(self.events[0])])
        self.assertEqual(st["ideas_sent"], ["AUDUSD=X|baissier|2026-11-16"])
        self.assertEqual(st["day"], TODAY)
        for text in self.sent:
            self.assertIsNone(FORBIDDEN.search(text))
        self.assertIn(("bars", ("EURUSD=X",), "5m", "5d"), self.calls)
        self.assertTrue(all(c[1:] == ("tok-SECRET", "42") for c in self.calls if c[0] == "send"))

    def test_second_run_sends_nothing_new(self):
        self.full_setup()
        self.run_main()
        self.sent.clear()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.sent, [])

    def test_a_new_day_announces_the_idea_again_but_not_the_fired_rule(self):
        self.full_setup()
        self.run_main()
        self.sent.clear()
        tomorrow = NOW + timedelta(days=1)
        self.events = []
        self.assertEqual(self.run_main(now=tomorrow), 0)
        self.assertEqual(self.prefixes(), ["Idée de trade, en formation, non confirmée à la clôture"])

    def test_no_rules_means_no_bars_and_no_calendar_call_but_ideas_still_go(self):
        self.write_alerts(rules_doc())
        self.assertEqual(self.run_main(), 0)
        self.assertEqual([c[0] for c in self.calls if c[0] in ("bars", "calendar")], [])
        self.assertEqual(len(self.sent), 1)


class TestFailures(Harness):
    def test_failed_send_is_not_marked_stops_the_run_and_exit_code_is_1(self):
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.bars = {"EURUSD=X": [bar(10, 10, 1.094, 1.1)]}
        self.send_script = [(False, "HTTP 500")]
        self.assertEqual(self.run_main(), 1)
        self.assertEqual(len(self.sent), 1)                       # stopped after the first failure
        self.assertFalse(os.path.exists(self.state))              # nothing was marked: nothing to save
        self.assertIn("HTTP 500", self.output)
        self.assertNotIn("SECRET", self.output)
        self.sent.clear()
        self.assertEqual(self.run_main(), 0)                       # the next run sends them again
        self.assertEqual(len(self.sent), 2)

    def test_missing_telegram_secrets_exit_1_except_in_dry_run(self):
        self.env.pop("TELEGRAM_BOT_TOKEN")
        self.assertEqual(self.run_main(), 1)
        self.assertEqual(self.sent, [])
        self.assertIn("TELEGRAM_BOT_TOKEN", self.output)
        self.assertEqual(self.run_main("--dry-run"), 0)

    def test_alerts_json_invalid_or_wrong_version_still_sends_ideas(self):
        for doc in ("{", "[]", rules_doc(rule(), v=2)):
            self.setUp()
            self.write_alerts(doc)
            self.assertEqual(self.run_main(), 0, self.output)
            self.assertEqual(self.prefixes(), ["Idée de trade, en formation, non confirmée à la clôture"])
            self.assertEqual([c for c in self.calls if c[0] in ("bars", "calendar")], [])

    def test_missing_alerts_json_still_sends_ideas(self):
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(self.sent), 1)

    def test_all_bars_missing_sends_one_down_message_per_day(self):
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.bars_fail = True
        self.assertEqual(self.run_main(), 0)
        downs = [t for t in self.sent if t.startswith("Impossible de vérifier vos stops")]
        self.assertEqual(len(downs), 1)
        self.sent.clear()
        self.run_main()
        self.assertEqual([t for t in self.sent if t.startswith("Impossible")], [])
        self.sent.clear()
        self.run_main(now=NOW + timedelta(days=1))
        self.assertEqual(len([t for t in self.sent if t.startswith("Impossible")]), 1)

    def test_one_missing_symbol_among_several_is_only_logged(self):
        self.write_alerts(rules_doc(rule("stop", 1.095), rule("stop", 150.0, "U", "USDJPY=X", "haussier")))
        self.bars = {"EURUSD=X": [bar(10, 5, 1.099, 1.101)]}
        self.assertEqual(self.run_main(), 0)
        self.assertEqual([t for t in self.sent if t.startswith("Impossible")], [])
        self.assertIn("USDJPY=X", self.output)

    def test_briefing_unavailable_skips_ideas_but_not_stops(self):
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.bars = {"EURUSD=X": [bar(10, 10, 1.094, 1.1)]}
        self.briefing = None
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.prefixes(), ["Stop touché"])
        self.assertIn("briefing", self.output.lower())

    def test_an_exception_in_the_briefing_skips_ideas_only(self):
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.bars = {"EURUSD=X": [bar(10, 10, 1.094, 1.1)]}

        def boom(config_path):
            raise ZeroDivisionError("secret detail 987654")

        deps = self.deps()
        deps["brief"] = boom
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = alerts_run.main(["--state", self.state, "--alerts", self.alerts,
                                    "--config", self.config], deps)
        self.assertEqual(code, 0)
        self.assertEqual(self.prefixes(), ["Stop touché"])
        self.assertIn("ZeroDivisionError", out.getvalue())
        self.assertNotIn("987654", out.getvalue())

    def test_a_rule_without_trade_id_does_not_silence_the_others(self):
        broken = rule("stop", 1.0, "X")
        del broken["trade_id"]
        self.write_alerts(rules_doc(broken, rule("stop", 1.095)))
        self.bars = {"EURUSD=X": [bar(10, 10, 1.0, 1.1)]}
        self.assertEqual(self.run_main(), 0, self.output)
        self.assertEqual(self.prefixes()[0], "Stop touché")
        self.assertEqual(len([t for t in self.sent if t.startswith("Stop touché")]), 1)

    def test_a_level_moved_after_its_alert_is_announced_again(self):
        self.write_alerts(rules_doc(rule("cible", 1.11)))
        self.bars = {"EURUSD=X": [bar(10, 10, 1.1, 1.1101), bar(10, 40, 1.1, 1.121)]}
        self.briefing = None
        self.run_main()
        self.assertEqual(self.prefixes(), ["Cible touchée"])
        self.sent.clear()
        moved = rule("cible", 1.12)
        moved["since"] = "2026-11-16T10:30:00+00:00"                  # the user moved the target
        self.write_alerts(rules_doc(moved))
        self.run_main()
        self.assertEqual(self.prefixes(), ["Cible touchée"])
        self.sent.clear()
        self.run_main()
        self.assertEqual(self.sent, [])                                 # and only once

    def test_closed_weekend_sends_no_idea_but_still_checks_stops(self):
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.bars = {"EURUSD=X": [bar(10, 10, 1.094, 1.1)]}
        self.briefing = briefing_doc(idea(), market_state="closed_weekend")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.prefixes(), ["Stop touché"])


class TestState(Harness):
    def test_state_saved_only_when_changed_and_github_output_says_so(self):
        self.run_main()
        with open(self.gh_output, encoding="utf-8") as f:
            self.assertIn("state_changed=true", f.read())
        before = self.state_bytes()
        self.run_main()
        with open(self.gh_output, encoding="utf-8") as f:
            self.assertTrue(f.read().strip().endswith("state_changed=false"))
        self.assertEqual(self.state_bytes(), before)

    def test_fired_rules_that_left_alerts_json_are_forgotten_only_when_the_file_is_readable(self):
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "day": TODAY, "ideas_sent": [], "rules_fired": ["OLD-stop"],
                       "events_sent": [], "down_notified_day": None}, f)
        self.write_alerts("{")                                   # unreadable: keep what we know
        self.run_main()
        self.assertEqual(self.saved_state()["rules_fired"], ["OLD-stop"])
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.bars = {"EURUSD=X": [bar(10, 5, 1.099, 1.101)]}
        self.run_main()
        self.assertEqual(self.saved_state()["rules_fired"], [])

    def test_announced_events_are_kept_while_the_calendar_is_empty(self):
        key = "2026-11-16T13:25:00+00:00|USD|Core CPI m/m"
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "day": TODAY, "ideas_sent": [], "rules_fired": [],
                       "events_sent": [key], "down_notified_day": None}, f)
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.events = []                                         # calendar down or empty
        self.run_main()
        self.assertEqual(self.saved_state()["events_sent"], [key])
        self.events = [event(13, 25)]
        self.sent.clear()
        self.run_main()
        self.assertEqual([t for t in self.sent if t.startswith("Annonce")], [])


class TestDryRun(Harness):
    def test_dry_run_prints_messages_and_writes_no_state_and_sends_nothing(self):
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.bars = {"EURUSD=X": [bar(10, 10, 1.094, 1.1)]}
        self.assertEqual(self.run_main("--dry-run"), 0)
        self.assertEqual(self.sent, [])
        self.assertFalse(os.path.exists(self.state))
        self.assertIn("Stop touché : EUR/USD haussier", self.output)
        self.assertIn("Idée de trade, en formation", self.output)
        self.assertGreaterEqual(self.output.count("---"), 4)
        with open(self.gh_output, encoding="utf-8") as f:
            self.assertIn("state_changed=false", f.read())


class TestConfigSecret(Harness):
    def test_trader_fx_config_secret_is_written_validated_and_never_printed(self):
        self.env["TRADER_FX_CONFIG"] = SECRET_CONFIG
        self.assertEqual(self.run_main(), 0, self.output)
        with open(self.config, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["account"]["capital"], 250000)
        self.assertIn(("brief", self.config), self.calls)
        self.assertNotIn("250000", self.output)
        for text in self.sent:
            self.assertNotIn("250000", text)

    def test_an_invalid_secret_gives_one_line_exit_1_and_no_value_in_the_output(self):
        for bad in ('{"account": {"capital": -123456}}', "not json 123456", '{"risk": {"per_trade_pct": 77}}'):
            self.setUp()
            self.env["TRADER_FX_CONFIG"] = bad
            self.assertEqual(self.run_main(), 1)
            self.assertEqual(len(self.output.strip().splitlines()), 1, self.output)
            self.assertNotIn("123456", self.output)
            self.assertNotIn("77", self.output)
            self.assertIn("TRADER_FX_CONFIG", self.output)
            self.assertEqual(self.sent, [])

    def test_without_the_secret_the_default_capital_line_is_in_the_idea(self):
        self.briefing = briefing_doc(idea())
        self.briefing["trade_ideas"]["account"]["source"] = "default"
        self.run_main()
        self.assertIn("Taille calculée sur le capital par défaut.", self.sent[0])


class TestNow(Harness):
    def test_now_option_fixes_the_utc_time(self):
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.events = [event(13, 25)]
        self.assertEqual(self.run_main("--now", "2026-11-16 13:00"), 0)
        self.assertTrue(any(t.startswith("Annonce") for t in self.sent))
        self.sent.clear()
        self.setUp()
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.events = [event(13, 25)]
        self.run_main("--now", "2026-11-16 12:00")
        self.assertFalse(any(t.startswith("Annonce") for t in self.sent))

    def test_a_bad_now_is_one_line_exit_1(self):
        self.assertEqual(self.run_main("--now", "yesterday"), 1)
        self.assertEqual(len(self.output.strip().splitlines()), 1)


class TestSignals(Harness):
    def setUp(self):
        super().setUp()
        with open(self.config, "w", encoding="utf-8") as fh:      # les signaux sont désactivés par défaut
            fh.write('{"intraday": {"enabled": true}}')

    def run_signal(self, *extra, now=SIGNAL_NOW):
        return self.run_main(*extra, now=now)

    def test_signal_alert_is_sent_after_ideas_and_marked(self):
        self.london_break_setup(with_idea=True)
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(len(self.sent), 2, self.sent)
        self.assertTrue(self.sent[0].startswith("Idée de trade"), self.sent[0])
        self.assertTrue(self.sent[1].startswith("Signal en séance"), self.sent[1])
        for text in self.sent:
            self.assertIsNone(FORBIDDEN_SIGNAL.search(text), text)
        st = self.saved_state()
        self.assertEqual(st["signals_count"], 1)
        self.assertEqual(len(st["signals_sent"]), 1)
        self.assertTrue(alert_state.signal_sent_for_bar(st, "EURUSD=X", "haussier", SIGNAL_BAR))
        self.assertTrue(st["signals_sent"][0].startswith("EURUSD=X|haussier|" + SIGNAL_BAR + "|"))
        self.assertIn(("bars", ("EURUSD=X",), "15m", "5d"), self.calls)

    def test_second_run_sends_no_duplicate_for_the_same_bar(self):
        self.london_break_setup()
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(len(self.signal_texts()), 1)                    # premise
        self.sent.clear()
        before = self.state_bytes()
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.state_bytes(), before)

    def test_failed_send_is_not_marked_and_is_resent_next_run_while_fresh_and_not_after_30_minutes(self):
        self.london_break_setup()
        self.send_script = [(False, "HTTP 500")]
        self.assertEqual(self.run_signal(), 1, self.output)
        self.assertEqual(len(self.signal_texts()), 1)                    # it was attempted
        self.assertFalse(os.path.exists(self.state))                     # nothing marked
        self.assertNotIn("SECRET", self.output)
        # more than 30 minutes after the bar closed (08:45): too old, nothing is sent
        self.sent.clear()
        self.assertEqual(self.run_signal(now=utc(2026, 11, 16, 9, 37)), 0, self.output)
        self.assertEqual(self.sent, [])
        self.assertFalse(os.path.exists(self.state))
        # still fresh: it goes again, and is marked this time
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(len(self.signal_texts()), 1)
        self.assertEqual(self.saved_state()["signals_count"], 1)
        self.assertIsNone(FORBIDDEN_SIGNAL.search(self.sent[0]))

    def test_exception_in_signals_does_not_silence_stops_or_ideas(self):
        self.london_break_setup(with_idea=True)
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.bars = {"EURUSD=X": [bar(10, 10, 1.094, 1.1)]}
        with mock.patch.object(intraday_run, "collect",
                               side_effect=ZeroDivisionError("secret detail 987654")):
            code = self.run_main(now=NOW)
        self.assertEqual(code, 0, self.output)
        self.assertEqual(self.prefixes(),
                         ["Stop touché", "Idée de trade, en formation, non confirmée à la clôture"])
        self.assertIn("ZeroDivisionError", self.output)
        self.assertNotIn("987654", self.output)
        self.assertNotIn("secret detail", self.output)
        self.assertEqual(self.saved_state()["signals_count"], 0)

    def test_dry_run_prints_signal_and_writes_no_state(self):
        self.london_break_setup()
        self.assertEqual(self.run_signal("--dry-run"), 0, self.output)
        self.assertEqual(self.sent, [])
        self.assertFalse(os.path.exists(self.state))
        self.assertIn("Signal en séance", self.output)
        self.assertIsNone(FORBIDDEN_SIGNAL.search(self.output.split("\n---\n", 1)[1]))
        with open(self.gh_output, encoding="utf-8") as f:
            self.assertIn("state_changed=false", f.read())

    def test_signal_cap_10_per_day_across_runs(self):
        self.london_break_setup()
        capped = alert_state.empty_state(TODAY)
        capped["signals_count"] = 10
        with open(self.state, "w", encoding="utf-8") as f:
            json.dump(capped, f)
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(self.signal_texts(), [])
        self.assertEqual(len(self.sent), 1, self.sent)
        self.assertIn("Plafond de 10 alertes de signal atteint", self.sent[0])
        self.assertIsNone(FORBIDDEN_SIGNAL.search(self.sent[0]))
        self.assertEqual(self.saved_state()["signals_cap_day"], TODAY)
        self.assertEqual(self.saved_state()["signals_count"], 10)
        self.sent.clear()
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(self.sent, [])

    def test_secret_config_capital_never_printed_in_logs(self):
        self.london_break_setup()
        self.env["TRADER_FX_CONFIG"] = SECRET_CONFIG[:-1] + ', "intraday": {"enabled": true}}'
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(len(self.signal_texts()), 1)                    # premise
        self.assertNotIn("250000", self.output)
        for text in self.sent:
            self.assertNotIn("250000", text)
        self.assertNotIn("250000", json.dumps(self.saved_state()))

    def test_calendar_is_fetched_only_when_a_signal_candidate_exists_and_without_open_rules(self):
        def calendar():
            return [c for c in self.calls if c[0] == "calendar"]
        # a candidate, no open rule: the calendar is read once, and no block means the alert goes
        self.london_break_setup()
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(len(calendar()), 1)
        self.assertEqual(len(self.signal_texts()), 1)
        # a High USD or EUR event within 30 minutes blocks the alert
        for currency in ("USD", "EUR"):
            self.setUp()
            self.london_break_setup()
            self.events = [event(9, 10, currency)]
            self.assertEqual(self.run_signal(), 0, self.output)
            self.assertEqual(len(calendar()), 1, currency)
            self.assertEqual(self.signal_texts(), [], currency)
        # a candidate and an open trade on the other side: the calendar read for the
        # announcements is reused, never fetched twice
        self.setUp()
        self.london_break_setup()
        self.write_alerts(rules_doc(rule("stop", 1.12, side="baissier")))
        self.events = [event(9, 10, "EUR")]
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(len(calendar()), 1)
        self.assertEqual(self.signal_texts(), [])
        # no daily context: no 15-minute bars and no calendar
        self.setUp()
        self.briefing = briefing_doc()
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(self.bars15_calls(), [])
        self.assertEqual(calendar(), [])
        # a daily context but no signal: bars are asked, the calendar is not
        self.setUp()
        self.london_break_setup()
        flat = (1.1, 1.1, 1.1, 1.1)
        self.bars15 = {"EURUSD=X": make_bars(utc(2026, 11, 16, 7, 0), [flat] * 7)}
        self.assertEqual(self.run_signal(), 0, self.output)
        self.assertEqual(len(self.bars15_calls()), 1)
        self.assertEqual(calendar(), [])
        self.assertEqual(self.signal_texts(), [])

    def test_missing_or_invalid_alerts_json_still_sends_signals(self):
        for doc in (None, "{", "[]", rules_doc(rule(), v=2)):
            self.setUp()
            self.london_break_setup()
            if doc is not None:
                self.write_alerts(doc)
            self.assertEqual(self.run_signal(), 0, self.output)
            self.assertEqual(len(self.signal_texts()), 1, doc)
            self.assertIn("suivi des stops et annonces sautés", self.output)

    def test_existing_tests_still_see_no_15m_call_without_daily_context(self):
        self.assertNotIn("daily_context", self.briefing)
        self.assertEqual(self.run_main(), 0, self.output)
        self.assertEqual(self.bars15_calls(), [])
        self.assertIn("contexte journalier absent : signaux en séance sautés.", self.output)
        self.assertEqual(self.signal_texts(), [])
        self.assertEqual(len(self.sent), 1)                                # the idea only


if __name__ == "__main__":
    unittest.main()


SHEET_HEADER = ("Id,Actif,Symbole Yahoo,Sens,Entrée,SL,TP,Lots,\"Valeur 1,00 pour 1 lot ($)\","
                "Ouverture (Paris),,Paramètre,Valeur")
# opened 10:00 Paris = 09:00 UTC on 2026-11-16; CFD entry 3547, stop 3498, target 3640
SHEET_GOLD = 'Ligne 2,XAUUSD,GC=F,haussier,3547,3498,3640,"0,1",100,2026-11-16 10:00,,Solde clos ($),"99302,00"'
SHEET_PARAMS = ['P&L clos aujourd\'hui ($),"-382,00"', 'Capital initial ($),"100000,00"',
                'Alerte perte du jour ($),"1000,00"', 'Stop journalier interne ($),"1500,00"',
                'Perte journalière max FundedNext ($),"5000,00"', 'Plancher perte max ($),"90000,00"',
                'Risque ouvert max ($),"1500,00"']


def sheet_csv(*rows):
    lines = [SHEET_HEADER] + list(rows) + [",,,,,,,,,,," + p for p in SHEET_PARAMS]
    return "\n".join(lines) + "\n"


def gold_bar(h, m, low, high, close):
    return (ts(h, m), close, high, low, close)


class TestSheetPositions(Harness):
    """POSITIONS_CSV_URL set: the sheet replaces alerts.json and the guard runs."""

    def setUp(self):
        super().setUp()
        self.env["POSITIONS_CSV_URL"] = "https://docs.google.com/private-link"
        self.csv = sheet_csv(SHEET_GOLD)
        self.csv_fail = False
        self.briefing = briefing_doc()
        # Yahoo GC=F is 20 above the CFD: the 09:00 UTC bar closes at 3567
        self.bars = {"GC=F": [gold_bar(9, 0, 3560, 3570, 3567), gold_bar(10, 5, 3550, 3560, 3555)]}

    def deps(self, now=NOW):
        d = super().deps(now)

        def fetch_positions(url):
            self.calls.append(("csv",))
            if self.csv_fail:
                raise alerts_run.positions.PositionsError("réseau (URLError)")
            return self.csv
        d["fetch_positions"] = fetch_positions
        return d

    def test_quiet_position_sends_nothing_and_ignores_alerts_json(self):
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.assertEqual(self.run_main(), 0, self.output)
        self.assertEqual(self.sent, [])
        self.assertNotIn("EURUSD=X", str([c for c in self.calls if c[0] == "bars"]))
        self.assertIn(("bars", ("GC=F",), "5m", "5d"), self.calls)
        self.assertIn("garde-fou : 1 position(s)", self.output)

    def test_stop_level_is_moved_by_the_cfd_gap(self):
        # CFD stop 3498 + gap 20 = 3518 on Yahoo: a low of 3519 is not a touch, 3517 is
        self.bars["GC=F"].append(gold_bar(11, 0, 3519, 3530, 3525))
        self.run_main()
        self.assertFalse(any(t.startswith("Stop touché") for t in self.sent))
        self.bars["GC=F"].append(gold_bar(11, 5, 3517, 3525, 3520))
        self.sent.clear()
        self.run_main()
        stops = [t for t in self.sent if t.startswith("Stop touché")]
        self.assertEqual(len(stops), 1, self.sent)
        self.assertIn("trade XAUUSD ouvert le 16/11 10:00", stops[0])

    def test_guard_message_goes_first_and_once_a_day(self):
        # Yahoo 3497 = CFD 3477: -700 floating, -1 082 for the day
        self.bars["GC=F"].append(gold_bar(11, 0, 3496, 3530, 3497))
        self.assertEqual(self.run_main(), 0, self.output)
        self.assertTrue(self.sent[0].startswith("Garde-fou FundedNext. Seuil d'alerte franchi"), self.sent)
        self.assertIn("guard|alerte|%s" % TODAY, self.saved_state()["guard_sent"])
        self.sent.clear()
        self.run_main()
        self.assertFalse(any(t.startswith("Garde-fou") for t in self.sent))

    def test_unreadable_sheet_falls_back_to_alerts_json_and_says_it_once(self):
        self.csv_fail = True
        self.write_alerts(rules_doc(rule("stop", 1.095)))
        self.bars["EURUSD=X"] = [bar(10, 5, 1.094, 1.1)]
        self.assertEqual(self.run_main(), 0, self.output)
        self.assertTrue(self.sent[0].startswith("Garde-fou FundedNext inactif"), self.sent)
        self.assertTrue(any(t.startswith("Stop touché : EUR/USD") for t in self.sent))
        self.assertNotIn("private-link", self.output)
        self.sent.clear()
        self.run_main()
        self.assertFalse(any(t.startswith("Garde-fou") for t in self.sent))

    def test_empty_sheet_means_no_bars(self):
        self.csv = sheet_csv()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual([c for c in self.calls if c[0] == "bars" and c[2] == "5m"], [])
        self.assertEqual(self.sent, [])


class TestReversal(Harness):
    def setUp(self):
        super().setUp()
        lst = os.path.join(self.dir, "fundednext.txt")
        with open(lst, "w", encoding="utf-8") as f:
            f.write("# liste\n^NDX|Nasdaq 100 (NAS100)\n")
        self.env["TRADER_FX_REVERSE_LIST"] = lst
        start = int(NOW.timestamp()) - 70 * 86400
        closes = [30000 - i * 50 for i in range(60)]
        self.bars = {"^NDX": [(start + i * 86400, c, c + 100, c - 100, c) for i, c in enumerate(closes)]}
        self.briefing = briefing_doc()
        self.write_alerts(rules_doc())

    def test_morning_summary_once_a_day(self):
        self.assertEqual(self.run_main(), 0, self.output)
        morning = [t for t in self.sent if t.startswith("Niveaux de reverse du jour")]
        self.assertEqual(len(morning), 1, self.sent)
        self.assertIn("Nasdaq 100 (NAS100) : tendance D1 baissière", morning[0])
        self.assertIsNone(FORBIDDEN.search(morning[0]))
        self.sent.clear()
        self.run_main()
        self.assertFalse(any(t.startswith("Niveaux de reverse du jour") for t in self.sent))

    def test_not_before_six_in_paris(self):
        early = datetime(2026, 11, 16, 4, 30, tzinfo=timezone.utc)      # 05:30 Paris
        self.run_main(now=early)
        self.assertFalse(any(t.startswith("Niveaux de reverse du jour") for t in self.sent))

    def test_no_list_no_extra_calls(self):
        del self.env["TRADER_FX_REVERSE_LIST"]
        self.run_main()
        self.assertFalse(any(c[0] == "bars" and c[2] == "1d" for c in self.calls))
