# Bookmark Research 搜索路由与触发计划（2026-10-19）

> 状态：计划稿，不是实现记录。目标版本：`0.5.0-beta.16`（npm `beta` 通道）。
>
> 本轮主题：**把“书签内搜索、外部搜索、Deep research、Wiki 复用、宿主 fetch”收进一个预检入口，让它们按规则触发，而不是靠宿主自觉。**

## 0. 一句话

现在插件不是没有工具，而是没有“搜索前的统一入口”和“触发规则”：

- `search_web` 在 19 个 DSH 会话里只出现 **1 次**；
- `wiki_search` **0 次**；
- `fetch_web` **10 次**；
- `wiki_write` 2 次，`wiki_get` 2 次——Wiki 基本是 write-only。

本轮要做的不是再加 10 个工具，而是：

1. 让 `plan_research` 变成**知识预检**（Wiki + 归档 + 书签 + 新鲜度 + 路由）；
2. 让 `search_web`、`fetch_web`、`research_service_*`、`wiki_*` 有明确的**触发条件**；
3. 让“读 URL 用插件还是宿主”有明确**归属策略**；
4. 让上下文只装“指针 + 证据”，全文留在归档。

## 1. 基线

### 1.1 工具调用（DSH 本地 19 个会话，102 次插件调用）

| 工具 | 次数 | 解读 |
|---|---:|---|
| `get_context` | 20 | 空间结构读得多 |
| `search_bookmarks` | 11 | 书签内搜索是主路径 |
| `fetch_web` | 10 | 插件主要被当 reader |
| `research_record` | 9 | 深研路径有使用 |
| `get_settings` | 6 | |
| `index_status` | 5 | |
| `sync_package` | 5 | |
| `research_readiness` | 4 | |
| `research_finish` | 4 | |
| `plan_research` | 4 | 新入口用得少 |
| `research_start` | 3 | |
| `research_fetch` | 3 | |
| `research_source` | 3 | |
| `discovery_bundle` | 2 | |
| `research_import_evidence` | 2 | |
| `wiki_write` | 2 | |
| `wiki_get` | 2 | 只按已知 page_id |
| `wiki_lint` | 2 | |
| `search_archive` | 1 | |
| `search_web` | **1** | 外部发现搜索几乎不触发 |
| `wiki_search` | **0** | 已有 Wiki 库搜索不触发 |
| `wiki_work` | 1 | |

### 1.2 研究轮上下文成本（turn 4，字符数，不是 token）

| 工具 | 次数 | 字符数 | 占本轮 |
|---|---:|---:|---:|
| `fetch_web` | 2 | 97,835 | 27.3% |
| `get_context` | 8 | 73,110 | 20.4% |
| `search_bookmarks` | 2 | 41,374 | 11.5% |
| `index_status` | 1 | 9,149 | 2.6% |
| `plan_research` | 1 | 4,842 | 1.3% |
| `discovery_bundle` | 1 | 4,633 | 1.3% |
| 插件合计 | 15 | 230,943 | 64.4% |
| 宿主 bash/read/skill | 23 | 127,689 | 35.6% |
| 合计 | 38 | 358,632 | 100% |

关键结论：`discovery_bundle` 压缩比约 21:1，但它发生在 `fetch_web` 之后。**压缩太晚，全文已经进上下文。**

### 1.3 现有能力与缺口

| 能力 | 现有零件 | 状态 | 缺口 |
|---|---|---|---|
| 直接读 URL | `fetch_web` | 有 | 宿主 `web_fetch` 的归属/去重/证据导入没规定 |
| Agentic search | `search_web` + `fetch_web` + `discovery_bundle` | 零件齐 | 没有自动 seed search、没有触发规则、预算靠宿主自报 |
| Deep research | `research_*` + `research_service_*` + 分组 workflow | 零件齐 | API 默认关闭；API vs 本地 inventory 没有策略 |
| Wiki 预检 | `wiki_search` / `wiki_get` / `wiki_refresh` | 工具齐 | `plan_research` 不查 Wiki；write-only |
| 归档复用 | `search_archive` | 有 | 预检不查归档 |
| 空间/时间 | `get_context` / `added_at` | 有 | `get_context` 输出过重；低置信度时间参与排序 |
| 路由 | `research_route` | 有 | 只建议、不执行；`plan_research` 只查书签 |

