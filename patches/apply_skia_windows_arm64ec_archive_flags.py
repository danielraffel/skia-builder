#!/usr/bin/env python3
"""Wire the ARM64EC archive machine flag into Skia's default config."""

import sys
from pathlib import Path


def apply_patch(skia_dir: Path) -> bool:
    path = skia_dir / "gn" / "skia" / "BUILD.gn"
    content = path.read_text(encoding="utf-8")
    changed = False
    if "extra_arflags = []" not in content:
        needle = "  extra_ldflags = []\n"
        if needle not in content:
            raise RuntimeError("Skia extra_ldflags declaration anchor not found")
        content = content.replace(needle, needle + "  extra_arflags = []\n", 1)
        changed = True
    if "arflags = extra_arflags" not in content:
        needle = "    ldflags = extra_ldflags\n"
        if needle not in content:
            raise RuntimeError("Skia extra_flags ldflags anchor not found")
        content = content.replace(needle, needle + "    arflags = extra_arflags\n", 1)
        changed = True
    if changed:
        path.write_text(content, encoding="utf-8")
    return changed


if __name__ == "__main__":
    root = Path(sys.argv[1])
    apply_patch(root)
