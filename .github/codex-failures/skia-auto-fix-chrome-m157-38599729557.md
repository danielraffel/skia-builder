# Skia auto-update failed: chrome/m157

The automated Skia update detected `chrome/m157`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/38599729557
- Failing head branch: `main`
- Failing head SHA: `519ef86e21bd9ddd9540ccd34dd5769ac999c783`
- Target Skia branch: `chrome/m157`
- Run status when reported: `unknown`
- Detection reason: `completed workflow failure`
- Created at: `unknown`
- Updated at: `unknown`

## Failed or stalled jobs

- [build-skia (windows-11-arm, win, win-arm64ec, gpu, arm64ec, Release, true)](https://github.com/danielraffel/skia-builder/actions/runs/38599729557/job/115975711672)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m157` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

