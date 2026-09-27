# Bookmark Research 0.5.0 beta 2

**Beta.** Please report problems on [GitHub Issues](https://github.com/Browser-bookmark-hub/Bookmark-Research/issues).

## Install or update

```sh
npx bookmark-research@latest install   # interactive; macOS, Linux, Windows
bookmark-research update               # if already installed
```

## Changes

- **Codex on Windows**: the installer now registers a copy whose MCP command is the Python it detected, instead of `python3`, which is often missing or a Microsoft Store stub on Windows. `update` refreshes that copy from the original source. Install Codex on Windows with `bookmark-research install codex`.
- **Windows environment**: the MCP server receives `SystemRoot` and `windir`, which older Codex builds stripped and Python networking needs.
- **`bookmark-research status`** shows the detected Python and the MCP command written into client configs.
- **README** lists the bundle by layer: one Skill, one local MCP server (36 tools), the remote MCPs it calls (Exa, Parallel, Tavily), Jina Reader, and optional client MCPs.

## Validation

452 regression tests pass in GitHub Actions on Ubuntu, macOS and Windows with Python 3.9 and 3.12, plus an npm pack and install smoke test. Codex on native Windows is covered by simulated tests, not yet by a real Windows machine. Pi has not been tested on a real machine.

Assets: plugin ZIP, developer test pack and `SHA256SUMS`.
