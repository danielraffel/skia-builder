#!/usr/bin/env python3

import tempfile
from pathlib import Path

import apply_windows_arm64ec_avx


FEATURES = """#if defined(__i386) || defined(_M_IX86) ||  defined(__x86_64__) || defined(_M_X64)
  #define SK_CPU_X86 1
#endif
"""
BUILD = 'is_x86 = current_cpu == "x64" || current_cpu == "x86"\n'
RASTER = """#elif defined(_MSC_VER)
    // Even if not vectorized, this lets us pass {r,g,b,a} as registers,
    #define ABI __vectorcall
"""


def test_patch_is_idempotent_and_fail_closed_for_arm64ec() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "include" / "private").mkdir(parents=True)
        (root / "include" / "private" / "SkFeatures.h").write_text(FEATURES)
        (root / "BUILD.gn").write_text(BUILD)
        (root / "src" / "opts").mkdir(parents=True)
        (root / "src" / "opts" / "SkRasterPipeline_opts.h").write_text(RASTER)

        assert apply_windows_arm64ec_avx.apply_patch(root)
        features = (root / "include" / "private" / "SkFeatures.h").read_text()
        build = (root / "BUILD.gn").read_text()
        assert "!defined(_M_ARM64EC)" in features
        assert "defined(skia_win_arm64ec)" in build
        assert "_MSC_VER) && !defined(_M_ARM64EC)" in (root / "src" / "opts" / "SkRasterPipeline_opts.h").read_text()
        assert not apply_windows_arm64ec_avx.apply_patch(root)
        assert (root / "include" / "private" / "SkFeatures.h").read_text() == features
        assert (root / "BUILD.gn").read_text() == build


def test_patch_does_not_remove_x64_detection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "include" / "private").mkdir(parents=True)
        (root / "include" / "private" / "SkFeatures.h").write_text(FEATURES)
        (root / "BUILD.gn").write_text(BUILD)
        (root / "src" / "opts").mkdir(parents=True)
        (root / "src" / "opts" / "SkRasterPipeline_opts.h").write_text(RASTER)
        apply_windows_arm64ec_avx.apply_patch(root)
        assert "defined(_M_X64)" in (root / "include" / "private" / "SkFeatures.h").read_text()
        assert 'current_cpu == "x64"' in (root / "BUILD.gn").read_text()


if __name__ == "__main__":
    test_patch_is_idempotent_and_fail_closed_for_arm64ec()
    test_patch_does_not_remove_x64_detection()
    print("apply_windows_arm64ec_avx tests passed")
