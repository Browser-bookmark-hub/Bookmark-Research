# Host workflows and native delegation

**English** · [中文](zh/host-workflows.md)

Use this reference for grouped reading, independent verification and follow-up across multiple sources. Select a route from capabilities actually exposed in the current session. A configuration file, package name or version does not establish loaded tools. Ordinary lookups can call shared research tools directly.

| Host | Entry point for grouped work | Required capability |
| --- | --- | --- |
| Codex | `hosts/codex/delegate.md` and native subagents | Native delegation and waiting tools in the current session. |
| Claude Code | `/bookmark-research:bookmark-research` | This plugin's Dynamic Workflow loaded and enabled. |
| Pi | `bookmark-research` definition through `pi_subagent_workflow` | `pi-subagents` and `pi-subagents-workflows` loaded in the same parent session; trusted project definition. |
| DSH | Host `workflow` tool with the exported complete call object | A profile with workflow service, worker-thread engine, tool and research MCP configured. |

The host owns agents, concurrency, waits, cancellation and resume. The plugin stores inventory, sources, text, reviews, coverage and reports. Children must not create another scheduler. Inspect state with existing tools; do not change global settings, install another host or silently select a different execution mode to fill a missing capability.

Resolve the user's output language before delegation. Include it in the research brief and Codex assignments; pass `output_language` to scripted workflows (for example `"en"` or `"zh"`). Omission or `"auto"` follows the brief/questions, falling back to English if they select no language. This is a task argument, not an installer locale or persistent setting. Keep quotations, IDs and JSON fields unchanged. See the plugin's `docs/prompt-reference.en.md` for the full prompt reading reference.

## Shared workflow

1. Create questions and frozen scope through `research_start`; retain its actual `research_id`. `source_ids` identify registered packages, `u-` IDs original-URL inventory, and `sN` saved evidence; they are not interchangeable. Selected bookmarks do not implicitly narrow whole-package review. An intended subset uses explicit scope parameters and is disclosed in the report.
2. Read every `research_inventory` page until `next_offset` is null. Keep all IDs, original URLs and instances. Neither a preview nor the first page is the full inventory. Record `resume` before continuing an incomplete task; completed/cancelled tasks cannot reopen.
3. Groups default to 12 items. Readers read each source and record `source_review`, claims with exact quotations and `inventory_review`. Reviewed requires accepted original text, questions and citations/claims. Failures need specific blocking reasons; exclusions need `out_of_scope` or `non_content` explanations.
4. Wait for every reader, then use fresh verifier agents to independently inspect original text, citation meaning, versions/dates and counterevidence. An uncheckable item is not a successful refutation. Preserve gaps, failures and unverified IDs.
5. Paginate each `research_coverage` filter: `all`, `missing`, `unread`, `unreviewed`. Compare complete ID sets and `difference_counts`. Assign source differences and unverified items to another reading/verification round. Scripts default to 1 follow-up round, configurable from 0 to 4.
6. Save complete analysis JSON, answer questions and check coverage again. `research_finish` owns completion. Accounted-for inputs, usable text, substantive review and question completion are separate measures. All-failed/all-excluded input, unverified major claims or unexplained gaps require `incomplete`.
7. After workflow return, the parent directly calls `research_status` and every relevant `research_coverage` page to check actual final state, frozen scope and artifacts. Read the complete analysis attachment in `external_runs`, verify SHA-256 and compare report paths with `status.artifacts`. A successful script/child, a claimed path or an existing attachment cannot substitute for that check.

The script saves analysis through `research_record` kind `external_run` and uses actual `recorded.result_path` / `recorded.result_sha256`. It includes the full inventory, group results, failures, differences and verification state. The `<run_key>-analysis` record uses `run_id:local:<run_key>` as an explicit local correlation ID. It observes finished analysis stages, not a native host run ID or whole-research completion. Record real host run IDs and observed states separately when available.

Never record pending, queued, in_progress or unknown_outcome as completed. On workflow stop/timeout, inspect host and saved research state before resending any paid action. Host-session resume and persistent plugin archives have separate lifecycles.

Without explicit `max_fetch_calls`, the initial budget allows the lower bound of at most 8 URLs per call plus 12 follow-up calls, capped at 80. For 207 URLs the lower bound is 26 and default budget 38. Preserve explicit user budgets. `initial_fetch_plan` reports `minimum_required`, `call_shortfall` and `urls_beyond_capacity`; insufficient capacity never reduces scope. Group splits, failures and additional evidence may need more calls, and estimated capacity does not guarantee usable text.

