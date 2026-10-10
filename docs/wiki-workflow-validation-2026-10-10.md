# Wiki 检索与整理恢复验证

> 本文保留本轮固定检索回放和安装记录。后续完整条件检查、文档修正与剩余升级项见 [2026-10-11 升级核对](upgrade-status-2026-10-11.md)。

日期：2026-10-10。基于 `0.5.0-beta.9` 工作区，承接 [上一轮修复验证](fixes-validation-0.5.0-beta.9.md)。

## 本轮结果

1. 技能增加检索决策：已知页面直接读；否则使用短而有区分度的词，必要时尝试少量同义词、别名或原文语言，查看目录摘要、相关页面链接，再回查归档。证据足够即停止扩展。继续使用现有 SQLite 字符索引和字面匹配。
2. 增加 `wiki_work` MCP 工具及 `wiki work` CLI，依据已保存资料和当前已提交修订，恢复待整理结论、发布回执和待复核页面。
3. 使用测试包中的六个公开来源，执行 20 道中英文问题的固定检索回放；新增十项工作恢复回归测试，并完成本地插件重新安装。

## 状态与更新

| 状态 | 含义 |
| --- | --- |
| `archived` | 材料已保存，尚无已识别的合格待写结论；不表示已阅读或审阅 |
| `pending` | 已审阅的有效结论尚未被当前完整 Wiki 修订引用；返回待整理 claim ID 和继续调用参数 |
| `compiled` | 对应结论或保存的正文被当前完整修订引用；返回实际页面、修订号与记录哈希 |
| `needs_review` | 页面有时效性／完整性问题，或研究任务／快照无法核验 |

`compiled` 不表示快照每段内容都已提炼，也不保证源站仍然最新。页面工作项另行检查时效性。原文归档与整理后的 Wiki 分开保存；抓取本身不会成为已发布的 Wiki。

工作项使用稳定的 `work_id`，可按 `research_id`、`capture_id`、`page_id` 定位，或按种类／状态分页。列表依据持久快照、可恢复研究回执和当前 Wiki 索引重建，不另存容易与实际提交失配的完成开关。未提交的孤立修订不算完成；索引已提交但响应丢失时，可以找回实际发布回执。快照引用的正文须通过哈希和来源归属校验，不能凭另一份完整研究副本掩盖原始归档损坏。

网页更新后，页面工作项提供已保存新证据的 `source_reads`。宿主读取、导入并审阅新材料，用 `expected_revision` 修订受影响页面；关联页面可能仍需单独复核。沿用已有 `wiki.after_research` 偏好和会话授权。`wiki_work` 是显式的本地检查，不在每次查询时全量执行，也不启动后台抓取、模型或发布任务。

实现入口：[wiki_work.py](../src/wiki_work.py)、[工作恢复测试](../tests/test_wiki_work.py)、[技能](../skills/bookmark-research/SKILL.md)、[中文使用说明](../skills/bookmark-research/references/zh/wiki-and-evaluation.md)。

## 六个来源与 20 道问题

六个 URL 均来自用户提供的书签画布包：

| 来源 | URL |
| --- | --- |
| A2A | https://github.com/google-a2a/A2A |
| Gemini CLI | https://github.com/google-gemini/gemini-cli |
| FlashMLA | https://github.com/deepseek-ai/FlashMLA |
| udocker | https://github.com/indigo-dc/udocker |
| Z.AI 定价 | https://docs.z.ai/guides/overview/pricing |
| MCP | https://www.anthropic.com/news/model-context-protocol |

来源通过当前仓库运行时抓取并归档，使用三个并发工作线程。抓取时间为 2026-10-10 09:42:21–09:42:29 UTC。保留 capture ID、URL、抓取时间和 SHA-256；用于回放的文本与归档哈希核对一致。提供商可能返回缓存或部分提取文本，例如本次 udocker 提取为 18,000 字符；引用片段实际存在，不将其描述为完整网页或源站实时验证。

在隔离的临时资料库中，以这些实际提取文本和精确引用建立六篇人工整理的 Wiki。问题、查询步骤、别名、页面链接和预期目标在执行前固定，包括中英文表达、跨页比较、两道原文回查以及一道资料缺失问题。预期目标仅用于评分，不参与检索或停止条件。回放过程不联网，不改用户 Wiki。

