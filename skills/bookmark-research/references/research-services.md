# Deep Research APIs

**English** · [中文](zh/research-services.md)

For an extended investigation, submit the actual question directly to OpenAI Responses or the Parallel Task API. The host chooses the scope, observes the job and reviews the returned report. A local `research_start` session is optional. Host-native research tools remain usable independently.

## Configure and prepare

`research_services` reports configuration and missing credentials offline. Enable the chosen provider in `professional_research`; OpenAI uses `OPENAI_API_KEY`, Parallel uses `PARALLEL_API_KEY`. Set keys in terminal `setup` or the process environment.

```json
{"changes":{"professional_research":{"enabled":true,"provider":"openai"}}}
```

Prepare the concrete request with no network call or job creation:

```json
{"input":"Compare the specified products using original documentation. Include limits, versions, counterevidence and citations; write in English.","provider":"openai","options":{"max_tool_calls":24}}
```

The returned payload is the request that will be sent. The configured OpenAI default is `gpt-5.6-sol`; custom model IDs require `allow_untested_model:true`. Legacy model identifiers remain accepted for old configurations; accepted does not establish availability. Parallel defaults to `processor:"pro"`. Access, costs and quotas depend on the account.

Cloud services cannot read local paths or local stdio MCPs. Supply relevant public URLs and an explicit brief. OpenAI may use up to two existing account `vector_store_ids`; uploading documents is a separate operation.

## Run, observe and recover

| Action | Tool and behavior |
| --- | --- |
| Prepare | `research_service_prepare`: inspect the payload offline. |
| Start | `research_service_start`: add a stable `operation_id`; identical inputs replay the saved operation. |
| Observe | `research_service_status`: local state; `refresh:true` queries the existing run once. |
| Read | `research_service_result`: retain and paginate the report; `refresh:true` observes once. |
| Cancel | `research_service_cancel`: supported for OpenAI; stopping observation does not cancel a remote job. |
| Recover | `research_service_attach`: supply `operation_id`, `provider`, known `run_id`; no new job. |

Continue within existing user authorization. The provider runs the background job; the plugin starts no polling worker. Keep the same operation ID after timeouts or lost responses. Inspect `unknown_outcome` and recover a known run ID before considering a new creation. Failed observations preserve the last trustworthy state. Parallel result requests use a one-second server wait.

OpenAI uses `store:false`, `background:true`; save results promptly under the provider's temporary retention policy. Parallel cancellation is unavailable in this adapter. Failed or cancelled jobs leave explicit gaps; the host decides whether another authorized route is useful.

## Return to the Wiki or a collection audit

Read the complete report and important original sources. Provider citations are not verified evidence. Results include text, raw-response paths/hashes and usage when known. Citation previews are bounded; inspect `citation_count`, `citations_truncated` and the complete `citations_file` when necessary.

For ordinary research, use `wiki_write` with the reviewed report or original text as `sources` and exact section citations. Mark a report as `kind:"external_report"`. Preserve uncertainty and distinguish the report's claims from original-source verification.

When an explicitly selected persistent collection audit already exists, pass optional `research_id`, `question_id` and `inventory_ids` to preparation/start. The complete selected inventory is included unless IDs narrow that subtask. The advanced `research_service_import` attaches a completed report to that session; it does not mark referenced originals as read. Finish original reviews and coverage separately. These scope IDs require `research_id`.

Requests and reports live in `service-runs/er-.../`, outside the bookmark package. See [Wiki](wiki.md) and [optional collection audits](deep-research.md).

API references: [OpenAI Deep Research](https://developers.openai.com/api/docs/guides/deep-research), [background mode](https://developers.openai.com/api/docs/guides/background), [Parallel Task API](https://docs.parallel.ai/task-api/guides/execute-task-run).
