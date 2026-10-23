#!/usr/bin/env python3
"""Write, and check, the content-addressed legal manifest for one build cell.

A Skia archive ships compiled code from Skia, Dawn and every third-party
library Skia's DEPS pulls in, but carries no license or notice file.  A
consumer that redistributes the archive's object code cannot tell from the
archive which licenses it inherited.  This manifest answers that from the
build itself, without changing the archive:

    zip member -> static-archive slice -> object member
               -> the object file ninja wrote (matched by content digest)
               -> every source and header that object was compiled from
                  (ninja's compdb and its depfile log)
               -> the license/notice file(s) that govern each source

Matching an object member to its object file by digest, rather than by name,
is what makes the chain exhaustive: archives repeat member names (Dawn's
combined archive has dozens of duplicates), but a member's bytes are the
object's bytes.  ``gn desc <label> deps --all`` is recorded per packaged GN
library as the target graph that produced it.

The manifest is ``exhaustive`` only when every zip member and every object
member resolved to its origin, every object file resolved to at least one
source, and every source resolved to a license file.  Anything that did not
resolve is listed under ``gaps``; ``--check`` fails while any gap remains.
Toolchain headers (the SDK and libc++) are compiled into objects too; they are
listed under ``toolchain_inputs`` with their digests.  They are not sources
this build redistributes, so they are recorded rather than counted as gaps.

License attribution is the nearest ancestor directory, inside the source tree,
that holds a license or notice file; ``license_resolution`` names that rule so
a reviewer knows what was inferred.  A generated file is attributed through
the source path its build directory mirrors.

The manifest contains no timestamps, so the same inputs produce the same
bytes.  ``--content-addressed-dir`` also writes a copy named after its own
SHA-256, which is the name the release publishes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apple_archive  # noqa: E402

SCHEMA = "skia-builder.legal-manifest.v1"
LICENSE_RESOLUTION = "nearest-ancestor-license-file"
LICENSE_NAME_RE = re.compile(
    r"^(LICEN[CS]E|COPYING|NOTICE|UNLICENSE|COPYRIGHT)([._-].*)?$", re.IGNORECASE)
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
CONTENT_ADDRESSED_RE = re.compile(r"\.legal-manifest\.sha256-([0-9a-f]{64})\.json$")
OBJECT_SUFFIXES = (".o", ".obj")
SKIP_DIRS = {".git", ".cipd", "__pycache__"}

Runner = Callable[[list[str], Path], str]


def run_tool(args: list[str], cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def content_addressed_name(archive_name: str, data: bytes) -> str:
    stem = archive_name[:-4] if archive_name.endswith(".zip") else archive_name
    return f"{stem}.legal-manifest.sha256-{hashlib.sha256(data).hexdigest()}.json"


# ---------------------------------------------------------------- ninja ----

def parse_ninja_deps(text: str) -> dict[str, list[str]]:
    """Parse ``ninja -t deps`` output into output -> [inputs]."""
    deps: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if not line.strip():
            current = None
        elif line[0] in " \t":
            if current is not None:
                current.append(line.strip())
        else:
            match = re.match(r"^(.*?): #deps \d+", line)
            current = deps.setdefault(match.group(1), []) if match else None
    return deps


def parse_compdb(text: str) -> dict[str, list[str]]:
    """Parse ``ninja -t compdb`` JSON into absolute output -> [absolute source]."""
    result: dict[str, list[str]] = defaultdict(list)
    for entry in json.loads(text or "[]"):
        output, source = entry.get("output"), entry.get("file")
        if not output or not source:
            continue
        directory = entry.get("directory", ".")
        result[os.path.normpath(os.path.join(directory, output))].append(
            os.path.normpath(os.path.join(directory, source)))
    return dict(result)


def ninja_dirs(out_dir: Path) -> list[Path]:
    """Every ninja build directory under a GN out dir (GN's own, Dawn's CMake)."""
    return sorted(build.parent for build in out_dir.rglob("build.ninja")
                  if (build.parent / ".ninja_deps").exists())


def cmake_source_dir(build_dir: Path) -> Path | None:
    cache = build_dir / "CMakeCache.txt"
    if not cache.exists():
        return None
    for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("CMAKE_HOME_DIRECTORY:"):
            return Path(line.split("=", 1)[1].strip())
    return None


# ----------------------------------------------------------- the graph ----

class BuildGraph:
    """Objects, their sources, and license ownership for one build cell."""

    def __init__(self, source_root: Path, out_dirs: dict[str, Path], ninja: str,
                 runner: Runner = run_tool, builder_root: Path | None = None,
                 toolchain_roots: list[Path] | None = None):
        self.source_root = Path(os.path.realpath(source_root))
        self.toolchain_roots = [Path(os.path.realpath(root)) for root in (toolchain_roots or [])]
        self._real: dict[tuple[Path, str], str] = {}
        self.out_dirs = {arch: Path(os.path.realpath(path)) for arch, path in out_dirs.items()}
        self.builder_root = Path(os.path.realpath(builder_root)) if builder_root else None
        self.ninja = ninja
        self.runner = runner
        self.gaps: list[dict[str, str]] = []
        self.objects: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.sources: dict[str, set[str]] = defaultdict(set)
        self.build_dirs: list[tuple[Path, Path]] = []  # (ninja dir, source dir it mirrors)
        self._license_cache: dict[Path, list[str]] = {}
        self._listing: dict[Path, list[str]] = {}
        self._file_index: dict[str, list[Path]] | None = None
        self.files: dict[str, dict[str, object]] = {}
        self.licenses: dict[str, dict[str, str]] = {}
        self.repositories: dict[str, dict[str, str]] = {}
        self.toolchain_inputs: dict[str, str | None] = {}

    # -- indexing -----------------------------------------------------------
    def index(self) -> None:
        for arch, out_dir in sorted(self.out_dirs.items()):
            for path in sorted(out_dir.rglob("*")):
                if path.suffix in OBJECT_SUFFIXES and path.is_file():
                    self.objects[sha256_file(path)].append((arch, str(path)))
            for build_dir in ninja_dirs(out_dir):
                mirrored = cmake_source_dir(build_dir) or self.source_root
                self.build_dirs.append((build_dir, Path(os.path.realpath(mirrored))))
                compdb = parse_compdb(self.runner([self.ninja, "-C", str(build_dir), "-t", "compdb"],
                                                  build_dir))
                for output, sources in compdb.items():
                    self.sources[os.path.realpath(output)].update(
                        os.path.realpath(source) for source in sources)
                deps = parse_ninja_deps(self.runner([self.ninja, "-C", str(build_dir), "-t", "deps"],
                                                    build_dir))
                for output, inputs in deps.items():
                    self.sources[self.real(build_dir, output)].update(
                        self.real(build_dir, item) for item in inputs)
        # Deepest build directory first, so Dawn's CMake tree wins over GN's.
        self.build_dirs.sort(key=lambda row: len(row[0].parts), reverse=True)

    def real(self, build_dir: Path, item: str) -> str:
        """Resolve a ninja-relative path once; depfile logs repeat the same headers."""
        key = (build_dir, item)
        if key not in self._real:
            self._real[key] = os.path.realpath(os.path.join(build_dir, item))
        return self._real[key]

    def match_object(self, data: bytes) -> list[tuple[str, str]]:
        for candidate in apple_archive.unpadded_candidates(data):
            found = self.objects.get(apple_archive.sha256_bytes(candidate))
            if found:
                return found
        return []

    # -- classification and licenses ---------------------------------------
    def _relative(self, path: Path, root: Path) -> str | None:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return None

    def _entries(self, directory: Path) -> list[str]:
        if directory not in self._listing:
            try:
                self._listing[directory] = sorted(os.listdir(directory))
            except OSError:
                self._listing[directory] = []
        return self._listing[directory]

    def license_for(self, directory: Path) -> list[str]:
        """License ids governing ``directory``: the nearest ancestor's license files."""
        if directory in self._license_cache:
            return self._license_cache[directory]
        found: list[str] = []
        if self._relative(directory, self.source_root) is not None:
            names = [name for name in self._entries(directory)
                     if LICENSE_NAME_RE.match(name) and (directory / name).is_file()]
            if names:
                for name in names:
                    path = directory / name
                    rel = self._relative(path, self.source_root)
                    license_id = f"source:{rel}"
                    if license_id not in self.licenses:
                        text = path.read_bytes().decode("utf-8", errors="replace")
                        self.licenses[license_id] = {"sha256": sha256_file(path), "text": text}
                    found.append(license_id)
            elif directory != self.source_root:
                found = self.license_for(directory.parent)
        self._license_cache[directory] = found
        return found

    def builder_license(self) -> list[str]:
        if not self.builder_root:
            return []
        for name in self._entries(self.builder_root):
            if LICENSE_NAME_RE.match(name):
                path = self.builder_root / name
                license_id = f"builder:{name}"
                self.licenses.setdefault(license_id, {
                    "sha256": sha256_file(path),
                    "text": path.read_bytes().decode("utf-8", errors="replace")})
                return [license_id]
        return []

    def repository_for(self, path: Path) -> str:
        directory = path.parent
        while True:
            rel = self._relative(directory, self.source_root)
            if rel is None:
                return "."
            if (directory / ".git").exists():
                key = rel or "."
                if key not in self.repositories:
                    row: dict[str, str] = {}
                    for field, args in (("commit", ["git", "rev-parse", "HEAD"]),
                                        ("remote", ["git", "config", "--get", "remote.origin.url"])):
                        try:
                            row[field] = self.runner(args, directory).strip()
                        except (OSError, subprocess.CalledProcessError):
                            row[field] = ""
                    self.repositories[key] = row
                return key
            if directory == self.source_root:
                return "."
            directory = directory.parent

    def display_path(self, raw: str) -> str:
        path = Path(raw)
        rel = self._relative(path, self.source_root)
        if rel is not None:
            return f"source:{rel}"
        for arch, out_dir in sorted(self.out_dirs.items()):
            rel = self._relative(path, out_dir)
            if rel is not None:
                return f"generated:{arch}:{rel}"
        return f"toolchain:{raw}"

    def mirrored_source_dir(self, path: Path) -> Path | None:
        for build_dir, mirrored in self.build_dirs:
            rel = self._relative(path, build_dir)
            if rel is None:
                continue
            parts = PurePosixPath(rel).parts[:-1]
            if parts and parts[0] in ("gen", "obj"):
                parts = parts[1:]
            candidate = mirrored.joinpath(*parts) if parts else mirrored
            while self._relative(candidate, self.source_root) is not None and not candidate.is_dir():
                candidate = candidate.parent
            return candidate if self._relative(candidate, self.source_root) is not None else None
        return None

    def file_id(self, raw: str) -> str | None:
        """Record one input file; return its id, or None for a toolchain input."""
        path = Path(raw)
        rel = self._relative(path, self.source_root)
        if rel is not None:
            file_id = f"source:{rel}"
            if file_id not in self.files:
                licenses = self.license_for(path.parent)
                self.files[file_id] = {
                    "sha256": sha256_file(path) if path.is_file() else None,
                    "licenses": licenses,
                    "repository": self.repository_for(path),
                }
                if not licenses:
                    self.gaps.append({"kind": "source-without-license", "path": file_id})
                if not path.is_file():
                    self.gaps.append({"kind": "source-missing", "path": file_id})
            return file_id
        for arch, out_dir in sorted(self.out_dirs.items()):
            rel = self._relative(path, out_dir)
            if rel is None:
                continue
            file_id = f"generated:{arch}:{rel}"
            if file_id not in self.files:
                mirrored = self.mirrored_source_dir(path)
                licenses = self.license_for(mirrored) if mirrored else []
                self.files[file_id] = {
                    "sha256": sha256_file(path) if path.is_file() else None,
                    "licenses": licenses,
                    "generated_from": (f"source:{self._relative(mirrored, self.source_root) or '.'}"
                                       if mirrored else None),
                }
                if not licenses:
                    self.gaps.append({"kind": "generated-without-license", "path": file_id})
            return file_id
        if not any(self._relative(path, root) is not None for root in self.toolchain_roots):
            gap = {"kind": "input-outside-known-roots", "path": raw}
            if gap not in self.gaps:
                self.gaps.append(gap)
            return None
        if raw not in self.toolchain_inputs:
            self.toolchain_inputs[raw] = sha256_file(path) if path.is_file() else None
        return None

    def file_index(self) -> dict[str, list[Path]]:
        """basename -> paths across the source tree and the out dirs."""
        if self._file_index is None:
            index: dict[str, list[Path]] = defaultdict(list)
            for root in [self.source_root, *self.out_dirs.values()]:
                for directory, subdirs, names in os.walk(root):
                    subdirs[:] = sorted(d for d in subdirs if d not in SKIP_DIRS)
                    for name in names:
                        index[name].append(Path(directory) / name)
            self._file_index = index
        return self._file_index

    def locate_packaged_file(self, member: str, data: bytes) -> str | None:
        """The source or generated file a packaged (non-archive) zip member copies."""
        digest = apple_archive.sha256_bytes(data)
        candidates = self.file_index().get(PurePosixPath(member).name, [])
        matches = [path for path in candidates
                   if path.stat().st_size == len(data) and sha256_file(path) == digest]
        if not matches:
            return None
        # Prefer the copy whose path shares the longest suffix with the member.
        member_parts = PurePosixPath(member).parts

        def shared_suffix(path: Path) -> int:
            parts, count = path.parts, 0
            while count < min(len(parts), len(member_parts)) and parts[-1 - count] == member_parts[-1 - count]:
                count += 1
            return count

        best = sorted(matches, key=lambda path: (-shared_suffix(path), str(path)))[0]
        return self.file_id(str(best))

    # -- gn ------------------------------------------------------------------
    def target_graph(self, gn: str | None, libraries: list[str]) -> dict[str, object]:
        graph: dict[str, object] = {}
        if not gn:
            return {"error": "gn binary not found"}
        for arch, out_dir in sorted(self.out_dirs.items()):
            per_arch: dict[str, object] = {}
            try:
                labels = self.runner([gn, "ls", str(out_dir), "--type=static_library"],
                                     self.source_root).split()
            except (OSError, subprocess.CalledProcessError) as error:
                graph[arch] = {"error": f"gn ls failed: {error}"}
                continue
            for library in libraries:
                stem = library[3:] if library.startswith("lib") else library
                stem = stem.rsplit(".", 1)[0]
                matched = None
                for label in labels:
                    if label.rsplit(":", 1)[-1] != stem:
                        continue
                    try:
                        outputs = self.runner([gn, "desc", str(out_dir), label, "outputs"],
                                              self.source_root).split()
                    except (OSError, subprocess.CalledProcessError):
                        continue
                    if any(output.endswith("/" + library) for output in outputs):
                        matched = label
                        break
                if matched is None:
                    per_arch[library] = {"label": None,
                                         "note": "not a GN static_library (for example Dawn's CMake action)"}
                    continue
                try:
                    deps = sorted(self.runner([gn, "desc", str(out_dir), matched, "deps", "--all"],
                                              self.source_root).split())
                    per_arch[library] = {"label": matched, "deps_all": deps}
                except (OSError, subprocess.CalledProcessError) as error:
                    per_arch[library] = {"label": matched, "error": f"gn desc deps failed: {error}"}
            graph[arch] = per_arch
        return graph


