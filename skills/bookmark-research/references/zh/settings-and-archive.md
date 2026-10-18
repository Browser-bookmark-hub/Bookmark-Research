# 配置与来源归档

[English](../settings-and-archive.md) · **中文阅读版**

用户可直接在对话中改配置，CLI 与 MCP 使用同一套实现。当前没有独立图形设置页。

provider 可选 `exa`、`parallel`、`tavily`、`jina`。搜索第一轮由 `search.providers` 指定（Exa + Parallel），策略由 `search.strategy` 选择：`hedged`（默认）全并发，所有查询都有结果后最多再等 `search.grace_seconds`（默认 2）即返回；`staggered` 错峰，查询未全部解析才发下一家；`sequential` 按顺序逐家调用，只把未解析查询交给下一家；`wait_all` 等全部。首轮受 `search.deadline_seconds`（默认 10）约束，被放弃与未调用的 provider 分别记录在 `routing.abandoned_providers` 与 `routing.not_attempted_providers`；设为 null 可关闭对应限制。无结果查询交给 `search.fallback_providers`（Tavily + 有 key 的 Jina）；设为空数组可关闭回退。读取先用 `fetch.provider`，策略由 `fetch.strategy` 选择：`staggered`（默认）在当前提供商超过 `fetch.grace_seconds`（默认 25）仍未解决时并行下一家；`hedged` 全部并发；`sequential` 逐家等待；`grace_seconds` 设为 null 即回到逐家等待。被放弃的提供商记入 `abandoned_providers`；连续两次整批无可用正文的提供商会短暂跳过（`provider_stalled`）。其余 `fetch.providers` 对未成功 URL 并发兜底，默认为 Exa → Parallel + Jina。Jina Reader 支持匿名读取，Search 需要 `JINA_API_KEY`。Tavily 使用 `TAVILY_API_KEY` 或 keyless header。密钥优先读取进程环境，其次读取私有凭据文件，公共访问仍受限额影响。

## 终端向导与就绪检查

运行 `python3 <root>/src/cli.py setup --host codex`（或 `claude_code`、`pi`、`dsh`）设置偏好、隐藏输入密钥并检查所选服务。`--lang auto|en|zh` 选择向导语言。`--non-interactive --input FILE` 无提示合并部分偏好，`--input -` 从 stdin 读取 JSON。Agent 通过环境变量提供密钥，不在聊天或偏好 JSON 中传递。`--skip-checks` 不联网；`--test-retrieval` 选择执行可能使用额度的样例搜索／阅读，两者互斥。向导和检查不会创建专业研究任务。

向导将密钥保存为配置旁的 `credentials.json`，或 `BOOKMARK_RESEARCH_CREDENTIALS` 指定的文件；文件为权限 `0600` 的本地明文，仅当前用户可读。运行时会重新读取文件，保存后不必重启插件；更改进程环境变量需重启对应进程。环境变量优先。宿主 OAuth token 留在宿主，插件密钥不会自动授权另外登记的宿主 MCP。

访问能力不明、诊断失败或选择外部研究服务时调用 `research_readiness`，传入实际 `host`、`observed_tools` 及限定的 `providers`。CLI 示例：`readiness --host codex --tool mcp__exa__agent_run`。工具观察省略表示未知，空数组表示未观察到工具；复用当前结果。本地查询无需检查，已知 URL 可以直接交给选定的读取工具。搜索／读取命令不会隐式运行 readiness；下表策略作用于显式的 readiness 调用。

