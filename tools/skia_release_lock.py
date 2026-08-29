#!/usr/bin/env python3
"""Resolve one immutable Skia branch head and its Skia-DEPS Dawn revision."""

import argparse
import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


SKIA_GITILES = "https://skia.googlesource.com/skia"
RETRYABLE = {408, 429, 500, 502, 503, 504}


def _read_url(url, attempts=4):
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(url, timeout=30).read()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE or attempt + 1 == attempts:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def _json_url(url):
    raw = _read_url(url).decode("utf-8", "replace")
    if raw.startswith(")]}'"):
        raw = raw.split("\n", 1)[1]
    return json.loads(raw)


def resolve_lock(tag):
    match = re.fullmatch(r"chrome/m([0-9]+)", tag)
    if not match:
        raise SystemExit(f"skia_release_lock: non-canonical milestone tag: {tag}")
    revision = _json_url(f"{SKIA_GITILES}/+/refs/heads/{tag}?format=JSON")["commit"]
    deps = base64.b64decode(
        _read_url(f"{SKIA_GITILES}/+/{revision}/DEPS?format=TEXT")
    ).decode("utf-8", "replace")
    dawn = re.search(
        r'"third_party/externals/dawn"\s*:\s*"[^"]+@([0-9a-f]{40})"', deps
    )
    if not dawn:
        raise SystemExit(f"skia_release_lock: missing Dawn revision in Skia {revision}")
    return {
        "schema": 1,
        "source": "skia-branch-head",
        "skia_release_tag": tag,
        "milestone": int(match.group(1)),
        "built_skia": revision,
        "built_dawn": dawn.group(1),
        "repos": {
            "skia": "https://skia.googlesource.com/skia.git",
            "dawn": "https://dawn.googlesource.com/dawn.git",
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--output", type=Path, default=Path("skia-release-lock.json"))
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    lock = resolve_lock(args.tag)
    args.output.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as out:
            out.write(f"tag={lock['skia_release_tag']}\n")
            out.write(f"milestone={lock['milestone']}\n")
            out.write(f"skia={lock['built_skia']}\n")
            out.write(f"dawn={lock['built_dawn']}\n")
    print(json.dumps(lock, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
