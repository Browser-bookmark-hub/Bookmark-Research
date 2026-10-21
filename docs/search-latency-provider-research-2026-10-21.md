# 搜索时延：官方文档核对与插件实测（2026-10-21）

> 目的：核对 Perplexity / OpenAI / DeepSeek / 豆包（火山引擎）的公开文档，区分“URL 发现”和“全文读取”，再和本插件实测对比。
>
> 数据来源分三类：官方文档（可引用）、第三方性能页（标注）、本插件真实调用（可复现）。

## 1. 官方文档怎么说

### 豆包搜索 / 火山引擎（官方）

[豆包搜索产品简介](https://docs.volcengine.com/docs/Networkedsearch/Onlinesearchproductintroduction?lang=zh) 明确给出：

| 版本 | 搜索时延 | 返回数量 | 内容 |
|---|---:|---:|---|
| 豆包搜索 Global 版 | **平均 1,053 ms** | 20 以内 | 标题、摘要、发布时间、原文插图、权威度、站点信息 |
| 豆包搜索 Custom 版 | **平均 700 ms** | **50 以内** | 标题、摘要、**网页正文（txt/markdown）**、发布时间、权威度、rerank、站点信息 |

这不是“只返回 URL”：Custom 版在搜索响应里就带网页正文。也就是说，**50 个结果 + 正文，官方标称平均 700ms**，和用户说的“几十个 URL 两三秒”是同一量级，甚至更快。

### DeepSeek（官方）

[DeepSeek Search & Fetch API](https://api-docs.deepseek.com/guides/search/)：

- Search：`POST /v1/tools/search`，`count` 1–50，**`need_content=true` 可直接返回页面正文**；
- Fetch：`POST /v1/tools/fetch`，单页返回 Markdown；
- 限流：Search 100 QPS，Fetch 25 QPS；
- 官方没有给搜索时延数字，但它是“搜索 + 可选正文”的单次 JSON API，不是先搜 URL 再逐页抓。

### OpenAI（官方）

[Web search 指南](https://developers.openai.com/api/docs/guides/agents-api/tools/web-search.md)：

- `web_search` 是 Agent 工具，模式 `live` / `cached` / `disabled`；
- `context_size` 可取 `low` / `medium` / `high`，控制“模型从搜索收到多少信息”，默认 `medium`；
- 文档没有承诺“几十个 URL 2–3 秒”；它描述的是模型在 agent 循环里搜索并生成带引用答案。

[Introducing deep research](https://openai.com/index/introducing-deep-research/) 明确写：

> “Deep research may take anywhere from **5 to 30 minutes** to complete its work.”

所以 Deep Research 和“2–3 秒出几十个 URL”不是同一个东西。

### Perplexity（官方 + 第三方）

[Perplexity 官方文档](https://docs.perplexity.ai/docs/sonar/features) 说明：

- 搜索模型返回 `citations` 和 `search_results`（含 `url`、`snippet`、日期等）；
- 搜索结果在**流式响应的最后一个 chunk** 才交付，不是边搜边推；
- Sonar Chat Completions 已于 **2026-09-27** 结束支持，官方推荐 Agent API；
- 官方没有给统一时延数字。

第三方性能页（非官方）：

- [Vercel AI Gateway: Sonar](https://vercel-docs.vercel.sh/ai-gateway/models/sonar/latency) 标称延迟 **2.7 s**；
- [OpenRouter: Sonar Pro Search](https://openrouter.ai/perplexity/sonar-pro-search/performance) 显示平均延迟 **5.39 s**、端到端 **15.03 s**。

这两个数字说明：Perplexity 也不是所有模式都 2–3 秒；Pro Search / agentic 模式明显更慢。

## 2. 本插件实测（真实 provider）

同一环境、真实公共 provider、真实样本包 URL：

| 操作 | 冷启动 | 复用会话 |
|---|---:|---:|
| `search_web` 1 provider，20 个 URL | 5.08 s | **1.86 s** |
| `search_web` 2 providers，10 个 URL | 4.69 s | **1.82 s** |
| `fetch_web` 6 URL，单 provider（Exa） | 7.4 s | — |
| `fetch_web` 6 URL，单 provider（Parallel） | 6.9 s error → 17.2 s ok | — |
| `fetch_web` 6 URL，Exa+Parallel 并发分片 | 4.9 s | **1.68 s** |

本插件 `search_web` 的 URL 发现暖会话是 **1.8 秒/20 个 URL**，与 Perplexity 的 2.7 秒接近，但**慢于豆包官方 700ms/50 个结果**。

本插件 `fetch_web` 是“逐页全文读取 + 归档 + 内容状态 + 日期 + SHA”，6 页 7–17 秒；并发分片后暖会话 1.68 秒/6 页。它不是“搜索 API 直接带正文”的架构。

## 3. 差距在哪里

| 系统 | URL 发现 | 正文 | 典型时延 |
|---|---|---|---|
| 豆包搜索 Custom | 搜索 API 直接返回 50 条 | 搜索响应带正文 | 官方平均 700ms |
| DeepSeek Search | 搜索 API 返回 50 条 | `need_content=true` 带正文 | 官方未标；单次 JSON |
| Perplexity Sonar | 返回 citations/search_results | 片段/摘要 | 2.7s（Vercel）/5.39s（OpenRouter） |
| OpenAI web_search | Agent 工具返回结果 | 模型收到 context，不直接给你全文 | 未承诺 |
| OpenAI Deep Research | 多步浏览 | 报告 | 5–30 分钟 |
| 本插件 search_web | 返回 URL + 片段 | 无正文 | 1.8s 暖会话/20 URL |
| 本插件 fetch_web | 无发现 | 全文归档 | 6 页 7–17s 单 provider；分片 1.68s 暖 |

**结论：用户看到的“50 个 URL 700ms”是豆包搜索 Custom 这种“搜索即带正文”的 API；本插件是“搜索出 URL，再 fetch 全文”，两段加起来自然更慢。** 这不是说本插件不能快，而是架构不同。

## 4. 真正能追平的方向

1. **接入“搜索即带正文”的 provider**：DeepSeek Search `need_content=true`、豆包搜索 Custom。这样一次请求就能拿到 50 条结果 + 正文，不需要 `search_web` + 50 次 `fetch_web`。
2. **`fetch_web` 分片并发**：已实测 6 页从 7–17 秒降到 1.68 秒（暖会话），但需要改 archive/证据合并契约。
3. **预热 provider 会话**：冷启动 5 秒主要是 `initialize` + `tools/list`，暖会话 1.8 秒；可在首次使用前预热，或复用长期 MCP 进程。
4. **只抓 top N**：搜索返回 50 条 URL，但只为答案抓 2–5 页；不要 50 页全文都落上下文。
5. **不要把 Deep Research 当 2–3 秒搜索**：OpenAI 官方写 5–30 分钟；DeepSeek/豆包搜索是搜索，不是深度研究。

## 5. 事实边界

- 豆包/DeepSeek 的数字来自官方文档；本插件没有接入这两家搜索 API，所以不能直接使用它们的 700ms/1,053ms 指标。
- Vercel/OpenRouter 的 Perplexity 数字是第三方测量，不是 Perplexity 官方 SLA。
- 本插件实测使用 Exa/Parallel 公共 MCP；冷/暖差异、provider 负载和网络位置都会影响结果。
- 本次没有 API key，无法实测 DeepSeek/豆包 API；只核对了官方文档。
- 没有对公共 provider 做高并发压测；那会撞 429/配额，不能代表用户单次查询体验。

## 6. 可引用来源

- 火山引擎豆包搜索：[产品简介](https://docs.volcengine.com/docs/Networkedsearch/Onlinesearchproductintroduction?lang=zh)、[联网搜索工具](https://ark.volcengine.com/region:cn-beijing/docs/web-search)
- DeepSeek：[Search & Fetch API](https://api-docs.deepseek.com/guides/search/)
- OpenAI：[Web search 指南](https://developers.openai.com/api/docs/guides/agents-api/tools/web-search.md)、[Deep Research 发布说明](https://openai.com/index/introducing-deep-research/)
- Perplexity：[Sonar / Agent API 文档](https://docs.perplexity.ai/docs/sonar/features)
- 第三方性能：[Vercel Sonar 延迟](https://vercel-docs.vercel.sh/ai-gateway/models/sonar/latency)、[OpenRouter Sonar Pro Search](https://openrouter.ai/perplexity/sonar-pro-search/performance)
