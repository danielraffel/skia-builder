#!/usr/bin/env python3
"""rebind-provenance.yml must only ever rebind an attested build-skia.yml run on main.

A branch run can carry edited tools, so its records could claim any license
or toolchain. These checks hold the workflow to the guards that stop such a
run being laundered into an attestation signed by rebind-provenance.yml@main.
"""
import pathlib
import unittest

import yaml

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "rebind-provenance.yml"


class RebindWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.workflow = yaml.safe_load(cls.text)
        # PyYAML reads the bare key `on` as True.
        cls.inputs = (cls.workflow.get("on") or cls.workflow[True])["workflow_dispatch"]["inputs"]
        cls.rebind = cls.workflow["jobs"]["rebind"]

    def step(self, name):
        return next(step for step in self.rebind["steps"] if step.get("name") == name)

    def test_the_rebuild_ref_is_never_an_input(self):
        self.assertNotIn("rebuild_ref", self.inputs)
        rebind = self.step("Rebind the rebuild's records to the published archive")
        self.assertEqual(rebind["env"]["REBUILD_REF"], "${{ steps.run.outputs.ref }}")

    def test_the_run_must_be_a_successful_main_build_skia_dispatch(self):
        script = self.step("Require a successful build-skia.yml run on main")["run"]
        for guard in ('run.get("path") != ".github/workflows/build-skia.yml"',
                      'run.get("head_branch") != "main"',
                      'run.get("event") != "workflow_dispatch"',
                      '"head_repository"',
                      'run.get("run_attempt") != int(os.environ["RUN_ATTEMPT"])',
                      'attempt.get("conclusion") != "success"'):
            self.assertIn(guard, script)

    def test_the_rebuild_attestation_is_verified_before_rebinding(self):
        names = [step.get("name") for step in self.rebind["steps"]]
        verify = names.index("Verify the rebuild's build-provenance attestation")
        self.assertLess(names.index("Require a successful build-skia.yml run on main"), verify)
        self.assertLess(verify, names.index("Rebind the rebuild's records to the published archive"))
        script = self.step("Verify the rebuild's build-provenance attestation")["run"]
        for flag in ("--source-ref refs/heads/main", "--deny-self-hosted-runners",
                     '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/build-skia.yml"'):
            self.assertIn(flag, script)
        self.assertIn('"rebuild/$stem/$ASSET" rebuild/"$stem"/provenance-assets/*.json', script)

    def test_only_the_attest_job_holds_an_oidc_grant(self):
        for name, job in self.workflow["jobs"].items():
            granted = (job.get("permissions") or {}).get("id-token") == "write"
            self.assertEqual(granted, name == "attest", name)


if __name__ == "__main__":
    unittest.main()