# ------------------------------------------------------------- manifest ----

DEPS_CHECKOUTS = {"skia": ".", "dawn": "third_party/externals/dawn"}


def source_revisions(graph: BuildGraph, expected: dict[str, str]) -> dict[str, object]:
    """The exact Skia/Dawn commits checked out, against the revisions the lock pinned."""
    rows: dict[str, object] = {}
    for name, rel in sorted(DEPS_CHECKOUTS.items()):
        directory = graph.source_root / rel
        try:
            actual = graph.runner(["git", "rev-parse", "HEAD"], directory).strip()
        except (OSError, subprocess.CalledProcessError):
            actual = None
        row = {"checkout": rel, "commit": actual, "expected": expected.get(name)}
        if actual is None or not re.fullmatch(r"[0-9a-f]{40}", actual):
            graph.gaps.append({"kind": "source-revision-unknown", "path": f"source:{rel}"})
        elif expected.get(name) and expected[name] != actual:
            graph.gaps.append({"kind": "source-revision-mismatch",
                               "path": f"{name}: built {actual}, lock pinned {expected[name]}"})
        rows[name] = row
    return rows


def build_manifest(archive: Path, graph: BuildGraph, cell: dict[str, object],
                   gn: str | None = None, expected_revisions: dict[str, str] | None = None
                   ) -> dict[str, object]:
    graph.index()
    revisions = source_revisions(graph, expected_revisions or {})
    zip_members: list[dict[str, object]] = []
    static_archives: dict[str, object] = {}
    with zipfile.ZipFile(archive) as handle:
        for info in sorted(handle.infolist(), key=lambda item: item.filename):
            if info.is_dir():
                continue
            data = handle.read(info)
            row: dict[str, object] = {"name": info.filename, "sha256": apple_archive.sha256_bytes(data),
                                      "size": len(data)}
            if data.startswith(apple_archive.AR_MAGIC) or apple_archive.slices(data)[0].data.startswith(
                    apple_archive.AR_MAGIC):
                row["kind"] = "static-archive"
                static_archives[info.filename] = describe_static_archive(info.filename, data, graph)
            elif PurePosixPath(info.filename).name == "gn_args.txt":
                row["kind"] = "builder-metadata"
                row["licenses"] = graph.builder_license()
            else:
                row["kind"] = "packaged-file"
                file_id = graph.locate_packaged_file(info.filename, data)
                row["origin"] = file_id
                if file_id is None:
                    graph.gaps.append({"kind": "packaged-file-unmatched", "path": info.filename})
                    row["licenses"] = []
                else:
                    row["licenses"] = graph.files[file_id]["licenses"]
            zip_members.append(row)

    libraries = sorted({PurePosixPath(name).name for name in static_archives})
    gaps = sorted({json.dumps(gap, sort_keys=True) for gap in graph.gaps})
    manifest = {
        "schema": SCHEMA,
        "license_resolution": LICENSE_RESOLUTION,
        "archive": {"name": archive.name, "sha256": sha256_file(archive), "size": archive.stat().st_size},
        "cell": cell,
        "source_revisions": revisions,
        "repositories": dict(sorted(graph.repositories.items())),
        "zip_members": zip_members,
        "static_archives": static_archives,
        "files": dict(sorted(graph.files.items())),
        "licenses": dict(sorted(graph.licenses.items())),
        "toolchain_inputs": dict(sorted(graph.toolchain_inputs.items())),
        "target_graph": graph.target_graph(gn, libraries),
        "gaps": [json.loads(gap) for gap in gaps],
    }
    manifest["exhaustive"] = not manifest["gaps"]
    manifest["summary"] = {
        "zip_members": len(zip_members),
        "static_archives": len(static_archives),
        "object_members": sum(len(arch["members"]) for row in static_archives.values()
                              for arch in row["slices"].values()),
        "files": len(graph.files),
        "licenses": len(graph.licenses),
        "toolchain_inputs": len(graph.toolchain_inputs),
        "gaps": len(manifest["gaps"]),
    }
    return manifest


