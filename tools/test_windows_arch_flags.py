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


def test_arm64ec_summary_records_gn_cpu_and_ec_mode():
    script = build_skia.SkiaBuildScript()
    script.platform = "win"
    script.config = "Release"
    script.variant = "gpu"
    summary = script.generate_gn_args_summary("arm64ec")
    assert 'target_cpu = "arm64"' in summary
    assert "skia_win_arm64ec = true" in summary
    assert 'extra_cflags = ["/MT", "/arm64EC"]' in summary
    assert 'extra_ldflags = ["/machine:ARM64EC"]' in summary


if __name__ == "__main__":
    test_pure_arm64_stays_arm64_and_disables_vector_stl()
    test_arm64ec_is_explicitly_distinct_from_pure_arm64()
    test_x64_and_win32_do_not_get_arm64ec_flags()
    test_arm64ec_summary_records_gn_cpu_and_ec_mode()
    print("PASS: Windows architecture flag contract")
