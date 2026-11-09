# 工具面收敛任务书：CLI / MCP 分工与可验证调研

> 2026-11-07 · 依据：`planning/2026-11-hardening-plan.md`（已完成）＋ `.bench/report-mcp-vs-cli.md`（7 轮实测）
> 定位：把默认 MCP 工具面收敛到「**10 个有清晰证据边界的原语 + 一套 CLI 执行器**」
> 目标是减少宿主选择与往返成本，同时完整保留空间上下文、时间上下文、外部证据回流和 Wiki 复用。

> **当前状态（2026-11-08）：实现批次已完成，验收批次未完成。** P0b 的 10 个原语、共享 locate core、短 ref/read/walk、兼容别名、quick 目录收敛、安装器探测、CLI 文件 ingest 和输出契约已落地。0.7.0 兼容截止逻辑与回归用例已实现；本地包版本已同步为 0.6.4，未发布。此前检查点在 Darwin / Python 3.9.6、隔离 XDG 配置与数据目录下有 882 项全量单测通过（4 项条件跳过）；本次未重跑全量套件。尚未完成的是宿主真实 15 题阶梯、Q1–Q5 质量基线及 Q2 gold matrix，以及 P1-4/P2-3/P2-5 的后续工作。不能据此宣称整份任务书已最终验收。

---

## 0. 一句话判断

**好的工具面 = 宿主掌舵推理与编排，插件提供确定的领域能力；CLI 与 MCP 共享同一套 core、schema 和寻址。**
入口按能力边界划分，不按任务发生在本地还是远端划分：Git、JSON 处理和批量编排交给宿主 shell；索引拓扑、外部鉴权搜索抓取、证据归档与校验由插件提供。

判定证据（7 轮同提示词回归）：

```
wall ≈ 24.3s + 3.15s × 步数        r = 0.902,  r² = 0.813
```

中位工具步数是主指标，wall time 用于解释变化；现有 7 轮回归中步数解释 81% 的时长方差。证据质量是有否决权的守门指标，不替代速度目标：Q1–Q5 任一缺失或不达标，整批不通过。

---

## 1. 六条设计原则（两份指导的合成）

| # | 原则 | 来源 | 落到本项目的判据 |
|---|---|---|---|
| A | 模型已经会做的，不包装成工具 | 你那份"按场景怎么落地" | `ls/cat/grep/git/jq/python` 一律不包装 |
| B | 本地确定性、结果大、人要复用 → CLI | 同上 | CLI 必须 `--json` + `--out` + 稳定退出码 |
| C | 需要鉴权 / 远程 / 跨客户端 / 集中审计 → MCP | 同上 | 外部搜索、Deep Research API 归 MCP |
| D | 领域索引 / 排序 / 拓扑，shell 做起来很贵 → 原语 | 实测 | `plan_scope` 0.07s 就是典型：模型自己写不出来 |

补充两条本项目特有的：

| E | 长任务（>10s）不占同步工具位 | 实测 | `plan_research` 23s 吃掉 22% 总时长，必须改成 `spawn` + `job` |
| F | 证据的确定性归并属于 core，不交给模型临场去重 | 现有实现 | URL/内容哈希、provider 来源、搜索覆盖与归档由 `ingest` 处理；Agentic Search 的判断仍归宿主 |

---

## 2. 目标形态

```
┌──────────────────────────────────────────────┐
│ Skill（≤60 行）：何时 locate / 何时转 CLI / 何时 spawn │
└───────────────┬──────────────────────────────┘
                │
    ┌───────────┴────────────┐
    │                        │
┌───▼─────────────┐   ┌──────▼──────────────────┐
│ MCP 默认档 10 个 │   │ CLI 执行器（全量）        │
│ tools/list ≤16.5k字符│   │ br … --json / --out      │
│ 跨宿主自动发现   │   │ 人机共用 / 可管道 / 可 diff │
└───┬─────────────┘   └──────┬──────────────────┘
    └───────────┬────────────┘
        ┌───────▼────────┐
        │ 同一 core      │
        │ BookmarkIndex  │
        │ + archive/wiki │
        └────────────────┘
```

**铁律：MCP 与 CLI 共享同一个 core、同一份返回 schema、同一套 `ref`。** 换入口不换心智模型。

---

## 3. 工具归属总表（默认 MCP 10 个 + CLI）

### 3.1 MCP 默认档：10 个原语

