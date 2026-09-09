# 0.2.0 聚合 MCP：实现依据与验证范围

核验日期：2026-09-10（Asia/Shanghai）。官方资料通过 Exa 搜索、读取；工具名和参数另外通过各服务真实 `initialize` / `tools/list` 核验。版本演进会改变目录，运行时以实际目录和 schema 检查为准。

## 实际接入

| 服务 | 本插件接入方式 | 实际搜索 / 提取工具 | 执行边界 |
| --- | --- | --- | --- |
| Exa | HTTPS Streamable HTTP；可选 `EXA_API_KEY` → `x-api-key` | `web_search_exa` / `web_fetch_exa` | 匿名访问有服务端限流；支持 `maxCharacters` |
| Parallel | HTTPS Streamable HTTP；可选 `PARALLEL_API_KEY` → Bearer | `web_search` / `web_fetch` | `/mcp` 可匿名；默认提取为 `excerpts`，schema 没有字符上限参数 |
| Tavily | HTTPS Streamable HTTP；可选 `TAVILY_API_KEY` → Bearer；未设置时发送 `X-Tavily-Access-Mode: keyless` | 实测为 `tavily_search` / `tavily_extract`，兼容官方文字说明使用的连字符名 | keyless 只覆盖搜索与提取；schema 没有字符上限参数 |

默认搜索源仍为 Exa 和 Parallel，Tavily 可按调用或保存的设置选择。API Key 仅从进程环境读取并放在请求头中；不拼到 URL，不保存到插件配置、研究记录或错误日志。本插件没有 OAuth 流程；需要 OAuth 的原生 MCP 由宿主管理。

