#!/usr/bin/env python3
"""Reconcile Skia milestone release notes to an exact matched V8 release."""

import argparse
import json
import os
import re
import subprocess


V8_REPO = "danielraffel/v8-builder"
SKIA_TAG = re.compile(r"^chrome/m(?P<milestone>[0-9]+)$")
V8_TAG = re.compile(
    r"^v8-m(?P<milestone>[0-9]+)-"
    r"(?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?)-"
    r"(?P<revision>[0-9a-f]{12})$"
)
PLATFORMS = (
    "android-arm64",
    "ios-simulator-arm64",
    "linux-arm64",
    "linux-x64",
    "mac-arm64",
    "mac-x86_64",
    "win-arm64",
    "win-x64",
)
PLATFORM_ARCHES = {
    ("android", "arm64"),
    ("ios", "arm64"),
    ("linux", "arm64"),
    ("linux", "x64"),
    ("mac", "arm64"),
    ("mac", "x86_64"),
    ("win", "arm64"),
    ("win", "x64"),
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _published(release):
    return (
        not release.get("draft", False)
        and not release.get("prerelease", False)
        and bool(release.get("published_at"))
    )


def _asset(release, name):
    return next(
        (asset for asset in release.get("assets", []) if asset.get("name") == name),
        None,
    )


def _complete_v8_assets(release, tag):
    suffix = tag.removeprefix("v8-")
    required = {"release-metadata.json"}
    required.update(f"v8-{platform}-{suffix}.zip" for platform in PLATFORMS)
    assets = {asset.get("name") for asset in release.get("assets", [])}
    return required <= assets


def _canonical_v8_candidates(releases, milestone):
    candidates = []
    for release in releases:
        tag = release.get("tag_name", "")
        match = V8_TAG.fullmatch(tag)
        if (
            not match
            or int(match.group("milestone")) != milestone
            or not _published(release)
            or not _complete_v8_assets(release, tag)
        ):
            continue
        candidates.append(release)
    return sorted(
        candidates,
        key=lambda release: (release["published_at"], release["tag_name"]),
        reverse=True,
    )


def _valid_skia_lock(lock, milestone):
    return (
        isinstance(lock, dict)
        and lock.get("schema") == 1
        and lock.get("milestone") == milestone
        and lock.get("skia_release_tag") == f"chrome/m{milestone}"
        and bool(SHA40.fullmatch(lock.get("built_skia", "")))
        and bool(SHA40.fullmatch(lock.get("built_dawn", "")))
    )


def _valid_v8_metadata(metadata, milestone, tag, skia_lock):
    match = V8_TAG.fullmatch(tag)
    if not isinstance(metadata, dict) or not match or metadata.get("schema") != 1:
        return False
    suffix = tag.removeprefix("v8-")
    expected_assets = {f"v8-{platform}-{suffix}.zip" for platform in PLATFORMS}
    if set(metadata.get("assets", [])) != expected_assets:
        return False
    pair = metadata.get("pair")
    if not isinstance(pair, dict):
        return False
    if not (
        pair.get("source") == "chromium-milestone-branch-deps"
        and pair.get("pair_kind") == "chromium-milestone"
        and pair.get("this_artifact") == "v8"
        and pair.get("milestone") == milestone
        and pair.get("skia_release_tag") == f"chrome/m{milestone}"
        and pair.get("validated_skia_release") == f"chrome/m{milestone}"
        and pair.get("built_skia") == skia_lock["built_skia"]
        and pair.get("built_dawn") == skia_lock["built_dawn"]
        and pair.get("built_revision") == pair.get("v8")
        and bool(SHA40.fullmatch(pair.get("v8", "")))
        and pair["v8"].startswith(match.group("revision"))
    ):
        return False
    manifests = metadata.get("manifests")
    return (
        isinstance(manifests, list)
        and len(manifests) == len(PLATFORM_ARCHES)
        and {(item.get("platform"), item.get("arch")) for item in manifests}
        == PLATFORM_ARCHES
        and all(item.get("pair") == pair for item in manifests)
        and all(
            isinstance(item.get("consumer_defines"), list)
            and bool(item["consumer_defines"])
            and all(
                isinstance(define, str) and define
                for define in item["consumer_defines"]
            )
            for item in manifests
        )
    )


def _provisional_line(milestone):
    return (
        f"**Matched V8 release:** [V8 builds for M{milestone}]"
        f"(https://github.com/{V8_REPO}/releases?q=v8-m{milestone})"
    )


def _exact_line(milestone, tag):
    return (
        f"**Matched V8 release:** [M{milestone} matched V8: {tag}]"
        f"(https://github.com/{V8_REPO}/releases/tag/{tag})"
    )


def _reconciled_line_pattern(milestone):
    tag = (
        rf"v8-m{milestone}-[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?-"
        rf"[0-9a-f]{{12}}"
    )
    return re.compile(
        rf"^\*\*Matched V8 release:\*\* \[M{milestone} matched V8: "
        rf"(?P<tag>{tag})\]"
        rf"\(https://github\.com/{re.escape(V8_REPO)}/releases/tag/"
        rf"(?P=tag)\)$",
        re.MULTILINE,
    )


def updated_body(body, milestone, v8_tag):
    """Replace only a link owned by this producer; preserve all other notes."""
    replacement = _exact_line(milestone, v8_tag)
    provisional = re.compile(
        rf"^{re.escape(_provisional_line(milestone))}$", re.MULTILINE
    )
    result, count = provisional.subn(replacement, body, count=1)
    if count == 0:
        result, count = _reconciled_line_pattern(milestone).subn(
            replacement, body, count=1
        )
    if count == 0:
        return None
    return None if result == body else result


def _embedded_json(asset):
    return asset.get("data")


def plan_updates(skia_releases, v8_releases, load_skia_json=_embedded_json,
                 load_v8_json=_embedded_json):
    updates = []
    for release in skia_releases:
        tag = release.get("tag_name", "")
        match = SKIA_TAG.fullmatch(tag)
        if not match or not _published(release):
            continue
        milestone = int(match.group("milestone"))
        lock_asset = _asset(release, "skia-release-lock.json")
        lock = load_skia_json(lock_asset) if lock_asset else None
        if not _valid_skia_lock(lock, milestone):
            continue
        v8_release = None
        for candidate in _canonical_v8_candidates(v8_releases, milestone):
            metadata_asset = _asset(candidate, "release-metadata.json")
            metadata = load_v8_json(metadata_asset)
            if _valid_v8_metadata(
                metadata, milestone, candidate["tag_name"], lock
            ):
                v8_release = candidate
                break
        if not v8_release:
            continue
        body = updated_body(release.get("body") or "", milestone, v8_release["tag_name"])
        if body is not None:
            updates.append({
                "id": release["id"],
                "tag_name": tag,
                "v8_tag": v8_release["tag_name"],
                "body": body,
            })
    return sorted(updates, key=lambda update: update["tag_name"])


def _gh_json(*args, input_data=None):
    completed = subprocess.run(
        ["gh", *args],
        check=True,
        input=None if input_data is None else json.dumps(input_data),
        stdout=subprocess.PIPE,
        text=True,
    )
    return json.loads(completed.stdout) if completed.stdout.strip() else None


def _list_releases(repo):
    pages = _gh_json(
        "api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"
    )
    return [release for page in pages for release in page]


def _load_asset_json(repo, asset):
    return _gh_json(
        "api", "-H", "Accept: application/octet-stream",
        f"repos/{repo}/releases/assets/{asset['id']}",
    )


def reconcile(skia_repo, v8_repo, dry_run=False):
    updates = plan_updates(
        _list_releases(skia_repo),
        _list_releases(v8_repo),
        load_skia_json=lambda asset: _load_asset_json(skia_repo, asset),
        load_v8_json=lambda asset: _load_asset_json(v8_repo, asset),
    )
    for update in updates:
        action = "Would update" if dry_run else "Updating"
        print(f"{action} {update['tag_name']} -> {update['v8_tag']}")
        if not dry_run:
            _gh_json(
                "api", "--method", "PATCH",
                f"repos/{skia_repo}/releases/{update['id']}",
                "--input", "-",
                input_data={"body": update["body"]},
            )
    if not updates:
        print("All eligible Skia releases already have exact matched V8 links.")
    return updates


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skia-repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--v8-repo", default=V8_REPO)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.skia_repo:
        parser.error("--skia-repo or GITHUB_REPOSITORY is required")
    reconcile(args.skia_repo, args.v8_repo, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
