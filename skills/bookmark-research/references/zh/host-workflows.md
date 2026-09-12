# 宿主工作流与原生委派

[English](../host-workflows.md) · **中文阅读版**

这份参考用于多来源研究的分组阅读、独立核验和补查。先判断当前宿主实际暴露的能力，再选择入口；仅有配置文件、包名或版本号不能证明会话工具已经可用。普通查找仍可直接调用共享研究工具。

| 宿主 | 多组任务的入口 | 必要能力 |
| --- | --- | --- |
| Codex | `hosts/codex/delegate.md`＋原生子代理 | 当前会话提供原生委派与等待工具 |
| Claude Code | `/bookmark-research:bookmark-research` | 已加载本插件的 Dynamic Workflow，功能已启用 |
| Pi | `pi_subagent_workflow` 的 `bookmark-research` 定义 | 同一父会话已加载 `pi-subagents` 和 `pi-subagents-workflows`，项目定义受信任 |
| DSH | 宿主 `workflow` 工具＋导出的完整调用对象 | profile 已配置 workflow service、worker-thread engine、tool 及研究 MCP |

宿主负责子代理、并发、等待、取消和恢复。插件只保存研究清单、来源、正文、审阅、覆盖率和报告。子代理不能再创建调度器。用现有工具检查状态；不要为补齐能力改全局配置、安装替代宿主或自动转入另一种执行模式。

## 共同流程

委派前确定输出语言：在研究 brief 和 Codex 各次任务中保留要求，脚本工作流通过 `output_language` 传入（例如 `"en"` 或 `"zh"`）。省略或传 `"auto"` 时跟随 brief／问题中的语言要求，没有语言依据才默认英文。这是单次任务参数，不是安装语言或持久设置；引用、ID 和 JSON 字段保持原样。完整提示阅读对照见插件根目录 `docs/prompt-reference.md`。

1. 用 `research_start` 建立问题与冻结范围，保留返回的 `research_id`。`source_ids` 指已同步的数据包；`u-` ID 指原始 URL 清单；`sN` 指已保存的证据来源，三者不可互换。选中书签不能隐式缩小一个完整数据包的审阅范围；确需子集时使用显式范围参数并在报告中标明。
2. 分页读取 `research_inventory`，直到 `next_offset` 为 null。保存全部 ID、原始 URL 和对应的书签实例，不使用第一页或预览替代全量清单。现有任务状态为 `incomplete` 时先明确记录 `resume`；已完成或取消的任务不能重开。
3. 每组默认 12 项，读者逐项读取正文并记录 `source_review`、有准确引文的 claim、`inventory_review`。已有的多条记录用 `research_record.entries` 批量提交（最多 50 条），按分组和阶段使用稳定的 `batch_id`，后续批次引用返回的真实 claim ID。`reviewed` 需要已接受的原始来源、问题和引文或 claim；失败页面只记录具体阻塞原因，排除项需说明 `out_of_scope` 或 `non_content`。
4. 等全部读者结束后，由另一批子代理独立核验原文、引用语义、版本日期和反证。无法检查不等于反驳成功；保留缺口、失败和未核验 ID。
5. 对 `research_coverage` 的 `all`、`missing`、`unread`、`unreviewed` 各自读取全部分页。比较完整 ID 集合及 `difference_counts`。把来源差集和未核验项交给下一轮阅读、独立核验；脚本默认补查 1 轮，可设为 0 至 4 轮。
6. 保存完整分析 JSON，再回答问题和重查覆盖。`research_finish` 决定研究能否完成；所有输入被列明、可用正文覆盖、实质审阅覆盖、问题完成率是不同指标。全失败、全排除、重要结论未核验或仍有未解释缺口时输出 `incomplete`。工作流返回后，主代理直接调用 `research_status`、`research_coverage` 并读取返回的报告与分析附件，核对真实状态、完整范围和哈希；不能只相信子代理返回的成功文字或预期文件名。
7. 宿主主代理收到返回后，直接调用 `research_status` 和完整分页的 `research_coverage`，核对真实终态、冻结范围和实际产物；不要仅信报告子代理返回的状态或路径。回读 `external_runs` 中的完整分析附件并核对 SHA-256，将报告路径与 status.artifacts 对照。宿主脚本成功、子代理声称完成或某个附件存在，都不能代替这一核验。

脚本的分析附件通过 `research_record` 的 `external_run` 保存，取真实的 `recorded.result_path` 与 `recorded.result_sha256`。附件含完整清单、各组返回、失败、差集和核验状态。`<run_key>-analysis` 的 `run_id` 使用 `local:<run_key>`，明确是本地关联号；它记录已结束的分析阶段，不能冒充宿主 run ID 或整项研究完成。可获得真实宿主 run ID 时另存其观测状态。

`pending`、`queued`、`in_progress`、`unknown_outcome` 不能记为完成。工作流停止或超时时先查宿主状态和已保存研究状态，不盲目重发付费操作。宿主会话的恢复能力与插件研究档案的持久保存分别处理。

