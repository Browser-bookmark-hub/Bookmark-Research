# Host workflows and native delegation

**English** · [中文](zh/host-workflows.md)

Read this only after selecting useful, authorized delegation. Ordinary questions and Wiki writes do not require it. Use the current host's section; the host owns agents, concurrency, waits and cancellation, while the plugin stores evidence and research state.

| Host | Entry point | Prerequisite |
| --- | --- | --- |
| [Codex](https://developers.openai.com/codex/subagents) | Native subagents; `hosts/codex/delegate.md` | Visible delegation/wait tools and permission to delegate |
| [Claude Code](https://code.claude.com/docs/en/sub-agents) | `Agent` / older `Task`; optional Dynamic Workflow | Current tool access; teams/workflows require host enablement |
| [Pi](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/examples/extensions/subagent) | Loaded subagent extension; optional `pi_subagent_workflow` | Core provides neither subagents nor MCP |
| [DSH](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/workflow) | Subagent or `workflow` | Active profile supplies tools and research MCP/CLI access |

Give each child its scope, questions, output language, Skill path, operation prefix, actual MCP/CLI entry points and shared research-store location. Inherit current model, reasoning and permissions unless instructed otherwise. Do not assume parent conversation/Skill text transfers across hosts. Without delegation, continue locally and describe any review accurately.

## Chosen grouped workflow

These recipes require a frozen bookmark inventory. General web questions use the ordinary host loop instead. Scope, record fields, budgets and resume rules are defined in [deep research](deep-research.md); they apply here unchanged.

1. Read the complete inventory once and divide it into groups (script default: 12 items). Use actual research/inventory IDs and preserve every assigned instance.
2. Readers fetch/read and record source reviews, quoted claims and inventory reviews. Batch ready records with stable group/stage `batch_id` values; dependent records use returned IDs.
3. Wait for all readers, then use fresh verifiers for the selected grouped recipe. Check original evidence, citation meaning, versions and counterevidence. Preserve failed or uncheckable items.
4. Compare the complete coverage differences and follow up on remaining IDs. Scripts default to one gap round (configurable 0–4). Reuse unchanged evidence and inventories.
5. Save the full analysis and supported answers; `research_finish` determines completion. After return, check persisted status, relevant coverage and artifact paths once. Inspect the analysis attachment for group failures and verification gaps; an agent's success message is insufficient.

The analysis is saved through `external_run`, with actual `result_path` and `result_sha256`; verify that attachment when using it. Its `<run_key>-analysis` record and `run_id:local:<run_key>` identify a local analysis stage, not a native run or overall completion. Record real host run IDs separately. Pending/unknown runs must be observed before resubmission.

Use a unique `run_key` for each new script run and retain it on resume: letters, digits, dots, hyphens or underscores, at most 40 characters. Pass `output_language` explicitly; `auto` uses the brief/questions, falling back to English. Preserve original quotations and IDs.

## One-question discovery

For one question about a package, the discovery script runs a bounded loop instead of the grouped recipe. `plan_research` ranks the cards and bookmarks the question touches; each round reads the current URL batch with `fetch_web` while the first round also runs one `search_web` seed, and URLs the seed discovers are read next round. Every round ends with `discovery_bundle`, which owns the budget decision (defaults: steps ≤ 6, fetches ≤ 8, variants ≤ 3, 90 seconds) and returns the citable bundle: only `content_state=usable` pages become `evidence[]`, everything else is listed with its reason, and the bundle degrades excerpts → digest → URL list rather than returning nothing.

The host counts steps, fetches and variants and passes them to every `discovery_bundle` call; `budget.used` and `budget.remaining` say where the budget stands, and the loop stops when `budget.continue` is false, when three evidence entries are in hand, or when no further round fits the remaining budget. The result carries `status` (ok / partial / no_evidence / empty / blocked), `host_stop` (why the loop ended), the counters, the plugin's last `budget` verdict and the `bundle` string. Answer only from `evidence[].id`, report unavailable sources and gaps separately, and never cite a URL without an evidence entry; snippets never answer.

## Codex

Use `hosts/codex/delegate.md` with current native agent controls. The helper prepares inventory groups only:

```sh
python3 hosts/codex/prepare.py --research-id RID --group-size 12
```

Replace RID with the actual research ID. Respect the current concurrency limit, wait for each assigned stage and review the combined result. The plugin supplies no Codex JavaScript workflow runtime.

## Claude Code

Ordinary subagents can use available MCP tools subject to filtering; pass/preload the needed Skill explicitly. Teams do not inherit the lead's conversation. Neither option requires Dynamic Workflow.

The export contains two native scripts, `workflows/bookmark-research.js` (grouped recipe) and `workflows/bookmark-research-discovery.js` (one-question discovery). With workflow access enabled (Claude Code 2.1.154+; Pro also needs its `/config` setting), explicitly invoke:

```text
Run /bookmark-research:bookmark-research with
{"research_id":"RID","run_key":"review-1","group_size":12,"max_gap_rounds":1,"method":"comparison","output_language":"en"}.
```

Run the discovery script as `/bookmark-research:bookmark-research-discovery` with `{question, source_id, run_key, output_language}`; it returns the bundle described above.

Manage runs through `/workflows`. Resume works within the same session; restarting may replay completed children, so retain evidence and operation IDs. Claude's separate built-in deep research does not automatically cover this plugin's frozen inventory.

## Pi

The grouped recipe needs Node 22.19+, Pi 0.83+, `pi-subagents` 0.43.0+ and `pi-subagents-workflows`. The export declares the Skill only. Register the script in the intended trusted project:

```sh
python3 hosts/pi/register-workflow.py --project /absolute/path/to/project
```

The registrar writes two files per workflow under project `.pi/subagent-workflows/` — `bookmark-research/` and `bookmark-research-discovery/`; conflicting content is preserved. It neither installs extensions nor changes settings. Re-register after moving the stable export because the bridge path is absolute.

```js
pi_subagent_workflow({
  action: "run", name: "bookmark-research",
  args: { research_id: "RID", run_key: "review-1", output_language: "en" }
});
```

Run discovery with `pi_subagent_workflow({action:"run", name:"bookmark-research-discovery", args:{question:"…", source_id:"SID", run_key:"discover-1", output_language:"en"}})`.

The extension runs detached: wait through its status/artifact tools until terminal and inspect failures. Use structured results (`structuredOutput`, `run.error`, `ok`), not truncated display text. There is no cross-session journal replay.

Children need native MCP access or Bash access to `hosts/shared/research-call.py`, whose JSON input is `{name,arguments}` and result is `{isError,result}`. Besides `research_*` it serves `plan_research`, `discovery_bundle`, `fetch_web`, `search_web` and the read-only local queries (`index_status`, `search_bookmarks`, `get_context`). A timeout means unknown outcome; inspect saved state before continuing.

## DSH

The export includes workflow metadata, plain JavaScript and a call-object helper:

```sh
python3 hosts/dsh/workflow-call.py --research-id RID --run-key review-1 --output-language en
python3 hosts/dsh/workflow-call.py --workflow bookmark-research-discovery --question "…" --source-id SID --run-key discover-1 --output-language en
```

Pass the entire returned JSON to the current `workflow` tool. It contains `meta`, `script` and object `args`; use the host's actual MCP names. The host waits and returns `{runId,agentsStarted,result}`; cancellation returns an error. Preserve branch failures and let fatal schema/limit errors propagate.

Display may truncate; the explicitly saved analysis attachment is the full result. This interface provides no background start/poll API. `cordis.patch.yml` connects the MCP client using final absolute paths; it does not enable Skill/workflow services. Rebuild those paths after moving the export.
