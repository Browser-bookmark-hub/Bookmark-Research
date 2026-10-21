# Bookmark Research 搜索路由与触发计划（2026-10-19，修订版 2）

> 状态：**beta.16 执行计划**。已按真实包验证结果收敛；不是实现记录。
>
> 实现状态（2026-10-19）：R1 预检（词项、Wiki/归档、relevance、freshness、stale/url_kind）与 R2 的预算/证据/compact 初版已落地；R0 的 `tool_scope` 服务端白名单已实现；DSH/Codex 默认改为全量目录，避免藏掉第三阶段；R3 的 Skill/设置文档与 [beta.16 发布说明草稿](release-notes-0.5.0-beta.16.md) 已建，3 场景 MCP 回放已跑（宿主侧行为回放待重装/新会话）；100k 合成书签压测 p50 约 0.39–0.51 秒（[报告](bench-preflight-2026-10-21.md)）；真实样本包网络测试见 [network-test-2026-10-21](network-test-2026-10-21.md)。当前 `768` 项测试通过、`3` 项跳过。
>
> 依据：实包验证报告（`docs/archive/plugin-search-routing-plan-validation-2026-10-19.md`）；原始稿保留为 v1（`docs/archive/plugin-search-routing-plan-2026-10-19-v1.md`）。
>
> 目标版本：`0.5.0-beta.16`（npm `beta` 通道）。
>
> 范围：**4–6 个工作日**。R0 行为实验 + R1 预检 + R2 预算/证据 + R3 Skill/入口；R4 provider/Deep 策略、R5 `draft_claims` 延到 beta.17。

## 0. 修订摘要

| v1 | v2 | 原因 |
|---|---|---|
| `WikiStore.search(question)` / `RawLibrary.search(question)` | 先 `plan_terms` 词项化，再按词检索并合并 | 实包上整句问题命中 0；`RAG` 单字面词才命中 |
| “Wiki current 直接复用” | 返回 `current / needs_review / invalid`，并给低成本动作 | 当前 5/5 页 `needs_review`，没有 current 样本 |
| 缺失卡“排除/标记” | `stale_missing_file` + URL 类型 + 保留/降权策略 | 直接排除后 top URL 变成首页、登录页、Bing 结果 |
| “URL 厂商多样性，top 8 ≥3 厂商” | `url_kind`（docs/changelog/repo/homepage/login/search）优先 | 当前 top 8 已覆盖 7 个厂商，验收没有区分度 |
| “只用高置信度 dateAdded” | `newest_any` / `newest_high` / `confidence`，low 降权不丢弃 | high 仅 1,043/4,130，37/38 栏目只有 low |
| `fetch_web` 新增 `return=handle`，默认 text | 默认预算 + 公平分配；`handle` 作为可选，不作为唯一解 | 默认 text 不改，98k 问题不会消失；10k 预算会让后几页空文本 |
| `get_context compact` 降 ≥50% | 按 collection 取数；full context 目标改为约 -40% | 计划列的三字段只降 37.9% |
| `search_bookmarks projection` | 复用现有 `compact` | compact 已存在，limit=10 时降 51.2% |
| R5 `discovery_bundle(draft_claims)` | 删除；复用 `research_finish.wiki_follow_up` | 已有 `eligible_claims` + `draft.page` |
| R3 新增 `required_tools` 等字段 | 先做 R0 行为实验 + Skill/allowlist | `next_action.tools` 已经在，宿主仍会不照做 |
| 44 → 8 allowlist 放“未决问题” | 提到 R0 | 工具面 44 个 / 47 KB，入口收缩更可能改变行为 |

## 1. 已验证基线

### 1.1 会话基线（可复现）

| 指标 | 值 |
|---|---:|
| DSH 会话 | 19 |
| 插件调用 | 102（不含本轮验证新增的 4 次） |
| 重点轮次总字符 | 358,632 |
| 插件占比 | 64.4% |
| 该轮 `fetch_web` | 2 次 / 97,835 字符 |
| 该轮 `get_context` | 8 次 / 73,110 字符 |
| 该轮 `search_bookmarks` | 2 次 / 41,374 字符 |
| `wiki_search` | 0 次 |
| `search_web` | 1 次（宿主自带 `web_search` 另有 2 次） |

结论：问题不是“工具不存在”，而是**预检入口不存在、输出过重、入口太多**。

### 1.2 真实包基线

