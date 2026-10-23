#!/usr/bin/env python3
"""Tests for the Apple archive reader, legal manifest, toolchain receipt and archive comparison."""
import importlib.util
import json
import os
import pathlib
import shutil
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
    # dataclasses resolve string annotations through sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


apple_archive = load("apple_archive")
manifest_tool = load("write_legal_manifest")
receipt_tool = load("write_apple_toolchain_receipt")
compare_tool = load("compare_archive_members")


# ------------------------------------------------------------ fixtures ----

def macho(text: bytes, sdk=(15, 5), minos=(13, 0), cputype=0x0100000C, data: bytes = b"") -> bytes:
    """A minimal MH_OBJECT with __TEXT,__text, __DATA,__const and LC_BUILD_VERSION."""
    sections = [(b"__text", b"__TEXT", text), (b"__const", b"__DATA", data)]
    seg_size = 72 + 80 * len(sections)
    build_size = 24
    header = 32
    payload_offset = header + seg_size + build_size
    seg = struct.pack("<II16sQQQQiiII", 0x19, seg_size, b"", 0, 0, 0, 0, 7, 7, len(sections), 0)
    payload = b""
    for sectname, segname, content in sections:
        seg += struct.pack("<16s16sQQIIIIIIII", sectname, segname, 0, len(content),
                           payload_offset + len(payload), 0, 0, 0, 0, 0, 0, 0)
        payload += content
    build = struct.pack("<IIIIII", 0x32, build_size, 1, (minos[0] << 16) | (minos[1] << 8),
                        (sdk[0] << 16) | (sdk[1] << 8), 0)
    head = struct.pack("<IiIIIIII", 0xFEEDFACF, cputype, 0, 1, 2, seg_size + build_size, 0, 0)
    return head + seg + build + payload


def bsd_ar(members, date=1_700_000_000, pad8=True) -> bytes:
    out = bytearray(apple_archive.AR_MAGIC)
    for name, data in members:
        encoded = name.encode()
        name_len = (len(encoded) + 8) & ~7 if pad8 else len(encoded)
        body = encoded.ljust(name_len, b"\0") + data
        if pad8 and len(body) % 8:
            body += b"\0" * (8 - len(body) % 8)
        out += f"#1/{name_len}".ljust(16).encode() + str(date).ljust(12).encode()
        out += b"501   20    100644  " + str(len(body)).ljust(10).encode() + b"`\n" + body
        if len(body) & 1:
            out += b"\n"
    return bytes(out)


def gnu_ar(members) -> bytes:
    names = b"".join(name.encode() + b"/\n" for name, _ in members)
    out = bytearray(apple_archive.AR_MAGIC)
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


def fat(*slices) -> bytes:
    header = struct.pack(">II", 0xCAFEBABE, len(slices))
    offset = 4096
    table, body = b"", b""
    for cputype, data in slices:
        table += struct.pack(">iiIII", cputype, 0, offset + len(body), len(data), 12)
        body += data + b"\0" * ((-len(data)) % 4096)
    return (header + table).ljust(offset, b"\0") + body


def write_zip(path, entries, date=(2026, 8, 18, 4, 0, 0)):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as handle:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=date)
            handle.writestr(info, data)


# ------------------------------------------------------- apple_archive ----

