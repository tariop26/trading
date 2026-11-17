import _path  # noqa
import re
import unittest
from datetime import datetime, timezone

import alert_messages as am

FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b")
ACCOUNT = {"currency": "USD", "capital": 100000, "risk_per_trade_usd": 500.0,
           "leverage_max": 30, "source": "file"}
LOTS = {"status": "ok", "lots": 0.45, "units": 45000, "size": None, "risk_usd": 480.75}


def idea(**kw):
    i = {"symbol": "EURJPY=X", "name": "EUR/JPY", "side": "baissier", "reference_price": 176.659,
         "stop": 178.408, "target": 173.161, "rr": 2.0, "decimals": 3, "setups": ["lose_ma20"],
         "size": dict(LOTS)}
    i.update(kw)
    return i


def hit(kind="stop", **kw):
    rule = {"id": "2026-11-16-EURJPY-1-%s" % kind, "trade_id": "2026-11-16-EURJPY-1",
            "symbol": "EURJPY=X", "type": kind, "side": "baissier",
            "level": 178.408 if kind == "stop" else 173.161, "decimals": 3,
            "since": "2026-11-16T08:30:00+00:00"}
    h = {"rule": rule, "bar_time": "2026-11-16T13:35:00+00:00", "extreme": 178.412,
         "extreme_kind": "plus haut"}
    h.update(kw)
    return h


def item(**kw):
    e = {"utc": "2026-11-16T13:30:00+00:00", "currency": "USD", "title": "Core CPI m/m",
         "impact": "High", "time_paris": "14:30"}
    e.update(kw.pop("event", {}))
    i = {"event": e, "minutes": 25, "symbols": ["EURJPY=X"]}
    i.update(kw)
    return i


class TestLabels(unittest.TestCase):
    def test_pair_label(self):
        self.assertEqual(am.pair_label("EURJPY=X"), "EUR/JPY")
        self.assertEqual(am.pair_label("^FCHI"), "^FCHI")


class TestIdeaMessage(unittest.TestCase):
    def test_forex_idea_with_lots(self):
        self.assertEqual(am.idea_message(idea(), ACCOUNT), "\n".join([
            "Idée de trade, en formation, non confirmée à la clôture : EUR/JPY baissier.",
            "Entrée 176.659, stop 178.408, cible 173.161 (1:2).",
            "Taille 0.45 lot, risque 480.75 USD (0.5 % du capital).",
            "Règles : lose_ma20.",
            "Plan mécanique à valider, pas un conseil. Prix Yahoo, retardé."]))

    def test_two_lots_or_more_take_the_plural_and_several_rules_are_joined(self):
        size = dict(LOTS, lots=2.5, units=250000, risk_usd=495.0)
        text = am.idea_message(idea(size=size, setups=["breakdown_20d", "lose_ma20"]), ACCOUNT)
        self.assertIn("Taille 2.5 lots, risque 495.00 USD (0.5 % du capital).", text)
        self.assertIn("Règles : breakdown_20d, lose_ma20.", text)

    def test_contract_size(self):
        size = {"status": "ok", "lots": None, "units": None, "size": 4.5, "risk_usd": 495.0}
        text = am.idea_message(idea(symbol="^FCHI", name="CAC 40", side="haussier", decimals=2,
                                    reference_price=8368.91, stop=8300.0, target=8500.0, rr=2.0,
                                    size=size), ACCOUNT)
        self.assertIn("CAC 40 haussier.", text)
        self.assertIn("Entrée 8368.91, stop 8300.00, cible 8500.00 (1:2).", text)
        self.assertIn("Taille 4.5, risque 495.00 USD (0.5 % du capital).", text)

    def test_size_to_confirm_and_too_wide(self):
        for status, line in (("to_confirm", "Taille à confirmer chez le courtier."),
                             ("too_wide", "Stop trop large pour le risque fixé.")):
            size = {"status": status, "lots": None, "units": None, "size": None, "risk_usd": None}
            text = am.idea_message(idea(size=size), ACCOUNT)
            self.assertIn("\n" + line + "\n", text)
            self.assertNotIn("risque 480", text)
            self.assertNotIn("Taille 0", text)

    def test_an_incomplete_size_never_crashes_and_never_invents_a_figure(self):
        for size in ({}, None, {"status": "ok"}, {"status": "ok", "lots": None, "size": None},
                     {"status": "ok", "lots": 0.45, "risk_usd": None}):
            text = am.idea_message(idea(size=size), ACCOUNT)
            self.assertIn("Taille à confirmer chez le courtier.", text, size)

    def test_default_account_and_waiting_lines(self):
        text = am.idea_message(idea(), dict(ACCOUNT, source="default"), waiting=2)
        self.assertEqual(text.split("\n")[-3:], [
            "Taille calculée sur le capital par défaut.",
            "Plan mécanique à valider, pas un conseil. Prix Yahoo, retardé.",
            "2 autres idées en attente."])
        # the default-capital line sits before the plan disclaimer, never after it
        self.assertLess(text.index("par défaut"), text.index("Plan mécanique"))
        one = am.idea_message(idea(), ACCOUNT, waiting=1)
        self.assertEqual(one.split("\n")[-1], "1 autre idée en attente.")
        self.assertNotIn("par défaut", am.idea_message(idea(), ACCOUNT))

    def test_prices_use_the_decimals_of_the_idea(self):
        text = am.idea_message(idea(decimals=5, reference_price=1.18831, stop=1.18029,
                                    target=1.20435, symbol="EURUSD=X", name="EUR/USD",
                                    side="haussier"), ACCOUNT)
        self.assertIn("Entrée 1.18831, stop 1.18029, cible 1.20435 (1:2).", text)

    def test_a_ratio_that_is_not_an_integer(self):
        self.assertIn("(1:1.5)", am.idea_message(idea(rr=1.5), ACCOUNT))


