# Skia auto-update failed: chrome/m155

The automated Skia update detected `chrome/m155`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/34985423961
- Failing head branch: `main`
- Failing head SHA: `c3dd00025995f1bedf8e246a772cd60ecdee809b`
- Target Skia branch: `chrome/m155`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-09-15T14:59:56Z`
- Updated at: `2026-09-15T15:43:45Z`

## Failed or stalled jobs

- [portable-linux-x64](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436247789)
- [build-skia (macos-15, mac, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436248093)
- [build-skia (ubuntu-24.04-arm, linux, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436248118)
- [build-skia (macos-15, mac, gpu, x86_64)](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436248120)
- [build-skia (macos-15, mac, gpu, universal)](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436248150)
- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436248153)
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436248195)
- [build-skia (macos-15, visionos, gpu, arm64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436248285)
- [build-skia (ubuntu-latest, wasm, gpu, wasm32, Release)](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436248286)
- [build-skia (macos-15, ios, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/34985423961/job/104436248444)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m155` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

