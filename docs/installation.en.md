# Installation

**English** · [中文](installation.md)

Install the same plugin for English or Chinese use. See the [user guide](user-guide.en.md) for package inputs, the three research modes, settings and output languages.

## The `bookmark-research` command (recommended)

After `npm install -g bookmark-research`, type `bookmark-research` to open a menu for preferences and API keys, service checks, installing into another client, updates and status. Subcommands work directly: `install [HOST...]`, `update`, `verify`, `setup`, `status`, `config show|set`, `doctor`. The npm package is only an entry point that runs the bundled Python installer and runtime, so Python 3.9+ is still required; it works on native Windows, macOS and Linux. Run the latest `main` with `npx github:Browser-bookmark-hub/Bookmark-Research`. Without arguments and without a terminal (agents/CI) it prints status JSON instead of opening the menu.

<a id="one-command-codex-installation"></a>

## One-command installation

Requirements: Bash, Git, Python 3.9+ with SQLite FTS5, and the selected host CLI (Codex, Claude Code, Pi or DSH). Other hosts do not need Codex installed.

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash
```

The terminal wizard detects available CLIs and lets you choose one or more hosts: arrow keys move, Space toggles, Enter confirms, and detected hosts are preselected. It then asks each host's scope/project/profile and shows a summary to confirm before installing. It works with piped installation by reading `/dev/tty`; without a capable terminal, or with `BOOKMARK_RESEARCH_PLAIN=1`, it uses plain numbered prompts. If no supported CLI is found, the bootstrap stops before downloading. `--interactive` requires a terminal; `--non-interactive` never prompts. Without a terminal or an explicit host, the legacy default is Codex. Agents should pass `--host`.

The first installation follows `main` and uses the selected host's native registration commands. It does not use GitHub Release assets. Codex retains its own Git source/cache; other hosts receive complete persistent exports and installation receipts under `${XDG_DATA_HOME:-~/.local/share}/bookmark-research/installations/` (override with `--install-dir`). Temporary downloads can then be removed. Start a new host session to load the Skill and tools.

From a checkout, choose a host directly:

```sh
bash install.sh install --host codex
bash install.sh install --host claude --scope user
bash install.sh install --host pi --scope project --project /absolute/path/to/project
bash install.sh install --host dsh --profile web
bash install.sh install --host claude --host dsh --profile web   # same as --host claude,dsh
```

Repeat `--host` or comma-separate names to install several hosts in one run. `--scope`/`--project` then apply to Claude/Pi (`local` is rejected when Pi is selected) and `--profile` to DSH; an option that matches no selected host is rejected. Hosts are installed in order; a failure is recorded for that host and the rest continue. Guided setup runs once afterwards, since preferences and keys are user-wide. A single host keeps the usual JSON result; several hosts produce `{"results": [...], "setup": {...}}`, with exit code 1 if any host or setup failed.

Claude supports `user`, `project` and `local`; Pi supports `user` and `project`. Project/local scope requires `--project PATH`; DSH requires the actual `--profile NAME`. Pass the same scope/project/profile and custom `--install-dir` on update/verify. The wizard asks for missing target choices on install. `--claude`, `--pi`, `--dsh` and `--codex` select a custom executable.

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- install --lang en
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- update --host codex --lang en
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- verify --host codex --lang en
```

`--lang en` selects English help/onboarding; `--lang zh` selects Chinese. The default `auto` checks `LC_ALL`, then `LC_MESSAGES`, then `LANG`. Chinese locales select Chinese; other or missing locales select English. The bootstrap forwards its selection through `BOOKMARK_RESEARCH_INSTALL_LANG`; an explicit Python `--lang` overrides that hint. Technical errors returned by Git, Codex and the runtime retain their original text. Installation language does not persist a research-language preference.

`--dry-run` reads registration and downloads/prepares a temporary export but does not install, save preferences or modify host registration. `--help` performs no download. `--timeout 60` limits each native command to 1–300 seconds; human input has no timeout. A service readiness timeout is configured separately.

To select a previously published snapshot on a **first installation**, use `install --ref v0.2.0`. Repeat installations and updates retain the registered ref; an update does not advance a fixed tag. A historical tag uses its own installer and features, so older versions may retain their original onboarding language. The current bootstrap does not send unsupported language flags to historical installers.

The Codex branch manages `bookmark-research@bookmark-research`. If already installed through `personal` or another marketplace, keep using that source's update flow. Other hosts also reject conflicting sources and preserve existing settings. Claude receives a content-derived native version so changed local/main code refreshes its cache even when the release version is unchanged. Pi retains the persistent local package. DSH installs a relocatable native bundle in the selected profile.

## Guided setup and readiness

After installation, the wizard offers research depth, answer language, primary/fallback search providers, page readers, archive location, check frequency and optional professional APIs. Enter keeps displayed preferences. API-key input is masked; each key is checked immediately and can be re-entered if the check fails. Keys are saved separately in `credentials.json` next to settings, with mode `0600`; this local file is not encrypted. `BOOKMARK_RESEARCH_CREDENTIALS` overrides its path, and environment variables override saved keys. No keys enter preferences, packages, receipts or readiness output. A ChatGPT/Codex login is separate from an OpenAI API key.

Rerun setup at any time with `python3 <installed path>/src/cli.py setup`; the exact command (`getting_started.setup_command` in the JSON result) is printed after installation. From a checkout:

```sh
python3 src/cli.py setup --host claude_code --lang en
python3 src/cli.py setup --non-interactive --input /absolute/path/to/preferences.json --skip-checks
python3 src/cli.py readiness --host codex --refresh
python3 src/cli.py readiness --provider exa --test-retrieval
```

