# 三能力收敛与大清理（2026-10-21）

> 只围绕三件事：
> 1. Canvas/JSON 空间关系 + 卡片上下文 + Git 时间上下文
> 2. 书签外部调研：web fetch / agentic search / deep research
> 3. LLM Wiki 作为调研存储
>
> 目标：保留三宿主（Codex / Claude Code / DSH），去掉不属于这三层的包袱。

## 1. 已经清理掉的

| 项 | 处理 |
|---|---|
| Pi 支持 | 删除 `hosts/pi/`、`pi`/`pi-package` 字段、安装/导出/路由/测试 |
| 旧构建产物 | 删除 `dist/bookmark-research-0.5.0-beta.6.tgz` |
| 历史文档 | 34 个旧计划/旧 release notes/旧验证记录移入 `docs/archive/` |
| 发布包 | `docs/archive/**` 从 npm 包排除；`npm pack` 127 个文件，不含 archive |
| 旧文档链接 | 现行文档改成 `docs/archive/...` 文本或已更新路径，避免发布包内断链 |
| Pi 历史文字 | 保留在 archive/release notes，不重写历史 |

全量测试仍为 **768 通过，3 跳过**。

## 2. 保留的核心（不清理）

| 能力 | 工具/代码 | 理由 |
|---|---|---|
| Canvas 空间上下文 | `get_context`、`search_bookmarks`、`bookmark_index` | 第 1 层核心 |
| 卡片/栏目/副本/时间 | `bookmark_index`、`package-semantics` | 第 1 层核心 |
| Git 时间上下文 | 宿主 Git 工具 + `source_history` | 不重复造 Git |
| 已知 URL 读取 | `fetch_web` | 第 2 层 1 |
| Agentic search | `plan_research` + `search_web` + `fetch_web` + `discovery_bundle` | 第 2 层 2 |
| Deep research | `research_*` + `research_service_*` | 第 2 层 3 |
| Wiki | `wiki_*` | 第 3 层 |
| 三宿主 | Codex / Claude Code / DSH | 用户明确保留 |
| 证据/覆盖/预算 | `capture_id`、SHA、coverage、budget | 严谨性核心 |
| 4 个 provider | Exa/Parallel/Tavily/Jina | 外部调研的搜索/读取/回退；不是 UI 功能 |

## 3. 清理决定（已删/暂留）

| 项 | 为什么暂留 | 如果严格三能力，可删吗 |
|---|---|---|
| `agent-plugin` 导出 | 已删除；Agent Plugins 不是三宿主之一 | 已完成 |
| `evaluate_research` / `src/evaluation.py` | 用于质量/评测，不属于三能力主路径 | 可删；会少一个工具和一批测试 |
| `install.sh` | npm 安装的便捷入口 | 暂留；`bookmark-research install` 也可用 |
| `source_remove` / `source_merge` / `source_history` | 维持 Canvas 来源生命周期 | 建议保留 |
| `wiki_lint` / `wiki_refresh` | Wiki 质量与来源新鲜度 | 建议保留 |
| `research_service_cancel/attach` | 外部 Deep Research 生命周期 | 建议保留 |

## 4. 参考项目：只取什么，不搬什么

### smartsearch

可取：

- provider 配置/诊断的产品化思路；
- “先检查连接，再花配额”的 readiness；
- 搜索/读取/研究分层。

不搬：

- 桌面 App / Windows/macOS 原生 UI；
- 18 个 Agent 安装器；
- 独立 Python 运行时分发；
- 多 provider 商店式配置。

### aether-search

可取：

- 多后端 fan-out + RRF 融合；
- 并发 + 总 deadline；
- 引用交叉验证 / 死链探测；
- session source cache。

暂不搬：

- Grok 主通道；
- 9 个搜索后端；
- `web_map`；
- `toggle_builtin_tools`（改宿主设置，风险高）；
- Aux LLM 工具调用循环（和宿主 agentic search 重叠）。

## 5. 当前三宿主边界

| 宿主 | 保留 | 不承诺 |
|---|---|---|
| Codex | 原生 plugin + MCP + `web_search` | 完整 workflow runtime 未验证 |
| Claude Code | marketplace/plugin + MCP + WebSearch/WebFetch | project/local scope 未真实回归 |
| DSH | 官方 MCP client + bundle + 自带搜索 | 同版本重装可能 no-op；workflow 需 profile 配置 |

## 6. 清理后的包结构

```text
bin/            npm CLI
src/            Python 核心 + MCP
scripts/        安装/导出/构建/验证
config/         provider 配置
skills/         Skill + references
hosts/          codex / claude / dsh / shared
docs/           现行文档
docs/archive/   历史记录（不发布）
tests/          测试（不发布）
```

## 7. 下一步

1. `agent-plugin` 已删除；`evaluate_research`、`install.sh` 暂留（见 §3）。
2. 版本 bump beta.16，重装三宿主。
3. 真实 OpenAI 单任务验收。
4. 需要性能时再做 `fetch_web` 分片并发；不要先加 provider/UI。

**结论：先删“非三能力”的历史包袱和 Pi，保留证据链与三阶段；参考项目只借架构，不搬产品。**
