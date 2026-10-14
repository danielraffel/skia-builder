#!/usr/bin/env python3
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("provenance", ROOT / "tools" / "write_windows_toolchain_provenance.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

# The receipt published in chrome/m153's skia-build-win-arm64-gpu-release.zip
# (sha256 18e57481...).  The writer ran outside a developer shell, so it
# recorded "unknown" toolsets and clang-cl's no-argument error as a version.
BROKEN_M153 = ROOT / "tools" / "testdata" / "chrome-m153-win-arm64-msvc-toolchain.json"

# What GitHub's windows-11-arm image actually used for that build (from the
# backfill run's CMake command line): Visual Studio 18, toolset 14.51.36231,
# SDK 10.0.26100.0, LLVM 20.1.0.
TOOLSET = "14.51.36231"
SDK = "10.0.26100.0"
CL_BANNER = "Microsoft (R) C/C++ Optimizing Compiler Version 19.51.36231 for ARM64"


def fake_run(args):
    exe = args[0].lower()
    if exe.endswith("vswhere.exe"):
        return r"C:\Program Files\Microsoft Visual Studio\18\Enterprise"
    if exe.endswith("cl.exe") and "clang" not in exe:
        return CL_BANNER + "\nCopyright (C) Microsoft Corporation.  All rights reserved.\n\nusage: cl [ option... ] filename... [ /link linkoption... ]"
    if exe.endswith("clang-cl.exe"):
        if args[1:] == ["--version"]:
            return "clang version 20.1.0\nTarget: aarch64-pc-windows-msvc"
        return "clang-cl: error: no input files"
    return "error: unexpected"


class Layout:
    """A fake Visual Studio + Windows SDK install tree."""

    def __init__(self, root: pathlib.Path):
        self.vc = root / "VS" / "18" / "Enterprise" / "VC"
        for version in ("14.44.35207", TOOLSET, "not-a-version"):
            toolset = self.vc / "Tools" / "MSVC" / version
            toolset.mkdir(parents=True)
            if version == TOOLSET:
                compiler = toolset / "bin" / "HostX64" / "arm64" / "cl.exe"
                compiler.parent.mkdir(parents=True)
                compiler.write_text("")
        self.sdk = root / "Windows Kits" / "10"
        for version in ("10.0.22621.0", SDK, "wdf"):
            (self.sdk / "Include" / version).mkdir(parents=True)


class WindowsToolchainProvenanceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.layout = Layout(self.tmp)
        env = {k: v for k, v in os.environ.items()
               if k not in ("VCToolsVersion", "WindowsSDKVersion", "WindowsSdkDir", "CC", "CXX")}
        env["CC"] = r"C:\Program Files\LLVM\bin\clang-cl.exe"
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def receipt(self, **kwargs):
        return MODULE.build_receipt("arm64", "Release", "gpu", vc_dir=self.layout.vc,
                                    win_sdk=self.layout.sdk, run=fake_run, **kwargs)

    def test_published_m153_receipt_is_rejected(self):
        problems = MODULE.validate_receipt(json.loads(BROKEN_M153.read_text()), "arm64", "Release")
        text = "\n".join(problems)
        self.assertIn("msvc_toolset_version", text)
        self.assertIn("windows_sdk_version", text)
        self.assertIn("no input files", text)
        self.assertIn("skia_gn_compiler.version", text)

    def test_resolves_toolset_sdk_and_compiler_versions(self):
        receipt = self.receipt()
        producer = receipt["producer"]
        self.assertEqual(producer["msvc_toolset_version"], TOOLSET)
        self.assertEqual(producer["windows_sdk_version"], SDK)
        self.assertTrue(producer["skia_gn_compiler"]["path"].endswith(
            os.path.join("MSVC", TOOLSET, "bin", "HostX64", "arm64", "cl.exe")))
        self.assertEqual(producer["skia_gn_compiler"]["version"], CL_BANNER)
        self.assertEqual(producer["dawn_cmake_compiler"]["version"], CL_BANNER)
        self.assertEqual(producer["dawn_cmake_compiler"]["driver"], "cl.exe")
        self.assertIn(os.path.join("MSVC", TOOLSET), producer["dawn_cmake_compiler"]["path"])
        self.assertEqual(receipt["runtime"]["compile_flag"], "/MT")
        self.assertIn(TOOLSET, receipt["runtime"]["consumer_requirement"])
        self.assertEqual(MODULE.validate_receipt(receipt, "arm64", "Release"), [])

    def test_arm64ec_uses_arm64_compiler_with_explicit_target_architecture(self):
        receipt = MODULE.build_receipt("arm64ec", "Release", "gpu", vc_dir=self.layout.vc,
                                       win_sdk=self.layout.sdk, run=fake_run)
        self.assertEqual(receipt["target"]["architecture"], "arm64ec")
        self.assertTrue(receipt["producer"]["skia_gn_compiler"]["path"].endswith(
            os.path.join("HostX64", "arm64", "cl.exe")))
        self.assertEqual(MODULE.validate_receipt(receipt, "arm64ec", "Release"), [])

    def test_unresolvable_toolchain_fails_validation(self):
        receipt = MODULE.build_receipt("arm64", "Release", "gpu", vc_dir=self.tmp / "missing",
                                       win_sdk=self.tmp / "missing", run=fake_run)
        problems = MODULE.validate_receipt(receipt, "arm64", "Release")
        self.assertTrue(any("msvc_toolset_version" in p for p in problems), problems)
        self.assertTrue(any("windows_sdk_version" in p for p in problems), problems)

    def test_find_msvc_falls_back_to_vswhere_for_visual_studio_18(self):
        found = MODULE.find_msvc(program_dirs=[self.tmp / "nothing-here"], run=fake_run)
        self.assertEqual(str(found).replace("\\", "/"),
                         "C:/Program Files/Microsoft Visual Studio/18/Enterprise/VC")

    def test_find_msvc_ignores_a_failed_vswhere(self):
        self.assertIsNone(MODULE.find_msvc(program_dirs=[], run=lambda args: "error: not found"))

    def test_toolchain_ninja_cl_is_authoritative(self):
        ninja = self.tmp / "toolchain.ninja"
        ninja.write_text(
            'rule cxx\n  command = ccache "C:/Program Files/Microsoft Visual Studio/18/Enterprise/'
            'VC/Tools/MSVC/14.44.35207/bin/HostX64/arm64/cl.exe" /nologo /showIncludes\n')
        receipt = self.receipt(toolchain_ninja=ninja)
        producer = receipt["producer"]
        self.assertEqual(producer["msvc_toolset_version"], "14.44.35207")
        self.assertEqual(producer["skia_gn_compiler"]["source"], "toolchain.ninja")
        self.assertIn("14.44.35207", producer["skia_gn_compiler"]["path"])

    def test_toolchain_ninja_unescapes_windows_drive_colon(self):
        ninja = self.tmp / "toolchain.ninja"
        ninja.write_text(
            'rule cxx\n  command = "C$:/Program Files/Microsoft Visual Studio/18/Enterprise/'
            'VC/Tools/MSVC/14.44.35207/bin/HostX64/arm64/cl.exe" /nologo\n')
        receipt = self.receipt(toolchain_ninja=ninja)
        self.assertEqual(receipt["producer"]["msvc_toolset_version"], "14.44.35207")
        self.assertEqual(receipt["producer"]["skia_gn_compiler"]["path"].split(":", 1)[0], "C")

    def test_toolchain_ninja_decodes_ninja_space_escapes(self):
        ninja = self.tmp / "toolchain-spaces.ninja"
        ninja.write_text(
            'rule cxx\n  command = C$:/Program$ Files/Microsoft$ Visual$ Studio/18/'
            'Enterprise/VC/Tools/MSVC/14.44.35207/bin/HostX64/arm64/cl.exe\n')
        built = MODULE.cl_from_toolchain_ninja(ninja)
        self.assertIsNotNone(built)
        assert built
        self.assertIn("Program Files/Microsoft Visual Studio", built[0])

    def test_wrong_architecture_is_rejected(self):
        problems = MODULE.validate_receipt(self.receipt(), "x64", "Release")
        self.assertTrue(any("architecture" in p for p in problems), problems)

    def test_main_refuses_to_write_an_unprovable_receipt(self):
        out = self.tmp / "msvc-toolchain.json"
        with mock.patch.object(MODULE, "find_msvc", return_value=None), \
                mock.patch.object(MODULE, "_run", fake_run):
            code = MODULE.main([str(out), "--arch", "arm64"])
        self.assertEqual(code, 1)

    def test_check_mode_rejects_the_published_receipt(self):
        self.assertEqual(MODULE.main([str(BROKEN_M153), "--arch", "arm64", "--check"]), 1)

    def test_receipt_is_json_serializable(self):
        json.dumps(self.receipt())

    def test_arm64_vector_stl_guard_is_present(self):
        source = (ROOT / "build-skia.py").read_text(encoding="utf-8")
        self.assertIn("_USE_STD_VECTOR_ALGORITHMS=0", source)


if __name__ == "__main__":
    unittest.main()
