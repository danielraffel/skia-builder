#!/usr/bin/env python3

import tempfile
from pathlib import Path

import apply_skia_windows_arm64ec_archive_flags


def test_patch_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gn" / "skia" / "BUILD.gn"
        path.parent.mkdir(parents=True)
        path.write_text(
            "declare_args() {\n  extra_ldflags = []\n}\n"
            "config(\"extra_flags\") {\n    ldflags = extra_ldflags\n}\n",
            encoding="utf-8",
        )
        assert apply_skia_windows_arm64ec_archive_flags.apply_patch(Path(tmp))
        output = path.read_text(encoding="utf-8")
        assert "extra_arflags = []" in output
        assert "arflags = extra_arflags" in output
        assert not apply_skia_windows_arm64ec_archive_flags.apply_patch(Path(tmp))


if __name__ == "__main__":
    test_patch_is_idempotent()
