import _path  # noqa
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone

import journal
from test_jstats import sample_journal

NOW = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b")
IDEA = {"rank": 4, "symbol": "EURJPY=X", "name": "EUR/JPY", "side": "baissier", "score": 4,
        "setups": ["breakdown_20d"], "reference_price": 176.659, "stop": 178.408,
        "target": 173.161, "rr": 2.0, "decimals": 3, "last_bar_date": "2026-11-13",
        "atr": 1.0, "why": ["x"], "since_close": None,
        "size": {"status": "ok", "lots": 0.45, "units": 45000, "risk_usd": 480.75}}


class CliCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.jpath = os.path.join(self.dir, "journal.json")
        self.bpath = os.path.join(self.dir, "briefing.json")
        self.outputs = []
        self.rate_calls = []

    def run_cli(self, *args, rate=159.875, now=NOW, journal_arg=True, extra_deps=None):
        argv = list(args)
        if journal_arg:
            argv += ["--journal", self.jpath]
        deps = {"now": lambda: now,
                "fetch_rate": lambda sym: (self.rate_calls.append(sym), rate)[1]}
        deps.update(extra_deps or {})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = journal.main(argv, deps)
        text = out.getvalue()
        self.outputs.append(text)
        return code, text

    def write_briefing(self, ideas):
        with open(self.bpath, "w", encoding="utf-8") as f:
            json.dump({"as_of": {"iso": "2026-11-14T07:50:00+00:00"},
                       "trade_ideas": {"ideas": ideas}}, f)

    def stored(self):
        return journal.load_journal(self.jpath)

    def bytes_of(self, path):
        with open(path, "rb") as f:
            return f.read()

    def assertOneLine(self, text):
        self.assertEqual(len(text.strip().splitlines()), 1, text)


class TestOpen(CliCase):
    def open_eurjpy(self, *extra, **kw):
        return self.run_cli("open", "--symbol", "EURJPY=X", "--side", "baissier", "--price", "176.70",
                            "--lots", "0.45", "--briefing", self.bpath, *extra, **kw)

    def test_open_from_briefing_idea_attaches_it(self):
        self.write_briefing([IDEA])
        code, text = self.open_eurjpy()
        self.assertEqual(code, 0)
        t = self.stored()["trades"][0]
        self.assertEqual((t["source"], t["stop"], t["target"], t["risk_usd"]),
                         ("idee", 178.408, 173.161, 480.75))
        self.assertEqual((t["idea"]["rank"], t["idea"]["last_bar_date"], t["idea"]["decimals"]),
                         (4, "2026-11-13", 3))
        self.assertEqual(t["idea"]["as_of"], "2026-11-14T07:50:00+00:00")
        self.assertEqual(self.rate_calls, ["USDJPY=X"])             # exactly one conversion request
        self.assertIn("2026-11-16-EURJPY-1", text)
        self.assertIn("480.75", text)

    def test_open_when_side_differs_is_off_plan_and_needs_a_stop(self):
        self.write_briefing([IDEA])
        code, text = self.run_cli("open", "--symbol", "EURJPY=X", "--side", "haussier",
                                  "--price", "176.70", "--lots", "0.45", "--briefing", self.bpath)
        self.assertEqual(code, 1)
        self.assertOneLine(text)
        self.assertFalse(os.path.exists(self.jpath))
        code, _ = self.run_cli("open", "--symbol", "EURJPY=X", "--side", "haussier", "--price", "176.70",
                               "--lots", "0.45", "--stop", "175.5", "--briefing", self.bpath)
        self.assertEqual(code, 0)
        self.assertEqual(self.stored()["trades"][0]["source"], "hors_plan")

    def test_open_without_a_briefing_file_is_off_plan(self):
        code, text = self.run_cli("open", "--symbol", "eurusd=x", "--side", "haussier", "--price", "1.10",
                                  "--lots", "1", "--stop", "1.095", "--briefing", self.bpath)
        self.assertEqual(code, 0, text)
        t = self.stored()["trades"][0]
        self.assertEqual((t["symbol"], t["source"], t["risk_usd"], t["name"]),
                         ("EURUSD=X", "hors_plan", 500.0, "EUR/USD"))
        self.assertEqual(self.rate_calls, [])                    # a USD-quoted pair needs no rate

    def test_open_cross_with_no_rate_warns_and_keeps_the_risk_unknown(self):
        code, text = self.open_eurjpy("--stop", "178.4", rate=None)
        self.assertEqual(code, 0)
        self.assertOneLine(text)
        self.assertIn("risque prévu inconnu", text)
        self.assertIsNone(self.stored()["trades"][0]["risk_usd"])

    def test_open_cross_uses_the_quote_usd_rate(self):
        code, _ = self.open_eurjpy("--stop", "178.408", "--quote-usd-rate", "0.00625")
        self.assertEqual(code, 0)
        self.assertEqual(self.rate_calls, [])                    # the given rate replaces the request
        self.assertEqual(self.stored()["trades"][0]["risk_usd"], 480.38)   # 76860 * 0.00625 = 480.375

    def test_open_explicit_risk_usd_needs_no_rate(self):
        code, _ = self.open_eurjpy("--stop", "178.4", "--risk-usd", "300")
        self.assertEqual(code, 0)
        self.assertEqual(self.rate_calls, [])
        self.assertEqual(self.stored()["trades"][0]["risk_usd"], 300.0)

    def test_time_is_paris_and_stored_in_utc(self):
        self.run_cli("open", "--symbol", "EURUSD=X", "--side", "haussier", "--price", "1.1", "--lots", "1",
                     "--stop", "1.095", "--time", "2026-11-16 09:30", "--briefing", self.bpath)
        self.run_cli("open", "--symbol", "EURUSD=X", "--side", "haussier", "--price", "1.1", "--lots", "1",
                     "--stop", "1.095", "--time", "2026-07-16 09:30", "--briefing", self.bpath)
        times = [t["entry"]["time"] for t in self.stored()["trades"]]
        self.assertEqual(times, ["2026-11-16T08:30:00+00:00", "2026-07-16T07:30:00+00:00"])

    def test_default_time_is_now(self):
        self.run_cli("open", "--symbol", "EURUSD=X", "--side", "haussier", "--price", "1.1", "--lots", "1",
                     "--stop", "1.095", "--briefing", self.bpath)
        self.assertEqual(self.stored()["trades"][0]["entry"]["time"], "2026-11-16T10:00:00+00:00")

    def test_bad_time_and_missing_arguments_are_one_line(self):
        for args in (["open", "--symbol", "EURUSD=X", "--side", "haussier", "--price", "1.1", "--lots", "1",
                      "--stop", "1.095", "--time", "demain"],
                     ["open", "--side", "haussier"],
                     ["open", "--symbol", "EURUSD=X", "--side", "haussier", "--price", "abc", "--lots", "1"],
                     ["inconnu"], []):
            code, text = self.run_cli(*args)
            self.assertEqual(code, 1, args)
            self.assertOneLine(text)
        self.assertFalse(os.path.exists(self.jpath))


