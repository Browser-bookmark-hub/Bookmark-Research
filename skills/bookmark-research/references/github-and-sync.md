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

## Git constraints in canvas packages

A reference to GitHub in `AGENTS.md` neither installs nor authorizes GitHub MCP. The guide permits consulting official repositories and constrains handling of packages in Git/sync directories.

Ordinary local queries need no full-repository synchronization audit. Check the package guide's P2 only when the task actually involves file structure changes, write-back or commit/push/pull: inspect allowed structure and `.canvas`, handle external file nodes/unrelated files according to those rules, and validate actual changes. Do not turn analysis into unrequested cleanup or commits.

Keep reports, page snapshots, settings and databases outside the canvas package. Do not add `knowledge/`, `raw/` or `wiki/` to the original synced directory to enable research; canvas synchronization may clean them. Store lasting preferences in user settings or the Skill. Package `AGENTS.md` may be regenerated from templates during export/sync.

A persistently synced local canvas directory can use `mode:live`, with `completeness:complete` only for a confirmed full mirror. MCP checks on-disk changes and preserves the valid index during Git locks, empty directories or validation failures. It does not pull, push or log in to Git. Manual exports of the same canvas can still be imported as snapshots. See [source lifecycle](source-lifecycle.md) for parameters, deletion stability and reconnect behavior.
