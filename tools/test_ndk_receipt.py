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
CELL = {"abi": "arm64-v8a", "configuration": "Release", "variant": "gpu"}
CELL_ARGS = ["--abi", "arm64-v8a", "--configuration", "Release", "--variant", "gpu"]


class NdkReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="ndk-receipt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ndk = self.tmp / "ndk"
        (self.ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin").mkdir(parents=True)
        (self.ndk / "source.properties").write_text("Pkg.Desc = Android NDK\nPkg.Revision = 30.0.14904198-beta1\n")
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
        self.assertEqual(ndk_tool.validate_receipt(receipt, archive, **CELL), [])
        self.assertEqual(receipt["ndk"], {"revision": "30.0.14904198", "pkg_revision": "30.0.14904198-beta1"})
        self.assertEqual(receipt["cpp_abi"]["arm64-v8a"]["stdlib_version"], "210000")
        self.assertEqual(receipt["observed"]["target_triple"], "aarch64-linux-android26")

    def test_an_object_for_another_abi_is_refused(self):
        archive = self.archive(machine=62)
        self.assertTrue(any("in a arm64-v8a cell" in p
                            for p in ndk_tool.validate_receipt(self.receipt(archive), archive, **CELL)))

    def test_objects_built_by_another_clang_are_refused(self):
        archive = self.archive(comments=("Android clang version 19.0.0 (x)",))
        self.assertTrue(any("built by clang" in p
                            for p in ndk_tool.validate_receipt(self.receipt(archive), archive, **CELL)))

    def test_an_unknown_ndk_revision_is_refused(self):
        archive = self.archive()
        (self.ndk / "source.properties").write_text("Pkg.Desc = x\n")
        self.assertTrue(ndk_tool.validate_receipt(self.receipt(archive), archive, **CELL))

    def test_a_different_valid_ndk_revision_is_refused(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        receipt["ndk"]["revision"] = "29.0.13113456"
        receipt["ndk"]["pkg_revision"] = "29.0.13113456"
        problems = ndk_tool.validate_receipt(receipt, archive, **CELL)
        self.assertTrue(any("does not match pinned" in problem for problem in problems), problems)

    def test_a_different_api_level_is_refused(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        receipt["api_level"] = 27
        receipt["observed"]["target_triple"] = "aarch64-linux-android27"
        problems = ndk_tool.validate_receipt(receipt, archive, **CELL)
        self.assertTrue(any("api_level 27 does not match pinned 26" in problem
                            for problem in problems), problems)

    def test_a_different_pkg_revision_suffix_is_refused(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        receipt["ndk"]["pkg_revision"] = "30.0.14904198-evil"
        problems = ndk_tool.validate_receipt(receipt, archive, **CELL)
        self.assertTrue(any("pkg_revision" in problem and "pinned values" in problem
                            for problem in problems), problems)

    def test_a_compiler_target_for_another_abi_is_refused(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        receipt["compiler"]["target_triple"] = "x86_64-unknown-linux-android26"
        problems = ndk_tool.validate_receipt(receipt, archive, **CELL)
        self.assertTrue(any("compiler.target_triple" in problem for problem in problems), problems)

    def test_a_receipt_bound_to_other_bytes_is_refused(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        other = self.tmp / "other.zip"
        fixtures.write_zip(other, [("build/android-gpu/lib/Release/libskia.a",
                                    fixtures.gnu_ar([("b.o", ELF(183))]))])
        self.assertTrue(ndk_tool.validate_receipt(receipt, other, **CELL))

    def test_the_content_addressed_copy_checks_and_tamper_fails(self):
        archive = self.archive()
        data = ndk_tool.apple.canonical_bytes(self.receipt(archive))
        staged = self.tmp / ndk_tool.content_addressed_name(archive.name, data)
        staged.write_bytes(data)
        self.assertEqual(ndk_tool.main([str(staged), "--archive", str(archive), "--check", *CELL_ARGS]), 0)
        staged.write_bytes(data.replace(b"210000", b"210001", 1))
        self.assertEqual(ndk_tool.main([str(staged), "--archive", str(archive), "--check", *CELL_ARGS]), 1)

    def staged(self, archive, receipt):
        data = ndk_tool.apple.canonical_bytes(receipt)
        path = self.tmp / ndk_tool.content_addressed_name(archive.name, data)
        path.write_bytes(data)
        return path

    def test_check_requires_the_expected_cell(self):
        archive = self.archive()
        staged = self.staged(archive, self.receipt(archive))
        for missing in ("--abi", "--configuration", "--variant"):
            index = CELL_ARGS.index(missing)
            with self.subTest(missing=missing), self.assertRaises(SystemExit):
                ndk_tool.main([str(staged), "--archive", str(archive), "--check",
                               *CELL_ARGS[:index], *CELL_ARGS[index + 2:]])
        with self.assertRaises(SystemExit):
            ndk_tool.main([str(staged), "--check", *CELL_ARGS])

    def test_a_receipt_rehashed_to_claim_another_cell_is_refused(self):
        archive = self.archive()
        for key, value in (("platform", "linux"), ("architectures", ["x86_64"]),
                           ("configuration", "Debug"), ("variant", "cpu")):
            receipt = self.receipt(archive)
            receipt["target"][key] = value
            with self.subTest(key=key):
                self.assertTrue(any(f"target.{key}" in p for p in
                                    ndk_tool.validate_receipt(receipt, archive, **CELL)))
                self.assertEqual(ndk_tool.main([str(self.staged(archive, receipt)), "--archive",
                                                str(archive), "--check", *CELL_ARGS]), 1)
        # Flags that agree with a rewritten receipt still have to match the archive's name.
        receipt = self.receipt(archive)
        receipt["target"]["configuration"] = "Debug"
        problems = ndk_tool.validate_receipt(receipt, archive, **dict(CELL, configuration="Debug"))
        self.assertTrue(any(p.startswith("target.configuration") for p in problems), problems)

    def test_measurements_are_required_and_compared(self):
        archive = self.archive()
        tampers = {
            "observed_elf": lambda r: r.pop("observed_elf"),
            "elf_machines": lambda r: r["observed"].__setitem__("elf_machines", ["x64"]),
            "archive name": lambda r: r["archive"].__setitem__("name", "other.zip"),
            "triple api level": lambda r: r.__setitem__("api_level", 21),
        }
        for label, tamper in tampers.items():
            receipt = self.receipt(archive)
            tamper(receipt)
            with self.subTest(field=label):
                self.assertTrue(ndk_tool.validate_receipt(receipt, archive, **CELL), label)
                self.assertEqual(ndk_tool.main([str(self.staged(archive, receipt)), "--archive",
                                                str(archive), "--check", *CELL_ARGS]), 1)

    def test_check_requires_the_exact_content_addressed_name(self):
        archive = self.archive()
        plain = self.tmp / "ndk-toolchain.json"
        plain.write_bytes(ndk_tool.apple.canonical_bytes(self.receipt(archive)))
        self.assertEqual(ndk_tool.main([str(plain), "--archive", str(archive), "--check", *CELL_ARGS]), 1)


if __name__ == "__main__":
    unittest.main()
