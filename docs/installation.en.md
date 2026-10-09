# Installation

**English** · [中文](installation.md)

Install the same plugin for English or Chinese use. See the [user guide](user-guide.en.md) for package inputs, the three research modes, settings and output languages.

## The `bookmark-research` command (recommended)

After `npm install -g bookmark-research`, type `bookmark-research` to open a menu for preferences and API keys, service checks, installing into another client, updates and status. Subcommands work directly: `install [HOST...]`, `update`, `verify`, `setup`, `status`, `config show|set`, `doctor`. npm is the single release package for all four hosts and includes the Python installer, runtime, Skill and adapters, so Python 3.9+ is still required; it works on native Windows, macOS and Linux. Use `npx bookmark-research@latest install HOST` for a release, and the Python source installer for unpublished development changes. Without arguments and without a terminal (agents/CI) it prints status JSON instead of opening the menu.

<a id="one-command-codex-installation"></a>

## One-command installation

Requirements: Bash, Node.js/npm, Python 3.9+ with SQLite FTS5, and the selected host CLI (Codex, Claude Code, Pi or DSH). Other hosts do not need Codex installed.

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash
```

The terminal wizard detects available CLIs and lets you choose one or more hosts: arrow keys move, Space toggles, Enter confirms, and detected hosts are preselected. It then asks each host's scope/project/profile and shows a summary to confirm before installing. It works with piped installation by reading `/dev/tty`; without a capable terminal, or with `BOOKMARK_RESEARCH_PLAIN=1`, it uses plain numbered prompts. The npm installer checks the selected host before native registration. `--interactive` requires a terminal; `--non-interactive` never prompts. Without a terminal or an explicit host, the legacy default is Codex. Agents should pass `--host`.

The first installation selects `npm:bookmark-research` (`latest`). All four hosts receive a clean export from that release through their native registration commands. The recorded source is the npm package and selector, not the temporary download or npx cache. `update` downloads that selector again; it does not need the original cache. GitHub serves this convenience script and source catalogs, not a separate release ZIP. Persistent host exports live under `${XDG_DATA_HOME:-~/.local/share}/bookmark-research/installations/` (override with `BOOKMARK_RESEARCH_INSTALL_DIR`; other hosts also accept `--install-dir`). Temporary downloads can then be removed. Start a new host session to load the Skill and tools.

Choose a release host directly, even when running the bootstrap from a checkout:

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

`--lang en` selects English help/onboarding; `--lang zh` selects Chinese. The default `auto` checks `LC_ALL`, then `LC_MESSAGES`, then `LANG`. Chinese locales select Chinese; other or missing locales select English. The bootstrap forwards `--lang` unchanged to the npm installer; `BOOKMARK_RESEARCH_INSTALL_LANG` remains an optional locale override. Technical errors returned by Git, Codex and the runtime retain their original text. Installation language does not persist a research-language preference.

`--dry-run` reads registration and downloads/prepares a temporary export but does not install, save preferences or modify host registration. `--help` performs no download. `--timeout 60` limits each native command to 1–300 seconds; human input has no timeout. A service readiness timeout is configured separately.

For a pinned release on first installation, use `npx bookmark-research@latest install HOST --source npm:bookmark-research@0.5.0-beta.3`. The same selector is retained on reinstall/update. Without a pin, `latest` advances with npm publication. `--ref` belongs to explicit Git development sources only; it no longer chooses a release through the bootstrap. Existing Git/local installations retain their original source; they are not silently migrated to npm. To adopt npm, resolve the old registration using the host’s own commands first.

The Codex branch manages `bookmark-research@bookmark-research`. If already installed through `personal` or another marketplace, keep using that source's update flow. Other hosts also reject conflicting sources and preserve existing settings. Claude receives a content-derived native version so changed local/main code refreshes its cache even when the release version is unchanged. Pi retains the persistent local package. DSH installs a relocatable native bundle in the selected profile.

## Guided setup and readiness

After installation, the wizard offers research depth, answer language, primary/fallback search providers, page readers, archive location, where research reports and evidence go (central folder, a custom central path, or beside the bookmark file/folder with fallback to the central folder; new tasks only), whether finished research updates the Wiki (suggest and ask first, automatic, off), check frequency and optional professional APIs. Enter keeps displayed preferences. API-key input is masked; each key is checked immediately and can be re-entered if the check fails. Keys are saved separately in `credentials.json` next to settings, with mode `0600`; this local file is not encrypted. `BOOKMARK_RESEARCH_CREDENTIALS` overrides its path, and environment variables override saved keys. No keys enter preferences, packages, receipts or readiness output. A ChatGPT/Codex login is separate from an OpenAI API key.

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

## Source development and historical ZIPs

GitHub [Releases](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases) retain version notes and npm links; installation and test attachments have been withdrawn. Release packages come from npm. ZIP/export helpers remain available for local development and tests; preserve required plugin manifests when extracting a historical package.

From a checkout or ZIP containing the installer:

```sh
python3 scripts/install.py install --interactive --lang en
python3 scripts/install.py verify --host codex --lang en
```

Commands also work from another directory using an absolute script path. Quote paths containing spaces. The installer locates its source from its own file location.

Local checkouts, npm packages, extracted ZIPs and new Git sources are exported before Codex registration. Personal `.claude/`, `.codex/`, `.pi/`, `.agent/`, `.git/` and old build artifacts are excluded; plugin declarations and runtime content remain. The original source is recorded beside the persistent export, and `update` exports it again. Installation compares the native cache file list with the clean export. Keep local sources and the persistent export for future updates. Git origins record the repository and selected ref: branches advance on update; tags and commits remain selected. Reinstalling without `--ref` retains the saved ref; an explicit different ref is rejected.

An older installation registered directly from a local source migrates through native `marketplace remove/add` and `plugin add` commands only when its catalog contains this plugin alone. The original source stays the same; user configuration is never edited by the installer. `--dry-run` previews the migration. Conflicting sources and catalogs containing other plugins are preserved for resolution in Codex.

For an older Git marketplace, Codex retains its registration and ref. The installer runs native `marketplace upgrade`, exports that fetched checkout, and passes the clean path through per-command `-c` overrides to native `plugin add`. Those overrides do not rewrite the Git registration. This also preserves pins whose ref is absent from native listing JSON. This fallback applies to historical catalogs that point at their repository root. The current release catalog selects an npm package; native updates retain that package source. A Git checkout or GitHub source archive can contain development files; it is not the plugin cache.

| Command | Behavior |
| --- | --- |
| `install` | Installs or reinstalls the script's local source. |
| `install --source PATH` | Selects another valid local marketplace root. |
| `install --source owner/repo --ref TAG` | Exports the chosen Git ref and registers the clean bundle. |
| `install --dry-run` | Prints the planned commands after checking registration. |
| `install --source npm:bookmark-research[@VERSION]` | Installs the shared npm release for the selected host. |
| `update` | Re-fetches the recorded npm selector, refreshes the Git source/ref, or reinstalls local files. |
| `verify` | Checks enabled registration, cache version, FTS5 and MCP initialization/tool discovery. |

The Python installer accepts the same host/setup flags. `verify --installed-path PATH` is Codex-only. Verification uses an isolated store, does not import bookmarks, and does not test provider authentication. Stdout stays JSON; prompts use the terminal and diagnostics use stderr. The setup stage persists only selected preferences; unreadable settings are reported and preserved.

### Native Codex installation of the published release

The repository marketplace points to the published npm version recorded in its `source.version` field. Codex downloads that package without lifecycle scripts, then owns registration and caching. Adding the repository installs the published release, including its released Skill; it does not install unpublished source changes from `main`.

```sh
codex plugin marketplace add Browser-bookmark-hub/Bookmark-Research --ref main
codex plugin add bookmark-research@bookmark-research
```

For subsequent native updates, run `codex plugin marketplace upgrade bookmark-research`, then `codex plugin add bookmark-research@bookmark-research`. The pinned package changes only when the catalog is updated after that version is published; a frozen Git catalog retains its selected npm version. `bookmark-research update codex` also preserves a native release source. npm and a working `python3` with SQLite FTS5 must be on the host's PATH. On Windows without a working `python3`, use the installer described above to pin the detected interpreter.

To install the current checkout, use `python3 scripts/install.py install --source /absolute/path/to/checkout`. To install current source from Git, use `install --source owner/repo --ref BRANCH_OR_TAG`. Both prepare clean exports of the selected source. If this marketplace is already registered, keep its existing source or explicitly choose the intended source in Codex first.

To install current source manually with native commands, first export to a new persistent directory. Exported bundles have a local marketplace pointing at their own clean root, so this path does not fetch the published npm release:

```sh
python3 scripts/export_bundle.py --format codex --output /absolute/path/to/clean/bookmark-research
codex plugin marketplace add /absolute/path/to/clean/bookmark-research
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

