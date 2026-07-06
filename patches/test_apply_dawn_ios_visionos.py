#!/usr/bin/env python3

import tempfile
from pathlib import Path

import apply_dawn_ios_visionos


ARGS_GNI = """declare_args() {
  dawn_enable_vulkan = is_linux || is_android
}
"""

BUILD_GN = """template("dawn_action") {
  args += sanitizer_args
}
"""

BUILD_DAWN_PY = '''from cmake_utils import (add_common_cmake_args, combine_into_library,
                         discover_dependencies, get_cmake_os_cpu,
                         get_windows_settings, quote_if_needed, write_depfile,
                         get_third_party_locations)

def main():
  parser.add_argument(
      "--dawn_enable_vulkan", default="false", help="Enable Vulkan backend.")
  args = parser.parse_args()

  configure_cmd = [
      "-DCMAKE_CXX_EXTENSIONS=OFF",
      "-DDAWN_FORCE_SYSTEM_COMPONENT_LOAD=ON", # https://g-issues.chromium.org/issues/399358291
  ]

  if target_os == "Darwin" or target_os == "iOS":
    configure_cmd.append(f"-DCMAKE_OSX_ARCHITECTURES={target_cpu}")

  env = os.environ.copy()
'''

CMAKE_UTILS_PY = '''  if os == "mac":
    target_cpu_map = {
      "arm64": "arm64",
      "x64": "x86_64",
    }
    return "Darwin", target_cpu_map[cpu]

  if os == "win":
    return "Windows", cpu

def get_windows_settings(args):
  return [], [], []
'''


def write_fixture(root: Path) -> list[Path]:
  dawn_dir = root / "third_party" / "dawn"
  dawn_dir.mkdir(parents=True)

  files = {
      "args.gni": ARGS_GNI,
      "BUILD.gn": BUILD_GN,
      "build_dawn.py": BUILD_DAWN_PY,
      "cmake_utils.py": CMAKE_UTILS_PY,
  }

  paths = []
  for name, content in files.items():
    path = dawn_dir / name
    path.write_text(content)
    paths.append(path)

  return paths


def test_patch_is_complete_and_idempotent() -> None:
  with tempfile.TemporaryDirectory() as tmp:
    paths = write_fixture(Path(tmp))

    assert apply_dawn_ios_visionos.apply_patches(Path(tmp))

    build_dawn = (Path(tmp) / "third_party" / "dawn" / "build_dawn.py").read_text()
    assert "-DDAWN_SUPPORTS_CXX_MODULES=OFF" in build_dawn
    assert "Skia consumes Dawn headers and libraries" in build_dawn
    assert "--ios_simulator" in build_dawn
    assert "--visionos" in build_dawn

    cmake_utils = (Path(tmp) / "third_party" / "dawn" / "cmake_utils.py").read_text()
    assert "def get_ios_settings" in cmake_utils
    assert "def get_visionos_settings" in cmake_utils

    first_pass = {path: path.read_text() for path in paths}
    assert apply_dawn_ios_visionos.apply_patches(Path(tmp))
    second_pass = {path: path.read_text() for path in paths}
    assert second_pass == first_pass


if __name__ == "__main__":
  test_patch_is_complete_and_idempotent()
  print("apply_dawn_ios_visionos tests passed")
