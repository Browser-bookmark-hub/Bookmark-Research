# Bookmark Research

**English** · [中文](README.zh.md)

[![GitHub Bookmark-Canvas](https://img.shields.io/badge/GitHub-Bookmark--Canvas-181717?logo=github&logoColor=white)](https://github.com/Browser-bookmark-hub/Bookmark-Canvas)
[![npm version](https://img.shields.io/npm/v/bookmark-research?logo=npm)](https://www.npmjs.com/package/bookmark-research)

Research with bookmark context and retain reusable knowledge. Read a [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas) package, investigate with the host model or a research API, and save sourced Wiki pages. Works in **Codex, Claude Code and DeepSeek Harness (dsh)**.

[Installation guide](docs/installation.en.md) · [User guide](docs/user-guide.en.md) · [Details](docs/details.en.md) · [npm](https://www.npmjs.com/package/bookmark-research)

## Version 0.6.0

The stable release includes bilingual Canvas package support, safer Exa batch reading that isolates ambiguous pages, and concise installation/update summaries. Installation prints the version, actual paths, checks and any required action. Use `--json` for complete structured diagnostics; `--non-interactive` only disables prompts. Existing settings, credentials and research data are retained during upgrades.

## How it works

- **Local understanding.** A Bookmark Canvas package is read as structure, not a flat URL list: card and group layout, edges with their direction and labels, and the same bookmark appearing across cards (spatial context); dated fields, protocol-defined date segments in IDs, and Git commits that changed content (temporal context). These queries run offline.
- **External research takes one of three routes.** Reading a known URL needs no reasoning; agentic search has the host model plan, search, read and follow the gaps; deep research can use the OpenAI or Parallel research API directly. Persistent inventories and coverage checks are available when you explicitly need a complete collection audit. Host browsers and crawlers can supply source text.
- **Reviewed knowledge store.** Finished research can be compiled into a Wiki of reviewed pages with revisions and links, reused by later questions instead of searching the web again.

## Requirements

- Python 3.9+ with SQLite FTS5 (checked by `bookmark-research doctor`)
- The CLI of at least one client: Codex, Claude Code or DeepSeek Harness (dsh). DeepSeek Harness (dsh) also needs `pnpm`, unless it is the DeepSeek Harness Desktop CLI, which carries its own
- Node 18+ and npm to install a release
- No API key is needed to install, or to query bookmarks locally

## Install

```sh
npx bookmark-research@latest install
```

Installs the latest stable release directly. To pin this release, use `npx bookmark-research@0.6.0 install`. Add `--lang zh` for the Chinese wizard. For a permanent command, run `npm install -g bookmark-research@latest`; the GitHub convenience script uses the same npm release (macOS/Linux/WSL):

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

Enter keeps the highlighted value, so a full run can be just a few keystrokes. Then start a new client session so the Skill and MCP tools load. Wiki follow-up suggests retention and honors existing authorization. Optional service diagnostics retain a 15-minute cache.

### Non-interactive install

| Client | Command | Registers with |
| --- | --- | --- |
| Codex | `npx bookmark-research@latest install codex --non-interactive` | `codex plugin add` |
| Claude Code | `npx bookmark-research@latest install claude --scope user --non-interactive` | `claude plugin install` |
| DeepSeek Harness (dsh) | `npx bookmark-research@latest install dsh --profile web --non-interactive` | `dsh plugin add` |

Several at once: `npx bookmark-research@latest install claude dsh --profile web --non-interactive`. Project scope: `--scope project --project /path/to/project` (Claude Code). All options: [installation guide](docs/installation.en.md).

**Ask your agent to install it.** Paste this into Codex, Claude Code or DeepSeek Harness (dsh):

```text
Install the Bookmark Research plugin into the client you are running in.

1. Identify your own client: codex, claude or dsh.
2. Run: npx bookmark-research@latest install <client> --non-interactive --json
   - Claude Code: add --scope user (or --scope project --project <dir>).
   - DeepSeek Harness (dsh): add --profile <profile>; ask me for the profile name.
3. The command prints JSON. Confirm "verified": true and report any "error".
4. Do not ask me for API keys in chat. Tell me to run `bookmark-research setup`
   in my terminal to enter them.
5. Tell me to start a new session so the Skill and MCP tools load.
```

Install notes:

- **npm is the single release source** for all three hosts; it contains the shared runtime, Skill and host adapters. The installer downloads the release, prepares the host's format, then calls the host's native commands. GitHub hosts source, versions and the installation catalog; unpublished source uses the Python installer. See [distribution policy](docs/distribution.md).
- **DeepSeek Harness (dsh) installs the release directly.** The package declares `dsh.bundle.patch`, so `dsh plugin --profile <name> add bookmark-research@<version>` installs it with no export first. The reserved `desktop` profile belongs to DeepSeek Harness Desktop; use that app's CLI, which the installer and wizard locate themselves.
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

Use `npx bookmark-research@latest …` if the command is not installed globally. Preferences and keys are user-wide, so one change applies to every installed client; start a new client session afterwards. `--lang zh` shows the wizard and menu in Chinese. The default `quick` preset exposes 21 everyday tools. Use `bookmark-research config set --tool-scope-preset deep` for the full 43-tool catalog when a persistent collection audit is needed. An explicit `tool_scope` list still overrides the preset.

**Update.** Run `npx bookmark-research@latest install` and confirm the upgrade/overwrite plan to adopt the latest release for your installed clients. For Codex without prompts, use `npx bookmark-research@latest install codex --non-interactive --replace-source`. `bookmark-research update` refreshes the recorded source: Git/npm selectors follow their selected ref, while a bundled build or pinned release stays on that build. Both paths preserve preferences, keys and data. Start a new host session afterwards.

**API keys are optional.** Enter them in `bookmark-research setup` (hidden input, checked immediately, saved in a private local file) or set environment variables, which take precedence.

| Variable | Service | Without it |
| --- | --- | --- |
| `EXA_API_KEY` | Exa search and page reading | Anonymous use where Exa allows it |
| `PARALLEL_API_KEY` | Parallel search and page reading | Free anonymous use with lower limits |
| `TAVILY_API_KEY` | Tavily search fallback and extraction | Keyless mode |
| `JINA_API_KEY` | Jina search | Jina Reader still reads pages anonymously |
| `DEEPSEEK_API_KEY` | Optional DeepSeek Search / Fetch | Not selected; other providers still work |
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

For a grouped report, the plugin supplies a reader → fresh verifier → coverage check → follow-up → report workflow. Codex uses its native subagent tools and the bundled delegation guide; Claude Code and DeepSeek Harness (dsh) use available host workflow hooks. The host owns concurrency, cancellation and agent lifetime. All children must receive the relevant instructions and access the same research store.

The workflow adapters have simulated contract tests, but a successful install does not prove that every host can execute the complete multi-agent workflow. See [host workflows](skills/bookmark-research/references/host-workflows.md) for requirements. Historical validation records are available in Git history.

## What's inside

A bundle of one Skill, one local MCP server, and the remote MCPs and services that server connects to. The client registers only the local MCP.

| Layer | Component | Runs as | Setup |
| --- | --- | --- | --- |
| Skill | [`bookmark-research`](skills/bookmark-research/SKILL.md) and method references, each with a [Chinese copy](skills/bookmark-research/references/zh/skill-guide.md) | Loaded by the client | None |
| Local MCP | `bookmark-research`, 21 default tools (below) | Python process started by the client | Installed for you |
| Remote MCPs, called by the local MCP | [Exa](https://exa.ai) (search, page reading), [Parallel](https://parallel.ai) (search, fallback reading), [Tavily](https://tavily.com) (search fallback) | HTTPS, no local process | Optional API keys |
| HTTP services, called by the local MCP | [Jina Reader](https://jina.ai/reader) (fallback reading; search with a key); [DeepSeek Search / Fetch](https://api-docs.deepseek.com/guides/search/) (optional; raw JSON tools API) | HTTPS | Optional `JINA_API_KEY`, `DEEPSEEK_API_KEY` |
| Optional client MCPs | Exa Agent, Parallel Task MCP, Tavily Research | Added to your client by you | `bookmark-research setup` shows the steps |

Default MCP tools:

| Group | Tools |
| --- | --- |
| Canvas context | `sync_package`, `index_status`, `search_bookmarks`, `get_context`, `plan_research` |
| Web and archives | `search_web`, `fetch_web`, `search_archive` |
| Wiki | `wiki_write`, `wiki_get`, `wiki_list`, `wiki_search` |
| Research API | `research_services`, `research_service_prepare`, `_start`, `_status`, `_result`, `_cancel`, `_attach` |
| Settings | `get_settings`, `update_settings` |

`plan_research` retrieves local candidates and independently checks the Wiki/archive; the host assesses relevance and follows gaps. It also works without a Canvas source. `wiki_write` accepts authored sections, exact citations and source text or capture IDs in one call. Research APIs accept a question without a local research session.

The `deep` preset additionally exposes source maintenance, persistent research records, routing diagnostics and Wiki maintenance. These support explicit audits and resumption. Git history uses the host's shell.

Tool descriptions: [details](docs/details.en.md#mcp-tools).

## More

- [Installation guide](docs/installation.en.md): all install options, npm updates and source development
- [User guide](docs/user-guide.en.md): first use, the three research modes, languages
- [Details](docs/details.en.md): data model, research modes, settings, export formats, development checks
- [Architecture](docs/bookmark-research-architecture.md) (Chinese)

Originally developed in [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas). License: [GPL-3.0](LICENSE).
