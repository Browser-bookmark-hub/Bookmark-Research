# 计划书实包验证（2026-10-19）

> 验证对象：[搜索路由与触发计划](plugin-search-routing-plan-2026-10-19.md)（验证时为其 v1；修订后的 beta.16 计划见同一路径的修订版 2）。
>
> 数据包：`/Users/kk/Downloads/kk/Bookmark-Canvas/bookmark/书签画布`（`source_id = github-bookmark-canvas`）。
>
> 运行版本：`0.5.0-beta.15`，44 个 MCP 工具。
>
> 方法：真实 MCP 调用 + 索引 SQL + `src/` 只读脚本测量。没有修改源包；索引测量使用 `/tmp` 副本；联网 `fetch_web` 测试新建了 1 个 6 页归档（副作用，见 §6）。

## 0. 结论

**诊断部分可信，方案部分还不能直接开工。** 计划书最关键的那组数字——19 个会话、102 次插件调用、某一轮 358,632 字符、插件占 64.4%——我都在 DSH 会话日志里复算到了原值。缺口也是真的：`plan_research` 不查 Wiki/归档、A-10-2 缺失文件仍排第一、`fetch_web` 会一次输出近 10 万字符。

但把计划书当 beta.16 施工图，会在真实包上遇到 6 类问题：

1. **Wiki/归档预检按“原问题”检索会直接返回 0**；必须先做词项构造，计划书没写。
2. **“Wiki current 直接复用”在当前库里没有样本**：5 页全部 `needs_review`。
3. **缺失文件“一删了之”会让 URL 质量明显变差**：A-10-2 排除后，A-10 给出的是一批首页、登录页和 Bing 搜索结果。
4. **“只用高置信度 dateAdded”不可行**：4,130 个书签里高置信度只有 1,043 条，38 个栏目里只有 1 个有高置信度时间。
5. **`get_context compact` 按计划书列的字段只降 37.9%，达不到 ≥50%**；`search_bookmarks` 的 compact 反而已经存在，且 limit=10 时降 51.2%。
6. **`fetch_web` 的 10k 总预算会把后几页压成 0 字符，却仍标 `usable`、仍算 `successful_url_count`**；“14 页 <10k”这个验收会掩盖“其实只读了前 3 页”。

| 维度 | 评分 | 依据 |
|---|---:|---|
| 基线与问题诊断 | **9 / 10** | 会话数、调用数、上下文占比逐项复现；缺口可实测 |
| 契约正确性 | **5 / 10** | 原问题检索、Wiki 状态、时间置信度、compact 比例、`route: null` 阈值均有反例 |
| 验收严谨性 | **5 / 10** | URL 多样性验收当前已通过；“14 页 <10k”不等同于读 14 页；缺少反例 fixture |
| 范围与 ROI | **5 / 10** | 6 个工作包、约 3 周；至少 3 处重复已实现能力；关键行为杠杆仍是 open question |
| 综合 | **6 / 10** | 适合做“需求库/问题清单”，不适合原样作为 beta.16 施工图 |

## 1. 基线与环境

### 1.1 计划书基线的复现

| 计划书 | 复算 | 判定 |
|---|---|---|
| 19 个 DSH 会话 | `~/.dsh/sessions` 下本工作区 19 个会话 | ✅ |
| 102 次插件调用 | 全部会话 106 次；扣掉本轮验证新增的 4 次 = **102** | ✅ |
| 某轮 358,632 字符、插件 64.4% | session `ac53db66` turn 4：total 358,632，plugin 230,943 = **64.4%** | ✅ |
| `fetch_web` 2 次 97,835 字符 | 同轮 2 次，97,835 | ✅ |
| `get_context` 8 次 73,110 字符 | 同轮 8 次，73,110 | ✅ |
| `search_bookmarks` 2 次 41,374 字符 | 同轮 2 次，41,374 | ✅ |
| `plan_research` 4 次 | 扣掉本轮 1 次 = 4 | ✅ |
| `wiki_search` 0 次 | 0 | ✅ |
| `search_web` 1 次 | 1（宿主自带 `web_search` 另有 2 次） | ✅ |

结论：这不是拍脑袋写的基线。计划书在“发生了什么”上是可靠的。

### 1.2 数据包与索引

