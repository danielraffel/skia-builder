# Skia auto-update failed: chrome/m156

The automated Skia update detected `chrome/m156`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/35112076666
- Failing head branch: `main`
- Failing head SHA: `c3dd00025995f1bedf8e246a772cd60ecdee809b`
- Target Skia branch: `chrome/m156`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-09-16T14:57:40Z`
- Updated at: `2026-09-16T15:39:02Z`

## Failed or stalled jobs

- [portable-linux-x64](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848178651)
- [build-skia (macos-15, visionos, gpu, arm64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848178805)
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848178854)
- [build-skia (ubuntu-24.04-arm, linux, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848178904)
- [build-skia (macos-15, ios, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848178930)
- [build-skia (macos-15, mac, gpu, universal)](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848178933)
- [build-skia (macos-15, mac, gpu, x86_64)](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848178970)
- [build-skia (macos-15, mac, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848178995)
- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848179098)
- [build-skia (ubuntu-latest, wasm, gpu, wasm32, Release)](https://github.com/danielraffel/skia-builder/actions/runs/35112076666/job/104848179123)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m156` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

