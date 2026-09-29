# Skia auto-update failed: chrome/m156

The automated Skia update detected `chrome/m156`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/35356673411
- Failing head branch: `main`
- Failing head SHA: `c3dd00025995f1bedf8e246a772cd60ecdee809b`
- Target Skia branch: `chrome/m156`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-09-18T14:30:40Z`
- Updated at: `2026-09-18T15:11:30Z`

## Failed or stalled jobs

- [build-skia (macos-15, ios, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676399)
- [portable-linux-x64](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676400)
- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676408)
- [build-skia (macos-15, mac, gpu, universal)](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676416)
- [build-skia (macos-15, visionos, gpu, arm64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676427)
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676482)
- [build-skia (macos-15, mac, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676510)
- [build-skia (ubuntu-latest, wasm, gpu, wasm32, Release)](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676581)
- [build-skia (macos-15, mac, gpu, x86_64)](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676669)
- [build-skia (ubuntu-24.04-arm, linux, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/35356673411/job/105637676760)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m156` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

