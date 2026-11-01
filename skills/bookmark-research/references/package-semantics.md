# Bookmark Canvas package semantics

**English** · [中文](zh/package-semantics.md)

These bundled analysis rules cover JSON files, fields and relationships. The runtime importer does not read `AGENTS.md`; known formats can be indexed and queried without it. Consult the original guide and data when a package adds conventions, meanings conflict, or the user requests a check. This reference does not replace applicable directory instructions already loaded by the host. The package's exported guide also governs writes to the package; this reference and the plugin only read the package.

## Files and fields

Section JSON uses `format: "bookmark-canvas-section"`; `sectionType` distinguishes `permanent` and `temporary`. Files reside in the protocol directories `永久栏目/` / `Permanent/` and `临时栏目/` / `Temporary/`.
- Chinese layout: `永久栏目/` (e.g. `A书签树.json`), `临时栏目/` (e.g. `常规链式/A-1.json`, `特殊临时栏目/AI 推荐资源.json`)
- English layout: `Permanent/` (e.g. `A-PermanentBookmarks.json`), `Temporary/` (e.g. `General Chain/A-1.json`, `Special temporary/AI Recommended Resources.json`)
The entry `.canvas` stores `nodes[]`, `edges[]` and file mappings. In JSON mode, section content is not in separate Markdown files.

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

File-node `file` and copy `inheritFrom` values are vault-relative paths. They may include package/vault prefixes or start directly at protocol directories (`永久栏目/`, `Permanent/`, `临时栏目/`, `Temporary/`). Resolve against the package file map. Do not select an arbitrary match for duplicate names, broken links or ambiguous references. External attachments are not section bookmark data.

Temporary items must be classified by `type`: a folder can have `url:""`, and a bookmark can have `children:[]`. Field presence alone does not identify its kind. These empty fields are part of the current serialized shape, not a request to clean the package. The derived item index omits `children` from each item projection and omits empty folder URLs; this projection does not modify the original source snapshot, which retains the complete tree. Use `folder_id` to page through a subtree as flat rows carrying parent IDs, paths and positions, avoiding a repeated nested tree in each result. For source edits, reread the original node and preserve fields unrelated to the requested change. Missing/conflicting types, nonempty folder URLs or nonempty bookmark children require checking the original node and reporting the anomaly. Do not guess a type, discard content or rewrite the source to make indexing succeed. This temporary-item convention does not change permanent-tree rules.

## Tool-based reading with or without the plugin (Core Red Line)

**Core Red Line Invariant**: Small files may be read directly; when handling large files or full packages, **never dump entire files or large JSONs into the conversation context**; a standalone section JSON contains only node items and metadata without `.canvas` coordinates or connections; when reading an isolated section JSON without canvas topology, **never speculate on or hallucinate spatial positions or visual layouts**.

Actually call available tools to read package data; examples are not evidence of a user's current content. When the companion plugin is available, prioritize querying its local SQLite index and MCP tools. If the plugin is unavailable, use the host's file reader, terminal or code execution tools (Python, Node.js, `jq`) without making installation a prerequisite. Check actual paths and byte sizes; use a reader for small files and local Python/Node.js/`jq` scripts to parse and slice large JSON or compact `.canvas` files.

- **One card:** locate its node ID and resolved file reference, then read the required section description and `tree` / `items`, or a text card's body. A copy follows `inheritFrom` to its main tree. A standalone section JSON contains only node items and metadata without `.canvas` coordinates or connections; when reading an isolated section JSON without canvas topology, never speculate on or hallucinate spatial positions or visual layouts.
- **Multiple cards:** extract a compact layout map, then expand the requested cards and relevant relations/text as described below. Return selected records and coverage rather than dumping full large files into context.
- **Reusable queries:** for large packages, cross-card work or repeated queries, reuse the existing source index when possible; otherwise build a local in-memory map or derived SQLite index outside the package. A small one-off read needs no database. Retain source, section ID, item ID, parent path and sibling order; do not collapse instances by URL. With the plugin, use `get_context` for layout and `search_bookmarks` for items, respecting scopes and pagination. Partial input is not a complete mirror.

