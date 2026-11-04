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

Raw upstream EC compilation fails because the header spells its narrow
stage ABI `__vectorcall`, which this clang-cl EC target rejects. The experiment
used **`/D__vectorcall=`**, recorded explicitly, for the diagnostic TU only.
This is not an approved production flag. Native ARM64 clang-cl compilation
succeeded without that override. The producer already carries a source-local
ARM64EC ABI branch in `patches/apply_windows_arm64ec_avx.py`; the diagnostic used
raw upstream headers without that patch. Production compilation must use the
existing source patch, never a global redefinition of a language keyword.

The producer's original CPU feature patch had a separate precedence defect:
`!defined(_M_ARM64EC)` excluded only `_M_X64`, leaving clang-cl's simultaneous
`__x86_64__` definition able to select x86 dispatch. The corrected patch groups
the entire x86 disjunction and migrates already-patched sources idempotently.
The regression test preprocesses native ARM64, ARM64EC, x64 and x86 macro sets,
including the actual clang-cl EC combination. With both source guards applied,
the full `src/core/SkOpts.cpp` compiles as COFF ARM64EC without a keyword override,
without `Init_ml3` or `SkCpu::gCachedFeatures` imports, and without `__std_*`
imports. This is object-level evidence; archive/link/runtime proof is pending.

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
single `src/core/SkOpts.cpp` translation unit with clang-cl in the provider build,
reusing the existing source-level EC ABI branch. Keep its normal initialization
and replace only that member in the archive, rather than injecting dispatch
tables at runtime. Initially retain `SK_DISABLE_LOWP_RASTER_PIPELINE` to match
the measured highp precision experiment. Carry immutable source,
compiler, target, runtime and stage-object provenance. Require no new unresolved
STL helpers; retain the current verified SDK closure. Do not change every
provider archive to Clang as a shortcut.

`tools/replace_windows_raster_object.py` performs the archive transformation
with llvm-ar/llvm-lib. It refuses to overwrite an existing output, checks the
replacement machine and complete normal SkOpts symbols, rejects x86 dispatch
and STL helper imports, and verifies that all unrelated object bytes and names
survive unchanged. This tool does not yet integrate compilation into
`build-skia.py`; callers must preserve the exact provider compilation recipe.

A candidate with only this member replaced linked an MSVC primitive consumer
in the ARM64EC UTM guest without either diagnostic object. Its normal startup
selected highp stride 4. Two renders were byte-identical to the earlier highp
diagnostic, and differed from scalar in only six channels, each by one level.
Lowp stages remain null under `SK_DISABLE_LOWP_RASTER_PIPELINE`; their reported
stride is 4 in the normal object, which does not enable those null stages.
This proves the primitive archive consumer, not final product qualification.
Compile the probe with `/DPULP_RASTER_PROVIDER_PROBE` and invoke it as
`raster-simd-probe-provider.exe provider output.bgra` to exercise only normal
provider initialization, with no runtime table replacement.

The same archive subsequently linked Spectr's standalone, VST3 and CLAP targets.
Four standalone traces exercised live noise, 64 bands, LFO modulation and 38
mouse moves per run with the diagnostic startup archive removed. CPU mean frame
times were 50.09 / 53.77 ms (p95 79.92 / 74.25 ms); default D3D12 mean frame
times were 416.93 / 446.34 ms. All four exited cleanly without unfinished spans
or positive trace-loss statistics. This is standalone tracing evidence, not
installed plugin or installer acceptance, and CPU is still below 60 Hz.

The default adapter identified itself as Microsoft Basic Render Driver,
vendor `microsoft`, architecture `warp`, yet reported type `integrated`.
Its `gpu_acquire` span averaged 338.91 / 371.56 ms, while paint averaged
5.48 / 5.10 ms. Do not assume an integrated adapter type implies hardware
acceleration, or blame the frontend solely from end-to-end frame time. A Windows
host policy for this software adapter requires separate integration, controls
and proof; these measurements do not change the backend default themselves.

Qualify native ARM64 and ARM64EC independently. Intel must retain its own
provider/runtime lane. Recheck complete dispatch-table consistency, context
layout, callbacks, tail widths, gradients, blending, images, clipping and real
application scenes. Run exact installed standalone/VST3/CLAP controls, audio,
resize, settings/presets and performance after removing every diagnostic linker
flag/environment control. Any backend default change needs a new full-scene
CPU-versus-WARP comparison; these results alone do not authorize one.
