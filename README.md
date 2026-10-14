# SKIA BUILDER

This is a python script and github actions workflow to manage building static libraries for [SKIA](https://skia.org/).

![output](https://github.com/user-attachments/assets/b40cc273-272c-4f38-a64f-968327408fa5)

The script automates the process of building the libraries for various platforms (macOS, iOS, Windows, WASM). It handles the setup of the build environment, cloning of the Skia repository, configuration of build parameters, and compilation. The script also includes functionality for creating universal binaries for macOS and an XCFramework for apple platforms.

The GN Args are supplied in constants which you will need to tweak if you want to modify the build.

## Building

Skia's build scripts requires ninja and python3 to be installed on all platforms. Emscripten is installed via skia.

## Helper commands

There is a Makefile with helper commands to build the libraries for each platform (from macOS). On windows you can use the `build-win.sh` script.

```bash
make example-mac # Build example for macOS (will also build libSkia etc)
./example/build-mac/example
Image saved as output.png
```

Other options:
```bash
make skia-mac # Build libraries for macOS
make skia-ios # Build libraries for iOS
make skia-wasm # Build libraries for WASM
make skia-xcframework # Build XCFramework
make example-mac # Build example for macOS
make example-wasm # Build example for WASM
make serve-wasm # Serve the WASM example
```

## Build script

The script is called as follows

```
build-skia.py [-h] [-config {Debug,Release}] [-archs ARCHS] [-branch BRANCH] [--shallow] {mac,ios,win,spm,wasm}
```

## Building on macOS

### Published macOS release assets

Each release publishes **three** independent macOS GPU archives — do not assume
Apple Silicon is the only one:

| Asset | Arch | Use |
|-------|------|-----|
| `skia-build-mac-arm64-gpu-release.zip` | `arm64` | Apple Silicon only |
| `skia-build-mac-x86_64-gpu-release.zip` | `x86_64` | Intel only |
| `skia-build-mac-universal-gpu-release.zip` | `arm64;x86_64` | universal / lipo'd — links thin **or** fat |

A consumer targeting `CMAKE_OSX_ARCHITECTURES=x86_64` should pull `mac-x86_64`
(or the fat `mac-universal`, which links fine into a thin target); a universal
build pulls `mac-universal`. All three ship every static lib (`libskia.a`,
`libdawn_combined.a`, HarfBuzz/ICU/skparagraph/skottie/…) fat or thin to match.

Note: you may need to call `ulimit -n 2048` in order to increase the number of
files that can be opened at once.

```bash
ulimit -n 2048
```

### Published Windows GPU release assets

Windows publishes separate GPU archives for each supported architecture:

| Asset | Arch | Use |
|-------|------|-----|
| `skia-build-win-arm64-gpu-release.zip` | `arm64` | Windows 11 ARM64, including Apple Silicon Windows VMs |
| `skia-build-win-x64-gpu-release.zip` | `x64` | Windows x64 and x64 emulation on Windows ARM64 |
| `skia-build-win-x64-gpu-debug.zip` | `x64` | Windows x64 debug investigations |

An experimental `arm64ec` producer can be configured locally with
`-archs arm64ec`. It emits ARM64EC objects using MSVC `/arm64EC` and
`/machine:ARM64EC`; it is intentionally not in the published matrix until a
matching Skia/Dawn and Pulp consumer link/runtime receipt exists.

The ARM64 archive uses Dawn/Direct3D; OpenGL is disabled for that target. The
release workflow builds the ARM64 archive alongside the x64 archives. To
backfill an existing milestone release without rebuilding every platform, run
the workflow with `platforms=win-arm64`, `release_tag=chrome/m153`,
`skia_branch=chrome/m153`, and `skip_release=false`. A backfill builds the exact
Skia/Dawn revision recorded in that release's `skia-release-lock.json`, not the
branch head, so the new asset matches the rest of the release.

### Published assets are immutable

Consumers pin every release asset by sha256 (Pulp's `tools/deps/manifest.json`
does), so no workflow replaces published bytes in place.
`tools/release_asset_guard.py` is the only path that puts a file on a release:

- an asset that does not exist yet is uploaded;
- an asset whose bytes are identical is skipped, so re-running a release or a
  backfill is safe;
- an asset whose bytes differ is refused, and nothing is uploaded. The refusal
  prints the published and new sha256 and the consumer repin steps.

A deliberate rebuild (for example the Windows ARM64 rebuild with the MSVC ABI)
re-dispatches with `replace_asset=<asset file name>` and
`replace_reason='<why the published bytes are wrong>'`. The guard replaces only
that asset, proves the new digest landed, and appends the old and new sha256,
the reason, the run, and the commit to an "Asset replacements" section in the
release notes. Repin consumers in the same change. `create-xcframework.yml`
takes `replace_reason` for `Skia.xcframework.zip` the same way.

Each Windows GPU archive includes `msvc-toolchain.json`. It records the exact
MSVC toolset, Windows SDK, compiler drivers, architecture, and `/MT` or `/MTd`
runtime selection used to produce the static libraries. Consumers must use the
MSVC STL/CRT from the recorded toolset or a newer toolset that has passed a
consumer link probe. Older toolsets, libc++, MinGW, `/NODEFAULTLIB`, and mixed
CRT settings are unsupported until a matching link receipt exists. The static
archives intentionally leave `__std_*` MSVC STL helpers for the consumer's
runtime library to resolve.

The receipt is resolved the way Skia's GN build finds MSVC (`gn/find_msvc.py`,
including its `vswhere` fallback for Visual Studio 18) and then cross-checked
against the `cl.exe` GN wrote into `toolchain.ninja`. A receipt that records
`unknown` or a compiler error instead of a version fails the build, and
`tools/check_windows_archive.py` re-checks every Windows archive before it is
published: the receipt must be valid for the archive's architecture and
configuration, and every `.lib` must contain objects for that architecture only.

## Minimum OS versions (deployment targets)

A consumer that links these prebuilts inherits `max(Chromium's floor, its own
toolchain constraints)`. These builds track Google's upstream floor and never ship
*below* it; two platforms land slightly *above*, for the reasons noted.

| Platform | Minimum | Set where | Tracks / why |
|----------|---------|-----------|--------------|
| macOS | **13.0** (Ventura) | `MAC_MIN_VERSION` in `build-skia.py` (env `MAC_DEPLOYMENT_TARGET`); `-target {arch}-apple-macos{ver}` | Chromium `mac_deployment_target` (`build/config/mac/mac_sdk.gni`; 13.0 @ M151). *A consumer using `std::format` / `std::to_chars(float)` needs **13.3** — Apple's libc++ gates those above 13.0, not Skia.* |
| iOS | 14.0 | `IOS_MIN_VERSION` (Dawn needs iOS 14+ for C++ atomic wait/notify) | Dawn iOS requirement |
| visionOS | 1.0 | `VISIONOS_MIN_VERSION` | — |
| Linux x64 | **glibc 2.34** | `portable-linux-x64` job in `build-skia.yml` (Ubuntu 22.04 container) | See Linux note. Chromium reaches ~2.28 via its own sysroot; we use a stock 22.04 base. Loadable on Ubuntu 22.04+ / Debian 12+ / RHEL 9+ / Fedora 35+. |
| Windows | **Windows 10** (`_WIN32_WINNT` / `WINVER` `0x0A00`) | Skia/Dawn GN default | Chromium `build/config/win/BUILD.gn` |

**macOS — two build systems, two levers (both driven by `MAC_MIN_VERSION`):** Skia (GN)
takes the target from `-target` in `extra_cflags`; **Dawn's separate CMake sub-build
(`cmake_dawn/`) does not inherit GN flags** and reads `MACOSX_DEPLOYMENT_TARGET` from the
environment, which the mac path exports. Set neither and Dawn's objects silently inherit
the CI runner's macOS (e.g. 15.0), re-leaking the floor.

**Linux — why 2.34 and not lower:** the `portable-linux-x64` job builds in an
`ubuntu:22.04` container (gcc-11), the oldest clean **C++20** base — Chromium's own sysroot
breaks C++20 for Skia, and older bases (Rocky 8, Debian 11) fail on GLIBCXX / C++20. The
default `ubuntu-latest` cell leaked glibc ~2.39; the container drops it to 2.34. The floor is
*measured* by a `--whole-archive` link-probe over `libskia.a` + `libdawn_combined.a` (a static
`.a`'s undefined glibc refs are unversioned until linked).

### Build for macOS universal (arm64 & x86_64 intel)

```bash
python3 build-skia.py -config Release -branch chrome/m152 mac
```

### Build for iOS (including x86_64 simulator)

```bash
python3 build-skia.py -config Release -branch chrome/m152 ios
```

### Build an XCFramework

```bash
python3 build-skia.py -config Release -branch chrome/m152 xcframework
```

## Building on Windows 

On Windows, you need to install LLVM in order to compile Skia with clang, as recommened by the authors.

LLVM should be installed in `C:\Program Files\LLVM\`

```bash
py -3 build-skia.py -config Release -branch chrome/m152 win
```

On Windows 11 ARM64, pass `-archs arm64`. The ARM64 GPU build uses Dawn and
Direct3D (OpenGL is disabled for this target):

```bash
py -3 build-skia.py -config Release -branch chrome/m153 -archs arm64 win
```

The published `arm64` archive is a pure ARM64 provider. It is not an
ARM64EC/ARM64X provider and must not be consumed by an ARM64EC or ARM64X Pulp
target. Those targets require a separately produced Skia/Dawn archive built
with the matching ARM64EC/ARM64X compiler and CRT; until that producer lane
exists, consumers should fail closed rather than selecting the ARM64 or x64
archive by host architecture.

To exercise the experimental producer locally (on a Windows ARM64 host with
the matching MSVC toolset):

```bash
py -3 build-skia.py -config Release -branch chrome/m153 -archs arm64ec win
```

Do not rename a pure `arm64` archive to `arm64ec`; the archive identity must
match the object and CRT ABI that produced it.

The producer also has an opt-in Windows ARM CI lane. It uploads a workflow
artifact only and never edits a release asset:

```bash
ghapp workflow run build-skia.yml -f platforms=win-arm64ec \
  -f skip_release=true -f skia_branch=chrome/m153
```

## CI / GitHub Actions

The repository includes a GitHub Actions workflow (`.github/workflows/build-skia.yml`) that builds all platforms in parallel and creates releases tagged with the Skia branch name.

Before the build matrix starts, the workflow resolves the milestone branch once and pins
every platform to that immutable Skia SHA. The release includes
`skia-release-lock.json`, which records the exact Skia and Skia-DEPS Dawn revisions.
After a full, non-test milestone release publishes, the workflow sends a
`skia_milestone_published` dispatch to `danielraffel/v8-builder`. That repo resolves the
matching Chromium milestone-branch V8 revision and publishes it through its sealed
all-platform lane; its independent weekly LKGR releases continue unchanged. Configure
the skia-builder Actions secret `V8_BUILDER_DISPATCH_TOKEN` with a fine-grained personal
access token that can access `danielraffel/v8-builder` and has repository **Contents:
write** permission. A classic personal access token instead needs the `repo` scope. The
dispatch is intentionally after release creation and carries the immutable producer lock.
The receiver is idempotent for complete releases and already-active matching builds.

Milestone release notes link to the corresponding [matched V8 releases](https://github.com/danielraffel/v8-builder/releases).
The two releases form a tested Skia/Dawn/V8 tuple, but consumers can download only
Skia/Dawn, only V8, or both.

### Workflow Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `skia_branch` | Skia branch to build | `chrome/m152` |
| `platforms` | Platforms to build (comma-separated or `all`) | `all` |
| `skip_release` | Skip creating release | `false` |
| `test_mode` | Skip build, create dummy files | `false` |
| `apple_runner` | macOS runner label for Apple builds (`macos-15`, `macos-15-intel`, or `macos-14`) | `macos-15` |

### Trigger Builds

```bash
# Build all platforms and create release
gh workflow run build-skia.yml

# Build specific platform(s) without creating a release
gh workflow run build-skia.yml -f platforms=visionos -f skip_release=true
gh workflow run build-skia.yml -f platforms=mac,ios -f skip_release=true
gh workflow run build-skia.yml -f platforms=win -f skip_release=true

# Build with a different Skia branch
gh workflow run build-skia.yml -f skia_branch=chrome/m152

# Retry Apple builds on the Intel macOS runner if GitHub's M1 runners are stalled
gh workflow run build-skia.yml -f skia_branch=chrome/m152 -f platforms=all -f apple_runner=macos-15-intel
```

### Automatic Skia Updates

The `Watch Skia` workflow (`.github/workflows/watch-skia.yml`) runs once per day and checks `google/skia` for the latest `chrome/m*` branch. If this repository does not already have a GitHub release tagged with that branch name, it dispatches `build-skia.yml` with `platforms=all` and `skip_release=false`.

You can also run the watcher manually:

```bash
gh workflow run watch-skia.yml
```

To verify the watcher without starting the full build matrix, run it in dry-run mode against a branch that exists upstream:

```bash
# Should report no dispatch when the release already exists
gh workflow run watch-skia.yml -f skia_branch=chrome/m152 -f dry_run=true

# Should report that a build would be dispatched when the release is missing
gh workflow run watch-skia.yml -f skia_branch=chrome/m148 -f dry_run=true
```

The watcher decision logic also has a local fixture test:

```bash
make test-watch-skia
```

### Check CI Status

```bash
gh run list
gh run view <run-id> --log-failed
```

### Create XCFramework from Existing Release

If you've already built all platforms, you can create an XCFramework without rebuilding:

```bash
gh workflow run create-xcframework.yml -f release_tag=chrome/m152
```

This downloads mac, ios, and visionos artifacts from the specified release and creates a combined XCFramework.
