# Wiki 增量编译（wiki_compile）设计草案

> 2026-11-09 · 关联：[工具面任务书](2026-11-tool-surface-plan.md)、[加固计划](2026-11-hardening-plan.md)
> 状态：M1 已实现（`wiki_compile` 的 plan/status，CLI + deep MCP，含单测）；M2 起待验证。目标是把 LLM Wiki 的 “compile” 一环补成**可恢复的规划与审计**，不是再造一个自动写手机器。

## 0. 一句话

插件负责“找簇、选证据、算受影响页、验引用”；宿主负责“读与写”。编译是一段**宿主主导的长流程**，插件只提供确定性的计划、状态和门禁。

## 1. 为什么不做“一键全自动编译”

1. 插件进程没有模型，写不出正文；现有 `research_finish` 的 `after_research:"auto"` 只是把已审阅 claims 拼成一页，按 heading 追加，不是编译。
2. 5,006 条素材全量一把梭，成本与噪音都不可控：282 条搜索页、783 组重复、4 条分隔符，都会污染知识库。
3. Wiki 的写入门禁要求逐字引用（`quote in body` + `sha256`）；批处理最容易“生成得很顺、引不到原文”，越是自动越容易绕过语义审阅。
4. 真正缺的不是“写得更快”，而是“新素材进来后，哪些页该变”——这一步是确定性的，可以交给插件。

## 2. 形态

```
A. plan    确定性、进程内      → 不可变 plan.json + 可重建的进度视图
B. compile 宿主循环，逐簇       → 读证据 → 写/合并 → save(expected_revision) → receipt
C. audit   确定性、只读         → 覆盖、引用、冲突、成本
```

三段都不新增“完成标志位”：进度一律从当前 `index.json`、修订记录和 research 状态重算，和 `wiki_work` 的现有原则一致。

## 3. A：计划生成（`plan`）

输入：

| 参数 | 含义 |
|---|---|
| `source_id` + `section` / `folder_id` / `tags` | 作用域；`folder_id` 走子树 |
| `query` | 可选，按标题/备注/标签过滤 |
| `max_pages` / `max_items_per_cluster` / `min_cluster_size` | 预算 |
| `include_covered` | 默认 false，只列未被现有 Wiki 覆盖的条目 |

步骤：

1. **解析作用域**：复用 `BookmarkIndex._scope`，不新写查询。
2. **去噪**：排除搜索页、分隔符、空 URL、纯占位；URL 规范化（`SourceArchive._key`）后去重，保留实例数与目录上下文。
3. **聚类**：主键为目录路径，次键为 tag 集合；同一簇必须能用一个 `page_id` 和标题说清。不引入 embedding。
4. **覆盖判定**：URL 是否已被任一当前修订的 claim 引用；标题/别名是否命中现有页面。命中则归入 `covered`，不进入写队列。
5. **受影响页**：调用 `WikiStore._affected(urls)`，得到直接引用页与依赖页；写入计划，供“改一页要连带复核谁”。
6. **排序**：`新条目数 × 证据价值`（有 note、非搜索页、非重复）+ `受影响页数`；同分按目录稳定排序。
7. **产出工作项**：`cluster_id`、建议标题与 `page_id`、条目 refs（短 ref、URL、note 摘要）、`existing_pages`、`affected_pages`、`evidence_requirements`（需要读几个 URL、是否已有 capture）。
8. **落盘**：`wiki/compile/<plan_id>.json` 不可变；`wiki/compile/index.json` 可重建。`plan_id = sha256(scope + budget + source_version)`，同参数重复调用返回同一计划；`basis` 记录规划时的 Wiki 修订号，供 `status` 判断来源变化，不参与 id。

计划里每个簇同时给一个 **research session 草案**（`topic:"Wiki: <title>"`、URL 列表）。v1 让每个簇跑一次现有 research 流程，直接复用 claims、`conflicts`、freshness 和 `wiki_work`，不新增证据模型。

## 4. B：宿主编译循环（`compile`）

对每个工作项：

1. `read(page_id)`（有既有页时）→ 只合并相关节，不重写无关内容。
2. `fetch`/`read` 需要的 URL，落 capture；读不到就记 `evidence_gap`，不猜。
3. 组织 sections：一页讲一个实体/主题；反证与不确定性保留在正文。
4. `save(kind="wiki", page=..., sources/captures, expected_revision=...)`，`review` 必须写真实审阅者。
5. 回执写回计划进度：`page_id`、`revision`、`record_sha256`（复用 `WikiWork.receipt`）。
6. 发现反证：在簇的 research session 里 `research_record(kind="conflict")`，不要让页面“看起来一切正常”。

