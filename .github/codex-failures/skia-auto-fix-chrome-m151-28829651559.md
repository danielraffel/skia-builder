# Skia auto-update failed: chrome/m151

The automated Skia update detected `chrome/m151`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/28829651559
- Failing head branch: `main`
- Failing head SHA: `a233bdab79c1a40fdba892eb11417ea205996191`
- Target Skia branch: `chrome/m151`
- Run status when reported: `queued`
- Detection reason: `stale queued matrix job for at least 90 minutes`
- Created at: `2026-07-06T23:12:40Z`
- Updated at: `2026-07-06T23:12:40Z`

## Failed or stalled jobs

- [build-skia (macos-15, mac, gpu, universal)](https://github.com/danielraffel/skia-builder/actions/runs/28829651559/job/85500528608) queued for 127 minutes
- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/28829651559/job/85500528636) queued for 127 minutes

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m151` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

