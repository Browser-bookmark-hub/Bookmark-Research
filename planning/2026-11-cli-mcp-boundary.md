# 能力 × 入口：CLI / MCP / Skill / 共享核心 的分层判据

> 2026-11-08 · 配套 `planning/2026-11-tool-surface-plan.md`（10 原语 + 15 题阶梯）与 `.bench/report-runs-6-9.md`（9 轮实测）
> 本文解决一个计划书里没有单独展开的问题：**同一份能力，什么时候给 CLI、什么时候给 MCP、什么时候只写 Skill、什么时候必须进共享核心。**

## 0. 先纠正一个隐含前提

九轮实测只覆盖 **T2 模糊定位** 一个格子。它证明的是"步数主导 wall（r²≈0.85）、工具延迟可忽略"，**不能外推**到 T5 搜索、T6 抓取、T7 深度调研、T8 沉淀。

所以"通用"不靠把 32s 复制到别处，靠**判据 + 分层**：每个能力先回答"谁执行、结果多大、跑多久、要不要鉴权、要不要并发"，入口是这五个答案的函数。

## 1. 五个轴（不是"本地 vs 远程"）

| 轴 | 问法 | 偏 CLI | 偏 MCP |
|---|---|---|---|
| 调用者 | 谁在逐步决策 | 人 / CI / 批量脚本 | 宿主 agent 的**单步**决策 |
| 结果形状 | 回包多大 | 大产物、落盘、可 diff | 小决策负载（≤4k 字符） |
| 生命周期 | 跑多久 | 秒–分钟，需要 `--dry-run` | 亚秒–数秒 |
| 状态与权限 | 有没有凭证/受控动作 | 无状态、幂等 | OAuth、refresh token、受控写入 |
| 并发 | 单发还是多路 | 批量/后台 | 交互式，少量并行 |

**四条判据（按顺序问，命中即停）：**

1. 宿主 shell 能在 ≤2 步稳定做完？→ **不做工具**，Skill 写命令（`git`、`ls`、`jq`、`npm`）。
2. 需要领域索引/排序/拓扑/鉴权/并发/归档/引用校验？→ 进 **共享核心**。
3. 该原语在 ≥3 类任务复用 **且** 中位步数 >6？→ 进 **MCP 默认档**。
4. 结果大 / 要审计 / 批量 / 长任务？→ 给 **CLI 入口**；MCP 只保留 `spawn` + `job` 两个句柄。

> 判据 3 是闸门，不是鼓励：当前 10 个原语已经覆盖三个宗旨的"原语"部分，**第 11 个工具要有 15 题数据才准进**。

## 2. 三个宗旨 × 入口矩阵

| 能力 | 共享核心 | CLI | MCP 默认档 | Skill 职责 | 并发/状态 |
|---|---|---|---|---|---|
| **1① Canvas 节点/边/卡片上下文** | `BookmarkIndex` + `locate` core | `br locate/read/walk --json --out` | `locate` `read` `walk` | 先 locate，命中即 read，禁止 `/**/` 全包扫 | 无状态，读快照 |
| **1② Git 时间上下文** | **不进 core** | 宿主 `git log/show/diff` | **不做工具** | 明确"Git 时间 ≠ 导入快照时间" | 宿主 shell |
| **1③ 导入/同步/快照** | `SourceManager` | `br sync --dry-run` → `--apply` | 不给默认档 | 大 I/O 走 CLI | 单写者 |
| **2① web fetch（有明确 URL）** | 抓取 + 正文抽取 + capture | `br fetch --max-total-chars --out` | `fetch`（正文 + `content_state` + `capture_id`） | 只在"要引用原文"时抓；抓后必须看 `content_state` | 单次内 1–16 URL 并发 |
| **2② 宿主 search（Non-reasoning）** | — | — | **不做工具** | 首选宿主自带 search（三宿主各有） | 宿主 |
| **2③ 插件 search（多 provider fallback）** | `fuse_results` + provider 适配 | `br search --providers --json` | `search`（只回发现结果，不称正文已核验） | 宿主结果够用就不调插件 search | 单次内 provider 并发 |
| **2④ Agentic search（reasoning）** | 只提供 `search`/`fetch`/`ingest` | `br research …` 记录 | **不做阻塞式 agent loop**；批量用 `spawn` | **宿主掌舵**：自己迭代、自己洗稿 | 宿主循环；批量进 job |
| **2⑤ Deep research（API）** | `ResearchServices`（provider-managed） | `br research service start/status/result` | `spawn` → `job` | 报告是二手证据，必须回查原始 URL | 外部异步，只按 external_id 观察 |
| **2⑥ ingest（宿主结果回流）** | `fuse_results`（URL/SHA-256/RRF） | `br ingest --input <file>` | `ingest`（≤16 批 / 8,000 字符） | 不把"链接重合"说成"事实印证" | 幂等，CPU 轻 |
| **3① Wiki 写入** | `WikiStore`（引用校验 + revision） | `br wiki write --expected-revision` | `save` | 只在有可核验引用时写 | 单写者 + CAS |
| **3② Wiki 检索** | `locate(in=["wiki"])` | `br locate --in wiki` | `locate` + `read` | 先读 revision 再判断 freshness | 读快照 |
| **3③ Wiki 维护** | `wiki lint/refresh` | CLI | **不给默认档** | 诊断类走 CLI | 后台 job |