## 2. 目标与非目标

### 2.1 目标

1. **一个预检入口**：一次 `plan_research` 返回 Wiki、归档、书签、新鲜度、路由、fetch 归属、Deep research 策略、必需工具、seed 查询。
2. **Wiki 先查**：任何研究型问题先查已有 Wiki；`current` 直接复用，`needs_review` 先刷新，不重复联网。
3. **外部搜索按条件触发**：最近/最新、对比/替代、本地 0 命中、本地过期或不可用、用户明确要求时触发 `search_web`。
4. **fetch 归属明确**：要引用/归档的 URL 用插件 `fetch_web`；宿主 `web_fetch` 只做快速查看或兜底；同一 URL 不重复读。
5. **Deep research 分工明确**：覆盖本地书签包用插件 inventory + workflow；广泛外部主题用 API；两者可 hybrid。
6. **上下文可预算**：`fetch_web` 支持 handle 模式，`discovery_bundle` 支持 `capture_id`，`get_context`/`search_bookmarks` 支持 compact 投影。
7. **可测量**：记录 `wiki_search`、`search_web`、`fetch_web` 的触发次数和上下文成本。

### 2.2 非目标（本轮不做）

- **不做无头浏览器/爬虫**。`challenge_blocked` 只标注，不绕过；要做得单独立项。
- 不新增搜索 provider（先用好 Exa/Parallel/Tavily/Jina）。
- 不自动发布 Wiki；`wiki.after_research = suggest` 的审阅门槛不变。
- 不改 Bookmark Canvas 数据包格式。
- 不重写宿主的 `workflow` 引擎；只改插件侧脚本/策略。
- 不把 141M 研究证据塞进 Git 包；包级证据根另立计划。

## 3. 目标架构

### 3.1 默认流水线

```text
用户问题
  → plan_research（预检）
      ├─ wiki[]：current / needs_review / invalid
      ├─ archive[]：已有 capture
      ├─ bookmarks{}：卡片 + URL
      ├─ freshness：意图、最新本地时间、是否过期
      ├─ route：direct_retrieval / host_iterative_research / host_workflow / professional_service
      ├─ fetch：owner=plugin|host，fallback=host
      ├─ deep_research：inventory_first|api_first|hybrid
      ├─ required_tools[]
      └─ seed_queries[]
  → 分支
      ├─ wiki current → wiki_get → 回答/复用
      ├─ wiki needs_review → wiki_refresh → 复核
      ├─ 问题自带 URL → fetch_web
      ├─ 本地 URL 新鲜 → fetch_web
      ├─ 最近/最新/对比/本地缺失 → search_web（seed）
      └─ deep → research_* 或 research_service_*
  → fetch_web / research_fetch
  → discovery_bundle（capture_id，只回证据）
  → research_record（claim）→ research_finish（draft）→ wiki_write
```

### 3.2 路由决策表

| 条件 | Wiki | 书签 | 外部搜索 | 读取 | Deep |
|---|---|---|---|---|---|
| Wiki `current` 命中 | `wiki_get` | 可选 | 否 | 否 | 否 |
| Wiki `needs_review` | `wiki_refresh` | 可选 | 否 | 只刷新过期源 | 否 |
| 问题自带 URL | 先查 | 可选 | 否 | `fetch_web` | 否 |
| 本地卡片/URL 命中且新鲜 | 先查 | `plan_research` | 否 | `fetch_web` | 否 |
| 最近/最新/本周/current | 先查 | 先查 | **1 次 seed** | 选中 URL | 否 |
| 对比/替代/还有什么 | 先查 | 先查 | **强制** | 选中 URL | 可选 |
| 本地 0 卡/0 URL | 先查 | 0 | 询问后搜 | 选中 URL | 可选 |
| 本地 URL 过期/不可用 | 先查 | 先查 | 搜替代源 | 选中 URL | 可选 |
| 覆盖整个书签包 | 先查 | inventory | 补缺口 | `research_fetch` | `inventory_first` |
| 广泛外部主题 | 先查 | 可选 | API 负责 | 读引用原文 | `api_first` |