| 固定方案 | 完整命中问题 | 预设目标召回比例 | 本地耗时中位数 | 调用数 |
| --- | ---: | ---: | ---: | ---: |
| 每题首次预设查询 | 11 / 20 | 52.38% | 5.993 ms | 20 |
| 预设补充词／关联页／原文回查步骤 | 20 / 20 | 100% | 6.662 ms | 33 |

这是人工选取、使用预设查询步骤的小样本诊断，不是旧版与新版模型的盲测，也没有评判回答语义正确性。结果说明这些检索路径在所选问题上有效，不能外推为通用召回率、自由问答准确率或引入向量检索后的效果。耗时仅为六页小库的暖缓存本地检索，不含建库、联网、模型推理和完整回答。

三个控制检查均通过：时间推进 31 天后检索提示复核；同一页面的工作项变为待复核；破坏临时证据副本后，相应页面从检索结果排除。诊断脚本在检索目标漏召回或控制检查失败时返回非零退出码。

固定输入：[wiki-retrieval-questions.json](../tests/fixtures/wiki-retrieval-questions.json)。回放脚本：[verify_wiki_retrieval.py](../scripts/verify_wiki_retrieval.py)。

```sh
python3 scripts/verify_wiki_retrieval.py \
  --sources-dir /Users/kk/Downloads/bookmark-wiki-workflow-20261010-rd3bs2k6 \
  --output /Users/kk/Downloads/bookmark-wiki-workflow-20261010-rd3bs2k6/retrieval-results.json
```

## 自动检查

- 完整单元测试：`python3 -m unittest discover -s tests -v`；631 项，628 通过、3 跳过，114.138 秒。
- 十项新增回归覆盖：归档到发布及重启恢复、部分结论整理、未审阅材料、指引不等于发布、提交前中断、提交后响应丢失、新正文和关联页复核、刷新失败、研究证据与原始归档损坏、限定页面／分页／参数校验，以及 MCP 与 CLI 一致性。
- 三项跳过沿用原配置：原生 Pi/DSH 检查需要 `BOOKMARK_NATIVE_HOST_BIN`；另外两项发布包检查需要显式启用并下载 npm 来源。
- `skill-creator/scripts/quick_validate.py skills/bookmark-research` 通过。
- `plugin-creator/scripts/validate_plugin.py` 对仓库和导出插件均通过。
- `git diff --check` 通过。
- 原测试包逐文件 SHA-256 比对：7 个文件完全一致，无新增、删除或内容变化。

## 实际本地安装

安装版本：`0.5.0-beta.9+codex.20261010100243`，基础版本保持 `0.5.0-beta.9`。

使用既有安装导出助手刷新受管理的本地 bundle，再使用 `plugin-creator` 的 cachebuster 助手和 `codex plugin add bookmark-research@bookmark-research --json` 重装。安装前保存旧 bundle、origin 和插件清单。已有 marketplace 条目内容不变。

安装后确认：插件已安装、已启用；35 个运行时代码文件及 25 个技能文件与工作区逐一哈希一致；隔离资料目录中的实际 MCP 进程返回 42 个工具，包含 `wiki_work`，其调用成功返回空的只读工作清单。`fetch_web` 的安装后 schema 也包含快照续读与总输出预算参数。

安装目录：`/Users/kk/.codex/plugins/cache/bookmark-research/bookmark-research/0.5.0-beta.9+codex.20261010100243`。

当前对话已经加载的旧 MCP 进程不会因重装自动替换；新建对话后加载本轮技能和工具。

## 本地验证产物

目录：`/Users/kk/Downloads/bookmark-wiki-workflow-20261010-rd3bs2k6`。

- `full-tests.log`：完整回归日志。
- `retrieval-results.json`：逐题结果、固定方案统计、来源归属及控制检查。
- 六组 `*-source.json` 与 `*-fetch.json`：回放使用的实际抓取材料。
- `package-before.json`、`package-after.json`、`package-verification.json`：原包完整性记录。
- `install-result.json`、`install-verification.json`、`installed-mcp-smoke.json`、`installed-file-hashes.json`：实际安装与工具核验。
- `preinstall-bundle.tar.gz`、`plugin-list-before.json`、`marketplace-before.json`：安装前备份。

该目录另有测试包书签清单，属于用户本地资料，不作为公开测试夹具提交。
