# MCP vs CLI：同一提示词的时间账单

> 数据来源：`~/.dsh/sessions/**/session.v4.jsonl.zstd` 的 `turn/start`、`turn/end`、`step/start`、`tool/call`、`tool/result`、`assistant/message.usage`。
> 只统计每个会话的 **turn 1**（第一条用户消息到该轮结束），单位秒。生成日期：2026-11-06。

## 0. 先说结论

1. **MCP 通道本身不慢。** 今晚这轮真实 MCP 检索调用全部是 50ms 量级：12 次 `search_bookmarks` 合计 **0.63s**，3 次 `get_context` **0.16s**，`sync_package` 0.21s，`index_status` 0.04s。
2. **慢的是两个"重工具"和步数。** 103.5s = LLM 70.4s（22 步）+ 工具等待 33.1s，而 33.1s 里 `plan_research` **23.0s** + `fetch_web` **8.7s** = 31.7s（占 96%）。
3. **每步其实比 11-03 更快**：今晚 3.20s/步，11-03 那轮 5.08s/步。58s → 103.5s 的差距来自 **步数 ×2.4** 加 **一个 23s 的重工具**，不是 MCP 变慢。

## 1. 两处口径修正（重要）

| 你给的 session | 实际是什么 |
|---|---|
| `session-c82b154c`（11-03 15:58，58.0s） | ✅ 真 MCP 基线，同一提示词，5 次 MCP 调用 |
| `session-ea3835c3`（11-06 21:37，113.4s） | ❌ **不是 MCP**。38 次调用全部是 `bash` 跑 `python3 .../src/cli.py`（还带 `time` 前缀、`--format json \| head -40`）。它是**第 4 次 CLI 跑**，不能当 MCP 对照 |
| `session-727d4f0a`（11-06 21:48，58.0s） | ⚠️ `isSeeded: true`，是 `c82b154c` 的 **fork 副本**，数值完全一样，不是第 5 次实验 |
| `session-7ddd1600`（11-06 23:29，103.5s） | ✅ 今晚这轮，真 MCP，19 次 MCP 调用 |

也就是说：**同一提示词、真·MCP 的样本只有 2 个**（58.0s vs 103.5s）。"MCP 这次也慢了" 的对照基础其实是缺的；`ea3835c3` 那 113.4s 是 CLI 的成绩。

## 2. 总表（同一"书签画布"提示词，turn 1）

| 时间 | session | 模式 | wall | 步数 | 调用 | MCP | 工具耗时 | LLM 耗时 | 每步 | 峰值上下文 | 最慢单次 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 11-03 15:58 | c82b154c | **MCP** | **58.0** | 9 | 14 | 5 | 12.3 | 45.7 | 5.08 | 100,130 | 11.4s plan_research |
| 11-06 14:44 | 4516e4f1 | CLI#1 | 175.1 | 40 | 44 | 0 | 26.2 | 148.9 | 3.72 | 69,406 | 6.1s bash |
| 11-06 15:53 | e23ac349 | CLI#2 | 93.7 | 27 | 30 | 0 | 8.5 | 85.2 | 3.16 | 38,717 | 5.6s bash |
| 11-06 17:23 | 0e25abab | CLI#3 | 115.7 | 30 | 45 | 0 | 10.6 | 105.1 | 3.50 | 51,891 | 3.8s bash |
| 11-06 21:37 | ea3835c3 | CLI#4（自称控制变量） | 113.4 | 35 | 38 | 0 | 8.8 | 104.6 | 2.99 | 48,654 | 1.8s bash |
| 11-06 21:45 | 8ecead0f | CLI | 132.2 | 34 | 35 | 0 | 10.2 | 122.0 | 3.59 | 72,271 | 6.2s ask_user |
| 11-06 23:29 | **7ddd1600** | **MCP** | **103.5** | 22 | 29 | 19 | 33.1 | 70.4 | 3.20 | 73,842 | **23.0s plan_research** |

CLI 四轮：93.7 / 113.4 / 115.7 / 175.1，中位 **114.6s**。
MCP 两轮：58.0 / 103.5，中位 **80.8s**。

**结论：MCP 仍不慢于 CLI**（中位快约 34s），但 MCP 的波动来自 `plan_research` 这一次调用的 11s→23s。

## 3. 今晚 103.5s 的逐项拆解

