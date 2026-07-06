# Skia auto-update failed: chrome/m151

The automated Skia update detected `chrome/m151`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/28514023623
- Failing head branch: `main`
- Failing head SHA: `df58af4e6052236e29b020d1d001fdea044b33a4`
- Target Skia branch: `chrome/m151`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-07-01T11:24:54Z`
- Updated at: `2026-07-01T12:49:06Z`

## Failed jobs

- [build-skia (windows-2022, win, gpu, x64, Release)](https://github.com/danielraffel/skia-builder/actions/runs/28514023623/job/84521101586)
- [build-skia (windows-2022, win, gpu, x64, Debug)](https://github.com/danielraffel/skia-builder/actions/runs/28514023623/job/84521101637)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m151` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

