# Bookmark Research 0.5.0-beta.15 改进计划（2026-10-17）

> 本轮主题：**把 README 的三条基础路线串成默认流——问题 → 本地定位链接 → MCP 抓取/搜索 → 证据 → Wiki。**
>
> 依据：
> 1. README 的“三个基础”（本地理解 / 外部调研三条路线 / 可复核知识存储）；
> 2. 2026-10-17 真实画布包实测（`github-bookmark-canvas`，4,966 items / 4,130 bookmarks / 3,079 unique URLs）＋同日联网冒烟（2 目标 × 2 提供商、3 个 URL、2 份归档）。
> 3. 参考项目 `smartsearch-main`（能力路由、`deep` 规划 → `research` 实跑、`fetch_before_claim`）与 `aether-search-main`（seed fan-out + tool loop、RRF、探活/印证）；
> 4. 用户判断：**“用户想调研时，自动通过 MCP 去抓关键链接；不拿链接、不联网搜索，插件怎么知道？拿完链接就是 Wiki。”**
> 5. **本轮立项前的代码核对**（§0.5、§0.6）：把“已有能力”与“真缺口”分开，避免重复立项。
>
> 本文件是计划，不是实现记录；不随本轮改动发版。

## 0. 基线

### 0.1 README 定义的三个基础（本计划的框架）

| 基础 | README 原文要点 | 现状 |
| --- | --- | --- |
| 本地理解 | 卡片/分组布局、连线方向与标签、跨卡片副本（空间）；日期字段、ID 日期段、真正改过内容的 Git 提交（时间）；纯离线 | 空间可用；时间只到“能手工推”，无 `added_at` 列（§4.1） |
| 外部调研三条路线 | ① 读取已知 URL 不需要推理；② Agentic 搜索由宿主模型规划、搜索、阅读、追缺口；③ 深度研究加入持续清单、独立核验、覆盖检查与报告；OpenAI/Parallel 为可选路线 | 三条都能跑。②的循环在宿主侧，插件只声明步骤、不计数（§2.3 已定为编排式）；①没有内容状态；③的引文门槛与缺口记录**已存在**（§0.6），缺的是自动触发 |
| 可复核知识存储 | 研究沉淀为 Wiki：已审核页面、带历史版本与互链，之后直接复用 | `wiki_write` 可用，但要求**已审阅 claim**；research → claim → review → wiki 的“人工逐条确认”仍是断点（§3.2） |

> README 同时明确：**无头浏览器与爬虫类项目不在集成范围内。** 本计划默认遵守这条边界（见 §9 决策项）。

### 0.2 本次实测（本地 + 联网）

- 本地：38 sections / 47 nodes / 6 groups / 14 edges / 25 memberships；25 条包含关系逐条正确；41 张卡 0 重叠；3 实例 / 1 URL 的副本识别正确。
- 时间：`tempId_YYYYMMDD` 覆盖 3,673/3,913 条（**口径存疑**，2026-10-18 复核见 §4.1）；永久树 `dateAdded` 1,241 条；edge epoch 可还原 06-27 → 09-08；170 次提交，最近 push 10-17 22:52:18（+152/−2）。
- 联网：`search_web` 2 目标 × 2 提供商全成功（RRF k=60）；`fetch_web` 3 URL / 2 capture；但 `developers.google.com/edge/foresight` 仅 284 字符（“No additional info available”）仍记为成功；Google Blog 正文有 “OCT. 6, 2026” 而 `provider_published_at: null`。

> **复现要求**：`tempId` / `dateAdded` 这两个字段名在 `src/`、`tests/`、`docs/` 中都不存在，只来自这次对真实包的观测。§10 必须记录本次实测包的绝对路径与提取脚本，否则 3,673 / 1,241 这两个数字无法被实现者复现或证伪。

### 0.3 参考项目可借鉴的机制

| 项目 | 机制 | 用在哪 |
| --- | --- | --- |
| smartsearch | 能力路由 + 同能力 fallback；`deep` 离线规划、`research` 实跑（plan → discover → fetch → gap check → evidence-only）；Cloudflare 挑战标记 | 路线 ②③ 的**规划**与能力路由；“挑战标记”并入 §5.1 |
| aether | 无条件 seed fan-out；tool loop（`search_multi`/`fetch_page`，6 步 / 90s）；超时降级 digest → 原始证据；探活 404/410；跨通道印证；RRF | 路线 ② 的**循环形状**与“永不空输出”；注意其工具名与本插件现有工具名不同（§2.3） |

不搬：Grok 通道（第三方模型直接出答案，和“宿主洗稿”冲突）、桌面 App、provider 扩张。

> `fetch_before_claim` 不再列为“待借鉴”：本插件 `research_record(kind=claim)` 已强制引文逐字存在于已抓正文（§0.6）。

### 0.4 问题清单

| # | 问题 | 侧 | 严重度 |
| --- | --- | --- | --- |
| 1 | 没有“问题 → 链接”的默认自动流，用户得先自己选卡片/贴 URL | 产品 | P0 |
| 2 | 空壳/JS 壳页无状态，284 字符也算成功 | 联网 | P0 → 已解决（§5.1；见 §10） |
| 3 | 研究结束没有 Wiki 草稿；且 claim 逐条人工确认的成本未被计量 | Wiki | P0 |
| 4 | 路线 ② 的循环在宿主侧；插件只**声明**步骤、不计数，而宿主 workflow 层也没有步数上限 | 联网/架构 | P0（原 P1 上调，见 §2.3） |
| 5 | 路线 ③ 缺**自动**缺口发现与补抓；缺口“记录”与“证据不足即拒答”已存在 | 联网 | P1 |
| 6 | 无探活、无跨来源印证、`published_at` 只取了 provider 元数据一层 | 联网 | P1 |
| 7 | `get_context(collection="items", section=…)` 返回 0，与同一响应里的 `bookmark_count` 自相矛盾 | 本地 | P1 |
| 8 | 无 `added_at`；edge 按 id 字典序；导入根目录失败；重名 label | 本地 | P1/P2 |

### 0.5 与既有计划的关系

| 文件 | 本轮处置 |
| --- | --- |
| `plugin-improvement-plan-2026-10-15.md` §2.1 引文级复核、§2.2 批量刷新 | **本轮不排**，R1–R5 已满；明确保留待办，不回退其验收口径 |
| `plugin-improvement-plan-2026-10-15.md` §3.3 提供商健康跨进程持久化 | 本轮不排，可作为 §5.2 的后续积木 |
| `plugin-improvement-plan-2026-10-15.md` §4.1 “`wiki work` 只读草稿大纲：按 question 分组 eligible claims，附引文首句” | **与本轮 §3.1 同源**，合并实现，验收样本沿用该计划记录的 `r-eb7778ec8c954b9a`（16 条 eligible claim） |
| `knowledge-storage-plan.md` | 语义边界不变；§4.2 的日期透传不得破坏 hedge/waterfall 与缓存复用语义 |
| `search-hedge-plan-2026-10-14.md` §7.6“子代理编排开箱化”（子代理调插件已实测：23 次调用、约 12.6 分钟；bundle 内 `workflows/bookmark-research.js` 待启用与验证） | **与本轮 §2.3 同源**，并入路线 ②：编排接缝已在包内，本轮补预算计数与发现脚本 |

### 0.6 已存在、本轮不重复立项的能力

