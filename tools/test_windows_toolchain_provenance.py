#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("provenance", ROOT / "tools" / "write_windows_toolchain_provenance.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class WindowsToolchainProvenanceTests(unittest.TestCase):
    def test_receipt_declares_static_msvc_runtime_policy(self):
        receipt = MODULE.build_receipt("arm64", "Release", "gpu")
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["target"]["architecture"], "arm64")
        self.assertEqual(receipt["producer"]["skia_gn_compiler"]["driver"], "cl.exe")
        self.assertEqual(receipt["runtime"]["abi"], "msvc")
        self.assertEqual(receipt["runtime"]["library"], "static")
        self.assertEqual(receipt["runtime"]["compile_flag"], "/MT")
        self.assertIn("older toolsets are not proven", receipt["runtime"]["consumer_requirement"])

    def test_receipt_is_json_serializable(self):
        json.dumps(MODULE.build_receipt("x64", "Debug", "gpu"))


if __name__ == "__main__":
    unittest.main()
