# Bookmark Research 0.5.0 beta 5

**Beta / 测试版.** Uses the npm `beta` channel. The npm `latest` tag remains unchanged.

## Install this beta

Pin both the installer and the plugin content:

```sh
npx bookmark-research@0.5.0-beta.5 install --source npm:bookmark-research@0.5.0-beta.5
```

Choose Codex, Claude Code, Pi or DSH in the installer. Existing installations retain their recorded source and version selection. The GitHub Codex marketplace advances to this npm version after the registry confirms publication.

## Changes

- **Retrieve saved knowledge when needed.** The Skill uses Wiki when earlier research or personal knowledge is needed and missing from the conversation. Supplied text and sufficient existing evidence can be used directly; current public facts can go straight to current sources.
- **Reuse suitable host tools and evidence.** API, SDK and repository questions prefer available documentation or file tools. Attributable source excerpts can answer narrow questions; additional fetching follows evidence gaps or freshness requirements. Host-native evidence can be retained through the existing import tool.
- **Preserve fetched documentation.** Fenced code examples containing `URL:` fields or apparent page headers no longer cause a valid multi-page response to lose its extracted text. Ambiguous, unclosed examples retain the raw response.
- **Keep Wiki references usable after relocation.** New records use evidence paths relative to their research task. Reads resolve verified references at current locations, including legacy records, without rewriting history. Claims, quotes and artifact hashes remain checked.
- **Show review state in Wiki search.** Results include revision dates and validation. Changed bookmark input produces `needs_review`; invalid or retracted evidence remains excluded.

## Validation and limits

The functional diff passed [all 10 GitHub CI jobs](https://github.com/Browser-bookmark-hub/Bookmark-Research/actions/runs/37750192790), covering Python 3.9/3.12 on Linux, macOS and Windows, native Codex installation/update, npm installation and package contents. The local suite discovered 499 tests: 496 passed and three conditional integration tests were skipped. Platform-specific and unavailable-host skips are recorded separately in CI.

A replay of saved responses restored two extracted pages. A copy of real Wiki and research data recovered two searchable pages and verified 49 citations; original files and immutable revisions remained unchanged. These are data and implementation checks, not a new-session model behavior evaluation or a guarantee that upstream websites are currently available.

Move or sync Wiki indexes and revisions together with the cited research state, inventory and evidence. Preserve their relative layout for Markdown links and configure paths on the destination. Retrieval remains literal text matching. Evidence archival and Wiki synthesis remain separate, following the existing `suggest`, `auto` and `off` settings.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.5). GitHub supplies source, version notes and installation catalogs; npm remains the shared release package for all four hosts.