| 工具 | 签名 | 覆盖的现有工具 | 为什么必须是原语 |
|---|---|---|---|
| `locate` | **当前实现**：`locate(text?, url?, in=["canvas","wiki","archive"], source_id?, section?, folder_id?, tags?, tag_colors?, has_note?, has_tags?, metadata_match="all", limit=8, offset=0, handle?, refresh=false)`（`text`/`url` 二选一；或只给 `folder_id` 列子项；或只给元数据过滤（tags/tag_colors/has_note/has_tags）枚举命中；或只给 `package_path` 导入单卡/包并返回来源摘要，`in` 单 scope）；Canvas、Wiki revision、archive capture 均已有 adapter | `search_bookmarks`、`lookup_url`、`search_archive`、`wiki_search`、`wiki_list`、`plan_research` 的本地候选段 | 统一入口保留各 scope 的 evidence kind、revision/capture provenance 和验证状态；Canvas 承担元数据过滤，Wiki/archive 拒绝伪造 Canvas 条件 |
| `read` | `read(ref, …)`；也接受 Wiki `page_id/revision` 或 research `research_id/evidence_source_id(s)` | `get_context`、`wiki_get`、`research_source` | Canvas 短 ref 绑定 source version；Wiki ref 固定 revision；archive ref 固定 capture/hash；research source 保留 content state |
| `walk` | `walk(ref, dir="out", depth=1)` | `traverse_graph` | 沿 Canvas edges / memberships 多跳遍历，shell 难以稳定复现 |
| `search` | `search(query, targets?, providers?, limit=8)` | `search_web` | 需要鉴权、并发、provider fallback、失败与覆盖记账；只返回外部发现结果，不声称页面正文已核验 |
| `fetch` | `fetch(urls, provider?, archive=true, capture_id?, offset?)` | `fetch_web` | 已知 URL 的多页并发读取、内容状态分类、归档与同一捕获续读；保留预算和 provider fallback |
| `ingest` | `ingest(batches, archive=false)`；内联最多 16 条结果、序列化 payload ≤8,000 字符 | `merge_search_results` | 宿主原生搜索结果回流后，由 core 按规范 URL / 内容哈希归并、RRF 排序、保留 provider 来源与覆盖；超预算时宿主写 JSON 文件，再由 CLI 读取，不把已生成的搜索结果重复塞回上下文 |
| `save` | `save(kind="wiki", page, sources, expected_revision)` | `wiki_write`、`wiki_acknowledge` | 精确引用、来源文本或不可变捕获、书签引用、修订冲突与新鲜度校验必须集中执行 |
| `spawn` | `spawn(task="deep_research"|"fetch"|"ingest"|"research", args)` → `job_id` | `research_service_start` | `deep_research` 提交外部 API 长任务；`fetch`/`ingest`/`research` 进入本地持久化作业队列（`br job worker` 消费，三宿主共享） |
| `job` | `job(job_id|external_id, action="status|result|cancel")` | `research_service_status`、`research_service_result`、`research_service_cancel` | 本地 `j-…` 作业与外部 provider 作业统一观察；状态、结果、取消一致 |
| `health` | `health()` → ≤200 字符摘要 | `index_status`、`research_services` 的就绪摘要 | 热路径诊断要短；完整预算、provider 配置和维护操作走 CLI `br route` / `br doctor` |

### 3.2 CLI：其余全部及批量工作流

| CLI 命令 | 覆盖能力 | 替代掉的 MCP 工具 |
|---|---|---|
| `br sync <path>` | 导入/同步/快照 | `sync_package` |
| `br source list\|history\|merge\|remove` | 源管理 | `source_history`、`source_merge`、`source_remove` |
| `br config get\|set` | 偏好配置 | `get_settings`、`update_settings` |
| `br route` | 路由/预算/就绪诊断 | `discovery_bundle`、`research_route`、`research_readiness`、`search_providers`、`research_services` |
| `br doctor` | 离线自检 | （已有） |
| `br archive` | 存档检索/归并 | `search_archive`（批量与维护用法） |
| `br ingest` | 归并宿主搜索结果；可选归档 | `merge_search_results` 的 CLI 入口，与 MCP `ingest` 共用 core |
| `br dupes` | 重复 URL 报告：分组、份数、建议保留项（只读，不改包） | （新增） |
| `br locate` / `br ingest --input <file>` | `locate` 复用共享 core；`ingest` 从文件读取大批次并调用 `fuse_results` | 与 MCP 原语共用业务 core；其他原语仍可通过 `br research/wiki/fetch-web` 等现有 CLI 命令调用 |
| `br wiki lint\|refresh\|work` | Wiki 维护 | `wiki_lint`、`wiki_refresh`、`wiki_work` |
| `br research plan\|record\|finish\|coverage\|inventory` | 深度研究流程 | `research_start`、`research_record`、`research_finish`、`research_coverage`、`research_inventory`、`research_import_evidence`、`research_service_import` |
| `br job submit\|list\|status\|result\|cancel\|worker` | 本地作业队列与单例 worker | （新增） |
| `br bench …` | 基准回归 | （新增） |

### 3.3 替代、弃用与保留

