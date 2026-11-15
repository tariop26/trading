import _path  # noqa
import unittest
from datetime import datetime, timezone

import alert_checks as ck
import alert_state
import data

TODAY = "2026-11-16"
SINCE = "2026-11-16T10:00:00+00:00"


def ts(h, m=0):
    return int(datetime(2026, 11, 16, h, m, tzinfo=timezone.utc).timestamp())


def bar(h, m, low, high):
    """A 5-minute bar starting at h:m UTC whose close sits in the middle of the range."""
    return (ts(h, m), (low + high) / 2, high, low, (low + high) / 2)


def rule(kind="stop", side="haussier", level=1.095, symbol="EURUSD=X", since=SINCE, **kw):
    r = {"id": "T-%s" % kind, "trade_id": "T", "symbol": symbol, "type": kind, "side": side,
         "level": level, "decimals": 5, "since": since}
    r.update(kw)
    return r


def idea(symbol, side, rank, since_close=None):
    return {"rank": rank, "symbol": symbol, "name": symbol, "side": side, "score": 3,
            "setups": ["breakout_20d"], "since_close": since_close}


def briefing(ideas, market_state="open"):
    return {"market_state": market_state, "trade_ideas": {"ideas": ideas}}


def state(**kw):
    s = alert_state.empty_state(TODAY)
    s.update(kw)
    return s


class TestConstants(unittest.TestCase):
    def test_intraday_profile(self):
        self.assertEqual(data.INTRADAY, ("5m", "5d"))


class TestNewIdeas(unittest.TestCase):
    def test_a_new_idea_is_announced(self):
        got, waiting = ck.new_ideas(briefing([idea("AUDUSD=X", "baissier", 1)]), [], state(), TODAY)
        self.assertEqual(([i["symbol"] for i in got], waiting), (["AUDUSD=X"], 0))

    def test_idea_key(self):
        self.assertEqual(ck.idea_key(idea("AUDUSD=X", "baissier", 1), TODAY),
                         "AUDUSD=X|baissier|2026-11-16")

    def test_the_same_idea_is_not_sent_twice_the_same_day(self):
        s = state(ideas_sent=["AUDUSD=X|baissier|2026-11-16"])
        self.assertEqual(ck.new_ideas(briefing([idea("AUDUSD=X", "baissier", 1)]), [], s, TODAY),
                         ([], 0))
        # the opposite side of the same symbol is another idea
        got, _ = ck.new_ideas(briefing([idea("AUDUSD=X", "haussier", 1)]), [], s, TODAY)
        self.assertEqual(len(got), 1)

    def test_an_idea_of_a_trade_already_open_is_skipped(self):
        rules = [rule(symbol="EURJPY=X", side="baissier")]
        got, waiting = ck.new_ideas(briefing([idea("EURJPY=X", "baissier", 1),
                                              idea("EURJPY=X", "haussier", 2)]), rules, state(), TODAY)
        self.assertEqual([(i["symbol"], i["side"]) for i in got], [("EURJPY=X", "haussier")])

    def test_a_void_idea_is_skipped(self):
        stop = {"last": 1.0, "stop_crossed": True, "target_crossed": False}
        reached = {"last": 1.0, "stop_crossed": False, "target_crossed": True}
        fine = {"last": 1.0, "stop_crossed": False, "target_crossed": False}
        got, _ = ck.new_ideas(briefing([idea("A=X", "haussier", 1, stop), idea("B=X", "haussier", 2, reached),
                                        idea("C=X", "haussier", 3, fine)]), [], state(), TODAY)
        self.assertEqual([i["symbol"] for i in got], ["C=X"])

    def test_at_most_three_ideas_per_run_in_rank_order_and_the_rest_wait(self):
        ideas = [idea("S%d=X" % n, "haussier", n) for n in (5, 2, 4, 1, 3)]
        got, waiting = ck.new_ideas(briefing(ideas), [], state(), TODAY)
        self.assertEqual(([i["rank"] for i in got], waiting), ([1, 2, 3], 2))
        got, waiting = ck.new_ideas(briefing(ideas), [], state(), TODAY, limit=1)
        self.assertEqual(([i["rank"] for i in got], waiting), ([1], 4))

    def test_closed_weekend_announces_nothing(self):
        self.assertEqual(ck.new_ideas(briefing([idea("A=X", "haussier", 1)], "closed_weekend"),
                                      [], state(), TODAY), ([], 0))

    def test_odd_documents_do_not_crash(self):
        for doc in ({}, {"trade_ideas": None}, {"trade_ideas": {"ideas": [None, 3, "x"]}}):
            self.assertEqual(ck.new_ideas(doc, [], state(), TODAY), ([], 0))