| 能力 | 位置 | 结论 |
| --- | --- | --- |
| 引文必须来自已抓正文，逐字校验 | `src/research.py:1297`（`quote not in body` 即拒）、`:1247`、`:1079` | **已实现**，无需重做；§2.4 只写“复核 + 用例” |
| claim 需要审阅、`wiki_write` 需要 reviewed claim | `src/mcp_server.py:358` | 已实现，门槛保持 |
| 缺口可记录并阻塞完成 | `research_record(kind="gap")`（`research.py:1539`）、`research_finish` 输出 `Unresolved:`（`:1744`）、“completed 要求无未解决冲突”（`mcp_server.py:269`） | **已实现**，缺的是自动发现 |
| 会话预算 | `research.py:30` `DEFAULT_BUDGET = {max_search_calls:16, max_fetch_calls:12, max_rounds:8}` | 已实现，路线 ③ 的预算不需要新造 |
| 卡片内 URL 与实例数 | `search_bookmarks` 返回 `url` / `counts.instances` / `counts.unique_urls` | 已实现，§2.1 直接复用（见 §6.1） |
| 外部报告作为未审阅二级证据 | `research_import_evidence` 描述 | 已实现，§2.5 保持 |
| 档位路由（quick/agentic/deep × task_shape） | `src/routing.py:36` `route()`；`auto` 下 `investigation → agentic`、`batch_research → deep`；普通 agentic 入口是 `search_web / fetch_web`（`:124`） | 已实现，§2.3 的入口据此写 |
| 四宿主 workflow 接缝 + 共享编排脚本 | `hosts/codex/delegate.md`、`hosts/claude/runtime.js`、`hosts/pi/register-workflow.py`、`hosts/dsh/workflow-call.py`、`hosts/shared/research-flow.js`、桥 `hosts/shared/research-call.py` | 已实现，§2.3 复用而非新建 |

## 1. 目标与非目标

做：

1. **默认自动流**：研究请求 → 本地定位相关卡片与链接 → 按三条路线取证据 → 产出证据包与 Wiki 草稿建议。
2. **三条路线各自补齐**：① 抓取状态与日期；② 循环预算与降级；③ 缺口自动发现与补抓。
3. **Wiki 沉淀**：研究完成即生成“可审阅的草稿”（不自动发布），并把用户的确认动作**批量**化。
4. **时间统一**：本地 `added_at`、联网 `published_at/updated_at`，带来源与置信度。

不做：

- 不做无头浏览器/爬虫（遵守 README 边界，§9 可复议）；
- 不做 Grok/第三方模型直接出答案；洗稿归四个宿主；
- 不做 GUI、向量库、知识图谱、多模态；
- 不自动发布 Wiki、不自动改画布包；
- **不重复实现 §0.6 中已有的门槛**（引文校验、review 门槛、缺口记录、会话预算、URL/实例计数）。

## 2. 默认自动流（P0）

### 2.1 触发与范围解析

用户提出调研请求时，宿主应自动执行，**不要求用户先选卡片或贴 URL**：

1. 调 `plan_research(question, source_id, max_cards=3, max_urls=8)`（**新增工具，2026-10-18 已定**，契约见下）或手工等价步骤；
2. 工具内部用 `search_bookmarks` 定位相关卡片（默认 Top 3，按词权排序；同级再按卡片最新 `added_at` 排序，无时间的排后）；
3. 用 **`search_bookmarks(section=<卡片>, targets=[…], item_types=["bookmark"])`** 取该卡的条目（URL、note、标签），按 `url` 去重并保留 `counts.instances`；**不要用 `get_context(collection="items")`**（原因见 §6.1）；
4. 判断意图，选择路线：
   - 问题里已有 URL，或卡片里命中“官方文档/仓库” → 路线 ①；
   - 需要发现/对比/时效 → 路线 ②；
   - 明确“深度/核验/报告” → 路线 ③；
5. 取数上限：单次 ≤ 3 张卡、≤ 8 个 URL、≤ 1 次补充搜索（路线 ②/③ 另计预算）。

**`plan_research` 工具契约（2026-10-18 已定，§9 决策记录 3）**

纯本地、不发网络请求、不写盘的只读工具。它存在的理由：§2.1 与 §2.3 的验收都是宿主行为，跑不了 CI，而 §7 要求新增单测；把“选卡片 + 取 URL + 判路线”收敛成一个函数才测得动。

| 项 | 规定 |
| --- | --- |
| 入参 | `source_id`（必填）、`question`（必填，1–2000 字符）、`max_cards`（默认 3，1–3）、`max_urls`（默认 8，1–8）、`refresh`（默认 true，语义同 `search_bookmarks`） |
| 出参 | `terms[]`；`term_cards{}`（每个词指向的卡树数，“点名”判据）；`question_urls[]`（问题里已有的 URL）；`cards[]`（`section_id` / `label` / `file_path` / `hits` / `score` / `density` / `bookmarks` / `matched_terms` / `anchor_of`）；`urls[]`（`url` / `title` / `instances` / `matched_terms` / `section_ids[]` / `source_instances`）；`task_shape` + `task_shape_reason`；`depth` / `route` / `route_id` / `entrypoint` / `next_action`；`truncated`；`errors[]` |
| 排序规则 | 词权 = 词长 ÷ 命中卡片数（越具体越重），卡片按**词权和 × 密度（hits ÷ bookmarks）**排序（2026-10-19 修订：只按词权和时，1,053 条的永久树与 543 条的大卡压过 82/107 的主题卡）；URL 按它自身命中过的最重词排序，不被所在的大卡片带偏。实测：`EmbeddingGemma 2 怎么本地部署` 第一名仍是 A-1-1；`RAG 企业落地` 改为两张 A-1-1 居前、永久树退出前三（§10） |
| `route` 取值 | **复用 `routing.py` 的既有 route id**，不另起一套词表：`direct_retrieval` / `host_iterative_research` / `host_workflow` / `professional_service`。`plan_research` 只给建议，档位与失败的最终判定仍归 `research_route`（`routing.py:36`），两者不得各说一套 |
| 不做什么 | 不发网络请求、不读正文、不建研究会话、不抓取、不扩大范围 |
| 空结果 | 命中 0 卡时返回 `cards: []` 与 `route: null`，由宿主回“包里没有”，**不得**静默扩大范围 |
| URL 范围 | `urls` 是所选卡片中命中该问题的书签，按 URL 去重；匹配发生在标题或 note 上、URL 里不含问题词的书签同样会返回（每条 URL 带 `matched_terms`）。导入器拒绝无 URL 的书签（`bookmark_index._items`），因此卡片命中时 `urls` 不会为空；守卫只作防御并在代码里注明。问题文本自带的 URL 另在 `question_urls` 单列并从搜索词中剔除，路线 ① 直接读它们 |

边界：范围是“用户的书签里与问题相关的部分”，不是全网漫游；找不到相关卡片时明确说“包里没有”，再问是否扩大范围。

**2026-10-19 收口修订（评审后，代码为准）**：文档／仓库书签只有在“问题点名它”（某词只指向一棵卡树且命中该 URL 行）时才判 `lookup`，偶然命中不再把研究型问题降档；0 卡且问题不带 URL 时短路返回 `route: null`（`depth` / `route_id` / `entrypoint` 同为 null，问题自带 URL 时仍给 `direct_retrieval`）；`depth` 传 `None` 读已存的 `research.depth` 设置，不再写死 `auto`。

**用户动作预算（新增验收项）**：一次完整调研（问题 → 证据包 → Wiki 草稿）用户侧动作 ≤ 2 次（提出请求、确认草稿）；需要中途追问时才增加。

验收：对一个纯问题（如“EmbeddingGemma 2 怎么本地部署”），不要求用户指定卡片即可命中 A-1-1 并抓取其中 2–3 个链接。自动化部分是 `plan_research` 的单测，覆盖“命中 0 卡 / 命中多卡 / 命中卡片但无 URL / 被 `max_urls` 截断”四条分支；宿主是否真的照做属**人工验收**，记录到 §10，附原问题与命中卡片。

### 2.2 路线 ①：读取已知 URL（无推理）

- 输入：URL 列表（来自卡片）；
- 并发与超时**沿用现有旋钮，不新造常量**：并发用 `server.network_workers`（默认 4，1–16，需重启生效）；单 URL 超时用全局 `timeout_seconds`（1–60）；
- reader 链沿用现有 provider（parallel/exa/jina/tavily），瀑布流沿用 `fetch.strategy`（默认 `staggered`）＋ `fetch.grace_seconds`（默认 25）＋ `fetch.deadline_seconds`；单页与总量沿用 `fetch.max_characters`（默认 12000）；
- 归一化：`title / text / sha256 / characters / status / content_state / published_at / fetched_at`；
- 内容状态（见 §5.1）：`content_state` = `usable` / `content_insufficient` / `js_shell_suspected` / `challenge_blocked` / `soft_404` / `paywall_suspected`；
- 归档沿用 capture（manifest + page body）。

