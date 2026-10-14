#!/usr/bin/env python3
"""Write, and check, the Windows ABI/toolchain receipt shipped in a Skia archive.

Static MSVC archives do not carry the producer's STL/CRT toolset version in a
portable, machine-readable form.  A newer MSVC STL can emit ``__std_*`` helper
references that an older consumer runtime does not provide, so every Windows
archive must publish the exact producer toolset and runtime model alongside
the libraries.

The workflow step that writes the receipt runs outside a Visual Studio
developer shell, so ``cl.exe`` is not on PATH and ``VCToolsVersion`` /
``WindowsSDKVersion`` are unset.  Skia's GN build finds MSVC by itself, so the
receipt resolves the toolchain the same way GN does (``gn/find_msvc.py`` and
``gn/highest_version_dir.py`` in Skia, ``gn/toolchain/BUILD.gn`` for the
``cl.exe`` path), and, once the build has run, cross-checks that against the
``cl.exe`` GN actually wrote into ``toolchain.ninja``.

A receipt that records ``unknown`` or a compiler error instead of a version is
worse than none: it looks like provenance and proves nothing.  ``validate``
rejects such a receipt, the writer exits non-zero rather than ship one, and the
publish step re-checks the receipt inside each archive.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

TOOLSET_RE = re.compile(r"^[0-9]{2}\.[0-9]{2}\.[0-9]{5}$")
SDK_RE = re.compile(r"^[0-9]{2}\.[0-9]\.[0-9]{5}\.[0-9]$")
CL_BANNER_RE = re.compile(r"C/C\+\+ Optimizing Compiler Version [0-9]+\.[0-9]+\.[0-9]+")
CL_PATH_RE = re.compile(
    r"([A-Za-z]:[^\"\n]*?[\\/]Tools[\\/]MSVC[\\/]([0-9]{2}\.[0-9]{2}\.[0-9]{5})"
    r"[\\/]bin[\\/]Host[A-Za-z0-9]+[\\/][A-Za-z0-9]+[\\/]cl\.exe)", re.IGNORECASE)
BAD_VALUE_RE = re.compile(r"unknown|error|no input files|not recognized|not found|cannot find",
                          re.IGNORECASE)
GN_TARGET_CPU = {"arm64": "arm64", "arm64ec": "arm64", "x64": "x64", "x86_64": "x64", "win32": "x86", "x86": "x86"}
DEFAULT_WIN_SDK = r"C:\Program Files (x86)\Windows Kits\10"

Runner = Callable[[list[str]], str]


def unescape_ninja_value(value: str) -> str:
    """Decode Ninja's literal drive-colon/space escapes only."""
    return re.sub(r"\$([$: ])", r"\1", value)


def _run(args: list[str]) -> str:
    try:
        result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"error: {exc}"
    return (result.stdout + result.stderr).strip()


def highest_version_dir(directory: Path, pattern: str) -> str | None:
    """Same selection as Skia's gn/highest_version_dir.py: lexical max of matches."""
    if not directory.is_dir():
        return None
    regex = re.compile(pattern)
    matches = sorted(name for name in os.listdir(directory) if regex.match(name))
    return matches[-1] if matches else None


def find_msvc(program_dirs: list[Path] | None = None, run: Runner = _run) -> Path | None:
    """Mirror Skia's gn/find_msvc.py, including its vswhere fallback.

    GitHub's windows-11-arm image ships Visual Studio 18 (2026), which the
    fixed-path probe does not know, so the vswhere fallback is the path GN takes
    there.
    """
    if program_dirs is None:
        program_dirs = [Path(r"C:\Program Files\Microsoft Visual Studio"),
                        Path(r"C:\Program Files (x86)\Microsoft Visual Studio")]
    for base in program_dirs:
        for release in ("2022", "2019", "2017"):
            for edition in ("Enterprise", "Professional", "Community", "BuildTools", "Preview"):
                candidate = base / release / edition / "VC"
                if candidate.is_dir():
                    return candidate
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    output = run([str(vswhere), "-prerelease", "-legacy", "-products", "*", "-sort", "-utf8",
                  "-property", "installationPath"])
    for line in output.splitlines():
        line = line.strip()
        if line and not BAD_VALUE_RE.search(line):
            return Path(line) / "VC"
    return None


