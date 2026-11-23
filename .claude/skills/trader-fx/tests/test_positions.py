import _path  # noqa
import unittest
from datetime import datetime, timezone

import positions as pos

HEADER = ("Id,Actif,Symbole Yahoo,Sens,Entrée,SL,TP,Lots,\"Valeur 1,00 pour 1 lot ($)\","
          "Ouverture (Paris),,Paramètre,Valeur")


def csv_text(*rows, header=HEADER):
    return "\n".join([header] + list(rows)) + "\n"


GOLD = 'Ligne 6,XAUUSD,GC=F,haussier,3547,3498,3840,"0,1",100,2026-11-20 17:34,,Solde clos ($),"99302,00"'
DAX = 'Ligne 4,GER40,^GDAXI,haussier,"24888,66",24600,25240,"0,08","10,9601",2026-11-20 17:35,,' \
      'P&L clos aujourd\'hui ($),"-382,00"'
PARAMS = [',,,,,,,,,,,Capital initial ($),"100000,00"',
          ',,,,,,,,,,,Alerte perte du jour ($),"1000,00"',
          ',,,,,,,,,,,Stop journalier interne ($),"1500,00"',
          ',,,,,,,,,,,Perte journalière max FundedNext ($),"5000,00"',
          ',,,,,,,,,,,Plancher perte max ($),"90000,00"',
          ',,,,,,,,,,,Risque ouvert max ($),"1500,00"']


def ts(y, mo, d, h, mi):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp())


class TestNumbers(unittest.TestCase):
    def test_french_and_currency_formats(self):
        cases = {"24888,66": 24888.66, "99 302 $": 99302.0, "-382 $": -382.0,
                 "1 500,00": 1500.0, "−250": -250.0, "3547": 3547.0, "0,1": 0.1}
        for text, want in cases.items():
            self.assertAlmostEqual(pos.parse_number(text), want, msg=text)

    def test_unreadable_is_none(self):
        for text in ("", " ", "n/a", "#N/A", None, "abc"):
            self.assertIsNone(pos.parse_number(text), text)

    def test_paris_to_utc_winter_and_summer(self):
        self.assertEqual(pos.paris_to_utc("2026-11-20 17:35").isoformat(), "2026-11-20T16:35:00+00:00")
        self.assertEqual(pos.paris_to_utc("2026-07-01 10:00").isoformat(), "2026-07-01T08:00:00+00:00")
        self.assertIsNone(pos.paris_to_utc("20/11/2026 17:35"))


class TestParse(unittest.TestCase):
    def test_positions_and_params(self):
        got, params, problems = pos.parse_csv(csv_text(DAX, GOLD, *PARAMS))
        self.assertEqual(problems, [])
        self.assertEqual([p["asset"] for p in got], ["GER40", "XAUUSD"])
        gold = got[1]
        self.assertEqual(gold["symbol"], "GC=F")
        self.assertEqual(gold["side"], "haussier")
        self.assertEqual((gold["entry"], gold["stop"], gold["target"], gold["lots"]), (3547, 3498, 3840, 0.1))
        self.assertEqual(gold["opened_utc"], "2026-11-20T16:34:00+00:00")
        self.assertEqual(params, {"closed_balance": 99302.0, "realized_today": -382.0, "capital": 100000.0,
                                  "warn_loss": 1000.0, "internal_stop": 1500.0, "fn_daily": 5000.0,
                                  "floor": 90000.0, "open_risk_max": 1500.0})

    def test_bad_rows_are_skipped_with_a_reason(self):
        rows = ['L1,XAUUSD,GC=F,long,3547,3498,3840,1,100,2026-11-20 17:34',
                'L2,XAUUSD,,haussier,3547,3498,3840,1,100,2026-11-20 17:34',
                'L3,XAUUSD,GC=F,haussier,3547,3600,3840,1,100,2026-11-20 17:34',
                'L4,XAUUSD,GC=F,haussier,3547,3498,3840,0,100,2026-11-20 17:34',
                'L5,XAUUSD,GC=F,haussier,3547,3498,3840,1,100,20/11 17:34',
                'L6,XAUUSD,GC=F,baissier,3547,3600,3700,1,100,2026-11-20 17:34',
                ',,,,,,,,,']
        got, _, problems = pos.parse_csv(csv_text(*rows))
        self.assertEqual([p["id"] for p in got], ["L6"])
        self.assertIsNone(got[0]["target"])                      # TP on the wrong side: dropped
        self.assertEqual(len(problems), 6)
        for word in ("sens", "symbole", "SL du mauvais", "lots", "heure", "TP du mauvais"):
            self.assertTrue(any(word in p for p in problems), word)

    def test_empty_tab_has_no_positions(self):
        self.assertEqual(pos.parse_csv(csv_text(*PARAMS))[0], [])

    def test_wrong_tab_raises(self):
        for text in ("", "a,b,c\n1,2,3\n", "Date ouverture,Heure,Actif,Setup,Sens,Entrée,SL,TP,Lots,Risque\n"):
            with self.assertRaises(pos.PositionsError):
                pos.parse_csv(text)

    def test_fetch_errors_keep_the_url_out(self):
        def boom(url):
            raise OSError("https://docs.google.com/secret-link")
        with self.assertRaises(pos.PositionsError) as ctx:
            pos.fetch_csv("https://docs.google.com/secret-link", http_get=boom)
        self.assertNotIn("secret", str(ctx.exception))
        with self.assertRaises(pos.PositionsError):
            pos.fetch_csv("u", http_get=lambda url: "  \n")


