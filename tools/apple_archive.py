#!/usr/bin/env python3
"""Read universal (fat) files, static archives and Mach-O objects in pure Python.

The legal manifest, the Apple toolchain receipt and the archive comparison all
need to look inside a packaged ``.a``: which architecture slices it carries,
which object members each slice holds, and which platform/SDK every member
was compiled for.  ``lipo``/``ar``/``otool`` answer one question per process
and only on macOS; this module answers all of them from the bytes, so the
same code runs in the Linux lint job and the tests can build fixtures without
Xcode.

Static archives come in two dialects and both are read:

* BSD (Apple ``ar``/``libtool``): long names are stored as ``#1/<len>`` with
  the name at the start of the member data, and ``libtool`` pads members to
  8-byte alignment.
* GNU/System V (binutils ``ar``, COFF ``.lib``): long names live in a ``//``
  table and are referenced as ``/<offset>``.

Symbol tables (``__.SYMDEF*``, ``/``, ``/SYM64/``) are reported separately
from object members because they are derived from the members, not compiled.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
AR_MAGIC = b"!<arch>\n"
MH_MAGIC_64 = 0xFEEDFACF
MH_MAGIC = 0xFEEDFACE
LC_SEGMENT = 0x1
LC_SEGMENT_64 = 0x19
LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_MACOSX = 0x24
LC_VERSION_MIN_IPHONEOS = 0x25

CPU_ARCH_ABI64 = 0x01000000
CPU_NAMES = {
    7: "i386",
    7 | CPU_ARCH_ABI64: "x86_64",
    12: "arm",
    12 | CPU_ARCH_ABI64: "arm64",
}
# LC_BUILD_VERSION platform numbers (mach-o/loader.h).
PLATFORMS = {1: "macos", 2: "ios", 3: "tvos", 4: "watchos", 6: "maccatalyst",
             7: "ios-simulator", 8: "tvos-simulator", 9: "watchos-simulator",
             11: "visionos", 12: "visionos-simulator"}
SYMBOL_TABLE_NAMES = {"__.SYMDEF", "__.SYMDEF SORTED", "__.SYMDEF_64",
                      "__.SYMDEF_64 SORTED", "/", "/SYM64/"}


class ArchiveFormatError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Slice:
    arch: str
    data: bytes


@dataclass
class Member:
    name: str
    data: bytes
    date: int
    uid: int
    gid: int
    mode: str

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.data)


@dataclass
class Archive:
    members: list[Member] = field(default_factory=list)
    symbol_tables: list[Member] = field(default_factory=list)


# Subtypes that keep the plain architecture name; any other subtype gets a
# distinct name, so two slices of one CPU type can never share a key.
PLAIN_SUBTYPES = {"x86_64": 3, "arm64": 0, "i386": 3, "arm": 0}
NAMED_SUBTYPES = {("x86_64", 8): "x86_64h", ("arm64", 2): "arm64e", ("arm64", 1): "arm64v8"}


def arch_name(cputype: int, cpusubtype: int) -> str:
    """A name unique to (cputype, cpusubtype), ignoring capability bits."""
    name = CPU_NAMES.get(cputype, f"cpu-{cputype:#x}")
    subtype = cpusubtype & 0x00FFFFFF
    if name in PLAIN_SUBTYPES and subtype == PLAIN_SUBTYPES[name]:
        return name
    return NAMED_SUBTYPES.get((name, subtype), f"{name}-subtype{subtype}")


def slices(data: bytes) -> list[Slice]:
    """Return the architecture slices of a fat file, or the file as one slice."""
    if len(data) >= 8:
        magic = struct.unpack(">I", data[:4])[0]
        if magic in (FAT_MAGIC, FAT_MAGIC_64):
            count = struct.unpack(">I", data[4:8])[0]
            # A Java class file also starts with 0xCAFEBABE; its "count" is a
            # class-file version, far above any real slice count.
            if 0 < count < 32:
                result = []
                offset = 8
                for _ in range(count):
                    if magic == FAT_MAGIC:
                        cputype, subtype, start, size, _align = struct.unpack(
                            ">iiIII", data[offset:offset + 20])
                        offset += 20
                    else:
                        cputype, subtype, start, size, _align, _reserved = struct.unpack(
                            ">iiQQII", data[offset:offset + 32])
                        offset += 32
                    if start + size > len(data):
                        raise ArchiveFormatError("fat slice extends past end of file")
                    name = arch_name(cputype & 0xFFFFFFFF, subtype)
                    if any(piece.arch == name for piece in result):
                        raise ArchiveFormatError(f"fat file has more than one {name} slice")
                    result.append(Slice(name, data[start:start + size]))
                return result
    return [Slice(thin_arch(data), data)]


def thin_arch(data: bytes) -> str:
    """Best-effort architecture of a thin archive or object (first Mach-O member)."""
    if data.startswith(AR_MAGIC):
        try:
            archive = parse_archive(data)
        except ArchiveFormatError:
            return "unknown"
        for member in archive.members:
            arch = macho_arch(member.data)
            if arch:
                return arch
        return "unknown"
    return macho_arch(data) or "unknown"


def macho_arch(data: bytes) -> str | None:
    if len(data) < 12:
        return None
    magic = struct.unpack("<I", data[:4])[0]
    if magic not in (MH_MAGIC, MH_MAGIC_64):
        return None
    cputype, subtype = struct.unpack("<iI", data[4:12])
    return arch_name(cputype & 0xFFFFFFFF, subtype)


def parse_archive(data: bytes) -> Archive:
    if not data.startswith(AR_MAGIC):
        raise ArchiveFormatError("not a static archive")
    archive = Archive()
    gnu_names = b""
    offset = len(AR_MAGIC)
    while offset < len(data):
        if data[offset:offset + 1] == b"\n":  # alignment padding between members
            offset += 1
            continue
        header = data[offset:offset + 60]
        if len(header) < 60 or header[58:60] != b"`\n":
            raise ArchiveFormatError(f"bad archive member header at offset {offset}")
        raw_name = header[0:16].decode("ascii", "replace").rstrip(" ")
        size = int(header[48:58].decode("ascii").strip() or "0")
        body_start = offset + 60
        body = data[body_start:body_start + size]
        if len(body) != size:
            raise ArchiveFormatError(f"truncated archive member at offset {offset}")
        offset = body_start + size + (size & 1)

        def field_int(start: int, end: int, base: int = 10) -> int:
            text = header[start:end].decode("ascii").strip()
            return int(text, base) if text else 0

        date = field_int(16, 28)
        uid = field_int(28, 34)
        gid = field_int(34, 40)
        mode = header[40:48].decode("ascii").strip()

        if raw_name.startswith("#1/"):
            length = int(raw_name[3:])
            name = body[:length].rstrip(b"\0").decode("utf-8", "replace")
            body = body[length:]
        elif raw_name == "//":
            gnu_names = body
            continue
        elif raw_name in ("/", "/SYM64/"):
            name = raw_name
        elif raw_name.startswith("/") and raw_name[1:].isdigit():
            start = int(raw_name[1:])
            end = gnu_names.find(b"\n", start)
            name = gnu_names[start:end if end >= 0 else None].decode("utf-8", "replace")
            name = name[:-1] if name.endswith("/") else name
        else:
            name = raw_name[:-1] if raw_name.endswith("/") else raw_name
        member = Member(name, body, date, uid, gid, mode)
        if name in SYMBOL_TABLE_NAMES:
            archive.symbol_tables.append(member)
        else:
            archive.members.append(member)
    return archive


def unpadded_candidates(data: bytes) -> list[bytes]:
    """The member bytes, then the same bytes without up to 7 bytes of padding.

    ``libtool -static`` pads each member to 8-byte alignment inside ``ar_size``,
    so the stored bytes can be the object file plus trailing NUL or newline
    bytes.  A caller matching members to object files tries each candidate.
    """
    candidates = [data]
    for trim in range(1, 8):
        if len(data) <= trim:
            break
        tail = data[-trim:]
        if tail.strip(b"\0\n"):
            break
        candidates.append(data[:-trim])
    return candidates


def _version(value: int) -> str:
    major, minor, patch = value >> 16, (value >> 8) & 0xFF, value & 0xFF
    return f"{major}.{minor}.{patch}" if patch else f"{major}.{minor}"


@dataclass
class Section:
    segment: str
    name: str
    data: bytes


@dataclass
class MachO:
    arch: str
    platform: str | None = None
    minos: str | None = None
    sdk: str | None = None
    sections: list[Section] = field(default_factory=list)
    symtab: bytes = b""


def parse_macho(data: bytes) -> MachO | None:
    """Parse a thin Mach-O object; None when the bytes are not Mach-O."""
    arch = macho_arch(data)
    if arch is None:
        return None
    magic = struct.unpack("<I", data[:4])[0]
    is64 = magic == MH_MAGIC_64
    header_size = 32 if is64 else 28
    ncmds, sizeofcmds = struct.unpack("<II", data[16:24])
    result = MachO(arch)
    offset = header_size
    end = header_size + sizeofcmds
    for _ in range(ncmds):
        if offset + 8 > end:
            break
        cmd, cmdsize = struct.unpack("<II", data[offset:offset + 8])
        if cmdsize < 8:
            break
        body = data[offset:offset + cmdsize]
        if cmd == LC_BUILD_VERSION and len(body) >= 24:
            platform, minos, sdk = struct.unpack("<III", body[8:20])
            result.platform = PLATFORMS.get(platform, f"platform-{platform}")
            result.minos, result.sdk = _version(minos), _version(sdk)
        elif cmd in (LC_VERSION_MIN_MACOSX, LC_VERSION_MIN_IPHONEOS) and len(body) >= 16:
            version, sdk = struct.unpack("<II", body[8:16])
            result.platform = "macos" if cmd == LC_VERSION_MIN_MACOSX else "ios"
            result.minos, result.sdk = _version(version), _version(sdk)
        elif cmd in (LC_SEGMENT_64, LC_SEGMENT):
            if is64:
                nsects = struct.unpack("<I", body[64:68])[0]
                sect_offset, sect_size = 72, 80
            else:
                nsects = struct.unpack("<I", body[48:52])[0]
                sect_offset, sect_size = 56, 68
            for index in range(nsects):
                raw = body[sect_offset + index * sect_size:sect_offset + (index + 1) * sect_size]
                sectname = raw[0:16].rstrip(b"\0").decode("ascii", "replace")
                segname = raw[16:32].rstrip(b"\0").decode("ascii", "replace")
                if is64:
                    size, file_offset = struct.unpack("<QI", raw[40:52])
                else:
                    size, file_offset = struct.unpack("<II", raw[36:44])
                content = data[file_offset:file_offset + size] if file_offset else b""
                result.sections.append(Section(segname, sectname, content))
        elif cmd == 0x2 and len(body) >= 24:  # LC_SYMTAB
            symoff, nsyms, stroff, strsize = struct.unpack("<IIII", body[8:24])
            entry = 16 if is64 else 12
            result.symtab = (data[symoff:symoff + nsyms * entry]
                             + data[stroff:stroff + strsize])
        offset += cmdsize
    return result
