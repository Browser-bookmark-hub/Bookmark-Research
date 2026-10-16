# 插件后续改进计划（2026-10-15）

> 依据：2026-10-15 的 LLM Wiki 调研任务（`r-eb7778ec8c954b9a`，已完成，报告与证据在该任务目录）＋当日实测（Exa 免 Key 通道两次 fail-closed、wiki lint 对 4 个存量页面报出 3 个时效复核类警告（口径见 §0）、wiki work 显示该调研任务 16 条 claim 待编译）。
> 调研结论三条：形态流行（代理记忆基础设施与 LLM 编译个人 wiki 两支）；主流失败模式是维护衰减、时效失真、评测混杂与厂商数字不可比；来源级问责与"把维护移入系统"被同行评审（SciTrue）与行业观察支持。
> 已完成项见 `search-hedge-plan-2026-10-14.md` §9.1（读取对冲与回合压缩）与 §9.2（缓存复用、并发配置、targets 一致性、宿主提示同步）；本文件只列未完成项与新增项，按优先级逐个讨论后执行。

## 0. 当前基线（2026-10-15 收尾）

- 代码：第 1、2、4–7 项已实现并验证（全量 659 项通过、3 项跳过）；第 3 项（档位与通道）停放，需 REST + Key，免 Key MCP 通道不暴露档位。
- 提交：本轮全部改动已入库，含本目录的 `search-hedge-plan-2026-10-14.md`。
- 激活：本机安装 bundle 仍为旧版；需重装 bundle、重启会话后新功能生效，并核对 receipt 版本与运行代码一致。
- Wiki 体系：4 个存量页面（`rag-search-and-mcp-20260912` rev2、`rag-evaluation-and-wiki-20260912`、`personal-knowledge-evidence-and-wiki-20261009`、`code-retrieval-evidence-20261009`）；lint 状态 ok，其中 3 条复核类警告（`newer_source_snapshot`×1、`source_input_changed`×2；lint 同时报出 16 条 `source_capture_expired`、2 条 `linked_page_needs_review`、1 条 `link_has_newer_revision`，均不阻塞）；本调研任务 16 条 eligible claim 待编译。

## 1. 收尾与发布（P0）

1.1 重装 bundle 并重启会话；核对运行代码为新版（工具 schema 应出现 `reuse_seconds`、`cache_seconds` 与 `server` 节）。
1.2 会话内冒烟：`research_fetch` 带 `reuse_seconds` 复用已存正文；`search.cache_seconds` 生效；`config set --server-workers` 重启后生效。
1.3 发版 0.5.0-beta.12（安装器已支持无缝覆盖升级）。
1.4 激活后第一次真实使用：编译本调研任务的 16 条 claim 成 1–2 个 Wiki 页面，并处理现存 3 条复核类 lint 警告（与 2.1 联动；lint 另报的 16 条 capture 过期与 3 条页间链接类不阻塞）。

## 2. 时效治理闭环（P1，调研报告直指）

背景：调研结论指出主流知识库的头号死因是维护衰减与时效失真（94% 内容月内未动；检索不辨时效）。本插件差异化恰在此处，但闭环只做了一半：lint 能发现"被引 URL 有新快照 / 输入变化"，复核仍是粗粒度，只说来源和页面，不说哪几条 claim 受影响、引文是否仍然成立。

2.1 **引文级复核辅助**（只读）。wiki lint 与 wiki refresh 输出扩展：对每条受影响 claim 列出 claim id，并检查其引文在新快照中的逐字存在性（仍在 / 已变 / 消失）＋变更摘录。积木：`search_archive` 逐字检索与 source_versions 快照。边界：只回答"引文是否仍逐字存在"，不做语义等价判断，修订仍走人工审阅。
2.2 **批量刷新**。`wiki refresh` 现在一次一页（每页最多 16 个被引 URL）；增加"所有过期页面"批量入口，配合 cron 或 watch 例行化，把维护真正移入系统。
2.3 （小）纯问题型任务的覆盖率表格补 claims 计数与来源审阅计数，替代 0/0 n/a（本次调研实测）。
验收：对现存 3 条复核类警告输出引文级差异报告；批量刷新覆盖 2 页以上。

## 3. Exa fail-closed：已归因并完成抓取侧修复（P2 → 2026-10-16）

背景（2026-10-16 补证）：2026-10-15 的 8 URL 批量抓取"全部 `unrecognized_or_not_returned`"经归档原文复现，**不是限流**。该响应（`r-748272ccc9fc4749` 证据目录 `20261015T032831001944Z-a124bc85cbb5/response.json`，已固化为测试 fixture `tests/fixtures/exa-fetch-8url-fence-desync-20261015.json`）含全部 8 页正文（63,410 字符）、无 error 信封、无 Error fetching 页脚；失败原因是本地解析器拒收：第 2 页 markdown 围栏未闭合，遮罩把第 4、5 页真实页头盖住（偏移 32510–37279），8 条记录只识别 5 条后整批放弃，瀑布流转 Parallel 全部成功。全库 102 份 capture 中 7 份同签名（4 份围栏未闭合、3 份页头被遮罩），另有 20 份含真实提供商错误页（如 `CRAWL_HTTP_403`），"真错误"走的是另一通道。搜索侧"6 批全失败"回执为 2 批 `result_format` + 4 批熔断跳过 + 1 批传输瞬断；当日原始响应未留存，限流与形状变化无法事后判定（同查询 2026-10-16 实测 5/5 正常，原始响应为单文本块 `Title:/URL:` 记录格式）。

