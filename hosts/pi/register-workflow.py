#!/usr/bin/env python3
"""Register the saved workflow in one project, without changing Pi settings."""

import argparse
import json
from pathlib import Path
import sys
import tempfile


def register(project):
    project = Path(project).expanduser().absolute()
    if not project.is_dir() or project.is_symlink():
        raise ValueError("Project must be an existing, nonsymlink directory")
    project = project.resolve()
    root = Path(__file__).resolve().parents[2]
    source = root / "workflows/bookmark-research"
    if source.is_dir():
        manifest = json.loads((source / "workflow.json").read_text())
        script = (source / "script.js").read_bytes()
    else:
        sys.path.insert(0, str(root / "scripts"))
        from host_assets import build_workflow
        definition, script = build_workflow(root, "pi")
        manifest = {**definition["meta"], "parameters": definition["parameters"]}
        script = script.encode("utf-8")
    manifest["parameters"]["bridge_path"] = {
        "type": "string", "default": str(root / "hosts/shared/research-call.py"),
        "description": "Shared research tool bridge in this stable bundle location",
    }
    target = project / ".pi/subagent-workflows/bookmark-research"
    current = project
    for part in target.relative_to(project).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Refusing a symlink registration path: " + str(current))
    payload = {"workflow.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
               "script.js": script}
    if target.exists():
        same = target.is_dir() and {p.name for p in target.iterdir()} == set(payload) and all(
            (target / name).is_file() and not (target / name).is_symlink() and
            (target / name).read_bytes() == content for name, content in payload.items())
        if not same:
            raise ValueError("Existing workflow differs; preserve it and choose a clean project registration location")
        return {"path": str(target), "changed": False, "extensions_installed": False}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bookmark-workflow-", dir=target.parent) as temporary:
        stage = Path(temporary) / "bookmark-research"
        stage.mkdir()
        for name, content in payload.items():
            (stage / name).write_bytes(content)
        stage.rename(target)
    return {"path": str(target), "changed": True, "extensions_installed": False}


def main():
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
