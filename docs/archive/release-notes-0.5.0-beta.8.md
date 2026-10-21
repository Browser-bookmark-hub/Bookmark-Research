# Bookmark Research 0.5.0 beta 8

**Beta / 测试版.** Published through the npm `beta` channel; the `latest` tag remains unchanged.

## Install

Pin both the installer and the plugin content:

```sh
npx bookmark-research@0.5.0-beta.8 install --source npm:bookmark-research@0.5.0-beta.8
```

Choose Codex, Claude Code, Pi or DSH in the installer. For an existing DSH profile, the released layer can also be installed directly:

```sh
dsh plugin --profile <name> add bookmark-research@0.5.0-beta.8
```

## Changes

- DSH exports support legacy npm packages that lack the nested ESM manifest. Repair instructions retain the selected profile and release version. The Desktop prerequisite test now resolves actual executable shims on Windows.
- Relocated Codex, Claude Code and Agent Plugins exports report their own release version during the real MCP handshake.
- Cancelled or incomplete research tasks reject late provider results and further fallback reservations. Concurrent evidence imports retain the final source IDs in their manifests.
- Source merging checks matching, nonempty synchronized versions inside the write transaction. Source removal preserves concurrent reimports; startup recovers hash-verified snapshots left by an interrupted removal without reviving committed deletions.
- Wiki acknowledgements cannot accept invalid evidence. Unavailable sources require review, and a new acknowledgement retains its review note.
- Canvas searches preserve literal `%`, `_` and backslash characters. Storage diagnostics close probe handles, preserve existing files and report paths blocked by files.

## Verification

Regression coverage includes research cancellation, source merge/removal races, process-exit recovery, Wiki evidence integrity, exported release identity and DSH installation prerequisites. CI runs the Python suite and npm command smoke checks on Linux, macOS and Windows, plus isolated native Codex installation, migration and update tests.

Release branches test registry integration against the currently published package while validating the candidate's source and packed runtime. After publication, the main branch verifies the newly pinned npm version. Personal canvas packages and local evaluation reports are excluded from the published package.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.8). GitHub provides source and release notes; npm is the shared release package for all four hosts.
