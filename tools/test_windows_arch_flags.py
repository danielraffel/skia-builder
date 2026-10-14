#!/usr/bin/env python3
"""Contract tests for the Windows Skia producer architecture mapping."""

import importlib.util
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "build-skia.py"
spec = importlib.util.spec_from_file_location("build_skia", MODULE)
build_skia = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_skia)


def test_pure_arm64_stays_arm64_and_disables_vector_stl():
    cpu, flags = build_skia.windows_arch_gn_settings("arm64", "/MT")
    assert cpu == "arm64"
    assert flags == ["/MT", "/D_USE_STD_VECTOR_ALGORITHMS=0"]


def test_arm64ec_is_explicitly_distinct_from_pure_arm64():
    cpu, flags = build_skia.windows_arch_gn_settings("arm64ec", "/MT")
    assert cpu == "arm64"
    assert flags == ["/MT", "/arm64EC"]


def test_x64_and_win32_do_not_get_arm64ec_flags():
    assert build_skia.windows_arch_gn_settings("x64", "/MT") == ("x64", ["/MT"])
    assert build_skia.windows_arch_gn_settings("Win32", "/MT") == ("x86", ["/MT"])


if __name__ == "__main__":
    test_pure_arm64_stays_arm64_and_disables_vector_stl()
    test_arm64ec_is_explicitly_distinct_from_pure_arm64()
    test_x64_and_win32_do_not_get_arm64ec_flags()
    print("PASS: Windows architecture flag contract")
