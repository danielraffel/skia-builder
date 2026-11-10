# Skia auto-update failed: chrome/m159

The automated Skia update detected `chrome/m159`, dispatched `Build Skia`, and the build needs attention before a release can be published.

- Failed run: https://github.com/danielraffel/skia-builder/actions/runs/40535241085
- Failing head branch: `main`
- Failing head SHA: `e8319e1df4e938ddf29b88b3c2fa6575a4ab7eb5`
- Target Skia branch: `chrome/m159`
- Run status when reported: `completed/failure`
- Detection reason: `failed matrix job before workflow completion`
- Created at: `2026-10-27T15:52:08Z`
- Updated at: `2026-10-27T17:18:35Z`

## Failed or stalled jobs

- [portable-linux-x64](https://github.com/danielraffel/skia-builder/actions/runs/40535241085/job/122298709517)
- [build-skia (macos-15, ios, gpu, arm64,x86_64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/40535241085/job/122298793980)
- [build-skia (macos-15, visionos, gpu, arm64, simulator)](https://github.com/danielraffel/skia-builder/actions/runs/40535241085/job/122298794008)
- [build-skia (macos-15, ios, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/40535241085/job/122298794284)
- [build-skia (macos-15, visionos, gpu, arm64, device)](https://github.com/danielraffel/skia-builder/actions/runs/40535241085/job/122298794482)

## Expected handling

1. Inspect the failed or stalled jobs and logs.
2. Make the smallest repository change needed to restore the `chrome/m159` build.
3. Re-run only the failed platform with `Build Skia` and `skip_release=true` (for example, `-f platforms=visionos`). Do not dispatch `platforms=all` for an isolated matrix failure.
4. Let one complete `platforms=all` run publish the release after every required platform passes.

