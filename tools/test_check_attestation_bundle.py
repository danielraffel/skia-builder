#!/usr/bin/env python3
"""check_attestation_bundle.py publishes a bundle only beside the bytes it attests."""
import base64
import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_attestation_bundle",
                                              ROOT / "tools" / "check_attestation_bundle.py")
tool = importlib.util.module_from_spec(spec)
sys.modules["check_attestation_bundle"] = tool
spec.loader.exec_module(tool)

STEM = "skia-build-linux-x64-gpu-release"


class BundleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.archive = self.tmp / f"{STEM}.zip"
        self.archive.write_bytes(b"archive")
        self.receipt = self.tmp / f"{STEM}.linux-toolchain.sha256-{'a' * 64}.json"
        self.receipt.write_bytes(b"{}\n")
        self.manifest = self.tmp / f"{STEM}.legal-manifest.sha256-{'b' * 64}.json"
        self.manifest.write_bytes(b"{\"m\": 1}\n")

    def bundle(self, files=None, payload_type=tool.IN_TOTO, stem=STEM, signatures=({"sig": "x"},)):
        files = [self.archive, self.receipt, self.manifest] if files is None else files
        statement = {"_type": "https://in-toto.io/Statement/v1",
                     "subject": [{"name": f.name, "digest": {"sha256": hashlib.sha256(f.read_bytes()).hexdigest()}}
                                 for f in files]}
        data = json.dumps({"dsseEnvelope": {"payloadType": payload_type, "signatures": list(signatures),
                                            "payload": base64.b64encode(json.dumps(statement).encode()).decode()}}
                          ).encode()
        path = self.tmp / f"{stem}.provenance-attestation.sha256-{hashlib.sha256(data).hexdigest()}.sigstore.json"
        path.write_bytes(data)
        return path

    def check(self, bundle):
        return tool.main([str(bundle), str(self.archive), str(self.receipt), str(self.manifest)])

    def test_a_bundle_attesting_every_file_passes(self):
        self.assertEqual(self.check(self.bundle()), 0)

    def test_a_bundle_missing_a_record_is_refused(self):
        self.assertEqual(self.check(self.bundle(files=[self.archive, self.receipt])), 1)

    def test_a_bundle_for_other_bytes_is_refused(self):
        bundle = self.bundle()
        self.manifest.write_bytes(b"{\"m\": 2}\n")
        self.assertEqual(self.check(bundle), 1)

    def test_a_bundle_named_for_another_archive_or_digest_is_refused(self):
        self.assertEqual(self.check(self.bundle(stem="skia-build-linux-arm64-gpu-release")), 1)
        bundle = self.bundle()
        renamed = bundle.with_name(f"{STEM}.provenance-attestation.sha256-{'0' * 64}.sigstore.json")
        bundle.rename(renamed)
        self.assertEqual(self.check(renamed), 1)

    def test_an_unsigned_or_non_in_toto_bundle_is_refused(self):
        self.assertEqual(self.check(self.bundle(signatures=())), 1)
        self.assertEqual(self.check(self.bundle(payload_type="text/plain")), 1)


if __name__ == "__main__":
    unittest.main()
