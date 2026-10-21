# 工具与 Skill 精简审计（2026-10-10）

> 下文 40 工具及目录体积是本次审计的历史基线。当前源码为 42 工具；后续实现、文档修正与验收边界见 [2026-10-11 升级核对](upgrade-status-2026-10-11.md)。

这次按「画布基础能力 → 直接检索 → Agentic Search → Deep Research」检查职责、调用关系和真实任务。结论是：**保留小而完整的检索基础层，复杂任务按需组合；优先减少强制步骤与重复返回内容。** 未发现可以据现有证据直接删除实现的无用接口。

已将本项目默认 Bookmark MCP 入口从上一轮的 13 个收敛为 **6 个**，保留全部 40 个服务端契约及 CLI。Chrome 在本项目默认关闭，CodeGraph 复用已有注册。接口合并保留为原型；紧凑搜索已作为可选参数落地，默认旧格式兼容，实施结果见第 9 节。

## 1. 从基础原则确定能力边界

| 层次 | 应做的事 | 所需入口 | 按需增加的能力 |
| --- | --- | --- | --- |
| 画布基础 | 理解包、定位内容、计数、读取层级与空间关系 | `sync_package`、`index_status`、`search_bookmarks`、`get_context` | Git 学习回顾、来源历史和管理 |
| 直接检索 / Non-reasoning retrieval | 对给定 URL 读取，或执行一个明确的查询 | 已知 URL 用 `fetch_web`；固定查询也可一次 `search_web` | 访问不明或失败时诊断；需要旧正文时查档案 |
| Agentic Search | 模型拆问题、判断结果、选择下一次搜索或读取，直到证据足够 | 同一组 `search_web` + `fetch_web` | 持久进度、预算、证据留存 |
| Deep Research | 持续调查多个问题、比较来源、解决矛盾并综合结论 | 推理由宿主模型或选定的外部研究服务执行 | 冻结输入、恢复、覆盖检查、持久证据；外部任务生命周期 |

URL 是否已知决定「读取还是发现来源」；是否由模型主动管理多轮过程决定「直接检索还是 Agentic Search」。保存一份文件、写入一条 Wiki、检查整个包的本地数量，都不自动构成深研。

`research_start` 只建立任务、冻结输入和预算，不启动模型循环或后台研究。需要持久深研时，使用 `research_start/status/inventory/search/fetch/source/record/coverage/finish`；需要导入宿主取得的正文时增加 `research_import_evidence`。专业研究服务是另一组可选入口，并非每次深研都必须启动。

代码依据：[MCP 分发](../src/mcp_server.py)、[检索引擎](../src/web_search.py)、[研究会话](../src/research.py)。CodeGraph 用于核对分发、目标方法、CLI 和测试依赖；真实画布测试使用新 CLI 进程与隔离索引。

## 2. 已实施的精简与基础修正

- 本机项目配置 `.codex/config.toml` 默认只开放上述 6 个基础入口。Wiki、档案、历史、设置、诊断、研究任务及管理操作继续可用；需要时通过 CLI 或调整工具配置使用。该配置仅影响本项目，新线程采用。
- [主 Skill](../skills/bookmark-research/SKILL.md) 明确区分直接读取、模型管理的搜索和持续研究。已知 URL 可直接读；`research_readiness` 用于访问不明、失败诊断或外部服务选择，复用已有结果。
- 普通回答保存不再自动引入持久研究会话。空间总览已经足够时，不再要求追加局部 context。
- 修正中英文包语义及 CLI 说明：文件夹可直接按 `item_types:["folder"]` 查询；不必先找书签、再读祖先、再找文件夹。文本卡、组和边标签由独立的 `canvas_matches` 返回；栏目说明仍需 context。
- 修正两条计数说明：混合查询的 instances 按所选条目类型计数；context 的 counts 是栏目范围，不是指定文件夹的子树数量。数字、结果字段和查询行为保持原契约。

这些是对上一轮精简的补充。此前已移除会被宿主重复附加到每个工具的通用 instructions，并压缩工具描述和按需参考文档。主 Skill 从最初 13,177 字符精简到本轮审计时的 5,509 字符，随后补充了紧凑格式的使用说明；字符数不是模型 token 数。

## 3. 默认目录的实际成本

以下是**实现 compact 参数前的审计基线**，各配置使用相同描述，以 UTF-8 紧凑 JSON 编码 `{ "tools": [...] }`；比较包含名称、描述和 inputSchema，没有把字符数换算成上下文 token。