| 项 | 实测 |
|---|---|
| 源包 JSON | 37 个 |
| Canvas 节点 / 连线 | 47 / 14 |
| 索引 items / bookmarks / unique URLs | 4,966 / 4,130 / 3,079 |
| 栏目 sections | 38 |
| `retained_missing_files` | `临时栏目/常规链式/A-10-2 Agent API｜Agent Runtime（云厂商）.json` |
| A-10-2 文件当前是否存在 | **不存在**（`find` 无结果）；Canvas 的 37 个 file 节点里也没有它 |
| 索引快照时间 | 2026-10-19 06:29:57 UTC |
| Wiki | 5 页 / 45 条 claim |
| Wiki 状态 | `wiki_lint` 5 页全部有 warning；`wiki_search` 命中的页面均为 `needs_review` |
| 归档文档（测试前） | 276 篇 / 301 次出现 |

一个容易忽略的点：A-10-2 不是“当前包里有文件但索引没读到”，而是**快照里曾经有、当前包已经删掉**。`refresh: true` 在 snapshot 模式下不会重新同步，所以它会一直留在 `retained_missing_files` 里。计划书说“排除/标记”，但没有说是否要触发 `sync_package` 或如何处理“只有旧快照才知道的内容”。

## 2. 逐项验证

### 2.1 R1 预检入口

#### 2.1.1 当前 `plan_research` 确实没有预检字段

以“云厂商 Agent Runtime 有哪些变化”为例，返回字段只有 `terms / term_cards / cards / urls / task_shape / route / next_action / source / refresh`。没有计划书要求的：

`wiki[]`、`archive[]`、`freshness`、`fetch`、`deep_research`、`required_tools`、`skip_conditions`、`seed_queries`、`coverage`。

判定：**缺口成立**。

#### 2.1.2 A-10-2 仍排第一，且过滤后 URL 质量下降

当前返回：

| 排名 | 卡片 | 命中 | 分数 | 说明 |
|---|---|---:|---:|---|
| 1 | A-10-2 | 26 | 5.092 | **文件已缺失** |
| 2 | A-10 | 184 | 0.728 | 543 条的大卡 |
| 3 | A-1-1 | 26 | 0.511 | RAG 卡 |

在 `/tmp` 副本中删除 A-10-2 后重跑，结果变成：

| 排名 | 卡片 | 分数 |
|---|---|---:|
| 1 | A-10 | 0.864 |
| 2 | A-1-1 | 0.640 |
| 3 | A（永久树） | 0.480 |

排名上确实不再有 A-10-2，但 top 8 URL 变成：

- `https://www.huaweicloud.com/`
- `https://cloud-gpus.com/`
- `https://cloud.baidu.com/product-s/qianfan_home`
- `https://cloud.tencent.com/solution`
- `https://cn.bing.com/search?...`（Bing 搜索结果）
- `https://developer.baidu.com/`
- `https://huggingface.co/enterprise`
- `https://login.bce.baidu.com/...`（百度登录页）

A-10-2 原来给出的 AWS、Google Cloud、腾讯云、千帆 API 等具体入口反而没了。

判定：**“排除缺失文件”只解决了排名症状，没有解决“替代结果是否可用”**。计划书需要补充 URL 类型/质量策略，或者保留 stale 卡的 URL 并标注，而不是二值删除。

#### 2.1.3 Wiki 预检按原问题检索会返回 0

计划书写的是 `WikiStore.search(question, limit=3)`。实测：

| 查询 | 结果 |
|---|---:|
| `RAG 企业落地要点` | **0** |
| `RAG` | 4 页（含目标页） |
| `RAG 企业` | **0** |
| `RAG 落地` | **0** |

目标页 `rag-search-and-mcp-20260912` 是存在的，但多词查询没有命中。原因是 Wiki 搜索是字面/字符 grams 匹配，不是语义检索；整句问题不会自动拆成可命中的词。

判定：**按计划书字面实现会失败**。R1 必须先复用 `plan_terms` 做词项构造，再做 OR/加权合并；还要定义“至少命中几个词、是否允许单字面词”的门槛。

#### 2.1.4 “Wiki current 直接复用”在当前库里没有样本

计划书的 R1 测试第一项是“Wiki 命中 `current` → `wiki_get`，不触发 search”。实测：

