#!/usr/bin/env python3
"""Surveillance rapide de l'or : stops et cibles contrôlés toutes les ~75 s sur des barres 1 min.

    python3 .claude/skills/trader-fx/live_gold.py [--dry-run] [--once] [--duration S] [--interval S]
        [--state PATH] [--alerts PATH] [--raw-url URL]

Prix : Twelve Data, offre gratuite (XAU/USD, retard mesuré d'environ 2 min), au lieu de Yahoo
(9 à 15 min). Les règles viennent de l'onglet Positions ouvertes du classeur quand le secret
POSITIONS_CSV_URL existe, sinon de trader/fx/alerts.json (relu à chaque tour depuis GitHub, sinon
depuis le fichier local). Seules les règles dont le symbole est l'or sont suivies ; sans règle, aucun
appel n'est fait (le quota gratuit est de 800 appels par jour). Les messages partent sur Telegram.
Le suivi à 15 minutes (alerts_run.py) reste actif : en cas de panne du flux il prend le relais, et
il peut alors répéter un message déjà envoyé ici (au plus une fois par règle et par heure).
Bibliothèque standard seulement. Les secrets viennent de l'environnement et ne sont jamais affichés
(les erreurs réseau sont réduites à leur type : l'URL contient la clé).
Code de sortie 0, ou 1 si un secret manque ou si un envoi Telegram a échoué.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alert_checks  # noqa: E402
import alert_messages  # noqa: E402
import alert_state  # noqa: E402
import journal  # noqa: E402
import positions  # noqa: E402
import telegram  # noqa: E402

# Symbole des règles (Yahoo) -> symbole Twelve Data.
SYMBOL_MAP = {"GC=F": "XAU/USD", "XAUUSD=X": "XAU/USD"}
TD_URL = "https://api.twelvedata.com/time_series"
BAR_LABEL = "barre 1 min, Twelve Data XAU/USD"
DEFAULT_STATE = "trader/fx/alerts_state.json"
DEFAULT_ALERTS = "trader/fx/alerts.json"
RAW_TEMPLATE = "https://raw.githubusercontent.com/%s/main/trader/fx/alerts.json"
BARS_WANTED = 15          # 15 barres 1 min : couvre un tour manqué sans gaspiller (1 appel = 1 crédit)
IDLE_S = 120              # sans règle sur l'or : on relit les règles, sans appeler le fournisseur
QUOTA_BACKOFF_S = 300
DOWN_AFTER = 5            # échecs de suite avant d'annoncer que le flux est en panne
TIMEOUT = 20


class FeedError(Exception):
    """Le flux n'a pas donné de barres. `quota` : limite d'appels atteinte."""

    def __init__(self, reason, quota=False):
        super().__init__(reason)
        self.quota = quota


def _say(line):
    print("[or-direct] " + line, flush=True)


def _http_get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "trader-fx-live/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace")      # Twelve Data met son erreur dans le corps
    # URLError et délais : propagés, l'appelant ne garde que le type (l'URL contient la clé)


def parse_bars(text):
    """Réponse JSON Twelve Data -> [[epoch, open, high, low, close], ...] triées par date."""
    try:
        doc = json.loads(text)
    except ValueError:
        raise FeedError("réponse illisible")
    if not isinstance(doc, dict):
        raise FeedError("réponse illisible")
    if doc.get("status") == "error":
        code = doc.get("code")
        raise FeedError("erreur fournisseur %s" % code, quota=(code == 429))
    bars = []
    for v in doc.get("values") or []:
        try:
            when = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            bars.append([when.timestamp(), float(v["open"]), float(v["high"]),
                         float(v["low"]), float(v["close"])])
        except (KeyError, TypeError, ValueError):
            continue                                    # une barre abîmée ne bloque pas les autres
    if not bars:
        raise FeedError("aucune barre")
    return sorted(bars, key=lambda b: b[0])


def fetch_bars(key, symbol, http_get=_http_get):
    q = urllib.parse.urlencode({"symbol": symbol, "interval": "1min", "outputsize": BARS_WANTED,
                                "timezone": "UTC", "apikey": key})
    try:
        text = http_get(TD_URL + "?" + q)
    except Exception as e:  # noqa: BLE001 - le type seulement : le message d'erreur contient l'URL
        raise FeedError("réseau (%s)" % type(e).__name__)
    return parse_bars(text)


def parse_alerts(text):
    """alerts.json (texte) -> (règles, date de mise à jour) ou (None, None)."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None, None
    if not isinstance(doc, dict) or doc.get("v") != 1 or not isinstance(doc.get("rules"), list):
        return None, None
    return [r for r in doc["rules"] if isinstance(r, dict)], doc.get("updated")


def rules_from_sheet(csv_url, http_get=_http_get):
    """Les règles or du classeur (onglet Positions ouvertes publié), ou None si illisible.

    Twelve Data donne le prix au comptant XAU/USD, celui du CFD à quelques centimes près : les
    niveaux CFD sont pris tels quels, sans correction d'écart (au contraire des futures Yahoo)."""
    try:
        plist, _params, _problems = positions.parse_csv(positions.fetch_csv(csv_url, http_get))
    except positions.PositionsError as e:
        _say("classeur illisible (%s) : alerts.json utilisé." % e)
        return None
    return positions.to_rules([p for p in plist if p["symbol"] in SYMBOL_MAP], {})


