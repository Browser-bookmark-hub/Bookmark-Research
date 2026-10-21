# Bookmark Research 0.5.0 beta 13

**Beta / 测试版.** Published through the npm `beta` channel and synced with `latest`.

## Install

Interactive multi-host installation and seamless upgrade:

```sh
npx bookmark-research@0.5.0-beta.13 install
```

or simply:

```sh
npx bookmark-research@beta install
```

Choose Codex, Claude Code, Pi or DSH in the interactive wizard. Existing user preferences, API credentials, research archives, and Wiki databases are strictly preserved during upgrade.

For an existing DSH profile:

```sh
dsh plugin --profile <name> add bookmark-research@0.5.0-beta.13
```

## Changes

- **Installer Version Locking Bug Fix**: Fixed a critical issue in `scripts/host_install.py` where installing an npm release would erroneously overwrite the requested version with an older receipt version (`old["ref"]`), preventing Claude Code and other hosts from upgrading. The ref retention logic is now strictly scoped to Git checkouts.
- **Auto-Versioned Launcher Pinning**: Updated `scripts/launcher.py` to automatically detect and default `--source` to the running package's version (`npm:bookmark-research@{version}`). Users no longer need to type redundant `--source npm:bookmark-research@VERSION` flags when upgrading via `npx`.
- **Seamless Upgrade Experience**: Enhanced host installer to cleanly update native bundles, validate plugins, and retain all existing user settings and configurations without requiring re-entering API keys.
- **Comprehensive Regression Tests**: Added unit tests in `tests/test_host_install.py` and `tests/test_launcher.py` to prevent version regressions during upgrades.

## Verification

Full test suite passing across all platforms.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.13). GitHub provides source and release notes; npm is the shared release package for all four hosts.
