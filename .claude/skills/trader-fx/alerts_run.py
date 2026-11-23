#!/usr/bin/env python3
"""One run of the alert server (GitHub Actions calls it every 15 minutes in session).

    python3 .claude/skills/trader-fx/alerts_run.py [--dry-run] [--state PATH] [--alerts PATH]
        [--config PATH] [--now "YYYY-MM-DD HH:MM"]

A run: reads the open positions (the published "Positions ouvertes" tab of the sheet when the
POSITIONS_CSV_URL secret is set, else trader/fx/alerts.json), runs the FundedNext risk guard (day
loss and account floor, see guard.py), checks the stop and target of the open trades on 5-minute
bars, looks at the coming high-impact announcements, reruns the briefing for new ideas, and sends
what is new to Telegram. A message is remembered (state file) only once Telegram answered 200.
Standard library only. Exit code 0, or 1 when a send failed, a secret is missing or invalid.
Secrets come from the environment and are never printed.
"""
import argparse
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alert_checks  # noqa: E402
import alert_messages  # noqa: E402
import alert_state  # noqa: E402
import briefing as fxbriefing  # noqa: E402
import config as fxconfig  # noqa: E402
import data  # noqa: E402
import economic_calendar  # noqa: E402
import fx  # noqa: E402
import gold_reverse  # noqa: E402
import guard  # noqa: E402
import intraday_run  # noqa: E402
import journal  # noqa: E402
import live_gold  # noqa: E402
import positions  # noqa: E402
import reversal  # noqa: E402
import sessions  # noqa: E402
import telegram  # noqa: E402

DEFAULT_STATE = "trader/fx/alerts_state.json"
DEFAULT_ALERTS = "trader/fx/alerts.json"
DEFAULT_CONFIG = "trader/fx/config.json"
WORKERS = 3
REVERSE_LIST_ENV = "TRADER_FX_REVERSE_LIST"   # list file of the assets with reversal levels
REVERSE_MAX_PER_RUN = 3                       # live reversal messages per run (plus the morning one)
MORNING_HOUR_PARIS = 6                        # the morning summary goes from 06:00 Paris
SETUP_D_ENV = "SETUP_D_GOLD"                  # "1": gold H4 reversal alerts (Twelve Data key needed)


def risk_per_trade(params, cfg):
    """Risk allowed per trade in USD: the sheet's figure, else the configuration's."""
    if params and params.get("risk_per_trade"):
        return params["risk_per_trade"]
    try:
        return cfg["account"]["capital"] * cfg["risk"]["per_trade_pct"] / 100.0
    except (KeyError, TypeError):
        return None


def setup_d_items(now, env, fetch_bars, fetch_gold_hourly, state, risk, events):
    """-> (queue items, log lines) of setup D (gold H4 reversal), never fatal for the caller."""
    key = env.get("TWELVE_DATA_API_KEY", "").strip()
    if env.get(SETUP_D_ENV, "").strip() != "1":
        return [], []
    if not key:
        return [], ["setup D : secret TWELVE_DATA_API_KEY absent, sauté"]
    try:
        hourly = fetch_gold_hourly(key)
    except live_gold.FeedError as e:
        return [], ["setup D : flux or indisponible (%s)" % e]
    daily, _ = fetch_bars(["GC=F"], *data.DAILY, cache_dir=None, ttl_s=0, use_cache=False,
                          workers=WORKERS)
    ts = now.timestamp()
    trend = None
    if "GC=F" in daily:
        trend = reversal.trend(reversal.completed(reversal.clean(daily["GC=F"].bars), ts,
                                                  reversal.DAY_S))
    news = alert_checks.news_blocked("GC=F", events, now)
    found, log = gold_reverse.alerts(hourly, ts, risk, trend, set(state.get("guard_sent", [])),
                                     now.date().isoformat(), news)
    return [(text, lambda st, k=k: st["guard_sent"].append(k)) for k, text in found], log