| 策略 | 行为 |
| --- | --- |
| `cached`（默认） | 首次、配置／密钥变化或过期后检查，默认 TTL 为 900 秒 |
| `always` | 每次 readiness 调用均刷新 |
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
  "search": {"providers": ["exa", "parallel"], "fallback_providers": ["tavily", "jina"], "limit_per_target": 5,
    "strategy": "hedged", "grace_seconds": 2, "deadline_seconds": 10, "cache_seconds": 0},
  "fetch": {"provider": "exa", "providers": ["exa", "parallel", "jina"], "max_characters": 12000,
    "strategy": "staggered", "grace_seconds": 25, "deadline_seconds": null, "reuse_seconds": 0},
  "server": {"network_workers": 4, "max_pending_calls": 16},
  "archive": {"enabled": true, "directory": "/absolute/path/to/knowledge"},
  "research": {"depth": "auto", "prefer_host_workflows": true, "response_language": "auto",
    "methods": ["comparative_analysis", "fact_check", "benchmark_review"]},
  "readiness": {"mode": "cached", "ttl_seconds": 900, "timeout_seconds": 10},
  "professional_research": {"enabled": false, "provider": null,
    "openai": {"model": "o4-mini-deep-research", "max_tool_calls": 24},
    "parallel": {"processor": "pro"}},
  "wiki": {"directory": "/absolute/path/to/wiki", "after_research": "suggest", "max_source_age_days": 30},
  "output": {"mode": "central", "directory": "/absolute/path/to/research"}
}
```

优先级为本次调用参数 → 用户持久配置 → 内置默认值。`fetch_web.archive=false` 只禁用这次保存；改变今后默认值用 `update_settings`。`max_characters` 范围为 100–100000，普通输出始终执行每页限制；提供商支持时也传递对应请求参数。`character_limit_applied:false` 仅表示提供商侧没有可用长度参数，不代表插件输出无限制。加大限额不保证完整页面。`wiki.max_source_age_days` 默认 30 天，范围为 1–3650。

`search.cache_seconds`（0–3600，默认 0）让短时间内的相同搜索直接返回进程内缓存，不再调用提供商；这些批次标记 `cached:true`，保留原 `retrieved_at`，不消耗提供商额度。`fetch.reuse_seconds`（0–86400，默认 0）让 `research_fetch` 对窗口内已保存正文的 URL 直接返回 `reused_sources`（保留原 ID 与检索时间，不追加新快照），不再联网，也不占抓取预算。`server.network_workers`（1–16）与 `server.max_pending_calls`（1–64，且不小于 worker 数）设置 stdio 服务端并发，重启服务后生效。

## 研究结果位置与 Wiki 后续整理

`output.mode` 决定新研究任务文件夹的位置。`central`（默认）使用 `output.directory`（`<数据目录>/research`）。`beside_input` 放在唯一输入旁边：文件 `a.json` → 同级 `a.bookmark-research/`，文件夹或 ZIP `pkg` → 同级 `pkg.bookmark-research/`，不进入原文件夹。URL 列表、多个来源、Git 仓库、画布包、插件目录或没有写权限时退回统一目录，`research_start` 的 `output.fallback_reason` 说明原因。修改只影响新任务，已有任务不迁移；`<数据目录>/research-locations.json` 登记所有任务文件夹，移动或删除的标为 missing。每个任务有 `work/` 文件夹，供 agent 存放中间文件。

`wiki.after_research` 决定 `research_finish.wiki_follow_up`：`suggest`（默认）列出候选页面并先征求用户同意，`auto` 直接写入已审核结论，`off` 不给建议。

配置文件路径：CLI `--config` → `BOOKMARK_RESEARCH_CONFIG` → `${XDG_CONFIG_HOME:-~/.config}/bookmark-research/settings.json`。归档默认目录为 `${BOOKMARK_RESEARCH_DATA_DIR}/knowledge`；未指定数据目录时采用 `${XDG_DATA_HOME:-~/.local/share}/bookmark-research/knowledge`。不同载体指向同一配置文件和数据目录即可共享偏好及档案。API key 与偏好分开，放在环境变量或私有凭据文件。

`XDG_CONFIG_HOME` 与 `XDG_DATA_HOME` 必须是绝对路径；空值或相对路径按 XDG 规范忽略，使用用户主目录下的默认位置，避免随客户端工作目录漂移。

`research.depth` 为 auto／quick／agentic／deep；auto 按当前 task_shape 路由。methods 可选 comparative_analysis、fact_check、benchmark_review、wiki_synthesis。路由只给建议，不启动子代理或更改宿主设置。专业服务默认未启用，需独立的 `OPENAI_API_KEY` 或 `PARALLEL_API_KEY`；Search MCP 成功不证明研究 API 已认证，见 [服务参考](research-services.md)。

旧设置文件会继承新增默认值，只保存用户的覆盖字段。若显式保存过 `search.providers` 而没有备用字段，则保留原服务范围、关闭回退；同时设置两组列表即可启用首轮与备用分工。长期偏好存这里，不修改数据包 `AGENTS.md`。配置、证据、Wiki、SQLite 和来源快照位于插件及画布包之外，升级不打包这些用户数据。没有 embedding。目录是否持续检查由每个来源的 `mode` 决定，和网页归档开关无关，见 [来源生命周期](source-lifecycle.md)。

## 一次读取怎样保存

输出语言优先级为本次要求 → `research.response_language`（`auto`／`en`／`zh`）→ auto 时跟随任务／对话 → 均未指定时英文。安装器 `--lang` 只影响帮助和引导，向导另外询问答复语言；委派工作流时传入确定后的 `output_language`。

`fetch_web` 自动保存它自己收到的实际 provider 响应。搜索命中本身不触发抓取或存档，宿主另外配置的 Exa／GitHub MCP 响应也不会被本插件自动截获。

普通输出同时执行每页 `max_characters` 与整批 `max_total_characters` 限制（整批默认 100000，范围 100–800000）。`characters`／`text_sha256` 对应当前切片，`source_characters`／`sha256` 对应完整归档正文；`output_truncated`、`next_offset` 和 `continuation` 明确标出未返回部分。带 `capture_id` 和 offset 续读同一快照时不联网，并省略 provider、archive、raw。`raw:true` 用于诊断原始响应，仍受 MCP 总返回上限约束。

stdio 服务最多同时执行 4 个网络调用，运行与排队合计最多 16 个。本地书签 SQLite 查询留在连接线程，可在抓取期间先返回；响应按 request ID 对应，可能乱序。队列满时明确报错，取消只能停止尚未开始的请求，已发出的 HTTP 调用按提供商超时结束并保留结果／操作回执。正常 stdin EOF 会处理完已接受请求。

认证、传输或工具契约失败且没有取得实际响应时，返回 `status:"error"`、`error_kind` 和 `usage`，不包含 `result`，也不生成虚构归档。已经取得响应但没有提取出正文时，仍保留实际 `result` 与逐页状态。MCP 将完整调用失败标为 `isError:true`；部分成功保留可用结果。

```text
knowledge/
  sources/
    <本次抓取时间与唯一 ID>/
      response.json
      manifest.json
  pages/<SHA-256>.md      每份不同正文一个文件，多次抓取共用