```
103.5s
├─ LLM 生成/推理      70.4s  (22 步 × 3.20s)
│    └─ 步数是最贵的东西：每多一步 ≈ +3.2s
└─ 工具等待           33.1s
     ├─ plan_research  23.0s  ← 唯一的异常项
     ├─ fetch_web       8.7s  ← 网络（Exa 4 次 HTTP + 1 次会话恢复）
     └─ 其余 27 次 MCP+本地调用   1.4s
          search_bookmarks ×12  0.63s (avg 53ms)
          get_context      ×3   0.16s
          sync_package     ×1   0.21s
          index_status     ×1   0.04s
          bash             ×9   0.45s
```

对照 11-03 的 58.0s：

```
58.0s = LLM 45.7s (9 步 × 5.08s) + 工具 12.3s（plan_research 11.4s + 其余 0.9s）
```

**差在哪：**
- 步数 9 → 22（+13 步 ≈ +41.6s LLM）
- plan_research 11.4 → 23.0s（+11.6s）
- 新增 fetch_web 8.7s
- 但每步速率反而从 5.08s 降到 3.20s（−1.88s/步 × 22 ≈ −41s），几乎把步数增量抵消掉

## 4. 为什么 `plan_research` 要 23s

实测拆解（用 `index.sqlite3` 副本跑仓库里的 `BookmarkIndex.plan_scope`，同一 question）：

| 步骤 | 耗时 |
|---|---:|
| 打开库 | 0.006s |
| `plan_scope`（term 展开 + FTS + 卡片密度排序 + URL 汇总） | **0.07 / 0.06 / 0.06s** |

→ **数据库扫描不是原因**。23s 落在 `ResearchPlan.build()` 的另外三块：
`wiki`（页面完整性校验 / 过期证据核对，19MB knowledge）、`raw.search`（archive FTS，22MB raw-library）、`freshness`+预算裁剪。
11-03 到 11-06 之间 knowledge 19MB、索引 60MB 都长大了；首次调用还要 warm archive 索引 → 11.4s 变 23.0s。

**待办**：在 `ResearchPlan.build` 里加分段计时（wiki / raw / freshness / render），确认是不是 archive 索引增量重建吃掉了 20s。这是目前唯一"能用一次改动拿回 20s"的地方。

## 5. 为什么第一次 MCP（58s）能这么快

它不是运气好，是**调用次数少**：
- `search_bookmarks` 一次就带了 `targets: ["3D","2D"]` 合并查询 + `folder_id` 直接下钻到 `2D / 3D` 文件夹，3 次就收敛。
- 没有 `fetch_web`（没去验证原页）。
- `plan_research` 只当旁证用了一次。

今晚这轮我做了 12 次 `search_bookmarks`（把 `three.js / WebGL / Spline / Blender / Meshy / gaussian / splat / 建模` 等拆成多轮试探）+ 3 次 `get_context` + 1 次 `fetch_web`。**信息量并没有多 4 倍，步数多了 2.4 倍。**

## 6. 首步 prompt cache 命中情况

| session | 首步 inputTokens | 首步 cacheReadTokens |
|---|---:|---:|
| c82b154c（11-03 MCP） | 1,043 | 23,552 |
| 7ddd1600（今晚 MCP） | **20,661** | **512** |

今晚首步几乎全量 prefill（工具表/prompt 前缀变了导致缓存失效）。影响约 1–2s，被后续 22 步的缓存命中摊薄；但如果每轮都 miss，就是固定开销。**建议把 MCP 工具 schema 的序列化顺序固定**，别让 `tools/list` 抖动。

## 7. 优化清单（按性价比排序）

1. **`plan_research` 加分段计时 + 缓存**（同一 `question + source_id`，60s TTL）。目标 23s → 3s 内；命中直接 0。
2. **`plan_research` 默认 `refresh: false`**（省掉每次的 live 源检查；需要新鲜度时显式传 `refresh: true`）。
3. **`include_archive` / `include_wiki` 开关**：定位类问题默认跳过 archive，把 archive 留给"调研"类问题。这是 1、2 之外最快的一刀。
4. **SKILL.md 加检索纪律**：`search_bookmarks` 每轮 ≤3 次，优先 `folder_id` 下钻，多词一律塞进同一个 `targets` 数组；不要为同义词反复试探。
5. **`fetch_web` 只在"要引用原文"时调用**，定位任务不必验证。
6. **CLI 侧**：`cli.py` 每次冷启动 + `--format json` 全量输出是固定税；如果坚持 CLI 化，考虑 `serve` 常驻 + 客户端复用同一进程。

## 8. 复现方法

会话数据是 zstd 压缩的 JSONL，直接解压即可算：

```sh
zstd -dc ~/.dsh/sessions/<project>/session-<id>/session.v4.jsonl.zstd \
  | python3 -c "import sys,json; evs=[json.loads(l) for l in sys.stdin if l.strip()]; ..."
```

