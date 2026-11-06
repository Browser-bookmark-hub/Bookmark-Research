# 全能力延迟基线（不是只 optimize locate）

> 数据集：`书签画布` 5006 条目，索引 63 MB。DB 副本 `.bench/run7-data/index.sqlite3`（不碰线上库）。
> 机器：同一台 Mac；时间：2026-11-08 10:35–10:45。
> 复现：`python3 .bench/cap_bench.py`（本地能力），`.bench/session_timing.py`（模型侧）。

## 0. 结论：时间不在工具里

对本次会话 21 步做最小二乘拟合（R² = **0.991**）：

```
单步耗时 = 0.74s + 6.7ms × 输出token + 0.01ms × 输入token
```

| 项 | 本次总量 | 折算时间 | 占比 |
|---|---:|---:|---:|
| 输出 token | 13,497 | **90.4s** | **85%** |
| 每步固定开销 | 21 步 | 15.6s | 15% |
| 输入 token | 53,232 | 0.6s | 0.6% |
| 工具执行（全部 32 次） | — | 7.0s | 6.5% |

**输入 token 几乎免费（10 µs/tok），输出 token 6.7 ms/tok。**
所以"每项能力变快"的通用公式只有三条：

1. **少写**（输出 token）→ 每次省 6.7ms/tok，是唯一能按秒计的杠杆；
2. **少步**（每步 0.74s 固定 + 该步输出）；
3. 工具本身：除 `plan_research` 外全部 < 35ms，**已经不是瓶颈**。

## 1. 每项能力的实测单次成本

| 能力 | 单次耗时 | 回包 | ≈ token | 备注 |
|---|---:|---:|---:|---|
| `lookup-url` | **0.08 ms** | 1.0 KB | 0.3k | 无优化空间 |
| `traverse` (depth 2) | 2.1 ms | 6.0 KB | 1.7k | |
| 打开索引（只读） | 1.8 ms | – | – | |
| 打开索引（读写 + DDL） | 2.4 ms | – | – | DDL 每次仅 0.6ms |
| `refresh`（live 包，无变更） | 1.7 ms | – | – | 已很快 |
| `read/context`（1 item） | 6.5 ms | 9.8 KB | 2.7k | 回包偏胖 |
| `search`（1 target, 10 hits） | 8.2 ms | **36.6 KB** | **10.2k** | **最胖的常规能力** |
| `search`（3 targets） | 29.1 ms | 58.1 KB | 16.1k | 约 3.5× 单 target |
| `wiki search` | 9.3 ms | 0.4 KB | 0.1k | |
| `locate`（text） | **34.7 ms** | 7.3 KB | 2.0k | 本地最慢（term 展开+FTS+密度排序） |
| `locate`（text+has_note） | 29.6 ms | 1.4 KB | 0.4k | |
| `archive search` | init 14 ms | — | — | ❌ **直接崩溃：readonly** |
| `plan_research` | **11–23 s** | 7–9 KB | 2.5k | 唯一秒级重工具 |
| CLI 冷启动（全命令固定税） | **70–100 ms** | – | – | 其中 `import cli` 38ms |

结论：本地能力全在 **0.1–35 ms / 0.1–10k token** 区间；`search` 的回包是 `locate` 的 5 倍、10k token 一次，这是最该瘦的常规能力。

## 2. 真正的系统性问题：只读路径没统一

| 模块 | 打开方式 | 只读场景 |
|---|---|---|
| `bookmark_index.py` | `mode=ro` / rw 双模（新 diff） | ✅ |
| `raw_library.py` | `connect(path)` 恒定读写 | ❌ `archive search` 报 readonly |
| `wiki_search.py` | `connect(path)` 恒定读写 | ❌ 只读盘/沙箱下失败 |
| `source_versions.py` | `connect(path)` 恒定读写 | ❌ history 同上 |

实测：`RawLibrary(settings).search("3D")` → `attempt to write a readonly database`。
这不是 locate 专属——**archive / wiki / history / research 的读路径都踩同一个坑**，而且每次都跑建表 DDL。

## 3. 按能力的优化处方（每项都能算账）

| 能力 | 现状 | 处方 | 预期 |
|---|---|---|---|
| `search` | 10.2k tok/次 | 默认 `compact` + 只回 title/url/path/note/tags + `limit 10` | 10.2k → ~2k tok |
| `locate` | 34.7ms / 2k tok | 保留；但首跳就要给 `folder_id` 下钻 + 唯一子项 | 8 次 → 1–2 次 |
| `read/context` | 2.7k tok | `fields` 投影 + 默认不带 ancestors 全文 | 2.7k → 0.8k |
| `traverse` | 6 KB | 只回 `nodes`+`paths`，去掉 memberships 回显 | −40% |
| `archive search` | 崩溃 | 走统一只读打开 | 0.1→0.2s，可用 |
| `wiki search` | 9.3ms | 统一只读打开 | 同左 |
| `plan_research` | 23s | 结果缓存 60s + 默认 `include_archive/wiki=false` + 分段计时 | 23s → 1s |
| `fetch/search web` | 网络 RTT | 并发扇出（已有）+ 超时 8s + 命中缓存 | 受 provider 限制 |
| CLI 全部 | 70–100ms/次 | `serve` 常驻 + 复用连接 | 100ms → 5ms |
| 模型回答 | 13.5k tok | 回答协议：结论 ≤3 行 + 表格 ≤8 行 + 不列路径全文 | 13.5k → 3.5k (−67s) |

