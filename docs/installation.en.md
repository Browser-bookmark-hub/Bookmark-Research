# Installation

**English** · [中文](installation.md)

Install the same plugin for English or Chinese use. See the [user guide](user-guide.en.md) for package inputs, the three research modes, settings and output languages.

## One-command Codex installation

Requirements: Bash, Git, Python 3.9+ with SQLite FTS5, and a Codex CLI supporting native plugin commands and JSON output.

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash
```

The first installation follows `main`, fetching the installer from Git and registering the Git source through Codex. It does not use GitHub Release assets. Codex retains its own source and cache after the temporary download is removed. Start a new thread to load the Skill and tools.

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- install --lang en
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- update --lang en
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- verify --lang en
```

`--lang en` selects English help/onboarding; `--lang zh` selects Chinese. The default `auto` checks `LC_ALL`, then `LC_MESSAGES`, then `LANG`. Chinese locales select Chinese; other or missing locales select English. The bootstrap forwards its selection through `BOOKMARK_RESEARCH_INSTALL_LANG`; an explicit Python `--lang` overrides that hint. Technical errors returned by Git, Codex and the runtime retain their original text. Installation language does not persist a research-language preference.

`--dry-run` reads registration and downloads the installer but does not install or modify Codex registration. `--help` performs no download. Use `--codex /absolute/path/to/codex` and `--timeout 60` when needed; the timeout is per native command, between 1 and 300 seconds.

To select a previously published snapshot on a **first installation**, use `install --ref v0.2.0`. Repeat installations and updates retain the registered ref; an update does not advance a fixed tag. A historical tag uses its own installer and features, so older versions may retain their original onboarding language. The current bootstrap does not send unsupported language flags to historical installers.

This Git installer manages `bookmark-research@bookmark-research`. If the plugin is already installed through `personal` or another marketplace, keep using that source's update flow. Existing sources are not silently replaced or duplicated. Inspect `codex plugin list --json` when identifying a registration.

## Local checkout or ZIP

Published ZIPs and test packs appear on [Releases](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases). Local 0.4.0 validation is recorded separately in [validation](validation-0.4.0.md). Preserve hidden `.codex-plugin/` and `.agents/` directories when extracting.

From a checkout or ZIP containing the installer:

```sh
python3 scripts/install.py install --lang en
python3 scripts/install.py verify --lang en
```

Commands also work from another directory using an absolute script path. Quote paths containing spaces. The installer locates its source from its own file location.

| Command | Behavior |
| --- | --- |
| `install` | Installs or reinstalls the script's local source. |
| `install --source PATH` | Selects another valid local marketplace root. |
| `install --source owner/repo --ref TAG` | Registers the chosen Git ref on the first installation. |
| `install --dry-run` | Prints the planned commands after checking registration. |
| `update` | Refreshes the registered Git source/ref, or reinstalls current local files. |
| `verify` | Checks enabled registration, cache version, FTS5 and MCP initialization/tool discovery. |

`verify --installed-path PATH` accepts the path returned by `codex plugin add --json`. Verification uses an isolated store, does not import bookmarks, and does not test provider authentication. Output on stdout stays JSON; onboarding is printed to stderr. Your effective preferences are shown without overwriting them; unreadable settings are reported and preserved.

The native commands for this repository's explicit marketplace are:

```sh
codex plugin marketplace add .
codex plugin add bookmark-research@bookmark-research
codex plugin list --json
```

The default personal marketplace at `~/.agents/plugins/marketplace.json` is discovered implicitly and uses its own registration. Do not add a second source just to update a personal installation.

## Other clients and clean exports

Exports contain the shared runtime, English execution Skill, Chinese reading copies and paired user/prompt guides. See the [instruction index](instructions.en.md). Exporting writes files; it does not configure a host. Choose an empty/new output directory and keep the final installation path stable.

### Codex clean bundle

```sh
python3 scripts/export_bundle.py --format codex --output exports/codex/bookmark-research
python3 scripts/install.py install --source exports/codex/bookmark-research --lang en
```

Native subagents belong to the host. The bundled `hosts/codex/prepare.py` reads complete inventories and prepares groups; it does not start agents.

### Claude Code