def reversal_items(now, env, fetch_bars, state, known_bars):
    """-> (queue items, log lines) for the reversal levels of the listed assets.

    The morning summary goes once a day, from MORNING_HOUR_PARIS; live alerts (flip level crossed,
    zone approached, SAR turned) go once each, at most REVERSE_MAX_PER_RUN per run."""
    path = env.get(REVERSE_LIST_ENV, "").strip()
    if not path:
        return [], []
    try:
        items = fxbriefing.read_list(path)
    except (OSError, ValueError):
        return [], ["liste des niveaux de reverse illisible : %s" % path]
    syms = [s for s, _ in items]
    if not syms:
        return [], []
    kw = dict(cache_dir=None, ttl_s=0, use_cache=False, workers=WORKERS)
    daily, _ = fetch_bars(syms, *data.DAILY, **kw)
    hourly, _ = fetch_bars(syms, "1h", "1mo", **kw)
    missing = [s for s in syms if s not in known_bars]
    recent = dict(known_bars)
    if missing:
        series, _ = fetch_bars(missing, *data.INTRADAY, **kw)
        recent.update(_bars_by_symbol(series))
    ts = now.timestamp()
    sent = set(state.get("guard_sent", []))
    day = now.date().isoformat()
    rows, live, log = [], [], []
    for sym, name in items:
        if sym not in daily:
            rows.append((name, None))
            log.append("niveaux de reverse : pas de barres journalières pour %s" % sym)
            continue
        lv = reversal.levels(daily[sym].bars, hourly[sym].bars if sym in hourly else [], ts)
        rows.append((name, lv))
        price = positions.last_price(recent.get(sym))[0]
        live += [(k, t) for k, t in reversal.live_alerts(sym, name, lv, price, day) if k not in sent]
    queue = []
    morning_key = "reverse|resume|%s" % day
    if morning_key not in sent and now.astimezone(sessions.PARIS).hour >= MORNING_HOUR_PARIS:
        queue.append((reversal.morning_message(rows),
                      lambda st, k=morning_key: st["guard_sent"].append(k)))
    for k, text in live[:REVERSE_MAX_PER_RUN]:
        queue.append((text, lambda st, k=k: st["guard_sent"].append(k)))
    if len(live) > REVERSE_MAX_PER_RUN:
        log.append("niveaux de reverse : %d alerte(s) reportée(s) au lancement suivant"
                   % (len(live) - REVERSE_MAX_PER_RUN))
    return queue, log


def _say(line):
    print("[alertes] " + line)


def _utf8_streams():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def build_parser():
    p = argparse.ArgumentParser(prog="alerts_run.py", description="un lancement du serveur d'alertes")
    p.add_argument("--dry-run", action="store_true",
                   help="affiche les messages sans rien envoyer ni mémoriser")
    p.add_argument("--state", default=DEFAULT_STATE)
    p.add_argument("--alerts", default=DEFAULT_ALERTS)
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--now", help='heure UTC "AAAA-MM-JJ HH:MM" (pour les essais)')
    return p


def _default_brief(config_path):
    """The briefing document, or None. Runs the existing `fx.py brief` in this process."""
    with tempfile.TemporaryDirectory() as folder:
        out = os.path.join(folder, "briefing.json")
        argv = ["brief", "--no-cache", "--out", out]
        if os.path.exists(config_path):
            argv += ["--config", config_path]
        with contextlib.redirect_stdout(io.StringIO()):
            code = fx.main(argv)
        if code != 0 or not os.path.exists(out):
            return None
        with open(out, encoding="utf-8") as f:
            return json.load(f)


def apply_config_secret(secret, path):
    """Write the TRADER_FX_CONFIG secret to `path` after validating it. -> an error line or None.
    The line never repeats the secret or any value from it."""
    try:
        fxconfig.validate(json.loads(secret))
    except (ValueError, fxconfig.ConfigError):
        return ("Le secret TRADER_FX_CONFIG est invalide (JSON ou valeurs hors bornes) : "
                "corrigez-le dans les réglages du dépôt.")
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(secret)
    except OSError:
        return "Impossible d'écrire la configuration issue du secret TRADER_FX_CONFIG."
    return None


