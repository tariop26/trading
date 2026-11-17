import _path  # noqa
import re
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import alert_state
import config as cfgmod
import intraday_plan
import intraday_run
from intraday_helpers import make_bars, utc

EUR, GBP, FCHI, GOLD = "EURUSD=X", "GBPUSD=X", "^FCHI", "GC=F"
NOW = utc(2026, 11, 16, 8, 45)            # a Monday, the 08:30 bar has just closed
TODAY = "2026-11-16"
FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell|prévision|gagnant|profit)\b")
ACCOUNT = {"capital": 100000, "risk_per_trade_usd": 500.0, "source": "file"}


def london_break(scale=1.0, long_=True):
    """A Londres range (08:00-08:30) then a close outside it on the 08:30 bar."""
    if long_:
        ohlc = [(1.1000, 1.1010, 1.0990, 1.1005), (1.1005, 1.1010, 1.0995, 1.1000),
                (1.1005, 1.1025, 1.1000, 1.1020)]
    else:
        ohlc = [(1.1000, 1.1010, 1.0990, 1.0995), (1.0995, 1.1005, 1.0990, 1.1000),
                (1.0995, 1.1000, 1.0975, 1.0980)]
    return make_bars(utc(2026, 11, 16, 8, 0),
                     [tuple(round(x * scale, 5) for x in row) for row in ohlc])


def ctx(last=1.10, name="Euro / Dollar", trend="up", atr_pct=0.6):
    return {"name": name, "last": last, "atr_pct": atr_pct, "trend": trend}


def document(contexts=None, account=ACCOUNT):
    return {"market_state": "open",
            "trade_ideas": {"account": account, "ideas": []},
            "daily_context": {EUR: ctx()} if contexts is None else contexts}


class Fetch:
    """A fake fetch_bars: {symbol: bars}; `fail` symbols come back as failures."""

    def __init__(self, bars=None, fail=()):
        self.bars = {EUR: london_break()} if bars is None else bars
        self.fail = list(fail)
        self.calls = []

    def __call__(self, symbols, interval, rng, **kw):
        self.calls.append((list(symbols), interval, rng, kw))
        series = {s: SimpleNamespace(bars=self.bars[s]) for s in symbols
                  if s in self.bars and s not in self.fail}
        failed = [{"symbol": s, "reason": "HTTP 404"} for s in symbols if s in self.fail]
        return series, failed


def no_events():
    raise AssertionError("get_events must not be called")


def rule(symbol=EUR, side="haussier", kind="stop"):
    return {"id": "T-%s" % kind, "trade_id": "T", "symbol": symbol, "type": kind,
            "side": side, "level": 1.095, "decimals": 5, "since": "2026-11-16T07:00:00+00:00"}


