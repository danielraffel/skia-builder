# Skia auto-update failed: chrome/m151

The automated Skia update detected `chrome/m151`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/28987596647
- Failing head branch: `main`
- Failing head SHA: `22870b02f323f90fd4d25d0e67cd0259c6acfee2`
- Target Skia branch: `chrome/m151`
- Run status when reported: `queued`
- Detection reason: `stale queued matrix job for at least 90 minutes`
- Created at: `2026-07-09T01:28:23Z`
- Updated at: `2026-07-09T01:28:23Z`

## Failed or stalled jobs

- [build-skia (macos-15, mac, gpu, x86_64)](https://github.com/danielraffel/skia-builder/actions/runs/28987596647/job/86020100151) queued for 135 minutes
- [build-skia (macos-15, mac, gpu, universal)](https://github.com/danielraffel/skia-builder/actions/runs/28987596647/job/86020100159) queued for 135 minutes
- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/28987596647/job/86020100175) queued for 135 minutes
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/28987596647/job/86020100203) queued for 135 minutes
- [build-skia (macos-15, ios, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/28987596647/job/86020100207) queued for 135 minutes
- [build-skia (macos-15, mac, gpu, arm64)](https://github.com/danielraffel/skia-builder/actions/runs/28987596647/job/86020100214) queued for 135 minutes

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m151` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