| 配置 | 工具数 | inputSchema 字节合计 | 工具目录字节 |
| --- | ---: | ---: | ---: |
| 全部服务端契约 | 40 | 27,019 | 37,900 |
| 上一轮扩展读取集 | 13 | 5,741 | 9,523 |
| 当前基础集 | 6 | 3,018 | 4,922 |

基础集相对完整目录减少约 **87.0%**，相对 13 项减少约 **48.3%**。这证明目录体积减少，不证明模型时延同比下降。

本会话起始的 68 项是旧连接中的 Bookmark 37 + Chrome 30 + CodeGraph 1；源码已有 40 个 Bookmark 工具。现有连接不会因重装自动换成新目录，不能把旧连接数量当成配置未生效的证据。

## 4. 哪些值得合并、移出默认目录或保留

| 候选 | 判断 | 依据与边界 |
| --- | --- | --- |
| 无用实现的硬删除 | 本轮没有足够证据 | 40 个入口都有实现和 CLI 对应；静态引用也不能排除外部调用者。 |
| `index_status` + `source_history` | 能合并，当前收益低 | 临时 `view=overview/history` 原型通过 5 个正常回放、7 个错误参数检查。两项目录 861 → 588 字节，省 273 字节；每项请求仍是一次调用。基础集已隐藏 history，合并反而会扩大常用 status 的 schema。 |
| `wiki_list` + `wiki_search` | 可作为以后的一项读取入口 | 列表包含失效页，搜索排除失效证据；默认分页和 pages/results 结构不同。空查询不能直接替代列表。 |
| `research_service_status` + `research_service_result` | 可研究统一观察入口，低优先级 | 网络观察端点不同，读取还会保存本地观察；默认状态检查不应隐式变成读取报告。 |
| 提供商描述 + readiness | 有重叠，尚非等价替代 | readiness 已复用部分描述，但不包含全部配置与服务输出；catalog probe 也不等同实际检索成功。 |
| `evaluate_research` | 最适合默认走 CLI/脚本 | 属于离线评测和发布验证，不应进入每次普通研究；兼容契约继续保留。 |
| 来源删除/合并、设置写入、Wiki lint | 放到管理任务 | 与查询的副作用、用途不同；默认不暴露，不混成一个读写工具。 |
| `search_bookmarks` 与 `get_context` | 保留两种能力 | 前者回答内容与目录，后者提供节点、文字、组、边和几何；单个局部查询不能替代空间总览。 |
| `search_web`、`fetch_web` 与任务内 search/fetch | 保留运行边界 | 发现片段、读取正文、持久预算与幂等操作不是同一契约；Agentic Search 可以直接组合前两者。 |
| 原始档案与 Wiki | 保留证据层次 | 原文检索与经过整理、引用和复核的结论不能混作同一种事实。 |

合并前必须处理三个依赖：CLI 的 `_checked_input` 直接读取 `TOOL_SCHEMAS[tool]`；服务端发现和接受旧名目前共用该表；现有验证器不实现 `oneOf/const/if`。因此不能只删注册名或塞入 action union。临时原型先选择受限分支，再调用原 schema 校验，保留错误与返回行为。

静态 union 实验也没有显示「名字更少就更省」：把 4 个普通/任务 search、fetch 逐分支包装，schema 从 2,363 增至 2,634 字节；6 个 Wiki 工具从 2,899 增至 3,281。它不是所有合并设计的下界，但足以否定只按名字数量判断成本。

## 5. 更值得加强的方向：紧凑的基础查询结果

真实 Exa/MCP 查询只有 6 个字面命中，格式化输出却约 20 KB。同一批行出现在顶层和各 target 中，行内又有身份别名和重复 raw/metadata。

临时原型建立一次响应内的行表，顶层与 target 保留有序引用；按实例 ID 保留同 URL 的不同条目，目标分页独有的行也进入行表。标题、URL、父 ID、路径、卡片来源、note/tag、复制关系和分页保留。未知或冲突的原始字段保存在明确标记的可展开文件中。

| 真实样本 | 原始紧凑 JSON | 投影后 | 减少 |
| --- | ---: | ---: | ---: |
| Exa/MCP 搜索 | 15,511 B | 6,839 B | 55.91% |
| 文件夹发现 | 19,944 B | 15,396 B | 22.80% |
| 文件夹子树 | 8,228 B | 6,605 B | 19.73% |
| 合计 | 43,683 B | 28,840 B | 33.98% |

两侧使用相同紧凑编码，收益不包含删除 JSON 排版空白。计入实际需要的 117 B 额外字段文件后，仍减少 33.71%。三个样本的标准证据、来源状态和分页机器比对通过；另检查了目标独有行、同页多实例以及未知/冲突字段。真实样本未出现 canvas_matches，其透传只用明确标注的构造样例验证。

