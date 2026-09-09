#!/usr/bin/env python3
"""Build a source distribution ZIP with the native plugin and host exporter."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from export_bundle import SOURCE_ROOT, VERSION, _copy_plan


EXTRA_FILES = (
    ".codex-plugin/plugin.json",
    ".agents/plugins/marketplace.json",
    "LICENSE",
    "docs/installation.md",
    "README.md",
    "docs/harness-compatibility.md",
    "docs/harness-sources.json",
    "scripts/export_bundle.py",
    "scripts/build_zip.py",
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


def build_zip(output):
    source = SOURCE_ROOT.resolve()
    selected = set(_copy_plan(source)) | {Path(name) for name in EXTRA_FILES}
    payload = {path.as_posix(): _read_file(source / path, source)
               for path in sorted(selected)}

    output = Path(output).expanduser()
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing existing output: " + str(output))
    if output.suffix.lower() != ".zip":
        raise ValueError("Output must have a .zip extension")
    output = output.resolve()
    if output == source or (source in output.parents and source / "dist" not in output.parents):
        raise ValueError("ZIP output inside the repository must be under dist/")
    output.parent.mkdir(parents=True, exist_ok=True)
    archive_root = "bookmark-research-" + VERSION
    # Exclusive creation keeps an existing user archive intact.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, data in sorted(payload.items()):
            archive.writestr(archive_root + "/" + relative, data)
    return {"output": str(output), "archive_root": archive_root, "files": len(payload),
            "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "installed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New ZIP path under dist/ or outside the repository")
    args = parser.parse_args(argv)
    try:
        result = build_zip(args.output)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
