#!/usr/bin/env python3
"""build-skia.yml's attest-apple subject listing finds every Apple cell.

download-artifact unpacks a lone matching artifact straight into its path, and
several into one directory each. Both layouts must list the cell's archive and
provenance records, or the attestation is silently skipped.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def listing_script() -> str:
    workflow = yaml.safe_load((REPO / ".github/workflows/build-skia.yml").read_text())
    for step in workflow["jobs"]["attest-apple"]["steps"]:
        if step.get("id") == "subjects":
            return step["run"]
    raise AssertionError("attest-apple has no `subjects` step")


def make_cell(root: Path, name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.zip").write_bytes(b"archive " + name.encode())
    (root / "provenance-assets").mkdir()
    (root / "provenance-assets" / f"{name}.legal-manifest.sha256-aa.json").write_text("{}\n")


class AttestSubjectsTest(unittest.TestCase):
    def run_listing(self, work: Path) -> tuple[str, str, str]:
        output = work / "github-output"
        summary = work / "summary"
        env = {**os.environ, "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)}
        subprocess.run(["bash", "-c", listing_script()], cwd=work, env=env, check=True,
                       capture_output=True, text=True)
        cells = (work / "cells.txt").read_text() if (work / "cells.txt").exists() else ""
        return output.read_text(), (work / "subjects.sha256").read_text(), cells

    def test_a_lone_cell_unpacked_into_the_path_is_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            make_cell(work / "cells", "skia-build-mac-universal-gpu-release")
            output, subjects, cells = self.run_listing(work)
            self.assertIn("present=true", output)
            self.assertIn("skia-build-mac-universal-gpu-release.zip", subjects)
            self.assertIn("skia-build-mac-universal-gpu-release.legal-manifest", subjects)
            self.assertEqual(cells.split(), ["skia-build-mac-universal-gpu-release"])

    def test_several_cells_each_in_their_own_directory_are_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            for name in ("skia-build-mac-universal-gpu-release", "skia-build-ios-gpu-release"):
                make_cell(work / "cells" / name, name)
            output, subjects, cells = self.run_listing(work)
            self.assertIn("present=true", output)
            self.assertEqual(sorted(cells.split()),
                             ["skia-build-ios-gpu-release", "skia-build-mac-universal-gpu-release"])
            self.assertEqual(subjects.count(".zip"), 2)

    def test_no_apple_cell_reports_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / "cells").mkdir()
            output, subjects, _ = self.run_listing(work)
            self.assertIn("present=false", output)
            self.assertEqual(subjects, "")


if __name__ == "__main__":
    unittest.main()
