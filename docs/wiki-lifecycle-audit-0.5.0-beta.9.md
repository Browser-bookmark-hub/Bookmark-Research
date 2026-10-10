# Wiki 存储、召回与更新审计：0.5.0-beta.9

> 本文记录修复前的生命周期问题。来源新鲜度、按需刷新、候选索引和整理恢复的当前实现，以及仍未完成的建议，见 [2026-10-11 升级核对](upgrade-status-2026-10-11.md)。

2026-10-10。判断：**证据留存已有基本工程保障；知识召回、网页新鲜度与变更传播仍不成熟。** 当前 Wiki 可以保存经过声明复核的结论及历史引用，但不足以单凭 `validation.status=current` 判断这些结论现在仍适用。

本轮使用实际安装的 beta.9、独立的合成书签、虚构价格和模拟网页响应。没有访问外部网页，也没有修改用户真实 Wiki 或原始书签包。相关 22 项 Wiki 自动测试全部通过。以下生命周期结果来自实际调用，性能结果来自 WikiStore API，未包含模型、MCP 和网络耗时。

## 一、已复现的更新边界

| 场景 | 实际结果 | 含义 |
| --- | --- | --- |
| 引用抓取时间为 2020-01-01 的合成网页 | Wiki 为 `current`，读/搜没有触发抓取 | 没有按网页年龄判定新鲜度 |
| 同一网址的合成价格从每月 10 美元变成 20 美元，重新抓取、保存并接受新证据 | 旧 Wiki 仍写 10 美元，仍为 `current`，没有提醒 | 新网页版本尚未驱动旧结论的复核状态 |
| 主动把定价 Wiki 更新为 20 美元，另一个使用说明页面链接到它 | 使用说明仍写 10 美元，整体为 `current`，issues 中有 `link_has_newer_revision` 警告 | 能看到直接链接的新版本，但没有可靠传播到依赖结论的复核状态 |
| 同一书签包里仅重命名一个未引用书签，重新 sync | 定价 Wiki 变为 `needs_review`，引用的书签未变 | 更新检查粒度是冻结研究输入的版本，容易扩大复核范围 |
| 对这个无关书签修改执行 acknowledge | 新 Wiki 修订恢复 `current`，没有抓网页 | acknowledge 记录人工/模型对输入版本的复核声明；它不刷新网页证据 |
| 显式撤回所引用 claim | Wiki 变为 `stale`，搜索不再返回该页面 | 明确的证据失效能正确传播 |
| 使用旧 expected_revision 写入 | 拒绝覆盖 | 并发版本保护有效 |

同网址的新旧网页证据拥有不同的内容哈希，历史 Wiki 文件也保持原哈希。保留旧证据是合理行为；缺失的是“出现了更新证据，需要检查旧结论是否仍适用”的关联。

实现依据：[source_freshness](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/research.py:670) 明确只比较最近已同步的本地索引；[Wiki 校验](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/wiki.py:176) 检查保存的 claim、引用、文件和输入版本；[状态汇总](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/wiki.py:435) 不把网页年龄、同 URL 新快照或 `link_has_newer_revision` 纳入 `needs_review`。

书签同步本身有可用的规则：live 模式检查本地目录变化，snapshot 模式保留导入版本、需要再次 sync 才推进；都不会因远端网页更新而自动改写书签或 Wiki。网页正文的更新与书签 JSON 的更新是两个独立事件。

## 二、存储：完整性保护值得保留，维护成本需要改进

现有写入具备不可变修订、expected_revision、研究状态与 Wiki 索引锁、引用原文校验、来源接受状态与 claim 撤回检查。正文在同一归档内按内容哈希复用。写锁内的二次校验用于防止发布时的并发变化，不应为了几毫秒删掉。

但目前还有三个维护问题：

- 每次写一个页面，都会重写 JSON 索引，读取所有当前页面重建 `index.md`，读取并重写完整 `log.md`。增量写入的工作量随总页数增长。
- Wiki 引用依赖原 research state、claim 和证据文件；仅备份 Wiki Markdown 无法保留工具层的可验证性。长期知识应有明确的依赖打包、引用保护和恢复检查。
- 写入结构必须引用 research_id/claim_id。简短知识保存也要先形成这些记录；可以提供轻量的带证据保存流程，底层继续保留可验证 claim，避免把简单保存扩成完整研究仪式。

[写入路径](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/wiki.py:294)、[全目录重建](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/wiki.py:384)、[日志读取](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/wiki.py:406)、[引用依赖](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/wiki.py:145)、[归档正文复用](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/archive.py:43)。

## 三、查询：能用，但召回和扩展性都有局限

搜索按标题、段落标题和正文做字面匹配，支持大小写折叠与中文空白差异，没有实体别名、语义召回或新鲜度排序。合成页面中，`定价` 命中 1 页，`收费标准` 与 `多少钱` 均为 0；`合成 产品 定价` 能利用空白兼容命中。这展示能力边界，不是对真实用户问题的召回率评估。

