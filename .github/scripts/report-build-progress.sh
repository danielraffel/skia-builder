#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GH_BIN="${GH_BIN:-gh}"
RELEASE_REPO="${RELEASE_REPO:-${GITHUB_REPOSITORY:-}}"
BUILD_WORKFLOW_FILE="${BUILD_WORKFLOW_FILE:-build-skia.yml}"
BUILD_WORKFLOW_NAME="${BUILD_WORKFLOW_NAME:-Build Skia}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-}"
WATCH_RUN_ID="${WATCH_RUN_ID:-}"
STALE_MINUTES="${STALE_MINUTES:-90}"
ACTIVE_STALE_MINUTES="${ACTIVE_STALE_MINUTES:-240}"
MAX_RUNS="${MAX_RUNS:-10}"
DRY_RUN="${DRY_RUN:-false}"

die() {
  echo "$*" >&2
  exit 1
}

api() {
  "$GH_BIN" api "$@"
}

iso_epoch() {
  python3 - "$1" <<'PY'
import datetime
import sys

value = sys.argv[1]
if not value:
    print(0)
    raise SystemExit

if value.endswith("Z"):
    value = value[:-1] + "+00:00"
print(int(datetime.datetime.fromisoformat(value).timestamp()))
PY
}

runs_to_tsv() {
  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
runs = payload.get("workflow_runs")
if runs is None:
    runs = [payload]

def field(value):
    return str(value) if value not in (None, "") else "__EMPTY__"

for run in runs:
    print("\t".join([
        field(run.get("id")),
        field(run.get("status")),
        field(run.get("conclusion")),
        field(run.get("html_url")),
        field(run.get("head_sha")),
        field(run.get("head_branch")),
        field(run.get("name") or run.get("display_title")),
        field(run.get("created_at")),
        field(run.get("updated_at")),
    ]))
'
}

jobs_summary() {
  python3 -c '
import json
import sys
import datetime

now_epoch = int(sys.argv[1])
stale_minutes = int(sys.argv[2])
active_stale_minutes = int(sys.argv[3])

payload = json.load(sys.stdin)
jobs = payload.get("jobs", [])
failed = [job for job in jobs if job.get("conclusion") == "failure"]
queued = [job for job in jobs if job.get("status") == "queued"]
in_progress = [job for job in jobs if job.get("status") == "in_progress"]
completed = [job for job in jobs if job.get("status") == "completed"]

def iso_epoch(value):
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return int(datetime.datetime.fromisoformat(value).timestamp())

if failed:
    markdown = "\n".join(
        "- [{}]({})".format(job.get("name"), job.get("html_url"))
        for job in failed
    )
else:
    markdown = ""

stale_queued = []
for job in queued:
    queued_at = job.get("created_at") or job.get("started_at")
    queued_epoch = iso_epoch(queued_at)
    if queued_epoch is None:
        continue
    age_minutes = (now_epoch - queued_epoch) // 60
    if age_minutes >= stale_minutes:
        stale_queued.append((job, age_minutes))

if stale_queued:
    stale_markdown = "\n".join(
        "- [{}]({}) queued for {} minutes".format(
            job.get("name"), job.get("html_url"), age_minutes
        )
        for job, age_minutes in stale_queued
    )
else:
    stale_markdown = ""

stale_running = []
for job in in_progress:
    started_epoch = iso_epoch(job.get("started_at") or job.get("created_at"))
    if started_epoch is None:
        continue
    age_minutes = (now_epoch - started_epoch) // 60
    if age_minutes >= active_stale_minutes:
        stale_running.append((job, age_minutes))

if stale_running:
    stale_running_markdown = "\n".join(
        "- [{}]({}) in progress for {} minutes".format(
            job.get("name"), job.get("html_url"), age_minutes
        )
        for job, age_minutes in stale_running
    )
else:
    stale_running_markdown = ""

print(json.dumps({
    "failed_count": len(failed),
    "queued_count": len(queued),
    "in_progress_count": len(in_progress),
    "completed_count": len(completed),
    "total_count": len(jobs),
    "failed_jobs_markdown": markdown,
    "stale_queued_count": len(stale_queued),
    "stale_queued_jobs_markdown": stale_markdown,
    "stale_running_count": len(stale_running),
    "stale_running_jobs_markdown": stale_running_markdown,
}))
' "$1" "$2" "$3"
}

json_field() {
  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
value = payload
for part in sys.argv[1].split("."):
    value = value.get(part) if isinstance(value, dict) else None
print("" if value is None else value)
' "$1"
}

report_run() {
  local run_id="$1"
  local status="$2"
  local conclusion="$3"
  local html_url="$4"
  local head_sha="$5"
  local head_branch="$6"
  local run_name="$7"
  local created_at="$8"
  local updated_at="$9"
  local reason="${10}"
  local failed_jobs_markdown="${11}"

  FAILURE_REASON="$reason" \
    FAILED_RUN_STATUS="${status}${conclusion:+/${conclusion}}" \
    FAILED_RUN_CREATED_AT="$created_at" \
    FAILED_RUN_UPDATED_AT="$updated_at" \
    FAILED_JOBS_MARKDOWN="$failed_jobs_markdown" \
    FAILED_RUN_ID="$run_id" \
    FAILED_RUN_URL="$html_url" \
    FAILED_RUN_NAME="${run_name:-$BUILD_WORKFLOW_NAME}" \
    FAILED_HEAD_SHA="$head_sha" \
    FAILED_HEAD_BRANCH="${head_branch:-$DEFAULT_BRANCH}" \
    RELEASE_REPO="$RELEASE_REPO" \
    GH_BIN="$GH_BIN" \
    DRY_RUN="$DRY_RUN" \
    bash "${SCRIPT_DIR}/report-build-failure.sh"
}

