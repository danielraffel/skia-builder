#!/usr/bin/env python3
import pathlib, sys, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_tag


class ReleaseTagTests(unittest.TestCase):
    def test_default_and_own_tag(self):
        self.assertEqual(release_tag.resolve("chrome/m158", ""), ("chrome/m158", ""))
        self.assertEqual(release_tag.resolve("chrome/m158", "chrome/m158"), ("chrome/m158", "chrome/m158"))

    def test_attested_form_for_the_same_milestone(self):
        self.assertEqual(release_tag.resolve("chrome/m158", "chrome/m158-attested.1"),
                         ("chrome/m158", "chrome/m158-attested.1"))

    def test_anything_else_is_refused(self):
        for tag in ("chrome/m159-attested.1", "chrome/m158-attested.0", "chrome/m158-attested.",
                    "chrome/m158-attested.1x", "chrome/m158-test", "v1", "chrome/m158-attested.1/../x"):
            with self.assertRaises(ValueError, msg=tag):
                release_tag.resolve("chrome/m158", tag)

    def test_workflow_uses_the_helper(self):
        text = (pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/build-skia.yml").read_text()
        self.assertIn("tools/release_tag.py", text)
        self.assertNotIn('"$RELEASE_TAG" != "$SKIA_BRANCH"', text)


if __name__ == "__main__":
    unittest.main()
