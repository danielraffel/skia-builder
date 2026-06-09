#!/usr/bin/env python3
"""Guard: every active build-matrix lane must be uploaded by create-release.

Root-cause guard for the chrome/m150 incident: commit 634672f added the
linux-arm64 (gpu) lane to the build matrix but never added the produced
artifact to the `create-release` job's `files:` list. The slice was built on
every run and uploaded as a workflow *artifact*, but silently dropped from the
published GitHub Release. Consumers (e.g. Pulp's release-cli) then failed
because the asset they expected did not exist.

This script reconstructs the archive name each active matrix lane produces
(replicating the "Set archive name" step's logic) and asserts that every one
of those `<name>.zip` files appears in the `create-release` step's `files:`
block. A lane that is built but not released fails the check.

Run locally:  python3 tools/check_release_coverage.py
CI:           .github/workflows/lint.yml on any PR touching build-skia.yml
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "build-skia.yml"


def archive_name(entry: dict) -> str:
    """Mirror the 'Set archive name' step in build-skia.yml."""
    config = (entry.get("config") or "Release")
    name = f"skia-build-{entry['platform']}"
    if entry.get("target"):
        name += f"-{entry['target']}"
    arch = entry.get("arch")
    if arch:
        # Multi-arch builds (e.g. "arm64,x86_64") replace commas with dashes.
        name += "-" + str(arch).replace(",", "-")
    name += f"-{entry['variant']}-{config.lower()}"
    return name


def find_release_files_block(wf: dict) -> str:
    """Return the raw `files:` string from the action-gh-release step."""
    jobs = wf.get("jobs", {})
    release = jobs.get("create-release")
    if not release:
        sys.exit("FAIL: no create-release job found in build-skia.yml")
    for step in release.get("steps", []):
        uses = step.get("uses", "")
        if uses.startswith("softprops/action-gh-release"):
            files = step.get("with", {}).get("files", "")
            if not files:
                sys.exit("FAIL: create-release action has no `files:` list")
            return files
    sys.exit("FAIL: no softprops/action-gh-release step in create-release job")


def main() -> int:
    wf = yaml.safe_load(WORKFLOW.read_text())
    matrix = wf["jobs"]["build-skia"]["strategy"]["matrix"]["include"]
    files = find_release_files_block(wf)

    missing = []
    checked = []
    for entry in matrix:
        name = archive_name(entry)
        zip_name = f"{name}.zip"
        checked.append(zip_name)
        if zip_name not in files:
            missing.append(zip_name)

    if missing:
        print("FAIL: matrix lanes built but NOT uploaded by create-release:")
        for z in missing:
            print(f"  - {z}")
        print(
            "\nAdd each to the `files:` list of the create-release "
            "softprops/action-gh-release step in build-skia.yml."
        )
        return 1

    print(f"OK: all {len(checked)} active matrix lanes are wired into create-release.")
    for z in checked:
        print(f"  - {z}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