| 现有工具 | 处置 |
|---|---|
| `merge_search_results` | 改名为 `ingest`，保留 `fuse_results` core；不能用 Skill 去重替代 URL / SHA-256 归并、来源留痕和可选归档 |
| `research_services` | 汇总状态进入 `health`，完整能力诊断进入 `br route` |
| `agentic_search` | 不并入通用 `spawn`；宿主负责 Agentic Search 的迭代与推理。插件现有模型回答通道放入显式 `deep` / provider 专项入口 |
| `lookup_url` | **并入** `locate(url=...)`，仅表示本地索引命中；要读取页面正文仍调用 `fetch` |
| `wiki_list` / `wiki_search` | **并入** `locate(in=["wiki"])`，返回页面 ref 与修订号，不混入 Web 搜索发现结果 |
| `get_context` / `traverse_graph` | **并入** `read` / `walk` |
| 被默认原语替代的旧工具（`search_bookmarks`、`lookup_url`、`search_archive`、`wiki_search`、`wiki_list`、`get_context`、`traverse_graph`、`research_source`、`search_web`、`fetch_web`、`merge_search_results`、`wiki_write`、`wiki_get`、`wiki_acknowledge`、`research_service_start/status/result/cancel`） | P0b 起从默认 `quick` 移除，改由 10 个原语承接；all/deep 兼容目录仍保留，用差分等价验证结果集、排序、分页、错误和 provenance。旧 description 已标 `[deprecated→目标]`，0.6.x 兼容期内旧 handler 仍可调用；**0.8.0 起 quick 拒绝非契约旧工具调用，并移除旧 schema 与 handler（原定 0.7.0，因测试迁移未完成顺延一个版本）**。未被替代的 deep 工具保持冻结 |

### 3.4 净效果

| | 现在 | 目标 |
|---|---:|---:|
| MCP 默认工具数 | P0b 前 `Settings.QUICK_TOOLS` 有 26 个入口 | **10 个有清晰证据边界的原语** |
| MCP 全量目录 | P0a 前 47 个工具；加入 10 个兼容原语名称后当前 57 个 | 未被替代的 deep 能力行为冻结；被新原语替代的旧入口按 P0b 弃用、0.7.0 删除 |
| MCP tools/list | P0a 前 quick：25 个工具；生产完整 JSON-RPC 输出 `len()` = 31,831。新 quick 基线：10 个、12,996；本轮当前 quick：10 个、12,959；legacy 名称集当前 schema：25 个、32,132。全量目录 57 个、68,752 为 2026-11-07 早先实测 | 默认档完整生产 JSON-RPC 响应含换行 ≤16,500 字符；以固定脚本的生产序列化结果为唯一回归口径 |
| 单次响应信封占比 | 48%（实测 100,961 字符里 48,671 是元数据） | **≤10% 的重复元数据**；来源、版本、provider、内容状态和失败信息不得裁掉 |
| 发现入口数 | 本地索引、插件 Web、宿主 Web 各有入口 | 本地统一 `locate`，外部统一 `search`，宿主结果统一 `ingest` |

工具项预算按紧凑序列化后的 `{name, description, inputSchema}` 计：`locate` ≤2,400、`save` ≤2,800、`fetch` ≤2,100，其余每项 ≤1,600 字符；每个 `description` ≤700 字符。单项预算是上限，完整 tools/list 的 16,500 字符仍是硬门槛。

---

## 4. 统一契约（比工具数量更重要）

### 4.1 短引用 `ref`

现用 id 形如 `tempId_20261026_hash_1i5z632`（28 字符），单轮出现 126 次、3,528 字符。改为短引用，但不能丢失来源和版本绑定：

```text
ref 格式：<kind><scope><seq>  例：b-k9d4-1 / w-p3a1-2 / a-91f0-1
解析绑定：{kind, source_id, source_version_id | capture_id | wiki_revision, object_id}
规则：跨工具通用；同一返回批次内无歧义；版本更新后仍可读旧版本或明确返回 stale_ref。`ref` 是由登记表解析的 opaque handle，绑定 `{kind, source_id, object_id, source_version_id | capture_id | wiki_revision}`；生成短 scope 时必须做冲突检测并确保唯一，不能用截断 checksum 作为唯一性保证，也不能把多候选歧义留给宿主消解。
```

任何工具**返回 `ref`、接受 `ref`**。ref 是短寻址句柄，不替代权威 ID；需要审计或长期引用时，响应可展开 source / version / object ID。

### 4.2 响应信封 ≤10%

```jsonc
// 现在（每次调用都重复）
{ "source": {"checked_at":…,"completeness":…,"snapshot_path":…,"version_id":…,"aliases":[…]},
  "refresh": {"performed":true,"index_updated":false,"requested":true,"mode":…,"sync":{…}},
  "query_scope": {…9 个 null 字段…}, "counts": {…}, "_compact": {…} }

// 目标：保留解释证据所需的字段，只压缩重复的 envelope
{ "hits": [{"ref":"b-k9d4-1", "source_kind":"canvas", "source_id":"...",
             "version_id":"...", "evidence_kind":"bookmark_instance", "title":"NFFA 2026.5/6th",
             "why":{"terms":["2D","3D","note"], "fields":["path","note"], "match_mode":"literal"}}],
  "next": {"tool":"read", "ref":"b-k9d4-1", "reason":"inspect_card"}, "v":"v-e5d7" }
```

