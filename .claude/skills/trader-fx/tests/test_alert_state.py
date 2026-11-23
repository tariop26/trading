import _path  # noqa
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import alert_state

TODAY = "2026-11-16"
SENT = "EURUSD=X|haussier|2026-11-16T09:00:00+00:00|3|2026-11-16T09:05:00+00:00|tendance+momentum"


def full_state(**kw):
    state = {"v": 1, "day": TODAY, "ideas_sent": ["EURJPY=X|baissier|2026-11-16"],
             "rules_fired": ["2026-11-16-EURJPY-1-stop"], "events_sent": ["2026-11-16T13:30:00+00:00|USD|CPI"],
             "down_notified_day": TODAY,
             "signals_sent": [SENT], "signals_count": 1, "signals_cap_day": TODAY,
             "guard_sent": ["guard|alerte|2026-11-16"]}
    state.update(kw)
    return state


def old_state(**kw):
    """A state saved before the signal keys existed."""
    state = full_state()
    for k in ("signals_sent", "signals_count", "signals_cap_day", "guard_sent"):
        del state[k]
    state.update(kw)
    return state


def candidate(**kw):
    c = {"symbol": "EURUSD=X", "side": "haussier", "bar_iso": "2026-11-16T09:00:00+00:00",
         "score": 3, "families": ["tendance", "momentum"]}
    c.update(kw)
    return c


NOW = datetime(2026, 11, 16, 9, 5, tzinfo=timezone.utc)


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "alerts_state.json")

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_empty_state_shape(self):
        self.assertEqual(alert_state.empty_state(TODAY),
                         {"v": 1, "day": TODAY, "ideas_sent": [], "rules_fired": [],
                          "events_sent": [], "down_notified_day": None,
                          "signals_sent": [], "signals_count": 0, "signals_cap_day": None,
                          "guard_sent": []})

    def test_missing_corrupt_and_other_version_give_an_empty_state(self):
        empty = alert_state.empty_state(TODAY)
        self.assertEqual(alert_state.load_state(self.path, TODAY), empty)           # missing file
        for text in ("", "{", "[]", "3", '{"v": 2, "day": "2026-11-16"}',
                     json.dumps(full_state(ideas_sent="oops")),                      # wrong type
                     json.dumps(full_state(rules_fired=[1, 2])),                     # wrong item type
                     json.dumps({"v": 1})):                                          # keys missing
            self.write(text)
            self.assertEqual(alert_state.load_state(self.path, TODAY), empty, text)

    def test_undecodable_bytes_give_an_empty_state(self):
        with open(self.path, "wb") as f:
            f.write(b"\xff\xfe\x00bad")
        self.assertEqual(alert_state.load_state(self.path, TODAY), alert_state.empty_state(TODAY))

    def test_same_day_keeps_everything(self):
        self.write(json.dumps(full_state()))
        self.assertEqual(alert_state.load_state(self.path, TODAY), full_state())

    def test_new_day_resets_ideas_and_down_flag_but_keeps_rules_and_events(self):
        self.write(json.dumps(full_state()))
        got = alert_state.load_state(self.path, "2026-11-17")
        self.assertEqual(got, full_state(day="2026-11-17", ideas_sent=[], down_notified_day=None,
                                         signals_sent=[], signals_count=0, signals_cap_day=None,
                                         guard_sent=[]))

    def test_old_state_without_signal_keys_loads_with_defaults(self):
        self.write(json.dumps(old_state()))
        got = alert_state.load_state(self.path, TODAY)
        self.assertEqual(got, full_state(signals_sent=[], signals_count=0, signals_cap_day=None,
                                         guard_sent=[]))

    def test_signal_keys_reset_on_new_day(self):
        self.write(json.dumps(full_state()))
        got = alert_state.load_state(self.path, "2026-11-17")
        self.assertEqual((got["signals_sent"], got["signals_count"], got["signals_cap_day"]), ([], 0, None))

    def test_wrong_type_signal_key_gives_empty_state(self):
        empty = alert_state.empty_state(TODAY)
        for bad in (dict(signals_sent="oops"), dict(signals_sent=[1, 2]), dict(signals_sent=None),
                    dict(signals_count="3"), dict(signals_count=True), dict(signals_count=-1),
                    dict(signals_count=1.5), dict(signals_cap_day=5), dict(signals_cap_day=[])):
            self.write(json.dumps(full_state(**bad)))
            self.assertEqual(alert_state.load_state(self.path, TODAY), empty, bad)

    def test_wrong_type_guard_key_gives_empty_state(self):
        empty = alert_state.empty_state(TODAY)
        for bad in (dict(guard_sent="oops"), dict(guard_sent=[1]), dict(guard_sent=None)):
            self.write(json.dumps(full_state(**bad)))
            self.assertEqual(alert_state.load_state(self.path, TODAY), empty, bad)

    def test_save_then_load_roundtrip(self):
        alert_state.save_state(self.path, full_state())
        self.assertEqual(alert_state.load_state(self.path, TODAY), full_state())
        self.assertEqual([n for n in os.listdir(self.dir)], ["alerts_state.json"])


