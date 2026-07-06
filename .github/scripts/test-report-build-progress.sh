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

if [ "$1" = "api" ] && [ "$2" = "repos/owner/repo" ]; then
  if [ "${3:-}" = "--jq" ]; then
    echo "main"
    exit 0
  fi
fi

if [ "$1" = "api" ] && [ "$2" = "repos/owner/repo/actions/runs/28808354972" ]; then
  cat <<'JSON'
{
  "id": 28808354972,
  "status": "queued",
  "conclusion": null,
  "html_url": "https://github.com/owner/repo/actions/runs/28808354972",
  "head_sha": "026cda9",
  "head_branch": "main",
  "name": "Build Skia",
  "created_at": "2026-07-06T16:52:47Z",
  "updated_at": "2026-07-06T18:28:05Z"
}
JSON
  exit 0
fi

if [ "$1" = "api" ] && [ "$2" = "repos/owner/repo/actions/runs/28808354972/jobs?per_page=100" ]; then
  cat <<'JSON'
{
  "jobs": [
    {
      "name": "build-skia (windows-2022, win, gpu, x64, Release)",
      "status": "completed",
      "conclusion": "failure",
      "html_url": "https://github.com/owner/repo/actions/runs/28808354972/job/1"
    },
    {
      "name": "build-skia (macos-15, mac, gpu, arm64)",
      "status": "queued",
      "conclusion": null,
      "html_url": "https://github.com/owner/repo/actions/runs/28808354972/job/2"
    }
  ]
}
JSON
  exit 0
fi

if [ "$1" = "run" ] && [ "$2" = "view" ]; then
  echo "unexpected run view fallback" >&2
  exit 1
fi

echo "unexpected gh call: $*" >&2
exit 1
EOF
chmod +x "${TMP_DIR}/gh"

output="$(
  GH_BIN="${TMP_DIR}/gh" \
  DRY_RUN=true \
  RELEASE_REPO=owner/repo \
  WATCH_RUN_ID=28808354972 \
  SKIA_BRANCH=chrome/m151 \
  bash "${SCRIPT_DIR}/report-build-progress.sh"
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
assert_contains "failed matrix job before workflow completion"
assert_contains "Run status when reported: \`queued\`"
assert_contains "build-skia (windows-2022, win, gpu, x64, Release)"
assert_contains "GitHub REST job-log endpoint"
assert_contains "@codex fix the CI failures for \`chrome/m151\`."

echo "report-build-progress tests passed"
