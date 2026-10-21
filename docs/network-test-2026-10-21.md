# 真实网络与样本包测试（2026-10-21）

> 测试对象：用户提供的真实样本包 `书签画布-关于书签数据包的AI化升级调研-20260906-125939`（223 bookmarks / 207 unique URLs，索引 source_id `research`）。
>
> 不是合成数据。网络调用使用当前已安装的插件（beta.15 进程）和真实公共 provider；预检/证据回链的新代码用源码内进程验证。
>
> 测试时间：2026-10-21 05:32–05:33 UTC（13:32–13:33 Asia/Shanghai）。

## 1. 实际执行了什么

| 步骤 | 工具 | 规模 |
|---|---|---|
| 预检 | `plan_research(source_id=research)` | 1 次，问题“AI 搜索与 Deep Research 的评测基准和工具有哪些” |
| 外部发现 | `search_web` | 1 个 target，2 providers（Exa、Parallel），limit=3 |
| 插件抓取 | `fetch_web` | 8 个真实包内 URL，archive=true，max_total=24,000 |
| 证据包 | `discovery_bundle` | 3 个来源（2 usable + 1 js_shell） |
| 宿主读取 | `web_fetch` | 1 个相同 URL（Exa docs） |
| Deep research | `research_services` | 1 次；确认默认关闭 |
| 新代码回读 | `SourceArchive.read_capture` | 同一 8 页 capture，fair share |

## 2. 实际结果

### 2.1 `search_web`：2 个 provider 都成功

- `successful_provider_count: 2`，`tool_calls: 2`，`http_requests: 4`；
- 6 个 unique URL，返回 3 个；
- 两个 provider 的 URL 没有重叠，`corroborated` 均为 false；
- 结果里既有可用排名（DeepResearch Bench、BenchLM、Artificial Analysis），也有一条明显不相关的公司目录 `platform.tracxn.com/.../benchlm ai`。

**事实结论**：网络发现链路可用；结果质量仍需要宿主阅读/筛选，不能把 provider 排名直接当证据。

### 2.2 `fetch_web`：8 个真实 URL，8 个归档

`archive.status: saved`，`capture_id: 20261021T053322399181Z-b9e22082f102`。

| URL | 字符数 | `content_state` | 发布日期 |
|---|---:|---|---|
| exa.ai/docs/reference/search-api-guide | 25,430 | usable | null |
| docs.parallel.ai/integrations/mcp/quickstart | 11,563 | usable | null |
| artificialanalysis.ai/zh/agents/search-api | 12,965 | usable | 2026-10-19（low，body_date） |
| leaderboard.steel.dev/leaderboards/browsecomp/ | 28,589 | usable | 2026-09-04（high，structured） |
| github.com/brave/brave-search-mcp-server | 22,072 | usable | 2025-06-12（low，body_date） |
| openai.com/research/index/release/ | 3,357 | **js_shell_suspected** | 2026-10-07（low） |
| skills.sh/?q=search | 11,879 | usable | null |
| arcprize.org/leaderboard | 73,291 | **输出 0 字符** | null |

**发现的真实问题**：当前安装的 beta.15 逐页消耗 24k 总预算，前 6 页吃掉额度，`arcprize` 只剩 0 字符，但页面仍标 `usable`。这不是合成数据问题，是实际包 URL 上发生的。

用新代码对同一 capture 回读：

```text
pages_with_text=8, pages_without_text=0, successful_url_count=8
每页 3,000 字符；arcprize 也是 3,000 字符
耗时约 1.3–4.4 ms（归档读，无网络）
```

**事实结论**：新 fair-share 修复在实际 capture 上有效，8/8 页都有正文。

### 2.3 `discovery_bundle`：实际证据 / 不可用分开

输入 2 个 usable + 1 个 `js_shell_suspected`：

- `evidence_count: 2`；
- `unavailable_count: 1`，reason `js_shell_suspected`；
- 输出 997 字符，degradation `excerpts`。

新代码带 `capture_id` 回读同一 capture：

```text
capture_id=20261021T053322399181Z-b9e22082f102
text_origin=archive
quote_verified=true
text_sha256=88646739b300b8e42e0cbe2c3ce87d9a4d765c855c310d6ed3e3de91f1fcb4dd
source_characters=25430
```

**事实结论**：证据能回链到不可变归档；宿主文本没有这个保证。

### 2.4 宿主 `web_fetch` 对比

对 `https://exa.ai/docs/reference/search-api-guide` 调用宿主 `web_fetch`：

- 实际落到 `https://exa.ai/docs/search/quickstart`（重定向）；
- 返回正文，但被截断；
- **没有 `capture_id`、`content_state`、`published_at`、sha 或归档**；
- 因此不能直接作为可引用证据，必须导入或重新用插件抓取。

**事实结论**：宿主 fetch 是“快速查看”，不是“证据读取”。

### 2.5 样本包里的本地文件 URL

