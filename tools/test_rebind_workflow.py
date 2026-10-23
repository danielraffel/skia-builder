#!/usr/bin/env python3
"""rebind-provenance.yml must only ever rebind an attested build-skia.yml run on main.

A branch run can carry edited tools, so its records could claim any license
or toolchain. The guard logic lives in tools/check_rebuild_run.py and is
tested here against real GitHub API records (testdata/rebuild-run/, captured
from run 39903006566 and a gh attestation verify of run 39920192131); the
workflow tests check that every guard is wired in, in order.
"""
import copy
import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "rebind-provenance.yml"
DATA = ROOT / "tools" / "testdata" / "rebuild-run"
REPO = "danielraffel/skia-builder"

spec = importlib.util.spec_from_file_location("check_rebuild_run", ROOT / "tools" / "check_rebuild_run.py")
check = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(check)


def fixture(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class RunGuardTests(unittest.TestCase):
    def setUp(self):
        # The captured run is a real branch dispatch; the "main" pair is the
        # same record with only its branch changed.
        self.branch_run = fixture("branch-run.json")
        self.branch_attempt = fixture("branch-run-attempt-2.json")
        self.run = copy.deepcopy(self.branch_run)
        self.run["head_branch"] = "main"
        self.attempt = copy.deepcopy(self.branch_attempt)
        self.attempt["head_branch"] = "main"

    def problems(self, run=None, attempt=None, requested=2):
        return check.run_problems(run or self.run, attempt or self.attempt, REPO, requested)

    def test_successful_main_dispatch_is_accepted(self):
        self.assertEqual(self.problems(), [])

    def test_the_real_branch_probe_is_refused(self):
        problems = self.problems(self.branch_run, self.branch_attempt)
        self.assertEqual(len(problems), 1)
        self.assertIn("not a dispatch on main", problems[0])

    def test_other_workflow_event_repository_or_attempt_is_refused(self):
        cases = {
            "path": (".github/workflows/lint.yml", "not .github/workflows/build-skia.yml"),
            "event": ("push", "not a dispatch on main"),
        }
        for field, (value, message) in cases.items():
            run = copy.deepcopy(self.run)
            run[field] = value
            self.assertTrue(any(message in p for p in self.problems(run=run)), field)
        run = copy.deepcopy(self.run)
        run["head_repository"]["full_name"] = "someone/fork"
        self.assertIn("run is from another repository", self.problems(run=run))
        self.assertTrue(any("not the run's latest" in p for p in self.problems(requested=1)))

    def test_failed_or_foreign_attempt_is_refused(self):
        attempt = copy.deepcopy(self.attempt)
        attempt["conclusion"] = "failure"
        self.assertTrue(any("concluded 'failure'" in p for p in self.problems(attempt=attempt)))
        attempt = copy.deepcopy(self.attempt)
        attempt["id"] = 1
        self.assertTrue(any("does not belong" in p for p in self.problems(attempt=attempt)))
        attempt = copy.deepcopy(self.attempt)
        attempt["head_sha"] = "0" * 40
        self.assertTrue(any("head commit differs" in p for p in self.problems(attempt=attempt)))

    def test_a_rerun_during_the_download_is_refused(self):
        after = copy.deepcopy(self.run)
        self.assertEqual(check.same_problems(self.run, after), [])
        after["run_attempt"] = 3
        self.assertEqual(len(check.same_problems(self.run, after)), 1)

    def test_cli_writes_ref_and_head_only_when_accepted(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="rebind-run-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name, value in (("run.json", self.run), ("attempt.json", self.attempt),
                            ("branch.json", self.branch_run)):
            (tmp / name).write_text(json.dumps(value))
        out = tmp / "out"
        out.write_text("")
        self.assertEqual(check.main(["run", str(tmp / "run.json"), str(tmp / "attempt.json"),
                                     "--repository", REPO, "--attempt", "2", "--github-output", str(out)]), 0)
        self.assertEqual(out.read_text(), f"ref=refs/heads/main\nhead_sha={self.run['head_sha']}\n")
        out.write_text("")
        self.assertEqual(check.main(["run", str(tmp / "branch.json"), str(tmp / "attempt.json"),
                                     "--repository", REPO, "--attempt", "2", "--github-output", str(out)]), 1)
        self.assertEqual(out.read_text(), "")


class InvocationGuardTests(unittest.TestCase):
    """Against a real gh attestation verify result for run 39920192131 attempt 1."""

    RUN, ATTEMPT, HEAD = 39920192131, 1, "0091d97f17ae716f2fd5968e37a903224cd32b49"

    def setUp(self):
        self.results = fixture("verify-run-39920192131.json")

    def test_the_signing_run_attempt_and_commit_are_accepted(self):
        self.assertEqual(check.invocation_problems(self.results, REPO, self.RUN, self.ATTEMPT, self.HEAD), [])

    def test_another_attempt_run_or_commit_is_refused(self):
        self.assertTrue(check.invocation_problems(self.results, REPO, self.RUN, 2, self.HEAD))
        self.assertTrue(check.invocation_problems(self.results, REPO, 39903006566, self.ATTEMPT, self.HEAD))
        self.assertTrue(check.invocation_problems(self.results, REPO, self.RUN, self.ATTEMPT, "1" * 40))

    def test_self_hosted_or_empty_results_are_refused(self):
        results = copy.deepcopy(self.results)
        results[0]["verificationResult"]["signature"]["certificate"]["runnerEnvironment"] = "self-hosted"
        self.assertTrue(check.invocation_problems(results, REPO, self.RUN, self.ATTEMPT, self.HEAD))
        self.assertTrue(check.invocation_problems([], REPO, self.RUN, self.ATTEMPT, self.HEAD))


class RebindWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        # PyYAML reads the bare key `on` as True.
        cls.inputs = (cls.workflow.get("on") or cls.workflow[True])["workflow_dispatch"]["inputs"]
        cls.rebind = cls.workflow["jobs"]["rebind"]
        cls.names = [step.get("name") for step in cls.rebind["steps"]]

    def step(self, name):
        return next(step for step in self.rebind["steps"] if step.get("name") == name)

    def test_the_rebuild_ref_is_never_an_input(self):
        self.assertNotIn("rebuild_ref", self.inputs)
        rebind = self.step("Rebind the rebuild's records to the published archive")
        self.assertEqual(rebind["env"]["REBUILD_REF"], "${{ steps.run.outputs.ref }}")

    def test_guards_run_in_order(self):
        order = ["Require a successful build-skia.yml run on main", "Download the rebuild",
                 "Require the run unchanged after the download",
                 "Verify the rebuild's build-provenance attestation",
                 "Rebind the rebuild's records to the published archive"]
        self.assertEqual([name for name in self.names if name in order], order)
        self.assertIn("check_rebuild_run.py run", self.step(order[0])["run"])
        self.assertEqual(self.step(order[2])["run"].count("check_rebuild_run.py same"), 2)

    def test_the_attestation_is_bound_to_the_run(self):
        step = self.step("Verify the rebuild's build-provenance attestation")
        script = step["run"]
        for flag in ("--source-ref refs/heads/main", '--source-digest "$HEAD_SHA"',
                     "--deny-self-hosted-runners", "--format json",
                     '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/build-skia.yml"',
                     "check_rebuild_run.py invocation"):
            self.assertIn(flag, script)
        self.assertEqual(step["env"]["HEAD_SHA"], "${{ steps.run.outputs.head_sha }}")
        self.assertIn('"rebuild/$stem/$ASSET" rebuild/"$stem"/provenance-assets/*.json', script)

    def test_the_rebuild_bundle_is_recorded(self):
        script = self.step("Rebind the rebuild's records to the published archive")["run"]
        self.assertIn('--rebuild-bundle "${bundles[0]}"', script)
        self.assertIn("rebuild/skia-build-apple-attestation/", script)

    def test_only_the_attest_job_holds_an_oidc_grant(self):
        for name, job in self.workflow["jobs"].items():
            granted = (job.get("permissions") or {}).get("id-token") == "write"
            self.assertEqual(granted, name == "attest", name)


if __name__ == "__main__":
    unittest.main()
