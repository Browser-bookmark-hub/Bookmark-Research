# Installation

Bookmark Research supports **Codex, Claude Code, Pi, and DSH** through a shared Skill and Python runtime. Install Python 3.9+ with SQLite FTS5 support and your chosen client first. The [client support table](../README.md#client-support) records what has been verified.

## Codex: install directly from GitHub

The repository includes a Codex marketplace, so you can install without manually cloning it or creating a manifest:

```sh
codex plugin marketplace add kwenxu/Bookmark-Research --ref main
codex plugin add bookmark-research@bookmark-research
codex plugin list
```

Reopen Codex, confirm `bookmark-research` is enabled, and start a new session. Python must be available to the MCP process as `python3`. The native MCP integration has been verified in Codex CLI 0.153.4.

For a local clone or extracted release ZIP, run `codex plugin marketplace add .` from its root instead of adding the GitHub address, then use the same `codex plugin add` command.

These commands follow the [OpenAI plugin packaging documentation](https://developers.openai.com/plugins/build/plugins) and [Codex CLI reference](https://developers.openai.com/codex/cli/reference).

## Start from source or a release ZIP

For the other client adapters, clone this repository:

```sh
git clone https://github.com/kwenxu/Bookmark-Research.git
cd Bookmark-Research
python3 src/cli.py doctor
```

Alternatively, extract `bookmark-research-0.1.0.zip` from the repository's [Releases](https://github.com/kwenxu/Bookmark-Research/releases) to a permanent directory. Open a terminal in the extracted root and run `python3 src/cli.py doctor`; skip the clone commands. Preserve hidden directories such as `.codex-plugin/` and `.agents/`.

The ZIP includes the runtime, Skill, manifests, exporter, documentation, and license. Developer tests are excluded and are not needed to install or use the plugin. After extraction, follow the setup for your client below.

## Ask your agent to install

Copy this prompt into the client you want to use:

```text
Read this plugin's README and installation guide, then help me install it
for the client I am using. I will provide my Bookmark Canvas data package afterward.
https://github.com/kwenxu/Bookmark-Research/blob/main/README.md
```

If the source or ZIP is already on your computer, replace the URL with the absolute path to its README. The agent needs access to that directory to run setup. If your Codex environment includes `$plugin-creator`, it can help with registration and installation.

## Claude Code

From the repository or extracted ZIP root, export and load the native Claude plugin:

```sh
python3 scripts/export_bundle.py --format claude --output exports/claude/bookmark-research
claude --plugin-dir ./exports/claude/bookmark-research
```

The export contains `.claude-plugin/plugin.json`, `.mcp.json`, and the shared Skill. `--plugin-dir` loads it for that Claude Code session. The destination must be new or empty. See the generated README and [Claude Code plugin reference](https://code.claude.com/docs/en/plugins-reference) for setup details.

## Pi

From the repository or extracted ZIP root:

```sh
python3 scripts/export_bundle.py --format pi --output exports/pi/bookmark-research
pi --skill ./exports/pi/bookmark-research/skills/bookmark-research/SKILL.md
```

Use `/skill:bookmark-research` in the session to load the workflow. For persistent registration, run `pi install /absolute/path/to/exports/pi/bookmark-research`, replacing the placeholder with your export directory. The destination must be new or empty.

The package declares `pi.skills`; the Skill calls the bundled Python CLI. This integration does not include a Pi MCP bridge or native tool extension. See the [Pi package documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md).

## DSH / DeepSeek Harness

Use a DSH environment with the official `@deepseek-ai/dsh-mcp-client` dependency available. From the repository or extracted ZIP root, export to the directory you intend to keep. Replace the placeholder paths with your actual paths:

```sh
python3 scripts/export_bundle.py --format dsh --output /absolute/path/to/bookmark-research-dsh
dsh --profile web --patch /absolute/path/to/bookmark-research-dsh/cordis.patch.yml --dump-config
dsh web --patch /absolute/path/to/bookmark-research-dsh/cordis.patch.yml
```

The destination must be new or empty. The generated `cordis.patch.yml` connects the MCP server. To load the shared Skill, point the existing Skill provider's `customSkillDirs` at `/absolute/path/to/bookmark-research-dsh/skills`, or use DSH's documented Skill directories.

The patch contains absolute local paths: regenerate it if the export moves. It is a local adapter, not a relocatable `dsh.bundle` npm package. DSH is in developer preview; consult the generated README and [official MCP client documentation](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md).

Claude Code, Pi, and DSH exports and their shared runtime have been checked. Loading and tool calls inside those clients still need verification.

## Agent Plugins standard format

For a client that implements [Agent Plugins 1.0.0](https://agent-plugins.org/specification), generate its separate standard package:

```sh
python3 scripts/export_bundle.py --format agent-plugin --output exports/agent-plugin/bookmark-research
```

It uses root `plugin.json` and `mcp.json`. This standard format is separate from the Codex native manifest. Follow the generated README for loading requirements.

## First query

In a session with the Skill loaded, send this prompt with your own package's absolute path:

```text
Use Bookmark Research to import /absolute/path/to/my-canvas-package
as the source my-canvas. Work locally: list its sections and groups,
then search for "my research topic" and preserve each folder and card context.
```

For web research, ask: "Use Exa and Parallel to research these targets, read key sources, and save a report." When service access requires credentials, set `EXA_API_KEY` / `PARALLEL_API_KEY` in the environment used to launch the MCP or CLI process. Local bookmark queries work offline.

Settings can be changed through conversation, for example: "Use only Exa for future searches." The index, settings, and page archives live outside the plugin. See [settings and archives](../README.md#settings-and-page-archives) for locations and options.

## Updates

For Codex, refresh the registered marketplace and update or reinstall the plugin through your client or available `$plugin-creator` workflow. Reopen Codex afterward. Codex uses an installed cache, so editing a downloaded source directory does not update an active installation.

For Claude Code, Pi, and DSH, obtain the new source, export it to a new or empty directory, update the client's loaded or registered path, and restart the session. Generate DSH configuration at its final path. Keep user data and settings outside plugin and export directories.

## Build a ZIP (maintainers)

Run from this repository root and choose an output path that does not already exist:

```sh
python3 scripts/build_zip.py --output dist/bookmark-research-0.1.0.zip
```

The ZIP preserves the repository's installation layout and includes the native Codex marketplace. It excludes tests, caches, databases, and personal data. The builder only creates a local archive; publishing a GitHub Release is a separate step.