3.1 抓取侧修复（已完成）：`_boundary_text` 不再对未闭合围栏整批放弃；保守规则细化为安全阀——被遮罩页头的 URL 集合恰好等于缺失的请求 URL 集合（无重复、各出现一次）时按记录恢复，否则整批保持 raw；新增状态拆分 `no_content_returned`（真无正文）与 `content_present_unparsed`（有正文、记录级解析失败），熔断只对前者计数，本地解析缺口不再消耗提供商熔断预算。残余风险：被遮罩示例恰好逐一引用缺失 URL 时会被误收；条件已收紧到精确集合相等，且原始响应始终归档可复核。
3.2 搜索侧保留未识别原始响应（已完成）：`result_format` 失败的批次在回执中携带 `unparsed_excerpt`（≤400 字符、空白折叠）；"限流形状映射 + 一次失败即冷却"（原 3.2）待拿到真实样本再定，冷却逻辑暂不动。
3.3 （可选，未做）提供商健康跨进程持久化：冷却状态写入数据目录，CLI 单次进程也能先跳过坏提供商；可与 §5-7 任务型排序合并。
验收：fixture 8/8 恢复（已达成）；下一次真实 fail-closed 事件在回执中可读到原始响应开头（机制已就位，待实测）。

## 4. Wiki 编译辅助（P3）

4.1 `wiki work` 增加只读草稿大纲：按 question 或 topic 分组 eligible claims（附引文首句），供宿主作者快速成页；不落盘、不改审阅门槛。
验收：对 `r-eb7778ec8c954b9a` 输出 2–3 个页面大纲。

## 5. 扩展项（按需，多数需 Key，沿用 §5 清单）

- web_map 与 tavily_crawl（需免费 Tavily key）、Context7 文档通道（零 key 可跑）、免费池加入顺序（§5-1/2/5）。
- 交叉印证标记（§5-3）：provider_count 提升为显式多源命中信号；边界不变，印证的是链接重叠，不是内容真值。
- 档位与通道（第 3 项）：Exa REST instant/fast、Parallel turbo；需 Key。
- 维持否决：Parallel 摘录默认与 allow_live_fetch 纯缓存模式（理由见 §9.2）；定位不扩到向量库、知识图谱、多模态产出（调研结论：属范围取舍，非缺口）。

## 6. 风险与边界

- 新功能默认关闭或只读（沿用 §9.2 风格：`cache_seconds` 与 `reuse_seconds` 默认 0）；replay 与预算语义不得回退。
- 引文级检查与草稿大纲都不替用户做语义判断；审阅门槛与不可变修订保持。
- 每次发版前跑全量测试与真实网络冒烟；激活后核对 receipt 与运行代码。

## 7. 实施记录（2026-10-16）

- **抓取侧修复**（`src/archive.py`）：`_boundary_text` 不再对未闭合围栏整批放弃（遮罩只影响边界识别，正文仍按原始文本切片）；`_text_rows` 保守规则细化为安全阀——被遮罩页头的 URL 集合恰好等于缺失的请求 URL 集合（无重复、各一次）时按记录恢复，否则整批保持 raw；`_select` 增加 `empty_status` 参数，新增 `_carries_content`/`_empty_status`；`save`/`compact_fetch` 传递空状态。`compact_fetch` 同时收紧背书检查：归档存在时只服务与 manifest sha256 一致的正文（manifest 未记录的正文一律拒绝），旧解析器写的 capture 不会经新解析器"复活"——该收紧由全量测试暴露（`test_legacy_mixed_source_capture_is_rejected_on_read_citation_and_existing_archive_search`）。
- **熔断与状态**（`src/web_search.py`）：`_fetch_coverage` 传递空状态；抓取熔断只对 `no_content_returned` 计数，`content_present_unparsed` 不再消耗提供商熔断预算；waterfall quality 排除表扩展两个新状态。
- **搜索侧留存**（`src/web_search.py`）：`result_format` 失败批次在回执中携带 `unparsed_excerpt`（≤400 字符、空白折叠）；搜索冷却逻辑未动（待真实样本再定）。
- **测试**：新增 fixture `tests/fixtures/exa-fetch-8url-fence-desync-20261015.json`（2026-10-15 真实归档响应，63,410 字符）；新增/改写 8 项：fixture 8/8 恢复（archive 与 coverage 两层）、未闭合围栏恢复缺失请求页、隐藏未请求页保持 raw、空信封/未解析区分、未解析内容不触发熔断、搜索回执 excerpt、截断围栏恢复且不串页、截断围栏隐藏未请求页保持 raw。全量 666 项通过、3 项跳过、128.5 秒。
- **冒烟（真实网络）**：`fetch-web https://example.com` 正常（archive saved）；同查询 `search-web` 5/5 URL 正常。
- **文档修正**：§0/§1.4/§2 的"3 个警告"改为"3 条复核类警告"并列明 lint 其余计数；`search-hedge-plan-2026-10-14.md` 追加 §9.3 修正记录。
- **状态**：改动在工作树，未提交；§3 仅剩 3.3（跨进程健康持久化）可选未做。