来源：`github-bookmark-canvas`，`/Users/kk/Downloads/kk/Bookmark-Canvas/bookmark/书签画布`。

| 项 | 值 |
|---|---:|
| items / bookmarks / unique URLs | 4,966 / 4,130 / 3,079 |
| sections | 38 |
| JSON 文件 | 37 |
| Canvas 节点 / 连线 | 47 / 14 |
| `retained_missing_files` | A-10-2（当前包中已不存在） |
| `added_at` high / low | 1,043 / 3,087 |
| 有 high 时间的栏目 | 1 / 38 |
| Wiki 页 / claim | 5 / 45 |
| Wiki current 页 | **0 / 5**（全部 `needs_review`） |
| 归档文档（测试前） | 276 |

### 1.3 验证中确认的关键反例

| 问题 | 实测 |
|---|---|
| `RAG 企业落地要点` 查 Wiki | 0 条；`RAG` 4 条；`RAG 企业` 0 条 |
| `EmbeddingGemma 2 怎么本地部署` 查归档 | 0 条；`EmbeddingGemma` 5 条 |
| `quantum entanglement agriculture breeding` | 命中 `QuantumNous/new-api`，被误判 `lookup → direct_retrieval` |
| 6 页 fetch / 10k 总预算 | 3 页有正文，3 页 0 字符但仍 `usable`；`successful_url_count=6` |
| `discovery_bundle` 带 `capture_id` | 不读归档，返回 `evidence: []` |
| `discovery_bundle` 的 `text_sha256` | 不校验；错误 sha 仍接受 |
| `get_context` 全量 compact | 70,010 → 43,464（-37.9%），不到 50% |
| A-10-2 排除后 | A-10 第一，top 8 出现首页、登录页、Bing 搜索结果 |

## 2. 目标与非目标

### 2.1 目标

1. **一个预检入口**：`plan_research` 一次返回书签、Wiki、归档、相关性判定、新鲜度、路由、fetch 归属和预算；只读、本地、无网络。
2. **Wiki 先查且能低成本复用**：`current` 直接复用；`needs_review` 先给 `wiki_acknowledge`/`wiki_get` 的轻量路径，只有证据过期且用户要求时才 `wiki_refresh`。
3. **上下文可预算**：`fetch_web` 默认总预算 + 按页公平分配；`discovery_bundle` 证据必须能回到归档；`get_context`/`search_bookmarks` 用现有 compact/分页。
4. **行为可改变**：8 工具 allowlist + Skill 固定顺序 + 触发计数；不靠“再加一个字段”期待宿主自觉。

### 2.2 非目标（本轮不做）

- 不做无头浏览器/爬虫；`challenge_blocked` 只标注。
- 不新增搜索 provider；provider 画像/health 扩展延到 beta.17。
- 不自动发布 Wiki；`after_research = suggest` 不变。
- 不改 Bookmark Canvas 数据包格式。
- 不做 `max_urls 16`；8 个 URL 配合 `url_kind` 足够。
- 不做 `discovery_bundle(draft_claims)`；复用 `research_finish` 的 Wiki 草稿。
- 不做 Deep research API 策略块；`research_route` 仍是唯一来源。
- 不改宿主 `workflow` 引擎；只改插件脚本/策略/Skill。

## 3. 默认流水线

```text
问题
  → plan_research（预检，本地）
      ├─ terms + relevance（是否值得继续）
      ├─ wiki[]：current / needs_review / invalid + 动作
      ├─ archive[]：capture_id + 命中词
      ├─ bookmarks：cards + urls（带 url_kind、stale 标记）
      ├─ freshness：newest_any / newest_high / confidence / stale
      ├─ route：direct_retrieval / host_iterative_research / host_workflow
      └─ fetch：owner=plugin，预算建议
  → 分支
      ├─ wiki current → wiki_get → 回答/复用
      ├─ wiki needs_review → wiki_acknowledge 或（capture 过期时）wiki_refresh
      ├─ 问题自带 URL → fetch_web
      ├─ 本地 URL 新鲜 → fetch_web
      ├─ 最近/对比/本地缺失 → search_web（1 次 seed）
      └─ deep/批量 → research_* 或 host workflow
  → fetch_web（预算内）
  → discovery_bundle（capture_id，只回证据）
  → research_record → research_finish → wiki_write
```