### 3.3 Fetch 归属规则

| 场景 | 工具 | 证据等级 |
|---|---|---|
| 书签 URL、要引用/Wiki | 插件 `fetch_web` | 可归档、可引用 |
| 快速查看、不引用 | 宿主 `web_fetch` | 非证据 |
| 插件 provider 全失败 | 宿主 `web_fetch` 兜底 | 需导入证据 |
| 登录态/浏览器渲染 | 宿主/浏览器 | 标注限制 |
| 同一 URL 同一轮 | 只选一个 | 避免重复 |

设置：

```json
"fetch": {
  "provider": "parallel",
  "providers": ["parallel", "exa", "jina"],
  "policy": "plugin_first",
  "fallback": "host"
}
```

`policy` 取值：`plugin_first`（默认）/ `plugin_only` / `host_fallback` / `host_only`。

宿主 fetch 的结果必须通过 `research_import_evidence`（`provenance.kind = "page"`）或 `discovery_bundle` 的 `text_origin = "host"` 进入证据，不能直接引用。

### 3.4 Deep research 规则

| 场景 | 策略 | 执行 |
|---|---|---|
| 覆盖本地书签包 | `inventory_first` | `research_start` + `research_*` + 分组 workflow |
| 广泛外部主题 | `api_first` | `research_service_prepare/start/status/result/import` |
| 两者都要 | `hybrid` | API 发现/综述；插件逐 URL 核验 + Wiki |

规则：

- API 报告导入为 **unreviewed secondary evidence**；原始 URL 覆盖不变，引用原文仍要读。
- API 不可用/未启用时，不能假装覆盖了本地 inventory。
- `professional_research.enabled` 默认 `false`；启用需要 key 和显式设置。

设置：

```json
"deep_research": {
  "policy": "inventory_first",
  "api_provider": null
}
```

`policy` 取值：`inventory_first`（默认）/ `api_first` / `hybrid`。

### 3.5 上下文预算

| 层 | 内容 | 目标 |
|---|---|---|
| 指针层 | URL、title、capture_id、content_state、characters、published_at、sha256 | 每条 100–300 字符 |
| 证据层 | 1200 字摘录 / 320 字文摘 / URL 清单 | 每条 320–1200 字符 |
| 全文层 | 归档 `knowledge/pages/` | 默认 0，按需 `research_source(capture_id, offset)` |

目标：单轮插件工具结果从 64% 降到 **<40%**；`fetch_web` 从 98k 降到 **<10k**；`get_context` 从 73k 降到 **<20k**；`search_bookmarks` 从 41k 降到 **<15k**。

## 4. 工作包

### R1：预检入口（P0，2–3 天）

**改什么**

- `src/research_plan.py`：新增 `ResearchPreflight`（或扩展 `ResearchPlan.build`）：
  - 调 `BookmarkIndex.plan_scope`；
  - 调 `WikiStore.search(question, limit=3)`；
  - 调 `RawLibrary.search(question, limit=5)`；
  - 计算 `freshness`（高置信度 `added_at`、`newest_added_at`、关键词）；
  - 返回 `wiki[]`、`archive[]`、`bookmarks{}`、`freshness`、`route`、`fetch`、`deep_research`、`required_tools`、`seed_queries`、`coverage`。
- `src/bookmark_index.py`：
  - 排除/标记 `retained_missing_files` 的卡片（`stale_missing_file`）；
  - 新鲜度排序只用高置信度 `dateAdded`，低置信度 ID 日期降权；
  - URL 选择加多样性（每张卡/每个厂商至少一个，或 MMR）；
  - `max_urls` 上限从 8 提到 16（可选）。
