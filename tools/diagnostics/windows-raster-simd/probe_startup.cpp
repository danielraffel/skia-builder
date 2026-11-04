// Diagnostic-only opt-in pre-main installer, not for shipping SDKs.
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include "include/core/SkGraphics.h"
#include "src/core/SkOpts.h"
extern "C" void spectr_probe_install_neon(int enable_lowp);
namespace {
struct RasterProbeStartup {
 RasterProbeStartup() {
  const char* enabled=std::getenv("PULP_SKIA_EC_NEON_DIAGNOSTIC");
  if (!enabled || std::strcmp(enabled,"highp")) return;
  SkGraphics::Init();
  const auto before=SkOpts::raster_pipeline_highp_stride;
  spectr_probe_install_neon(0);
  std::fprintf(stderr,"[raster-neon-diagnostic] explicit nonshipping EC ABI probe highp %zu -> %zu lowp %zu\n",before,SkOpts::raster_pipeline_highp_stride,SkOpts::raster_pipeline_lowp_stride);
 }
} rasterProbeStartup;
}
