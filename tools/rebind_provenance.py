#!/usr/bin/env python3
"""Derive a legal manifest and toolchain receipt for a published archive from a
member-identical rebuild of it.

A release published before the builder wrote provenance has no manifest or
receipt, and rebuilding it never reproduces the zip byte for byte: zip entries
and Apple ar member headers carry timestamps.  When a rebuild of the same
source, with the same toolchain, is member-identical to the published archive
(every zip member, every static-archive member and every symbol table has the
same content; see compare_archive_members.py), the rebuild's manifest and
receipt describe the published archive's contents exactly.  This tool rebinds
them to the published archive:

* it refuses unless the comparison verdict is ``identical`` or
  ``metadata-only``;
* every digest that names the published archive (the archive, each zip
  member, each static-archive slice, and the receipt's per-member
  LC_BUILD_VERSION census) is recomputed from the published bytes, never
  copied; per-member and symbol-table digests must equal the rebuild's, and
  slices are keyed by CPU type and subtype, so no slice goes uncompared;
* both records gain ``derived_from``, naming the rebuild's content-addressed
  manifest and receipt, the rebuild archive, the comparison report, the run
  that built it, and that run's build-provenance bundle, against which a
  consumer re-verifies the rebuild;
* the receipt states that its toolchain values were measured on the rebuild's
  runner, and records the values the original build's job log shows, which
  must match.

The comparison report is written content-addressed next to the two records.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apple_archive  # noqa: E402
import compare_archive_members  # noqa: E402
import write_apple_toolchain_receipt as receipt_tool  # noqa: E402
import write_legal_manifest as manifest_tool  # noqa: E402

REBIND_METHOD = "member-identical-rebuild"
ACCEPTED_VERDICTS = {compare_archive_members.IDENTICAL, compare_archive_members.METADATA_ONLY}


class RebindError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RebindError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def addressed(stem: str, kind: str, data: bytes, suffix: str = ".json") -> str:
    return f"{stem}.{kind}.sha256-{sha256_bytes(data)}{suffix}"


def rebind_manifest(probe: dict, pinned: Path) -> dict:
    """The rebuild's manifest with every archive-bound digest recomputed from ``pinned``."""
    manifest = copy.deepcopy(probe)
    manifest["archive"] = {"name": pinned.name, "sha256": compare_archive_members.sha256_file(pinned),
                           "size": pinned.stat().st_size}
    rows = {row["name"]: row for row in manifest["zip_members"]}
    with zipfile.ZipFile(pinned) as handle:
        names = sorted(info.filename for info in handle.infolist() if not info.is_dir())
        require(names == sorted(rows), "the published archive's zip members differ from the manifest's")
        for name in names:
            data = handle.read(name)
            row = rows[name]
            if row.get("kind") != "static-archive":
                require(row["sha256"] == sha256_bytes(data),
                        f"{name}: content differs from the rebuild")
            row["sha256"], row["size"] = sha256_bytes(data), len(data)
            if row.get("kind") != "static-archive":
                continue
            recorded = manifest["static_archives"][name]["slices"]
            pieces = apple_archive.slices(data)
            require(sorted(piece.arch for piece in pieces) == sorted(recorded),
                    f"{name}: architecture slices differ from the rebuild")
            for piece in pieces:
                parsed = apple_archive.parse_archive(piece.data)
                slice_row = recorded[piece.arch]
                require(len(parsed.members) == len(slice_row["members"]),
                        f"{name}[{piece.arch}]: member count differs from the rebuild")
                for member, member_row in zip(parsed.members, slice_row["members"]):
                    require(member.name == member_row["name"] and member.sha256 == member_row["sha256"],
                            f"{name}[{piece.arch}] {member.name}: content differs from the rebuild")
                require([table.sha256 for table in parsed.symbol_tables] == slice_row["symbol_tables"],
                        f"{name}[{piece.arch}]: symbol table differs from the rebuild")
                slice_row["sha256"] = sha256_bytes(piece.data)
    return manifest


def rebind_receipt(probe: dict, pinned: Path) -> dict:
    receipt = copy.deepcopy(probe)
    observed = receipt_tool.observed_macho(pinned)
    require(observed == probe.get("observed_macho"),
            "the published archive's LC_BUILD_VERSION census differs from the rebuild's")
    receipt["archive"] = {"name": pinned.name, "sha256": compare_archive_members.sha256_file(pinned)}
    receipt["observed_macho"] = observed
    return receipt


def original_build_matches(receipt: dict, original: dict) -> list[str]:
    """Differences between the receipt and what the original job log shows."""
    problems = []
    if original.get("image_version") != receipt["runner"]["image_version"]:
        problems.append(f"runner image {receipt['runner']['image_version']} != original "
                        f"{original.get('image_version')}")
    xcode = original.get("xcode", "")
    if not xcode or f"/{xcode}.app/" not in receipt["xcode"]["developer_dir"] + "/":
        problems.append(f"Xcode {receipt['xcode']['developer_dir']} is not the original {xcode}")
    return problems


def rebuild_bundle_record(bundle: Path, stem: str) -> dict:
    """The rebuild run's build-provenance bundle, as the records name it.

    A consumer re-verifies the rebuild archive, manifest and receipt against
    this bundle (build-skia.yml on main), so the records name it by its own
    content-addressed file name and digest.
    """
    data = bundle.read_bytes()
    digest = sha256_bytes(data)
    expected = f"{stem}.provenance-attestation.sha256-{digest}.sigstore.json"
    require(bundle.name == expected,
            f"the rebuild bundle is named {bundle.name!r}, not its content-addressed {expected!r}")
    try:
        media_type = json.loads(data).get("mediaType", "")
    except ValueError:
        media_type = ""
    require(str(media_type).startswith("application/vnd.dev.sigstore.bundle"),
            "the rebuild bundle is not a Sigstore bundle")
    return {"name": bundle.name, "sha256": digest}


