# Skia auto-update failed: chrome/m157

The automated Skia update detected `chrome/m157`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/38603857495
- Failing head branch: `main`
- Failing head SHA: `0443cb93aea5954736f8e3fb4953916c5092d866`
- Target Skia branch: `chrome/m157`
- Run status when reported: `unknown`
- Detection reason: `completed workflow failure`
- Created at: `unknown`
- Updated at: `unknown`

## Failed or stalled jobs

- [build-skia (windows-11-arm, win, win-arm64ec, gpu, arm64ec, Release, true)](https://github.com/danielraffel/skia-builder/actions/runs/38603857495/job/115991267477)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m157` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

