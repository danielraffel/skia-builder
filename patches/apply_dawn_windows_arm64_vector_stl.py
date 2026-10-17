#!/usr/bin/env python3
"""Route Windows ARM64 and ARM64EC flags into Dawn's CMake sub-build."""

import sys
from pathlib import Path


EC_MARKER = '"--cxx_flags=/arm64EC"'
ARCHIVE_FLAG_MARKER = "      combine_obj_cmd.extend(args.ld_flags)"


def _patch_cmake_cpu_map(cmake_utils: Path) -> bool:
    """Teach Dawn's helper to accept the explicit ARM64EC architecture name."""
    content = cmake_utils.read_text(encoding="utf-8")
    if '"arm64ec": "ARM64"' in content:
        return False
    needle = '      "arm64": "ARM64",\n      "x64": "AMD64",'
    replacement = '      "arm64": "ARM64",\n      "arm64ec": "ARM64",\n      "x64": "AMD64",'
    if needle not in content:
        raise RuntimeError("Dawn CMake Windows architecture map anchor not found")
    cmake_utils.write_text(content.replace(needle, replacement, 1), encoding="utf-8")
    return True


def _patch_cmake_archive_flags(cmake_utils: Path) -> bool:
    """Pass Dawn's linker machine flags to the MSVC archive command too."""
    content = cmake_utils.read_text(encoding="utf-8")
    if ARCHIVE_FLAG_MARKER in content:
        return False
    needle = "    combine_obj_cmd = [\n        linker_exe, \"/LIB\", f\"/OUT:{lib_name}\", f\"@{response_file_name}\"\n    ]\n  else:"
    replacement = "    combine_obj_cmd = [\n        linker_exe, \"/LIB\", f\"/OUT:{lib_name}\", f\"@{response_file_name}\"\n    ]\n    if args.ld_flags:\n      # lib.exe does not inherit CMake's linker machine mode. Keep the\n      # combined archive in the same architecture as its object files.\n      combine_obj_cmd.extend(args.ld_flags)\n  else:"
    if needle not in content:
        raise RuntimeError("Dawn CMake archive command anchor not found")
    cmake_utils.write_text(content.replace(needle, replacement, 1), encoding="utf-8")
    return True


def _patch_skia_args(skia_gni: Path) -> bool:
    """Declare the custom GN switch in the scope Dawn's BUILD.gn imports."""
    content = skia_gni.read_text(encoding="utf-8")
    marker = "  skia_win_arm64ec = false\n"
    if marker in content:
        return False
    needle = "declare_args() {\n  skia_android_serial = \"\"\n"
    if needle not in content:
        raise RuntimeError("Skia root args declare_args anchor not found")
    replacement = needle + "  # Select ARM64EC flags for Dawn's CMake sub-build.\n" + marker
    skia_gni.write_text(content.replace(needle, replacement, 1), encoding="utf-8")
    return True


def apply_patch(skia_dir: Path) -> bool:
    build_gn = skia_dir / "third_party" / "dawn" / "BUILD.gn"
    content = build_gn.read_text(encoding="utf-8")
    cmake_utils = skia_dir / "third_party" / "dawn" / "cmake_utils.py"
    skia_gni = skia_dir / "gn" / "skia.gni"
    changed = _patch_skia_args(skia_gni)
    changed = _patch_cmake_cpu_map(cmake_utils) or changed
    changed = _patch_cmake_archive_flags(cmake_utils) or changed
    if EC_MARKER in content:
        return changed

    needle = '''  if (is_clang) {
    args += [ "--is_clang" ]
  }
  if (is_debug) {'''
    replacement = '''  if (is_clang) {
    args += [ "--is_clang" ]
  }
  if (is_win && target_cpu == "arm64") {
    if (defined(skia_win_arm64ec) && skia_win_arm64ec) {
      # GN selects the ARM64 source/toolchain for both slices; these flags
      # make Dawn's separate CMake build emit ARM64EC objects and links.
      args += [
        "--cxx_flags=/arm64EC",
        "--ld_flags=/machine:ARM64EC",
      ]
    } else {
      # VS ARM64's vectorized STL entry points are not linkable from the
      # ARM64 runtime archive; keep these algorithms header-only.
      args += [ "--cxx_flags=/D_USE_STD_VECTOR_ALGORITHMS=0" ]
    }
  }
  if (is_debug) {'''
    old_replacement = '''  if (is_clang) {
    args += [ "--is_clang" ]
  }
  if (is_win && target_cpu == "arm64") {
    # VS ARM64's vectorized STL entry points are not linkable from the
    # ARM64 runtime archive; keep these algorithms header-only.
    args += [ "--cxx_flags=/D_USE_STD_VECTOR_ALGORITHMS=0" ]
  }
  if (is_debug) {'''
    if old_replacement in content:
        build_gn.write_text(content.replace(old_replacement, replacement, 1), encoding="utf-8")
        return True
    if needle not in content:
        raise RuntimeError("Dawn BUILD.gn CMake argument anchor not found")
    build_gn.write_text(content.replace(needle, replacement, 1), encoding="utf-8")
    return True


if __name__ == "__main__":
    changed = apply_patch(Path(sys.argv[1]))
    print("  Patched Dawn Windows ARM64/ARM64EC CMake flags" if changed
          else "  Dawn Windows ARM64/ARM64EC CMake flags already patched")
