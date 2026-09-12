"""Assemble host-owned workflows; this module never starts a host or an agent."""

import json
from pathlib import Path


HOST_SOURCE_FILES = (
    "hosts/shared/workflow.json", "hosts/shared/research-flow.js", "hosts/shared/research-call.py",
    "hosts/claude/runtime.js", "hosts/dsh/runtime.js", "hosts/dsh/workflow-call.py",
    "hosts/pi/runtime.js", "hosts/pi/register-workflow.py",
    "hosts/codex/delegate.md", "hosts/codex/prepare.py",
)


def read_asset(root, relative):
    """Read a curated asset without following source symlinks."""
    current = Path(root)
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Source symlinks are not exported: " + relative)
    if not current.is_file():
        raise ValueError("Required host asset is missing: " + relative)
    return current.read_bytes()


def build_workflow(root, host):
    if host not in ("claude", "dsh", "pi"):
        raise ValueError("Unknown workflow host: " + str(host))
    definition = json.loads(read_asset(root, "hosts/shared/workflow.json"))
    script = read_asset(root, "hosts/" + host + "/runtime.js").decode("utf-8")
    script += "\n" + read_asset(root, "hosts/shared/research-flow.js").decode("utf-8")
    if host == "claude":
        script = "export const meta = " + json.dumps(definition["meta"], ensure_ascii=False, indent=2) + ";\n\n" + script
    return definition, script


def export_host_assets(source, stage, host):
    """Return concrete, host-specific assets in the staged distribution."""
    if host == "agent-plugin":
        return []  # Do not mix client-specific components into the standard format.
    files = {"hosts/shared/research-call.py": read_asset(source, "hosts/shared/research-call.py")}
    if host == "codex":
        for name in ("delegate.md", "prepare.py"):
            relative = "hosts/codex/" + name
            files[relative] = read_asset(source, relative)
    else:
        definition, script = build_workflow(source, host)
        if host == "claude":
            files["workflows/bookmark-research.js"] = script.encode("utf-8")
        else:
            files["workflows/bookmark-research/script.js"] = script.encode("utf-8")
            if host == "pi":
                parameters = definition["parameters"]
                parameters["bridge_path"]["required"] = True
                workflow = {**definition["meta"], "parameters": parameters}
                files["workflows/bookmark-research/workflow.json"] = (
                    json.dumps(workflow, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                relative = "hosts/pi/register-workflow.py"
            else:
                files["workflows/bookmark-research/meta.json"] = (
                    json.dumps(definition["meta"], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                relative = "hosts/dsh/workflow-call.py"
            files[relative] = read_asset(source, relative)
    for relative, content in files.items():
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return sorted(files)
