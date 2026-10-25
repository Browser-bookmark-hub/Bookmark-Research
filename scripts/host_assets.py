"""Assemble host-owned workflows; this module never starts a host or an agent."""

import json
from pathlib import Path


HOST_SOURCE_FILES = (
    "hosts/shared/workflow.json", "hosts/shared/research-flow.js", "hosts/shared/research-call.py",
    "hosts/claude/runtime.js", "hosts/claude/commands/research.md", "hosts/dsh/runtime.js", "hosts/dsh/workflow-call.py", "hosts/dsh/plugin.js",
    "hosts/dsh/package.json",
    "hosts/codex/delegate.md", "hosts/codex/prepare.py",
)


def read_asset(root, relative, default=None):
    """Read a curated asset without following source symlinks."""
    current = Path(root)
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Source symlinks are not exported: " + relative)
    if default is not None and not current.exists():
        return default
    if not current.is_file():
        raise ValueError("Required host asset is missing: " + relative)
    return current.read_bytes()


WORKFLOWS = {"bookmark-research": ("hosts/shared/workflow.json", "hosts/shared/research-flow.js")}


def build_workflow(root, host, name="bookmark-research"):
    if host not in ("claude", "dsh"):
        raise ValueError("Unknown workflow host: " + str(host))
    if name not in WORKFLOWS:
        raise ValueError("Unknown workflow: " + str(name))
    relative_definition, relative_script = WORKFLOWS[name]
    definition = json.loads(read_asset(root, relative_definition))
    script = read_asset(root, "hosts/" + host + "/runtime.js").decode("utf-8")
    script += "\n" + read_asset(root, relative_script).decode("utf-8")
    if host == "claude":
        script = "export const meta = " + json.dumps(definition["meta"], ensure_ascii=False, indent=2) + ";\n\n" + script
    return definition, script


def export_host_assets(source, stage, host):
    """Return concrete, host-specific assets in the staged distribution."""
    files = {"hosts/shared/research-call.py": read_asset(source, "hosts/shared/research-call.py")}
    if host == "codex":
        for name in ("delegate.md", "prepare.py"):
            relative = "hosts/codex/" + name
            files[relative] = read_asset(source, relative)
    else:
        if host == "claude":
            command = read_asset(source, "hosts/claude/commands/research.md", default=b"")
            if command:
                files["commands/research.md"] = command
        for name in WORKFLOWS:
            definition, script = build_workflow(source, host, name)
            if host == "claude":
                files["workflows/" + name + ".js"] = script.encode("utf-8")
                continue
            files["workflows/" + name + "/script.js"] = script.encode("utf-8")
            # Scope ESM to the entry module so a package root may stay CommonJS
            # (the npm package keeps a CommonJS bin).
            # Older releases predate the nested manifest. Supply the scope
            # when absent, while still rejecting links or invalid file types.
            files["workflows/" + name + "/meta.json"] = (
                json.dumps(definition["meta"], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if host == "dsh":
            files["hosts/dsh/workflow-call.py"] = read_asset(source, "hosts/dsh/workflow-call.py")
            files["hosts/dsh/plugin.js"] = read_asset(source, "hosts/dsh/plugin.js")
            files["hosts/dsh/package.json"] = read_asset(
                source, "hosts/dsh/package.json", default=b'{"type":"module"}\n')
    for relative, content in files.items():
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return sorted(files)
