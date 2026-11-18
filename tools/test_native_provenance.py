#!/usr/bin/env python3
"""Tests for the Linux and Windows provenance records and the non-Mach-O archive reader."""
import importlib.util
import json
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


apple_archive = load("apple_archive")
manifest_tool = load("write_legal_manifest")
linux_tool = load("write_linux_toolchain_receipt")
stage_tool = load("stage_windows_receipt")

CELL = {"arch": "x64", "configuration": "Release", "variant": "gpu"}
CELL_ARGS = ["--arch", "x64", "--configuration", "Release", "--variant", "gpu"]
CLANG = "clang version 20.1.0 (https://github.com/llvm/llvm-project 24a30daaa559829ad079f2ff7f73eb4e18095f88)"


def elf(machine=62, comments=(CLANG,)):
    """A minimal little-endian ELF64 relocatable with a .comment section."""
    comment = b"".join(text.encode() + b"\0" for text in comments)
    names = b"\0.comment\0.shstrtab\0"
    body = 64
    comment_offset = body
    names_offset = comment_offset + len(comment)
    shoff = names_offset + len(names)

    def section(name, offset, size, kind):
        return struct.pack("<IIQQQQIIQQ", name, kind, 0, 0, offset, size, 0, 0, 1, 0)

    sections = (b"\0" * 64 + section(1, comment_offset, len(comment), 1)
                + section(10, names_offset, len(names), 3))
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    header = ident + struct.pack("<HHIQQQIHHHHHH", 1, machine, 1, 0, 0, shoff, 0, 64, 0, 0, 64, 3, 2)
    assert len(header) == 64
    return header + comment + names + sections


def coff(machine):
    return struct.pack("<HHIIIHH", machine, 0, 0, 0, 0, 0, 0)


def bigobj(machine):
    return struct.pack("<HHHHH", 0, 0xFFFF, 2, machine, 0) + b"\0" * 20


def gnu_ar(members, extra_names=()):
    names = b"".join(name.encode() + b"/\n" for name, _ in members)
    out = bytearray(apple_archive.AR_MAGIC)
    for special, body in [(b"/", b"\0\0\0\0"), *[(name.encode(), b"\0\0\0\0") for name in extra_names]]:
        out += special.ljust(16) + b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6) + b"0".ljust(8)
        out += str(len(body)).ljust(10).encode() + b"`\n" + body
    out += b"//".ljust(16) + b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6) + b"0".ljust(8)
    out += str(len(names)).ljust(10).encode() + b"`\n" + names + (b"\n" if len(names) & 1 else b"")
    offset = 0
    for name, data in members:
        out += f"/{offset}".ljust(16).encode() + b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6)
        out += b"644".ljust(8) + str(len(data)).ljust(10).encode() + b"`\n" + data
        if len(data) & 1:
            out += b"\n"
        offset += len(name) + 2
    return bytes(out)


def write_zip(path, entries):
    with zipfile.ZipFile(path, "w") as handle:
        for name, data in entries:
            handle.writestr(zipfile.ZipInfo(name, date_time=(2026, 11, 16, 0, 0, 0)), data)


class ObjectArchTests(unittest.TestCase):
    def test_elf_machines(self):
        self.assertEqual(apple_archive.object_arch(elf(62)), "x64")
        self.assertEqual(apple_archive.object_arch(elf(183)), "arm64")
        self.assertIsNone(apple_archive.object_arch(elf(40)))

    def test_coff_machines_including_arm64ec_and_bigobj(self):
        self.assertEqual(apple_archive.object_arch(coff(0x8664)), "x64")
        self.assertEqual(apple_archive.object_arch(coff(0xAA64)), "arm64")
        self.assertEqual(apple_archive.object_arch(coff(0xA641)), "arm64ec")
        self.assertEqual(apple_archive.object_arch(bigobj(0x8664)), "x64")

    def test_wasm_and_text_are_distinguished(self):
        self.assertEqual(apple_archive.object_arch(b"\0asm\x01\0\0\0" + b"\0" * 16), "wasm32")
        self.assertIsNone(apple_archive.object_arch(b"GN args summary, nothing binary here\n"))

    def test_a_gnu_archive_names_its_slice_after_the_object_machine(self):
        data = gnu_ar([("core.o", elf(183))])
        self.assertEqual(apple_archive.slices(data)[0].arch, "arm64")

    def test_arm64ec_symbol_table_is_not_an_object_member(self):
        data = gnu_ar([("core.obj", coff(0xA641))], extra_names=["/<ECSYMBOLS>/"])
        parsed = apple_archive.parse_archive(data)
        self.assertEqual([member.name for member in parsed.members], ["core.obj"])
        self.assertEqual(len(parsed.symbol_tables), 2)


class LinuxReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="linux-receipt-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.os_release = self.tmp / "os-release"
        self.os_release.write_text('PRETTY_NAME="Ubuntu 22.04.5 LTS"\n')
        self.ninja = self.tmp / "toolchain.ninja"
        self.ninja.write_text("rule cc\n  command = ccache clang -c $in -o $out\n"
                              "rule cxx\n  command = ccache clang++ -c $in -o $out\n")

    def archive(self, machine=62, comments=(CLANG,)):
        path = self.tmp / "skia-build-linux-x64-gpu-release.zip"
        write_zip(path, [("build/linux-gpu/lib/libskia.a", gnu_ar([("a.o", elf(machine, comments))])),
                         ("build/linux-gpu/lib/libdawn_combined.a",
                          gnu_ar([("d.o", elf(machine, comments))])),
                         ("build/include/core.h", b"int core(void);\n")])
        return path

    def runner(self, clang=CLANG, glibc="ldd (Ubuntu GLIBC 2.35-0ubuntu3.8) 2.35"):
        def run(args, stdin=None):
            program = pathlib.Path(args[0]).name
            out = {"clang": clang, "clang++": clang, "ar": "GNU ar (GNU Binutils for Ubuntu) 2.38",
                   "ld": "GNU ld (GNU Binutils for Ubuntu) 2.38", "ldd": glibc,
                   "ccache": "ccache version 4.5.1"}.get(program, "")
            if program == "objdump":
                out = "00 g DF .text GLIBC_2.17 memcpy\n00 g DF .text GLIBC_2.34 x\n00 DO GLIBCXX_3.4.29 y\n"
            if args[-1] == "-dumpmachine":
                out = "x86_64-unknown-linux-gnu"
            if "-E" in args:
                out = "GLIBCXX_RELEASE=11\n"
            return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
        return run

    def receipt(self, archive, **kwargs):
        probe = linux_tool.apple.Probe(runner=self.runner(**kwargs),
                                       which=lambda name: f"/opt/llvm/bin/{name}" if name in ("clang", "clang++", "ccache") else f"/usr/bin/{name}",
                                       hasher=lambda path: "ab" * 32, realpath=lambda path: path)
        return linux_tool.build_receipt("x64", "Release", "gpu", [self.ninja], archive, probe=probe,
                                        container_image="ubuntu@sha256:" + "0" * 64,
                                        link_probe_enabled=True,
                                        os_release_path=self.os_release)

    def test_a_receipt_matching_its_archive_is_proven(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        self.assertEqual(linux_tool.validate_receipt(receipt, archive, **CELL), [])
        self.assertEqual(receipt["cpp_abi"]["x64"], {"stdlib": "libstdc++", "stdlib_version": "11",
                                                      "glibcxx_release": "11"})
        self.assertEqual(receipt["observed"]["max_glibc_version"], "2.34")
        self.assertEqual(receipt["observed"]["max_glibcxx_version"], "3.4.29")
        self.assertEqual(receipt["compiler"]["cxx"]["vendor"], "clang")
        self.assertEqual(receipt["libc"]["version"], "2.35")
        self.assertEqual(receipt["observed_elf"]["machines"], {"x64": 2})

    def test_objects_built_by_another_clang_are_refused(self):
        archive = self.archive(comments=("clang version 19.1.0 (x)",))
        problems = linux_tool.validate_receipt(self.receipt(archive), archive, **CELL)
        self.assertTrue(any("built by clang" in problem for problem in problems), problems)

    def test_an_object_for_another_architecture_is_refused(self):
        archive = self.archive(machine=183)
        problems = linux_tool.validate_receipt(self.receipt(archive), archive, **CELL)
        self.assertTrue(any("in a x64 cell" in problem for problem in problems), problems)

    def test_objects_needing_a_newer_glibc_than_the_producer_are_refused(self):
        archive = self.archive()
        problems = linux_tool.validate_receipt(self.receipt(archive, glibc="ldd (x) 2.31"), archive, **CELL)
        self.assertTrue(any("newer than the producer" in problem for problem in problems), problems)

    def test_a_failed_link_probe_reports_the_linker_error(self):
        archive = self.tmp / "skia-build-linux-x64-gpu-release.zip"
        fixtures_zip = [("build/linux-gpu/lib/libskia.a", gnu_ar([("a.o", elf())])),
                        ("build/linux-gpu/lib/libdawn_combined.a", gnu_ar([("d.o", elf())]))]
        write_zip(archive, fixtures_zip)
        def run(args, stdin=None):
            if args[0].endswith("clang++") or args[0] == "c++":
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="ld.lld: error: undefined x")
            return self.runner()(args, stdin)
        probe = linux_tool.apple.Probe(runner=run, which=lambda n: f"/usr/bin/{n}",
                                       hasher=lambda p: "ab" * 32, realpath=lambda p: p)
        self.assertIn("ld.lld: error", linux_tool.link_probe(archive, "/usr/bin/clang++", probe)["link_error"])

    def test_an_unmeasured_symbol_version_is_refused(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        del receipt["observed"]["max_glibcxx_version"]
        self.assertTrue(any("max_glibcxx_version" in p for p in linux_tool.validate_receipt(receipt, archive, **CELL)))

    def test_object_measurements_are_required_and_complete(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        receipt["observed_elf"]["members_not_elf"] = 1
        receipt["observed_elf"]["members_without_comment"] = 1
        receipt.pop("observed")
        receipt.pop("observed_elf")
        problems = linux_tool.validate_receipt(receipt, archive, **CELL)
        self.assertTrue(any("observed_elf is required" in p for p in problems), problems)
        self.assertTrue(any("observed link-probe data is required" in p for p in problems), problems)

    def test_non_elf_and_commentless_members_are_refused(self):
        archive = self.tmp / "skia-build-linux-x64-gpu-release.zip"
        write_zip(archive, [
            ("build/linux-gpu/lib/libskia.a", gnu_ar([("bad.o", b"not an elf")])),
            ("build/linux-gpu/lib/libdawn_combined.a", gnu_ar([("no-comment.o", elf(comments=()))])),
        ])
        receipt = self.receipt(archive)
        problems = linux_tool.validate_receipt(receipt, archive, **CELL)
        self.assertTrue(any("not ELF" in p for p in problems), problems)
        self.assertTrue(any("without .comment" in p for p in problems), problems)

    def test_an_unknown_compiler_banner_is_refused(self):
        archive = self.archive()
        problems = linux_tool.validate_receipt(self.receipt(archive, clang="error: exit 1"), archive, **CELL)
        self.assertTrue(problems)

    def test_a_receipt_bound_to_other_archive_bytes_is_refused(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        other = self.tmp / "other.zip"
        write_zip(other, [("build/linux-gpu/lib/libskia.a", gnu_ar([("b.o", elf())]))])
        self.assertTrue(linux_tool.validate_receipt(receipt, other, **CELL))

    def test_the_compiler_is_found_past_a_ccache_wrapper(self):
        self.assertEqual(linux_tool.compiler_program("ccache clang++ -c a.cc"), "clang++")
        self.assertEqual(linux_tool.compiler_program("CCACHE_DISABLE=1 ccache /opt/llvm/bin/clang -c"),
                         "/opt/llvm/bin/clang")

    def test_cli_writes_a_content_addressed_copy_that_checks(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        data = linux_tool.apple.canonical_bytes(receipt)
        name = linux_tool.content_addressed_name(archive.name, data)
        staged = self.tmp / name
        staged.write_bytes(data)
        self.assertEqual(linux_tool.main([str(staged), "--archive", str(archive), "--check", *CELL_ARGS]), 0)
        staged.write_bytes(data.replace(b"2.35", b"2.36", 1))
        self.assertEqual(linux_tool.main([str(staged), "--archive", str(archive), "--check", *CELL_ARGS]), 1)

    def test_cli_rejects_a_non_content_addressed_filename(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        staged = self.tmp / "linux-toolchain.json"
        staged.write_bytes(linux_tool.apple.canonical_bytes(receipt))
        self.assertEqual(linux_tool.main([str(staged), "--archive", str(archive), "--check", *CELL_ARGS]), 1)

    def staged(self, archive, receipt):
        data = linux_tool.apple.canonical_bytes(receipt)
        path = self.tmp / linux_tool.content_addressed_name(archive.name, data)
        path.write_bytes(data)
        return path

    def test_check_requires_the_expected_cell(self):
        archive = self.archive()
        staged = self.staged(archive, self.receipt(archive))
        for missing in ("--arch", "--configuration", "--variant"):
            index = CELL_ARGS.index(missing)
            args = CELL_ARGS[:index] + CELL_ARGS[index + 2:]
            with self.subTest(missing=missing), self.assertRaises(SystemExit):
                linux_tool.main([str(staged), "--archive", str(archive), "--check", *args])
        with self.assertRaises(SystemExit):
            linux_tool.main([str(staged), "--check", *CELL_ARGS])

    def test_a_receipt_rehashed_to_claim_another_cell_is_refused(self):
        archive = self.archive()
        for key, value in (("platform", "android"), ("configuration", "Debug"), ("variant", "cpu")):
            receipt = self.receipt(archive)
            receipt["target"][key] = value
            with self.subTest(key=key):
                self.assertTrue(any(f"target.{key}" in p
                                    for p in linux_tool.validate_receipt(receipt, archive, **CELL)))
                self.assertEqual(linux_tool.main([str(self.staged(archive, receipt)), "--archive",
                                                  str(archive), "--check", *CELL_ARGS]), 1)
        # The caller's expectation, not the receipt's claim, names the cell.
        problems = linux_tool.validate_receipt(self.receipt(archive), archive,
                                               **dict(CELL, arch="arm64"))
        self.assertTrue(any("target.architectures" in p for p in problems), problems)
        problems = linux_tool.validate_receipt(self.receipt(archive), archive,
                                               **dict(CELL, arch="riscv64"))
        self.assertTrue(any("not a Linux architecture" in p for p in problems), problems)

    def test_an_unknown_target_architecture_is_refused(self):
        archive = self.archive()
        receipt = self.receipt(archive)
        receipt["target"]["architectures"] = ["riscv64"]
        receipt["cpp_abi"] = {"riscv64": receipt["cpp_abi"]["x64"]}
        problems = linux_tool.validate_receipt(receipt, archive, **dict(CELL, arch="riscv64"))
        self.assertTrue(any("unknown architecture" in p for p in problems), problems)
        self.assertTrue(any("no known architecture to compare" in p for p in problems), problems)


class WindowsStagingTests(unittest.TestCase):
    CL = r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"

    def receipt(self, toolset="14.44.35207"):
        banner = "Microsoft (R) C/C++ Optimizing Compiler Version 19.44.35207 for x64"
        compiler = {"driver": "cl.exe", "path": self.CL, "version": banner, "source": "toolchain.ninja"}
        return {"schema_version": 1,
                "target": {"platform": "windows", "architecture": "x64", "configuration": "Release",
                           "variant": "gpu"},
                "producer": {"skia_gn_compiler": compiler, "dawn_cmake_compiler": compiler,
                             "msvc_toolset_version": toolset, "windows_sdk_version": "10.0.26100.0",
                             "visual_studio_vc_dir": "x", "host_architecture": "AMD64"},
                "runtime": {"abi": "msvc", "library": "static", "compile_flag": "/MT",
                            "consumer_requirement": f"MSVC STL/CRT toolset >= {toolset}"}}

    def archive(self, tmp, receipt, machine=0x8664):
        path = tmp / "skia-build-win-x64-gpu-release.zip"
        write_zip(path, [("build/win-gpu/msvc-toolchain.json", json.dumps(receipt, indent=2).encode()),
                         ("build/win-gpu/lib/Release/x64/skia.lib", gnu_ar([("a.obj", coff(machine))]))])
        return path

    def stage(self, archive, out):
        def banner(path):
            return ("Microsoft (R) Incremental Linker Version 14.44.35207.0" if path.endswith("link.exe")
                    else "Microsoft (R) Library Manager Version 14.44.35207.0")
        source = archive_receipt_bytes(archive)
        staged = stage_tool.derive(archive, json.loads(source), source, "x64", "Release", "gpu", banner=banner,
                                  hasher=lambda path: "cd" * 32)
        data = stage_tool.canonical_bytes(staged)
        out.mkdir(exist_ok=True)
        path = out / stage_tool.content_addressed_name(archive.name, data)
        path.write_bytes(data)
        return path, staged

    def check(self, archive, staged_path):
        return stage_tool.main(["--archive", str(archive), "--arch", "x64", "--configuration",
                                "Release", "--variant", "gpu", "--check", str(staged_path)])

    def test_stage_then_check_round_trips(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            archive = self.archive(tmp, self.receipt())
            path, staged = self.stage(archive, tmp / "assets")
            self.assertEqual(self.check(archive, path), 0)
            self.assertEqual(staged["observed"]["coff_machines"], {"x64": 1})
            self.assertEqual(staged["msvc_toolset"], {"version": "14.44.35207"})
            self.assertEqual(staged["cpp_abi"]["x64"]["stdlib"], "msvc-stl")

    def test_staged_receipt_for_another_archive_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            path, _ = self.stage(self.archive(tmp, self.receipt()), tmp / "assets")
            other = self.archive(tmp, self.receipt(), machine=0xAA64)
            self.assertEqual(self.check(other, path), 1)

    def test_an_object_for_another_architecture_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            archive = self.archive(tmp, self.receipt(), machine=0xAA64)
            path, _ = self.stage(archive, tmp / "assets")
            self.assertEqual(self.check(archive, path), 1)

    def test_unknown_members_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            receipt = self.receipt()
            archive = tmp / "skia-build-win-x64-gpu-release.zip"
            write_zip(archive, [
                ("build/win-gpu/msvc-toolchain.json", json.dumps(receipt, indent=2).encode()),
                ("build/win-gpu/lib/Release/x64/skia.lib",
                 gnu_ar([("a.obj", coff(0x8664)), ("unknown.obj", b"not coff")])),
            ])
            path, _ = self.stage(archive, tmp / "assets")
            self.assertEqual(self.check(archive, path), 1)

    def test_staged_target_must_match_requested_arch_and_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            archive = self.archive(tmp, self.receipt())
            _, staged = self.stage(archive, tmp / "assets")
            staged["target"]["architectures"] = ["arm64"]
            staged["target"]["configuration"] = "Debug"
            problems = stage_tool.problems_for(archive, staged, archive_receipt_bytes(archive),
                                                "x64", "Release", "gpu")
            self.assertTrue(any("target.architectures" in p for p in problems), problems)
            self.assertTrue(any("target.configuration" in p for p in problems), problems)

    def test_a_receipt_that_proves_nothing_is_not_staged(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            bad = self.receipt()
            bad["producer"]["windows_sdk_version"] = "unknown"
            archive = self.archive(tmp, bad)
            args = ["--archive", str(archive), "--arch", "x64", "--configuration", "Release",
                    "--variant", "gpu", "--out-dir", str(tmp / "assets")]
            self.assertEqual(stage_tool.main(args), 1)
            self.assertFalse((tmp / "assets").exists())

    def test_a_tampered_staged_copy_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            archive = self.archive(tmp, self.receipt())
            path, _ = self.stage(archive, tmp / "assets")
            path.write_bytes(path.read_bytes().replace(b"14.44.35207", b"14.44.35208", 1))
            self.assertEqual(self.check(archive, path), 1)

    def test_staged_receipt_must_claim_the_windows_cell(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            archive = self.archive(tmp, self.receipt())
            for key, value in (("platform", "linux"), ("variant", "cpu")):
                _, staged = self.stage(archive, tmp / "assets")
                staged["target"][key] = value
                problems = stage_tool.problems_for(archive, staged, archive_receipt_bytes(archive),
                                                    "x64", "Release", "gpu")
                self.assertTrue(any(f"target.{key}" in p for p in problems), (key, problems))
                data = stage_tool.canonical_bytes(staged)
                path = tmp / stage_tool.content_addressed_name(archive.name, data)
                path.write_bytes(data)
                self.assertEqual(self.check(archive, path), 1, key)

    def test_receipt_inside_the_archive_must_claim_the_windows_cell(self):
        for key, value in (("platform", "linux"), ("variant", "cpu"), ("architecture", "arm64")):
            with tempfile.TemporaryDirectory() as temporary:
                tmp = pathlib.Path(temporary)
                source = self.receipt()
                source["target"][key] = value
                archive = self.archive(tmp, source)
                path, staged = self.stage(archive, tmp / "assets")
                problems = stage_tool.problems_for(archive, staged, archive_receipt_bytes(archive),
                                                    "x64", "Release", "gpu")
                self.assertTrue(any(p.startswith("archive receipt: target.") for p in problems),
                                (key, problems))
                self.assertEqual(self.check(archive, path), 1, key)

    def test_an_unknown_expected_architecture_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            archive = self.archive(tmp, self.receipt())
            _, staged = self.stage(archive, tmp / "assets")
            problems = stage_tool.problems_for(archive, staged, archive_receipt_bytes(archive),
                                                "riscv64", "Release", "gpu")
            self.assertTrue(any("not a Windows architecture" in p for p in problems), problems)

    def test_a_staged_copy_named_for_another_archive_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            archive = self.archive(tmp, self.receipt())
            path, _ = self.stage(archive, tmp / "assets")
            renamed = path.with_name(path.name.replace("-x64-", "-arm64-"))
            path.rename(renamed)
            self.assertEqual(self.check(archive, renamed), 1)

    def test_check_requires_the_variant(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = pathlib.Path(temporary)
            archive = self.archive(tmp, self.receipt())
            path, _ = self.stage(archive, tmp / "assets")
            with self.assertRaises(SystemExit):
                stage_tool.main(["--archive", str(archive), "--arch", "x64", "--configuration",
                                 "Release", "--check", str(path)])


def archive_receipt_bytes(archive):
    return stage_tool.archive_receipt(archive)


class ToolchainRootTests(unittest.TestCase):
    def test_platform_defaults(self):
        self.assertIn(pathlib.Path("/usr"), manifest_tool.default_toolchain_roots("linux"))
        windows = [str(path).lower() for path in manifest_tool.default_toolchain_roots("win")]
        self.assertTrue(any("program files" in path for path in windows), windows)
        self.assertNotIn(pathlib.Path("/Library/Developer/CommandLineTools"),
                         manifest_tool.default_toolchain_roots("linux"))

    def test_msvc_receipt_is_builder_metadata_not_a_gap(self):
        self.assertIn("msvc-toolchain.json", manifest_tool.BUILDER_METADATA)


if __name__ == "__main__":
    unittest.main()