def load_rules(path, raw_url, http_get=_http_get, csv_url=None):
    """Les règles les plus récentes : le classeur s'il est publié, sinon GitHub (raw), puis le
    fichier de l'extraction."""
    if csv_url:
        rules = rules_from_sheet(csv_url, http_get)
        if rules is not None:
            return rules, None
    if raw_url:
        try:
            rules, updated = parse_alerts(http_get(raw_url, timeout=10))
            if rules is not None:
                return rules, updated
        except Exception:  # noqa: BLE001 - le fichier local sert de repli
            pass
    try:
        with open(path, encoding="utf-8") as f:
            return parse_alerts(f.read())
    except (OSError, ValueError):
        return None, None


def down_message():
    return ("Flux rapide de l'or indisponible : le suivi en direct est interrompu.\n"
            "Le suivi toutes les 15 minutes (prix Yahoo) reste actif.")


def _write_output(env, changed):
    path = env.get("GITHUB_OUTPUT")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("state_changed=%s\n" % ("true" if changed else "false"))
        except OSError:
            _say("GITHUB_OUTPUT illisible : sortie state_changed non écrite.")


def build_parser():
    p = argparse.ArgumentParser(prog="live_gold.py", description="surveillance rapide de l'or")
    p.add_argument("--dry-run", action="store_true",
                   help="affiche les messages sans rien envoyer ni mémoriser")
    p.add_argument("--once", action="store_true", help="un seul tour puis arrêt")
    p.add_argument("--duration", type=float, default=3570, help="durée de la boucle en secondes")
    p.add_argument("--interval", type=float, default=75, help="secondes entre deux tours")
    p.add_argument("--state", default=DEFAULT_STATE)
    p.add_argument("--alerts", default=DEFAULT_ALERTS)
    p.add_argument("--raw-url", default=None, help="URL de alerts.json sur GitHub (défaut : dépôt courant)")
    return p


def main(argv=None, deps=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    deps = dict(deps or {})
    args = build_parser().parse_args(argv)
    env = deps.get("env", os.environ)
    now = deps.get("now", lambda: datetime.now(timezone.utc))
    sleep = deps.get("sleep", time.sleep)
    get_bars = deps.get("fetch_bars", fetch_bars)
    csv_url = env.get("POSITIONS_CSV_URL", "").strip() or None
    get_rules = deps.get("load_rules",
                         lambda path, raw: load_rules(path, raw, csv_url=csv_url))
    send = deps.get("send", telegram.send_message)

    key = env.get("TWELVE_DATA_API_KEY", "").strip()
    token, chat = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if not key:
        print("Secret manquant : TWELVE_DATA_API_KEY.")
        return 1
    if not args.dry_run and not (token and chat):
        print("Secrets Telegram manquants : TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID.")
        return 1
    raw_url = args.raw_url
    if raw_url is None and env.get("GITHUB_REPOSITORY"):
        raw_url = RAW_TEMPLATE % env["GITHUB_REPOSITORY"]

    start = now()
    end = start.timestamp() + args.duration
    state = alert_state.load_state(args.state, start.date().isoformat())
    before = json.loads(json.dumps(state))
    code, failures, down_sent, cycles = 0, 0, False, 0
    _say("démarrage : %d s, un tour toutes les %d s%s." % (
        args.duration, args.interval, " (essai à blanc)" if args.dry_run else ""))

    while True:
        cycles += 1
        rules, updated = get_rules(args.alerts, raw_url)
        gold = [r for r in rules or [] if r.get("symbol") in SYMBOL_MAP]
        wait = args.interval if gold else IDLE_S
        if gold:
            symbols = sorted({SYMBOL_MAP[r["symbol"]] for r in gold})
            try:
                by_td = {s: get_bars(key, s) for s in symbols}
                failures = 0
            except FeedError as e:
                failures += 1
                _say("flux en échec (%s), %d de suite." % (e, failures))
                by_td = None
                if e.quota:
                    wait = QUOTA_BACKOFF_S
            if by_td is None:
                if failures >= DOWN_AFTER and not down_sent and not args.dry_run:
                    down_sent = True
                    sent, reason = send(token, chat, down_message())
                    if not sent:
                        _say("envoi Telegram échoué (%s)." % reason)
                        code = 1
            else:
                bars = {r["symbol"]: by_td[SYMBOL_MAP[r["symbol"]]] for r in gold}
                hits, log = alert_checks.touched_rules(gold, bars, state, updated)
                for line in log:
                    _say(line)
                for h in hits:
                    h["bar_label"] = BAR_LABEL
                    text = alert_messages.touch_message(h)
                    if args.dry_run:
                        print("---\n%s\n---" % text)
                        continue
                    sent, reason = send(token, chat, text)
                    if not sent:
                        _say("envoi Telegram échoué (%s) : nouvel essai au prochain tour." % reason)
                        code = 1
                        continue
                    state["rules_fired"].append(alert_checks.rule_key(h["rule"]))
                    try:
                        alert_state.save_state(args.state, state)
                    except journal.JournalError as e:
                        _say("état non sauvegardé : %s" % e)
                if cycles == 1 or cycles % 10 == 0:
                    age = (now().timestamp() - by_td[symbols[0]][-1][0]) / 60
                    _say("tour %d : %d règle(s) or, dernière barre il y a %.1f min." % (
                        cycles, len(gold), age))
        elif cycles == 1 or cycles % 10 == 0:
            _say("tour %d : aucune règle sur l'or, pas d'appel au fournisseur." % cycles)
        if args.once or now().timestamp() + wait >= end:
            break
        sleep(wait)

    _write_output(env, state != before)
    return code


if __name__ == "__main__":
    sys.exit(main())