class AppleArchiveTests(unittest.TestCase):
    def test_bsd_archive_with_long_names_and_libtool_padding(self):
        obj = macho(b"\x01\x02\x03")
        archive = apple_archive.parse_archive(bsd_ar([("__.SYMDEF SORTED", b"\0" * 8),
                                                      ("libskia.SkCamera.o", obj),
                                                      ("dup.o", b"a"), ("dup.o", b"b")]))
        self.assertEqual([m.name for m in archive.members], ["libskia.SkCamera.o", "dup.o", "dup.o"])
        self.assertEqual(len(archive.symbol_tables), 1)
        # libtool padding is inside ar_size; the padded bytes still match the object.
        self.assertNotEqual(archive.members[0].data, obj)
        self.assertIn(obj, apple_archive.unpadded_candidates(archive.members[0].data))
        self.assertEqual(archive.members[0].date, 1_700_000_000)
        self.assertEqual((archive.members[0].uid, archive.members[0].gid), (501, 20))

    def test_gnu_archive_long_name_table(self):
        archive = apple_archive.parse_archive(gnu_ar([("a_very_long_object_name.o", b"xyz"),
                                                      ("b.o", b"12")]))
        self.assertEqual([(m.name, m.data) for m in archive.members],
                         [("a_very_long_object_name.o", b"xyz"), ("b.o", b"12")])

    def test_fat_slices_and_build_version(self):
        arm = bsd_ar([("a.o", macho(b"arm"))])
        x86 = bsd_ar([("a.o", macho(b"x86", cputype=0x01000007))])
        pieces = apple_archive.slices(fat((0x0100000C, arm), (0x01000007, x86)))
        self.assertEqual([p.arch for p in pieces], ["arm64", "x86_64"])
        self.assertEqual(pieces[0].data, arm)
        parsed = apple_archive.parse_macho(apple_archive.parse_archive(pieces[1].data).members[0].data)
        self.assertEqual((parsed.arch, parsed.platform, parsed.minos, parsed.sdk),
                         ("x86_64", "macos", "13.0", "15.5"))
        self.assertEqual({(s.segment, s.name) for s in parsed.sections},
                         {("__TEXT", "__text"), ("__DATA", "__const")})

    def test_thin_archive_is_one_slice(self):
        data = bsd_ar([("a.o", macho(b"arm"))])
        self.assertEqual([(p.arch, p.data) for p in apple_archive.slices(data)], [("arm64", data)])

    def test_unpadded_candidates_never_strip_real_bytes(self):
        self.assertEqual(apple_archive.unpadded_candidates(b"abc"), [b"abc"])
        self.assertEqual(apple_archive.unpadded_candidates(b"ab\0\0"), [b"ab\0\0", b"ab\0", b"ab"])


# ------------------------------------------------------ legal manifest ----

def have_native_build() -> str | None:
    if not shutil.which("ninja"):
        return "ninja is not installed"
    if not (shutil.which("cc") and shutil.which("ar")):
        return "a C compiler and ar are required"
    return None