**关键顺序**：预检只做本地判断；`wiki_refresh`、`search_web`、`fetch_web` 都是预检之后的显式动作。

## 4. `plan_research` v2 契约

### 4.1 新增/调整参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `include_wiki` | `true` | 默认查；失败不影响书签结果 |
| `include_archive` | `true` | 默认查 |
| `max_wiki` | 3 | 1–5 |
| `max_archive` | 5 | 1–8 |
| `max_cards` | 3 | 保持 1–3 |
| `max_urls` | 8 | 保持 1–8，不扩到 16 |
| `refresh` | `true` | 语义同 `search_bookmarks`；snapshot 模式不重新同步 |

输出新增：

- `relevance`：`accepted`、`matched_terms`、`score`、`density`、`reason`；
- `wiki[]`：`page_id`、`title`、`status`、`score`、`matched_terms`、`issues_count`、`actions[]`；
- `archive[]`：`capture_id`、`url`、`title`、`characters`、`retrieved_at`、`matched_terms`；
- `freshness`：`intent`、`newest_any`、`newest_high`、`confidence`、`stale`、`reason`；
- `fetch`：`owner`（默认 `plugin`）、`fallback`（`host`）、`max_total_characters`、`reason`；
- `urls[]` 增加 `url_kind`、`stale`；
- `preflight_budget`：`characters`、`max_characters`。

**不新增** `required_tools`、`skip_conditions`、`deep_research`；保留现有 `next_action`，由 Skill/allowlist 执行。

### 4.2 词项构造（R1 的核心）

复用 `BookmarkIndex.plan_terms`，再过滤：

1. ASCII：长度 ≥ 3，整词匹配；丢弃 `the/and/for/with/how/what` 之类的停用词。
2. CJK：保留二元组，但丢弃高频通用词：`中的 / 的应 / 应用 / 哪些 / 有哪 / 怎么 / 什么 / 如何 / 变化 / 最新` 等；这些词只可作为**辅助**，不能单独决定命中。
3. 具体性：`term_cards == 1` 且该词长度 ≥ 3，或该词出现在卡片标题/URL 行中，才算“具体词”。
4. 预检继续条件：至少 **2 个不同词命中**；或 **1 个词命中且该词出现在卡片 `label`/`title` 中（不是 URL 子串）且 hits ≥2**；或 **1 个具体词 + hits ≥2 + density ≥0.02**。单字面词查询（如 `RAG`）靠第二/第三条通过。
5. 若都不满足：`cards: []`、`route: null`，并给出 `relevance.reason`，要求宿主先问用户是否扩大范围。

用已验证反例锁定：

- `量子纠缠在农业育种中的应用`：`应用/中的` 是通用词，不能单独通过；`量子` 只命中 qbitai 一次，不应把整题判为相关。
- `quantum entanglement agriculture breeding`：`quantum` 是 `QuantumNous` 的子串，不算“点名”；必须走 `route: null`。
- `云厂商 Agent Runtime 有哪些变化`：`云厂商/厂商/Agent/Runtime` 多词命中，通过。
- `RAG 企业落地要点`：`RAG/企业/落地` 多词命中，通过。

### 4.3 `task_shape` 修正

`lookup` 只在以下条件成立：

- 问题包含 `question_urls`；或
- 问题文本**完整包含**某张卡的 `label`/`title`/仓库名（不是子串偶然命中）；或
- 问题点名一个 `term_cards == 1` 且该词长度 ≥ 3 的具体名称，并且该词不是通用词。

禁止仅凭“某个词只指向一张卡”判 `lookup`。否则 `quantum`、`企业` 这类词会把研究题降档。

### 4.4 Wiki 状态分支

| 状态 | 预检返回 | 下一步 |
|---|---|---|
| `current` | `actions: ["wiki_get"]` | 直接复用，不搜索 |
| `needs_review`，仅 `source_input_changed` / `newer_source_snapshot` | `actions: ["wiki_get","wiki_acknowledge"]` | 读页 + 确认输入版本，不联网 |
| `needs_review`，有 `source_capture_expired` | `actions: ["wiki_get","wiki_refresh"]`，并给 `expired_count` | 用户确认后刷新；刷新预算单列，不占 `fetch_web` 的 8 次 |
| `invalid` | 不进入 `wiki[]` | 忽略 |

**不在预检里自动刷新**。RAG 页有 13 个来源，自动刷新会把预检变成一次大抓取。

### 4.5 归档