def describe_static_archive(name: str, data: bytes, graph: BuildGraph) -> dict[str, object]:
    slices_out: dict[str, object] = {}
    archive_licenses: set[str] = set()
    for piece in apple_archive.slices(data):
        parsed = apple_archive.parse_archive(piece.data)
        members = []
        for index, member in enumerate(parsed.members):
            objects = graph.match_object(member.data)
            where = f"{name}[{piece.arch}]#{index}:{member.name}"
            row: dict[str, object] = {"name": member.name, "sha256": member.sha256}
            if not objects:
                graph.gaps.append({"kind": "object-member-unmatched", "path": where})
                row.update(objects=[], licenses=[], inputs=0)
                members.append(row)
                continue
            inputs: set[str] = set()
            for _arch, obj in objects:
                inputs |= graph.sources.get(obj, set())
            if not inputs:
                graph.gaps.append({"kind": "object-without-sources", "path": where})
            licenses: set[str] = set()
            for raw in sorted(inputs):
                file_id = graph.file_id(raw)
                if file_id is not None:
                    licenses.update(graph.files[file_id]["licenses"])
            if inputs and not licenses:
                graph.gaps.append({"kind": "object-without-license", "path": where})
            archive_licenses |= licenses
            row.update(
                objects=sorted({graph.display_path(obj) for _arch, obj in objects}),
                licenses=sorted(licenses),
                inputs=len(inputs),
                inputs_sha256=hashlib.sha256("\n".join(sorted(
                    graph.display_path(raw) for raw in inputs)).encode()).hexdigest(),
            )
            members.append(row)
        slices_out[piece.arch] = {
            "sha256": apple_archive.sha256_bytes(piece.data),
            "members": members,
            "symbol_tables": [table.sha256 for table in parsed.symbol_tables],
        }
    return {"slices": slices_out, "licenses": sorted(archive_licenses)}