class LegalManifestTests(unittest.TestCase):
    """Build a tiny GN-shaped tree with real ninja, then inventory its archive."""

    def setUp(self):
        reason = have_native_build()
        if reason:
            self.skipTest(f"native build fixture unavailable: {reason}")
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="legal-manifest-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        src = self.tmp / "src" / "skia"
        (src / "include").mkdir(parents=True)
        (src / "third_party" / "externals" / "zlib").mkdir(parents=True)
        (src / "LICENSE").write_text("Skia BSD\n")
        (src / "third_party" / "externals" / "zlib" / "LICENSE").write_text("zlib license\n")
        (src / "include" / "core.h").write_text("int core(void);\n")
        (src / "core.c").write_text('#include "include/core.h"\nint core(void) { return 1; }\n')
        (src / "third_party" / "externals" / "zlib" / "inflate.c").write_text(
            "int inflate_it(void) { return 2; }\n")
        self.src = src
        self.out = self.tmp / "tmp" / "skia" / "mac_Release_arm64_gpu"
        self.out.mkdir(parents=True)
        (self.out / "build.ninja").write_text(
            "rule cc\n"
            "  command = cc -MMD -MF $out.d -I../../../src/skia -c $in -o $out\n"
            "  depfile = $out.d\n  deps = gcc\n"
            "rule alink\n  command = rm -f $out && ar rcs $out $in\n"
            "build obj/core.o: cc ../../../src/skia/core.c\n"
            "build obj/inflate.o: cc ../../../src/skia/third_party/externals/zlib/inflate.c\n"
            "build libskia.a: alink obj/core.o obj/inflate.o\n")
        subprocess.run(["ninja", "-C", str(self.out)], check=True, capture_output=True)
        self.builder = self.tmp / "builder"
        self.builder.mkdir()
        (self.builder / "LICENSE").write_text("MIT builder\n")

    def package(self, extra=()):
        archive = self.tmp / "skia-build-mac-arm64-gpu-release.zip"
        entries = [("build/include/core.h", (self.src / "include" / "core.h").read_bytes()),
                   ("build/mac-gpu/lib/Release/libskia.a", (self.out / "libskia.a").read_bytes()),
                   ("build/mac-gpu/lib/gn_args.txt", b"summary\n"), *extra]
        write_zip(archive, entries)
        return archive

    def manifest(self, archive):
        graph = manifest_tool.BuildGraph(self.src, {"arm64": self.out}, "ninja",
                                         builder_root=self.builder,
                                         toolchain_roots=manifest_tool.default_toolchain_roots())
        return manifest_tool.build_manifest(archive, graph, {"platform": "mac"}, gn=None)

    def test_exhaustive_inventory_resolves_every_member_to_a_license(self):
        archive = self.package()
        manifest = self.manifest(archive)
        self.assertEqual(manifest["gaps"], [])
        self.assertTrue(manifest["exhaustive"])
        library = manifest["static_archives"]["build/mac-gpu/lib/Release/libskia.a"]
        members = {m["name"]: m for piece in library["slices"].values() for m in piece["members"]}
        self.assertEqual(members["core.o"]["licenses"], ["source:LICENSE"])
        self.assertEqual(members["inflate.o"]["licenses"], ["source:third_party/externals/zlib/LICENSE"])
        self.assertEqual(sorted(library["licenses"]),
                         ["source:LICENSE", "source:third_party/externals/zlib/LICENSE"])
        # The header the object includes is a transitive source of core.o.
        self.assertIn("source:include/core.h", manifest["files"])
        header = next(r for r in manifest["zip_members"] if r["name"] == "build/include/core.h")
        self.assertEqual(header["origin"], "source:include/core.h")
        metadata = next(r for r in manifest["zip_members"] if r["name"].endswith("gn_args.txt"))
        self.assertEqual(metadata["licenses"], ["builder:LICENSE"])
        self.assertEqual(manifest_tool.validate_manifest(manifest, archive), [])
        # No timestamps: the same inputs give the same bytes.
        self.assertEqual(manifest_tool.canonical_bytes(manifest),
                         manifest_tool.canonical_bytes(self.manifest(archive)))

    def test_member_not_built_by_ninja_is_a_gap(self):
        # Control for the test above: a member whose bytes no build output
        # produced must not be silently attributed.
        foreign = self.tmp / "foreign.o"
        (self.tmp / "foreign.c").write_text("int foreign(void) { return 3; }\n")
        subprocess.run(["cc", "-c", str(self.tmp / "foreign.c"), "-o", str(foreign)], check=True)
        subprocess.run(["ar", "rs", str(self.out / "libskia.a"), str(foreign)], check=True,
                       capture_output=True)
        archive = self.package()
        manifest = self.manifest(archive)
        self.assertFalse(manifest["exhaustive"])
        self.assertIn("object-member-unmatched", {gap["kind"] for gap in manifest["gaps"]})
        self.assertTrue(manifest_tool.validate_manifest(manifest, archive))

    def test_source_without_any_license_is_a_gap(self):
        (self.src / "LICENSE").unlink()
        manifest = self.manifest(self.package())
        self.assertIn({"kind": "source-without-license", "path": "source:core.c"}, manifest["gaps"])

    def test_packaged_file_with_unknown_origin_is_a_gap(self):
        manifest = self.manifest(self.package(extra=[("build/include/stray.h", b"not from the tree\n")]))
        self.assertIn({"kind": "packaged-file-unmatched", "path": "build/include/stray.h"}, manifest["gaps"])

    def test_check_rejects_a_manifest_for_different_bytes(self):
        archive = self.package()
        manifest = self.manifest(archive)
        manifest["zip_members"][0]["sha256"] = "0" * 64
        self.assertTrue(any("not listed with its digest" in p
                            for p in manifest_tool.validate_manifest(manifest, archive)))

    def test_cli_publishes_content_addressed_copy_only_when_exhaustive(self):
        archive = self.package()
        out = self.tmp / "manifest.json"
        published = self.tmp / "assets"
        args = [str(out), "--archive", str(archive), "--source-root", str(self.src),
                "--out-dir", f"arm64={self.out}", "--builder-root", str(self.builder),
                "--content-addressed-dir", str(published)]
        self.assertEqual(manifest_tool.main(args), 0)
        [asset] = list(published.iterdir())
        self.assertRegex(asset.name, manifest_tool.CONTENT_ADDRESSED_RE)
        self.assertEqual(asset.read_bytes(), out.read_bytes())
        self.assertEqual(manifest_tool.main([str(asset), "--archive", str(archive), "--check"]), 0)
        # A content-addressed name that no longer matches its bytes is refused.
        renamed = published / asset.name.replace(asset.name[-69:-5], "f" * 64)
        asset.rename(renamed)
        self.assertEqual(manifest_tool.main([str(renamed), "--archive", str(archive), "--check"]), 1)

        shutil.rmtree(published)
        (self.src / "LICENSE").unlink()
        self.assertEqual(manifest_tool.main(args), 1)
        self.assertFalse(published.exists() and any(published.iterdir()))


