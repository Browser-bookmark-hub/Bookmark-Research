#!/usr/bin/env python3
"""Export shared runtime files into a selected host format, without installing it."""

import argparse
import json
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
FORMATS = ("agent-plugin", "claude", "pi", "dsh")
NAME = "bookmark-research"
VERSION = "0.1.0"
DESCRIPTION = "Query Bookmark Canvas packages through reusable skills and MCP tools."
SCHEMA_ROOT = "https://agent-plugins.org/schemas/1.0.0/"
SHARED_ROOTS = ("src", "config", "skills")
REQUIRED_FILES = (
    "src/archive.py",
    "src/bookmark_index.py",
    "src/cli.py",
    "src/mcp_server.py",
    "src/remote_mcp.py",
    "src/search_results.py",
    "src/settings.py",
    "src/web_search.py",
    "config/providers.json",
    "skills/bookmark-research/SKILL.md",
)
EXCLUDED_DIRECTORIES = {
    "__pycache__", "node_modules", "tests", "test", "build", "dist", "target",
    "cache", "caches", "coverage", "htmlcov", "venv",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".swp", ".swo", ".canvas"}
DATABASE_NAME = re.compile(r"\.(?:db|db3|sqlite|sqlite3|s3db)(?:$|[.-])", re.IGNORECASE)


def _copy_plan(source_root):
    """Enumerate only shared roots; reject links rather than following external files."""
    files = []

    def visit(path):
        relative = path.relative_to(source_root)
        if path.name.startswith(".") or path.name.casefold() in EXCLUDED_DIRECTORIES:
            return
        # Codex presentation metadata is not needed by any of these exports.
        if relative.parts[0] == "skills" and relative.parts[-2:] == ("agents", "openai.yaml"):
            return
        if DATABASE_NAME.search(path.name) or path.suffix.casefold() in EXCLUDED_SUFFIXES:
            return
        if path.is_symlink():
            raise ValueError("Source symlinks are not exported: " + str(relative))
        if path.is_dir():
            # Runtime configuration has one public registry. Do not copy local
            # preferences or credential JSON merely because it is under config/.
            children = [path / "providers.json"] if relative.as_posix() == "config" else sorted(path.iterdir())
            for child in children:
                visit(child)
        elif path.is_file():
            if relative.parts[0] == "src" and path.suffix != ".py":
                return
            with path.open("rb") as stream:
                if stream.read(16) == b"SQLite format 3\x00":
                    return
            files.append(relative)
        else:
            raise ValueError("Unsupported or missing source entry: " + str(relative))

    for root in SHARED_ROOTS:
        visit(source_root / root)
    present = {path.as_posix() for path in files}
    missing = set(REQUIRED_FILES) - present
    if missing:
        raise ValueError("Required shared files are missing: " + ", ".join(sorted(missing)))
    return files


def _check_destination(output):
    if output.is_symlink():
        raise ValueError("Output must not be a symlink: " + str(output))
    if output.exists():
        if not output.is_dir():
            raise ValueError("Output must be a directory: " + str(output))
        if next(output.iterdir(), None) is not None:
            raise ValueError("Refusing nonempty output directory: " + str(output))


