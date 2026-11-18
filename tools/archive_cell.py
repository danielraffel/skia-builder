#!/usr/bin/env python3
"""The build cell a published archive's name promises.

A release asset is named ``skia-build-<platform>[-<target>]-<arch>[-<arch>...]
-<variant>-<config>.zip`` by the workflow's "Set archive name" step.  A
consumer picks an asset by that name, so a record bound to the archive must
describe exactly that cell.  ``--check`` modes use :func:`cell_for_archive`
as the expectation: it comes from the archive the record is being proved
against, never from the record itself, and an unrecognised name fails closed.
"""
from __future__ import annotations

import re

NAME_RE = re.compile(
    r"^skia-build-(?P<platform>mac|ios|visionos|linux|win)"
    r"(?:-(?P<target>device|simulator))?"
    r"-(?P<archs>[a-z0-9_]+(?:-[a-z0-9_]+)*)"
    r"-(?P<variant>[a-z0-9]+)-(?P<config>release|debug)\.zip$")
ARCHS = {
    "mac": {"arm64", "x86_64"},
    "ios": {"arm64", "x86_64"},
    "visionos": {"arm64"},
    "linux": {"x64", "arm64"},
    "win": {"x64", "arm64", "arm64ec"},
}
# The universal mac cell builds both slices and lipos them together.
EXPANSIONS = {("mac", "universal"): ["arm64", "x86_64"]}


def cell_for_archive(name: str) -> dict[str, object]:
    """Platform, target, architectures, variant and configuration ``name`` promises.

    Raises ``ValueError`` for a name that is not a known cell, so a caller
    can never fall back to trusting the record's own claim.
    """
    match = NAME_RE.match(name)
    if not match:
        raise ValueError(f"{name} is not a skia-build-<platform>-...-<variant>-<config>.zip name")
    platform = match["platform"]
    archs: list[str] = []
    for token in match["archs"].split("-"):
        archs += EXPANSIONS.get((platform, token), [token])
    unknown = sorted(set(archs) - ARCHS[platform])
    if unknown or len(set(archs)) != len(archs):
        raise ValueError(f"{name} names architectures {archs} that are not {platform} architectures")
    target = match["target"] or ""
    if platform in ("ios", "visionos") and not target:
        raise ValueError(f"{name} does not say device or simulator")
    if platform not in ("ios", "visionos") and target:
        raise ValueError(f"{name}: {platform} has no {target} target")
    return {"platform": platform, "target": target, "architectures": sorted(archs),
            "variant": match["variant"], "configuration": match["config"].capitalize()}


def cell_problems(name: str, claimed: object, *, label: str) -> list[str]:
    """Every way ``claimed`` (a record's target or cell) differs from what ``name`` promises."""
    try:
        expected = cell_for_archive(name)
    except ValueError as error:
        return [str(error)]
    claimed = claimed if isinstance(claimed, dict) else {}
    problems = []
    if claimed.get("platform") != expected["platform"]:
        problems.append(f"{label}.platform {claimed.get('platform')!r} != {expected['platform']!r}")
    architectures = claimed.get("architectures")
    if not isinstance(architectures, list) or sorted(map(str, architectures)) != expected["architectures"]:
        problems.append(f"{label}.architectures {architectures!r} != {expected['architectures']!r}")
    for key in ("variant", "configuration"):
        if claimed.get(key) != expected[key]:
            problems.append(f"{label}.{key} {claimed.get(key)!r} != {expected[key]!r}")
    return problems