新任务未显式给 `max_fetch_calls` 时，根据冻结 URL 数量按每次最多 8 URL 计算首轮下界，再保留 12 次有界补查余量，并受 80 次硬上限限制。207 URL 的下界为 26 次，默认上限为 38 次。显式用户预算保持原值；`initial_fetch_plan` 报告 `minimum_required`、`call_shortfall` 和 `urls_beyond_capacity`，不足时保留完整范围。读者在适用时批量抓取，每组如何拆分、失败重试和补充证据可能需要更多调用；这些估计不保证正文一定可用。

## Codex

按 `hosts/codex/delegate.md` 使用当前会话的原生子代理。`prepare.py` 只是分页读取共享 MCP 后生成分组，不启动子代理：

```sh
python3 hosts/codex/prepare.py --research-id RID --group-size 12
```

主代理传入完整分组，遵守当前并发上限并等待全部读者结束，再派新核验代理。沿用当前模型、推理、权限和工具访问，除非用户另有指定。没有原生子代理工具时说明缺失能力，可由宿主按相同证据规则处理有界的单代理任务；不要声称发生了原生委派。Codex 没有由本插件提供的 JavaScript workflow runtime。

## Claude Code

Claude 导出包的 `workflows/bookmark-research.js` 包含 `export const meta` 和原生脚本正文。已建立研究后，由用户明确调用，例如：

```text
运行 /bookmark-research:bookmark-research，传入对象
{"research_id":"RID","run_key":"review-1","group_size":12,"max_gap_rounds":1,"method":"comparison","output_language":"zh"}。
```

将 `RID` 替换为真实研究 ID。`run_key` 每次新运行保持唯一，同一运行恢复时保持不变；只含字母数字、点、横线和下划线，最长 40 字符。Claude 将对象作为全局 `args` 提供，脚本使用原生 `agent` 和 `pipeline`，读者通过可见的研究 MCP 工具操作。

Dynamic Workflows 需要 Claude Code 2.1.154+ 及启用的工作流访问；Pro 还需在 `/config` 开启。使用 `/workflows` 管理宿主运行。只能在同一会话恢复，退出后重新开始，部分已结束子代理也可能重跑。读者需复用已保存证据和操作 ID。

Claude 自带 `/deep-research` 是另一项入口，自 2.1.218 起需显式调用；它不自动保证本插件冻结的书签清单被逐项审阅。`ultracode` 的触发取决于用户真实输入；把该词写进 Skill、普通 `-p` 输入或没有 human origin 的 SDK 内容不能触发。插件不替用户切换 effort 或启用设置。

## Pi

需要 Node 22.19+、Pi 0.83+、`pi-subagents` 0.43.0+ 和 `pi-subagents-workflows`。这两项是扩展能力，Pi 核心不内建本插件的 MCP 工具。导出包的 `package.json` 只声明 Skill；保存的脚本需单独在受信任项目登记：

```sh
python3 hosts/pi/register-workflow.py --project /absolute/path/to/project
```

登记器只创建项目 `.pi/subagent-workflows/bookmark-research/workflow.json` 和 `script.js`，相同内容可重复执行，已有不同内容会保留并报冲突。它不修改 Pi settings，不安装扩展。桥接脚本的绝对路径绑定当前稳定导出目录，迁移后需重新登记。

在该项目的 Pi 会话调用：

```js
pi_subagent_workflow({
  action: "run",
  name: "bookmark-research",
  args: { research_id: "RID", run_key: "review-1", output_language: "zh" }
});
```

扩展以 detached 模式启动；主代理必须用扩展的状态、等待和 artifacts 功能等到终态，检查每个失败子代理。脚本使用 `runs.all`、`outputSchema` 和 `structuredOutput`，逐项检查 `run.error` 与 `ok`，不从可截断的显示文本重建结果。脚本只用顶层 await 与 Promise 链，避开该运行时禁止的嵌套 async helper。注册表不提供跨会话 journal replay。

读者使用 `delegate`，需要 Bash 访问稳定包中的 `hosts/shared/research-call.py`，或已有原生研究 MCP 工具。Python bridge 以 `{name,arguments}` 为 JSON stdin，调用同一 stdio MCP 并返回 `{isError,result}`；不是 Pi 核心的 MCP 功能。超时返回 `unknown_outcome`，先查已保存状态再判断是否继续。

## DSH

DSH 导出含 `workflows/bookmark-research/meta.json`、无 export 的 `script.js` 和生成调用对象的脚本：

```sh
python3 hosts/dsh/workflow-call.py --research-id RID --run-key review-1 --output-language zh
```

将输出 JSON 整体作为宿主 `workflow` 工具参数。它分别包含 `meta`、普通 JS `script` 和对象 `args`。宿主脚本使用 `agent(prompt,{label,schema})` 与 `pipeline`；MCP 名称以当前可见工具为准，常见格式是 `mcp__bookmark-research__research_*`。

DSH 等完整流程结束后返回 `{runId,agentsStarted,result}`；取消作为错误返回。普通分支失败需保留，schema 错误或硬上限等 fatal 错误交给宿主传播。渲染可能截断，不能假设另有自动生成的完整结果句柄；报告子代理显式保存的完整分析附件才是本插件的可回读结果。宿主没有在此接口定义后台 start/poll API。

`cordis.patch.yml` 使用最终导出路径连接官方 MCP client，但不会安装 DSH、配置 Skill discovery 或启用 workflow 服务。profile 必须预先提供这些能力，搬迁导出目录后重新生成绝对路径补丁。
