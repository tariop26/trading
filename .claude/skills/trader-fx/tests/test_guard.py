import _path  # noqa
import re
import unittest

import guard

DAY = "2026-11-23"
FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b|—")
PARAMS = {"closed_balance": 99302.0, "realized_today": -382.0, "capital": 100000.0,
          "warn_loss": 1000.0, "internal_stop": 1500.0, "fn_daily": 5000.0, "floor": 90000.0,
          "open_risk_max": 1500.0}


def position(pid="L6", asset="XAUUSD", symbol="GC=F", side="haussier", entry=3547.0, stop=3498.0,
             lots=0.1, ppt=100.0):
    return {"id": pid, "asset": asset, "symbol": symbol, "side": side, "entry": entry, "stop": stop,
            "target": None, "lots": lots, "usd_per_point": ppt,
            "opened_utc": "2026-11-20T16:34:00+00:00"}


def run(positions, prices, offsets=None, params=None, sent=()):
    state = {"guard_sent": list(sent)}
    return guard.evaluate(positions, params or PARAMS, prices, offsets or {}, state, DAY)


class TestGuard(unittest.TestCase):
    def test_quiet_day_sends_nothing(self):
        msgs, summary = run([position()], {"GC=F": 3550.0})
        self.assertEqual(msgs, [])
        self.assertIn("1 position", summary)

    def test_warn_threshold(self):
        # -382 closed, gold -700 floating: -1 082
        msgs, _ = run([position()], {"GC=F": 3477.0})
        self.assertEqual(len(msgs), 1)
        text, keys = msgs[0]
        self.assertEqual(keys, ["guard|alerte|%s" % DAY])
        self.assertIn("Seuil d'alerte franchi (-1 000 $)", text)
        self.assertIn("Résultat du jour estimé -1 082 $ (clos -382 $, latent -700 $)", text)
        self.assertIn("XAUUSD haussier -700 $", text)

    def test_gap_correction_is_used(self):
        # Yahoo 20 above the CFD: 3497 Yahoo = 3477 CFD
        msgs, _ = run([position()], {"GC=F": 3497.0}, offsets={"L6": 20.0})
        self.assertEqual(msgs[0][1], ["guard|alerte|%s" % DAY])

    def test_jump_sends_only_the_worst_and_marks_the_lower_ones(self):
        msgs, _ = run([position(lots=0.5)], {"GC=F": 3477.0})      # -3 500 floating, -3 882 day
        self.assertEqual(len(msgs), 2)                               # day message + open risk
        text, keys = msgs[0]
        self.assertIn("DANGER FUNDEDNEXT", text)
        self.assertEqual(keys, ["guard|alerte|%s" % DAY, "guard|stop|%s" % DAY, "guard|fn_jour|%s" % DAY])
        self.assertIn("Risque ouvert", msgs[1][0])

    def test_already_sent_is_not_repeated_but_a_worse_level_is(self):
        sent = ["guard|alerte|%s" % DAY]
        self.assertEqual(run([position()], {"GC=F": 3477.0}, sent=sent)[0], [])
        msgs, _ = run([position()], {"GC=F": 3437.0}, sent=sent)     # -1 482? no: -1 100 - 382
        self.assertEqual(msgs, [])
        msgs, _ = run([position()], {"GC=F": 3427.0}, sent=sent)     # -1 200 - 382 = -1 582
        self.assertEqual(len(msgs), 1)
        self.assertIn("STOP INTERNE ATTEINT", msgs[0][0])

    def test_floor_danger(self):
        params = dict(PARAMS, closed_balance=93000.0, realized_today=0.0, warn_loss=None,
                      internal_stop=None, fn_daily=None)
        msgs, _ = run([position()], {"GC=F": 3447.0}, params=params)   # equity 92 000
        self.assertEqual(len(msgs), 1)
        self.assertIn("DANGER PLANCHER", msgs[0][0])
        self.assertEqual(msgs[0][1], ["guard|plancher|%s" % DAY])

    def test_open_risk_above_the_cap(self):
        many = [position(pid="a"), position(pid="b", asset="GER40", symbol="^GDAXI", entry=24888.66,
                                            stop=24600.0, lots=0.08, ppt=10.96),
                position(pid="c", asset="NAS100", symbol="NQ=F", entry=25829.0, stop=25200.0, lots=0.05, ppt=10.0),
                position(pid="d", asset="BTCUSD", symbol="BTC-USD", entry=60206.0, stop=54000.0, lots=0.1, ppt=1.0)]
        prices = {"GC=F": 3547.0, "^GDAXI": 24888.66, "NQ=F": 25829.0, "BTC-USD": 60206.0}
        msgs, summary = run(many, prices, params=dict(PARAMS, realized_today=0.0))
        self.assertEqual(len(msgs), 1)
        self.assertIn("Risque ouvert 1 678 $", msgs[0][0])
        self.assertIn("plafond de 1 500 $", msgs[0][0])

    def test_missing_price_is_said(self):
        msgs, summary = run([position(), position(pid="x", asset="GER40", symbol="^GDAXI")],
                            {"GC=F": 3477.0})
        self.assertIn("pas de prix pour GER40", msgs[0][0])
        self.assertIn("sans prix : GER40", summary)

    def test_short_positions(self):
        short = position(side="baissier", stop=3600.0)
        msgs, _ = run([short], {"GC=F": 3617.0})                       # -700 floating
        self.assertEqual(msgs[0][1], ["guard|alerte|%s" % DAY])

    def test_vocabulary(self):
        texts = [m[0] for m in run([position(lots=0.5)], {"GC=F": 3377.0})[0]]
        texts.append(guard.csv_down_message())
        self.assertTrue(texts)
        for t in texts:
            self.assertIsNone(FORBIDDEN.search(t), t)
            self.assertLess(len(t), 4096)


if __name__ == "__main__":
    unittest.main()
