---
name: bookmark-research
description: "Research ordinary bookmark URLs or Bookmark Canvas directories, ZIPs and cards: locate bookmarks, check linked pages, compare sources or deliver a scoped research report. Preserves original inputs; does not generate or write back canvas packages."
---

# Bookmark Research

[中文阅读版](references/zh/skill-guide.md)

Use the user's links, package paths or registered sources. Answer in the requested language, otherwise the task's language (English if neither selects one). Pass that language to delegates and saved briefs; preserve original quotations and identifiers. Load references in one language only. Keep source packages unchanged and local notes out of public queries.

## Choose the work the user needs

| Request | Workflow |
| --- | --- |
| Find bookmarks, count items, inspect notes or canvas relationships | Query local metadata. |
| Check a known link or a few facts | `quick`: read the URL and answer with evidence. |
| Compare bookmarked tools or investigate an open question | `agentic`: the current host model searches/reads, assesses evidence and follows remaining gaps. |
| Investigate a complete list/package, retain progress or deliver a verifiable report | `deep`: the same host-led investigation with frozen inputs, evidence records, independent review and coverage checks. |

Honor the task's explicit depth, then saved preferences; the table guides `auto`. Depth and scope are separate: a topic comparison covers that topic, while a whole-package request retains all original URLs. Briefly state the scope when useful, then perform the work. A capabilities question alone does not start an investigation. Host-led search and deep research need no professional research API key.

## Tools and the quick path

Use the actual MCP tool names exposed by the host. If a required tool or parameter is missing from an older catalog, use the bundled CLI: `<plugin-root>/src/cli.py`, where the plugin root is `../..` from this Skill's directory. Use its absolute path. Other CLI operations and their names are in the [CLI reference](references/cli.md).

For a known public URL, call `fetch_web({urls:[url]})`. The equivalent fallback command is:

```sh
python3 <plugin-root>/src/cli.py fetch-web 'https://example.com/page' --timeout 20
```

`--timeout` limits individual provider HTTP requests, not the entire waterfall. Ordinary URL checks need no package import, research session, provider probe or additional reference. Public GitHub README pages use this same path.

`fetch_web.pages` contains one selected extract per URL; each attempt retains status and archive paths. Read the relevant text and cite the original URL. Complete provider envelopes remain in the archive; `raw:true` (CLI `--raw`) returns them when needed. Check archive errors and completeness markers; a provider extract is not proof of a complete or live origin page.

## Search, assess, follow up

The current host model owns the first pass. Read known URLs directly; use `search_web` to discover sources, then read the relevant pages. Ordinary comparisons can answer directly. Create persistent research records when the user needs retained progress or a report.

Omitting providers uses the saved retrieval fallback. Defaults: reading tries Exa, then Parallel + Jina concurrently for unresolved URLs; search starts with Exa + Parallel, then Tavily + keyed Jina for queries without usable results. Explicit providers restrict the call. Preserve successful siblings and inspect unresolved items, skipped providers and remaining budget.

A nonempty response does not settle the question. Check page identity, relevant passages, date/version and whether the quotation supports the conclusion. For irrelevant, stale or insufficient text, follow up on that URL/question only: choose another permitted provider, a linked official document, an original-site API/Markdown view, or an available authorized browser. In a research session, record uncertain/rejected source reviews and use a new operation ID for justified new retrieval; do not replay a known inadequate result expecting new text. An alternative page can support an answer but cannot count as reading the original URL.

Read [provider access](references/research-workflow.md) when choosing or diagnosing retrieval services; [GitHub boundaries](references/github-and-sync.md) for code, issues, releases, private access or Git synchronization; [research methods](references/research-methods.md) for systematic comparisons, conflicts or benchmarks. A small fact check does not need these full procedures.

## Canvas context

For Canvas input, first read [package semantics](references/package-semantics.md); reuse it within the session. Consult the original package guide only for new/conflicting fields or a requested convention check.

- Find registered sources with `index_status`. Import a new export through `sync_package` in `snapshot` mode; use `live` for a persistent directory identified by the user. Only a confirmed full mirror uses `completeness:complete`; partial exports and single cards use `partial`. Reuse the actual source ID for moved exports of the same canvas. [Source lifecycle](references/source-lifecycle.md) covers migration, recovery and monitoring.
- Batch search targets in `search_bookmarks`; follow each target's pagination. Matching is literal across metadata, so verify short-name hits against titles/domains. Preserve IDs, URLs and grouping context. Local metadata does not prove online capabilities.
- Use `get_context` with `item_id` for a bookmark and its ancestors, and for card descriptions, groups and directed edges. A section overview does not enumerate all items. Obtain a folder ID from ancestors before restricting a search.
- Inspect `source.state`: disclose pending updates; use `refresh:false` on an unavailable/error source only when the user accepts the saved index. Historical snapshots use `source_history`. Research inventories and Wiki pages retain versions; freshness warnings request review, not an automatic reinvestigation.

## Deep research and collaboration

Read the [deep workflow](references/deep-research.md) when this mode is needed. Start with explicit questions and the complete requested input:

- Ordinary bookmarks: `research_start` with `urls:[...]`; duplicate positions remain in the frozen inventory. No Canvas registration is needed.
- Canvas packages: use indexed `source_ids`; whole-package scope is the default. Only an explicit subset uses `scope_mode:subset` and selected inventory IDs or bookmark references.
- A public question without an original bookmark list may omit both inputs. URLs mentioned only in the brief are not tracked input.

Follow every `research_inventory.next_offset`. Keep original `u-...` inventory IDs separate from saved `sN` evidence IDs. Read original text, review it, record quoted claims and each inventory judgment. Batch ready `research_record.entries` (up to 50) with a stable `batch_id`; use returned IDs in dependent batches. Check coverage differences and continue until complete or budget-limited. Failure notes, bulk exclusions, search snippets and external report citations cannot establish full original-source review.

The parent owns synthesis. When delegation is available and permitted, give independent readers/verifiers the scope, questions, output language, relevant instructions and actual MCP/CLI access. Read [host workflows](references/host-workflows.md) for Codex, Claude, Pi or DSH execution details; do not assume child context inheritance. Without delegation, conduct and disclose same-agent review.

Professional research is optional support for a concrete subproblem or an explicit user selection. Read [research services](references/research-services.md) before using it. Preserve explicit provider choices and known run IDs; do not replace running or unknown-outcome jobs. `research_route` recommends support but launches no work. A saved API preference does not displace the host's first pass.

## Delivery and settings

Answer quick tasks directly. Before finishing a report, review the actual short answer against evidence and counterevidence; condensing supported claims must preserve their conditions and limits. Use `research_finish` for reports and source/coverage artifacts: distinguish accounted inputs, usable text, substantive review and answered questions. Use `completed` only when coverage, supported answers and conflict checks pass; otherwise retain an `incomplete` report and gaps. Resume an incomplete archive with a `resume` record. Saved state is not a background agent.

Create Wiki pages when the user asks to retain conclusions in a Wiki or knowledge base; read [Wiki and evaluation](references/wiki-and-evaluation.md) for publication, lint and actual labeled quality comparisons. Do not infer semantic correctness from quote/hash checks.

Use `get_settings` for configuration questions and `update_settings` for lasting preferences; temporary choices use per-call options. [Settings and archives](references/settings-and-archive.md) describes storage. All archives, indexes and authored outputs stay outside the original package.
