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


def apply_patch(skia_dir: Path) -> bool:
    changed = _patch_features(skia_dir / "include" / "private" / "SkFeatures.h")
    changed = _patch_build_gn(skia_dir / "BUILD.gn") or changed
    return changed


if __name__ == "__main__":
    changed = apply_patch(Path(sys.argv[1]))
    print("  Patched Skia Windows ARM64EC AVX source guards" if changed
          else "  Skia Windows ARM64EC AVX source guards already patched")