def event(currency="EUR", minutes=20, impact="High"):
    start = datetime.fromtimestamp(NOW.timestamp() + minutes * 60, timezone.utc)
    return {"utc": start.isoformat(), "currency": currency, "title": "CPI", "impact": impact,
            "time_paris": "10:05"}


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.config = cfgmod.defaults()
        self.state = alert_state.empty_state(TODAY)
        self.fetch = Fetch()

    def collect(self, doc=None, events=lambda: [], rules=(), now=NOW, fetch=None, state=None):
        return intraday_run.collect(now, document() if doc is None else doc, events,
                                    list(rules), self.state if state is None else state,
                                    self.config, fetch or self.fetch)

    def test_collect_returns_message_and_mark_updates_state(self):
        items, log = self.collect()
        self.assertEqual(len(items), 1)
        text, mark = items[0]
        self.assertIn("Euro / Dollar haussier", text)
        self.assertIn("session_break (Londres)", text)
        self.assertIsNone(FORBIDDEN.search(text))
        self.assertEqual(self.state["signals_count"], 0)         # nothing marked before sending
        mark(self.state)
        self.assertEqual(self.state["signals_count"], 1)
        self.assertTrue(alert_state.signal_sent_for_bar(
            self.state, EUR, "haussier", "2026-11-16T08:30:00+00:00"))
        self.assertTrue(all(isinstance(line, str) for line in log))
        # the 15-minute bars are asked without cache, for the symbols of the context
        symbols, interval, rng, kw = self.fetch.calls[0]
        self.assertEqual((symbols, interval, rng), ([EUR], "15m", "5d"))
        self.assertEqual((kw["cache_dir"], kw["ttl_s"], kw["use_cache"], kw["workers"]),
                         (None, 0, False, 3))
        # marked: the same bar gives nothing the next time
        items, _ = self.collect()
        self.assertEqual(items, [])

    def test_no_bars_call_when_daily_context_is_missing(self):
        for doc in ({"trade_ideas": {}}, {"daily_context": {}}, {"daily_context": None},
                    {"daily_context": []}):
            items, log = self.collect(doc)
            self.assertEqual(items, [])
            self.assertEqual(log, ["contexte journalier absent : signaux en séance sautés."])
        self.assertEqual(self.fetch.calls, [])

    def test_skipped_on_closed_weekend(self):
        saturday = utc(2026, 11, 14, 10, 0)
        items, log = self.collect(now=saturday)
        self.assertEqual((items, log), ([], ["signaux en séance : marché fermé (week-end)."]))
        self.assertEqual(self.fetch.calls, [])

    def test_skipped_when_document_is_none_with_log_line(self):
        items, log = intraday_run.collect(NOW, None, no_events, [], self.state, self.config,
                                          self.fetch)
        self.assertEqual((items, log),
                         ([], ["briefing indisponible : signaux en séance sautés."]))
        self.assertEqual(self.fetch.calls, [])

    def test_disabled_returns_nothing(self):
        self.config["intraday"]["enabled"] = False
        self.assertEqual(self.collect(), ([], []))
        self.assertEqual(self.fetch.calls, [])

    def test_open_trade_same_symbol_and_side_is_skipped(self):
        self.assertEqual(len(self.collect()[0]), 1)              # premise: it alerts
        items, _ = self.collect(rules=[rule(EUR, "haussier")])
        self.assertEqual(items, [])
        # an open trade on the other side does not hold this one
        items, _ = self.collect(rules=[rule(EUR, "baissier")])
        self.assertEqual(len(items), 1)

    def test_news_within_30_minutes_blocks_the_symbol(self):
        items, _ = self.collect(events=lambda: [event("EUR", 20)])
        self.assertEqual(items, [])
        items, _ = self.collect(events=lambda: [event("USD", 20)])
        self.assertEqual(items, [])
        # out of the window, other currency, or not high impact: no block
        for ev in (event("EUR", 45), event("JPY", 20), event("EUR", 20, impact="Low")):
            items, _ = self.collect(events=lambda ev=ev: [ev])
            self.assertEqual(len(items), 1, ev)

    def test_events_called_once_and_only_with_candidates(self):
        calls = []

        def get_events():
            calls.append(1)
            return []
        self.config["intraday"]["symbols"] = []
        doc = document({EUR: ctx(), GBP: ctx(1.27, "Livre / Dollar")})
        fetch = Fetch({EUR: london_break(), GBP: london_break(1.27 / 1.10)})
        items, _ = self.collect(doc, events=get_events, fetch=fetch)
        self.assertEqual(len(items), 2)
        self.assertEqual(len(calls), 1)

    def test_events_not_requested_when_no_candidate(self):
        # no signal at all
        flat = make_bars(utc(2026, 11, 16, 8, 0), [(1.1, 1.1, 1.1, 1.1)] * 3)
        items, _ = self.collect(events=no_events, fetch=Fetch({EUR: flat}))
        self.assertEqual(items, [])
        # a candidate removed by an open trade
        items, _ = self.collect(events=no_events, rules=[rule(EUR, "haussier")])
        self.assertEqual(items, [])
        # no series at all
        items, _ = self.collect(events=no_events, fetch=Fetch({}))
        self.assertEqual(items, [])

    def test_symbol_failure_is_logged_not_fatal(self):
        doc = document({EUR: ctx(), GBP: ctx(1.27, "Livre / Dollar")})
        fetch = Fetch({EUR: london_break(), GBP: london_break(1.27 / 1.10)}, fail=[GBP])
        items, log = self.collect(doc, fetch=fetch)
        self.assertEqual(len(items), 1)
        self.assertIn("Euro / Dollar", items[0][0])
        failure = [line for line in log if GBP in line]
        self.assertEqual(len(failure), 1)
        self.assertIn("1", failure[0])

    def test_failure_log_names_at_most_five_symbols(self):
        names = ["S%d=X" % n for n in range(8)]
        doc = document({n: ctx() for n in names})
        items, log = self.collect(doc, fetch=Fetch({}, fail=names))
        self.assertEqual(items, [])
        line = [x for x in log if "S0=X" in x][0]
        self.assertIn("8", line)
        self.assertIn("S4=X", line)
        self.assertNotIn("S5=X", line)

    def test_unexpected_exception_on_a_symbol_logs_only_the_type(self):
        doc = document({EUR: ctx(), GBP: ctx(1.27, "Livre / Dollar")})
        fetch = Fetch({EUR: london_break(), GBP: london_break(1.27 / 1.10)})
        real = intraday_plan.scan_symbol

        def scan(symbol, *args, **kw):
            if symbol == GBP:
                raise ValueError("secret-detail-42")
            return real(symbol, *args, **kw)
        with mock.patch.object(intraday_plan, "scan_symbol", side_effect=scan):
            items, log = self.collect(doc, fetch=fetch)
        self.assertEqual(len(items), 1)
        self.assertIn("Euro / Dollar", items[0][0])
        joined = "\n".join(log)
        self.assertIn("ValueError", joined)
        self.assertIn(GBP, joined)
        self.assertNotIn("secret-detail-42", joined)

    def test_stale_index_series_gives_no_alert(self):
        scale = 7500 / 1.10
        doc = document({FCHI: ctx(7500.0, "CAC 40", atr_pct=1.0)})
        fetch = Fetch({FCHI: london_break(scale)})
        items, _ = self.collect(doc, fetch=fetch)                # premise: fresh, it alerts
        self.assertEqual(len(items), 1)
        three_hours_later = utc(2026, 11, 16, 11, 45)
        last = fetch.bars[FCHI][-1][0]
        self.assertEqual(three_hours_later.timestamp() - (last + 900), 3 * 3600 - 0)
        items, log = self.collect(doc, fetch=fetch, now=three_hours_later)
        self.assertEqual(items, [])

    def test_cap_message_once_per_day(self):
        self.state["signals_count"] = 10
        items, _ = self.collect()
        self.assertEqual(len(items), 1)
        text, mark = items[0]
        self.assertIn("Plafond de 10 alertes", text)
        self.assertIsNone(self.state["signals_cap_day"])
        mark(self.state)
        self.assertEqual(self.state["signals_cap_day"], TODAY)
        self.assertEqual(self.state["signals_count"], 10)
        items, _ = self.collect()
        self.assertEqual(items, [])

    def test_cap_message_comes_after_the_alerts(self):
        self.state["signals_count"] = 9
        doc = document({EUR: ctx(), GBP: ctx(1.27, "Livre / Dollar")})
        fetch = Fetch({EUR: london_break(), GBP: london_break(1.27 / 1.10)})
        items, _ = self.collect(doc, fetch=fetch)
        self.assertEqual(len(items), 2)
        self.assertIn("Signal en séance", items[0][0])
        self.assertIn("Plafond", items[1][0])

    def test_per_run_cap_alone_does_not_send_the_cap_message(self):
        self.config["intraday"]["max_per_run"] = 1
        doc = document({EUR: ctx(), GBP: ctx(1.27, "Livre / Dollar")})
        fetch = Fetch({EUR: london_break(), GBP: london_break(1.27 / 1.10)})
        items, _ = self.collect(doc, fetch=fetch)
        self.assertEqual(len(items), 1)
        self.assertNotIn("Plafond", items[0][0])

    def test_symbols_filter_from_config(self):
        doc = document({EUR: ctx(), GBP: ctx(1.27, "Livre / Dollar")})
        fetch = Fetch({EUR: london_break(), GBP: london_break(1.27 / 1.10)})
        self.config["intraday"]["symbols"] = [GBP]
        items, _ = self.collect(doc, fetch=fetch)
        self.assertEqual(fetch.calls[0][0], [GBP])
        self.assertEqual(len(items), 1)
        self.assertIn("Livre / Dollar", items[0][0])
        # empty list: every symbol of the context, in context order
        self.config["intraday"]["symbols"] = []
        fetch = Fetch({EUR: london_break(), GBP: london_break(1.27 / 1.10)})
        self.collect(doc, fetch=fetch)
        self.assertEqual(fetch.calls[0][0], [EUR, GBP])

    def test_gold_without_contract_still_alerts_with_size_to_confirm(self):
        self.assertNotIn(GOLD, self.config["contracts"])
        doc = document({GOLD: ctx(2650.0, "Or", atr_pct=1.2)})
        fetch = Fetch({GOLD: london_break(2650.0 / 1.10)})
        items, _ = self.collect(doc, fetch=fetch)
        self.assertEqual(len(items), 1)
        self.assertIn("Taille à confirmer chez le courtier.", items[0][0])

    def test_refusal_reasons_are_summarised_in_one_line(self):
        flat = make_bars(utc(2026, 11, 16, 8, 0), [(1.1, 1.1, 1.1, 1.1)] * 3)
        doc = document({EUR: ctx(), GBP: ctx(1.27, "Livre / Dollar"), "USDJPY=X": ctx(150.0)})
        fetch = Fetch({EUR: london_break(), GBP: london_break(1.27 / 1.10, long_=False),
                       "USDJPY=X": flat})
        # a plan the ATR forbids: GBP stop wider than the daily ATR
        doc["daily_context"][GBP]["atr_pct"] = 0.0001
        items, log = self.collect(doc, fetch=fetch)
        self.assertEqual(len(items), 1)
        summary = [line for line in log if "candidat" in line]
        self.assertEqual(len(summary), 1)
        self.assertIn("1 candidat", summary[0])
        self.assertIn("stop trop large", summary[0])
        self.assertNotIn("aucun signal récent", summary[0])


if __name__ == "__main__":
    unittest.main()
