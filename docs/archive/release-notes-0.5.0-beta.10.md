# Bookmark Research 0.5.0 beta 10

**Beta / 测试版.** Published through the npm `beta` channel; the `latest` tag remains unchanged.

## Install

Pin both the installer and the plugin content:

```sh
npx bookmark-research@0.5.0-beta.10 install --source npm:bookmark-research@0.5.0-beta.10
```

Choose Codex, Claude Code, Pi or DSH in the installer. For an existing DSH profile:

```sh
dsh plugin --profile <name> add bookmark-research@0.5.0-beta.10
```

## Changes

- **Wiki Refresh & Workflows**: Added `wiki_refresh` to update Wiki pages against new source updates and evidence, and `wiki_work` for resumable, interrupted multi-page maintenance and status tracking.
- **Candidate-First Wiki Search**: Implemented optimized candidate-first retrieval in `wiki_search.py`, supporting aliases, incremental log maintenance, and directory summaries without scanning every revision.
- **MCP Server Concurrency & Dispatch**: Integrated worker-pool request dispatching with thread isolation, request IDs, serialized output, and guarded cancellation to prevent slow network fetches from blocking local MCP calls.
- **Fetch & Archive Boundaries**: Enforced page/batch fetch budget limits, distinct slice vs archive SHA tracking, and snapshot resumption.
- **Source Dependency & Freshness**: Added URL version tracking (`source_versions.py`) and bookmark dependency mapping (`bookmark_dependencies.py`) to trigger reviews based on age and content shifts.

## Verification

Full unit test suite (633 tests) passing across Linux, macOS and Windows environments covering concurrency, pagination, wiki work resumption, and retrieval accuracy.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.10). GitHub provides source and release notes; npm is the shared release package for all four hosts.