## Codex

Follow `hosts/codex/delegate.md` using current native subagent tools. `prepare.py` only paginates shared MCP inventory and prepares groups; it starts no agents:

```sh
python3 hosts/codex/prepare.py --research-id RID --group-size 12
```

Give agents complete assignments within the current concurrency limit, wait for all readers, then use fresh verifiers. Inherit the current model, reasoning, permissions and tools unless the user specifies otherwise. If native agents are unavailable, report that capability gap; the host may perform bounded single-agent work under the same evidence rules without claiming native delegation. This plugin supplies no Codex JavaScript workflow runtime.

## Claude Code

The Claude export's `workflows/bookmark-research.js` includes `export const meta` and the native script body. After creating research, explicitly invoke it, for example:

```text
Run /bookmark-research:bookmark-research with
{"research_id":"RID","run_key":"review-1","group_size":12,"max_gap_rounds":1,"method":"comparison","output_language":"en"}.
```

Replace RID with the real research ID. Give each new run a unique `run_key`, retaining it for resume of the same run. Keys contain letters, digits, dots, hyphens or underscores and have a 40-character maximum. Claude supplies the object as global `args`; scripts use native `agent` and `pipeline`, and children use visible research MCP tools.

Dynamic Workflows require Claude Code 2.1.154+ and enabled workflow access; Pro also needs the setting in `/config`. Manage host runs through `/workflows`. Resume is within the same session only. Exiting starts afresh; some completed children may replay. Reuse persisted evidence and operation IDs.

The separate built-in `/deep-research` requires explicit invocation from 2.1.218 and does not automatically guarantee review of every frozen bookmark. `ultracode` depends on actual human-origin input; placing it in a Skill, ordinary `-p` input or SDK content without human origin does not trigger it. The plugin does not change effort or enable settings on the user's behalf.

## Pi

Requires Node 22.19+, Pi 0.83+, `pi-subagents` 0.43.0+ and `pi-subagents-workflows`. These are extensions; Pi core does not provide this plugin's MCP tools. Exported `package.json` declares the Skill only. Register the saved script separately in a trusted project:

```sh
python3 hosts/pi/register-workflow.py --project /absolute/path/to/project
```

The registrar creates only project `.pi/subagent-workflows/bookmark-research/workflow.json` and `script.js`. Identical content is repeatable; differing existing content is preserved with a conflict error. It does not change Pi settings or install extensions. The absolute bridge path binds the stable export directory; register again after relocation.

Invoke in that project's Pi session:

```js
pi_subagent_workflow({
  action: "run",
  name: "bookmark-research",
  args: { research_id: "RID", run_key: "review-1", output_language: "en" }
});
```

The extension starts detached. The parent must use its status, waiting and artifacts features until terminal, inspecting every failed child. The script uses `runs.all`, `outputSchema`, `structuredOutput`, `run.error` and `ok` rather than rebuilding results from possibly truncated display text. Top-level await and Promise chains avoid nested async helpers forbidden by that runtime. Its registry provides no cross-session journal replay.

Readers use `delegate`, with Bash access to stable `hosts/shared/research-call.py` or native research MCP tools. The Python bridge accepts JSON stdin `{name,arguments}`, calls the same stdio MCP and returns `{isError,result}`; this is not Pi-core MCP support. A timeout returns unknown_outcome; inspect saved state before continuing.

## DSH

The DSH export includes `workflows/bookmark-research/meta.json`, plain `script.js` without export syntax, and a call-object helper:

```sh
python3 hosts/dsh/workflow-call.py --research-id RID --run-key review-1 --output-language en
```

Pass the entire returned JSON to the host `workflow` tool. It contains `meta`, ordinary JS `script` and object `args`. The script uses `agent(prompt,{label,schema})` and `pipeline`. Use currently visible MCP names, commonly `mcp__bookmark-research__research_*`.

DSH waits for the full workflow and returns `{runId,agentsStarted,result}`; cancellation returns an error. Preserve ordinary branch failures and let fatal schema/hard-limit errors propagate. Display may truncate; do not assume an additional automatically generated full-result handle. The reporter explicitly saves the complete analysis attachment for rereading. This interface defines no background start/poll API.

`cordis.patch.yml` connects the official MCP client using final absolute export paths. It does not install DSH, configure Skill discovery or enable workflow services. The profile must already supply those capabilities; regenerate absolute paths after moving the export.
