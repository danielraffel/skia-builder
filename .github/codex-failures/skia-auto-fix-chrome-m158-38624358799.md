# Skia auto-update failed: chrome/m158

The automated Skia update detected `chrome/m158`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/38624358799
- Failing head branch: `main`
- Failing head SHA: `f710b2834eaf37dbf1bd39408f9361d10d85eda2`
- Target Skia branch: `chrome/m158`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-10-14T19:31:13Z`
- Updated at: `2026-10-14T20:08:27Z`

## Failed or stalled jobs

- [build-skia (windows-11-arm, win, win-arm64ec, gpu, arm64ec, Release, true)](https://github.com/danielraffel/skia-builder/actions/runs/38624358799/job/116060166581)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m158` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

