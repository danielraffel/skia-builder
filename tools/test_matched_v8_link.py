#!/usr/bin/env python3
import unittest
from unittest.mock import patch

import matched_v8_link as mvl


def skia_release(milestone, body=None):
    if body is None:
        body = (
            mvl._provisional_line(milestone)
            + "\nKeep this text and https://example.com/release-notes\n"
        )
    lock = {
        "schema": 1,
        "milestone": milestone,
        "skia_release_tag": f"chrome/m{milestone}",
        "built_skia": "a" * 40,
        "built_dawn": "b" * 40,
    }
    return {
        "id": milestone,
        "tag_name": f"chrome/m{milestone}",
        "body": body,
        "draft": False,
        "prerelease": False,
        "published_at": "2026-08-01T00:00:00Z",
        "assets": [{"name": "skia-release-lock.json", "id": milestone, "data": lock}],
    }


def v8_release(milestone, version="15.3.76.5", revision="1" * 12,
               published="2026-08-02T00:00:00Z", complete=True):
    tag = f"v8-m{milestone}-{version}-{revision}"
    suffix = tag.removeprefix("v8-")
    assets = [{"name": "release-metadata.json"}]
    assets += [{"name": f"v8-{platform}-{suffix}.zip"} for platform in mvl.PLATFORMS]
    if not complete:
        assets.pop()
    pair = {
        "source": "chromium-milestone-branch-deps",
        "pair_kind": "chromium-milestone",
        "this_artifact": "v8",
        "milestone": milestone,
        "skia_release_tag": f"chrome/m{milestone}",
        "validated_skia_release": f"chrome/m{milestone}",
        "built_skia": "a" * 40,
        "built_dawn": "b" * 40,
        "built_revision": revision + "c" * 28,
        "v8": revision + "c" * 28,
    }
    metadata = {
        "schema": 1,
        "assets": [f"v8-{platform}-{suffix}.zip" for platform in mvl.PLATFORMS],
        "pair": pair,
        "manifests": [
            {
                "platform": platform,
                "arch": arch,
                "pair": pair,
                "consumer_defines": ["V8_COMPRESS_POINTERS", "V8_CPPGC_MICROTASK_QUEUE"],
            }
            for platform, arch in sorted(mvl.PLATFORM_ARCHES)
        ],
    }
    assets[0]["id"] = int(revision[0], 16) if revision[0].isalnum() else 1
    assets[0]["data"] = metadata
    return {
        "tag_name": tag,
        "assets": assets,
        "draft": False,
        "prerelease": False,
        "published_at": published,
    }


