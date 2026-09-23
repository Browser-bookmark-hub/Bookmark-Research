# 配置与来源归档

[English](../settings-and-archive.md) · **中文阅读版**

用户可直接在对话中改配置，CLI 与 MCP 使用同一套实现。当前没有独立图形设置页。

provider 可选 `exa`、`parallel`、`tavily`、`jina`。搜索第一轮由 `search.providers` 指定（Exa + Parallel），无结果查询交给 `search.fallback_providers`（Tavily + 有 key 的 Jina）；设为空数组可关闭回退。读取先用 `fetch.provider`，再将未成功 URL 交给其余 `fetch.providers` 并发，默认为 Exa → Parallel + Jina。Jina Reader 支持匿名读取，Search 需要 `JINA_API_KEY`。Tavily 使用 `TAVILY_API_KEY` 或 keyless header。密钥优先读取进程环境，其次读取私有凭据文件，公共访问仍受限额影响。

## 终端向导与就绪检查

运行 `python3 <root>/src/cli.py setup --host codex`（或 `claude_code`、`pi`、`dsh`）设置偏好、隐藏输入密钥并检查所选服务。`--lang auto|en|zh` 选择向导语言。`--non-interactive --input FILE` 无提示合并部分偏好，`--input -` 从 stdin 读取 JSON。Agent 通过环境变量提供密钥，不在聊天或偏好 JSON 中传递。`--skip-checks` 不联网；`--test-retrieval` 选择执行可能使用额度的样例搜索／阅读，两者互斥。向导和检查不会创建专业研究任务。

向导将密钥保存为配置旁的 `credentials.json`，或 `BOOKMARK_RESEARCH_CREDENTIALS` 指定的文件；文件为权限 `0600` 的本地明文，仅当前用户可读。运行时会重新读取文件，保存后不必重启插件；更改进程环境变量需重启对应进程。环境变量优先。宿主 OAuth token 留在宿主，插件密钥不会自动授权另外登记的宿主 MCP。

每个联网研究新问题前调用 `research_readiness`，传入实际 `host`、`observed_tools` 及明确限定的 `providers`。CLI 示例：`readiness --host codex --tool mcp__exa__agent_run`。只传实际观察到的工具；省略表示未知，空数组表示未观察到任何工具。本地查询无需检查，同一调查复用结果，不反复强制刷新。直接调用 CLI 时，在网页操作前显式运行 readiness。

| 策略 | 行为 |
| --- | --- |
| `cached`（默认） | 首次、配置／密钥变化或过期后检查，默认 TTL 为 900 秒 |
| `always` | 每个新问题的 readiness 调用均刷新 |
| `manual` | 仅 `refresh:true`／`--refresh` 或明确的实际检索测试联网 |
| `offline:true`／`--offline` | 只读本地配置和仍有效的缓存证据，不联网 |

按验证范围理解结果：

- `missing_credentials`：用 setup 或进程环境配置指明的密钥。
- `catalog_reachable`：MCP 发现成功，实际搜索／读取权限和额度未验证。
- `http_unchecked`：有 HTTP 适配，检查各操作缺失的密钥；Jina Search 必须有 key。
- `retrieval_verified`：仅逐操作状态为 `verified` 的操作已验证，其他操作仍可能失败。
- `model_access_verified`：OpenAI 模型元数据可读，尚未测试付费研究任务。
- `task_mcp_access_verified`：Parallel Task MCP 接受了密钥，不证明 Task API 的执行权限。
- `failed`：按认证／网络／契约错误修复，再刷新受影响服务；其他路线仍可使用。

可选原生研究 MCP 返回对应端点的 `setup` 指引。先检查已有登记，避免重复添加。Codex 使用 `codex mcp list --json`、`codex mcp add NAME --url URL`，支持 OAuth 的端点用 `codex mcp login NAME`；Claude 使用 `claude mcp list`、`claude mcp add --scope user --transport http NAME URL`，再在 `/mcp` 授权。采用实际 scope 和已存在的名称。Pi 不假定安装任何 MCP 扩展，宿主自行进行的普通／深度研究使用同包 CLI。DSH 通过官方 MCP client 在所选 profile 配置 `transport: streamable-http`、端点及环境变量引用的 headers；该桥接器文档尚未确立 OAuth 支持。工具可见不证明登录成功，不用启动付费任务来测试授权。

