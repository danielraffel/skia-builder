#!/usr/bin/env python3
"""Prove a per-cell Sigstore bundle covers the exact files published beside it.

``attest-native`` and ``attest-apple`` copy one bundle per cell as
``<archive stem>.provenance-attestation.sha256-<digest>.sigstore.json``.
Before a job publishes that copy next to an archive and its records, this
checks that

* the file carries its own sha256 in its name and is named for the archive;
* it is a DSSE-wrapped in-toto statement;
* its subjects list every given file by name with that file's sha256.

It does not verify the Sigstore signature; consumers do that with
``gh attestation verify``.  It proves the bundle is the one that attested
these bytes, so a stale or mismatched bundle is never published.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

BUNDLE_RE = re.compile(r"^(?P<stem>.+)\.provenance-attestation\.sha256-(?P<digest>[0-9a-f]{64})\.sigstore\.json$")
IN_TOTO = "application/vnd.in-toto+json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle_subjects(data: bytes) -> dict[str, str]:
    """``{name: sha256}`` of the in-toto statement inside a Sigstore bundle."""
    bundle = json.loads(data.decode("utf-8"))
    envelope = bundle.get("dsseEnvelope") or {}
    if envelope.get("payloadType") != IN_TOTO:
        raise ValueError(f"payloadType {envelope.get('payloadType')!r} is not {IN_TOTO}")
    if not envelope.get("signatures"):
        raise ValueError("the envelope carries no signature")
    statement = json.loads(base64.b64decode(envelope.get("payload") or "", validate=True))
    subjects: dict[str, str] = {}
    for subject in statement.get("subject") or []:
        name, digest = subject.get("name"), (subject.get("digest") or {}).get("sha256")
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ValueError(f"malformed subject {subject!r}")
        subjects[name] = digest
    if not subjects:
        raise ValueError("the statement has no subjects")
    return subjects


def problems_for(bundle: Path, archive: Path, records: list[Path]) -> list[str]:
    match = BUNDLE_RE.match(bundle.name)
    data = bundle.read_bytes()
    problems = []
    if not match:
        return [f"{bundle.name} is not a content-addressed attestation bundle name"]
    if match["digest"] != hashlib.sha256(data).hexdigest():
        problems.append(f"{bundle.name} does not carry its own sha256")
    if match["stem"] != archive.name.removesuffix(".zip"):
        problems.append(f"{bundle.name} is not the bundle for {archive.name}")
    try:
        subjects = bundle_subjects(data)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return problems + [f"{bundle.name}: {error}"]
    for path in (archive, *records):
        actual = sha256_file(path)
        if subjects.get(path.name) != actual:
            problems.append(f"{bundle.name} does not attest {path.name} at {actual} "
                            f"(attested {subjects.get(path.name)!r})")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("records", type=Path, nargs="+", help="the provenance records published beside it")
    args = parser.parse_args(argv)
    problems = problems_for(args.bundle, args.archive, args.records)
    for problem in problems:
        print(f"attestation-bundle: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"attestation-bundle: {args.bundle.name} attests {args.archive.name} and {len(args.records)} record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
