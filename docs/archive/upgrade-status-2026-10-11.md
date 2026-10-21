# 升级事项核对（2026-10-11）

本次核对 README、0.5.0 beta.1–beta.9 发布说明、安装与存储计划，以及 2026-10-09/10 的审计、修复和 Wiki 验证记录，并对照当前实现和测试。结论：已经交付的主要功能和本轮 Wiki 修复有实现及回归覆盖；审计中提出的全部优化、知识管理能力和真实模型工作流验收尚未全部完成。

核对基线为 `b5cba1e` 之后的工作树。当前源码提供 42 个 MCP 工具；`wiki_refresh`、`wiki_work` 及本轮修复属于本地开发构建，不包含在已发布的 npm `0.5.0-beta.9` 中。历史文件中的版本、测试数量和性能测量保留原值，不作为当前验收结果。

## 已发布功能与原始计划

| 依据 | 当前核对结果 | 实现与回归证据 |
| --- | --- | --- |
| [0.2.0 安装设计](install-design-0.2.0.md)、[命令入口计划](cli-launcher-plan.md)、[多宿主安装计划](multi-host-installation-plan.md) | 安装、更新、验证、持久来源、作用域和 Windows 适配均已实现。本轮四宿主原生安装检查在 macOS 通过。早期“不使用 npm”和 ZIP 分发的决定已被 beta.4 的统一 npm 分发取代。 | `scripts/launcher.py`、`install.py`、`host_install.py`、`host_clients.py`；`test_launcher.py`、`test_install.py`、`test_host_install.py`、`test_bootstrap.py` |
| [知识存储计划](knowledge-storage-plan.md)、[beta.3](release-notes-0.5.0-beta.3.md) | 统一目录／输入旁边、回退、旧任务登记、work 目录、原文检索、归档去重、Wiki 目录与日志均已实现。原文随任务冻结保存；逻辑统一检索不等于物理只保留一份。 | `src/research.py`、`research_locations.py`、`raw_library.py`、`wiki.py`；`test_output_location.py`、`test_raw_library.py` |
| [beta.1](release-notes-0.5.0-beta.1.md)、[beta.2](release-notes-0.5.0-beta.2.md)、[beta.4](release-notes-0.5.0-beta.4.md) | 交互入口、凭据与偏好、就绪检查、Python 路径、npm 持久安装和四宿主导出均保留。当前安装来源与固定版本语义有回归覆盖。 | `test_onboarding.py`、`test_tui.py`、`test_settings.py`、`test_npm_source.py`、`test_export_bundle.py` |
| [beta.5](release-notes-0.5.0-beta.5.md)、[beta.6](release-notes-0.5.0-beta.6.md) | Wiki 迁移后的证据定位、按需检索指引、DSH 可搬移配置层、解释器探测、Desktop 前置检查和缓存错误回退已实现。批量正文归属又在后续工作树中加强，不能只依赖 beta.5 的围栏修复。 | `src/archive.py`、`wiki.py`、`hosts/dsh/plugin.js`、`scripts/npm_source.py`；相关归档、Wiki、宿主和导出测试 |
| [beta.7](release-notes-0.5.0-beta.7.md)、[beta.8](release-notes-0.5.0-beta.8.md)、[10-09 Diff 审查](diff-review-2026-10-09.md) | 运行时版本、研究位置优先级、锁范围、迟到结果、归档出现位置分页、复核保护、来源合并／删除与崩溃恢复、字面检索和存储诊断都有实现与回归。beta.7 留下的 context N+1 与时间索引问题没有因后续发布自动关闭。 | `test_release_version.py`、`test_research_location_precedence.py`、`test_research_lock_scope.py`、`test_lifecycle_regressions.py`、`test_source_duplicates.py`、`test_wiki_acknowledge.py` |
| [beta.9](release-notes-0.5.0-beta.9.md)、[工具精简审计](tool-surface-audit.md) | 紧凑搜索、目标独立分页、实例与副本语义、空间／时间和 Git 学习指引已落地。接口合并只是原型，不是遗漏的已承诺接口。默认 6 工具属于本机项目配置；服务端保留完整工具集。 | `src/bookmark_output.py`、`skills/bookmark-research/SKILL.md` 及中英参考；`test_bookmark_output.py`、`test_mcp_server.py` |

测试文件均位于 [tests](../tests/)；表格中的实现文件位于相应源码目录。原生安装与适配器测试不证明模型已经完整执行过研究流程。

## 2026-10-10 审计逐项落实情况

