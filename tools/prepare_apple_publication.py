#!/usr/bin/env python3
"""Stage one Apple build for publication; cryptographic verification runs separately.

Only a supported canonical archive and its three content-addressed records are
copied. Bind the caller's expected archive digest, both release locks, and the
legal manifest's source revisions before the privileged job can upload anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ASSETS = tuple(f"skia-build-{cell}-gpu-release.zip" for cell in (
    "mac-universal", "mac-arm64", "mac-x86_64", "ios-device-arm64",
    "ios-simulator-arm64-x86_64", "visionos-device-arm64", "visionos-simulator-arm64"))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(directory: Path, stem: str, kind: str, suffix: str) -> Path:
    candidates = list(directory.glob(f"{stem}.{kind}.sha256-*.{suffix}"))
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one {kind}, found {len(candidates)}")
    path = candidates[0]
    if path.name != f"{stem}.{kind}.sha256-{digest(path)}.{suffix}":
        raise ValueError(f"content-addressed name does not match bytes: {path.name}")
    return path


def stage(root: Path, published_lock: Path, tag: str, asset: str,
          expected_sha256: str, output: Path) -> list[Path]:
    if asset not in ASSETS:
        raise ValueError("unsupported Apple archive name")
    if not re.fullmatch(r"chrome/m[1-9][0-9]*", tag):
        raise ValueError("expected a canonical milestone tag")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected archive SHA256 must be 64 lowercase hex characters")
    stem = asset.removesuffix(".zip")
    archive = root / stem / asset
    if digest(archive) != expected_sha256:
        raise ValueError("archive differs from the explicitly approved digest")
    lock = root / "skia-release-lock" / "skia-release-lock.json"
    if lock.read_bytes() != published_lock.read_bytes():
        raise ValueError("build lock differs from destination release lock")
    source = json.loads(lock.read_bytes())
    if source.get("skia_release_tag") != tag:
        raise ValueError("build lock names another release tag")
    for key in ("built_skia", "built_dawn"):
        if not re.fullmatch(r"[0-9a-f]{40}", source.get(key, "")):
            raise ValueError(f"invalid source lock {key}")
    manifest = record(root / stem / "provenance-assets", stem, "legal-manifest", "json")
    receipt = record(root / stem / "provenance-assets", stem, "apple-toolchain", "json")
    bundle = record(root / "skia-build-apple-attestation", stem,
                    "provenance-attestation", "sigstore.json")
    for path in (manifest, receipt):
        data = json.loads(path.read_bytes())
        if data.get("archive", {}).get("name") != asset or data["archive"].get("sha256") != expected_sha256:
            raise ValueError(f"{path.name}: record does not bind the archive")
    revisions = json.loads(manifest.read_bytes()).get("source_revisions", {})
    for repo in ("skia", "dawn"):
        revision = revisions.get(repo, {})
        if revision.get("commit") != source[f"built_{repo}"] or revision.get("expected") != source[f"built_{repo}"]:
            raise ValueError(f"manifest {repo} revision differs from release lock")
    files = [archive, manifest, receipt, bundle, lock]
    output.mkdir(parents=True, exist_ok=False)
    for path in files:
        shutil.copyfile(path, output / path.name)
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in files), encoding="utf-8")
    return [output / path.name for path in files]


def check_destination(before: dict, asset: str, previous_sha256: str | None,
                      desired_sha256: str) -> None:
    if previous_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", previous_sha256):
        raise ValueError("expected previous digest must be 64 lowercase hex characters")
    current = next((item.get("digest") for item in before["assets"] if item["name"] == asset), None)
    approved = (("sha256:" + previous_sha256, "sha256:" + desired_sha256)
                if previous_sha256 is not None else (None, "sha256:" + desired_sha256))
    if current not in approved:
        raise ValueError("destination archive differs from both approved prior and desired digests")


def verify_published(before: dict, after: dict, staged: Path, asset: str, reason: str,
                     previous_sha256: str | None) -> None:
    """Prove expected bytes, preservation of unrelated assets, and replacement ledger."""
    from release_asset_guard import extract_ledger

    check_destination(before, asset, previous_sha256, digest(staged / asset))
    original = {item["name"]: item for item in before["assets"]}
    current = {item["name"]: item for item in after["assets"]}
    if before["id"] != after["id"] or before["tag_name"] != after["tag_name"]:
        raise ValueError("destination release identity changed")
    expected = {path.name: "sha256:" + digest(path) for path in staged.iterdir()
                if path.name != "SHA256SUMS"}
    for name, sha in expected.items():
        if current.get(name, {}).get("digest") != sha:
            raise ValueError(f"published digest mismatch: {name}")
    for name, item in original.items():
        if name != asset and (current.get(name, {}).get("digest") != item.get("digest")
                              or current.get(name, {}).get("id") != item["id"]):
            raise ValueError(f"unrelated asset changed or disappeared: {name}")
    if set(current) != set(original) | set(expected):
        raise ValueError("unexpected asset set after publication")
    if previous_sha256 is not None and "sha256:" + previous_sha256 != expected[asset]:
        old_sha = previous_sha256
        new_sha = expected[asset].removeprefix("sha256:")
        if not any(asset in line and old_sha in line and new_sha in line and reason.strip() in line
                   for line in extract_ledger(after.get("body") or "")):
            raise ValueError("replacement succeeded without its required old/new/reason ledger entry")
    for line in extract_ledger(before.get("body") or ""):
        if line not in extract_ledger(after.get("body") or ""):
            raise ValueError("an existing replacement ledger entry disappeared")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--published-lock", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--asset", choices=ASSETS, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage(args.root, args.published_lock, args.tag, args.asset, args.sha256, args.output)


if __name__ == "__main__":
    main()
