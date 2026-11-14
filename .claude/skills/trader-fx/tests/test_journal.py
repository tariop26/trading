import _path  # noqa
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import journal

T0 = datetime(2026, 11, 16, 8, 30, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)
RATES = {"USDJPY=X": 159.875}
IDEA = {"as_of": {"iso": "2026-11-14T07:50:00+00:00"}, "rank": 4, "score": 4,
        "setups": ["breakdown_20d"], "reference_price": 176.659, "stop": 178.408,
        "target": 173.161, "rr": 2.0, "last_bar_date": "2026-11-13", "decimals": 3,
        "size": {"status": "ok", "lots": 0.45, "units": 45000}}
FCHI = {"^FCHI": {"usd_per_point": 1.1, "step": 0.1, "min": 0.1}}


def eurjpy(j, **kw):
    args = dict(symbol="EURJPY=X", name="EUR/JPY", side="baissier", price=176.70, lots=0.45,
                when_utc=T0, idea=IDEA, prices=RATES)
    args.update(kw)
    return journal.open_trade(j, **args)


def eurusd(j, **kw):
    args = dict(symbol="EURUSD=X", name="EUR/USD", side="haussier", price=1.1000, lots=1.0,
                stop=1.0950, target=1.1100, when_utc=T0, prices={"EURUSD=X": 1.10})
    args.update(kw)
    return journal.open_trade(j, **args)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "sub", "journal.json")

    def write(self, data, mode="w"):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if "b" in mode:
            with open(self.path, mode) as f:
                f.write(data)
        else:
            with open(self.path, mode, encoding="utf-8") as f:
                f.write(data)

    def test_load_missing_gives_empty(self):
        self.assertEqual(journal.load_journal(self.path), {"v": 1, "trades": []})

    def test_load_rejects_bad_files_with_one_line(self):
        for text in ("{", "[]", "42", '{"v": 2, "trades": []}', '{"v": 1, "trades": {}}',
                     '{"trades": []}', ""):
            self.write(text)
            with self.assertRaises(journal.JournalError) as cm:
                journal.load_journal(self.path)
            msg = str(cm.exception)
            self.assertNotIn("\n", msg)
            self.assertTrue(msg.endswith("."), msg)

    def test_load_rejects_undecodable_bytes_and_a_directory(self):
        self.write(b"\xff\xfe\x00bad", mode="wb")
        with self.assertRaises(journal.JournalError):
            journal.load_journal(self.path)
        with self.assertRaises(journal.JournalError):
            journal.load_journal(self.dir)

    def test_load_tolerates_a_bom(self):
        self.write("﻿" + json.dumps(journal.empty_journal()))
        self.assertEqual(journal.load_journal(self.path)["trades"], [])

    def test_save_is_atomic_and_keeps_a_backup(self):
        j1 = journal.empty_journal()
        journal.save_journal(self.path, j1)
        self.assertFalse(os.path.exists(self.path + ".bak"))
        j2 = journal.empty_journal()
        eurusd(j2)
        journal.save_journal(self.path, j2)
        with open(self.path + ".bak", encoding="utf-8") as f:
            self.assertEqual(json.load(f), j1)
        self.assertEqual(journal.load_journal(self.path), j2)

    def test_failed_save_keeps_the_old_file_and_leaves_no_temp(self):
        j1 = journal.empty_journal()
        journal.save_journal(self.path, j1)
        with open(self.path, "rb") as f:
            before = f.read()
        j2 = journal.empty_journal()
        eurusd(j2)
        with mock.patch.object(journal.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(journal.JournalError) as cm:
                journal.save_journal(self.path, j2)
        self.assertNotIn("\n", str(cm.exception))
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), before)
        leftovers = [n for n in os.listdir(os.path.dirname(self.path))
                     if n not in ("journal.json", "journal.json.bak")]
        self.assertEqual(leftovers, [])


