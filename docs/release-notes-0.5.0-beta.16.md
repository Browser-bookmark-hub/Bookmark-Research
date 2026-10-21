# Bookmark Research 0.5.0 beta 16（草稿）

> **Release 0.5.0-beta.16.** 版本号已同步到 `package.json` / `.codex-plugin/plugin.json` / marketplace；发布渠道为 npm `beta` 标签。

## Changes

- **Preflight becomes a knowledge check.** `plan_research` now returns `wiki[]`, `archive[]`, `relevance`, `freshness`, `fetch` and a bounded `preflight_budget` alongside the existing cards, URLs and route. It remains local and read-only.
- **Wiki and archive are searched by terms, not by the whole question.** A natural-language question is reduced with `plan_terms`; each term is searched and merged by page/bundle. `WikiStore.search_terms` reports `current` / `needs_review` / `invalid`, `issues_count`, `expired_count` and suggested actions; it does not refresh automatically.
- **Missing cards no longer hide behind stale data.** A retained card whose file is gone is marked `stale_missing_file`; it does not take a top slot while a current card exists, but its URLs remain available and are marked `stale`. The source input path is used for this check, not the frozen snapshot path.
- **URLs are ordered by shape.** `url_kind` distinguishes docs/changelog/repo/homepage/login/search; docs and changelogs come first, homepage count is capped, and login/search results are deprioritized.
- **Relevance has a floor.** Incidental substring matches such as `quantum` inside `QuantumNous` or a lone `量子` in a large tree now produce `route: null` instead of a false `lookup`. The floor and homepage cap are settings.
- **Freshness is data, not a guess.** `freshness.newest_any`, `newest_high`, `confidence` and `stale` are returned together; low-confidence ID dates are kept and downweighted, never treated as high-confidence.
- **Fetch budget is fair.** `fetch_web` defaults to a 24,000-character total, divides the remainder over pages (`fetch.fair_share_min`), reports `pages_with_text` / `pages_without_text`, and marks zero-text pages `unavailable` instead of `usable`.
- **Evidence can be tied back to a capture.** `discovery_bundle` accepts `capture_id` and `text_sha256`, reads the saved extract, verifies the hash and adds `capture_id`, `text_origin`, `quote_verified` and `source_characters` to evidence. Host text stays `text_origin=host` / `quote_verified=false`; a mismatch is reported, not silently accepted.
- **Context has a compact projection.** `get_context(compact=true)` drops `raw_json`, `description_md` and `revision`; pair it with a collection for the smallest response.
- **Tool scope is server-side.** `tool_scope` (default `[]` = all) narrows `tools/list` and rejects hidden calls on hosts that cannot filter MCP tools. The Codex project config and the DSH plugin now expose the full catalog by default; `BOOKMARK_RESEARCH_TOOL_SCOPE` can still narrow it, and an empty value restores all tools.
- **CLI follows the same budget.** `fetch-web` uses the saved `fetch.max_total_characters` and `fetch.fair_share_min` when flags are omitted.

## Verification

- `768` tests pass, `3` skipped (`python3 -m unittest discover -s tests -p 'test_*.py'`).
- Real package `github-bookmark-canvas` (4,966 items / 4,130 bookmarks / 3,079 URLs):
  - `云厂商 Agent Runtime 有哪些变化`: A-10-2 is flagged stale and does not take a top slot; the top URLs are documentation pages, not vendor homepages.
  - `RAG 企业落地要点`: Wiki hits `rag-search-and-mcp-20260912` and `rag-evaluation-and-wiki-20260912` with `needs_review`; they are not refreshed automatically.
  - `EmbeddingGemma 2 怎么本地部署`: preserves the direct-retrieval route and finds the target Wiki page and archive captures.
  - `quantum entanglement agriculture breeding` and `量子纠缠在农业育种中的应用`: `route: null`.
- Six pages under a 10,000-character archive read now all receive text (six text-bearing pages) instead of starving the last three.

## Boundaries

- No provider-profile expansion; no `deep_research` policy block.
- No `discovery_bundle(draft_claims)`; the existing `research_finish.wiki_follow_up` draft remains the only claim path.
- `fetch_web(return="handle")` is not enabled by default; the text budget fix lands first.
- No automatic Wiki refresh or publish; review gates are unchanged.
- The companion plan and its evidence are in [the beta.16 plan](plugin-search-routing-plan-2026-10-19.md) and the validation report (`docs/archive/plugin-search-routing-plan-validation-2026-10-19.md`).