def rebind(pinned: Path, probe_archive: Path, probe_manifest: Path, probe_receipt: Path,
           probe_run: dict, original_build: dict, out_dir: Path,
           rebuild_bundle: Path) -> dict[str, Path]:
    report = compare_archive_members.compare(pinned, probe_archive, limit=5)
    require(report["verdict"] in ACCEPTED_VERDICTS,
            f"the rebuild is not member-identical to {pinned.name}: {report['verdict']} "
            f"({'; '.join(report.get('causes', []))})")
    manifest_bytes, receipt_bytes = probe_manifest.read_bytes(), probe_receipt.read_bytes()
    manifest_probe, receipt_probe = json.loads(manifest_bytes), json.loads(receipt_bytes)
    probe_sha = compare_archive_members.sha256_file(probe_archive)
    require(manifest_probe["archive"]["sha256"] == probe_sha,
            "the rebuild manifest does not describe the rebuild archive")
    require(receipt_probe["archive"]["sha256"] == probe_sha,
            "the rebuild receipt does not describe the rebuild archive")
    require(not manifest_tool.validate_manifest(manifest_probe, probe_archive),
            "the rebuild manifest is not an exhaustive inventory of the rebuild archive")
    require(not receipt_tool.validate_receipt(receipt_probe, probe_archive),
            "the rebuild receipt does not prove the rebuild archive")
    mismatches = original_build_matches(receipt_probe, original_build)
    require(not mismatches, "the rebuild toolchain is not the original build's: " + "; ".join(mismatches))

    stem = pinned.name.removesuffix(".zip")
    bundle_record = rebuild_bundle_record(rebuild_bundle, stem)
    report_bytes = canonical(report)
    report_name = addressed(stem, "member-comparison", report_bytes)
    derived_from = {
        "method": REBIND_METHOD,
        "comparison": {"name": report_name, "sha256": sha256_bytes(report_bytes),
                       "verdict": report["verdict"]},
        "rebuild_archive": {"name": probe_archive.name, "sha256": probe_sha},
        "rebuild_manifest": {"name": probe_manifest.name, "sha256": sha256_bytes(manifest_bytes)},
        "rebuild_receipt": {"name": probe_receipt.name, "sha256": sha256_bytes(receipt_bytes)},
        "rebuild_run": probe_run,
        "rebuild_bundle": bundle_record,
    }

    manifest = rebind_manifest(manifest_probe, pinned)
    manifest["derived_from"] = derived_from
    problems = manifest_tool.validate_manifest(manifest, pinned)
    require(not problems, "rebound manifest does not prove the published archive: " + "; ".join(problems))

    receipt = rebind_receipt(receipt_probe, pinned)
    receipt["derived_from"] = derived_from
    receipt["measurement"] = {
        "toolchain_values_measured_on": "the rebuild runner named in derived_from.rebuild_run",
        "original_build_log": dict(original_build, matches_rebuild_toolchain=True,
                                   note="values observed in the original build's job log"),
    }
    problems = receipt_tool.validate_receipt(receipt, pinned)
    require(not problems, "rebound receipt does not prove the published archive: " + "; ".join(problems))

    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for kind, data in (("member-comparison", report_bytes),
                       ("legal-manifest", canonical(manifest)),
                       ("apple-toolchain", canonical(receipt))):
        path = out_dir / addressed(stem, kind, data)
        path.write_bytes(data)
        written[kind] = path
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pinned", type=Path, required=True, help="the published archive")
    parser.add_argument("--rebuild-archive", type=Path, required=True)
    parser.add_argument("--rebuild-manifest", type=Path, required=True)
    parser.add_argument("--rebuild-receipt", type=Path, required=True)
    parser.add_argument("--rebuild-bundle", type=Path, required=True,
                        help="the rebuild run's build-provenance bundle, as attest-apple published it")
    parser.add_argument("--rebuild-repository", default="danielraffel/skia-builder")
    parser.add_argument("--rebuild-run-id", type=int, required=True)
    parser.add_argument("--rebuild-run-attempt", type=int, required=True)
    parser.add_argument("--rebuild-ref", required=True, help="the ref the rebuild ran on")
    parser.add_argument("--original-job", type=int, required=True,
                        help="the job that built the published archive")
    parser.add_argument("--original-image-version", required=True)
    parser.add_argument("--original-xcode", required=True, help="for example Xcode_16.4")
    parser.add_argument("--original-compiler-identification", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        written = rebind(
            args.pinned, args.rebuild_archive, args.rebuild_manifest, args.rebuild_receipt,
            {"repository": args.rebuild_repository, "run_id": args.rebuild_run_id,
             "run_attempt": args.rebuild_run_attempt, "ref": args.rebuild_ref},
            {"job": args.original_job, "image_version": args.original_image_version,
             "xcode": args.original_xcode,
             "compiler_identification": args.original_compiler_identification},
            args.out_dir, args.rebuild_bundle)
    except (RebindError, OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print(f"rebind-provenance: {error}", file=sys.stderr)
        return 1
    for kind, path in written.items():
        print(f"rebind-provenance: {kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
