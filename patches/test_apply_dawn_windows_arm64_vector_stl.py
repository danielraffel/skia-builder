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
''', encoding="utf-8")

        assert apply_dawn_windows_arm64_vector_stl.apply_patch(Path(tmp))
        first = build_gn.read_text(encoding="utf-8")
        assert "target_cpu == \"arm64\"" in first
        assert "_USE_STD_VECTOR_ALGORITHMS=0" in first
        assert '"arm64ec": "ARM64"' in cmake_utils.read_text(encoding="utf-8")
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
''', encoding="utf-8")
        assert apply_dawn_windows_arm64_vector_stl.apply_patch(root)
        patched = (dawn / "BUILD.gn").read_text(encoding="utf-8")
        assert "defined(skia_win_arm64ec)" in patched
        assert '"--cxx_flags=/arm64EC"' in patched
        assert '"--ld_flags=/machine:ARM64EC"' in patched


if __name__ == "__main__":
    test_patch_is_idempotent()
    test_patch_routes_arm64ec_flags()
    print("apply_dawn_windows_arm64_vector_stl tests passed")
