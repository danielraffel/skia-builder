#!/usr/bin/env python3
"""Write, and check, the toolchain receipt for one Linux cell.

A Linux static archive records, per object, the compiler that wrote it only as
a free-text ``.comment`` string.  It does not record which linker or archiver
ran, or which C library and C++ standard-library release the objects were
compiled against, so a consumer cannot tell from the archive whether its own
toolchain is compatible.  This receipt records the producer toolchain from the
runner that built the archive:

* the ``cc``/``cxx`` commands GN wrote into ``toolchain.ninja`` (the
  authoritative compile command, including any ``ccache`` wrapper), and the
  compiler each resolves to: path, SHA-256, ``--version`` banner and target
  triple;
* ``ar`` and ``ld``: path, SHA-256 and version;
* the C library (glibc) version and the libstdc++ release the compiler's
  headers define (``_GLIBCXX_RELEASE``);
* the OS release, runner image and, for the container build, the base image;
* ``ccache``'s version and hit/miss counts;
* the ELF facts of every object member of every packaged library: machine,
  class and the distinct ``.comment`` strings.

``--check`` takes the cell the caller built (``--arch``, ``--configuration``,
``--variant``) and fails when the receipt claims any other target, when a
field is empty or unknown, when the archive is not the one the receipt names, when an object is not for the cell's architecture,
or when a clang-written object was produced by a different clang than the
receipt names: a receipt that does not match its archive is worse than none.

The glibc floor an archive needs is proved separately by the portable build's
link-probe; this receipt records the producer, not the floor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import struct
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apple_archive  # noqa: E402
import write_apple_toolchain_receipt as apple  # noqa: E402

SCHEMA = "skia-builder.linux-toolchain-receipt.v1"
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
CLANG_BANNER_RE = re.compile(r"clang version (\d+\.\d+\.\d+)")
LD_BANNER_RE = re.compile(r"^(GNU ld|GNU gold|LLD)\b.*\d+\.\d+")
AR_BANNER_RE = re.compile(r"^GNU ar\b.*\d+\.\d+")
GLIBC_RE = re.compile(r"(\d+\.\d+)\s*$")
BAD_VALUE_RE = re.compile(r"^(unknown|error.*|)$", re.IGNORECASE)
CONTENT_ADDRESSED_RE = re.compile(r"\.linux-toolchain\.sha256-([0-9a-f]{64})\.json$")
WRAPPERS = {"ccache", "sccache", "distcc"}
ARCH_NAMES = {"x64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}


def content_addressed_name(archive_name: str, data: bytes) -> str:
    stem = archive_name[:-4] if archive_name.endswith(".zip") else archive_name
    return f"{stem}.linux-toolchain.sha256-{hashlib.sha256(data).hexdigest()}.json"


def elf_facts(data: bytes) -> dict[str, object] | None:
    """Class, machine and ``.comment`` strings of a little-endian ELF64 object."""
    if data[:4] != b"\x7fELF" or len(data) < 64 or data[4] != 2 or data[5] != 1:
        return None
    machine = struct.unpack("<H", data[18:20])[0]
    shoff = struct.unpack("<Q", data[40:48])[0]
    shentsize, shnum, shstrndx = struct.unpack("<HHH", data[58:64])
    comments: list[str] = []
    if shoff and shnum and shentsize >= 64 and shoff + shentsize * shnum <= len(data):
        def header(index: int) -> tuple[int, int, int]:
            base = shoff + index * shentsize
            name, _type, _flags, _addr, offset, size = struct.unpack("<IIQQQQ", data[base:base + 40])
            return name, offset, size
        if shstrndx < shnum:
            _n, str_offset, str_size = header(shstrndx)
            names = data[str_offset:str_offset + str_size]
            for index in range(shnum):
                name, offset, size = header(index)
                end = names.find(b"\0", name)
                if names[name:end] == b".comment":
                    blob = data[offset:offset + size]
                    comments = [part.decode("utf-8", "replace") for part in blob.split(b"\0") if part]
    return {"machine": apple_archive.ELF_MACHINES.get(machine, f"e_machine-{machine}"),
            "comments": sorted(set(comments))}


def observed_elf(archive: Path) -> dict[str, object]:
    """Machines and ``.comment`` strings across every object member of every library."""
    machines: Counter = Counter()
    comments: Counter = Counter()
    without_comment = 0
    non_elf = 0
    libraries: dict[str, int] = {}
    with zipfile.ZipFile(archive) as handle:
        for info in sorted(handle.infolist(), key=lambda item: item.filename):
            if info.is_dir() or not info.filename.endswith(".a"):
                continue
            members = apple_archive.parse_archive(handle.read(info)).members
            libraries[info.filename] = len(members)
            for member in members:
                facts = elf_facts(member.data)
                if facts is None:
                    non_elf += 1
                    continue
                machines[facts["machine"]] += 1
                if not facts["comments"]:
                    without_comment += 1
                for comment in facts["comments"]:
                    comments[comment] += 1
    return {"libraries": libraries, "machines": dict(sorted(machines.items())),
            "comments": dict(sorted(comments.items())), "members_without_comment": without_comment,
            "members_not_elf": non_elf}


def compiler_program(command: str) -> str:
    """The compiler a GN rule command invokes, past any ccache-style wrapper."""
    for token in command.split():
        if "=" in token and not token.startswith("/"):
            continue  # an environment assignment
        if Path(token).name in WRAPPERS:
            continue
        return token
    return ""


def tool_row(probe: apple.Probe, program: str, version_args: list[str]) -> dict[str, str]:
    path = program if os.path.isabs(program) else (probe.which(program) or "")
    row = {"path": path or "unknown", "realpath": "unknown", "sha256": "unknown", "version": "unknown"}
    if path:
        real = probe.realpath(path)
        row["realpath"] = real
        try:
            row["sha256"] = probe.hasher(Path(real))
        except OSError as error:
            row["sha256"] = f"error: {error}"
        banner = probe.out([path, *version_args], stream="both")
        row["version"] = banner.splitlines()[0] if banner else "unknown"
    return row


def build_receipt(arch: str, configuration: str, variant: str, toolchain_ninja: list[Path],
                  archive: Path | None, probe: apple.Probe | None = None,
                  container_image: str = "", link_probe_enabled: bool = False,
                  os_release_path: Path = Path("/etc/os-release")) -> dict[str, object]:
    probe = probe or apple.Probe()
    commands = {str(path): apple.toolchain_ninja_commands(path) for path in toolchain_ninja}
    first = next(iter(commands.values()), {})
    cc = tool_row(probe, compiler_program(first.get("cc", "")), ["--version"])
    cxx = tool_row(probe, compiler_program(first.get("cxx", "")), ["--version"])
    cxx_path = cxx["path"] if cxx["path"] != "unknown" else "c++"
    probe_source = "#include <bits/c++config.h>\nGLIBCXX_RELEASE=_GLIBCXX_RELEASE\n"
    release = probe.out([cxx_path, "-std=c++20", "-E", "-P", "-x", "c++", "-"], stdin=probe_source)
    match = re.search(r"^GLIBCXX_RELEASE=(\d+)\s*$", release, re.MULTILINE)
    glibc_banner = probe.out(["ldd", "--version"], stream="both")
    glibc_match = GLIBC_RE.search(glibc_banner.splitlines()[0]) if glibc_banner else None
    os_release: dict[str, str] = {}
    try:
        for line in os_release_path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            os_release[key] = value.strip('"')
    except OSError:
        pass
    glibcxx = match.group(1) if match else "unknown"
    cxx["vendor"] = cc["vendor"] = "clang"
    archiver = dict(tool_row(probe, "ar", ["--version"]), vendor="gnu-binutils")
    linker = dict(tool_row(probe, "ld", ["--version"]), vendor="gnu-ld",
                  note="not invoked for static archives; recorded for consumers that link them")
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "target": {"platform": "linux", "architectures": [arch], "configuration": configuration,
                   "variant": variant},
        "runner": {
            "runner_arch": os.environ.get("RUNNER_ARCH", platform.machine()),
            "os_release": os_release.get("PRETTY_NAME", "unknown"),
            "container_image": container_image or "none",
        },
        "runner_image": {"name": os.environ.get("ImageOS", "local"),
                         "version": os.environ.get("ImageVersion", "local")},
        "compiler": {
            "c": cc,
            "cxx": cxx,
            "target_triple": probe.out([cxx_path, "-dumpmachine"]),
            "gn_toolchain_commands": commands,
        },
        "archiver": archiver,
        "linker": linker,
        "cpp_abi": {arch: {"stdlib": "libstdc++", "stdlib_version": glibcxx,
                           "glibcxx_release": glibcxx}},
        "libc": {"name": "glibc",
                 "version": glibc_match.group(1) if glibc_match else "unknown"},
        "ccache": apple.ccache_state(probe),
    }
    if archive is not None:
        receipt["archive"] = {"name": archive.name, "sha256": apple.sha256_file(archive)}
        receipt["observed_elf"] = observed_elf(archive)
        receipt["observed"] = {
            "elf_machines": sorted(receipt["observed_elf"]["machines"]),
            **(link_probe(archive, cxx_path, probe) if link_probe_enabled else {}),
        }
    return receipt


def symbol_versions(objdump_output: str) -> dict[str, str]:
    """The highest GLIBC_ and GLIBCXX_ version an ``objdump -T`` listing references."""
    found: dict[str, tuple[int, ...]] = {}
    for family, version in re.findall(r"\b(GLIBCXX|GLIBC)_([0-9]+(?:\.[0-9]+)+)", objdump_output):
        key = tuple(int(part) for part in version.split("."))
        if family not in found or key > found[family]:
            found[family] = key
    return {f"max_{family.lower()}_version": ".".join(str(part) for part in key)
            for family, key in sorted(found.items())}


PROBE_LIBRARIES = ("libskia.a", "libdawn_combined.a")


def link_probe(archive: Path, cxx: str, probe: apple.Probe) -> dict[str, str]:
    """Link the two big libraries whole into a throwaway executable and read its symbol versions.

    A static archive's undefined references are unversioned; only a link
    against the shared C and C++ libraries records the GLIBC_ and GLIBCXX_
    versions the objects need.  The probe links exactly what the build's
    glibc-floor gate links (libskia.a and libdawn_combined.a), because the
    smaller modules add nothing the floor depends on and do not link alone.
    A failed link is reported with the linker's own message, not as a
    missing number.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as temporary, zipfile.ZipFile(archive) as handle:
        libraries = []
        for info in handle.infolist():
            if Path(info.filename).name in PROBE_LIBRARIES:
                target = Path(temporary) / Path(info.filename).name
                target.write_bytes(handle.read(info))
                libraries.append(str(target))
        if len(libraries) != len(PROBE_LIBRARIES):
            return {"link_error": f"archive lacks one of {PROBE_LIBRARIES}"}
        source = Path(temporary) / "probe.c"
        source.write_text("int main(void){return 0;}\n")
        exe = Path(temporary) / "probe"
        done = probe.runner([cxx, str(source), "-Wl,--whole-archive", *libraries,
                             "-Wl,--no-whole-archive", "-Wl,--unresolved-symbols=ignore-all",
                             "-lstdc++", "-lm", "-lpthread", "-ldl", "-o", str(exe)])
        if done.returncode != 0:
            return {"link_error": ((done.stderr or "").strip() or f"exit {done.returncode}")[-400:]}
        return symbol_versions(probe.out(["objdump", "-T", str(exe)]))


