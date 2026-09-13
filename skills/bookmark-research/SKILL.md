---
name: bookmark-research
description: "Query Bookmark Canvas directories, ZIPs or single cards; preserve snapshots or sync live directories, research the complete requested scope with evidence and Wiki delivery. Does not generate or write back to canvas packages."
---

# Bookmark Research

[中文阅读版](references/zh/skill-guide.md)

Turn the user's question into repeatable local queries and web research as needed, delivering an answer or a research report. Inputs follow the Bookmark Canvas JSON protocol. Use package paths, registered sources and targets supplied by the current user; the plugin contains no personal bookmark collection. Decide whether the task needs local metadata, page content, or both.

## Output language

Use the user's explicitly requested output language; otherwise follow their actual task and conversation. If neither selects a language, use English. Apply this to answers, progress, authored report text, and Wiki titles/sections. Bilingual starter prompts and the language of these instructions do not select the answer language. Installer `--lang` affects onboarding only.

Pass the resolved output language to delegated agents, workflow `output_language`, and professional research briefs. Record explicit language requirements in the research brief so a later session can recover them. Preserve original quotations, URLs, identifiers, code and technical field names; put translations outside quotations. Language choice never narrows source coverage or restricts retrieval to sources in one language.

This is the single execution Skill. The linked Chinese copies are for reading and review; load the relevant reference in one language, without loading both copies.

## Reading a package

For package analysis, first read the bundled [package semantics](references/package-semantics.md) for fields, metadata locations, copies and relationships. Reuse that reference within the same session if its rules have not changed. Routine analysis of a supported format does not require rereading the package's entire `AGENTS.md`.

Consult relevant parts of the original package guide and actual JSON when the format is new, fields are unexplained, meanings conflict, or the user asks to check special conventions. Follow applicable directory instructions already loaded by the host. This Skill has no canvas generation or write-back workflow; a research report is not an importable JSON/.canvas package.

## Tool entry points

The plugin registers one `bookmark-research` MCP server for local queries, search/page reading, `research_*` records and services, `wiki_*`, evaluation and settings. Hosts may prefix tool names; use those actually exposed in the current session.

Check availability per operation. If the required MCP tool is missing, use the bundled CLI, including when the host exposes only part of an older tool catalog. The plugin root is `../..` from this `SKILL.md` directory; the entry point is `<plugin-root>/src/cli.py`. Use its actual absolute path rather than assuming a working directory. See the [CLI reference](references/cli.md). Reuse this implementation instead of writing a new query script or rebuilding the database for each question. If the CLI command is also absent, report that version's missing capability.

## Select a workflow from the request

Users state the question, scope and deliverable naturally; no fixed trigger phrase is required. Use local queries for bookmark location, counts or canvas structure. For web tasks, honor the explicit depth requested for this task, then saved defaults. With `research.depth:auto`, choose by intent:

| Example intent | Mode | Action |
| --- | --- | --- |
| “Quickly check this fact in my bookmark.” | `quick` | Read the known URL, or search for a source and read key pages, then answer. |
| “Compare these bookmarked tools and establish their differences.” | `agentic` | Use canvas context to break down questions, search, read, analyze and follow evidence gaps. |
| “Research the whole package” or “Investigate this thoroughly and deliver a verifiable report.” | `deep` | Create research records, preserve the complete requested scope, investigate, independently review evidence and check coverage; write a Wiki when requested. |

Choose depth and scope separately. Keep an explicitly selected card or topic; for a whole-package request, apply the full-scope rules below. Briefly state the selected mode and scope, then actually call the tools. A `research_route` suggestion does not start research. Native host investigation needs no professional research API credential. If the user explicitly selects a professional service, check its availability and do not silently switch execution routes. A question about capabilities or a plan alone does not start a package investigation.

## Local questions