`why.terms` 列出实际命中的查询词，`why.fields` 只列出这些词实际命中的字段（书签可为 title/note/tags/path/url，Wiki/archive 使用各自字段名），`match_mode` 标明 literal/alias 等匹配方式。metadata 条件是否满足只放在顶层 `filters`，不得把 `has_note`/`has_tags` 的满足伪装成词命中字段。`why` 是命中解释，不是相关性结论。`source`/`refresh` 的重复诊断块仅在变化时返回完整内容；不变时可用 `v` 引用缓存版本。`v` 只能折叠 aliases、snapshot_path、refresh.sync 等可恢复的诊断 metadata，绝不能替代 hit 上的 source/version 身份。每个 hit 每次都保留解释证据需要的 `source_kind`、`source_id`、`source_version_id` / `wiki_revision` / `capture_id`、provider、retrieved_at、content_state 等适用字段；调用者不得依赖先前读过另一个 hit 才能定位。错误、部分失败、过期和未核验状态不得被压缩掉。信封目标按“可缓存重复 metadata 字符 / 总响应字符”计算，证据字段不计作可裁剪的 metadata。

### 4.2.1 locate 参数与所有权

P0a/P0b 的 locate 查询参数矩阵固定为 15 项：`text`、`url`、`in`、`source_id`、`section`、`folder_id`、`tags`、`tag_colors`、`has_note`、`has_tags`、`metadata_match`、`limit`、`refresh`；分页控制另有 `offset` 与不透明的 `handle` 两项。`text` 与 `url` 二选一；列目录可只给 `folder_id`；纯元数据查询可只给 `tags`/`tag_colors`/`has_note`/`has_tags`。续读请求改为提供 `handle` 与 `offset`；当前已支持单一 `in` scope：Canvas、Wiki 或 archive。Canvas 才接受 `source_id` 和 metadata filters；未指定 Canvas `source_id` 时只能选唯一 live 源，否则返回 `source_required`。`metadata_match` 只组合 Canvas metadata 条件，不能改变词命中的定义。

locate 的规范化、停用词处理、口语 metadata 识别、排序、分页和 `why` 生成属于共享 core；MCP 与 CLI 只负责参数校验、调用和传输。P0a 可以暂时保留 MCP 薄包装，但不得在 CLI 复制规则；新增的 core 测试必须覆盖两入口逐字等价。

### 4.3 大结果给句柄

```jsonc
{ "hits": [ ...前 8 条... ],
  "more": { "handle": "h-7f3a", "offset": 8, "total": 42 },
  "next": {"tool":"read", "handle":"h-7f3a", "offset":8, "reason":"continue_results"} }
```

超过 ~4k 字符一律如此，不再整块灌上下文。只要响应声明 `truncated: true`，就必须同时提供可续读的 `more:{handle,offset,total}` 和结构化 `next`；没有句柄时不得返回静默截断标志。P0a locate 已实现 `offset`、进程内不透明 `handle`、`more` 和 `next`，但不声明 `truncated`；后续 P0b/P1 需将同一 contract 扩展到其他原语，并替换成长生命周期的跨工具 ref/句柄。

### 4.4 每个响应带结构化 `next`

指出下一步的工具、ref 和原因，但不替宿主决定研究结论或掩盖用户选择。`next` 是建议而非强制工作流；保留 `plan_research.next_action` 的有用信息，避免返回 8k 的无关 blob。

### 4.5 CLI 侧的同等契约

```text
br locate "3D/2D 英文名 带 note" --in canvas --limit 8 --json
br read b-k9d4-1 --part card --json
br walk b-k9d4-1 --depth 2 --json
br search "question" --providers exa,jina --json
br ingest --input host-results.json --archive --json
br ingest --input large-host-results.json --archive --json # 大批次从文件读，不内联回传
br fetch https://… --max-total-chars 10000 --json
br save --kind wiki --input page.json --expected-revision 2 --json
br spawn deep-research --input q.json --json        # → {"job":"j-91c","external_id":"…"}
br job j-91c --json [--out report.md]
br locate … --out hits.json --quiet                 # 大结果落盘，stdout 只回摘要
```

统一要求：`--json` 稳定 schema、`--out` 落盘、业务结果走 stdout、日志走 stderr、稳定退出码（0/1/2/3）、写操作支持 `--dry-run`。

---

## 5. 为什么这套对"千奇百怪的需求"也快

五条机制，全部与具体任务无关：