Index/search results are projections, not replacement source objects: item `raw_json` omits `children`, and folder projections omit an empty `url`. The original source snapshot retains these fields. Search a folder with `folder_id` to read its descendants as paginated flat rows; parent IDs, paths and positions preserve tree structure without making an ancestor count as changed whenever a descendant changes. Compact responses omit additional fields. For a user-authorized edit, the host must reread the current original node, check for intervening file changes and preserve untouched values, descendants, metadata and unknown fields under the package guide. Validate the edited file and refresh the same `source_id` before querying again. Neither reading nor building an index calls for source cleanup.

## Interpreting relationships

### Retrieve layout, then expand content

For a small indexed canvas, start with `get_context({source_id})`: this includes the whole stored layout, even text cards without edges. Then select the requested section/group/item. Scoped context deliberately selects nodes; missing text in that selection does not prove that the canvas contains no nearby note. Match file nodes to section IDs through the returned file mapping, not by assuming node IDs and section IDs are interchangeable.

For a large canvas, read `.canvas` locally with Python's standard-library `json` parser. Keep the full parsed object in the local process; send only relevant records to the model:

1. Extract a compact map of IDs, types, file references, `x/y/width/height`, group labels, short text previews and edges. If even that is large, report total counts and group/region summaries first. Retain the complete map locally; a preview is not complete traversal.
2. Locate the requested card by its ID or resolved file. Select containing groups, relevant group members, connected nodes and geometrically nearby text/cards. Preserve edges crossing the selection boundary and their endpoint records. A remote connected card can matter more than a close unconnected card.
3. Read full text and section descriptions for the selected context, then the requested bookmark trees. Preserve IDs and report selected/omitted node counts and any truncated text. Expand when a label, edge or question points outside the selection; whole-canvas analysis must traverse all relevant regions.

The bounds are `[x, y, x+width, y+height]`; x increases rightward and y downward. Group membership requires full containment. For nearest-neighbor questions, use rectangle gaps (zero for overlapping rectangles) and retain direction, rather than sorting JSON array order or using centers alone. An unconnected nearby note remains an unassigned contextual clue unless its text or another stored relation establishes its subject. Copy cards use their own rectangles and links.

`get_context` has section/group/item scopes and supports collection-level pagination (`collection`, `offset`, `limit`, `compact`). It defaults to 200 rows per collection; follow each collection's `next_offset` with the same `source_id` and scope until exhausted. `compact=true` omits raw JSON, descriptions, and revision. There are no region or nearest-neighbor parameters; use local extraction when its scopes cannot express the task. A section JSON by itself provides card content but no surrounding layout. A `.canvas` without its referenced section files provides layout but incomplete bookmark content. Neither case requires inventing missing relationships or changing the package.

- Chain labels such as `A-1 → A-1-1` suggest derivation. A child chain may retain most content or only a subset. A/B families describe creation clues; they do not prove ongoing synchronization with permanent trees or a persistent relationship. Check descriptions, titles, URLs and actual items.
- Groups have no explicit `children` list. Nesting comes from full containment using `x/y/width/height`. Groups contain canvas nodes; bookmarks inherit group context through sections and need not have individual canvas nodes.
- Edges default from `fromNode` to `toNode`, with `fromEnd:none` and `toEnd:arrow`. Read returned `direction` and original endpoints: `forward`, `reverse`, `both`, `none`. Interpret labels when present; an unlabeled connection does not establish dependency, competition or recommendation.
- Folders, groups, chain labels, tags, notes and descriptions are different classification clues. Preserve clear user categories; disclose conflicts and distinguish inference from stored facts. Analysis alone does not require reorganizing the package.

### Repeated and related bookmarks across cards

The same bookmark appearing in different cards is spatial context even when those cards are distant or unconnected. Search for its URL within the requested source, follow pagination, then check exact returned `url` equality: public search is substring matching. Retain each `source_id + section_id + item_id`, folder path, sibling order, notes and tags. Use `get_context` to connect each appearance to its card rectangle, groups, neighbors and edges. An item's `position` is tree order, not a canvas coordinate; bookmarks obtain canvas position through their cards.

`shown_in_anchors` identifies additional copy cards displaying the same main-tree item. Include each copy's own layout and description when relevant without inventing extra bookmark instances. An exact URL match establishes a shared link, not why it was placed there. For related topics or similar bookmarks, compare titles, folders, tags and notes and label the inferred relationship; SQLite lookup does not itself establish semantic similarity. Preserve distinct appearances and their contexts when deduplicating URLs for counts.

## Querying and counting

`source_id` is the logical canvas namespace. Locate items with `source_id + section_id + item_id`. One URL in different sections, paths or items still represents multiple bookmark instances. Report bookmark counts, unique URLs and company counts separately.

