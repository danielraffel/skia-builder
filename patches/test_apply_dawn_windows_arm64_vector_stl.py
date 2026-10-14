#!/usr/bin/env python3

import tempfile
from pathlib import Path

import apply_dawn_windows_arm64_vector_stl


def test_patch_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        build_gn = Path(tmp) / "third_party" / "dawn" / "BUILD.gn"
        build_gn.parent.mkdir(parents=True)
        build_gn.write_text('''  if (is_clang) {
    args += [ "--is_clang" ]
  }
  if (is_debug) {
''', encoding="utf-8")

        assert apply_dawn_windows_arm64_vector_stl.apply_patch(Path(tmp))
        first = build_gn.read_text(encoding="utf-8")
        assert "target_cpu == \"arm64\"" in first
        assert "_USE_STD_VECTOR_ALGORITHMS=0" in first
        assert not apply_dawn_windows_arm64_vector_stl.apply_patch(Path(tmp))
        assert build_gn.read_text(encoding="utf-8") == first


if __name__ == "__main__":
    test_patch_is_idempotent()
