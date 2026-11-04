#!/usr/bin/env python3
"""Windows-only patch scripts must not change what other platforms build or package."""

import contextlib
import hashlib
import importlib.util
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_skia", ROOT / "build-skia.py")
build_skia = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_skia)

# include/private/SkFeatures.h exactly as packaged in chrome/m157's
# skia-build-mac-universal-gpu-release.zip (sha256 bb24c74f...), the archive
# Pulp pins.  A mac build must still package these bytes.
PUBLISHED_FEATURES = ROOT / "tools" / "testdata" / "chrome-m157-SkFeatures.h"
PUBLISHED_FEATURES_SHA256 = "d20d246f13400fe5a0e9f335611d825f936fa469e043e967849db673476196d1"


class PatchScriptPlatformTests(unittest.TestCase):
    def test_every_windows_script_is_gated_to_windows(self):
        scripts = {path.name for path in (ROOT / "patches").glob("apply_*.py")}
        windows = {name for name in scripts if "windows" in name}
        self.assertEqual(set(build_skia.PATCH_SCRIPT_PLATFORMS), windows)
        for name in windows:
            self.assertEqual(build_skia.PATCH_SCRIPT_PLATFORMS[name], {"win"}, name)

    def run_patches(self, platform: str) -> bytes:
        tmp = Path(tempfile.mkdtemp(prefix="skia-patches-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        features = tmp / "include" / "private" / "SkFeatures.h"
        features.parent.mkdir(parents=True)
        shutil.copy(PUBLISHED_FEATURES, features)
        script = build_skia.SkiaBuildScript.__new__(build_skia.SkiaBuildScript)
        script.platform = platform
        cwd = os.getcwd()
        original = build_skia.SKIA_SRC_DIR
        build_skia.SKIA_SRC_DIR = tmp
        try:
            # Scripts for other sources (Dawn) find nothing in this tree and
            # only warn; the build script tolerates that.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                script.apply_patches()
        finally:
            build_skia.SKIA_SRC_DIR = original
            os.chdir(cwd)
        return features.read_bytes()

    def test_fixture_is_the_published_header(self):
        self.assertEqual(hashlib.sha256(PUBLISHED_FEATURES.read_bytes()).hexdigest(),
                         PUBLISHED_FEATURES_SHA256)

    def test_mac_and_other_platforms_keep_the_published_header(self):
        for platform in ("mac", "ios", "visionos", "linux", "wasm"):
            self.assertEqual(hashlib.sha256(self.run_patches(platform)).hexdigest(),
                             PUBLISHED_FEATURES_SHA256, platform)

    def test_windows_still_gets_the_arm64ec_guard(self):
        # Control: the same tree, patched for Windows, does change.
        patched = self.run_patches("win").decode()
        self.assertIn("defined(_M_X64) && !defined(_M_ARM64EC)", patched)


if __name__ == "__main__":
    unittest.main()
