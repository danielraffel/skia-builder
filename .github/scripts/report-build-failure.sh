#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GH_BIN="${GH_BIN:-gh}"
RELEASE_REPO="${RELEASE_REPO:-${GITHUB_REPOSITORY:-}}"
FAILED_RUN_ID="${FAILED_RUN_ID:-}"
FAILED_RUN_URL="${FAILED_RUN_URL:-}"
FAILED_RUN_NAME="${FAILED_RUN_NAME:-Build Skia}"
FAILED_HEAD_SHA="${FAILED_HEAD_SHA:-}"
FAILED_HEAD_BRANCH="${FAILED_HEAD_BRANCH:-main}"
FAILED_RUN_STATUS="${FAILED_RUN_STATUS:-unknown}"
FAILED_RUN_CREATED_AT="${FAILED_RUN_CREATED_AT:-}"
FAILED_RUN_UPDATED_AT="${FAILED_RUN_UPDATED_AT:-}"
FAILED_JOBS_MARKDOWN="${FAILED_JOBS_MARKDOWN:-}"
FAILURE_REASON="${FAILURE_REASON:-completed workflow failure}"
SKIA_BRANCH="${SKIA_BRANCH:-}"
DRY_RUN="${DRY_RUN:-false}"

die() {
  echo "$*" >&2
  exit 1
}

safe_ref_component() {
  printf '%s' "$1" | tr '/[:upper:]' '-[:lower:]' | tr -cd 'a-z0-9._-'
}

output_value() {
  local output_file="$1"
  local name="$2"

  grep -E "^${name}=" "$output_file" | tail -1 | cut -d= -f2-
}

resolve_skia_branch() {
  if [ -n "$SKIA_BRANCH" ]; then
    printf '%s\n' "$SKIA_BRANCH"
    return
  fi

  local output_file
  output_file="$(mktemp)"
  RELEASE_REPO="$RELEASE_REPO" GITHUB_OUTPUT="$output_file" bash "${SCRIPT_DIR}/check-skia-update.sh" >/dev/null
  output_value "$output_file" skia_branch
  rm -f "$output_file"
}

failed_jobs_markdown() {
  if [ -n "$FAILED_JOBS_MARKDOWN" ]; then
    printf '%s\n' "$FAILED_JOBS_MARKDOWN"
    return
  fi

  if [ -z "$FAILED_RUN_ID" ]; then
    echo "- Failed run ID was not provided."
    return
  fi

  if ! "$GH_BIN" run view "$FAILED_RUN_ID" \
    --repo "$RELEASE_REPO" \
    --json jobs \
    --jq '.jobs[] | select(.conclusion == "failure") | "- [" + .name + "](" + .url + ")"'; then
    echo "- Failed job list could not be fetched. Inspect the run URL."
  fi
}

