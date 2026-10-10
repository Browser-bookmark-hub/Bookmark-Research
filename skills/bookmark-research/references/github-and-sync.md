# GitHub and synchronization boundaries

**English** · [中文](zh/github-and-sync.md)

This reference incorporates research routing, persistent preferences and synchronization boundaries from S6.0, S6.4, P1 and P2 of the public package guide; see [provenance](package-semantics.md#provenance-and-maintenance). It does not add generation or write-back workflows to this analysis Skill.

## Researching GitHub content

The plugin does not bundle or install GitHub MCP, GitHub OAuth or `gh`. Identify tools actually available and authorized in the host:

| Task | Entry point |
| --- | --- |
| Public README, documentation or Gist | Existing GitHub file-reading tool, or `fetch_web` for the public URL. |
| Exact code, branch/commit, issue, PR or release lookup | Prefer the host's GitHub MCP; an existing `gh` can also be used through host commands. |
| Local repository history and changes supplied by the user | Host commands such as `git status`, `git diff`, `git log`. |
| Commit, push, pull, create an issue or PR | A separate modification task governed by current user authorization and directory rules. This plugin exposes no such operations. |

Fetching a page does not establish that all repository code, comments or a particular commit were checked. Without specialized GitHub tools, read relevant public pages and disclose coverage. Use existing host access and task scope for private repositories; do not send private content to public search services. The official GitHub MCP project is https://github.com/github/github-mcp-server .

Host GitHub MCP / `gh` results bypass this plugin's `fetch_web` and are not automatically archived. When retention is needed, save actual returned content and record repository, file path, ref/commit when available, URL and reading time. Do not invent missing fields.

## Review learning stages

For requests such as “what did I learn this month?”, “how has my focus changed?” or “what have I been working on recently?”, use the supplied knowledge base's version history. Commits provide stage boundaries; content differences provide evidence. This is a host-led workflow using existing Git tools, not a separate plugin operation.

Combine this history with [package time clues](package-semantics.md#temporal-context), preserving each date's meaning. Check the corresponding layout and repeated-bookmark placements in each revision when they help explain a change.

1. **Establish the range.** Identify the repository, branch and package path, then use the requested dates and timezone. If “recently” has no defined window, inspect recent relevant commits and state the range used. Include a baseline before the range where available. Distinguish commit/export time from when a bookmark was actually read or learned.
2. **Read the recorded changes.** Prefer the supplied local repository: use scoped `git log`, `git diff --find-renames` and `git show <commit>:<path>` to inspect historical content without checking out another revision. For a remote-only repository, use the host's existing GitHub MCP or `gh` to read commits, comparisons and files at their refs. Follow pagination and disclose missing or shallow history. Local history needs no network check or pull; establish available host access before remote reads.
3. **Compare knowledge content.** Read both relevant versions of section JSON and `.canvas`. Match sections/items by stable IDs, checking URLs and content if export IDs changed. Inspect added/removed bookmarks, note and `descriptionMd` edits, folder/tag changes, text cards, groups and edges. Distinguish moves, renames, copies, reordering, layout changes and automatic backup/export churn from substantive additions or revisions. Preserve bookmark-instance identity; a changed filename or commit message alone does not establish a new topic.
4. **Explain the stages with evidence.** Cite commit hashes, file paths and representative content differences for each finding. Summarize observed additions, revised views and recurring questions; label inferred interests or learning progress. A saved link supports a collecting activity, not mastery or the linked project's capabilities. Use existing notes and reviewed Wiki knowledge where relevant. When the user also asks what deserves attention now, read the relevant linked sources and use targeted web research for current claims or gaps under the normal readiness rules.
5. **Retain the useful result when requested.** Save actual commit/file/diff evidence with the repository, branch, range and refs, then use the existing research and Wiki evidence workflow. Continue authorized retention after sharing supported findings; do not delay all useful feedback until a full report is compiled.

`source_history` lists plugin-managed import snapshots, not Git commits. If repository history is unavailable, those snapshots or earlier exports can support a bounded comparison, with their actual dates and limits stated. Absence of tracked changes does not prove absence of learning.

## Git constraints in canvas packages

A reference to GitHub in `AGENTS.md` neither installs nor authorizes GitHub MCP. The guide permits consulting official repositories and constrains handling of packages in Git/sync directories.

Ordinary local queries need no full-repository synchronization audit. Check the package guide's P2 only when the task actually involves file structure changes, write-back or commit/push/pull: inspect allowed structure and `.canvas`, handle external file nodes/unrelated files according to those rules, and validate actual changes. Do not turn analysis into unrequested cleanup or commits.

Keep reports, page snapshots, settings and databases outside the canvas package. Do not add `knowledge/`, `raw/` or `wiki/` to the original synced directory to enable research; canvas synchronization may clean them. Store lasting preferences in user settings or the Skill. Package `AGENTS.md` may be regenerated from templates during export/sync.

A persistently synced local canvas directory can use `mode:live`, with `completeness:complete` only for a confirmed full mirror. MCP checks on-disk changes and preserves the valid index during Git locks, empty directories or validation failures. It does not pull, push or log in to Git. Manual exports of the same canvas can still be imported as snapshots. See [source lifecycle](source-lifecycle.md) for parameters, deletion stability and reconnect behavior.
