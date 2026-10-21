# Bookmark Research 0.5.0 beta 7

**Beta / 测试版.** Uses the npm `beta` channel. The npm `latest` tag remains unchanged.

## Install this beta

Pin both the installer and the plugin content:

```sh
npx bookmark-research@0.5.0-beta.7 install --source npm:bookmark-research@0.5.0-beta.7
```

Choose Codex, Claude Code, Pi or DSH in the installer. Existing installations retain their recorded source and version selection. The GitHub Codex marketplace advances to this npm version after the registry confirms publication.

DSH installs the released layer directly:

```sh
dsh plugin --profile <name> add bookmark-research@0.5.0-beta.7
```

## Changes

### Correctness

- **One release-version source.** `src/release.py` reads `package.json`, and the MCP `serverInfo`, the remote client `clientInfo` and both outbound user agents use it. Runtime identity had reported `0.5.0-beta.3` while the manifests said `0.5.0-beta.6`. A regression test fails any build that reintroduces a hardcoded release version outside `release.py`, and asserts that the real handshake matches the manifest.
- **A copied data directory resolves its own research tasks.** `research-locations.json` carries absolute paths, so a same-machine clone used to read and write the *origin's* task folder even when `--directory` named the clone. The task folder inside the data directory in use now wins, the registry stays the fallback for tasks created beside their input, and a second valid folder for the same id is reported as `location_status: "conflict"` with `alternate_path` instead of being hidden.
- **The task lock no longer spans a network request.** A provider that answered slowly held the task lock for the whole call, so an independent process recording a finding timed out after ten seconds with a settings-worded error. Reservation, request and commit are now separate: only reserve and commit hold the lock, a mid-request fallback reservation re-reads state under it, and genuine contention returns a retryable "research task is being written by another process".
- **Every occurrence of a merged body can be enumerated.** `search_archive` truncated a body's occurrences at 50 with no marker and no continuation. Results now carry the true `occurrence_count`, `occurrences_truncated` and `occurrences_next_offset`, and `occurrence_limit` / `occurrence_offset` page through them in a stable order.
- **A legitimate source change can be resolved.** `source_input_changed` is a warning about the frozen research input version; re-reviewing a page could never clear it. `wiki_write` now accepts `reviewed_input_version`, `wiki acknowledge` records a review without editing content, acknowledgements carry forward while they are still current, and a later source change reopens the warning. `wiki_lint` also reports `severity: "info"` for an acknowledged change instead of leaving only the warning.
- **`wiki.directory` applies without a restart.** A long-lived stdio server cached the Wiki store built from the directory configured at first use, so `update_settings` appeared to succeed while reads and writes continued against the old location.

### Retrieval

- **`items_fts` now answers queries.** The shipped FTS table used the default tokenizer, which treats a whole run of CJK characters as one token, so it could not match `推理` inside `推理加速` and the query path used `LIKE` only. The table uses the substring-based **trigram** tokenizer and is rebuilt in place when an existing database is opened. Terms of three or more characters use `MATCH`; one- and two-character terms keep the `LIKE` fallback, because a trigram index cannot answer them. Substring semantics are unchanged (`RAG` still finds `AutoRAG`). When trigram is unavailable the index stays usable and every term falls back to `LIKE`.
- **Whitespace-separated terms are required together.** A multi-word target was matched as one literal phrase, so `linux.do topic` returned nothing. Each term must now occur; `推理 加速` requires both words.
- **Canvas text is findable.** Group labels, edge labels and text cards were outside every search field, so asking about "the card labelled 123" returned unrelated short-substring bookmark hits with no sign that `123` was a group label. `search_bookmarks` now reports `canvas_matches` (attributed per target) and states explicitly that they are not bookmark items and never inflate `total`.
- **Counting guardrails.** A copy anchor reports the shared tree's count, so summing per-card counts over-reported 638 bookmarks as 1239. `context.sections[]` now carries `counted_in_totals` and `anchor_of`, `context.counts` and `search.counts` give instance and unique-URL totals for the scope, `search` warns when the requested card is an anchor, and items report `shown_in_anchors`.
- **Smaller gaps.** Folders can be enumerated (`item_types` / `--item-type folder`), the synthetic untitled tree root is marked `synthetic` and counted separately as `tree_roots`, `search` returns `next_offset`, `limit=0` / `count_only` returns counts without rows, tag colours are filterable, and Wiki search matches text whose spacing differs from the query (`唯一URL` finds `唯一 URL`).

### Operations

- **Duplicate imports are no longer silent, and can be undone.** Importing the same canvas from a new folder used to add a second identical source with `warnings: []` and no way back. `sync_package` now reports `duplicate_source_ids` with a warning naming the source to reuse, and `source remove` / `source merge` (MCP `source_remove` / `source_merge`, CLI `source remove` / `source merge`) clean up. Both only report until `confirm: true` / `--confirm` is passed; merge refuses sources whose content versions differ and moves the duplicate's path aliases to the survivor.
- **`doctor` checks that it can actually write.** An unwritable data directory produced a fully green `doctor` followed by a raw SQLite error from the first import. `doctor.storage` now probes the data directory, the config directory and an existing database, and reports `next_step` with the exact environment variables to set. A read-only failure from any command is rewritten to name `BOOKMARK_RESEARCH_DATA_DIR` and `BOOKMARK_RESEARCH_CONFIG`.
- **An incomplete DSH install says so.** The DSH entry module preflights `src/cli.py` and the Skill before registering; when either is missing it writes the reason and the reinstall command to stderr and registers nothing, instead of letting the host fail later with a bare `ENOENT`.
- **`partial` retention is stated up front.** `status` returns `retained_missing_note` when imported files are no longer in the package.

## New tools

`wiki_acknowledge`, `source_remove` and `source_merge` bring the local MCP surface from 37 to 40 tools. `search_bookmarks` gained `tag_colors`, `item_types` and `count_only`; `search_archive` gained `occurrence_limit` and `occurrence_offset`.

## Validation and limits

561 discovered local tests pass (three conditional integration tests skipped), up from 506, with new coverage for every change above. Verified end to end on the sample canvas package (638 bookmark instances, 557 unique URLs, 5 sections, 7 canvas nodes, 3 edges): index counts still match an independent parse, the copy anchor is not double counted, `complete` still refuses an incoherent export and keeps the previous index, a fabricated citation is still rejected, and `research_finish` still refuses to claim completion while original URLs are unread.

Not verified in this release: Windows and Pi installation; a fresh DSH Desktop profile (the running app still resolves the Skill from a native-install directory that a previous installer created and that no longer exists — restarting the app, or reinstalling into the profile, re-resolves it); ten-thousand-plus URL research budgets; and the still-open items listed in the evaluation report: `context()` N+1 queries, an index time field, and local-only facts entering a research report.

Install from [npm](https://www.npmjs.com/package/bookmark-research/v/0.5.0-beta.7). GitHub supplies source, version notes and installation catalogs; npm remains the shared release package for all four hosts.