关键字段：`turn/start.time`、`turn/end.time`、`step/start`（步数）、`tool/call.callId → tool/result.message.source.callId`（工具耗时）、`assistant/message.usage.{inputTokens,cacheReadTokens}`（上下文规模）。
注意 `tool/result` 的 callId 在 `data.message.source.callId`，不在 `data.toolCallId`。

---

# 9. 结合「CLI-first / MCP 只在必要时」的重估

参考口径：延迟、上下文消耗、成功率、失败恢复四项一起比，不看单次调用 token。

## 9.1 先把"CLI 慢"归因到正确的位置

如果是"进程启动慢"，CLI 每轮 27–44 次 bash 也只该花 5–10s。实测也不是：CLI 轮的工具总耗时是 **8.5–26.2s**，其余 85–149s 全在模型侧。

真正的问题是**CLI 没做成 agent 接口**，于是模型自己现场造了个查询引擎：

| session | 模式 | 步数 | bash 数 | 内联 python 解析 | `\| head`/`\| tail` 截断 | 直接 `sqlite3` 查库 |
|---|---|---:|---:|---:|---:|---:|
| c82b154c | MCP | 9 | 8 | – | – | – |
| 7ddd1600 | MCP | 22 | 9 | – | – | – |
| e23ac349 | CLI | 27 | 29 | 9 (31%) | 20 (68%) | 12 |
| 0e25abab | CLI | 30 | 44 | 14 (31%) | 23 (52%) | 1 |
| 8ecead0f | CLI | 34 | 33 | 11 (33%) | 19 (57%) | 17 |
| ea3835c3 | CLI | 35 | 37 | 19 (51%) | 14 (37%) | 2 |
| 4516e4f1 | CLI | 40 | 39 | 24 (61%) | 7 (17%) | 21 |

CLI 轮里 **31%–61% 的调用是在写一次性 Python 解析器**，**17%–68% 的调用把结构化输出 `head` 截断后重查**，还有 1–21 次直接绕过 CLI 去 `sqlite3` 查索引。这不是"CLI 慢"，这是"CLI 的输出形状不适合模型"——正好对应那份调研里的第一优先级（稳定 `--json`、大结果落盘、字段选择）。

对照结果：CLI 轮输出 token **13.2k–23.7k**，MCP 轮 **7.8k–10.3k**。差的那 6k–13k token 就是模型写的解析器代码。

## 9.2 MCP 的真实成本：工具面税

实测本仓库 `TOOL_SCHEMAS` + `TOOL_DESCRIPTIONS` 序列化后的大小：

| 工具面 | 工具数 | 序列化字符 | ≈ token |
|---|---:|---:|---:|
| `all` | 47 | 59,465 | **19.8k** |
| `quick`（默认） | 25 | 34,080 | **11.4k** |
| 一个"定位专用"窄档（下面那 10 个） | 10 | 12,662 | **4.2k** |

今晚这轮首步 `inputTokens = 20,661`，和 `quick` 档 11.4k schema + 系统提示 + 附件完全对得上。**这 11k 是每一步都存在的固定上下文**，只是后续靠 cacheRead 摊薄。

而今晚 25 个工具里**只用了 6 个**（search_bookmarks / get_context / plan_research / fetch_web / sync_package / index_status）。其余 19 个（含 6 个 `research_service_*`、4 个 `wiki_*`）纯占位。

这正是你调研里那句"连上的 MCP 即使没用，工具名和说明也会进上下文"的量化版本：**25 个工具里 19 个是 0 次调用，却要吃 8k 左右 token。**

## 9.3 成功率不是差异项

按"结果以 Error 开头 / 非零退出码"统计，两边都很干净：

| session | 结果数 | Error | 非零退出 |
|---|---:|---:|---:|
| c82b154c | 14 | 0 | 0 |
| 7ddd1600 | 29 | 1 | 0 |
| e23ac349 | 30 | 0 | 0 |
| 0e25abab | 45 | 1 | 1 |
| ea3835c3 | 38 | 2 | 2 |
| 4516e4f1 | 44 | 3 | 4 |

CLI 的最大代价不是失败率，而是失败方式是"静默截断"——`head -40` 截掉的内容不会报错，模型以为看完了。

## 9.4 重排后的判断