依据：[Exa MCP](https://exa.ai/docs/reference/exa-mcp)、[Parallel Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp)、[Tavily MCP](https://docs.tavily.com/documentation/mcp)、[Tavily keyless](https://docs.tavily.com/documentation/keyless)。Tavily keyless 文档明确要求该 header，并说明 `/research`、`/crawl`、`/map` 需要 API Key。

## 聚合运行方式

`SearchProviders.search/fetch/describe/probe` 的调用方式保持兼容。不同服务并行，同一服务的握手、目录访问和工具调用串行，复用同一个 client/session。每个 `SearchProviders` 实例还生成稳定的 Parallel `session_id`；不猜测或伪造 `model_name`。CLI 新进程会建立新的客户端会话。

每个服务最多缓存一份目录，缓存有效期 300 秒、大小上限 1 MB、工具数量上限 256；API Key、端点或 timeout 改变会替换 client 并使缓存失效。接收到 `notifications/tools/list_changed`、session 失效或 schema/RPC 参数错误时也会失效。`probe` 强制重新读取目录；探测成功不清除已观察到的工具限流。

HTTP client 支持 JSON/SSE、协议协商、服务器 ping，以及最多 8 页的 `tools/list`；游标重复、工具名重复、目录过大均明确失败。分页中的 session 404 只允许重新握手一次，丢弃此前的目录页，避免混用两个 session 的目录。依据：[MCP Streamable HTTP / Session Management](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[MCP Tools / Pagination / List Changed](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。

每家 adapter 仅映射已知搜索与提取参数，并检查当前 schema 中的必填字段、类型、枚举、数组元素与数量、字符串和数字范围。支持当前实际参数使用的 JSON Schema 子集；遇到引用、未支持的约束或未知必填字段时不猜默认值、不调用收费工具。仅有 `url` 的提取 schema 遇到多个 URL 会明确拒绝，不暗中拆成额外调用。

`describe` 无网络访问，返回配置元数据；`probe` 只核验连接与工具目录，分别返回 search/fetch 的兼容性。两者均不把“配置了 Key”或“目录中有工具”当作执行授权验证。探测中的 `execution_verified: false` 指本次探测没有执行该工具。

## 部分失败与预算

搜索保留每个 provider / target / query 的独立 batch，再按已有 RRF 规则融合；一个服务的失败不丢弃其他结果。相同 provider、target、query 去重后只调用一次。

每个搜索 batch 或一次 fetch 最多发起 **1 次 `tools/call`**。404、429、5xx、超时、响应丢失和本地归档失败均不自动重放工具调用。带有效 session 的 404 清除会话，下次显式动作重新初始化；只有目录请求允许一次 session 恢复。429 按 `Retry-After` 暂停该服务后续动作；无该头时默认 5 秒，上限 24 小时；跳过的 batch 明确标记 `skipped_due_to_cooldown`，不执行隐藏重试。

search 总结果、各 batch 和 fetch 都提供：

```json
{
  "usage": {
    "tool_calls": 1,
    "http_requests": 4,
    "initialize_requests": 1,
    "list_requests": 1,
    "session_recoveries": 0,
    "cache_hits": 0
  }
}
```

`tool_calls` 是发起的语义调用尝试，失败也计入；HTTP 计数另含握手、通知与目录。不是金额或供应商结算凭据。研究层可在请求前按 provider/query 数量预留调用预算；响应失败不表示供应商没有执行或计费。

错误分类包括 `authentication_required`、`quota_exhausted`、`rate_limited`、`session_expired`、`transient_http`、`timeout`、`connection_error`、`schema_mismatch`、`capability_unavailable`、`tool_error` 和 `result_format`。`retryable` 是供下一步决策使用的信息，不会触发自动执行。上游错误正文、URL 和凭据不进入错误信息。

fetch 保留实际 `result`，同时提供 `per_url`、`successful_url_count`、`character_limit_applied`。提取部分成功为 `partial`；未能关联到请求 URL 的正文为 `unverified`。`complete_page_verified` 恒为 false，服务返回正文或片段不证明完整页面已抓取。

传输、握手、schema 或工具级失败返回 `status: error` 与 usage，**不含 `result`**；此时不能调用 `SourceArchive.save`，研究层应先落失败 receipt。有效响应中所有 URL 都提取失败时仍保留 `result`，可以归档原始响应。输入校验失败继续抛 `ValueError`。

## 第三层研究与供应商原生任务

本插件的研究会话由宿主推理模型决定子问题、搜索、读取、补查与停止，再由本地研究记录管理预算、操作、证据和引用。聚合层仅提供检索，不宣称自身包含一个研究模型。

供应商的原生研究是额外的可选路径：

- Exa 当前官方工具为 opt-in `agent_run`。它执行服务器端研究循环，返回结果、grounding 与 usage；长任务可返回运行中的 `id`，用 `runId` 继续等待。需要认证；默认搜索目录不包含此工具。不要依赖旧版 `deep_researcher_start/check` 名称。
- [Parallel Task MCP](https://docs.parallel.ai/integrations/mcp/task-mcp) 是独立、需要认证的 `https://task-mcp.parallel.ai/mcp`。官方列出 `createDeepResearch`、`createTaskGroup`、`getStatus`、`getResultMarkdown`；创建是异步动作，应查询已有任务状态，不能把观测超时当成重新创建的理由。Search MCP 的探测没有验证 Task MCP 的权限。
- Tavily keyless 的真实目录仍列出 `tavily_research`，但 keyless 文档明确 `/research` 需要 API Key。此处只报告目录可见性，不调用或声称已验证付费研究。

原生研究 URL、名称和文档保留在 provider 元数据中供宿主选用；聚合 adapter 不转发任意工具、付费研究创建或 OAuth 请求。

## 可重复验证与当前证据

[provider schema fixture](../tests/fixtures/provider-schemas-0.2.0.json) 来自三家真实 `tools/list`，保留输入 schema、annotations、公开工具名和目录指纹，删除描述与标题。离线测试会检查当前 adapter 能使用这份实际 schema，并验证 schema 漂移不会造成猜参数调用。

离线测试：

```bash
python3 -B -m unittest discover -s tests
```

聚合相关测试覆盖多目标部分失败、线程间隔离、会话与目录复用、TTL / 通知失效、分页 / 游标循环 / 超限、session 404、限流 / 凭据保密、真实 HTTP 调用计数、Tavily 搜索与部分提取、未知字段 / 类型漂移和无需网络的元数据。

显式运行 public smoke（进程中清除三家 API Key，不用个人设置，不归档，不调用原生研究）：

```bash
python3 -B tests/live_provider_smoke.py --run-live --output /tmp/bookmark-provider-smoke.json
```

一次 smoke 最多 3 次搜索 + 3 次提取。更新 schema fixture 还需显式传 `--record-schemas PATH`，离线测试不会自行访问网络或更新 fixture。

[此次 smoke 原始摘要](provider-smoke-0.2.0.json)：三家的目录和提取均成功；Parallel/Tavily 搜索成功；Exa 首次搜索发生连接错误，原始 `passed: false` 保留。针对该失败另发起一次 Exa 搜索，成功返回官方页面，记录在 `follow_up_checks`。因此每家都有实际搜索与提取成功证据，但这次六调用集合并非全绿，不能由单次访问推断持续可用性。

验证范围不含真实 API Key、有偿额度、OAuth、Exa Agent / Parallel Task / Tavily Research 的执行权限或供应商计费金额。网络故障属于当前记录的一部分；离线故障注入测试负责验证这类失败不会丢失其他结果、掩盖调用次数或触发隐形重试。
