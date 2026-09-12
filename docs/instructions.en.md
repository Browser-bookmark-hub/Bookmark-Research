# Skill and prompt languages

**English** · [中文](instructions.md)

Bookmark Research has one execution Skill and one runtime. The execution Skill and all 11 method references are maintained in English. Complete Chinese reading copies retain the same scope, evidence, budget and recovery rules.

## Reading index

| Instructions | English | 中文 |
| --- | --- | --- |
| Execution Skill | [Read](../skills/bookmark-research/SKILL.md) | [阅读](../skills/bookmark-research/references/zh/skill-guide.md) |
| Package semantics | [Read](../skills/bookmark-research/references/package-semantics.md) | [阅读](../skills/bookmark-research/references/zh/package-semantics.md) |
| Source lifecycle | [Read](../skills/bookmark-research/references/source-lifecycle.md) | [阅读](../skills/bookmark-research/references/zh/source-lifecycle.md) |
| CLI commands | [Read](../skills/bookmark-research/references/cli.md) | [阅读](../skills/bookmark-research/references/zh/cli.md) |
| Research and provider access | [Read](../skills/bookmark-research/references/research-workflow.md) | [阅读](../skills/bookmark-research/references/zh/research-workflow.md) |
| Deep research | [Read](../skills/bookmark-research/references/deep-research.md) | [阅读](../skills/bookmark-research/references/zh/deep-research.md) |
| Research methods | [Read](../skills/bookmark-research/references/research-methods.md) | [阅读](../skills/bookmark-research/references/zh/research-methods.md) |
| Host workflows | [Read](../skills/bookmark-research/references/host-workflows.md) | [阅读](../skills/bookmark-research/references/zh/host-workflows.md) |
| Professional services | [Read](../skills/bookmark-research/references/research-services.md) | [阅读](../skills/bookmark-research/references/zh/research-services.md) |
| Settings and archives | [Read](../skills/bookmark-research/references/settings-and-archive.md) | [阅读](../skills/bookmark-research/references/zh/settings-and-archive.md) |
| GitHub and sync | [Read](../skills/bookmark-research/references/github-and-sync.md) | [阅读](../skills/bookmark-research/references/zh/github-and-sync.md) |
| Wiki and evaluation | [Read](../skills/bookmark-research/references/wiki-and-evaluation.md) | [阅读](../skills/bookmark-research/references/zh/wiki-and-evaluation.md) |
| Host prompt reference | [Read](prompt-reference.en.md) | [阅读](prompt-reference.md) |
| Wiki API and evaluation details | [Read](wiki-quality.md) | [阅读](wiki-quality.zh.md) |

Only the root `skills/bookmark-research/SKILL.md` is a discoverable Skill. Files under `references/zh/` are Markdown reading copies, without a second Skill entry point or manifest. Read the relevant reference in one language; loading both is unnecessary.

Codex delegation and the shared Claude/Pi/DSH prompt templates execute in English. The paired prompt reference covers shared context, inventory, readers, independent verifiers, coverage, reporting, parent checks and native Codex delegation. Its placeholders are explained task data, not invented research evidence.

## Output language

Explicit user instructions take priority, followed by the actual task/conversation; use English if neither selects a language. Preserve that choice in the research brief, delegated assignments and workflow `output_language`. Professional research input must carry the same requirement. Answers, authored report text, review notes and Wiki titles/sections follow it. Original quotes, URLs, identifiers, code, JSON fields and status values remain unchanged; translations are separate.

This does not restrict retrieval by source language or change whole-package scope. Installer `--lang auto|en|zh` controls help/onboarding only and does not save a research-language preference.

Plugin presentation and starter prompts are bilingual. See the [English user guide](user-guide.en.md) or [Chinese user guide](user-guide.md) for ordinary use. Technical diagnostics and fixed report/Wiki metadata labels retain their runtime text. Historical research/validation records and original source material retain their original language.

## Maintaining equivalent instructions

Update English execution rules first, then the paired Chinese reading text and affected prompt documentation. Preserve API names, IDs, enums, numeric limits, pagination rules, scope/completion gates, authorization boundaries and citation semantics. Translate explanatory prose and illustrative values, never actual evidence.

After changes, check links and packaged contents. Workflow changes also require the host workflow tests; export changes require export/distribution tests. An independent isolated use check can verify that the Skill guides a real task. These checks do not substitute for a live paid research run or prove research quality.