- `src/mcp_server.py`：`plan_research` schema 加 `include_wiki`、`include_archive`、`since`；描述同步。
- `src/settings.py`：`wiki_preflight: true`、`freshness_days: 30`。

**测试**

- Wiki 命中 `current` → `wiki_get`，不触发 search；
- Wiki `needs_review` → `wiki_refresh`；
- 无 Wiki → 继续书签；
- 归档命中 → `capture_id` 复用；
- 0 卡 + 问题无 URL → `route: null`；
- A-10-2 这类 missing file 不计入 top；
- “最近”问题 → `freshness.intent = true`；
- URL 多样性：top 8 至少覆盖 3 个不同厂商。

**验收**

- 一次调用返回全部预检字段；纯本地，无网络；
- 真实包 `github-bookmark-canvas` 上，“云厂商 Agent Runtime”问题不再把 A-10-2 排第一；
- `书签画布-关于书签数据包的AI化升级调研-20260906-125939`（245 items / 223 bookmarks / 4 sections）作为小样本回归。

### R2：Fetch 归属与上下文（P0，2–3 天）

**改什么**

- `src/mcp_server.py`：`fetch_web` 加 `return: "handle" | "text"`（默认 `text` 兼容）；handle 只回 URL/title/capture_id/content_state/characters/published_at/sha256。
- `src/discovery.py`：`evidence_bundle` 支持 `capture_id` / `text_sha256`；从归档读正文；标 `text_origin`、`quote_verified`；`sources` 仍兼容旧格式。
- `src/context_output.py` / `src/mcp_server.py`：`get_context` 加 `compact: true`，省略 `raw_json`、`description_md`、`revision`。
- `src/bookmark_index.py` / `src/bookmark_output.py`：`search_bookmarks` 加 `projection`，默认不返回 `raw_json`/`metadata`，需要时 `raw: true`。
- `src/settings.py`：`fetch.policy`、`fetch.fallback`。

**测试**

- handle 模式不返回正文；`capture_id` 可续读；
- `capture_id` 读归档，sha 不匹配报错；
- host 文本标 `text_origin=host`，`quote_verified=false`；
- compact 输出字符数下降 ≥50%；
- 旧格式 sources 仍可生成 bundle。

**验收**

- 14 页 fetch 的上下文从 98k 降到 <10k；
- 证据 100% 带 `capture_id`/sha；
- 不改变现有 `fetch_web` 默认行为（`return` 默认 `text`）。

### R3：触发规则与 provider 画像（P0/P1，2–3 天）

**改什么**

- `src/research_plan.py`：意图分类：
  - URL 在问题里 → `fetch`；
  - 最近/最新/本周/current → `freshness`；
  - API/SDK/文档/框架 → `docs`；
  - 对比/替代/还有什么 → `compare`；
  - CVE/金融/法律/论文 → `vertical`（可选）。
- `src/web_search.py`：
  - `quality()` / `unresolved()` 纳入 `content_state`；
  - 低质量页面允许一次备用 provider 重试；
  - 后到的 `usable` 覆盖主 provider 的 `content_insufficient`；
  - provider 画像（`capability`/`strengths`/`exclusions`/`quality_filters`/`fallback_group`）从 `config/providers.json` 读取；
  - health/cooldown 复用现有状态，增加延迟/成功率。
- `src/mcp_server.py`：`plan_research` 返回 `required_tools`、`skip_conditions`、`seed_queries`。
- `src/settings.py`：`search.seed_on_freshness: true`、`search.seed_on_local_miss: true`、`search.seed_on_compare: true`。

**测试**

- “最近/最新” → `required_tools` 含 `search_web`；
- “RAG 企业落地” Wiki 命中 → 不含 `search_web`；
- 本地 0 命中 → `route: null`，询问后搜；
- 主 provider 空壳 + 备用可用 → 备用赢；
- provider 冷却跳过，不重复调用。

**验收**

