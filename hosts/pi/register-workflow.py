#!/usr/bin/env python3
"""Register the saved workflows in one project, without changing Pi settings."""

import argparse
import json
from pathlib import Path
import sys
import tempfile

WORKFLOWS = ("bookmark-research", "bookmark-research-discovery")


def register_one(root, project, name):
    source = root / "workflows" / name
    if source.is_dir():
        manifest = json.loads((source / "workflow.json").read_text(encoding="utf-8"))
        script = (source / "script.js").read_bytes()
    else:
        sys.path.insert(0, str(root / "scripts"))
        from host_assets import build_workflow
        definition, script = build_workflow(root, "pi", name)
        manifest = {**definition["meta"], "parameters": definition["parameters"]}
        script = script.encode("utf-8")
    manifest["parameters"]["bridge_path"] = {
        "type": "string", "default": str(root / "hosts/shared/research-call.py"),
        "description": "Shared research tool bridge in this stable bundle location",
    }
    target = project / ".pi/subagent-workflows" / name
    current = project
    for part in target.relative_to(project).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Refusing a symlink registration path: " + str(current))
    payload = {"workflow.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
               "script.js": script}
    if target.exists():
        same = target.is_dir() and {entry.name for entry in target.iterdir()} == set(payload) and all(
            (target / entry).is_file() and not (target / entry).is_symlink() and
            (target / entry).read_bytes() == content for entry, content in payload.items())
        if not same:
            raise ValueError("Existing workflow differs; preserve it and choose a clean project registration location")
        return {"name": name, "path": str(target), "changed": False}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bookmark-workflow-", dir=target.parent) as temporary:
        stage = Path(temporary) / name
        stage.mkdir()
        for entry, content in payload.items():
            (stage / entry).write_bytes(content)
        stage.rename(target)
    return {"name": name, "path": str(target), "changed": True}


def register(project):
    project = Path(project).expanduser().absolute()
    if not project.is_dir() or project.is_symlink():
        raise ValueError("Project must be an existing, nonsymlink directory")
    project = project.resolve()
    root = Path(__file__).resolve().parents[2]
    workflows = [register_one(root, project, name) for name in WORKFLOWS]
    return {"changed": any(row["changed"] for row in workflows), "workflows": workflows,
            "extensions_installed": False}


def main():
    for stream in (sys.stdout, sys.stderr):  # Windows pipes default to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Existing project whose .pi/subagent-workflows directory to use")
    options = parser.parse_args()
    try:
        print(json.dumps(register(options.project), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
