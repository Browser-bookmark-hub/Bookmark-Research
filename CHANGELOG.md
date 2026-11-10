# Changelog

## 0.7.2 — 2026-11-10

0.7.2 adds cross-platform Codex CLI auto-discovery across Node version managers
and system locations, refactors the `deep`/`all` tool surface to advertise 40
real tools without replaced aliases, and tightens skill preflight workflows.

### Added
- Cross-platform Codex auto-discovery (`src/codex_client.py`): probes `$PATH`
  first, then scans NVM/fnm/Volta/asdf version pools, persistent user bins
  (`~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, Windows `%APPDATA%\npm`),
  and official Codex runtime releases (`~/.codex/packages/app-server-daemon`).
  Solves `◯ Codex (CLI not found)` when switching Node versions or in hermetic
  terminal sessions.
- Interactive wizard and installer transparency: automatically resolves Codex
  binaries and displays the discovered executable path in upgrade/install plans.
- Test coverage in `tests/test_codex_client.py` and `tests/test_onboarding.py`
  for multi-platform discovery and PATH-absent resolution.

### Changed
- The 18 replaced MCP names are no longer advertised by `deep`/`all`; the
  catalog shows 40 real tools. Replaced names remain callable (and can be named
  by an explicit `tool_scope`) until the 0.8.0 cutoff.
- Skill instructions and Chinese reference guide: bounded preflight guidance
  for local evidence when relevant, bounded `plan_research` usage with Canvas
  `source_id`, clarified `ingest` provenance requirements, and explicit note
  when `wiki.enabled` is false.
- Added planning documents for evidence impact and tool surface cleanup.

## 0.7.1 — 2026-11-09

0.7.1 keeps the 0.7.0 CLI-first surface and adds a switchable Wiki layer, a
deterministic compile planner, host-native search reporting and discovery
backflow, plus two Wiki write fixes found in the B-1-1 pilot.

### Added
- CLI aliases: `read` (context), `walk` (traverse), `fetch` (fetch-web). `search`
  stays the bookmark search command, so web search remains `search-web`.
- `bookmark-research job prune --days 7 --keep-latest 200`; the worker prunes on
  start and `spawn` reports `worker: running|not_running`.
- `locate --exclude-junk` (MCP `exclude_junk`) drops divider/placeholder rows.
- Fetch cache eviction: expired rows and anything beyond the newest 500.
- Chinese `docs/details.md` lists the 10-primitive MCP surface.
- `wiki.enabled` master switch (default true), asked once by setup and editable
  through `get_settings`/`update_settings`. When false, `save` and the deep Wiki
  tools disappear from the catalog, Wiki-scope reads/writes and compile planning
  fail with a clear error, and `research_finish` skips the Wiki follow-up.
- `wiki_compile` (deep MCP) and `br wiki compile plan|status|gap`: deterministic
  incremental-compile planning over a bookmark scope. It clusters by folder,
  drops search pages, dividers and duplicate URLs, reports current-revision
  coverage, existing/affected pages and a per-cluster item budget. Planning
  writes only `compile/<plan_id>.json`; it starts no fetch and writes no page.
- `wiki_compile(action:"gap")` / `br wiki compile gap`: record planned URLs that
  were attempted but could not be read, so `status` separates covered, gap and
  pending items and reports `coverage_basis`.
- `research_finish(discovery={...})`: record the host/plugin search channel and
  whether host results were ingested; declaring host search without backflow is
  rejected, and an unreported channel is flagged in `discovery_audit`.
- CJK bigrams in Wiki page-title matching, so Chinese cluster titles can match
  existing pages instead of relying on URL overlap only.

### Changed
- Host-native search detection accepts namespaced tool names (`tools.web__run`,
  `functions.web__run`) and ignores `mcp__...` plugin tools. `health` (optional
  `host`/`observed_tools`) and `readiness` (`host_integrations.search`) report the
  observed channel.
- Skill and references require host search batches to be ingested with
  `provider=host:<name>` before they support an answer or a Wiki page.
- Auto-save now preserves an authored page title and kind when merging a
  research draft; the draft only appends sections and links.
- Wiki writes accept canvas section/item IDs with non-ASCII names when bookmark
  references are derived from the index instead of rejecting them.
- Added `planning/2026-11-wiki-compile.md` (design draft; plan/status and gap
  are implemented).

### Tests
- Added coverage for job pruning/worker lock, cache eviction and the junk filter.
- Routing, readiness and health coverage for namespaced host search names and
  MCP-prefixed rejection.
- Wiki compile planning: noise filtering, coverage/gap status, folder scope,
  idempotency, plan-file containment and CJK title matching; auto-merge
  title/kind; research discovery reporting and backflow rejection.

## 0.7.0 — 2026-11-09

CLI-first release: the CLI and MCP entries share one core, one result schema and
one set of refs. The default MCP surface is 10 primitives; the full catalog keeps
57 names and deprecated aliases stay callable until 0.8.0.

### Added
- `locate(package_path=...)`: import a package, a single card or a card export
  and return counts, sections (`source`/`temp_kind`), notes, search-result
  pages, divider rows and duplicate groups.
- `locate` metadata-only queries (`has_note`, `has_tags`, `tags`) and folder
  title hits with a `folder_id` hint.
- `read(folder_ref)` returns the first children and `child_count`.
- Durable local job queue (`jobs.sqlite3`) with idempotency, leases, retries,
  cancellation and crash recovery; singleton `bookmark-research job worker`.
- `spawn(task="fetch"|"ingest"|"research")` and `job(job_id|external_id)`.
- Card-export imports: section JSON without ids, Netscape bookmark HTML with
  nested folders, `{"data": …}` envelopes and bare lists.
- `bookmark-research dupes`: duplicate URL report with a proposed keeper.
- `fetch` skips search-engine result pages without network access.
- TTL fetch cache keyed by urls/provider/archive/max (opt-in via
  `fetch.reuse_seconds`).

### Changed
- `read`/`walk`/`locate`/`health` use read-only index connections and default
  to `refresh=false` (concurrent read cost from ~20s to <0.3s).
- Skill and CLI reference document the 10 primitives, first-contact rules and
  host-first fetch routing.

### Deprecated
- Legacy tool names remain callable but are hidden from the default catalog;
  they are rejected at 0.8.0.

### Tests
- 925 tests (13 skipped).
