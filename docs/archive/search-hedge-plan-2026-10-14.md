# 搜索对冲与总期限实施计划（2026-10-14）

> 本轮只实施一件事：把 `search_web` 主提供商阶段的"等待全部"改为"对冲加总期限"。
> 不新增 MCP 工具、不新增提供商、不改 fetch 路径。其余待办见文末"后续待办"，供下次讨论后再做。

## 1. 背景与本机实测

2026-10-14 在本机安装版上的实测（单次采样，含约 60ms 进程启动，受网络条件影响）：

| 组合 | 总耗时 |
| --- | ---: |
| 仅 Exa | 6.36 s；复测 5.22 s |
| 仅 Parallel | 2.00 s |
| 两者并行 | 5.61 s |

结论：跨提供商并行已生效（5.61 秒约等于慢者而非相加），但 `web_search.search()` 等待全部主提供商，最慢的提供商决定总延迟，Parallel 2 秒得到的结果被扣住 3 秒多。参考项目 aether-search 的两通道同样"等全部"，其竞速仅用于 Grok 多端点且默认关闭；smartsearch 无竞速。文献（Google "The Tail at Scale" 的对冲请求）表明先到先得加取消输家可在约 2% 额外请求量下大幅降低尾部延迟。

在线探测（2026-10-14）：Exa 与 Parallel 的 hosted MCP 搜索工具均不暴露速度档（instant/fast/turbo 只在 REST API），因此对冲是当前 MCP 通道上唯一可用的延迟杠杆。

## 2. 本轮范围

做：

- `SearchProviders.search()` 主提供商阶段：先到先得 + 宽限窗口 + 总期限 + 放弃披露。
- 新设置 `search.grace_seconds`（默认 2，null 关闭宽限）与 `search.deadline_seconds`（默认 10，null 不设总期限）。
- 研究路径（`research_search`）显式 `hedge=False`，保持等待全部与预算语义不变。

不做（后续再议）：不新增 MCP 工具（web_map 等）、不新增提供商、不改 fetch 路径、不动 fallback 阶段。

## 3. 设计

主提供商阶段语义：

1. 全部主提供商工作线程同时启动（现状不变）。
2. 任一提供商完成后：若所有查询均已解析，最多再等 `grace_seconds`，窗口内完成的提供商结果照常并入 RRF；窗口结束仍未完成的提供商被放弃。
3. 若仍有查询未解析，继续等待其余提供商，直到全部完成或到达总期限。
4. 总期限到达时返回已到结果，未完成的提供商放弃。
5. 输出在 `routing` 增加 `hedge`（生效的 grace/deadline 值）与 `abandoned_providers`（provider 加 reason：grace_expired/deadline）。
6. fallback 阶段（仅在存在未解析查询时触发）保持等待全部，不设期限。

边界与如实声明：

- 线程无法真正取消：被放弃的请求可能继续执行到超时，并照常消耗提供商额度；其 usage 不计入本次返回（在 routing 与 retry_policy 中说明）。
- 对冲使结果集依赖时序；研究路径用 `hedge=False` 保持完整性优先。
- grace 与 deadline 接受整数或小数秒，范围 0 到 60；grace=0 表示解析完成即返回。

实现清单：

- `src/settings.py`：defaults 与校验增加两个字段。
- `src/web_search.py`：新增 `_search_batches_hedged`；`search()` 增加仅关键字参数 `hedge`（None 用设置，False 强制等待全部）；routing 输出。
- `src/research.py`（`research_search` 调用处）：加 `hedge=False`。
- `src/mcp_server.py`：SETTINGS_SCHEMA 的 search 增加两字段；`search_web` 描述补一句。
- `skills/bookmark-research/references/settings-and-archive.md`：补充两个字段说明。
- `tests/test_web_search.py`：新增对冲行为测试（宽限内合并、超窗放弃、未解析继续等待、期限放弃、null 与 hedge=False 保持等待全部）。

## 4. 验收标准

- 全量测试通过（现基线 633 项、3 跳过）加新增测试。
- 固定题集本机复测：慢提供商场景总耗时从约 5.6 s 降到约 4.0 s（grace=2）；两家都快的场景不增加延迟（宽限窗口内合并）。
- `research_search` 行为与预算语义不变；`abandoned_providers` 与 usage 口径如实。

## 5. 后续待办（防遗忘）

