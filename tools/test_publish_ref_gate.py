#!/usr/bin/env python3
"""Only main's copy of a workflow may write to a GitHub release.

A workflow_dispatch runs the workflow file of the ref it was dispatched on, so
a branch cut before a publish guard changed publishes with its own older copy
of that guard. Every job that CAN write to a release must therefore run only
when github.ref is refs/heads/main.

A job can write to a release when either:
  * its effective GITHUB_TOKEN has contents: write (job-level permissions, or
    inherited from the workflow), which covers releases whatever the job's
    scripts do, including scripts that call the REST API themselves; or
  * one of its steps writes a release explicitly (gh release create/upload/
    edit/delete, a mutating gh api call on a releases path, the release action,
    or the release asset guard), possibly with another token.

Such a job passes only if its `if:` carries the main gate, or it is listed in
ALLOWLIST with the reason it cannot run a branch's copy.
"""
from __future__ import annotations

import copy
import pathlib
import re
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
MAIN_GATE = "github.ref == 'refs/heads/main'"

# (workflow file, job) -> why the job can only ever run main's workflow file.
ALLOWLIST: dict[tuple[str, str], str] = {
    ("build-failure-watchdog.yml", "report"): (
        "triggered only by workflow_run, which always runs the default "
        "branch's workflow file, never a dispatching branch's"
    ),
}

RELEASE_WRITE_PATTERNS = (
    re.compile(r"\bgh\s+release\s+(create|upload|edit|delete|delete-asset)\b"),
    re.compile(r"softprops/action-gh-release"),
    re.compile(r"release_asset_guard\.py\s+--repo"),
    # gh api with a mutating method aimed at a releases path, in either order.
    re.compile(
        r"\bgh\s+api\b[^\n]*(-X|--method)\s*(PATCH|POST|PUT|DELETE)\b[^\n]*/releases\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bgh\s+api\b[^\n]*/releases\b[^\n]*(-X|--method)\s*(PATCH|POST|PUT|DELETE)\b",
        re.IGNORECASE,
    ),
)


def _contents_write(perms) -> bool:
    if perms == "write-all":
        return True
    return isinstance(perms, dict) and perms.get("contents") == "write"


def release_writer_reasons(wf: dict, job: dict) -> list[str]:
    reasons = []
    perms = job["permissions"] if "permissions" in job else wf.get("permissions")
    if _contents_write(perms):
        reasons.append("contents: write")
    for step in job.get("steps") or []:
        text = " ".join(
            str(step.get(key, "")) for key in ("run", "uses")
        ).replace("\\\n", " ")
        if any(p.search(text) for p in RELEASE_WRITE_PATTERNS):
            reasons.append(f"step {step.get('name') or step.get('uses') or '?'!r} writes a release")
    return reasons


def ungated(name: str, wf: dict) -> list[str]:
    bad = []
    for job_name, job in (wf.get("jobs") or {}).items():
        reasons = release_writer_reasons(wf, job)
        if not reasons or (name, job_name) in ALLOWLIST:
            continue
        if MAIN_GATE not in str(job.get("if", "")):
            bad.append(f"{job_name} ({'; '.join(reasons)})")
    return bad


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def all_workflows() -> dict[str, dict]:
    return {p.name: load(p) for p in sorted(WORKFLOWS.glob("*.yml"))}


class PublishRefGate(unittest.TestCase):
    def test_every_release_writer_is_gated_on_main(self) -> None:
        writers = 0
        for name, wf in all_workflows().items():
            writers += sum(
                1 for job in (wf.get("jobs") or {}).values()
                if release_writer_reasons(wf, job)
            )
            with self.subTest(workflow=name):
                self.assertEqual(ungated(name, wf), [])
        # create-release, the win-arm64 backfill, the XCFramework upload, the
        # matched-V8 link reconciler and the two watchdogs. Fewer means the
        # scan went blind.
        self.assertGreaterEqual(writers, 6)

    def test_allowlist_entries_exist(self) -> None:
        workflows = all_workflows()
        for (name, job), reason in ALLOWLIST.items():
            with self.subTest(workflow=name, job=job):
                self.assertTrue(reason.strip())
                self.assertIn(job, workflows[name]["jobs"])

    def test_removing_a_real_gate_is_caught(self) -> None:
        # Control on the real files: drop the main gate from each gated
        # writer in turn and the check must name that job.
        controls = [
            ("watch-skia.yml", "reconcile-matched-v8-links"),
            ("build-skia.yml", "publish-windows-arm64-backfill"),
            ("build-skia.yml", "create-release"),
            ("create-xcframework.yml", "create-xcframework"),
            ("build-progress-watchdog.yml", "report"),
        ]
        workflows = all_workflows()
        for name, job in controls:
            with self.subTest(workflow=name, job=job):
                wf = copy.deepcopy(workflows[name])
                cond = str(wf["jobs"][job].get("if", ""))
                self.assertIn(MAIN_GATE, cond)
                wf["jobs"][job]["if"] = cond.replace(MAIN_GATE, "true")
                self.assertTrue(any(b.startswith(f"{job} ") for b in ungated(name, wf)))

    def test_inherited_contents_write_is_a_writer(self) -> None:
        wf = yaml.safe_load(
            "permissions:\n  contents: write\n"
            "jobs:\n  reconcile:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: python3 tools/edit_notes.py\n"
        )
        self.assertEqual(len(ungated("x.yml", wf)), 1)
        wf["jobs"]["reconcile"]["permissions"] = {"contents": "read"}
        self.assertEqual(ungated("x.yml", wf), [])

    def test_explicit_release_writes_with_another_token(self) -> None:
        for run in (
            "gh release upload chrome/m1 a.zip --clobber",
            "gh api -X PATCH repos/o/r/releases/123 -f body=x",
            "gh api repos/o/r/releases/assets/9 --method DELETE",
        ):
            with self.subTest(run=run):
                wf = {"permissions": {"contents": "read"},
                      "jobs": {"j": {"steps": [{"run": run}]}}}
                self.assertEqual(len(ungated("x.yml", wf)), 1)
        # A read, or a mutating call elsewhere, is not a release write.
        for run in (
            "gh api repos/o/r/releases/tags/t --jq .assets",
            "gh api --method POST repos/o/other/dispatches --input -",
        ):
            with self.subTest(run=run):
                wf = {"permissions": {"contents": "read"},
                      "jobs": {"j": {"steps": [{"run": run}]}}}
                self.assertEqual(ungated("x.yml", wf), [])

    def test_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "wf.yml"
            path.write_text(
                "jobs:\n  publish:\n    if: ${{ !inputs.skip_release }}\n"
                "    runs-on: ubuntu-24.04\n    steps:\n"
                "      - run: gh release upload chrome/m1 a.zip --clobber\n",
                encoding="utf-8",
            )
            self.assertEqual(len(ungated("wf.yml", load(path))), 1)


if __name__ == "__main__":
    sys.exit(unittest.main())
