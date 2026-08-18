# Skia auto-update failed: chrome/m153

The automated Skia update detected `chrome/m153`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/28738447662
- Failing head branch: `main`
- Failing head SHA: `df58af4e6052236e29b020d1d001fdea044b33a4`
- Target Skia branch: `chrome/m153`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-07-05T10:57:28Z`
- Updated at: `2026-07-05T11:21:53Z`

## Failed or stalled jobs

- [build-skia (windows-2022, win, gpu, x64, Release)](https://github.com/danielraffel/skia-builder/actions/runs/28738447662/job/85216793009)
- [build-skia (windows-2022, win, gpu, x64, Debug)](https://github.com/danielraffel/skia-builder/actions/runs/28738447662/job/85216793024)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m153` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