验收：8 URL 并发总耗时 ≤ 最慢单页 + 2s；284 字符页面被标 `content_insufficient`，不计入可引用证据。

### 2.3 路线 ②：Agentic search（**已定方案 B：编排式**，2026-10-17）

**决策**：预算落到**插件侧计数 + 四宿主 workflow 接缝**，不新增通用编排 MCP 工具。依据：

- 插件已有路由决策点：`research_route`（`src/routing.py:36`）按 `depth` 与 `task_shape` 选路线，`auto` 下 `investigation → agentic`；普通 agentic 的入口本就是 `search_web / fetch_web`（`:124`），只有批量才落到 `research_start / research_*`。
- 四宿主 workflow 接缝已在包内（§0.6）。共享脚本 `hosts/shared/research-flow.js` 开头已经把原则写死，照抄即可：**“Thin choreography only. The host owns agents, concurrency, cancellation and replay. ResearchSessions owns the inventory, evidence, reviews, budgets and completion gate.”**
- **宿主侧没有步数上限**。DSH `workflow` 工具（[W7][W8]，developer preview）文档只给 `maxResultChars`（默认 50000）与 deployment-fixed 的 provider/caps/toolName，**未给步数、子代理数或墙钟上限**；取消或异常结束一律返回错误，“partial output is never reported as success”。所以“步数 ≤ 6、总超时 90s”**只能由插件自己数**。

落地：

1. **单问题不启动 workflow**：宿主直接用 `search_web` + `fetch_web`。DSH 官方写明 `workflow` “use it only when the user explicitly requests a workflow or large multi-agent orchestration”，小任务用普通子代理/工具调用。
2. **批量/并行发现**沿用现有会话作为**唯一预算权威**（复用 `research_*` 状态，不另起一套；`routing.py` 的 batch 分支已经指向它），补上发现轮次所需的 `budget` 语义；宿主侧由 `scripts/host_assets.py build_workflow` 生成与 `hosts/shared/workflow.json` 并列的发现脚本。
3. **预算**：步数 ≤ 6、总超时 90s、查询变体 ≤ 3、抓取 ≤ 8，全部在插件侧计数；超时/工具不支持 → 用已收证据生成 digest，再不行退回证据列表，**永不空输出**。
4. **返回值约束**：宿主只见**一个最终 JSON**（“The model sees one final outcome, never intermediate child messages”）；证据包必须 ≤ `maxResultChars`（默认 50000），超出会被截断且**截断内容没有取回句柄**。因此证据包按条给 excerpt 上限，不塞整页正文。
5. **阻塞语义**：DSH workflow 前台执行会阻塞父轮次直到完成并 dispose；90s 因此是用户体验约束，不是可省的优化。
6. 可与路线 ① 并发：卡片 URL 先抓，同时发 1 次 seed search，结果按 URL 去重合并。

验收：单测覆盖“预算耗尽降级非空 / 连续两步无新增即停 / 工具报错降级 digest / 证据包不超 `maxResultChars`”；3 步内对“EmbeddingGemma 2 本地部署”给出 ≥ 3 条带 URL 的证据。

[W7]: https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/workflow
[W8]: https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/workflow/tool-workflow/README.md

### 2.4 路线 ③：Deep research

复用现有 `research_*` 会话。**先明确已有什么，再定补什么**：

| 事项 | 现状 | 本轮做什么 |
| --- | --- | --- |
| 结论只引用已抓正文 | **已有**：`_citations` 强制引文逐字存在于正文（`research.py:1297`），无正文来源直接拒（`:1247`） | 只补用例与文档措辞，不重写 |
| 缺口记录 | **已有**：`kind="gap"` → question `unresolved`；`research_finish` 输出 `Unresolved:`；completed 门槛已要求无未解决冲突 | 不动数据模型 |
| 缺口自动发现与补抓 | **缺**（这是 agent 侧判断，不是缺失字段） | 新增：按子问题核对已收证据的覆盖，缺口触发 1 轮补抓或标 `unsupported` |
| 证据不足即输出“不足 + 缺口清单” | **半有**：门槛会拒绝 completed，但不生成“不足 + 缺口”的成型答复 | 新增：证据不足时输出固定形状的“不足 + 缺口清单”（不是流畅答案） |

预算：沿用 `DEFAULT_BUDGET`（`max_search_calls:16` / `max_fetch_calls:12` / `max_rounds:8`）与 `LIMITS`（上限分别为 120 / 80 / 40）。两处口径要对齐现有实现：

- “子问题 ≤ 6”是本轮**自设的更严预算**（`research_start` 的 `questions` 上限是 24），要显式传 `budget`，不能改默认值；
- “抓取 ≤ 24”高于默认 12、低于上限 80，同样只在本次任务显式传 `budget`；若想让它成为常态，改 `DEFAULT_BUDGET` 需说明对既有任务恢复语义的影响。

**不加墙钟时长预算**：研究会话可恢复，10 分钟墙钟在恢复语义下没有定义。

验收：对“RAG 企业落地要点”产出 ≥ 3 条证据、≥ 1 个明确缺口（或说明无缺口），每条结论可回引 capture。

### 2.5 可选路线：OpenAI Deep Research / Parallel Task API

保持现状：默认关闭，开启后作为路线 ③ 的替代执行器；插件只导入其报告为**未审阅二级证据**，原始 URL 覆盖需另行读取（现有语义不变）。

### 2.6 洗稿边界

- 插件只交付证据包：`evidence[]`（id/url/title/excerpt/published_at/sha）、`citations[]`、`gaps[]`、`conflicts[]`；
- 四个宿主（Codex / Claude / Pi / DSH）负责组织语言、取舍、翻译、成文；
- 成文必须引用 `evidence[].id`，不引用未抓取的 URL；
- 插件不做文风判断，只判断引用是否成立。

## 3. Wiki 沉淀（P0）

### 3.1 研究结束即给草稿

`research_finish` 或卡片报告完成时，自动生成 **Wiki 草稿建议**（只读）：

- 页面标题/别名、分节标题；
- 每条结论对应的 `evidence[].id` 与原文摘录；
- 未支持/冲突项单列，不进正文；
- 默认行为沿用 `wiki.after_research = suggest`（`settings.py:73`）：先问，不自动发布。

> 与 `plugin-improvement-plan-2026-10-15.md` §4.1 的同源项合并：那份计划的“按 question 分组 eligible claims、附引文首句”的输出形状直接作为本节的草稿大纲，验收样本沿用 `r-eb7778ec8c954b9a`（16 条 eligible claim）。

### 3.2 从证据到 claim

现状是断的：`wiki_write` 要求 `research_id + claim_id` 且 claim 已审阅，而研究只产证据。补：

1. 草稿阶段把“证据摘录”转成候选 claim（标注 `inference=false`，引文逐字）；
2. **一次批量确认**：用户确认后对整批调 `research_record`（支持 `entries` 批量，最多 50 条），不是逐条；
3. 再做 `wiki_write`（保留 `review` 门槛与 `expected_revision`）。

不自动把“模型推断”写成 claim；推断必须 `inference=true` 且单独标注。

**交互成本验收（新增）**：16 条 claim 的任务，用户确认动作 ≤ 2 次（审阅草稿、提交批量）；草稿必须标出“逐字引文”与“推断”两类，便于一次判断。

### 3.3 复用

- 后续问题先 `wiki_search` / `wiki_get`，命中已审核页面就直接用，仅对过期/缺失部分联网；
- Wiki 页面带 `source_url`，刷新走现有 `wiki_refresh`。

验收：一次研究后能生成 1 页草稿（≥ 3 条 claim、每条有 evidence id），用户确认后成页；再次提问命中该页而不重复抓取。

## 4. 时间信号统一（P1）

### 4.1 本地 `added_at`

| 来源 | 解析 | 语义 |
| --- | --- | --- |
| `tempId_YYYYMMDD_hash_*` | 日期段 | 条目生成/导入线索，不等于阅读时间 |
| `syncId_YYYYMMDD_hash_*` | 日期段 | 同步批次线索 |
| 永久树 `dateAdded` | epoch ms | 收藏时间；批量导入时≈迁移时间 |
| `edge - N -<epoch>` | epoch ms | 关系创建时间 |

