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

Note: you may need to call 

```bash
ulimit -n 2048
```

in order to increase the number of files that can be opened at once.

## Minimum OS versions (deployment targets)

The output libraries are built for these minimum OS versions. The values track
Google's upstream, so they stay consistent with what Chrome/Dawn are built and
tested against.

| Platform | Minimum | Set where | Tracks |
|----------|---------|-----------|--------|
| macOS | **13.0** (Ventura) | `MAC_MIN_VERSION` in `build-skia.py` (env `MAC_DEPLOYMENT_TARGET`); applied as `-target {arch}-apple-macos{MAC_MIN_VERSION}` on the mac path | Chromium `mac_deployment_target` in `build/config/mac/mac_sdk.gni` (12.0 @ M150, 13.0 @ M151) |
| iOS | 14.0 | `IOS_MIN_VERSION` (Dawn needs iOS 14+ for C++ atomic wait/notify) | Dawn iOS requirement |
| visionOS | 1.0 | `VISIONOS_MIN_VERSION` | — |
| Linux | host glibc (see note) | not yet pinned | — |
| Windows | Skia GN default | Skia's `WINVER`/`_WIN32_WINNT` | Skia defaults |

**To change the macOS minimum:** edit `MAC_MIN_VERSION` in `build-skia.py`, or set
`MAC_DEPLOYMENT_TARGET` in the environment before building. Prior to this being
applied, the mac path passed no `-target`, so Dawn's objects inherited the CI
runner's macOS as their `minos` (Skia's own libs escaped this because Skia's GN
pins its own macOS target internally).

**Linux note:** the Linux build currently passes no `--sysroot`, so the resulting
`.so` binds against the *build host's* glibc — i.e. the libraries require whatever
glibc the build machine has. To get a predictable, low Linux floor, build against a
pinned sysroot (as Chromium does with its Debian sysroot). Tracked as a follow-up.

### Build for macOS universal (arm64 & x86_64 intel)

```bash
python3 build-skia.py -config Release -branch chrome/m150 mac
```

### Build for iOS (including x86_64 simulator)

```bash
python3 build-skia.py -config Release -branch chrome/m150 ios
```

### Build an XCFramework

```bash
python3 build-skia.py -config Release -branch chrome/m150 xcframework
```

## Building on Windows 

On Windows, you need to install LLVM in order to compile Skia with clang, as recommened by the authors.

LLVM should be installed in `C:\Program Files\LLVM\`

```bash
py -3 build-skia.py -config Release -branch chrome/m150 win
```

## CI / GitHub Actions

The repository includes a GitHub Actions workflow (`.github/workflows/build-skia.yml`) that builds all platforms in parallel and creates releases tagged with the Skia branch name.

### Workflow Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `skia_branch` | Skia branch to build | `chrome/m150` |
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
gh workflow run build-skia.yml -f skia_branch=chrome/m150

# Retry Apple builds on the Intel macOS runner if GitHub's M1 runners are stalled
gh workflow run build-skia.yml -f skia_branch=chrome/m150 -f platforms=all -f apple_runner=macos-15-intel
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
gh workflow run watch-skia.yml -f skia_branch=chrome/m150 -f dry_run=true

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
gh workflow run create-xcframework.yml -f release_tag=chrome/m150
```

This downloads mac, ios, and visionos artifacts from the specified release and creates a combined XCFramework.
