# 插件成熟度与标准对照（2026-10-21）

> 对象：Bookmark Research 当前工作树（三宿主：Codex / Claude Code / DSH）。
>
> 结论先行：**本地代码和单元测试成熟度较高；真实宿主、真实 API、负载/故障压测仍是缺口。**
>
> 它不是“比宿主内置搜索更快的搜索器”，而是“书签包覆盖 + 可复核证据链”的慢而重的插件。

## 1. 网络测试到底做到哪一步

| 类型 | 做了吗 | 事实 |
|---|---|---|
| 真实网络功能测试 | ✅ | `search_web` 2/2 provider 成功；`fetch_web` 8/8 URL 归档；真实包 URL |
| 真实网络时延测试 | ✅ | 暖会话 20 URL 约 1.86s；6 页单 provider 7–17s；Exa+Parallel 分片约 1.68s |
| 本地规模压测 | ✅ | 1k–100k 书签，100k p50 388–507ms |
| **负载/并发压测** | ❌ | 没有持续 QPS、并发用户、队列打满 |
| **故障注入压测** | ❌ | 没有批量 429/5xx/timeout/challenge/断线/重试恢复 |
| **长时间稳定性** | ❌ | 没有小时级运行、内存泄漏、会话退化 |
| **多 provider 配额/成本压测** | ❌ | 没有耗尽配额、冷却、fallback 级联的真实数据 |
| **OpenAI Deep Research 真实压测** | ❌ | 没有 key，未跑真实任务 |

所以准确说：**真实网络“功能/时延”测了；网络“压测（load/fault）”没做。** 把两者混为一谈是不严谨的。

## 2. 对用户的明显优点

1. **书签包不是普通网页搜索**：能读 Canvas 的栏目、卡片、副本、时间、缺文件；内置搜索做不到。
2. **证据可复核**：`capture_id`、SHA-256、`content_state`、`published_at`、`quote_verified`；答案可以回链到不可变归档。
3. **覆盖意识**：inventory/coverage/gap/conflict，不把“搜到几条”冒充“读完整个包”。
4. **本地优先**：本地查询不联网；原始包只读，不回写；私有笔记不进入公开查询。
5. **预算和降级**：fetch 有每页/总预算、fair share；证据包会从 excerpt 降级到 digest/URL 列表，而不是空手而归。
6. **跨三宿主**：同一套 Python/MCP 工具，Codex、Claude Code、DSH 都能接；不绑定某一家模型。
7. **可配置模型**：OpenAI 默认 `gpt-5.6-sol`，允许自填 model ID，未知模型显式放行。
8. **测试量**：768 个 Python 测试通过；真实包/压测有独立报告。

## 3. 对用户的明显缺点

1. **慢**：不是 2–3 秒出答案的搜索器。首次 MCP 握手约 5s；6–8 页全文抓取 7–17s（单 provider）。
2. **重**：需要 Python 3.9+、SQLite FTS5、MCP 进程、外部 provider key/配额；安装和排障比内置搜索复杂。
3. **工具面大**：默认 44 个工具，模型上下文和选择成本高；虽然可收窄，但默认不是“轻量”。
4. **依赖宿主自觉**：Skill 只能引导，不能强制模型先 `plan_research`、只读证据、按预算停；不同宿主行为会漂移。
5. **没有流式/进度**：MCP 调用是最终 JSON；长任务看起来像卡住，只有取消，没有 progress。
6. **没有浏览器/爬虫**：JavaScript 壳、Cloudflare、登录墙只标记不可用，不绕过；和商业搜索产品的“什么都能读”不同。
7. **外部 API 仍未验收**：`gpt-5.6-sol` Deep Research 只有 mock；真实请求形状/费用/超时未验证。
8. **当前安装仍旧**：DSH beta.15、Claude beta.13；源码改动没生效。
9. **历史文档仍有 Pi**：已标历史，但对外搜索时可能造成混淆。
10. **版本/发布未闭环**：`package.json` 还是 beta.15，release notes 已是 beta.16。

## 4. 与宿主内置搜索相比

| 维度 | 宿主内置搜索（Claude WebSearch/WebFetch、Codex web_search、DSH 自带） | 本插件 |
|---|---|---|
| 安装 | 零安装/宿主自带 | Python + MCP + 三宿主导出/安装 |
| 速度 | 宿主托管、通常更快、可流式 | 受外部 provider + 全文抓取影响，慢 |
| 网页覆盖 | 广、由宿主维护 | 依赖 Exa/Parallel/Tavily/Jina |
| 书签包语义 | 基本没有 | 强：栏目/卡片/副本/时间/缺文件 |
| 证据归档 | 通常没有 | `capture_id` + SHA + 内容状态 |
| 引用严谨性 | 取决于宿主 | 强制 evidence ID / 不可用来源 |
| 覆盖/缺口 | 弱 | inventory/coverage/gap/conflict |
| 隐私 | 宿主策略 | 本地索引；外部查询仍会发 URL/问题 |
| 可移植性 | 绑定宿主 | 三宿主共享同一套工具 |