- 用词项检索，不传整句。
- 每条返回 `capture_id`、`url`、`title`、`characters`、`retrieved_at`、`matched_terms`，不回正文。
- 同一 URL 多个 capture 时，优先最新 `retrieved_at`；`characters` 取最大。

### 4.6 新鲜度

- `newest_any`：栏目内最大 `added_at`（含 low）。
- `newest_high`：最大 high-confidence `added_at`；没有则 `null`。
- `confidence`：`newest_high` 存在则 `high`，否则 `low`。
- `stale`：按 `freshness_days`（默认 30）判断 `newest_any`；low 置信度仍可判 stale，但 `reason` 标注 `low_confidence`。
- 不丢弃 low；排序权重建议 `high=1.0, low=0.5`，由 `plan.freshness_weight` 配置。

### 4.7 URL 选择

新增 `url_kind`：

| 类型 | 判定 | 排序 |
|---|---|---|
| `docs` | 路径含 `/docs/`、`/documentation/`、`developer.`、`developers.` | 最高 |
| `changelog` | 路径含 `changelog`、`release`、`whats-new`、`updates` | 最高 |
| `repo` | `github.com`、`gitlab.com` 等仓库 | 高 |
| `homepage` | 路径为空或 `/` | 中，低配额 |
| `login` | `login`、`signin`、`auth` | 低，默认排除 |
| `search` | `bing.com/search`、`google.com/search` 等 | 低，默认排除 |
| `other` | 其余 | 中 |

规则：

- 每张卡最多 2 个 `homepage`；`login`/`search` 只有在没有其他 URL 时才保留。
- 缺失文件的卡片**不进入 `cards[]` 的 top 3**；其 URL 以 `stale: true` 进入 `urls[]` 候选池，按 `url_kind` 排序；只有全部候选都 stale 时才把 stale 卡放回 `cards[]`。这样既不让 A-10-2 排第一，也不丢掉它给出的具体入口。
- **不做厂商 MMR**。多样性不是当前问题；先做类型/具体性。

### 4.8 输出上限

- `max_characters` 默认 8,000；`wiki` 只回摘要 ≤200 字符，不回正文；`archive` 不回正文。
- 超限时截断 `wiki`/`archive` 条目数，并在 `preflight_budget.truncated` 标注；不静默丢卡片。

## 5. `fetch_web` / 证据 / 上下文

### 5.1 `fetch_web` 预算

新增设置：

```json
"fetch": {
  "provider": "parallel",
  "providers": ["parallel", "exa", "jina"],
  "max_characters": 12000,
  "max_total_characters": 24000,
  "fair_share_min": 500
}
```

- `max_total_characters` 默认从 100,000 降到 24,000（行为变化；在 release notes 写明）。
- 分配算法：
  1. 先按 `remaining // remaining_pages` 给每页份额；
  2. 每页至少 `fair_share_min`（默认 500），但不超过 `max_characters`；若总额不足以覆盖所有页的最小份额，则退化为均分，不强行 500；
  3. 剩余额度按页顺序回填；
  4. 仍为 0 的页（只在总额小于页数，或 provider 无正文时出现）标 `content_state: "unavailable"`、`read: false`，不计入 `successful_url_count`。
- 新增 `pages_with_text`、`pages_without_text`；`status` 只有全无正文才是 `error`。
- `return: "handle"`（可选）：只回 `url/title/capture_id/content_state/characters/published_at/sha256`；默认仍是 `text`。**beta.16 不把 handle 设为默认**，先用预算 + Skill 解决。

### 5.2 证据回链

`discovery_bundle` 的 `sources` 支持：

```json
{"url": "...", "capture_id": "...", "text_sha256": "..."}
```

- 有 `capture_id`：从归档读正文；`text_origin: "archive"`；`quote_verified: true`。
- 只有 `text`：`text_origin: "host"`；`quote_verified: false`。
- `text_sha256` 不匹配：该来源进 `unavailable_sources`，reason `sha256_mismatch`，不进入 `evidence`。
- `evidence[]` 新增：`capture_id`、`text_sha256`、`text_origin`、`quote_verified`、`source_characters`。
- 空文本：reason 用 `no_text`，不要再用 `usable` 作为不可用原因。

### 5.3 上下文

