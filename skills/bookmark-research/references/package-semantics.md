# Bookmark Canvas package semantics

**English** · [中文](zh/package-semantics.md)

These bundled analysis rules cover JSON files, fields and relationships. The runtime importer does not read `AGENTS.md`; known formats can be indexed and queried without it. Consult the original guide and data when a package adds conventions, meanings conflict, or the user requests a check. This reference does not replace applicable directory instructions already loaded by the host.

## Files and fields

Section JSON uses `format: "bookmark-canvas-section"`; `sectionType` distinguishes `permanent` and `temporary`. Files reside in the protocol directories `永久栏目/` and `临时栏目/`. The entry `.canvas` stores `nodes[]`, `edges[]` and file mappings. In JSON mode, section content is not in separate Markdown files.

One source represents one logical canvas. Each supplied directory may contain at most one entry `.canvas`. Supplying a renamed entry for the same `source_id` replaces the previous layout record; a partial export without an entry retains the previous layout.

| User concept | Stored structure and query behavior |
| --- | --- |
| Permanent section card | `slot` identifies its slot, `title` its title, and `tree` a browser bookmark-tree snapshot; filters such as `section=A` restrict scope. |
| Temporary section card | `id`, `label`, `title`, `tempKind`, `source` and `items` describe an independent bookmark sandbox. A `label` may repeat and is not a unique ID. |
| Bookmarks and folders | `children` defines hierarchy. Preserve node IDs, parents, sibling order, titles and URLs. Temporary items use `type:folder/bookmark`; `sectionId` identifies their section. |
| Permanent node identity | `tree.id/parentId` uses `syncId_*`. Browser roots use `folderType` and `syncing`; these are not local Chrome numeric IDs. |
| Tags and notes | Permanent metadata joins tree nodes through `identityMap[].syncId`. Temporary `tags`, `note` and `noteColor` live directly on each item. Folders may also carry metadata. |
| Copy card | `fileRole:copy-anchor` / `inheritFrom` references a main tree. Keep the card's own description and reuse the main tree without counting another copy of its bookmarks. |
| Section descriptions and text cards | `descriptionMd` describes a section. A `.canvas` node with `type:text` contains Markdown/safe HTML. Both provide context and are not bookmark items. |
| Card group | A `.canvas` group node. Full geometric containment determines membership; visual overlap alone does not. |
| Edge | Endpoints and arrows in `.canvas.edges` determine direction. `edges[].label` is relationship text, distinct from section and group labels. |
| Original properties | `raw_json` retains unknown fields. Section headers in `get_context` omit the full tree to avoid repeating it. |

`tags` is an array of `{color,text}` objects; color and text together distinguish tags. `note` is one plain-text string, with `noteColor` as a sibling field. Metadata containing only a note remains valid. Legacy notes without `noteColor` default to `orange`. The seven tag/note colors (`red`, `orange`, `yellow`, `green`, `blue`, `purple`, `gray`) are separate from `.canvas` color fields. Color alone does not prove a business category.

File-node `file` and copy `inheritFrom` values are vault-relative paths. They may include package/vault prefixes or start directly at `永久栏目/` or `临时栏目/`. Resolve against the package file map. Do not select an arbitrary match for duplicate names, broken links or ambiguous references. External attachments are not section bookmark data.

## Interpreting relationships

- Chain labels such as `A-1 → A-1-1` suggest derivation. A child chain may retain most content or only a subset. A/B families describe creation clues; they do not prove ongoing synchronization with permanent trees or a persistent relationship. Check descriptions, titles, URLs and actual items.
- Groups have no explicit `children` list. Nesting comes from full containment using `x/y/width/height`. Groups contain canvas nodes; bookmarks inherit group context through sections and need not have individual canvas nodes.
- Edges default from `fromNode` to `toNode`, with `fromEnd:none` and `toEnd:arrow`. Read returned `direction` and original endpoints: `forward`, `reverse`, `both`, `none`. Interpret labels when present; an unlabeled connection does not establish dependency, competition or recommendation.
- Folders, groups, chain labels, tags, notes and descriptions are different classification clues. Preserve clear user categories; disclose conflicts and distinguish inference from stored facts. Analysis alone does not require reorganizing the package.

## Querying and counting

`source_id` is the logical canvas namespace. Locate items with `source_id + section_id + item_id`. One URL in different sections, paths or items still represents multiple bookmark instances. Report bookmark counts, unique URLs and company counts separately.

