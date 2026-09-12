# Reviewed Wiki and annotated research evaluation

**English** · [中文](wiki-quality.zh.md)

The host writes and reviews knowledge pages. The plugin stores their evidence and revisions, checks their integrity, and searches the organized prose. Evaluation consumes explicitly annotated outputs; it does not call a model or infer semantic support from matching words.

## Wiki API

`WikiStore(directory=None, settings=None, research_sessions=None)` uses an explicit directory first, then `settings.wiki.directory` (default: the data directory's `wiki/`). Plugin directories and canvas package directories are rejected. Research evidence remains in its research session, outside the original input package.

```python
from wiki import WikiStore

wiki = WikiStore(research_sessions=sessions)
page = {
    "title": "Reusable sessions",
    "kind": "topic",  # or entity
    "sections": [{
        "heading": "Supported behavior",
        "text": "The host's reviewed synthesis, including relevant limits.",
        "claims": [{"research_id": research_id, "claim_id": "c1"}],
    }],
    "links": [],
    "review": {
        "method": "model",  # or human
        "reviewer": "The actual model/version or human reviewer",
        "note": "Explain the scope and support checks actually performed.",
    },
}
written = wiki.write("reusable-sessions", page, "Organize reviewed findings", expected_revision=0)
current = wiki.get("reusable-sessions")
wiki.write("reusable-sessions", revised_page, "Explain the new limitation", expected_revision=current["revision"])
```

Every section requires explicit research claim references. A reference is accepted only when its claim is active, every cited source is `accepted`, the quote occurs in its saved body, and the body hash matches. The Wiki snapshot retains the research ID, claim ID, source ID, original-inventory IDs, bookmark instance references, exact quotes, reviews, retrieval metadata and artifact hashes. Up to 24 distinct claims may support one page; oversized topics must be split.

The review declaration addresses whether the prose is supported, uses the correct entities and scope, preserves uncertainty, and acknowledges contrary evidence. The program records this declaration and its rubric. It cannot verify that the named human or model performed the judgment, and a successful write is not an independent semantic endorsement.

An imported external report stays secondary evidence. Its provenance and quoted report text are retained; its bibliography is not expanded into pages supposedly read or original sources supposedly covered.

### Revisions, links and inspection

Each update writes an immutable JSON revision and a rendered Markdown revision under `revisions/<page_id>/`, then atomically updates `index.json`. The index is the publication point. A failed publication can leave unreferenced files, while the preceding revision stays readable. `expected_revision=0` creates a page; an update must name the revision the caller read. After an interrupted write, inspect the current revision before retrying.

Cross-links have the form `{"page_id": "existing-page", "relation": "The host's explanation"}`. The target must already exist. Rendered links point to the target revision present when the page was written, preserving the historical meaning. A later target update produces a lint warning; the host can explicitly revise the relationship. Prior page revisions remain available with `get(page_id, revision=N)`.

| Method | Result |
| --- | --- |
| `write(page_id, page, change_note, expected_revision=0)` | Revision metadata and absolute artifact paths |
| `get(page_id, revision=None)` | Authored page, evidence snapshot, update record and current provenance validation |
| `list(offset=0, limit=20)` | Paginated current page metadata |
| `lint(page_id=None)` | Source review, active-claim, citation, hash, link and history issues |
| `search(query, offset=0, limit=10)` | Matching current Wiki prose, with stale pages excluded |

Lint detects later rejection, withdrawal, source/claim changes and altered or missing artifacts. Historical text is preserved and identified as stale. Lint explicitly returns `semantic_support: "not_scored"`.

Search checks titles, section headings and authored section text. It uses case-folded literal terms, including Chinese substrings, and simple occurrence ordering. Saving a provider extract alone does not make that extract searchable as organized Wiki knowledge. This is not embedding retrieval or semantic reranking; neither is selected without actual question-answering evaluation.

## Quality evaluation input

`evaluation.evaluate(suite, runs, judgments=None)` is a pure computation over supplied data. The complete runnable input is [research-quality.json](https://github.com/Browser-bookmark-hub/Bookmark-Research/blob/main/tests/fixtures/research-quality.json), also included at `tests/fixtures/research-quality.json` in the source checkout and verification pack.

- A **suite** identifies tasks, their original source/question IDs, gold answers and a versioned rubric. `gold_answers: null` means no answer-set benchmark is available. The rubric defines answer identity matching, citation support and report dimensions on a 0–4 scale.
- A **run** records its task, system, mode, repeat, final report, atomic answers/claims/citations, coverage IDs and measurements. It also records model, tools, budget, input snapshot/version, time window and harness version. Citations are unique claim/source pairs.
- A **judgment** identifies the rubric version and the actual human or model evaluator. It supplies predicted-answer → gold-ID matches, supported/unsupported/uncertain citation labels with reasons, and report rubric scores with reasons. Fixture judgments must identify themselves as synthetic.

Answer matching is an annotation task. Evaluators must read the actual prediction, establish identity and scope, and use `gold_id: null` for an incorrect entity. The scorer does not guess aliases or use regex matches as a semantic judge. Multiple predictions matched to one gold entity count once for set precision/recall; unmatched predictions count as false positives. Duplicate matches are also reported.

Each citation judgment concerns the complete claim and the actual source context, including identity, dates and scope. `supported` means the text supports the claim. `unsupported` and `uncertain` both remain in the full accuracy denominator. Exact-quote matching alone is not a support judgment.

### Metrics and missing information

| Output | Meaning and limit |
| --- | --- |
| Answer precision, recall, F1 | Uses gold data and complete answer-match annotations; otherwise null |
| Semantic citation accuracy | Supported / all citations when all are judged; partial-label statistics are shown separately |
| Semantic claim support | Claims with a supported citation / all claims, once all citations are judged |
| Citation presence | Claims with any citation / all claims; this is a structural measurement |
| Report quality | Mean supplied dimension scores normalized from 0–4, only when every rubric dimension is scored |
| Accounted/text/reviewed coverage | Separate rates against the original source set; failed sources remain in the denominator |
| Question coverage | Recorded answered question IDs / original question IDs; this does not judge answer truth |
| Cost and latency | Supplied USD/seconds with observed, reported or synthetic measurement basis; unknown values stay null |
| Repeat variation | Count, mean, sample variance, sample standard deviation and range under the same declared conditions |

Coverage must satisfy `reviewed ⊆ text ⊆ accounted ⊆ original scope`. These reported IDs still need the research evidence audit: an input label alone does not prove that a source was read. External tool and model usage unavailable to the plugin must remain unknown.

Groups compare the same task. Differences in model, tools, budget, input version, time window, harness, evaluator or measurement basis are reported. Differing conditions form separate aggregates. Unknown budgets prevent a controlled-comparison declaration. A single observation has no variance estimate; missing costs are not averaged as zero. Failed and incomplete outputs remain in the supplied run set.

The output pins suite, run and judgment hashes, retains evaluator/rubric identity and includes null-score diagnostics. It does not produce a provider ranking, a causal claim, a RACE/FACT score or a public leaderboard score. Real claims about improved research quality require real task runs and independently defensible annotations.

## Reproduce the offline demonstration

These commands need a source checkout or verification pack. Runtime exports contain the guides, but not the test fixtures or verification scripts.

```sh
python3 -B scripts/verify_quality.py
python3 -B -m unittest discover -s tests -p 'test_wiki.py'
python3 -B -m unittest discover -s tests -p 'test_evaluation.py'
```

The verification script writes `inputs.json`, `evaluation.json` and a readable `evaluation.md` under a new external data-directory run. `--output /absolute/external/directory` selects another artifact directory. `--fixture /path/input.json` accepts a wrapper containing `suite`, `runs`, `judgments` and optional known fixture expectations.

The included example contains four invented source records, two gold entities and six hand-authored outputs labeled as direct, workflow and professional modes. One source is unavailable, some outputs miss or invent an answer, and one citation has uncertain scope. Costs and durations are synthetic values; one cost is deliberately unknown. These cases exercise denominators, semantic-label completeness, repeat variance and missing measurements. **They do not measure those three execution modes or any real host/model/provider.**

Wiki tests additionally verify immutable history, failed index publication, cross-links, Chinese prose search, source rejection/withdrawal, secondary-report provenance and source/package boundaries. Live host research, real professional-service comparisons and independent semantic judging remain separate validation work.