- `get_context` 新增 `compact: true`：
  - 去掉 `raw_json`、`description_md`、`revision`；
  - **必须配合 `collection` 使用**才能达到 <20k；全量 compact 目标改为 ≤45k（约 -35%）。
  - Skill 默认：研究场景先 `collection="sections"`，需要空间时再 `nodes`/`edges`。
- `search_bookmarks` **不新增 projection**；Skill 默认 `compact=true`、`limit<=10`，目标 <15k（实测 14,332）。
- 文档中删除“compact 全量 ≥50%”的表述；改为“按 collection 的达标值”。

## 6. 行为改变（R0，先做）

### 6.1 原 8 工具 allowlist（已改为默认全量）

默认研究入口只暴露：

1. `plan_research`
2. `search_bookmarks`
3. `get_context`
4. `search_web`
5. `fetch_web`
6. `discovery_bundle`
7. `wiki_search`
8. `wiki_get`

其余 36 个工具继续存在，通过 profile/CLI 显式开启；持久研究（`research_*`）与设置写在 `tool_scope` 或 CLI 里按需恢复。理由：44 个工具 / 47,121 bytes 目录；102 次调用集中在 5 个工具。

DSH 插件默认不设置 `BOOKMARK_RESEARCH_TOOL_SCOPE`（全量目录）；Codex 项目配置也移除了 8 项 `enabled_tools`。仍可用环境变量或 `enabled_tools` 收窄；`tool_scope` 设置仅在环境变量不存在时生效。

### 6.2 Skill 固定顺序

```text
1. plan_research（必做）
2. wiki: current → wiki_get；needs_review → wiki_get + acknowledge/refresh
3. 本地 URL：docs/changelog/repo 优先，homepage 最多 2 个
4. 需要发现/最新/对比/本地缺失 → search_web 1 次
5. fetch_web：一次 ≤4 URL，总预算 ≤24k
6. discovery_bundle：只回证据；引用 evidence[].id
7. research_record → research_finish（需要持久报告时）
8. wiki_write（用户确认后）
```

### 6.3 触发计数

新增本地计数（不联网、不上报）：

- `plan_research`、`wiki_search`、`wiki_get`、`search_web`、`fetch_web` 的次数；
- 每次 `fetch_web` 的 `pages_with_text` / 字符数；
- 每次 `plan_research` 的 `wiki` 命中状态。

落点：数据目录下 `usage.jsonl`（只记工具名、时间、字符数、状态；不记 URL/query 正文）。`get_settings` 返回汇总。beta.16 先本地文件，后续再做轮转/清理。

## 7. 工作包

### R0：行为实验与入口（0.5–1 天）

- 8 工具 allowlist；Skill 顺序；`usage.jsonl`。
- 3 个场景回放：RAG/Wiki、云厂商时效、EmbeddingGemma。
- 产出：基线/对照的 `wiki_search`、`search_web`、`fetch_web` 次数与上下文占比。
- 验收：3 个场景中至少 2 个按 Skill 顺序执行；记录未执行的原因。

### R1：预检（2–3 天）

改：

- `src/bookmark_index.py`：`plan_terms` 过滤/具体性；`plan_scope` 支持 `missing_files`、`url_kind`、`relevance`；返回 `newest_high`。
- `src/wiki_search.py`：`search_terms(terms, limit)` 或逐词检索合并；按 `page_id` 去重、按词权/标题命中打分。
- `src/raw_library.py`：`search_terms`；返回 capture_id/最新 capture。
- `src/research_plan.py`：预检组装、状态分支、输出上限。
- `src/mcp_server.py`：schema/描述；`plan_research` 新参数。
- `src/settings.py`：`wiki_preflight`、`freshness_days`、`plan.max_chars`、`plan.min_relevance`、`plan.homepage_limit`、`plan.freshness_weight`。

测试：

- 整句问题 → 词项 → Wiki/归档命中（RAG、EmbeddingGemma）；
- `RAG 企业`/`RAG 落地` 这类多词查询不再 0；
- `quantum…` → `route: null`；
- `A-10-2` → `stale: true`，不排第一；
- high/low 时间都保留；
- `url_kind`：top 8 中文档/仓库优先，homepage ≤2/卡；
- 预检输出 ≤8k。

### R2：预算与证据（1–2 天）

改：

