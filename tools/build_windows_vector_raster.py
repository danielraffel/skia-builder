#!/usr/bin/env python3
"""Build only SkOpts.cpp with pinned Clang and verify archive preservation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from replace_windows_raster_object import replace
from windows_raster_recipe import recipe


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(build_dir: Path, source_dir: Path, original: Path, output: Path,
          arch: str, llvm: Path, ninja: str = 'ninja',
          expected_version: str = '20.1.0') -> dict:
    if output.exists() or output.with_suffix('.raster-object.json').exists():
        raise ValueError('fresh output required; preserve prior provider evidence')
    suffix = '.exe' if (llvm / 'clang-cl.exe').exists() else ''
    compiler = llvm / ('clang-cl' + suffix)
    version = subprocess.check_output([str(compiler), '--version'], text=True)
    if not re.search(r'clang version ' + re.escape(expected_version) + r'(?:\s|$)', version):
        raise ValueError(f'expected pinned LLVM {expected_version}, got {version.strip()}')
    source = source_dir / 'src/core/SkOpts.cpp'
    source_head = subprocess.check_output(
        ['git', '-C', str(source_dir), 'rev-parse', 'HEAD'], text=True).strip()
    if not re.fullmatch('[0-9a-f]{40}', source_head):
        raise ValueError('immutable Skia source identity required')
    diff = subprocess.check_output(['git', '-C', str(source_dir), 'diff', 'HEAD', '--'])
    database = subprocess.check_output(
        [ninja, '-C', str(build_dir), '-t', 'compdb', '-x'], text=True)
    rows = json.loads(database)
    obj = output.with_suffix('.SkOpts.obj')
    if obj.exists():
        raise ValueError('fresh object output required')
    plan = recipe(rows, source, arch, compiler, obj)
    recipe_path = output.with_suffix('.compile.json')
    if recipe_path.exists():
        raise ValueError('fresh recipe output required')
    recipe_path.write_text(json.dumps(plan, indent=2) + '\n')
    subprocess.run(plan['arguments'], cwd=plan['directory'], check=True)
    receipt = replace(original, obj, output, arch,
                      str(llvm / ('llvm-ar' + suffix)),
                      str(llvm / ('llvm-lib' + suffix)),
                      str(llvm / ('llvm-nm' + suffix)))
    receipt.update({'skia_source_head': source_head,
                    'skia_tracked_diff_sha256': hashlib.sha256(diff).hexdigest(),
                    'skopts_source_sha256': digest(source),
                    'compiler_sha256': digest(compiler), 'compiler_version': version,
                    'compile_recipe_sha256': digest(recipe_path),
                    'compilation_database_sha256': hashlib.sha256(database.encode()).hexdigest(),
                    'runtime': plan['runtime'], 'highp_only': True,
                    'keyword_override': False, 'shipping_qualification': False})
    output.with_suffix('.raster-object.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-dir', type=Path, required=True)
    p.add_argument('--source-dir', type=Path, required=True)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--arch', choices=('arm64', 'arm64ec'), required=True)
    p.add_argument('--llvm-bin', type=Path, required=True)
    p.add_argument('--ninja', default='ninja')
    a = p.parse_args()
    print(json.dumps(build(a.build_dir, a.source_dir, a.original, a.output,
                           a.arch, a.llvm_bin, a.ninja), indent=2))
