#!/usr/bin/env python3
"""The published briefing: builds the page for GitHub Pages and announces it on Telegram.

    python3 .claude/skills/trader-fx/briefing_run.py build  [--out-dir site] [--config PATH]
        [--dry-run] [--now "YYYY-MM-DD HH:MM"]
    python3 .claude/skills/trader-fx/briefing_run.py notify --url URL [--summary-file PATH]
        [--dry-run] [--now "YYYY-MM-DD HH:MM"]

`build` runs the existing briefing, writes `index.html` (the page) and `summary.txt` (the text
summary) to the output folder, and publishes nothing itself: a failed briefing leaves the folder
untouched and sends one Telegram line, so the page already online stays. `notify` sends the link
and the summary. Standard library only. Exit code 0, or 1 on any failure. Secrets come from the
environment and are never printed.
"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alerts_run  # noqa: E402
import briefing  # noqa: E402
import config as fxconfig  # noqa: E402
import fx  # noqa: E402
import page  # noqa: E402
import telegram  # noqa: E402

DEFAULT_OUT_DIR = "site"
DEFAULT_CONFIG = "trader/fx/config.json"
REASON_CLIP = 200


def _utf8_streams():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def title(now):
    return "Briefing marchés, %s UTC." % now.strftime("%Y-%m-%d %H:%M")


def failure_message(now, reason):
    reason = reason.strip()
    if reason.endswith("."):
        reason = reason[:-1]
    return "Briefing indisponible (%s UTC) : %s. La page précédente reste en ligne." % (
        now.strftime("%Y-%m-%d %H:%M"), reason[:REASON_CLIP])


def run_brief(config_path):
    """-> (briefing document, "") or (None, short reason). Runs `fx.py brief` in this process."""
    with tempfile.TemporaryDirectory() as folder:
        out = os.path.join(folder, "briefing.json")
        argv = ["brief", "--no-cache", "--out", out]
        if os.path.exists(config_path):
            argv += ["--config", config_path]
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                code = fx.main(argv)
        except Exception as e:  # noqa: BLE001 - the type only: a message could quote data
            return None, "briefing en échec (%s)" % type(e).__name__
        if code != 0 or not os.path.exists(out):
            lines = [x.strip() for x in captured.getvalue().splitlines() if x.strip()]
            return None, (lines[-1][:REASON_CLIP] if lines else "briefing impossible")
        try:
            with open(out, encoding="utf-8") as f:
                return json.load(f), ""
        except (OSError, ValueError):
            return None, "briefing illisible"


def build_parser():
    p = argparse.ArgumentParser(prog="briefing_run.py", description="briefing publié sur GitHub Pages")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("build",):
        s = sub.add_parser(name)
        s.add_argument("--dry-run", action="store_true")
        s.add_argument("--now", help='heure UTC "AAAA-MM-JJ HH:MM" (pour les essais)')
    b = sub.choices["build"]
    b.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    b.add_argument("--config", default=DEFAULT_CONFIG)
    return p


def _parse_now(text, deps):
    if text:
        return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    return deps["now"]() if "now" in deps else datetime.now(timezone.utc)


def _announce_failure(args, now, reason, env, send):
    """Send (or print, in a dry run) the failure notice; always an exit code of 1."""
    message = failure_message(now, reason)
    if args.dry_run:
        print(message)
        return 1
    token, chat = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        print("%s Message Telegram non envoyé : secrets manquants." % message)
        return 1
    sent, why = send(token, chat, message)
    if not sent:
        print("Message Telegram non envoyé (%s)." % why)
    else:
        print(message)
    return 1


def _write_site(out_dir, files):
    """Write every file or none: on failure what this call wrote is removed. -> an error or None."""
    created_dir = not os.path.isdir(out_dir)
    written = []
    try:
        os.makedirs(out_dir, exist_ok=True)
        for name, content in files:
            path = os.path.join(out_dir, name)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            written.append(path)
    except OSError:
        for path in written:
            with contextlib.suppress(OSError):
                os.remove(path)
        if created_dir:
            with contextlib.suppress(OSError):
                os.rmdir(out_dir)
        return "écriture impossible : %s" % out_dir
    return None


def cmd_build(args, now, env, brief, send):
    secret = env.get("TRADER_FX_CONFIG")
    if secret:
        problem = alerts_run.apply_config_secret(secret, args.config)
        if problem:
            print(problem)
            return 1
    try:
        fxconfig.load_config(args.config)
    except fxconfig.ConfigError as e:
        print(str(e))
        return 1

    try:
        document, reason = brief(args.config)
    except Exception as e:  # noqa: BLE001
        document, reason = None, "briefing en échec (%s)" % type(e).__name__
    if document is None:
        return _announce_failure(args, now, reason, env, send)

    try:
        files = [("index.html", page.render_page(document, fx.TEMPLATE)),
                 ("summary.txt", briefing.render_summary(document) + "\n")]
    except Exception as e:  # noqa: BLE001
        return _announce_failure(args, now, "page impossible (%s)" % type(e).__name__, env, send)

    if args.dry_run:
        print(files[1][1], end="")
        return 0
    problem = _write_site(args.out_dir, files)
    if problem:
        return _announce_failure(args, now, problem, env, send)
    print("Page écrite : %s (%d octets)." % (os.path.join(args.out_dir, "index.html"), len(files[0][1])))
    return 0


def main(argv=None, deps=None):
    _utf8_streams()
    deps = dict(deps or {})
    args = build_parser().parse_args(argv)
    env = deps.get("env", os.environ)
    try:
        now = _parse_now(args.now, deps)
    except ValueError:
        print('--now doit être au format "AAAA-MM-JJ HH:MM" (heure UTC).')
        return 1
    send = deps.get("send", telegram.send_message)
    if args.cmd == "build":
        return cmd_build(args, now, env, deps.get("brief", run_brief), send)
    print("Sous-commande inconnue : %s" % args.cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