- `wiki_lint` 检查 5 页，5 页均有 warning；
- 最新的 `embeddinggemma-2-local-deployment` 也是 `needs_review`（`newer_source_snapshot`）；
- `RAG` 目标页是 `needs_review`，还伴随 `source_input_changed` 和 13 条 `source_capture_expired`。

判定：**当前真实库的 current 命中率是 0/5**。R1 的主分支在真实数据上没有可验收样本；计划书应改用合成 fixture，或把 `needs_review` 的“低成本复用/确认”路径写清楚。现在直接跳到 `wiki_refresh`，RAG 页一次要刷新 13 个来源，和“≤8 次抓取”的预算也不一致。

#### 2.1.5 归档预检同样不能直接用原问题

计划书写的是 `RawLibrary.search(question, limit=5)`。实测：

| 查询 | 结果 |
|---|---:|
| `EmbeddingGemma 2 怎么本地部署` | **0** |
| `EmbeddingGemma` | 5 条 |
| `EmbeddingGemma 本地` | 3 条 |

判定：**与 Wiki 同样的问题**；必须词项化。好消息是归档条目带 `capture_id`，命中的正文和来源都在，预检复用是可行的。

#### 2.1.6 URL 多样性：计划书的验收当前已经通过

“云厂商 Agent Runtime”当前 top 8 覆盖：

华为云、火山引擎、CoreWeave、AWS、百度智能云（2 条）、Google Cloud、腾讯云 = **7 个厂商**。

计划书的验收是“top 8 至少覆盖 3 个不同厂商”，当前已经满足。

判定：**这项验收没有区分度**。真正的问题不是“厂商不够多”，而是 8 条里 7 条是厂商首页、1 条是文档页；没有 changelog、release notes 或 Agent Runtime 的产品页。计划书应把 URL 类型（homepage / docs / changelog / repo / login / search-result）纳入排序，而不是只做厂商 MMR。

#### 2.1.7 `route: null` 只在“完全没有字面命中”时成立

| 问题 | 结果 |
|---|---|
| `zzzzqqqq` | `cards: []`、`route: null` ✅ |
| `量子纠缠在农业育种中的应用` | 3 张卡（永久树/A-10/B-1-1），`host_iterative_research` ❌ |
| `量子纠缠` | 永久树 1 张卡（qbitai），`host_iterative_research` ❌ |
| `quantum entanglement agriculture breeding` | “添加 code优惠”1 张卡（QuantumNous/new-api），`lookup` + `direct_retrieval` ❌ |

最后一个例子尤其能说明问题：

- 命中词只有 `quantum`，指向 `QuantumNous/new-api`；
- 卡片分数 0.035、密度 0.005，显然不是相关内容；
- `task_shape_reason` 却写“the question names it（quantum points at one card）”，把偶然子串当成了“点名”，于是把研究型问题降档成 `lookup`。

判定：**计划书的“0 卡 → route null”守卫只覆盖完全无命中**；没有分数/密度/词项门槛，近义噪声会把 out-of-scope 问题送进研究路径。R1 需要新增 relevance floor，R3 需要修正 `lookup` 判定。

#### 2.1.8 高置信度时间不可行

SQL 统计（`github-bookmark-canvas`，bookmarks）：

| `added_at_confidence` | 数量 |
|---|---:|
| high | **1,043** |
| low | **3,087** |
| medium | 0 |

38 个栏目中：

- 有任意时间（high/low）：38 / 38；
- 有高置信度时间：**1 / 38**（只有永久树）。

计划书写“新鲜度排序只用高置信度 `dateAdded`，低置信度 ID 日期降权”。如果按“只用 high”实现，37 个临时栏目会全部失去时间；如果按“降权”实现，则需要给出权重，而计划书没有给。按当前数据，**必须保留 low 置信度时间作为弱信号**，并同时输出 `confidence`。

### 2.2 R2 Fetch 归属与上下文

#### 2.2.1 `handle`、`max_urls=16` 都不存在

| 调用 | 结果 |
|---|---|
| `fetch_web(return="handle")` | `arguments contains unknown fields: return` |
| `plan_research(max_urls=16)` | `arguments.max_urls is out of range` |

判定：与计划书“新增参数”的预期一致，当前没有。

#### 2.2.2 `capture_id` 续读已经存在