def cl_from_toolchain_ninja(path: Path) -> tuple[str, str] | None:
    """Return (cl.exe path, toolset) that GN wrote into toolchain.ninja."""
    if not path.is_file():
        return None
    # GN/Ninja serializes Windows drive colons and spaces as `$:` and `$ `.
    # Decode the command text before matching and handing the path to cl.exe.
    content = unescape_ninja_value(path.read_text(encoding="utf-8", errors="replace"))
    match = CL_PATH_RE.search(content)
    if not match:
        return None
    return (match.group(1), match.group(2))


def _first_matching_line(output: str, regex: re.Pattern) -> str:
    for line in output.splitlines():
        if regex.search(line):
            return line.strip()
    # Keep the raw output so a failure says what the tool printed instead.
    return output.splitlines()[0].strip() if output.strip() else "unknown"


def find_msvc_cl(vc_dir: Path | None, toolset: str | None, arch: str) -> Path | None:
    """Find the MSVC compiler GN can use for a Windows target.

    ARM64 GitHub images do not all expose the same host-tool directory.  The
    ARM64EC compiler is accepted by the ARM64 cl.exe when passed `/arm64EC`,
    so probe the explicit EC directory first and then the ordinary ARM64
    compiler as a compatibility fallback.  Never invent a path: callers must
    validate the resulting banner.
    """
    if not vc_dir or not toolset:
        return None
    target = GN_TARGET_CPU.get(arch.lower(), arch.lower())
    target_dirs = ["arm64ec", target] if arch.lower() == "arm64ec" else [target]
    for host in ("HostX64", "HostARM64"):
        for target_dir in target_dirs:
            candidate = vc_dir / "Tools" / "MSVC" / toolset / "bin" / host / target_dir / "cl.exe"
            if candidate.is_file():
                return candidate
    return None


def build_receipt(arch: str, configuration: str, variant: str, *,
                  vc_dir: Path | None = None, win_sdk: Path | None = None,
                  toolchain_ninja: Path | None = None, run: Runner = _run) -> dict:
    target_cpu = GN_TARGET_CPU.get(arch.lower(), arch.lower())
    vc_dir = vc_dir or find_msvc(run=run)
    toolset = os.environ.get("VCToolsVersion", "").strip("\\/ ") or (
        highest_version_dir(vc_dir / "Tools" / "MSVC", TOOLSET_RE.pattern.strip("^$"))
        if vc_dir else None)
    sdk_root = win_sdk or Path(os.environ.get("WindowsSdkDir", "").rstrip("\\/") or DEFAULT_WIN_SDK)
    sdk = os.environ.get("WindowsSDKVersion", "").strip("\\/ ") or highest_version_dir(
        sdk_root / "Include", SDK_RE.pattern.strip("^$"))
    # gn/toolchain/BUILD.gn normally uses HostX64; ARM images may expose only
    # HostARM64, and ARM64EC may share the ARM64 compiler with /arm64EC.
    cl_path = find_msvc_cl(vc_dir, toolset, arch)
    cl = str(cl_path) if cl_path else "unknown"
    built = cl_from_toolchain_ninja(toolchain_ninja) if toolchain_ninja else None
    if built:
        cl, toolset = built
    cl_version = (_first_matching_line(run([cl]), CL_BANNER_RE)
                  if cl != "unknown" else "unknown")
    return {
        "schema_version": 1,
        "target": {"platform": "windows", "architecture": arch, "configuration": configuration,
                   "variant": variant},
        "producer": {
            "skia_gn_compiler": {
                "driver": "cl.exe", "path": cl,
                # cl.exe prints its banner to stderr when run without arguments.
                "version": cl_version,
                "source": "toolchain.ninja" if built else "gn find_msvc resolution",
            },
            "dawn_cmake_compiler": {
                # build-skia.py deliberately sets CC/CXX=cl.exe and
                # is_clang=false. Dawn's separate CMake sub-build therefore
                # uses the same MSVC compiler and CRT as Skia.
                "driver": "cl.exe", "path": cl,
                "version": cl_version,
                "source": "build-skia.py MSVC ABI",
            },
            "msvc_toolset_version": toolset or "unknown",
            "windows_sdk_version": sdk or "unknown",
            "visual_studio_vc_dir": str(vc_dir) if vc_dir else "unknown",
            "host_architecture": platform.machine(),
        },
        "runtime": {
            "abi": "msvc",
            "library": "static",
            "compile_flag": "/MT" if configuration.lower() == "release" else "/MTd",
            "consumer_requirement": f"MSVC STL/CRT toolset >= {toolset or 'unknown'}; "
                                    "older toolsets are not proven compatible",
        },
        "notes": [
            "Static archives intentionally retain unresolved MSVC STL __std_* references.",
            "The consumer linker supplies those references from its matching MSVC runtime library.",
            "Do not mix this archive with a consumer using libc++, MinGW, /NODEFAULTLIB, or an older unvalidated MSVC toolset.",
        ],
    }