- `src/archive.py`：公平分配、`pages_with_text`、0 字页 `unavailable`、`return=handle`。
- `src/discovery.py`：`capture_id` 读取、sha 校验、`text_origin`、`quote_verified`、证据字段。
- `src/mcp_server.py`：`fetch_web` 的 `return`、设置默认；`discovery_bundle` 的 sources 说明。
- `src/context_output.py` / `mcp_server.py`：`get_context compact`。
- `src/settings.py`：`fetch.max_total_characters`、`fetch.fair_share_min`、`context.compact_default`。

测试：

- 6 页 / 10k：`pages_with_text=6`（每页约 1,666 字符），没有 0 字 `usable` 页；
- 14 页 / 10k：`pages_with_text=14`（每页约 714 字符），不出现后几页空文本；
- 6 页 / 2k：仍每页有文本（约 333 字符）；0 字页只在总额小于页数或 provider 无正文时出现，并标 `unavailable`；
- `capture_id` 读归档，`network_request_performed=false`；
- sha 不匹配 → 不进 evidence；
- evidence 100% 带 `capture_id`/`text_sha256`/`text_origin`；
- `get_context` sections compact <20k；full compact ≤45k；
- `search_bookmarks` compact limit=10 <15k；
- 旧格式 sources 仍兼容。

### R3：Skill/文档/发布（1 天）

- `skills/bookmark-research/SKILL.md`：预检顺序、Wiki 状态、URL 类型、预算、证据回链。
- `README.md` / `README.zh.md` / `docs/details*.md` / `docs/prompt-reference*.md`：工具表、设置、默认值变化。
- `docs/release-notes-0.5.0-beta.16.md`：变更、行为变化、边界。
- `docs/archive/tool-surface-audit.md`：补 44 工具/47 KB 与 8 工具 allowlist 的当前数据（不改历史结论）。

### 延后到 beta.17

- provider 画像（capability/strengths/exclusions/quality_filters）；
- `deep_research.policy` 块；
- `discovery_bundle(draft_claims)`；
- `max_urls 16`；
- 浏览器/Cloudflare 并发。

## 8. 测试计划

### 8.1 单元/契约

| 文件 | 覆盖 |
|---|---|
| `tests/test_research_plan.py` | 词项、relevance floor、Wiki 状态、归档、URL 类型、输出上限 |
| `tests/test_wiki_search.py` | 多词 OR、标题/正文打分、invalid 排除 |
| `tests/test_bookmark_index.py` | missing file、url_kind、newest_high、homepage 配额 |
| `tests/test_discovery.py` | capture_id、sha 校验、text_origin、空文本 |
| `tests/test_evidence_state.py` | 0 字页状态、公平分配 |
| `tests/test_context_pagination.py` | compact 各 collection 体积 |
| `tests/test_mcp_server.py` | 新 schema/描述/默认值 |

### 8.2 真实包回归

| 场景 | 期望 |
|---|---|
| `RAG 企业落地要点` | `wiki` 命中 `rag-search-and-mcp`（`needs_review`，含 13 个过期 capture）；`actions` 含 `wiki_get`/`wiki_acknowledge`/`wiki_refresh`；本地 A-1-1；不自动联网 |
| `云厂商 Agent Runtime 有哪些变化` | A-10-2 标 stale 不第一；A-10/A-1-1 前二；top 8 至少 2 个 docs/changelog/repo；1 次 seed search |
| `EmbeddingGemma 2 怎么本地部署` | A-1-1 第一；`lookup/direct_retrieval`；归档命中 Unsloth |
| `量子纠缠在农业育种中的应用` | `route: null`，提示包内无相关内容 |
| `quantum entanglement agriculture breeding` | `route: null`，不能判 `lookup` |
| `zzzzqqqq` | `route: null` |

### 8.3 行为回放

- 3 个研究场景，记录 `plan_research → wiki → fetch → bundle` 的顺序；
- 指标：`wiki_search` 至少 1 次/场景；`search_web` 只在 freshness/compare/local miss 时出现；`fetch_web` 结果 <24k（text 模式）/ <4k（handle 模式）；插件上下文占比 <40%。

## 9. 验收与指标

