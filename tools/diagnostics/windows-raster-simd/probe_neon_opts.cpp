// Diagnostic only. This TU never enters a shipping library or live DAW.
#include "src/core/SkOpts.h"
#define SK_OPTS_NS spectr_probe_neon
#define SKRP_CPU_NEON 1
#include "src/opts/SkRasterPipeline_opts.h"
extern "C" void spectr_probe_install_neon(int enable_lowp) {
#define M(st) (SkOpts::StageFn)spectr_probe_neon::st,
    const SkOpts::StageFn highp[] = { SK_RASTER_PIPELINE_OPS_ALL(M) };
#undef M
#define M(st) (SkOpts::StageFn)spectr_probe_neon::lowp::st,
    const SkOpts::StageFn lowp[] = { SK_RASTER_PIPELINE_OPS_LOWP(M) };
#undef M
    memcpy(SkOpts::ops_highp, highp, sizeof highp);
    if (enable_lowp) memcpy(SkOpts::ops_lowp, lowp, sizeof lowp);
    SkOpts::just_return_highp=(SkOpts::StageFn)spectr_probe_neon::just_return;
    if (enable_lowp) SkOpts::just_return_lowp=(SkOpts::StageFn)spectr_probe_neon::lowp::just_return;
    SkOpts::start_pipeline_highp=spectr_probe_neon::start_pipeline;
    if (enable_lowp) SkOpts::start_pipeline_lowp=spectr_probe_neon::lowp::start_pipeline;
    SkOpts::raster_pipeline_highp_stride=spectr_probe_neon::raster_pipeline_highp_stride();
    if (enable_lowp) SkOpts::raster_pipeline_lowp_stride=spectr_probe_neon::raster_pipeline_lowp_stride();
}