用 6 页 fetch 返回的 `capture_id` 调：

`fetch_web(urls=["https://www.huaweicloud.com/"], capture_id="20261019T142017089336Z-e53090c33e28", offset=4000, max_characters=1000)`

返回 `mode: archive_read`、`network_request_performed: false`。这说明“按 capture 续读”不需要新做；R2 的 `handle` 只是把“只回指针”做成一个返回模式。

#### 2.2.3 10k 总预算会把后几页压成空文本

6 个 URL，`max_characters=4000`、`max_total_characters=10000`，实测：

| 页 | 字符 | `content_state` |
|---|---:|---|
| 华为云 | 4000 | usable |
| 火山引擎 | 4000 | usable |
| CoreWeave | 2000 | usable |
| AWS | **0** | **usable** |
| 百度智能云 | **0** | **usable** |
| 腾讯云 | **0** | **usable** |

响应同时给出 `successful_url_count: 6`、`status: ok`。

判定：**预算是顺序耗尽的，不是公平分配**；“6 页成功”实际上只有前 3 页有正文。计划书说“14 页 <10k”，如果不改分配策略，14 页会变成“前 2–3 页有正文、其余空文本但仍 usable”。这会直接污染后续引用。需要：

- 每页最低配额或按页均分；
- 0 字页面标 `content_state=unavailable` 或 `evidence_incomplete`；
- `successful_url_count` 只计有正文的页；
- `handle` 模式与 text 模式分开验收。

#### 2.2.4 `discovery_bundle` 没有 capture_id/sha 语义

传 `sources: [{url, capture_id}]`，返回 `evidence: []`、`unavailable_sources` 一条，reason 为 `unavailable`。它没有从归档读正文。

传 `text_sha256`（且故意用整页 sha、只给摘录文本）时，bundle 仍然接受该文本，没有校验。

当前 `evidence[]` 只有：`id / url / title / published_at / characters / excerpt / excerpt_truncated`；**没有 `capture_id`、`text_sha256`、`text_origin`、`quote_verified`**。

判定：R2 要补的不是一个字段，而是“证据条目必须能回到归档并校验”的完整链路；计划书的 `text_sha256` 不匹配报错、`text_origin=host → quote_verified=false` 都还没落地。

#### 2.2.5 `get_context compact` 按计划书字段达不到 50%

对完整 context（70,010 bytes）：

| 投影 | bytes | 降幅 |
|---|---:|---:|
| 原始 | 70,010 | — |
| 去掉 `raw_json` | 45,823 | 34.5% |
| 再去 `description_md` | 44,829 | 36.0% |
| 再去 `revision` | **43,464** | **37.9%** |

单 collection：

| collection | 原始 | 去三字段 | 降幅 |
|---|---:|---:|---:|
| sections | 25,878 | 15,565 | 39.9% |
| nodes | 32,231 | 19,391 | 39.8% |
| edges | 8,663 | 6,227 | 28.1% |

判定：计划书 R2 的“compact 输出字符数下降 ≥50%”按它自己列的字段**达不到**。若目标是 `<20k`，需要按 collection 取数，或进一步投影 `path_json`、`ancestor_ids_json`、`preorder` 等字段；但 `description_md` 可能是栏目唯一说明，直接删有语义损失。

#### 2.2.6 `search_bookmarks compact` 已经存在，且达标

`search_bookmarks` 自 0.5.0 早期就有 `compact` 参数；`BookmarkIndex.search(compact=True)` 会走 `bookmark_output.compact_search`。

实测 `targets=["Agent"]`：

| limit | 原始 bytes | compact bytes | 降幅 |
|---:|---:|---:|---:|
| 10 | 29,386 | **14,332** | 51.2% |
| 20 | 57,134 | 24,980 | 56.3% |
| 50 | 131,328 | 50,409 | 61.6% |

计划书要新增的 `projection` 与现有 `compact` 是同一件事。**不要新增第二套投影参数**；把 Skill/默认值接到 `compact` 即可。

### 2.3 R3 触发规则

当前 `plan_research` 已经返回 `next_action.tools`：

- “云厂商…” → `["search_web", "fetch_web"]`
- “RAG 企业落地…” → `["search_web", "fetch_web"]`
- “EmbeddingGemma…” → `["fetch_web", "search_web"]`