更值得修的是执行顺序：搜索会逐页读取修订、校验证据，再判断文本是否匹配。即使 `limit=1` 或最后没有命中，也处理整个 Wiki。研究结束寻找候选 Wiki 时，还会针对最多 6 个词重复调用这个搜索；可合并为一次候选检索与共享校验。

使用每页 1 个 claim、全部共享同一研究任务和约 6.7 KB 来源正文的简单合成样本，预热 2 次、查询采样 10 次：

| Wiki 页数 | 命中 1 页的搜索中位数 | 无命中的搜索中位数 | 按已知 ID get | 阶段最后 10 次新增写入中位数 |
| --- | ---: | ---: | ---: | ---: |
| 10 | 5.94 ms | 5.83 ms | 1.63 ms | 9.58 ms |
| 100 | 50.51 ms | 52.73 ms | 1.61 ms | 28.64 ms |
| 300 | 151.65 ms | 151.12 ms | 1.89 ms | 71.44 ms |

300 页时，无命中搜索仍检查 **300 个修订、300 组证据**；更新一个已有页面会检查 **301 个修订**。这是简单合成负载，没有多来源大正文、最多 24 个不同 claim 或大量画布研究的附加开销。数据说明线性扫描成本，不能将数值直接外推到任意真实 Wiki。

[搜索实现](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/wiki.py:492)、[候选 Wiki 查找](/Users/kk/Downloads/chrome-download/Bookmark-Research/src/research.py:1504)。`after_research:auto` 返回让宿主执行写入/更新的后续指令，不是持续运行的网页巡检器。

## 四、建议优先补齐的知识生命周期

先把现有引用整理成可查询的反向依赖，再设计更新调度：

```mermaid
flowchart LR
    B[书签实例] --> U[网页 URL]
    U --> V[网页快照版本]
    V --> C[引用该版本的结论]
    C --> W[Wiki 页面修订]
```

1. **分开完整性、新鲜度与复核状态。** 保存的证据未损坏、网页最近检查过、结论经过复核分别表达。记录来源内容版本、抓取时间、最近检查时间、结论适用时间和复核时间。更新 Wiki 的标题或目录不应刷新网页的检查时间。
2. **给网页建立可控的检查策略。** 按需检查与按计划检查结合；定价、接口、产品能力等易变事实采用更短有效期，历史文章采用更宽松规则。在服务支持时利用 ETag/Last-Modified 减少下载；比较正文和实质变化，降低导航、广告和动态时间戳造成的误报。检查失败应标记不可确认，保留历史证据。
3. **把变化定位到具体结论和页面。** 同 URL 出现新快照后，找出引用旧版本的 claim/Wiki，先标为待复核。LLM 对比新旧依据，判断哪些事实变化，再生成带新引用的修订。无关书签重命名不应要求整批知识重新确认；有空间/标签语义的结论仍需依赖对应元数据。
4. **让查询同时考虑召回与时效。** 先建立正文检索索引及实体/别名，按需要加入语义召回；对候选及最终输出校验来源。全库完整性审计独立执行，明确区分候选总数与已验证数。问“现在多少钱”应检查当前依据，问“当时多少钱”应能返回历史版本。
5. **减少维护开销。** 查询内复用相同证据的校验结果；增量维护目录摘要和日志；给持久 Wiki 及其证据依赖提供完整备份/导出与恢复检查。

建议验收用例应包括：同网址正文变更、同网址无实质变化、无关书签变化、关联 Wiki 新修订、检查失败、旧资料的历史查询、更新中断与重试，以及引用撤回后的检索行为。性能验收应同时记录页数、证据体积和引用数量，避免只用短文本单 claim 样本。

## 复现

[离线审计脚本](/Users/kk/Downloads/bookmark-research-performance-20261010-lqvfqxgz/wiki_audit.py) · [原始生命周期结果与全部采样](/Users/kk/Downloads/bookmark-research-performance-20261010-lqvfqxgz/wiki-run/wiki-results.json)。脚本只调用模拟提供商，所有书签与网页正文均明确为合成数据；使用新输出目录执行：

```sh
wiki_audit_output=$(mktemp -d /tmp/bookmark-wiki-audit.XXXXXX)
python3 -B /Users/kk/Downloads/bookmark-research-performance-20261010-lqvfqxgz/wiki_audit.py \
  --plugin-root /Users/kk/.codex/plugins/cache/bookmark-research/bookmark-research/0.5.0-beta.9 \
  --output "$wiki_audit_output"
```

相关回归命令：`python3 -B -m unittest discover -s tests -p 'test_wiki*.py'`，22 项通过，耗时 1.325 秒。此轮仅增加审计报告与隔离脚本，未将建议变为插件运行时修改。