class NinjaParserTests(unittest.TestCase):
    def test_deps_and_compdb_parsing(self):
        deps = manifest_tool.parse_ninja_deps(
            "obj/a.o: #deps 2, deps mtime 1 (VALID)\n    ../../a.c\n    ../../a.h\n\n"
            "obj/b.o: #deps 1, deps mtime 1 (STALE)\n    ../../b.c\n\n")
        self.assertEqual(deps, {"obj/a.o": ["../../a.c", "../../a.h"], "obj/b.o": ["../../b.c"]})
        compdb = manifest_tool.parse_compdb(json.dumps([
            {"directory": "/out", "file": "../src/a.c", "output": "obj/a.o", "command": "cc"}]))
        self.assertEqual(compdb, {"/out/obj/a.o": ["/src/a.c"]})


# ---------------------------------------------------- toolchain receipt ----

XCODE = "/Applications/Xcode_16.4.app/Contents/Developer"
BIN = f"{XCODE}/Toolchains/XcodeDefault.xctoolchain/usr/bin"
SDK_PATH = f"{XCODE}/Platforms/MacOSX.platform/Developer/SDKs/MacOSX15.5.sdk"


def fake_runner(sdk_version="15.5", clang_banner="Apple clang version 17.0.0 (clang-1700.0.13.5)"):
    outputs = {
        ("xcrun", "--sdk", "macosx", "--show-sdk-path"): SDK_PATH,
        ("xcrun", "--sdk", "macosx", "--show-sdk-version"): sdk_version,
        ("xcrun", "--sdk", "macosx", "--show-sdk-build-version"): "24F74",
        ("sw_vers", "-productVersion"): "15.6",
        ("sw_vers", "-buildVersion"): "24G84",
        ("xcode-select", "-p"): XCODE,
        ("xcodebuild", "-version"): "Xcode 16.4\nBuild version 16F6",
        (f"{BIN}/clang", "--version"): clang_banner,
        (f"{BIN}/clang++", "--version"): clang_banner,
        (f"{BIN}/ld", "-v"): "",
        (f"{BIN}/libtool", "-V"): "Apple Inc. version cctools-1010.6",
    }

    def runner(args, stdin=None):
        key = tuple(args)
        if args[:4] == ["xcrun", "--sdk", "macosx", "--find"]:
            return subprocess.CompletedProcess(args, 0, f"{BIN}/{args[4]}\n", "")
        if args[0].endswith("clang++") and "-E" in args:
            return subprocess.CompletedProcess(
                args, 0, "LIBCPP_VERSION=190102\nLIBCPP_ABI_VERSION=1\nLIBCPP_ABI_NAMESPACE=__1\n", "")
        if key == (f"{BIN}/ld", "-v"):
            return subprocess.CompletedProcess(args, 0, "", "@(#)PROGRAM:ld PROJECT:ld-1167.5\n")
        if key in outputs:
            return subprocess.CompletedProcess(args, 0, outputs[key] + "\n", "")
        return subprocess.CompletedProcess(args, 1, "", "unexpected")
    return runner


class ToolchainReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="apple-receipt-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ninja = self.tmp / "toolchain.ninja"
        self.ninja.write_text("rule cxx\n  command = ccache clang++ -MD -MF ${out}.d $cflags -c $in -o $out\n"
                              "rule alink\n  command = rm -f $out && libtool -static -o $out $in\n")
        lib = fat((0x0100000C, bsd_ar([("a.o", macho(b"arm"))])),
                  (0x01000007, bsd_ar([("a.o", macho(b"x86", cputype=0x01000007))])))
        self.archive = self.tmp / "skia-build-mac-universal-gpu-release.zip"
        write_zip(self.archive, [("build/mac-gpu/lib/Release/libskia.a", lib)])

    def receipt(self, **runner_args):
        probe = receipt_tool.Probe(runner=fake_runner(**runner_args), which=lambda name: f"/usr/bin/{name}",
                                   hasher=lambda path: "a" * 64, realpath=lambda path: path)
        return receipt_tool.build_receipt("mac", ["x86_64", "arm64"], "Release", "gpu", "13.0",
                                          [self.ninja], self.archive, probe=probe)

    def test_receipt_records_toolchain_and_matches_every_object(self):
        receipt = self.receipt()
        self.assertEqual(receipt_tool.validate_receipt(receipt, self.archive), [])
        self.assertEqual(receipt["xcode"]["version"], "Xcode 16.4 Build version 16F6")
        self.assertEqual(receipt["compiler"]["cxx"]["path"], f"{BIN}/clang++")
        self.assertEqual(receipt["linker"]["version"], "@(#)PROGRAM:ld PROJECT:ld-1167.5")
        self.assertEqual(receipt["cpp_abi"]["arm64"]["libcpp_abi_version"], "1")
        self.assertEqual(receipt["observed_macho"]["sdk_versions"], ["15.5"])
        commands = receipt["compiler"]["gn_toolchain_commands"][str(self.ninja)]
        self.assertTrue(commands["cxx"].startswith("ccache clang++"))

    def test_receipt_for_a_different_sdk_than_the_objects_is_refused(self):
        # Negative control: the same objects, described by a toolchain whose
        # SDK is not the one they were compiled against.
        problems = receipt_tool.validate_receipt(self.receipt(sdk_version="26.0"), self.archive)
        self.assertTrue(any("built against SDK(s) ['15.5']" in p for p in problems), problems)

    def test_unknown_compiler_banner_is_refused(self):
        problems = receipt_tool.validate_receipt(self.receipt(clang_banner="error: exit 1"))
        self.assertTrue(any("compiler.c.version" in p for p in problems), problems)

    def test_receipt_bound_to_other_archive_bytes_is_refused(self):
        receipt = self.receipt()
        other = self.tmp / "other.zip"
        write_zip(other, [("build/mac-gpu/lib/Release/libskia.a", bsd_ar([("a.o", macho(b"zzz"))]))])
        self.assertTrue(receipt_tool.validate_receipt(receipt, other))


# ---------------------------------------------------------- comparison ----

class CompareArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="compare-archives-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def zip_with(self, name, objects, ar_date=1, zip_date=(2026, 8, 18, 4, 0, 0)):
        path = self.tmp / name
        write_zip(path, [("build/include/a.h", b"header\n"),
                         ("build/mac-gpu/lib/Release/libskia.a", bsd_ar(objects, date=ar_date))],
                  date=zip_date)
        return path

    def test_identical_files(self):
        a = self.zip_with("a.zip", [("x.o", macho(b"code"))])
        self.assertEqual(compare_tool.compare(a, a)["verdict"], compare_tool.IDENTICAL)

    def test_timestamps_only_is_metadata_only(self):
        a = self.zip_with("a.zip", [("x.o", macho(b"code"))], ar_date=1)
        b = self.zip_with("b.zip", [("x.o", macho(b"code"))], ar_date=2, zip_date=(2026, 10, 22, 1, 0, 0))
        report = compare_tool.compare(a, b)
        self.assertEqual(report["verdict"], compare_tool.METADATA_ONLY)
        piece = report["static_archives"]["build/mac-gpu/lib/Release/libskia.a"]["slices"]["arm64"]
        self.assertEqual(piece["header_only_differences"], {"date": 1})
        self.assertTrue(any("member dates differ" in cause for cause in report["causes"]))
        self.assertTrue(any("zip entry timestamps" in cause for cause in report["causes"]))

    def test_machine_code_difference_names_the_section_and_sdk(self):
        a = self.zip_with("a.zip", [("x.o", macho(b"code")), ("y.o", macho(b"same"))])
        b = self.zip_with("b.zip", [("x.o", macho(b"CODE", sdk=(26, 0))), ("y.o", macho(b"same"))])
        report = compare_tool.compare(a, b)
        self.assertEqual(report["verdict"], compare_tool.CODE_DIFFERS)
        piece = report["static_archives"]["build/mac-gpu/lib/Release/libskia.a"]["slices"]["arm64"]
        self.assertEqual((piece["identical_content"], piece["differing_content"]), (1, 1))
        self.assertIn("__TEXT,__text", piece["examples"][0]["sections"])
        self.assertTrue(any("different SDKs" in cause for cause in report["causes"]))

    def test_data_only_difference_is_reported_as_such(self):
        a = self.zip_with("a.zip", [("x.o", macho(b"code", data=b"/Users/runner/a"))])
        b = self.zip_with("b.zip", [("x.o", macho(b"code", data=b"/Users/runner/b"))])
        report = compare_tool.compare(a, b)
        piece = report["static_archives"]["build/mac-gpu/lib/Release/libskia.a"]["slices"]["arm64"]
        self.assertEqual(piece["examples"][0]["sections"], ["__DATA,__const"])
        self.assertTrue(any("only data sections differ" in cause for cause in report["causes"]))


if __name__ == "__main__":
    unittest.main()
