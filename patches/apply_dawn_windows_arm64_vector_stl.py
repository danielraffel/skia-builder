#!/usr/bin/env python3
"""Disable MSVC vectorized STL calls for the Windows ARM64 Dawn sub-build."""

import sys
from pathlib import Path


MARKER = '"--cxx_flags=/D_USE_STD_VECTOR_ALGORITHMS=0"'


def apply_patch(skia_dir: Path) -> bool:
    build_gn = skia_dir / "third_party" / "dawn" / "BUILD.gn"
    content = build_gn.read_text(encoding="utf-8")
    if MARKER in content:
        return False

    needle = '''  if (is_clang) {
    args += [ "--is_clang" ]
  }
  if (is_debug) {'''
    replacement = '''  if (is_clang) {
    args += [ "--is_clang" ]
  }
  if (is_win && target_cpu == "arm64") {
    # VS ARM64's vectorized STL entry points are not linkable from the
    # ARM64 runtime archive; keep these algorithms header-only.
    args += [ "--cxx_flags=/D_USE_STD_VECTOR_ALGORITHMS=0" ]
  }
  if (is_debug) {'''
    if needle not in content:
        raise RuntimeError("Dawn BUILD.gn CMake argument anchor not found")
    build_gn.write_text(content.replace(needle, replacement, 1), encoding="utf-8")
    return True


if __name__ == "__main__":
    changed = apply_patch(Path(sys.argv[1]))
    print("  Patched Dawn Windows ARM64 vectorized STL guard" if changed else "  Dawn Windows ARM64 vectorized STL guard already patched")