class TestIds(unittest.TestCase):
    def test_new_trade_id_increments_per_day_and_symbol(self):
        j = journal.empty_journal()
        self.assertEqual(eurjpy(j)["id"], "2026-11-16-EURJPY-1")
        self.assertEqual(eurjpy(j)["id"], "2026-11-16-EURJPY-2")
        self.assertEqual(eurusd(j)["id"], "2026-11-16-EURUSD-1")
        later = datetime(2026, 11, 17, 7, 0, tzinfo=timezone.utc)
        self.assertEqual(eurjpy(j, when_utc=later)["id"], "2026-11-17-EURJPY-1")

    def test_an_id_is_never_reused_after_a_trade_is_deleted_by_hand(self):
        j = journal.empty_journal()
        first, second = eurjpy(j), eurjpy(j)
        del j["trades"][0]                       # the only way to remove a mistaken entry
        third = eurjpy(j)
        self.assertEqual((first["id"], second["id"], third["id"]),
                         ("2026-11-16-EURJPY-1", "2026-11-16-EURJPY-2", "2026-11-16-EURJPY-3"))
        self.assertEqual(len({t["id"] for t in j["trades"]}), len(j["trades"]))

    def test_id_numbering_ignores_a_lookalike_prefix(self):
        j = journal.empty_journal()
        eurusd(j)
        j["trades"].append({"id": "2026-11-16-EURUSD-1x", "status": "closed"})
        j["trades"].append({"id": "2026-11-16-EURUSD-abc", "status": "closed"})
        self.assertEqual(eurusd(j)["id"], "2026-11-16-EURUSD-2")

    def test_id_of_non_forex_symbols_is_sanitised(self):
        j = journal.empty_journal()
        t = journal.open_trade(j, symbol="GC=F", name="Or", side="haussier", price=3000.0,
                               size=1.0, stop=2950.0, when_utc=T0, risk_usd=100.0)
        self.assertEqual(t["id"], "2026-11-16-GC_F-1")

    def test_find_trade_unknown_is_an_error(self):
        with self.assertRaises(journal.JournalError):
            journal.find_trade(journal.empty_journal(), "nope")


class TestOpen(unittest.TestCase):
    def test_open_from_idea(self):
        j = journal.empty_journal()
        t = eurjpy(j)
        self.assertEqual(j["trades"], [t])
        self.assertEqual((t["status"], t["source"], t["side"]), ("open", "idee", "baissier"))
        self.assertEqual(t["entry"], {"time": "2026-11-16T08:30:00+00:00", "price": 176.70,
                                      "lots": 0.45, "units": 45000, "size": None})
        self.assertEqual((t["stop"], t["target"]), (178.408, 173.161))
        self.assertEqual((t["initial_stop"], t["initial_target"]), (178.408, 173.161))
        # 45000 * 1.708 / 159.875 = 480.75
        self.assertEqual(t["risk_usd"], 480.75)
        self.assertEqual(t["idea"]["rank"], 4)
        self.assertIsNot(t["idea"], IDEA)               # a copy
        self.assertEqual((t["exit"], t["result"], t["tags"], t["note"]), (None, None, [], ""))
        self.assertEqual([h["event"] for h in t["history"]], ["ouverture"])

    def test_explicit_levels_override_the_idea(self):
        t = eurjpy(journal.empty_journal(), stop=178.0, target=174.0)
        self.assertEqual((t["stop"], t["target"], t["source"]), (178.0, 174.0, "idee"))

    def test_off_plan_needs_a_stop(self):
        with self.assertRaises(journal.JournalError):
            eurusd(journal.empty_journal(), stop=None)
        t = eurusd(journal.empty_journal())
        self.assertEqual((t["source"], t["idea"], t["risk_usd"]), ("hors_plan", None, 500.0))

    def test_non_forex_uses_size_and_the_contract_table(self):
        t = journal.open_trade(journal.empty_journal(), symbol="^FCHI", name="CAC 40",
                               side="haussier", price=8000, size=4.5, stop=7900, target=8200,
                               when_utc=T0, contracts=FCHI)
        self.assertEqual((t["entry"]["size"], t["entry"]["lots"], t["entry"]["units"]),
                         (4.5, None, None))
        self.assertEqual(t["risk_usd"], 495.0)

    def test_validations(self):
        j = journal.empty_journal()
        bad = [dict(stop=1.1050),                    # haussier stop above the price
               dict(target=1.0900),                  # haussier target below the price
               dict(side="baissier", stop=1.0950, target=1.0900),   # baissier stop below
               dict(side="baissier", stop=1.1050, target=1.1100),   # baissier target above
               dict(lots=0), dict(lots=-1), dict(lots=None),
               dict(lots=None, size=2.0),            # a forex pair is entered in lots
               dict(side="sideways"), dict(price="abc"), dict(price=-1.0),
               dict(stop=-5.0), dict(symbol="")]
        for kw in bad:
            with self.assertRaises(journal.JournalError, msg=str(kw)) as cm:
                eurusd(j, **kw)
            self.assertNotIn("\n", str(cm.exception))
        self.assertEqual(j["trades"], [])             # nothing half-written
        with self.assertRaises(journal.JournalError):
            journal.open_trade(j, symbol="^FCHI", name="CAC", side="haussier", price=8000,
                               lots=1.0, stop=7900, when_utc=T0)   # lots on a non-forex
        with self.assertRaises(ValueError):
            eurusd(j, when_utc=datetime(2026, 11, 16, 8, 30))      # naive time

    def test_unknown_risk_is_none_and_r_stays_none(self):
        j = journal.empty_journal()
        t = journal.open_trade(j, symbol="GBPZAR=X", name="GBP/ZAR", side="haussier", price=22.0,
                               lots=0.1, stop=21.8, when_utc=T0)
        self.assertIsNone(t["risk_usd"])
        journal.close_trade(j, t["id"], price=22.4, when_utc=T1, pnl_usd=90.0)
        self.assertIsNone(t["result"]["r"])
        self.assertEqual((t["result"]["pnl_usd"], t["result"]["source"]), (90.0, "courtier"))

    def test_explicit_risk_usd_is_kept(self):
        t = journal.open_trade(journal.empty_journal(), symbol="GBPZAR=X", name="x",
                               side="haussier", price=22.0, lots=0.1, stop=21.8,
                               when_utc=T0, risk_usd=120.0)
        self.assertEqual(t["risk_usd"], 120.0)