失败与恢复：`save` 失败按现有语义处理（冲突→重读合并；引用不匹配→重取证据）；中断后 `wiki_compile status` 从修订反推已完成项，不重跑已提交页。

## 5. C：审计（`status` / `audit`）

只读，重算：

| 维度 | 内容 |
|---|---|
| 覆盖 | 每簇 `total / covered / pending / no_evidence` |
| 产出 | 页数、revision、每页 claim 数、重复概念 warning |
| 门禁 | 引用校验失败次数、`needs_review` 页、open conflicts |
| 成本 | 每页工具调用数、抓取字节、wall time（由宿主回报） |

不写“已完成”标记；删除页面后对应条目自动回到 `pending`。

## 6. 接口

| 入口 | 形态 |
|---|---|
| MCP（deep） | `wiki_compile(action:"plan"|"status", ...)`；默认 10 原语不变 |
| CLI | `br wiki compile plan --source-id … --folder … --max-pages …`；`br wiki compile status --plan …` |
| 长任务 | 大包计划生成走 `spawn(task="wiki_plan")`，新增 `JOB_KINDS` 一项；worker 只做确定性规划，不写页 |

`wiki_compile` 不进入 quick 目录：它是维护动作，不是日常检索。

## 7. 矛盾（v1 / v2）

- **v1**：冲突留在簇的 research session（现有 `conflicts`，open 会阻止 `research_finish` completed）；计划与审计把 open conflicts 显示在簇上。Wiki 页面 schema 不变。
- **v2**：页面增加可选 `conflicts` 字段，`save` 拒绝未解决的冲突 claim，`wiki_lint` 增加 `contradiction_unresolved`，Markdown 增加 “Conflicts” 段。这一步需要 schema 版本迁移，单独立项。

## 8. 验收（B-1-1，325 条）

先 25 条小簇 pilot，再全子树；对照组是“人工指定 3 页”的现状。

| 指标 | 门槛 |
|---|---|
| 引用一次通过率 | ≥ 95% |
| `needs_review` 页占比 | ≤ 10% |
| 每页工具调用 | ≤ 8 |
| 噪音页（搜索页/分隔符成页） | 0 |
| 重复概念 warning 率 | ≤ 15% |
| 每 100 条素材产出页数 | 3–8（低于 3 说明漏，高于 8 说明碎） |

成本用“每页抓取字节 + 工具步数 + 宿主报告的 token”三项记录，不用估算。

## 9. 非目标

- 不做后台自动监控或定时编译；
- 不做 embedding 聚类与语义重排；
- 不替代 research：compile 是“整理已有证据”，不是“调查新问题”；
- 不自动改写已发布的 authored 正文；
- 不在插件内调用模型。

## 10. 里程碑

| 阶段 | 内容 | 预计 |
|---|---|---|
| M1 | `plan` + `status`（确定性、CLI + deep MCP、单测） | ✅ 已完成 |
| M2 | B-1-1 子集 pilot，测引用通过率与每页成本 | 🟡 首簇 6/12，剩余 6 条来源不可读 |
| M3 | 325 条全子树 + 并发写冲突处理 | 1 天 |
| M4 | v2 冲突门禁（schema 迁移） | 另立项 |

## 11. Pilot 记录（2026-11-09）

> 本机 Wiki 是多轮迭代累积的测试数据，已在 pilot 结束后整体清空；下面的数字只保留方法学与成本参考，不对应当前磁盘状态。

- 作用域 `temp-section-B-1-1`（325 条）：plan 得到 4 簇 / 45 条计划 / 140 条 deferred；排除 51 条搜索页、12 条重复 URL。
- 首簇「TTS 语音模型」12 条：1 次 `fetch`（4 个 URL，1 个 capture）、2 次 `save`（r1 4 源 → r2 6 源）、1 次 `status`、1 次 `lint`。
- 结果：页面 `voice-models-tts-asr` r2（6 节 / 6 claims），覆盖 6/12；`lint` 0 issue。
- 剩余 6 条：5 个 linux.do 帖子的 provider 均返回不可解析/空内容，小红书返回 provider_error；没有把它们写成 claim。pilot 之后补了 `wiki_compile(action:"gap")`，可把这些 URL 记为 gap，使 `status` 区分 covered / gap / pending。
- 结论：引用门禁 100% 通过；成本约 7 次工具调用 + 6 次网页读取。

## 12. 风险

1. **成本**：325 条已需数百次抓取；先 pilot，再决定是否扩到全包。
2. **噪音**：去噪规则必须可解释、可回退；计划里保留 `excluded` 明细。
3. **并发**：三个宿主可能同时写同一 Wiki；`expected_revision` 会冲突，v1 接受“重读合并”，不做自动合并。
4. **审阅自证**：`review` 仍是调用方声明；compile 不改变这一点，文档必须继续写清。
