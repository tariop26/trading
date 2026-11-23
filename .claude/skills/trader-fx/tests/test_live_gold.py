import _path  # noqa
import atexit
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

import alert_messages
import live_gold

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "live-gold.yml")

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)
SINCE = "2026-11-23T08:00:00+00:00"
T0 = datetime(2026, 11, 23, 8, 59, tzinfo=timezone.utc).timestamp()
FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b")


def rule(kind="stop", side="haussier", level=3600.0, symbol="GC=F", rid=None):
    return {"id": rid or "t1-%s" % kind, "trade_id": "t1", "symbol": symbol, "type": kind,
            "side": side, "level": level, "decimals": 2, "since": SINCE}


def td_text(rows, status="ok"):
    return json.dumps({"status": status, "values": [
        {"datetime": d, "open": o, "high": h, "low": l, "close": c} for d, o, h, l, c in rows]})


class Run:
    """Une exécution de la boucle avec tout le réseau remplacé."""

    def __init__(self, rules, bars_per_call, sent_ok=True):
        self.rules = rules
        self.bars = list(bars_per_call)          # une entrée par appel : liste de barres ou FeedError
        self.calls, self.sent, self.sleeps = 0, [], []
        self.sent_ok = sent_ok
        self.clock = NOW.timestamp()
        folder = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, folder, True)
        self.state = os.path.join(folder, "state.json")

    def deps(self):
        def fetch_bars(key, symbol):
            self.calls += 1
            item = self.bars[min(self.calls - 1, len(self.bars) - 1)]
            if isinstance(item, Exception):
                raise item
            return item

        def sleep(s):
            self.sleeps.append(s)
            self.clock += s

        def send(token, chat, text):
            self.sent.append(text)
            return (self.sent_ok, None if self.sent_ok else "HTTP 500")

        return {"env": {"TWELVE_DATA_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"},
                "now": lambda: datetime.fromtimestamp(self.clock, timezone.utc),
                "sleep": sleep, "fetch_bars": fetch_bars, "send": send,
                "load_rules": lambda path, url: (self.rules, SINCE)}

    def go(self, *extra):
        argv = ["--state", self.state, "--alerts", "x", *extra]
        return live_gold.main(argv, self.deps())


def bar(minute_offset, o, h, l, c):
    return [T0 + 60 * minute_offset, o, h, l, c]


class TestParse(unittest.TestCase):
    def test_bars_are_sorted_oldest_first_and_in_utc(self):
        text = td_text([("2026-11-23 08:41:00", "3600", "3606", "3599", "3605"),
                        ("2026-11-23 08:40:00", "3598", "3601", "3597", "3600")])
        bars = live_gold.parse_bars(text)
        self.assertEqual([b[0] for b in bars], sorted(b[0] for b in bars))
        self.assertEqual(bars[-1], [datetime(2026, 11, 23, 8, 41, tzinfo=timezone.utc).timestamp(),
                                    3600.0, 3606.0, 3599.0, 3605.0])

    def test_a_damaged_bar_is_skipped_not_fatal(self):
        text = json.dumps({"status": "ok", "values": [
            {"datetime": "bad", "open": "1", "high": "1", "low": "1", "close": "1"},
            {"datetime": "2026-11-23 08:41:00", "open": "1", "high": "2", "low": "0", "close": "1"}]})
        self.assertEqual(len(live_gold.parse_bars(text)), 1)

    def test_provider_error_and_quota(self):
        with self.assertRaises(live_gold.FeedError) as cm:
            live_gold.parse_bars(json.dumps({"status": "error", "code": 429, "message": "x"}))
        self.assertTrue(cm.exception.quota)
        with self.assertRaises(live_gold.FeedError) as cm:
            live_gold.parse_bars(json.dumps({"status": "error", "code": 404, "message": "x"}))
        self.assertFalse(cm.exception.quota)
        for bad in ("not json", "[]", json.dumps({"status": "ok", "values": []})):
            with self.assertRaises(live_gold.FeedError):
                live_gold.parse_bars(bad)

    def test_network_error_never_leaks_the_key(self):
        def boom(url, timeout=20):
            raise OSError("failed for https://api.twelvedata.com/?apikey=SECRETKEY")
        with self.assertRaises(live_gold.FeedError) as cm:
            live_gold.fetch_bars("SECRETKEY", "XAU/USD", http_get=boom)
        self.assertNotIn("SECRETKEY", str(cm.exception))

    def test_alerts_text(self):
        self.assertEqual(live_gold.parse_alerts("nope"), (None, None))
        self.assertEqual(live_gold.parse_alerts(json.dumps({"v": 2, "rules": []})), (None, None))
        rules, updated = live_gold.parse_alerts(json.dumps({"v": 1, "updated": "u", "rules": [{"a": 1}, 5]}))
        self.assertEqual((rules, updated), ([{"a": 1}], "u"))


