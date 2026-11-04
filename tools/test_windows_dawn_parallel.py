"""Execute the patched Dawn launcher with a fake subprocess, without compiling."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dawn_patch", ROOT / "patches/apply_dawn_windows_arm64_vector_stl.py")
dawn_patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dawn_patch)

FIXTURE = '''def build(env, subprocess):
  ninja_exe = "ninja"
  build_dir = "cmake_dawn"
  build_targets = ["dawn_native"]
  build_cmd = [ninja_exe, "-C", build_dir, "-dkeepdepfile"] + build_targets
  subprocess.run(build_cmd, check=True, env=env)
'''


class DawnParallelTests(unittest.TestCase):
    def patched(self, original=FIXTURE):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "build_dawn.py"
        path.write_text(original, encoding="utf-8")
        self.assertTrue(dawn_patch._patch_nested_ninja_share(path))
        content = path.read_bytes()
        self.assertFalse(dawn_patch._patch_nested_ninja_share(path))
        self.assertEqual(content, path.read_bytes())
        namespace = {}
        exec(compile(content, str(path), "exec"), namespace)
        return namespace["build"]

    def test_governed_nested_build_uses_one_parent_slot(self):
        build = self.patched()
        for share in ("1", "3", "12"):
            runner = Mock()
            env = {"CMAKE_BUILD_PARALLEL_LEVEL": share}
            build(env, runner)
            runner.run.assert_called_once_with(
                ["ninja", "-C", "cmake_dawn", "-dkeepdepfile", "-j", "1", "dawn_native"],
                check=True, env=env)

    def test_unset_preserves_upstream_behavior(self):
        runner = Mock()
        self.patched()({}, runner)
        self.assertNotIn("-j", runner.run.call_args.args[0])

    def test_invalid_share_never_starts_ninja(self):
        build = self.patched()
        for invalid in ("", "0", "-1", "auto", "3 4", " 3", "٣"):
            runner = Mock()
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build({"CMAKE_BUILD_PARALLEL_LEVEL": invalid}, runner)
            runner.run.assert_not_called()

    def test_upstream_drift_is_refused(self):
        for text in ("# changed upstream\n", FIXTURE + FIXTURE):
            with self.assertRaisesRegex(RuntimeError, "exactly once"):
                self.patched(text)


if __name__ == "__main__":
    unittest.main()
