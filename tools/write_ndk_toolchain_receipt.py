#!/usr/bin/env python3
"""Write, and check, the Android NDK toolchain receipt for one ABI cell.

An Android static archive records the compiler only as a free-text ELF
``.comment`` string.  This receipt records the producer toolchain from the
runner that built it:

* the NDK revision (``source.properties``) and the minimum API level;
* the NDK's ``clang++``, ``ld.lld`` and ``llvm-ar``: absolute path, SHA-256,
  ``--version`` first line and vendor, plus the ``cc``/``cxx`` commands GN
  wrote into ``toolchain.ninja``;
* the C++ standard library: the NDK's libc++, with ``_LIBCPP_VERSION`` and
  ``_LIBCPP_ABI_VERSION`` read from its headers by the same compiler;
* the runner image;
* ``observed``: the ELF machine of every object member of every packaged
  library, the target triple the NDK compiler reports, and the clang each
  object records in ``.comment``.

``--check`` fails when a field is empty or unknown, when the archive is not
the one the receipt names, when an object is for another ABI, or when a
clang-written object names a different clang than the receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import write_apple_toolchain_receipt as apple  # noqa: E402
import write_linux_toolchain_receipt as linux  # noqa: E402

SCHEMA = "skia-builder.ndk-toolchain-receipt.v1"
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
BAD_VALUE_RE = re.compile(r"^(unknown|error.*|)$", re.IGNORECASE)
CONTENT_ADDRESSED_RE = re.compile(r"\.ndk-toolchain\.sha256-([0-9a-f]{64})\.json$")
ABI_ELF = {"arm64-v8a": "arm64", "x86_64": "x64"}
ABI_TRIPLE = {"arm64-v8a": "aarch64-linux-android", "x86_64": "x86_64-linux-android"}
LLD_RE = re.compile(r"LLD \d+\.\d+")
LLVM_AR_RE = re.compile(r"(LLVM|llvm)")
REVISION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def content_addressed_name(archive_name: str, data: bytes) -> str:
    return linux.content_addressed_name(archive_name, data).replace(".linux-toolchain.", ".ndk-toolchain.")


def ndk_revision(ndk: Path) -> str:
    try:
        for line in (ndk / "source.properties").read_text(encoding="utf-8").splitlines():
            if line.startswith("Pkg.Revision"):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def build_receipt(abi: str, api_level: int, configuration: str, variant: str, ndk: Path,
                  toolchain_ninja: list[Path], archive: Path | None,
                  probe: apple.Probe | None = None) -> dict[str, object]:
    probe = probe or apple.Probe()
    commands = {str(path): apple.toolchain_ninja_commands(path) for path in toolchain_ninja}
    first = next(iter(commands.values()), {})
    bin_dir = ndk / "toolchains" / "llvm" / "prebuilt" / "linux-x86_64" / "bin"
    cxx_program = linux.compiler_program(first.get("cxx", "")) or str(bin_dir / "clang++")
    cc_program = linux.compiler_program(first.get("cc", "")) or str(bin_dir / "clang")
    cxx = dict(linux.tool_row(probe, cxx_program, ["--version"]), vendor="clang")
    cc = dict(linux.tool_row(probe, cc_program, ["--version"]), vendor="clang")
    linker = dict(linux.tool_row(probe, str(bin_dir / "ld.lld"), ["--version"]), vendor="lld",
                  note="not invoked for static archives; recorded for consumers that link them")
    archiver = dict(linux.tool_row(probe, str(bin_dir / "llvm-ar"), ["--version"]), vendor="llvm")
    triple = f"{ABI_TRIPLE[abi]}{api_level}"
    probe_source = ("#include <__config>\nLIBCPP_VERSION=_LIBCPP_VERSION\n"
                    "LIBCPP_ABI_VERSION=_LIBCPP_ABI_VERSION\n")
    text = probe.out([cxx["path"], f"--target={triple}", "-std=c++20", "-E", "-P", "-x", "c++", "-"],
                     stdin=probe_source)
    libcxx = {"stdlib": "libc++", "target": triple}
    for key in ("LIBCPP_VERSION", "LIBCPP_ABI_VERSION"):
        found = re.search(rf"^{key}=(\S+)\s*$", text, re.MULTILINE)
        libcxx[key.lower()] = found.group(1) if found else "unknown"
    libcxx["stdlib_version"] = libcxx["libcpp_version"]
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "target": {"platform": "android", "architectures": [abi], "configuration": configuration,
                   "variant": variant},
        "ndk": {"revision": ndk_revision(ndk)},
        "api_level": api_level,
        "runner_image": {"name": os.environ.get("ImageOS", "local"),
                         "version": os.environ.get("ImageVersion", "local")},
        "compiler": {"c": cc, "cxx": cxx,
                     "target_triple": probe.out([cxx["path"], f"--target={triple}", "-dumpmachine"]),
                     "gn_toolchain_commands": commands},
        "linker": linker,
        "archiver": archiver,
        "cpp_abi": {abi: libcxx},
        "ccache": apple.ccache_state(probe),
    }
    if archive is not None:
        receipt["archive"] = {"name": archive.name, "sha256": apple.sha256_file(archive)}
        observed = linux.observed_elf(archive)
        receipt["observed_elf"] = observed
        receipt["observed"] = {"elf_machines": sorted(observed["machines"]),
                               "target_triple": triple}
    return receipt


def validate_receipt(receipt: dict, archive: Path | None = None) -> list[str]:
    problems: list[str] = []

    def walk(value: object, where: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("gn_toolchain_commands", "stats"):
                    continue
                walk(item, f"{where}.{key}" if where else key)
        elif isinstance(value, str):
            if BAD_VALUE_RE.match(value.strip()) or value.startswith("error"):
                problems.append(f"{where} = {value!r}")
        elif value is None:
            problems.append(f"{where} is null")

    walk({key: receipt.get(key) for key in ("target", "ndk", "runner_image", "compiler", "linker",
                                           "archiver", "cpp_abi")}, "")
    if receipt.get("schema") != SCHEMA:
        problems.append(f"schema = {receipt.get('schema')!r}")
    if not REVISION_RE.match(str((receipt.get("ndk") or {}).get("revision", ""))):
        problems.append("ndk.revision is not a Pkg.Revision")
    if not isinstance(receipt.get("api_level"), int):
        problems.append("api_level is not an integer")
    compiler = receipt.get("compiler") or {}
    versions: set[str] = set()
    for side in ("c", "cxx"):
        row = compiler.get(side) or {}
        banner = linux.CLANG_BANNER_RE.search(str(row.get("version", "")))
        if not banner:
            problems.append(f"compiler.{side}.version {row.get('version')!r} is not a clang banner")
        else:
            versions.add(banner.group(1))
        if not HEX_64.match(str(row.get("sha256", ""))):
            problems.append(f"compiler.{side}.sha256 is not a SHA-256")
        if not str(row.get("path", "")).startswith("/"):
            problems.append(f"compiler.{side}.path is not absolute")
    if len(versions) > 1:
        problems.append(f"cc and cxx are different clang versions: {sorted(versions)}")
    for name, regex in (("linker", LLD_RE), ("archiver", LLVM_AR_RE)):
        row = receipt.get(name) or {}
        if not HEX_64.match(str(row.get("sha256", ""))):
            problems.append(f"{name}.sha256 is not a SHA-256")
        if not str(row.get("path", "")).startswith("/"):
            problems.append(f"{name}.path is not absolute")
        if not regex.search(str(row.get("version", ""))):
            problems.append(f"{name}.version {row.get('version')!r} is not a {name} banner")
    abi = ((receipt.get("target") or {}).get("architectures") or [""])[0]
    libcxx = (receipt.get("cpp_abi") or {}).get(abi) or {}
    if libcxx.get("stdlib") != "libc++" or not re.fullmatch(r"\d+", str(libcxx.get("stdlib_version", ""))):
        problems.append("cpp_abi has no libc++ version for the target ABI")
    if not compiler.get("gn_toolchain_commands"):
        problems.append("compiler.gn_toolchain_commands is empty")
    observed = receipt.get("observed_elf")
    if observed is not None:
        machines = observed.get("machines") or {}
        want = ABI_ELF.get(abi, "")
        if not machines:
            problems.append("the archive holds no ELF object member")
        if want and set(machines) - {want}:
            problems.append(f"objects for {sorted(set(machines) - {want})} in a {abi} cell")
        clang = {m.group(1) for text in (observed.get("comments") or {})
                 for m in [linux.CLANG_BANNER_RE.search(text)] if m}
        if not clang:
            problems.append("no object member records the clang that built it")
        elif versions and clang != versions:
            problems.append(f"objects were built by clang {sorted(clang)}, receipt names {sorted(versions)}")
        triple = (receipt.get("observed") or {}).get("target_triple", "")
        if not triple.startswith(ABI_TRIPLE.get(abi, "?")):
            problems.append(f"observed.target_triple {triple!r} is not for {abi}")
    if archive is not None:
        if (receipt.get("archive") or {}).get("sha256") != apple.sha256_file(archive):
            problems.append("receipt archive sha256 does not match the archive")
        if observed is not None and observed != linux.observed_elf(archive):
            problems.append("observed_elf does not match the archive")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--abi", choices=sorted(ABI_ELF))
    parser.add_argument("--api-level", type=int, default=26)
    parser.add_argument("--ndk", type=Path, default=Path(os.environ.get("ANDROID_NDK_HOME", "")))
    parser.add_argument("--configuration", default="Release")
    parser.add_argument("--variant", default="gpu")
    parser.add_argument("--toolchain-ninja", action="append", type=Path, default=[])
    parser.add_argument("--content-addressed-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.check:
        receipt = json.loads(args.output.read_text(encoding="utf-8"))
        problems = validate_receipt(receipt, args.archive)
        match = CONTENT_ADDRESSED_RE.search(args.output.name)
        if match and match.group(1) != apple.sha256_file(args.output):
            problems.append(f"{args.output.name} does not carry its own sha256")
        for problem in problems:
            print(f"ndk-toolchain-receipt: {problem}", file=sys.stderr)
        if not problems:
            print(f"ndk-toolchain-receipt: {args.output} is proven")
        return 1 if problems else 0

    if not args.abi:
        parser.error("--abi is required")
    receipt = build_receipt(args.abi, args.api_level, args.configuration, args.variant, args.ndk,
                            args.toolchain_ninja, args.archive)
    data = apple.canonical_bytes(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    problems = validate_receipt(receipt, args.archive)
    for problem in problems:
        print(f"ndk-toolchain-receipt: {problem}", file=sys.stderr)
    if args.content_addressed_dir and not problems:
        args.content_addressed_dir.mkdir(parents=True, exist_ok=True)
        target = args.content_addressed_dir / content_addressed_name(
            args.archive.name if args.archive else "toolchain", data)
        target.write_bytes(data)
        print(f"ndk-toolchain-receipt: content-addressed copy {target}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
