#!/usr/bin/env python3
"""Verify experimental producer selection and packaged candidate provenance."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import os
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('build_skia', Path(__file__).parents[1] / 'build-skia.py')
build_skia = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_skia)


class IntegrationTests(unittest.TestCase):
    def test_explicit_architecture_and_platform_required(self):
        for args in (['win'], ['win', '-archs', 'x64'], ['mac', '-archs', 'arm64']):
            with self.subTest(args=args), patch('sys.argv', ['build-skia.py', *args,
                     '--windows-vector-raster']), self.assertRaises(SystemExit):
                build_skia.SkiaBuildScript().parse_arguments()
        with patch('sys.argv', ['build-skia.py', 'win', '-archs', 'arm64,arm64ec',
                               '--windows-vector-raster']):
            script = build_skia.SkiaBuildScript()
            script.parse_arguments()
            self.assertTrue(script.windows_vector_raster)

    def test_default_keeps_msvc_archive(self):
        script = build_skia.SkiaBuildScript()
        script.platform, script.config = 'win', 'Release'
        with patch.object(build_skia.subprocess, 'run') as run:
            script.build_skia('arm64ec')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(script.vector_raster_outputs, {})

    def test_vector_mode_refuses_patch_script_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'patches').mkdir()
            (root / 'patches/apply_failure.py').write_text('raise RuntimeError()')
            script = build_skia.SkiaBuildScript()
            script.platform, script.windows_vector_raster = 'win', True
            with patch.object(build_skia, '__file__', str(root / 'build-skia.py')), \
                 patch.object(build_skia.os, 'chdir'), \
                 patch.object(build_skia.subprocess, 'run',
                              side_effect=subprocess.CalledProcessError(1, 'patch')), \
                 self.assertRaises(subprocess.CalledProcessError):
                script.apply_patches()

    def test_ninja_honors_the_governed_nested_build_share(self):
        script = build_skia.SkiaBuildScript()
        script.platform, script.config = 'win', 'Release'
        with patch.dict(os.environ, {'CMAKE_BUILD_PARALLEL_LEVEL': '3'}), \
             patch.object(build_skia.subprocess, 'run') as run:
            script.build_skia('arm64ec')
            self.assertEqual(run.call_args.args[0][-2:], ['-j', '3'])
        for invalid in ('', '0', '-1', 'auto', '3 4'):
            with patch.dict(os.environ, {'CMAKE_BUILD_PARALLEL_LEVEL': invalid}), \
                 patch.object(build_skia.subprocess, 'run') as run, self.assertRaises(ValueError):
                script.build_skia('arm64ec')
            run.assert_not_called()

    def test_packaging_uses_candidate_and_both_receipts_preserves_scalar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src = root / 'tmp/win_Release_arm64ec_cpu'
            src.mkdir(parents=True)
            scalar = src / 'skia.lib'
            scalar.write_bytes(b'scalar-original')
            candidate = src / 'vector/skia.lib'
            candidate.parent.mkdir()
            candidate.write_bytes(b'verified-vector')
            suffixes = ('.compile.json', '.raster-object.json',
                        '.source-inputs.json', '.source-patches.diff')
            for suffix in suffixes:
                candidate.with_suffix(suffix).write_text(suffix)
            script = build_skia.SkiaBuildScript()
            script.platform, script.config, script.variant = 'win', 'Release', 'cpu'
            script.strip_arm64e = False
            script.vector_raster_outputs['arm64ec'] = candidate
            with patch.object(build_skia, 'TMP_DIR', root / 'tmp'), \
                 patch.object(build_skia, 'LIBS', {'win': ['skia.lib']}), \
                 patch.object(script, 'get_lib_dir', return_value=root / 'packaged'):
                script.move_libs('arm64ec')
            dest = root / 'packaged/Release/arm64ec/skia.lib'
            self.assertEqual(dest.read_bytes(), b'verified-vector')
            self.assertEqual(scalar.read_bytes(), b'scalar-original')
            for suffix in suffixes:
                self.assertEqual(dest.with_suffix(suffix).read_text(), suffix)


if __name__ == '__main__':
    unittest.main()