**数据落点（2026-10-18 实测确认，已实现）**：`tempId_` / `syncId_` 日期段在 **`item_id`** 里；`dateAdded` 是 **`items.raw_json` 里的裸整数 epoch ms**（permanent 树节点字段）；edge 时间在 **`edge_id` 尾部**（`edge - 9 -1782572278545`，中间那个数是计数器不是时间）。落成三列 `added_at` / `added_at_source` / `added_at_confidence`，`user_version` 1 → 2：打开旧库时 ALTER 三列并用**库内 `raw_json`** 回填（不读包、不重建索引），`added_at_precision` 由来源派生（`dateAdded` 与 `edge_epoch` = millisecond，`id_date_segment` = day）。取值优先级：`dateAdded`（high，收藏时间）> id 日期段（low，生成/导入线索，**明确不等于阅读时间**）。无信号时 `added_at` 输出 `null`，不回落到抓取时间或文件 mtime。edges 在 `context()` 里按解析时间升序、无时间的排末尾（保持 id 稳定序）。

实测（`~/Downloads/kk/Bookmark-Canvas/bookmark/书签画布/`，4,926 items / 4,104 bookmarks / 14 edges）：`dateAdded` **1,241 条，与 §0.2 完全一致**；回落到 id 日期段 3,685 条；**4,104 条书签全部有 `added_at`**，跨度 2025-11-17 → 2026-10-17；14 条 edge 全部解析（2026-06-27 → 09-08，与 §0.2 一致）。§0.2 的“3,673/3,913”应按今日口径改读为“3,685 条回落 / 4,926 items”：分子同量级，分母是当时的快照。

### 4.2 联网 `published_at` / `updated_at`

优先级：provider 元数据 → JSON-LD/OG/meta → 正文日期正则 → `null`（低置信度）。现状只有第一层（`archive.py:435` 的 `provider_published_at`）。抓取时间不冒充发布时间；search 片段的 `Published:` 透传到 fetch。

验收 fixture（**2026-10-18 按实测重写**；原始响应存为 `tests/fixtures/exa-fetch-evidence-states-20261018.json`，并由单测离线回放）：

| URL | 字符（原计划） | 期望与实测 |
| --- | ---: | --- |
| `developers.googleblog.com/embeddinggemma-2-the-developer-guide/` | 9,973（原 14,577） | `published_at=2026-10-06`（provider_metadata，high）✓ |
| `developers.google.com/edge/foresight` | 1,411（原 284） | `published_at=null` ✓，`content_state=js_shell_suspected`（原期望 content_insufficient：该 URL 今天返回的是 1,411 字符的导航壳，见 §10） |
| `www.deepseek.com/harness/` | 3,437（原 4,433） | `published_at=null` ✓ |

## 5. 证据质量与核验（P1）

### 5.1 内容状态：一个权威字段，不与现有词汇打架

现状有两套已存在的信号，**都保留原义**：

- `status`：`ok` / `partial` / `error` / `unverified`（瀑布流质量）；
- `extraction_status`：`extracted` / `provider_error` / `request_failed` / `no_content_returned` / `content_present_unparsed` / `unrecognized_or_not_returned`（取数与解析通道）。

新增的是**内容形态**，单独一个字段 `content_state`，映射关系如下（`_fetch_coverage`，`web_search.py`）：

| 现有信号 | `content_state` | 说明 |
| --- | --- | --- |
| `extracted` 且字符 ≥ 400，无壳页标记 | `usable` | 可引用 |
| `extracted` 且字符 < 400，或命中空壳标记（“No additional info available”） | `content_insufficient` | 不可引用；现在的 `status=ok` 只看 `body is not None`，这就是 284 字符页被判成功的原因 |
| `no_content_returned` | `content_insufficient` | 真无正文 |
| `content_present_unparsed` | `usable` + 标注 `parse_gap=true` | 本地解析缺口，**不**消耗提供商熔断（既有语义） |
| `request_failed` / `provider_error` / `unrecognized_or_not_returned` | `usable` 之外，单列“未取得正文 + 原因” | 未取得正文，原因归传输/提供商 |
| 有标题无正文段落且字符 < 4,000（按剥掉链接后的正文权重判定） | `js_shell_suspected` | 实测修订：1,411 字符的导航壳仍属此类 |
| 命中 Cloudflare/JS 挑战标记 | `challenge_blocked` | 新增判定 |
| 短页且命中 SSO/登录墙标记（`sign in to continue`、`请登录` 等） | `login_required` | 新增判定；R4 验收中登录壳页被误当正文后补上 |
| 200 但标题/正文含 not found | `soft_404` | 新增判定 |
| 订阅墙标记且可用正文 < 600 | `paywall_suspected` | 新增判定 |

`content_state != usable` 一律不进“可引用证据”；报告中单列“未取得正文 + 原因”。

### 5.2 探活与印证

- 死链：HEAD/GET 探测，404/410 → `dead`，不引用；
- 印证：同一 URL 被 ≥ 2 个 provider 命中 → `corroborated`（只证明链接重叠，不证明内容为真）；
- 冲突：两个已抓取来源对同一事实不一致 → `conflicts[]`，交宿主呈现。

## 6. 本地结构修复（P1）

6.1 **`get_context` 的诚实性**（原“让 items 返回”改口径）。
`context()` 只在传 `item_id` 时填 `items`（`bookmark_index.py`），代码注释写明上下文有意“bounded to section headers”；`page_context`（`context_output.py`）只是对数组分页。因此 `collection="items"` + 仅 `section` 时 `pagination.items.total = 0`，而同一响应里 `sections[].bookmark_count` 非 0，**自相矛盾**。修法：

1. **取卡片 URL 改走 `search_bookmarks(section=…)`**（本就返回 `url`、`counts.instances`、`counts.unique_urls`），§2.1 第 3 步据此改写；
2. `get_context` 侧只做诚实报数：`collection="items"` 且无 `item_id` 时，`pagination` 里给出 `included` 与原因（如 `requires item_id`），不再静默报 0；
3. 不做“让 context 吐整卡 items”。一张卡可能有几百条，会直接撑爆宿主上下文。

6.2 导入根目录自动下探一层；失败时给出候选包根。
6.3 重名 section label 消歧（A-1-1 ×2）：给 `section_id` + `file_path`。
6.4 未分组卡片：`related_nodes` 增加“最近分组 + 间距”。
6.5 `retained_missing_files` 在计数与报告中标注“无画布位置”。

## 7. 测试与发布门槛

**自动化**（本仓库为 Python，测试用 pytest）

- 单测：日期解析、edge 时间排序、`published_at` 三层提取、`content_state` 映射全表、search→fetch 日期透传、`plan_research`（已定，四条分支 + 与 `research_route` 的 route id 一致性）、路线 ② 预算计数与降级（§2.3 已定编排式）、claim 草稿门槛与批量确认。
- 集成：真实网络冒烟（1 次 search + 3 个 fetch，含 1 个 JS 壳页）。
- 回归：现有 **692** 项全过；新增 ≥ 40 项（**且不含人工验收项**）。

**人工验收**（记录进 §10，不计入 ≥ 40）

- “纯问题 → 定位卡片 → 抓链接 → Wiki 草稿”端到端一次，附原问题、命中卡片、用户动作数；
- 路线 ② 批量发现：一次真实 `workflow` 调用，检查最终 JSON 是否超 `maxResultChars`、中间子代理消息是否确实不可见。

**发布**：仅 npm `beta` 通道；release notes 写清“未取得正文”“证据不足”“Wiki 草稿需审阅”。

**工具面改动的连带成本**：若采纳 §9 决策项 3，新增 `plan_research` 必须同步 `skills/bookmark-research/`、`docs/prompt-reference.md`、`docs/details.md`、README（中英）与 `tests/test_mcp_server.py`。

## 8. 实施顺序

