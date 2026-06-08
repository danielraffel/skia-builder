#!/usr/bin/env bash
set -euo pipefail

SKIA_REPO_URL="${SKIA_REPO_URL:-https://github.com/google/skia.git}"
RELEASE_REPO="${RELEASE_REPO:-${GITHUB_REPOSITORY:-}}"
REQUESTED_SKIA_BRANCH="${REQUESTED_SKIA_BRANCH:-}"

die() {
  echo "$*" >&2
  exit 1
}

write_output() {
  local name="$1"
  local value="$2"

  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "${name}=${value}" >> "$GITHUB_OUTPUT"
  fi
}

parse_latest_skia_branch() {
  awk '{ print $2 }' |
    awk -F 'refs/heads/chrome/m' 'NF == 2 && $2 ~ /^[0-9]+$/ { print $2 }' |
    sort -n |
    tail -1 |
    awk 'NF { print "chrome/m" $1 }'
}

list_skia_refs() {
  git ls-remote --heads "$SKIA_REPO_URL" 'refs/heads/chrome/m*'
}

skia_branch_exists() {
  local skia_branch="$1"
  git ls-remote --exit-code --heads "$SKIA_REPO_URL" "refs/heads/${skia_branch}" >/dev/null
}

release_notes_exist() {
  local release_notes_url="$1"
  curl --fail --silent --show-error --location --head "$release_notes_url" >/dev/null
}

release_exists() {
  local skia_branch="$1"
  gh release view "$skia_branch" --repo "$RELEASE_REPO" >/dev/null 2>&1
}

resolve_skia_branch() {
  if [ -n "$REQUESTED_SKIA_BRANCH" ]; then
    if [[ ! "$REQUESTED_SKIA_BRANCH" =~ ^chrome/m[0-9]+$ ]]; then
      die "Invalid Skia branch '${REQUESTED_SKIA_BRANCH}'. Expected chrome/mNNN."
    fi

    if ! skia_branch_exists "$REQUESTED_SKIA_BRANCH"; then
      die "Skia branch '${REQUESTED_SKIA_BRANCH}' does not exist upstream."
    fi

    echo "$REQUESTED_SKIA_BRANCH"
    return
  fi

  local latest_branch
  latest_branch="$(list_skia_refs | parse_latest_skia_branch)"

  if [ -z "$latest_branch" ]; then
    die "No chrome/m* branches found in google/skia."
  fi

  echo "$latest_branch"
}

main() {
  if [ -z "$RELEASE_REPO" ]; then
    die "RELEASE_REPO or GITHUB_REPOSITORY must be set."
  fi

  local skia_branch
  local release_notes_url
  local release_exists_value
  local should_dispatch

  if ! skia_branch="$(resolve_skia_branch)"; then
    return 1
  fi

  release_notes_url="https://raw.githubusercontent.com/google/skia/${skia_branch}/RELEASE_NOTES.md"

  if ! release_notes_exist "$release_notes_url"; then
    die "Release notes not found: ${release_notes_url}"
  fi

  if release_exists "$skia_branch"; then
    release_exists_value="true"
    should_dispatch="false"
  else
    release_exists_value="false"
    should_dispatch="true"
  fi

  write_output "skia_branch" "$skia_branch"
  write_output "release_notes_url" "$release_notes_url"
  write_output "release_exists" "$release_exists_value"
  write_output "should_dispatch" "$should_dispatch"

  echo "Skia branch: ${skia_branch}"
  echo "Release notes: ${release_notes_url}"
  echo "Existing release: ${release_exists_value}"
  echo "Should dispatch: ${should_dispatch}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