class TestTouchedRules(unittest.TestCase):
    def hit(self, r, bars, st=None):
        hits, log = ck.touched_rules([r], {r["symbol"]: bars}, st or state(), SINCE)
        return hits, log

    def test_the_four_directions(self):
        quiet = bar(10, 5, 1.099, 1.101)
        cases = (
            (rule("stop", "haussier", 1.095), bar(10, 10, 1.0949, 1.1), "plus bas", 1.0949),
            (rule("stop", "baissier", 1.105), bar(10, 10, 1.1, 1.1051), "plus haut", 1.1051),
            (rule("cible", "haussier", 1.11), bar(10, 10, 1.1, 1.1101), "plus haut", 1.1101),
            (rule("cible", "baissier", 1.09), bar(10, 10, 1.0899, 1.1), "plus bas", 1.0899),
        )
        for r, touching, kind, extreme in cases:
            hits, _ = self.hit(r, [quiet, touching])
            self.assertEqual(len(hits), 1, r)
            self.assertEqual((hits[0]["extreme_kind"], hits[0]["extreme"], hits[0]["rule"]["id"]),
                             (kind, extreme, r["id"]))
            self.assertEqual(hits[0]["bar_time"], "2026-11-16T10:10:00+00:00")
            hits, _ = self.hit(r, [quiet])
            self.assertEqual(hits, [], r)

    def test_a_level_exactly_reached_counts(self):
        hits, _ = self.hit(rule("stop", "haussier", 1.095), [bar(10, 5, 1.095, 1.1)])
        self.assertEqual(len(hits), 1)

    def test_a_bar_at_or_before_since_is_ignored(self):
        touching = lambda h, m: bar(h, m, 1.09, 1.1)
        self.assertEqual(self.hit(rule(), [touching(9, 55), touching(10, 0)])[0], [])
        self.assertEqual(len(self.hit(rule(), [touching(9, 55), touching(10, 0), touching(10, 5)])[0]), 1)

    def test_since_in_the_middle_of_a_bar_ignores_that_bar(self):
        r = rule(since="2026-11-16T10:02:00+00:00")
        self.assertEqual(self.hit(r, [bar(10, 0, 1.09, 1.1)])[0], [])
        hits, _ = self.hit(r, [bar(10, 0, 1.09, 1.1), bar(10, 5, 1.09, 1.1)])
        self.assertEqual(hits[0]["bar_time"], "2026-11-16T10:05:00+00:00")

    def test_a_wick_between_two_runs_is_seen_and_the_first_touching_bar_wins(self):
        bars = [bar(10, 5, 1.099, 1.101), bar(10, 10, 1.0940, 1.1), bar(10, 15, 1.0990, 1.101),
                bar(10, 20, 1.0930, 1.1)]
        hits, _ = self.hit(rule(), bars)
        self.assertEqual((len(hits), hits[0]["bar_time"], hits[0]["extreme"]),
                         (1, "2026-11-16T10:10:00+00:00", 1.094))

    def test_bars_out_of_order_still_give_the_first_touching_bar(self):
        bars = [bar(10, 20, 1.093, 1.1), bar(10, 10, 1.094, 1.1)]
        self.assertEqual(self.hit(rule(), bars)[0][0]["bar_time"], "2026-11-16T10:10:00+00:00")

    def test_a_rule_already_fired_is_ignored(self):
        st = state(rules_fired=[ck.rule_key(rule())])
        self.assertEqual(self.hit(rule(), [bar(10, 5, 1.09, 1.1)], st), ([], []))

    def test_a_level_moved_after_it_fired_is_watched_again(self):
        st = state(rules_fired=[ck.rule_key(rule())])
        touching = [bar(10, 5, 1.09, 1.1), bar(10, 40, 1.09, 1.1)]
        moved_level = rule(level=1.096)                                  # same id, new level
        moved_since = rule(since="2026-11-16T10:30:00+00:00")           # same id, moved later
        for moved in (moved_level, moved_since):
            self.assertNotEqual(ck.rule_key(moved), ck.rule_key(rule()))
            hits, _ = self.hit(moved, touching, st)
            self.assertEqual(len(hits), 1)
        self.assertEqual(ck.rule_key(rule()), ck.rule_key(rule()))

    def test_a_rule_without_a_trade_id_is_skipped_not_fatal(self):
        broken = rule(id="X-stop")
        del broken["trade_id"]
        good = rule("cible", "haussier", 1.11, id="G-cible")
        hits, log = ck.touched_rules([broken, good], {"EURUSD=X": [bar(10, 5, 1.1, 1.12)]}, state(), SINCE)
        self.assertEqual([h["rule"]["id"] for h in hits], ["G-cible"])
        self.assertGreaterEqual(len(log), 1)
        self.assertEqual(ck.upcoming_events([TestEvents().ev(13, 20)], [broken], TestEvents.NOW, state()), [])

    def test_since_after_the_last_bar_gives_no_hit(self):
        r = rule(since="2026-11-16T12:00:00+00:00")
        self.assertEqual(self.hit(r, [bar(10, 5, 1.09, 1.1)]), ([], []))

    def test_missing_or_empty_bars_give_a_log_line_and_no_exception(self):
        hits, log = ck.touched_rules([rule()], {}, state(), SINCE)
        self.assertEqual(hits, [])
        self.assertEqual(len(log), 1)
        self.assertIn("EURUSD=X", log[0])
        hits, log = ck.touched_rules([rule()], {"EURUSD=X": []}, state(), SINCE)
        self.assertEqual((hits, len(log)), ([], 1))

    def test_a_malformed_rule_is_skipped_and_the_others_are_processed(self):
        bad = [rule(level="abc"), rule(since="not a date"), rule(since="2026-11-16T10:00:00"),
               rule(kind="weird"), rule(side="sideways"), {"id": "x"}, None, 3,
               rule(level=True)]
        good = rule("cible", "haussier", 1.11, id="G-cible")
        hits, log = ck.touched_rules(bad + [good], {"EURUSD=X": [bar(10, 5, 1.1, 1.12)]}, state(), SINCE)
        self.assertEqual([h["rule"]["id"] for h in hits], ["G-cible"])
        self.assertGreaterEqual(len(log), 1)

    def test_a_missing_since_falls_back(self):
        r = rule()
        del r["since"]
        hits, _ = ck.touched_rules([r], {"EURUSD=X": [bar(10, 0, 1.09, 1.1), bar(10, 5, 1.09, 1.1)]},
                                   state(), "2026-11-16T10:02:00+00:00")
        self.assertEqual(hits[0]["bar_time"], "2026-11-16T10:05:00+00:00")

    def test_bars_with_missing_values_are_skipped(self):
        bars = [(ts(10, 5), None, None, None, None), (ts(10, 10), 1.1, 1.1, None, 1.1),
                bar(10, 15, 1.09, 1.1)]
        self.assertEqual(self.hit(rule(), bars)[0][0]["bar_time"], "2026-11-16T10:15:00+00:00")

    def test_stop_and_target_of_the_same_trade_give_two_hits(self):
        rules = [rule("stop", "haussier", 1.095), rule("cible", "haussier", 1.11)]
        bars = {"EURUSD=X": [bar(10, 5, 1.094, 1.111)]}
        hits, _ = ck.touched_rules(rules, bars, state(), SINCE)
        self.assertEqual([h["rule"]["type"] for h in hits], ["stop", "cible"])