包内有一个 `file:///.../Manus_...pdf`。当前 beta.15 的 `plan_research` 会把它排到 URL 第一位；用新源码跑同一问题，top 8 变成 docs/repo，`file://` 因 `url_kind=local_file` 被排到最后。

直接 `fetch_web(file://...)` 返回：

```text
Every URL must be HTTP(S) without embedded credentials
```

**事实结论**：本地文件不是网络 URL；预检应标 `local_file`，不要让宿主拿它去走 HTTP fetch。

### 2.6 Deep research：当前不可测真实 API

`research_services(provider=parallel)` 实际返回：

```text
enabled: false
ready_to_start: false
missing: ["professional_research.enabled", "PARALLEL_API_KEY"]
```

**事实结论**：外部 Deep Research API 当前关闭且没有 key，不能做真实网络测试；只能测插件本地 `research_*` 生命周期或 mock。宿主 `research_start` 仍可用，但它不自动调用外部 API。

## 3. 修复项（由真实测试触发）

| 问题 | 修复 |
|---|---|
| 24k 预算被前几页吃光，后页 0 字符仍 `usable` | `fetch_web` fair share；0 字页 `unavailable`；`pages_with_text` |
| `file://` 被当普通 URL 排第一 | `url_kind=local_file`，排序最后；`fetch_web` 明确拒绝 |
| 两字母缩写 `AI` 被 relevance 丢弃 | 大写两字母词（AI/UI/5G）计为 meaningful |
| 长唯一词命中一条但分数低被误杀 | token-aware 标题命中；`unique5000` 等可接受 |
| 样本包自身问题“书签数据包的 AI 化升级”被拒 | 加上 `AI` 后 accepted，top cards 正常 |

验证：全量 **774 通过，3 跳过**。

## 4. 结论

- **真实网络链路是通的**：`search_web` 2/2 provider 成功，`fetch_web` 8/8 URL 归档；
- **真实包暴露了 beta.15 的预算 bug**：`arcprize` 0 字符；新代码同一 capture 8/8 页 3,000 字符；
- **宿主 fetch 与插件 fetch 不是一回事**：宿主没有状态/归档/证据回链；
- **Deep research 当前无法真实测**：API 关闭、无 key；不要用 mock 代替后声称“测过真实 API”；
- **Agentic search 的“网络部分”已验证**：search → fetch → bundle 实跑；但“是否该搜、搜几次”仍是宿主行为，不属于网络吞吐测试。

## 4.5 延迟实测：URL 发现 vs 全文抓取

同一样本包、同一批公共 URL，实际计时（不是 mock）：

| 操作 | 冷启动（首次） | 复用会话（第二次） |
|---|---:|---:|
| `search` 1 provider，20 个 URL | 5.08 s | **1.86 s** |
| `search` 2 providers，10 个 URL | 4.69 s | **1.82 s** |
| `fetch` 6 URL，单 provider（Exa） | 7.4 s | — |
| `fetch` 6 URL，单 provider（Parallel） | 6.9 s（首次 error）→17.2 s（成功） | — |
| `fetch` 6 URL，Exa+Parallel 并发分片 | 4.9 s | **1.68 s** |

关键差异：

- **URL 发现**是有可能做到 2–3 秒的：暖会话下 20 个 URL 1.86 秒，和 Perplexity/ChatGPT 那类“先把几十个链接列出来”的体验接近。
- **冷启动**的 5 秒主要花在 provider MCP 的 `initialize` + `tools/list` + 会话建立；同一进程内第二次调用就降到 1.8 秒。插件 MCP 进程会缓存 provider client，所以同一会话后续搜索受益。
- **全文抓取**是另一件事：当前 `fetch_web` 默认把一个 provider 的全部 URL 放在一个调用里，6 页实测 7–17 秒；把 URL 分片到 Exa/Parallel 并发后，冷启动 4.9 秒、暖会话 **1.68 秒**。
- Perplexity/ChatGPT/DeepSeek/豆包展示的“几十个 URL 2–3 秒”通常是**搜索结果/引用**，不是把几十页全文都抓回本地并做归档、哈希、内容状态和日期判定。全文读取不可能对所有页面都维持 2–3 秒。

## 4.6 官方文档核对

豆包/DeepSeek/OpenAI/Perplexity 的公开文档与第三方延迟数据见 [搜索时延：官方文档核对](search-latency-provider-research-2026-10-21.md)。

## 5. 复现

```sh
# 真实包预检
python3 - <<'PY'
# 见 docs/validation report 中的 source_id=research 调用
PY

# 插件抓取（真实 URL）
# MCP: fetch_web(urls=[...], archive=true, max_total_characters=24000)

# 归档回读（新 fair share，无网络）
python3 - <<'PY'
from archive import SourceArchive
from settings import Settings
a = SourceArchive(Settings().load()['archive']['directory'])
print(a.read_capture('20261021T053322399181Z-b9e22082f102', [...], fair_share_min=500)['pages_with_text'])
PY
```

本次调用消耗：2 次 provider search 工具调用（4 HTTP）、1 次 fetch 工具调用（8 URL）、1 次宿主 fetch；没有使用 API key。
