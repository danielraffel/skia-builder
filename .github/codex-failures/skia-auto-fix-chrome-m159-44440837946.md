# Skia auto-update failed: chrome/m159

The automated Skia update detected `chrome/m159`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/44440837946
- Failing head branch: `main`
- Failing head SHA: `1b97010d2f025b4331a9c0db9481c440d1f33042`
- Target Skia branch: `chrome/m159`
- Run status when reported: `unknown`
- Detection reason: `completed workflow failure`
- Created at: `unknown`
- Updated at: `unknown`

## Failed or stalled jobs

- [create-release](https://github.com/danielraffel/skia-builder/actions/runs/44440837946/job/135321056339)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m159` build.
3. Re-run only the failed platform with `Build Skia` and `skip_release=true` (for example, `-f platforms=visionos`). Do not dispatch `platforms=all` for an isolated matrix failure.
4. Let one complete `platforms=all` run publish the release after every required platform passes.