计划书说新增 `required_tools`、`skip_conditions`、`seed_queries`。问题是：**这些和 `next_action.tools` 是同一层信号**。会话轨迹里宿主有时照 `next_action` 抓 URL（`plan_research → fetch_web`），有时不抓；增加一个字段不会自动改变。

另外，计划书把 `search_web 1/19` 当缺陷，但同一批会话里宿主自带 `web_search` 也只有 2 次，而插件 `fetch_web` 有 10 次。**外部发现本身发生得少**，不等于“插件搜索没被调用”。要证明“该搜没搜”，需要逐轮标注预期动作，而不是只看计数。

### 2.4 R4 Deep research 策略

`research_route` 实测：

| 调用 | 结果 |
|---|---|
| `task_shape=batch_research`，host=dsh，不传 provider | `selected = host_workflow`；候选含 professional_service（不可用） |
| 同上，传 `provider=parallel` | **`selected = null`**；`next_action` 让去看 `research_services`；不自动回退 workflow |
| `task_shape=investigation` | `selected = host_iterative_research` |

响应中没有计划书要的 `deep_research` 块。

判定：R4 的验收“API 未启用 → 回退 workflow”只在**不显式指定 provider** 时成立；显式指定不可用 provider 是 fail-closed，不会静默替换。这是现有设计（`provider_fallback` 写明“explicitly selected unavailable service is reported unavailable; never silently substituted”），计划书应明确写“不要传 provider / 或由宿主再调一次”，而不是承诺自动回退。

### 2.5 R5 Discovery → Claim → Wiki

`research_finish` 已经返回：

- `wiki_follow_up.eligible_claims[]`：带逐字首句、`inference` 标记；
- `wiki_follow_up.draft.page`：按 question 分组、已按写入上限切好；
- `insufficiency`：缺口与覆盖。

代码位置：[research.py](../src/research.py) 的 `_wiki_follow_up` / `_wiki_page` / `_wiki_draft`。

计划书 R5 要在 `discovery_bundle` 新增 `draft_claims`，这是**第二条 claim 路径**。应该复用现有 `wiki_follow_up`，或者把 `discovery_bundle` 的证据直接喂给 `research_record`，而不是再造一套草稿。

判定：**R5 与 beta.15 已实现能力重叠**，建议删除或改成“复用/对齐”。

### 2.6 R6 测量与文档

`get_settings` 当前返回的内容里没有 `usage`；也没有 `fetch.policy`、`wiki_preflight`、`freshness_days`、`deep_research`、`context.*`、`search.seed_on_*`。

工具目录实测：**44 tools / 47,121 bytes**（schema 30,793 + descriptions 13,711）。

计划书把“44 → 8 的 allowlist”放在未决问题 1。结合工具审计的历史结论（6 工具基础集约 4.9 KB）和本次 102 次调用高度集中在 5 个工具的事实，**allowlist 很可能比新增字段更能改变行为**，应提前做实验。

## 3. 计划书中最需要改的条款