以下每一项都在 2026-10-14 会话中核实过事实与来源，下次讨论后按此清单逐项决定是否实施。

1. **web_map 站点地图 / tavily_crawl**。插件现有 Tavily 连接已暴露 `tavily_map` 与 `tavily_crawl`（2026-10-14 在线探测）；aether 的 web_map 就是调 Tavily `/map`（`aether-search-main/src/aether_search/fetcher.py:69`，参数 url/instructions/max_depth/max_breadth/limit）。keyless 模式不支持 map/crawl，需免费 Tavily key（1,000 credits/月，无需信用卡；map 每 10 页 1 credit，带 instructions 2 credits）。改动 = 白名单加工具 + 适配器加参数 + 工具入口。
2. **Context7 文档通道**。smartsearch 的 `providers/context7.py`：两段式（先搜库再取该库代码与文档片段），公开库免费、key 可选。接入模式同 Jina（http 传输），零 key 可先跑。
3. **交叉印证标记**。aether `verify.py` 两级核验（证据集交叉印证 + 存活探测）；插件 RRF 输出已有 `provider_count`，可提升为显式"多源命中"信号，探活做成可选。保留"印证的是链接重叠，不是内容真值"的边界。
4. **Parallel fetch 修正**。适配层现发 `full_content: true`（`src/provider_adapters.py:126`），Parallel 官方工具描述警告其显著增加体积与延迟；其 `web_fetch` 还有 `allow_live_fetch=false` 纯缓存模式未被使用。计划：默认摘录 + 显式全文 + 缓存选项。
5. **免费池与提供商加入顺序**（aether `docs/BACKENDS.md`，2026-07-27 一手核实）：Tavily 1,000/月无卡（建议第一个拿，解锁 map）> You.com $100 约 20,000 次无卡 > Parallel 5,000/月 > Linkup 4,000 一次性 > Serper 2,500（Google 透传）> Exa $10/月加注册 $20 > Firecrawl 约 1,000/月 > Brave $5/月（需绑卡）> Perplexity Sonar 无免费层。国内层候选：智谱（0.01 到 0.05 元/次；smartsearch 有 `zhipu.py` 与 `zhipu_mcp.py` 两种现成实现）、博查（REST，`api.bochaai.com/v1/web-search`，带语义重排 API）。加入方式沿用现有可选机制（`search.providers` 与 `search.fallback_providers` 选择启用，单次可用 `providers` 参数限制）；建议新提供商默认不进入默认列表（opt-in），由用户显式启用，避免升级后悄悄增加调用量与额度消耗。Grok/xAI 备注（2026-10-15）：它是答案引擎而非结果列表 API；aether 以 Grok 为主通道、smartsearch 以 `xai-responses` 为默认链首，两者都产出带引用的模型答案。若接入本插件，位置应是外部研究服务槽（opt-in，与 OpenAI/Parallel 并列），不是 `search.providers`；独有价值是 X 搜索；无免费层（Live Search 约 $0.025/来源，另加 token 费）。
6. **子代理编排开箱化**。子代理调用插件 MCP 工具已实测通过（23 次调用、约 12.6 分钟、16 万 token 完成画布查询），但有摩擦：`search_bookmarks` 与 `search_web` 的 targets 形状不一致（字符串数组 vs 对象）、多词 target 是 AND 字面匹配须拆短词、只查元数据字段（正文走 `search_archive`）。bundle 内已有 `workflows/bookmark-research.js`，待启用与验证。
7. **任务型提供商排序**。openbenchmarks（2026-09/10）：无通吃赢家。Exa fast 569ms/99.3%（事实查询）、Perplexity 77.3%（开发任务）、Parallel basic 93.3%/1.8s、Parallel turbo 333ms/64.7%。可据此做默认顺序的启发式或按任务预设。
8. **发布注意**。本机安装回执（`~/.local/share/bookmark-research/installations/claude-6e6c0896f096aa68/receipt.json`）仍为 `0.5.0-beta.10`，bundle 的 src 与仓库逐字节一致（beta11 只改安装器脚本）。本次改动完成后需重装 bundle、重启会话，并核对 receipt 版本与运行代码一致。
9. **Exa 免 Key 通道 fail-closed 复发调查**。2026-10-15 两次观测（q2 检索批次、8 URL 批量抓取）中 Exa 返回无法识别的结果形状（`unrecognized_or_not_returned`），fallback 到 Parallel 后全部成功；同日早些时候 Exa 正常。需查明是匿名配额限流还是响应形状变化，决定调整识别逻辑或默认顺序（可与第 5 项免费池排序一起做）。

