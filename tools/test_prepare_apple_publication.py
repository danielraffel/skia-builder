#!/usr/bin/env python3
"""Negative controls for existing-run Apple publication admission."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import yaml

import prepare_apple_publication as pub


class Admission(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.asset = pub.ASSETS[0]
        self.stem = self.asset[:-4]
        self.cell = self.root / self.stem
        self.cell.mkdir()
        self.archive = self.cell / self.asset
        self.archive.write_bytes(b"a build archive")
        self.sha = pub.digest(self.archive)
        self.tag = "chrome/m158"
        self.source = {"skia_release_tag": self.tag, "built_skia": "a" * 40, "built_dawn": "b" * 40}
        self.lock = self.root / "skia-release-lock" / "skia-release-lock.json"
        self.lock.parent.mkdir()
        self.lock.write_text(json.dumps(self.source))
        self.published = self.root / "published.json"
        self.published.write_bytes(self.lock.read_bytes())
        self.records = {}
        self.data = {"archive": {"name": self.asset, "sha256": self.sha}, "source_revisions": {
            repo: {"commit": self.source[f"built_{repo}"], "expected": self.source[f"built_{repo}"]}
            for repo in ("skia", "dawn")}}
        self.write_record("legal-manifest", self.data)
        self.write_record("apple-toolchain", {"archive": self.data["archive"]})
        self.write_record("provenance-attestation", {"signature": "fixture"})

    def write_record(self, kind, value):
        if kind in self.records:
            self.records[kind].unlink()
        parent = self.root / "skia-build-apple-attestation" if kind == "provenance-attestation" else self.cell / "provenance-assets"
        parent.mkdir(exist_ok=True)
        body = json.dumps(value).encode()
        suffix = "sigstore.json" if kind == "provenance-attestation" else "json"
        path = parent / f"{self.stem}.{kind}.sha256-{hashlib.sha256(body).hexdigest()}.{suffix}"
        path.write_bytes(body)
        self.records[kind] = path
        return path

    def stage(self, **changes):
        args = dict(root=self.root, published_lock=self.published, tag=self.tag,
                    asset=self.asset, expected_sha256=self.sha, output=self.root / "staged")
        args.update(changes)
        return pub.stage(**args)

    def test_valid_stages_only_five_bound_files_and_checksum_inventory(self):
        (self.cell / "ignore-me").write_text("not published")
        staged = self.stage()
        self.assertEqual(len(staged), 5)
        self.assertEqual({p.name for p in staged}, {self.asset, self.lock.name} | {p.name for p in self.records.values()})
        self.assertEqual((self.root / "staged" / "SHA256SUMS").read_text(),
                         "".join(f"{pub.digest(p)}  {p.name}\n" for p in staged))

    def test_archive_digest_is_explicit(self):
        self.archive.write_bytes(b"different build")
        with self.assertRaisesRegex(ValueError, "approved digest"):
            self.stage()

    def test_invalid_asset_or_tag_or_digest(self):
        for arg, values in {"asset": ["../a.zip", "skia-build-win-x64-gpu-release.zip"],
                            "tag": ["chrome/m158/../m159", "other"],
                            "expected_sha256": ["0", "A" * 64]}.items():
            for value in values:
                with self.subTest(arg=arg, value=value), self.assertRaises(ValueError):
                    self.stage(**{arg: value})

    def test_different_destination_lock(self):
        for key in self.source:
            data = dict(self.source, **{key: "different"})
            self.published.write_text(json.dumps(data))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "destination release lock"):
                self.stage()

    def test_both_locks_cannot_redirect_destination(self):
        self.source["skia_release_tag"] = "chrome/m159"
        self.lock.write_text(json.dumps(self.source))
        self.published.write_bytes(self.lock.read_bytes())
        with self.assertRaisesRegex(ValueError, "another release"):
            self.stage()

    def test_invalid_locked_commit(self):
        self.source["built_skia"] = "not-a-commit"
        self.lock.write_text(json.dumps(self.source))
        self.published.write_bytes(self.lock.read_bytes())
        with self.assertRaisesRegex(ValueError, "source lock"):
            self.stage()

    def test_manifest_revisions_must_match_lock(self):
        for repo in ("skia", "dawn"):
            for field in ("commit", "expected"):
                value = copy.deepcopy(self.data)
                value["source_revisions"][repo][field] = "c" * 40
                self.write_record("legal-manifest", value)
                with self.subTest(repo=repo, field=field), self.assertRaisesRegex(ValueError, "revision differs"):
                    self.stage()

    def test_missing_revision_is_refused(self):
        self.write_record("legal-manifest", {"archive": self.data["archive"]})
        with self.assertRaisesRegex(ValueError, "revision differs"):
            self.stage()

    def test_record_must_bind_archive(self):
        for kind in ("legal-manifest", "apple-toolchain"):
            for field in ("name", "sha256"):
                value = copy.deepcopy(self.data)
                value["archive"][field] = "incorrect"
                self.write_record(kind, value)
                with self.subTest(kind=kind, field=field), self.assertRaisesRegex(ValueError, "bind the archive"):
                    self.stage()
                self.write_record(kind, self.data)

    def test_each_sidecar_tamper_is_refused(self):
        for kind, path in self.records.items():
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "content-addressed"):
                self.stage()
            path.write_bytes(original)

    def test_missing_or_duplicate_sidecars(self):
        for kind, path in self.records.items():
            original = path.read_bytes()
            path.unlink()
            with self.subTest(kind=kind, condition="missing"), self.assertRaisesRegex(ValueError, "exactly one"):
                self.stage()
            path.write_bytes(original)
            extra = path.with_name(path.name.replace("sha256-", "sha256-0"))
            extra.write_bytes(original)
            with self.subTest(kind=kind, condition="duplicate"), self.assertRaisesRegex(ValueError, "exactly one"):
                self.stage()
            extra.unlink()


class PublishedProof(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.staged = Path(self.tmp.name)
        self.asset = pub.ASSETS[0]
        (self.staged / self.asset).write_bytes(b"new archive")
        (self.staged / "sidecar.json").write_bytes(b"record")
        (self.staged / "SHA256SUMS").write_bytes(b"inventory")
        self.old = "0" * 64
        self.new = pub.digest(self.staged / self.asset)
        self.reason = "fix Metal language selection"
        self.before = {"id": 1, "tag_name": "chrome/m158", "body": "release notes", "assets": [
            {"id": 2, "name": self.asset, "digest": "sha256:" + self.old},
            {"id": 3, "name": "other.zip", "digest": "sha256:" + "1" * 64}]}
        self.after = copy.deepcopy(self.before)
        self.after["assets"][0]["digest"] = "sha256:" + self.new
        self.after["assets"].append({"id": 4, "name": "sidecar.json", "digest": "sha256:" + pub.digest(self.staged / "sidecar.json")})
        from release_asset_guard import with_ledger
        self.after["body"] = with_ledger("release notes", [f"- {self.asset}: {self.old} -> {self.new}; {self.reason}"])

    def verify(self):
        pub.verify_published(self.before, self.after, self.staged, self.asset, self.reason, self.old)

    def test_complete_publication_passes(self):
        self.verify()

    def test_missing_ledger_fails_even_if_all_uploads_succeeded(self):
        self.after["body"] = "release notes"
        with self.assertRaisesRegex(ValueError, "ledger"):
            self.verify()

    def test_retry_still_requires_original_replacement_ledger(self):
        self.before["assets"][0]["digest"] = "sha256:" + self.new
        self.verify()
        self.after["body"] = "release notes"
        with self.assertRaisesRegex(ValueError, "ledger"):
            self.verify()

    def test_unknown_or_unapproved_prior_digest_fails_before_mutation(self):
        for value in (None, "sha256:" + "f" * 64):
            self.before["assets"][0]["digest"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "approved prior"):
                pub.check_destination(self.before, self.asset, self.old, self.new)

    def test_missing_asset_is_approved_for_immutable_backfill(self):
        before = copy.deepcopy(self.before)
        before["assets"].pop(0)
        pub.check_destination(before, self.asset, None, self.new)

    def test_changed_asset_is_rejected_without_replacement_input(self):
        with self.assertRaisesRegex(ValueError, "differs from both approved"):
            pub.check_destination(self.before, self.asset, None, self.new)

    def test_missing_or_changed_or_extra_assets_fail(self):
        baseline = copy.deepcopy(self.after)
        for change in ("missing", "digest", "id", "extra"):
            self.after = copy.deepcopy(baseline)
            if change == "missing":
                self.after["assets"].pop(1)
            elif change == "extra":
                self.after["assets"].append({"id": 9, "name": "surprise", "digest": "sha256:unknown"})
            else:
                self.after["assets"][1][change] = "wrong"
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify()

    def test_uploaded_digest_mismatch_fails(self):
        self.after["assets"][0]["digest"] = "sha256:" + self.old
        with self.assertRaisesRegex(ValueError, "published digest"):
            self.verify()

    def test_release_identity_change_fails(self):
        self.after["id"] = 10
        with self.assertRaisesRegex(ValueError, "identity"):
            self.verify()


class Workflow(unittest.TestCase):
    def test_privileged_job_uses_only_verified_current_run_artifact(self):
        workflow = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows/publish-apple-build.yml").read_text())
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        jobs = workflow["jobs"]
        for job in jobs.values():
            self.assertIn("github.ref == 'refs/heads/main'", job["if"])
            for step in job["steps"]:
                if "actions/checkout@" in step.get("uses", ""):
                    self.assertNotIn("ref", step["with"])
                    self.assertFalse(step["with"]["persist-credentials"])
        self.assertEqual(jobs["verify"]["permissions"]["contents"], "read")
        self.assertEqual(jobs["publish"]["permissions"], {"contents": "write"})
        self.assertEqual(jobs["publish"]["needs"], "verify")
        trigger = workflow.get("on", workflow[True])
        self.assertNotIn("previous_archive_sha256", trigger["workflow_dispatch"]["inputs"])
        downloads = [s for s in jobs["publish"]["steps"] if "actions/download-artifact@" in s.get("uses", "")]
        self.assertEqual(len(downloads), 1)
        self.assertNotIn("run-id", downloads[0]["with"])
        self.assertEqual(downloads[0]["with"]["name"], "verified-apple-publication")
        verify = "\n".join(s.get("run", "") for s in jobs["verify"]["steps"])
        for command in ("check_rebuild_run.py run", "check_rebuild_run.py same run.json run-after.json",
                        "check_rebuild_run.py same attempt.json attempt-after.json", "check_rebuild_run.py invocation",
                        "--source-digest", "--deny-self-hosted-runners", "write_legal_manifest.py", "write_apple_toolchain_receipt.py"):
            self.assertIn(command, verify)
        for job in jobs.values():
            for step in job["steps"]:
                self.assertNotIn("${{ inputs.", step.get("run", ""))
        publish = "\n".join(s.get("run", "") for s in jobs["publish"]["steps"])
        self.assertNotIn("check_destination", publish)
        self.assertIn("verify_published", publish)

    def test_publication_proof_accepts_a_new_asset_without_replacement_ledger(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        staged = Path(tmp.name)
        asset = pub.ASSETS[0]
        (staged / asset).write_bytes(b"new archive")
        (staged / "sidecar.json").write_bytes(b"record")
        before = {"id": 1, "tag_name": "chrome/m158", "body": "release notes", "assets": []}
        after = copy.deepcopy(before)
        after["assets"] = [
            {"id": 2, "name": asset, "digest": "sha256:" + pub.digest(staged / asset)},
            {"id": 3, "name": "sidecar.json", "digest": "sha256:" + pub.digest(staged / "sidecar.json")},
        ]
        pub.verify_published(before, after, staged, asset, "", None)


if __name__ == "__main__":
    unittest.main()
