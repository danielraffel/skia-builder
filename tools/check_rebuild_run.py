#!/usr/bin/env python3
"""Decide whether a build-skia.yml run may be rebound, and bind its attestation to it.

rebind-provenance.yml turns a rebuild's records into records for a published
archive and attests them as rebind-provenance.yml@main. A branch run can
carry edited tools, so only one kind of run is acceptable, and everything
about it is read from the GitHub API, never from dispatch inputs:

``run``         the run is this repository's build-skia.yml, dispatched on
                main, and the requested attempt is its latest and succeeded.
                Writes ``ref`` and ``head_sha`` for later steps.
``same``        the run and attempt read again after the artifacts were
                downloaded are the ones that were checked (no rerun replaced
                the artifacts in between).
``invocation``  each ``gh attestation verify --format json`` result was signed
                by that run's attempt: the certificate's run invocation is
                runs/<id>/attempts/<attempt>, its source digest is the run's
                head commit, and it ran on a GitHub-hosted runner.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKFLOW_PATH = ".github/workflows/build-skia.yml"
STABLE_FIELDS = ("id", "run_attempt", "head_sha", "head_branch", "event", "path",
                 "status", "conclusion")


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def run_problems(run: dict, attempt: dict, repository: str, requested_attempt: int) -> list[str]:
    problems = []
    if run.get("path") != WORKFLOW_PATH:
        problems.append(f"run is {run.get('path')!r}, not {WORKFLOW_PATH}")
    if run.get("head_branch") != "main" or run.get("event") != "workflow_dispatch":
        problems.append(f"run is a {run.get('event')} on {run.get('head_branch')!r}, not a dispatch on main")
    if (run.get("head_repository") or {}).get("full_name") != repository:
        problems.append("run is from another repository")
    if run.get("run_attempt") != requested_attempt:
        problems.append(f"attempt {requested_attempt} is not the run's latest ({run.get('run_attempt')})")
    if attempt.get("id") != run.get("id") or attempt.get("run_attempt") != requested_attempt:
        problems.append("attempt record does not belong to this run and attempt")
    if attempt.get("status") != "completed" or attempt.get("conclusion") != "success":
        problems.append(f"attempt concluded {attempt.get('conclusion')!r}")
    if attempt.get("head_sha") != run.get("head_sha"):
        problems.append("attempt head commit differs from the run's")
    return problems


def same_problems(before: dict, after: dict) -> list[str]:
    return [f"{field} changed from {before.get(field)!r} to {after.get(field)!r} while downloading"
            for field in STABLE_FIELDS if before.get(field) != after.get(field)]


def invocation_problems(results: object, repository: str, run_id: int, attempt: int,
                        head_sha: str) -> list[str]:
    if not isinstance(results, list) or not results:
        return ["gh attestation verify returned no verified attestation"]
    expected = f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{attempt}"
    problems = []
    for index, result in enumerate(results):
        certificate = (((result or {}).get("verificationResult") or {}).get("signature") or {}).get(
            "certificate") or {}
        if certificate.get("runInvocationURI") != expected:
            problems.append(f"attestation {index} was signed by {certificate.get('runInvocationURI')!r}, "
                            f"not {expected}")
        if certificate.get("sourceRepositoryDigest") != head_sha:
            problems.append(f"attestation {index} source digest {certificate.get('sourceRepositoryDigest')!r} "
                            f"is not the run's head {head_sha}")
        if certificate.get("runnerEnvironment") != "github-hosted":
            problems.append(f"attestation {index} ran on {certificate.get('runnerEnvironment')!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("run_json", type=Path)
    run.add_argument("attempt_json", type=Path)
    run.add_argument("--repository", required=True)
    run.add_argument("--attempt", type=int, required=True)
    run.add_argument("--github-output", type=Path)
    same = sub.add_parser("same")
    same.add_argument("before", type=Path)
    same.add_argument("after", type=Path)
    invocation = sub.add_parser("invocation")
    invocation.add_argument("verify_json", type=Path)
    invocation.add_argument("--repository", required=True)
    invocation.add_argument("--run-id", type=int, required=True)
    invocation.add_argument("--attempt", type=int, required=True)
    invocation.add_argument("--head-sha", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            run_record = load(args.run_json)
            problems = run_problems(run_record, load(args.attempt_json), args.repository, args.attempt)
            if not problems and args.github_output:
                with args.github_output.open("a", encoding="utf-8") as out:
                    out.write("ref=refs/heads/main\n")
                    out.write(f"head_sha={run_record['head_sha']}\n")
        elif args.command == "same":
            problems = same_problems(load(args.before), load(args.after))
        else:
            problems = invocation_problems(load(args.verify_json), args.repository, args.run_id,
                                           args.attempt, args.head_sha)
    except (OSError, ValueError) as error:
        problems = [str(error)]
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
