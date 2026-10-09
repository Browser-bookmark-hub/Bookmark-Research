# Bookmark Research 0.5.0 beta 6

**Beta / 测试版.** Uses the npm `beta` channel. The npm `latest` tag remains unchanged.

## Install this beta

Pin both the installer and the plugin content:

```sh
npx bookmark-research@0.5.0-beta.6 install --source npm:bookmark-research@0.5.0-beta.6
```

Choose Codex, Claude Code, Pi or DSH in the installer. Existing installations retain their recorded source and version selection. The GitHub Codex marketplace advances to this npm version after the registry confirms publication.

## Changes

- **DSH installs the release directly.** The package now declares `dsh.bundle.patch` and ships `bundle.patch.yml`, so `dsh plugin --profile <name> add bookmark-research@0.5.0-beta.6` — or the DSH plugin manager — installs it with no export step first, and DSH selects the bundle into `dsh.profile.bundles` on its own. Nothing in the layer is tied to the building machine: the entry module supplies the interpreter, working directory, MCP arguments and forwarded environment variables at load time.
- **No `python3` assumption in the DSH layer.** The module discovers Python 3.9+ with SQLite in the same order as the npm launcher (`BOOKMARK_RESEARCH_PYTHON`, `python3`, `python`, `py -3`) and reports a warning instead of failing silently when none is found, so Windows no longer depends on a `python3` alias.
- **DSH Desktop's reserved profile is installable.** DeepSeek Harness Desktop refuses to boot or dump the profile name `desktop`, so the installer verifies that profile from the persisted layer (dependency target, package-relative `dsh.bundle.patch`, entry module, Skill and MCP rows) instead of `--dump-config`.
- **A bundled package manager satisfies the DSH prerequisite.** A CLI that carries its own pnpm — the DeepSeek Harness Desktop CLI does — no longer requires `pnpm` on `PATH`; a generic CLI still fails before creating a profile, with instructions.
- **Unwritable npm caches are diagnosed and retried.** When npm reports a cache permission failure (for example root-owned files from a privileged install), the download retries once in a scratch cache and otherwise reports the `chown` repair command.
- **The exported DSH bundle is the released layer.** `export_bundle.py --format dsh` copies the committed `bundle.patch.yml` byte for byte; a source tree that predates the layer (an older published package or Git ref) still exports a working equivalent, so pinned installations do not regress.

## Validation and limits

The functional diff passed 506 discovered local tests, including new coverage for the released DSH layer, the offline verification of the reserved `desktop` profile, the bundled package manager, and the npm cache retry. A real installation into the DeepSeek Harness Desktop profile (`desktop`, runtime `0.2.0-rc.2`) registered the Skill, listed 37 MCP tools, and resolved the running MCP child to the installed package; a packed release installed in a throwaway profile was selected into `dsh.profile.bundles` automatically.

Not verified in this release: Windows and Pi installation, and the cache-retry path on a machine whose npm cache is genuinely unwritable. These are covered by unit tests only. No paid research model was started.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.6). GitHub supplies source, version notes and installation catalogs; npm remains the shared release package for all four hosts.