```

- `response.json` 是 MCP 返回的原始结果对象，包含文本块和 provider 状态；不是网页原始 HTML，也不包含本插件的认证请求头。
- Markdown 保存能确认关联到指定 URL 的实际提取文本，不让模型凭摘要补全文；相同正文只存一份，由各 manifest 的 `body_file` 引用（旧抓取在其目录内保存 `pages/<URL 哈希>.md`，两种都可读取）。来源信息放在 `manifest.json`，避免混入原文。
- manifest 记录请求 URL、返回 URL、provider、tool、实际请求参数、检索时间、响应哈希 `response_sha256`、正文路径与哈希，以及失败、缺失、摘录或可能截断的标记。服务返回的发布时间与作者分别放在 `provider_published_at`、`provider_author`，不混入正文。每页还带 `content_state`（页面自身的形态：`usable`、`content_insufficient`、`js_shell_suspected`、`challenge_blocked`、`soft_404`、`paywall_suspected`，没拿到正文时为 `unavailable`），只有 `usable` 值得引用。`published_at` 是解析后的日精度日期，附 `published_at_source`（`provider_metadata`、`structured_metadata`、`body_date`）与 `published_at_confidence`；正文里的裸日期为低置信，且晚于抓取日的一律拒绝。`completeness: "unknown"` 表示不能证明完整。`possibly_truncated: false` 也不是完整性保证。
- `#comments` 等锚点会保留，但网页提取不保证所有评论已加载；`fragment_scope_verified: false` 明示这一点。检索时间不等于网页发布时间、更新时间或缓存时间。
- 返回格式无法识别时仍保存响应与 manifest，正文路径为空；部分 URL 失败时只保存成功识别的正文。每页的 `extraction_status: "provider_error"` 表示服务报告失败；同一 URL 的正文冲突时为 `conflicting_provider_results`，不自动挑选一份正文。归档失败会在 `archive.status: "error"` 明示，工具仍返回已收到的内容，不自动重复付费抓取。
- Exa 批量记录支持带缩进的多行标题。每个独占行的 `URL:` 字段都必须属于已识别的记录；边界缺失、格式异常或重复时，该文本块只保留原始响应。未请求的重定向页面同样构成边界。正文内出现类似记录字段的歧义内容时，这项保守检查可能不提取正文，应检查原始响应，不将其归给另一页。
- 旧提供商快照在续读或引用时会对照保存的原始响应重新核对来源；即使正文哈希未变，串页等归属不明的摘录也会被拒绝。归档检索索引会按新提取版本对已有记录复核一次，原抓取文件保留不动。
- 再读同一 URL 会追加新快照，不覆盖旧档案；这只是按调用保存，不是后台版本监控。

报告可引用 `archive.manifest_path` 和各页 `body_path`。`search_archive`（CLI `search-archive`）对本归档和所有已登记研究任务证据中的已保存正文做字面全文检索，按内容哈希合并；可重建的索引为 `<数据目录>/raw-library.sqlite3`。档案不自动加入书签 SQLite 或生成 Wiki。宿主实际取得的原文可用 `research_import_evidence` 导入并标明 provenance；外部研究报告用 external_report，引用列表不算原页阅读。整理知识页使用 `wiki_write`。

深度研究在各自的任务文件夹保存状态和证据（位置见上文）。`research_fetch` 始终保存已取得的研究响应和正文，普通 fetch 的 archive 开关不影响它；任务恢复和引用校验需要这些快照。会话详情与分页见 [深度研究流程](deep-research.md)。
