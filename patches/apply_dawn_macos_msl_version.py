#!/usr/bin/env python3
"""Select Metal's shader language from macOS, never from a plugin host's SDK."""
import sys
from pathlib import Path

RELATIVE = Path("third_party/externals/dawn/src/dawn/native/metal/ShaderModuleMTL.mm")
ANCHOR = "    NSRef<MTLCompileOptions> compileOptions = AcquireNSRef([[MTLCompileOptions alloc] init]);\n"
BLOCK = """#if DAWN_PLATFORM_IS(MACOS)
    // Metal's default depends on the main executable's linked SDK. A modern
    // plugin in an older host (REAPER: SDK 10.12) otherwise inherits MSL 1.2,
    // which cannot compile Tint's metal::array. Select by runtime OS instead.
#if __MAC_OS_X_VERSION_MAX_ALLOWED >= 150000
    if (@available(macOS 15.0, *)) {
        (*compileOptions).languageVersion = MTLLanguageVersion3_2;
    } else
#endif
#if __MAC_OS_X_VERSION_MAX_ALLOWED >= 140000
    if (@available(macOS 14.0, *)) {
        (*compileOptions).languageVersion = MTLLanguageVersion3_1;
    } else
#endif
#if __MAC_OS_X_VERSION_MAX_ALLOWED >= 130000
    if (@available(macOS 13.0, *)) {
        (*compileOptions).languageVersion = MTLLanguageVersion3_0;
    } else
#endif
#if __MAC_OS_X_VERSION_MAX_ALLOWED >= 120000
    if (@available(macOS 12.0, *)) {
        (*compileOptions).languageVersion = MTLLanguageVersion2_4;
    } else
#endif
    {
        // Dawn's macOS backend requires macOS 11 or newer.
        (*compileOptions).languageVersion = MTLLanguageVersion2_3;
    }
#endif
"""

def apply(skia_dir: Path) -> None:
    path = skia_dir / RELATIVE
    source = path.read_text()
    if source.count(ANCHOR) != 1:
        raise ValueError(f"{path}: expected exactly one compiler-options allocation")
    if ANCHOR + BLOCK in source:
        return
    if "Select by runtime OS instead" in source:
        raise ValueError(f"{path}: partial or altered MSL-version patch")
    path.write_text(source.replace(ANCHOR, ANCHOR + BLOCK, 1))

if __name__ == "__main__":
    apply(Path(sys.argv[1]))
