#!/usr/bin/env python3

import tempfile
from pathlib import Path

import apply_dawn_windows_arm64_vector_stl


def test_patch_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        build_gn = Path(tmp) / "third_party" / "dawn" / "BUILD.gn"
        cmake_utils = Path(tmp) / "third_party" / "dawn" / "cmake_utils.py"
        build_gn.parent.mkdir(parents=True)
        build_gn.write_text('''  if (is_clang) {
    args += [ "--is_clang" ]
  }
  if (is_debug) {
''', encoding="utf-8")
        cmake_utils.write_text('''    target_cpu_map = {
      "arm64": "ARM64",
      "x64": "AMD64",
    }
    combine_obj_cmd = [
        linker_exe, "/LIB", f"/OUT:{lib_name}", f"@{response_file_name}"
    ]
  else:
''', encoding="utf-8")

        assert apply_dawn_windows_arm64_vector_stl.apply_patch(Path(tmp))
        first = build_gn.read_text(encoding="utf-8")
        assert "target_cpu == \"arm64\"" in first
        assert "_USE_STD_VECTOR_ALGORITHMS=0" in first
        patched_cmake = cmake_utils.read_text(encoding="utf-8")
        assert '"arm64ec": "ARM64"' in patched_cmake
        assert "combine_obj_cmd.extend(args.ld_flags)" in patched_cmake
        assert not apply_dawn_windows_arm64_vector_stl.apply_patch(Path(tmp))
        assert build_gn.read_text(encoding="utf-8") == first


def test_patch_routes_arm64ec_flags() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dawn = root / "third_party" / "dawn"
        dawn.mkdir(parents=True)
        (dawn / "BUILD.gn").write_text('''  if (is_clang) {
    args += [ "--is_clang" ]
  }
  if (is_debug) {
''', encoding="utf-8")
        (dawn / "cmake_utils.py").write_text('''    target_cpu_map = {
      "arm64": "ARM64",
      "x64": "AMD64",
    }
    combine_obj_cmd = [
        linker_exe, "/LIB", f"/OUT:{lib_name}", f"@{response_file_name}"
    ]
  else:
''', encoding="utf-8")
        assert apply_dawn_windows_arm64_vector_stl.apply_patch(root)
        patched = (dawn / "BUILD.gn").read_text(encoding="utf-8")
        assert "defined(skia_win_arm64ec)" in patched
        assert '"--cxx_flags=/arm64EC"' in patched
        assert '"--ld_flags=/machine:ARM64EC"' in patched
        patched_cmake = (dawn / "cmake_utils.py").read_text(encoding="utf-8")
        assert "if args.ld_flags:" in patched_cmake
        assert "combine_obj_cmd.extend(args.ld_flags)" in patched_cmake
        assert '"arm64": "ARM64"' in patched_cmake
        assert '"x64": "AMD64"' in patched_cmake


if __name__ == "__main__":
    test_patch_is_idempotent()
    test_patch_routes_arm64ec_flags()
    print("apply_dawn_windows_arm64_vector_stl tests passed")