class TestAmend(unittest.TestCase):
    def test_stop_farther_is_tagged_and_keeps_the_initial_risk(self):
        j = journal.empty_journal()
        t = eurusd(j)
        journal.amend_trade(j, t["id"], when_utc=T1, stop=1.0900)
        self.assertEqual((t["stop"], t["initial_stop"], t["risk_usd"]), (1.0900, 1.0950, 500.0))
        self.assertIn("stop_deplace", t["tags"])
        self.assertEqual(t["history"][-1]["event"], "stop_deplace")

    def test_stop_closer_or_trailing_is_not_tagged(self):
        j = journal.empty_journal()
        t = eurusd(j)
        journal.amend_trade(j, t["id"], when_utc=T1, stop=1.0980)      # closer
        journal.amend_trade(j, t["id"], when_utc=T1, stop=1.1020)      # trailing, above the entry
        self.assertEqual(t["stop"], 1.1020)
        self.assertEqual(t["tags"], [])
        self.assertEqual(t["risk_usd"], 500.0)

    def test_baissier_stop_farther_means_higher(self):
        j = journal.empty_journal()
        t = eurjpy(j)
        journal.amend_trade(j, t["id"], when_utc=T1, stop=179.0)
        self.assertIn("stop_deplace", t["tags"])

    def test_target_move_is_logged_and_validated(self):
        j = journal.empty_journal()
        t = eurusd(j)
        journal.amend_trade(j, t["id"], when_utc=T1, target=1.1200)
        self.assertEqual((t["target"], t["initial_target"]), (1.1200, 1.1100))
        self.assertEqual(t["history"][-1]["event"], "cible_deplacee")
        with self.assertRaises(journal.JournalError):
            journal.amend_trade(j, t["id"], when_utc=T1, stop=1.1300)     # stop above the target
        with self.assertRaises(journal.JournalError):
            journal.amend_trade(j, t["id"], when_utc=T1, target=1.0900)   # target on the loss side

    def test_amend_errors(self):
        j = journal.empty_journal()
        t = eurusd(j)
        with self.assertRaises(journal.JournalError):
            journal.amend_trade(j, t["id"], when_utc=T1)                   # nothing to change
        with self.assertRaises(journal.JournalError):
            journal.amend_trade(j, "nope", when_utc=T1, stop=1.09)
        journal.close_trade(j, t["id"], price=1.1050, when_utc=T1, pnl_usd=500.0)
        with self.assertRaises(journal.JournalError):
            journal.amend_trade(j, t["id"], when_utc=T1, stop=1.09)        # already closed