| 维度 | CLI 现状 | MCP 现状 | 判定 |
|---|---|---|---|
| 延迟 | 93.7–175.1s（中位 114.6） | 58.0 / 103.5s（中位 80.8） | MCP 胜，赢在步数 |
| 上下文 | 峰值 38.7k–72.3k，输出 13.2k–23.7k | 峰值 73.8k–100.1k，输出 7.8k–10.3k | 打平：CLI 峰值低、MCP 输出少 |
| 固定税 | ~1–2k（Skill 元数据） | 11.4k（quick）/ 19.8k（all） | CLI 胜 |
| 成功率 | 低但会静默截断 | 高 | MCP 略胜 |
| 失败恢复 | 模型现场重写脚本，通常 1–3 次 | 报错信息明确 | MCP 胜 |
| 安装/维护 | 一个 bin + PATH | 每宿主注册 + 版本对齐 | CLI 胜 |

**结论：CLI-first 在架构上是对的（共享核心、人机共用、零 schema 税），但"用哪个入口"不该按协议选，该按"一次调用能拿回多少可用信息"选。**

这个任务的关键特征是：**5006 个条目 + 模糊自然语言目标**。模型无法从原始 JSON 里一次二分，必须靠索引的 term 展开、倒排、卡片密度排序（实测 0.07s）。这 0.07s 的领域逻辑就是 MCP 唯一真正值钱的地方；把 `ls`/`git` 包成 MCP 才是错的——我们没这么干，但我们把 47 个工具全挂上去了，这是另一种错。

## 9.5 落地顺序（按你的优先级）

1. **先修 CLI 的 agent 形状**（第一优先级）：`search/lookup/context/traverse` 统一 `--json` + `--fields` + `--limit` + `--out FILE`（大结果落盘，stdout 只回摘要 + 路径）+ 稳定退出码。目标：消灭 `head` 截断和 61% 的内联解析器。
2. **再收 MCP 工具面**（第三优先级，但成本最低）：默认从 `quick`(25 / 11.4k) 收到 `locate` 档 10 个 / 4.2k；`research_service_*`、`wiki_write`、`update_settings` 归到 `deep`。
3. **拆 `plan_research`**：`cards+urls` 部分 0.07s 独立成 `plan_cards`；wiki/archive 走 `include_archive=false` 或另一个工具。这一步能把 23s 的异常项直接消掉。
4. **Skill 写流程不写手册**：明确"每轮 `search_bookmarks` ≤3 次、优先 `folder_id` 下钻、同义词塞进同一个 `targets` 数组"。今晚我违反的正是这条（12 次试探）。
5. **对照实验**：同一提示词跑 3 组 —— (a) MCP `quick`、(b) MCP `locate` 窄档、(c) CLI 带 `--fields/--out`。看步数与峰值上下文，别只看 wall。

**一句话：我们不该在 CLI 和 MCP 之间选，而该让 CLI 承担确定性与大结果，让 MCP 只保留"索引语义"这一小段；现在 47 个工具里，值钱的就 6 个。**

---

# 10. 通用方法：步数优先（step-first）

## 10.1 单任务实测不可外推：两种模式的方差都在 1.8 倍以上

同一提示词、同一模型、同一天：

- CLI 五轮：93.7 / 113.4 / 115.7 / 132.2 / 175.1 → **1.87 倍**离散
- MCP 两轮：58.0 / 103.5 → **1.78 倍**离散

所以「MCP 58s 赢 CLI 93s」这类单次对比是噪声，不能当结论。

## 10.2 真正解释方差的变量是步数

对 7 轮同提示词做回归：

```
wall ≈ 24.3s + 3.15s × 步数        r = 0.902,  r² = 0.813
```

| session | 模式 | 步数 | 实测 | 拟合 | 残差 |
|---|---|---:|---:|---:|---:|
| c82b154c | MCP | 9 | 58.0 | 52.7 | +5.3 |
| 7ddd1600 | MCP | 22 | 103.5 | 93.7 | +9.8 |
| e23ac349 | CLI | 27 | 93.7 | 109.5 | −15.8 |
| 0e25abab | CLI | 30 | 115.7 | 118.9 | −3.2 |
| 8ecead0f | CLI | 34 | 132.2 | 131.6 | +0.6 |
| ea3835c3 | CLI | 35 | 113.4 | 134.7 | −21.3 |
| 4516e4f1 | CLI | 40 | 175.1 | 150.5 | +24.6 |

**步数解释了 81% 的时长方差；协议在控制步数后没有系统性优势。**
（MCP 两轮残差都为正，正是 `plan_research` 那 11–23s 的重工具；CLI 残差有正有负，说明它的问题不在协议而在步数。）

结论：**优化目标不是"选 CLI 还是 MCP"，而是"降低步数"。** 协议只是实现细节。

## 10.3 步数由什么决定：单次调用的信息密度