def target_problems(target: object, arch: str, configuration: str, variant: str) -> list[str]:
    """Reasons ``target`` is not exactly the Linux cell the caller built."""
    target = target if isinstance(target, dict) else {}
    problems: list[str] = []
    expected_arch = ARCH_NAMES.get(str(arch).lower(), "")
    if not expected_arch:
        problems.append(f"expected architecture {arch!r} is not a Linux architecture")
    if target.get("platform") != "linux":
        problems.append(f"target.platform {target.get('platform')!r} != 'linux'")
    claimed = target.get("architectures")
    if not isinstance(claimed, list) or len(claimed) != 1:
        problems.append(f"target.architectures {claimed!r} is not exactly one architecture")
    elif not ARCH_NAMES.get(str(claimed[0]).lower()):
        problems.append(f"target.architectures {claimed!r} names an unknown architecture")
    elif expected_arch and ARCH_NAMES[str(claimed[0]).lower()] != expected_arch:
        problems.append(f"target.architectures {claimed!r} != [{arch!r}]")
    if not configuration or target.get("configuration") != configuration:
        problems.append(f"target.configuration {target.get('configuration')!r} != {configuration!r}")
    if not variant or target.get("variant") != variant:
        problems.append(f"target.variant {target.get('variant')!r} != {variant!r}")
    return problems


