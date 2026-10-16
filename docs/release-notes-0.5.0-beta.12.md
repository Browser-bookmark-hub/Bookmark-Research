# Bookmark Research 0.5.0 beta 12

**Beta / 测试版.** Published through the npm `beta` channel; the `latest` tag remains unchanged.

## Install

Pin both the installer and the plugin content:

```sh
npx bookmark-research@0.5.0-beta.12 install --source npm:bookmark-research@0.5.0-beta.12
```

Choose Codex, Claude Code, Pi or DSH in the installer. For an existing DSH profile:

```sh
dsh plugin --profile <name> add bookmark-research@0.5.0-beta.12
```

## Changes

- **Hedged Fetching & Round-Trip Compression**: Introduced request hedging across search providers, racing fetch requests, compressing round trips, and prioritizing reuse of previously verified local evidence.
- **Fence Desync Page Recovery**: Added intelligent markdown code fence desync recovery in `archive.py`. When provider markdown truncates fences but contains valid requested page headers, the parser safely extracts and isolates each page without corrupting boundaries or dropping content.
- **Provider Circuit Breaker Refinements**: Refined fetch breaker logic in `web_search.py` to differentiate between empty provider responses and unparsed content layouts, preventing spurious provider cooldowns when valid data is received.
- **Bounded Diagnostic Excerpts**: Captured bounded raw excerpts for unreadable or malformed search provider results to streamline debugging without bloating logs.
- **End-to-End Reliability**: Full test suite updated to 666 passing tests covering fence desync recovery, provider hedging, and multi-host installations.

## Verification

Full unit test suite (666 tests) passing across Linux, macOS and Windows environments.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.12). GitHub provides source and release notes; npm is the shared release package for all four hosts.
