#!/usr/bin/env python3
"""Stage a Windows archive's toolchain receipt as a content-addressed release asset.

The Windows build writes ``msvc-toolchain.json`` (the MSVC toolset and SDK
receipt) into the packaged tree.  That receipt stays as it is; this derives
the release asset ``<archive>.msvc-toolchain.sha256-<digest>.json`` from it,
in the same shape the Linux, wasm and Android receipts use
(``skia-builder.msvc-toolchain-receipt.v1``):

* ``archive``: the zip's name and sha256;
* ``compiler``/``linker``/``archiver``: path, sha256, version and vendor of
  ``cl.exe``, ``link.exe`` and ``lib.exe`` from the toolset the build used;
* ``cpp_abi``: the MSVC STL release (the toolset version);
* ``msvc_toolset`` and ``windows_sdk`` versions, and the runner image;
* ``observed``: the COFF machine types of every object in every packaged
  library, and ``source_receipt``: the digest of the receipt inside the archive.

The in-archive receipt must pass ``write_windows_toolchain_provenance
.validate_receipt`` first.  ``--check`` re-derives everything that can be
re-derived from the archive alone (digest binding, machines, source receipt)
and validates the rest; it cannot re-hash tools that only exist on the runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apple_archive  # noqa: E402
import write_windows_toolchain_provenance as receipt_tool  # noqa: E402

SCHEMA = "skia-builder.msvc-toolchain-receipt.v1"
CONTENT_ADDRESSED_RE = re.compile(r"\.msvc-toolchain\.sha256-([0-9a-f]{64})\.json$")
MEMBER_NAME = "msvc-toolchain.json"
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
BAD_VALUE_RE = re.compile(r"^(unknown|error.*|)$", re.IGNORECASE)
LINK_BANNER_RE = re.compile(r"Microsoft \(R\) Incremental Linker Version \d+\.\d+\.\d+")
LIB_BANNER_RE = re.compile(r"Microsoft \(R\) Library Manager Version \d+\.\d+\.\d+")
ARCH_MACHINES = {"x64": "x64", "arm64": "arm64", "arm64ec": "arm64ec", "x86": "x86"}


def content_addressed_name(archive_name: str, data: bytes) -> str:
    stem = archive_name[:-4] if archive_name.endswith(".zip") else archive_name
    return f"{stem}.msvc-toolchain.sha256-{hashlib.sha256(data).hexdigest()}.json"


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=1) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_receipt(archive: Path) -> bytes:
    with zipfile.ZipFile(archive) as handle:
        names = [info.filename for info in handle.infolist()
                 if PurePosixPath(info.filename).name == MEMBER_NAME]
        if len(names) != 1:
            raise SystemExit(f"{archive.name}: expected one {MEMBER_NAME}, found {names}")
        return handle.read(names[0])


def observed_member_machines(archive: Path) -> tuple[dict[str, int], int]:
    counts: dict[str, int] = {}
    undecodable = 0
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".lib"):
                continue
            data = handle.read(info)
            if not data.startswith(apple_archive.AR_MAGIC):
                undecodable += 1
                continue
            for member in apple_archive.parse_archive(data).members:
                machine = apple_archive.object_arch(member.data)
                if machine:
                    counts[machine] = counts.get(machine, 0) + 1
                else:
                    undecodable += 1
    return dict(sorted(counts.items())), undecodable


def observed_machines(archive: Path) -> dict[str, int]:
    """Return recognized COFF member machines (for callers that only need counts)."""
    return observed_member_machines(archive)[0]


def run_banner(program: str) -> str:
    try:
        done = subprocess.run([program], capture_output=True, text=True, check=False)
    except OSError as error:
        return f"error: {error}"
    for line in ((done.stdout or "") + (done.stderr or "")).splitlines():
        if "Microsoft (R)" in line:
            return line.strip()
    return "unknown"


def tool_row(path: str, vendor: str, banner: str, hasher=None) -> dict[str, str]:
    row = {"vendor": vendor, "path": path, "version": banner, "sha256": "unknown"}
    try:
        row["sha256"] = (hasher or sha256_file)(Path(path))
    except OSError as error:
        row["sha256"] = f"error: {error}"
    return row


def derive(archive: Path, source: dict, source_bytes: bytes, arch: str, configuration: str,
           banner=run_banner, hasher=None) -> dict:
    producer = source.get("producer") or {}
    cl = (producer.get("skia_gn_compiler") or {}).get("path", "")
    directory = str(Path(cl).parent) if cl else ""
    sep = "\\" if "\\" in cl else "/"
    link = f"{directory}{sep}link.exe"
    lib = f"{directory}{sep}lib.exe"
    toolset = producer.get("msvc_toolset_version", "unknown")
    return {
        "schema": SCHEMA,
        "archive": {"name": archive.name, "sha256": sha256_file(archive)},
        "target": {"platform": "windows", "architectures": [arch], "configuration": configuration,
                   "variant": (source.get("target") or {}).get("variant", "gpu")},
        "compiler": {"cxx": tool_row(cl, "msvc", (producer.get("skia_gn_compiler") or {}).get("version", "unknown"), hasher)},
        "linker": tool_row(link, "msvc", banner(link), hasher),
        "archiver": tool_row(lib, "msvc", banner(lib), hasher),
        "cpp_abi": {arch: {"stdlib": "msvc-stl", "stdlib_version": toolset}},
        "msvc_toolset": {"version": toolset},
        "windows_sdk": {"version": producer.get("windows_sdk_version", "unknown")},
        "runner_image": {"name": os.environ.get("ImageOS", "local"),
                         "version": os.environ.get("ImageVersion", "local")},
        "observed": {"coff_machines": observed_machines(archive),
                     "undecodable_members": observed_member_machines(archive)[1]},
        "source_receipt": {"member": MEMBER_NAME, "sha256": hashlib.sha256(source_bytes).hexdigest()},
    }


def problems_for(archive: Path, staged: dict, source_bytes: bytes, arch: str,
                 configuration: str) -> list[str]:
    try:
        source = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"receipt inside the archive is not JSON: {error}"]
    problems = receipt_tool.validate_receipt(source, arch, configuration)
    walked: list[str] = []

    def walk(value: object, where: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{where}.{key}" if where else key)
        elif isinstance(value, str) and BAD_VALUE_RE.match(value.strip()):
            walked.append(f"{where} = {value!r}")
        elif value is None:
            walked.append(f"{where} is null")
    walk({key: staged.get(key) for key in ("target", "compiler", "linker", "archiver", "cpp_abi",
                                           "msvc_toolset", "windows_sdk", "runner_image")}, "")
    problems += walked
    if staged.get("schema") != SCHEMA:
        problems.append(f"schema = {staged.get('schema')!r}")
    if (staged.get("archive") or {}).get("sha256") != sha256_file(archive):
        problems.append("staged archive sha256 does not match the archive")
    if (staged.get("source_receipt") or {}).get("sha256") != hashlib.sha256(source_bytes).hexdigest():
        problems.append("staged source_receipt is not the receipt inside the archive")
    target = staged.get("target") or {}
    if target.get("architectures") != [arch]:
        problems.append(f"target.architectures {target.get('architectures')!r} != {[arch]!r}")
    if target.get("configuration") != configuration:
        problems.append(f"target.configuration {target.get('configuration')!r} != {configuration!r}")
    for name in ("compiler", "linker", "archiver"):
        row = (staged.get("compiler") or {}).get("cxx") if name == "compiler" else staged.get(name)
        row = row or {}
        if not HEX_64.match(str(row.get("sha256", ""))):
            problems.append(f"{name}.sha256 is not a SHA-256")
    if not LINK_BANNER_RE.search(str((staged.get("linker") or {}).get("version", ""))):
        problems.append("linker.version is not a link.exe banner")
    if not LIB_BANNER_RE.search(str((staged.get("archiver") or {}).get("version", ""))):
        problems.append("archiver.version is not a lib.exe banner")
    observed = staged.get("observed") or {}
    machines = observed.get("coff_machines") or {}
    actual_machines, actual_undecodable = observed_member_machines(archive)
    if machines != actual_machines:
        problems.append("observed.coff_machines does not match the archive")
    if "undecodable_members" not in observed:
        problems.append("observed.undecodable_members was not measured")
    elif observed.get("undecodable_members") != actual_undecodable:
        problems.append("observed.undecodable_members does not match the archive")
    if actual_undecodable:
        problems.append(f"archive has {actual_undecodable} undecodable object member(s)")
    if not machines:
        problems.append("the archive holds no COFF object member")
    elif set(machines) - {ARCH_MACHINES.get(arch.lower(), arch.lower())}:
        problems.append(f"objects for {sorted(machines)} in a {arch} cell")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--out-dir", type=Path, help="write the content-addressed receipt here")
    parser.add_argument("--check", type=Path, metavar="STAGED",
                        help="re-prove a staged receipt against --archive instead of writing one")
    args = parser.parse_args(argv)

    source_bytes = archive_receipt(args.archive)
    if args.check:
        data = args.check.read_bytes()
        staged = json.loads(data.decode("utf-8"))
        problems = problems_for(args.archive, staged, source_bytes, args.arch, args.configuration)
        match = CONTENT_ADDRESSED_RE.search(args.check.name)
        if not match or match.group(1) != hashlib.sha256(data).hexdigest():
            problems.append(f"{args.check.name} does not carry its own sha256")
    else:
        try:
            source = json.loads(source_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            print(f"msvc-toolchain-receipt: receipt inside the archive is not JSON: {error}",
                  file=sys.stderr)
            return 1
        staged = derive(args.archive, source, source_bytes, args.arch, args.configuration)
        problems = problems_for(args.archive, staged, source_bytes, args.arch, args.configuration)
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
    data = canonical_bytes(staged)
    target = args.out_dir / content_addressed_name(args.archive.name, data)
    target.write_bytes(data)
    print(f"msvc-toolchain-receipt: staged {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