class TestPricesAndRules(unittest.TestCase):
    def setUp(self):
        self.gold = pos.parse_csv(csv_text(GOLD))[0][0]          # opened 16:34 UTC, entry 3547

    def test_offset_from_the_opening_bar(self):
        bars = [(ts(2026, 11, 20, 16, 25), 0, 0, 0, 3560.0), (ts(2026, 11, 20, 16, 30), 0, 0, 0, 3567.0),
                (ts(2026, 11, 20, 16, 35), 0, 0, 0, 3570.0)]
        self.assertAlmostEqual(pos.entry_offset(self.gold, bars), 20.0)

    def test_offset_falls_back_to_a_recent_bar_then_none(self):
        quiet = [(ts(2026, 11, 20, 16, 20), 0, 0, 0, 3565.0)]           # 14 min before: kept
        self.assertAlmostEqual(pos.entry_offset(self.gold, quiet), 18.0)
        old = [(ts(2026, 11, 20, 15, 0), 0, 0, 0, 3565.0)]
        self.assertIsNone(pos.entry_offset(self.gold, old))
        self.assertIsNone(pos.entry_offset(self.gold, []))
        far = [(ts(2026, 11, 20, 16, 30), 0, 0, 0, 3700.0)]               # 4 %: wrong symbol or time
        self.assertIsNone(pos.entry_offset(self.gold, far))

    def test_floating_and_risk(self):
        self.assertAlmostEqual(pos.floating_usd(self.gold, 3577.0, 20.0), 100.0)   # +10 net x 0.1 x 100
        self.assertAlmostEqual(pos.floating_usd(self.gold, 3537.0, None), -100.0)
        short = dict(self.gold, side="baissier", stop=3600.0)
        self.assertAlmostEqual(pos.floating_usd(short, 3537.0, None), 100.0)
        self.assertAlmostEqual(pos.risk_usd(self.gold), 490.0)

    def test_last_price(self):
        bars = [(3, 0, 0, 0, 2.0), (5, 0, 0, 0, None), (4, 0, 0, 0, 3.0)]
        self.assertEqual(pos.last_price(bars), (3.0, 4))
        self.assertEqual(pos.last_price([]), (None, None))

    def test_rules_are_moved_by_the_gap(self):
        rules = pos.to_rules([self.gold], {"Ligne 6": 20.0})
        self.assertEqual([(r["id"], r["type"], r["level"]) for r in rules],
                         [("Ligne 6-stop", "stop", 3518.0), ("Ligne 6-cible", "cible", 3860.0)])
        self.assertEqual(rules[0]["since"], "2026-11-20T16:34:00+00:00")
        self.assertEqual(rules[0]["trade_id"], "XAUUSD ouvert le 20/11 17:34")
        self.assertEqual(rules[0]["symbol"], "GC=F")
        no_target = dict(self.gold, target=None)
        self.assertEqual(len(pos.to_rules([no_target], {})), 1)
        self.assertEqual(pos.to_rules([no_target], {})[0]["level"], 3498.0)


if __name__ == "__main__":
    unittest.main()
