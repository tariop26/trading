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

import alert_checks
import alerts_run

NOW = datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc)
TODAY = "2026-11-16"
SINCE = "2026-11-16T10:00:00+00:00"
SECRET_CONFIG = '{"account": {"currency": "USD", "capital": 250000}}'
FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b")


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
            return ({s: SimpleNamespace(bars=self.bars[s]) for s in symbols if s in self.bars},
                    [{"symbol": s, "reason": "x"} for s in symbols if s not in self.bars])

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


if __name__ == "__main__":
    unittest.main()
