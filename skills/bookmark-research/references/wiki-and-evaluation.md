# Wiki and research evaluation

**English** · [中文](zh/wiki-and-evaluation.md)

The Wiki contains reviewed knowledge synthesized across sources; page archives contain original evidence. They are stored separately. Evaluation calculates supplied runs and judgments; it neither conducts research nor automatically judges citation meaning.

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

`wiki_get` returns page content, claim/source mappings, bookmark instances and inventory IDs. `wiki_lint` checks hashes, retractions/rejections, changed source input, links and revision problems. `semantic_support:"not_scored"` means it is not a semantic judge. Historical pages remain when evidence fails, but `wiki_search` excludes them as current reliable knowledge.

`wiki_list` and `wiki_search` are paginated. Search matches literal terms in authored titles, headings and text, including Chinese. Saving page text does not automatically write a Wiki. There are no embeddings, vector retrieval, reranking or monitoring. Default storage is the data directory's `wiki/`, overridable with `settings.wiki.directory`; keep it outside the original package.

## Evaluate actual runs

Run native host research, a host workflow and a professional service on the same question, frozen inputs and comparable budgets. Record actual model, tools, host version, input version, time window, failures and available usage. Disclose conditions that cannot be matched. Retain failures and keep unknown costs unknown rather than treating them as 0.

An independent reviewer reads actual reports and evidence under a versioned rubric and supplies:

- Matches between atomic answers and gold-answer IDs; incorrect answers map to null, and absent labels remain unknown.
- Supported/unsupported/uncertain labels and reasons for each claim/source citation pair. Matching quote substrings does not establish semantic support.
- Actual 0–4 scores and reasons for each report dimension, including factual reliability, completeness and uncertainty handling.

Call `evaluate_research` with `{suite,runs,judgments}`. The suite defines the task, gold answers (or null), original source/question IDs and rubric. Runs contain atomic answers, claims, citations, coverage, final text, conditions and measurements. Judgments identify the actual reviewer/version and labels above. The plugin's `docs/wiki-quality.md` explains the complete input; the source repository's `tests/fixtures/research-quality.json` is an explicitly synthetic runnable example.

| Output | Required evidence and limits |
| --- | --- |
| Answer precision/recall/F1 | Gold answers and complete answer matching; null if absent. |
| Semantic citation accuracy | Complete semantic labels; uncertain remains in the denominator. Partial labeling is reported separately. |
| Report quality | Scores for every versioned rubric dimension; no inferred scores. |
| Four coverage measures | Original source/question denominators; reviewed ⊆ text ⊆ accounted. Actual reading evidence still needs review. |
| Cost and latency | Observed or provider-reported values with a basis; otherwise null. |
| Variation | Repeated comparable runs provide means/sample variance; one run provides no variance estimate. |

Evaluation fixes hashes of inputs/judgments and reports condition differences. It does not publish a leaderboard or rename a local rubric as RACE/FACT. Bundled synthetic examples validate calculations, not the superiority of a host, workflow or API. Claims of better research need actual runs and defensible independent judgments.
