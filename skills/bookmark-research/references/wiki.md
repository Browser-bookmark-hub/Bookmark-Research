# Wiki

**English** · [中文](zh/wiki.md)

The Wiki contains reviewed knowledge synthesized across sources; page archives contain original evidence. They are stored separately.

## Save read sources in one call

After reading and reviewing evidence, call `wiki_write` with authored sections, exact citations and a top-level `sources` list. The host supplies the knowledge organization and review; the plugin retains evidence internally. No prior research session is required.

```json
{
  "page_id": "aurora", "expected_revision": 0, "change_note": "Save reviewed findings",
  "sources": [{"id": "docs", "url": "https://example.com/docs", "text": "Reusable sessions are supported."}],
  "page": {
    "title": "Aurora sessions", "kind": "topic", "links": [],
    "sections": [{"heading": "Reuse", "text": "Aurora supports session reuse.",
      "citations": [{"source_id": "docs", "quote": "Reusable sessions are supported."}]}],
    "review": {"method": "model", "reviewer": "Actual reviewer", "note": "Checked the source and citation meaning."}
  }
}
```

Use real content in place of the fixture. A source may supply `capture_id` instead of `text` to reuse a verified saved extract; keep its original URL. Each source needs a unique `id` and must be cited. Quotes must occur in its text. Sources support `kind:"page"`, `"local_document"` or `"external_report"`, and optional `title` / `retrieved_at`. Keep reports identified as secondary material. Read the current page before an update and pass its `expected_revision`.

Source text is limited to 2 million characters. Pages remain bounded to 16 sections, 12,000 characters per section and 24 internal claims; split larger topics. Integrity checks do not establish semantic support. The older claim-reference format below remains available for persistent research tasks.

## Advanced maintenance

The following resume, refresh and audit tools require the `deep` preset; ordinary storage and retrieval use the default tools.

## Resume compilation and review

Use `wiki_work` when resuming unfinished organization or checking whether a write committed. Scope it with `research_id`, `capture_id` or `page_id`, or list a `kind` (`research`, `capture`, `page`) and optional `status`. Stable `work_id` values and pagination support resumption. A full listing is a local audit, not a prerequisite for each answer.

- `archived`: saved material has no eligible, unpublished claim identified yet; this does not mean the text was read or accepted.
- `pending`: reviewed active claims remain outside current intact Wiki revisions. Follow `pending_claim_ids` and `resume`. Candidates do not authorize publication or require writing every claim.
- `compiled`: the applicable claims or captured bodies are cited by current intact Wiki revisions; this does not mean every passage of a capture has been synthesized. `pages` and `work_receipt` identify actual page IDs, revisions and record hashes. Check page work separately for freshness.
- `needs_review`: a page has freshness/integrity issues, or a task/capture cannot be validated. Page entries include issue previews and `source_reads` for already saved new evidence, avoiding another fetch. Read the page and evidence before revising it.

The view is reconstructed from durable captures, recoverable research receipts and the current committed Wiki index; there is no second mutable completion flag. It survives process restarts, ignores orphan revision files, and recognizes a committed write even if its response was lost. Removing a citation from the current Wiki can make its claim pending again; historical revisions remain accessible through `wiki_get`. Rows can change while paging; re-list the affected ID before writing.

For a useful research result, follow the existing `suggest` / `auto` / `off` preference and session authorization. Read matching pages, compile eligible claims, maintain relevant links, and write with `expected_revision`. A `wiki_follow_up.instruction` is a next action, not a completed write. Report actual `work_receipt` page IDs and revisions; after interruption, check `wiki_work` before retrying.

For changed webpages, read saved `source_reads` or follow `wiki_refresh` continuation, import and review new evidence, then revise affected pages. Recheck their IDs or `wiki_work(kind="page", status="needs_review")`; linked pages may still need review after their target changes. A successful fetch alone does not close a review. This workflow starts no background model, monitor or automatic publisher.

## Compile research into a Wiki

Read text with `research_source`, accept valid material with `source_review`, and save atomic `claim` entries. Organize supporting/conflicting claims into topic/entity pages. Preserve versions, conditions, counterevidence and unresolved issues rather than stacking unstructured extracts.

Example `wiki_write` input; replace all content and IDs with actual values:

```json
{
  "page_id": "research-execution",
  "expected_revision": 0,
  "change_note": "Compile reviewed research into a topic page",
  "page": {
    "title": "Research execution",
    "kind": "topic",
    "sections": [{
      "heading": "Available capabilities and limits",
      "text": "Synthesis supported by the claims below, retaining limits and uncertainty.",
      "claims": [{"research_id": "r-actual-id", "claim_id": "c1"}]
    }],
    "links": [],
    "review": {"method": "model", "reviewer": "Actual reviewer model and version", "note": "Describe the page identity, citation meaning and scope actually checked."}
  }
}
```

