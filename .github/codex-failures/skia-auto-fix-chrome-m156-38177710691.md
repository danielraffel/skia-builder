# Skia auto-update failed: chrome/m156

The automated Skia update detected `chrome/m156`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/38177710691
- Failing head branch: `main`
- Failing head SHA: `f466973453f5520764271293820f242cef2ffca7`
- Target Skia branch: `chrome/m156`
- Run status when reported: `unknown`
- Detection reason: `completed workflow failure`
- Created at: `unknown`
- Updated at: `unknown`

## Failed or stalled jobs

- [build-skia (windows-11-arm, win, win-arm64, gpu, arm64, Release)](https://github.com/danielraffel/skia-builder/actions/runs/38177710691/job/114583570725)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m156` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