# ------------------------------------------------------------ validation ----

def validate_manifest(manifest: dict, archive: Path | None = None) -> list[str]:
    """Return every reason this manifest does not prove an exhaustive inventory."""
    problems: list[str] = []
    if manifest.get("schema") != SCHEMA:
        problems.append(f"schema = {manifest.get('schema')!r}")
    if manifest.get("license_resolution") != LICENSE_RESOLUTION:
        problems.append(f"license_resolution = {manifest.get('license_resolution')!r}")
    if manifest.get("gaps"):
        problems.append(f"{len(manifest['gaps'])} unresolved gap(s), first: {manifest['gaps'][0]}")
    if manifest.get("exhaustive") is not True:
        problems.append("exhaustive is not true")
    licenses = manifest.get("licenses") or {}
    for license_id, row in licenses.items():
        text = row.get("text", "")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != row.get("sha256"):
            # Only flagged when the stored text decodes to the recorded file;
            # a non-UTF-8 license is stored with replacement characters.
            if "�" not in text:
                problems.append(f"license {license_id} text does not match its sha256")
    files = manifest.get("files") or {}
    for file_id, row in files.items():
        if not row.get("licenses"):
            problems.append(f"file {file_id} has no license")
        for license_id in row.get("licenses", []):
            if license_id not in licenses:
                problems.append(f"file {file_id} names unknown license {license_id}")
    for name, row in (manifest.get("static_archives") or {}).items():
        for arch, piece in row.get("slices", {}).items():
            for member in piece.get("members", []):
                if not member.get("objects") or not member.get("licenses"):
                    problems.append(f"{name}[{arch}] member {member.get('name')} is unresolved")
    if archive is not None:
        actual = sha256_file(archive)
        if manifest.get("archive", {}).get("sha256") != actual:
            problems.append(f"archive sha256 {actual} != manifest {manifest.get('archive', {}).get('sha256')}")
        listed = {row["name"]: row["sha256"] for row in manifest.get("zip_members", [])}
        with zipfile.ZipFile(archive) as handle:
            for info in handle.infolist():
                if info.is_dir():
                    continue
                data = handle.read(info)
                if listed.get(info.filename) != apple_archive.sha256_bytes(data):
                    problems.append(f"zip member {info.filename} is not listed with its digest")
                    continue
                recorded = (manifest.get("static_archives") or {}).get(info.filename)
                pieces = apple_archive.slices(data)
                if not pieces[0].data.startswith(apple_archive.AR_MAGIC):
                    continue
                if recorded is None:
                    problems.append(f"static archive {info.filename} has no member inventory")
                    continue
                for piece in pieces:
                    expected = [member.sha256 for member in apple_archive.parse_archive(piece.data).members]
                    got = [member["sha256"] for member in recorded["slices"].get(piece.arch, {}).get("members", [])]
                    if expected != got:
                        problems.append(f"{info.filename}[{piece.arch}] member inventory differs from the archive")
            if set(listed) != {info.filename for info in handle.infolist() if not info.is_dir()}:
                problems.append("manifest lists zip members the archive does not contain")
    return problems


