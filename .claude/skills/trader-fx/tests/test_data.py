import _path  # noqa
import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error

import data

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def chart_json(rows, gmtoffset=0):
    """rows: list of (ts, o, h, l, c) where any price may be None."""
    return json.dumps({"chart": {"error": None, "result": [{
        "meta": {"gmtoffset": gmtoffset},
        "timestamp": [r[0] for r in rows],
        "indicators": {"quote": [{
            "open": [r[1] for r in rows], "high": [r[2] for r in rows],
            "low": [r[3] for r in rows], "close": [r[4] for r in rows]}]}}]}})


ROWS = [(1000 + i * 86400, 1.0 + i, 2.0 + i, 0.5 + i, 1.5 + i) for i in range(3)]
GOOD = chart_json(ROWS, 3600)
NO_DATA = json.dumps({"chart": {"result": None, "error": {
    "code": "Not Found", "description": "No data found, symbol may be delisted"}}})


def http_error(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b""))


class Net:
    """Scripted http_get: each item is a str (returned) or an Exception (raised).
    The last item repeats once the script is exhausted."""

    def __init__(self, *script):
        self.script = list(script)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


class Sleeps:
    def __init__(self):
        self.calls = []

    def __call__(self, s):
        self.calls.append(s)


def cache_file(d, name="EURUSD_X_1d_6mo.json"):
    return os.path.join(d, name)


def write_cache(d, fetched_at, bars=None, name="EURUSD_X_1d_6mo.json"):
    bars = bars if bars is not None else [list(r) for r in ROWS]
    with open(cache_file(d, name), "w") as f:
        json.dump({"fetched_at": fetched_at, "gmtoffset": 7200, "bars": bars}, f)


class ParseChartTests(unittest.TestCase):
    def test_parse_chart_drops_bars_with_null_prices(self):
        rows = [(1, 1.0, 2.0, 0.5, 1.5), (2, 1.1, 2.1, 0.6, None),
                (3, None, 2.2, 0.7, 1.7), (4, 1.3, 2.3, 0.8, 1.8)]
        s = data.parse_chart(chart_json(rows, 3600), "EURUSD=X")
        self.assertEqual([b[0] for b in s.bars], [1, 4])
        self.assertEqual(s.gmtoffset, 3600)
        self.assertIsNone(s.age_s)

    def test_parse_chart_no_data_raises(self):
        with self.assertRaises(data.DataError) as cm:
            data.parse_chart(NO_DATA, "XXX=X")
        self.assertTrue(str(cm.exception).startswith("no data"))

    def test_parse_chart_all_null_raises(self):
        with self.assertRaises(data.DataError):
            data.parse_chart(chart_json([(1, None, None, None, None)]), "X")

    def test_parse_chart_garbage_raises(self):
        for text in ("", "<html>", "[]", '{"chart": 3}'):
            with self.assertRaises(data.DataError):
                data.parse_chart(text, "X")

    def test_parse_chart_real_fixtures(self):
        for name in ("eurusd_1d", "eurusd_1h", "gc_1d", "fchi_1d"):
            with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as f:
                s = data.parse_chart(f.read(), name)
            self.assertGreater(len(s.bars), 60, name)
            for b in s.bars:
                self.assertGreaterEqual(b[2], b[3], name)
            ts = [b[0] for b in s.bars]
            self.assertEqual(ts, sorted(ts), name)


