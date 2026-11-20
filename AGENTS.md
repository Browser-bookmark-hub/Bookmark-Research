# Bookmark Research — Installation and Development Guide (for AI agents and developers)

**English** · [中文阅读版](docs/agents.zh.md)

This file has two parts. Section 0 is for an agent a user asked to install this plugin. Sections 1–4 are the development, testing and release conventions for maintaining this project; they apply to every AI agent (including Codex, Claude Code, DeepSeek Harness, Devin and Antigravity) and to developers. Follow them strictly when changing code, running tests or preparing a release.

---

## 0. Install into the client you are running in

When a user gives you this repository or the npm link and asks you to install it, follow these steps in the client you are running in:

1. Identify your client: `codex`, `claude` or `dsh`. Any other client that loads [Agent Plugins 1.0.0](https://agent-plugins.org/specification) packages (root `plugin.json`, `mcp.json`, `skills/`), whatever it is called, uses `other`.
2. Run: `npx bookmark-research@latest install <client> --non-interactive --json`
   - `claude`: add `--scope user` (or `--scope project --project <dir>`).
   - `dsh`: add `--profile <name>`; ask the user for the profile name first. For DeepSeek Harness Desktop use `--dsh "<path to the Desktop's bundled CLI>" --profile desktop`.
   - `other`: `installed_path` in the result is an [Agent Plugins 1.0.0](https://agent-plugins.org/specification) plugin directory (root `plugin.json`, `mcp.json`, `skills/`). Register it with your own plugin command; the result's `register` field lists known commands (Devin: `devin plugins install --local <installed_path>`). If your client loads only MCP servers, add a stdio server `python3 <installed_path>/src/cli.py serve` and use `<installed_path>/skills` as a skills directory, or read `skills/bookmark-research/SKILL.md` there directly.
3. The command prints JSON. Confirm `"verified": true`; report any `"error"` to the user as it is and do not work around it. For `other`, `verified: true` means the exported files and stdio check passed (`verified_scope: "files_and_stdio"`); client registration is a separate step — read `registration`. If the client's register command fails (Devin needs `devin auth login` first), use `registration.fallback` instead.
4. Find your own web search and page-reading tools: check your tool list and judge by what each tool's description says it does, not by its name (this plugin's tools do not count). Tell the user which tools you found, or that there are none. The Skill uses them before the plugin's `search`/`fetch` and records the tool actually used as `provider:"host:<tool name>"`.
5. Never ask the user for API keys in chat (all keys are optional). Ask them to run `bookmark-research setup` in a terminal, or to set the corresponding environment variables.
6. Tell the user to start a new session so the Skill and MCP tools load.

Do not install this Git repository itself as a plugin (for example `devin plugins install Browser-bookmark-hub/Bookmark-Research`): the repository root contains tests and development files, and this file would be loaded as a session rule. Always install with the `npx` command above, which generates a clean host package.

---

## 1. Development and testing: local first, never publish npm frequently

> [!IMPORTANT]
> **Publishing to npm is only for official releases to all users.**
> During everyday development, feature integration, bug fixes or PR testing, **never** bump the version and push to npm repeatedly. Complete the full test suite locally.

### Three standard ways to test locally

#### Method 1: run the source directly (fastest, changes apply immediately)
Install and test straight from the current development source; code changes take effect at once:
```sh
# Install or update Codex only
python3 scripts/launcher.py install codex

# Launch the interactive install wizard for a hands-on test
python3 scripts/launcher.py install

# Quickly verify every host's installation and MCP tools on this machine
python3 scripts/launcher.py verify

# Offline environment and SQLite self-check
python3 scripts/launcher.py doctor
```

#### Method 2: `npm pack` to simulate npx locally (reproduces a real install exactly, no publishing)
To test the real npm packing and extraction flow, generate a tarball with `npm pack` and load it directly with `npx`:
```sh
# 1. Build the package locally (e.g. bookmark-research-0.5.0-beta.19.tgz; no network, no upload)
npm pack

# 2. Simulate an npx install from the local tarball (--package points at the tgz, followed by the binary name bookmark-research)
# If the npm cache was created by another user, use a project-specific cache so npm-cache permissions do not interfere.
LOCAL_NPM_CACHE=/private/tmp/bookmark-research-npm-cache
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package ./bookmark-research-*.tgz bookmark-research install codex --non-interactive --json

# Or test the interactive mode
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package ./bookmark-research-*.tgz bookmark-research install
```
- **Advantage**: identical behavior to the published `npx bookmark-research install` (package file filtering, tarball extraction, link injection and host registration).
- **No cost**: purely local; it does not touch the published npm versions, needs no CDN refresh and no 2FA login.

##### Local acceptance for the three hosts and DSH Desktop/CLI

A local tgz must be verified on each of the three hosts separately. The ordinary DSH CLI and the Desktop CLI are two different install targets; one `--profile` or one `--dsh` path cannot stand in for both.

~~~sh
LOCAL_NPM_CACHE=/private/tmp/bookmark-research-npm-cache
LOCAL_PACKAGE=./bookmark-research-0.6.5.tgz
CLI_PROFILE=web  # replace with the profile used by this machine's ordinary DSH CLI

# Codex
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research install codex --non-interactive --json

# Claude Code
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research install claude \
  --scope user --non-interactive --json

# Ordinary DSH CLI: the profile name comes from the DSH configuration; requires dsh and pnpm on PATH.
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research install dsh \
  --profile "$CLI_PROFILE" --non-interactive --json

# DeepSeek Harness Desktop: must use the Desktop's bundled CLI and the reserved desktop profile.
# macOS path below; on Windows/Linux substitute the local Desktop installation path.
DSH_DESKTOP_CLI="/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh"
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research install dsh \
  --dsh "$DSH_DESKTOP_CLI" --profile desktop --non-interactive --json
~~~

Check every acceptance JSON field by field: host, profile, version, installed_path and verified. For DSH Desktop the target must be desktop and must use the Desktop CLI. The ordinary DSH profile may be an existing name or an explicitly chosen new one; never hand desktop to the generic CLI on PATH.

Use install when testing a new local build: it keeps the running tarball as a clean source and overwrites an existing target. update keeps using the source registered in the target's receipt, which suits verifying later updates of a published npm release, Git or a registered local source; do not use update with an old receipt to judge whether a brand-new local tarball has been installed.

To test an upgrade of a registered source, run each target separately and confirm the version:

~~~sh
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research update dsh \
  --profile "$CLI_PROFILE" --json
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research update dsh \
  --dsh "$DSH_DESKTOP_CLI" --profile desktop --json

npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research verify dsh \
  --profile "$CLI_PROFILE" --json
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research verify dsh \
  --dsh "$DSH_DESKTOP_CLI" --profile desktop --json
~~~

After an upgrade, reopen the corresponding host and run verify with the same profile and the same actual CLI. Seeing "Updated" or checking only the installer's exit code does not count as passing.

#### Method 3: the full local automated test suite
Run the full suite after every code change and make sure every test passes:
```sh
python3 -B -m unittest discover -s tests -p "test_*.py"
```

---

## 2. Interaction (TUI) design rules

When maintaining `src/onboarding.py` and `src/tui.py`, follow these user-experience rules:

1. **Key hints must be prominent (to avoid accidental Enter presses)**:
   - A multi-select must show how to operate it both in the question title and at the bottom:
     `安装到哪些宿主？（空格 勾选/取消，回车 确认）` (English UI: which hosts to install to; Space toggles, Enter confirms)
     with a highlighted footer: `[空格] 勾选/取消  [a] 全选/全不选  [回车] 确认` (Space toggle, a select all/none, Enter confirm).
2. **Never design dead ends; always support going back (Back / Re-select)**:
   - Host parameter steps (such as Claude scope or DSH profile) must offer `← 返回重新选择宿主` (back to host selection).
   - If the user answers `No` at the final install-plan confirmation (Install now?), do not raise and exit; offer `重新选择宿主与选项？` (re-select hosts and options?) to return to the first step.

---

## 3. Release and version management (for official releases only)

Start an official release only after every feature and interaction has been fully verified locally:

### Version consistency
When bumping the version, keep these three places exactly identical:
1. `"version"` in `package.json`
2. `"version"` in `.codex-plugin/plugin.json`
3. `"version"` in `.agents/plugins/marketplace.json`

### npm publishing
- Always publish with the `latest` tag:
  ```sh
  npm publish --tag latest
  ```
- Keep the `latest` dist-tag pointing at the newest stable release so `npx bookmark-research install` pulls the newest build by default.

---

## 4. Managing and hiding old npm versions

To withdraw or hide messy historical test versions on npm:

1. **Unpublish (`unpublish`)**:
   - Rule: only for builds published **within the last 72 hours**.
   - Command:
     ```sh
     npm unpublish bookmark-research@<version> --force
     ```
   - Note: an unpublished version number can never be reused, and 2FA confirmation is required.
2. **Deprecate in bulk (`deprecate`)**:
   - Rule: for every older release published more than 72 hours ago, or one you do not want to hard-delete.
   - Command:
     ```sh
     npm deprecate bookmark-research@"<0.5.0-beta.19" "已废弃，请使用最新版本"
     ```
   - Effect: older releases are collapsed and marked deprecated on the npm website, and npm clients ignore them when installing and searching.
