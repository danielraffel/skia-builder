# Skia auto-update failed: chrome/m151

The automated Skia update detected `chrome/m151`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/28821175098
- Failing head branch: `main`
- Failing head SHA: `c2903fbc35a4b1ff27e3ba6dc940bf1e714d932d`
- Target Skia branch: `chrome/m151`
- Run status when reported: `queued`
- Detection reason: `stale queued workflow for 100 minutes`
- Created at: `2026-07-06T20:30:03Z`
- Updated at: `2026-07-06T20:30:03Z`

## Failed jobs

- No failed jobs were available yet. The workflow stayed `queued` for 100 minutes.

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m151` build.
3. Let the normal `Build Skia` workflow publish the release after the fix merges.

