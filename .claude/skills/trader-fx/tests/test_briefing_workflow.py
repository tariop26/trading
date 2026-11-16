import _path  # noqa
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "briefing.yml")
ACTIONS = {"actions/checkout@v6", "actions/upload-pages-artifact@v5", "actions/deploy-pages@v5"}
RUNNER = "python3 .claude/skills/trader-fx/briefing_run.py"
DRY_IF = "if: ${{ inputs.dry_run != true }}"


def read_workflow():
    with open(WORKFLOW, encoding="utf-8") as f:
        return f.read()


class TestBriefingWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = read_workflow()
        self.lines = self.text.splitlines()
        self.steps = re.split(r"(?m)^      - ", self.text.split("    steps:\n", 1)[1])[1:]

    def step(self, needle):
        found = [s for s in self.steps if needle in s]
        self.assertEqual(len(found), 1, needle)
        return found[0]

    def test_the_two_schedules_are_exact_and_there_are_no_others(self):
        crons = re.findall(r'^\s*- cron: "([^"]+)"\s*$', self.text, re.M)
        self.assertEqual(crons, ["30 4 * * 1-5", "15 22 * * 0-4"])

    def test_manual_run_has_a_boolean_dry_run_input_off_by_default(self):
        self.assertRegex(self.text, r"(?m)^  workflow_dispatch:\n    inputs:\n      dry_run:")
        block = self.text.split("dry_run:", 1)[1].split("permissions:", 1)[0]
        self.assertIn("type: boolean", block)
        self.assertIn("default: false", block)

    def test_concurrency_does_not_cancel_a_running_job(self):
        self.assertRegex(self.text, r"(?m)^concurrency:\n  group: briefing\n  cancel-in-progress: false$")

    def test_workflow_permissions_are_read_only_and_pages_rights_live_in_the_job(self):
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read$")
        top, jobs = self.text.split("\njobs:\n", 1)
        self.assertNotIn("pages: write", top)
        self.assertNotIn("id-token: write", top)
        self.assertEqual(jobs.count("pages: write"), 1)
        self.assertEqual(jobs.count("id-token: write"), 1)

    def test_one_job_with_the_pages_environment_and_a_timeout(self):
        self.assertEqual(re.findall(r"(?m)^  (\w[\w-]*):$", self.text.split("\njobs:\n", 1)[1]), ["publish"])
        self.assertIn("    timeout-minutes: 10\n", self.text)
        self.assertRegex(self.text, r"(?m)^    environment:\n      name: github-pages\n")

    def test_actions_are_pinned_to_the_expected_versions(self):
        used = re.findall(r"^\s*(?:- )?uses: (\S+)\s*$", self.text, re.M)
        self.assertEqual(set(used), ACTIONS)
        self.assertEqual(len(used), 3)

    def test_steps_run_in_order_checkout_build_upload_deploy_notify_then_the_failure_notice(self):
        names = [s for s in self.steps]
        order = [next(i for i, s in enumerate(names) if needle in s)
                 for needle in ("actions/checkout", "briefing_run.py build", "upload-pages-artifact",
                                "actions/deploy-pages", "briefing_run.py notify", "briefing_run.py fail")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(len(set(order)), 6)
        self.assertEqual(len(names), 6)

    def test_a_publication_failure_is_announced_once_and_never_after_a_build_failure(self):
        self.assertIn("id: upload", self.step("upload-pages-artifact"))
        fail = self.step("briefing_run.py fail")
        # always(): the earlier step failed; only an upload or deploy failure (a failed build has
        # already sent its own notice and never reaches those steps)
        self.assertIn("always()", fail)
        self.assertIn("inputs.dry_run != true", fail)
        self.assertIn("steps.upload.outcome == 'failure'", fail)
        self.assertIn("steps.deployment.outcome == 'failure'", fail)
        self.assertNotIn("steps.build", fail)
        self.assertIn(RUNNER + ' fail --reason "publication sur GitHub Pages en échec"', fail)
        self.assertIn("TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}", fail)
        self.assertIn("TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}", fail)
        self.assertNotIn("TRADER_FX_CONFIG", fail)

    def test_upload_deploy_and_notify_are_skipped_on_a_dry_run(self):
        for needle in ("upload-pages-artifact", "actions/deploy-pages", "briefing_run.py notify"):
            self.assertIn(DRY_IF, self.step(needle), needle)
        self.assertNotIn("inputs.dry_run", self.step("actions/checkout"))
        self.assertNotIn(DRY_IF, self.step("briefing_run.py build"))

    def test_the_upload_publishes_only_the_site_folder(self):
        self.assertRegex(self.step("upload-pages-artifact"), r"path: site\n?$")

    def test_the_build_step_passes_dry_run_on_demand(self):
        build = self.step("briefing_run.py build")
        self.assertIn("DRY_RUN: ${{ inputs.dry_run }}", build)
        self.assertIn(RUNNER + " build --out-dir site --dry-run", build)
        self.assertIn(RUNNER + " build --out-dir site\n", build)

    def test_the_page_url_reaches_notify_through_env_not_the_script_line(self):
        deploy = self.step("actions/deploy-pages")
        self.assertIn("id: deployment", deploy)
        notify = self.step("briefing_run.py notify")
        self.assertIn("PAGE_URL: ${{ steps.deployment.outputs.page_url }}", notify)
        self.assertIn(RUNNER + ' notify --url "$PAGE_URL"', notify)
        run_lines = [l for l in notify.splitlines() if l.strip().startswith("run:")]
        self.assertEqual(len(run_lines), 1)
        self.assertNotIn("${{", run_lines[0])

    def test_secrets_are_read_only_through_env_and_never_echoed(self):
        refs = [l for l in self.lines if "secrets." in l]
        self.assertEqual(len(refs), 7, refs)                          # three in build, two in notify, two in fail
        for line in refs:
            self.assertRegex(line, r"^\s{10}[A-Z_]+: \$\{\{ secrets\.[A-Z_]+ \}\}$")
        for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TRADER_FX_CONFIG"):
            self.assertIn("%s: ${{ secrets.%s }}" % (name, name), self.step("briefing_run.py build"))
        self.assertNotIn("TRADER_FX_CONFIG", self.step("briefing_run.py notify"))
        self.assertNotIn("echo", self.text)
        self.assertNotIn("set -x", self.text)
        self.assertNotIn("continue-on-error", self.text)

    def test_the_runner_script_exists(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, ".claude", "skills", "trader-fx", "briefing_run.py")))

    def test_site_is_ignored_by_git(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            self.assertIn("site/", [l.strip() for l in f])


if __name__ == "__main__":
    unittest.main()