| 轮次 | 内容 | 完成标志 |
| --- | --- | --- |
| R1（2 天） | §2.1 范围解析（新增 `plan_research` 工具 + Skill／docs 文案，**不含**新鲜度排序；新鲜度留到 R2）＋ §6.1 诚实报数 | 纯问题能自动命中卡片与链接；单测覆盖 0 卡／多卡／有卡无 URL／截断四条分支；`skills/`、`docs/prompt-reference.md`、README 与 `tests/test_mcp_server.py` 同步 |
| R2（2–3 天） | §2.2 抓取状态 + §4.1 `added_at`（含 `user_version` 升级）+ §4.2 `published_at` + §5 ＋ 启用 R1 的新鲜度排序 | 284 字符页有明确结论；日期 fixture 通过；新旧索引升级路径可用 |
| R3（2 天） | §2.3 路线 ②（插件侧预算计数 + 发现脚本 + 与路线 ① 并发） | 单测覆盖降级、停止与 `maxResultChars` 上限；一次真实 workflow 冒烟 |
| R4（2–3 天） | §2.4 自动缺口与 evidence-only + §3 Wiki 草稿 → 批量确认 → claim → 页面 | 一次研究生成可审草稿；16 条 claim 确认 ≤ 2 次动作 |
| R5（1 天） | §6.2–6.5 消歧与导入体验 | 新包首次导入不用猜路径 |

每轮结束：全量测试 + 真实网络冒烟 + 更新 §10。

## 9. 风险与决策项

**决策记录（逐条落定后才开工对应轮次）**：

1. ~~路线 ② 预算落地方案~~ **已定：B（编排式，2026-10-17）**。落在插件侧计数 + 四宿主 workflow 接缝，**复用 `research_*` 会话作为唯一预算权威**（早先草案里“不复用 `research_*` 状态”一句作废）。R3 可直接开工，无需再等决策。R3 实际落地为插件侧计数 + `discovery_bundle` 判定，未接入 `research_*` 会话；差异与理由见 §10 R3。
2. **内容状态字段**：确认新增 `content_state` 而不替换既有 `extraction_status`，且 `status` 语义不动（§5.1 映射表为准）。
3. ~~是否新增 `plan_research`~~ **已定：新增（2026-10-18）**。契约见 §2.1，`route` 取值复用 `routing.py` 的既有 route id。连带成本是同步 `skills/bookmark-research/`、`docs/prompt-reference.md`、`docs/details.md`、README（中英）与 `tests/test_mcp_server.py`，已并入 R1 的完成标志。
4. **`added_at` 列的升级方式**：重建索引，还是惰性补列；对已保存的旧索引是否需要一次性迁移工具。

**其他风险**：

- **无头浏览器边界**：README 明确“不在集成范围”。Cloudflare 并发抓取是合理方向，但会引入新依赖/Key 并改变公开边界；建议 beta.15 不做，先用 §5.1 状态诚实标注，另开单独决策（改边界需同步改 README 与安装向导）。
- 自动范围解析可能选错卡片：给“命中卡片 + 依据”让用户可纠正，默认 ≤ 3 张。
- 匿名 provider 配额有限：每问题 ≤ 8 URL、≤ 1 次补充搜索。
- Wiki 草稿不等于已审核：claim 需确认，推断必须标注，禁止自动发布。
- 引用可能在“洗稿”中丢失：证据包给稳定 ID，成文回引。
- 隐私：只发卡片内 URL 与查询词；归档本地。
- 与上一轮计划的排队关系：§0.5 里“本轮不排”的三项不得因为本轮新增 R1–R5 而被静默丢弃，需在下一轮计划开头重申。

## 10. 实施记录

### R1（2026-10-18，代码已改，未提交）

- **新增工具** `plan_research`：`src/research_plan.py`（问题 → 本地范围 → 路线建议）＋ `src/mcp_server.py` 的 schema、描述与分派。输入与契约一致（`source_id` / `question` / `max_cards` / `max_urls` / `refresh`），另返回 `terms`（实际搜的词）与 `task_shape_reason`，便于用户纠正。
- **本地范围**在 `src/bookmark_index.py`：`plan_terms` 抽字面词（ASCII 整段、CJK 二元组、ASCII 单字符丢弃、上限 12），`plan_scope` 按**词权（词长 ÷ 命中卡片数）**排序卡片、每棵主树只留一张（副本锚点不占名额）、每张卡带 `score` 与 `matched_terms`；URL 按 URL 去重、按**自身命中过的最重词**排序，并给 `section_ids` 与 `source_instances`（与所选范围区分）；`max_cards` 1–3、`max_urls` 1–8，越界即报错。
- **路线不新建词表**：`route` / `depth` / `next_action` 直接取自 `ResearchRouting.route(task_shape=…, host="unknown", depth="auto")`，测试断言其值等于 `research_route` 的返回。
- **§6.1**：`get_context` 未传 `item_id` 时，`pagination.items` 增补 `scope_note`（`context_output.page_context` 新增 `scope_notes` 参数，`mcp_server` 传参），说明它需要 `item_id` 并指向 `search_bookmarks(section=…)` 与 `plan_research`；`context()` 的返回结构不变。
- **契约偏差**：原“卡片命中但无 URL”一栏不可达——导入器拒绝无 URL 的书签（`bookmark_index.py:347`）——已按真实行为改成“URL 范围”，守卫保留并在代码注明。
- **测试**：新增 `tests/test_research_plan.py`（12 项）＋ `tests/test_context_pagination.py` 的 `scope_note` 用例（1 项）；全量 705 项通过、3 项跳过、131 秒（此前 692）。R1 新增 13 项；§7 的“≥40 项”覆盖 R1–R5。
- **真实包验收（2026-10-18）**：包 `~/Downloads/kk/Bookmark-Canvas/bookmark/书签画布/`（37 卡 / 4,926 items / 4,104 bookmarks / 3,067 unique URLs；比 §0.2 记的 4,966 / 4,130 / 3,079 略少，因为包此后又变过）。问题 `EmbeddingGemma 2 怎么本地部署`，不指定卡片：第一名卡片确为 `A-1-1`（`临时栏目/常规链式/A-1-1 企业知识库(RAG).json`），与独立 `search_bookmarks` 查到的唯一命中卡一致；URL 前两位正是那两条书签（`developers.google.com/edge/foresight`、`unsloth.ai/docs/zh/mo-xing/embeddinggemma-2`）；`task_shape=lookup`、`route=direct_retrieval`；纯本地 0.07 秒。边界：单字符 ASCII（`A`）明确报“无可搜词”而不是静默返空，单字符中文（`书`）正常（3 卡 / 8 URL），无匹配词同样明确报错。顺带暴露该包有重名 label（两张 `A-1-1`），输出以 `file_path` 区分（对应 §6.3）。
- **冒烟发现并修掉两个真实缺陷**：①“按原始命中数排序”会选错卡——千条大卡（A、A-10）压过真正命中的 A-1-1，URL 列表被通用 CJK 二元组的噪音占满，真 URL 掉到第 6–8 位；改为词权排序 + URL 自身词排序后，A-1-1 第一、两条真 URL 前二。② 文档站判定过窄——`developers.google.com` 不在硬编码列表里，`lookup` 被误判成 `investigation`；改为规则（`docs.` / `developer(s).` 前缀）加原有列表。两者均有单测锁定。
- **文档同步**：`README.md` / `README.zh.md` 工具表、`docs/details.en.md` 的 MCP tools 表、`SKILL.md` 与 `references/zh/skill-guide.md` 流程表、`references/package-semantics.md` 与 `zh/package-semantics.md`（`plan_research` 段落 + `scope_note` 说明）。
- **有意未做**：CLI 不加 `plan` 子命令（`cli.md` 的 MCP↔CLI 映射表保持原样）；`docs/tool-surface-audit.md` 的 40 项计数属历史审计，不改写；`docs/prompt-reference.md` 与 `docs/details.md` 不含工具清单，无需同步。
- **仍待记录 / 仍待人工验收**：R2 的时序字段提取口径与 `user_version` 升级结果；真实宿主会话里“宿主是否真按 `plan_research` 的建议去抓链接”（本轮只到证据包与路线建议，不含实际抓取）。

### R2（2026-10-18，已完成）

**§4.1 本地 `added_at`（已完成）**

