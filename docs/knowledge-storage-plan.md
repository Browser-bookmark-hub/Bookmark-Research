# 知识库统一与研究结果位置计划

日期：2026-09-29。依据两次讨论：研究结果放在哪里、按 LLM Wiki 统一知识库。

## 决策

| 问题 | 决定 |
| --- | --- |
| 研究结果默认位置 | 统一目录 `<数据目录>/research`，路径可改 |
| 放在输入旁边 | 可选 `output.mode = beside_input`：单文件 `a.json` → `a.bookmark-research/`，文件夹或 ZIP `pkg` → `pkg.bookmark-research/`，一律同级，不进原文件夹 |
| 放不了时 | 退回统一目录并说明原因：没有输入文件（URL 列表）、多个来源、位置落在 git 仓库里、位置在画布包里、没有写权限 |
| 改设置 | 只影响新任务，旧任务不迁移；位置登记表 `research-locations.json` 保证新旧任务都能列出，不存在的标为 missing |
| agent 中间文件 | 只放 `<任务文件夹>/work/`，`research_start` 返回该路径 |
| 研究结束后整理进 Wiki | 默认 `wiki.after_research = suggest`：给出建议，经用户确认再写；可设 `auto` 或 `off` |
| Wiki 目录与日志 | 每次写入后自动生成 `wiki/index.md`（目录）和追加 `wiki/log.md`（时间线）；`index.json` 仍是准确数据 |
| 原始资料检索 | 新增 `search_archive`：SQLite FTS5 覆盖 `knowledge/` 归档和所有已登记任务的证据原文 |

## 对"原始资料只存一处"的调整

讨论时提出研究任务的证据改存进 `knowledge/`、任务只记引用。实施前发现它和"放在输入旁边"冲突：任务文件夹会依赖统一目录里的文件，搬走或放在输入旁边时报告链接和哈希校验会失效；冻结证据也是现有设计"任务文件夹可整体移动"的前提。

因此改为：

- 物理上，研究证据仍随任务保存（冻结、可移动），`knowledge/` 内对完全相同的正文去重（同一内容只存一份页面文件）。
- 逻辑上，`search_archive` 用一个全文索引覆盖两处，按内容哈希合并同一正文，结果列出所有出现位置。查原始资料只需一个入口。

## 分工

| 部分 | 文件 |
| --- | --- |
| 结果位置、登记表、`work/`、结束后的 Wiki 建议 | `src/research.py`、`tests/test_output_location.py` |
| 原始资料去重与 `search_archive`（MCP + CLI） | `src/archive.py`、`src/raw_library.py`、`src/mcp_server.py`、`src/cli.py`、`tests/test_raw_library.py` |
| Wiki `index.md`/`log.md`、向导问题、`status`、Skill 与 README | `src/wiki.py`、`src/onboarding.py`、`scripts/launcher.py`、Skill（中英）、README（中英）、`docs/details*.md` |

已先完成：`output` 与 `wiki.after_research` 配置和校验、`update_settings` 结构、`src/research_locations.py`。

## 验收

本机全量测试通过；CI 三系统通过；真实走一遍：统一目录研究、放在输入旁边研究、git 仓库内回退、改目录后旧任务仍可列出、`search_archive` 查到归档与证据、Wiki 写入后 `index.md`/`log.md` 更新。

## 完成情况（2026-09-29）

已实现上述全部内容。本机全量 482 个测试通过；隔离数据目录端到端验证：统一目录、放在输入旁边（文件夹、ZIP、单文件）、git 仓库内回退（仓库无新增文件）、URL 列表与多来源回退、单次指定目录、改目录后 9 个任务仍全部列出且删除的任务标为 missing、`search_archive` 中文查到研究证据、Wiki 写入后生成 `index.md` 并追加 `log.md`。