class FetchTests(unittest.TestCase):
    def fetch(self, net, sleep=None, symbols=("EURUSD=X",), **kw):
        kw.setdefault("cache_dir", None)
        kw.setdefault("ttl_s", data.TTL_DAILY)
        return data.fetch_bars(list(symbols), "1d", "6mo", http_get=net,
                               sleep=sleep or Sleeps(), now=100000.0, **kw)

    def test_fetch_ok(self):
        net = Net(GOOD)
        got, failed = self.fetch(net)
        self.assertEqual(failed, [])
        self.assertEqual(len(got["EURUSD=X"].bars), 3)
        self.assertIn("query2", net.urls[0])
        self.assertIn("/v8/finance/chart/EURUSD%3DX?range=6mo&interval=1d", net.urls[0])

    def test_fetch_falls_back_to_query1_on_500(self):
        net = Net(http_error(500), GOOD)
        got, failed = self.fetch(net)
        self.assertEqual(failed, [])
        self.assertIn("EURUSD=X", got)
        self.assertIn("query2", net.urls[0])
        self.assertIn("query1", net.urls[1])

    def test_429_waits_backoff_once(self):
        net = Net(http_error(429), http_error(429), GOOD)
        sl = Sleeps()
        got, failed = self.fetch(net, sl)
        self.assertEqual(failed, [])
        self.assertEqual(sl.calls.count(5.0), 1)
        self.assertEqual(len(net.urls), 3)

    def test_429_persisting_fails_cleanly(self):
        net = Net(http_error(429))
        sl = Sleeps()
        got, failed = self.fetch(net, sl)
        self.assertEqual(got, {})
        self.assertEqual(sl.calls.count(5.0), 1)
        self.assertEqual(len(net.urls), 4)
        self.assertEqual(failed, [{"symbol": "EURUSD=X", "reason": "Yahoo answered HTTP 429"}])

    def test_4xx_with_json_body_is_parsed_as_no_data(self):
        err = urllib.error.HTTPError("http://x", 404, "nf", {}, io.BytesIO(NO_DATA.encode()))
        got, failed = self.fetch(Net(err), symbols=("XXX=X",))
        self.assertEqual(got, {})
        self.assertEqual(failed[0]["symbol"], "XXX=X")
        self.assertTrue(failed[0]["reason"].startswith("no data"))

    def test_pause_between_symbols_only(self):
        sl = Sleeps()
        got, failed = self.fetch(Net(GOOD), sl, symbols=("A=X", "B=X", "C=X"))
        self.assertEqual(sorted(got), ["A=X", "B=X", "C=X"])
        self.assertEqual(sl.calls, [data.PAUSE, data.PAUSE])

    def test_failure_without_cache_listed_in_failed(self):
        got, failed = self.fetch(Net(NO_DATA), symbols=("XXX=X",))
        self.assertEqual(got, {})
        self.assertEqual(failed, [{"symbol": "XXX=X",
                                   "reason": "no data: No data found, symbol may be delisted"}])

    def test_one_failure_does_not_stop_the_others(self):
        net = Net(NO_DATA, GOOD)
        got, failed = self.fetch(net, symbols=("XXX=X", "EURUSD=X"))
        self.assertEqual(list(got), ["EURUSD=X"])
        self.assertEqual([f["symbol"] for f in failed], ["XXX=X"])


class KeyedNet:
    """Thread-safe http_get answering by symbol found in the URL. A symbol mapped to
    an Exception is raised, to a str returned; unknown symbols get NO_DATA."""

    def __init__(self, table, delay=0.0):
        self.table, self.delay = table, delay
        self.urls = []
        self._lock = threading.Lock()

    def __call__(self, url):
        with self._lock:
            self.urls.append(url)
        sym = url.split("/chart/")[1].split("?")[0].replace("%3D", "=")
        if self.delay:  # earlier symbols answer later: completion order != input order
            time.sleep(self.delay * (3 - len(self.urls) % 4))
        item = self.table.get(sym, NO_DATA)
        if isinstance(item, Exception):
            raise item
        return item


class LockedSleeps(Sleeps):
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()

    def __call__(self, s):
        with self._lock:
            self.calls.append(s)


