# Professional research services: prepare, run and retrieve

**English** · [中文](zh/research-services.md)

Deep research starts with the current host model's investigation. Professional services can take a scoped subquestion after the host's first assessment, or a task explicitly assigned to them by the user. This plugin provides thin OpenAI Responses Deep Research and Parallel Task API clients; existing host research MCPs can also be used. Their reports return to the host for review and synthesis. Search interfaces authenticate separately from these research services.

## Settings and entry points

Call `research_services` to inspect status offline. Each provider reports `ready_to_start` and concrete `missing` settings/credential names; readiness is configuration, not verified authentication. Native host research remains available independently. OpenAI uses `OPENAI_API_KEY`; Parallel uses `PARALLEL_API_KEY`. Keys belong in the launching process environment, never project files, manifests, research inputs or reports.

Effective `professional_research` defaults to `enabled:false, provider:null`. After the user selects a service, update its settings as needed:

```json
{"changes":{"professional_research":{"enabled":true,"provider":"openai","openai":{"model":"o4-mini-deep-research","max_tool_calls":24}}}}
```

Another supported OpenAI model is `o3-deep-research`; Parallel defaults to `processor:"pro"`. Model/processor access, fees and quotas depend on the current account. Per-request options can override supported fields. Configuration and an explicit provider choice do not automatically start a task or silently select a different service.

## Prepare actual material

Create local research with `research_start` and a clear question, scope, sources, time requirements, output language/format and known limitations. `research_service_prepare` accepts:

```json
{
  "research_id": "r-actual-id",
  "question_id": "q1",
  "provider": "openai",
  "input": "The complete question, scope, evaluation dimensions and deliverable requirements. Write the report in English and preserve original quotations.",
  "options": {"max_tool_calls": 24}
}
```

Without `inventory_ids`, preparation uses the investigation's entire selected inventory. Specific IDs may be assigned to a subquestion without reducing overall research scope. The result contains the exact request payload, input version and shared source scope; inspect whether these can answer the original question. Only explicit input and original URLs are added automatically, not the package, notes, tags or local paths.

Cloud services cannot read local filesystem paths or reach local stdio MCPs. OpenAI can receive up to 2 existing account `options.vector_store_ids`; uploading material and creating a vector store are separate intentional actions. Putting a local path or account page in a brief does not make it accessible. Unread material remains a coverage gap.

## Single creation and status observation

Once the concrete request is within existing user authorization, call `research_service_start` with the same fields as prepare plus a stable `operation_id`. Do not ask again for already-authorized service use. Creation saves `external_id` and the actual provider run ID. The provider owns background execution; the plugin has no polling loop.

Follow `next_action` from each run observation: query an active run with `refresh:true`, retrieve the completed report, or recover a known run ID after an uncertain creation. Continue through report import and original-source review; neither `research_route` nor `research_service_prepare` executes the research. A saved service preference orders optional external services after host research. An explicit `research_route.provider` selects that service exclusively. Do not mark the host route failed merely to delegate a subquestion.

On a confirmed error, the returned next action points to `research_route`. Add the failed `route_id` to earlier `failed_routes`, supply current host observations, and execute the next available route in the same research session. Do not drop the user's explicit provider restriction. Disabled or uncredentialed APIs are unavailable; pending, running, unknown and cancelled runs do not trigger fallback. If no eligible route remains, retain the evidence and report gaps.

For host-native research MCPs, routing recognizes observed Exa `agent_run` or Parallel `createDeepResearch` + `getStatus` + `getResultMarkdown`. These MCPs are not installed by this plugin, and tool presence does not verify authentication. Use their actual schemas; record each returned run ID and subsequent states with `research_record` kind `external_run`. Resume Exa through `runId`; observe an existing Parallel task instead of creating another. Import the actual report with `research_import_evidence` as `external_report`, then review original sources. This continuation is executed by the host following the Skill, not a local polling worker.

| Action | Tool / behavior |
| --- | --- |
| Prepare | `research_service_prepare`; no network call or billed creation. |
| Create | `research_service_start`; identical research ID + operation ID + input replays a saved result instead of resubmitting. |
| Local status | `research_service_status`; saved observations only by default. |
| Remote status | The same tool with `refresh:true`; one query of the existing run ID. |
| Result | `research_service_result`; save/paginate the report. `refresh:true` observes that run once. |
| Cancel | `research_service_cancel`; only documented OpenAI cancellation is implemented. |
| Attach an existing run | `research_service_attach` with research_id, operation_id, provider, known run_id and optional question_id; no remote creation. |
| Import | `research_service_import` with external_id, operation_id and optional question_id; only a completed saved report can be imported. |

A timeout or lost create response can leave `unknown_outcome`. Retain the original operation ID and inspect status. Attach a known real run ID to recover; do not create another possibly billed task with a new ID. Disconnecting or stopping observation is not remote cancellation. Failed status/result observations retain the last trustworthy state. Parallel result requests use a 1-second server wait; a timeout may still mean running.

OpenAI defaults to `store:false`, `background:true`, a supported combination. The current background guide describes roughly ten minutes of temporary storage for asynchronous polling; save returned results promptly. No cancellation endpoint has been confirmed for Parallel Task in this adapter's checked interface. Do not invent successful cancellation.

## Return reports to the evidence workflow

Results include report text, raw-response location/hash, provider citations and available usage. `citations` previews at most 100 items / approximately 100 KB. Check `citation_count` and `citations_truncated`, then read the complete `citations_file` and verify its hash. A preview is not the full citation scope. These citations are not yet verified.

`research_service_import` stores the report as an unreviewed `external_report` in the original investigation. It can support a secondary claim about what the report says, but does not prove its cited original pages were read.

Read the complete report and check the original question, omitted dimensions, conclusions and counterevidence. Actually read important original URLs, then record `source_review`, claims and `inventory_review`. A completed external run does not complete whole-package research. `research_coverage` and `research_finish` check original sources and questions. Keep unavailable provider usage unknown.

Exact requests/status live in `service-runs/er-.../`; linked records and imported evidence live in `research/r-.../`, all outside the original package.

References: [OpenAI Deep Research](https://developers.openai.com/api/docs/guides/deep-research), [OpenAI background mode](https://developers.openai.com/api/docs/guides/background), [Parallel Task API](https://docs.parallel.ai/task-api/guides/execute-task-run). Report interface-contract validation separately from authenticated live-task validation.
