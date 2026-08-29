#!/usr/bin/env python3
import base64
import json
import unittest
from unittest.mock import patch

import skia_release_lock as srl


class SkiaReleaseLockTests(unittest.TestCase):
    def test_resolves_immutable_skia_and_dawn(self):
        revision = "1" * 40
        dawn = "2" * 40

        def fake_read(url, attempts=4):
            if "refs/heads" in url:
                return ( ")]}'\n" + json.dumps({"commit": revision}) ).encode()
            return base64.b64encode((
                f'"third_party/externals/dawn": "https://dawn.googlesource.com/dawn.git@{dawn}"'
            ).encode())

        with patch.object(srl, "_read_url", fake_read):
            lock = srl.resolve_lock("chrome/m153")
        self.assertEqual(lock["milestone"], 153)
        self.assertEqual(lock["built_skia"], revision)
        self.assertEqual(lock["built_dawn"], dawn)

    def test_rejects_noncanonical_tag(self):
        with self.assertRaisesRegex(SystemExit, "non-canonical"):
            srl.resolve_lock("chrome/m153-test")


if __name__ == "__main__":
    unittest.main()