# ------------------------------------------------------------------ main ----

def default_toolchain_roots() -> list[Path]:
    roots = [Path("/Library/Developer/CommandLineTools"), Path("/usr")]
    developer = os.environ.get("DEVELOPER_DIR")
    if not developer:
        try:
            developer = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True,
                                       check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            developer = ""
    if developer:
        # The developer dir is <Xcode>.app/Contents/Developer; SDKs and the
        # toolchain both live under the app bundle.
        roots.insert(0, Path(developer).parents[1] if developer.endswith("Contents/Developer")
                     else Path(developer))
    return roots


def parse_out_dirs(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        arch, sep, path = value.partition("=")
        if not sep or not arch or not path:
            raise argparse.ArgumentTypeError(f"--out-dir must be ARCH=PATH, got {value!r}")
        result[arch] = Path(path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path, help="manifest to write (or, with --check, to read)")
    parser.add_argument("--archive", type=Path, required=True, help="the packaged cell zip")
    parser.add_argument("--source-root", type=Path, help="Skia checkout (build/src/skia)")
    parser.add_argument("--out-dir", action="append", default=[], metavar="ARCH=PATH",
                        help="GN out dir for one architecture; repeat per architecture")
    parser.add_argument("--builder-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ninja", default="ninja")
    parser.add_argument("--toolchain-root", action="append", type=Path, default=[],
                        help="directory whose headers are toolchain inputs (SDK, libc++); "
                             "defaults to the active developer dir, the Command Line Tools and /usr")
    parser.add_argument("--gn", help="GN binary; defaults to <source-root>/bin/gn")
    parser.add_argument("--expect-skia-revision", default="",
                        help="Skia commit the release lock pinned; a different checkout is a gap")
    parser.add_argument("--expect-dawn-revision", default="",
                        help="Dawn commit the release lock pinned; a different checkout is a gap")
    parser.add_argument("--platform", default="")
    parser.add_argument("--variant", default="")
    parser.add_argument("--configuration", default="")
    parser.add_argument("--content-addressed-dir", type=Path,
                        help="also write <archive>.legal-manifest.sha256-<digest>.json here")
    parser.add_argument("--check", action="store_true",
                        help="validate an existing manifest against --archive instead of writing one")
    args = parser.parse_args(argv)

    if args.check:
        manifest = json.loads(args.output.read_text(encoding="utf-8"))
        match = CONTENT_ADDRESSED_RE.search(args.output.name)
        problems = validate_manifest(manifest, args.archive)
        if match and match.group(1) != sha256_file(args.output):
            problems.append(f"{args.output.name} does not carry its own sha256")
        for problem in problems:
            print(f"legal-manifest: {problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"legal-manifest: exhaustive: {manifest['summary']}")
        return 0

    if not args.source_root or not args.out_dir:
        parser.error("--source-root and at least one --out-dir are required to write a manifest")
    out_dirs = parse_out_dirs(args.out_dir)
    gn = args.gn or str(args.source_root / "bin" / "gn")
    if not Path(gn).exists():
        gn = None
    graph = BuildGraph(args.source_root, out_dirs, args.ninja, builder_root=args.builder_root,
                       toolchain_roots=args.toolchain_root or default_toolchain_roots())
    cell = {"platform": args.platform, "variant": args.variant,
            "configuration": args.configuration, "architectures": sorted(out_dirs)}
    expected = {name: value for name, value in (("skia", args.expect_skia_revision),
                                                ("dawn", args.expect_dawn_revision)) if value}
    manifest = build_manifest(args.archive, graph, cell, gn, expected)
    data = canonical_bytes(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(f"legal-manifest: wrote {args.output} ({len(data)} bytes) "
          f"exhaustive={manifest['exhaustive']} {manifest['summary']}")
    for gap in manifest["gaps"][:50]:
        print(f"legal-manifest: gap: {gap}", file=sys.stderr)
    # Only an exhaustive manifest gets the name a release publishes.
    if args.content_addressed_dir and manifest["exhaustive"]:
        args.content_addressed_dir.mkdir(parents=True, exist_ok=True)
        target = args.content_addressed_dir / content_addressed_name(args.archive.name, data)
        target.write_bytes(data)
        print(f"legal-manifest: content-addressed copy {target}")
    return 0 if manifest["exhaustive"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
