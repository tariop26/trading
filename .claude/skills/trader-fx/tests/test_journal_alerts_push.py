import _path  # noqa
import json
import os
import unittest

import journal
from test_journal_cli import CliCase

TRADE_ID = "2026-11-16-EURUSD-1"
OPEN = ["open", "--symbol", "EURUSD=X", "--side", "haussier", "--price", "1.1", "--lots", "1",
        "--stop", "1.095", "--target", "1.11", "--time", "2026-11-16 11:00"]


class FakeGit:
    """Records the git calls it receives; never touches a real repository."""

    def __init__(self, branch="main", porcelain="?? alerts.json\n", fail_on=None, missing=False):
        self.calls, self.branch, self.porcelain = [], branch, porcelain
        self.fail_on, self.missing = fail_on, missing

    def __call__(self, args):
        self.calls.append(list(args))
        if self.missing:
            return 127, ""
        if args[0] == "rev-parse":
            return 0, self.branch + "\n"
        if args[0] == "status":
            return 0, self.porcelain
        if args[0] == self.fail_on:
            return 1, ""
        return 0, ""


class PushCase(CliCase):
    def setUp(self):
        super().setUp()
        self.apath = os.path.join(self.dir, "alerts.json")
        self.cfg = os.path.join(self.dir, "config.json")

    def enable(self, value=True):
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump({"alerts": {"auto_push": value}}, f)

    def go(self, git, *args):
        # an explicit --config path must exist: pass it only once enable() wrote it
        extra = ["--config", self.cfg] if os.path.exists(self.cfg) else []
        return self.run_cli(*args, *extra, extra_deps={"run_git": git})

    def rules(self):
        with open(self.apath, encoding="utf-8") as f:
            return json.load(f)["rules"]


class TestAlertsFileRefresh(PushCase):
    def test_alerts_file_rewritten_after_open_amend_close(self):
        git = FakeGit()
        self.assertEqual(self.go(git, *OPEN)[0], 0)
        self.assertEqual([r["type"] for r in self.rules()], ["stop", "cible"])
        code, _ = self.go(git, "amend", TRADE_ID, "--stop", "1.098", "--time", "2026-11-16 12:00")
        self.assertEqual(code, 0)
        stop = [r for r in self.rules() if r["type"] == "stop"][0]
        self.assertEqual((stop["level"], stop["since"]), (1.098, "2026-11-16T11:00:00+00:00"))
        code, _ = self.go(git, "close", TRADE_ID, "--price", "1.105", "--pnl", "500",
                          "--time", "2026-11-16 13:00")
        self.assertEqual(code, 0)
        self.assertEqual(self.rules(), [])

    def test_default_path_is_alerts_json_next_to_the_journal(self):
        self.go(FakeGit(), *OPEN)
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(self.jpath), "alerts.json")))


class TestAutoPush(PushCase):
    def test_no_git_call_when_auto_push_is_false_or_absent(self):
        absent, off = FakeGit(), FakeGit()
        self.go(absent, *OPEN)                       # no config file at all
        self.enable(False)
        self.go(off, "amend", TRADE_ID, "--stop", "1.098", "--time", "2026-11-16 12:00")
        self.assertEqual((absent.calls, off.calls), ([], []))

    def test_auto_push_runs_add_commit_push_limited_to_the_file(self):
        self.enable()
        git = FakeGit()
        code, text = self.go(git, *OPEN)
        self.assertEqual(code, 0, text)
        self.assertEqual(git.calls, [
            ["rev-parse", "--abbrev-ref", "HEAD"],
            ["status", "--porcelain", "--", self.apath],
            ["add", "--", self.apath],
            ["commit", "-m", journal.ALERTS_COMMIT_MESSAGE, "--", self.apath],
            ["push"]])
        self.assertEqual(journal.ALERTS_COMMIT_MESSAGE, "alerts: règles de stop et de cible")
        for call in git.calls:
            self.assertFalse(any("journal.json" in part for part in call), call)
        self.assertNotIn("non poussé", text)

    def test_nothing_committed_when_the_file_did_not_change(self):
        self.enable()
        git = FakeGit(porcelain="")
        self.go(git, *OPEN)
        self.assertEqual([c[0] for c in git.calls], ["rev-parse", "status"])

    def test_no_push_off_main_says_why(self):
        self.enable()
        git = FakeGit(branch="feat/x")
        code, text = self.go(git, *OPEN)
        self.assertEqual(code, 0)
        self.assertEqual([c[0] for c in git.calls], ["rev-parse"])
        last = text.strip().splitlines()[-1]
        self.assertEqual(last, "alerts.json non poussé : branche courante feat/x, pas main. "
                               "Poussez-le à la main.")

    def test_commit_or_push_failure_keeps_the_trade_prints_one_warning_and_exits_0(self):
        self.enable()
        for failing, reason in (("commit", "git commit a échoué"), ("push", "git push a échoué"),
                                ("add", "git add a échoué")):
            self.setUp()
            self.enable()
            code, text = self.go(FakeGit(fail_on=failing), *OPEN)
            self.assertEqual(code, 0, text)
            self.assertEqual(len(self.stored()["trades"]), 1)
            lines = text.strip().splitlines()
            self.assertEqual(lines[-1], "alerts.json non poussé : %s. Poussez-le à la main." % reason)
            self.assertTrue(lines[0].startswith("Trade ouvert : "), lines[0])
            self.assertEqual(sum("non poussé" in x for x in lines), 1)

    def test_git_missing_gives_a_warning(self):
        self.enable()
        code, text = self.go(FakeGit(missing=True), *OPEN)
        self.assertEqual(code, 0)
        self.assertIn("alerts.json non poussé : git est introuvable.", text)
        self.assertEqual(len(self.stored()["trades"]), 1)

    def test_amend_and_close_publish_too(self):
        self.enable()
        git = FakeGit()
        self.go(git, *OPEN)
        git.calls.clear()
        self.go(git, "amend", TRADE_ID, "--stop", "1.098", "--time", "2026-11-16 12:00")
        self.assertEqual(git.calls[-1], ["push"])
        git.calls.clear()
        self.go(git, "close", TRADE_ID, "--price", "1.105", "--pnl", "500", "--time", "2026-11-16 13:00")
        self.assertEqual(git.calls[-1], ["push"])

    def test_a_failed_trade_command_publishes_nothing(self):
        self.enable()
        git = FakeGit()
        code, text = self.go(git, "close", "nope", "--price", "1.1", "--pnl", "1")
        self.assertEqual(code, 1)
        self.assertEqual(git.calls, [])
        self.assertFalse(os.path.exists(self.apath))


if __name__ == "__main__":
    unittest.main()
