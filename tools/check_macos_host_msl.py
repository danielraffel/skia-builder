#!/usr/bin/env python3
"""Opt-in hardware regression: modern plugin shader inside an older-SDK host.

Builds only a disposable Metal probe. It never modifies REAPER or Spectr.
Requires Xcode, Intel macOS 13+, and a real Metal device. No virtual/null PASS.
"""
import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "patches"))
from apply_dawn_macos_msl_version import BLOCK

SOURCE = r'''#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#define DAWN_PLATFORM_IS(x) 1
int main() {
 @autoreleasepool {
  id<MTLDevice> dev=MTLCreateSystemDefaultDevice();
  if (!dev) return 3;
  NSMutableArray *results=[NSMutableArray array];
  NSString *src=@"#include <metal_stdlib>\nusing namespace metal;\nkernel void probe(device array<float,4>& a [[buffer(0)]]) { a[0]=1.0f; }\n";
  for (NSNumber *selected in @[@NO,@YES]) {
   MTLCompileOptions *opt=[[MTLCompileOptions alloc] init];
   NSUInteger initial=opt.languageVersion;
   if(selected.boolValue) {
@SELECTION@
   }
   NSError *err=nil;
   id<MTLLibrary> lib=[dev newLibraryWithSource:src options:opt error:&err];
   [results addObject:@{@"selected":selected,@"default":@(initial),@"effective":@(opt.languageVersion),@"compiled":@(lib!=nil),@"error":err.localizedDescription?:@""}];
  }
  NSData *data=[NSJSONSerialization dataWithJSONObject:@{@"device":dev.name,@"results":results} options:NSJSONWritingPrettyPrinted error:nil];
  puts([[NSString alloc]initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
 }
 return 0;
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        parser.error("requires an Intel macOS Metal host for the SDK 10.12 negative control")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = root / "probe.m"
    # Exercise the exact selection block inserted into Dawn, not a duplicate.
    source.write_text(SOURCE.replace("@SELECTION@", BLOCK.replace("(*compileOptions)", "opt")))
    modern, old = root / "modern-host", root / "old-sdk-host"
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-framework", "Foundation", "-framework", "Metal", str(source), "-o", str(modern)], check=True)
    subprocess.run(["xcrun", "vtool", "-set-build-version", "macos", "10.9", "10.12", "-replace", "-output", str(old), str(modern)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(old)], check=True)
    receipts = {}
    for name, exe in (("modern", modern), ("old_sdk", old)):
        result = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
        receipts[name] = json.loads(result.stdout)
    (root / "results.json").write_text(json.dumps(receipts, indent=2) + "\n")
    for name in receipts:
        assert receipts[name]["results"][1]["compiled"], f"{name}: selected MSL failed"
        assert receipts[name]["results"][1]["effective"] >= 131075, f"{name}: selection below MSL2.3"
    assert receipts["modern"]["results"][0]["compiled"], "modern-host control failed"
    old_default = receipts["old_sdk"]["results"][0]
    assert not old_default["compiled"] and "no template named 'array'" in old_default["error"], "old-host negative control did not reproduce"
    assert receipts["old_sdk"]["results"][1]["effective"] == receipts["modern"]["results"][1]["effective"], "selected MSL still depends on host SDK"
    print("PASS: old-SDK failure reproduced; exact patched selection compiles on both hosts")

if __name__ == "__main__":
    main()
