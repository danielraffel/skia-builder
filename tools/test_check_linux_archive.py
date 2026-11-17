#!/usr/bin/env python3
"""Tests for the Linux BackupRefPtr gate and the Linux GN arguments behind it."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_linux_archive as gate  # noqa: E402

spec = importlib.util.spec_from_file_location("build_skia", ROOT / "build-skia.py")
build_skia = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_skia)

UNDEF = "                 U base::internal::RawPtrBackupRefImpl<true>::AcquireInternal(unsigned long)\n"
DEF = "0000000000000010 T base::internal::RawPtrBackupRefImpl<true>::AcquireInternal(unsigned long)\n"


class GateTests(unittest.TestCase):
    def test_reference_with_no_definition_is_refused(self) -> None:
        found = gate.unresolved_backup_ref({"libskia.a": "Resource.o:\n" + UNDEF})
        self.assertEqual(list(found), ["libskia.a"])

    def test_reference_defined_by_a_shipped_library_is_accepted(self) -> None:
        self.assertEqual(gate.unresolved_backup_ref({"libskia.a": UNDEF, "libpa.a": DEF}), {})

    def test_other_undefined_symbols_are_ignored(self) -> None:
        self.assertEqual(gate.unresolved_backup_ref({"libskia.a": "                 U malloc\n"}), {})

    @unittest.skipUnless(shutil.which("cc") and shutil.which("ar") and shutil.which("nm"),
                         "a C compiler, ar and nm are required")
    def test_real_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "a.c"
            # A C symbol named like the C++ one is enough for nm's pattern.
            source.write_text("void RawPtrBackupRefImpl_AcquireInternal(void);\n"
                              "void use(void) { RawPtrBackupRefImpl_AcquireInternal(); }\n")
            subprocess.run(["cc", "-c", str(source), "-o", str(root / "a.o")], check=True)
            subprocess.run(["ar", "rcs", str(root / "libskia.a"), str(root / "a.o")], check=True)
            archive = root / "skia-build-linux-x64-gpu-release.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.write(root / "libskia.a", "build/linux-gpu/lib/Release/libskia.a")
            self.assertTrue(gate.check_archive(archive))
            # Control: the same archive with a definition passes.
            (root / "b.c").write_text("void RawPtrBackupRefImpl_AcquireInternal(void) {}\n")
            subprocess.run(["cc", "-c", str(root / "b.c"), "-o", str(root / "b.o")], check=True)
            subprocess.run(["ar", "rcs", str(root / "libpa.a"), str(root / "b.o")], check=True)
            with zipfile.ZipFile(archive, "a") as handle:
                handle.write(root / "libpa.a", "build/linux-gpu/lib/Release/libpa.a")
            self.assertEqual(gate.check_archive(archive), [])


class GnArgsTests(unittest.TestCase):
    def test_linux_builds_turn_partition_alloc_off(self) -> None:
        for table in (build_skia.PLATFORM_GN_ARGS, build_skia.PLATFORM_GN_ARGS_CPU):
            self.assertIn("skia_use_partition_alloc = false", table["linux"])

    def test_no_other_platform_changes(self) -> None:
        for table in (build_skia.PLATFORM_GN_ARGS, build_skia.PLATFORM_GN_ARGS_CPU):
            for platform, args in table.items():
                if platform != "linux":
                    self.assertNotIn("skia_use_partition_alloc", args, platform)
        self.assertNotIn("skia_use_partition_alloc", build_skia.RELEASE_GN_ARGS)


class AndroidTests(unittest.TestCase):
    def test_android_archives_are_gated_by_name(self) -> None:
        self.assertTrue(gate.NAME_RE.match("skia-build-android-arm64-v8a-gpu-release.zip"))
        self.assertTrue(gate.NAME_RE.match("skia-build-android-x86_64-gpu-release.zip"))
        self.assertTrue(gate.NAME_RE.match("skia-build-linux-x64-gpu-release.zip"))
        self.assertFalse(gate.NAME_RE.match("skia-build-win-x64-gpu-release.zip"))

    def test_android_gn_args_are_pulps_and_not_the_shared_release_args(self) -> None:
        args = build_skia.ANDROID_GN_ARGS.format(cpu="arm64", ndk="/ndk")
        for line in ('target_os = "android"', 'target_cpu = "arm64"', 'ndk = "/ndk"', "ndk_api = 26",
                     "skia_enable_graphite = true", "skia_use_dawn = true", "skia_use_vulkan = true",
                     "skia_use_gl = false", "skia_enable_pdf = false", "skia_enable_sksl = true"):
            self.assertIn(line, args.splitlines())
        # Nothing the shared tables add: they would make the asset differ from Pulp's build.
        for forbidden in ("skia_use_partition_alloc", "skia_use_libwebp", "skia_use_xps", "cc = "):
            self.assertNotIn(forbidden, args)

    def test_android_cpu_mapping(self) -> None:
        self.assertEqual(build_skia.ANDROID_ABI_CPU, {"arm64-v8a": "arm64", "x86_64": "x64"})


if __name__ == "__main__":
    unittest.main()