- 一次调用能省掉的决策数 = 信息密度。
- 高密度（索引检索、拓扑、图遍历、外部抓取、wiki）→ 值得做成工具。
- 低密度（ls / cat / git / grep / jq）→ 模型已会，做成工具纯亏 schema。
- 中密度、批量、结果大 → CLI（可参数化、可 `--out` 落盘、人也能用）。

## 10.4 四条判据（替代"本地 vs MCP"）

| # | 问题 | 是 → | 否 → |
|---|---|---|---|
| 1 | 模型用 shell 能在 ≤2 步可靠完成？ | 不做工具，Skill 写提示即可 | 进 2 |
| 2 | 需要领域索引 / 语义排序 / 拓扑 / 鉴权？ | 做成"原语" | 不做工具 |
| 3 | 该原语在 ≥3 类任务里复用？ | 配 MCP 适配（自动发现） | 只留 CLI |
| 4 | 需要远程 / OAuth / 集中审计 / 非技术用户？ | MCP | CLI |

## 10.5 关键反模式：用工具数量覆盖任务种类

当前 47 个工具 ≈ 试图把"任务空间"装进 schema。任务是开放集合，工具数是线性增长，而**每个任务实际只用到其中 6 个**：

- `all` 47 个 → 19.8k token
- `quick` 25 个 → 11.4k token
- 定位类实际需要 10 个 → 4.2k token

**正确形态是"少数高密度原语 + 一个通用执行器（CLI）+ Skill 编排"**：新任务靠组合已有原语，不靠新增工具。这样任务从 5 类涨到 50 类，schema 税不变。

## 10.6 验证方案（替代单任务对比）

5 类任务 × 3 题 = 15 轮，每轮记录：步数、wall、峰值上下文、输出 token、静默失败数。

| 任务类 | 例子 | 预期形态 |
|---|---|---|
| L1 精确定位 | 按 URL / 标题精确找 | CLI 1–3 步，不该用 MCP |
| L2 模糊定位 | 本次的"3D/2D + 英文名 + note" | 原语（4–8 步） |
| L3 空间上下文 | 同卡片邻居、连线、分组 | 原语 |
| L4 时间上下文 | git 历史、新增/删除 | CLI（git）+ 原语 |
| L5 外部调研 + 沉淀 | 抓 URL → wiki | 原语 + 异步 job |

判据：某类任务中位步数 **>6** → 值得做原语；**≤3** → 别做工具；**3–6** → 先靠 Skill 教。

---

# 11. 目标工具面：从模型视角设计（8 个工具）

## 11.1 现在的工具面在我眼里长什么样（实测）

对 `7ddd1600` turn 1 的 18 次 MCP 响应做解剖：

| 项目 | 字符 | 占比 |
|---|---:|---:|
| 响应总量 | 100,961 | 100% |
| 有效负载（rows/items/cards/urls/pages） | 52,290 | 51% |
| **信封**（source / refresh / counts / query_scope / _compact / targets / pagination） | **48,671** | **48%** |

单项：`source` 10,757（11 次调用重复同一块）、`sources` 10,924（`index_status` 一次性吐出全部 4 个源）、`refresh` 6,900、`counts` 3,828、`_compact` 3,032、`query_scope` 2,418。

`index_status` 一次调用 10,548 字符、**有效负载 0**——我只是想知道"索引在不在、多少条"。

**约 16k token 是纯信封。**

## 11.2 三个结构性问题

1. **信封比内容大。** 每次返回都重述 source / refresh / 匹配模式 / 字段清单。
2. **发现入口有 6 个**：`search_bookmarks`、`search_archive`、`search_web`、`agentic_search`、`plan_research`、`wiki_search`。我每步都要先判断"该用哪个"，而用户的问题只有一个。
3. **匹配是字面的**（`match_mode: literal_substring`），模糊需求只能靠我枚举同义词——本次 12 次 `search_bookmarks` 就是这么来的。而真正会做 term 展开 + 卡片密度排序的 `plan_scope` 只要 **0.07s**，却被埋在 23s 的 `plan_research` 里。

## 11.3 我要的 8 个工具

