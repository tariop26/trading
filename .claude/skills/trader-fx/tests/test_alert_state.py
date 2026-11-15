import _path  # noqa
import copy
import json
import os
import tempfile
import unittest

import alert_state

TODAY = "2026-11-16"


def full_state(**kw):
    state = {"v": 1, "day": TODAY, "ideas_sent": ["EURJPY=X|baissier|2026-11-16"],
             "rules_fired": ["2026-11-16-EURJPY-1-stop"], "events_sent": ["2026-11-16T13:30:00+00:00|USD|CPI"],
             "down_notified_day": TODAY}
    state.update(kw)
    return state


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
                          "events_sent": [], "down_notified_day": None})

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
        self.assertEqual(got, full_state(day="2026-11-17", ideas_sent=[], down_notified_day=None))

    def test_save_then_load_roundtrip(self):
        alert_state.save_state(self.path, full_state())
        self.assertEqual(alert_state.load_state(self.path, TODAY), full_state())
        self.assertEqual([n for n in os.listdir(self.dir)], ["alerts_state.json"])


class TestPrune(unittest.TestCase):
    def test_prune_forgets_rules_that_left_alerts_json_and_past_events(self):
        state = full_state(rules_fired=["a-stop", "b-cible"], events_sent=["e1", "e2"])
        got = alert_state.prune(state, {"b-cible", "c-stop"}, {"e2"})
        self.assertEqual((got["rules_fired"], got["events_sent"]), (["b-cible"], ["e2"]))
        self.assertEqual(got["ideas_sent"], state["ideas_sent"])

    def test_prune_does_not_mutate_its_input(self):
        state = full_state(rules_fired=["a-stop"], events_sent=["e1"])
        before = copy.deepcopy(state)
        alert_state.prune(state, set(), set())
        self.assertEqual(state, before)


if __name__ == "__main__":
    unittest.main()
