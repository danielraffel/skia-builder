#!/usr/bin/env python3
"""Every job that writes to a GitHub release must run only from main.

A workflow_dispatch runs the workflow file of the ref it was dispatched on, so
a branch cut before a publish guard changed publishes with its own older copy
of that guard. Gating each release-writing job on refs/heads/main means only
reviewed workflow code can change published assets.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
MAIN_GATE = "github.ref == 'refs/heads/main'"
WRITES = (
    "gh release upload",
    "gh release create",
    "gh release edit",
    "gh release delete",
    "softprops/action-gh-release",
    "release_asset_guard.py --repo",
)


def release_writing_jobs(path: pathlib.Path) -> list[tuple[str, dict]]:
    wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    found = []
    for name, job in (wf.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            text = f"{step.get('run', '')}\n{step.get('uses', '')}"
            if any(marker in text for marker in WRITES):
                found.append((name, job))
                break
    return found


def ungated(path: pathlib.Path) -> list[str]:
    return [
        name
        for name, job in release_writing_jobs(path)
        if MAIN_GATE not in str(job.get("if", ""))
    ]


class PublishRefGate(unittest.TestCase):
    def test_every_release_writing_job_is_gated_on_main(self) -> None:
        checked = 0
        for path in sorted(WORKFLOWS.glob("*.yml")):
            checked += len(release_writing_jobs(path))
            with self.subTest(workflow=path.name):
                self.assertEqual(ungated(path), [])
        # The known publishers: create-release, the win-arm64 backfill, and
        # the standalone XCFramework upload. Fewer means the scan went blind.
        self.assertGreaterEqual(checked, 3)

    def test_an_ungated_publisher_is_reported(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            wf = pathlib.Path(td) / "wf.yml"
            wf.write_text(
                "jobs:\n"
                "  publish:\n"
                "    if: ${{ !inputs.skip_release }}\n"
                "    runs-on: ubuntu-24.04\n"
                "    steps:\n"
                "      - run: gh release upload chrome/m1 a.zip --clobber\n",
                encoding="utf-8",
            )
            self.assertEqual(ungated(wf), ["publish"])


if __name__ == "__main__":
    sys.exit(unittest.main())