class TestAmendClose(CliCase):
    def open_eurusd(self):
        self.run_cli("open", "--symbol", "EURUSD=X", "--side", "haussier", "--price", "1.1000",
                     "--lots", "1", "--stop", "1.0950", "--target", "1.1100", "--briefing", self.bpath)
        return self.stored()["trades"][0]["id"]

    def test_amend_then_close_keeps_the_initial_risk(self):
        tid = self.open_eurusd()
        code, text = self.run_cli("amend", tid, "--stop", "1.0900")
        self.assertEqual(code, 0, text)
        self.assertIn("stop_deplace", text)
        code, text = self.run_cli("close", tid, "--price", "1.0900", "--reason", "stop",
                                  "--quote-usd-rate", "1")
        self.assertEqual(code, 0, text)
        t = self.stored()["trades"][0]
        self.assertEqual((t["result"]["pnl_usd"], t["result"]["r"], t["initial_stop"], t["stop"]),
                         (-1000.0, -2.0, 1.095, 1.09))
        self.assertIn("estimé, hors frais", text)
        self.assertIn("R -2.00", text)

    def test_close_with_the_broker_result(self):
        tid = self.open_eurusd()
        code, text = self.run_cli("close", tid, "--price", "1.105", "--pnl", "498.2",
                                  "--tags", "entree_tardive, hors_plan", "--note", "ok")
        self.assertEqual(code, 0, text)
        t = self.stored()["trades"][0]
        self.assertEqual((t["result"]["source"], t["tags"], t["note"]),
                         ("courtier", ["entree_tardive", "hors_plan"], "ok"))
        self.assertIn("courtier", text)
        self.assertNotIn("estimé", text)

    def test_close_a_cross_estimates_with_a_fetched_rate(self):
        self.write_briefing([IDEA])
        self.run_cli("open", "--symbol", "EURJPY=X", "--side", "baissier", "--price", "176.70",
                     "--lots", "0.45", "--briefing", self.bpath)
        tid = self.stored()["trades"][0]["id"]
        code, text = self.run_cli("close", tid, "--price", "175.10")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.stored()["trades"][0]["result"],
                         {"pnl_usd": 450.35, "r": 0.94, "source": "estime"})
        self.assertIn("R +0.94", text)
        self.assertEqual(self.rate_calls, ["USDJPY=X", "USDJPY=X"])      # one request per command

    def test_close_without_rate_or_pnl_is_a_one_line_error_and_the_file_is_untouched(self):
        self.write_briefing([IDEA])
        self.run_cli("open", "--symbol", "EURJPY=X", "--side", "baissier", "--price", "176.70",
                     "--lots", "0.45", "--briefing", self.bpath)
        tid = self.stored()["trades"][0]["id"]
        before = self.bytes_of(self.jpath)
        code, text = self.run_cli("close", tid, "--price", "175.10", rate=None)
        self.assertEqual(code, 1)
        self.assertOneLine(text)
        self.assertIn("--pnl", text)
        self.assertEqual(self.bytes_of(self.jpath), before)

    def test_unknown_or_closed_trade(self):
        tid = self.open_eurusd()
        for args in (["close", "nope", "--price", "1.1", "--pnl", "1"],
                     ["amend", "nope", "--stop", "1.09"]):
            code, text = self.run_cli(*args)
            self.assertEqual(code, 1)
            self.assertOneLine(text)
        self.run_cli("close", tid, "--price", "1.105", "--pnl", "500")
        code, text = self.run_cli("close", tid, "--price", "1.105", "--pnl", "500")
        self.assertEqual(code, 1)
        self.assertOneLine(text)


