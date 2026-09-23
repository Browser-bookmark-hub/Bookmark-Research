# Using Bookmark Research

**English** · [中文](user-guide.md)

Use one plugin in either language. Provide your package and explain the question, scope, and result you need. The host model reads the Skill and calls the tools; no fixed trigger phrase is required.

## First use

After installing, start a new host session so it loads the current Skill and tools. Provide your own Bookmark Canvas directory, ZIP, or single-card JSON:

> Use Bookmark Research to read the package at "/absolute/path/to/my-package". First list its cards, folders, and bookmark counts offline.

Local queries require no API key. The plugin starts without personal bookmarks or a seed database. Later requests can refer to the registered source; a new export of the same canvas should explicitly reuse that source.

## Choose the depth and scope

| Task | Example request | What happens |
| --- | --- | --- |
| Local query | “Which card contains this bookmark?” | Searches local metadata and canvas relationships. |
| Quick check | “Read the official page I bookmarked and check whether it supports MCP.” | Reads the known URL, or searches to find a source, then answers with citations. |
| Agentic search | “Compare the search tools in these cards, including their authentication and research capabilities.” | Uses card context to plan questions, searches and reads pages, and follows evidence gaps. |
| Deep research | “Research every URL in this package, verify the rankings, compare it with our plugin, and save a report and Wiki.” | Preserves the full source inventory, organizes sustained investigation, reviews evidence and coverage, and saves the requested deliverables. |

Quick checking does not switch the host to a non-reasoning model. Depth and scope are separate: a deep study may cover one explicitly selected card; a whole-package request keeps every original URL and every duplicate bookmark's context. Pagination, batching, and subagent count do not reduce that scope. Search snippets and external reports do not count as reading the original pages.

Deep research can run through the host's reasoning, subagents, or existing workflows. Optional OpenAI Deep Research and Parallel Task APIs require separate configuration and credentials. Search access alone does not enable those services. An unavailable explicitly requested service is reported rather than silently substituted.

## Snapshots and live directories

Ordinary exports default to `snapshot`. The plugin saves the necessary source files and index, so the downloaded export can later be moved or deleted. Directories inside Git repositories default to `live`; existing registrations retain their selected mode. For a persistent full mirror, say:

> Register this directory as a live source. It is the complete synchronized canvas directory.

The plugin checks registered live directories while its MCP process runs and before queries. A standalone CLI command exits when finished; use `python3 src/cli.py watch` for continuous foreground monitoring. Git synchronization itself belongs to your existing sync tool.

Partial exports preserve omitted files. A complete mirror can remove missing files; a supplied complete card can remove items even in partial mode. Single cards are always partial. Both modes save reusable versions. Updated input prompts research/Wiki review; it does not automatically fetch pages or rewrite conclusions.

## Settings

Ask “Show Bookmark Research settings” or run `python3 src/cli.py config show`. Set a lasting preference with a request such as “Use only Exa for future searches”; say “for this request” for a temporary override.

| Setting | Default | Example |
| --- | --- | --- |
| Web search | Exa + Parallel; 5 hits per target per search call | “Use only Exa for future searches.” |
| Page reading | Exa; requested length 12,000 characters | “Use Parallel to read this page.” |
| Ordinary page archives | Enabled | “Do not archive this page read.” |
| Research depth | `auto` | “Use deep research for this task.” |
| Answer language | `auto`, follows the question | “Use Chinese for future reports.” |
| Service readiness | Cached for 15 minutes; refresh on key/config changes | “Check availability before every question.” |
| Professional research API | Disabled | “Show what is needed to enable OpenAI research.” |

The search result limit is not a limit on package scope. Requested text length does not guarantee a complete page. Deep research always preserves its task evidence, independently of the ordinary page archive preference.

Run `python3 <plugin-root>/src/cli.py setup` for guided preferences and hidden key entry. Keys come from the host environment first, then a private `credentials.json` next to settings: `EXA_API_KEY`, `PARALLEL_API_KEY`, `TAVILY_API_KEY`, `JINA_API_KEY`, and, for professional OpenAI research, `OPENAI_API_KEY`. Access and quotas depend on each provider. Host-led research needs no additional professional-service key.

Before a new web question, the Skill checks selected services and observed host tools with `research_readiness`. Cached/always/manual modes control frequency; local queries stay offline. Optional native MCP connection/login steps are shown by setup, with actual OAuth handled in the host. Keys, visible tools and successfully tested operations have distinct status; checks never create a paid research job. See [settings and readiness](../skills/bookmark-research/references/settings-and-archive.md).

Default settings live in `~/.config/bookmark-research/settings.json`; data lives in `~/.local/share/bookmark-research/`. XDG settings and the plugin's data/config path overrides are supported. SQLite stores the local query index; source versions, webpage archives, research records, and Wiki revisions live alongside it. Multiple hosts can share these locations. Keep user data outside the plugin and original canvas package.

## Languages and evidence

Answers, progress updates, report text and Wiki titles/sections follow the current explicit request, then saved `research.response_language`; `auto` follows the task and conversation. For example:

> Research these Chinese and English sources, but write the report in English. Preserve original quotations and add translations separately.

The Skill's instruction language does not determine output language. Installer `--lang auto|en|zh` selects help and onboarding; the wizard separately asks which answer language to save. With `auto`, installation checks `LC_ALL`, then `LC_MESSAGES`, then `LANG`; Chinese locales select Chinese, others select English. `BOOKMARK_RESEARCH_INSTALL_LANG` carries that choice from the shell bootstrap to Python.

The execution Skill and all 11 method references are in English, with complete Chinese reading copies. The [instruction index](instructions.en.md) also links the bilingual host prompt reference. The host preserves the selected output language in research briefs and delegated tasks; scripted workflows accept `output_language`. If the task and conversation select no language, English is the fallback.

Original URLs, identifiers, evidence text and quotations remain unchanged. Tool/JSON fields, technical diagnostics and fixed report/Wiki metadata labels remain in English; the host supplies the authored prose in your requested language. Historical research records retain their original language.

If an older session exposes only some MCP tools, the host can use the bundled CLI for missing operations. A new session loads the updated Skill and tool catalog. Selecting a route or importing a package alone does not start background research.

See the [shared Skill](../skills/bookmark-research/SKILL.md), [settings reference](../skills/bookmark-research/references/settings-and-archive.md), and [Wiki/evaluation guide](wiki-quality.md) for implementation details.