class TestSignals(unittest.TestCase):
    def test_mark_signal_then_signal_sent_for_bar(self):
        state = alert_state.empty_state(TODAY)
        c = candidate()
        self.assertFalse(alert_state.signal_sent_for_bar(state, c["symbol"], c["side"], c["bar_iso"]))
        alert_state.mark_signal(state, c, NOW)
        self.assertEqual(state["signals_sent"], [SENT])
        self.assertTrue(alert_state.signal_sent_for_bar(state, "EURUSD=X", "haussier", c["bar_iso"]))
        self.assertFalse(alert_state.signal_sent_for_bar(state, "EURUSD=X", "baissier", c["bar_iso"]))
        self.assertFalse(alert_state.signal_sent_for_bar(state, "GBPUSD=X", "haussier", c["bar_iso"]))
        self.assertFalse(alert_state.signal_sent_for_bar(state, "EURUSD=X", "haussier",
                                                         "2026-11-16T09:05:00+00:00"))

    def test_mark_signal_increments_count(self):
        state = alert_state.empty_state(TODAY)
        alert_state.mark_signal(state, candidate(), NOW)
        alert_state.mark_signal(state, candidate(symbol="GBPUSD=X"), NOW)
        self.assertEqual(state["signals_count"], 2)
        self.assertEqual(len(state["signals_sent"]), 2)

    def test_last_signal_inside_and_outside_cooldown(self):
        state = alert_state.empty_state(TODAY)
        alert_state.mark_signal(state, candidate(), NOW)
        later = NOW + timedelta(minutes=30)
        self.assertEqual(alert_state.last_signal(state, "EURUSD=X", "haussier", later, 120),
                         {"score": 3, "families": ["tendance", "momentum"],
                          "sent_iso": "2026-11-16T09:05:00+00:00"})
        self.assertIsNone(alert_state.last_signal(state, "EURUSD=X", "haussier",
                                                  NOW + timedelta(hours=3), 120))
        self.assertIsNone(alert_state.last_signal(state, "EURUSD=X", "baissier", later, 120))
        self.assertIsNone(alert_state.last_signal(state, "GBPUSD=X", "haussier", later, 120))
        self.assertIsNone(alert_state.last_signal(state, "EURUSD=X", "haussier", later, 0))
        self.assertIsNone(alert_state.last_signal(state, "EURUSD=X", "haussier", NOW, 0))

    def test_last_signal_cooldown_boundary(self):
        state = alert_state.empty_state(TODAY)
        alert_state.mark_signal(state, candidate(), NOW)
        self.assertIsNotNone(alert_state.last_signal(state, "EURUSD=X", "haussier",
                                                     NOW + timedelta(minutes=119), 120))
        self.assertIsNone(alert_state.last_signal(state, "EURUSD=X", "haussier",
                                                  NOW + timedelta(minutes=120), 120))

    def test_last_signal_takes_the_latest_send(self):
        state = alert_state.empty_state(TODAY)
        alert_state.mark_signal(state, candidate(score=2, families=["tendance"]), NOW)
        alert_state.mark_signal(state, candidate(score=4, families=[], bar_iso="2026-11-16T10:00:00+00:00"),
                                NOW + timedelta(minutes=60))
        alert_state.mark_signal(state, candidate(score=1), NOW + timedelta(minutes=10))   # older, listed last
        got = alert_state.last_signal(state, "EURUSD=X", "haussier", NOW + timedelta(minutes=90), 120)
        self.assertEqual(got, {"score": 4, "families": [], "sent_iso": "2026-11-16T10:05:00+00:00"})

    def test_last_signal_skips_malformed_entries(self):
        state = alert_state.empty_state(TODAY)
        state["signals_sent"] = ["", "garbage", "EURUSD=X|haussier|b|notint|notadate|x",
                                 "EURUSD=X|haussier|b|3|2026-11-16T09:05:00|x",        # naive time
                                 "EURUSD=X|haussier|b|3", "a|b|c|d|e|f|g"]
        self.assertIsNone(alert_state.last_signal(state, "EURUSD=X", "haussier", NOW, 120))
        alert_state.mark_signal(state, candidate(), NOW)
        got = alert_state.last_signal(state, "EURUSD=X", "haussier", NOW + timedelta(minutes=1), 120)
        self.assertEqual(got["score"], 3)


class TestPrune(unittest.TestCase):
    def test_prune_forgets_rules_that_left_alerts_json_and_past_events(self):
        state = full_state(rules_fired=["a-stop", "b-cible"], events_sent=["e1", "e2"])
        got = alert_state.prune(state, {"b-cible", "c-stop"}, {"e2"})
        self.assertEqual((got["rules_fired"], got["events_sent"]), (["b-cible"], ["e2"]))
        self.assertEqual(got["ideas_sent"], state["ideas_sent"])

    def test_prune_keeps_signal_keys(self):
        state = full_state()
        got = alert_state.prune(state, set(), set())
        for k in ("signals_sent", "signals_count", "signals_cap_day"):
            self.assertEqual(got[k], state[k])
        got["signals_sent"].append("x")
        self.assertEqual(len(state["signals_sent"]), 1)

    def test_prune_does_not_mutate_its_input(self):
        state = full_state(rules_fired=["a-stop"], events_sent=["e1"])
        before = copy.deepcopy(state)
        alert_state.prune(state, set(), set())
        self.assertEqual(state, before)


if __name__ == "__main__":
    unittest.main()
