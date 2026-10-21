# Bookmark Research 0.5.0 beta 14

**Beta / 测试版.** Published through the npm `beta` channel.

## Install

Interactive multi-host installation and seamless upgrade:

```sh
npx bookmark-research@0.5.0-beta.14 install
```

or simply:

```sh
npx bookmark-research@beta install
```

Choose Codex, Claude Code, Pi or DSH in the interactive wizard. Existing user preferences, API credentials, research archives, and Wiki databases are strictly preserved during upgrade.

For an existing DSH profile:

```sh
dsh plugin --profile <name> add bookmark-research@0.5.0-beta.14
```

## Changes

- **Streamlined Setup Workflow**: Greatly simplified `onboarding.py` prompts, reducing redundant questions during initial installation and relying on well-tested, robust defaults for search concurrency, fallback strategies, and storage directories.
- **DeepSeek Harness (DSH) Discovery (`src/dsh_client.py`)**: Added dedicated cross-platform client detection for DeepSeek Harness Desktop, automatically identifying bundled binaries and internal pnpm distributions across macOS, Windows, and Linux.
- **Short CLI Alias (`bookmark`)**: Registered `bookmark` alongside `bookmark-research` in `package.json` bin definitions for more convenient CLI invocation.
- **Enhanced Test Coverage**: Added comprehensive test suites in `tests/test_dsh_client.py` and updated onboarding and host install test suites (totaling 692 passing tests).

## Verification

Full test suite passing across all platforms.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.14). GitHub provides source and release notes; npm is the shared release package for all four hosts.