向导展示宿主步骤，不执行它们或导入宿主 token。`needs_attention` 列出失败检查和所选服务必需但缺失的密钥。缓存保留时间戳与过期时间，失败最多缓存 60 秒；文件位于数据目录的 `readiness/`，不含原始密钥。修改配置或轮换密钥会使对应证据失效。

## 配置入口

`get_settings` 返回有效设置及 `config_path`，只读不创建文件。`update_settings` 接收 `changes`，按字段合并并持久保存；后续调用立即读取新设置，不需重启 MCP。例如用户要求以后仅用 Exa 搜索并打开归档：

```json
{"changes":{"search":{"providers":["exa"],"fallback_providers":[]},"archive":{"enabled":true}}}
```

多个 CLI／MCP 进程同时更新同一配置时，通过配置旁的 `.<文件名>.lock` 串行合并，再原子替换配置文件；不同字段的更新不会互相覆盖。锁文件会保留，锁等待超过 10 秒则返回超时。

支持的有效配置形状如下；`directory` 的示例路径须换成使用者选择的绝对路径，也支持 `~`：

```json
{
  "schema_version": 1,
  "timeout_seconds": 30,
  "search": {"providers": ["exa", "parallel"], "fallback_providers": ["tavily", "jina"], "limit_per_target": 5},
  "fetch": {"provider": "exa", "providers": ["exa", "parallel", "jina"], "max_characters": 12000},
  "archive": {"enabled": true, "directory": "/absolute/path/to/knowledge"},
  "research": {"depth": "auto", "prefer_host_workflows": true, "response_language": "auto",
    "methods": ["comparative_analysis", "fact_check", "benchmark_review"]},
  "readiness": {"mode": "cached", "ttl_seconds": 900, "timeout_seconds": 10},
  "professional_research": {"enabled": false, "provider": null,
    "openai": {"model": "o4-mini-deep-research", "max_tool_calls": 24},
    "parallel": {"processor": "pro"}},
  "wiki": {"directory": "/absolute/path/to/wiki"}
}
```

优先级为本次调用参数 → 用户持久配置 → 内置默认值。`fetch_web.archive=false` 只禁用这次保存；改变今后默认值用 `update_settings`。`max_characters` 范围为 100–100000，只有 provider 支持对应参数时才会传递限制，实际请求参数记录在归档中；`character_limit_applied: false` 表示服务未提供本插件支持的长度参数。加大限额不保证得到完整页面。

配置文件路径：CLI `--config` → `BOOKMARK_RESEARCH_CONFIG` → `${XDG_CONFIG_HOME:-~/.config}/bookmark-research/settings.json`。归档默认目录为 `${BOOKMARK_RESEARCH_DATA_DIR}/knowledge`；未指定数据目录时采用 `${XDG_DATA_HOME:-~/.local/share}/bookmark-research/knowledge`。不同载体指向同一配置文件和数据目录即可共享偏好及档案。API key 与偏好分开，放在环境变量或私有凭据文件。

`XDG_CONFIG_HOME` 与 `XDG_DATA_HOME` 必须是绝对路径；空值或相对路径按 XDG 规范忽略，使用用户主目录下的默认位置，避免随客户端工作目录漂移。

`research.depth` 为 auto／quick／agentic／deep；auto 按当前 task_shape 路由。methods 可选 comparative_analysis、fact_check、benchmark_review、wiki_synthesis。路由只给建议，不启动子代理或更改宿主设置。专业服务默认未启用，需独立的 `OPENAI_API_KEY` 或 `PARALLEL_API_KEY`；Search MCP 成功不证明研究 API 已认证，见 [服务参考](research-services.md)。

