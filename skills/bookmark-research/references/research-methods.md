# Comparison, fact checking and benchmark analysis

**English** · [中文](zh/research-methods.md)

Select methods for the research question; simple lookups do not require every analysis step. Readers and independent verifiers share questions, frozen inventory IDs, comparison dimensions and evidence format. The host owns concurrency. Package categories and edges help interpret intent without proving webpage facts.

## comparative_analysis: compare equivalent dimensions

Identify the kind of object being compared. Search/extract tools, sustained research services, agent frameworks, hosts, workflow extensions and knowledge stores are different categories. Subagents do not make an SDK equivalent to a Deep Research API; multiple tools do not make a search MCP a research workflow.

Choose dimensions relevant to the user's decision: capability/input, authentication, source access, execution owner, outputs/citations, cancellation/resume, cost/quota and integration requirements. Each cell records a conclusion, source and applicable version. Use unknown for absent evidence rather than inferring support from names or blanks.

| Object | Dimension | Conclusion | Evidence type | Date/version | Evidence ID, quotation and limits |
| --- | --- | --- | --- | --- | --- |
| Actual object | Actual dimension | Bounded finding | Documented / currently discovered / actually tested | Actual value or unknown | Mapping from original evidence to the claim |

Documentation describes a product contract; visible tools/configuration establish discovery; a complete run establishes behavior in the current environment. Record those separately. Schema validation does not prove a model workflow runs. For resume support, specify same-session/cross-session behavior, replay scope and idempotency limits. Distinguish search authentication, research-task authentication and user web login.

Build the matrix from all original user material, then fill evidence gaps with first-party documentation. Convenient external search does not replace the original package. Check differing dates, plans or versions before recording a conflict.

Deliver the matrix, decision criteria and limits. Make conditional recommendations tied to evidence and untested conditions, instead of ranking overall quality by tool count.

## fact_check: atomic claims and counterevidence

Split compound statements into independently supportable claims. “This host has subagents, background workflows and cross-session resume” contains at least three contracts. Check each:

- Correct entity, version and period; whether extraction produced the wrong page, a login shell, snippet or truncated text.
- Whether the quotation supports the whole claim, including conditions, quantities and defaults. Text matching proves only that the quote exists.
- Direct first-party evidence and independent counterevidence. Multiple search providers returning one page do not increase independent-source count.

Save `source_review`, then a `claim` with an exact `quote`. Mark inferences with `inference:true` and explain their factual basis. Do not present inference as a documentation statement. Use `retraction` when evidence fails and revise affected questions; retain both sides of version conflicts and their resolution through `conflict` / `resolution`.

An independent verifier reads original text and claims, then reports supported/unsupported/uncertain, reasons, counterevidence and inventory/question IDs needing follow-up. Repeating a reader's summary is insufficient. Check `research_coverage` afterward: record completeness and semantic reliability are separate checks.

## benchmark_review: establish comparability

For every leaderboard, benchmark or paper in scope, record what was measured and its protocol; do not read only the current leader. Distinguish the leaderboard, benchmark task, evaluated systems and this plugin.

| Record | Why it affects comparison |
| --- | --- |
| Task, sample size, languages, temporal split and open/private data | Determines which questions the result generalizes to. |
| Model, version, reasoning configuration, host and agent framework | Scores may reflect the model or execution strategy, not the search service. |
| Search/browser/file tools and external research APIs | Different access changes the available evidence. |
| Token, call, time and monetary budgets; retry/best-of-N policy | Larger budgets and selected runs cannot directly represent a single run. |
| Gold answers, matching rules, semantic citation judge and scoring rubric | F1, citation existence, citation accuracy and report quality differ. |
| Whether failures, refusals and missing sources enter denominators | Counting only successes inflates results. |
| Repetitions, variation, confidence intervals and leaderboard update date | A single rank does not establish stable superiority. |

Keep missing details unknown. Group results with the same tasks, inputs and conditions, then explain remaining differences. Do not treat framework leaderboards as search API rankings or local synthetic tests as public benchmark scores. Use names such as RACE/FACT only when their actual implementation and protocol were used.

To compare this plugin's three execution routes, use the same frozen inputs, questions, deliverables and budgets and record actual model, tool and host versions. Retain failures and unknown costs. Independently label answer matches, citation meaning and report quality, then use the [evaluation tool](wiki-and-evaluation.md) for calculation. Disclose unobservable model/tool differences in professional services. A successful API call alone does not prove better research quality.