| 原建议 | 状态 | 当前证据与剩余工作 |
| --- | --- | --- |
| 批量正文归属、每页及整批预算、快照续读 | 已实现并验证 | [archive.py](../src/archive.py)、[边界回归](../tests/test_fetch_boundaries.py)；不明归属正文不进入可引用提取，切片与存档 SHA 分开。原始响应仍可保留。 |
| 区分完整性、新鲜度和复核；URL 版本及引用依赖 | 已实现当前范围 | [source_versions.py](../src/source_versions.py)、[bookmark_dependencies.py](../src/bookmark_dependencies.py)、[新鲜度回归](../tests/test_wiki_freshness.py)。跨任务新正文、年龄、失败及相关书签／链接变化触发复核；不宣称源站实时验证。 |
| Wiki 候选优先检索、别名、目录摘要及日志增量维护 | 已实现当前范围 | [wiki_search.py](../src/wiki_search.py)、[wiki.py](../src/wiki.py)。只校验命中候选，失效页不占结果页名额；写入复用目录摘要并追加日志。JSON 索引和 Markdown 目录仍随当前页数重写。 |
| 按需刷新引用来源并定位受影响页面 | 已实现并验证 | `wiki_refresh` 返回变化状态、归档读取和续页参数；`wiki_list(source_url=...)` 包括关联页。刷新保留原 Wiki 修订，后续由宿主审阅并提交。 |
| 整理状态、发布回执、中断恢复 | 已实现并验证 | [wiki_work.py](../src/wiki_work.py)、[工作恢复回归](../tests/test_wiki_work.py)；从持久数据重建状态，未提交修订不计完成，已提交但响应丢失的写入可查回。 |
| 解除慢网络对本地 MCP 的阻塞 | 已实现并验证；部分调度建议待做 | [mcp_dispatch.py](../src/mcp_dispatch.py)、[并发回归](../tests/test_mcp_concurrency.py)；4 个工作线程、最多 16 个活动／排队请求、请求 ID 和输出串行化。仅能取消未启动任务；没有覆盖排队与多次 HTTP 的统一请求总时限，也未输出完整的排队／执行计时。 |
| 大 context 可以完整续读 | 输出分页已实现；底层优化未完成 | [context_output.py](../src/context_output.py)、[分页回归](../tests/test_context_pagination.py)覆盖 5,000 节点和各集合。仍先构建完整 context 再切片；offset 不是绑定固定来源版本的游标，跨页期间来源变化仍需重新核对。 |
| 单关键词重复 SQL、每次查询额外的全库统计 | 已补主要重复读取；计数缓存未做 | 既有单关键词复用保留。本轮新增 `SourceManager.source_status`，MCP／CLI 查询和研究新鲜度读取不再为了取来源状态而计算完整索引统计。显式状态查询及查询自身所需的范围计数仍计算，尚无按输入版本持久化的计数缓存。 |
| 输入未变时跳过同步暂存及重复读取 | 未实现完整优化 | [SourceManager._ingest](../src/source_manager.py)仍写 incoming 和候选快照，再验证已有版本。live 检查无变化可提前返回，但重复显式 sync 仍有这笔成本。优化须保留模式、partial/complete、绑定关系及快照完整性判断。 |
| 栏目头部与原始树分开读取；context N+1 | 未完成 | [BookmarkIndex.context](../src/bookmark_index.py)仍读取栏目完整 raw_json 后剔除树；逐栏目统计、逐祖先读取仍存在。单次搜索内的栏目缓存没有解决全部 context 开销。 |
| 研究结束时合并多个 Wiki 候选查询和校验 | 未实现 | [ResearchSessions._wiki_follow_up](../src/research.py)仍逐词调用搜索；每个搜索已有候选索引，但不同词之间尚不共享一次检索／证据校验。 |
| Wiki 连同研究证据的备份、导出和恢复检查 | 部分已有，专用流程未实现 | 证据相对路径、移动后解析与哈希验证已有测试；没有完整的 Wiki 依赖打包／恢复命令。仅复制 Markdown 仍不足以恢复可验证知识库。 |
| 轻量保存一条带证据的本地知识 | 现有通路可用，专用快捷入口未实现 | 可通过 `research_import_evidence(provenance.kind=local_document)` 保存真实本地原文并建立 claim；没有绕过研究记录的本地结构事实接口。局部文档和推论仍保留整体输入依赖。 |
| 分内容类型 TTL、后台监测、ETag/Last-Modified、实质变化判定 | 未实现 | 当前提供统一的 `wiki.max_source_age_days`（默认 30）和显式按需刷新。正文 SHA 变化不是事实变化判断；没有后台网页监测或自动改写知识。 |
| 语义召回、重排、来源／时间检索过滤和历史检索入口 | 未实现这些扩展 | 当前为字符索引、字面／空白匹配及显式别名；可按页 ID 和 revision 读历史。20 道固定回放题不是盲测或通用问答准确率评测。 |
| 性能与交互回归指标 | 部分完成 | 有离线故障、输出预算、并发、分页及本地性能采样；尚未建立四类固定负载的 CI 相对性能门槛，也未完成同模型、同预算、保留题集的答案和引用质量比较。 |