- 纯解析器（`src/bookmark_index.py` 模块级）：`_added_at_from_id`（`tempId_/syncId_YYYYMMDD` → 当日 UTC 零点，非法日期返回 `null`）、`_added_at_from_epoch`（**范围校验 2001–2286**，所以 edge id 中间那个计数器不会被当成日期）、`_added_at_from_edge_id`（取尾部数字）、`_added_at_fields`（`dateAdded` 优先于 id 段）。
- 三列 + `user_version` 1 → 2，旧库打开时 `ALTER TABLE` 并**从库内 `raw_json` 回填**；`_item_result` 暴露 `added_at` / `added_at_source` / `added_at_confidence` / 派生 `added_at_precision`。
- `context()` 的 edges 按解析时间升序（无时间排末尾）；`plan_scope` 的同级排序启用新鲜度（`newest_added_at`），R1 的“延后启用”就此关闭。
- 测试：`tests/test_added_at.py` 10 项（含**手工造 v1 库**验证迁移与回填、v2 库不重复修复）；全量 **715 项通过、3 项跳过、137 秒**。
- 真实包复核：见 §4.1 的实测段；§0.2 的口径已就地标注。
- 过程中的自纠：两处 UTC 期望值我手算错了（差 1h20m），由测试暴露后按 `epoch/86400` 独立验算改正，代码未动。

**§5.1 内容状态 + §4.2 联网日期（已完成）**

- `src/archive.py` 新增两个纯函数：
  - `content_state(title, text, extraction_status)` → `unavailable` / `challenge_blocked` / `paywall_suspected` / `soft_404` / `content_insufficient` / `js_shell_suspected` / `usable`，与既有 `extraction_status`、`status` 并存（§5.1 映射表为准）。
  - `published_at(text, provider_value, reference)` → `(published_at, source, confidence)`：provider 元数据（high）→ 正文中带标签的字段（JSON-LD / meta / `<time>` / `Published:` / `发布日期`，high）→ 正文前 1,500 字符内的裸日期（low，且**不得晚于抓取日**）。
- 三处接线：`compact_fetch` 的 `pages[]`（`fetch_web` 输出）、`save()` 的 manifest、`web_search._fetch_coverage` 的 `per_url`（`research_fetch` 与覆盖度）；无正文的失败行统一 `content_state: "unavailable"`。
- 真实抓取与 fixture（2026-10-18，Exa 通道，3/3 成功；原始响应 `tests/fixtures/exa-fetch-evidence-states-20261018.json`，18.5 KB，单测离线回放）：见 §4.2 的实测表。
- **实测迫使的三处修正**：
  1. §0.4 #2 的“284 字符”今天不再复现（同一 URL 返回 1,411 字符），但那 1,411 字符**全是标题与链接导航**。因此 shell 上限从 800 提到 4,000，并改为“正文权重”判定：先剥掉链接/图片/裸 URL，再按句子标点或 ≥60 字符的行累计；该页由此得到明确结论 `js_shell_suspected`。
  2. 挑战标记加“无正文”前提：长正文里出现 `enable javascript…` 是文章主题，不是页面状态（付费墙不同：墙前的免费导语也是正文，故保留计划里的纯长度规则）。
  3. 日期正则的 `\b` 漏掉 `2026-09-08T10:00:00Z`（`8` 与 `T` 之间没有词边界），改为 `(?<!\d)` / `(?!\d)` 守卫；缺陷由单测发现。
  4. §4.2 的 fixture 表按实测重写（保留原计划数字对照）。
- 测试：新增 `tests/test_evidence_state.py` 15 项（含 fixture 回放）；全量 **729 项通过、3 项跳过、130 秒**。

**§5.2 死链与印证（已完成）**

- **印证**：`fuse_results` 本来就有 `provider_count`（去重后的 provider 数）与 `independent_fact_confirmation: false`；本轮只把信号显式化——每条结果新增 `corroborated = provider_count > 1`，并在 `ranking` 里写明“两家以上返回同一 URL 只是链接重叠，不是内容确认”。零新词表。
- **死链**：`_liveness(url)` 先 HEAD，被拒（403/405/501）再一次 GET；只有 **404/410** 记 `dead`，其余（含 200）一律 `unknown`——探测不是抓取，绝不冒充成功。`_with_liveness` 只探测**没有拿到正文**的 URL，写 `per_url[].liveness`（`dead` / `unknown` / 有正文的 `not_probed`）与顶层 `dead_urls[]`。
- **一次真实的设计回退（值得记下）**：最初把探测放在每个 provider 尝试内部，结果 ① 让离线测试开始做真实 DNS/HTTP；② 改变了瀑布流“完成即入列”的尝试顺序——`test_fetch_waterfall_parallel_fallback_only_receives_unresolved_urls` 从 5/5 通过变成 4/5 失败。我在 HEAD 版本上跑同样 5 次作对照，确认是本次引入而非既有。修法：探测只在**最外层** `fetch()` 收尾做一次，内部尝试显式 `probe=False`，并留 `_probe_opener()` 这一个可被测试替换的出口。改后该测试 5/5 通过。
- 测试：`tests/test_evidence_state.py` 增到 18 项（`dead`/`unknown`/`not_probed`、HEAD→GET 回退、两 provider 印证）；全量 **733 项通过、3 项跳过、约 130 秒**（R1+R2 共新增 41 项，§7 的“≥40 项”已达成）。

**R2 完成情况**：§2.2 的抓取字段（`content_state` / `published_at` / `retrieved_at` 即计划里的 `fetched_at`；并发与超时沿用 `server.network_workers`、`timeout_seconds`、`fetch.strategy/grace/deadline`，未新造常量）随 §5.1/§4.2 一起落地；R1 延后的新鲜度排序已启用。§8 的 R2 验收三项均达成：284 字符页（今天为 1,411 字符的壳页）有明确结论、日期 fixture 通过、新旧索引升级路径可用（含手工 v1 库的迁移测试）。
- **未解释现象（不掩盖）**：§5.1/§4.2 完成后的一次全量跑里，`test_web_search.test_real_transport_usage_is_per_operation_and_not_mixed_between_providers` 失败——`len(requests)` 11 ≠ 10，而同一回执的 usage 计数仍是 10（一次**未被计数**的传输调用）；此后多次全量与单文件重跑均通过，未能复现，本轮未改搜索路径。§5.2 期间还出现过一次“尝试顺序”失败，但那一次已定位并修复（见下），与本条无关。

### R3（2026-10-18，已完成）

**§2.3 路线 ②（编排式）**