An agent can use `install --host pi --non-interactive --preferences FILE --skip-checks`. Preferences are a partial settings object, for example:

```json
{"research":{"depth":"agentic","response_language":"en"},"readiness":{"mode":"cached","ttl_seconds":900},"professional_research":{"enabled":false}}
```

Default checks contact selected retrieval catalogs and enabled professional services. They distinguish configured keys, catalog reachability, tested search/read operations and verified authorization scope. `--skip-checks` prevents these service requests; downloading/installing the plugin still requires network access where applicable. `--test-retrieval` opts into sample searches and example.com reads that may use provider quota. OpenAI's check reads model metadata; Parallel's check discovers authenticated Task MCP tools. Neither proves permission/quota for a paid research run, and no professional job is started.

Before each new web research question, the Skill calls `research_readiness` with the actual host and observed tools. `cached` refreshes on first use, key/config changes or expiry (15 minutes); `always` checks each new question; `manual` waits for `--refresh`. Reuse checks within an investigation. Local bookmark queries need no network check. Direct CLI users run `readiness` before their search/read commands.

Search/read adapters are included. Optional Exa Agent, Parallel Task and Tavily Research MCPs belong to the host: setup displays endpoint-specific add/login steps, and readiness returns the same structured guidance. Inspect existing registrations before adding one. Codex uses `codex mcp list` and, where supported, `codex mcp login`; Claude uses `claude mcp list` and `/mcp`. Pi needs a separately selected MCP extension for those optional native tools; DSH uses its official MCP client's profile configuration and authentication headers. Tool visibility alone is never reported as a successful login. Plugin key storage does not authenticate a separately registered host MCP. See [settings and remediation](../skills/bookmark-research/references/settings-and-archive.md).

Optional service failures appear under `setup.needs_attention` and do not block local work or other providers. Native install or setup failures return nonzero, with installation and setup status reported separately. Historical versions without setup can still install without requesting that newer feature.

## Local checkout or ZIP

Published ZIPs and test packs appear on [Releases](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases). Local 0.4.0 validation is recorded separately in [validation](validation-0.4.0.md). Preserve hidden `.codex-plugin/` and `.agents/` directories when extracting.

From a checkout or ZIP containing the installer:

```sh
python3 scripts/install.py install --interactive --lang en
python3 scripts/install.py verify --host codex --lang en
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

The Python installer accepts the same host/setup flags. `verify --installed-path PATH` is Codex-only. Verification uses an isolated store, does not import bookmarks, and does not test provider authentication. Stdout stays JSON; prompts use the terminal and diagnostics use stderr. The setup stage persists only selected preferences; unreadable settings are reported and preserved.

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

Persistent installation: `python3 scripts/install.py install --host claude --scope user`. For a manually exported package or session-only development:

```sh
python3 scripts/export_bundle.py --format claude --output exports/claude/bookmark-research
claude plugin validate --strict ./exports/claude/bookmark-research
claude --plugin-dir ./exports/claude/bookmark-research
```

The export includes `.claude-plugin/plugin.json`, `.mcp.json`, Skill and `workflows/bookmark-research.js`. After creating a research task, explicitly invoke `/bookmark-research:bookmark-research` with its actual `research_id`, a unique `run_key`, and suitable grouping parameters. Dynamic Workflows must be enabled; see the host's configuration. The packaged workflow's resume boundary is the same session. A separately available `/deep-research` command does not itself guarantee enumeration of a local bookmark package.

### Pi

Persistent installation: `python3 scripts/install.py install --host pi`. The basic Skill + CLI does not require subagent extensions. For a manual export:

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
python3 scripts/install.py install --host dsh --profile web
python3 scripts/install.py verify --host dsh --profile web
```

The installer exports a relocatable `dsh.bundle` and calls `dsh plugin --profile web add PATH`. `dsh plugin` delegates to pnpm, so install it first (`npm install -g pnpm` or `corepack enable pnpm`); without it the installer stops before creating a profile and the wizard shows DSH as unavailable. The bundle registers the shared Skill and resolves Python/MCP paths from the installed module. The selected profile must provide the Skill registry and official MCP client. For manual distribution, export with `--format dsh` and install the stable export using that native command. The legacy `cordis.patch.yml` still contains absolute paths and requires separate Skill discovery. Workflow execution separately requires the host service/engine; `hosts/dsh/workflow-call.py --research-id RID --run-key KEY` prepares a call without launching it.

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

`python3 src/cli.py config show` displays effective settings. Defaults are Exa + Parallel search, Exa page reading, ordinary page archiving enabled, research depth and response language `auto`, cached readiness checks, and professional APIs disabled. Configure keys through setup or the host environment. See the [bilingual user guide](user-guide.en.md) for examples.

Default data: `~/.local/share/bookmark-research/`. Default settings: `~/.config/bookmark-research/settings.json`. `BOOKMARK_RESEARCH_DATA_DIR`, `BOOKMARK_RESEARCH_CONFIG`, XDG variables and CLI path options can override these. Multiple hosts may share the same paths. Keep settings, SQLite, source versions and evidence outside the plugin/cache and original package.

## Updating

```sh
python3 scripts/install.py update --host claude --scope user --dry-run --lang en
python3 scripts/install.py update --host claude --scope user --lang en
python3 scripts/install.py verify --host claude --scope user --lang en
```

Use the installer matching the existing registration. After updating, start a new session to load the new Skill and tools. If the active session still exposes older MCP tools, use the current bundled CLI for missing operations. Existing data, evidence and settings are retained.
