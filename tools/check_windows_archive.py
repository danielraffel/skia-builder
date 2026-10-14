#!/usr/bin/env python3
"""Smoke-check Windows Skia archives before they are published.

For every ``skia-build-win-<arch>-<variant>-<config>.zip`` given, this checks
what a consumer relies on and cannot easily see from the outside:

* ``msvc-toolchain.json`` is present and records a real toolset, SDK and
  compiler versions for the archive's own architecture and configuration
  (``write_windows_toolchain_provenance.validate_receipt``);
* every static library under ``lib/<Config>/<arch>/`` holds objects for that
  architecture only (COFF machine field), so an x64 library can never ship in
  the ARM64 asset or vice versa.

Archives for other platforms are skipped.  Exit status is non-zero when any
Windows archive fails.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from write_windows_toolchain_provenance import validate_receipt  # noqa: E402

NAME_RE = re.compile(r"^skia-build-win-(?P<arch>arm64|arm64ec|x64)-(?P<variant>[a-z0-9]+)-(?P<config>release|debug)\.zip$")
MACHINES = {0x8664: "x64", 0xAA64: "arm64", 0xA641: "arm64ec", 0x014C: "x86", 0x01C4: "arm"}
AR_MAGIC = b"!<arch>\n"
SPECIAL_MEMBERS = {"/", "//", "/<ECSYMBOLS>/", "/<HYBRIDMAP>/"}


def coff_machines(stream) -> Counter:
    """Count COFF machine types of the object members in an ``ar``/.lib stream."""
    if stream.read(8) != AR_MAGIC:
        raise ValueError("not an ar archive")
    counts: Counter = Counter()
    while True:
        header = stream.read(60)
        if len(header) < 60:
            return counts
        name = header[:16].decode("ascii", "replace").strip()
        size = int(header[48:58].decode("ascii").strip())
        body_head = stream.read(min(size, 8))
        remaining = size - len(body_head)
        while remaining > 0:
            chunk = stream.read(min(remaining, 1 << 20))
            if not chunk:
                break
            remaining -= len(chunk)
        if size % 2:
            stream.read(1)
        if name in SPECIAL_MEMBERS or len(body_head) < 8:
            continue
        sig1, sig2 = struct.unpack_from("<HH", body_head, 0)
        if sig1 == 0 and sig2 == 0xFFFF:
            # Import object or anonymous (e.g. /GL bitcode) object header:
            # Sig1, Sig2, Version, Machine.
            machine = struct.unpack_from("<H", body_head, 6)[0]
        else:
            machine = sig1
        counts[MACHINES.get(machine, f"0x{machine:04x}")] += 1


def check_archive(path: Path) -> list[str]:
    match = NAME_RE.match(path.name)
    if not match:
        return []
    arch, config = match["arch"], match["config"]
    config_dir = "Release" if config == "release" else "Debug"
    problems = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        receipts = [n for n in names if n.endswith("/msvc-toolchain.json")]
        if len(receipts) != 1:
            problems.append(f"expected one msvc-toolchain.json, found {len(receipts)}")
        else:
            receipt = json.loads(archive.read(receipts[0]))
            problems += [f"{receipts[0]}: {p}" for p in validate_receipt(receipt, arch, config_dir)]
        lib_dir = f"/lib/{config_dir}/{arch}/"
        libs = [n for n in names if lib_dir in n and n.lower().endswith(".lib")]
        stray = [n for n in names if n.lower().endswith(".lib") and lib_dir not in n]
        if not libs:
            problems.append(f"no static libraries under *{lib_dir}")
        for name in stray:
            problems.append(f"{name}: library outside {lib_dir}")
        for name in libs:
            with archive.open(name) as stream:
                try:
                    machines = coff_machines(stream)
                except ValueError as exc:
                    problems.append(f"{name}: {exc}")
                    continue
            foreign = {m: c for m, c in machines.items() if m != arch}
            if not machines.get(arch):
                problems.append(f"{name}: no {arch} objects (found {dict(machines)})")
            elif foreign:
                problems.append(f"{name}: objects for other machines {foreign}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args(argv)
    failed = False
    for path in args.archives:
        if not NAME_RE.match(path.name):
            print(f"check-windows-archive: skip {path.name} (not a Windows archive)")
            continue
        problems = check_archive(path)
        if problems:
            failed = True
            print(f"check-windows-archive: FAIL {path.name}", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
        else:
            print(f"check-windows-archive: ok   {path.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
