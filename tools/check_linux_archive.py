#!/usr/bin/env python3
"""Check that a Linux Skia archive links without PartitionAlloc's BackupRefPtr.

Skia compiles its ``raw_ptr`` members against PartitionAlloc when
``skia_use_partition_alloc`` is on, and PartitionAlloc's BackupRefPtr then
makes every ``raw_ptr`` call ``base::internal::RawPtrBackupRefImpl``. That
implementation is not packaged in any library this repository ships, so a
consumer's link fails with undefined references to it. The Linux builds turn
``skia_use_partition_alloc`` off, which makes ``raw_ptr`` a plain pointer.

For every ``skia-build-linux-*.zip`` given, this lists the static libraries'
symbols with ``nm`` and fails when any library references a
``RawPtrBackupRefImpl`` symbol that no library in the same archive defines.
Archives for other platforms are skipped.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

NAME_RE = re.compile(r"^skia-build-linux-[a-z0-9_]+-[a-z0-9]+-(release|debug)\.zip$")
FORBIDDEN = re.compile(r"RawPtrBackupRefImpl")
UNDEFINED_TYPES = {"U", "w", "v"}


def symbols(nm_output: str) -> tuple[set[str], set[str]]:
    """(defined, undefined) symbol names from ``nm -C`` output."""
    defined, undefined = set(), set()
    for line in nm_output.splitlines():
        line = line.rstrip()
        if not line or line.endswith(":"):
            continue
        # "<address> <type> <name>" for defined, "<spaces> U <name>" for undefined.
        match = re.match(r"^(?:[0-9a-fA-F]+)?\s+([A-Za-z?])\s+(.+)$", line)
        if not match:
            continue
        kind, name = match.groups()
        (undefined if kind in UNDEFINED_TYPES else defined).add(name)
    return defined, undefined


def unresolved_backup_ref(libraries: dict[str, str]) -> dict[str, list[str]]:
    """Library -> BackupRefPtr symbols it references that no library defines."""
    defined: set[str] = set()
    parsed = {}
    for name, output in libraries.items():
        lib_defined, lib_undefined = symbols(output)
        defined |= lib_defined
        parsed[name] = lib_undefined
    found = {}
    for name, undefined in sorted(parsed.items()):
        missing = sorted(symbol for symbol in undefined if FORBIDDEN.search(symbol) and symbol not in defined)
        if missing:
            found[name] = missing
    return found


def check_archive(path: Path) -> list[str]:
    libraries: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as temporary:
        for member in archive.namelist():
            if not member.endswith(".a"):
                continue
            target = Path(temporary) / member.replace("/", "_")
            target.write_bytes(archive.read(member))
            result = subprocess.run(["nm", "-C", str(target)], capture_output=True, text=True)
            if result.returncode != 0:
                return [f"{path.name}: nm failed on {member}: {result.stderr.strip()[-300:]}"]
            libraries[member] = result.stdout
    if not libraries:
        return [f"{path.name}: no static libraries found"]
    return [f"{path.name}: {name} references {len(missing)} undefined BackupRefPtr symbol(s), e.g. {missing[0]}"
            for name, missing in unresolved_backup_ref(libraries).items()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args()
    problems, checked = [], 0
    for path in args.archives:
        if not NAME_RE.match(path.name):
            continue
        checked += 1
        problems += check_archive(path)
    for problem in problems:
        print(f"::error::{problem}")
    if not problems:
        print(f"Linux archives free of unresolved BackupRefPtr references: {checked}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