class TestCorruptJournal(CliCase):
    def test_a_bad_journal_is_a_one_line_error_and_stays_untouched(self):
        for content in (b'{"v": 1, "trades": [', b'{"v": 9, "trades": []}', b"[1, 2]"):
            with open(self.jpath, "wb") as f:
                f.write(content)
            before = self.bytes_of(self.jpath)
            for args in (["open", "--symbol", "EURUSD=X", "--side", "haussier", "--price", "1.1",
                          "--lots", "1", "--stop", "1.095", "--briefing", self.bpath],
                         ["list"], ["stats"], ["alerts", "--out", os.path.join(self.dir, "a.json")]):
                code, text = self.run_cli(*args)
                self.assertEqual(code, 1, args)
                self.assertOneLine(text)
            self.assertEqual(self.bytes_of(self.jpath), before)


class TestListStatsAlerts(CliCase):
    def seed(self):
        journal.save_journal(self.jpath, sample_journal())

    def test_list_open_and_closed(self):
        self.seed()
        code, text = self.run_cli("list")
        self.assertEqual((code, len(text.strip().splitlines())), (0, 9))
        code, text = self.run_cli("list", "--open")
        self.assertEqual(len(text.strip().splitlines()), 1)
        code, text = self.run_cli("list", "--closed")
        self.assertEqual(len(text.strip().splitlines()), 8)

    def test_stats_text(self):
        self.seed()
        code, text = self.run_cli("stats")
        self.assertEqual(code, 0)
        self.assertIn("Journal : 8 trades clôturés, 1 ouverts", text)
        self.assertIn("échantillon trop petit pour conclure", text)
        self.assertIn("n=8", text)
        self.assertIn("900.35 USD", text)
        for heading in ("Par règle", "Par sens", "Par paire", "Par session", "Par jour", "Erreurs",
                        "Capital"):
            self.assertIn(heading, text)
        self.assertIn("breakdown_20d : n=2", text)

    def test_stats_json_is_the_full_stats_object(self):
        self.seed()
        code, text = self.run_cli("stats", "--json")
        doc = json.loads(text)
        self.assertEqual((doc["n_closed"], doc["overall"]["pnl_usd"], doc["equity"]["cap_pct"]),
                         (8, 900.35, 2.0))

    def test_stats_on_an_empty_journal(self):
        code, text = self.run_cli("stats")
        self.assertEqual(code, 0)
        self.assertIn("Journal : 0 trades clôturés, 0 ouverts", text)
        self.assertIn("Aucun trade clôturé", text)

    def test_alerts_only_for_open_trades_and_nothing_financial(self):
        j = journal.empty_journal()
        t1 = journal.open_trade(j, symbol="EURUSD=X", name="EUR/USD", side="haussier", price=1.1,
                                lots=1.0, stop=1.095, target=1.11, when_utc=NOW,
                                prices={"EURUSD=X": 1.1})
        t2 = journal.open_trade(j, symbol="USDJPY=X", name="USD/JPY", side="baissier", price=150.0,
                                lots=0.5, stop=151.0, when_utc=NOW)            # no target
        t3 = journal.open_trade(j, symbol="EURUSD=X", name="EUR/USD", side="haussier", price=1.1,
                                lots=1.0, stop=1.095, target=1.11, when_utc=NOW, risk_usd=500.0)
        journal.close_trade(j, t3["id"], price=1.105, when_utc=NOW, pnl_usd=500.0)
        journal.save_journal(self.jpath, j)
        out = os.path.join(self.dir, "alerts.json")
        code, text = self.run_cli("alerts", "--out", out)
        self.assertEqual(code, 0, text)
        raw = self.bytes_of(out).decode("utf-8")
        doc = json.loads(raw)
        self.assertEqual(set(doc), {"v", "updated", "rules"})
        self.assertEqual(doc["updated"], "2026-11-16T10:00:00+00:00")
        self.assertEqual([r["id"] for r in doc["rules"]],
                         [t1["id"] + "-stop", t1["id"] + "-cible", t2["id"] + "-stop"])
        for rule in doc["rules"]:
            self.assertEqual(set(rule), {"id", "trade_id", "symbol", "type", "side", "level", "decimals"})
        self.assertEqual((doc["rules"][0]["level"], doc["rules"][0]["decimals"],
                          doc["rules"][2]["decimals"]), (1.095, 5, 3))
        for word in ("pnl", "risk", "capital", "lots", "units", "result", "note"):
            self.assertNotIn(word, raw)
        self.assertIn("3 règle(s)", text)

    def test_alerts_with_no_open_trade_writes_an_empty_rule_list(self):
        out = os.path.join(self.dir, "alerts.json")
        code, _ = self.run_cli("alerts", "--out", out)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.bytes_of(out))["rules"], [])


