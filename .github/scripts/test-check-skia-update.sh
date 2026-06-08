#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=check-skia-update.sh
source "${SCRIPT_DIR}/check-skia-update.sh"

FIXTURE_REFS=$'1111111\trefs/heads/chrome/m148\n2222222\trefs/heads/chrome/m149\n3333333\trefs/heads/chrome/m150\n4444444\trefs/heads/chrome/not-a-milestone\n5555555\trefs/heads/chrome/m90'
EXISTING_RELEASES="chrome/m150"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_equal() {
  local expected="$1"
  local actual="$2"
  local label="$3"

  if [ "$expected" != "$actual" ]; then
    fail "${label}: expected '${expected}', got '${actual}'"
  fi
}

output_value() {
  local output_file="$1"
  local name="$2"

  grep -E "^${name}=" "$output_file" | tail -1 | cut -d= -f2-
}

list_skia_refs() {
  printf '%s\n' "$FIXTURE_REFS"
}

skia_branch_exists() {
  local skia_branch="$1"
  printf '%s\n' "$FIXTURE_REFS" |
    awk '{ print $2 }' |
    grep -qx "refs/heads/${skia_branch}"
}

release_notes_exist() {
  local release_notes_url="$1"
  [[ "$release_notes_url" =~ ^https://raw\.githubusercontent\.com/google/skia/chrome/m[0-9]+/RELEASE_NOTES\.md$ ]]
}

release_exists() {
  local skia_branch="$1"
  [[ " ${EXISTING_RELEASES} " == *" ${skia_branch} "* ]]
}

run_decision() {
  local requested_branch="$1"
  local output_file="$2"

  REQUESTED_SKIA_BRANCH="$requested_branch"
  RELEASE_REPO="owner/repo"
  GITHUB_OUTPUT="$output_file"
  main >/dev/null
}

test_latest_parser_sorts_numerically() {
  local latest
  latest="$(printf '%s\n' "$FIXTURE_REFS" | parse_latest_skia_branch)"
  assert_equal "chrome/m150" "$latest" "latest parser"
}

test_latest_existing_release_does_not_dispatch() {
  local output_file
  output_file="$(mktemp)"

  run_decision "" "$output_file"

  assert_equal "chrome/m150" "$(output_value "$output_file" skia_branch)" "latest existing branch"
  assert_equal "true" "$(output_value "$output_file" release_exists)" "latest existing release"
  assert_equal "false" "$(output_value "$output_file" should_dispatch)" "latest existing dispatch"

  rm -f "$output_file"
}

test_requested_missing_release_dispatches() {
  local output_file
  output_file="$(mktemp)"

  run_decision "chrome/m148" "$output_file"

  assert_equal "chrome/m148" "$(output_value "$output_file" skia_branch)" "requested branch"
  assert_equal "false" "$(output_value "$output_file" release_exists)" "requested release"
  assert_equal "true" "$(output_value "$output_file" should_dispatch)" "requested dispatch"

  rm -f "$output_file"
}

test_new_upstream_milestone_dispatches() {
  local output_file
  local original_refs

  output_file="$(mktemp)"
  original_refs="$FIXTURE_REFS"

  FIXTURE_REFS="${FIXTURE_REFS}"$'\n6666666\trefs/heads/chrome/m151'
  run_decision "" "$output_file"

  assert_equal "chrome/m151" "$(output_value "$output_file" skia_branch)" "new upstream branch"
  assert_equal "false" "$(output_value "$output_file" release_exists)" "new upstream release"
  assert_equal "true" "$(output_value "$output_file" should_dispatch)" "new upstream dispatch"

  FIXTURE_REFS="$original_refs"
  rm -f "$output_file"
}

test_invalid_requested_branch_fails() {
  local output_file
  output_file="$(mktemp)"

  if (
    REQUESTED_SKIA_BRANCH="main"
    RELEASE_REPO="owner/repo"
    GITHUB_OUTPUT="$output_file"
    main >/dev/null 2>&1
  ); then
    fail "invalid requested branch should fail"
  fi

  rm -f "$output_file"
}

test_latest_parser_sorts_numerically
test_latest_existing_release_does_not_dispatch
test_requested_missing_release_dispatches
test_new_upstream_milestone_dispatches
test_invalid_requested_branch_fails

echo "check-skia-update tests passed"