A permanent copy B queries the main tree A while keeping B's own description and position. Per-card `bookmark_count` values may reference the same tree and cannot simply be summed as unique bookmarks. When citing copy context, also retain the main-tree origin.

With both `section` and `group_id`, intersect actual cards before resolving their shared main trees. If only B belongs to the group, A plus that group does not match; B plus the group returns its shared bookmarks.

`search_bookmarks` matches literal substrings in selected item titles, URLs, notes, tag text and folder paths, with section/group/folder/tag filters. Separate source-wide `canvas_matches` report text cards, group labels and edge labels, outside item totals and pagination. Read `descriptionMd` and full layout through `get_context`. Short terms can produce incidental matches: `Exa` can match `examples` in a URL. Inspect matched fields and context.

`plan_research` turns one question into a bounded local scope: it splits the question into literal terms (a URL inside the question is returned separately in `question_urls` and removed from the terms), weights each term by its length over the number of cards it matches, and ranks cards by that weight scaled by the card's own density (hits ÷ bookmarks), so a specific name outranks a common word and a 1,053-bookmark tree cannot win on size alone. It returns each card's `score`, `density`, `file_path` and matched terms, plus that card's matching bookmarks deduplicated by URL and ordered by the most specific term each URL's own rows matched; `term_cards` counts the canonical trees each term points at (one tree means the question names it). It keeps one card per canonical tree, so a copy anchor cannot fill two of the three card slots, and reports `source_instances` separately from the selected scope's `instances`. A documentation or repository bookmark only makes the route a lookup when the question names it. It reads nothing from the web and never widens the scope: no cards with no question URL means the package has nothing on those terms and the route is `null`; the returned `terms` say what was searched. Its `task_shape` and `route` reuse the `research_route` vocabulary as a suggestion (depth follows the saved `research.depth`); confirm the route there before running it.

The `tags` filter matches text only; returned `tags[].color` retains color. To count a color/text combination, paginate all candidates and match both fields on the same tag object. A filtered first page is not the total.

`section` can match an ID, slot, label or file path. Repeated labels can select multiple cards; use a section ID for a unique card. Without `item_id`, `get_context` returns section headers, nodes, groups and edges; empty `items` does not mean an empty tree. The empty `items` page carries a `scope_note` in `pagination.items` naming the parameter it needs; read a card's bookmarks with `search_bookmarks(section:…)` or `plan_research`. Its counts cover returned sections, not an item's subtree. Find folders with `search_bookmarks(item_types:["folder"])`, then pass `folder_id` and the desired item types to read the subtree. Paginate complete listings and distinguish `synthetic:true` roots from user folders. Use item context only for additional ancestor metadata or layout.

Standard targeted tree read (replace IDs with values returned by the current source):

```json
{
  "tool": "get_context",
  "arguments": {
    "source_id": "<current source ID>",
    "section": "<section ID>",
    "item_id": "<target item ID>",
    "collection": "items",
    "compact": true,
    "limit": 1
  }
}
```

The selected item result includes its `ancestors`; use this for the exact folder path without loading the card's full tree. To inspect a selected folder's subtree, call `search_bookmarks` with `folder_id`, `item_types:["folder","bookmark"]`, and a bounded `limit`; continue at each returned `next_offset` until `null`. The page includes the selected folder and descendants, while `total` describes the full scoped result. Do not treat a page as complete when `next_offset` is non-null.

```json
{
  "tool": "search_bookmarks",
  "arguments": {
    "source_id": "<current source ID>",
    "section": "<section ID>",
    "folder_id": "<target folder ID>",
    "item_types": ["folder", "bookmark"],
    "compact": true,
    "limit": 50,
    "offset": 0
  }
}
```

Derived FTS5 tables exist, but the public query does not use BM25 ranking, embeddings, webpage-body search or arbitrary SQL. Retaining an unknown field does not provide a filter or an interpretation rule for it.

## Temporal context

Use the available time evidence alongside spatial context when explaining a card's history or changes:

- Read explicit date fields and dates in card titles, descriptions, notes or filenames under their documented meaning. Retain source, timezone and precision; unknown timezone stays unknown. Raw fields remain available through context/search or the original JSON, without implying a dedicated time filter.
- The package protocol defines bookmark/folder IDs such as `syncId_YYYYMMDD_hash_<token7>` and `tempId_YYYYMMDD_hash_<token7>`. Their valid date segment is an identity-generation clue. Import, copying or migration may create new IDs for older content. A parent folder's date does not date its descendants. Do not decode arbitrary IDs, chain counters or digit strings as timestamps without a generation rule, or infer exact time from a day-only ID.
- The index surfaces that evidence per item as `added_at` with `added_at_source`, `added_at_precision` and `added_at_confidence`. `dateAdded` (the bookmark's own add time, millisecond, high confidence) wins over an ID date segment (generation clue, day, low confidence); edges use the millisecond at the end of their id (medium confidence), and their id's middle number is a counter, not a time. A missing signal stays `null`: nothing falls back to retrieval time or file modification time. Items from `search_bookmarks` and `get_context` carry these fields, and `plan_research` breaks an equal-score, equal-hit tie by each card's newest `added_at`.
- For a Git-backed package, use scoped `git log`, `git show` and content diffs as described in [learning retrospectives](github-and-sync.md#review-learning-stages). Compare the corresponding layouts and bookmark appearances as well as text. A commit dates the recorded change; a file's first appearance in available history is only its first observed version.
- Keep identity generation, recorded creation/modification, export/import, commit, collection and reading dates distinct. Use notes or other explicit evidence for collecting/learning claims. Without Git, dated content and available snapshots support only a bounded account; missing dates remain missing.

## Synchronization and retention

`sync_package` and the CLI accept directories, ZIPs and single-card JSON, saving original snapshots, file hashes and parsed results. Snapshot queries survive removal of the original export. Live directories are checked while MCP runs and before queries by default. Invalid JSON, unsafe paths or cyclic references fail and roll back. Unavailable live sources produce query errors by default; use `refresh=false` only when the user permits the old index. See [source lifecycle](source-lifecycle.md).

In `completeness:partial`, missing files are retained and listed by sync. Deleted items inside a supplied complete section are still removed. Use `complete` only for an explicitly complete mirror to remove records for missing files. Single-card imports are always partial. Inspect `retained_missing_files`; a partial input is not necessarily all source data.

When a section keeps its ID but changes filename, update the file map and remove the replaced path's hash. Renaming it back triggers parsing again. If a partial export omits canvas or copy files, retain previously resolved stable relationships and warn that references come from older files. Once supplied, a file's actual written paths govern resolution. Original `.canvas.file` and `inheritFrom` must still agree with real paths; the index does not repair the package.

Source identity is independent of path. Reuse `source_id` for a new export of the same canvas; registered paths become aliases. Managed snapshots contain merged necessary source files and resolved relationships. Find them through `source_history` and restore into a new index without collecting every past partial export. Research inventories stay frozen; research/Wiki review flags signal changed input.

JSON/.canvas remains the source of truth; SQLite stores derived state and registrations. Background checks process local files only. Databases, source snapshots, reports, aliases and inventories stay outside the synced package. A reading task does not trigger cleanup or generation.

## Provenance and maintenance

Reading-rule version: `2026-11-01`. The protocol source is the public Bookmark Canvas [AGENTS templates](https://github.com/Browser-bookmark-hub/Bookmark-Canvas/tree/main/Bookmark-Canvas-main/history_html/transfer_AI_sync/AGENTS_template). These rules extract analysis semantics without binding the plugin to a particular user's package or paths. Check upstream protocol and parser changes during maintenance; queries do not require visiting that link.

| Protocol guide material | Where it is used |
| --- | --- |
| A1–A8, A9 text semantics, R1/R6/R7 reading semantics | File, field, identity and relationship rules above |
| S8 and S7 analysis clues | Relationship interpretation, temporary aliases and source location |
| S6 web research | [Research and provider access](research-workflow.md) |
| P1 plugin boundary | Read-only scope, plugin data outside the package, resync after external edits |
| Relevant S1/P2 storage and partial-export semantics, P1 persistence rules | Synchronization boundaries and version retention above |

Tested `schemaVersion` values are 3 for permanent main trees, 2 for permanent copy anchors, and 2 for temporary sections. The importer validates actual fields; it is not a validator for every future schema. Changed semantics require checking the protocol and parser. Documentation changes alone do not add runtime capabilities.

Section creation/modification, ID generation, tag/note writes, layout changes and pre-import validation belong to a future generation Skill. It could reuse these reading rules and add write rules and validators, but the package's exported guide remains the write protocol. This plugin does not provide those generation capabilities.