依据：[性能审计](performance-audit-0.5.0-beta.9.md)、[Wiki 生命周期审计](wiki-lifecycle-audit-0.5.0-beta.9.md)、[搜索设计调研](search-design-research-2026-10-10.md)、[修复验证](fixes-validation-0.5.0-beta.9.md)、[Wiki 工作流验证](wiki-workflow-validation-2026-10-10.md)。

“未实现”包括审计明确提出的后续建议，不表示已发布版本声称具有这些能力。以后推进这些条目时，应按其验收条件单独关闭；不能用新增工具数量或测试数量代替验收。

## 本轮修正与实测

- 中英文 README 工具数改为 42，并说明源码新增工具的发布边界；英文详细工具表补齐刷新、工作恢复、复核、来源删除及合并。
- 增加来源状态的轻量读取；全来源状态列表复用已经计算的统计，避免同一列表重复计算。返回的来源版本、别名、路径存在性和 live 检查状态保持原语义。
- 新增两项回归：禁止读取内容表时仍能取得正确来源状态，并检查后续过期、版本变化和来源不可用；MCP 搜索／context 在禁止调用完整统计接口时仍正常返回来源状态。
- 完整测试：`python3 -B -m unittest discover -s tests -v`，显式启用 npm 与原生 Pi/DSH 条件检查，**633 项全部通过、0 跳过，129.900 秒**。
- 六份已保存的真实来源再次执行固定检索回放：首次查询 11/20，补充词／关联页／原文回查方案 20/20；31 天过期提醒、工作项复核和损坏证据排除三项控制检查全部通过。回放没有联网，也未评判回答的语义正确性。
- 环境：macOS，Python 3.9.6；Codex 0.160.1、Claude Code 2.1.285、Pi 0.73.1、DSH 0.1.5-rc.1、pnpm 10.15.1。Pi 和 pnpm 安装在临时目录；各宿主测试使用隔离配置。
- 首次临时依赖安装遇到现有 npm 缓存的 EACCES，改用独立缓存后成功；没有变更原缓存所有权。
- 63,800 个合成书签实例的来源状态读取，10 次交错采样：先算完整统计再取状态的中位数为 47.522 ms，轻量路径为 0.046 ms；SQL 从 11 条减为 2 条，返回状态相同。这只测来源状态读取，不代表完整 MCP、网络或模型时延。
- 实际 npm 包核对：当前候选包 138 个文件、42 个工具；已发布 beta.9 为 124 个文件、40 个工具。候选包内 35 个运行时文件和 25 个技能文件与工作区一致；Codex、Claude、Pi、DSH、Agent Plugins 五种导出均通过真实 MCP 初始化。包内未包含本机配置、索引、原始画布或测试目录。
- 从候选 tgz 安装的 npm 命令通过 `--help`、`doctor`、非交互 `status`、隔离 Codex 的 `install --dry-run`；没有创建研究索引。仓库及导出插件校验、Skill 校验和 24 份变更 Markdown 中的 191 个相对文件链接检查均通过。
- 本机 Codex 已更新并验证为 `0.5.0-beta.9+codex.20261010212606`，已安装且启用，实际 MCP 返回 42 个工具；35 个运行时文件和 25 个技能文件与工作区一致。更新前保留 bundle 与来源备份，marketplace 内容及本地更新来源保持一致。新建对话后加载新副本。

可重复运行完整条件检查：

```sh
BOOKMARK_RESEARCH_TEST_PUBLISHED_NPM=1 \
BOOKMARK_NATIVE_HOST_BIN=/path/to/native/bin \
python3 -B -m unittest discover -s tests -v
```

`BOOKMARK_NATIVE_HOST_BIN` 须包含实际可执行的 `pi`、`dsh` 和 `pnpm`。缺少宿主或关闭条件检查时，测试会如实跳过。

本机复核产物位于 `/var/folders/f0/4qk09cq91tg6sk7gffvk85bw0000gn/T/bookmark-upgrade-audit-20261011-dnhhwt9r`：`full-tests.log`、`retrieval-results.json`、`status-benchmark.json` 及其复现脚本、`package-verification.json`、`npm-launcher-smoke.json`、`installation-verification.json` 和安装前备份。临时宿主依赖、合成资料库和这些运行日志不纳入插件分发。

## 仍需独立验收的范围

1. Windows、Linux 上的这份新工作树及原生宿主安装：现有 CI 矩阵和历史通过记录保留，本轮没有在这些系统重新执行。
2. 四宿主真实模型驱动的阅读代理、独立验证、补查、取消与恢复：本轮验证了原生安装、共享运行时和模拟工作流契约，没有把安装成功记作完整研究成功。
3. OpenAI／Parallel 等有偿研究服务的真实任务、OAuth／额度与长期供应商可用性：现有契约与失败处理测试通过，未以真实付费任务验收。
4. 上表未完成的性能、检索和知识生命周期扩展。
5. 新版本发布与发布后的安装回归：本轮完成本地工作树及安装验收，不改 npm dist-tag 或历史发布记录。
