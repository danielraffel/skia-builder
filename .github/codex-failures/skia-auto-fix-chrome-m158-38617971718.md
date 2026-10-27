# Skia auto-update failed: chrome/m158

The automated Skia update detected `chrome/m158`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/38617971718
- Failing head branch: `main`
- Failing head SHA: `1023d4d0d979fe06f7c508dd888adb0c0ea35d46`
- Target Skia branch: `chrome/m158`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-10-14T18:46:15Z`
- Updated at: `2026-10-14T19:03:06Z`

## Failed or stalled jobs

- [build-skia (windows-11-arm, win, win-arm64ec, gpu, arm64ec, Release, true)](https://github.com/danielraffel/skia-builder/actions/runs/38617971718/job/116040478071)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m158` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

