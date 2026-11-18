#!/usr/bin/env python3
"""Guard source drift, repeatability, and non-publication of an unpatched Dawn."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from apply_dawn_macos_msl_version import ANCHOR, BLOCK, RELATIVE, apply

ROOT = Path(__file__).resolve().parents[1]

class MetalLanguageTests(unittest.TestCase):
    def test_apply_preserves_surrounding_source_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Path(tmp)
            p = r / RELATIVE
            p.parent.mkdir(parents=True)
            p.write_text("before\n" + ANCHOR + "after\n")
            apply(r)
            expected = "before\n" + ANCHOR + BLOCK + "after\n"
            self.assertEqual(p.read_text(), expected)
            apply(r)
            self.assertEqual(p.read_text(), expected)

    def test_source_drift_refuses_without_writing(self):
        for source in ("unknown Dawn", ANCHOR * 2,
                       ANCHOR + "// Select by runtime OS instead (incomplete)\n"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                r = Path(tmp)
                p = r / RELATIVE
                p.parent.mkdir(parents=True)
                p.write_text(source)
                with self.assertRaises(ValueError):
                    apply(r)
                self.assertEqual(p.read_text(), source)

    def test_builder_stops_when_required_patch_fails(self):
        spec = importlib.util.spec_from_file_location("build_skia", ROOT / "build-skia.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        script = module.SkiaBuildScript.__new__(module.SkiaBuildScript)
        script.platform = "mac"
        target = "apply_dawn_macos_msl_version.py"
        def run(args, **kwargs):
            if any(str(x).endswith(target) for x in args):
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0)
        previous = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(module, "SKIA_SRC_DIR", Path(tmp)), patch.object(module.subprocess, "run", side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    script.apply_patches()
        finally:
            os.chdir(previous)

if __name__ == "__main__":
    unittest.main()
