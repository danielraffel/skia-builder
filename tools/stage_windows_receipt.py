#!/usr/bin/env python3
"""Stage a Windows archive's toolchain receipt as a content-addressed release asset.

The Windows build writes ``msvc-toolchain.json`` into the packaged tree, so the
receipt already travels inside the archive.  A consumer or attestation verifier
that wants the producer toolchain without unpacking a 100 MB archive needs it
beside the archive, bound to the same bytes.  This copies the receipt out of
the archive, refuses it unless it proves what it claims
(``write_windows_toolchain_provenance.validate_receipt``), and writes it as
``<archive>.msvc-toolchain.sha256-<digest>.json`` so a release can only ever
gain it as a new asset.  ``--check`` re-proves a staged copy against its
archive: same bytes as the archive's member, valid, and carrying its own digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import write_windows_toolchain_provenance as receipt_tool  # noqa: E402

CONTENT_ADDRESSED_RE = re.compile(r"\.msvc-toolchain\.sha256-([0-9a-f]{64})\.json$")
MEMBER_NAME = "msvc-toolchain.json"


def content_addressed_name(archive_name: str, data: bytes) -> str:
    stem = archive_name[:-4] if archive_name.endswith(".zip") else archive_name
    return f"{stem}.msvc-toolchain.sha256-{hashlib.sha256(data).hexdigest()}.json"


def archive_receipt(archive: Path) -> bytes:
    with zipfile.ZipFile(archive) as handle:
        names = [info.filename for info in handle.infolist()
                 if PurePosixPath(info.filename).name == MEMBER_NAME]
        if len(names) != 1:
            raise SystemExit(f"{archive.name}: expected one {MEMBER_NAME}, found {names}")
        return handle.read(names[0])


def problems_for(data: bytes, arch: str, configuration: str) -> list[str]:
    try:
        receipt = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"receipt is not JSON: {error}"]
    return receipt_tool.validate_receipt(receipt, arch, configuration)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--out-dir", type=Path, help="write the content-addressed copy here")
    parser.add_argument("--check", type=Path, metavar="STAGED",
                        help="re-prove a staged copy against --archive instead of writing one")
    args = parser.parse_args(argv)

    data = archive_receipt(args.archive)
    problems = problems_for(data, args.arch, args.configuration)
    if args.check:
        staged = args.check.read_bytes()
        if staged != data:
            problems.append(f"{args.check.name} differs from the receipt inside {args.archive.name}")
        match = CONTENT_ADDRESSED_RE.search(args.check.name)
        if not match or match.group(1) != hashlib.sha256(staged).hexdigest():
            problems.append(f"{args.check.name} does not carry its own sha256")
    for problem in problems:
        print(f"msvc-toolchain-receipt: {problem}", file=sys.stderr)
    if problems:
        return 1
    if args.check:
        print(f"msvc-toolchain-receipt: {args.check} is proven")
        return 0
    if not args.out_dir:
        parser.error("--out-dir is required to stage a receipt")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    target = args.out_dir / content_addressed_name(args.archive.name, data)
    target.write_bytes(data)
    print(f"msvc-toolchain-receipt: staged {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
