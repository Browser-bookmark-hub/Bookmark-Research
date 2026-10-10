# 宿主工作流与原生委派

[English](../host-workflows.md) · **中文阅读版**

确定委派有用且已获授权后才读本文。普通问答和 Wiki 写入不要求委派；只读当前宿主小节。宿主负责代理、并发、等待和取消，插件保存证据与研究状态。

| 宿主 | 入口 | 前提 |
| --- | --- | --- |
| [Codex](https://developers.openai.com/codex/subagents) | 原生子代理，`hosts/codex/delegate.md` | 本次可见委派／等待工具且允许委派 |
| [Claude Code](https://code.claude.com/docs/en/sub-agents) | `Agent`／旧 `Task`；可选 Dynamic Workflow | 当前工具访问；团队／工作流须宿主启用 |
| [Pi](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/examples/extensions/subagent) | 已加载子代理扩展；可选 `pi_subagent_workflow` | 核心不内置子代理或 MCP |
| [DSH](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/workflow) | subagent 或 `workflow` | 当前 profile 提供工具及研究 MCP／CLI |

给子代理传范围、问题、输出语言、Skill 路径、操作号前缀、实际工具入口和共享研究目录。除非另有指示，继承当前模型、推理与权限；不假定父会话或 Skill 自动传入。无法委派时继续本地工作，如实描述实际复核方式。

## 已选择的分组流程

以下配方用于冻结的书签清单；一般网页问题使用宿主常规循环。范围、记录字段、预算和恢复规则统一见[深度研究](deep-research.md)。

1. 完整清单读一次后分组，脚本默认每组 12 项。使用真实研究／清单 ID，保留每个分配实例。
2. 读者抓取／阅读，保存来源审阅、有引文的 claim 和 inventory_review。已就绪记录使用稳定分组／阶段 `batch_id` 批量提交，依赖记录使用返回 ID。
3. 等全部读者结束，再按选定分组配方派新核验者，检查原证据、引用语义、版本与反证；保留失败和无法核验的项目。
4. 比较完整覆盖差集，针对剩余 ID 补查。脚本默认补查 1 轮，可设 0–4；复用未变证据与清单。
5. 保存完整分析和有依据的回答，由 `research_finish` 判定完成。返回后核对一次已存状态、相关覆盖及产物路径，查看分析中的分组失败和核验缺口，不能只信代理的成功消息。

分析通过 `external_run` 保存，使用真实 `result_path`、`result_sha256` 并校验附件。`<run_key>-analysis` 和 `run_id:local:<run_key>` 表示本地分析阶段，不是原生运行 ID 或整项完成。真实宿主运行 ID 另记；pending／未知状态先观察再判断是否重发。

每次新脚本运行用唯一 `run_key`，恢复时保持原值；仅字母数字、点、横线和下划线，最长 40 字符。显式传 `output_language`；`auto` 根据 brief／问题判断，无依据则英文。原句和 ID 不翻译。

## Codex

按 `hosts/codex/delegate.md` 使用当前代理工具。辅助脚本只准备清单分组：

```sh
python3 hosts/codex/prepare.py --research-id RID --group-size 12
```

RID 换成真实研究 ID。遵守并发上限，等待已分配阶段结束并复核综合结果。插件不提供 Codex JavaScript 工作流运行时。

## Claude Code

普通子代理的 MCP 访问受工具过滤约束，需显式传入／预载相关 Skill；团队不继承主代理对话。两者均不要求 Dynamic Workflow。

导出的 `workflows/bookmark-research.js` 包含原生脚本。启用工作流访问后（Claude Code 2.1.154+，Pro 另需 `/config` 设置），显式调用：

```text
运行 /bookmark-research:bookmark-research，传入
{"research_id":"RID","run_key":"review-1","group_size":12,"max_gap_rounds":1,"method":"comparison","output_language":"zh"}。
```

通过 `/workflows` 管理运行。只能同会话恢复，重启可能重跑已完成子代理，因此复用证据和操作 ID。Claude 自带的深研不自动保证本插件冻结清单的覆盖。

## Pi

分组配方需要 Node 22.19+、Pi 0.83+、`pi-subagents` 0.43.0+ 和 `pi-subagents-workflows`。导出只声明 Skill；在预期的受信任项目中登记脚本：

```sh
python3 hosts/pi/register-workflow.py --project /absolute/path/to/project
```

登记器只写项目 `.pi/subagent-workflows/bookmark-research/` 下的两个工作流文件，保留冲突内容，不安装扩展或更改设置。稳定导出搬迁后需重新登记绝对桥接路径。

```js
pi_subagent_workflow({
  action: "run", name: "bookmark-research",
  args: { research_id: "RID", run_key: "review-1", output_language: "zh" }
});
```

扩展 detached 运行，须通过状态／附件工具等到终态并检查失败。使用结构化结果（`structuredOutput`、`run.error`、`ok`），不能重建被截断的显示文本；不支持跨会话 journal replay。

子代理需原生 MCP 或通过 Bash 访问 `hosts/shared/research-call.py`，JSON 输入 `{name,arguments}`、输出 `{isError,result}`。超时表示结果未知，继续前先查保存状态。

## DSH

导出包含元数据、普通 JavaScript 和调用对象生成器：

```sh
python3 hosts/dsh/workflow-call.py --research-id RID --run-key review-1 --output-language zh
```

把返回 JSON 整体传给当前 `workflow` 工具，其中有 `meta`、`script` 和对象 `args`；使用实际 MCP 名称。宿主等待后返回 `{runId,agentsStarted,result}`，取消返回错误；保留分支失败，fatal schema／上限错误正常传播。

显示可能截断，显式保存的分析附件才是完整结果；此接口没有后台 start/poll。`cordis.patch.yml` 用最终绝对路径连接 MCP client，不启用 Skill／工作流服务，搬迁后重新生成路径。
