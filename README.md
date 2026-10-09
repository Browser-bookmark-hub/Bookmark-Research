# Bookmark Research

**English** · [中文](README.zh.md)

Research your bookmarks with verified web sources. Give it a list of bookmark URLs or a [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas) package; it checks every link, searches and reads the web, and writes a cited report you can resume.

Works in **Codex, Claude Code, Pi and DSH (DeepSeek Harness)**.

[Installation guide](docs/installation.en.md) · [User guide](docs/user-guide.en.md) · [Details](docs/details.en.md) · [npm](https://www.npmjs.com/package/bookmark-research)

> [!NOTE]
> **0.5.0 is a beta.** Report problems on [GitHub Issues](https://github.com/Browser-bookmark-hub/Bookmark-Research/issues).

**Install releases from [npm](https://www.npmjs.com/package/bookmark-research).** GitHub Releases retain version notes and npm links; downloadable installation/test packages have been withdrawn. GitHub's automatic **Source code** archives are source checkouts, not installation packages.

## Requirements

- Python 3.9+ with SQLite FTS5 (check with `bookmark-research doctor`)
- The CLI of at least one client: Codex, Claude Code, Pi or DSH (DSH also needs `pnpm`)
- Node 18+ and npm for release installation (including the GitHub convenience script)
- No API key is needed to install or to query bookmarks locally

## Install

**Current beta (`0.5.0-beta.8`)**, interactive on macOS, Linux and Windows:

```sh
npx bookmark-research@0.5.0-beta.8 install --source npm:bookmark-research@0.5.0-beta.8
```

This pins both the installer and the content. The `@latest` examples below follow the default channel, which remains `0.5.0-beta.3`; `@beta` currently points to `0.5.0-beta.8`. Changing only the npx selector does not change the installer's default content source.

**Default-channel interactive installation:**

```sh
npx bookmark-research@latest install
```

Pick clients with the arrow keys and Space, confirm the summary, then choose search services and enter API keys. Start a new client session afterwards.

For a permanent `bookmark-research` command: `npm install -g bookmark-research`. The GitHub convenience script uses the same npm release (macOS/Linux/WSL): `curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash`.

**One client, no prompts:**

| Client | Command | Registers with |
| --- | --- | --- |
| Codex | `npx bookmark-research@latest install codex --non-interactive` | `codex plugin add` |
| Claude Code | `npx bookmark-research@latest install claude --scope user --non-interactive` | `claude plugin install` |
| Pi | `npx bookmark-research@latest install pi --non-interactive` | `pi install` |
| DSH | `npx bookmark-research@latest install dsh --profile web --non-interactive` | `dsh plugin add` |

**One release source for all four hosts:** npm contains the shared runtime, Skill and host adapters. The installer downloads the release, prepares the selected host format, then invokes the host’s native commands. Updates retain an npm selector rather than an npx cache path. GitHub hosts source and installation catalogs; unpublished source uses the Python installer. See [distribution policy and official references](docs/distribution.md).

**DSH installs the release directly:** the published package declares `dsh.bundle.patch`, so `dsh plugin --profile <name> add bookmark-research@<version>` — or the DSH plugin manager — installs it with no export first, resolving Python and MCP paths from the installed package. DeepSeek Harness Desktop reserves the `desktop` profile for its own carrier, so install that one with the app's CLI. See the [installation guide](docs/installation.en.md).

**Windows:** the installer writes the detected Python path into each client's MCP config, because Windows often has no working `python3`. Install Codex with `bookmark-research install codex` rather than adding the repository to Codex directly. `bookmark-research status` shows the interpreter in use.

Several at once: `npx bookmark-research@latest install claude dsh --profile web --non-interactive`. Project scope: `--scope project --project /path/to/project` (Claude Code, Pi). All options: [installation guide](docs/installation.en.md).

**Ask your agent to install it.** Paste this into Codex, Claude Code, Pi or DSH:

```text
Install the Bookmark Research plugin into the client you are running in.

1. Identify your own client: codex, claude, pi or dsh.
2. Run: npx bookmark-research@latest install <client> --non-interactive
   - Claude Code or Pi: add --scope user (or --scope project --project <dir>).
   - DSH: add --profile <profile>; ask me for the profile name.
3. The command prints JSON. Confirm "verified": true and report any "error".
4. Do not ask me for API keys in chat. Tell me to run `bookmark-research setup`
   (or `npx bookmark-research@latest setup`) in my terminal to enter them.
5. Tell me to start a new session so the Skill and MCP tools load.
```

## Configure and API keys

No reinstall is needed. Settings and keys apply to every installed client; start a new client session after changing them.

| Task | Command |
| --- | --- |
| Menu: configure, check, install, update | `bookmark-research` |
| Preferences and API keys | `bookmark-research setup` |
| Installed clients, preferences, storage locations, recent research, key status | `bookmark-research status` |
| Script preferences | `bookmark-research config show` · `bookmark-research config set --input prefs.json` |
| Update or verify all clients | `bookmark-research update` · `bookmark-research verify` |

Use `npx bookmark-research@latest …` if the command is not installed globally.

**API keys are optional.** Enter them in `bookmark-research setup` (hidden input, checked immediately, saved in a private local file) or set environment variables, which take precedence. Keys are never accepted in chat, command arguments or JSON files.

| Variable | Service | Without it |
| --- | --- | --- |
| `EXA_API_KEY` | Exa search and page reading | Anonymous use where Exa allows it |
| `PARALLEL_API_KEY` | Parallel search and page reading | Free anonymous use with lower limits |
| `TAVILY_API_KEY` | Tavily search fallback and extraction | Keyless mode |
| `JINA_API_KEY` | Jina search | Jina Reader still reads pages anonymously |
| `OPENAI_API_KEY` | Optional OpenAI Deep Research runs | Feature off; host-led research still works |

Setup also asks where research reports and evidence go: a central folder (default `<data dir>/research`, path changeable) or beside the bookmark file or folder (falls back to the central folder when that is not possible). This affects new research only; existing tasks stay where they are. It then asks whether finished research should update the Wiki: suggest pages and ask first (default), automatic, or off.

Preferences (research depth, answer language, providers, archiving, output location, Wiki follow-up) can also be changed by asking the agent in a client session; it uses the `update_settings` tool.

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

## Agent loops and delegation

The host model plans the research, searches or reads pages, evaluates the evidence and follows unresolved questions. The Skill guides this loop; MCP stores inputs, evidence, budgets and progress. Saving a research task does not start a background agent.

For a grouped report, the plugin supplies a reader → fresh verifier → coverage check → follow-up → report workflow. Codex uses its native subagent tools and the bundled delegation guide; Claude Code and DSH use available host workflow hooks, while Pi requires a loaded subagent/workflow extension. The host owns concurrency, cancellation and agent lifetime. All children must receive the relevant instructions and access the same research store.

The workflow adapters have simulated contract tests, but a successful install does not prove that every host can execute the complete multi-agent workflow. See [host workflows](skills/bookmark-research/references/host-workflows.md) for requirements and [the validation matrix](docs/validation-0.4.0.md#host-and-provider-boundaries) for observed limits.

## What's inside

A bundle of one Skill, one local MCP server, and the remote MCPs and services that server connects to. The client registers only the local MCP.

| Layer | Component | Runs as | Setup |
| --- | --- | --- | --- |
| Skill | [`bookmark-research`](skills/bookmark-research/SKILL.md) and 11 method references, each with a [Chinese copy](skills/bookmark-research/references/zh/skill-guide.md) | Loaded by the client | None |
| Local MCP | `bookmark-research`, 40 tools (below; the list grows with capabilities) | Python process started by the client | Installed for you |
| Remote MCPs, called by the local MCP | [Exa](https://exa.ai) (search, page reading), [Parallel](https://parallel.ai) (search, fallback reading), [Tavily](https://tavily.com) (search fallback) | HTTPS, no local process | Optional API keys |
| HTTP service, called by the local MCP | [Jina Reader](https://jina.ai/reader) (fallback reading; search with a key) | HTTPS | Optional `JINA_API_KEY` |
| Optional client MCPs | Exa Agent, Parallel Task MCP, Tavily Research | Added to your client by you | `bookmark-research setup` shows the steps |

Local MCP tools:

| Group | Tools |
| --- | --- |
| Bookmarks | `sync_package`, `index_status`, `source_history`, `source_remove`, `source_merge`, `search_bookmarks`, `get_context` |
| Web | `search_web`, `fetch_web`, `search_archive`, `search_providers` |
| Research | `research_readiness`, `research_start`, `research_status`, `research_search`, `research_fetch`, `research_source`, `research_record`, `research_inventory`, `research_coverage`, `research_import_evidence`, `research_finish`, `research_route` |
| Research services (optional) | `research_services`, `research_service_prepare`, `_start`, `_status`, `_result`, `_cancel`, `_attach`, `_import` |
| Settings | `get_settings`, `update_settings` |
| Wiki and evaluation | `wiki_write`, `wiki_get`, `wiki_list`, `wiki_search`, `wiki_lint`, `wiki_acknowledge`, `evaluate_research` |

Tool descriptions: [details](docs/details.en.md#mcp-tools).

## More

- [Installation guide](docs/installation.en.md): all install options, npm updates and source development
- [User guide](docs/user-guide.en.md): first use, the three research modes, languages
- [Details](docs/details.en.md): data model, research modes, settings, export formats, development checks
- [Architecture](docs/bookmark-research-architecture.md) (Chinese)

Originally developed in [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas). License: [GPL-3.0](LICENSE).
