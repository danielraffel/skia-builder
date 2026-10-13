#!/usr/bin/env python3
"""The lint workflow installs its Python dependencies wheels-only and hash-locked.

With --require-hashes alone, a runner with no matching wheel silently falls
back to building the sdist, and that build fetches setuptools and cython
unpinned.  --only-binary :all: refuses the fallback, and the requirements
file carries wheel hashes only.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "lint.yml"
REQUIREMENTS = ROOT / "tools" / "requirements-lint.txt"
PYYAML_6_0_3_SDIST = "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"


class LintRequirements(unittest.TestCase):
    def test_every_pip_install_is_wheels_only_and_hash_locked(self):
        installs = [line for line in WORKFLOW.read_text().splitlines()
                    if re.search(r"\bpip install\b", line.split("#", 1)[0])
                    and "--dry-run" not in line]
        self.assertTrue(installs, "the lint workflow installs its requirements")
        for line in installs:
            with self.subTest(line=line.strip()):
                self.assertIn("--only-binary :all:", line)
                self.assertIn("--require-hashes", line)
                self.assertIn("--no-deps", line)
                self.assertIn("-r tools/requirements-lint.txt", line)

    def test_requirements_pin_exact_versions_with_wheel_hashes_only(self):
        text = REQUIREMENTS.read_text()
        self.assertRegex(text, r"(?m)^pyyaml==\d+\.\d+\.\d+ \\$")
        self.assertGreater(text.count("--hash=sha256:"), 10)
        self.assertNotIn(PYYAML_6_0_3_SDIST, text)


if __name__ == "__main__":
    unittest.main()