def _write_json(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _readme(format_name, output):
    introduction = """# Bookmark Research export

This directory includes the shared Skill, Python CLI, stdio MCP server, and public
provider configuration. It requires Python 3.9+ and the standard library;
`doctor` checks whether the local SQLite build supports FTS5.

Supply your own Bookmark Canvas package through `sync`. A fresh data directory
has no registered sources; existing indexes remain part of your local data.

Run these commands from this directory to check the runtime and provider registry:

```sh
python3 src/cli.py doctor
python3 src/cli.py providers
```

These checks run offline and do not create a persistent database. See the
[shared Skill](skills/bookmark-research/SKILL.md) for query and research workflows.
Exporting generates files; complete the client setup below to load them.

The database location follows the CLI rules: explicit `--db` takes precedence,
then `BOOKMARK_RESEARCH_DATA_DIR/index.sqlite3`, then
`${XDG_DATA_HOME:-~/.local/share}/bookmark-research/index.sqlite3`.
To share an index across clients, pass the same `BOOKMARK_RESEARCH_DATA_DIR` to
each MCP / CLI process, or use the same `--db` path. Clients may filter inherited
environment variables, so check what each client forwards to its child process.

Use `config show` and `config set` to inspect or change settings. The configuration
path is selected by `--config`, `BOOKMARK_RESEARCH_CONFIG`, or
`${XDG_CONFIG_HOME:-~/.config}/bookmark-research/settings.json`, in that order.
Page reads archive actual responses, recognized text, and source records under
`knowledge/` in the data directory by default. You can change this location or
disable archiving. To share settings, forward the same configuration path through
each client, including `BOOKMARK_RESEARCH_CONFIG` or `XDG_CONFIG_HOME` as needed.
See the [settings reference (Chinese)](skills/bookmark-research/references/settings-and-archive.md).

Keep databases, user settings, and page archives outside this package. Exports
exclude existing indexes, caches, tests, and build artifacts. They do not read
API key values from the environment; supply provider credentials at runtime.

"""
    if format_name == "agent-plugin":
        instructions = """## Agent Plugins 1.0.0

The entry files are root `plugin.json` and `mcp.json`, with the Skill under
`skills/bookmark-research/`. The client must implement this specification and
expand `${PLUGIN_ROOT}` in MCP arguments to this package's absolute path.
The command is `python3`; database placement follows the CLI rules above.
This export does not force the use of `${PLUGIN_DATA}`.

This is a separate standard format. Export checks do not establish compatibility
with an untested client or make it equivalent to Codex's native plugin format.

Specification: https://agent-plugins.org/specification
"""
    elif format_name == "claude":
        instructions = """## Claude Code

The entry files are `.claude-plugin/plugin.json` and root `.mcp.json`. MCP
arguments use `${CLAUDE_PLUGIN_ROOT}`. With Claude Code installed, load this
plugin for a session using its actual absolute path:

```sh
claude --plugin-dir /absolute/path/to/this-bundle
```

The native format and shared runtime have been checked. Loading, environment
inheritance, and tool calls inside Claude Code still need client verification.

Reference: https://code.claude.com/docs/en/plugins-reference
"""
    elif format_name == "pi":
        instructions = """## Pi Skill package

`package.json` declares `pi.skills`. The shared Skill calls the bundled Python
CLI. This integration does not include a Pi extension or MCP bridge.

Load the Skill for one session, replacing the path with your export location:

```sh
pi --skill /absolute/path/to/this-bundle/skills/bookmark-research/SKILL.md
```

Use `/skill:bookmark-research` in the session to load its workflow. For persistent
registration, follow Pi's package instructions and run
`pi install /absolute/path/to/this-bundle`. That command changes Pi settings;
the exporter itself does not run it. Actual loading in Pi still needs verification.

Reference: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md
"""
    else:
        patch_path = shlex.quote(str(output / "cordis.patch.yml"))
        skill_root = str(output / "skills")
        instructions = """## DeepSeek Harness local adapter

`cordis.patch.yml` uses the official `@deepseek-ai/dsh-mcp-client` to connect the
stdio MCP tools. **It contains absolute local paths** and must be generated at
its final installation location. It is not a relocatable npm bundle and does not
declare `dsh.bundle`. Install DSH and its official MCP client dependency separately.
If you move this directory, export it again or update the CLI path in the patch.

In a DSH environment with that dependency available, inspect the merged configuration:

```sh
dsh --profile web --patch %s --dump-config
```

Start the client with `dsh web --patch /absolute/path/to/this-bundle/cordis.patch.yml`,
using your actual patch path. These integration commands still need client verification.

The MCP patch does not configure Skill discovery. To use the shared Skill, point
the existing Skill provider's `customSkillDirs` at `%s`, or use the documented
DSH Skill directories. DSH is in developer preview, so setup options may change.

Reference: https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md
""" % (patch_path, skill_root)
    return introduction + instructions


def _write_adapter(stage, format_name, output):
    metadata = {"name": NAME, "version": VERSION, "description": DESCRIPTION}
    if format_name == "agent-plugin":
        _write_json(stage, "plugin.json", {"$schema": SCHEMA_ROOT + "plugin.schema.json", **metadata})
        _write_json(stage, "mcp.json", {
            "$schema": SCHEMA_ROOT + "mcp.schema.json",
            "mcpServers": {NAME: {"type": "stdio", "command": "python3",
                                  "args": ["${PLUGIN_ROOT}/src/cli.py", "serve"]}},
        })
    elif format_name == "claude":
        _write_json(stage, ".claude-plugin/plugin.json", metadata)
        _write_json(stage, ".mcp.json", {"mcpServers": {NAME: {
            "type": "stdio", "command": "python3",
            "args": ["${CLAUDE_PLUGIN_ROOT}/src/cli.py", "serve"],
        }}})
    elif format_name == "pi":
        _write_json(stage, "package.json", {**metadata, "keywords": ["pi-package"],
                                           "pi": {"skills": ["./skills"]}})
    else:
        # JSON strings are valid YAML scalars, including paths with spaces/quotes.
        cli_path = json.dumps(str(output / "src/cli.py"), ensure_ascii=False)
        patch = """- insert:
    - id: bookmark-research-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: bookmark-research
        transport: stdio
        command: python3
        args:
          - %s
          - serve
        failOnStartupError: true
""" % cli_path
        (stage / "cordis.patch.yml").write_text(patch, encoding="utf-8")
    (stage / "README.md").write_text(_readme(format_name, output), encoding="utf-8")


def export_bundle(format_name, output, source_root=SOURCE_ROOT):
    """Publish a staged export to a missing or empty directory; never merge files."""
    if format_name not in FORMATS:
        raise ValueError("Unknown export format: " + str(format_name))
    source_root = Path(source_root).expanduser().resolve()
    output = Path(output).expanduser()
    _check_destination(output)
    output = output.resolve()
    if output == source_root or output in source_root.parents:
        raise ValueError("Output must be separate from the source directory")
    for root in SHARED_ROOTS:
        shared = source_root / root
        if output == shared or shared in output.parents:
            raise ValueError("Output must not be inside a shared source root: " + root)
    files = _copy_plan(source_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bookmark-research-export-", dir=output.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        for relative in files:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_root / relative, destination)
        _write_adapter(stage, format_name, output)
        _check_destination(output)
        if output.exists():
            output.rmdir()  # Only an empty directory can be removed here.
        stage.rename(output)  # Renaming a directory cannot replace nonempty data.
    return {"format": format_name, "output": str(output), "shared_files": len(files),
            "installed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=FORMATS, required=True)
    parser.add_argument("--output", required=True, help="New or empty output directory")
    args = parser.parse_args(argv)
    try:
        result = export_bundle(args.format, args.output)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
