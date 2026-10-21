# Bookmark Research

**English** · [中文](README.zh.md)

[![GitHub Bookmark-Canvas](https://img.shields.io/badge/GitHub-Bookmark--Canvas-181717?logo=github&logoColor=white)](https://github.com/Browser-bookmark-hub/Bookmark-Canvas)
[![npm version](https://img.shields.io/npm/v/bookmark-research/beta?logo=npm)](https://www.npmjs.com/package/bookmark-research)

Research your bookmarks with verified web sources. Give it a list of bookmark URLs or a [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas) package; it checks every link, searches and reads the web, and writes a cited report you can resume. Works in **Codex, Claude Code and DSH (DeepSeek Harness)**.

[Installation guide](docs/installation.en.md) · [User guide](docs/user-guide.en.md) · [Details](docs/details.en.md) · [npm](https://www.npmjs.com/package/bookmark-research)

> [!NOTE]
> **0.5.0 is a prerelease**, published on npm's `beta` tag; the `latest` tag still points at an older build. Report problems on [GitHub Issues](https://github.com/Browser-bookmark-hub/Bookmark-Research/issues).

## How it works

- **Local understanding.** A Bookmark Canvas package is read as structure, not a flat URL list: card and group layout, edges with their direction and labels, and the same bookmark appearing across cards (spatial context); dated fields, protocol-defined date segments in IDs, and Git commits that changed content (temporal context). These queries run offline.
- **External research takes one of three routes.** Reading a known URL needs no reasoning; agentic search has the host model plan, search, read and follow the gaps; deep research adds a persistent inventory, independent verification, a coverage check and a report. Enabled OpenAI Deep Research or Parallel Task API runs are a separate, optional route; headless-browser and scraping projects are not bundled.
- **Reviewed knowledge store.** Finished research can be compiled into a Wiki of reviewed pages with revisions and links, reused by later questions instead of searching the web again.

## Requirements

- Python 3.9+ with SQLite FTS5 (checked by `bookmark-research doctor`)
- The CLI of at least one client: Codex, Claude Code or DSH. DSH also needs `pnpm`, unless it is the DeepSeek Harness Desktop CLI, which carries its own
- Node 18+ and npm to install a release
- No API key is needed to install, or to query bookmarks locally

## Install

```sh
npx bookmark-research@beta install
```

`@beta` follows the newest prerelease; pin one build with `@0.5.0-beta.16`. Add `--lang zh` for the Chinese wizard. For a permanent command, run `npm install -g bookmark-research`; the GitHub convenience script uses the same npm release (macOS/Linux/WSL):

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash
```

### What the installer asks

1. **Clients** — arrow keys and Space to toggle; detected CLIs are preselected. The install plan is shown for confirmation.
2. **Research depth (optional)** — leave `auto` and the depth is picked from each request; set `quick`, `agentic` or `deep` only to pin one default.
3. **Answer and report language** — follow the question, Chinese or English.
4. **Search and page-reading services** — one ordered multiselect. Unselected providers become the fallback search tier.
5. **Storage** — the default data folder, one custom folder for archives and reports, or reports beside the bookmark file or folder.
6. **Optional professional APIs** — off by default: OpenAI Deep Research or the Parallel Task API.
7. **API keys** — one hidden prompt per selected key, checked immediately; every key is optional.
8. **Service check** — runs on its own and reports each provider; a sample search/read test is opt-in.

Enter keeps the highlighted value, so a full run can be just a few keystrokes. Then start a new client session so the Skill and MCP tools load. Wiki follow-up (suggest and ask first) and the pre-research availability check (15-minute cache) are on by default and need no answer.

### Non-interactive install

| Client | Command | Registers with |
| --- | --- | --- |
| Codex | `npx bookmark-research@beta install codex --non-interactive` | `codex plugin add` |
| Claude Code | `npx bookmark-research@beta install claude --scope user --non-interactive` | `claude plugin install` |
| DSH | `npx bookmark-research@beta install dsh --profile web --non-interactive` | `dsh plugin add` |

Several at once: `npx bookmark-research@beta install claude dsh --profile web --non-interactive`. Project scope: `--scope project --project /path/to/project` (Claude Code). All options: [installation guide](docs/installation.en.md).

**Ask your agent to install it.** Paste this into Codex, Claude Code or DSH:

```text
Install the Bookmark Research plugin into the client you are running in.

1. Identify your own client: codex, claude or dsh.
2. Run: npx bookmark-research@beta install <client> --non-interactive
   - Claude Code: add --scope user (or --scope project --project <dir>).
   - DSH: add --profile <profile>; ask me for the profile name.
3. The command prints JSON. Confirm "verified": true and report any "error".
4. Do not ask me for API keys in chat. Tell me to run `bookmark-research setup`
   in my terminal to enter them.
5. Tell me to start a new session so the Skill and MCP tools load.
```

Install notes:

- **npm is the single release source** for all three hosts; it contains the shared runtime, Skill and host adapters. The installer downloads the release, prepares the host's format, then calls the host's native commands. GitHub hosts source, versions and the installation catalog; unpublished source uses the Python installer. See [distribution policy](docs/distribution.md).
- **DSH installs the release directly.** The package declares `dsh.bundle.patch`, so `dsh plugin --profile <name> add bookmark-research@<version>` installs it with no export first. The reserved `desktop` profile belongs to DeepSeek Harness Desktop; use that app's CLI, which the installer and wizard locate themselves.
- **Windows** often has no working `python3`, so the installer writes the detected Python path into each client's MCP config. Install Codex with `bookmark-research install codex` rather than adding the repository to Codex directly; `bookmark-research status` shows the interpreter in use.

## Configure and update

**Open the configuration page.** Run `bookmark-research` with no arguments in a terminal: the menu covers preferences and API keys, service checks, installing into another client, updates and status. The alias `bookmark` (or `bookmark research`) does the same, and `bookmark-research setup` goes straight to the wizard.

| Task | Command |
| --- | --- |
| Preferences and API keys | `bookmark-research setup` |
| Menu | `bookmark-research` · `bookmark` · `bookmark research` |
| Clients, preferences, storage, recent research, key status | `bookmark-research status` |
| Scripted preferences | `bookmark-research config show` · `bookmark-research config set --input prefs.json` |
| Update or verify all clients | `bookmark-research update` · `bookmark-research verify` |

Use `npx bookmark-research@beta …` if the command is not installed globally. Preferences and keys are user-wide, so one change applies to every installed client; start a new client session afterwards. `--lang zh` shows the wizard and menu in Chinese.

**Update.** `bookmark-research update` refreshes every installed client from its registered source and keeps preferences, keys and data. Re-running `npx bookmark-research@beta install` also upgrades an existing Claude Code or DSH installation in place. A Codex installation keeps the source and version it was registered with; to move it to another version, remove that registration first (`codex plugin marketplace remove bookmark-research`) and install again.

**API keys are optional.** Enter them in `bookmark-research setup` (hidden input, checked immediately, saved in a private local file) or set environment variables, which take precedence.

| Variable | Service | Without it |
| --- | --- | --- |
| `EXA_API_KEY` | Exa search and page reading | Anonymous use where Exa allows it |
| `PARALLEL_API_KEY` | Parallel search and page reading | Free anonymous use with lower limits |
| `TAVILY_API_KEY` | Tavily search fallback and extraction | Keyless mode |
| `JINA_API_KEY` | Jina search | Jina Reader still reads pages anonymously |
| `OPENAI_API_KEY` | Optional OpenAI Deep Research runs | Feature off; host-led research still works |

Keys are never accepted in chat, command arguments or JSON files. Preferences can also be changed by asking the agent in a client session ("Show Bookmark Research settings", "Use only Exa for future searches"); it uses the `update_settings` tool.

## Where data is stored

Nothing is written into your bookmark files or the plugin. The data directory is `$BOOKMARK_RESEARCH_DATA_DIR`, or `${XDG_DATA_HOME:-~/.local/share}/bookmark-research`.

| Location | Contents |
| --- | --- |
| `research/` (or `<input>.bookmark-research/` beside the input) | One folder per research task: report, sources, evidence, and `work/` for the agent's intermediate files |
| `research-locations.json` | Where every task folder is, so tasks stay listed after the location setting changes |
| `knowledge/` | Saved page reads: `sources/` per fetch, `pages/` with each distinct text stored once |
| `wiki/` | Reviewed knowledge pages and revisions; `index.md` catalog and `log.md` timeline |
| `index.sqlite3`, `index.sqlite3.sources/` | Bookmark search index and managed snapshots of imported packages |
| `raw-library.sqlite3` | Rebuildable full-text index for `search_archive` |
| `${XDG_CONFIG_HOME:-~/.config}/bookmark-research/` | `settings.json` and `credentials.json` (private, owner-only) |

Changing the location affects new research only; existing tasks stay where they are.

## Research loops and delegation

The host model plans the research, searches or reads pages, evaluates the evidence and follows unresolved questions. The Skill guides this loop; MCP stores inputs, evidence, budgets and progress. Saving a research task does not start a background agent.

For a grouped report, the plugin supplies a reader → fresh verifier → coverage check → follow-up → report workflow. Codex uses its native subagent tools and the bundled delegation guide; Claude Code and DSH use available host workflow hooks. The host owns concurrency, cancellation and agent lifetime. All children must receive the relevant instructions and access the same research store.

The workflow adapters have simulated contract tests, but a successful install does not prove that every host can execute the complete multi-agent workflow. See [host workflows](skills/bookmark-research/references/host-workflows.md) for requirements and [the validation matrix](docs/validation-0.4.0.md#host-and-provider-boundaries) for observed limits.

## What's inside

A bundle of one Skill, one local MCP server, and the remote MCPs and services that server connects to. The client registers only the local MCP.

| Layer | Component | Runs as | Setup |
| --- | --- | --- | --- |
| Skill | [`bookmark-research`](skills/bookmark-research/SKILL.md) and 11 method references, each with a [Chinese copy](skills/bookmark-research/references/zh/skill-guide.md) | Loaded by the client | None |
| Local MCP | `bookmark-research`, 44 tools (below) | Python process started by the client | Installed for you |
| Remote MCPs, called by the local MCP | [Exa](https://exa.ai) (search, page reading), [Parallel](https://parallel.ai) (search, fallback reading), [Tavily](https://tavily.com) (search fallback) | HTTPS, no local process | Optional API keys |
| HTTP service, called by the local MCP | [Jina Reader](https://jina.ai/reader) (fallback reading; search with a key) | HTTPS | Optional `JINA_API_KEY` |
| Optional client MCPs | Exa Agent, Parallel Task MCP, Tavily Research | Added to your client by you | `bookmark-research setup` shows the steps |

Local MCP tools:

| Group | Tools |
| --- | --- |
| Bookmarks | `sync_package`, `index_status`, `source_history`, `source_remove`, `source_merge`, `search_bookmarks`, `get_context`, `plan_research` |
| Web | `search_web`, `fetch_web`, `search_archive`, `search_providers` |
| Research | `research_readiness`, `research_start`, `research_status`, `research_search`, `research_fetch`, `research_source`, `research_record`, `research_inventory`, `research_coverage`, `research_import_evidence`, `research_finish`, `research_route`, `discovery_bundle` |
| Research services (optional) | `research_services`, `research_service_prepare`, `_start`, `_status`, `_result`, `_cancel`, `_attach`, `_import` |
| Settings | `get_settings`, `update_settings` |
| Wiki and evaluation | `wiki_write`, `wiki_get`, `wiki_list`, `wiki_search`, `wiki_refresh`, `wiki_work`, `wiki_lint`, `wiki_acknowledge`, `evaluate_research` |

Tool descriptions: [details](docs/details.en.md#mcp-tools).

## More

- [Installation guide](docs/installation.en.md): all install options, npm updates and source development
- [User guide](docs/user-guide.en.md): first use, the three research modes, languages
- [Details](docs/details.en.md): data model, research modes, settings, export formats, development checks
- [Architecture](docs/bookmark-research-architecture.md) (Chinese)

Originally developed in [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas). License: [GPL-3.0](LICENSE).
