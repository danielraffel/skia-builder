# Windows ARM raster pipeline investigation

These are isolated diagnostic sources, not a shipping provider or an installer.
Do not link `probe_startup.cpp` into a release. The actual producer integration
and its per-architecture qualification remain to be implemented.

## Root cause and measured scope

Skia at `be7d7c3e996e567eda7dc9774274f7a0103cdb8c` explicitly selects
`SKRP_CPU_SCALAR` in `src/opts/SkRasterPipeline_opts.h` when the compiler is
neither Clang nor GCC. Its scalar path also omits the low-precision vector stage
table. Our Windows provider deliberately uses MSVC to keep its STL/CRT ABI
compatible with its consumers. The installed ARM64EC provider reports raster
strides 1/1. This compiler choice therefore disables the vector raster stages;
it is not evidence that the VM lacks ARM SIMD instructions.

The diagnostic keeps the exact MSVC provider archive and adds a single Clang
leaf translation unit containing the pinned raster stage implementations. It
replaces each selected stage table, terminal, entry point and stride together,
before any rendering. Each comparison uses a new process. It never swaps
process-wide tables in an active DAW or editor.

Measured on Windows 11 ARM build 26100.9711 in an 8-vCPU HVF UTM VM, MSVC
14.51.36231 with `/MT`, and LLVM clang-cl 23.1.3:

| Fixed 1320x860 scene, 64 iterations | Scalar wall | Vector wall | Image difference |
| --- | --- | --- | --- |
| Two radial gradients and plus blend; both vector tables | 11.66 / 11.92 s | 0.519 / 0.496 s | Maximum 2 channel levels; fails the experiment's <=1 tolerance |
| Same scene, highp only; original lowp remains null | 13.84 / 13.61 s | 1.256 / 1.211 s | Six channels differ by one level out of 4,540,800; repeat outputs identical |

QPC wall and actual GetProcessTimes CPU agree on substantial in-process work.
Highp-only mean wall improvement is 11.13x for this primitive workload.

A separate interleaved same-binary Spectr CPU-renderer test used live noise,
64 bands, LFO modulation and 38 mouse moves per run. Scalar mean frame times
were 296.8 / 348.8 ms; highp-vector means were 44.47 / 43.80 ms (7.31x).
Optimized p95 was 70.31 / 65.04 ms. All four runs exited cleanly, with no
unfinished Perfetto spans or positive trace-loss reports. These are frame
wall times, not scheduler-attributed CPU times. This is still below a smooth
60 Hz target and does not qualify WARP, installed plugins or native Intel.

## Reproducing the diagnostic

Use the exact pinned Skia source and the same Windows toolset headers as the
MSVC provider. `probe_main.cpp` uses the m158 `SkGradient` API. Compile main
with MSVC `/arm64EC /O2 /MT /DNDEBUG /std:c++20 /EHsc`; link the unchanged
provider and its existing, verified dependency closure with `/MACHINE:ARM64EC`.
Compile `probe_neon_opts.cpp` using clang-cl targeting `arm64ec-pc-windows-msvc`,
`/O2 /MT /DNDEBUG /std:c++20`, with the identical Skia/STL/UCRT include roots.
Inspect COFF machine identity and all undefined symbols before linking. The
measured leaf object was ARM64EC `0xA641` and introduced no `__std_*` references.

Unmodified EC compilation currently fails because the header spells its narrow
stage ABI `__vectorcall`, which this clang-cl EC target rejects. The experiment
used **`/D__vectorcall=`**, recorded explicitly, for the diagnostic TU only.
This is not an approved production flag. Native ARM64 clang-cl compilation
succeeded without that override. A source-local ARM64EC ABI branch requires
review and testing before a production integration; do not globally redefine
language keywords in a provider or a consumer.

Run separate invocations of `raster-simd-probe.exe scalar scalar.bgra`, then
`neon-highp highp.bgra`, and repeat in that order. `neon` additionally installs
the lowp table and is retained as a distinct precision experiment. Verify all
exit codes, process CPU/QPC receipts, exact executable/provider hashes, byte
lengths and every output channel. Do not silently relax image tolerances.

`probe_startup.cpp` enabled the full Spectr experiment through an explicit
`PULP_SKIA_EC_NEON_DIAGNOSTIC=highp` environment flag and a recorded diagnostic
archive passed with `/WHOLEARCHIVE`. Preserve existing linker flags, especially
`/MACHINE:ARM64EC`; replacing them caused a retained LNK1392 negative result.
Baseline and optimized runs used the same diagnostic binary. No screenshots,
file diagnostics or builds ran on the VM host during timing.

## Production follow-up

Keep MSVC as the producer of the provider's STL/CRT-facing code. Implement the
optimized stage leaf in the provider build, using an explicit source-level EC
ABI branch and a reviewed initialization hook. Carry immutable source,
compiler, target, runtime and stage-object provenance. Require no new unresolved
STL helpers; retain the current verified SDK closure. Do not change every
provider archive to Clang as a shortcut.

Qualify native ARM64 and ARM64EC independently. Intel must retain its own
provider/runtime lane. Recheck complete dispatch-table consistency, context
layout, callbacks, tail widths, gradients, blending, images, clipping and real
application scenes. Run exact installed standalone/VST3/CLAP controls, audio,
resize, settings/presets and performance after removing every diagnostic linker
flag/environment control. Any backend default change needs a new full-scene
CPU-versus-WARP comparison; these results alone do not authorize one.
