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
assert_contains "Do not publish a release manually."

echo "report-build-failure tests passed"

