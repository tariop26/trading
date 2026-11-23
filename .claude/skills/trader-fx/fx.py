#!/usr/bin/env python3
"""trader-fx command line. Subcommands: brief, page. Standard library only.

Run from the repo root (paths are relative to the working directory):
    python3 .claude/skills/trader-fx/fx.py brief [--list FILE ...] [--no-cache]
        [--json] [--now "YYYY-MM-DD HH:MM"] [--out PATH] [--config PATH]

    python3 .claude/skills/trader-fx/fx.py page [--in PATH] [--out PATH]

Exit code 0 when the briefing was produced, 1 otherwise, with one explanatory
line. No briefing.json is written when no symbol could be fetched. `page` turns
briefing.json into a static HTML page (no network call) and exits 1 with one line
when the JSON is missing or unreadable.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import briefing  # noqa: E402
import config as fxconfig  # noqa: E402
import data  # noqa: E402
import economic_calendar  # noqa: E402
import page  # noqa: E402

NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_LISTS = ("trader/lists/fx_pairs.txt", "trader/lists/commodities.txt",
                 "trader/lists/indices.txt")
LISTS_ENV = "TRADER_FX_LISTS"   # comma-separated list files, used when --list is not given
DEFAULT_OUT = "trader/fx/briefing.json"
DEFAULT_CONFIG = "trader/fx/config.json"
DEFAULT_PAGE = "trader/fx/briefing.html"
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_template.html")
CACHE_DIR = "trader/fx/cache"
WORKERS = 3  # parallel Yahoo requests (a cold run is ~85 s sequentially)


def parse_now(text):
    """'YYYY-MM-DD HH:MM' in New York time -> timezone-aware UTC datetime."""
    return (datetime.strptime(text, "%Y-%m-%d %H:%M")
            .replace(tzinfo=NEW_YORK).astimezone(timezone.utc))


def build_parser():
    p = argparse.ArgumentParser(prog="fx.py", description="trader-fx")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief", help="collecte, analyse et écrit le briefing")
    b.add_argument("--list", dest="lists", action="append", metavar="FILE",
                   help="liste SYMBOLE|nom (répétable ; défaut : les trois listes)")
    b.add_argument("--no-cache", action="store_true", help="ignore le cache disque")
    b.add_argument("--json", action="store_true",
                   help="JSON sur la sortie standard au lieu du résumé")
    b.add_argument("--now", help='heure de New York "YYYY-MM-DD HH:MM" (tests)')
    b.add_argument("--out", default=DEFAULT_OUT, help="fichier briefing.json")
    b.add_argument("--config", default=DEFAULT_CONFIG, metavar="PATH",
                   help="configuration des idées de trade (défaut : %s ; absent = valeurs "
                        "par défaut)" % DEFAULT_CONFIG)
    g = sub.add_parser("page", help="écrit la page HTML à partir de briefing.json")
    g.add_argument("--in", dest="inp", default=DEFAULT_OUT, help="fichier briefing.json")
    g.add_argument("--out", default=DEFAULT_PAGE, help="fichier HTML")
    return p


def _fail(msg):
    print(msg)
    return 1


def cmd_brief(args, deps):
    fetch_bars = deps.get("fetch_bars", data.fetch_bars)
    fetch_calendar = deps.get("fetch_calendar", economic_calendar.fetch_calendar)

    if args.now:
        try:
            now_utc = parse_now(args.now)
        except ValueError:
            return _fail('--now doit être au format "YYYY-MM-DD HH:MM" (heure de New York).')
    else:
        now_utc = datetime.now(timezone.utc)

    # before the lists and any network call. An explicit --config path must exist;
    # the default path may be absent (the defaults apply).
    if args.config != DEFAULT_CONFIG and not os.path.exists(args.config):
        return _fail("Fichier de configuration introuvable : %s." % args.config)
    config_source = "file" if args.config and os.path.exists(args.config) else "default"
    try:
        cfg = fxconfig.load_config(args.config)
    except fxconfig.ConfigError as e:
        return _fail(str(e))

    universe, seen = [], set()
    env_lists = [p.strip() for p in os.environ.get(LISTS_ENV, "").split(",") if p.strip()]
    for path in args.lists or env_lists or DEFAULT_LISTS:
        try:
            items = briefing.read_list(path)
        except (OSError, ValueError) as e:  # ValueError: UnicodeDecodeError
            return _fail("Liste illisible : %s (%s)." % (path, getattr(e, "strerror", None) or e))
        for sym, name in items:
            if sym not in seen:
                seen.add(sym)
                universe.append((sym, name))
    if not universe:
        return _fail("Aucun symbole à analyser dans les listes données.")

    use_cache = not args.no_cache
    daily, failed = fetch_bars([s for s, _ in universe], *data.DAILY,
                               cache_dir=CACHE_DIR, ttl_s=data.TTL_DAILY,
                               use_cache=use_cache, workers=WORKERS)
    if not daily:
        return _fail("Aucun symbole reçu sur %d demandés : pas de briefing écrit."
                     % len(universe))

    analyses = briefing.analyze_universe(universe, daily, now_utc)
    hits = [a for a in analyses if briefing.has_setup(a)]
    analysed = {a["symbol"] for a in analyses}
    alert = [s for s in briefing.alert_symbols(hits) if s in analysed]
    hourly, extra = {}, []
    if alert:
        hourly, _ = fetch_bars(alert, *data.HOURLY, cache_dir=CACHE_DIR,
                                     ttl_s=data.TTL_INTRADAY, use_cache=use_cache,
                                     workers=WORKERS)
        missing = [s for s in alert if s not in hourly]
        if missing:
            extra.append("Barres 1 h indisponibles pour %d symbole(s) en alerte (%s) : "
                         "plage asiatique non calculée." % (len(missing), briefing.join_names(missing)))

    calendar = fetch_calendar()
    b = briefing.build_briefing(universe, daily, failed, hourly, calendar, now_utc,
                                extra_warnings=extra, config=cfg,
                                config_source=config_source)

    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False, indent=2)
    except OSError as e:
        return _fail("Écriture impossible : %s (%s)." % (args.out, e.strerror or e))

    if args.json:
        print(json.dumps(b, ensure_ascii=True, indent=2))
    else:
        print(briefing.render_summary(b))
    return 0


def cmd_page(args):
    try:
        with open(args.inp, encoding="utf-8") as f:
            b = json.load(f)
    except OSError as e:
        return _fail("briefing.json introuvable : %s (%s). Lancer d'abord : fx.py brief."
                     % (args.inp, e.strerror or e))
    except ValueError as e:
        return _fail("briefing.json illisible : %s (%s)." % (args.inp, e))
    if not isinstance(b, dict):
        return _fail("briefing.json illisible : %s (objet JSON attendu)." % args.inp)
    try:
        html = page.render_page(b, TEMPLATE)
    except (OSError, ValueError) as e:
        return _fail("Gabarit inutilisable : %s." % e)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError as e:
        return _fail("Écriture impossible : %s (%s)." % (args.out, e.strerror or e))
    print("Page écrite : %s" % args.out)
    return 0


def _utf8_streams():
    """Piped output on Windows defaults to the ANSI code page: force UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv=None, deps=None):
    _utf8_streams()
    args = build_parser().parse_args(argv)
    if args.cmd == "brief":
        return cmd_brief(args, deps or {})
    if args.cmd == "page":
        return cmd_page(args)
    return _fail("Sous-commande inconnue : %s" % args.cmd)


if __name__ == "__main__":
    sys.exit(main())
