# Bookmark Research 0.5.0 beta 15

**Beta / 测试版.** Published through the npm `beta` channel.

## Install

Pin the installer and the plugin content:

```sh
npx bookmark-research@0.5.0-beta.15 install --source npm:bookmark-research@0.5.0-beta.15
```

or follow the beta channel:

```sh
npx bookmark-research@beta install
```

For an existing DSH profile:

```sh
dsh plugin --profile <name> add bookmark-research@0.5.0-beta.15
```

## Changes

- **Question-scoped retrieval (`plan_research`).** A question is resolved locally into the cards and bookmarks it touches: literal terms weighted by length over the cards they match, multiplied by card density, one card per canonical tree. It returns `question_urls`, `task_shape`, and a route suggestion from the existing `research_route` vocabulary (`depth` follows the saved preference; no match returns `route: null`). It never fetches and never widens the scope.
- **Route-② budget and evidence bundle (`discovery_bundle`).** The plugin owns the stop decision over host-supplied `steps`/`fetches`/`variants`/`elapsed_seconds` (defaults 6 / 8 / 3 / 90s) and assembles a citation-ready bundle: only `content_state=usable` pages become evidence, the rest are listed with the reason, and the bundle degrades from excerpts to digest to a URL list instead of returning nothing. Host workflow scripts are exported for Claude, Pi and DSH.
- **Fetch evidence states.** `fetch_web` now reports `content_state` (`usable`, `content_insufficient`, `js_shell_suspected`, `challenge_blocked`, `login_required`, `soft_404`, `paywall_suspected`), `published_at` with its source and confidence (provider → structured metadata → body date, never later than the fetch day), and liveness for pages without a body (`dead` only for 404/410). Search results mark `corroborated` when more than one provider returns the same URL; that is link overlap, not content confirmation.
- **Time as data.** The index gains `added_at` / `added_at_source` / `added_at_confidence`, derived from `dateAdded` (high), the protocol ID date segment (low) or an edge id's trailing epoch (medium). Existing indexes upgrade in place (`user_version` 1 → 2) from stored `raw_json`; a missing signal stays `null` and never falls back to fetch time. Edges are ordered by parsed time.
- **Wiki one-pass page.** An incomplete finish now returns a fixed `insufficiency` block (with a derived gap and `gap_source` when no gap was recorded). `wiki_follow_up` carries `eligible_claims` with exact first quotes and `draft.page`, a page skeleton grouped by question and already split to the write limits, so one confirmation plus one `wiki_write` completes it. Imported evidence keeps the host's fetch time and text size; legacy citations without a top-level retrieval time validate against the recorded fetch time.
- **Hosts and docs.** The Skill, package semantics, host workflow references and the DSH/Codex tool scope were updated for the new tools. The Skill's suggest/ask-first rule and the human review gate are unchanged.

## Verification

- 756 tests pass, 3 skipped.
- Real package replay: `plan_research("EmbeddingGemma 2 本地部署")` selects A-1-1, `fetch_web` reports the foresight shell as unusable and the Unsloth page as usable, and `discovery_bundle` returns one citable page plus one unavailable source.
- First real host-created Wiki page (`embeddinggemma-2-local-deployment`) was checked claim by claim against its saved text; `wiki_get` now reports `current` / `valid` and lint reports no issues.

## Boundaries

The plugin does not run a headless browser or crawl pages. A login wall, JavaScript shell or dead link is reported honestly and must be re-read or replaced by the host. Automatic refetch and cross-source conflict adjudication remain host responsibilities.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.15). GitHub provides source and release notes; npm is the shared release package for all four hosts.
