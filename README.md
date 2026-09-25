# Bookmark Research

**English** · [中文](README.zh.md)

Research your bookmarks with verified web sources. Give it a list of bookmark URLs or a [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas) package; it checks every link, searches and reads the web, and writes a cited report you can resume.

Works in **Codex, Claude Code, Pi and DSH (DeepSeek Harness)**.

[Installation guide](docs/installation.en.md) · [User guide](docs/user-guide.en.md) · [Details](docs/details.en.md) · [npm](https://www.npmjs.com/package/bookmark-research) · [Releases](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases)

> [!NOTE]
> **0.5.0 is a beta.** Report problems on [GitHub Issues](https://github.com/Browser-bookmark-hub/Bookmark-Research/issues).

## Requirements

- Python 3.9+ with SQLite FTS5 (check with `bookmark-research doctor`)
- The CLI of at least one client: Codex, Claude Code, Pi or DSH (DSH also needs `pnpm`)
- Node 18+ for the `bookmark-research` command; optional on macOS/Linux
- No API key is needed to install or to query bookmarks locally

## Install

**Interactive** (macOS, Linux, Windows):

```sh
npx bookmark-research install
```

Pick clients with the arrow keys and Space, confirm the summary, then choose search services and enter API keys. Start a new client session afterwards.

For a permanent `bookmark-research` command: `npm install -g bookmark-research`. Without Node (macOS/Linux/WSL): `curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash`.

**One client, no prompts:**

| Client | Command | Registers with |
| --- | --- | --- |
| Codex | `npx bookmark-research install codex --non-interactive` | `codex plugin add` |
| Claude Code | `npx bookmark-research install claude --scope user --non-interactive` | `claude plugin install` |
| Pi | `npx bookmark-research install pi --non-interactive` | `pi install` |
| DSH | `npx bookmark-research install dsh --profile web --non-interactive` | `dsh plugin add` |

Several at once: `npx bookmark-research install claude dsh --profile web --non-interactive`. Project scope: `--scope project --project /path/to/project` (Claude Code, Pi). All options: [installation guide](docs/installation.en.md).

**Ask your agent to install it.** Paste this into Codex, Claude Code, Pi or DSH:

```text
Install the Bookmark Research plugin into the client you are running in.

1. Identify your own client: codex, claude, pi or dsh.
2. Run: npx bookmark-research install <client> --non-interactive
   - Claude Code or Pi: add --scope user (or --scope project --project <dir>).
   - DSH: add --profile <profile>; ask me for the profile name.
3. The command prints JSON. Confirm "verified": true and report any "error".
4. Do not ask me for API keys in chat. Tell me to run `bookmark-research setup`
   (or `npx bookmark-research setup`) in my terminal to enter them.
5. Tell me to start a new session so the Skill and MCP tools load.
```

## Configure and API keys

No reinstall is needed. Settings and keys apply to every installed client; start a new client session after changing them.

| Task | Command |
| --- | --- |
| Menu: configure, check, install, update | `bookmark-research` |
| Preferences and API keys | `bookmark-research setup` |
| Installed clients, preferences, key status | `bookmark-research status` |
| Script preferences | `bookmark-research config show` · `bookmark-research config set --input prefs.json` |
| Update or verify all clients | `bookmark-research update` · `bookmark-research verify` |

Use `npx bookmark-research …` if the command is not installed globally.

**API keys are optional.** Enter them in `bookmark-research setup` (hidden input, checked immediately, saved in a private local file) or set environment variables, which take precedence. Keys are never accepted in chat, command arguments or JSON files.

| Variable | Service | Without it |
| --- | --- | --- |
| `EXA_API_KEY` | Exa search and page reading | Anonymous use where Exa allows it |
| `PARALLEL_API_KEY` | Parallel search and page reading | Free anonymous use with lower limits |
| `TAVILY_API_KEY` | Tavily search fallback and extraction | Keyless mode |
| `JINA_API_KEY` | Jina search | Jina Reader still reads pages anonymously |
| `OPENAI_API_KEY` | Optional OpenAI Deep Research runs | Feature off; host-led research still works |

Preferences (research depth, answer language, providers, archiving) can also be changed by asking the agent in a client session; it uses the `update_settings` tool.

## What's inside

### Skill

| Skill | Use it for |
| --- | --- |
| [`bookmark-research`](skills/bookmark-research/SKILL.md) | Query bookmarks, check links, run a full research pass over every bookmark and write a cited report. English, with a [Chinese reading copy](skills/bookmark-research/references/zh/skill-guide.md). |

### MCP server

One local stdio server, `bookmark-research` (`python3 src/cli.py serve`), with 36 tools:

| Group | Tools |
| --- | --- |
| Bookmarks | `sync_package`, `index_status`, `source_history`, `search_bookmarks`, `get_context` |
| Web | `search_web`, `fetch_web`, `search_providers` |
| Research | `research_readiness`, `research_start`, `research_status`, `research_search`, `research_fetch`, `research_source`, `research_record`, `research_inventory`, `research_coverage`, `research_import_evidence`, `research_finish`, `research_route` |
| Research services (optional) | `research_services`, `research_service_prepare`, `_start`, `_status`, `_result`, `_cancel`, `_attach`, `_import` |
| Settings | `get_settings`, `update_settings` |
| Wiki and evaluation | `wiki_write`, `wiki_get`, `wiki_list`, `wiki_search`, `wiki_lint`, `evaluate_research` |

Tool descriptions: [details](docs/details.en.md#mcp-tools).

### Web services

Called by the plugin's own MCP server; you do not add their MCPs separately.

| Service | Role |
| --- | --- |
| [Exa](https://exa.ai) | Primary search; first page reader |
| [Parallel](https://parallel.ai) | Primary search; fallback page reader |
| [Tavily](https://tavily.com) | Search fallback |
| [Jina Reader](https://jina.ai/reader) | Fallback page reader; search with a key |

Optional research MCPs you may add to your client yourself: Exa Agent, Parallel Task and Tavily Research. `bookmark-research setup` shows the steps for each client.

## More

- [Installation guide](docs/installation.en.md): all install options, updates, ZIP downloads
- [User guide](docs/user-guide.en.md): first use, the three research modes, languages
- [Details](docs/details.en.md): data model, research modes, settings, export formats, development checks
- [Architecture](docs/bookmark-research-architecture.md) (Chinese)

Originally developed in [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas). License: [GPL-3.0](LICENSE).
