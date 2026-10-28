# Skia auto-update failed: chrome/m158

The automated Skia update detected `chrome/m158`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/40606724726
- Failing head branch: `main`
- Failing head SHA: `584b32f9793771b13adc203cf69976b26b2b4524`
- Target Skia branch: `chrome/m158`
- Run status when reported: `unknown`
- Detection reason: `completed workflow failure`
- Created at: `unknown`
- Updated at: `unknown`

## Failed or stalled jobs

- [build-skia (macos-15, visionos, gpu, arm64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/40606724726/job/122548056598)
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/40606724726/job/122548056633)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m158` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

