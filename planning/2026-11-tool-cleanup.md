# 工具面清理评估：18 个别名该不该删

> 2026-11-10 · 复核对象：MCP 全量目录 58 个名字中的 18 个 deprecated 别名
> 结论先行：**不建议现在执行完整删除。** 默认 DSH 会话只看到 10 个工具，别名只在 `deep`/`all` 出现；完整删除需要先合并 9 项能力并迁移 58 处测试，收益只落在 deep 档。建议只做“目录移除”或维持现状。

## 1. 实际证据

### 1.1 DSH 宿主里看到什么

本会话（DSH Desktop）向模型暴露的 bookmark-research 工具只有 10 个：

```
fetch  health  ingest  job  locate  read  save  search  spawn  walk
```

没有 `get_context`、`search_web`、`wiki_write` 等旧名。本机配置没有显式 `tool_scope`，走默认 `quick`。也就是说：**日常使用没有别名噪音，也没有 58 个名字的上下文成本。**

### 1.2 上下文实测（生产 `tools/list`）

| 目录 | 工具数 | 响应字符 | 约 tokens |
|---|---|---|---|
| `quick` | 10 | 15,038 | ~3,760 |
| `deep`/`all`（含别名） | 58 | 73,220 | ~18,300 |
| 仅真实工具 | 40 | 51,549 | ~12,890 |
| 18 个别名 | 18 | 21,671 | ~5,400 |

别名占全量目录 **29.6%**，但只影响 opt-in 的 `deep`/`all`。

### 1.3 Codegraph 爆炸半径

- `impact TOOL_SCHEMAS`：**45 个受影响符号**，生产代码只有 `_tool_names`、`handle`、`background_call`，其余是 7 个测试方法/文件。
- `_call` 的调用方只有 `handle`（外加一个测试）；但 `_call` 内部是**字符串分派**，codegraph 看不到 `"search_web"` 这类字符串分支，真实耦合被低估。
- 生产代码中别名以字符串形式出现：`fetch_web` 16 处、`search_web` 13 处、`wiki_write` 10 处、`research_service_start` 10 处、`wiki_get`/`wiki_list` 各 9/5 处。
- 测试中直接调用旧名的位置约 **58 处**。

### 1.4 哪些别名不是 1:1 重复

| 旧名 | 新原语 | 缺口 |
|---|---|---|
| `search_bookmarks` | `locate` | `sort_by`、`score`、`count_only`、`compact`、`item_types`、target 搜索 |
| `lookup_url` | `locate(url=…)` | 返回每个实例的父级/复制卡上下文 |
| `search_archive` | `locate(in=["archive"])` | 按 URL 分组、版本数、时间跨度、`expand_versions` |
| `wiki_list` | `locate(in=["wiki"])` | 页面目录 + revision + `source_url` 过滤 |
| `wiki_acknowledge` | `save` | acknowledge 语义与 `note` 字段 |
| `research_service_start/status/result/cancel` | `spawn`/`job` | 服务生命周期字段与 operation_id |
| `search_web` | `search` | `targets` 数组（已可并入） |
| `get_context`/`traverse_graph`/`fetch_web`/`merge_search_results`/`wiki_write`/`research_source` | `read`/`walk`/`fetch`/`ingest`/`save`/`read` | 基本 1:1 |

**18 个里约 9 个可平移，9 个会丢能力。** 这就是计划书里“测试迁移未完成”的真实含义：不是改名，是能力搬家。

### 1.5 CodeGraph 源码证据（本机 /Users/kk/Downloads/codegraph-main）

CodeGraph 是同一类问题的现成答案：**CLI 全量，MCP 极小。**

- `package.json` 的 `bin` 只暴露 `codegraph` 一个 CLI；README 的 CLI Reference 列了约 25 个命令（`query`/`explore`/`impact`/`callers`/`files`/`status`…）。
- 但 MCP 默认**只列一个** `codegraph_explore`。源码 `src/mcp/tools.ts:2023`：

  ```ts
  // Pared to ONLY codegraph_explore — the single tool that reliably earns its
  // place ... presence itself steers mis-picks, so they are no longer LISTED.
  const DEFAULT_MCP_TOOLS = new Set(['explore']);
  ```

- 其余 `node/search/callers/callees/impact/files/status` 的 **handler 全部保留、仍可调用**，只是不列在 `tools/list`；用 `CODEGRAPH_MCP_TOOLS=explore,node,...` 可重新暴露。
- 我没有给 DSH 装 CodeGraph 插件，直接在 shell 里执行 `codegraph status/query/impact`；DSH 有 bash，本地确定性命令不需要 MCP 包一层。

这正好证明：**“旧能力保留、表面只列少数”是生产级做法，不需要把 9 项能力搬进原语再删 handler。** 我们的 10 原语 + CLI 已经是同一结构；差别只是 deep/all 把 18 个旧名也列了出来。

## 2. 三个方案

### A. 目录移除（推荐，如果在意 deep 上下文）

- `_tool_names` 永远排除 18 个别名；`tools/list` 58 → **40**；
- 旧调用仍可跑，能力不丢；
- 测试只改目录断言；文档改成“40 个广告名，旧名不再展示”；
- 风险低，改动小。

**代价**：旧名仍可调用，不是“彻底删除”。

### B. 完整删除（0.8.0 项目）

- 先把 9 项缺口并入 `locate`/`save`/`spawn`；
- 迁移 58 处测试与 CLI 输入校验；
- 删 schema/description/handler/`DEPRECATED_TOOL_TARGETS`/legacy bench；
- 目录 40，deep 51.5k 字符。

**代价**：行为面广、测试重写、发布重打 tag；收益只在 deep 档。

### C. 维持现状

- 默认 10 个已经干净；
- deep 用户继续付 5.4k tokens；
- 什么都不用动，0.7.1 直接发。

## 3. 建议

按 DSH 里的实际体验和 CodeGraph 的源码：**默认面已经干净；正确做法是 A，不是 B。**

- CodeGraph 没有合并能力，也没有删 handler；它只是**不再列出**窄工具，同时保留调用。A 是同一个模式。
- 如果近期会频繁用 `deep` 做整包审计：做 **A**，`tools/list` 58 → 40，deep 73,220 → 51,549 字符。
- 如果 deep 只是偶尔用：**C**，什么都不动。
- **B 不需要做**：9 项能力合并 + 58 处测试迁移，是在重造 CodeGraph 已经证明不必要的轮子。

## 4. 如果以后做 B：验收

- `tools/list` 40，quick 10，无别名；
- sort/score/count/compact、实例、archive 分组、wiki 目录、acknowledge、service 生命周期都能通过原语触达；
- 全量测试通过；deep 实测 51,549 字符；
- 文档不再出现“0.8.0 拒绝”。

## 5. Codegraph 使用记录

```sh
codegraph status
codegraph impact TOOL_SCHEMAS
codegraph callers _call
codegraph callers _tool_names
codegraph query search_bookmarks --json
codegraph explore "legacy tool alias removal"
```

索引：154 文件 / 4,216 节点 / 13,596 边。