1. Use `index_status` to find registered `source_id` values. `sync_package` accepts directories, ZIPs and single-card JSON. Use `mode:"snapshot"` for manual exports and `mode:"live"` for a persistent directory identified by the user. Use `completeness:"complete"` only for a confirmed full mirror; use `partial` for partial exports and single cards. Reuse the existing `source_id` for a new export path of the same canvas; do not merge sources by similar titles or URLs. Read [source lifecycle](references/source-lifecycle.md) for intake, migration or recovery.
2. Combine multiple targets in one `search_bookmarks.targets` request. Apply `section`, `group_id`, `folder_id` or `tags` only as required by the user's scope. Each target has its own total and pagination. Snapshots work offline; live queries check for changes first. Read the returned `source.state`: disclose pending synchronization, and use `refresh=false` on error/unavailable only when the user allows the old index. Find historical snapshots through `source_history`; `refresh=false` does not select a past version.
3. Use `get_context` for card descriptions, group membership and directed relationships; bookmark text search does not cover these fields. Supply `item_id` to retrieve an item and its `ancestors`. A section/group alone returns a structural overview, not every bookmark and folder. Obtain a `folder_id` from bookmark ancestors before restricting a query to that folder.

Search uses literal metadata matching plus structural filters, not company entity recognition or semantic retrieval. Query Chinese aliases, English names and domains separately when useful. “536 bookmarks in a company folder” does not mean “536 companies.” Zero local matches do not establish that something does not exist online. When grouping by company, retain bookmark IDs, URLs and context and explain the grouping basis.

JSON/.canvas is the source of truth. SQLite holds a derived index and source registrations; source snapshots, notes, evidence and the database live outside the synced package. While MCP runs, only local indexes of live sources update automatically. Research inventories, text and Wiki pages retain versions. `research_status.source_freshness` or Wiki `needs_review` indicates changed input requiring review, not a completed reinvestigation.

## Web questions

- **Quick checking:** use `fetch_web` for a known URL. When discovering sources, use one `search_web` round and read key pages. “Non-reasoning” describes a model's search approach; a known URL does not establish its reasoning capability. A provider is not guaranteed to visit the origin live.
- **Agentic search:** the current host model leads the first pass: use the question and bookmark context to plan, search or read relevant sources, assess the evidence, then target remaining gaps. A nonempty search response is not an answered question. Ordinary comparisons can use `search_web` / `fetch_web` and answer directly; persistent research records are for tasks needing retained progress or a report. Retrieval fallback supports this reasoning loop. Omit `providers` to use it; inspect `unresolved_queries`, skipped providers and remaining budget, preserving successful results.
- **Deep research:** extend that host-led loop with explicit questions, sustained investigation, independent verification, coverage checks and a report. Read the [deep research workflow](references/deep-research.md) and create or resume its records. The parent owns the plan and synthesis; delegate independent topics or verification through available, permitted host capabilities. Without subagents, continue the host investigation and disclose a same-agent review. Missing professional API credentials do not disable this method.

For collaboration, read [host workflows](references/host-workflows.md). Codex native subagents, Claude ordinary subagents or enabled teams, Pi subagent extensions, and configured DSH subagents/workflows support the same research method. The bundled grouped workflows are useful for a frozen package inventory. Give children the questions, scope, relevant Skill instructions and actual MCP or CLI access; do not assume they inherit the parent's loaded context. Use current capabilities and host delegation rules. `research_route` suggests execution support and a host reasoning process; it launches nothing.

External research is optional support after the host assesses a concrete subquestion, or when the user explicitly selects it. Routing recognizes observed Exa `agent_run`, complete Parallel Task MCP tools and enabled API clients; availability or a saved API preference does not displace the host's first pass. Follow [research services](references/research-services.md) to prepare, start once, track the run and import its report for source verification. On confirmed route failure, accumulate `failed_routes` and continue in the same research session; a question gap alone is not a failed route. Preserve explicit provider choices. Running, unknown or cancelled jobs do not trigger replacements. Stop when no eligible route or budget remains and retain the gaps.

For product comparisons, fact checking or leaderboard analysis, read [research methods](references/research-methods.md) and give readers and independent verifiers the selected method and questions. Use an existing SDK only when a real programmatic task lacks a host. This plugin does not implement a scheduler, agent pool or background worker.

Before web research, read [research and provider access](references/research-workflow.md), then use actual available tools within the user's scope. Search starts with Exa + Parallel, then Tavily + keyed Jina for unresolved queries; reading tries Exa, then Parallel + Jina Reader for unresolved URLs. `search.providers`, `search.fallback_providers` and `fetch.providers` are separate choices. Missing Jina Search credentials skip that fallback; Jina Reader supports anonymous access. Local-only queries need no web reference or remote probe.