1. **长尾不靠工具。** 任何没预见的任务，模型用 `bash + br --json + jq/python` 组合就能做，不新增 schema 税。
2. **热路径保留少数领域原语。** 索引语义、拓扑、鉴权搜索、正文抓取、证据归并与引用校验由 core 做；宿主擅长的 Git、推理和 agent 协调不复制进插件。
3. **证据边界可见。** Web 搜索是 discovery；fetch 才取得页面正文；ingest 只归并与留存搜索结果，不构成事实核验；Wiki 引用必须回指实际读过的文本或不可变捕获。
4. **组合不付重复税。** 统一 `ref` + 可续读句柄 + 精简重复 envelope，降低跨工具传 ID 和截断的成本；响应精简不能删掉来源、版本和失败状态。
5. **新增工具的闸门。** 只有满足"5 类任务里 ≥3 类复用 **且** 中位步数 >6"才允许增加默认 MCP 原语；否则先写 Skill 或 CLI。

### 5.1 任务类 → 入口映射（验证通用性）

| 任务类 | 典型请求 | 主入口 | 说明 |
|---|---|---|---|
| T1 精确查找 | "url 含 x 的条目在哪" | CLI `br locate --exact` | 1–3 步 |
| T2 模糊定位 | "关于 3D/2D、英文名、带 note 的书签" | `locate` | 4–8 步 |
| T3 空间上下文 | "这张卡片旁边是什么、连到哪" | `read` + `walk` | 原语 |
| T4 时间上下文 | "最近新增了什么、git 改了什么" | 目标 Canvas 仓库的 CLI `git` + `br source history` | Git commit 历史与插件 source snapshot history 是两种时间证据，分别读取 |
| T5 外部搜索 | "搜 X，补上宿主结果并比较来源" | 宿主搜索 + `search` + `ingest` | 保留 provider/query/rank 和失败覆盖，不把链接重合称为事实印证 |
| T6 外链调研 | "读这 3 个 URL 并总结" | `fetch` | 正文、内容状态、捕获版本与后续分页 |
| T7 深度调研 | "调研 X 并出报告" | 宿主定方向；Deep Research API 用 `spawn` + `job` | 插件提交外部长任务，宿主读结果并核查原始来源 |
| T8 沉淀与复用 | "写进 Wiki，之后按来源找回来" | `save` → `locate` → `read` | 精确引文、书签 ref、页面修订和 freshness |
| T9 编辑/运维 | "把 note 批量改一下 / 诊断三个宿主" | CLI（`--dry-run` → `--apply`） | 人有审计需要；安装和 Git 走 shell |
| T10 未知任务 | 任何没想到的 | CLI 组合 + Skill | **不因未预见的任务自动加工具** |

**T10 是这套设计成立的关键：未知任务走宿主组合能力；默认插件工具只覆盖难以稳定复现的领域能力和证据边界。**

---

## 6. 批次计划

### P0a（约 6–8 个工作日；locate 步数实验先行）

| 编号 | 工作项 | 验收 |
|---|---|---|
| P0a-0（1–2 天） | 以加法方式给 `plan_scope` 加 Canvas-only `locate`，随后扩展为 Wiki/archive 单 scope adapter；实验性 quick 增至 26 个入口，旧面用 `--exclude locate` 保持 25 个对照；规范化、过滤推断、排序、`why` 和分页已下沉共享 core，MCP/CLI 只保留薄包装；文本查询必须用 `plan_scope` 产出的 `matched_terms` 查询，不能把整句人话作为一个 target；按 `term_cards` 稀有度排序，避免停用词挤掉目标条目。Canvas 的 metadata filters 必须透传，Note/Tag 口语不能当自由文本子串。Wiki/archive 必须保留 revision/capture provenance 和 content_state，不伪造 Canvas 条件。候选摘要最多 3 张卡片，只保留 `section_id/matched_terms`（URL 只保留 `url/matched_terms`）；`more/next` 使用携带原查询与过滤条件的 HMAC 签名句柄，可跨 CLI 进程续读 | 每个真实提示词至少 3 次；每次 `hits ≥ 1` 且包含预先登记的目标条目，再比较中位步数，locate 组目标 ≤12；各 evidence kind 的 provenance 和 `why` 字段均需可核对；宽查询必须能通过 `more/next` 取到下一页且不重复，且 CLI 新进程与 MCP 调用行为一致。单次 22 步只是热点记录，不当作中位数；若目标条目缺失，整组不通过，不得用 0 命中证明步数收益。保存原始提示词、目标条目、trace、输出和 Q1/Q2 核验结果 |
| P0a-1 | 新增 `scripts/bench_tools_list.py`：经真实 initialize → tools/list 路径捕获完整生产 JSON-RPC 输出，按含换行字符串 `len()` 计数；quick 基线保存在 `.bench/tools-list-baseline.json`；`legacy` preset 固定恢复 2026-11-06 的 25 个旧工具名 | 与 stdio 生产输出逐字符一致；支持 `--exclude` 与 `quick/legacy/all/deep`；quick 基线 12,996 字符，本轮当前 quick 10 工具、12,959 字符；legacy 名称集 25 工具、32,132 字符。legacy 使用当前 deprecated schema，不是历史 31,831 字符逐字 schema 快照；不再用独立 schema 求和或默认 JSON 分隔符作门槛 |
| P0a-2 | 新增 `scripts/evaluate_ladder.py` 和 `br bench ladder --preset legacy|quick`，生成 15 题采集模板并校验每题 3 次运行和 Q1–Q5；宿主需冻结真实提示、目标 ref、旧面输出与计时口径，并人工建立 Q2 claim/source gold matrix | `.bench/ladder.json` 已生成 legacy-25 空模板并记录所需 `BOOKMARK_RESEARCH_TOOL_SCOPE` 名单；prompt/ref/run 仍为空，模板不代表冻结了任务或跑过宿主。Q1/Q3–Q5 按 trace 自动统计；Q2 标注与真实跨宿主 traces 待运行，预计全量 5–6 个工作日 |