main() {
  if [ -z "$RELEASE_REPO" ]; then
    die "RELEASE_REPO or GITHUB_REPOSITORY must be set."
  fi

  if [ -z "$DEFAULT_BRANCH" ]; then
    DEFAULT_BRANCH="$(api "repos/${RELEASE_REPO}" --jq '.default_branch')"
  fi

  local runs_json
  if [ -n "$WATCH_RUN_ID" ]; then
    runs_json="$(api "repos/${RELEASE_REPO}/actions/runs/${WATCH_RUN_ID}")"
  else
    runs_json="$(api "repos/${RELEASE_REPO}/actions/workflows/${BUILD_WORKFLOW_FILE}/runs?branch=${DEFAULT_BRANCH}&per_page=${MAX_RUNS}")"
  fi

  local now_epoch
  now_epoch="${NOW_EPOCH:-$(date -u +%s)}"

  local reported=0
  while IFS=$'\t' read -r run_id status conclusion html_url head_sha head_branch run_name created_at updated_at; do
    [ -n "$run_id" ] || continue
    [ "$conclusion" = "__EMPTY__" ] && conclusion=""
    [ "$html_url" = "__EMPTY__" ] && html_url=""
    [ "$head_sha" = "__EMPTY__" ] && head_sha=""
    [ "$head_branch" = "__EMPTY__" ] && head_branch=""
    [ "$run_name" = "__EMPTY__" ] && run_name=""
    [ "$created_at" = "__EMPTY__" ] && created_at=""
    [ "$updated_at" = "__EMPTY__" ] && updated_at=""

    [ "$head_branch" = "$DEFAULT_BRANCH" ] || continue

    if [ "$status" = "completed" ] && [ "$conclusion" != "failure" ]; then
      continue
    fi

    local jobs_json
    local summary
    local failed_count
    local failed_jobs_markdown
    local stale_queued_count
    local stale_queued_jobs_markdown
    local stale_running_count
    local stale_running_jobs_markdown
    jobs_json="$(api "repos/${RELEASE_REPO}/actions/runs/${run_id}/jobs?per_page=100")"
    summary="$(printf '%s' "$jobs_json" | jobs_summary "$now_epoch" "$STALE_MINUTES" "$ACTIVE_STALE_MINUTES")"
    failed_count="$(printf '%s' "$summary" | json_field failed_count)"
    failed_jobs_markdown="$(printf '%s' "$summary" | json_field failed_jobs_markdown)"
    stale_queued_count="$(printf '%s' "$summary" | json_field stale_queued_count)"
    stale_queued_jobs_markdown="$(printf '%s' "$summary" | json_field stale_queued_jobs_markdown)"
    stale_running_count="$(printf '%s' "$summary" | json_field stale_running_count)"
    stale_running_jobs_markdown="$(printf '%s' "$summary" | json_field stale_running_jobs_markdown)"

    if [ "$failed_count" -gt 0 ]; then
      report_run "$run_id" "$status" "$conclusion" "$html_url" "$head_sha" "$head_branch" "$run_name" "$created_at" "$updated_at" "failed matrix job before workflow completion" "$failed_jobs_markdown"
      reported=$((reported + 1))
      continue
    fi

    if [ "$stale_queued_count" -gt 0 ]; then
      report_run "$run_id" "$status" "$conclusion" "$html_url" "$head_sha" "$head_branch" "$run_name" "$created_at" "$updated_at" "stale queued matrix job for at least ${STALE_MINUTES} minutes" "$stale_queued_jobs_markdown"
      reported=$((reported + 1))
      continue
    fi

    if [ "$stale_running_count" -gt 0 ]; then
      report_run "$run_id" "$status" "$conclusion" "$html_url" "$head_sha" "$head_branch" "$run_name" "$created_at" "$updated_at" "stale in-progress matrix job for at least ${ACTIVE_STALE_MINUTES} minutes" "$stale_running_jobs_markdown"
      reported=$((reported + 1))
      continue
    fi

    if [ "$status" = "pending" ] || [ "$status" = "queued" ]; then
      local created_epoch
      local age_minutes
      created_epoch="$(iso_epoch "$created_at")"
      age_minutes=$(((now_epoch - created_epoch) / 60))
      if [ "$age_minutes" -ge "$STALE_MINUTES" ]; then
        report_run "$run_id" "$status" "$conclusion" "$html_url" "$head_sha" "$head_branch" "$run_name" "$created_at" "$updated_at" "stale ${status} workflow for ${age_minutes} minutes" "- No failed jobs were available yet. The workflow stayed \`${status}\` for ${age_minutes} minutes."
        reported=$((reported + 1))
      fi
    fi
  done < <(printf '%s' "$runs_json" | runs_to_tsv)

  if [ "$reported" -eq 0 ]; then
    echo "No in-progress failed or stale ${BUILD_WORKFLOW_NAME} runs found."
  fi
}

main "$@"