- 3 个场景：
  1. Wiki 命中 → 0 次 `search_web`；
  2. 最近/最新 → 1 次 `search_web`；
  3. 本地 0 命中 → 先问，再搜。
- `search_web` 从 1/19 提升到“按条件触发”，不是“每次必搜”。

### R4：Deep research 策略（P1，2 天）

**改什么**

- `src/routing.py`：`route()` 读取 `deep_research.policy`、`professional_research.enabled`、credentials、`source_scope`；返回 `deep_research` 块。
- `src/research_plan.py`：预检返回 `deep_research.policy`。
- `src/research.py`：`research_finish` 记录 `deep_research` 来源（inventory/API/hybrid）；API 导入走 `research_service_import`，标 secondary。
- `src/mcp_server.py`：`research_route` 描述同步。

**测试**

- 覆盖本地包 → `inventory_first`；
- 广泛外部主题 + API 启用 → `api_first`；
- API 未启用 → 回退 workflow，不报“已完成”；
- API 报告导入 → 原文覆盖不变；
- `hybrid` → API 发现 + 插件核验。

**验收**

- `research_route` 明确显示策略与理由；
- API 报告不会被当成“本地 inventory 已覆盖”；
- 默认 `inventory_first`，不影响现有 `research_*`。

### R5：Discovery → Claim → Wiki（P1，3–4 天）

**改什么**

- `src/discovery.py`：`draft_claims: true` → 从 `usable` evidence 抽逐字首句（≤240 字），返回 `claims[]`（`quote`、`url`、`capture_id`、`inference=false`）；不生成新论断。
- `src/mcp_server.py`：`discovery_bundle` schema 加 `draft_claims`。
- `src/research.py`：`research_import_evidence` 支持从 `capture_id` 导入；`research_record(entries)` 批量；`research_finish` 的 `wiki_follow_up.draft` 可直接接收 discovery claims。
- `src/wiki.py`：不变；`wiki_write` 仍要求 reviewed claim。

**测试**

- 逐字引文必须在归档正文中；
- 摘要/改写不能当 claim；
- 批量 review + `wiki_write`；
- 一次问题 → 6 条 claim → 1 页 Wiki；
- 上下文只含 claim 与 draft，不含全文。

**验收**

- 一次云厂商调研 → `discovery_bundle(draft_claims)` → 6 条 claim → 批量确认 → `wiki_write`；
- Wiki 从 write-only 变成 read-write loop；
- 用户动作 ≤2 次（审阅草稿、确认写入）。

### R6：测量、文档、发布（P2，2 天）

**改什么**

- `src/mcp_server.py` / `src/settings.py`：`get_settings` 返回 `usage`（`wiki_search`、`search_web`、`fetch_web` 次数；本地计数，不上报）。
- `skills/bookmark-research/SKILL.md` + `references/`：默认流水线、fetch 归属、deep policy、Wiki 预检。
- `README.md` / `README.zh.md` / `docs/details*.md` / `docs/prompt-reference*.md`：工具表、设置、流程。
- `docs/release-notes-0.5.0-beta.16.md`：变更、边界、验收。
- `tests/`：全量 + 新增 ≥40 项。

**验收**

- 756 + 新增测试全过；
- 真实包 3 个场景通过；
- `npm beta` 发布；`latest` 不动；
- 发布说明写清“未取得正文”“证据不足”“Wiki 需审阅”。

## 5. API 契约（草案）

### 5.1 `plan_research` 新增字段

```json
{
  "wiki": [
    {
      "page_id": "rag-search-and-mcp-20260912",
      "title": "RAG、Agentic Search 与 MCP：书签证据笔记",
      "summary": "...",
      "updated_at": "2026-09-12T14:35:35Z",
      "validation": "current",
      "score": 0.82
    }
  ],
  "archive": [
    {
      "capture_id": "20261019T084437179198Z-f89368fc486e",
      "url": "https://...",
      "title": "...",
      "characters": 7448
    }
  ],
  "freshness": {
    "intent": true,
    "newest_local": "2026-10-17",
    "newest_local_confidence": "high",
    "stale": false,
    "reason": "question asks for current changes"
  },
  "fetch": {
    "owner": "plugin",
    "fallback": "host",
    "reason": "URLs will be cited"
  },
  "deep_research": {
    "policy": "inventory_first",
    "reason": "task covers a local bookmark package"
  },
  "required_tools": ["wiki_get", "fetch_web"],
  "skip_conditions": {
    "search_web": "wiki.current and freshness.stale=false"
  },
  "seed_queries": ["..."]
}
```