class TestLoop(unittest.TestCase):
    def test_no_gold_rule_means_no_provider_call(self):
        r = Run([rule(symbol="EURUSD=X")], [[bar(0, 1, 1, 1, 1)]])
        self.assertEqual(r.go("--once"), 0)
        self.assertEqual((r.calls, r.sent), (0, []))

    def test_missing_rules_file_is_handled(self):
        r = Run(None, [[bar(0, 1, 1, 1, 1)]])
        self.assertEqual(r.go("--once"), 0)
        self.assertEqual(r.calls, 0)

    def test_stop_touch_sends_one_message_with_the_fast_source_label(self):
        bars = [bar(0, 3610, 3612, 3608, 3611), bar(1, 3609, 3610, 3598, 3599)]   # bas 3598 <= 3600
        r = Run([rule("stop", "haussier", 3600.0)], [bars])
        self.assertEqual(r.go("--once"), 0)
        self.assertEqual(len(r.sent), 1)
        self.assertIn("Stop touché", r.sent[0])
        self.assertIn("Twelve Data XAU/USD", r.sent[0])
        self.assertIn("3598", r.sent[0])
        self.assertIsNone(FORBIDDEN.search(r.sent[0]))

    def test_target_of_a_short_is_below(self):
        bars = [bar(0, 3600, 3601, 3590, 3591)]
        r = Run([rule("cible", "baissier", 3592.0)], [bars])
        r.go("--once")
        self.assertEqual(len(r.sent), 1)
        self.assertIn("Cible touchée", r.sent[0])

    def test_no_touch_no_message(self):
        r = Run([rule("stop", "haussier", 3500.0)], [[bar(0, 3600, 3610, 3590, 3605)]])
        r.go("--once")
        self.assertEqual(r.sent, [])

    def test_bars_before_the_rule_was_set_are_ignored(self):
        old = [datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc).timestamp(), 3500, 3500, 3400, 3450]
        r = Run([rule("stop", "haussier", 3600.0)], [[old]])
        r.go("--once")
        self.assertEqual(r.sent, [])

    def test_a_touch_is_sent_once_across_cycles_and_remembered_on_disk(self):
        bars = [bar(0, 3609, 3610, 3598, 3599)]
        r = Run([rule("stop", "haussier", 3600.0)], [bars])
        r.go("--duration", "300", "--interval", "75")
        self.assertEqual(len(r.sent), 1)
        self.assertGreater(r.calls, 1)
        with open(r.state, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["rules_fired"]), 1)
        again = Run([rule("stop", "haussier", 3600.0)], [bars])
        again.state = r.state
        again.go("--once")
        self.assertEqual(again.sent, [])

    def test_failed_telegram_send_is_retried_next_cycle(self):
        bars = [bar(0, 3609, 3610, 3598, 3599)]
        r = Run([rule("stop", "haussier", 3600.0)], [bars], sent_ok=False)
        self.assertEqual(r.go("--duration", "200", "--interval", "75"), 1)
        self.assertGreater(len(r.sent), 1)               # réessayé, pas marqué comme envoyé

    def test_dry_run_sends_and_remembers_nothing(self):
        r = Run([rule("stop", "haussier", 3600.0)], [[bar(0, 3609, 3610, 3598, 3599)]])
        self.assertEqual(r.go("--dry-run", "--once"), 0)
        self.assertEqual(r.sent, [])
        self.assertFalse(os.path.exists(r.state))

    def test_loop_respects_duration_and_interval(self):
        r = Run([rule("stop", "haussier", 3500.0)], [[bar(0, 3600, 3610, 3590, 3605)]])
        r.go("--duration", "300", "--interval", "75")
        self.assertEqual(r.sleeps, [75, 75, 75])
        self.assertEqual(r.calls, 4)

    def test_quota_error_backs_off_five_minutes(self):
        r = Run([rule("stop", "haussier", 3500.0)], [live_gold.FeedError("q", quota=True)])
        r.go("--duration", "1000", "--interval", "75")
        self.assertEqual(r.sleeps[0], live_gold.QUOTA_BACKOFF_S)

    def test_down_notice_after_five_failures_and_only_once(self):
        r = Run([rule("stop", "haussier", 3500.0)], [live_gold.FeedError("x")])
        r.go("--duration", "1000", "--interval", "75")
        notices = [t for t in r.sent if "indisponible" in t]
        self.assertEqual(len(notices), 1)
        self.assertEqual(r.calls, 1000 // 75 + 1)       # un appel à t = 0, puis un par intervalle

    def test_missing_secrets(self):
        r = Run([], [[]])
        deps = r.deps()
        deps["env"] = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
        self.assertEqual(live_gold.main(["--once"], deps), 1)
        deps["env"] = {"TWELVE_DATA_API_KEY": "k"}
        self.assertEqual(live_gold.main(["--once"], deps), 1)
        self.assertEqual(live_gold.main(["--once", "--dry-run"], deps), 0)


class TestMessage(unittest.TestCase):
    def test_default_label_is_unchanged(self):
        hit = {"rule": rule(), "bar_time": SINCE, "extreme": 3598.0, "extreme_kind": "plus bas"}
        self.assertIn("barre 5 min", alert_messages.touch_message(hit))


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        with open(WORKFLOW, encoding="utf-8") as f:
            self.text = f.read()

    def test_hourly_weekday_schedule_and_no_overlap(self):
        self.assertEqual(re.findall(r'^\s*- cron: "([^"]+)"\s*$', self.text, re.M), ["3 7-21 * * 1-5"])
        self.assertRegex(self.text, r"(?m)^concurrency:\n  group: live-gold\n  cancel-in-progress: false$")

    def test_loop_is_shorter_than_the_job_timeout(self):
        self.assertIn("timeout-minutes: 70\n", self.text)
        self.assertLess(live_gold.build_parser().get_default("duration"), 70 * 60)
        self.assertGreaterEqual(live_gold.build_parser().get_default("duration"), 3500)

    def test_secrets_only_through_env_and_never_echoed(self):
        refs = [l for l in self.text.splitlines() if "secrets." in l]
        self.assertEqual(len(refs), 3, refs)
        for line in refs:
            self.assertRegex(line, r"^\s{10}[A-Z_]+: \$\{\{ secrets\.[A-Z_]+ \}\}$")
        self.assertNotIn("echo", self.text)
        self.assertNotIn("set -x", self.text)

    def test_shares_the_alert_state_cache_with_the_15_minute_server(self):
        self.assertEqual(self.text.count("key: alerts-state-${{ github.run_id }}"), 2)
        self.assertIn("restore-keys: alerts-state-\n", self.text)

    def test_daily_call_budget_fits_the_free_quota(self):
        d = live_gold.build_parser()
        per_job = d.get_default("duration") / d.get_default("interval")
        self.assertLess(per_job * 15, 800)            # 15 jobs par jour


if __name__ == "__main__":
    unittest.main()