| 位置 | 现在写法 | 建议 |
|---|---|---|
| R1 `plan_research` | `WikiStore.search(question)` / `RawLibrary.search(question)` | 先用 `plan_terms` 词项化，OR 合并并打分；至少一个“具体词”（`term_cards=1` 且长度≥3）或两个词命中；返回 `matched_terms` |
| R1 Wiki 分支 | `current → wiki_get`；`needs_review → wiki_refresh` | 当前 0/5 current；先做 `wiki_acknowledge` 低成本确认，只有 capture 过期且用户要求时才 refresh；refresh 预算单列 |
| R1 missing file | “排除/标记” | 标 `stale_missing_file` + `stale: true`，保留 URL 但降权；同时提示 `sync_package`；不要默认二值删除 |
| R1 URL 选择 | “每张卡/每个厂商至少一个，或 MMR” | 增加 `url_kind`（homepage/docs/changelog/repo/login/search-result）；优先 docs/changelog；限制 homepage 数量 |
| R1 新鲜度 | “只用高置信度 dateAdded，低置信度降权” | 同时返回 `newest_any` / `newest_high` / `confidence`；low 只降权，不丢弃；明确权重 |
| R1 触发 | “0 卡 → route null” | 增加 relevance floor（分数/密度/词项门槛）；`term_cards=1` 不能直接判 `lookup`，要求问题里出现该名称 |
| R2 fetch | `return=handle` 默认 text | 若要真的降上下文，改默认或让 Skill 强制传；否则保持现状不会发生 |
| R2 预算 | “14 页 <10k” | 增加按页最低配额/均分；0 字页标 unavailable；验收改为“有正文页数 + 字符数” |
| R2 证据 | `capture_id` / `text_sha256` | `discovery_bundle` 的 `evidence[]` 直接带 `capture_id`、`text_sha256`、`text_origin`、`quote_verified`；sha 不匹配必须报错 |
| R2 compact | “去掉 raw_json/description_md/revision，≥50%” | 按 collection 取数；或补充更多投影字段；不要删 `description_md` 除非有替代 |
| R3 | 新增 `required_tools` / `skip_conditions` | 先证明 `next_action.tools` 为什么不够；用 Skill/allowlist/ workflow 强制；计数器先于新字段 |
| R4 | “API 未启用 → 回退 workflow” | 明确“显式 provider 是排他的”；或实现显式 fallback，不要两种语义混写 |
| R5 | `discovery_bundle(draft_claims)` | 复用 `research_finish` 的 `wiki_follow_up`；删除第二条 claim 路径 |
| R6 | 文档最后 | Skill/默认值/allowlist 先行；文档随每个行为改动同步 |

## 4. 建议的 beta.16 收敛范围

| 步骤 | 内容 | 工期 |
|---|---|---|
| R0 | 记录 `wiki_search`/`search_web`/`fetch_web` 触发；8 工具 allowlist 实验；3 个场景回放 | 0.5–1 天 |
| R1 | 预检字段 + 词项化 Wiki/归档 + 状态分支 + relevance floor + missing-file 标记 + 预检输出上限 | 2–3 天 |
| R2 | 默认预算/compact 接线；证据带 capture_id/sha；按页预算；handle 只在 R0 证明必要时加 | 1–2 天 |
| R3 | Skill 写死顺序 + allowlist；不新增重复字段 | 1 天 |
| 延后 | provider 画像、Deep research policy、`draft_claims` | beta.17 |

总计约 **4–6 天**。先验证“预检 + 入口收敛”是否真的改变宿主行为，再决定是否做 provider 画像和 API 策略。

## 5. 复现方式

### 5.1 会话基线

```sh
python3 /tmp/session_stats.py   # 本次验证用脚本；读取 ~/.dsh/sessions/**/session.v4.jsonl.zstd
```

### 5.2 时间置信度

```sh
sqlite3 ~/.local/share/bookmark-research/index.sqlite3 \
  "select added_at_confidence, count(*) from items
   where source_id='github-bookmark-canvas' and item_type='bookmark'
   group by 1;"
```

### 5.3 上下文/搜索体积

```sh
cd src && python3 - <<'PY'
from bookmark_index import BookmarkIndex
from context_output import page_context
from bookmark_output import compact_search
import json
idx = BookmarkIndex('/tmp/br-index.sqlite3')
size = lambda v: len(json.dumps(v, ensure_ascii=False, separators=(',', ':')).encode())
ctx = page_context(idx.context('github-bookmark-canvas'))
print('context', size(ctx))
s = idx.search('github-bookmark-canvas', targets=['Agent'], limit=10)
print('search', size(s), 'compact', size(compact_search(s)))
PY
```

（先把索引复制到 `/tmp`，避免打开原库时触发只读失败。）

### 5.4 测试副作用

- 联网 `fetch_web` 新建归档：`20261019T142017089336Z-e53090c33e28`，6 个厂商首页，约 82k 字符。
- 归档索引从 276 篇增至 282 篇。
- 源包与 Wiki 未修改。
- `/tmp/br-index.sqlite3`、`/tmp/br-filtered.sqlite3`、`/tmp/session_stats.py` 为临时文件。

## 6. 一句话

**计划书的问题诊断是 9 分，方案是 5 分：它准确指出了“宿主不预检、上下文太重、Wiki 不读”，但把“加字段/加参数”当成了行为修复；在真实包上，先要解决词项化、相关性门槛、缺失卡替代、预算公平分配和证据回链，才轮到新增工具面。**
