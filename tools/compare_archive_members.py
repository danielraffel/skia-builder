#!/usr/bin/env python3
"""Compare two packaged Skia archives member by member, and say why they differ.

A rebuild of the same source almost never reproduces a zip byte for byte: zip
entries carry modification times, and Apple's ``ar``/``libtool`` record each
object's mtime, uid and gid in the archive member header.  Those differences
say nothing about the code.  This tool separates them from the differences
that matter:

* ``identical``      -- the two files are byte-identical;
* ``metadata-only``  -- every zip member's content is identical, or differs
  only in static-archive member headers (dates, owner, mode) and the symbol
  table that indexes them, while every object member's bytes are identical;
* ``code-differs``   -- at least one object member, header, or other packaged
  file has different content.  For each differing object the report names the
  Mach-O sections whose bytes differ and the ``LC_BUILD_VERSION`` of both
  sides, which is usually enough to tell a compiler change (``__TEXT``
  differs, the SDK moved) from an embedded path or timestamp (only a
  ``__cstring``/``__const`` section differs).

Object members are paired by name and occurrence, so an archive that repeats a
member name is compared position by position.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apple_archive  # noqa: E402

IDENTICAL = "identical"
METADATA_ONLY = "metadata-only"
CODE_DIFFERS = "code-differs"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def keyed_members(members: list[apple_archive.Member]) -> dict[tuple[str, int], apple_archive.Member]:
    seen: Counter = Counter()
    keyed = {}
    for member in members:
        keyed[(member.name, seen[member.name])] = member
        seen[member.name] += 1
    return keyed


def macho_summary(data: bytes) -> dict[str, object] | None:
    macho = apple_archive.parse_macho(data)
    if macho is None:
        return None
    return {"platform": macho.platform, "minos": macho.minos, "sdk": macho.sdk, "size": len(data)}


def differing_sections(left: bytes, right: bytes) -> list[str]:
    a, b = apple_archive.parse_macho(left), apple_archive.parse_macho(right)
    if a is None or b is None:
        return ["<not Mach-O>"]
    sections_a = {(s.segment, s.name): s.data for s in a.sections}
    sections_b = {(s.segment, s.name): s.data for s in b.sections}
    names = sorted(set(sections_a) | set(sections_b))
    result = [f"{seg},{sect}" for seg, sect in names if sections_a.get((seg, sect)) != sections_b.get((seg, sect))]
    if a.symtab != b.symtab:
        result.append("<symbol/string table>")
    if not result:
        result.append("<load commands/headers>")
    return result


def compare_static_archive(left: bytes, right: bytes, limit: int) -> dict[str, object]:
    slices_a = {piece.arch: piece.data for piece in apple_archive.slices(left)}
    slices_b = {piece.arch: piece.data for piece in apple_archive.slices(right)}
    report: dict[str, object] = {"architectures": {"reference": sorted(slices_a), "candidate": sorted(slices_b)}}
    code_differs = sorted(slices_a) != sorted(slices_b)
    per_arch = {}
    for arch in sorted(set(slices_a) & set(slices_b)):
        arch_a = apple_archive.parse_archive(slices_a[arch])
        arch_b = apple_archive.parse_archive(slices_b[arch])
        keyed_a, keyed_b = keyed_members(arch_a.members), keyed_members(arch_b.members)
        header_fields: Counter = Counter()
        differing = []
        section_counts: Counter = Counter()
        same = 0
        for key in sorted(set(keyed_a) & set(keyed_b)):
            ma, mb = keyed_a[key], keyed_b[key]
            if ma.data == mb.data:
                same += 1
                for field in ("date", "uid", "gid", "mode"):
                    if getattr(ma, field) != getattr(mb, field):
                        header_fields[field] += 1
                continue
            sections = differing_sections(ma.data, mb.data)
            section_counts.update(sections)
            if len(differing) < limit:
                differing.append({"member": ma.name, "occurrence": key[1], "sections": sections,
                                  "reference": macho_summary(ma.data), "candidate": macho_summary(mb.data)})
        only_a = sorted(f"{name}#{index}" for name, index in set(keyed_a) - set(keyed_b))
        only_b = sorted(f"{name}#{index}" for name, index in set(keyed_b) - set(keyed_a))
        differing_count = sum(1 for key in set(keyed_a) & set(keyed_b) if keyed_a[key].data != keyed_b[key].data)
        if differing_count or only_a or only_b:
            code_differs = True
        per_arch[arch] = {
            "members": {"reference": len(arch_a.members), "candidate": len(arch_b.members)},
            "identical_content": same,
            "differing_content": differing_count,
            "only_in_reference": only_a[:limit],
            "only_in_candidate": only_b[:limit],
            "header_only_differences": dict(header_fields),
            "symbol_table_identical": [t.data for t in arch_a.symbol_tables] == [t.data for t in arch_b.symbol_tables],
            "differing_sections": dict(section_counts.most_common()),
            "examples": differing,
        }
    report["slices"] = per_arch
    report["verdict"] = CODE_DIFFERS if code_differs else METADATA_ONLY
    return report


def compare(reference: Path, candidate: Path, limit: int = 20) -> dict[str, object]:
    report: dict[str, object] = {
        "reference": {"name": reference.name, "sha256": sha256_file(reference)},
        "candidate": {"name": candidate.name, "sha256": sha256_file(candidate)},
    }
    if report["reference"]["sha256"] == report["candidate"]["sha256"]:
        report["verdict"] = IDENTICAL
        return report
    with zipfile.ZipFile(reference) as za, zipfile.ZipFile(candidate) as zb:
        infos_a = {info.filename: info for info in za.infolist() if not info.is_dir()}
        infos_b = {info.filename: info for info in zb.infolist() if not info.is_dir()}
        zip_metadata: Counter = Counter()
        identical, differing_files, archives = 0, [], {}
        for name in sorted(set(infos_a) & set(infos_b)):
            ia, ib = infos_a[name], infos_b[name]
            for field in ("date_time", "external_attr", "compress_type", "extra", "create_system"):
                if getattr(ia, field) != getattr(ib, field):
                    zip_metadata[field] += 1
            da, db = za.read(ia), zb.read(ib)
            if da == db:
                identical += 1
                continue
            if da.startswith(apple_archive.AR_MAGIC) or apple_archive.slices(da)[0].data.startswith(apple_archive.AR_MAGIC):
                archives[name] = compare_static_archive(da, db, limit)
            else:
                differing_files.append({"name": name, "reference_sha256": apple_archive.sha256_bytes(da),
                                        "candidate_sha256": apple_archive.sha256_bytes(db)})
    only_a, only_b = sorted(set(infos_a) - set(infos_b)), sorted(set(infos_b) - set(infos_a))
    report["zip"] = {
        "members": {"reference": len(infos_a), "candidate": len(infos_b)},
        "identical_content": identical,
        "only_in_reference": only_a,
        "only_in_candidate": only_b,
        "metadata_differences": dict(zip_metadata),
        "differing_files": differing_files,
    }
    report["static_archives"] = archives
    code = bool(only_a or only_b or differing_files
                or any(row["verdict"] == CODE_DIFFERS for row in archives.values()))
    report["verdict"] = CODE_DIFFERS if code else METADATA_ONLY
    report["causes"] = causes(report)
    return report


def causes(report: dict[str, object]) -> list[str]:
    found = []
    zip_meta = report["zip"]["metadata_differences"]
    if zip_meta.get("date_time") or zip_meta.get("extra"):
        found.append("zip entry timestamps differ (zip -r records each file's mtime)")
    headers: Counter = Counter()
    sdks = set()
    sections: Counter = Counter()
    for row in report["static_archives"].values():
        for piece in row.get("slices", {}).values():
            headers.update(piece["header_only_differences"])
            sections.update(piece["differing_sections"])
            for example in piece["examples"]:
                ref, cand = example.get("reference") or {}, example.get("candidate") or {}
                if ref.get("sdk") != cand.get("sdk") or ref.get("minos") != cand.get("minos"):
                    sdks.add((ref.get("sdk"), cand.get("sdk")))
    if headers.get("date"):
        found.append("static-archive member dates differ (ar/libtool record object mtimes; ZERO_AR_DATE is unset)")
    if headers.get("uid") or headers.get("gid"):
        found.append("static-archive member owner differs")
    if sdks:
        found.append(f"objects were built against different SDKs: {sorted(sdks, key=str)}")
    if sections:
        text = [name for name in sections if name.startswith("__TEXT,__text")]
        found.append(("machine code differs (__TEXT,__text): compiler, flags, or source changed"
                      if text else "only data sections differ: embedded strings or constants")
                     + f"; most-differing sections: {dict(sections.most_common(6))}")
    if report["zip"]["differing_files"]:
        found.append(f"{len(report['zip']['differing_files'])} packaged non-archive file(s) differ")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--json", type=Path, help="write the full report here")
    parser.add_argument("--limit", type=int, default=20, help="examples per archive slice")
    args = parser.parse_args(argv)
    report = compare(args.reference, args.candidate, args.limit)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"verdict: {report['verdict']}")
    for cause in report.get("causes", []):
        print(f"cause: {cause}")
    zip_report = report.get("zip")
    if zip_report:
        print(f"zip members identical: {zip_report['identical_content']}/{zip_report['members']['reference']}")
        for name, row in report["static_archives"].items():
            for arch, piece in row.get("slices", {}).items():
                print(f"{name}[{arch}]: {piece['identical_content']} identical, "
                      f"{piece['differing_content']} differing object member(s); "
                      f"header-only: {piece['header_only_differences']}")
    return 0 if report["verdict"] == IDENTICAL else 1


if __name__ == "__main__":
    raise SystemExit(main())