class TestTouchMessage(unittest.TestCase):
    def test_stop(self):
        self.assertEqual(am.touch_message(hit("stop")), "\n".join([
            "Stop touché : EUR/JPY baissier, trade 2026-11-16-EURJPY-1.",
            "Niveau 178.408 franchi à 14:35 (plus haut de la barre 5 min : 178.412).",
            "Vérifiez la position chez le courtier."]))

    def test_target_and_a_low(self):
        text = am.touch_message(hit("cible", extreme=173.15, extreme_kind="plus bas"))
        self.assertEqual(text.split("\n")[0], "Cible touchée : EUR/JPY baissier, trade 2026-11-16-EURJPY-1.")
        self.assertIn("Niveau 173.161 franchi à 14:35 (plus bas de la barre 5 min : 173.150).", text)

    def test_summer_time_gives_paris_plus_two(self):
        text = am.touch_message(hit(bar_time="2026-07-15T13:35:00+00:00"))
        self.assertIn("franchi à 15:35", text)


class TestEventAndDown(unittest.TestCase):
    def test_event(self):
        self.assertEqual(am.event_message(item()), "\n".join([
            "Annonce à fort impact dans 25 min : 14:30 Paris, USD, Core CPI m/m.",
            "Vos trades concernés : EUR/JPY."]))

    def test_several_trades_and_special_characters_stay_as_they_are(self):
        text = am.event_message(item(symbols=["EURJPY=X", "^FCHI"], event={"title": 'Core <CPI> & "m/m"'}))
        self.assertIn('USD, Core <CPI> & "m/m".', text)
        self.assertIn("Vos trades concernés : EUR/JPY, ^FCHI.", text)

    def test_down(self):
        self.assertEqual(am.down_message(), "Impossible de vérifier vos stops : données Yahoo indisponibles.")


BAR_TS = int(datetime(2026, 11, 16, 8, 15, tzinfo=timezone.utc).timestamp())
PREVIOUS = {"score": 3, "families": ["session_break"], "sent_iso": "2026-11-16T08:31:00+00:00"}
FORBIDDEN_SIGNAL = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell|gagnant|profit|prévision)\b")


def candidate(**kw):
    c = {"symbol": "EURJPY=X", "display_name": "EUR/JPY", "side": "baissier", "score": 3,
         "why": "x", "families": ["session_break", "rsi_exit"], "primary": "session_break",
         "detail": "Londres", "bar_ts": BAR_TS, "bar_iso": "2026-11-16T08:15:00+00:00",
         "plan": {"reference_price": 176.7, "stop": 177.1, "target": 175.9, "rr": 2.0,
                  "decimals": 3, "limit_price": 176.64},
         "size": {"status": "ok", "lots": 0.45, "size": None, "risk_usd": 480.75, "units": 45000},
         "exposures": []}
    c.update(kw)
    return c