class TestClose(unittest.TestCase):
    def test_close_with_broker_pnl_and_estimated(self):
        j = journal.empty_journal()
        t = eurjpy(j)
        journal.close_trade(j, t["id"], price=175.10, when_utc=T1, pnl_usd=450.35, reason="cible",
                            tags=["entree_tardive"], note="ok")
        self.assertEqual(t["status"], "closed")
        self.assertEqual(t["result"], {"pnl_usd": 450.35, "r": 0.94, "source": "courtier"})
        self.assertEqual(t["exit"], {"time": "2026-11-16T14:00:00+00:00", "price": 175.10,
                                     "reason": "cible"})
        self.assertEqual((t["tags"], t["note"]), (["entree_tardive"], "ok"))
        self.assertEqual(t["history"][-1]["event"], "cloture")
        j2 = journal.empty_journal()
        t2 = eurjpy(j2)
        journal.close_trade(j2, t2["id"], price=175.10, when_utc=T1, prices=RATES)
        self.assertEqual(t2["result"], {"pnl_usd": 450.35, "r": 0.94, "source": "estime"})

    def test_close_without_rate_or_pnl_is_an_error_and_the_trade_stays_open(self):
        j = journal.empty_journal()
        t = eurjpy(j)
        snapshot = copy.deepcopy(j)
        with self.assertRaises(journal.JournalError) as cm:
            journal.close_trade(j, t["id"], price=175.10, when_utc=T1)       # no rates
        self.assertIn("--pnl", str(cm.exception))
        self.assertNotIn("\n", str(cm.exception))
        self.assertEqual(j, snapshot)

    def test_close_exactly_at_the_stop_gives_minus_one_r(self):
        j = journal.empty_journal()
        t = eurjpy(j)
        journal.close_trade(j, t["id"], price=178.408, when_utc=T1, prices=RATES, reason="stop")
        self.assertEqual(t["result"]["pnl_usd"], -480.75)
        self.assertEqual(t["result"]["r"], -1.0)

    def test_close_exactly_at_the_entry_gives_zero(self):
        j = journal.empty_journal()
        t = eurjpy(j)
        journal.close_trade(j, t["id"], price=176.70, when_utc=T1, prices=RATES)
        self.assertEqual((t["result"]["pnl_usd"], t["result"]["r"]), (0.0, 0.0))

    def test_close_uses_the_initial_risk_after_a_stop_move(self):
        j = journal.empty_journal()
        t = eurusd(j)
        journal.amend_trade(j, t["id"], when_utc=T1, stop=1.0900)
        journal.close_trade(j, t["id"], price=1.0900, when_utc=T1, prices={"EURUSD=X": 1.09},
                            reason="stop")
        self.assertEqual(t["result"]["pnl_usd"], -1000.0)
        self.assertEqual(t["result"]["r"], -2.0)             # 1000 / the initial 500, not / 1000

    def test_close_validations(self):
        j = journal.empty_journal()
        t = eurusd(j)
        for kw in (dict(price=-1.0), dict(price="x"), dict(reason="boom"),
                   dict(when_utc=datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc)),
                   dict(pnl_usd="abc"), dict(pnl_usd=True)):
            args = dict(price=1.1050, when_utc=T1, pnl_usd=500.0)
            args.update(kw)
            with self.assertRaises(journal.JournalError, msg=str(kw)):
                journal.close_trade(j, t["id"], **args)
        self.assertEqual(t["status"], "open")
        journal.close_trade(j, t["id"], price=1.1050, when_utc=T1, pnl_usd=500.0)
        with self.assertRaises(journal.JournalError):
            journal.close_trade(j, t["id"], price=1.1050, when_utc=T1, pnl_usd=500.0)  # twice

    def test_tags_merge_without_duplicates(self):
        j = journal.empty_journal()
        t = eurusd(j)
        journal.amend_trade(j, t["id"], when_utc=T1, stop=1.0900)
        journal.close_trade(j, t["id"], price=1.1050, when_utc=T1, pnl_usd=400.0,
                            tags=["stop_deplace", "hors_plan"])
        self.assertEqual(t["tags"], ["stop_deplace", "hors_plan"])

    def test_history_events_in_order(self):
        j = journal.empty_journal()
        t = eurusd(j)
        journal.amend_trade(j, t["id"], when_utc=T1, stop=1.0900, target=1.1200)
        journal.close_trade(j, t["id"], price=1.1050, when_utc=T1, pnl_usd=500.0)
        self.assertEqual([h["event"] for h in t["history"]],
                         ["ouverture", "stop_deplace", "cible_deplacee", "cloture"])


if __name__ == "__main__":
    unittest.main()