## 6. 实施记录

2026-10-14 至 10-15 完成（工作树改动，尚未提交）：

- 改动文件：`src/settings.py`（defaults 与校验：`grace_seconds` 默认 2、`deadline_seconds` 默认 10，接受 null 与小数秒）、`src/web_search.py`（新增 `_search_batches_hedged`；`search()` 增加仅关键字参数 `hedge`；routing 增加 `hedge` 与 `abandoned_providers`；retry_policy 补充放弃说明）、`src/research.py`（research_search 调用加 `hedge=False`）、`src/mcp_server.py`（SETTINGS_SCHEMA 与 search_web 描述）、`skills/bookmark-research/references/settings-and-archive.md`（中英两版）、`tests/test_web_search.py`（新增 6 项对冲测试），以及 `tests/test_settings.py`、`tests/test_research.py`、`scripts/verify_fixture.py` 的假引擎签名适配。
- 测试：定向 8 个模块 150 项通过；全量 `python3 -B -m unittest discover -s tests` 639 项通过、3 项跳过、125.8 秒（基线 633 项加新增 6 项）。
- 本机联网复测（2026-10-15 凌晨，仓库新代码）：同一条查询 7.56 秒，exa 与 parallel 均完成且合并，`abandoned_providers` 为空，routing 正确输出 `hedge` 字段。本次两家都慢且完成时间接近，未触发放弃；对冲收益出现在提供商延迟分化的场景：按 2026-10-14 白天实测的分化（Parallel 2.0 秒、Exa 5.2 秒），grace=2 时应在约 4.0 秒返回并放弃 Exa，从约 5.6 秒降到约 4.0 秒；调低 grace 可换更快。
- 待激活：本会话运行的 MCP 仍是旧 bundle 代码；需按第 5 节第 8 项刷新安装并重启会话后生效。

## 7. 追加：搜索策略可选（2026-10-15）

按用户要求把"怎么搜"做成配置项，也为后续增加提供商做准备（提供商越多，策略间的额度差异越大）。新增 `search.strategy`：

| 值 | 行为 | 额度 | 延迟 |
| --- | --- | --- | --- |
| `hedged`（默认） | 全部主提供商并发，先到先得加宽限窗口 | 每家都调用 | 最快 |
| `staggered` | 先发第一家，宽限时间内未全部解析再发下一家；已解析则后面的不调用 | 未调用的省下 | 居中 |
| `sequential` | 按顺序逐家调用，只把未解析查询交给下一家 | 最省 | 等于所用到的最慢一家 |
| `wait_all` | 等全部提供商返回（改动前的行为） | 每家都调用 | 最慢 |

- 配置入口：设置文件、MCP `update_settings`、CLI `config set --search-strategy`。
- `grace_seconds` 与 `deadline_seconds` 只对 hedged 与 staggered 生效；两者均为 null 时自动等价 wait_all；研究路径固定 wait_all 不受影响。
- 输出新增 `routing.strategy` 与 `routing.not_attempted_providers`。
- 测试与文档随本轮同步更新（英文与中文设置参考、details 两版）。验证：全量 645 项通过、3 项跳过、127.7 秒；CLI `config set --search-strategy` 与非法值拒绝在临时配置上实测通过。

## 8. 研究路径实测：画布调研包完整生命周期（2026-10-15）

用仓库新代码（`python3 -B src/cli.py`，非本会话旧 bundle）在画布调研包上跑了一遍完整研究生命周期，任务 `r-748272ccc9fc4749`：source `research` 以 whole 模式冻结 207 个 URL（223 个实例），预算 6 搜索／6 抓取／3 轮，问题 q1（搜索 API 延迟与质量对比）与 q2（Exa/Parallel 模式与延迟档位）。

