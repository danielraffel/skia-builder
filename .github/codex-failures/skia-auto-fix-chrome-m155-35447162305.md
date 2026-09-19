# Skia auto-update failed: chrome/m155

The automated Skia update detected `chrome/m155`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/35447162305
- Failing head branch: `main`
- Failing head SHA: `c3dd00025995f1bedf8e246a772cd60ecdee809b`
- Target Skia branch: `chrome/m155`
- Run status when reported: `in_progress`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-09-19T13:55:06Z`
- Updated at: `2026-09-19T13:57:13Z`

## Failed or stalled jobs

- [portable-linux-x64](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907989947)
- [build-skia (macos-15, mac, gpu, x86_64)](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907990015)
- [build-skia (ubuntu-latest, wasm, gpu, wasm32, Release)](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907990046)
- [build-skia (ubuntu-24.04-arm, linux, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907990057)
- [build-skia (macos-15, visionos, gpu, arm64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907990061)
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907990064)
- [build-skia (macos-15, mac, gpu, universal)](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907990065)
- [build-skia (macos-15, ios, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907990073)
- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907990116)
- [build-skia (macos-15, mac, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/35447162305/job/105907990131)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m155` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