class TestSignalMessage(unittest.TestCase):
    def test_signal_message_exact_text(self):
        self.assertEqual(am.signal_message(candidate(), ACCOUNT), "\n".join([
            "Signal en séance, non confirmé par le courtier : EUR/JPY baissier.",
            "Signaux : session_break (Londres), rsi_exit. Barre 15 min de 09:15 Paris.",
            "Entrée 176.700 (zone valable jusqu'à 176.640), stop 177.100, cible 175.900 (1:2).",
            "Taille 0.45 lot, risque 480.75 USD (0.5 % du capital).",
            "Plan mécanique à valider, pas un conseil. Prix Yahoo, retardé."]))

    def test_ratio_and_empty_detail(self):
        c = candidate(detail="")
        c["plan"] = dict(c["plan"], rr=1.2)
        text = am.signal_message(c, ACCOUNT)
        self.assertIn("(1:1.2).", text)
        self.assertIn("Signaux : session_break, rsi_exit. Barre", text)

    def test_reinforced_message_mentions_previous_families_and_time(self):
        lines = am.signal_message(candidate(), ACCOUNT, PREVIOUS).split("\n")
        self.assertEqual(lines[0], "Signal en séance renforcé, non confirmé par le courtier : EUR/JPY baissier.")
        self.assertEqual(lines[-2], "Déjà alerté à 09:31 Paris : session_break.")
        self.assertEqual(lines[-1], am.DISCLAIMER)
        summer = dict(PREVIOUS, sent_iso="2026-07-15T08:31:00+00:00", families=["a", "b"])
        self.assertIn("Déjà alerté à 10:31 Paris : a, b.", am.signal_message(candidate(), ACCOUNT, summer))
        none = dict(PREVIOUS, families=[])
        self.assertIn("Déjà alerté à 09:31 Paris : aucun.", am.signal_message(candidate(), ACCOUNT, none))

    def test_default_capital_line(self):
        lines = am.signal_message(candidate(), dict(ACCOUNT, source="default")).split("\n")
        self.assertEqual(lines[-2:], ["Taille calculée sur le capital par défaut.", am.DISCLAIMER])
        self.assertNotIn("par défaut", am.signal_message(candidate(), ACCOUNT))
        both = am.signal_message(candidate(), dict(ACCOUNT, source="default"), PREVIOUS).split("\n")
        self.assertEqual(both[-3], "Taille calculée sur le capital par défaut.")
        self.assertTrue(both[-2].startswith("Déjà alerté"))

    def test_to_confirm_and_too_wide_sizes_never_invent_a_figure(self):
        for status, line in (("to_confirm", "Taille à confirmer chez le courtier."),
                             ("too_wide", "Stop trop large pour le risque fixé.")):
            size = {"status": status, "lots": None, "size": None, "risk_usd": None}
            text = am.signal_message(candidate(size=size), ACCOUNT)
            self.assertEqual(text.split("\n")[3], line)
            self.assertNotIn("risque 480", text)
            self.assertNotIn("Taille 0", text)

    def test_display_name_falls_back_to_pair_label(self):
        for name in (None, ""):
            c = candidate(display_name=name)
            self.assertIn("EUR/JPY baissier.", am.signal_message(c, ACCOUNT).split("\n")[0])
        c = candidate()
        del c["display_name"]
        self.assertIn("EUR/JPY baissier.", am.signal_message(c, ACCOUNT).split("\n")[0])

    def test_display_name_is_clipped_and_shown(self):
        self.assertIn("CAC 40 baissier.", am.signal_message(candidate(display_name="CAC 40"), ACCOUNT))
        text = am.signal_message(candidate(display_name="N" * 5000, detail="D" * 5000), ACCOUNT)
        self.assertIn("N" * 299 + "…", text)
        self.assertNotIn("N" * 300, text)
        self.assertIn("D" * 299 + "…", text)
        self.assertLess(len(text), am.TELEGRAM_LIMIT)

    def test_no_forbidden_word_and_under_telegram_limit(self):
        self.assertTrue(FORBIDDEN_SIGNAL.search("un achat"))
        self.assertTrue(FORBIDDEN_SIGNAL.search("Sell now"))
        texts = [am.signal_message(candidate(), ACCOUNT),
                 am.signal_message(candidate(), dict(ACCOUNT, source="default"), PREVIOUS),
                 am.signal_message(candidate(side="haussier"), ACCOUNT, PREVIOUS),
                 am.signal_message(candidate(display_name="N" * 5000, detail="D" * 5000), ACCOUNT, PREVIOUS),
                 am.signal_message(candidate(size={"status": "too_wide"}), ACCOUNT),
                 am.cap_message(10)]
        for text in texts:
            self.assertIsNone(FORBIDDEN_SIGNAL.search(text), text)
            self.assertNotIn("à prendre", text)
            self.assertLess(len(text), am.TELEGRAM_LIMIT)

    def test_cap_message_text(self):
        self.assertEqual(am.cap_message(10),
                         "Plafond de 10 alertes de signal atteint pour aujourd'hui : "
                         "les suivantes ne sont pas envoyées.")
        self.assertIn("Plafond de 3 alertes", am.cap_message(3.0))


class TestEveryMessage(unittest.TestCase):
    def messages(self):
        return [am.idea_message(idea(), ACCOUNT), am.idea_message(idea(), dict(ACCOUNT, source="default"), 2),
                am.touch_message(hit("stop")), am.touch_message(hit("cible")),
                am.event_message(item()), am.down_message()]

    def test_the_forbidden_word_filter_works_and_no_message_has_one(self):
        self.assertTrue(FORBIDDEN.search("un achat"))
        self.assertTrue(FORBIDDEN.search("Sell now"))
        self.assertFalse(FORBIDDEN.search("survente"))
        for text in self.messages():
            self.assertIsNone(FORBIDDEN.search(text), text)
            self.assertNotIn("à prendre", text)

    def test_no_financial_field_leaks(self):
        for text in self.messages():
            cleaned = text.replace("du capital", "").replace("le capital par défaut", "")
            for word in ("pnl", "résultat", "capital", "compte", "solde", "gain"):
                self.assertNotIn(word, cleaned.lower(), text)

    def test_every_message_fits_the_telegram_limit(self):
        many = ["rule_%d" % n for n in range(400)]
        long_idea = am.idea_message(idea(setups=many, name="N" * 5000), ACCOUNT, waiting=9)
        long_event = am.event_message(item(event={"title": "T" * 9000}))
        for text in (long_idea, long_event) + tuple(self.messages()):
            self.assertLess(len(text), 4096)


if __name__ == "__main__":
    unittest.main()
