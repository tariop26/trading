import _path  # noqa
import os
import re
import unittest

import alerts_run

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "alerts.yml")
PINNED = {"actions/checkout@v6", "actions/cache/restore@v5", "actions/cache/save@v5"}


def read_workflow():
    with open(WORKFLOW, encoding="utf-8") as f:
        return f.read()


class TestAlertsWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = read_workflow()
        self.lines = self.text.splitlines()

    def test_schedule_is_every_15_minutes_in_session_on_weekdays_utc(self):
        crons = re.findall(r'^\s*- cron: "([^"]+)"\s*$', self.text, re.M)
        self.assertEqual(crons, ["7,22,37,52 7-21 * * 1-5"])

    def test_manual_run_has_a_boolean_dry_run_input(self):
        self.assertRegex(self.text, r"(?m)^  workflow_dispatch:\n    inputs:\n      dry_run:")
        block = self.text.split("dry_run:", 1)[1].split("permissions:", 1)[0]
        self.assertIn("type: boolean", block)
        self.assertIn("default: false", block)

    def test_concurrency_does_not_cancel_a_running_job(self):
        self.assertRegex(self.text, r"(?m)^concurrency:\n  group: alerts\n  cancel-in-progress: false$")

    def test_timeout_and_read_only_permissions(self):
        self.assertIn("    timeout-minutes: 10\n", self.text)
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read$")

    def test_actions_are_pinned_to_the_expected_versions(self):
        used = re.findall(r"^\s*(?:- )?uses: (\S+)\s*$", self.text, re.M)
        self.assertEqual(set(used), PINNED)
        self.assertEqual(len(used), 3)

    def test_secrets_are_read_only_through_env_and_never_echoed(self):
        refs = [l for l in self.lines if "secrets." in l]
        self.assertEqual(len(refs), 3, refs)
        for line in refs:
            self.assertRegex(line, r"^\s{10}[A-Z_]+: \$\{\{ secrets\.[A-Z_]+ \}\}$")
        for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TRADER_FX_CONFIG"):
            self.assertIn("%s: ${{ secrets.%s }}" % (name, name), self.text)
        self.assertNotIn("echo", self.text)
        self.assertNotIn("set -x", self.text)
        self.assertNotIn("continue-on-error", self.text)

    def test_the_state_cache_uses_one_key_per_run_and_restores_by_prefix(self):
        self.assertEqual(self.text.count("key: alerts-state-${{ github.run_id }}"), 2)
        self.assertIn("restore-keys: alerts-state-\n", self.text)
        paths = set(re.findall(r"^\s+path: (\S+)\s*$", self.text, re.M))
        self.assertEqual(paths, {alerts_run.DEFAULT_STATE})

    def test_the_state_is_saved_only_when_it_changed_even_after_a_failed_send(self):
        save = self.text.split("uses: actions/cache/save@v4", 1)[0].rsplit("- name:", 1)[1]
        self.assertIn("if: ${{ always() && steps.run.outputs.state_changed == 'true' }}", save)
        self.assertIn("id: run", self.text)

    def test_the_run_step_calls_the_runner_with_dry_run_on_demand(self):
        self.assertIn("python3 .claude/skills/trader-fx/alerts_run.py --dry-run", self.text)
        self.assertIn("python3 .claude/skills/trader-fx/alerts_run.py\n", self.text)
        self.assertIn('DRY_RUN: ${{ inputs.dry_run }}', self.text)
        self.assertTrue(os.path.exists(os.path.join(ROOT, ".claude", "skills", "trader-fx", "alerts_run.py")))

    def test_the_throwaway_probe_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".github", "workflows", "probe.yml")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "probe")))


if __name__ == "__main__":
    unittest.main()
