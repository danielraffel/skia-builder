# Metal language selection in older-SDK macOS plugin hosts

## Reproduced on physical Intel hardware, 2026-11-18

Mac mini, Intel UHD Graphics 630, macOS 15.8.3 (24H241), REAPER 7.86.
Spectr 1.0.11 standalone rendered, but installed VST3, CLAP and AU repeatedly
failed inside REAPER with `no template named 'array'`, followed by Graphite
rejecting the frame. The exact loaded system-plugin hashes are recorded in
[evidence](evidence/20261118-intel-metal/system-plugin-probes.json).
The desktop screenshot did not establish a visible editor; this is a shader
failure receipt, not a successful editor qualification.

Dawn `1716e88cc9e58398fab5d4473f7f2e858667b677` allocates `MTLCompileOptions`
without setting `languageVersion` unless shader printing is enabled. Skia
`be7d7c3e996e567eda7dc9774274f7a0103cdb8c` DEPS maps Dawn sources under
`third_party/externals/dawn`; `third_party/dawn` is Skia’s build wrapper. Metal's
implicit version depends on the **main executable's** linked SDK. REAPER's
executable records SDK 10.12; Spectr's executable records SDK 27.2.

A diagnostic REAPER extension observed default language 65538 (MSL 1.2).
A tiny shader using `metal::array` failed under that default; explicit MSL
2.2, 2.3, 2.4 and 3.0 all passed. A standalone probe observed default 196610
(MSL 3.2). Changing only that disposable probe's SDK load-command metadata to
10.12 reproduced the MSL 1.2 failure. This separates the cause from scene
complexity, stale plugin copies, drawable size, and the earlier MSAA change.
Raw compiler results are under [evidence](evidence/20261118-intel-metal).

## Fix and regression

`apply_dawn_macos_msl_version.py` sets Dawn's macOS compile-option language from
the runtime OS, with SDK guards: macOS 15 -> MSL 3.2; 14 -> 3.1; 13 -> 3.0;
12 -> 2.4; 11 -> 2.3. Dawn's existing shader-print override remains intact.
Only macOS slices run the patch. Unknown source shape fails the macOS build
instead of publishing an unpatched archive. No process-wide swizzle, host
executable modification, or Spectr-only renderer fallback is involved.

Run the opt-in hardware regression (Xcode and real Metal device required):

```sh
python3 tools/check_macos_host_msl.py --output /absolute/new/evidence-directory
```

It compiles the **exact inserted selection block**, creates a disposable
old-SDK test executable, checks the negative control, then requires the fixed
shader to compile in both host variants. The physical Intel run passed;
see `selection-regression.json`. It never modifies REAPER or Spectr.

## Remaining delivery requirements

The compiler regression does **not** prove a rebuilt Dawn library or working
Spectr editors. Before replacing a public consumer:

1. Build new macOS Skia/Dawn archives with immutable source/patch provenance.
2. Consume those exact assets through Pulp's verified dependency manifest and
   SDK release process; preserve matching-provider identity checks.
3. Rebuild Spectr and qualify exact loaded standalone, VST3, CLAP and AU on
   the Intel Mac mini: visible controls, audio, automation and state restoration.
4. Sign/notarize and verify the installed package, then publish accurate notes.

A successful source patch, shader probe, or plugin discovery is not product
qualification. Existing Spectr 1.0.11 Intel plugins remain unqualified.