class TestEvents(unittest.TestCase):
    NOW = datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc)

    def ev(self, h, m, currency="USD", impact="High", title="Core CPI m/m"):
        utc = datetime(2026, 11, 16, h, m, tzinfo=timezone.utc).isoformat()
        return {"utc": utc, "currency": currency, "title": title, "impact": impact,
                "time_paris": "%02d:%02d" % (h + 1, m)}

    def up(self, events, rules, st=None):
        return ck.upcoming_events(events, rules, self.NOW, st or state())

    def test_trade_currencies(self):
        self.assertEqual(ck.trade_currencies("EURJPY=X"), {"EUR", "JPY"})
        self.assertEqual(ck.trade_currencies("^FCHI"), {"USD"})
        self.assertEqual(ck.trade_currencies("GC=F"), {"USD"})

    def test_event_key(self):
        e = self.ev(13, 30)
        self.assertEqual(ck.event_key(e), "2026-11-16T13:30:00+00:00|USD|Core CPI m/m")

    def test_the_window_runs_from_now_to_30_minutes_so_a_late_or_dropped_run_loses_nothing(self):
        rules = [rule()]
        for (h, m), expected in (((12, 59), 0), ((13, 0), 0), ((13, 1), 1), ((13, 14), 1),
                                 ((13, 15), 1), ((13, 30), 1), ((13, 31), 0)):
            self.assertEqual(len(self.up([self.ev(h, m)], rules)), expected, (h, m))
        soon = self.ev(13, 0)
        soon["utc"] = "2026-11-16T13:00:30+00:00"                      # 30 seconds ahead
        self.assertEqual(self.up([soon], rules)[0]["minutes"], 1)       # never "dans 0 min"
        item = self.up([self.ev(13, 25)], rules)[0]
        self.assertEqual((item["minutes"], item["symbols"], item["event"]["title"]),
                         (25, ["EURUSD=X"], "Core CPI m/m"))

    def test_only_high_impact_events(self):
        self.assertEqual(self.up([self.ev(13, 20, impact="Medium")], [rule()]), [])

    def test_only_currencies_of_the_open_trades_and_a_jpy_event_concerns_eurjpy(self):
        self.assertEqual(self.up([self.ev(13, 20, currency="GBP")], [rule()]), [])
        item = self.up([self.ev(13, 20, currency="JPY")], [rule(symbol="EURJPY=X"), rule(symbol="EURUSD=X")])[0]
        self.assertEqual(item["symbols"], ["EURJPY=X"])

    def test_no_open_trade_means_no_announcement(self):
        self.assertEqual(self.up([self.ev(13, 20)], []), [])

    def test_a_key_already_sent_is_not_sent_again(self):
        e = self.ev(13, 20)
        self.assertEqual(self.up([e], [rule()], state(events_sent=[ck.event_key(e)])), [])

    def test_a_non_forex_instrument_is_concerned_by_usd_only(self):
        r = rule(symbol="^FCHI")
        self.assertEqual(len(self.up([self.ev(13, 20, currency="USD")], [r])), 1)
        self.assertEqual(self.up([self.ev(13, 20, currency="EUR")], [r]), [])

    def test_a_malformed_event_or_rule_is_skipped(self):
        events = [None, {"utc": "nope", "impact": "High", "currency": "USD", "title": "x"},
                  {"impact": "High"}, self.ev(13, 20)]
        self.assertEqual(len(self.up(events, [None, {"id": "x"}, rule()])), 1)


if __name__ == "__main__":
    unittest.main()
