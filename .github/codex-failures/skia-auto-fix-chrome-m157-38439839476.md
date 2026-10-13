# Skia auto-update failed: chrome/m157

The automated Skia update detected `chrome/m157`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/38439839476
- Failing head branch: `main`
- Failing head SHA: `0a6a87b0e312f890cf435ef479215dc049cf949a`
- Target Skia branch: `chrome/m157`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-10-13T17:35:09Z`
- Updated at: `2026-10-13T18:16:40Z`

## Failed or stalled jobs

- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/38439839476/job/115443486538)
- [build-skia (windows-2022, win, gpu, x64, Release)](https://github.com/danielraffel/skia-builder/actions/runs/38439839476/job/115443486626)
- [build-skia (ubuntu-24.04-arm, linux, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/38439839476/job/115443486719)
- [build-skia (windows-11-arm, win, win-arm64, gpu, arm64, Release)](https://github.com/danielraffel/skia-builder/actions/runs/38439839476/job/115443486767)
- [build-skia (windows-2022, win, gpu, x64, Debug)](https://github.com/danielraffel/skia-builder/actions/runs/38439839476/job/115443486774)
- [build-skia (macos-15, mac, gpu, universal)](https://github.com/danielraffel/skia-builder/actions/runs/38439839476/job/115443486806)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m157` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

