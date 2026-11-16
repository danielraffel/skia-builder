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


def listing_script(job: str = "attest-apple") -> str:
    workflow = yaml.safe_load((REPO / ".github/workflows/build-skia.yml").read_text())
    for step in workflow["jobs"][job]["steps"]:
        if step.get("id") == "subjects":
            return step["run"]
    raise AssertionError(f"{job} has no `subjects` step")


def make_cell(root: Path, name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.zip").write_bytes(b"archive " + name.encode())
    (root / "provenance-assets").mkdir()
    (root / "provenance-assets" / f"{name}.legal-manifest.sha256-aa.json").write_text("{}\n")
    (root / "provenance-assets" / f"{name}.apple-toolchain.sha256-bb.json").write_text("{}\n")


class AttestSubjectsTest(unittest.TestCase):
    job = "attest-apple"

    def run_listing(self, work: Path) -> tuple[str, str, str]:
        output = work / "github-output"
        summary = work / "summary"
        env = {**os.environ, "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)}
        subprocess.run(["bash", "-c", listing_script(self.job)], cwd=work, env=env, check=True,
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
            self.assertIn("skia-build-mac-universal-gpu-release.apple-toolchain", subjects)
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

    def test_an_unrecognised_layout_fails_instead_of_skipping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            make_cell(work / "cells", "skia-build-mac-universal-gpu-release")
            (work / "cells" / "skia-build-ios-gpu-release.zip").write_bytes(b"second")
            env = {**os.environ, "GITHUB_OUTPUT": str(work / "out"), "GITHUB_STEP_SUMMARY": str(work / "sum")}
            run = subprocess.run(["bash", "-c", listing_script(self.job)], cwd=work, env=env,
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("unrecognised cells/ layout", run.stdout)

    def test_a_lone_non_apple_cell_reports_absent(self) -> None:
        # A single-platform Windows, Linux or wasm dispatch unpacks one zip and no records.
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / "cells").mkdir()
            (work / "cells" / "skia-build-win-arm64-gpu-release.zip").write_bytes(b"archive")
            output, subjects, cells = self.run_listing(work)
            self.assertIn("present=false", output)
            self.assertEqual((subjects, cells), ("", ""))

    def test_lone_records_without_their_archive_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            make_cell(work / "cells", "skia-build-mac-universal-gpu-release")
            (work / "cells" / "skia-build-mac-universal-gpu-release.zip").unlink()
            env = {**os.environ, "GITHUB_OUTPUT": str(work / "out"), "GITHUB_STEP_SUMMARY": str(work / "sum")}
            run = subprocess.run(["bash", "-c", listing_script(self.job)], cwd=work, env=env,
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)

    def test_no_apple_cell_reports_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / "cells").mkdir()
            output, subjects, _ = self.run_listing(work)
            self.assertIn("present=false", output)
            self.assertEqual(subjects, "")


class AttestNativeSubjectsTest(AttestSubjectsTest):
    """attest-native lists the same layouts for Linux, Windows and wasm cells."""

    job = "attest-native"
    NATIVE = "skia-build-linux-x64-gpu-release"

    # The Apple tests above name Apple cells; the native job must ignore them.
    def test_a_lone_cell_unpacked_into_the_path_is_listed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            make_cell(work / "cells", self.NATIVE)
            output, subjects, cells = self.run_listing(work)
            self.assertIn("present=true", output)
            self.assertIn(f"{self.NATIVE}.zip", subjects)
            self.assertIn(f"{self.NATIVE}.legal-manifest", subjects)
            self.assertEqual(cells.split(), [self.NATIVE])

    def test_several_cells_each_in_their_own_directory_are_listed(self) -> None:
        names = ("skia-build-win-x64-gpu-release", "skia-build-win-x64-gpu-debug",
                 "skia-build-wasm-wasm32-gpu-release")
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            for name in names:
                make_cell(work / "cells" / name, name)
            output, subjects, cells = self.run_listing(work)
            self.assertIn("present=true", output)
            self.assertEqual(sorted(cells.split()), sorted(names))
            self.assertEqual(subjects.count(".zip"), 3)

    def test_an_unrecognised_layout_fails_instead_of_skipping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            make_cell(work / "cells", self.NATIVE)
            (work / "cells" / "skia-build-win-x64-gpu-debug.zip").write_bytes(b"second")
            env = {**os.environ, "GITHUB_OUTPUT": str(work / "out"), "GITHUB_STEP_SUMMARY": str(work / "sum")}
            run = subprocess.run(["bash", "-c", listing_script(self.job)], cwd=work, env=env,
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("unrecognised cells/ layout", run.stdout)

    def test_lone_records_without_their_archive_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            make_cell(work / "cells", self.NATIVE)
            (work / "cells" / f"{self.NATIVE}.zip").unlink()
            env = {**os.environ, "GITHUB_OUTPUT": str(work / "out"), "GITHUB_STEP_SUMMARY": str(work / "sum")}
            run = subprocess.run(["bash", "-c", listing_script(self.job)], cwd=work, env=env,
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)

    def test_a_lone_apple_cell_reports_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            make_cell(work / "cells", "skia-build-mac-universal-gpu-release")
            output, subjects, cells = self.run_listing(work)
            self.assertIn("present=false", output)
            self.assertEqual((subjects, cells), ("", ""))


class AppleJobIgnoresNativeCellsTest(unittest.TestCase):
    def test_a_native_cell_beside_an_apple_cell_is_not_attested_as_apple(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            for name in ("skia-build-mac-universal-gpu-release", "skia-build-linux-x64-gpu-release",
                         "skia-build-win-x64-gpu-debug"):
                make_cell(work / "cells" / name, name)
            env = {**os.environ, "GITHUB_OUTPUT": str(work / "out"), "GITHUB_STEP_SUMMARY": str(work / "sum")}
            subprocess.run(["bash", "-c", listing_script("attest-apple")], cwd=work, env=env, check=True,
                           capture_output=True, text=True)
            self.assertEqual((work / "cells.txt").read_text().split(), ["skia-build-mac-universal-gpu-release"])
            self.assertNotIn("linux", (work / "subjects.sha256").read_text())


if __name__ == "__main__":
    unittest.main()