The installer exports a relocatable `dsh.bundle` and calls `dsh plugin --profile web add PATH`. A released package also installs straight from the registry: it declares `dsh.bundle.patch` and ships that layer, so `dsh plugin --profile web add bookmark-research@VERSION` — or the DSH plugin manager — needs no export first. The layer resolves the interpreter, the working directory and the MCP argument list from the installed module, so nothing is tied to the machine that built it; the selected profile must still provide the Skill registry and the official `@deepseek-ai/dsh-mcp-client`.

`dsh plugin` delegates to pnpm. A generic CLI therefore needs pnpm on PATH (`npm install -g pnpm` or `corepack enable pnpm`) and the installer stops before creating a profile without it; the DeepSeek Harness Desktop CLI carries its own pnpm and needs none. DeepSeek Harness Desktop reserves the `desktop` profile — its launcher refuses every boot and dump for that name — so install it with the app's own CLI, and verification reads the persisted layer instead of `--dump-config`:

```sh
python3 scripts/install.py install --host dsh --profile desktop \
  --dsh "<DSH app>/Contents/Resources/runtime/cli/bin/dsh"
```

The legacy `cordis.patch.yml` still contains absolute paths and requires separate Skill discovery. Workflow execution separately requires the host service/engine; `hosts/dsh/workflow-call.py --research-id RID --run-key KEY` prepares a call without launching it.

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