class TestConfigAndPaths(CliCase):
    def test_config_error_is_one_line(self):
        cfg = os.path.join(self.dir, "config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"risk": {"per_trade": 1}}, f)
        code, text = self.run_cli("stats", "--config", cfg)
        self.assertEqual(code, 1)
        self.assertOneLine(text)
        code, text = self.run_cli("stats", "--config", os.path.join(self.dir, "absent.json"))
        self.assertEqual(code, 1)
        self.assertOneLine(text)

    def test_config_capital_feeds_the_equity_curve(self):
        journal.save_journal(self.jpath, sample_journal())
        cfg = os.path.join(self.dir, "config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"account": {"capital": 50000}, "risk": {"max_total_pct": 3}}, f)
        code, text = self.run_cli("stats", "--config", cfg, "--json")
        doc = json.loads(text)
        self.assertEqual((doc["equity"]["start"], doc["equity"]["cap_pct"]), (50000.0, 3.0))

    def test_contract_table_from_the_config(self):
        cfg = os.path.join(self.dir, "config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"contracts": {"^FCHI": {"usd_per_point": 1.1, "step": 0.1, "min": 0.1}}}, f)
        code, text = self.run_cli("open", "--symbol", "^FCHI", "--side", "haussier", "--price", "8000",
                                  "--size", "4.5", "--stop", "7900", "--config", cfg,
                                  "--briefing", self.bpath)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.stored()["trades"][0]["risk_usd"], 495.0)

    def test_default_paths_are_relative_to_the_working_directory(self):
        old = os.getcwd()
        os.chdir(self.dir)
        try:
            code, _ = self.run_cli("open", "--symbol", "EURUSD=X", "--side", "haussier", "--price", "1.1",
                                   "--lots", "1", "--stop", "1.095", journal_arg=False)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(os.path.join(self.dir, "trader", "fx", "journal.json")))
        finally:
            os.chdir(old)


class TestVocabulary(CliCase):
    def test_the_filter_works_and_no_output_uses_forbidden_words(self):
        self.assertTrue(FORBIDDEN.search("un achat"))
        self.assertTrue(FORBIDDEN.search("Sell the rip"))
        self.assertFalse(FORBIDDEN.search("survente"))
        self.assertFalse(FORBIDDEN.search("surachat"))
        self.write_briefing([IDEA])
        self.run_cli("open", "--symbol", "EURJPY=X", "--side", "baissier", "--price", "176.70",
                     "--lots", "0.45", "--briefing", self.bpath)
        tid = self.stored()["trades"][0]["id"]
        self.run_cli("amend", tid, "--stop", "179")
        self.run_cli("close", tid, "--price", "175.10", "--tags", "stop_deplace")
        self.run_cli("list")
        self.run_cli("stats")
        self.run_cli("alerts", "--out", os.path.join(self.dir, "a.json"))
        self.run_cli("close", "nope", "--price", "1", "--pnl", "1")
        self.assertGreater(len(self.outputs), 5)
        for text in self.outputs:
            self.assertIsNone(FORBIDDEN.search(text), text)

    def test_no_backspace_characters_in_the_test_files(self):
        here = os.path.dirname(os.path.abspath(__file__))
        for name in ("test_journal.py", "test_journal_cli.py", "test_jstats.py", "test_entry_session.py"):
            with open(os.path.join(here, name), "rb") as f:
                self.assertEqual(f.read().count(bytes([8])), 0, name)


if __name__ == "__main__":
    unittest.main()
