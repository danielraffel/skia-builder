#!/usr/bin/env python3
"""Reject mixed tools, missing ABI guards and new final-archive helper imports."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from build_windows_vector_raster import tool_manifest, source_manifest, archive_import_delta


class ProvenanceTests(unittest.TestCase):
    def test_lib_is_bound_to_versioned_multicall_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            for name in ('clang-cl', 'llvm-ar', 'llvm-lib', 'llvm-nm'):
                (p / name).write_bytes(b'official-tool')
            with patch('build_windows_vector_raster.subprocess.check_output',
                       return_value='LLVM version 20.1.0\n'):
                tools = tool_manifest(p, '', '20.1.0')
                self.assertIn('byte-identical', tools['llvm-lib']['version_source'])
                (p / 'llvm-lib').write_bytes(b'foreign-tool')
                with self.assertRaisesRegex(ValueError, 'multicall'):
                    tool_manifest(p, '', '20.1.0')

    def test_mixed_version_or_missing_tool_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p / 'clang-cl').write_bytes(b'compiler')
            with patch('build_windows_vector_raster.subprocess.check_output',
                       return_value='clang version 23.1.3\n'), self.assertRaisesRegex(ValueError, '20.1.0'):
                tool_manifest(p, '', '20.1.0')
            with patch('build_windows_vector_raster.subprocess.check_output',
                       return_value='clang version 20.1.0\n'), self.assertRaisesRegex(ValueError, 'missing'):
                tool_manifest(p, '', '20.1.0')

    def test_missing_guard_or_untracked_header_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            names = ['include/private/SkFeatures.h', 'src/opts/SkRasterPipeline_opts.h']
            for name in names:
                (p / name).parent.mkdir(parents=True, exist_ok=True)
                (p / name).write_text('unpatched')
            with self.assertRaisesRegex(ValueError, 'guard missing'):
                source_manifest(p)
            (p / names[0]).write_text('#if (defined(__i386) || defined(_M_IX86) ||  defined(__x86_64__) || defined(_M_X64)) && !defined(_M_ARM64EC)')
            (p / names[1]).write_text('#elif defined(_MSC_VER) && !defined(_M_ARM64EC)')
            with patch('build_windows_vector_raster.subprocess.check_output',
                       return_value=('\0'.join(names)+'\0').encode()):
                before = source_manifest(p)
                (p / names[0]).write_text((p / names[0]).read_text()+'\n// changed')
                self.assertNotEqual(before, source_manifest(p))
                (p / 'include/ignored-shadow.h').write_text('shadow input')
                with self.assertRaisesRegex(ValueError, 'source inputs'):
                    source_manifest(p)

    def test_final_archive_existing_stl_allowed_new_stl_refused(self):
        with patch('build_windows_vector_raster.subprocess.check_output',
                   side_effect=['old.obj:\n__std_existing\nmemcpy\n',
                                'new.obj:\n__std_existing\nmemcpy\n__os_arm64x_check_icall\n']):
            result = archive_import_delta(Path('old.lib'), Path('new.lib'), 'llvm-nm')
            self.assertEqual(result['added'], ['__os_arm64x_check_icall'])
        for symbol in ('__std_new_helper', '?Init_ml3@SkOpts@@', '?gCachedFeatures@SkCpu@@'):
            with patch('build_windows_vector_raster.subprocess.check_output',
                       side_effect=['memcpy\n', 'memcpy\n'+symbol+'\n']), self.assertRaises(ValueError):
                archive_import_delta(Path('old.lib'), Path('new.lib'), 'llvm-nm')

    def test_empty_symbol_audit_is_not_a_success(self):
        with patch('build_windows_vector_raster.subprocess.check_output',
                   side_effect=['old.obj:\n', 'new.obj:\n']), self.assertRaises(ValueError):
            archive_import_delta(Path('old.lib'), Path('new.lib'), 'llvm-nm')


if __name__ == '__main__':
    unittest.main()
