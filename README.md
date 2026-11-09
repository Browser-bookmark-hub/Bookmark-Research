# Bookmark Research

**English** · [中文](README.zh.md)

[![GitHub Bookmark-Canvas](https://img.shields.io/badge/GitHub-Bookmark--Canvas-181717?logo=github&logoColor=white)](https://github.com/Browser-bookmark-hub/Bookmark-Canvas)
[![npm version](https://img.shields.io/npm/v/bookmark-research?logo=npm)](https://www.npmjs.com/package/bookmark-research)

Research with bookmark context and retain reusable knowledge. Read a [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas) package, investigate with the host model or a research API, and save sourced Wiki pages. Works in **Codex, Claude Code and DeepSeek Harness (dsh)**.

[Installation guide](docs/installation.en.md) · [User guide](docs/user-guide.en.md) · [Details](docs/details.en.md) · [npm](https://www.npmjs.com/package/bookmark-research)

## Version 0.7.1

0.7.1 keeps the 0.7.0 CLI-first surface — 10 default primitives, a durable local job queue, card-export imports (JSON or Netscape HTML), search-result page skipping and a TTL fetch cache — and adds a switchable Wiki layer (`wiki.enabled`), a deterministic compile planner (`wiki_compile` plan/status/gap), host-native search reporting with discovery backflow, and two Wiki write fixes. The default surface is 9 primitives when the Wiki is off; deep/all advertises 40 real tools. The 18 replaced names are no longer listed (explicit tool_scope can still name them) and remain callable until the 0.8.0 cutoff.

The stable release includes bilingual Canvas package support, safer Exa batch reading that isolates ambiguous pages, and concise installation/update summaries. Installation prints the version, actual paths, checks and any required action. Use `--json` for complete structured diagnostics; `--non-interactive` only disables prompts. Existing settings, credentials and research data are retained during upgrades.

## How it works

- **Local understanding.** A Bookmark Canvas package is read as structure, not a flat URL list: card and group layout, edges with their direction and labels, and the same bookmark appearing across cards (spatial context); dated fields, protocol-defined date segments in IDs, and Git commits that changed content (temporal context). These queries run offline.
- **External research takes one of three routes.** Reading a known URL needs no reasoning; agentic search has the host model plan, search, read and follow the gaps; deep research can use the OpenAI or Parallel research API directly. Host-native search is the default discovery channel; its results are discovery only and must be merged with `ingest`, then reported through `research_finish(discovery=…)`. `search` aggregates configured URL providers such as Perplexity Search; `agentic_search` can return a separate Grok or user-configured OpenAI-compatible model answer and citations. Custom model search depends on the selected upstream's web capability and is not URL-fused. Persistent inventories and coverage checks are available when you explicitly need a complete collection audit. Host browsers and crawlers can supply source text.
- **Reviewed knowledge store.** Finished research can be compiled into a Wiki of reviewed pages with revisions and links, reused by later questions instead of searching the web again. `wiki_compile` plans a folder-scoped compile, audits covered/gap/pending items and lists the pages a cluster would touch; the host writes the page. Setup (or `update_settings`) can turn the whole Wiki off with `wiki.enabled`; `save` and the Wiki tools then disappear from the tool surface.

## Requirements

- Python 3.9+ with SQLite FTS5 (checked by `bookmark-research doctor`)
- The CLI of at least one client: Codex, Claude Code or DeepSeek Harness (dsh). DeepSeek Harness (dsh) also needs `pnpm`, unless it is the DeepSeek Harness Desktop CLI, which carries its own
- Node 18+ and npm to install a release
- No API key is needed to install, or to query bookmarks locally

## Install

```sh
npx bookmark-research@latest install
```

Installs the latest stable release directly. To pin this release, use `npx bookmark-research@0.7.1 install`. Add `--lang zh` for the Chinese wizard. For a permanent command, run `npm install -g bookmark-research@latest`; the GitHub convenience script uses the same npm release (macOS/Linux/WSL):

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash
```

### What the installer asks

1. **Clients** — arrow keys and Space to toggle; detected CLIs are preselected. The install plan is shown for confirmation.
2. **Research depth (optional)** — leave `auto` and the depth is picked from each request; set `quick`, `agentic` or `deep` only to pin one default.
3. **Answer and report language** — follow the question, Chinese or English.
4. **Search sources** — one ordered multiselect. Unselected providers become the fallback search tier. Perplexity is search-only; page reading uses a separate provider.
5. **Storage** — the default data folder, one custom folder for archives and reports, or reports beside the bookmark file or folder.
6. **Optional professional APIs** — off by default: OpenAI Deep Research or the Parallel Task API.
7. **Custom model endpoint (optional)** — enter a compatible Base URL, model and protocol; web-search support depends on the upstream.
8. **API keys** — select the variables for services you enabled (Space to toggle, Enter to continue), then enter each value in a hidden prompt; optional and skippable. Values are saved separately from preferences.
9. **Service check** — reports configured providers; a sample search/read test is opt-in.

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
| Configuration JSON guide and example | [Guide](docs/configuration.en.md) · [Partial JSON](config/settings.example.json) |
| Update or verify all clients | `bookmark-research update` · `bookmark-research verify` |
| Duplicate URL report | `bookmark-research dupes --source-id <id>` |
| Local job queue | `bookmark-research job submit --kind fetch --input job.json` · `bookmark-research job worker --concurrency 2` |

Use `npx bookmark-research@latest …` if the command is not installed globally. Preferences and keys are user-wide, so one change applies to every installed client; start a new client session afterwards. `--lang zh` shows the wizard and menu in Chinese. The default `quick` preset exposes 10 primitives shared by the CLI and MCP. Use `bookmark-research config set --tool-scope-preset deep` for the 40-tool deep catalog when a persistent collection audit is needed. An explicit `tool_scope` list still overrides the preset.

**Update.** Run `npx bookmark-research@latest install` and confirm the upgrade/overwrite plan to adopt the latest release for your installed clients. For Codex without prompts, use `npx bookmark-research@latest install codex --non-interactive --replace-source`. `bookmark-research update` refreshes the recorded source: Git/npm selectors follow their selected ref, while a bundled build or pinned release stays on that build. Both paths preserve preferences, keys and data. Start a new host session afterwards.

**API keys are optional.** Enter them in `bookmark-research setup` (hidden input, checked immediately, saved in a private local file) or set environment variables, which take precedence.

| Variable | Service | Without it |
| --- | --- | --- |
| `EXA_API_KEY` | Exa search and page reading | Anonymous use where Exa allows it |
| `PARALLEL_API_KEY` | Parallel search and page reading | Free anonymous use with lower limits |
| `TAVILY_API_KEY` | Tavily search fallback and extraction | Keyless mode |
| `JINA_API_KEY` | Jina search | Jina Reader still reads pages anonymously |
| `DEEPSEEK_API_KEY` | Optional DeepSeek Search / Fetch | Not selected; other providers still work |
| `PERPLEXITY_API_KEY` | Optional Perplexity structured Search | Search results only; no page extraction |
| `XAI_API_KEY` | Optional Grok Agentic search | Separate `agentic_search` answer channel; not URL-fused |
| `CUSTOM_AGENTIC_API_KEY` | Optional user-configured OpenAI-compatible endpoint | Separate `agentic_search` channel; set Base URL/model/protocol in setup |
| `OPENAI_API_KEY` | Optional OpenAI Deep Research runs | Feature off; host-led research still works |

At the setup key step, select the keys for enabled services with Space, then enter each key at the hidden prompt; leave the selection empty to skip. Keys go to the separate private `credentials.json` or can come from environment variables, which take precedence. They are not part of `prefs.json` or `settings.json`; the settings JSON import rejects credential fields. Preferences can also be changed by asking the agent in a client session ("Show Bookmark Research settings", "Use only Exa for future searches"); it uses the `update_settings` tool when the deep catalog is enabled. See the [configuration guide](docs/configuration.en.md) for every key and service.

## Where data is stored

Nothing is written into your bookmark files or the plugin. The data directory is `$BOOKMARK_RESEARCH_DATA_DIR`, or `${XDG_DATA_HOME:-~/.local/share}/bookmark-research`.

| Location | Contents |
| --- | --- |
| `research/` (or `<input>.bookmark-research/` beside the input) | One folder per research task: report, sources, evidence, and `work/` for the agent's intermediate files |
| `research-locations.json` | Where every task folder is, so tasks stay listed after the location setting changes |
| `knowledge/` | Saved page reads: `sources/` per fetch, `pages/` with each distinct text stored once |
| `wiki/` | Reviewed knowledge pages and revisions; `index.md` catalog and `log.md` timeline |
| `index.sqlite3`, `index.sqlite3.sources/` | Bookmark search index and managed snapshots of imported packages |
| `jobs.sqlite3` | Durable local job queue read by every host and the CLI worker |
| `fetch-cache.sqlite3` | TTL cache for identical fetch batches (only when `fetch.reuse_seconds` > 0) |
| `raw-library.sqlite3` | Rebuildable full-text index behind `locate(in=["archive"])` |
| `${XDG_CONFIG_HOME:-~/.config}/bookmark-research/` | `settings.json` and `credentials.json` (private, owner-only) |

Changing the location affects new research only; existing tasks stay where they are.

## Research loops and delegation

The host model plans the research, searches or reads pages, evaluates the evidence and follows unresolved questions. Batch work goes through the local job queue instead of blocking the tool step. The Skill guides this loop; MCP stores inputs, evidence, budgets and progress. Saving a research task does not start a background agent.

For a grouped report, the plugin supplies a reader → fresh verifier → coverage check → follow-up → report workflow. Codex uses its native subagent tools and the bundled delegation guide; Claude Code and DeepSeek Harness (dsh) use available host workflow hooks. The host owns concurrency, cancellation and agent lifetime. All children must receive the relevant instructions and access the same research store.

The workflow adapters have simulated contract tests, but a successful install does not prove that every host can execute the complete multi-agent workflow. See [host workflows](skills/bookmark-research/references/host-workflows.md) for requirements. Historical validation records are available in Git history.

## What's inside

A bundle of one Skill, one local MCP server, and the remote MCPs and services that server connects to. The client registers only the local MCP.

| Layer | Component | Runs as | Setup |
| --- | --- | --- | --- |
| Skill | [`bookmark-research`](skills/bookmark-research/SKILL.md) and method references, each with a [Chinese copy](skills/bookmark-research/references/zh/skill-guide.md) | Loaded by the client | None |
| Local MCP | `bookmark-research`, 10 default tools (below) | Python process started by the client | Installed for you |
| Remote MCPs, called by the local MCP | [Exa](https://exa.ai) (search, page reading), [Parallel](https://parallel.ai) (search, fallback reading), [Tavily](https://tavily.com) (search fallback) | HTTPS, no local process | Optional API keys |
| HTTP services, called by the local MCP | [Jina Reader](https://jina.ai/reader) (fallback reading; search with a key); [DeepSeek Search / Fetch](https://api-docs.deepseek.com/guides/search/); [Perplexity Search](https://docs.perplexity.ai/api-reference/search-post) (structured results only) | HTTPS | Optional provider keys |
| Model search API | [xAI Grok Responses](https://docs.x.ai/developers/tools/web-search) with optional Web Search and X Search | HTTPS | Optional `XAI_API_KEY`; invoked separately via `agentic_search` |
| Optional client MCPs | Exa Agent, Parallel Task MCP, Tavily Research | Added to your client by you | `bookmark-research setup` shows the steps |

Default MCP tools:

| Group | Tools | What they answer |
| --- | --- | --- |
| Local Canvas | `locate`, `read`, `walk` | Find an item (text, URL, folder children or metadata only), open its card or a folder's children, follow edges |
| Diagnostics | `health` | Bounded readiness summary (no network, no index write); pass `host`/`observed_tools` to confirm host-native search |
| Web | `search`, `fetch`, `ingest` | Discovery results, bounded page text with `content_state`/`capture_id`, deterministic host-result fusion |
| Long-running | `spawn`, `job` | Submit fetch/ingest/research work to the durable local queue and observe or cancel it |
| Knowledge | `save` | Reviewed Wiki revisions with exact citations |

`locate(package_path=...)` is the first contact: it imports a package, a single card or a card export (JSON without ids, or Netscape bookmark HTML) and returns counts, sections with `source`/`temp_kind`, notes, search-result pages, divider rows and duplicate groups. `read` opens a hit; `walk` follows Canvas edges. `save` accepts authored sections, exact citations and source text or capture IDs in one call.

Long or batch work does not block a tool step: `spawn(task="fetch"|"ingest"|"research", args)` enqueues it, a singleton `bookmark-research job worker` executes it with a bounded pool, and `job(job_id)` reports state and result. The queue is shared by every host and the CLI.

The `deep` preset additionally exposes 30 maintenance tools: source maintenance, persistent research records, routing diagnostics, Wiki maintenance and `wiki_compile` incremental compile plans. The 18 replaced names are not listed in any preset; an explicit `tool_scope` can still name them until they are rejected at 0.8.0. Git history uses the host's shell.

Tool descriptions: [details](docs/details.en.md#mcp-tools).

## More

- [Installation guide](docs/installation.en.md): all install options, npm updates and source development
- [User guide](docs/user-guide.en.md): first use, the three research modes, languages
- [Details](docs/details.en.md): data model, research modes, settings, export formats, development checks
- [Architecture](docs/bookmark-research-architecture.md) (Chinese)

Originally developed in [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas). License: [GPL-3.0](LICENSE).