- **插件侧**：新增 `src/discovery.py`。`budget_check(steps, fetches, variants, elapsed_seconds, limits)` 返回 `{continue, reason, used, limits, remaining, note}`（默认 steps ≤ 6、fetches ≤ 8、variants ≤ 3、90 秒，越界参数报错）；`evidence_bundle(sources, max_characters, excerpt_characters)` 只把 `content_state=usable` 的页面列为 `evidence[]`（稳定 `eN` ID、`excerpt`、`characters`、`published_at`），其余按原因进 `unavailable_sources[]`，按摘录(1200) → 文摘(320) → URL 清单逐级降级，绝不返回空。`src/mcp_server.py` 新增 `discovery_bundle` 工具，一次返回预算判定与证据包。
- **宿主接缝**：新增 `hosts/shared/discovery.json` + `discovery-flow.js`；`scripts/host_assets.py` 的 `build_workflow(root, host, name)` 泛化为双工作流，`export_host_assets` 同时导出 claude（`workflows/bookmark-research-discovery.js`）与 pi/dsh（`workflows/bookmark-research-discovery/` 两文件 + 元数据）；`hosts/dsh/workflow-call.py` 新增 `--workflow`（默认仍是分组配方，向后兼容）；`hosts/pi/register-workflow.py` 一次登记两个工作流（返回 `workflows[]`）；`HOST_SOURCE_FILES` 同步；bridge 白名单从“仅 `research_*`”扩为 `research_*` + `plan_research`/`discovery_bundle`/`fetch_web`/`search_web` + 只读本地查询（`index_status`/`search_bookmarks`/`get_context`），`sync_package` 等写操作仍被拒。
- **与路线 ① 并发**：每轮把“读卡片链接（`fetch_web` 一批）”与“首轮一次 `search_web` 种子”放进同一个 `host.all` 批次；种子发现的 URL 下一轮再读；同一 URL 只留一行，可用的重读替换未读占位。
- **计数与停止（诚实口径）**：steps/fetches/variants 由宿主统计并随每次 `discovery_bundle` 调用传入（bundle 自身计一步），插件据 `remaining` 决定停止；宿主另在“剩余预算放不下下一轮”时停止并如实报 `host_stop`（`evidence_satisfied` / `budget` / `queue_empty` / `insufficient_remaining_budget` / `max_steps` / `bundle_error` / `plan_empty` / `plan_blocked`）。**与 §9 决策 1 的差异**：决策原文要“复用 `research_*` 会话作为唯一预算权威”，R3 **未**接入 research 会话——`discovery_bundle` 不创建、不读取研究任务，route ① 及其 `research_fetch` 预算照旧；理由：路线 ② 的验收对象是“一次问答的证据包”，接研究会话会把 `research_finish` 的完成门禁带进来，违背轻量定位。§9 决策 1 已留指针。
- **结果字符串上限**：证据包按 40,000 字符预算（低于 DSH `maxResultChars` 默认 50,000）；`truncated` 只在连 URL 清单都放不下时置位——对应验收里的 `maxResultChars` 上限。
- **测试**：`tests/test_discovery.py` 10 项（预算四类停止、降级三档、截断、非可用来源、工具分派与参数校验）；`tests/host-discovery.test.js` 60 项检查（每宿主 20 项 × 3 宿主：成功、第二轮预算停、证据满足即停、预算不足不起轮、空范围、plan 失败、读失败、bundle 失败、bridge、语言、9 组参数校验、args 类型），由 `tests/test_host_workflows.py` 驱动；dsh `--workflow` 与 pi 双登记用例已扩展。全量 **744 项通过、3 项跳过、130 秒**（R2 为 733；R3 新增 Python 11 项 + Node 60 项检查）。
- **真实包冒烟（2026-10-18，我充当路线 ② 的子代理）**：`index_status(source_id=github-bookmark-canvas)` → `plan_research("EmbeddingGemma 2 怎么本地部署")` 0.2 秒命中 A-1-1（重名两张中的第一张，见 R1）、`task_shape=lookup`、`route=direct_retrieval`，URL 前两位仍是 R1 的两条；`fetch_web` 6 条 46 秒：unsloth 12,000 字可用、CSDN 12,000 字（`published_at=2026-10-03`）、linux.do 12,000 字（`2025-06-23`），foresight 页**今天只有 284 字符**（回到 §0.4 #2 的原始数字，判 `content_insufficient`；R2 当日是 1,411 字符 `js_shell_suspected`——同一壳页两次测量不同，按天变），apxml 判 `js_shell_suspected`、另一 linux.do 页 unavailable；一次 `search_web` 6.5 秒（响应键为 `batches`；一次性脚本只做防御性打印，未取行）；`discovery_bundle(steps=4, fetches=6, variants=1)`：**证据 3 条（e1/e2/e3，均带 URL）、degradation=excerpts、gaps 空、预算剩 steps 2**——“≥3 条带 URL 证据”在**第一读轮**达成，整链路一次跑通。
- **文档同步**：`README.md` / `README.zh.md`（工具数 42 → **44**，研究行加 `discovery_bundle`）、`docs/details.en.md` 工具表、`SKILL.md` 与 `references/zh/skill-guide.md` 流程行、`references/host-workflows.md` 与 `zh/`（新增“单问题发现”小节，Claude/Pi/DSH 入口与桥接白名单同步）。
- **过程中自纠（记录在案）**：① `export_host_assets` 泛化后 claude 分支跌进 pi/dsh 的边文件查找（`KeyError: 'claude'`），由 `test_export_bundle` 暴露后加宿主守卫；② 发现流程的 status 原把“1–2 条证据”判 ok，改为 `≥3 且无错误` 才 ok、1–2 条记 `partial`；③ Node 契约测试里对 vm 内数组要用展开再断言（跨 realm `deepEqual` 按原型比较）；④ 一次全量跑里桥接用例失败，原因是**改消息串时套件已在运行**（子进程读到新文件、断言用旧字符串），重跑即过，非代码缺陷。

### R3 收口（2026-10-19，评审后）

外部评审拿真实包副本复现了四个口子，逐条修掉，均有单测与实测锁定；全量 **749 项通过、3 项跳过、145 秒**。

- **排序密度**：`score` 改为“词权和 × 密度（hits ÷ bookmarks）”。修前 `RAG 企业落地` 是 A / A-10（均 3.633）压过 82/107 的 A-1-1（0.633）；修后两张 A-1-1（0.602 / 0.485）居前，1,053 条的永久树退出前三；`EmbeddingGemma 2 怎么本地部署` 第一仍为 A-1-1。新 fixture 以“2/32 密度的大卡 vs 9/9 的主题卡”锁定该翻转。
- **问题里的 URL**：`plan_terms` 先剔除 URL（修前 terms 里出现 `https`、`a.test`）；出参新增 `question_urls[]`，路线 ① 直接读它们。
- **点名规则**：文档／仓库书签只有在该 URL 行被“只指向一棵卡树”的词命中（`term_cards` 为判据）时才判 `lookup`。修前 `RAG 企业落地` 因一个 github／docs 命中被判 lookup/quick，现正确为 investigation/agentic。
- **两条契约**：0 卡且无自带 URL 时短路 `route: null`（修前 host_iterative_research）；`depth` 传 `None` 读已存 `research.depth`（修前写死 `auto`，`deep` 设置被忽略），并补 `config set --depth` 与用例。
- **`.codex/config.toml`**：`enabled_tools` 6 → 8，补 `plan_research`、`discovery_bundle`，否则本仓库自己用 Codex 时新工具不可见。
- **拆分提交**：R1–R3 与收口改动按 `feat(plan)` / `feat(evidence)` / `feat(discovery)` / `chore(codex)` 四个提交叠加在既有历史上（“1”提交保留，不改写历史）。中间的 `feat(plan)` 提交点上 `plan_scope` 已引用 `added_at` 列（列随 `feat(evidence)` 引入）：中间点是回滚粒度，不保证逐点全绿。

### R4（2026-10-19，已完成）

**§2.4 路线 ③（研究内缺口补查）与 §3 Wiki 一次成页**

