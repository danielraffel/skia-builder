#!/usr/bin/env python3
import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_windows_archive as cwa  # noqa: E402

ARM64, ARM64EC, X64 = 0xAA64, 0xA641, 0x8664


def coff_object(machine: int) -> bytes:
    return struct.pack("<HHIIIHH", machine, 0, 0, 0, 0, 0, 0)


def anon_object(machine: int) -> bytes:
    # Sig1=0, Sig2=0xFFFF, Version=1, Machine
    return struct.pack("<HHHH", 0, 0xFFFF, 1, machine) + b"\0" * 24


def ar_member(name: str, data: bytes) -> bytes:
    header = f"{name:<16}{0:<12}{0:<6}{0:<6}{644:<8}{len(data):<10}`\n".encode()
    assert len(header) == 60
    return header + data + (b"\n" if len(data) % 2 else b"")


def lib(*objects: bytes) -> bytes:
    out = cwa.AR_MAGIC + ar_member("/", b"\0\0\0\0symbols")
    for index, obj in enumerate(objects):
        out += ar_member(f"obj{index}.obj/", obj)
    return out


def receipt(arch: str, config: str = "Release") -> dict:
    return {
        "schema_version": 1,
        "target": {"platform": "windows", "architecture": arch, "configuration": config, "variant": "gpu"},
        "producer": {
            "skia_gn_compiler": {
                "driver": "cl.exe",
                "path": r"C:\VS\VC\Tools\MSVC\14.51.36231\bin\HostX64\arm64\cl.exe",
                "version": "Microsoft (R) C/C++ Optimizing Compiler Version 19.51.36231 for ARM64",
                "source": "toolchain.ninja",
            },
            "dawn_cmake_compiler": {
                "driver": "cl.exe",
                "path": r"C:\VS\VC\Tools\MSVC\14.51.36231\bin\HostX64\arm64\cl.exe",
                "version": "Microsoft (R) C/C++ Optimizing Compiler Version 19.51.36231 for ARM64",
                "source": "build-skia.py MSVC ABI",
            },
            "msvc_toolset_version": "14.51.36231",
            "windows_sdk_version": "10.0.26100.0",
            "visual_studio_vc_dir": r"C:\VS\VC",
            "host_architecture": "ARM64",
        },
        "runtime": {"abi": "msvc", "library": "static", "compile_flag": "/MT",
                    "consumer_requirement": "MSVC STL/CRT toolset >= 14.51.36231"},
    }


class CheckWindowsArchive(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def archive(self, name, libs, receipt_data):
        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as zf:
            for member, data in libs.items():
                zf.writestr(member, data)
            if receipt_data is not None:
                zf.writestr("build/win-gpu/msvc-toolchain.json", json.dumps(receipt_data))
        return path

    def test_good_arm64_archive_passes(self):
        path = self.archive("skia-build-win-arm64-gpu-release.zip",
                            {"build/win-gpu/lib/Release/arm64/skia.lib":
                             lib(coff_object(ARM64), anon_object(ARM64))},
                            receipt("arm64"))
        self.assertEqual(cwa.check_archive(path), [])
        self.assertEqual(cwa.main([str(path)]), 0)

    def test_x64_object_in_arm64_archive_fails(self):
        path = self.archive("skia-build-win-arm64-gpu-release.zip",
                            {"build/win-gpu/lib/Release/arm64/skia.lib":
                             lib(coff_object(ARM64), coff_object(X64))},
                            receipt("arm64"))
        problems = cwa.check_archive(path)
        self.assertTrue(any("other machines" in p for p in problems), problems)

    def test_good_arm64ec_archive_passes(self):
        path = self.archive("skia-build-win-arm64ec-gpu-release.zip",
                            {"build/win-gpu/lib/Release/arm64ec/skia.lib":
                             lib(coff_object(ARM64EC), anon_object(ARM64EC))},
                            receipt("arm64ec"))
        self.assertEqual(cwa.check_archive(path), [])

    def test_x64_library_shipped_as_arm64_fails(self):
        path = self.archive("skia-build-win-arm64-gpu-release.zip",
                            {"build/win-gpu/lib/Release/x64/skia.lib": lib(coff_object(X64))},
                            receipt("arm64"))
        problems = cwa.check_archive(path)
        self.assertTrue(any("no static libraries" in p for p in problems), problems)
        self.assertTrue(any("outside" in p for p in problems), problems)

    def test_missing_receipt_fails(self):
        path = self.archive("skia-build-win-arm64-gpu-release.zip",
                            {"build/win-gpu/lib/Release/arm64/skia.lib": lib(coff_object(ARM64))},
                            None)
        self.assertTrue(any("msvc-toolchain.json" in p for p in cwa.check_archive(path)))

    def test_unknown_receipt_fails_publish(self):
        bad = receipt("arm64")
        bad["producer"]["msvc_toolset_version"] = "unknown"
        bad["producer"]["dawn_cmake_compiler"]["version"] = "clang-cl: error: no input files"
        path = self.archive("skia-build-win-arm64-gpu-release.zip",
                            {"build/win-gpu/lib/Release/arm64/skia.lib": lib(coff_object(ARM64))},
                            bad)
        self.assertEqual(cwa.main([str(path)]), 1)

    def test_debug_archive_expects_debug_receipt(self):
        path = self.archive("skia-build-win-x64-gpu-debug.zip",
                            {"build/win-gpu/lib/Debug/x64/skia.lib": lib(coff_object(X64))},
                            receipt("x64", "Release"))
        problems = cwa.check_archive(path)
        self.assertTrue(any("configuration" in p for p in problems), problems)

    def test_non_windows_archives_are_skipped(self):
        path = self.tmp / "skia-build-mac-arm64-gpu-release.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("x", "y")
        self.assertEqual(cwa.main([str(path)]), 0)

    def test_coff_machines_reads_odd_sized_members(self):
        data = lib(coff_object(ARM64) + b"x", coff_object(ARM64))
        self.assertEqual(cwa.coff_machines(io.BytesIO(data))["arm64"], 2)


if __name__ == "__main__":
    unittest.main()
