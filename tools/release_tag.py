#!/usr/bin/env python3
"""Decide which release tag a run publishes under.

A run publishes under the Skia branch's own tag (``chrome/m158``) unless it
names an attested re-cut, ``<branch>-attested.<n>``.  Any other ``release_tag``
is refused, so a dispatch cannot publish under an arbitrary name.  An
``-attested.N`` tag is a new release: it never replaces assets another
release published, and the Skia/Dawn revisions come from the base release's
lock.  Without ``release_tag`` the publish tag is empty (use the branch tag).

Prints ``base=<tag>`` and ``publish=<tag>`` (``publish`` empty when unset).
"""
from __future__ import annotations

import re
import sys

ATTESTED = re.compile(r"^(chrome/m[0-9]+)-attested\.[1-9][0-9]*$")


def resolve(skia_branch: str, release_tag: str) -> tuple[str, str]:
    """Return (base release tag, publish tag or '')."""
    if not release_tag:
        return skia_branch, ""
    if release_tag == skia_branch:
        return skia_branch, release_tag
    match = ATTESTED.match(release_tag)
    if match and match.group(1) == skia_branch:
        return skia_branch, release_tag
    raise ValueError(f"release_tag={release_tag} must equal skia_branch={skia_branch} "
                     f"or be {skia_branch}-attested.<n>")


def main(argv: list[str]) -> int:
    try:
        base, publish = resolve(argv[1], argv[2] if len(argv) > 2 else "")
    except ValueError as error:
        print(f"::error::{error}")
        return 1
    print(f"base={base}\npublish={publish}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
