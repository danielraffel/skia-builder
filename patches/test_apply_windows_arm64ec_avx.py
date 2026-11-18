#!/usr/bin/env python3

import tempfile
import os
import shutil
import subprocess
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
LIBWEBP_CPU = """#if defined(_MSC_VER) && _MSC_VER > 1310 && \\
    (defined(_M_X64) || defined(_M_IX86))
#define WEBP_MSC_SSE2
#endif
#if defined(_MSC_VER) && _MSC_VER >= 1500 && \\
    (defined(_M_X64) || defined(_M_IX86))
#define WEBP_MSC_SSE41
#endif
"""


def test_patch_is_idempotent_and_fail_closed_for_arm64ec() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "include" / "private").mkdir(parents=True)
        (root / "include" / "private" / "SkFeatures.h").write_text(FEATURES)
        (root / "BUILD.gn").write_text(BUILD)
        (root / "src" / "opts").mkdir(parents=True)
        (root / "src" / "opts" / "SkRasterPipeline_opts.h").write_text(RASTER)
        (root / "third_party" / "externals" / "libwebp" / "src" / "dsp").mkdir(parents=True)
        (root / "third_party" / "externals" / "libwebp" / "src" / "dsp" / "cpu.h").write_text(LIBWEBP_CPU)

        assert apply_windows_arm64ec_avx.apply_patch(root)
        features = (root / "include" / "private" / "SkFeatures.h").read_text()
        build = (root / "BUILD.gn").read_text()
        assert "!defined(_M_ARM64EC)" in features
        assert "defined(skia_win_arm64ec)" in build
        assert "_MSC_VER) && !defined(_M_ARM64EC)" in (root / "src" / "opts" / "SkRasterPipeline_opts.h").read_text()
        cpu = (root / "third_party" / "externals" / "libwebp" / "src" / "dsp" / "cpu.h").read_text()
        assert cpu.count("!defined(_M_ARM64EC)") == 2
        assert "defined(_M_X64)" in cpu
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
        (root / "third_party" / "externals" / "libwebp" / "src" / "dsp").mkdir(parents=True)
        (root / "third_party" / "externals" / "libwebp" / "src" / "dsp" / "cpu.h").write_text(LIBWEBP_CPU)
        apply_windows_arm64ec_avx.apply_patch(root)
        assert "defined(_M_X64)" in (root / "include" / "private" / "SkFeatures.h").read_text()
        assert 'current_cpu == "x64"' in (root / "BUILD.gn").read_text()
        cpu = (root / "third_party" / "externals" / "libwebp" / "src" / "dsp" / "cpu.h").read_text()
        assert "defined(_M_X64)" in cpu


def test_x86_detection_with_real_preprocessor() -> None:
    compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("gcc")
    assert compiler, "A C preprocessor is required for architecture regression tests"
    cases = [
        ("msvc-ec", ["_M_ARM64EC", "_M_X64"], False),
        ("clang-ec", ["_M_ARM64EC", "_M_X64", "__x86_64__", "__x86_64"], False),
        ("msvc-arm64", ["_M_ARM64"], False),
        ("clang-arm64", ["_M_ARM64", "__aarch64__"], False),
        ("msvc-x64", ["_M_X64"], True),
        ("clang-x64", ["_M_X64", "__x86_64__"], True),
        ("gcc-x64", ["__x86_64__"], True),
        ("msvc-x86", ["_M_IX86"], True),
        ("gcc-x86", ["__i386"], True),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "features.h"
        for original in (FEATURES, FEATURES.replace(
                "defined(_M_X64)\n", "defined(_M_X64) && !defined(_M_ARM64EC)\n")):
            path.write_text(original)
            assert apply_windows_arm64ec_avx._patch_features(path)
            assert not apply_windows_arm64ec_avx._patch_features(path)
            source = path.read_text() + "\n#ifdef SK_CPU_X86\nX86_SELECTED\n#endif\n"
            for name, macros, expected in cases:
                result = subprocess.run(
                    [compiler, "-E", "-P", "-undef", "-x", "c", "-"] +
                    ["-D" + macro + "=1" for macro in macros], input=source,
                    text=True, capture_output=True, check=True)
                assert ("X86_SELECTED" in result.stdout) == expected, (name, result.stdout)


if __name__ == "__main__":
    test_patch_is_idempotent_and_fail_closed_for_arm64ec()
    test_patch_does_not_remove_x64_detection()
    test_x86_detection_with_real_preprocessor()
    print("apply_windows_arm64ec_avx tests passed")
