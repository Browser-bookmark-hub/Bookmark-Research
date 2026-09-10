#!/usr/bin/env python3
"""Build a source distribution ZIP with the native plugin and host exporter."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

from export_bundle import EXCLUDED_DIRECTORIES, SOURCE_ROOT, _copy_plan, read_plugin_manifest


EXTRA_FILES = (
    ".codex-plugin/plugin.json",
    ".agents/plugins/marketplace.json",
    "LICENSE",
    "docs/installation.md",
    "docs/install-design-0.2.0.md",
    "docs/mcp-aggregation-0.2.0.md",
    "docs/provider-smoke-0.2.0.json",
    "docs/research-0.2.0.md",
    "docs/research-sources-0.2.0.json",
    "docs/validation-0.2.0.md",
    "README.md",
    "install.sh",
    "docs/harness-compatibility.md",
    "docs/harness-sources.json",
    "scripts/export_bundle.py",
    "scripts/build_zip.py",
    "scripts/install.py",
    "skills/bookmark-research/agents/openai.yaml",
)


def _read_file(path, root):
    """Read a selected source file without following links outside the package."""
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Source symlinks are not packaged: " + str(relative))
    if not path.is_file():
        raise ValueError("Required distribution file is missing: " + str(relative))
    return path.read_bytes()


def _test_files(source):
    """Include the curated test tree only for an explicit verification pack."""
    root = source / "tests"
    if root.is_symlink() or not root.is_dir():
        raise ValueError("The verification pack requires a local tests directory")
    selected = {Path("scripts/verify_fixture.py")}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(source)
        if any(part.startswith(".") or part.casefold() in EXCLUDED_DIRECTORIES - {"tests", "test"}
               for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("Source symlinks are not packaged: " + relative.as_posix())
        if path.is_file() and (path.suffix == ".py" or
                              relative.parts[:2] == ("tests", "fixtures")
                              and path.suffix in (".json", ".canvas", ".md", ".txt")):
            selected.add(relative)
    if not any(path.name.startswith("test_") and path.suffix == ".py" for path in selected):
        raise ValueError("The verification pack requires Python tests")
    return selected


def build_zip(output, source_root=SOURCE_ROOT, include_tests=False):
    source = Path(source_root).resolve()
    manifest = read_plugin_manifest(source)
    selected = set(_copy_plan(source, include_codex_metadata=True)) | {Path(name) for name in EXTRA_FILES}
    if include_tests:
        selected.update(_test_files(source))
    payload = {path.as_posix(): _read_file(source / path, source)
               for path in sorted(selected)}
    checksums = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n"
                        for name, data in sorted(payload.items()))
    payload["MANIFEST.sha256"] = checksums.encode("utf-8")

    output = Path(output).expanduser()
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing existing output: " + str(output))
    if output.suffix.lower() != ".zip":
        raise ValueError("Output must have a .zip extension")
    output = output.resolve()
    if output == source or (source in output.parents and source / "dist" not in output.parents):
        raise ValueError("ZIP output inside the repository must be under dist/")
    output.parent.mkdir(parents=True, exist_ok=True)
    archive_root = ("bookmark-research-test-pack-" if include_tests else "bookmark-research-") + manifest["version"]
    with tempfile.TemporaryDirectory(prefix=".bookmark-research-zip-", dir=output.parent) as temporary:
        staged = Path(temporary) / "distribution.zip"
        with zipfile.ZipFile(staged, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative, data in sorted(payload.items()):
                # Fixed timestamps, permissions, order and compression make a
                # source snapshot reproducible with the same Python/zlib.
                entry = zipfile.ZipInfo(archive_root + "/" + relative, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        # A same-filesystem hard link publishes only a completed ZIP and cannot
        # replace an existing path, even if another writer wins the race.
        os.link(staged, output)
    return {"output": str(output), "version": manifest["version"], "archive_root": archive_root, "files": len(payload),
            "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "includes_tests": include_tests, "installed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New ZIP path under dist/ or outside the repository")
    parser.add_argument("--include-tests", action="store_true", help="Include tests, synthetic fixtures, and the offline verifier")
    args = parser.parse_args(argv)
    try:
        result = build_zip(args.output, include_tests=args.include_tests)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