- 流程（全部实测通过）：start → search 第 1 轮（4 个 provider 批次，约 7 秒，http_requests 10）→ fetch 2 次操作 3 个 URL（exa 提取 12000／10769／8434 字符）→ source 全文读取 → record 两批 12 条（3 source_review、6 claim、1 inventory_review、2 answer）→ coverage → finish（incomplete）。
- 引文为已存正文的逐字子串；q1 结论：AA 搜索指数 80/75/74/73 对基线 33，Time per Task（模型+实测搜索时间）Exa auto 33.1s、Parallel basic 27.7s、Parallel advanced 42.7s，单次快不等于每任务总时间短；q2 结论：Exa 六档搜索类型（约 250ms 到 12-40s），Parallel 四模式（turbo/fast/basic/advanced，AA 口径）。
- 覆盖率：207 个冻结 URL 中 substantive review 1 个（0.48%，画布保存的 Exa 指南页，并完成 inventory_review），206 个未读；问题完成 2/2；finish 正确判为 incomplete，blocker 为“原始输入仍需实质审阅”。产物：任务目录下 `report.md`、`sources.json`、`coverage-*.json`。
- 观察：研究路径 routing 为 `strategy: wait_all`（hedge=False）符合设计，同日 search-web 对冲实测 5.17s（两家完成、无放弃）；Exa 对 q2 一次 fail-closed 格式错误，同查询复测成功（4.91s），但当日稍后一次 8 URL 批量抓取中 Exa 对 8 个 URL 全部 fail-closed（`unrecognized_or_not_returned`），fallback 到 Parallel 全部成功，已按复发问题记入第 5 节第 9 项；AA 页在冻结清单中为 zh 变体，本次抓取的 en 页由搜索发现，未计入 inventory_review。
- 激活状态不变：本会话 MCP 仍为旧 bundle；研究路径新代码经 CLI 验证端到端可用。

### 8.1 宿主与插件耗时归因（2026-10-15 实测）

44 分 29 秒的任务墙钟拆开：插件侧联网操作合计 15.2 秒（检索轮 7.0s、两次抓取 4.3s/4.0s），占 0.6%；其余 99.4% 在宿主侧（模型回合与逐步操作），最大空档是检索完成到发起抓取之间的约 13 分钟、读文拼记录之间的约 14.5 分钟。瓶颈是宿主回合数乘每回合模型延迟，不是插件网络。

对照实验（同任务 resume 后，resume 流程实测通过）：一次 `research_fetch` 调用批量抓 8 个画布 URL，插件侧 23.3 秒、宿主 1 个回合、每页约 2.9 秒（1 URL 一次 4.0s、2 URL 一次 4.3s、8 URL 一次 23.3s）；8 页全部经 fallback（Parallel）提取入库。批量把宿主回合数从 8 降到 1。

可用杠杆（按性价比）：1) 每次抓取 8 个 URL、每回合并行发多个工具调用（服务端支持 4 路并发、16 排队）；2) 子代理/工作流并行审阅（第 5 节第 6 项）；3) 控制工具输出体积，超大结果会拖慢其后每个宿主回合。

批量抓取后的覆盖率口径（同任务实测）：8 页全部入库（sources 19 条，含 8 条 Exa 失败记录），但实质指标不变（usable_text 1/207、substantive_review 1/207）：抓取只把 `missing` 从 206 降到 200，`unread`/`unreviewed` 仍为 206——审阅才是实质覆盖，完成门槛因此仍未通过。8 个 URL 中 6 个直接对上冻结清单（accounted 1→7）；两个 docs.parallel.ai 链接因清单中带 `_gl` 跟踪参数未直接匹配，审阅时按原 URL 处理。任务保持 active，新增问题 q3 待答；预算 fetch 4/6（失败的一次调用也计 1 次），余 2 次。

## 9. 插件侧强化候选清单（2026-10-15，待讨论）

背景：实测确认研究任务墙钟 99.4% 在宿主侧（§8.1）。以下为插件可自行强化、不依赖宿主的候选项，按慢宿主假设下的性价比排序；第 1、2 项已实施（见 9.1），第 4–7 项已实施（见 9.2，2026-10-15），第 3 项因免 Key MCP 通道不暴露档位而停放。

