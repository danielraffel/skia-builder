#!/usr/bin/env python3
import base64
import json
import pathlib
import tempfile
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

    def _published(self, tmp, **overrides):
        lock = {
            "schema": 1,
            "source": "legacy-reconstructed-from-build-time",
            "skia_release_tag": "chrome/m153",
            "milestone": 153,
            "built_skia": "8b8c3872fbc03f025855db96ce683f34ec98a815",
            "built_dawn": "f91da75afe31d4d6f47a6da307e1fbabd1b1691a",
        }
        lock.update(overrides)
        path = pathlib.Path(tmp) / "skia-release-lock.json"
        path.write_text(json.dumps(lock))
        return path

    def test_backfill_reuses_the_published_revision_not_the_branch_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            published = self._published(tmp)
            out = pathlib.Path(tmp) / "out.json"
            gh_out = pathlib.Path(tmp) / "gh.txt"

            def branch_head(*args, **kwargs):
                raise AssertionError("a backfill must not resolve the moving branch head")

            with patch.object(srl, "_read_url", branch_head):
                srl.main(["chrome/m153", "--from-release-lock", str(published),
                          "--output", str(out), "--github-output", str(gh_out)])
            self.assertIn("skia=8b8c3872fbc03f025855db96ce683f34ec98a815", gh_out.read_text())
            self.assertEqual(json.loads(out.read_text())["built_dawn"],
                             "f91da75afe31d4d6f47a6da307e1fbabd1b1691a")

    def test_backfill_rejects_a_lock_for_another_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "not 'chrome/m153'"):
                srl.load_published_lock(self._published(tmp, skia_release_tag="chrome/m152"),
                                        "chrome/m153")
            with self.assertRaisesRegex(SystemExit, "no immutable built_skia"):
                srl.load_published_lock(self._published(tmp, built_skia="chrome/m153"),
                                        "chrome/m153")


if __name__ == "__main__":
    unittest.main()
