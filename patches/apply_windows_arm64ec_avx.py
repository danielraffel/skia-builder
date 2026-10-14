#!/usr/bin/env python3
"""Keep Skia's x86/AVX sources out of the Windows ARM64EC slice."""

import sys
from pathlib import Path


def _patch_features(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    old = "#if defined(__i386) || defined(_M_IX86) ||  defined(__x86_64__) || defined(_M_X64)"
    new = old + " && !defined(_M_ARM64EC)"
    if new in content:
        return False
    if old not in content:
        raise RuntimeError("SkFeatures x86 detection anchor not found")
    path.write_text(content.replace(old, new, 1), encoding="utf-8")
    return True


def _patch_build_gn(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    old = 'is_x86 = current_cpu == "x64" || current_cpu == "x86"'
    new = ('is_x86 = (current_cpu == "x64" || current_cpu == "x86") && '
           '(!defined(skia_win_arm64ec) || !skia_win_arm64ec)')
    if new in content:
        return False
    if old not in content:
        raise RuntimeError("Skia x86 opts anchor not found")
    path.write_text(content.replace(old, new, 1), encoding="utf-8")
    return True


def _patch_raster_pipeline(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    old = "#elif defined(_MSC_VER)\n    // Even if not vectorized, this lets us pass {r,g,b,a} as registers,"
    new = ("#elif defined(_MSC_VER) && !defined(_M_ARM64EC)\n"
           "    // ARM64EC does not implement MSVC's __vectorcall convention.\n"
           "    // Even if not vectorized, this lets us pass {r,g,b,a} as registers,")
    if new in content:
        return False
    if old not in content:
        raise RuntimeError("SkRasterPipeline ABI anchor not found")
    path.write_text(content.replace(old, new, 1), encoding="utf-8")
    return True


def _patch_libwebp_cpu(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    old = "(defined(_M_X64) || defined(_M_IX86))"
    new = "((defined(_M_X64) && !defined(_M_ARM64EC)) || defined(_M_IX86))"
    if new in content:
        return False
    if content.count(old) != 2:
        raise RuntimeError("libwebp CPU feature anchors not found twice")
    path.write_text(content.replace(old, new), encoding="utf-8")
    return True


def apply_patch(skia_dir: Path) -> bool:
    changed = _patch_features(skia_dir / "include" / "private" / "SkFeatures.h")
    changed = _patch_build_gn(skia_dir / "BUILD.gn") or changed
    changed = _patch_raster_pipeline(skia_dir / "src" / "opts" / "SkRasterPipeline_opts.h") or changed
    changed = _patch_libwebp_cpu(skia_dir / "third_party" / "externals" / "libwebp" / "src" / "dsp" / "cpu.h") or changed
    return changed


if __name__ == "__main__":
    changed = apply_patch(Path(sys.argv[1]))
    print("  Patched Skia Windows ARM64EC AVX source guards" if changed
          else "  Skia Windows ARM64EC AVX source guards already patched")