class MatchedV8LinkTests(unittest.TestCase):
    def test_provisional_link_becomes_exact_and_preserves_body(self):
        skia = skia_release(153)
        v8 = v8_release(153)
        updates = mvl.plan_updates([skia], [v8])
        self.assertEqual(len(updates), 1)
        self.assertIn(f"/releases/tag/{v8['tag_name']}", updates[0]["body"])
        self.assertIn("Keep this text and https://example.com/release-notes", updates[0]["body"])
        self.assertNotIn("releases?q=", updates[0]["body"])

    def test_no_match_or_incomplete_release_does_not_update(self):
        self.assertEqual(mvl.plan_updates([skia_release(153)], [v8_release(152)]), [])
        self.assertEqual(
            mvl.plan_updates([skia_release(153)], [v8_release(153, complete=False)]),
            [],
        )

    def test_corrupt_or_wrong_tuple_metadata_fails_closed(self):
        corrupt = v8_release(153)
        corrupt["assets"][0]["data"] = {"schema": 1}
        wrong_tuple = v8_release(153, revision="2" * 12)
        wrong_tuple["assets"][0]["data"]["pair"]["built_skia"] = "f" * 40
        self.assertEqual(mvl.plan_updates([skia_release(153)], [corrupt]), [])
        self.assertEqual(mvl.plan_updates([skia_release(153)], [wrong_tuple]), [])

    def test_missing_consumer_defines_fails_closed(self):
        release = v8_release(153)
        del release["assets"][0]["data"]["manifests"][0]["consumer_defines"]
        self.assertEqual(mvl.plan_updates([skia_release(153)], [release]), [])

    def test_newest_complete_release_wins_over_history_and_incomplete_newest(self):
        old = v8_release(153, revision="1" * 12, published="2026-08-02T00:00:00Z")
        newest_complete = v8_release(
            153, version="15.3.77.1", revision="2" * 12,
            published="2026-08-03T00:00:00Z",
        )
        incomplete = v8_release(
            153, version="15.3.78.1", revision="3" * 12,
            published="2026-08-04T00:00:00Z", complete=False,
        )
        updates = mvl.plan_updates([skia_release(153)], [old, incomplete, newest_complete])
        self.assertEqual(updates[0]["v8_tag"], newest_complete["tag_name"])

    def test_draft_prerelease_and_noncanonical_tags_are_ignored(self):
        draft = v8_release(153)
        draft["draft"] = True
        prerelease = v8_release(153)
        prerelease["prerelease"] = True
        noncanonical = v8_release(153)
        noncanonical["tag_name"] += "-test"
        self.assertEqual(
            mvl.plan_updates([skia_release(153)], [draft, prerelease, noncanonical]),
            [],
        )

    def test_old_reconciled_direct_link_advances_and_then_is_idempotent(self):
        old = v8_release(153, revision="1" * 12, published="2026-08-02T00:00:00Z")
        new = v8_release(
            153, version="15.3.77.1", revision="2" * 12,
            published="2026-08-03T00:00:00Z",
        )
        body = mvl._exact_line(153, old["tag_name"]) + "\nrest\n"
        updates = mvl.plan_updates([skia_release(153, body)], [old, new])
        self.assertEqual(updates[0]["v8_tag"], new["tag_name"])
        reconciled = skia_release(153, updates[0]["body"])
        self.assertEqual(mvl.plan_updates([reconciled], [old, new]), [])

    def test_unowned_release_text_is_not_rewritten(self):
        bodies = [
            "A hand-written link to https://github.com/danielraffel/v8-builder\n",
            "prefix " + mvl._provisional_line(153) + " suffix\n",
            (
                "**Matched V8 release:** [M153 matched V8: "
                "v8-m153-15.3.76.5-111111111111]"
                "(https://github.com/danielraffel/v8-builder/releases/tag/"
                "v8-m153-15.3.76.5-222222222222)\n"
            ),
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(
                    mvl.plan_updates([skia_release(153, body)], [v8_release(153)]),
                    [],
                )

    @patch.object(mvl, "_load_asset_json", side_effect=lambda repo, asset: asset["data"])
    @patch.object(mvl, "_gh_json")
    @patch.object(mvl, "_list_releases")
    def test_dry_run_reports_without_patching(
        self, list_releases, gh_json, load_asset_json
    ):
        list_releases.side_effect = [[skia_release(153)], [v8_release(153)]]
        updates = mvl.reconcile("owner/skia", "owner/v8", dry_run=True)
        self.assertEqual(len(updates), 1)
        gh_json.assert_not_called()

    @patch.object(mvl, "_load_asset_json", side_effect=lambda repo, asset: asset["data"])
    @patch.object(mvl, "_gh_json")
    @patch.object(mvl, "_list_releases")
    def test_live_mode_patches_only_the_skia_release_body(
        self, list_releases, gh_json, load_asset_json
    ):
        list_releases.side_effect = [[skia_release(153)], [v8_release(153)]]
        updates = mvl.reconcile("owner/skia", "owner/v8")
        self.assertEqual(len(updates), 1)
        gh_json.assert_called_once_with(
            "api", "--method", "PATCH", "repos/owner/skia/releases/153",
            "--input", "-", input_data={"body": updates[0]["body"]},
        )


if __name__ == "__main__":
    unittest.main()