class WorkersTests(unittest.TestCase):
    SYMS = ("A=X", "B=X", "BAD=X", "C=X", "D=X", "E=X")

    def table(self):
        return {s: GOOD for s in self.SYMS if s != "BAD=X"}

    def fetch(self, net, workers, sleep=None, symbols=None, **kw):
        kw.setdefault("cache_dir", None)
        kw.setdefault("ttl_s", 3600)
        return data.fetch_bars(list(symbols or self.SYMS), "1d", "6mo", http_get=net,
                               sleep=sleep or LockedSleeps(), now=100000.0,
                               workers=workers, **kw)

    def test_workers_3_same_result_and_order_as_sequential(self):
        seq = self.fetch(KeyedNet(self.table()), 1)
        par = self.fetch(KeyedNet(self.table(), delay=0.01), 3)
        self.assertEqual(par, seq)
        self.assertEqual(list(par[0]), ["A=X", "B=X", "C=X", "D=X", "E=X"])

    def test_failure_lands_in_failed_in_input_order(self):
        table = self.table()
        table["E=X"] = NO_DATA
        got, failed = self.fetch(KeyedNet(table, delay=0.01), 3)
        self.assertEqual([f["symbol"] for f in failed], ["BAD=X", "E=X"])
        self.assertTrue(all(f["reason"].startswith("no data") for f in failed))
        self.assertNotIn("BAD=X", got)

    def test_pause_before_each_real_request_workers_3(self):
        sl = LockedSleeps()
        self.fetch(KeyedNet(self.table()), 3, sleep=sl)
        self.assertEqual(sl.calls, [data.PAUSE] * len(self.SYMS))

    def test_cache_hits_make_no_request_and_no_pause_workers_3(self):
        with tempfile.TemporaryDirectory() as d:
            for s in self.SYMS:
                write_cache(d, 100000.0 - 100, name=s.replace("=", "_") + "_1d_6mo.json")
            net, sl = KeyedNet(self.table()), LockedSleeps()
            got, failed = self.fetch(net, 3, sleep=sl, cache_dir=d)
        self.assertEqual(net.urls, [])
        self.assertEqual(sl.calls, [])
        self.assertEqual(failed, [])
        self.assertEqual(list(got), list(self.SYMS))

    def test_stale_cache_fallback_workers_3(self):
        with tempfile.TemporaryDirectory() as d:
            for s in self.SYMS:
                write_cache(d, 100000.0 - 7200, name=s.replace("=", "_") + "_1d_6mo.json")
            table = {s: http_error(500) for s in self.SYMS}
            got, failed = self.fetch(KeyedNet(table), 3, cache_dir=d)
        self.assertEqual(failed, [])
        self.assertEqual(list(got), list(self.SYMS))
        self.assertTrue(all(s.age_s == 7200 for s in got.values()))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def fetch(self, net, **kw):
        kw.setdefault("ttl_s", 3600)
        return data.fetch_bars(["EURUSD=X"], "1d", "6mo", cache_dir=self.d,
                               http_get=net, sleep=Sleeps(), now=100000.0, **kw)

    def test_fetch_writes_cache_file(self):
        self.fetch(Net(GOOD))
        with open(cache_file(self.d)) as f:
            c = json.load(f)
        self.assertEqual(c["fetched_at"], 100000.0)
        self.assertEqual(c["gmtoffset"], 3600)
        self.assertEqual(len(c["bars"]), 3)

    def test_cache_hit_within_ttl_makes_no_request(self):
        write_cache(self.d, 100000.0 - 100)
        net = Net(GOOD)
        got, failed = self.fetch(net)
        self.assertEqual(net.urls, [])
        self.assertEqual(failed, [])
        s = got["EURUSD=X"]
        self.assertEqual(s.gmtoffset, 7200)
        self.assertIsNone(s.age_s)
        self.assertEqual(s.bars[0], (1000, 1.0, 2.0, 0.5, 1.5))
        self.assertIsInstance(s.bars[0], tuple)

    def test_cache_expired_refetches(self):
        write_cache(self.d, 100000.0 - 7200)
        net = Net(GOOD)
        got, failed = self.fetch(net)
        self.assertEqual(len(net.urls), 1)
        self.assertEqual(got["EURUSD=X"].gmtoffset, 3600)
        self.assertIsNone(got["EURUSD=X"].age_s)

    def test_corrupt_or_empty_cache_file_refetches(self):
        for content in ("", "{", "[]", '{"fetched_at": 99999, "bars": "x"}',
                        '{"fetched_at": 99999, "gmtoffset": 0, "bars": [[1, 2]]}'):
            with open(cache_file(self.d), "w") as f:
                f.write(content)
            net = Net(GOOD)
            got, failed = self.fetch(net)
            self.assertEqual(len(net.urls), 1, repr(content))
            self.assertEqual(failed, [])
            self.assertEqual(len(got["EURUSD=X"].bars), 3)

    def test_stale_cache_used_after_network_failure_sets_age(self):
        write_cache(self.d, 100000.0 - 7200)
        got, failed = self.fetch(Net(http_error(500)))
        self.assertEqual(failed, [])
        s = got["EURUSD=X"]
        self.assertGreater(s.age_s, 3600)
        self.assertEqual(s.age_s, 7200)
        self.assertEqual(len(s.bars), 3)

    def test_no_cache_flag_ignores_cache(self):
        write_cache(self.d, 100000.0 - 10)
        net = Net(GOOD)
        got, failed = self.fetch(net, use_cache=False)
        self.assertEqual(len(net.urls), 1)
        self.assertEqual(got["EURUSD=X"].gmtoffset, 3600)

    def test_no_cache_flag_does_not_fall_back_to_stale(self):
        write_cache(self.d, 100000.0 - 7200)
        got, failed = self.fetch(Net(http_error(500)), use_cache=False)
        self.assertEqual(got, {})
        self.assertEqual(failed[0]["symbol"], "EURUSD=X")

    def test_cache_filename_is_sanitised(self):
        data.fetch_bars(["^FCHI", "GC=F"], "1d", "6mo", cache_dir=self.d, ttl_s=60,
                        http_get=Net(GOOD), sleep=Sleeps(), now=1.0)
        self.assertEqual(sorted(os.listdir(self.d)), ["GC_F_1d_6mo.json", "_FCHI_1d_6mo.json"])

    def test_cache_dir_is_created(self):
        sub = os.path.join(self.d, "a", "b")
        data.fetch_bars(["EURUSD=X"], "1d", "6mo", cache_dir=sub, ttl_s=60,
                        http_get=Net(GOOD), sleep=Sleeps(), now=1.0)
        self.assertTrue(os.path.isfile(os.path.join(sub, "EURUSD_X_1d_6mo.json")))


if __name__ == "__main__":
    unittest.main()