- **先核后建**：§3 的机器侧（`wiki_follow_up` 的 suggest/auto/off、`wiki_work` 的 eligible/pending 记账、`wiki_write` 的 `research_id`+`claim_id` 与 `expected_revision`）在 R1–R3 时就位且有测试，本轮未重复实现；真实缺口只有三处：非 completed 交付没有缺口固定形状、`eligible_claims` 没有一次成页所需的草案材料、报告没有缺口小节。
- **`insufficiency` 固定形状**（`src/research.py`）：`finish` 在 `status != "completed"` 时返回 `{state, questions[{id,status,gap}], unresolved_conflicts, pending_operations, coverage_blockers}`；`report.md` 在 “## Research questions” 前新增 “## Insufficient evidence”。completed 交付不受影响（`tests/test_research.py` 断言该键不出现）。
- **`eligible_claims` 草案材料**：每条为 claim 的逐字首句引文（≤240 字，正则 `[.!?。！？](?:\s|$)` 截取）+ `inference` 标记 + 所属 question；suggest 保持“仅在用户确认后成页”、auto 保持“不问用户”的措辞。
- **补查手册与工具描述**：`deep-research.md`（+zh）新增“缺口补查”小节与显式预算段（≤6 个子问题、约 24 次抓取、不动 `DEFAULT_BUDGET`）；`wiki-and-evaluation.md`、`settings-and-archive.md`（+zh）补 `eligible_claims` 说明；`src/mcp_server.py` 同步 `plan_research`（密度排序、点名规则、`question_urls`、depth 读设置）与 `research_finish`（insufficiency、wiki_follow_up）的描述。
- **测试**：`tests/test_output_location.py` 扩 follow-up 断言、新增 `test_incomplete_finish_returns_the_fixed_gap_list`（缺口记录 → insufficiency 形状 + 报告小节 + cancelled 同样携带该块）；全量 **750 项通过、3 项跳过、128 秒**。
- **真实包验收（会话 `r-1c591120f3124b5d`，真实抓取）**：`plan_research("RAG 企业落地要点")` → investigation/agentic；`research_fetch` 读 5 条 URL（混合状态，3 条正文入存）；批次记 3 条 claim + q3 缺口；随后发现其中一条 claim 的引文取自 **SSO 登录壳页**，遂 `retraction` 撤回、补 q2 缺口、q1 改用余下两条作答；`finish(incomplete)` → `insufficiency`（q1 answered；q2/q3 unresolved 且各带 gap；3 条覆盖阻断项；`wiki_policy=suggest`；`eligible_claims=[c1,c3]`，**撤回的 c2 被正确排除**）→ 报告含 “## Insufficient evidence”。再 `resume` → 读 s10 正文 → 补 `source_review` + claim c4 → 答 q2 → 二次 `finish(incomplete)` → `eligible_claims=[c1,c3,c4]`。
- **Wiki 一次成页（写在临时 wiki）**：`wiki_write` 以 c1/c3/c4 成页 `rag-enterprise-landing`（revision 1）→ `wiki_search("RAG 企业落地")` 命中 → `wiki_work(research_id)` 报 `compiled`、`eligible_claim_count=3`。**用的是 `/tmp/br-r4-acceptance/` 下的临时配置与 wiki 目录，用户真实 wiki 未被写入。**
- **过程中自纠（记录在案）**：① 首轮三条证据里有一条引用登录壳页，是我选源不严，靠本轮新增的 retraction 路径纠正——也顺带证明 `eligible_claims` 会排除已撤回的 claim；② c4 的首句引文实为阿里云页面的导航行（抽取文本开头即导航），仍是逐字子串、通过校验，验收足够但值得记；③ bridge 白名单**不含** wiki 工具，这是设计（成页由宿主直连 MCP 完成），验收脚本因此改用进程内 MCP 直调 wiki 工具，等价于宿主路径；④ 验收期间的一次全量跑报了 1 个失败，但后台任务只保留尾部输出、未能定位到用例；该次与验收脚本（并发开子进程）时间重叠，独立重跑未见复现；⑤ 未 bump 版本号（留到发版前统一处理）。

### R4 补齐（2026-10-19，评审后）

评审确认 R4 的“自动缺口”与“批量确认”只做了一半，本轮补齐三处：

- **`login_required` 内容状态**（`src/archive.py`）：SSO/登录墙（`sign in to continue`、`login required`、`请登录`、`统一身份认证` 等）在正文权重 < 400 且标记出现在页头 300 字符内时判 `login_required`；它既不是 `paywall_suspected` 也不是 `js_shell_suspected`，不进可引用证据。这是 R4 验收里“引文取自 SSO 壳页”的直接修复，`tests/test_evidence_state.py` 增加英文/中文/长文反例三条。
- **自动缺口派生**（`src/research.py`）：`_question_gap` 在问题没有 `gap` 记录时按状态派生——无 claim → “No accepted claim answers this question”；claim 被撤回 → 要求修订；有 claim 无答案 → “Claims exist but no answer was recorded”。`insufficiency.questions[]` 新增 `gap_source`（`recorded` / `derived`），报告 “## Insufficient evidence” 与问题小节同样使用派生文本。**插件仍不抓取**：`next_action.tools` 明确指向 `research_fetch` → `research_record` → `research_finish`，抓取由宿主执行（与“插件不联网”边界一致）。
- **一次成页的页面骨架**（`src/research.py`）：`wiki_follow_up.draft` 给出 `{page:{title,kind,sections,links}, claim_count, section_count, truncated, instruction}`；`sections` 按 question 分组，`text` 只拼 claim 原文（不生成新论断），每条 claim 带 `{research_id, claim_id}`，按 `wiki_write` 的 12 claim/节、16 节上限自动切分。用户确认一次、宿主 `wiki_write` 一次即可成页，满足“16 条 claim ≤ 2 次动作”的路径；`review` 块留给宿主填写真实审阅人，不代填。
- **测试**：`test_evidence_state` +1（登录墙）、`test_output_location` +4（派生缺口、claims-without-answer、分节上限、导入时间/字符）并扩展 draft 断言；全量 **755 项通过、3 项跳过**（见提交说明）。
- **仍未做**：跨源冲突裁决、`login_required` 的自动补抓（换源/换读者由宿主决定）、真实宿主会话里的端到端验收（本轮只到源码级 E2E，见下）。

### 真实源码端到端（2026-10-19，临时目录）

在 `tempfile` 下复制真实索引库、临时 archive/wiki/output，用**工作树源码**跑完整链路，用户数据目录未写入：

- `plan_research("EmbeddingGemma 2 本地部署")` → A-1-1（score 2.0075）、`lookup/direct_retrieval/quick`；URL 前二为 foresight 与 unsloth。
- `fetch_web` 两条：`developers.google.com/edge/foresight` → `js_shell_suspected`（1,411 字符）、`published_at=null`；`unsloth.ai/...` → `usable`（3,994 字符）。`discovery_bundle(steps=1, fetches=2)` → `evidence=1`、`unavailable=1`、`degradation=excerpts`。
- 研究会话：import 一页 → accept → 一条 claim → `finish(incomplete)`；`wiki_follow_up.draft` 生成 1 claim / 1 section；`wiki_write` 到临时 wiki 后 `wiki_search("EmbeddingGemma")` 命中 `embeddinggemma-e2e`。S1/S3 路径成立。
- `plan_research("zzzqqqvvv")` → `route=null`、`depth=null`，S2 成立。
- **E2E 抓到的真实缺陷**：首次 `finish` 时，q1 明明已有一条 claim，`insufficiency` 却报 “No accepted claim answers this question”。原因是 `_question_gap` 只看 `question["claim_ids"]`，而该列表只有在记录 `answer` 时才填充；claim 虽带 `question_id`，没有被计入。修法：取 `claim["id"] in question["claim_ids"] or claim["question_id"] == question["id"]`。修复后同一路径报 “Claims exist but no answer was recorded”，并补 `test_a_claim_without_an_answer_is_not_reported_as_no_claim`。这也是本轮唯一由 E2E（而非单测）发现的缺陷。

### 首个真实宿主 Wiki 页（2026-10-19，评审后）

真实宿主会话产出 `embeddinggemma-2-local-deployment`（rev1，research `r-79dbcae30d204f88`）：3 节 / c1–c3，单一来源 s1（unsloth，已 accepted），s2（foresight）rejected；q1 answered，q2「仅定位、不联网」unresolved，会话状态 `incomplete`。

- **内容核验**：7.4 亿参数、2.7/1.7/3 亿拆分、Apache 2.0、100+ 语言、8K 上下文、176 MB GGUF、FP16 警告、L2 归一化均在已存 `body.txt` 中逐条存在；引文逐字命中；边界说明正确排除了 foresight 的 284 字符壳页。页面可取。
- **缺陷 1：`Retrieved None` + `source_capture_time_unknown`**。`import_evidence` 只读 `provenance.retrieved_at`，而宿主写的是 `provenance.fetched_at`。修复：导入时取 `retrieved_at or fetched_at`，并新增 `characters = len(text)`；渲染缺时间时显示 `unknown` 而不是 `None`。
- **缺陷 2：修复后旧页被判 `invalid_evidence`**。新代码在构造 citation 时把 `retrieved_at` 从 null 归一为 fetch 时间，而 revision 里存的是 null，`substantive()` 直接比较导致误判。修复：比较前对两侧都做同样的时间归一化。真实页现在 `status=current`、`integrity=valid`、`lint ok`（issues 为空）。
- **遗留观察（未改）**：宿主 review 文字写“首 12000/13290 字符”，但归档 `body.txt` 只有 6,800 字符；`characters` 现在会记录真实长度，但页面仍可能引用宿主自述的、未归档的数字。建议后续要么在页面显示归档字符数，要么禁止在 review 中写不可核对的长度。
- **测试**：新增 `test_imported_evidence_keeps_the_fetch_time_and_text_size`；全量 **755 项通过、3 项跳过**。
