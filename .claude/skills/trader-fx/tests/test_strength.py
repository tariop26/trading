import _path  # noqa
import unittest

import strength


def flat(n=30, v=1.0):
    return [v] * n


def rising(pct, n=30, v=1.0):
    """Flat series whose last close is `pct` percent above all previous ones."""
    return [v] * (n - 1) + [v * (1 + pct / 100.0)]


def scores(rows):
    return {r["ccy"]: r["score"] for r in rows}


class PairCurrenciesTest(unittest.TestCase):
    def test_pair_currencies_parses_pairs_and_rejects_others(self):
        self.assertEqual(strength.pair_currencies("EURUSD=X"), ("EUR", "USD"))
        self.assertEqual(strength.pair_currencies("USDJPY=X"), ("USD", "JPY"))
        self.assertIsNone(strength.pair_currencies("GC=F"))
        self.assertIsNone(strength.pair_currencies("^FCHI"))
        self.assertIsNone(strength.pair_currencies("EURUSD"))


class CurrencyStrengthTest(unittest.TestCase):
    def test_rising_currency_ranks_first_and_falling_last(self):
        closes = {
            "EURUSD=X": rising(1),
            "EURGBP=X": rising(1),
            "EURJPY=X": rising(1),
            "GBPUSD=X": flat(),
            "USDJPY=X": flat(),
            "GBPJPY=X": flat(),
        }
        out = strength.currency_strength(closes)
        self.assertEqual(set(out), {"1d", "5d", "20d"})
        order = [r["ccy"] for r in out["5d"]]
        self.assertEqual(order[0], "EUR")
        self.assertEqual(set(order[-3:]), {"USD", "GBP", "JPY"})
        self.assertEqual(len(order), 4)

    def test_signed_by_base_and_quote(self):
        out = strength.currency_strength({"USDJPY=X": rising(1)})
        s = scores(out["1d"])
        self.assertGreater(s["USD"], 0)
        self.assertLess(s["JPY"], 0)
        self.assertAlmostEqual(s["USD"], -s["JPY"], places=9)
        self.assertEqual([r["ccy"] for r in out["1d"]], ["USD", "JPY"])

    def test_pair_with_too_few_closes_is_skipped_without_error(self):
        closes = {"EURUSD=X": [1.0, 1.01, 1.02], "USDJPY=X": rising(1)}
        out = strength.currency_strength(closes)
        self.assertEqual({r["ccy"] for r in out["20d"]}, {"USD", "JPY"})
        self.assertEqual({r["ccy"] for r in out["1d"]}, {"EUR", "USD", "JPY"})
        s = scores(out["1d"])
        self.assertGreater(s["EUR"], 0)

    def test_non_forex_and_unknown_currencies_ignored(self):
        closes = {"GC=F": rising(5), "USDXXX=X": rising(5), "EURUSD=X": rising(1)}
        out = strength.currency_strength(closes)
        self.assertEqual({r["ccy"] for r in out["1d"]}, {"EUR", "USD"})


class ClustersTest(unittest.TestCase):
    def test_clusters_flags_dominant_currency(self):
        hits = [
            {"symbol": "EURUSD=X"},
            {"symbol": "GBPUSD=X"},
            {"symbol": "USDJPY=X"},
            {"symbol": "AUDUSD=X"},
            {"symbol": "EURGBP=X"},
        ]
        self.assertEqual(
            strength.clusters(hits), [{"ccy": "USD", "count": 4, "of": 5}]
        )

    def test_clusters_empty_when_no_dominant_currency(self):
        hits = [
            {"symbol": "EURUSD=X"},
            {"symbol": "GBPJPY=X"},
            {"symbol": "AUDNZD=X"},
            {"symbol": "GC=F"},
        ]
        self.assertEqual(strength.clusters(hits), [])


if __name__ == "__main__":
    unittest.main()