def _read_alerts(path):
    """-> (valid rules, updated time) or (None, None) when the file cannot be used."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except OSError:
        _say("alerts.json absent : suivi des stops et annonces sautés.")
        return None, None
    except ValueError:
        _say("alerts.json illisible : suivi des stops et annonces sautés.")
        return None, None
    if not isinstance(doc, dict) or doc.get("v") != 1 or not isinstance(doc.get("rules"), list):
        _say("alerts.json invalide ou d'une autre version : suivi des stops et annonces sautés.")
        return None, None
    return doc["rules"], doc.get("updated")


def _future_event_keys(events, now):
    keys = set()
    for e in events:
        if isinstance(e, dict):
            try:
                start = datetime.fromisoformat(e["utc"])
            except (KeyError, TypeError, ValueError):
                continue
            if start.tzinfo is not None and start >= now:
                keys.add(alert_checks.event_key(e))
    return keys


def _bars_by_symbol(series):
    return {sym: s.bars for sym, s in series.items()}


def _write_output(env, changed):
    path = env.get("GITHUB_OUTPUT")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("state_changed=%s\n" % ("true" if changed else "false"))
        except OSError:
            _say("GITHUB_OUTPUT illisible : sortie state_changed non écrite.")


def main(argv=None, deps=None):
    _utf8_streams()
    deps = dict(deps or {})
    args = build_parser().parse_args(argv)
    env = deps.get("env", os.environ)
    fetch_bars = deps.get("fetch_bars", data.fetch_bars)
    fetch_calendar = deps.get("fetch_calendar", economic_calendar.fetch_calendar)
    brief = deps.get("brief", _default_brief)
    send = deps.get("send", telegram.send_message)
    fetch_positions = deps.get("fetch_positions", positions.fetch_csv)
    fetch_gold_hourly = deps.get("fetch_gold_hourly",
                                 lambda key: gold_reverse.fetch_hourly(key, live_gold._http_get))

    if args.now:
        try:
            now = datetime.strptime(args.now, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
        except ValueError:
            print('--now doit être au format "AAAA-MM-JJ HH:MM" (heure UTC).')
            return 1
    else:
        now = deps["now"]() if "now" in deps else datetime.now(timezone.utc)
    today = now.date().isoformat()

    token, chat = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if not args.dry_run and not (token and chat):
        print("Secrets Telegram manquants : TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID.")
        return 1

    # 1. configuration (the secret is optional)
    if env.get("TRADER_FX_CONFIG"):
        problem = apply_config_secret(env["TRADER_FX_CONFIG"], args.config)
        if problem:
            print(problem)
            return 1
    try:
        cfg = fxconfig.load_config(args.config)
    except fxconfig.ConfigError as e:
        print(str(e))
        return 1

    # 2. state and rules
    state = alert_state.load_state(args.state, today)
    before = copy.deepcopy(state)
    queue = []                                   # (text, mark(state)), in sending order

    # 2a. the sheet, when its tab is published: the source of the open positions
    book, pos_bars, offsets = None, {}, {}
    csv_url = env.get("POSITIONS_CSV_URL", "").strip()
    if csv_url:
        try:
            plist, params, problems = positions.parse_csv(fetch_positions(csv_url))
            for line in problems:
                _say("classeur : " + line)
            book = (plist, params)
        except positions.PositionsError as e:
            _say("classeur illisible (%s) : alerts.json utilisé, garde-fou sauté." % e)
            down_key = guard.key("classeur", today)
            if down_key not in state["guard_sent"]:
                queue.append((guard.csv_down_message(),
                              lambda st, k=down_key: st["guard_sent"].append(k)))
    if book is not None:
        plist, params = book
        symbols = sorted({p["symbol"] for p in plist})
        if symbols:
            series, _failed = fetch_bars(symbols, *data.INTRADAY, cache_dir=None, ttl_s=0,
                                         use_cache=False, workers=WORKERS)
            pos_bars = _bars_by_symbol(series)
        for p in plist:
            offsets[p["id"]] = positions.entry_offset(p, pos_bars.get(p["symbol"]))
            if offsets[p["id"]] is None:
                _say("écart CFD non mesuré pour %s %s : niveaux CFD utilisés tels quels."
                     % (p["asset"], p["id"]))
        rules, updated = positions.to_rules(plist, offsets), None
        # 2b. the FundedNext risk guard, sent first: it is the most urgent
        prices = {sym: positions.last_price(b)[0] for sym, b in pos_bars.items()}
        guard_msgs, summary = guard.evaluate(plist, params, prices, offsets, state, today)
        _say(summary)
        for text, keys in guard_msgs:
            queue.append((text, lambda st, ks=keys: st["guard_sent"].extend(ks)))
    else:
        rules, updated = _read_alerts(args.alerts)
        rules = [r for r in rules or [] if isinstance(r, dict)] if rules is not None else None
    have_rules = bool(rules)

    # 3. stops and targets
    hits, down = [], False
    if have_rules:
        if book is not None:
            bars = pos_bars
        else:
            symbols = sorted({r["symbol"] for r in rules if isinstance(r.get("symbol"), str)})
            series, _failed = fetch_bars(symbols, *data.INTRADAY, cache_dir=None, ttl_s=0,
                                         use_cache=False, workers=WORKERS)
            bars = _bars_by_symbol(series)
        hits, log = alert_checks.touched_rules(rules, bars, state, updated)
        for line in log:
            _say(line)
        down = not bars
        if down and state["down_notified_day"] != today:
            queue.append((alert_messages.down_message(),
                          lambda st: st.update(down_notified_day=today)))
        for h in hits:
            queue.append((alert_messages.touch_message(h),
                          lambda st, key=alert_checks.rule_key(h["rule"]): st["rules_fired"].append(key)))

    # 4. announcements
    events = []
    if have_rules:
        calendar = fetch_calendar()
        events = calendar.get("events") or []
        if not events:
            _say("calendrier indisponible : annonces non vérifiées.")
        for item in alert_checks.upcoming_events(events, rules, now, state):
            queue.append((alert_messages.event_message(item),
                          lambda st, key=alert_checks.event_key(item["event"]):
                          st["events_sent"].append(key)))

    # 5. ideas
    try:
        document = brief(args.config)
    except Exception as e:  # noqa: BLE001 - a briefing bug must not silence the stops: type only
        _say("briefing en échec (%s) : idées sautées." % type(e).__name__)
        document = None
    if document is None:
        _say("briefing indisponible : idées sautées.")
    else:
        ideas, waiting = alert_checks.new_ideas(document, rules or [], state, today)
        account = (document.get("trade_ideas") or {}).get("account") or {}
        for n, idea in enumerate(ideas):
            text = alert_messages.idea_message(idea, account, waiting if n == len(ideas) - 1 else 0)
            queue.append((text, lambda st, key=alert_checks.idea_key(idea, today):
                          st["ideas_sent"].append(key)))

    # 5a. reversal levels (morning summary and live alerts), never fatal
    try:
        rev_items, rev_log = reversal_items(now, env, fetch_bars, state, pos_bars)
    except Exception as e:  # noqa: BLE001 - a reversal bug must not silence stops: type only
        _say("niveaux de reverse en échec (%s) : sautés." % type(e).__name__)
        rev_items, rev_log = [], []
    for line in rev_log:
        _say(line)
    queue.extend(rev_items)

    # 5b. intraday signals (the calendar is read only if a candidate needs it, once)
    calendar_cache = []

    def get_events():
        if have_rules:
            return events
        if not calendar_cache:
            calendar_cache.append(fetch_calendar().get("events") or [])
        return calendar_cache[0]

    try:
        sig_items, sig_log = intraday_run.collect(now, document, get_events, rules or [], state,
                                                  cfg, fetch_bars, workers=WORKERS)
    except Exception as e:  # noqa: BLE001 - a signals bug must not silence stops or ideas: type only
        _say("signaux en séance en échec (%s) : sautés." % type(e).__name__)
        sig_items, sig_log = [], []
    for line in sig_log:
        _say(line)
    queue.extend(sig_items)

    # 5c. setup D, gold H4 reversal on a level (limit order plan), never fatal
    try:
        d_events = get_events() if env.get(SETUP_D_ENV, "").strip() == "1" else []
        d_items, d_log = setup_d_items(now, env, fetch_bars, fetch_gold_hourly, state,
                                       risk_per_trade(book[1] if book else None, cfg), d_events)
    except Exception as e:  # noqa: BLE001 - a setup D bug must not silence stops: type only
        _say("setup D en échec (%s) : sauté." % type(e).__name__)
        d_items, d_log = [], []
    for line in d_log:
        _say(line)
    queue.extend(d_items)

    # 6. sending
    code = 0
    for text, mark in queue:
        if args.dry_run:
            print("---\n%s\n---" % text)
            continue
        sent, reason = send(token, chat, text)
        if not sent:
            _say("envoi Telegram échoué (%s) : le message repartira au prochain lancement." % reason)
            code = 1
            break
        mark(state)

    if args.dry_run:
        _write_output(env, False)
        return code

    # prune what is gone, but only against sources we could actually read
    active = ({alert_checks.rule_key(r) for r in rules} if rules is not None
              else set(state["rules_fired"]))
    future = _future_event_keys(events, now) if events else set(state["events_sent"])
    state = alert_state.prune(state, active, future)
    changed = state != before
    if changed:
        try:
            alert_state.save_state(args.state, state)
        except journal.JournalError as e:
            _say("état non sauvegardé : %s" % e)
            code = 1
    _write_output(env, changed)
    return code


if __name__ == "__main__":
    sys.exit(main())