For GitHub repositories, issues, code or Git synchronization, read [GitHub and synchronization boundaries](references/github-and-sync.md). No GitHub MCP is bundled. Prefer suitable GitHub tools actually available in the host; `fetch_web` can also read public pages.

## Full scope for package research

A request to research a package covers all its original URLs by default, retaining the folder, card and relationship context of every duplicate bookmark instance. Narrow scope only when the user selects a topic, card or source subset. Pagination, budget, duplicate URLs and subagent count never justify silently reducing scope.

1. After syncing, call `research_start` with actual indexed `source_ids`. Default `scope_mode:"whole"` freezes the complete inventory. `bookmark_refs` can mark points of interest without reducing that scope. Use explicit `scope_mode:"subset"` only for a required subset and report selected and omitted items.
2. Follow `research_inventory.next_offset` through the entire inventory. Distinguish package `source_id`, original-URL `u-...` inventory IDs and saved-text `sN` evidence IDs. Preserve every inventory ID in grouping; batching and concurrency change execution only.
3. Fetch original URL text, or import text actually obtained by the host. Read it through `research_source`, then record `source_review`, cited claims and `inventory_review`. Search snippets, file import alone, successful child turns and external report citation lists do not substitute for reviewing original pages.
4. Independently check claims and quotations, then use `research_coverage` to obtain missing/unread/unreviewed differences and continue. Omit `research_fetch.provider` to enable fallback among session providers within budget; inspect `attempts`, `unresolved_urls` and `remaining_providers` before recording a URL as `blocked`. Distinguish temporary retrieval failure, login barriers and insufficient content; `blocked` is an unresolved evidence gap, not proof that the URL is inaccessible. Record justified out-of-scope/non-content items as `excluded` with reasons. Bulk exclusions or merely recording failures cannot establish whole-package completion.

The initial reading budget has a lower bound based on URL count; inspect `initial_fetch_plan`. Each fetch may contain up to 8 URLs. Preserve explicit budgets and the full inventory if capacity is insufficient, reporting the gap. Plugin budgets cannot cover host or external-service consumption that the plugin cannot observe.

Batch ready evidence records with `research_record.entries` (up to 50 per call) and a stable, group-specific `batch_id`. Keep every source and inventory judgment; batching reduces calls without reducing coverage. Use returned claim IDs in subsequent batches. See [recording evidence](references/deep-research.md#record-types) for atomic writes and retry rules.

## User settings

Use `get_settings` when the user asks about configuration or storage. For a lasting preference, use `update_settings` to change only relevant fields. Apply temporary requirements as per-call overrides. See [settings and archives](references/settings-and-archive.md) for configuration and archive formats. These options use the shared implementation, not a freshly written script on each turn.

## Deliverables and retention

Answer simple queries directly; retain citations and actual scope in research reports. `fetch_web` archives actual responses, recognized text and source records by default; inspect failure, missing-content and completeness markers. `search_web` does not read result URLs automatically. A successful fetch and a matching quotation do not prove the claim: check page identity and citation meaning.

Use `research_finish` for the report, source list and coverage details. Report accounted-for inputs, usable text, substantive review and question completion separately. Use `completed` only when full source review, answers and conflict checks satisfy the gate. Important gaps, active/unknown external runs or insufficient budget require `incomplete`. Records live in the data directory's `research/`. A `research_status` overview previews at most 20 entries; paginate full records. Record `resume` before continuing an incomplete archive. Saved records do not imply a running background agent.

When knowledge synthesis is requested, use `wiki_write` to compile conclusions supported by accepted sources into topic/entity pages with links, revisions and review notes. Use `wiki_lint` for sources and links and `wiki_search` for authored text. The Wiki is outside the original package and has no automatic vectorization or webpage monitoring. For quality comparisons, prepare actual runs and independent judgment labels before calling `evaluate_research`; missing semantic scores, cost and latency remain unknown. See [Wiki and evaluation](references/wiki-and-evaluation.md).
