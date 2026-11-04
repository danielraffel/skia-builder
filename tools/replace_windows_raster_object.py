#!/usr/bin/env python3
"""Replace only SkOpts.cpp in an MSVC Skia archive with a verified vector object.

This is an archive transformation, not a compiler or runtime initialization
override. The caller must compile the normal SkOpts.cpp with its actual provider
configuration and record that recipe separately. Input archives stay untouched.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile

MACHINES = {"arm64": 0xAA64, "arm64ec": 0xA641}
SPECIAL = {"/", "//", "/<ECSYMBOLS>/", "/<HYBRIDMAP>/"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def members(data: bytes) -> list[tuple[str, bytes]]:
    """Read COFF ar members, including NUL-terminated Windows long names."""
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("not a COFF archive")
    result, names, offset = [], b"", 8
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[58:] != b"`\n":
            raise ValueError("truncated or invalid archive header")
        name = header[:16].decode("ascii").rstrip()
        size = int(header[48:58])
        if size < 0:
            raise ValueError("negative member size")
        start = offset + 60
        body = data[start:start + size]
        if len(body) != size:
            raise ValueError("truncated member")
        offset = start + size + (size & 1)
        if name == "//":
            names = body
        if name in SPECIAL:
            continue
        if re.fullmatch(r"/\d+", name):
            index = int(name[1:])
            if index >= len(names):
                raise ValueError("invalid long-name offset")
            ends = [n for n in (names.find(b"\0", index), names.find(b"\n", index)) if n >= 0]
            if not ends:
                raise ValueError("unterminated archive name")
            name = names[index:min(ends)].decode("utf-8").removesuffix("/")
        else:
            name = name.removesuffix("/")
        result.append((name, body))
    return result


def machine(data: bytes) -> int:
    if len(data) < 8:
        raise ValueError("truncated COFF object")
    first, second = struct.unpack_from("<HH", data)
    return struct.unpack_from("<H", data, 6)[0] if (first, second) == (0, 0xFFFF) else first


def validate_replacement(before: list[tuple[str, bytes]], after: list[tuple[str, bytes]],
                         old_name: str, replacement: bytes, arch: str) -> None:
    if any(machine(data) != MACHINES[arch] for _, data in before + after):
        raise ValueError("archive contains an incompatible COFF machine")
    expected = Counter((name, sha(data)) for name, data in before if name != old_name)
    candidates = [(name, data) for name, data in after if data == replacement]
    if len(candidates) != 1:
        raise ValueError("expected exactly one replacement object")
    actual = Counter((name, sha(data)) for name, data in after if data != replacement)
    if expected != actual:
        raise ValueError("replacement changed or lost unrelated archive members")


def replace(original: Path, vector: Path, output: Path, arch: str,
            ar: str, librarian: str, nm: str) -> dict:
    if output.exists() or original.resolve() == output.resolve():
        raise ValueError("output must be a new file; preserve the original archive")
    original_bytes, vector_bytes = original.read_bytes(), vector.read_bytes()
    if machine(vector_bytes) != MACHINES[arch]:
        raise ValueError("replacement object architecture mismatch")
    before = members(original_bytes)
    selected = [name for name, _ in before
                if re.search(r"(?:^|[\\/])(?:core\.)?SkOpts\.obj$", name)]
    if len(selected) != 1:
        raise ValueError(f"expected exactly one normal SkOpts.cpp member, found {selected}")
    undefined = subprocess.check_output([nm, "--undefined-only", str(vector)], text=True)
    if any(symbol in undefined for symbol in ("__std_", "Init_ml3", "Init_ml4", "gCachedFeatures")):
        raise ValueError("replacement imports STL helpers or x86 dispatch")
    defined = subprocess.check_output([nm, "--defined-only", str(vector)], text=True)
    for symbol in ("ops_highp", "ops_lowp", "just_return_highp", "just_return_lowp",
                   "start_pipeline_highp", "start_pipeline_lowp",
                   "raster_pipeline_highp_stride", "raster_pipeline_lowp_stride"):
        if symbol not in defined:
            raise ValueError(f"incomplete normal SkOpts implementation: {symbol}")
    with tempfile.TemporaryDirectory(prefix="raster-member-", dir=output.parent) as tmp:
        stripped = Path(tmp) / "stripped.lib"
        candidate = Path(tmp) / "candidate.lib"
        stripped.write_bytes(original_bytes)
        subprocess.run([ar, "d", str(stripped), selected[0]], check=True)
        subprocess.run([librarian, f"/machine:{arch}", f"/out:{candidate}",
                        str(stripped), str(vector.resolve())], check=True)
        candidate_bytes = candidate.read_bytes()
        validate_replacement(before, members(candidate_bytes), selected[0], vector_bytes, arch)
        # Publish only after every member and architecture has been checked.
        with output.open("xb") as handle:
            handle.write(candidate_bytes)
    return {"schema_version": 1, "architecture": arch, "removed_member": selected[0],
            "input_archive_sha256": sha(original_bytes), "object_sha256": sha(vector_bytes),
            "output_archive_sha256": sha(candidate_bytes), "object_count": len(before),
            "unrelated_members_byte_identical": True, "runtime_injection": False,
            "qualification": "archive transformation only; consumer link/runtime proof required"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("vector_object", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arch", required=True, choices=MACHINES)
    parser.add_argument("--llvm-ar", default="llvm-ar")
    parser.add_argument("--llvm-lib", default="llvm-lib")
    parser.add_argument("--llvm-nm", default="llvm-nm")
    args = parser.parse_args()
    receipt = replace(args.original, args.vector_object, args.output, args.arch,
                      args.llvm_ar, args.llvm_lib, args.llvm_nm)
    args.output.with_suffix(".raster-object.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
