#!/usr/bin/env python3
"""Derive a single Clang raster compile from Ninja's actual MSVC recipe.

No other translation unit changes compiler. Unknown wrappers, response files,
PCHs, target overrides and ABI keyword definitions fail closed.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path


def split_windows_command(command: str) -> list[str]:
    """Parse MS CRT argument quoting, including /I"paths with spaces"."""
    args, part, quoted, active, i = [], [], False, False, 0
    while i < len(command):
        ch = command[i]
        if ch in ' \t' and not quoted:
            if active:
                args.append(''.join(part))
                part, active = [], False
            i += 1
            continue
        active = True
        if ch == '\\':
            end = i
            while end < len(command) and command[end] == '\\':
                end += 1
            n = end - i
            if end < len(command) and command[end] == '"':
                part.extend('\\' * (n // 2))
                if n % 2:
                    part.append('"')
                else:
                    quoted = not quoted
                i = end + 1
            else:
                part.extend('\\' * n)
                i = end
        elif ch == '"':
            quoted = not quoted
            i += 1
        else:
            part.append(ch)
            i += 1
    if quoted:
        raise ValueError('unterminated Windows command quote')
    if active:
        args.append(''.join(part))
    return args


def recipe(rows: list[dict], source: Path, arch: str, compiler: Path,
           output: Path) -> dict:
    if arch not in ('arm64', 'arm64ec'):
        raise ValueError('vector raster recipe requires an explicit ARM ABI')
    matches = [r for r in rows
               if (Path(r['directory']) / r['file']).resolve() == source.resolve()]
    if len(matches) != 1:
        raise ValueError(f'expected one actual SkOpts.cpp compile, found {len(matches)}')
    row = matches[0]
    args = row.get('arguments') or split_windows_command(row['command'])
    wrapper = []
    if args and args[0].replace('\\', '/').rsplit('/', 1)[-1].lower() in ('ccache', 'ccache.exe'):
        cache = shutil.which(args[0])
        if not cache:
            raise ValueError('provider ccache wrapper is not available')
        wrapper = [str(Path(cache).resolve())]
        args = args[1:]
    if not args or args[0].replace('\\', '/').rsplit('/', 1)[-1].lower() != 'cl.exe':
        raise ValueError('expected direct MSVC compiler; wrappers need explicit qualification')
    if args[0].replace('\\', '/').lower().split('/')[-2:-1] != ['arm64']:
        raise ValueError('provider compiler must be the explicit MSVC ARM64 target tool')
    cwd = Path(row['directory']).resolve()
    flags, sources, runtime, ec, i = [], 0, [], 0, 1
    while i < len(args):
        arg = args[i]
        low = arg.lower()
        if (arg.startswith('@') or low.startswith(('/yu', '/yc', '/fp', '--target', '-target'))
                or '__vectorcall' in low or arg in ('&&', '||', '&', '|')):
            raise ValueError(f'unsupported raster recipe argument: {arg}')
        if low.startswith(('/fo', '/fd')):
            if len(arg) == 3:
                i += 1
                if i >= len(args):
                    raise ValueError('missing compiler output argument')
        elif low in ('/showincludes', '/fs', '/mp', '/c'):
            pass
        elif low == '/arm64ec':
            ec += 1
        elif low in ('/mt', '/mtd', '/md', '/mdd'):
            runtime.append(arg)
            flags.append(arg)
        elif (cwd / arg).resolve() == source.resolve():
            sources += 1
        elif low.endswith(('.cpp', '.cc', '.c', '.cxx')):
            raise ValueError('unexpected additional source')
        elif low in ('/zi', '/zi-'):
            # Embed debug data in this one object; never share MSVC's PDB.
            flags.append('/Z7')
        else:
            flags.append(arg)
        i += 1
    if (sources != 1 or len({r.lower() for r in runtime}) != 1
            or bool(ec) != (arch == 'arm64ec')):
        raise ValueError('source, CRT or ARM64EC mode disagrees with provider recipe')
    if any('SK_DISABLE_LOWP_RASTER_PIPELINE' in a for a in flags):
        raise ValueError('lowp configuration must be owned by the raster producer step')
    command = [*wrapper, str(compiler.resolve()), f'--target={arch}-pc-windows-msvc',
               *flags, '/DSK_DISABLE_LOWP_RASTER_PIPELINE', '/c', str(source.resolve()),
               '/Fo' + str(output.resolve())]
    return {'directory': str(cwd), 'arguments': command, 'provider_compile': row,
            'architecture': arch, 'runtime': runtime[0], 'highp_only': True,
            'keyword_override': False, 'cache_wrapper': wrapper}