def validate_receipt(receipt: dict, expect_arch: str | None = None,
                     expect_config: str | None = None) -> list[str]:
    """Return every reason this receipt does not prove what it claims."""
    problems = []
    producer = receipt.get("producer") or {}
    target = receipt.get("target") or {}

    def walk(value, where):
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{where}.{key}" if where else key)
        elif isinstance(value, list):
            return
        elif isinstance(value, str):
            if not value.strip() or BAD_VALUE_RE.search(value):
                problems.append(f"{where} = {value!r}")
        elif value is None:
            problems.append(f"{where} is null")

    walk({"target": target, "producer": producer, "runtime": receipt.get("runtime") or {}}, "")
    if receipt.get("schema_version") != 1:
        problems.append(f"schema_version = {receipt.get('schema_version')!r}")
    if not TOOLSET_RE.match(str(producer.get("msvc_toolset_version", ""))):
        problems.append(f"msvc_toolset_version {producer.get('msvc_toolset_version')!r} "
                        "is not an MSVC toolset version (NN.NN.NNNNN)")
    if not SDK_RE.match(str(producer.get("windows_sdk_version", ""))):
        problems.append(f"windows_sdk_version {producer.get('windows_sdk_version')!r} "
                        "is not a Windows SDK version (10.0.NNNNN.N)")
    cl = producer.get("skia_gn_compiler") or {}
    if not CL_BANNER_RE.search(str(cl.get("version", ""))):
        problems.append(f"skia_gn_compiler.version {cl.get('version')!r} is not a cl.exe banner")
    toolset = str(producer.get("msvc_toolset_version", ""))
    if toolset and toolset not in str(cl.get("path", "")):
        problems.append(f"skia_gn_compiler.path {cl.get('path')!r} is not from toolset {toolset}")
    dawn = producer.get("dawn_cmake_compiler") or {}
    if not CL_BANNER_RE.search(str(dawn.get("version", ""))):
        problems.append(f"dawn_cmake_compiler.version {dawn.get('version')!r} "
                        "is not a cl.exe banner")
    if toolset and toolset not in str(dawn.get("path", "")):
        problems.append(f"dawn_cmake_compiler.path {dawn.get('path')!r} "
                        f"is not from toolset {toolset}")
    if expect_arch and str(target.get("architecture", "")).lower() != expect_arch.lower():
        problems.append(f"target.architecture {target.get('architecture')!r} != {expect_arch!r}")
    if expect_config and str(target.get("configuration", "")).lower() != expect_config.lower():
        problems.append(f"target.configuration {target.get('configuration')!r} != {expect_config!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--configuration", default="Release")
    parser.add_argument("--variant", default="gpu")
    parser.add_argument("--toolchain-ninja", type=Path,
                        help="GN's toolchain.ninja; the cl.exe it names is authoritative")
    parser.add_argument("--check", action="store_true",
                        help="validate an existing receipt instead of writing one")
    args = parser.parse_args(argv)
    if args.check:
        receipt = json.loads(args.output.read_text(encoding="utf-8"))
    else:
        receipt = build_receipt(args.arch, args.configuration, args.variant,
                                toolchain_ninja=args.toolchain_ninja)
        if args.toolchain_ninja and receipt["producer"]["skia_gn_compiler"]["source"] \
                != "toolchain.ninja":
            print(f"error: no cl.exe path found in {args.toolchain_ninja}", file=sys.stderr)
            return 1
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2))
    problems = validate_receipt(receipt, args.arch, args.configuration)
    if problems:
        print(f"error: {args.output} is not a valid toolchain receipt:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
