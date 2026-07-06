#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

cat > "${TMP_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [ "$1" = "run" ] && [ "$2" = "view" ]; then
  cat <<'JOBS'
- [build-skia (windows-2022, win, gpu, x64, Release)](https://example.test/release)
- [build-skia (windows-2022, win, gpu, x64, Debug)](https://example.test/debug)
JOBS
  exit 0
fi

echo "unexpected gh call: $*" >&2
exit 1
EOF
chmod +x "${TMP_DIR}/gh"

output="$(
  GH_BIN="${TMP_DIR}/gh" \
  DRY_RUN=true \
  RELEASE_REPO=owner/repo \
  FAILED_RUN_ID=123456 \
  FAILED_RUN_URL=https://github.com/owner/repo/actions/runs/123456 \
  FAILED_RUN_NAME="Build Skia" \
  FAILED_HEAD_SHA=abc123 \
  FAILED_HEAD_BRANCH=main \
  SKIA_BRANCH=chrome/m151 \
  bash "${SCRIPT_DIR}/report-build-failure.sh"
)"

assert_contains() {
  local needle="$1"

  if [[ "$output" != *"$needle"* ]]; then
    echo "FAIL: missing '${needle}'" >&2
    echo "$output" >&2
    exit 1
  fi
}

assert_contains "Dry run: would report failed Skia update for chrome/m151."
assert_contains "Skia auto-update failed: chrome/m151"
assert_contains "build-skia (windows-2022, win, gpu, x64, Release)"
assert_contains "@codex fix the CI failures for \`chrome/m151\`."
assert_contains "GitHub REST job-log endpoint"
assert_contains "apple_runner=macos-15-intel"
assert_contains "Do not publish a release manually."

cat > "${TMP_DIR}/gh-disabled-issues" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [ "$1" = "api" ] && [ "$2" = "repos/owner/repo" ] && [ "${3:-}" = "--jq" ]; then
  echo "false"
  exit 0
fi

echo "unexpected gh call: $*" >&2
exit 1
EOF
chmod +x "${TMP_DIR}/gh-disabled-issues"

source "${SCRIPT_DIR}/report-build-failure.sh"

GH_BIN="${TMP_DIR}/gh-disabled-issues"
RELEASE_REPO=owner/repo
issue_output="$(ensure_issue chrome/m151 /dev/null 2>&1)"
if [[ "$issue_output" != *"Issues are disabled for owner/repo; skipping issue handoff."* ]]; then
  echo "FAIL: disabled issues should be skipped" >&2
  echo "$issue_output" >&2
  exit 1
fi

cat > "${TMP_DIR}/gh-existing-pr" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [ "$1" = "pr" ] && [ "$2" = "list" ]; then
  echo "https://github.com/owner/repo/pull/12"
  exit 0
fi

if [ "$1" = "pr" ] && [ "$2" = "comment" ]; then
  cat "$5" > "${COMMENT_CAPTURE}"
  exit 0
fi

echo "unexpected gh call: $*" >&2
exit 1
EOF
chmod +x "${TMP_DIR}/gh-existing-pr"

report_file="${TMP_DIR}/report.md"
prompt_file="${TMP_DIR}/prompt.md"
comment_capture="${TMP_DIR}/comment.md"
echo "report body" > "$report_file"
echo "@codex fix the CI failures for chrome/m151." > "$prompt_file"

GH_BIN="${TMP_DIR}/gh-existing-pr"
RELEASE_REPO=owner/repo
FAILED_RUN_ID=123456
FAILED_HEAD_BRANCH=main
COMMENT_CAPTURE="$comment_capture"
export COMMENT_CAPTURE
pr_output="$(create_codex_pr chrome/m151 "$report_file" "$prompt_file" chrome-m151)"

if [ "$pr_output" != "https://github.com/owner/repo/pull/12" ]; then
  echo "FAIL: existing PR URL should be reused" >&2
  echo "$pr_output" >&2
  exit 1
fi

if [[ "$(cat "$comment_capture")" != *"@codex fix the CI failures"* ]]; then
  echo "FAIL: existing PR should receive Codex prompt comment" >&2
  cat "$comment_capture" >&2
  exit 1
fi

echo "report-build-failure tests passed"
