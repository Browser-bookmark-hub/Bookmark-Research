# Bookmark Research 0.2.0 的研究依据与取舍

研究日期：2026-09-10（Asia/Shanghai）。本报告为升级提供可追溯的资料依据，重点是 MCP 聚合、三层搜索、研究证据与安装结构。运行时实现及测试结果应同时查看发布说明和测试报告；本报告不把阅读文档当作运行过上游产品。

历史来源表见 [v0.2.0 仓库快照](https://github.com/Browser-bookmark-hub/Bookmark-Research/blob/v0.2.0/docs/research-sources-0.2.0.json)。其中 `R001`–`R207` 对应用户调研包的每个原始去重 URL，`S001`–`S018` 是沿研究线索补读的一手资料。来源表保存读取时间、失败状态、正文位置、哈希、相关性、采取或不采取的理由，以及原书签实例的定位 ID。新版 ZIP 保留本方法说明，不再附带这份实例清单。

## 1. 原包实际包含什么

通过已安装插件的 `sync`、`context` 和原 JSON/.canvas 交叉核对，调研包有 **223 个书签实例、207 个不同的原始 URL、22 个文件夹、4 张临时栏目卡片**。四张卡片分别包含 35、91、78、19 个书签，全部位于同一个卡片组内。画布有 4 个成员关系、0 条连线、0 张文本卡；四个 `descriptionMd` 均为空，所有 item 都没有非空 note 或 tags。

因此，这个包的研究上下文来自文件夹和栏目位置。不能凭卡片排列推断依赖关系，也不能把重复 URL 当成独立事实来源。223 与 207 的差额是重复书签实例，不是解析丢失。本次只读原包，最终逐文件 SHA-256 与读取前一致。

历史公开来源表把原文件夹概括为 RAG、网页提取、评测、搜索提供商、深度研究、CLI、插件宿主、浏览器能力、ACP 等主题。它保留 `section_id + item_id`，不复制私人标题、账户路径或私人笔记。**所有原始 URL 和原上下文**仍完整保存在本机研究档案的 `input-inventory.json`；公开行用 `original_url_sha256` 与它一一对应。

## 2. 实际读取覆盖

| 范围 | 数量 | 本次结果 |
| --- | ---: | --- |
| 公开且与任务相关的 URL | 161 | 使用 Exa `web_fetch_exa`，分 21 批实际请求 |
| Exa 返回页面摘录 | 141 | 这是“有摘录”，不是“141 页事实已核验” |
| Exa 逐 URL 错误 | 20 | 保留原错误；其中 7 项随后从作者的 GitHub raw/API 补读成功 |
| 经补读仍不可用的公开 URL | 13 | 明确列为 unavailable，没有补造正文 |
| 私人会话、账户后台、编辑入口、个人云文件 | 12 | 本地识别，未传给公网抓取服务；公开地址已脱敏 |
| 搜索查询入口 | 23 | 解析 query 作为发现线索，不当成事实来源 |
| 搜索分隔占位链接 | 6 | 本地识别为分隔字符，不联网读取 |
| 明显无关的页面 | 4 | 记录不在研究范围内，未抓取 |
| 本地 Manus PDF | 1 | 完整提取 6 页，并继续读取其 5 个官方参考页面 |

141 份摘录中，**1 份发现明确身份错配，7 份只有导航或产品输入界面**；其余 133 份仍是不同长度的 provider 摘录，完整性和原站更新时间通常未知。7 个官方补读包括 README、目录列表、组织列表与 release 元数据，不能一概写成“7 个仓库全部代码已审查”。一次 Parallel 补读请求发生传输超时，8 个 URL 没有取得成功正文，未算入成功数。

仍不可用的是 R006、R021、R062、R082、R100、R102、R118、R138、R146、R157、R158、R172、R194，主要是 LINUX DO 与知乎页面。它们的完整公开 URL、尝试时间和 `CRAWL_UNKNOWN_ERROR`、`CRAWL_LIVECRAWL_TIMEOUT` 或 `CRAWL_NOT_FOUND` 均在来源表中。抓取失败只表示本次工具没有取得内容，不能据此判定原站永久失效。

额外补读 18 项参考资料：17 项取得网页摘录，另 1 项 roadmap 公网页超时后读取了用户提供的本地文件。所有请求响应和正文都在上述独立研究目录，未写入原画布包。时间记录是本次检索时间，不是网页发布时间或旧研究快照。

## 3. 三层搜索应对应不同的工作流程

用户给出的三层表述可在 OpenAI 官方 [Web search 文档（R086）](https://developers.openai.com/api/docs/guides/tools-web-search) 中找到。该文把快速检索、模型主动管理搜索和扩展研究区分开。**“已有明确 URL”是选用 fetch 的理由，并不是禁止模型推理的定义。**

| 层次 | 用户问题 | 0.2.0 的职责 | 完成依据 |
| --- | --- | --- | --- |
| 直接查证 | 已有 URL，或一个短事实问题 | 直接读取已知 URL；确实需要发现来源时再搜索 | 实际正文及其出处；失败、截断和时间边界可见 |
| Agentic search | 需要比较、查新或补齐上下文 | 宿主模型拆问题，选择查询，读取结果，再根据发现改变下一轮查询 | 能说明结论由哪些已读资料支持，还有哪些缺口 |
| Deep research | 多个子问题、长时间调查、矛盾来源或正式报告 | 持久保存 brief、问题、书签范围、预算、搜索/读取操作、来源审核、主张、冲突和报告；由宿主模型继续推进 | 问题有证据支持或明确未解决；错误可撤回；预算和终止状态真实 |

这与 [Jina 的循环说明（S005）](https://jina.ai/news/a-practical-guide-to-implementing-deepsearch-deepresearch)、[dzhng/deep-research（R084）](https://github.com/dzhng/deep-research) 的发现驱动后续研究，以及 [GPT Researcher（R081）](https://github.com/assafelovic/gpt-researcher) 的规划、执行与报告分工吻合。[Jina 项目（R074）](https://github.com/jina-ai/node-DeepResearch) 还明确说明：找到可靠答案与写出长报告是两个问题。网页数量、输出长度或固定执行三轮都不足以证明研究完成。

0.2.0 的 `ResearchSessions` 是 **host-led 会话**：宿主中的模型负责问题分解、来源判断和写作，插件负责可检查的动作与状态。保存一个 session 后，它不会自行在后台继续调用模型。`status` 读取持久状态，不应让用户误以为存在后台 worker。程序可检查“引用是否存在于存档”和“还有没有未处理问题”，不能自动保证回答符合事实。

## 4. MCP 聚合采用显式契约

一个本地 MCP 向宿主提供统一入口，内部把服务商接口适配成稳定结果。每个 provider 都要声明实际支持的 search/fetch、认证来源和参数映射；运行时工具发现与测试决定其是否可用。添加配置名称或在商店里找到服务器，都不能证明已经接通。

| 参考 | 一手事实 | 采用的设计 |
| --- | --- | --- |
| [Exa MCP（S001）](https://exa.ai/docs/reference/exa-mcp) | 默认工具为 `web_search_exa`、`web_fetch_exa`；另有显式启用的工具 | 采用专用适配和实际 schema 检查；不要沿用过时工具名 |
| [Parallel Search MCP（S002）](https://docs.parallel.ai/integrations/mcp/search-mcp) | `web_search` 与 `web_fetch` 分开，摘录有输出上限；默认模式在实际取得的快照间存在差异 | 区分发现和读取；保留截断与内容类型，不把低延迟检索叫原生研究任务 |
| [Tavily MCP（S004）](https://docs.tavily.com/documentation/mcp) | 支持 OAuth，也支持 API key/Authorization header | 宿主管理 OAuth 与环境变量凭据是不同路径；不能笼统称 Tavily 只能通过 OAuth 接入 |
| [Qwen search cookbook（R149）](https://github.com/QwenLM/Qwen-MM-Plugins/blob/main/cookbooks/search/usage.md) | search 与 extractor 分开，可使用 Serper、Exa、Tavily | 统一意图和结果，保留不同 provider 的参数与能力差异 |
| [OpenClaw Web 文档（R178）](https://docs.openclaw.ai/zh-CN/tools/web) | 区分结构化结果、综合答案与原始透传内容 | 对可识别结果规范化，对未知格式显式失败或保留原始证据，不从正文猜造结果记录 |

聚合时按稳定 target 分组、URL 去重和排名融合，同时保存每次查询的 provider、query、rank、时间和原 URL。RRF 解决展示排序，不解决事实可信度。Exa 与 Parallel 同时返回同一个官方页面，仍只是一份页面证据；同一个项目的英文 README 和中文翻译也不能算两个独立来源。

独立查询可以并行，依赖前一轮发现的查询顺序执行。限流、认证错误、传输超时、格式不匹配、部分 URL 失败和成功零结果应分开呈现。重试只能有界进行；不能靠重复抓取掩盖服务失败，也不能把某次网络超时变成“没有相关事实”。

后续真实研究验证发现，同一 Parallel Search MCP URL 的 Exa 摘录写 `basic`，Parallel 取得的正文写匿名搜索默认 `fast`。两个快照均保留；本插件不固定服务器默认模式，也未通过服务端遥测确定哪个描述适用于当前请求。这项差异和处理依据见 [验证记录](validation-0.2.0.md#真实研究流程)。

## 5. 第三层需要能修正证据的持久会话

[Anthropic 的研究系统工程说明（S007）](https://www.anthropic.com/engineering/multi-agent-research-system) 给出了直接依据：研究轨迹动态变化，长任务有状态，错误会累积；出现错误后应从保存状态恢复，不能总是从头开始。它还把引用定位与信息收集分开，并强调并行任务的边界与成本。

据此，0.2.0 的工作流采用以下约束：

1. **先固定问题与范围。** brief 应包含对象、时间口径、交付目标和必要限制。`bookmark_refs` 用 `source_id + section_id + item_id` 定位当前已同步索引中的书签，生成最小 `context.json`，保存标题、URL、文件夹和相关卡片关系。它是本地研究上下文，不会自动把整包或私人笔记发送到远端。
2. **把探索保存成操作记录。** 搜索与 fetch 使用稳定 operation ID，记录调用预算和结果。中断或未知结果不能自动当作成功、退款或重新发出同一昂贵请求。会话恢复时能看到已经取得的资料及下一项缺口。
3. **来源审核与逐字引用分开。** `accepted`、`rejected`、`uncertain` 表达宿主对来源的判断；quote 必须来自实际存档正文并记录哈希。拒绝来源不得继续支持有效主张。哈希和逐字匹配只证明内容对应，没有替宿主完成真实性判断。
4. **允许纠错。** 发现错误时撤回 claim，重开依赖该 claim 的问题；保留已有操作和错误原因。不同口径或相反资料应记录 conflict，解决时引用理由与相关证据。不能通过删除历史让报告看起来没有分歧。
5. **按问题而不是页面数结束。** 未回答的问题、未解决冲突和未确认中断的 pending 操作不得伪装为 completed。确认中断后仍保留 unknown_outcome 和预算预留；其余证据足以回答全部问题时可完成，并明确这项检索缺口。预算耗尽且证据不足时交付 incomplete 报告，明确已有结论、缺口与下一步。输出至少包含报告、来源清单、研究范围、时间、状态和限制。

本次出现的真实反例说明这不是抽象要求：**R003 请求 `https://chatgpt.com/`，但 Exa 返回标题为《The First Civilian Authored GPT Scroll》的 Zenodo 文章正文。** 工具返回了文本，URL 字段也匹配请求，仍不能据此接受该正文。它被记录为 `content_mismatch`，没有进入设计结论。R054、R064 等导航壳同样不能因为“非空”就通过证据门槛。

[DeepResearch Bench 的 FACT（S010）](https://github.com/ayanami0730/deep_research_bench) 采用主张—URL 对去重和支持关系核验，支持这里的证据组织方式。程序检查 exact quote、来源哈希和引用存在性是必要的机械检查；主张是否被段落支持、引用页面是否属于目标对象、两个来源是否独立，仍需要宿主判断和必要抽查。

## 6. 原生 Deep Research 是另一个执行通道

成熟服务已提供原生长任务，值得保留扩展方向，但不应把它们与本地会话状态混称。

| 通道 | 已核对的契约 | 本版本的边界 |
| --- | --- | --- |
| [Exa Agent（S001）](https://exa.ai/docs/reference/exa-mcp) | `agent_run` 支持多步研究、实体研究和结构化输出；需 OAuth 或自己的 API key，按用量收费 | 宿主实际加载并授权后可按任务选用；普通 search/fetch 接通不等于 Agent 已接通 |
| [Parallel Task MCP（S003）](https://docs.parallel.ai/integrations/mcp/task-mcp) | `createDeepResearch`/`createTaskGroup` 发起，`getStatus` 查看，完成后 `getResultMarkdown` 取结果 | 是真实异步服务任务，需独立认证、任务 ID 与恢复策略；不由本地 `status` 冒充 |
| [OpenAI Deep Research（R065）](https://developers.openai.com/api/docs/guides/deep-research) | 文档描述长任务、background、工具调用预算及专用数据源契约 | 不固定旧模型，不把任意本地工具集合宣称成已兼容的远程研究数据源 |
| [当前 MCP 集成指南（S017）](https://developers.openai.com/api/docs/mcp) | 研究兼容接口使用 `search` 与按 ID 的 `fetch`，返回可引用 URL | 只有实现并验证对应接口、远程连接及授权后才声明兼容 |

原包 [Building a Deep Research MCP Server（R067）](https://developers.openai.com/cookbook/examples/deep_research_api/how_to_build_a_deep_research_mcp_server/readme) 已明确标为 archived。它可以解释历史接口思路，不适合直接复制其旧示例模型、传输和参数。当前 Web search 指南与专用 Deep Research 指南的适用范围不同，也不应混为一个统一 API。

原 Manus PDF 的 5 个引用已全部补读：[Cloud Browser（S012）](https://manus.im/docs/features/cloud-browser)、[Wide Research（S013）](https://manus.im/docs/features/wide-research)、[发布说明（S014）](https://manus.im/blog/introducing-wide-research)、[帮助中心（S015）](https://help.manus.im/en/articles/11960169-what-is-wide-research)、[分析场景（S016）](https://manus.im/solutions/analysts)。它们支持“独立对象可以并行、每个对象保留自身上下文”的设计；帮助中心说明 Wide Research 自动触发。产品文档的 250 项案例与帮助中心的 20 项并行描述有不同口径，不能写成固定并发承诺，更不能推断未公开的供应商、路由算法或内部代码。

## 7. Qwen 的安装结构如何吸收

[Qwen README（R109）](https://github.com/QwenLM/Qwen-MM-Plugins) 把能力、安装、依赖、配置、快速使用和开发验证分开；推荐引导安装器，也保留每个宿主的原生命令。每个能力由 Skill 和可选 MCP 组成，安装器调用宿主已有机制，运行时与用户配置各有位置。

本插件采用相同的职责划分：README 先给下载安装和最短可用步骤，进阶宿主差异放到安装文档；共享 Skill 与 Python 运行时只维护一份，不为每个宿主复制核心逻辑；CLI 负责可重复的检查、安装产物和运行入口。安装、配置和验证各自报告结果。CLI 产物生成成功、宿主注册成功、宿主当前会话加载成功应分别描述，不能凭写入文件就宣称所有客户端已可调用。

[Perplexity CLI（R108）](https://github.com/perplexityai/perplexity-cli/)、[Parallel CLI（R169）](https://docs.parallel.ai/integrations/cli) 与 [lark-cli（R113）](https://github.com/larksuite/cli) 补充了 JSON 输出、平台安装与可检查命令的实践。本版本不因此引入它们的账户注册、业务操作或额外模型依赖，也不把上游远程安装脚本不经核对地复制为自己的安装命令。

## 8. 其余调研方向的处理

| 原包方向与代表来源 | 采用的内容 | 本次不采用的内容及理由 |
| --- | --- | --- |
| 书签 RAG：R012–R019、[MimirQ R026](https://github.com/skygazer42/MimirQ)、[Buku R110](https://github.com/jarun/buku) | 可检查流水线、来源映射、回归样本 | 不建第二个权威书签库；向量化不能代替当前网页核验 |
| 采集：Firecrawl R028、Scrapling R029、Cloudflare R030、MarkItDown R031 | 提取与研究分离，标记转换边界 | 不捆绑爬虫、代理池、浏览器和文件管理功能 |
| 目录与商店：R051–R057、R064、R156、R187 | 发现候选和确认安装入口 | 收录、星标、下载数不证明连接、准确率或服务保证 |
| 研究实现：R074、R081、R084、R085、R103–R107、R182 | 问题分解、迭代、预算、引用、缺口与报告 | 不整体复制其 SDK、模型选择、多 MCP 套装或 UI |
| 搜索插件：R148–R152、R162–R167 | 适配器、可见失败、会话错误记录、CLI | 不强制注入全局主动搜索策略，不把 issue 计划当已实现能力 |
| 浏览器与 NLWeb：R124–R146 | 需要动态交互时可路由到宿主已有工具 | 不改为浏览器运行时、网站索引服务或第二个 Bookmark Canvas |
| Agent SDK 与源码解读：R115–R120、R179、R184–R190 | 官方公开接口作为后续执行器参考 | 不依赖旧 Swarm、第三方内部实现推断或未经验证的镜像文档 |
| 工作区与 ACP：R191–R202 | 区分编辑器↔Agent 与 Agent↔工具 | 不把 ACP 当 MCP 搜索协议，也不构建桌面多 Agent 客户端 |

本地 [Bookmark Canvas README 对应的 roadmap（S018）](https://github.com/Browser-bookmark-hub/Bookmark-Canvas/blob/main/docs/ROADMAP_OUTLOOK_DATA_PROCESSING_CLI_SKILL_CLIENT_AI.md) 明确优先做有范围、可追溯的书签研究，先实践再决定全局索引、RAG 或客户端。该文件是方向草案。本插件已有派生索引的价值在于定位、增量读取和可重复验证，不能据此把索引内容当成网页事实。上述选择保持原项目为代码与协议参考，升级工作在独立插件完成。

## 9. 测试应分别证明什么

| 验证层 | 应使用的测试包或材料 | 应证明的行为 | 不能从中推出 |
| --- | --- | --- | --- |
| 画布语义 | 合成 JSON/.canvas fixture，以及用户给出的两个真实包只读试验 | 书签实例、去重 URL、空说明、重复 label、副本锚点、文件夹、组、方向边和增量边界正确 | 模型理解了全部分类含义或研究结论正确 |
| MCP 聚合 | 固定的 Exa/Parallel/Tavily 返回样本与协议测试 | 参数适配、分页/生命周期、来源保留、去重、部分失败、错误体和未知格式可见 | 所有未来 schema 和所有 MCP 服务都受支持 |
| 研究状态 | 含缺失证据、错配来源、冲突、撤回、中断、预算耗尽的情景包 | 引用必须来自存档；拒绝来源不能支持主张；错误能撤回；跨进程恢复不重复执行；未完成状态不伪报完成 | 内容真实、语义支持关系已自动验证 |
| 分发安装 | 导出包、CLI 和隔离目录安装检查 | 产物完整、路径正确、版本一致、共享运行时可运行、无原包私有内容 | 未实际启动的所有宿主已经加载成功 |
| 提供商可用性 | 少量明示范围的 live search/fetch | 当时的握手、工具发现和真实响应；记录时间与失败 | 永久免费、永远在线或固定延迟 |
| 研究质量 | 有标准答案的集合题、带原文的引用题、带冲突的比较题；必要时人工复核 | 事实准确、对象覆盖、证据支持、正确拒绝不确定内容，且成本与时间可比较 | 已经达到某公开 leaderboard 分数 |

[DeepSearchQA 官方数据集（S008）](https://huggingface.co/datasets/google/deepsearchqa) 和[原论文（S011）](https://arxiv.org/html/2601.20975) 强调完整答案集合的 precision、recall、F1，适合“找全一组对象”的研究任务；它也说明只看最终答案看不到轨迹问题，活网页会漂移。[DeepResearch Bench（S009/S010）](https://deepresearch-bench.github.io/) 把报告质量 RACE 与事实引用 FACT 分开，适合评价正式研究报告。两者都不能被一个本地 smoke test 替代；本次没有运行或宣称完成这些完整基准。

[Artificial Analysis（R036）](https://artificialanalysis.ai/zh/agents/search-api) 的固定模型、harness 和设置下比较 provider 的方法可用于后续 A/B 实验；应同时固定时间范围、查询预算和评审标准。[Steel 的 WebVoyager 说明（R042）](https://leaderboard.steel.dev/leaderboards/webvoyager/) 则明确存在交互环境、任务漂移和评估设置差异，主要服务于浏览器 Agent，不是此版本核心验收。排行榜的模型分数、搜索 API 分数与插件研究流程质量需要分别衡量。

## 10. 可复核材料与限制

来源表有 207 条原始 URL 记录、223 个书签实例映射、18 条补充来源及 16 个已逐字检查的短引用位置。每个公开来源保留相应响应或正文文件名与 SHA-256；失败、跳过、脱敏、导航壳、身份错配及本地补读均有不同状态。公开文件不包含原始私人会话链接、账户标识、私人 PDF 路径或凭据。

本次核查验证了清单全覆盖、引用确实存在于保存正文、证据文件存在和原包哈希不变。它没有把摘录升级成完整原文，没有独立复现上游宣传成绩，也没有把文档里的安装命令当作当前机器已经执行成功的记录。后续复查可以从来源表的未读取项、低相关性项和身份审核结果继续，保留同一来源 ID 与新的检索时间。