先由 P0a-1 固定测量口径，再由 P0a-2 捕获旧面的 15 题输出后完成 P0a-0 的速度对照；Q2 的人工标注可与 locate 对照并行。P0a 已完成共享 core、参数矩阵、Canvas/Wiki/archive 单 scope locate、续读和 10 个兼容原语名称；短 ref codec、quick 收敛、旧入口弃用标记和 CLI 输出已落地；15 题 Q1–Q5 gold matrix 仍需宿主运行并人工完成 Q2 标注。P0a 的长身份 ref 只是调试字段，不纳入 ref 字符占比验收。单题 locate 对照不替代完整 15 题阶梯。

### P0b（统一 contract 与新默认面）

| 编号 | 工作项 | 验收 |
|---|---|---|
| P0b-1 | 定义共享 core contract 与 10 个原语名称；已接入 `locate/read/walk/search/fetch/ingest/save/spawn/job/health` 的兼容 handler，旧入口仍保留 | 共享 locate core、短 ref、read/walk ref 解码、适配器和参数矩阵已接入；0.6.x 保持旧 handler 兼容；0.7.0 起从所有 MCP 目录和调用入口移除被替代名称，版本判断与回归用例已实现。新原语内部仍复用领域实现，不保留第二套业务规则 |
| P0b-2 | 精简重复 envelope、加入 `health` 短摘要、引入 source/version 绑定的短 `ref`；把 P0a 的长身份 ref 替换为登记表句柄 | `health()` 已是有界摘要；短 ref 已做碰撞检测并可供 read/walk 解析；Canvas `read(ref)` 默认只返回目标条目、祖先和必要来源元数据；真实包验收上限 ≤4,096 字符（当前实测 3,616），fixture 回归检查默认路径 <2,048；`collection="all"` 显式返回完整上下文；首次来源诊断可用短 `v` 扩展。整体重复 metadata ≤10% 仍由 15 题阶梯测量验收 |
| P0b-3 | 将本地 `locate`（Canvas / Wiki / archive）收敛到共享 contract；每个 hit 带 `why.terms` 与实际匹配的 `why.fields` | Canvas/Wiki/archive 单 scope、revision/capture provenance、content_state、metadata filters、续读和 why 分离已落地；仍需 15 轮验证跨 evidence kind 的解释字段一致性 |
| P0b-4 | 外部 `search` 与宿主 `ingest` 使用结构化批次和 `fuse_results`；`ingest` 兼容 handler 已限制 16 批 / 8,000 字符 | `fuse_results` 负责 URL/内容哈希归并并保留来源/覆盖/失败；超预算 MCP 输入已拒绝，`br ingest <file>` 已提供文件入口 |
| P0b-5 | 默认工具面已切为 10 个；旧入口从 quick 的 `tools/list` 隐藏、all/deep 保留兼容并标 deprecated；完整生产 `tools/list` JSON-RPC 响应 ≤16,500 字符，并满足逐工具项与 description 预算 | 本轮实测 quick 10 个、12,959 字符；0.6.x quick 仅过滤发现、不拒绝旧 handler 调用；显式 `tool_scope` / 宿主环境 allowlist 仍为硬限制。Codex 与多宿主安装自检接受新原语目录；0.7.0 起被替代旧名从全目录及 tools/call 公共入口移除，测试已加入但本轮未运行。此前全量 882 tests 结果不覆盖本轮改动 |

**P0 总门槛：15 题阶梯中位步数目标 ≤12（现有单次热点为 22）；Q1–Q5 全部达标，否则整批不通过。Q2 在 P0 最终验收全量复核 15 题。**

### P1（下周）

