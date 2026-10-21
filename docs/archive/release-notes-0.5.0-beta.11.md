# Bookmark Research 0.5.0 beta 11

**Beta / 测试版.** Published through the npm `beta` channel; the `latest` tag remains unchanged.

## Install

Pin both the installer and the plugin content:

```sh
npx bookmark-research@0.5.0-beta.11 install --source npm:bookmark-research@0.5.0-beta.11
```

Choose Codex, Claude Code, Pi or DSH in the installer. For an existing DSH profile:

```sh
dsh plugin --profile <name> add bookmark-research@0.5.0-beta.11
```

## Changes

- **Seamless Reinstall & Upgrades**: Removed rigid source/ref restrictions in `host_install.py` on `install`. Upgrading to a newer version or reinstalling now cleanly replaces the managed package bundle and updates `receipt.json` without requiring manual directory cleanup.
- **Claude Code CLI Compatibility**: Added fallback tolerance when `claude plugin validate --strict` is unsupported by the installed Claude CLI.
- **Auto-enable on Reinstall**: Reinstalling on Claude Code automatically re-enables previously disabled plugin registrations instead of rejecting installation.
- **Multi-Host Failure Diagnostics**: Explicitly reports errors to `stderr` when any target host fails in multi-target or wizard installs, preventing silent failures.
- **Data & Configuration Isolation**: Enforced complete separation between plugin code bundles and user data (`~/.config/bookmark-research` credentials and `~/.local/share/bookmark-research` research database/wiki), guaranteeing existing configurations and history remain untouched during updates.

## Verification

Full unit test suite (633 tests) passing across Linux, macOS and Windows environments covering installation overwrites, multi-host exports, and upgrade workflows.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.11). GitHub provides source and release notes; npm is the shared release package for all four hosts.
