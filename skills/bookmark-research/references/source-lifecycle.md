# Source intake, snapshots and live synchronization

**English** · [中文](zh/source-lifecycle.md)

Choose input format and source lifetime separately. A directory or ZIP may be a one-time export; a permanent/temporary card JSON is partial input; a Git-synced local directory may be live. A section's permanent/temporary type does not decide its source lifetime.

## Registration and identity

`sync_package(package_path, source_id?, mode?, completeness?)` and CLI `sync` share one implementation:

| Parameter | Behavior |
| --- | --- |
| `package_path` | Protocol directory, ZIP or one `bookmark-canvas-section` JSON. ZIPs may have wrapper directories but must contain only one canvas package. A ZIP with one card also works. |
| `source_id` | Stable logical source identity. Omission reuses a registered path's association; a new path creates an ID. Explicitly reuse the ID when moving, renaming or re-exporting the same canvas. Those paths then remember the association. |
| `mode: snapshot` | Save source protocol files and a derived index. Queries use the imported snapshot even after the original download directory/archive is moved. |
| `mode: live` | Directories only. Check before queries and while MCP runs; synchronize changes incrementally using hashes. |
| `completeness: partial` | Default. Retain omitted files; delete removed items inside a supplied complete section. |
| `completeness: complete` | An explicitly complete mirror. Remove missing section/canvas files; unavailable for a single card. |

New ordinary directories, ZIPs and cards default to `snapshot`; directories in Git repositories default to `live`, still with `partial` completeness. Existing sources retain registered mode/completeness; single-card input automatically uses `partial`. Legacy registrations keep `live + partial`; explicitly register again to convert to a snapshot.

When the user provides a new export of the same canvas, obtain its original `source_id` from `index_status`. The export protocol has no reliable global canvas ID. Do not merge different canvases by title, URL, slot or equal section IDs. If a path has been registered to multiple sources, specify `source_id`. Users can describe the relationship naturally; these are tool parameters.

```sh
# One export; reuse my-canvas for subsequent input
python3 <root>/src/cli.py sync /downloads/export.zip --source-id my-canvas
python3 <root>/src/cli.py sync /downloads/card.json --source-id my-canvas
# A complete Git-synced directory explicitly identified by the user
python3 <root>/src/cli.py sync /repos/bookmarks/canvas --source-id synced-canvas --mode live --completeness complete
python3 <root>/src/cli.py status synced-canvas
```

For a single-card update to a known source, stable section identity maps to its original file path, avoiding broken references caused by a changed download filename. A copy anchor alone contains no main tree. Report unresolved references when that tree is absent; do not invent bookmarks.

## Snapshots and recovery

Snapshots live next to the database under `<database-filename>.sources/`, normally `index.sqlite3.sources/`. Each source/content version has a directory: `package/` contains all required JSON/.canvas files, including files retained from partial exports; `manifest.json` records hashes, input locations and resolved relationships. Original files are not rewritten; attachments and unrelated files are not copied.

`source_history(source_id, limit?, offset?)` / CLI `history` lists content versions. Unchanged content and relationships reuse a version; old versions are neither overwritten nor automatically cleaned. Normal queries use the current index. `refresh=false` does not select history.

```sh
python3 <root>/src/cli.py history my-canvas
# Use snapshot_path returned by history, including when restoring into a new database
python3 <root>/src/cli.py --db /data/recovered.sqlite3 sync /data/index.sqlite3.sources/<source>/<version>/package --source-id my-canvas --mode snapshot --completeness complete
```

Recovery checks snapshot hashes and restores group/copy relationships. If a partial export only renamed a section and omitted a new canvas file, resolved relationships are stored separately in the manifest while original canvas bytes remain intact. When a legacy index has no snapshots and its directory is gone, full JSON stored in SQLite can recover semantics. `Recovered legacy JSON...` warns that original whitespace cannot be preserved and input hashes will change.

## When live updates occur

MCP starts in-process checks for existing live sources on connection and after first registration. Python standard-library polling checks protocol files every 1 second by default, synchronizes ordinary changes after 2 stable seconds, and waits 5 stable seconds for whole-file deletions in complete directories. The design borrows CodeGraph's change coalescing, pending state and reconnect checks, not its native filesystem event watcher.

Normal queries also check proactively. Valid changes without whole-file deletions can update immediately; deletions still wait for stability. Invalid JSON, unsafe paths, identity conflicts or unresolved references in a complete mirror roll back the entire import. A missing/temporarily empty directory or Git write lock preserves the last valid index. An empty directory does not clear the database; an explicit empty canvas or section can express empty content. Manual `sync` is an explicit import and does not use the background deletion grace period.

`index_status` and the `source` returned by local queries expose:

| `state` | Meaning |
| --- | --- |
| `snapshot` | Fixed imported snapshot; original download is not monitored. |
| `current` | Synchronized at the latest check; inspect `checked_at` too. |
| `pending` | Waiting for stability or a Git write; `pending_files` lists identified changes. |
| `unchecked` | A live source has not been checked recently; disk freshness is unproven. |
| `unavailable` / `error` | Source unavailable or invalid; `error` explains why and the old index remains. |

Live queries return errors for error/unavailable by default. Use `refresh=false` / `--no-refresh` only when the user permits old data. Pending queries may return previous valid data but must disclose pending synchronization. New research does not freeze inventories from pending/error/unavailable input.

Background checking follows the host MCP process, stops with it and resumes on reconnect. The first query also checks. A standalone CLI query exits when finished; run `python3 <root>/src/cli.py watch` for foreground monitoring and stop with Ctrl-C. `watch` accepts `--interval`, `--debounce` and `--deletion-grace` in seconds and emits JSON lines for status changes. A host using one-shot CLI commands does not automatically gain a persistent watcher.

Git pull, push and login remain with the existing sync system or host; the plugin reads local results. Multiple MCP processes have separate SQLite connections with transactional writes and consistent query snapshots. ZIP imports reject path traversal, symlinks, duplicate members and ambiguous multiple packages. Limits are 64 MiB per file, 256 MiB total uncompressed size and 10,000 entries.

## Research and Wiki

Index updates do not fetch webpages, call LLMs or rewrite Wiki pages. Research inventories, text and conclusions retain their original versions. `research_status.source_freshness` compares frozen input against the current synchronized index and sets `requires_review=true` on changes. Wiki reads/lint mark `source_input_changed`; `wiki_get.validation.status` becomes `needs_review`. This requests review against new input without declaring the old conclusion false. Webpage changes are outside this check.

References: [CodeGraph indexing](https://github.com/colbymchenry/codegraph/blob/main/site/src/content/docs/guides/indexing.md) and [watcher](https://github.com/colbymchenry/codegraph/blob/main/src/sync/watcher.ts). These are public documentation/code comparisons; CodeGraph's own tests are not acceptance tests for this plugin.
