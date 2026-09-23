# Settings and source archives

**English** · [中文](zh/settings-and-archive.md)

Users can change settings in conversation. CLI and MCP share one implementation; there is no separate graphical settings page.

Providers are `exa`, `parallel`, `tavily` and `jina`. Search starts with `search.providers` (Exa + Parallel), then `search.fallback_providers` (Tavily + keyed Jina) for unresolved queries; `[]` disables fallback. Reading uses `fetch.provider` first, then other `fetch.providers` concurrently for unresolved URLs (Exa → Parallel + Jina). Jina Reader supports anonymous access; Search requires `JINA_API_KEY`. Tavily uses `TAVILY_API_KEY` or a keyless header. Credentials come from the process environment, then the private credential file; service quotas still apply.

## Terminal setup and readiness

Run `python3 <root>/src/cli.py setup --host codex` (or `claude_code`, `pi`, `dsh`) to guide preferences, hidden key entry and selected service checks. `--lang auto|en|zh` selects the wizard language. `--non-interactive --input FILE` merges partial preferences without prompts; `--input -` reads JSON from stdin. Use environment variables for agent-supplied keys, never chat or preference JSON. `--skip-checks` stays offline; `--test-retrieval` opts into sample search/read requests that can use provider quota. The flags conflict. No professional research job is started by setup/checks.

Keys saved by setup live in `credentials.json` next to the settings file, or `BOOKMARK_RESEARCH_CREDENTIALS`. The file is unencrypted and readable only by its owner (`0600`). Runtime tools reload it, so saving a key takes effect without restarting the plugin; changed process environment requires restarting that process. Environment variables take precedence. Host OAuth tokens remain in the host, and plugin keys do not automatically authenticate a separate host MCP.

Before each new web research question, call `research_readiness` with the actual `host`, `observed_tools` and any explicitly restricted `providers`. CLI: `readiness --host codex --tool mcp__exa__agent_run`. Only report tools actually observed; omitted observations mean unknown, an empty list means no tools were observed. Local bookmark queries require no check. During an investigation, reuse its result instead of repeatedly refreshing. CLI callers run readiness explicitly before web commands.

| Policy | Behavior |
| --- | --- |
| `cached` (default) | Check on first use, changed settings/keys, or expiry; default TTL 900 seconds |
| `always` | Fresh check on each new question's readiness call |
| `manual` | No network unless `refresh:true` / `--refresh` or an explicit retrieval test |
| `offline:true` / `--offline` | Local configuration and valid cached evidence only; no network |

Read the scope of each result:

- `missing_credentials`: configure the named key through setup or the process environment.
- `catalog_reachable`: MCP discovery worked; search/read permission and quota are untested.
- `http_unchecked`: HTTP mapping exists; inspect operation-level missing keys (Jina Search requires one).
- `retrieval_verified`: use only operations whose own status is `verified`; other operations may have failed.
- `model_access_verified`: OpenAI model metadata was accessible, not a paid research execution test.
- `task_mcp_access_verified`: the Parallel Task MCP accepted the key; this does not establish Task API execution permission.
- `failed`: address the classified auth/network/contract failure, then refresh that provider. Other routes remain available.

Optional native research MCPs return endpoint-specific `setup` guidance. Inspect existing registrations before adding one to avoid duplicates. Codex uses `codex mcp list --json`, `codex mcp add NAME --url URL` and, for OAuth-capable endpoints, `codex mcp login NAME`; Claude uses `claude mcp list`, `claude mcp add --scope user --transport http NAME URL`, then `/mcp` to authorize. Use the actual scope and existing name. Pi has no assumed MCP extension; ordinary/deep host-led work uses the bundled CLI. DSH uses its official MCP client with `transport: streamable-http`, the endpoint and environment-backed headers in the selected profile; OAuth support is not established by that bridge's documentation. Do not infer login from tool presence or start a paid task just to test authorization.

The wizard displays these host steps; it does not execute them or import host login tokens. Its `needs_attention` lists failed checks or missing required service keys. Cached checks retain timestamps and expire; failures are cached for at most 60 seconds. Cache files live under the data directory's `readiness/` and contain no raw keys. Configuration and key rotation invalidate the relevant evidence.

## Configuration entry points

`get_settings` returns effective settings and `config_path` without creating a file. `update_settings` merges and persists supplied `changes`. Later calls read new settings immediately without restarting MCP. For a request to use only Exa for search and enable archiving:

```json
{"changes":{"search":{"providers":["exa"],"fallback_providers":[]},"archive":{"enabled":true}}}
```

Concurrent CLI/MCP updates use a `.<filename>.lock` next to the config to serialize merges, then atomically replace the file. Updates to different fields do not overwrite each other. The lock file remains; waiting more than 10 seconds returns a timeout.

The effective configuration shape is below. Replace example `directory` values with the user's absolute paths; `~` is supported.

```json
{
  "schema_version": 1,
  "timeout_seconds": 30,
  "search": {"providers": ["exa", "parallel"], "fallback_providers": ["tavily", "jina"], "limit_per_target": 5},
  "fetch": {"provider": "exa", "providers": ["exa", "parallel", "jina"], "max_characters": 12000},
  "archive": {"enabled": true, "directory": "/absolute/path/to/knowledge"},
  "research": {"depth": "auto", "prefer_host_workflows": true, "response_language": "auto",
    "methods": ["comparative_analysis", "fact_check", "benchmark_review"]},
  "readiness": {"mode": "cached", "ttl_seconds": 900, "timeout_seconds": 10},
  "professional_research": {"enabled": false, "provider": null,
    "openai": {"model": "o4-mini-deep-research", "max_tool_calls": 24},
    "parallel": {"processor": "pro"}},
  "wiki": {"directory": "/absolute/path/to/wiki"}
}
```

