#!/usr/bin/env python3
"""Build only SkOpts.cpp with pinned Clang and verify archive preservation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from replace_windows_raster_object import replace, forbidden_raster_imports
from windows_raster_recipe import recipe


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_manifest(llvm: Path, suffix: str, expected: str) -> dict:
    tools = {}
    for name in ('clang-cl', 'llvm-ar', 'llvm-nm', 'llvm-lib'):
        path = llvm / (name + suffix)
        if not path.is_file():
            raise ValueError(f'missing pinned LLVM tool: {path}')
        tools[name] = {'path': str(path.resolve()), 'sha256': digest(path)}
        if name != 'llvm-lib':
            version = subprocess.check_output([str(path), '--version'], text=True)
            if not re.search(r'(?:clang|LLVM) version ' + re.escape(expected) + r'(?:\s|$)', version):
                raise ValueError(f'expected LLVM {expected}: {name}: {version.strip()}')
            tools[name]['version'] = version
    # LLVM's official package ships ar/lib as the same multicall executable.
    # llvm-lib silently ignores --version and returns zero, so that invocation
    # cannot prove its version. Bind it to the verified ar bytes instead.
    if tools['llvm-lib']['sha256'] != tools['llvm-ar']['sha256']:
        raise ValueError('llvm-lib must match the versioned LLVM ar multicall binary')
    tools['llvm-lib']['version'] = tools['llvm-ar']['version']
    tools['llvm-lib']['version_source'] = 'byte-identical versioned llvm-ar executable'
    return tools


def source_manifest(source_dir: Path) -> dict:
    guards = {
        'include/private/SkFeatures.h':
            '#if (defined(__i386) || defined(_M_IX86) ||  defined(__x86_64__) || defined(_M_X64)) && !defined(_M_ARM64EC)',
        'src/opts/SkRasterPipeline_opts.h': '#elif defined(_MSC_VER) && !defined(_M_ARM64EC)',
    }
    for name, anchor in guards.items():
        if anchor not in (source_dir / name).read_text(encoding='utf-8'):
            raise ValueError(f'required Windows vector ABI/source guard missing: {name}')
    tracked = subprocess.check_output(
        ['git', '-C', str(source_dir), 'ls-files', '-z', '--', 'include', 'src']).decode().split('\0')
    tracked = {p for p in tracked if p}
    actual = {p.relative_to(source_dir).as_posix()
              for directory in ('include', 'src') for p in (source_dir / directory).rglob('*')
              if p.is_file()}
    if actual != tracked:
        raise ValueError('untracked, ignored or missing provider source inputs: '
                         + repr(sorted(actual ^ tracked)[:10]))
    files = []
    for name in sorted(tracked):
        path = source_dir / name
        if path.is_symlink():
            raise ValueError(f'symlink source input requires separate qualification: {name}')
        files.append({'path': name, 'sha256': digest(path)})
    patches = Path(__file__).resolve().parents[1] / 'patches'
    scripts = [{'name': p.name, 'sha256': digest(p)} for p in sorted(patches.glob('apply_*.py'))]
    return {'scope': 'all Skia include/src files; system and external headers remain separate',
            'files': files, 'producer_patch_script_inputs': scripts,
            'verified_source_guards': guards}


def archive_import_delta(original: Path, candidate: Path, nm: str) -> dict:
    def imports(path):
        text = subprocess.check_output([nm, '--undefined-only', '-j', str(path)], text=True)
        return {s.strip() for s in text.splitlines() if s.strip() and not s.strip().endswith(':')}
    before, after = imports(original), imports(candidate)
    if not before or not after:
        raise ValueError('final archive import audit requires positive symbol evidence')
    added = sorted(after - before)
    if forbidden_raster_imports('\n'.join(added)):
        raise ValueError('final archive introduces STL helpers or foreign CPU dispatch imports')
    return {'scope': 'complete final archive undefined-symbol delta; consumer link still required',
            'original_count': len(before), 'candidate_count': len(after),
            'added': added, 'removed': sorted(before - after),
            'new_stl_or_x86_dispatch_imports': False}


def build(build_dir: Path, source_dir: Path, original: Path, output: Path,
          arch: str, llvm: Path, ninja: str = 'ninja',
          expected_version: str = '20.1.0') -> dict:
    if output.exists() or output.with_suffix('.raster-object.json').exists():
        raise ValueError('fresh output required; preserve prior provider evidence')
    suffix = '.exe' if (llvm / 'clang-cl.exe').exists() else ''
    compiler = llvm / ('clang-cl' + suffix)
    tools = tool_manifest(llvm, suffix, expected_version)
    version = tools['clang-cl']['version']
    source = source_dir / 'src/core/SkOpts.cpp'
    source_head = subprocess.check_output(
        ['git', '-C', str(source_dir), 'rev-parse', 'HEAD'], text=True).strip()
    if not re.fullmatch('[0-9a-f]{40}', source_head):
        raise ValueError('immutable Skia source identity required')
    diff = subprocess.check_output(['git', '-C', str(source_dir), 'diff', 'HEAD', '--'])
    inputs = source_manifest(source_dir)
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
    source_path = output.with_suffix('.source-inputs.json')
    patch_path = output.with_suffix('.source-patches.diff')
    for path in (source_path, patch_path):
        if path.exists():
            raise ValueError(f'fresh source evidence output required: {path}')
    source_path.write_text(json.dumps(inputs, indent=2) + '\n')
    patch_path.write_bytes(diff)
    subprocess.run(plan['arguments'], cwd=plan['directory'], check=True)
    if source_manifest(source_dir) != inputs:
        raise ValueError('provider source inputs changed during compilation')
    receipt = replace(original, obj, output, arch,
                      str(llvm / ('llvm-ar' + suffix)),
                      str(llvm / ('llvm-lib' + suffix)),
                      str(llvm / ('llvm-nm' + suffix)))
    imports = archive_import_delta(original, output, str(llvm / ('llvm-nm' + suffix)))
    receipt.update({'skia_source_head': source_head,
                    'skia_tracked_diff_sha256': hashlib.sha256(diff).hexdigest(),
                    'skopts_source_sha256': digest(source),
                    'compiler_sha256': digest(compiler), 'compiler_version': version,
                    'llvm_tools': tools, 'archive_import_audit': imports,
                    'source_inputs_sha256': digest(source_path),
                    'source_patch_diff_sha256': digest(patch_path),
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