| 工具 | 签名 | 返回 |
|---|---|---|
| `locate` | `locate(text, in=["canvas","wiki"], limit=8)` | 排序候选 `[{id,title,why,folder,note?,tags?,url}]`；空结果给 `hints` |
| `read` | `read(id, part="card", offset=0, limit=20)` | 单目标的单一部分；超长给 `handle` |
| `walk` | `walk(id, dir="out", depth=1)` | 边 + 成员 + 相邻文本节点 |
| `fetch` | `fetch(url)` | 正文 + `capture_id`（已有，保留） |
| `save` | `save(kind, payload, sources)` | wiki / note / plan 统一写入口 |
| `spawn` | `spawn(task, args)` | 长任务（deep research / 批量抓取 / 重建索引）→ `job_id` |
| `job` | `job(id?)` | 状态 + 结果摘要 + 落盘路径 |
| `health` | `health()` | 版本、条目数、monitor —— **≤200 字符** |

合计 schema 约 **3.5k token**（现在 quick 是 11.4k）。

## 11.4 三条返回硬规则

1. **信封 ≤10%。** `source`/`refresh` 只在变化时返回，否则 `{"v":"v-e5d7...","changed":false}` 一行。
2. **大结果给句柄。** 超过 ~4k 字符：返回前 K 条 + `more:{handle,offset}`，用 `read(handle, offset)` 续读。这是"落盘"在 MCP 侧的等价物。
3. **每个响应带 `next`。** 一句话下一步（沿用 `plan_research.next_action` 的模式，但不要埋在 8k blob 里）。

## 11.5 期望效果（基于本次实测）

| 项 | 现在 | 目标 | 依据 |
|---|---|---|---|
| 搜索步数 | 12 | 2–3 | 一次 `locate` 给 8 个排序候选，不用枚举同义词 |
| 总步数 | 22 | 8–10 | 少 10 步 × 3.15s ≈ 31s |
| 响应信封 | 48% | ≤10% | 省 ~34k 字符 ≈ 11k token |
| schema 税 | 11.4k | ~3.5k | 25 → 8 工具 |
| 搜索延迟 | — | 0.07s | 直接暴露 `plan_scope`，不再背 wiki/archive |

## 11.6 迁移是纯减法

`locate` ← `plan_scope`（现成，0.07s）；`read` ← `get_context` + `search_bookmarks(folder_id)`；`walk` ← `traverse_graph`；`fetch` ← 已有；`save` ← `wiki_write` 简化；`spawn`/`job` ← `research_service_*` 收编；`health` ← `index_status` 瘦身。

删掉：`merge_search_results`、`research_services`、`research_service_*`（6 个）、`update_settings`/`get_settings`（改为 CLI）、`wiki_list`、`lookup_url`（并入 `locate`）、`traverse_graph`（并入 `walk`）。

## 11.7 同一个签名给 CLI

```
br locate "3D/2D 英文名 带 note" --in canvas --limit 8 --json
br read <id> --part card --json
br walk <id> --depth 2 --json
br spawn deep-research --input q.json --json      # → job id
br job <id> --json [--out result.md]
```

同一份 core、同一份返回 schema。Skill 只写一遍流程，MCP 和 CLI 语义一致——**模型换入口不用换心智模型**。

---

# 12. 第五轮实测：MCP + 本地 bash 混合（2026-11-07 22:11，`8c781836`）

> 口径与前文一致：每个会话的 **turn 1**，`turn/start` → `turn/end`；工具耗时用 `tool/call` → 对应 `tool/result` 配对。
> 复现脚本：`.bench/session_timing.py`（`python3 .bench/session_timing.py`）。

## 12.1 总表（含第五轮）

| 时间 | session | 模式 | wall | 净 wall* | 步数 | 调用 | 工具耗时 | LLM | 每步 | 峰值 ctx | 输出 tok | 结果字符 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 11-03 15:58 | c82b154c | MCP#1 | **58.0** | 58.0 | 9 | 14 | 12.3 | 45.7 | 5.08 | 102,365 | 7,793 | 175,156 |
| 11-06 14:44 | 4516e4f1 | CLI#1 | 175.1 | 175.1 | 40 | 44 | 26.2 | 148.9 | 3.72 | 70,834 | 23,678 | 117,795 |
| 11-06 15:53 | e23ac349 | CLI#2 | 93.7 | 93.7 | 27 | 30 | 8.5 | 85.2 | 3.16 | 40,321 | 13,190 | 44,180 |
| 11-06 17:23 | 0e25abab | CLI#3 | 115.7 | 115.7 | 30 | 45 | 10.6 | 105.1 | 3.50 | 54,517 | 19,464 | 76,152 |
| 11-06 21:37 | ea3835c3 | CLI#4 | 113.4 | 113.4 | 35 | 38 | 8.8 | 104.6 | 2.99 | 50,234 | 16,308 | 62,886 |
| 11-06 21:45 | 8ecead0f | CLI+ | 132.2 | 126.0 | 34 | 35 | 10.2 | 122.0 | 3.59 | 73,152 | 16,244 | — |
| 11-06 23:29 | 7ddd1600 | MCP#2 | 103.5 | 103.5 | 22 | 29 | 33.1 | 70.4 | 3.20 | 74,806 | 10,285 | 121,750 |
| **11-07 22:11** | **8c781836** | **RUN#5 混合** | **97.0** | **92.6** | **17** | **25** | **5.8** | **91.1** | **5.36** | **111,906** | **13,293** | **205,599** |

