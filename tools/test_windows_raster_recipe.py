#!/usr/bin/env python3
"""Exercise actual recipe preservation and reject architecture/ABI drift."""
import random
import subprocess
import unittest
from pathlib import Path

from windows_raster_recipe import recipe, split_windows_command


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.source = Path('src/core/SkOpts.cpp').resolve()
        self.args = ['C:/VS/VC/bin/Hostarm64/arm64/cl.exe', '/nologo', '/DSK_GRAPHITE', '/Iinclude with spaces',
                     '/std:c++20', '/O2', '/MT', '/arm64EC', '/showIncludes',
                     '/c', str(self.source), '/Foobj/old.obj', '/Fd', 'shared.pdb']

    def plan(self, args=None, arch='arm64ec'):
        row = {'directory': str(Path.cwd()), 'file': str(self.source),
               'arguments': self.args if args is None else args}
        return recipe([row], self.source, arch, Path('clang-cl'), Path('new.obj'))

    def test_preserves_defines_include_standard_optimization_and_crt(self):
        result = self.plan()
        for flag in ['/DSK_GRAPHITE', '/Iinclude with spaces', '/std:c++20', '/O2', '/MT']:
            self.assertIn(flag, result['arguments'])
        self.assertIn('--target=arm64ec-pc-windows-msvc', result['arguments'])
        self.assertIn('/DSK_DISABLE_LOWP_RASTER_PIPELINE', result['arguments'])
        self.assertNotIn('shared.pdb', result['arguments'])
        self.assertNotIn('/arm64EC', result['arguments'])

    def test_native_arm_does_not_inherit_ec_mode(self):
        args = [a for a in self.args if a != '/arm64EC']
        self.assertIn('--target=arm64-pc-windows-msvc', self.plan(args, 'arm64')['arguments'])
        with self.assertRaises(ValueError):
            self.plan(args)
        with self.assertRaises(ValueError):
            self.plan(arch='arm64')

    def test_repeated_identical_crt_does_not_become_a_false_conflict(self):
        plan = self.plan(self.args + ['/MT', '/arm64EC'])
        self.assertEqual(plan['runtime'], '/MT')
        self.assertEqual(plan['arguments'].count('/MT'), 2)

    def test_refuses_runtime_keyword_wrapper_response_pch_and_source_drift(self):
        variants = [self.args + [flag] for flag in
                    ['/MD', '/D__vectorcall=', '@input.rsp', '/Yupch.h',
                     '--target=x86_64-pc-windows-msvc', 'other.cpp']]
        variants += [['wrapper.exe'] + self.args, self.args + ['/Fd']]
        variants += [['C:/VS/VC/bin/Hostarm64/x64/cl.exe', *self.args[1:]]]
        for args in variants:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.plan(args)

    def test_windows_quoting_roundtrip(self):
        rng = random.Random(42)
        for _ in range(200):
            args = [''.join(rng.choice('ab \\"\t') for _ in range(rng.randrange(30)))
                    for _ in range(rng.randrange(1, 10))]
            self.assertEqual(split_windows_command(subprocess.list2cmdline(args)), args)
        self.assertEqual(split_windows_command('cl.exe /I"path with spaces" /MT'),
                         ['cl.exe', '/Ipath with spaces', '/MT'])
        with self.assertRaises(ValueError):
            split_windows_command('cl.exe "unterminated')

    def test_rejects_missing_and_ambiguous_actual_compile(self):
        row = {'directory': str(Path.cwd()), 'file': str(self.source), 'arguments': self.args}
        for rows in ([], [row, row]):
            with self.assertRaises(ValueError):
                recipe(rows, self.source, 'arm64ec', Path('clang-cl'), Path('new.obj'))


if __name__ == '__main__':
    unittest.main()
