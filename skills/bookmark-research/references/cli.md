# CLI and invocation examples

**English** · [中文](zh/cli.md)

Commands use Python 3.9+ and the standard library; stdout is JSON. Replace `<root>` with the actual absolute plugin path. Package paths, source/company names, node IDs and example.com URLs are placeholders for user input or actual query results; the plugin does not preload them. Global `--db` and `--config` options precede the subcommand. MCP provides the same core operations. Use the CLI in Pi or any host missing the required MCP tool.

| MCP | CLI command |
| --- | --- |
| `index_status` / `sync_package` | `status` / `sync` |
| `search_bookmarks` / `get_context` | `search` / `context` |
| `fetch_web` / `search_web` | `fetch-web` / `search-web` |
| `research_start` / `research_fetch` | `research start` / `research fetch` |

```sh
python3 <root>/src/cli.py doctor
python3 <root>/src/cli.py sync /absolute/path/to/package --source-id my-canvas
python3 <root>/src/cli.py status
python3 <root>/src/cli.py search my-canvas --target 'Example Company A' --target 'Example Company B' --section A --limit 5
python3 <root>/src/cli.py search my-canvas --group card-group-example --limit 50
python3 <root>/src/cli.py context my-canvas --group card-group-example
python3 <root>/src/cli.py context my-canvas --item actual-bookmark-id
```

`sync` accepts directories, ZIPs or single-card JSON. `--mode snapshot` saves a snapshot; `--mode live` connects a persistent directory. `--completeness partial` retains omitted files; use `complete` only for a confirmed full mirror. New ordinary exports default to snapshot, Git directories to live; existing sources retain their mode. Reuse `--source-id` for a new export of the same canvas. See [source lifecycle](source-lifecycle.md).

`history <source-id>` lists versions and recoverable snapshot paths. MCP checks live sources while running. In terminal-only use, `watch` provides foreground monitoring and JSON lines for status changes.

`search` matches titles, URLs, notes, tags and folder paths. Multiple `--tag` values must all match; multiple `--target` values have separate totals and return their union. It provides no arbitrary SQL execution. Default refresh checks live-file hashes; snapshots do not read original download locations. `--no-refresh` uses the current synchronized index, not a selected past version. Returned `source.state` distinguishes snapshots, current/pending and failed sources. Legacy `stored_snapshot_only` still means only that proactive checking was skipped.

Without `--item`, `context` returns section headers, canvas nodes and relationships. `items:[]` does not mean an empty section. Find one bookmark with `search`, retrieve its `ancestors` through `context --item <bookmark-id>`, then query `search --folder <folder-id>`. A repeated label in `--section` may select multiple sections; use a unique ID for one card.

Database precedence: `--db` → `BOOKMARK_RESEARCH_DATA_DIR/index.sqlite3` → `${XDG_DATA_HOME:-~/.local/share}/bookmark-research/index.sqlite3`. Point clients and CLI at the same path to share an index. Keep databases outside original synced packages and plugin code.

```sh
python3 <root>/src/cli.py providers
python3 <root>/src/cli.py providers --probe
python3 <root>/src/cli.py search-web --target 'Example Company A official pricing' --target 'Example Company B official pricing' --limit 5
python3 <root>/src/cli.py fetch-web https://example.com/company-a https://example.com/company-b
python3 <root>/src/cli.py fetch-web https://example.com/company-a --no-archive --max-characters 30000
python3 <root>/src/cli.py config show
python3 <root>/src/cli.py config set --search-provider exa --archive true
python3 <root>/src/cli.py config set --archive-dir /absolute/path/to/knowledge
```

`config show` / `config set` correspond to MCP `get_settings` / `update_settings`. `config set --input /path/to/changes.json` (or `-` for stdin) merges partial settings. CLI flags override matching fields from that invocation's JSON. `fetch-web` archives by default; `--archive` / `--no-archive` affects one call. Set future defaults with `config set --archive true|false`. See [settings and archives](settings-and-archive.md).

`fetch-web` returns one selected text per URL in `pages`, with all attempt statuses and archive paths. `--raw` returns the full provider envelopes. Its `--timeout` applies per provider HTTP request; discovery and fallback can take longer overall. `research fetch` accepts only its documented MCP JSON fields and does not accept `timeout`.

`providers` describes configuration only; `--probe` checks online handshake and tool discovery. Anonymous Exa/Parallel access depends on current provider limits. Set `EXA_API_KEY` / `PARALLEL_API_KEY` before starting the process when needed. Optional `--provider tavily` uses Bearer with `TAVILY_API_KEY` or an explicit keyless header without it. A listed tool does not prove execution authorization. Never place keys in manifests or reports.

Use `search-web --input /path/to/query.json` for stable target labels and repeated queries:

```json
{
  "targets": [
    {"target": "Example Company A", "query": "Example Company A official API pricing"},
    {"target": "Example Company A", "query": "Example Company A official product documentation"},
    {"target": "Example Company B", "query": "Example Company B official API pricing"}
  ],
  "providers": ["exa", "parallel"],
  "limit_per_target": 5
}
```

Limits are 12 target/query pairs and 20 returned URLs per target. `fetch-web` accepts up to 8 URLs per call. Providers run concurrently; each provider's requests run sequentially and reuse its tool catalog within the process.

To merge **actual results** from other host MCPs, normalize them to this shape and call `merge-results /path/to/batches.json`. Do not invent URLs, ranks or provider names from snippets.