**三条不可越界：**

- **Git 永不进 MCP**：宿主 shell 更强，且需要人可审计的 diff。
- **Agentic search 不进插件工具面**：它是"推理循环"，做成阻塞工具会占住宿主一步、且把宿主最擅长的编排抢走。
- **调度不进 MCP**：工具调用是同步等待；并发/排队必须落在核心的作业层。

## 3. 并发：现在有什么、缺什么（这是"通用"的真正缺口）

现状（已核对代码）：

- MCP 进程内网络并发：`NETWORK_WORKERS = 4`、`MAX_PENDING_CALLS = 16`，`br serve` 可由 `settings.server` 覆盖；
- 外部长任务状态**落盘**（按 `external_id` 一个目录），但**没有本地 worker、没有自动重试**（`research_services.describe()` 原文："No local worker or automatic retry"）；
- **没有作业列表**：`job`/`br research service status` 必须带 id；
- 三个宿主 = 三个 MCP 进程，各自 4 个 worker，**互不可见**；CLI 每次新进程。

→ 交互式并发够用；**批量/后台并发不成立**。要做"搜索 + 长期 Wiki 并发"，缺的是调度层：

```
提交（三个入口）                       执行                        观察（任意入口）
MCP spawn/job ─┐                 ┌─ worker pool（单例） ─┐
CLI br job   ─┼─► jobs 表(SQLite WAL) ─┤ provider 配额租约   ├─► artifacts/<job_id>/
cron/人      ─┘   (id, state, attempts, (openai/parallel/    │      report.md, pages.jsonl
                   artifacts, idempotency)  jina/exa…)        └─► 摘要 + 路径 + job_id
```

- **交互路径（≤10s）不进队列**：locate/read/walk/fetch 直接调，保持现在的 20–70ms。
- **后台路径（>10s / 批量 / 多目标）统一进表**：deep research、批量抓取、批量 ingest、Wiki 批量 refresh。
- **全局配额用 SQLite 租约**：每个 provider 独立并发数，避免 3 宿主同时打爆同一 key。
- **结果落 artifacts**：回包只给 `{job_id, state, summary, artifact_path}`，正文不让模型重新读一遍。
- **幂等键已有**（`operation_id` / `replay_matches`），保留并扩展到批量任务。

这一步做完，"三个宿主 + 人 + 定时任务"看到的是**同一个队列**，这才是"长期积累的 Wiki + 并发搜索"的底座。

## 4. 每层的"快"不是同一个指标

| 层 | 瓶颈 | 主指标 | 现状 |
|---|---|---|---|
| 本地定位 | 步数 | 中位步数 / turn-1 wall | 32.2s，8 步（R9） |
| 外部检索 | 吞吐 + 覆盖 | 首证据时间、URLs/min、provider 缺口 | 未测 |
| 深度调研 | 周转 + 可恢复 | 提交→可用报告 wall、取消成功率 | 未测 |
| Wiki | 一致性 | 写冲突率、revision 漂移、二次检索命中 | 未测 |

**不能用一个 wall 数衡量全部。** 定位看步数，检索看吞吐，Wiki 看一致性。

## 5. 验收：把 L5 补进 15 题阶梯

现有 `.bench/ladder.json` 仍是空壳（prompt/target_refs/runs 全空）。补三条 L5 即可覆盖宗旨 2 与 3：

| 题 | 形状 | 记录 |
|---|---|---|
| L5-1 搜索回流 | 宿主 search → `ingest` → 覆盖说明 | provider 覆盖缺口 = 0；不得把链接重合当印证 |
| L5-2 多 URL 抓取 | 3 个 URL 并发 → 正文/`content_state`/逐字引用 | usable 判定正确；引用逐字；capture 可续读 |
| L5-3 深度调研 + 沉淀 | `spawn` → `job` → `save` → `locate(in=wiki)` 复用 | 可取消/可恢复；引用回指原文；revision 冲突可见 |

判据仍是"中位步数 + Q1–Q5 否决"，但 L5 额外看**并发吞吐**与**缺口披露**。

## 6. 不该做的事（重复强调）

1. 不把 `ls`/`cat`/`git status`/文件读写包成 MCP。
2. 不为单场景加第 11 个默认工具。
3. 不把 Agentic Search 做成一个阻塞工具。
4. 不让 MCP 承担排队/重试/调度。
5. 不在 CLI 复制一套业务规则（先 core，再薄包装）。

## 7. 与现有任务书的关系

- 计划书的 10 个原语**已经**覆盖三个宗旨的原语部分，方向是对的；
- 缺的是两块：**作业/调度层**（§3）与 **L5 验收数据**（§5）；
- 0.7.0 之前必须先把 15 题跑出中位数，否则"通用"仍然只是架构主张，不是证据。