\* 净 wall = wall − `ask_user_question` 等待（#5 为 4.35s，8ecead0f 为 6.16s）。

排名：MCP#1 58.0 ＜ **RUN#5 92.6** ＜ CLI#2 93.7 ＜ MCP#2 103.5 ＜ CLI#4 113.4 ＜ CLI#3 115.7 ＜ CLI+ 126.0 ＜ CLI#1 175.1。
**第五轮是目前第二位，比 CLI 中位（114.6s）快 22s，比上一轮 MCP（103.5s）快 11s，但比 MCP 基线（58.0s）仍慢 34.6s。**

## 12.2 这 97 秒花在哪

| 阶段 | 步 | 耗时 | 内容 |
|---|---:|---:|---|
| 环境 + 索引 | 1–2 | 3.9s | `skill`、`ls`、`index_status` |
| **检索与判断** | 3–12 | **63.8s** | 15×`search_bookmarks` + 1×`get_context`，回包合计 **168.2k 字符**（搜索）+ 17.0k（context） |
| 提问确认 | 13 | 12.6s（其中 4.35s 等人） | `ask_user_question` |
| 本地核对 | 14–16 | 9.9s | 3×`bash` 内联 python 读 section JSON，确认 id/note/邻居顺序 |
| 收尾 | 17 | 6.8s | 输出答案（953 tok） |

- 工具本身不慢：15 次搜索合计 **0.89s**（avg 59ms），`get_context` 0.16s，`index_status` 0.11s。**5.8s 的工具时间里没有一项是瓶颈。**
- 峰值上下文 **111,906**，是 8 轮里最高；输出 13,293 tok，也偏高。

## 12.3 为什么没回到 58 秒

1. **步数 9 → 17（+8）**，每步 5.08 → 5.36s，纯步数增量就约 +41s。
2. 15 次搜索里只有 1 次是"7 词合并"；其余是 **8 次 Note/Tag 元数据**（含 2 次 `count_only`、2 次文件夹元数据）、**3 次 `folder_id` 下钻**、**3 次英文名/近义词试探**。
3. **回包过大**：168k 字符搜索回包 ≈ 42k token；`search_bookmarks` 单次最大 **49,931 字符**（7 个 target 合并后 737 条命中，摘要页仍带 `source/refresh/query_scope/targets/_compact` 全套信封）。
4. 3 步本地核对是"没有 `read` 原语"的代价——为了确认 `note`/邻居顺序，只能 `python3 - <<'PY'` 解析 section JSON。

## 12.4 关键发现：这一轮跑的 MCP **不是**当前 commit 的 MCP

| 事实 | 证据 |
|---|---|
| 会话实际加载的 bundle | `~/.dsh/profiles/desktop/package.json` → `link:~/.local/share/bookmark-research/installations/dsh-04b91797433ece07/bundle` |
| bundle 版本/时间 | `0.6.2`，文件 mtime **2026-11-06 23:38** |
| bundle 有没有 `locate`/`read`/`walk` | **没有**（`grep locate bundle/src/mcp_server.py` 为空；`TOOL_SCHEMAS` 仍是 `search_bookmarks`/`get_context` 那套 20 个） |
| 仓库 HEAD | `8f08d07`（"5"）**2026-11-07 15:30**，工作区还带 `src/locate.py`、`src/mcp_server.py` 等未提交改动 |

也就是说：**第五轮用旧工具面跑的是"旧 MCP + bash"，diff 里的 `locate` 一次都没被调用**（我的工具表里根本没有它）。这解释了为什么第 5 轮要在 15 次字面检索里兜圈子——`search_bookmarks` 是 `literal_substring`，而 `locate` 带 term 展开/排序/`has_note` 过滤。

用仓库当前代码直接实测同一条问题：

```sh
BOOKMARK_RESEARCH_DATA_DIR=/tmp/brdata python3 src/cli.py locate \
  --source-id user-bookmark-canvas-package-20261101 --text "3D" --has-note --limit 5
```