```sh
python3 scripts/export_bundle.py --format claude --output exports/claude/bookmark-research
claude plugin validate --strict ./exports/claude/bookmark-research
claude --plugin-dir ./exports/claude/bookmark-research
```

The export includes `.claude-plugin/plugin.json`, `.mcp.json`, Skill and `workflows/bookmark-research.js`. After creating a research task, explicitly invoke `/bookmark-research:bookmark-research` with its actual `research_id`, a unique `run_key`, and suitable grouping parameters. Dynamic Workflows must be enabled; see the host's configuration. The packaged workflow's resume boundary is the same session. A separately available `/deep-research` command does not itself guarantee enumeration of a local bookmark package.

### Pi

```sh
python3 scripts/export_bundle.py --format pi --output exports/pi/bookmark-research
pi --skill ./exports/pi/bookmark-research/skills/bookmark-research/SKILL.md
```

For persistent registration, `pi install /absolute/path/to/export` changes Pi settings. The package declares `pi.skills`, uses the CLI/stdio bridge, and relies on existing subagent extensions for workflows. Register its project workflow only after choosing the final path:

```sh
python3 exports/pi/bookmark-research/hosts/pi/register-workflow.py --project /absolute/path/to/project
```

The researched workflow combination requires Node 22.19+, Pi 0.83+, `pi-subagents` 0.43.0+, and `pi-subagents-workflows` loaded in the parent session. The registrar does not install extensions. Invoke the loaded `pi_subagent_workflow` tool with the actual research ID and wait for its result; its registry does not add cross-session replay.

### DSH / DeepSeek Harness

```sh
python3 scripts/export_bundle.py --format dsh --output /absolute/path/to/bookmark-research-dsh
dsh --profile web --patch /absolute/path/to/bookmark-research-dsh/cordis.patch.yml --dump-config
dsh web --patch /absolute/path/to/bookmark-research-dsh/cordis.patch.yml
```

Requires the official `@deepseek-ai/dsh-mcp-client`, separate Skill discovery, and configured workflow service/engine for workflow execution. The patch contains absolute paths, so regenerate after moving the export. `hosts/dsh/workflow-call.py --research-id RID --run-key KEY` prepares a call for the host's `workflow` tool; it does not launch a task itself.

### Agent Plugins 1.0.0

```sh
python3 scripts/export_bundle.py --format agent-plugin --output exports/agent-plugin/bookmark-research
```

This uses root `plugin.json` and `mcp.json` for clients supporting that package format. It is separate from Codex's native manifest.

Adapter existence does not mean every host has completed live research. See [host validation](host-validation.json), [compatibility notes](harness-compatibility.md), and each generated README for exact integration details and established limits.

## First use and data locations

Local bookmark queries need no API key or initial configuration. Provide your own directory, ZIP or single-card JSON in the new session:

> Use Bookmark Research to read the package at "/absolute/path/to/my-package". First list its cards, folders, and bookmark counts offline.

Ask for a quick check, comparison, or whole-package investigation naturally. Research uses the current host model. Professional research APIs are optional and require separate configuration; enabling a depth preference does not start a job.

Ordinary exports become reusable snapshots; persistent live directories are checked while MCP runs and before queries. Reuse the existing source for a new export of the same canvas. Single cards are partial inputs and do not delete omitted cards.

`python3 src/cli.py config show` displays effective settings. Defaults are Exa + Parallel search, Exa page reading, ordinary page archiving enabled, research depth `auto`, and professional APIs disabled. Provider credentials belong in the environment that launches the host, not the plugin package. See the [bilingual user guide](user-guide.en.md) for examples and language behavior.

Default data: `~/.local/share/bookmark-research/`. Default settings: `~/.config/bookmark-research/settings.json`. `BOOKMARK_RESEARCH_DATA_DIR`, `BOOKMARK_RESEARCH_CONFIG`, XDG variables and CLI path options can override these. Multiple hosts may share the same paths. Keep settings, SQLite, source versions and evidence outside the plugin/cache and original package.

## Updating

```sh
python3 scripts/install.py update --dry-run --lang en
python3 scripts/install.py update --lang en
python3 scripts/install.py verify --lang en
```

Use the installer matching the existing registration. After updating, start a new session to load the new Skill and tools. If the active session still exposes older MCP tools, use the current bundled CLI for missing operations. Existing data, evidence and settings are retained.
