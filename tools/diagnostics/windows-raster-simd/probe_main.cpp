// Offline CPU raster diagnostic. No product/UI/audio process is accessed.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "include/core/SkCanvas.h"
#include "include/core/SkGraphics.h"
#include "include/core/SkImageInfo.h"
#include "include/core/SkPaint.h"
#include "include/core/SkSurface.h"
#include "include/effects/SkGradient.h"
#include "src/core/SkOpts.h"
#ifndef PULP_RASTER_PROVIDER_PROBE
extern "C" void spectr_probe_install_neon(int enable_lowp);
#endif
static double cpu_seconds() {
    FILETIME creation,exit,kernel,user;
    if (!GetProcessTimes(GetCurrentProcess(),&creation,&exit,&kernel,&user)) std::exit(3);
    ULARGE_INTEGER k,u;k.LowPart=kernel.dwLowDateTime;k.HighPart=kernel.dwHighDateTime;
    u.LowPart=user.dwLowDateTime;u.HighPart=user.dwHighDateTime;
    return (k.QuadPart+u.QuadPart)/10000000.0;
}
int main(int argc,char**argv) {
#ifdef PULP_RASTER_PROVIDER_PROBE
    if(argc!=3 || strcmp(argv[1],"provider")) return 2;
#else
    if(argc!=3 || (strcmp(argv[1],"scalar") && strcmp(argv[1],"neon") && strcmp(argv[1],"neon-highp"))) return 2;
#endif
    SkGraphics::Init();
    const auto original_high=SkOpts::raster_pipeline_highp_stride;
    const auto original_low=SkOpts::raster_pipeline_lowp_stride;
#ifndef PULP_RASTER_PROVIDER_PROBE
    if(strcmp(argv[1],"scalar")) spectr_probe_install_neon(strcmp(argv[1],"neon-highp")!=0);
#endif
    constexpr int width=1320,height=860,iterations=64;
    auto surface=SkSurfaces::Raster(SkImageInfo::MakeN32Premul(width,height));
    if(!surface)return 4;
    const SkColor4f colorsA[]={SkColor4f::FromColor(0xA0336688),SkColor4f::FromColor(0x0005070A)};
    const SkColor4f colorsB[]={SkColor4f::FromColor(0x806D3366),SkColor4f::FromColor(0x0005070A)};
    const SkScalar positions[]={0,1};
    SkPaint a,b;
    a.setShader(SkShaders::RadialGradient({660,430},430,SkGradient(SkGradient::Colors(colorsA,positions,SkTileMode::kClamp),{})));
    b.setShader(SkShaders::RadialGradient({500,320},360,SkGradient(SkGradient::Colors(colorsB,positions,SkTileMode::kClamp),{})));
    b.setBlendMode(SkBlendMode::kPlus);
    auto draw=[&](){
        surface->getCanvas()->clear(0xFF05070A);
        surface->getCanvas()->drawRect(SkRect::MakeWH(width,height),a);
        surface->getCanvas()->drawRect(SkRect::MakeWH(width,height),b);
    };
    for(int i=0;i<8;i++)draw();
    LARGE_INTEGER freq,begin,end;QueryPerformanceFrequency(&freq);
    const double cpu_begin=cpu_seconds();QueryPerformanceCounter(&begin);
    for(int i=0;i<iterations;i++)draw();
    QueryPerformanceCounter(&end);const double cpu_end=cpu_seconds();
    const size_t bytes=size_t(width)*height*4;
    void* pixels=malloc(bytes);if(!pixels)return 5;
    if(!surface->readPixels(SkImageInfo::MakeN32Premul(width,height),pixels,width*4,0,0))return 6;
    FILE* f=nullptr;if(fopen_s(&f,argv[2],"wb") || !f)return 7;
    const auto written=fwrite(pixels,1,bytes,f);fclose(f);free(pixels);if(written!=bytes)return 8;
    printf("{\"diagnostic_only\":true,\"mode\":\"%s\",\"width\":%d,\"height\":%d,\"iterations\":%d,\"wall_ms\":%.6f,\"cpu_ms\":%.6f,\"provider_highp_stride\":%zu,\"provider_lowp_stride\":%zu,\"highp_stride\":%zu,\"lowp_stride\":%zu}\n",argv[1],width,height,iterations,1000.0*(end.QuadPart-begin.QuadPart)/freq.QuadPart,1000.0*(cpu_end-cpu_begin),original_high,original_low,SkOpts::raster_pipeline_highp_stride,SkOpts::raster_pipeline_lowp_stride);
    return 0;
}