| 编号 | 工作项 | 验收 |
|---|---|---|
| P1-1 | `read` / `walk` 合并 `get_context` / `traverse_graph` / `wiki_get` / `research_source`；接受 locate 短 ref 并保留 source version 与分页 | Canvas/Wiki/archive ref 可按绑定版本回读；research source 可读保存正文；图遍历只适用于有匹配节点的 Canvas ref |
| P1-2 | `fetch` 保留 1–16 URL、预算、provider fallback、content_state、capture_id/offset | 同一捕获续读不触发网络；无正文与低质量页面不误报为可引用 |
| P1-3 | CLI `--json/--fields/--out/--quiet` 递归统一，错误走 stderr，partial 使用稳定退出码；`ingest --input` 支持文件输入 | 机器输出、投影、完整落盘和写入回执可组合；普通成功=0、错误=1、参数错误=2、partial=3、中断=130；静默截断为 0 |
| P1-4 | 大结果句柄 `more:{handle,offset}` | >4k 字符响应全部走句柄 |

### P2

| 编号 | 工作项 | 验收 |
|---|---|---|
| P2-1 | `spawn`/`job` 已映射 Deep Research API；local resumable research 留在 CLI/deep；不接管宿主 Agentic Search | 通过兼容服务层提交、观察、读取、取消及恢复 external ID；需宿主对已配置 provider 做端到端验证 |
| P2-2 | `merge_search_results` 已映射为 `ingest`，保留宿主结果回流；高级 provider-specific `agentic_search` 留在显式 deep 入口 | MCP/CLI 共用 `fuse_results`，大批次走 CLI 文件输入；搜索回流可重复执行并保留 provenance；默认 MCP 原语数为 10 |
| P2-3 | 将 P0a 建立的 tools/list 序列化与 tokenizer 测量纳入固定回归 | 完整生产 JSON-RPC `tools/list` 响应 ≤16,500 字符；每个工具项和 description 预算达标；token 数单独实测 |
| P2-4 | Skill 重写为 ≤60 行流程，注明宿主掌舵、何时 locate/search/fetch/ingest/save/spawn | 英文 Skill 39 行、中文指南 34 行；默认原语、宿主掌舵、证据类别、引用要求与 Git 说明已同步 |
| P2-5 | 冻结现有 47 工具的 `deep` 全量目录行为 | 0.7.0 版本截止过滤与旧调用拒绝已实现；未替代工具的目录/schema 冻结快照仍未建立。被替代入口从公共工具目录和 dispatch 移除，供新原语复用的内部实现保留 |

---

## 7. 通用性验收：15 轮任务阶梯

**不是再测一次定位，而是每类 3 题；步数和 wall 不能代替证据质量。**

| 类 | 三题覆盖方向 | 记录字段 |
|---|---|---|
| L1 精确 | URL 精确查找、本地 URL 命中、无命中 | 步数 / wall / 峰值上下文 / 输出 token / envelope 占比 / 命中准确率 / 静默失败 |
| L2 模糊 | 3D/2D、中英别名、note/tag 条件 | 同上 + 目标召回率、字段解释是否正确 |
| L3 空间 | 邻居、连线方向、组包含和跨节点路径 | 同上 + 路径/方向/Canvas source version 正确性 |
| L4 时间 | 近 7 天新增、Git 改动、source snapshot 变化 | 同上 + Git commit 与导入版本是否正确区分、日期精度 |
| L5 调研+沉淀 | 宿主搜索回流、读 3 个 URL、Deep Research API、Wiki 写后复用 | 同上 + provider 覆盖、原文可读、引用逐字匹配、来源版本/freshness、后续 Wiki 检索复用 |

15 轮阶梯为每类 3 题，每题至少跑 3 次并报告中位步数。Q1、Q3–Q5 统计全部执行；Q2 人工审阅每题中位步数那次输出中的所有事实性 claim。步数是主指标；以下 Q1–Q5 是逐批否决门槛，缺少任何一项或不达标即整批不通过。

| 指标 | 定义 | 门槛 |
|---|---|---|
| Q1 引用逐字匹配率 | 引用的 quote 是否逐字存在于对应 source text / immutable capture；匹配引用条目数 ÷ 全部引用条目数 | 当前参考集 15/15（100%）；改动后不低于冻结基线 |
| Q2 声称-引用一致率 | 有至少一条经审阅引用支持的事实性 claim 数 ÷ 全部事实性 claim 数；按 claim-source gold matrix 计分 | P0a 全量 15 题建立 B2；P0 最终验收 15 题全量复核且 ≥B2。此后每个小批次轮换分层抽审 3 题，跨连续批次覆盖 5 类任务；抽样得分不得低于这 3 题的冻结基线。Wiki lint 的 `semantic_support=not_scored`，不能把结构校验冒充语义判定 |
| Q3 content_state 漏报数 | 将非 `usable` 页面当作可引用正文或未披露其状态的次数 | 0 |
| Q4 静默截断次数 | 结果被 MCP 上限、CLI 截断或分页切片截断，且响应无 `more/next` 或宿主没有续读/声明的次数 | 0 |
| Q5 覆盖缺口数 | provider/target 失败、未尝试或被放弃，但响应未显式报告该缺口的次数 | 0 |