A permanent copy B queries the main tree A while keeping B's own description and position. Per-card `bookmark_count` values may reference the same tree and cannot simply be summed as unique bookmarks. When citing copy context, also retain the main-tree origin.

With both `section` and `group_id`, intersect actual cards before resolving their shared main trees. If only B belongs to the group, A plus that group does not match; B plus the group returns its shared bookmarks.

`search_bookmarks` uses SQL substring matching on bookmark titles, URLs, notes, tag text and folder paths, plus section/group/folder/tag filters. It does not search `descriptionMd`, text nodes or edge labels; use `get_context` for those. Short terms can produce incidental matches: `Exa` can match `examples` in a URL. Inspect matched fields and context.

The `tags` filter matches text only; returned `tags[].color` retains color. To count a color/text combination, paginate all candidates and match both fields on the same tag object. A filtered first page is not the total.

`section` can match an ID, slot, label or file path. Repeated labels can select multiple cards; use a section ID for a unique card. Without `item_id`, `get_context` returns section headers, nodes, groups and edges. Empty `items` does not mean there are no bookmarks or folders. Get a folder ID from a matched item's `ancestors`. For a complete folder list, read the relevant section JSON; there is no separate folder-list tool.

Derived FTS5 tables exist, but the public query does not use BM25 ranking, embeddings, webpage-body search or arbitrary SQL. Retaining an unknown field does not provide a filter or an interpretation rule for it.

## Synchronization and retention

`sync_package` and the CLI accept directories, ZIPs and single-card JSON, saving original snapshots, file hashes and parsed results. Snapshot queries survive removal of the original export. Live directories are checked while MCP runs and before queries by default. Invalid JSON, unsafe paths or cyclic references fail and roll back. Unavailable live sources produce query errors by default; use `refresh=false` only when the user permits the old index. See [source lifecycle](source-lifecycle.md).

In `completeness:partial`, missing files are retained and listed by sync. Deleted items inside a supplied complete section are still removed. Use `complete` only for an explicitly complete mirror to remove records for missing files. Single-card imports are always partial. Inspect `retained_missing_files`; a partial input is not necessarily all source data.

When a section keeps its ID but changes filename, update the file map and remove the replaced path's hash. Renaming it back triggers parsing again. If a partial export omits canvas or copy files, retain previously resolved stable relationships and warn that references come from older files. Once supplied, a file's actual written paths govern resolution. Original `.canvas.file` and `inheritFrom` must still agree with real paths; the index does not repair the package.

Source identity is independent of path. Reuse `source_id` for a new export of the same canvas; registered paths become aliases. Managed snapshots contain merged necessary source files and resolved relationships. Find them through `source_history` and restore into a new index without collecting every past partial export. Research inventories stay frozen; research/Wiki review flags signal changed input.

JSON/.canvas remains the source of truth; SQLite stores derived state and registrations. Background checks process local files only. Databases, source snapshots, reports, aliases and inventories stay outside the synced package. A reading task does not trigger cleanup or generation.

## Provenance and maintenance

Reading-rule version: `2026-09-09`. The protocol source is the public Bookmark Canvas [AGENTS templates](https://github.com/Browser-bookmark-hub/Bookmark-Canvas/tree/main/Bookmark-Canvas-main/history_html/transfer_AI_sync/AGENTS_template). These rules extract analysis semantics without binding the plugin to a particular user's package or paths. Check upstream protocol and parser changes during maintenance; queries do not require visiting that link.

| Protocol guide material | Where it is used |
| --- | --- |
| A1–A8, A9 text semantics, R1/R6/R7 reading semantics | File, field, identity and relationship rules above |
| S8 and S7 analysis clues | Relationship interpretation, temporary aliases and source location |
| S6 web research | [Research and provider access](research-workflow.md) |
| Relevant S1/P2 storage and partial-export semantics, P1 persistence rules | Synchronization boundaries and version retention above |

Tested `schemaVersion` values are 3 for permanent main trees, 2 for permanent copy anchors, and 2 for temporary sections. The importer validates actual fields; it is not a validator for every future schema. Changed semantics require checking the protocol and parser. Documentation changes alone do not add runtime capabilities.

Section creation/modification, ID generation, tag/note writes, layout changes and pre-import validation belong to a future generation Skill. It could reuse these reading rules and add write rules and validators. This plugin does not provide those generation capabilities.
