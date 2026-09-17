# Skia auto-update failed: chrome/m155

The automated Skia update detected `chrome/m155`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/35237229010
- Failing head branch: `main`
- Failing head SHA: `c3dd00025995f1bedf8e246a772cd60ecdee809b`
- Target Skia branch: `chrome/m155`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-09-17T14:59:11Z`
- Updated at: `2026-09-17T15:33:58Z`

## Failed or stalled jobs

- [portable-linux-x64](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256282405)
- [build-skia (macos-15, ios, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256282617)
- [build-skia (macos-15, visionos, gpu, arm64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256282632)
- [build-skia (macos-15, mac, gpu, x86_64)](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256282647)
- [build-skia (ubuntu-24.04-arm, linux, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256282771)
- [build-skia (macos-15, mac, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256282788)
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256282803)
- [build-skia (macos-15, mac, gpu, universal)](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256282876)
- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256283021)
- [build-skia (ubuntu-latest, wasm, gpu, wasm32, Release)](https://github.com/danielraffel/skia-builder/actions/runs/35237229010/job/105256283024)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m155` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

