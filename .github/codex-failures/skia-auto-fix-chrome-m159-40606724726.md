# Skia auto-update failed: chrome/m159

The automated Skia update detected `chrome/m159`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/40606724726
- Failing head branch: `main`
- Failing head SHA: `584b32f9793771b13adc203cf69976b26b2b4524`
- Target Skia branch: `chrome/m159`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-10-28T00:07:33Z`
- Updated at: `2026-10-28T01:56:33Z`

## Failed or stalled jobs

- [build-skia (macos-15, visionos, gpu, arm64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/40606724726/job/122548056598)
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/40606724726/job/122548056633)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m159` build.
3. Re-run only the failed platform with `Build Skia` and `skip_release=true` (for example, `-f platforms=visionos`). Do not dispatch `platforms=all` for an isolated matrix failure.
4. Let one complete `platforms=all` run publish the release after every required platform passes.