Use the task's output language for titles, section headings, authored prose and review notes. Keep identifiers and original quotations unchanged; add translations separately.

`kind` is topic or entity. Every section needs a valid claim; a page can reference at most 24 distinct claims. Split larger topics into related pages. Writes check that claims are not retracted, sources are accepted, quotes occur in text, and hashes match. `review` must truthfully identify who performed semantic verification; the runtime cannot prove it occurred.

Write target entity/topic pages before adding `links:[{page_id,relation}]`. For updates, read the current revision through `wiki_get` and use it as `expected_revision`. On conflict, reread and merge rather than overwriting another update. Historical revisions and their referenced target versions remain unchanged.

`wiki_get` returns page content, claim/source mappings, bookmark instances and inventory IDs. `validation.integrity` checks saved evidence; `validation.freshness` checks capture age and known source versions. Newer extracts, expired/unknown capture dates, failed refreshes and changed linked pages produce `needs_review`. Direct webpage claims compare their cited bookmarks and related canvas context; inferences and local-document claims retain the full input scope. Invalid/retracted evidence is excluded from search. `semantic_support:"not_scored"` and `origin_current_verified:false` remain explicit.

`wiki_list` and `wiki_search` are paginated. Search uses a rebuildable SQLite character index over authored titles, headings, text and optional `page.aliases` (up to 30 names). Literal/spacing matches and explicit query aliases such as 价格/定价/pricing improve recall; there are no embeddings or semantic reranking. Only matching candidates undergo evidence validation; use `wiki_lint` for a complete audit. Writes update one search document and reuse catalog summaries. A failed derived search index does not undo a committed revision; queries fall back to scanning revisions. Default storage is the data directory's `wiki/`, overridable with `settings.wiki.directory`.

For time-sensitive knowledge, use `wiki_refresh(page_id, expected_revision, offset=0, limit=8)` to fetch and archive only that page's cited URLs. Follow its continuation to cover more URLs. Results distinguish changed, unchanged and unverified captures, return saved-capture read arguments, and list affected pages. `wiki_list(source_url=..., offset=..., limit=...)` paginates direct citations and linked dependents. Read saved text through `fetch_web` with `capture_id`, import actual evidence with `research_import_evidence` and its original `retrieved_at`, review sources/claims, then update the Wiki with `expected_revision`. Refresh never rewrites authored text or the bookmark package.

`wiki.max_source_age_days` defaults to 30 (range 1–3650). A newer identical body can renew capture age without rewriting history. A changed body requires review; historical imports cannot supersede newer known captures. Source observations are tracked across research tasks in the same research root and ordinary captures in the configured archive root. Retrieval may use a provider cache, so neither a fresh capture nor `current` proves live-origin freshness. There is no automatic background webpage monitor.

New revision records store evidence paths relative to their research task. `wiki_get` resolves verified evidence at current task locations; legacy absolute-path records remain readable without rewriting history. Move/sync the Wiki index and revisions together with the cited research state, inventory and evidence, keeping their relative layout for Markdown links. Configure the destination's local data/research paths; copying only Wiki Markdown does not preserve a verifiable knowledge base. Git synchronization belongs to the host and stays outside the canvas-managed directory.

Each write regenerates `index.md` (current pages by kind: link, title, one-line summary, revision, date, claim count) and appends `log.md` (`## [date] write | title (rN)` with page ID, change note and research IDs). Read or grep them to orient; `index.json` and revision files remain authoritative, and `wiki_lint` warns `catalog_stale`/`catalog_missing` until the next write regenerates `index.md`.

Complete an already authorized Wiki write without asking again; use only eligible reviewed claims. Otherwise `research_finish.wiki_follow_up` follows `settings.wiki.after_research`: `suggest` offers candidates before writing, `auto` updates or creates an eligible page, and `off` skips it. Updates still require the current `expected_revision`. Report completed writes. The `eligible_claims` list marks each claim's exact first quotes and whether it is an inference. `draft.page` goes one step further: sections are grouped by question, the text is the claim statements themselves, and every section already carries its `{research_id, claim_id}` list split at the write limits, so one `wiki_write` with the actual review block can save the bounded page within existing authorization. `remaining_claim_ids` identifies claims that need another page. Do not add claims outside that list.