**以上是设计原型的测量。** 引用解析和按需展开可能增加理解或读取成本；未测模型漏读率、首答时间或答案质量。后续实现改为把额外字段直接保留在结果行内，避免附属文件读取，并保持可选开关；见第 9 节。

## 6. 用示例画布验证

输入是用户提供的 `书签画布-20260906`。索引、快照和试验文件放在独立目录；没有向网页提供商发送包内容，没有启动外部研究任务。

独立读取原 JSON 与 CLI 得到一致结果：**638 个书签实例、557 个唯一 URL**；5 个栏目、7 个画布节点、3 条边；122 个文件夹行中有 1 个合成根，用户文件夹为 121 个。A 有 601 个实例，B 共享 A 的树，不新增实例；三个临时栏目分别有 32、1、4 个实例。

| 真实问题 | 足够的查询 | 关键质量检查 |
| --- | --- | --- |
| 总量与副本关系 | 一次 context 总览 | 不把 B 的 601 条再加一次。 |
| Exa/MCP 链接及所在目录、卡片 | 一次 search | 字面命中为 6 实例/5 URL；排除 examples 假阳性后，相关为 4 实例/3 URL。只据元数据，不宣称已读网页。 |
| 邻近文字、分组和连线 | 复用同一次总览 | A 的局部 context 会遗漏无连线的邻近文字；保留总览并区分方向、几何与意图。 |
| 找文件夹并读取层级与内容 | 两次 search | 子树的 5 行是 2 个文件夹 + 3 个书签；空子目录仍可见，不需要额外 context。 |

独立审计实际执行了 8 次业务查询，包含副本、局部 context 和祖先的对照检查，0 错误、0 重试。宿主两次截断过大输出，随后读取已经落盘的内容，没有重跑业务查询。

删除对照步骤、共享总览后，根节点将 **4 次查询重新执行**，全部证据与旧结果相同，仅两类 count 说明按修正更新。4 个 CLI 进程耗时合计 0.245 秒，输出 71,009 B；首次导入另计，原测为 0.156 秒。它们是本地进程时间，**不是模型首个有依据回答的时延，也不是同条件的模型 A/B 测试**。

这证明本例无需新建万能查询工具，已有能力就可完成较短路径。尚未测试网络服务时延、长时间深研质量、大画布的空间分页或学习 Git 历史；这些不从本例外推。

## 7. 8 个 Skill 与其余 MCP

审计开始时，8 个 Skill 的发现描述合计 2,651 字符；完整正文与参考文件按需读取，不能全加成每轮固定成本。

| Skill | 处理判断 |
| --- | --- |
| bookmark-research | 保留领域入口；按上述层次精简流程，维护包语义。 |
| find-skills | 最应收窄触发：仅在明确寻找可安装 Skill/扩展能力时选择，不把普通修代码、PR review 引向技能搜索。 |
| skill-installer | 保留已知 GitHub 路径及官方目录安装能力；与开放生态发现协作。 |
| skill-creator、plugin-creator | 保留内容创作与分发封装的边界；plugin-creator 直接引用 skill-creator 的兄弟校验脚本，不能直接删目录。 |
| openai-docs、build-with-exa | 分别负责 OpenAI 当前官方资料与 Exa API 集成开发，不能因都涉及搜索就合并。 |
| imagegen | 位图生成/编辑职责独立，未发现可替代项。 |

find-skills 的最小触发补丁保留明确发现请求时的自动选择。原文件和目录归 root 所有，曾阻止直接应用；后续通过用户目录中的精简副本和官方禁用旧入口的配置完成替换。root 文件和 OS 权限保持原样，实际提示词仅出现一次精简入口；见第 9 节。

Chrome 30 项已完成元数据分组。截图与无障碍树、网络与控制台、Lighthouse 与性能 trace 有不同证据用途；`fill` 与单元素 `fill_form` 是有限重叠候选，但未验证事件、textarea 和错误行为等价。按浏览器任务启用整个服务更合适。CodeGraph 已是单入口，仅用于已有索引的仓库，没有再合并的必要。

## 8. 审计阶段的验证与复核入口

- 21 项 MCP、20 项书签索引、10 项查询边界测试通过，共 51 项；未为说明文字新增镜像测试。
- 主 Skill 校验、100 个本地 Markdown 文件链接和 `git diff --check` 通过。
- 原始包全部 7 个文件的文件集及 SHA-256 前后相同。
- 此阶段本地插件重装并验证为 `0.5.0-beta.8+codex.20261010005044`。后续功能实现再次更新本地安装；全部服务端契约继续保留。

下列为本机审计记录，不纳入插件运行时，也未将原始画布内容复制进本报告：