兼容：旧字段 `terms`、`cards`、`urls`、`task_shape`、`route` 保留。

### 5.2 `fetch_web` 新增参数

```json
{
  "urls": ["https://..."],
  "return": "handle",
  "max_characters": 12000
}
```

`return` 默认 `text`；`handle` 返回：

```json
{
  "pages": [
    {
      "url": "https://...",
      "title": "...",
      "capture_id": "...",
      "content_state": "usable",
      "characters": 7448,
      "published_at": "2026-09-10",
      "sha256": "..."
    }
  ]
}
```

### 5.3 `discovery_bundle` 新增字段

```json
{
  "sources": [
    {
      "url": "https://...",
      "capture_id": "...",
      "text_sha256": "...",
      "content_state": "usable"
    }
  ],
  "draft_claims": true
}
```

`text_sha256` 与归档正文不匹配时报错；`text_origin` 为 `archive` 时 `quote_verified=true`，为 `host` 时 `quote_verified=false`。

## 6. 设置项

```json
{
  "fetch": {
    "policy": "plugin_first",
    "fallback": "host"
  },
  "deep_research": {
    "policy": "inventory_first"
  },
  "wiki_preflight": true,
  "freshness_days": 30,
  "search": {
    "seed_on_freshness": true,
    "seed_on_local_miss": true,
    "seed_on_compare": true
  },
  "context": {
    "fetch_handle_default": false,
    "get_context_compact_default": false,
    "search_bookmarks_projection_default": false
  }
}
```

默认值保持兼容：不改变现有 `fetch_web` 返回全文、`get_context` 全量、`search_bookmarks` compact 行为；新行为通过参数或设置启用。

## 7. 测试计划

### 7.1 单元测试

- `tests/test_research_plan.py`：预检 Wiki/归档/新鲜度/missing file/URL 多样性；
- `tests/test_evidence_state.py`：`content_state` 质量回退；
- `tests/test_discovery.py`：`capture_id`、sha 校验、`draft_claims`；
- `tests/test_web_search.py`：provider 画像、health、budget；
- `tests/test_output_location.py`：`wiki_follow_up`、claim 批量；
- `tests/test_mcp_server.py`：新 schema/描述/必填；
- `tests/host-discovery.test.js`：seed search、preflight、host_fetch 导入。

### 7.2 集成测试

- 真实包 `github-bookmark-canvas`：
  1. “RAG 企业落地要点” → Wiki 命中 + 本地 A-1-1；不触发 `search_web`；
  2. “最近云厂商 Agent Runtime 有什么变化” → Wiki miss + 本地 10/17 + `search_web` seed + `fetch_web`；
  3. “书签包里没有的新主题” → `route: null`，询问后搜。
- 小包 `书签画布-关于书签数据包的AI化升级调研-20260906-125939`：245 items / 223 bookmarks / 4 sections，作为回归样本；不提交用户数据。

### 7.3 上下文验收

- 同一研究轮：插件工具结果 <40%；`fetch_web` <10k；`discovery_bundle` <20k；
- 100% 证据带 `capture_id`/sha；
- 无重复 fetch 同一 URL。

## 8. 指标