```json
{
  "targets": ["Example Company A"],
  "limit_per_target": 5,
  "batches": [{
    "provider": "tavily",
    "target": "Example Company A",
    "query": "Example Company A official API pricing",
    "status": "ok",
    "results": [{"url": "https://example.com/company-a", "title": "Example Company A", "snippet": "Replace with the actual provider snippet.", "rank": 1}]
  }]
}
```

Failed batches use `status:"error"`, `results:[]` and an `error` description. A successful empty result uses `status:"ok"` with `results:[]`. Returned `coverage`, `uncovered_targets` and `errors` distinguish incomplete coverage from call failures.

## Deep research commands

`research record <research-id> --input <entry.json>` can use `{"kind":"resume","text":"Continue investigating recorded gaps"}` to resume an exported incomplete report while retaining its previous report and budget.

For batches, the same command accepts an input object `{"batch_id":"group-1-review-v1","entries":[...]}` with 1–50 entries. The existing bare single-entry JSON remains supported. Use stable batch IDs for safe retries; see [recording evidence](deep-research.md#record-types) for ordering, atomicity and compact results.

The current model makes decisions and synthesizes; the CLI stores state and executes individual operations. Read [deep research](deep-research.md) for briefs, budgets, citations and all record types.

```sh
python3 <root>/src/cli.py research start --input /path/to/brief.json
python3 <root>/src/cli.py research status
python3 <root>/src/cli.py research status <research-id>
python3 <root>/src/cli.py research status <research-id> --section claims --offset 0 --limit 20
python3 <root>/src/cli.py research inventory <research-id> --offset 0 --limit 100
python3 <root>/src/cli.py research coverage <research-id> --filter unreviewed --offset 0 --limit 100
python3 <root>/src/cli.py research search <research-id> --input /path/to/search-step.json
python3 <root>/src/cli.py research fetch <research-id> --input /path/to/fetch-step.json
python3 <root>/src/cli.py research source <research-id> s1 --offset 0 --limit 12000
python3 <root>/src/cli.py research import-evidence <research-id> --input /path/to/actual-evidence.json
python3 <root>/src/cli.py research record <research-id> --input /path/to/entry.json
python3 <root>/src/cli.py research finish <research-id> --summary 'Verified conclusions' --status completed
```

`--input -` reads JSON from stdin. Start input matches `research_start`. Search/fetch JSON uses corresponding MCP fields but omits the positional `research_id`. Record JSON contains **only the entry object**, such as `{"kind":"gap","question_id":"q1","text":"First-party evidence is still missing"}`. Finish accepts repeated `--limitation`; use `--status incomplete` for unfinished research or `cancelled` for cancellation.

The default research directory is the same data-directory `research/` used by MCP. Put `--directory /absolute/path/to/research` after `research` and before its action to override it. Preserve this location across sessions and resume using actual status IDs and text. Network steps require `operation_id`; reusing an ID to read its result does not resubmit. `research start/status/source/record/finish` need neither an API key nor network access.

Start input uses `urls:[...]` for ordinary bookmarks or `source_ids` for registered Canvas packages; both freeze the whole original scope by default. Read inventory/coverage until `next_offset` is null. Repeat `--inventory-id` for a batch of original-URL IDs. Import-evidence JSON matches MCP without positional `research_id` and requires actual text and provenance. An external report does not increase original-page coverage.

## Host routing and professional services

```sh
python3 <root>/src/cli.py research route --host codex --task-shape batch_research --tool collaboration.spawn_agent
python3 <root>/src/cli.py research route --host claude_code --available-command /bookmark-research:bookmark-research
python3 <root>/src/cli.py research service describe
python3 <root>/src/cli.py research service prepare --input /path/to/service-brief.json
python3 <root>/src/cli.py research service start --input /path/to/service-request-with-operation-id.json
python3 <root>/src/cli.py research service status <external-id> --refresh
python3 <root>/src/cli.py research service result <external-id> --offset 0 --limit 12000
python3 <root>/src/cli.py research service attach --input /path/to/known-run.json
python3 <root>/src/cli.py research service import <external-id> --operation-id import-report
python3 <root>/src/cli.py research service cancel <external-id>
```

Repeat route `--tool`, `--available-command` and `--extension` for capabilities actually observed in the session; `--input` also accepts complete MCP input. Routing does not execute a workflow. Prepare/start/attach JSON includes `research_id`. See [professional services](research-services.md) for creation, status and cancellation semantics. Describe/prepare are offline; `--refresh` observes an existing remote run once. Starting another task after a timeout is not recovery.

## Wiki and evaluation

```sh
python3 <root>/src/cli.py wiki write <page-id> --input /path/to/page-and-change-note.json
python3 <root>/src/cli.py wiki get <page-id>
python3 <root>/src/cli.py wiki get <page-id> --revision 1
python3 <root>/src/cli.py wiki list --offset 0 --limit 20
python3 <root>/src/cli.py wiki search 'research execution' --limit 10
python3 <root>/src/cli.py wiki lint
python3 <root>/src/cli.py evaluate --input /path/to/suite-runs-judgments.json
```

Wiki write input is `{page,change_note,expected_revision?}`; `page_id` is positional. Updates require the current revision. Put Wiki `--directory` before its action; use `--research-directory` for a nondefault research location. Evaluate accepts `{suite,runs,judgments?}` and calculates supplied data without starting a model judge. See [Wiki and evaluation](wiki-and-evaluation.md) for formats and limits.
