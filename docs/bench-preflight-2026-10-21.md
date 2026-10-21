# Preflight 规模压测（2026-10-21）

> 对象：`plan_research` 预检、`RawLibrary.search_terms`、`WikiSearchIndex`。
>
> 方式：源码内进程内调用，不发网络请求；不写用户数据目录。脚本：[scripts/bench_preflight.py](../scripts/bench_preflight.py)。
>
> 环境：macOS 15.7.2、Python 3.9.6、源码基线 `e7706e1` + 当前工作树改动。

## 测什么

| 层 | 数据 | 说明 |
|---|---|---|
| 书签预检 | 1k / 5k / 10k / 50k / 100k 书签，38 个栏目 | `ResearchPlan.build(include_wiki=False, include_archive=False)`，测 `plan_scope` 主体 |
| 归档检索 | 100 / 500 个 capture 页面 | `SourceArchive.save` + `RawLibrary.search_terms` |
| Wiki 索引 | 100 / 1,000 个合成文档 | `WikiSearchIndex.candidates` + `match`；不含 revision 校验 |

查询：

- `alpha`：泛词，几乎所有卡片命中；
- `alpha beta`：两个泛词，最重的排序路径；
- `unique500` / `unique2500` / …：只命中一条书签的长字面词。

每个场景先 warm-up 一次，再取 3 次；表中为 p50 / p95 毫秒。

## 结果

### 书签预检

| 书签数 | `alpha` p50 / p95 | `alpha beta` p50 / p95 | 唯一长词 p50 / p95 | 输出字符 |
|---:|---:|---:|---:|---:|
| 1,000 | 10.3 / 10.6 | 11.8 / 11.8 | 8.0 / 8.4 | 1.8–4.1k |
| 5,000 | 23.8 / 24.3 | 27.4 / 28.6 | 13.1 / 13.5 | 1.8–4.1k |
| 10,000 | 41.4 / 44.4 | 51.3 / 52.2 | 17.6 / 18.0 | 1.9–4.1k |
| 50,000 | 197.7 / 200.6 | 255.5 / 257.6 | 65.8 / 67.2 | 1.9–4.1k |
| 100,000 | 388.5 / 391.5 | 507.5 / 509.1 | 123.1 / 123.5 | 1.9–4.1k |

结论：近似线性，约 **0.4 秒/10 万书签（单泛词）**、**0.5 秒/10 万（双泛词）**；唯一长词约 **0.12 秒/10 万**。输出稳定在 4.1k 字符左右，远低于 8k 上限。

100k 进程峰值 RSS 约 **330 MB**（含 Python、SQLite、临时包和索引生成）。

### 归档检索

| 页面数 | `alpha` p50 / p95 | `alpha beta` p50 / p95 |
|---:|---:|---:|
| 100 | 2.8 / 3.2 | 4.5 / 5.3 |
| 500 | 5.3 / 9.5 | 9.5 / 10.0 |

结论：500 页归档仍在 10ms 量级；当前按词逐个 `search`，每次刷新 archive 索引是主要成本，但规模不大时不是瓶颈。

### Wiki 索引

| 文档数 | `alpha beta` p50 / p95 |
|---:|---:|
| 100 | 2.0 / 2.2 |
| 1,000 | 19.6 / 19.7 |

结论：索引层 1,000 页约 20ms；真实 Wiki 还包含 revision/证据校验，未在此表内。

## 判断

- **当前最慢的是书签预检的全表 OR 查询**，不是 Wiki/归档。10 万书签仍低于 1 秒，可以接受；如果目标是 100 万书签，按线性外推约 4–5 秒，才需要做倒排/分批。
- **输出预算没有随数据增长**：卡片/URL 上限固定，100k 时输出仍约 4.1k 字符，`preflight_budget` 没有触发截断。
- **唯一长词**依赖新增的 token-aware 标题命中；这条路径比泛词快，但 100k 仍需约 0.12 秒，因为要扫标题。
- 归档 500 页、Wiki 索引 1,000 页都不是当前瓶颈。

## 复现

```sh
# 默认矩阵（1k/5k/10k/50k，100/500 归档，100/1000 Wiki）
python3 scripts/bench_preflight.py

# 更大书签量、只看书签
python3 scripts/bench_preflight.py \
  --sizes 100000 --sections 38 --archive-pages 0 --wiki-documents 0 --repeats 3

# JSON 输出
python3 scripts/bench_preflight.py --json
```

## 边界

- 合成数据是“每张卡都有大量 alpha/beta”的偏重场景，不代表真实主题分布；真实包的时间应更低。
- 没有经过 MCP stdio 传输、宿主调度或 `plan_research` 的 Wiki/归档完整校验；这些是单独的集成层。
- 归档 benchmark 用同一模板但唯一页面正文，避免被 SHA-256 合并；真实归档的正文大小差异会影响 I/O。
- 没有测 100 万书签；需要时用同一脚本加 `--sizes 1000000`，但要预留内存和时间。