1. **读取对冲与短熔断**。读取当前是"主提供商完成或失败后再并发其余"（今日 8 URL 实测：先整段 Exa 失败阶段，后 Parallel 成功，总 23.3s）。搜索侧已有 hedged/staggered/grace/deadline，可复用到 fetch：超宽限即并行启动 fallback（staggered 省额度、hedged 最快，与搜索一致）；连续失败的提供商短时降级（熔断），避免每批先等它失败。与第 5 节第 9 项（Exa fail-closed 复发）联动。
2. **回合压缩**。抓取已支持 8 URL/调用（实测 1 回合 8 页），可将上限提到 16 并让 Skill 默认满批。`research_source` 现在一次读 1 个来源，读 8 页需 8 个宿主回合；改为一次最多 8 个来源（每页限长 + next_offset）可把读取回合压 8 倍。Skill 明示每回合并行多个工具调用（服务端 4 并发、16 排队）。
3. **档位与通道（需 Key）**。Exa REST instant/fast、Parallel turbo（第 5 节第 5/7 项）；免 Key MCP 通道不暴露档位。单次延迟 10 倍杠杆，等 Key 决策。
4. **缓存复用**。重复读取同一 URL 目前重新联网并追加快照；可加"新鲜度内直接返回已存正文"选项（source_freshness 已存在）；搜索加短 TTL 缓存，服务子代理并行场景。
5. **子代理/工作流开箱化**（第 5 节第 6 项）。慢宿主下唯一能并行上下文的路径；bundle 工作流待启用验证。
6. **并发上限可配置**。4 并发/16 排队现为保护性硬限；配置化后配合 Key 提高吞吐，默认保持保守。
7. **精简与一致性**。工具面本轮已精简，本地查询 68-107ms 非瓶颈；优先统一 targets 形状（第 5 节第 6 项）与继续限制工具输出体积。

优先级：慢宿主下先做 1、2（复用现有机制、不依赖 Key）；4、5 次之；3 等 Key；6 最后。宿主若变快，顺序变为 1、3、4 优先（网络时间重回主导），2、5 仍为低成本收益。

### 9.1 实施记录：第 1、2 项（2026-10-15，工作树改动）

- **读取策略 `fetch.strategy`**：`staggered`（默认）在当前提供商停滞超过 `fetch.grace_seconds`（默认 25）后把未解决 URL 并行交给下一家，正常完成则等同 sequential；`hedged` 全部并发先到先得；`sequential` 为改动前行为；`fetch.deadline_seconds` 默认 null。放弃发生在全部 URL 已解决或到达期限时，被放弃者记入 `abandoned_providers`，其请求可能仍在后台消耗额度；放弃不阻塞返回，单次尝试且无放弃时保持旧输出形状，有放弃时保留瀑布形状（per-URL provider 归属与披露不丢）。
- **短熔断**：提供商连续两次整批无可用正文（读取 `unrecognized_or_not_returned`、搜索 result_format）即冷却 300 秒，期间快速跳过并记 `provider_stalled` 与 `skipped_due_to_cooldown`；任何可用结果清零计数；进程内生效。与第 5 节第 9 项（Exa 免 Key 复发）联动：复发时后续批次不再等它失败。
- **回合压缩**：抓取批量上限 8→16（`web_search.fetch`、`research.FETCH_BATCH_SIZE`、`fetch_web`/`research_fetch`/`wiki_refresh` schema、`read_capture`）；`research_source` 支持 `source_ids`（一次最多 8 个，CLI `--source-id` 可重复）；默认抓取预算公式改为 `min(80,max(12,ceil(URL数/16)+12))`（207 URL → 下限 13、默认 25）。
- **入口**：设置文件、MCP `update_settings`（SETTINGS_SCHEMA 同步）、CLI `config set --fetch-strategy`（非法值拒绝）。
- **验证**：全量 650 项通过、3 项跳过（新增：staggered 停滞重叠、hedged 先到先得与放弃披露、短熔断、批量读来源、fetch 策略默认与校验；同步更新：抓取边界 16、预算公式 13/25、wiki refresh 上限 17、641→1281 输入）。CLI 冒烟（真实网络）：批量读来源一次返回 2 个（count=2）、`config set --fetch-strategy hedged` 生效、`fetch-web` 两个 URL 3.9s 单提供商形状正常。
- **未实施**：第 3 项（等 Key）、第 4–7 项（已于同日实施，见 9.2）。激活仍待第 5 节第 8 项（重装 bundle + 重启会话）。

### 9.2 实施记录：第 4–7 项（2026-10-15，工作树改动）

