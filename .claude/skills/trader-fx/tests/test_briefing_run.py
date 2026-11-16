import _path  # noqa
import contextlib
import copy
import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import briefing
import briefing_run
import fx
import page

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "briefing_sample.json")
NOW = datetime(2026, 11, 16, 4, 30, tzinfo=timezone.utc)
FORBIDDEN = re.compile(r"(?i)\b(achat|acheter|vente|vendre|buy|sell)\b")
SECRET_CONFIG = '{"account": {"currency": "USD", "capital": 250000}}'
URL = "https://tariop26.github.io/trading/"


def load_doc():
    with open(FIXTURE, encoding="utf-8-sig") as f:
        return json.load(f)


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


class Harness(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.site = os.path.join(self.dir, "site")
        self.config = os.path.join(self.dir, "config.json")
        self.doc = load_doc()
        self.brief_result = None                    # None: (self.doc, "")
        self.brief_raises = None
        self.brief_calls, self.sent = [], []
        self.env = {"TELEGRAM_BOT_TOKEN": "tok-SECRET", "TELEGRAM_CHAT_ID": "42"}
        self.send_result = (True, None)

    def deps(self, now=NOW):
        def brief(config_path):
            self.brief_calls.append(config_path)
            if self.brief_raises:
                raise self.brief_raises
            return self.brief_result if self.brief_result is not None else (self.doc, "")

        def send(token, chat, text):
            self.sent.append((token, chat, text))
            return self.send_result

        return {"brief": brief, "send": send, "now": lambda: now, "env": self.env}

    def run_main(self, *argv, now=NOW):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = briefing_run.main(list(argv), self.deps(now))
        self.output = out.getvalue() + err.getvalue()
        return code

    def build(self, *extra, now=NOW):
        return self.run_main("build", "--out-dir", self.site, "--config", self.config, *extra, now=now)


class TestMessages(unittest.TestCase):
    def test_title(self):
        self.assertEqual(briefing_run.title(NOW), "Briefing marchés, 2026-11-16 04:30 UTC.")

    def test_failure_message_strips_one_final_period_and_clips_the_reason(self):
        self.assertEqual(
            briefing_run.failure_message(NOW, "Aucun symbole reçu sur 104 demandés : pas de briefing écrit."),
            "Briefing indisponible (2026-11-16 04:30 UTC) : Aucun symbole reçu sur 104 demandés : "
            "pas de briefing écrit. La page précédente reste en ligne.")
        reason = briefing_run.failure_message(NOW, "x" * 500).split(" : ", 1)[1]
        self.assertEqual(reason, "x" * 200 + ". La page précédente reste en ligne.")


class TestRunBrief(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def fake_main(self, code=0, line=None, raises=None, write=True):
        def main(argv, deps=None):
            self.argv = list(argv)
            if raises:
                raise raises
            if line:
                print(line)
            if write:
                out = argv[argv.index("--out") + 1]
                with open(out, "w", encoding="utf-8") as f:
                    json.dump({"market_state": "open"}, f)
            return code
        return main

    def run_it(self, config_path, **kw):
        with mock.patch.object(briefing_run.fx, "main", self.fake_main(**kw)):
            return briefing_run.run_brief(config_path)

    def test_success_returns_the_document(self):
        doc, reason = self.run_it(os.path.join(self.dir, "none.json"))
        self.assertEqual((doc, reason), ({"market_state": "open"}, ""))
        self.assertEqual(self.argv[:2], ["brief", "--no-cache"])
        self.assertNotIn("--config", self.argv)

    def test_the_config_path_is_passed_only_when_the_file_exists(self):
        cfg = os.path.join(self.dir, "config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write("{}")
        self.run_it(cfg)
        self.assertEqual(self.argv[self.argv.index("--config") + 1], cfg)

    def test_a_failure_gives_the_last_printed_line(self):
        doc, reason = self.run_it("x.json", code=1, line="Aucun symbole reçu.", write=False)
        self.assertEqual((doc, reason), (None, "Aucun symbole reçu."))
        doc, reason = self.run_it("x.json", code=1, write=False)
        self.assertEqual((doc, reason), (None, "briefing impossible"))

    def test_an_exception_is_reported_by_type_only(self):
        doc, reason = self.run_it("x.json", raises=ValueError("detail 987654"))
        self.assertEqual((doc, reason), (None, "briefing en échec (ValueError)"))

    def test_unreadable_output_is_a_failure(self):
        def main(argv, deps=None):
            with open(argv[argv.index("--out") + 1], "w", encoding="utf-8") as f:
                f.write("{")
            return 0
        with mock.patch.object(briefing_run.fx, "main", main):
            self.assertEqual(briefing_run.run_brief("x.json"), (None, "briefing illisible"))


class TestBuild(Harness):
    def test_build_writes_the_exact_page_and_the_summary(self):
        self.assertEqual(self.build(), 0, self.output)
        self.assertEqual(read(os.path.join(self.site, "index.html")),
                         page.render_page(self.doc, fx.TEMPLATE))
        self.assertEqual(read(os.path.join(self.site, "summary.txt")),
                         briefing.render_summary(self.doc) + "\n")
        self.assertEqual(self.sent, [])                          # `build` never announces a success

    def test_closed_weekend_is_published_normally(self):
        self.doc["market_state"] = "closed_weekend"
        self.assertEqual(self.build(), 0, self.output)
        self.assertTrue(os.path.exists(os.path.join(self.site, "index.html")))

    def test_missing_telegram_secrets_do_not_stop_a_successful_build(self):
        self.env.clear()
        self.assertEqual(self.build(), 0, self.output)
        self.assertTrue(os.path.exists(os.path.join(self.site, "index.html")))

    def test_config_secret_is_written_validated_and_never_printed(self):
        self.env["TRADER_FX_CONFIG"] = SECRET_CONFIG
        self.assertEqual(self.build(), 0, self.output)
        self.assertEqual(json.loads(read(self.config))["account"]["capital"], 250000)
        self.assertEqual(self.brief_calls, [self.config])
        self.assertNotIn("250000", self.output)

    def test_an_invalid_secret_is_one_line_exit_1_and_no_value(self):
        for bad in ('{"account": {"capital": -123456}}', "not json 123456"):
            self.setUp()
            self.env["TRADER_FX_CONFIG"] = bad
            self.assertEqual(self.build(), 1)
            self.assertEqual(len(self.output.strip().splitlines()), 1, self.output)
            self.assertNotIn("123456", self.output)
            self.assertIn("TRADER_FX_CONFIG", self.output)
            self.assertFalse(os.path.exists(self.site))
            self.assertEqual((self.sent, self.brief_calls), ([], []))


class TestBuildFailures(Harness):
    def test_brief_failure_writes_nothing_sends_one_failure_message_exit_1(self):
        self.brief_result = (None, "Aucun symbole reçu sur 104 demandés : pas de briefing écrit.")
        self.assertEqual(self.build(), 1)
        self.assertFalse(os.path.exists(self.site))
        self.assertEqual(self.sent, [("tok-SECRET", "42", briefing_run.failure_message(
            NOW, "Aucun symbole reçu sur 104 demandés : pas de briefing écrit."))])
        self.assertIn("Briefing indisponible", self.output)

    def test_an_exception_in_the_brief_is_a_failure_with_the_type_only(self):
        self.brief_raises = ZeroDivisionError("secret detail 987654")
        self.assertEqual(self.build(), 1)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("briefing en échec (ZeroDivisionError)", self.sent[0][2])
        self.assertNotIn("987654", self.sent[0][2] + self.output)

    def test_a_page_or_summary_that_cannot_be_built_is_a_failure(self):
        del self.doc["counts"]                                    # render_summary needs it
        self.assertEqual(self.build(), 1)
        self.assertFalse(os.path.exists(self.site))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Briefing indisponible", self.sent[0][2])

    def test_write_failure_leaves_no_partial_site(self):
        os.makedirs(os.path.join(self.site, "summary.txt"))       # the second file cannot be written
        self.assertEqual(self.build(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.site, "index.html")))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("écriture impossible", self.sent[0][2])

    def test_missing_telegram_secrets_on_failure_say_the_notice_could_not_be_sent(self):
        self.env.clear()
        self.brief_result = (None, "Aucun symbole reçu.")
        self.assertEqual(self.build(), 1)
        self.assertEqual(self.sent, [])
        lines = self.output.strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("Briefing indisponible", lines[0])
        self.assertIn("non envoyé", lines[0])

    def test_a_failed_failure_notice_is_one_more_line_and_the_exit_stays_1(self):
        self.brief_result = (None, "Aucun symbole reçu.")
        self.send_result = (False, "HTTP 500")
        self.assertEqual(self.build(), 1)
        self.assertIn("HTTP 500", self.output)
        self.assertNotIn("SECRET", self.output)


class TestDryRun(Harness):
    def test_dry_run_writes_nothing_and_sends_nothing_but_shows_the_summary(self):
        self.assertEqual(self.build("--dry-run"), 0, self.output)
        self.assertFalse(os.path.exists(self.site))
        self.assertEqual(self.sent, [])
        self.assertIn("Briefing FX", self.output)

    def test_dry_run_on_a_failure_prints_the_notice_and_exits_1(self):
        self.brief_result = (None, "Aucun symbole reçu.")
        self.assertEqual(self.build("--dry-run"), 1)
        self.assertEqual(self.sent, [])
        self.assertIn("Briefing indisponible (2026-11-16 04:30 UTC) : Aucun symbole reçu.", self.output)


class TestEverything(Harness):
    def test_no_forbidden_word_or_secret_in_any_message_or_output(self):
        self.assertTrue(FORBIDDEN.search("un achat"))
        self.assertFalse(FORBIDDEN.search("survente"))
        self.brief_result = (None, "Aucun symbole reçu.")
        self.build()
        for text in [m[2] for m in self.sent] + [self.output]:
            self.assertIsNone(FORBIDDEN.search(text), text)
            self.assertNotIn("SECRET", text)
            self.assertNotIn("à prendre", text)

    def test_a_bad_now_is_one_line_exit_1(self):
        self.assertEqual(self.build("--now", "yesterday"), 1)
        self.assertEqual(len(self.output.strip().splitlines()), 1)

    def test_now_option_sets_the_title_time(self):
        self.brief_result = (None, "x")
        self.build("--now", "2026-11-16 22:15")
        self.assertIn("(2026-11-16 22:15 UTC)", self.sent[0][2])


class TestSuccessMessage(unittest.TestCase):
    HEAD = "Briefing marchés, 2026-11-16 04:30 UTC.\nPage : " + URL

    def test_the_link_comes_before_the_summary(self):
        self.assertEqual(briefing_run.success_message(NOW, URL, "Ligne 1\nLigne 2\n"),
                         self.HEAD + "\n\nLigne 1\nLigne 2")

    def test_an_empty_summary_gives_the_title_and_the_link_only(self):
        for summary in ("", "\n", "  \n"):
            self.assertEqual(briefing_run.success_message(NOW, URL, summary), self.HEAD)

    def test_a_10000_character_summary_is_clipped_under_4096_and_keeps_the_link(self):
        text = briefing_run.success_message(NOW, URL, "x" * 10000)
        self.assertLessEqual(len(text), briefing_run.TELEGRAM_CLIP)
        self.assertLess(len(text), 4096)
        self.assertTrue(text.startswith(self.HEAD + "\n\n"))
        self.assertTrue(text.endswith("…"))

    def test_special_characters_stay_as_they_are(self):
        summary = 'Core <CPI> & "m/m" <!-- x'
        self.assertTrue(briefing_run.success_message(NOW, URL, summary).endswith(summary))

    def test_a_summary_just_under_the_limit_is_not_clipped(self):
        room = briefing_run.TELEGRAM_CLIP - len(self.HEAD + "\n\n")
        text = briefing_run.success_message(NOW, URL, "y" * room)
        self.assertEqual(len(text), briefing_run.TELEGRAM_CLIP)
        self.assertFalse(text.endswith("…"))


class TestNotify(Harness):
    def setUp(self):
        super().setUp()
        self.summary = os.path.join(self.dir, "summary.txt")
        with open(self.summary, "w", encoding="utf-8") as f:
            f.write("Briefing FX : 08:30 New York\nReçus : 104 sur 104\n")

    def notify(self, *extra, now=NOW):
        return self.run_main("notify", "--url", URL, "--summary-file", self.summary, *extra, now=now)

    def test_notify_sends_the_link_and_the_summary(self):
        self.assertEqual(self.notify(), 0, self.output)
        self.assertEqual(self.sent, [("tok-SECRET", "42", briefing_run.success_message(
            NOW, URL, "Briefing FX : 08:30 New York\nReçus : 104 sur 104\n"))])
        self.assertNotIn("SECRET", self.output)

    def test_missing_summary_file_is_one_line_exit_1(self):
        os.remove(self.summary)
        self.assertEqual(self.notify(), 1)
        self.assertEqual(len(self.output.strip().splitlines()), 1)
        self.assertIn(self.summary, self.output)
        self.assertEqual(self.sent, [])

    def test_empty_summary_file_still_sends_title_and_link(self):
        open(self.summary, "w").close()
        self.assertEqual(self.notify(), 0)
        self.assertEqual(self.sent[0][2], TestSuccessMessage.HEAD)

    def test_missing_telegram_secrets_exit_1_except_in_dry_run(self):
        self.env.clear()
        self.assertEqual(self.notify(), 1)
        self.assertEqual(self.sent, [])
        self.assertIn("TELEGRAM_BOT_TOKEN", self.output)
        self.assertEqual(self.notify("--dry-run"), 0)

    def test_send_failure_exit_1_without_the_token_in_the_output(self):
        self.send_result = (False, "HTTP 500")
        self.assertEqual(self.notify(), 1)
        self.assertIn("HTTP 500", self.output)
        self.assertNotIn("SECRET", self.output)
        self.assertEqual(len(self.output.strip().splitlines()), 1)

    def test_dry_run_prints_the_message_and_sends_nothing(self):
        self.assertEqual(self.notify("--dry-run"), 0)
        self.assertEqual(self.sent, [])
        self.assertIn("Page : " + URL, self.output)
        self.assertIn("Reçus : 104 sur 104", self.output)

    def test_the_url_is_required(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                briefing_run.main(["notify"], self.deps())

    def test_a_message_built_from_the_fixture_summary_has_no_forbidden_word(self):
        summary = briefing.render_summary(self.doc)
        text = briefing_run.success_message(NOW, URL, summary)
        self.assertIsNone(FORBIDDEN.search(text), text)
        self.assertLessEqual(len(text), briefing_run.TELEGRAM_CLIP)


if __name__ == "__main__":
    unittest.main()
