# Bookmark Research 0.5.0 beta 9

**Beta / 测试版.** Published through the npm `beta` channel; the `latest` tag remains unchanged.

## Install

Pin both the installer and the plugin content:

```sh
npx bookmark-research@0.5.0-beta.9 install --source npm:bookmark-research@0.5.0-beta.9
```

Choose Codex, Claude Code, Pi or DSH in the installer. For an existing DSH profile:

```sh
dsh plugin --profile <name> add bookmark-research@0.5.0-beta.9
```

## Changes

- Bookmark search supports `compact:true` in MCP and `search --compact` in the CLI. Shared rows and ordered page references reduce repeated output while preserving independent target pages, instance identity, counts, source state and extra or conflicting raw fields. The existing full response remains the default API format.
- The Skill chooses compact output for ordinary search pages and count-only queries for totals. It keeps card context separate from search results and distinguishes shared-tree copy counts from distinct bookmark instances.
- Shorter Skill and MCP instructions separate direct URL reading, agent-led search and sustained research. Ordinary answers can use sufficient evidence directly; readiness diagnosis, delegation, coverage tracking and durable research are selected when the task needs them.
- Canvas interpretation explicitly includes spatial and temporal context: neighboring cards and text, group containment, edge direction and labels, ordinary chains, repeated bookmarks across cards, dated content, protocol-defined ID dates and Git history. URL equality, topic similarity, identity-generation dates and actual reading dates retain their distinct meanings.
- Git learning retrospectives compare recorded bookmark, note, folder and layout changes, with commit and file evidence. English and Chinese guidance retain the same workflow and source boundaries.

## Verification

Regression coverage checks compact/full compatibility, target-only pages, distinct instances sharing a URL, nested value types, unknown fields, input immutability and source refresh. Real Canvas replay preserves search evidence, pagination, totals and full spatial context without changing the original package.

For one real keyword-search sample, compact UTF-8 JSON output decreased from 15,546 to 7,016 bytes (54.87%). Savings depend on result shape; count-only and text-only responses can grow slightly because of format metadata. This measures output size, not model latency or answer quality.

CI runs the Python suite and npm command smoke checks on Linux, macOS and Windows, plus native Codex installation and the shared npm package across all four host formats. Release candidates use the published npm baseline for registry integration before the new version is available.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.9). GitHub provides source and release notes; npm is the shared release package for all four hosts.