| 指标 | 现状 | 目标 |
|---|---:|---:|
| `wiki_search` 触发率 | 0/19 会话 | 每次预检都查（100%） |
| `search_web` 触发 | 1/19 会话 | 按条件触发（最近/对比/本地缺失） |
| `fetch_web` 上下文 | 98k/轮 | <10k/轮 |
| 插件上下文占比 | 64% | <40% |
| 证据带 capture_id | 未统计 | 100% |
| Wiki 复用 | 0 次 search | 每次预检先查 |
| 用户动作 | 不等 | ≤2 次（审阅、确认） |

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 外部搜索过度触发，成本/配额上升 | 只在 freshness/local miss/compare/明确要求时触发；`seed_on_*` 可关 |
| Wiki 过期/错误被复用 | `validation` 门槛；`needs_review` 先 `wiki_refresh`；不自动发布 |
| 宿主不照 `required_tools` 执行 | 返回 `skip_conditions` 和理由；Skill 写死顺序；必要时 workflow 脚本 |
| API 报告被误当本地覆盖 | `research_service_import` 标 secondary；`research_finish` 记录来源 |
| handle 模式丢失细节 | `research_source(capture_id, offset)` 按需续读；`discovery_bundle` 保留摘录 |
| 旧客户端不兼容 | 新字段/参数可选；默认行为不变；旧 schema 兼容 |
| 真实包数据隐私 | 只发公开 URL；不提交用户包；测试用合成/脱敏样本 |

## 10. 发布与回滚

- 目标 `0.5.0-beta.16`；npm `beta` 通道；`latest` 保持 beta.14。
- 分两个提交：
  1. `feat(plan): preflight with wiki/archive/freshness`;
  2. `feat(fetch): handle mode, capture_id evidence, trigger policy`.
- 回滚：设置 `wiki_preflight=false`、`fetch.policy=plugin_only`、`search.seed_on_*=false` 可恢复旧行为；新字段不影响旧调用。
- 发布说明写清：未取得正文、证据不足、Wiki 需审阅、API 为二级证据。

## 11. 未决问题

1. 是否给 DSH 加工具 allowlist（44 → 8），还是只在 Skill 里引导？建议先做 allowlist 实验，测量 schema 上下文。
2. 是否增加 host `web_search` 桥（宿主搜、插件读/归档）？建议作为可选 `search.host_bridge`，默认关。
3. 是否在本轮加浏览器/Cloudflare 并发？建议不；单独立项，避免边界和合规风险。
4. 是否把 API provider 从 OpenAI/Parallel 扩到更多？建议不；先把 policy 和 secondary 证据语义做好。
5. 包级证据根（sidecar）是否与本轮一起做？建议分开；本轮只做 handle/capture_id，不动存储根。

## 12. 参考映射

| 参考 | 借什么 | 落到哪 |
|---|---|---|
| `smartsearch-main/src/smart_search/intent_router.py` | URL/latest/docs/vertical 意图路由 | `src/research_plan.py` |
| `smartsearch-main/src/smart_search/service.py` | provider 画像、capability chain、health/cooldown | `src/web_search.py`、`config/providers.json` |
| `aether-search-main/src/aether_search/server.py` | `toggle_builtin_tools` 的宿主工具开关思路 | `fetch.policy`、Skill |
| `aether-search-main/src/aether_search/agent.py` | seed fan-out、RRF、6 步/90 秒 | `hosts/shared/discovery-flow.js` |
| `aether-search-main/src/aether_search/sources.py` | 会话源缓存 | `search_web`/`discovery_bundle` 的 `session_id` |
| `书签画布-关于书签数据包的AI化升级调研-20260906-125939/AGENTS.md` S6.0 | 调研前识别 Deep Research/搜索 Agent/MCP/Skill | `plan_research` 预检、Skill |

## 13. 时间表

| 周 | 工作 |
|---|---|
| 第 1 周 | R1 预检、R2 fetch 归属/上下文 |
| 第 2 周 | R3 触发规则/provider、R4 Deep research 策略 |
| 第 3 周 | R5 Discovery→Claim→Wiki、R6 测量/文档/发布 |
| 发布前 | 全量测试、真实包 3 场景、npm beta |

总计约 2–3 周；如果只做 P0（R1 + R2 + R3 的核心），约 1 周可出 beta.16。