旧设置文件会继承新增默认值，只保存用户的覆盖字段。若显式保存过 `search.providers` 而没有备用字段，则保留原服务范围、关闭回退；同时设置两组列表即可启用首轮与备用分工。长期偏好存这里，不修改数据包 `AGENTS.md`。配置、证据、Wiki、SQLite 和来源快照位于插件及画布包之外，升级不打包这些用户数据。没有 embedding。目录是否持续检查由每个来源的 `mode` 决定，和网页归档开关无关，见 [来源生命周期](source-lifecycle.md)。

## 一次读取怎样保存

输出语言优先级为本次要求 → `research.response_language`（`auto`／`en`／`zh`）→ auto 时跟随任务／对话 → 均未指定时英文。安装器 `--lang` 只影响帮助和引导，向导另外询问答复语言；委派工作流时传入确定后的 `output_language`。

`fetch_web` 自动保存它自己收到的实际 provider 响应。搜索命中本身不触发抓取或存档，宿主另外配置的 Exa／GitHub MCP 响应也不会被本插件自动截获。

认证、传输或工具契约失败且没有取得实际响应时，返回 `status:"error"`、`error_kind` 和 `usage`，不包含 `result`，也不生成虚构归档。已经取得响应但没有提取出正文时，仍保留实际 `result` 与逐页状态。MCP 将完整调用失败标为 `isError:true`；部分成功保留可用结果。

```text
knowledge/
  sources/
    <本次抓取时间与唯一 ID>/
      response.json
      manifest.json
      pages/<URL 哈希>.md
```

- `response.json` 是 MCP 返回的原始结果对象，包含文本块和 provider 状态；不是网页原始 HTML，也不包含本插件的认证请求头。
- Markdown 保存能确认关联到指定 URL 的实际提取文本，不让模型凭摘要补全文。来源信息放在 `manifest.json`，避免混入原文。
- manifest 记录请求 URL、返回 URL、provider、tool、实际请求参数、检索时间、响应哈希 `response_sha256`、正文路径与哈希，以及失败、缺失、摘录或可能截断的标记。服务返回的发布时间与作者分别放在 `provider_published_at`、`provider_author`，不混入正文。`completeness: "unknown"` 表示不能证明完整。`possibly_truncated: false` 也不是完整性保证。
- `#comments` 等锚点会保留，但网页提取不保证所有评论已加载；`fragment_scope_verified: false` 明示这一点。检索时间不等于网页发布时间、更新时间或缓存时间。
- 返回格式无法识别时仍保存响应与 manifest，正文路径为空；部分 URL 失败时只保存成功识别的正文。每页的 `extraction_status: "provider_error"` 表示服务报告失败；同一 URL 的正文冲突时为 `conflicting_provider_results`，不自动挑选一份正文。归档失败会在 `archive.status: "error"` 明示，工具仍返回已收到的内容，不自动重复付费抓取。
- Exa 批量记录支持带缩进的多行标题。每个独占行的 `URL:` 字段都必须属于已识别的记录；边界缺失、格式异常或重复时，该文本块只保留原始响应。未请求的重定向页面同样构成边界。正文内出现类似记录字段的歧义内容时，这项保守检查可能不提取正文，应检查原始响应，不将其归给另一页。
- 再读同一 URL 会追加新快照，不覆盖旧档案；这只是按调用保存，不是后台版本监控。

报告可引用 `archive.manifest_path` 和各页 `body_path`。档案不自动加入书签 SQLite 或生成 Wiki。宿主实际取得的原文可用 `research_import_evidence` 导入并标明 provenance；外部研究报告用 external_report，引用列表不算原页阅读。整理知识页使用 `wiki_write`。

深度研究使用独立的 `research/` 目录保存状态和证据。`research_fetch` 始终保存已取得的研究响应和正文，普通 fetch 的 archive 开关不影响它；任务恢复和引用校验需要这些快照。会话详情与分页见 [深度研究流程](deep-research.md)。