| 指标 | 现状 | beta.16 目标 |
|---|---:|---:|
| `plan_research` 输出 | 3.5–6k | ≤8k |
| Wiki 预检命中 | 0 | 3/3 研究场景有 `wiki[]` 条目（可为 needs_review） |
| `search_web` | 1/19 | 按条件触发；不把绝对值当 KPI |
| `fetch_web` 单轮 | 97,835 | <24k（text）/ <4k（handle） |
| 插件上下文占比 | 64.4% | <40% |
| 证据带 capture_id/sha | 未统计 | 100% |
| `get_context` compact | 无 | sections <20k；full ≤45k |
| `search_bookmarks` compact | 已有 | limit=10 <15k |
| 测试 | 756 | 756 + ≥30；3 skipped |
| A-10-2 | 第一 | 标 stale，不第一 |
| 伪相关 | `quantum` → lookup | `route: null` |

## 10. 设置

```json
{
  "wiki_preflight": true,
  "freshness_days": 30,
  "fetch": {
    "provider": "parallel",
    "providers": ["parallel", "exa", "jina"],
    "max_characters": 12000,
    "max_total_characters": 24000,
    "fair_share_min": 500
  },
  "plan": {
    "max_characters": 8000,
    "min_relevance": 0.05,
    "homepage_limit": 2,
    "freshness_weight": {"high": 1.0, "low": 0.5}
  },
  "context": {
    "compact_default": false
  }
}
```

兼容：`fetch_web` 默认仍 `text`；`get_context` 默认仍全量；`search_bookmarks` 默认仍 `compact=false`。新行为通过 Skill 或显式参数启用；`max_total_characters` 默认变化需在 release notes 明示。

## 11. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 词项化后仍有漏检 | 保留单字面词兜底；`relevance` 说明为什么 0；不静默扩大范围 |
| `route: null` 过多 | `min_relevance` 可调；真实包 6 场景回归 |
| 缺失卡一删就丢好 URL | 默认保留 + `stale` 标记 + URL 类型排序；A/B 对比 |
| Wiki 全部 needs_review | 优先 `wiki_acknowledge`；`wiki_refresh` 仅在 capture 过期且用户确认时 |
| 默认 24k 截断正文 | 每页 `next_offset`/`capture_id` 续读；release notes 说明 |
| allowlist 隐藏必需工具 | profile 可覆盖；release notes 给开启方法 |
| 证据 sha 校验拒绝 host 文本 | host 文本标 `quote_verified=false`，不拒；只拒 archive 的 sha 不匹配 |

回滚：

- `wiki_preflight=false`；`plan.min_relevance=0`；
- `fetch.max_total_characters=100000`；`context.compact_default=false`；
- allowlist 恢复全量；
- 不涉及数据迁移。

## 12. 未决问题

1. 缺失卡：默认保留 + `stale`，还是可配置排除？建议先保留，用 `url_kind` 降权。
2. `needs_review`：仅输入变化 → `wiki_acknowledge`；capture 过期 → `wiki_refresh`。是否允许用户一键“先读后刷新”？
3. `handle`：只在 R0 证明默认 `text` 仍超预算时再加；否则不做默认。
4. `max_urls 16`：不做；8 + `url_kind` 足够。
5. provider 画像/Deep policy：beta.17，等 R0 行为数据。

## 13. 时间表

| 日 | 内容 |
|---|---|
| D1 | R0：allowlist、Skill 顺序、计数、3 场景回放 |
| D2–D4 | R1：词项、relevance、Wiki/归档、URL 类型、输出上限 + 单测 |
| D4–D5 | R2：公平预算、capture_id/sha、compact + 单测 |
| D6 | R3：文档、release notes、真实包 6 场景、发布 |

发布门槛：756 + 新增 ≥30 测试通过；真实包 6 场景通过；行为回放不出现“预检后仍直接全文抓 8 页”。

## 14. 参考映射

| 参考 | 借什么 | 落到哪 |
|---|---|---|
| 实包验证（`docs/archive/plugin-search-routing-plan-validation-2026-10-19.md`） | 反例、阈值、预算数据 | R0/R1/R2 验收 |
| `smartsearch-main` | 意图路由、URL 类型 | `plan_terms`、`url_kind`、`task_shape` |
| `aether-search-main` | seed fan-out、6 步/90 秒 | R0/R3 的 1 次 seed |
| beta.15 计划 §2.1/§3.3 | `plan_research`、Wiki 复用 | 本计划取代其触发部分；不重复 R5 |
| `docs/archive/tool-surface-audit.md` | 6 工具基础集 | R0 allowlist |

## 15. 一句话

**beta.16 只做三件事：预检能命中、预算不骗人、入口能改变行为。** 不新增 provider、不做 Deep 策略、不做第二套 claim/compact。