write_report() {
  local report_file="$1"
  local skia_branch="$2"
  local failed_jobs="$3"

  cat > "$report_file" <<EOF
# Skia auto-update failed: ${skia_branch}

The automated Skia update detected \`${skia_branch}\`, dispatched \`${FAILED_RUN_NAME}\`, and the build needs attention before a release can be published.

- Failed run: ${FAILED_RUN_URL}
- Failing head branch: \`${FAILED_HEAD_BRANCH}\`
- Failing head SHA: \`${FAILED_HEAD_SHA}\`
- Target Skia branch: \`${skia_branch}\`
- Run status when reported: \`${FAILED_RUN_STATUS}\`
- Detection reason: \`${FAILURE_REASON}\`
- Created at: \`${FAILED_RUN_CREATED_AT:-unknown}\`
- Updated at: \`${FAILED_RUN_UPDATED_AT:-unknown}\`

## Failed or stalled jobs

${failed_jobs}

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the \`${skia_branch}\` build.
3. Let the normal \`Build Skia\` workflow publish the release after the fix merges.

EOF
}

write_codex_prompt() {
  local prompt_file="$1"
  local skia_branch="$2"
  local failed_jobs="$3"

  cat > "$prompt_file" <<EOF
@codex fix the CI failures for \`${skia_branch}\`.

The Skia auto-update build failed here:
${FAILED_RUN_URL}

Run status when reported: \`${FAILED_RUN_STATUS}\`
Detection reason: \`${FAILURE_REASON}\`

Failed or stalled jobs:
${failed_jobs}

Please focus on the failing or stalled jobs, make the smallest repo change needed, and push the fix to this PR branch. If the workflow is still running, inspect completed failed jobs through the GitHub REST job-log endpoint because \`gh run view --log-failed\` may wait for the whole workflow to complete. Do not publish a release manually.
EOF
}

ensure_issue() {
  local skia_branch="$1"
  local report_file="$2"
  local issue_number
  local issue_url
  local has_issues

  if ! has_issues="$("$GH_BIN" api "repos/${RELEASE_REPO}" --jq '.has_issues' 2>/dev/null)"; then
    echo "Could not determine whether issues are enabled for ${RELEASE_REPO}; skipping issue handoff." >&2
    return 0
  fi

  if [ "$has_issues" != "true" ]; then
    echo "Issues are disabled for ${RELEASE_REPO}; skipping issue handoff." >&2
    return 0
  fi

  "$GH_BIN" label create auto-update-failed \
    --repo "$RELEASE_REPO" \
    --description "Automated dependency update failed" \
    --color d73a4a \
    --force >/dev/null 2>&1 || true

  if ! issue_number="$("$GH_BIN" issue list \
    --repo "$RELEASE_REPO" \
    --state open \
    --search "Skia auto-update failed: ${skia_branch} in:title" \
    --json number \
    --jq '.[0].number // ""')"; then
    echo "Could not list existing auto-update issues; skipping issue handoff." >&2
    return 0
  fi

  if [ -n "$issue_number" ]; then
    if ! "$GH_BIN" issue comment "$issue_number" --repo "$RELEASE_REPO" --body-file "$report_file" >/dev/null; then
      echo "Could not comment on issue #${issue_number}; skipping issue handoff." >&2
      return 0
    fi
  else
    if ! issue_url="$("$GH_BIN" issue create \
      --repo "$RELEASE_REPO" \
      --title "Skia auto-update failed: ${skia_branch}" \
      --label auto-update-failed \
      --body-file "$report_file")"; then
      echo "Could not create auto-update issue; skipping issue handoff." >&2
      return 0
    fi
    issue_number="${issue_url##*/}"
  fi

  printf '%s\n' "$issue_number"
}

existing_codex_pr_url() {
  local branch="$1"
  local repo_owner="${RELEASE_REPO%%/*}"
  local pr_url

  for head in "$branch" "${repo_owner}:${branch}"; do
    if ! pr_url="$("$GH_BIN" pr list \
      --repo "$RELEASE_REPO" \
      --head "$head" \
      --state open \
      --json url \
      --jq '.[0].url // ""' 2>/dev/null)"; then
      pr_url=""
    fi

    if [ -n "$pr_url" ]; then
      printf '%s\n' "$pr_url"
      return
    fi
  done
}

create_codex_pr() {
  local skia_branch="$1"
  local report_file="$2"
  local prompt_file="$3"
  local safe_branch="$4"
  local branch="codex/skia-auto-fix-${safe_branch}-${FAILED_RUN_ID:-manual}"
  local marker=".github/codex-failures/skia-auto-fix-${safe_branch}-${FAILED_RUN_ID:-manual}.md"
  local pr_url

  pr_url="$(existing_codex_pr_url "$branch")"
  if [ -n "$pr_url" ]; then
    "$GH_BIN" pr comment "$pr_url" --body-file "$prompt_file" >/dev/null
    printf '%s\n' "$pr_url"
    return
  fi

  if git ls-remote --exit-code origin "refs/heads/${branch}" >/dev/null 2>&1; then
    pr_url="$("$GH_BIN" pr create \
      --repo "$RELEASE_REPO" \
      --base "$FAILED_HEAD_BRANCH" \
      --head "$branch" \
      --title "Fix Skia auto-update failure: ${skia_branch}" \
      --body-file "$report_file")"
    "$GH_BIN" pr comment "$pr_url" --body-file "$prompt_file" >/dev/null
    printf '%s\n' "$pr_url"
    return
  fi

  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git switch -C "$branch"
  mkdir -p "$(dirname "$marker")"
  cp "$report_file" "$marker"
  git add "$marker"
  git commit -m "Report Skia auto-update failure for ${skia_branch}"
  git push origin "$branch"

  pr_url="$("$GH_BIN" pr create \
    --repo "$RELEASE_REPO" \
    --base "$FAILED_HEAD_BRANCH" \
    --head "$branch" \
    --title "Fix Skia auto-update failure: ${skia_branch}" \
    --body-file "$report_file")"

  "$GH_BIN" pr comment "$pr_url" --body-file "$prompt_file" >/dev/null
  printf '%s\n' "$pr_url"
}

main() {
  if [ -z "$RELEASE_REPO" ]; then
    die "RELEASE_REPO or GITHUB_REPOSITORY must be set."
  fi

  local skia_branch
  local safe_branch
  local failed_jobs
  local report_file
  local prompt_file

  skia_branch="$(resolve_skia_branch)"
  if [ -z "$skia_branch" ]; then
    die "Could not resolve Skia branch for failed build."
  fi

  safe_branch="$(safe_ref_component "$skia_branch")"
  failed_jobs="$(failed_jobs_markdown)"
  report_file="$(mktemp)"
  prompt_file="$(mktemp)"

  write_report "$report_file" "$skia_branch" "$failed_jobs"
  write_codex_prompt "$prompt_file" "$skia_branch" "$failed_jobs"

  if [ "$DRY_RUN" = "true" ]; then
    echo "Dry run: would report failed Skia update for ${skia_branch}."
    echo
    cat "$report_file"
    echo
    echo "## Codex prompt"
    cat "$prompt_file"
    rm -f "$report_file" "$prompt_file"
    return
  fi

  local issue_number
  local pr_url
  issue_number="$(ensure_issue "$skia_branch" "$report_file")"
  pr_url="$(create_codex_pr "$skia_branch" "$report_file" "$prompt_file" "$safe_branch")"

  {
    echo "## Build Failure Watchdog"
    echo
    if [ -n "$issue_number" ]; then
      echo "- Issue: #${issue_number}"
    else
      echo "- Issue: skipped"
    fi
    echo "- Codex PR: ${pr_url}"
    echo "- Skia branch: \`${skia_branch}\`"
  } >> "${GITHUB_STEP_SUMMARY:-/dev/stdout}"

  rm -f "$report_file" "$prompt_file"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
