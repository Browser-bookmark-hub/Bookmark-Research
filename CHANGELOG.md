# Changelog

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
