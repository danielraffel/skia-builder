# Skia auto-update failed: chrome/m157

The automated Skia update detected `chrome/m157`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/38586449628
- Failing head branch: `main`
- Failing head SHA: `320180fb261576a005b000e7fca786d321b47b11`
- Target Skia branch: `chrome/m157`
- Run status when reported: `in_progress`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-10-14T15:06:43Z`
- Updated at: `2026-10-14T15:09:13Z`

## Failed or stalled jobs

- [build-skia (macos-15, mac, gpu, universal)](https://github.com/danielraffel/skia-builder/actions/runs/38586449628/job/115929791404)
- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/38586449628/job/115929791439)
- [build-skia (windows-2022, win, gpu, x64, Release)](https://github.com/danielraffel/skia-builder/actions/runs/38586449628/job/115929791575)
- [build-skia (macos-15, mac, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/38586449628/job/115929791596)
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/38586449628/job/115929791597)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m157` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