Precedence is per-call arguments → saved preferences → built-in defaults. `fetch_web.archive=false` disables saving for one call; `update_settings` changes the future default. `max_characters` ranges from 100 to 100000 and is forwarded only when the provider supports the corresponding limit. Archives record actual request parameters. `character_limit_applied:false` means the provider has no length parameter supported by this adapter. A larger limit does not guarantee a complete page.

Config path: CLI `--config` → `BOOKMARK_RESEARCH_CONFIG` → `${XDG_CONFIG_HOME:-~/.config}/bookmark-research/settings.json`. Archives default to `${BOOKMARK_RESEARCH_DATA_DIR}/knowledge`, or `${XDG_DATA_HOME:-~/.local/share}/bookmark-research/knowledge` without that override. Clients sharing config and data paths share preferences and records. API keys remain separate from preferences, in the environment or private credential file.

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` must be absolute. Empty/relative values are ignored per XDG conventions, using home-directory defaults rather than locations relative to a client's working directory.

`research.depth` accepts auto/quick/agentic/deep; auto routes by the current `task_shape`. Methods include comparative_analysis, fact_check, benchmark_review and wiki_synthesis. Routing suggests a path without starting agents or changing host settings. Professional services default to disabled and require `OPENAI_API_KEY` or `PARALLEL_API_KEY`; search MCP success does not establish research API authentication. See [services](research-services.md).

Old config files inherit new defaults; only user overrides are saved. An explicit saved `search.providers` list without `fallback_providers` keeps fallback disabled to preserve the earlier provider choice. Set both lists to opt into primary and fallback groups. Store lasting preferences here instead of changing package `AGENTS.md`. Settings, evidence, Wiki, SQLite and source snapshots stay outside the plugin/package and are not bundled into upgrades. There are no embeddings. Continuous directory checks depend on each source's `mode`, separately from page archiving; see [source lifecycle](source-lifecycle.md).

Output language precedence is the current request → `research.response_language` (`auto`, `en`, `zh`) → task/conversation language when auto → English if unspecified. Installer `--lang` controls help/onboarding only; the wizard separately asks for response language. Pass the resolved language to workflow `output_language` when delegating.

## What a page read saves

`fetch_web` saves actual provider responses it receives. Search hits do not trigger reads or archives. Responses from Exa/GitHub MCPs separately configured by the host are not intercepted.

If authentication, transport or tool-contract failure prevents any actual response, the tool returns `status:"error"`, `error_kind` and `usage`, with no `result` and no invented archive. An actual response with no extracted text is retained with per-page status. MCP marks a complete call failure `isError:true`; partial success preserves usable results.

```text
knowledge/
  sources/
    <fetch-time-and-unique-id>/
      response.json
      manifest.json
      pages/<URL-hash>.md
```

- `response.json` is the raw MCP result object, including content blocks and provider status. It is not original webpage HTML and contains no authentication headers added by this plugin.
- Markdown contains actual extracted text reliably associated with the requested URL. Do not reconstruct it from snippets. Source metadata stays in `manifest.json`, outside the original text.
- The manifest records requested/returned URLs, provider, tool, actual parameters, retrieval time, `response_sha256`, body paths/hashes, and failure/missing/excerpt/possible-truncation markers. Provider publication time and author are stored in `provider_published_at` and `provider_author`, not inserted into text. `completeness:"unknown"` means completeness is unproven. `possibly_truncated:false` is not a completeness guarantee either.
- Fragments such as `#comments` remain, but extraction does not guarantee all comments were loaded. `fragment_scope_verified:false` makes this explicit. Retrieval time differs from publication, update and cache time.
- Unrecognized response formats still retain the response and manifest, with no body path. Partial failures save only recognized successful text. Per-page `extraction_status:"provider_error"` means the provider reported failure; conflicting text for one URL becomes `conflicting_provider_results` without arbitrarily choosing a body. Archive failure is explicit in `archive.status:"error"`; the actual received content is still returned without automatically repeating a paid fetch.
- Exa batch records support indented multiline titles. Every standalone `URL:` field must belong to a recognized record; unmatched, malformed or duplicate boundaries leave the block raw. Unrequested redirect records also delimit pages. This conservative check may withhold text containing ambiguous record-like fields; inspect the raw response instead of treating it as another page's body.
- Reading the URL again appends a new snapshot without replacing prior records. This is per-call retention, not background version monitoring.

Reports can cite `archive.manifest_path` and page `body_path`. Archives do not automatically enter the bookmark SQLite index or become Wiki pages. Use `research_import_evidence` for original text actually obtained by the host with real provenance. Mark external research reports as external_report; their citation lists do not count as original-page review. Use `wiki_write` for knowledge synthesis.

Deep research keeps separate state/evidence under `research/`. `research_fetch` always saves actual research responses and text regardless of ordinary fetch archiving, because resume and citation validation need these snapshots. See [deep research](deep-research.md) for sessions and pagination.