- [40 个契约、CLI 依赖与静态合并审查](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-interface-audit-y1m3n252/mcp-contract-audit.md)
- [8 个 Skill 的职责证据](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-interface-audit-y1m3n252/skill-portfolio-audit.md)
- [Chrome 与 CodeGraph 元数据审查](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-interface-audit-y1m3n252/chrome-codegraph-audit.md)
- [真实任务原始观察与计量](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-interface-audit-y1m3n252/trial/observations.md)
- [来源合并回放](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-interface-audit-y1m3n252/source-interface-replay.json) · [基础任务重放与最终目录计量](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-interface-audit-y1m3n252/core-replay.json)
- [紧凑输出原型、校验与限制](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-interface-audit-y1m3n252/trial/compact_prototype/README.md)
- [find-skills 最初生成的触发补丁](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-interface-audit-y1m3n252/find-skills-trigger-narrowing.patch)

## 9. 用户授权后的实现

`search_bookmarks` 增加 `compact:true`，CLI 增加 `search --compact`。未指定或传入 `compact:false` 时仍返回原有完整行；Skill 的普通结果页主动选择紧凑模式，只统计数量时使用 count_only。没有增加工具名字，也没有把搜索和上下文合并。

[投影模块](../src/bookmark_output.py) 使用 `_compact.format:"bookmark-search-v1"` 标识格式。`result_refs` 与各 target 的 `result_refs` 分别选择 `rows` 中的有序页面，引用仅在本次响应中有效。行表包括目标分页独有的行；它的大小不是查询总数。同一 URL 的不同实例保留，内容冲突的相同 ID 也不误合并。

只有与标准字段的 JSON 类型和值均相等时，才删除别名或重复 raw/metadata 字段，包括递归区分 true/1、false/0、1/1.0。未知及冲突字段留在行内容器中，不生成附属文件。`raw_json`/`metadata` 在此模式下表示这些残留字段；需要完整对象时使用完整模式。来源状态、刷新信息、canvas_matches 和计数均保留，get_context 继续返回完整空间视图。

同一真实画布的新 CLI 结果，按两侧相同的紧凑 UTF-8 JSON 编码计算：

| 查询 | 完整结果 | 紧凑结果 | 减少 |
| --- | ---: | ---: | ---: |
| Exa/MCP 关键词 | 15,546 B | 7,016 B | 54.87% |
| 文件夹发现 | 19,979 B | 15,512 B | 22.36% |
| 文件夹子树 | 8,263 B | 6,782 B | 17.92% |
| 各目标独立分页，limit=1 | 5,408 B | 3,924 B | 27.44% |

计数页和只有画布文字命中的页面没有可去重的书签行，紧凑格式反而增加约 260 B 的格式说明；因此不把 compact 作为所有查询的无条件默认。它是传输表示的选择，不是证据质量或模型速度的提升承诺。

13 次实际 CLI 调用验证了完整与紧凑页面、目标独有行、计数页、画布文字及完整空间总览。书签仍为 638 实例/557 URL，原包 7 个文件哈希不变。新增 7 项投影行为测试和 1 项 MCP 集成测试，并扩展参数校验；全量 595 项测试中 592 项通过、3 项跳过。

find-skills 的精简版本已写入用户可写的 `~/.codex/skills/find-skills/SKILL.md`，使用官方 `skills/config/write` 只禁用旧的 `~/.agents/skills/find-skills/SKILL.md` 入口。本机 Codex 0.160.1 的项目层 skills.config 虽能被 config/read 读到，未被所测技能启用流程执行，因此撤回了试验的项目副本及该配置段；6 工具的项目配置保留且已由 effective config 验证。用户层替换在项目内外的真实 prompt 检查均只有一个精简入口、没有旧描述，保留明确找 Skill 时的自动选择。

本地插件已更新至 `0.5.0-beta.8+codex.20261010022814`，安装验证通过。安装目录中 28 个源码与 Skill 文件逐字对比一致，6 工具项目配置保持不变。安装后的 CLI 在相同分页参数下重放 Exa/MCP 查询，6 行证据、目标页面和计数与验证基线一致；独立实现审查未发现必须修正的问题。新会话加载更新后的插件与 Skill 配置。

本次实施记录：[实际画布验证](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-compact-s0fhgq4g/real-canvas-validation.json)、[紧凑契约审查](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-compact-s0fhgq4g/contract-review.md)、[独立实现审查](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-compact-s0fhgq4g/implementation-review.md)、[安装文件比对](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-compact-s0fhgq4g/installed-byte-verification.json)、[安装版本查询验证](/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-compact-s0fhgq4g/installed-query-verification.json)。
