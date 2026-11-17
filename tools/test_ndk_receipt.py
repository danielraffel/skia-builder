#!/usr/bin/env python3
"""Tests for the Android NDK toolchain receipt."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_native_provenance as fixtures  # noqa: E402
import write_ndk_toolchain_receipt as ndk_tool  # noqa: E402

CLANG = "Android (13624864, +pgo, +bolt, +lto, -mlgo, based on r563880c) clang version 21.0.0 (https://android.googlesource.com/toolchain/llvm-project)"
ELF = fixtures.elf


class NdkReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="ndk-receipt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ndk = self.tmp / "ndk"
        (self.ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin").mkdir(parents=True)
        (self.ndk / "source.properties").write_text("Pkg.Desc = Android NDK\nPkg.Revision = 30.0.14904198\n")
        self.ninja = self.tmp / "toolchain.ninja"
        bin_dir = self.ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
        self.ninja.write_text(f"rule cc\n  command = ccache {bin_dir}/clang -c $in -o $out\n"
                              f"rule cxx\n  command = ccache {bin_dir}/clang++ -c $in -o $out\n")

    def archive(self, machine=183, comments=(CLANG,)):
        path = self.tmp / "skia-build-android-arm64-v8a-gpu-release.zip"
        fixtures.write_zip(path, [("build/android-gpu/lib/Release/libskia.a",
                                   fixtures.gnu_ar([("a.o", ELF(machine, comments))]))])
        return path

    def receipt(self, archive, clang=CLANG):
        def run(args, stdin=None):
            program = pathlib.Path(args[0]).name
            out = {"clang": clang, "clang++": clang, "ld.lld": "LLD 21.0.0 (compatible with GNU linkers)",
                   "llvm-ar": "LLVM (http://llvm.org/):\n  LLVM version 21.0.0", "ccache": "ccache version 4.9"
                   }.get(program, "")
            if args[-1] == "-dumpmachine":
                out = "aarch64-unknown-linux-android26"
            if "-E" in args:
                out = "LIBCPP_VERSION=210000\nLIBCPP_ABI_VERSION=2\n"
            return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
        probe = ndk_tool.apple.Probe(runner=run, which=lambda name: f"/usr/bin/{name}",
                                     hasher=lambda path: "ab" * 32, realpath=lambda path: path)
        return ndk_tool.build_receipt("arm64-v8a", 26, "Release", "gpu", self.ndk, [self.ninja],
                                      archive, probe=probe)

    def test_a_receipt_matching_its_archive_is_proven(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        self.assertEqual(ndk_tool.validate_receipt(receipt, archive), [])
        self.assertEqual(receipt["ndk"], {"revision": "30.0.14904198"})
        self.assertEqual(receipt["cpp_abi"]["arm64-v8a"]["stdlib_version"], "210000")
        self.assertEqual(receipt["observed"]["target_triple"], "aarch64-linux-android26")

    def test_an_object_for_another_abi_is_refused(self):
        archive = self.archive(machine=62)
        self.assertTrue(any("in a arm64-v8a cell" in p
                            for p in ndk_tool.validate_receipt(self.receipt(archive), archive)))

    def test_objects_built_by_another_clang_are_refused(self):
        archive = self.archive(comments=("Android clang version 19.0.0 (x)",))
        self.assertTrue(any("built by clang" in p
                            for p in ndk_tool.validate_receipt(self.receipt(archive), archive)))

    def test_an_unknown_ndk_revision_is_refused(self):
        archive = self.archive()
        (self.ndk / "source.properties").write_text("Pkg.Desc = x\n")
        self.assertTrue(ndk_tool.validate_receipt(self.receipt(archive), archive))

    def test_a_receipt_bound_to_other_bytes_is_refused(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        other = self.tmp / "other.zip"
        fixtures.write_zip(other, [("build/android-gpu/lib/Release/libskia.a",
                                    fixtures.gnu_ar([("b.o", ELF(183))]))])
        self.assertTrue(ndk_tool.validate_receipt(receipt, other))

    def test_the_content_addressed_copy_checks_and_tamper_fails(self):
        archive = self.archive()
        data = ndk_tool.apple.canonical_bytes(self.receipt(archive))
        staged = self.tmp / ndk_tool.content_addressed_name(archive.name, data)
        staged.write_bytes(data)
        self.assertEqual(ndk_tool.main([str(staged), "--archive", str(archive), "--check"]), 0)
        staged.write_bytes(data.replace(b"210000", b"210001", 1))
        self.assertEqual(ndk_tool.main([str(staged), "--archive", str(archive), "--check"]), 1)


if __name__ == "__main__":
    unittest.main()