## 4. 跨能力的四个"通用改法"（按性价比）

1. **统一只读存储层**：`storage.open_db(path, readonly=...)` 被 4 个 store 共用；读路径一律 `mode=ro`，失败再回落读写。→ archive/wiki/history 立刻可用，且沙箱/只读盘不再崩。
2. **回答协议（最强的一刀）**：每次工具回包内嵌 `answer_hint`（一句话结论 + 3 条证据 ref），skill 规定"直接引用 answer_hint，禁止重排全表"。→ 输出 token 直接砍 60–70%。
3. **批量参数**：`locate(texts[])` / `read(refs[])` / `traverse(items[])` / `search(targets[])`（已有）。→ 步数 −50%。
4. **重工具降级默认值**：`plan_research` 默认不含 archive/wiki + 60s 缓存；`search` 默认 compact。

## 5. 目标值

| 能力 | 现在 | 目标 |
|---|---:|---:|
| `search` 单次 | 8.2ms / 10.2k tok | 8.2ms / 2k tok |
| `locate` 单次 | 34.7ms / 2k tok | 34.7ms / 0.6k tok（text+note） |
| `read` 单次 | 6.5ms / 2.7k tok | 6.5ms / 0.8k tok |
| `archive search` | 崩溃 | 15ms |
| `plan_research` | 11–23s | ≤1s（命中）/ ≤3s（冷） |
| 一轮定位任务 | 21 步 / 113.9s | ≤12 步 / 55–65s |
| 一轮定位任务（严格遵守纪律） | — | 5 步 / 20–25s |

## 6. 只读路径修复状态（2026-11-08）

### 6.1 当前 DIFF 里已经有的

| 层 | 改动 | 状态 |
|---|---|---|
| `BookmarkIndex` | `readonly=` 参数；`mode=ro` 优先 + 写失败回落 | ✅ 已含 |
| `SourceManager` | `index.readonly` 时跳过 SCHEMA / 恢复扫描 | ✅ 已含 |
| `cli.py` | `status/history/lookup-url/locate/search/context/traverse` 按命令选 readonly | ✅ 已含 |
| `locate` | 无 text + `--folder-id` 时列直接子项（`folder_children`） | ✅ 已含 |

### 6.2 本次补齐的（同一类坑，其他 store 没跟上）

| 文件 | 改动 |
|---|---|
| `src/storage.py`（新增） | 统一只读打开策略：`connect(readonly=True)`、`is_readonly_failure()`、`mark_query_only()`；WAL 无 `-shm` 时回落 `mode=ro&immutable=1`，并强制 eager open（否则错误会拖到第一次查询才暴露） |
| `src/raw_library.py` | `_connect(readonly=)`；`_open_for_search()` 写失败降级；降级时跳过 `_refresh`（不再重扫 archive），结果标 `index_refresh: skipped_read_only` |
| `src/wiki_search.py` | `connection(readonly=)` 降级；`_sync()` 在 query-only 连接上直接返回 `[]`（不再尝试重建索引） |
| `src/source_versions.py` | `_connect(readonly=)`；`inspect()` 只读降级 |
| `src/bookmark_index.py` | 判定/打开委托给 `storage`，只保留一份 hint 列表 |
| `src/cli.py` | 索引已降级为只读时跳过 `sources.refresh()`，回 `refresh.state = "skipped"`（原先 context/traverse 仍会写，报 readonly） |

### 6.3 验证矩阵（真·只读文件系统 / 宿主 sandbox）

| 场景 | 修复前 | 修复后 |
|---|---|---|
| `search-archive 3D`（线上库，sandbox 不可写） | `attempt to write a readonly database` | rc=0，38 命中，`index_refresh=skipped_read_only` |
| `cli context --item …` | `readonly bookmark index` | rc=0，`refresh.state=skipped` |
| `cli traverse --item …` | `readonly bookmark index` | rc=0 |
| `cli lookup-url` / `status` / `locate` / `search` | 可用 | 可用（未回归） |
| `RawLibrary.search` on chmod 444 + 555 dir | PermissionError | 命中，且**不产生 `-wal/-shm`** |
| `WikiSearchIndex.candidates` on ro index | 写失败 | 返回已有结果 |
| `SourceVersions.inspect` on ro index | 写失败 | 返回 `available: true` |
| 单测 | 898 | **903**（+5 只读回归），1 个环境性 error（sandbox 禁止写 `~/.local/share`，可写目录下通过） |

### 6.4 还没做的（下一刀）

1. `plan_research` 23s → 缓存 60s + 默认跳过 archive/wiki + 分段计时。
2. `answer_hint` 回包字段 + SKILL 回答协议（输出 token 13.5k → 3.5k）。
3. 批量参数 `locate(texts[])` / `read(refs[])` / `traverse(items[])`。
4. 已安装的 host bundle 仍是 10:03 版本：需要 `python3 scripts/launcher.py update dsh` 才会用上本次修复。
