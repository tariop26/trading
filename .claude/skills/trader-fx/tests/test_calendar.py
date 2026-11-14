import _path  # noqa
import io
import json
import os
import unittest
import urllib.error
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import economic_calendar as cal

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(title="CPI m/m", country="USD", date="2026-11-10T08:30:00-05:00",
        impact="High", **kw):
    d = {"title": title, "country": country, "date": date, "impact": impact}
    d.update(kw)
    return d


def http_error(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b""))


class Net:
    """Scripted http_get keyed by URL: value is a str (returned) or an Exception."""

    def __init__(self, by_url):
        self.by_url = by_url
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        item = self.by_url[url]
        if isinstance(item, Exception):
            raise item
        return item


THIS = json.dumps([raw(forecast="0.3%", previous="0.6%")])


class ParseTest(unittest.TestCase):
    def test_parse_events_converts_times(self):
        ev = cal.parse_events([raw(forecast="0.3%", previous="0.6%")])[0]
        self.assertEqual(ev["time_ny"], "08:30")
        self.assertEqual(ev["time_paris"], "14:30")
        self.assertEqual(ev["utc"], "2026-11-10T13:30:00+00:00")
        self.assertEqual(ev["currency"], "USD")
        self.assertEqual(ev["title"], "CPI m/m")
        self.assertEqual(ev["impact"], "High")
        self.assertEqual(ev["forecast"], "0.3%")
        self.assertEqual(ev["previous"], "0.6%")

    def test_parse_handles_dst_gap_between_paris_and_new_york(self):
        # 2026-03-09: New York already on EDT, Paris still on CET (gap is 5 h).
        ev = cal.parse_events([raw(date="2026-03-09T08:30:00-04:00")])[0]
        self.assertEqual(ev["time_ny"], "08:30")
        self.assertEqual(ev["time_paris"], "13:30")

    def test_parse_real_fixture_has_high_impact_events(self):
        with open(os.path.join(FIX, "calendar_thisweek.json"), encoding="utf-8") as f:
            doc = json.load(f)
        events = cal.parse_events(doc)
        self.assertEqual(len(events), len(doc))
        high = [e for e in events if e["impact"] == "High"]
        self.assertGreater(len(high), 0)
        for e in events:
            self.assertRegex(e["time_paris"], r"^\d\d:\d\d$")
            self.assertRegex(e["time_ny"], r"^\d\d:\d\d$")
            self.assertIsInstance(e["forecast"], str)
            self.assertIsInstance(e["previous"], str)

    def test_empty_forecast_is_empty_string(self):
        ev = cal.parse_events([raw(), raw(forecast=None, previous=None),
                               raw(forecast="", previous="")])
        for e in ev:
            self.assertEqual(e["forecast"], "")
            self.assertEqual(e["previous"], "")

    def test_malformed_entries_are_skipped_not_fatal(self):
        doc = [raw(), {"title": "no date", "country": "USD"}, raw(date="garbage"),
               raw(date="2026-11-10T08:30:00"), "oops", None, raw(country=None)]
        events = cal.parse_events(doc)
        self.assertEqual(len(events), 1)

    def test_parse_non_list_gives_empty(self):
        self.assertEqual(cal.parse_events({"a": 1}), [])
        self.assertEqual(cal.parse_events(None), [])


class FilterTest(unittest.TestCase):
    def setUp(self):
        self.events = cal.parse_events([
            raw(title="usd high", country="USD"),
            raw(title="all high", country="All"),
            raw(title="cny high", country="CNY"),
            raw(title="eur medium", country="EUR", impact="Medium"),
            raw(title="eur high", country="EUR"),
            raw(title="usd holiday", country="USD", impact="Holiday"),
            raw(title="gbp high empty forecast", country="GBP"),
        ])

    def test_filter_drops_all_country_and_unfocused_currency_and_medium(self):
        out = cal.filter_events(self.events, {"USD", "EUR", "GBP"})
        self.assertEqual([e["title"] for e in out],
                         ["usd high", "eur high", "gbp high empty forecast"])
        # the kept event with no forecast is displayed, not crashed on
        self.assertEqual(out[-1]["forecast"], "")

    def test_all_country_dropped_even_if_all_in_currencies(self):
        out = cal.filter_events(self.events, {"All", "USD"})
        self.assertNotIn("all high", [e["title"] for e in out])

    def test_filter_can_include_medium(self):
        out = cal.filter_events(self.events, {"EUR"}, impacts=("High", "Medium"))
        self.assertEqual([e["title"] for e in out], ["eur medium", "eur high"])

    def test_filter_empty_currencies_gives_nothing(self):
        self.assertEqual(cal.filter_events(self.events, set()), [])


class WithinHoursTest(unittest.TestCase):
    def test_within_hours_window_boundaries(self):
        start = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        events = cal.parse_events([
            raw(title="before", date="2026-11-10T06:59:59-05:00"),   # 11:59:59Z
            raw(title="at start", date="2026-11-10T07:00:00-05:00"),  # 12:00Z
            raw(title="inside", date="2026-11-11T06:59:59-05:00"),    # 11:59:59Z +1d
            raw(title="at end", date="2026-11-11T07:00:00-05:00"),    # 12:00Z +1d
        ])
        out = cal.within_hours(events, start, 24)
        self.assertEqual([e["title"] for e in out], ["at start", "inside"])

    def test_within_hours_custom_hours(self):
        start = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        events = cal.parse_events([raw(title="a", date="2026-11-10T08:00:00-05:00"),
                                   raw(title="b", date="2026-11-10T12:00:00-05:00")])
        out = cal.within_hours(events, start, 2)
        self.assertEqual([e["title"] for e in out], ["a"])

    def test_within_hours_accepts_non_utc_start(self):
        start = datetime(2026, 11, 10, 7, 0, tzinfo=ZoneInfo("America/New_York"))
        events = cal.parse_events([raw(title="a", date="2026-11-10T08:30:00-05:00")])
        self.assertEqual(len(cal.within_hours(events, start, 24)), 1)