def validate_receipt(receipt: dict, archive: Path | None = None, *, arch: str,
                     configuration: str, variant: str) -> list[str]:
    """Every reason ``receipt`` does not prove the named Linux cell.

    The expected cell is required: a receipt is only meaningful for the cell
    the caller built, never for whatever target it claims.
    """
    problems: list[str] = target_problems(receipt.get("target"), arch, configuration, variant)

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

    walk({key: receipt.get(key) for key in ("target", "runner", "runner_image", "compiler", "archiver",
                                           "linker", "libc", "cpp_abi")}, "")
    if receipt.get("schema") != SCHEMA:
        problems.append(f"schema = {receipt.get('schema')!r}")
    compiler = receipt.get("compiler") or {}
    versions: set[str] = set()
    for side in ("c", "cxx"):
        row = compiler.get(side) or {}
        banner = CLANG_BANNER_RE.search(str(row.get("version", "")))
        if not banner:
            problems.append(f"compiler.{side}.version {row.get('version')!r} is not a clang banner")
        else:
            versions.add(banner.group(1))
        if not HEX_64.match(str(row.get("sha256", ""))):
            problems.append(f"compiler.{side}.sha256 is not a SHA-256")
    if len(versions) > 1:
        problems.append(f"cc and cxx are different clang versions: {sorted(versions)}")
    if not LD_BANNER_RE.match(str((receipt.get("linker") or {}).get("version", ""))):
        problems.append(f"linker.version {(receipt.get('linker') or {}).get('version')!r} "
                        "is not an ld banner")
    archiver = receipt.get("archiver") or {}
    if not HEX_64.match(str(archiver.get("sha256", ""))):
        problems.append("archiver.sha256 is not a SHA-256")
    if not AR_BANNER_RE.match(str(archiver.get("version", ""))):
        problems.append(f"archiver.version {archiver.get('version')!r} is not an ar banner")
    for row_name in ("c", "cxx"):
        if not str((compiler.get(row_name) or {}).get("path", "")).startswith("/"):
            problems.append(f"compiler.{row_name}.path is not absolute")
    if not str(archiver.get("path", "")).startswith("/"):
        problems.append("archiver.path is not absolute")
    if not str((receipt.get("linker") or {}).get("path", "")).startswith("/"):
        problems.append("linker.path is not absolute")
    target_arch = ((receipt.get("target") or {}).get("architectures") or [""])[0]
    abi = (receipt.get("cpp_abi") or {}).get(target_arch) or {}
    if not re.fullmatch(r"\d+", str(abi.get("stdlib_version", ""))) or abi.get("stdlib") != "libstdc++":
        problems.append("cpp_abi has no libstdc++ release for the target architecture")
    if not re.fullmatch(r"\d+\.\d+", str((receipt.get("libc") or {}).get("version", ""))):
        problems.append("libc.version is not a glibc version")
    commands = compiler.get("gn_toolchain_commands") or {}
    if not commands:
        problems.append("compiler.gn_toolchain_commands is empty")
    for path, rules in commands.items():
        if "error" in rules or not rules.get("cxx"):
            problems.append(f"{path}: no cxx command recorded")
    observed = receipt.get("observed_elf")
    if not isinstance(observed, dict):
        problems.append("observed_elf is required")
        observed = {}
    required_observed = ("libraries", "machines", "comments", "members_without_comment",
                         "members_not_elf")
    for key in required_observed:
        if key not in observed:
            problems.append(f"observed_elf.{key} was not measured")
    arch = ARCH_NAMES.get(str(target_arch).lower(), "")
    machines = observed.get("machines") or {}
    if not machines:
        problems.append("the archive holds no ELF object member")
    if not arch:
        problems.append(f"no known architecture to compare object machines against ({target_arch!r})")
    elif set(machines) - {arch}:
        problems.append(f"objects for {sorted(set(machines) - {arch})} in a {arch} cell")
    if observed.get("members_not_elf", 0):
        problems.append(f"archive has {observed['members_not_elf']} member(s) that are not ELF")
    if observed.get("members_without_comment", 0):
        problems.append(f"archive has {observed['members_without_comment']} ELF member(s) without .comment")
    clang = {match.group(1) for text in (observed.get("comments") or {})
             for match in [CLANG_BANNER_RE.search(text)] if match}
    if not clang:
        problems.append("no object member records the clang that built it")
    elif versions and clang != versions:
        problems.append(f"objects were built by clang {sorted(clang)}, receipt names {sorted(versions)}")
    observed_symbols = receipt.get("observed")
    if not isinstance(observed_symbols, dict):
        problems.append("observed link-probe data is required")
        observed_symbols = {}
    for key in ("max_glibc_version", "max_glibcxx_version"):
        if not re.fullmatch(r"\d+(\.\d+)+", str(observed_symbols.get(key, ""))):
            problems.append(f"observed.{key} was not measured"
                            + (f" (link probe: {observed_symbols['link_error']})"
                               if observed_symbols.get("link_error") else ""))
    host = str((receipt.get("libc") or {}).get("version", ""))
    needed = str(observed_symbols.get("max_glibc_version", ""))
    if re.fullmatch(r"\d+(\.\d+)+", needed) and re.fullmatch(r"\d+\.\d+", host) \
            and tuple(map(int, needed.split("."))) > tuple(map(int, host.split("."))):
        problems.append(f"objects need glibc {needed}, newer than the producer's {host}")
    if archive is not None:
        actual = apple.sha256_file(archive)
        if (receipt.get("archive") or {}).get("sha256") != actual:
            problems.append(f"receipt archive sha256 != {actual}")
        if observed != observed_elf(archive):
            problems.append("observed_elf does not match the archive")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--arch", required=True, help="the cell's architecture (x64 or arm64)")
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--toolchain-ninja", action="append", type=Path, default=[],
                        help="GN toolchain.ninja for the built architecture")
    parser.add_argument("--link-probe", action="store_true",
                        help="link the libraries whole and record the highest GLIBC_/GLIBCXX_ versions")
    parser.add_argument("--container-image", default="",
                        help="digest-pinned base image the build ran in, if any")
    parser.add_argument("--content-addressed-dir", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="validate an existing receipt (against --archive) instead of writing one")
    args = parser.parse_args(argv)

    expected = {"arch": args.arch, "configuration": args.configuration, "variant": args.variant}
    if args.check:
        if not args.archive:
            parser.error("--check requires --archive")
        data = args.output.read_bytes()
        receipt = json.loads(data.decode("utf-8"))
        problems = validate_receipt(receipt, args.archive, **expected)
        match = CONTENT_ADDRESSED_RE.search(args.output.name)
        digest = hashlib.sha256(data).hexdigest()
        if not match:
            problems.append(f"{args.output.name} is not a content-addressed Linux receipt name")
        elif match.group(1) != digest:
            problems.append(f"{args.output.name} does not carry its own sha256")
        if args.archive and args.output.name != content_addressed_name(args.archive.name, data):
            problems.append(f"{args.output.name} is not the exact content-addressed name for {args.archive.name}")
        for problem in problems:
            print(f"linux-toolchain-receipt: {problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"linux-toolchain-receipt: {args.output} is proven")
        return 0

    receipt = build_receipt(args.arch, args.configuration, args.variant, args.toolchain_ninja,
                            args.archive, container_image=args.container_image,
                            link_probe_enabled=args.link_probe)
    data = apple.canonical_bytes(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    problems = validate_receipt(receipt, args.archive, **expected)
    for problem in problems:
        print(f"linux-toolchain-receipt: {problem}", file=sys.stderr)
    if args.content_addressed_dir and not problems:
        args.content_addressed_dir.mkdir(parents=True, exist_ok=True)
        target = args.content_addressed_dir / content_addressed_name(
            args.archive.name if args.archive else "toolchain", data)
        target.write_bytes(data)
        print(f"linux-toolchain-receipt: content-addressed copy {target}")
    print(json.dumps({key: receipt[key] for key in ("compiler", "libc", "cpp_abi")}, indent=1)[:4000])
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
