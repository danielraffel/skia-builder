#!/usr/bin/env python3
"""Write, and check, the Apple toolchain receipt for one macOS/iOS/visionOS cell.

An Apple static archive records, per object, only the platform, minimum OS
and SDK version (``LC_BUILD_VERSION``).  It does not record which compiler
build, archiver or linker produced it, or which libc++ ABI its C++ objects
were compiled against, so a consumer cannot tell from the archive whether its
own toolchain is compatible.  This receipt records the producer toolchain from
the runner that built the archive:

* the Xcode the build used (``xcode-select``/``DEVELOPER_DIR``) and its version;
* ``clang``/``clang++``: the path ``xcrun`` resolves, its SHA-256, and its
  ``--version`` banner, plus the ``cc``/``cxx`` commands GN wrote into
  ``toolchain.ninja`` (Skia's GN build calls bare ``clang``, so this is the
  authoritative compile command, including any ``ccache`` wrapper);
* ``ld``, ``libtool``, ``ar`` and ``lipo``: path, SHA-256 and version;
* the SDK: version, build version, path and the digest of its ``libc++.tbd``;
* the C++ standard-library ABI: ``_LIBCPP_VERSION``, ``_LIBCPP_ABI_VERSION``
  and the ABI namespace, read from the SDK headers by the same compiler for
  each built architecture;
* ``ccache``'s version and hit/miss counts, since a cache hit returns an
  object compiled earlier (by a byte-identical compiler, with
  ``CCACHE_COMPILERCHECK=content``);
* the runner image (``ImageOS``/``ImageVersion``) and macOS build.

The receipt then reads ``LC_BUILD_VERSION`` from every object member of every
packaged library and records the distinct (platform, minimum OS, SDK) tuples.
``--check`` fails when a field is empty or unknown, or when the SDK the
receipt names is not the SDK every object was built against: a receipt that
does not match its archive is worse than none.

``ld`` is not invoked to produce a static archive; it is recorded because the
consumer links these objects, and its version bounds which object features the
producer toolchain emits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apple_archive  # noqa: E402

SCHEMA = "skia-builder.apple-toolchain-receipt.v1"
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
CLANG_BANNER_RE = re.compile(r"^(Apple )?clang version \S+")
LD_VERSION_RE = re.compile(r"PROJECT:(ld\S*|dyld\S*)")
BAD_VALUE_RE = re.compile(r"^(unknown|error.*|)$", re.IGNORECASE)
CONTENT_ADDRESSED_RE = re.compile(r"\.apple-toolchain\.sha256-([0-9a-f]{64})\.json$")
TARGET_TRIPLES = {
    ("mac", "arm64"): "arm64-apple-macos{min}",
    ("mac", "x86_64"): "x86_64-apple-macos{min}",
    ("ios", "arm64"): "arm64-apple-ios{min}",
    ("ios", "x86_64"): "x86_64-apple-ios{min}-simulator",
    ("visionos", "arm64"): "arm64-apple-xros{min}",
}
SDK_NAMES = {"mac": "macosx", "ios": "iphoneos", "visionos": "xros"}
SIMULATOR_SDK_NAMES = {"ios": "iphonesimulator", "visionos": "xrsimulator"}

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def run(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=stdin, capture_output=True, text=True, check=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=1) + "\n").encode("utf-8")


def content_addressed_name(archive_name: str, data: bytes) -> str:
    stem = archive_name[:-4] if archive_name.endswith(".zip") else archive_name
    return f"{stem}.apple-toolchain.sha256-{hashlib.sha256(data).hexdigest()}.json"


class Probe:
    def __init__(self, runner: Runner = run, which: Callable[[str], str | None] = shutil.which,
                 hasher: Callable[[Path], str] = sha256_file,
                 realpath: Callable[[str], str] = os.path.realpath):
        self.runner, self.which, self.hasher, self.realpath = runner, which, hasher, realpath

    def out(self, args: list[str], stdin: str | None = None, stream: str = "stdout") -> str:
        try:
            done = self.runner(args, stdin) if stdin is not None else self.runner(args)
        except OSError as error:
            return f"error: {error}"
        text = done.stdout if stream == "stdout" else done.stderr
        if stream == "both":
            text = (done.stdout or "") + (done.stderr or "")
        return (text or "").strip() if done.returncode == 0 else f"error: exit {done.returncode}"

    def digest(self, path: Path) -> str:
        try:
            return self.hasher(path)
        except OSError:
            return "unknown"

    def tool(self, name: str, version_args: list[str], version_stream: str = "stdout",
             sdk: str = "macosx") -> dict[str, str]:
        path = self.out(["xcrun", "--sdk", sdk, "--find", name])
        row = {"path": path, "realpath": "unknown", "sha256": "unknown", "version": "unknown"}
        if path and not path.startswith("error"):
            real = self.realpath(path)
            row["realpath"] = real
            try:
                row["sha256"] = self.hasher(Path(real))
            except OSError as error:
                row["sha256"] = f"error: {error}"
            if version_args:
                version = self.out([path, *version_args], stream=version_stream)
                row["version"] = version.splitlines()[0] if version else "unknown"
            else:
                row["version"] = "not reported (the tool has no version flag)"
        return row

    def libcxx(self, clangxx: str, triple: str, sysroot: str) -> dict[str, str]:
        probe = ("#include <ciso646>\n#include <__config>\n"
                 "LIBCPP_VERSION=_LIBCPP_VERSION\nLIBCPP_ABI_VERSION=_LIBCPP_ABI_VERSION\n"
                 "LIBCPP_ABI_NAMESPACE=_LIBCPP_ABI_NAMESPACE\n")
        text = self.out([clangxx, "-target", triple, "-isysroot", sysroot, "-std=c++20",
                         "-E", "-P", "-x", "c++", "-"], stdin=probe)
        row = {"stdlib": "libc++", "target": triple}
        for key in ("LIBCPP_VERSION", "LIBCPP_ABI_VERSION", "LIBCPP_ABI_NAMESPACE"):
            match = re.search(rf"^{key}=(\S+)\s*$", text, re.MULTILINE)
            row[key.lower()] = match.group(1) if match else "unknown"
        return row


def toolchain_ninja_commands(path: Path) -> dict[str, str]:
    """The cc/cxx/alink commands GN wrote for the default toolchain."""
    commands: dict[str, str] = {}
    if not path.exists():
        return {"error": f"{path} not found"}
    rule = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^rule (\S+)$", line)
        if match:
            rule = match.group(1)
            continue
        match = re.match(r"^\s+command = (.*)$", line)
        if match and rule in ("cc", "cxx", "objc", "objcxx", "alink", "link", "solink"):
            commands.setdefault(rule, match.group(1))
    return commands


def observed_macho(archive: Path) -> dict[str, object]:
    """Distinct LC_BUILD_VERSION tuples across every object member of every library."""
    libraries: dict[str, object] = {}
    overall: Counter = Counter()
    with zipfile.ZipFile(archive) as handle:
        for info in sorted(handle.infolist(), key=lambda item: item.filename):
            if info.is_dir() or not info.filename.endswith(".a"):
                continue
            data = handle.read(info)
            per_arch: dict[str, object] = {}
            for piece in apple_archive.slices(data):
                tuples: Counter = Counter()
                for member in apple_archive.parse_archive(piece.data).members:
                    macho = apple_archive.parse_macho(member.data)
                    key = (f"{macho.platform}/{macho.minos}/{macho.sdk}" if macho and macho.sdk
                           else "no-build-version")
                    tuples[key] += 1
                    overall[(piece.arch, key)] += 1
                per_arch[piece.arch] = dict(sorted(tuples.items()))
            libraries[info.filename] = per_arch
    # An assembled object (for example ICU's data blob) records SDK 0.0: it was
    # not compiled against any SDK, so it does not count against the receipt.
    sdks = sorted({key.split("/")[2] for (_arch, key) in overall
                   if key != "no-build-version" and key.split("/")[2] != "0.0"})
    return {
        "libraries": libraries,
        "sdk_versions": sdks,
        "members_with_unset_sdk": sum(count for (_arch, key), count in overall.items()
                                      if key.endswith("/0.0")),
        "members_without_build_version": sum(count for (_arch, key), count in overall.items()
                                             if key == "no-build-version"),
    }


def build_receipt(platform_name: str, archs: list[str], configuration: str, variant: str,
                  min_os: str, toolchain_ninja: list[Path], archive: Path | None,
                  probe: Probe | None = None, target: str = "") -> dict[str, object]:
    probe = probe or Probe()
    simulator = target == "simulator"
    sdk = (SIMULATOR_SDK_NAMES if simulator else SDK_NAMES).get(platform_name, "macosx")
    sysroot = probe.out(["xcrun", "--sdk", sdk, "--show-sdk-path"])
    clang = probe.tool("clang", ["--version"], sdk=sdk)
    clangxx = probe.tool("clang++", ["--version"], sdk=sdk)
    libcxx_tbd = Path(sysroot) / "usr" / "lib" / "libc++.tbd"
    abi = {}
    for arch in archs:
        triple = TARGET_TRIPLES.get((platform_name, arch), f"{arch}-apple-macos{{min}}").format(min=min_os)
        if simulator and not triple.endswith("-simulator"):
            triple += "-simulator"
        abi[arch] = probe.libcxx(clangxx["path"], triple, sysroot)
    cc_on_path = probe.which("clang")
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "target": {"platform": platform_name, "architectures": archs, "configuration": configuration,
                   "variant": variant, "minimum_os": min_os, "sdk_name": sdk},
        "runner": {
            "image_os": os.environ.get("ImageOS", "local"),
            "image_version": os.environ.get("ImageVersion", "local"),
            "runner_arch": os.environ.get("RUNNER_ARCH", platform.machine()),
            "macos_product_version": probe.out(["sw_vers", "-productVersion"]),
            "macos_build_version": probe.out(["sw_vers", "-buildVersion"]),
        },
        "xcode": {
            "developer_dir": os.environ.get("DEVELOPER_DIR") or probe.out(["xcode-select", "-p"]),
            "version": " ".join(probe.out(["xcodebuild", "-version"]).split()),
        },
        "compiler": {
            "c": clang,
            "cxx": clangxx,
            "clang_on_path": {"path": cc_on_path or "unknown",
                              "note": "GN's mac toolchain invokes bare clang/clang++ from PATH; "
                                      "/usr/bin/clang is the xcrun shim that resolves to compiler.c"},
            "gn_toolchain_commands": {str(path): toolchain_ninja_commands(path) for path in toolchain_ninja},
        },
        "archiver": {
            "libtool": probe.tool("libtool", ["-V"], sdk=sdk),
            "ar": probe.tool("ar", [], sdk=sdk),
            "lipo": probe.tool("lipo", [], sdk=sdk),
        },
        "linker": dict(probe.tool("ld", ["-v"], version_stream="stderr", sdk=sdk),
                       note="not invoked for static archives; recorded for consumers that link them"),
        "sdk": {
            "path": sysroot,
            "version": probe.out(["xcrun", "--sdk", sdk, "--show-sdk-version"]),
            "build_version": probe.out(["xcrun", "--sdk", sdk, "--show-sdk-build-version"]),
            "libcxx_tbd_sha256": probe.digest(libcxx_tbd),
        },
        "cpp_abi": abi,
        "ccache": ccache_state(probe),
    }
    if archive is not None:
        receipt["archive"] = {"name": archive.name, "sha256": sha256_file(archive)}
        receipt["observed_macho"] = observed_macho(archive)
    return receipt


def ccache_state(probe: Probe) -> dict[str, object]:
    if not probe.which("ccache"):
        return {"used": False}
    stats: dict[str, str] = {}
    for line in probe.out(["ccache", "--print-stats"]).splitlines():
        key, _, value = line.partition("\t")
        if key in ("direct_cache_hit", "preprocessed_cache_hit", "cache_miss",
                   "local_storage_hit", "local_storage_miss"):
            stats[key] = value.strip()
    return {
        "used": True,
        "version": (probe.out(["ccache", "--version"]).splitlines() or ["unknown"])[0],
        "compiler_check": os.environ.get("CCACHE_COMPILERCHECK", "mtime"),
        "stats": stats,
    }


def validate_receipt(receipt: dict, archive: Path | None = None) -> list[str]:
    problems: list[str] = []

    def walk(value: object, where: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if where.startswith("compiler.gn_toolchain_commands") or key == "stats":
                    continue
                walk(item, f"{where}.{key}" if where else key)
        elif isinstance(value, str):
            if BAD_VALUE_RE.match(value.strip()) or value.startswith("error"):
                problems.append(f"{where} = {value!r}")
        elif value is None:
            problems.append(f"{where} is null")

    walk({key: receipt.get(key) for key in ("target", "runner", "xcode", "compiler", "archiver",
                                           "linker", "sdk", "cpp_abi")}, "")
    if receipt.get("schema") != SCHEMA:
        problems.append(f"schema = {receipt.get('schema')!r}")
    compiler = receipt.get("compiler") or {}
    for side in ("c", "cxx"):
        row = compiler.get(side) or {}
        if not CLANG_BANNER_RE.match(str(row.get("version", ""))):
            problems.append(f"compiler.{side}.version {row.get('version')!r} is not a clang banner")
        if not HEX_64.match(str(row.get("sha256", ""))):
            problems.append(f"compiler.{side}.sha256 is not a SHA-256")
    linker = receipt.get("linker") or {}
    if not LD_VERSION_RE.search(str(linker.get("version", ""))):
        problems.append(f"linker.version {linker.get('version')!r} is not an ld PROJECT version")
    for name, row in (receipt.get("archiver") or {}).items():
        if not HEX_64.match(str(row.get("sha256", ""))):
            problems.append(f"archiver.{name}.sha256 is not a SHA-256")
    commands = compiler.get("gn_toolchain_commands") or {}
    if not commands:
        problems.append("compiler.gn_toolchain_commands is empty")
    for path, rules in commands.items():
        if "error" in rules or not rules.get("cxx"):
            problems.append(f"{path}: no cxx command recorded")
    sdk = receipt.get("sdk") or {}
    observed = receipt.get("observed_macho")
    if observed is not None:
        if observed.get("sdk_versions") != [sdk.get("version")]:
            problems.append(f"objects were built against SDK(s) {observed.get('sdk_versions')}, "
                            f"receipt names {sdk.get('version')!r}")
        if observed.get("members_without_build_version"):
            problems.append(f"{observed['members_without_build_version']} object member(s) "
                            "carry no LC_BUILD_VERSION")
    if archive is not None:
        actual = sha256_file(archive)
        if (receipt.get("archive") or {}).get("sha256") != actual:
            problems.append(f"receipt archive sha256 != {actual}")
        if observed is not None and observed != observed_macho(archive):
            problems.append("observed_macho does not match the archive")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--platform", default="mac", choices=sorted(SDK_NAMES))
    parser.add_argument("--target", default="", help="device or simulator (iOS/visionOS)")
    parser.add_argument("--arch", action="append", default=[], help="repeat per built architecture")
    parser.add_argument("--configuration", default="Release")
    parser.add_argument("--variant", default="gpu")
    parser.add_argument("--min-os", default="13.0")
    parser.add_argument("--toolchain-ninja", action="append", type=Path, default=[],
                        help="GN toolchain.ninja per architecture")
    parser.add_argument("--content-addressed-dir", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="validate an existing receipt (against --archive) instead of writing one")
    args = parser.parse_args(argv)

    if args.check:
        receipt = json.loads(args.output.read_text(encoding="utf-8"))
        problems = validate_receipt(receipt, args.archive)
        match = CONTENT_ADDRESSED_RE.search(args.output.name)
        if match and match.group(1) != sha256_file(args.output):
            problems.append(f"{args.output.name} does not carry its own sha256")
        for problem in problems:
            print(f"apple-toolchain-receipt: {problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"apple-toolchain-receipt: {args.output} is proven")
        return 0

    if not args.arch:
        parser.error("--arch is required")
    receipt = build_receipt(args.platform, args.arch, args.configuration, args.variant, args.min_os,
                            args.toolchain_ninja, args.archive, target=args.target)
    data = canonical_bytes(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    problems = validate_receipt(receipt, args.archive)
    for problem in problems:
        print(f"apple-toolchain-receipt: {problem}", file=sys.stderr)
    if args.content_addressed_dir and not problems:
        args.content_addressed_dir.mkdir(parents=True, exist_ok=True)
        target = args.content_addressed_dir / content_addressed_name(
            args.archive.name if args.archive else "toolchain", data)
        target.write_bytes(data)
        print(f"apple-toolchain-receipt: content-addressed copy {target}")
    print(json.dumps({key: receipt[key] for key in ("xcode", "sdk", "cpp_abi")}, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