| 指标 | 数值 |
|---|---|
| 冷启动 wall | **0.12s**（含 python 启动） |
| 回包大小 | **926 字节**（对比单次搜索 5k–50k） |
| 调用次数 | **1 次**就命中 `NFFA 2026.5/6th … UniFans`（`ref: b-591c-1`） |
| 命中解释 | `why.terms=["3D"]`, `why.fields=["path"]`（文件夹路径里的 `2D / 3D`），`filters.has_note=true` |

→ 用户给的三条线索（3D/2D、英文名、带 Note）在这一个调用里同时成立。**diff 已经把"15 次搜索"压成"1 次"，只是没装进正在跑的 bundle。**

## 12.5 为什么 CLI#4 在"同一提示词"下仍要 113 秒

| 项 | 数值 |
|---|---:|
| wall / 步数 / 工具耗时 | 113.4s / 35 / **8.8s** |
| 每步 LLM | **2.99s**（8 轮里最快） |
| 第一次真正 `search` 出现在 | **第 10 步** |
| 第 1–9 步在干什么 | 定位 `bundle/src/cli.py`（step 2）→ `info`/`source list`/`commands`/`status`（step 3–5）→ `sync --help`/`sync --dry-run`/`sync`（step 6–9），**一条真正的 `search` 都没有** |
| 调用构成 | 16 次内联 python（16/37≈43%）、8 次 CLI 元命令、8 次 bash 里共 18 条 `search`、4 次文件系统检查 |
| 输出 token | 16,308（MCP#1 为 7,793）——多出来的 8.5k 是现场写的解析器/引导命令 |

结论：**CLI#4 慢不是因为"每步慢"（它每步最快），而是因为它先花了 9 步把自己的运行环境装好，再在输出截断/解析上反复。** 这就是"CLI 没有 agent 形状"的账单：缺少稳定入口契约 → 模型先找 `cli.py`、再 `--help`、再 `export`、再 `sync --dry-run`。

## 12.6 更新后的模型（8 个样本）

```
wall ≈ 33.4s + 2.90s × 步数          r = 0.886,  r² = 0.784
```

| session | 步数 | 实测 | 拟合 | 残差 |
|---|---:|---:|---:|---:|
| c82b154c | 9 | 58.0 | 59.5 | −1.5 |
| 8c781836 | 17 | 97.0 | 82.8 | **+14.2** |
| 7ddd1600 | 22 | 103.5 | 97.3 | +6.2 |
| e23ac349 | 27 | 93.7 | 111.8 | −18.1 |
| 0e25abab | 30 | 115.7 | 120.5 | −4.8 |
| 8ecead0f | 34 | 132.2 | 132.1 | +0.1 |
| ea3835c3 | 35 | 113.4 | 135.0 | −21.6 |
| 4516e4f1 | 40 | 175.1 | 149.5 | +25.6 |

**步数仍解释 78% 的方差。** 第五轮的 +14.2s 残差正好对应它"回包最大"这一点（205.6k 字符，全轮最高）：**同样一步，喂进去的字符越多越贵**——这给"信封 ≤10% / 大结果给句柄"提供了第二个独立证据。

## 12.7 下一步（可验证）

1. **把 DSH 的 bundle 更新到当前工作区**（现在 profile 还链着 11-06 的 0.6.2）：`python3 scripts/launcher.py install dsh`（或 `host_install.py`），然后确认工具表里出现 `locate`/`read`/`walk`。
2. 用**同一提示词**跑第六轮，预期：8–10 步、1–2 次 `locate`、峰值上下文 < 40k、总时长 55–70s。若没达到，问题就不在协议，在返回形状。
3. **Skill 纪律**：每轮 `search_bookmarks` ≤3 次；多词一律塞进同一 `targets`；先 `folder_id` 下钻再全库扫；元数据（Note/Tag）直接用过滤器而不是全表扫。
4. **信封瘦身**：`source`/`refresh`/`query_scope`/`_compact` 只在变化时返回；单次回包 >4k 字符给 `handle`。
5. 保留 `.bench/ladder.json` 的 15 题梯子，跑 (a) legacy 25 工具、(b) quick-10 新原语、(c) CLI `--fields/--out` 三组，比较步数中位数而不是单轮 wall。

## 12.8 复现

```sh
# 8 轮总表
python3 .bench/session_timing.py
# 单轮逐步（步耗时 / 回包字符 / 工具序列）
python3 .bench/session_steps.py 8c781836    # 或 ea3835c3 / c82b154c
# 新原语实测（需可写的数据目录副本）
BOOKMARK_RESEARCH_DATA_DIR=/tmp/brdata python3 src/cli.py locate \
  --source-id user-bookmark-canvas-package-20261101 --text "3D" --has-note
```
