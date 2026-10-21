# Bookmark Research 0.5.0 beta 1

**Beta.** Installation and configuration are new; please report problems on [GitHub Issues](https://github.com/Browser-bookmark-hub/Bookmark-Research/issues).

## Install

```sh
npx bookmark-research install      # interactive; macOS, Linux, Windows
npm install -g bookmark-research   # keep the bookmark-research command
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash   # macOS/Linux without Node
```

Requires Python 3.9+ with SQLite FTS5 and at least one client CLI: Codex, Claude Code, Pi or DSH.

## What's new

- **`bookmark-research` command** (npm; macOS, Linux and native Windows): a menu plus `install`, `update`, `verify`, `setup`, `status`, `config` and `doctor`. `update` and `verify` cover every installed client.
- **Guided installer**: select several clients at once with arrow keys and Space (detected CLIs preselected), set scope or DSH profile, confirm a summary, then run one shared setup. Plain numbered prompts when no full terminal is available.
- **Native registration for all four clients**, verified after installation: Codex marketplace, Claude Code marketplace and plugin, `pi install`, `dsh plugin add`. DSH checks for `pnpm` first.
- **API keys**: masked entry, checked immediately, retry on failure, stored in a private local file; environment variables take precedence. Keys are never accepted in chat, arguments or JSON.
- **Readiness check** (`research_readiness` tool) before web research, with cached, always and manual modes.
- **Windows**: UTF-8 I/O, byte-exact evidence files, `.cmd` client shims and interpreter paths in exported MCP configs.
- **Shorter README** with per-client install commands, an install prompt for agents, and key and tool tables; reference material moved to `docs/details.en.md` and `docs/details.md`.

## Validation

450 regression tests pass in GitHub Actions on Ubuntu, macOS and Windows with Python 3.9 and 3.12, plus an npm pack and install smoke test. Real installations were checked on macOS for Claude Code 2.1.280 and DSH 0.1.5-rc.1 (36 MCP tools each).

Not yet tested: Pi on a real machine, and client installs on native Windows. Codex on Windows starts its MCP with `python3` from the repository manifest, which may be missing there.

## Assets

Plugin ZIP, developer test pack and `SHA256SUMS`. Both ZIPs include `MANIFEST.sha256` and exclude user exports, snapshots, databases and credentials.
