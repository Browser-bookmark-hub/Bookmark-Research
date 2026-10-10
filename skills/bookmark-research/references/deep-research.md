# Deep research: saved evidence and reports

**English** · [中文](zh/deep-research.md)

Use for sustained investigations needing durable evidence, coverage or resumption, including complete original-URL reviews. Saving an ordinary answer needs only its supporting material and requested output. A scoped Wiki write does not expand into whole-library research. The host conducts the investigation; saved task state does not run a background agent.

## Start and scope

Create answerable questions, scope, language and retrieval budgets with `research_start`. For an existing task, follow [resume and delivery](#resume-and-delivery).

```json
{
  "brief": "Compare the supplied tools; write the report in English.",
  "scope": "Capabilities supported by the supplied pages",
  "questions": [{"id": "q1", "question": "Which capabilities fit the requested use?"}],
  "urls": ["https://example.com/one", "https://example.com/two"]
}
```

- Ordinary lists use `urls` (1–10,000 entries); Canvas inputs use registered `source_ids`. Choose one. URLs in the brief alone are not tracked input. Omit both only when the task has no original link collection.
- Default `scope_mode:"whole"` preserves every input and duplicate instance, including non-web entries. Canvas `bookmark_refs` mark interests without narrowing scope. An explicitly requested subset uses `scope_mode:"subset"` with `inventory_ids` or Canvas `bookmark_refs`; retain the omitted IDs.
- Package source IDs, original inventory IDs (`u-…`) and evidence snapshot IDs (`sN`) are distinct. `inventory.json` freezes URLs, instances and Canvas context from the last synchronized input; `context.json` holds summaries. Local notes and paths are not automatically uploaded.
- Read `research_inventory` to the end (`next_offset:null`) when building a full inventory. Inventory/coverage pages and ID filters hold at most 100 items; previews do not define scope. Oversized context uses returned artifact paths and JSON pointers.
- Use the returned `work_directory` for scratch files and report any output-placement fallback.

## Evidence cycle

1. Fetch known URLs with `research_fetch`; discover missing sources with `research_search`, mapping queries to existing `question_id` values. Honor provider restrictions and inspect unresolved attempts.
2. Fetch returns metadata. Read saved text through `research_source`, continuing pagination for relevant passages. Check page identity, date/version and applicability; reject login shells or unrelated pages. An extract may be partial. Save `source_review` before claims.
3. Record claims with exact saved quotations and actual evidence IDs. Quote/hash checks establish presence, not semantic support. Mark inferences with `inference:true`; preserve conditions and counterevidence in the final answer. Multiple providers returning one page are not independent sources.
4. For original input, record `inventory_review` against accepted text from the matching original URL. A replacement page or external report may answer a question without satisfying original-URL coverage. Record specific blocks or justified exclusions when necessary.
5. Record supported `answer` entries using that question's claim IDs. Check `research_coverage` when choosing follow-up work or finishing; fetch the relevant differences rather than rereading every unchanged record. Resolve conflicts or retain gaps.

Reuse text and complete ID sets already read while their state remains valid. Recheck original evidence when identity, meaning, versions or contradictions remain uncertain; review the synthesized answer before delivery. Independent review is optional when warranted and authorized—see [host workflows](host-workflows.md) only if selecting delegation.

For rejected/uncertain evidence, retract affected claims and target the failed URL/question using another allowed route within budget. A new fetch needs a new operation ID; replaying an old ID returns old text. Reviews do not trigger retrieval. Never edit stored evidence to fit a claim.

Host-tool text can be saved with `research_import_evidence`: `research_id, operation_id, question_id, url, text, provenance`, optionally `title, inventory_ids`. Provenance kind is `page`, `archived_page`, `local_document` or `external_report`; retain actual provider, acquisition time and location. Imports start unreviewed. A snippet is not page text; an external report is secondary evidence. Read [research services](research-services.md) only for a selected provider service.

## Record types

`research_record` accepts `{research_id, entry}` or `{research_id, entries:[…], batch_id}`. Use only the fields for the selected kind.

| Kind | Fields and constraints |
| --- | --- |
| `source_review` | `source_id, verdict:accepted/rejected/uncertain, text`; rejected text cannot support claims. |
| `claim` | `question_id, statement, citations:[{source_id,quote}]`; optional `confidence:low/medium/high`, `inference:boolean`. Returns a claim ID. |
| `inventory_review` | `inventory_id, disposition:reviewed/excluded/blocked, text`. Reviewed also needs `question_ids, source_ids` and `claim_ids` or `citations` from accepted original text. Excluded needs `reason_code:out_of_scope/non_content`; blocked needs a specific reason. |
| `answer` | `question_id, answer, claim_ids`; claims must belong to that question. |
| `question` | `id, question`; up to 24 questions. |
| `gap` | `question_id, text`; a later answer can resolve it. |
| `conflict` | At least two `claim_ids`, plus `text`; returns a conflict ID. |
| `resolution` | `conflict_id, claim_ids, text`; preserves the original conflict. |
| `retraction` | `claim_id, text`; retains history and reopens affected questions/conflicts. |
| `external_run` | `id, provider, run_id, status, text`; optional `result` or `artifact_path`. States: prepared, pending, queued, in_progress, completed, cancelled, error, unknown_outcome. Saves references/hashes, not a scheduler. |
| `interruption` | `operation_id, text`; marks confirmed interrupted pending work as unknown, without refund or rerun. |
| `resume` | `text`; resumes an incomplete task while preserving reports, evidence and budgets. |

Batch ready records (1–50). They validate in order and save atomically; any invalid `entries[i]` rejects the entire batch. A source review may precede its claim in one batch; dependent claim/conflict IDs must come from the response before a subsequent batch. Reduce batch size for long quotations.

A stable `batch_id` replays identical entries, including after restart or completion; changed content fails. Without one, inspect saved records before retrying an uncertain response because claims are not deduplicated. Results contain ordered `index, kind, id, replayed` values; full records use `research_status` section pagination. `resume` and `external_run` require single-entry calls.

## Budgets and retries

Budgets bound plugin retrieval attempts, not money or model tokens:

| Counter | Unit | Default / maximum |
| --- | --- | --- |
| `search_calls` | A deduplicated provider + question + query attempt | 16 / 120 |
| `fetch_calls` | Provider attempt: Exa/Parallel/Tavily batch up to 8 URLs; Jina counts each URL | 12 without input; otherwise initial capacity plus 12 follow-ups, capped at 80 |
| `rounds` | One `research_search` batch | 8 / 40 |

Search accepts at most 12 queries and returns at most 20 URLs per question. Two queries across two providers cost four search calls and one round. A three-URL Exa → Parallel + Jina fallback costs 1 + 1 + 3 fetch calls.

Without explicit `max_fetch_calls`, the default is `min(80,max(12,ceil(URL_count/8)+12))`; replace the batch term with `URL_count` when Jina is first. `initial_fetch_plan` reports capacity and shortfall. Preserve explicit budgets and full scope even when capacity is insufficient. Saved-source reads, records and reports use no retrieval allowance; budgets may be zero. Host/provider usage outside these calls must be recorded separately.

Give each network step a stable `operation_id`. Identical parameters replay saved results; changed parameters fail. Reservations persist through auth/network failures and unknown outcomes. Do not enlarge budgets or resubmit solely to inspect a result.

Pending intent is saved before access and a completion receipt before state commit. Later reads recover a saved receipt; without one, the operation stays pending and is not resubmitted. Check whether it is still executing before recording `interruption`; a justified retry uses a new ID and budget. Observe active/unknown external runs rather than starting duplicates.

## Resume and delivery

Continue `active` tasks directly. For an exported `incomplete` report, first record `{"kind":"resume","text":"Reason for continuing"}`. Resume retains prior report snapshots and usage; it does not expand budgets. `completed` and `cancelled` are terminal. Exhausted tasks can still organize existing evidence; more retrieval needs a separately established task and budget.

`research_status` without an ID lists saved tasks. With an ID it returns bounded previews; use the needed `section` and follow `next_offset` for complete records. Page length alone does not signal the end. Use returned artifact locations for oversized entries, and `research_source` for page text.

Coverage separates `accounted_for`, `usable_text`, `substantive_review` and `question_completion`. Failure notes increase accounting only. Exclusions stay in the original denominator without increasing reading/review coverage; legacy tasks without frozen inventories have unknown original coverage.

`research_finish` may use `completed` only with supported answers to all questions, substantive review of the complete original scope, and no unresolved conflicts, pending operations or active/unknown external runs. Material gaps require `incomplete`; entirely blocked/excluded input cannot complete whole-package research. Invalidated evidence can reopen conflicts.

Finish returns report/source/coverage paths and `wiki_follow_up`. Respect existing authorization: complete a requested Wiki write using eligible reviewed claims; otherwise follow saved suggest/auto/off preferences. Wiki storage details are in the [writing reference](wiki-and-evaluation.md#compile-research-into-a-wiki).

Keep the complete task directory together when moving archives. Use the returned output location; placement preferences are in [settings](settings-and-archive.md#research-output-and-wiki-follow-up). Sharing follows the user's scope; archives may contain private material. Retrieval time does not prove origin freshness, and a saved task does not migrate a host agent's internal state.