**用户该怎么选：**

- 普通网页问题、要快：用宿主内置搜索。
- 书签包、要覆盖/引用/可复核：用本插件。
- 两者混用：内置搜索发现，插件 `fetch_web` 归档；或插件 `search_web` 发现，宿主综合。

## 5. 与 MCP / 插件标准的差距

依据：[MCP Tools 规范](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)、[MCP stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)。

| 标准项 | 本插件 | 评价 |
|---|---|---|
| MCP initialize / tools/list / tools/call | ✅ | 核心可用 |
| stdio transport | ✅ | 只支持 stdio，无 Streamable HTTP |
| 工具 `inputSchema` | ✅ | 完整 |
| 工具 `title` / `icons` | ❌ | 缺少展示元数据 |
| 工具 `outputSchema` | ❌ | 返回 `structuredContent` 但未声明输出 schema |
| 工具 `annotations`（readOnly/destructive/openWorld） | ❌ | 客户端无法按标准判断读写/外网/破坏性 |
| `tools/list` 分页/缓存 | 部分 | 有 cursor 参数但无分页；44 个工具未超限 |
| 进度通知 | ❌ | 长 fetch 无 progress |
| 取消 | ✅ | 支持 `notifications/cancelled` |
| Resources / Prompts / Sampling | ❌ | 只做 tools；这是有意的精简，但非全功能 MCP |
| 状态句柄 | ✅ 自定义 | `capture_id`/`research_id` 是普通字符串句柄，符合 MCP 状态建议 |
| 速率限制 | 部分 | 服务端队列/并发 + provider 冷却；无每工具限流 |
| 输入校验 | ✅ | 每个工具 schema + 边界 |
| 输出清洗 | 部分 | 外部文本不执行指令，但仍可能含提示注入；靠宿主 |
| 人类确认/成本提示 | 部分 | 预算是插件侧；宿主是否弹确认取决于宿主 |
| 单一标准包 | 部分 | Codex/Claude/DSH 各自 manifest；没有统一包 |

**最明显的“不标准”：**

1. 没有 `title`/`outputSchema`/`annotations`，工具在标准客户端里像“裸 JSON 函数”。
2. 没有 progress；长任务体验不符合现代 MCP 客户端预期。
3. 只做 tools，没有 resources/prompts；这是产品选择，但限制了“标准 MCP 完整度”。
4. 三宿主打包不统一：Codex 原生插件、Claude marketplace、DSH Cordis bundle；这是宿主生态现实，但对用户是学习成本。
5. 默认 44 工具 + 超长 description，和“标准工具应短小可发现”的实践有冲突。

## 6. 三宿主差异

| 宿主 | 优势 | 风险/不标准 |
|---|---|---|
| Codex | 原生 plugin/marketplace；`web_search` 内置；subagent | 项目 `.codex/config.toml` 的 `enabled_tools` 是宿主扩展；当前旧插件 |
| Claude Code | 原生 marketplace/plugin；WebSearch/WebFetch；Dynamic Workflow | 插件权限/工具搜索行为由宿主决定；project/local scope 路径未真实验证 |
| DSH | 官方 MCP client + Cordis bundle；自带搜索 | 自定义 bundle 层最深；同版本重装可能 no-op；工具可见性依赖 profile |

## 7. 成熟度判断

| 维度 | 评分 | 理由 |
|---|---|---|
| 本地正确性 | 较高 | 768 测试、真实包回归、边界覆盖 |
| 证据严谨性 | 高 | capture/SHA/不可用来源/覆盖 |
| 网络性能 | 中低 | 单 provider 全文抓取慢；分片未实现 |
| 可靠性/压测 | 低 | 无负载/故障/长稳 |
| 宿主集成 | 中 | 代码支持三宿主，但真实安装仍旧 |
| 外部 API | 低 | 模型已迁，真实未验收 |
| 标准 MCP 完整度 | 中 | 核心 tools 合规，metadata/progress/resources 缺失 |
| 发布成熟度 | 低 | 版本未 bump、未发布、安装未更新 |

**结论：这是一个“证据链很强、工程测试不错、但网络性能和真实集成还没验收完”的 beta 插件。** 不能对用户说“生产就绪”；可以说“本地书签研究可用，网络/宿主/成本仍需实测”。

## 8. 建议的下一步压测

不做对公共 provider 的高并发压测；做可控的：

1. **离线故障注入**：mock 429/5xx/timeout/challenge/断线，重复 100–1000 次；测 fallback、冷却、取消、恢复。
2. **插件边界并发**：4 workers / 16 pending，测队列、顺序、超时、内存。
3. **真实低量**：每 provider 1 次 search + 1 次 fetch；只做契约，不做吞吐。
4. **6 页分片**：Exa+Parallel 并发，目标 2–4s；验证 archive/证据合并。
5. **OpenAI 单任务**：有 key 后跑 1 个 `gpt-5.6-sol` 小任务，验证 background/status/result/import。
6. **三宿主重装**：DSH/Claude/Codex 各 1 次真实安装 + 工具列表 + 1 个书签问题。
