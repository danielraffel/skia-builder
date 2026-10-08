#!/usr/bin/env python3
"""Write the Windows ABI/toolchain receipt shipped in a Skia archive.

Static MSVC archives do not carry the producer's STL/CRT toolset version in a
portable, machine-readable form.  A newer MSVC STL can emit ``__std_*`` helper
references that an older consumer runtime does not provide, so every Windows
archive must publish the exact producer toolset and runtime model alongside
the libraries.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path


def _run(*args: str) -> str:
    try:
        result = subprocess.run(args, check=False, capture_output=True, text=True)
    except OSError:
        return ""
    return (result.stdout + result.stderr).strip()


def _compiler_version(path: str) -> str:
    output = _run(path)
    for line in output.splitlines():
        if re.search(r"version\s+\d+\.\d+", line, re.IGNORECASE):
            return line.strip()
    return output.splitlines()[0].strip() if output else "unknown"


def _toolset_from_path(path: str) -> str:
    # .../VC/Tools/MSVC/<version>/bin/Hostx64/arm64/cl.exe
    parts = Path(path).resolve().parts
    for i, part in enumerate(parts):
        if part.lower() == "msvc" and i + 1 < len(parts):
            return parts[i + 1]
    return os.environ.get("VCToolsVersion", "unknown")


def _sdk_version() -> str:
    value = os.environ.get("WindowsSDKVersion") or os.environ.get("WINDOWSSDKVERSION")
    if value:
        return value.rstrip("\\/")
    root = os.environ.get("WindowsSdkDir") or os.environ.get("WINDOWSSDKDIR")
    if root:
        include = Path(root) / "Include"
        versions = sorted((p.name for p in include.iterdir() if p.is_dir()), reverse=True) if include.is_dir() else []
        if versions:
            return versions[0]
    return "unknown"


def build_receipt(arch: str, configuration: str, variant: str) -> dict:
    cl = shutil.which("cl.exe") or shutil.which("cl") or "cl.exe"
    clang = shutil.which("clang-cl.exe") or shutil.which("clang-cl") or "clang-cl.exe"
    toolset = os.environ.get("VCToolsVersion") or _toolset_from_path(cl)
    sdk = _sdk_version()
    return {
        "schema_version": 1,
        "target": {"platform": "windows", "architecture": arch, "configuration": configuration, "variant": variant},
        "producer": {
            "skia_gn_compiler": {"driver": "cl.exe", "path": cl, "version": _compiler_version(cl)},
            "dawn_cmake_compiler": {"driver": "clang-cl.exe", "path": clang, "version": _compiler_version(clang)},
            "msvc_toolset_version": toolset,
            "windows_sdk_version": sdk,
            "host_architecture": platform.machine(),
        },
        "runtime": {
            "abi": "msvc",
            "library": "static",
            "compile_flag": "/MT" if configuration.lower() == "release" else "/MTd",
            "consumer_requirement": f"MSVC STL/CRT toolset >= {toolset}; older toolsets are not proven compatible",
        },
        "notes": [
            "Static archives intentionally retain unresolved MSVC STL __std_* references.",
            "The consumer linker supplies those references from its matching MSVC runtime library.",
            "Do not mix this archive with a consumer using libc++, MinGW, /NODEFAULTLIB, or an older unvalidated MSVC toolset.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--configuration", default="Release")
    parser.add_argument("--variant", default="gpu")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_receipt(args.arch, args.configuration, args.variant), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