- **第 4 项 缓存复用（两层，默认都关闭）**：
  - 搜索缓存 `search.cache_seconds`（0–3600，默认 0）：进程内按（提供商，查询，限额）缓存短时结果；命中批次标记 `cached:true`、保留原 `retrieved_at`、`usage` 记零、不调用提供商。研究预算诚实扣减：主阶段与 fallback 阶段都先问 `SearchProviders.cached_search_pairs()`（只统计距到期 5 秒以上的条目，避免预留后缓存过期导致超预算执行），命中项不占 `search_calls`。缓存只在 MCP 长驻进程内有效；CLI 每次命令是新进程，天然没有跨命令搜索缓存。
  - 读取复用 `fetch.reuse_seconds`（0–86400，默认 0；`research_fetch` 可用同名参数覆盖）：窗口内已有 extracted 正文的 URL 直接返回 `reused_sources`（原 `sN`、原检索时间，追加 `reused:true`，不追加新快照、不写新证据文件、不占 `fetch_calls`）；全部复用时 `attempts` 为空、`per_url` 标 `provider:"reused"`、`status:"ok"`，预算已耗尽也能执行。复用基于任务持久状态，跨进程有效。`reuse_seconds=0` 不写入 operation parameters，旧回执重放参数不变。
  - **被否决的做法（记录理由）**：不把 Parallel `full_content` 默认改为摘录——摘录是面向 objective 的 LLM 过滤文本，会破坏"引文必须是已存正文的逐字子串"的证据链；不启用 `allow_live_fetch=false` 纯缓存模式——静默返回陈旧正文与 `source_freshness` 的实时对比语义冲突。
- **第 5 项 子代理/工作流提示同步**：`hosts/shared/research-flow.js` 与 `hosts/codex/delegate.md` 的每批 8 → 16，并加"传 `reuse_seconds`（如 3600）让先前读者已保存的 URL 直接复用"；`docs/prompt-reference.md`／`.en.md` 同步。工作流生效仍待第 5 节第 8 项（重装 bundle + 重启会话），生效后建议用一次有界工作流验证。
- **第 6 项 并发上限可配置**：新 `server` 设置节 `network_workers`（1–16，默认 4）与 `max_pending_calls`（1–64，默认 16，且不得小于 workers）；`serve()` 新增 `workers`／`max_pending` 显式参数，CLI `serve` 启动时读取（配置不可读则回退默认并在 stderr 提示）；CLI `config set --server-workers/--server-max-pending`，MCP `update_settings` 同步；重启后生效，默认值保持保守。
- **第 7 项 精简与一致性**：`search_web` 的 `targets` 现在接受纯字符串（schema `type:["string","object"]`，等价 `{target:s, query:s}`），与 `search_bookmarks` 的字符串 targets 不再割裂；`cli.md`、`research-workflow.md`（中英）与工具描述同步；多词 AND 字面匹配与"正文走 `search_archive`"维持既有文档说明；输出体积由 16 URL／8 来源批上限与分页承担。
- **验证（2026-10-15）**：全量 659 项通过、3 项跳过、135.2 秒（9.1 基线 650 加新增 9 项：搜索缓存命中与默认关闭、`cached_search_pairs`、字符串 targets、设置校验、读取复用单条/混合/预算、显式 serve 并发参数）。实测（仓库代码、真实网络）：同一查询两次 5.53s→0.01s，第二次 `cached:[true,true]`、`tool_calls=0`、结果 5+5 条、`retrieved_at` 保留、预算扣减计数 2；`research_fetch` 第二次 `reused_sources=[s1]`（原检索时间）、`usage` 全零、`attempts=[]`、`per_url.provider="reused"`；新配置项写入与非法组合拒绝（`server.max_pending_calls must be at least server.network_workers`）实测通过。
- **未实施**：第 3 项（免 Key MCP 通道不暴露档位，需 REST + Key；用户确认不等待）。激活仍待第 5 节第 8 项（重装 bundle + 重启会话）。

### 9.3 修正（2026-10-16）：熔断读取状态与 fail-closed 归因

§9.1 的短熔断在抓取侧原读取 `unrecognized_or_not_returned`。该状态已拆分（`no_content_returned` / `content_present_unparsed`，另见 `plugin-improvement-plan-2026-10-15.md` §3）：8 URL 批次"全部 fail-closed"经归档原文复现为本地解析拒收（第 2 页围栏未闭合，遮罩盖住后续真实页头），非提供商问题；熔断改为只对 `no_content_returned` 计数，本地解析缺口不再消耗提供商熔断预算。搜索侧 `result_format` 失败批次现于回执保留 `unparsed_excerpt`（≤400 字符）。