class FetchTest(unittest.TestCase):
    def test_fetch_both_ok(self):
        net = Net({cal.URL_THIS: THIS, cal.URL_NEXT: THIS})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["events"]), 2)
        self.assertEqual(net.urls, [cal.URL_THIS, cal.URL_NEXT])

    def test_fetch_next_week_404_gives_partial(self):
        net = Net({cal.URL_THIS: THIS, cal.URL_NEXT: http_error(404)})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["status"], "partial")
        self.assertEqual(len(r["events"]), 1)

    def test_fetch_next_week_other_failure_gives_partial(self):
        net = Net({cal.URL_THIS: THIS, cal.URL_NEXT: OSError("boom")})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["status"], "partial")
        self.assertEqual(len(r["events"]), 1)

    def test_fetch_this_week_failure_gives_unavailable(self):
        for err in (http_error(500), http_error(404), OSError("down"),
                    TimeoutError("slow")):
            net = Net({cal.URL_THIS: err, cal.URL_NEXT: THIS})
            r = cal.fetch_calendar(http_get=net)
            self.assertEqual(r["status"], "unavailable")
            self.assertEqual(r["events"], [])

    def test_fetch_this_week_bad_json_gives_unavailable(self):
        for body in ("<html>nope</html>", "{}", "", "null"):
            net = Net({cal.URL_THIS: body, cal.URL_NEXT: THIS})
            r = cal.fetch_calendar(http_get=net)
            self.assertEqual(r["status"], "unavailable", body)
            self.assertEqual(r["events"], [])

    def test_fetch_this_week_empty_list_gives_unavailable_with_reason(self):
        net = Net({cal.URL_THIS: "[]", cal.URL_NEXT: THIS})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["events"], [])
        self.assertTrue(r["reason"])
        self.assertIn("this week", r["reason"])

    def test_fetch_this_week_all_malformed_gives_unavailable(self):
        body = json.dumps([{"title": "x", "country": "USD"},
                           raw(date="2026-11-10T08:30:00"), {"foo": 1}])
        net = Net({cal.URL_THIS: body, cal.URL_NEXT: THIS})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["events"], [])
        self.assertIn("parsed to 0 events", r["reason"])

    def test_fetch_this_week_dict_body_gives_unavailable(self):
        net = Net({cal.URL_THIS: json.dumps({"events": []}), cal.URL_NEXT: THIS})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["status"], "unavailable")
        self.assertTrue(r["reason"])

    def test_fetch_this_week_http_error_reason(self):
        net = Net({cal.URL_THIS: http_error(500), cal.URL_NEXT: THIS})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["reason"], "this week: HTTP 500")

    def test_fetch_reason_is_none_when_ok(self):
        net = Net({cal.URL_THIS: THIS, cal.URL_NEXT: THIS})
        self.assertIsNone(cal.fetch_calendar(http_get=net)["reason"])

    def test_fetch_next_week_404_reason_mentions_next_week_and_code(self):
        net = Net({cal.URL_THIS: THIS, cal.URL_NEXT: http_error(404)})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["status"], "partial")
        self.assertIn("next week", r["reason"])
        self.assertIn("404", r["reason"])

    def test_fetch_next_week_empty_list_gives_partial(self):
        net = Net({cal.URL_THIS: THIS, cal.URL_NEXT: "[]"})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["status"], "partial")
        self.assertEqual(len(r["events"]), 1)
        self.assertIn("next week", r["reason"])

    def test_fetch_next_week_all_malformed_gives_partial(self):
        net = Net({cal.URL_THIS: THIS, cal.URL_NEXT: json.dumps([{"foo": 1}])})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual(r["status"], "partial")
        self.assertIn("parsed to 0 events", r["reason"])

    def test_fetch_events_sorted_by_time(self):
        later = json.dumps([raw(title="later", date="2026-11-17T08:30:00-05:00")])
        earlier = json.dumps([raw(title="earlier", date="2026-11-10T08:30:00-05:00")])
        net = Net({cal.URL_THIS: earlier, cal.URL_NEXT: later})
        r = cal.fetch_calendar(http_get=net)
        self.assertEqual([e["title"] for e in r["events"]], ["earlier", "later"])


class FocusTest(unittest.TestCase):
    def test_focus_currencies_includes_usd_and_pair_codes(self):
        self.assertEqual(cal.focus_currencies(["EURGBP=X", "USDJPY=X"]),
                         {"USD", "EUR", "GBP", "JPY"})
        self.assertEqual(cal.focus_currencies(["AUDNZD=X"]), {"USD", "AUD", "NZD"})

    def test_focus_currencies_ignores_non_forex_symbols(self):
        self.assertEqual(cal.focus_currencies(["GC=F", "^FCHI", "EURUSD=X", "BAD=X"]),
                         {"USD", "EUR"})

    def test_focus_currencies_empty(self):
        self.assertEqual(cal.focus_currencies([]), {"USD"})


if __name__ == "__main__":
    unittest.main()