Q1、Q3–Q5 每批都对完整 15 题的全部执行按 fixture / trace 自动统计；Q2 首轮 gold matrix 覆盖全部 15 题各自的中位步数输出，后续每批轮换人工复核 3 题的对应中位步数输出，使连续批次覆盖 5 类任务，并与相同题目的冻结基线比较且不得退化。P0a 记录 B2 的具体百分比、分子、分母和逐 claim 标注；P0 最终门全量重跑 Q2 并达到 B2。没有冻结的题目级基线时不得声称 Q2 通过，也不得把 Q2 宣称为全自动语义验证。

工具数与工作流质量分别判断，不用单一步数门槛替代：

| 中位步数 | 结论 |
|---|---|
| >6 | 值得做原语 |
| 3–6 | 只需 Skill 教，不加工具 |
| ≤3 | 别做工具，CLI 就够 |

仅当目标工作流中位步数 >6、整体任务阶梯中位步数下降、至少 3 类任务重复受益且 Q1–Q5 全部达标，才允许增加默认原语。报告固定用表格，禁止用单次 wall 或单次步数下结论（实测同配置方差 1.8 倍）。

---

## 8. 红线

1. **不为单个场景加默认工具。** 任何新增默认 MCP 原语，必须附 15 轮阶梯里 ≥3 类的数据，中位步数有收益且 Q1–Q5 全部达标。
2. **不动索引与快照语义。** 本轮只改入口层，`bookmark_index.py` 的排序、分页、实例与版本语义保持不变。
3. **不写画布包。** 所有画布写操作仍归宿主或用户明确执行的 CLI 命令。
4. **宿主掌舵 Agentic Search。** 插件 `search` 提供可组合检索；`ingest` 归并宿主结果；`spawn/job` 管理 Deep Research API 等外部任务，不替宿主规划普通搜索轮次。
5. **搜索摘要、抓取正文、归档捕获、Wiki 修订必须有不同 evidence kind。** 结果可以统一寻址，不能统一成无来源的 `text`；网页和卡片内容是待判断的证据，不是宿主的操作指令。
6. **未替代的 deep 能力冻结。** 不新增或改变其行为；被新原语取代的旧入口可按 P0b 标 `[deprecated→tool]`、从 quick 移除；0.6.x 保持旧调用兼容，0.7.0 quick 必须拒绝旧调用并删除被替代 schema/handler，避免双份语义永久并存。
7. **CLI 与 MCP 不得出现两套业务规则。** 新增能力先进 core，再由两个入口薄包装。
8. **中位步数是主指标，证据质量有否决权。** wall、token、正确性、来源覆盖、引用核验和后续复用作为解释与守门数据一并报告。

---

## 9. 复现与验证命令

```text
# 1) 现状基线（本轮实测）
#    c82b154c = MCP 58.0s / 9 步 ；7ddd1600 = MCP 103.5s / 22 步
#    CLI 五轮 93.7–175.1s ；回归 wall ≈ 24.3 + 3.15×步数

# 2) P0 完成后重跑同一提示词，目标：任务阶梯中位步数 ≤12、重复信封 ≤10%、Q1–Q5 全部达标

# 3) 15 轮阶梯
python3 src/cli.py bench ladder --preset legacy --file .bench/ladder.json
#    生成的是空采集模板；先冻结 15 个 prompt/target_refs，再按文件中的 required_tool_scope 配置宿主。
#    legacy 固定 25 个旧工具名，但 schema 是当前 deprecated 描述，不是旧版逐字 schema 快照。
python3 scripts/bench_tools_list.py --preset legacy --out .bench/tools-list-legacy.json
#    每题分别运行 legacy 与 quick 至少 3 次；宿主 trace 需人工保存，CLI 不会伪造或自动执行宿主对话。
python3 scripts/evaluate_ladder.py .bench/ladder.json --out .bench/ladder-summary.json

# 4) 工具面审计（P0a-1 建立脚本）
python3 scripts/bench_tools_list.py --preset quick --out .bench/tools-list.json
#    捕获生产 stdio tools/list 完整响应行（含换行）并取 len()；默认 10 工具目标 ≤16,500 字符。
#    不用 len(TOOL_SCHEMAS)、逐项默认分隔符求和或工具数量代替生产 tools/list 长度。

# 5) 本地验证（不发 npm；当前基线 Darwin / Python 3.9.6，隔离用户态数据）
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
XDG_CONFIG_HOME="$test_root/config" XDG_DATA_HOME="$test_root/data" \
  python3 -B -m unittest discover -s tests -p "test_*.py"
# 记录 Python / OS、通过数、失败数、error 数和 skip 数；skip 数依环境而变，不能只抄总数。
python3 scripts/launcher.py verify
```

---

## 10. 一句话收尾

**先问宿主是否擅长，再问 shell 能否稳定完成，最后问插件是否需要承担可复用的领域规则或证据责任。**
推理、Git 和普通编排留给宿主；索引拓扑、鉴权检索、证据归并与引用校验进入共享 core。默认原语数量是验收约束，不是高于证据质量的目标。
