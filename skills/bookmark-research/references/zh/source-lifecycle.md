# 来源接入、快照与持续同步

[English](../source-lifecycle.md) · **中文阅读版**

输入载体与来源寿命分别选择。目录或 ZIP 可以是一次导出的快照；单个永久／临时卡片 JSON 是局部输入；Git 同步到本地的目录可以是持续来源。栏目的 permanent/temporary 不决定来源是否持续同步。

## 登记与识别

`sync_package(package_path, source_id?, mode?, completeness?)` 和 CLI `sync` 共用实现：

| 参数 | 行为 |
| --- | --- |
| `package_path` | 接受协议目录、ZIP、单个 `bookmark-canvas-section` JSON。ZIP 可有包装目录，但只能包含一个画布包；只有一张卡片的 ZIP 也可导入。 |
| `source_id` | 稳定的逻辑来源身份。省略时复用已登记路径的关联；新路径生成 ID。移动、改名或新日期导出同一画布时显式沿用原 ID，以后这些路径都会记住关联。 |
| `mode: snapshot` | 保存原始协议文件及派生索引，查询使用已接入快照，原下载目录或压缩包移走不影响查询。 |
| `mode: live` | 只接受目录，查询前检查变化；MCP 存活期间后台检查，按哈希增量同步。 |
| `completeness: partial` | 默认。未提供的文件继续保留；已提供的完整栏目内删除的 item 正常删除。 |
| `completeness: complete` | 明确的完整镜像，同步删除缺失的栏目和画布文件；单卡不能使用此模式。 |

新的普通目录、ZIP 和单卡默认 `snapshot`；Git 仓库中的目录默认 `live`，完整性仍默认 `partial`。已有来源沿用登记的模式与完整性；单卡自动使用 `partial`。旧版来源保留 `live + partial`，转成快照时显式重新登记一次。

用户说“这是同一个画布的新导出”时，先从 `index_status` 取原 `source_id`。当前导出协议没有可靠的全局画布 ID，不按标题、URL、槽位或相同栏目 ID 自动合并不同画布。同一路径登记过多个来源时，需要明确 `source_id`。这些是工具参数，用户正常用自然语言说明来源即可。

```sh
# 一次导出，以后沿用 my-canvas
python3 <root>/src/cli.py sync /downloads/export.zip --source-id my-canvas
python3 <root>/src/cli.py sync /downloads/card.json --source-id my-canvas
# 用户明确指定的完整 Git 同步目录
python3 <root>/src/cli.py sync /repos/bookmarks/canvas --source-id synced-canvas --mode live --completeness complete
python3 <root>/src/cli.py status synced-canvas
```

单卡更新已知来源时，以稳定栏目 ID 对应原文件路径，避免下载文件名改变导致引用断开。单独的副本锚点不包含主树；没有对应主树时报告未解析引用，不虚构书签。

## 快照和恢复

快照位于数据库旁的 `<数据库文件名>.sources/`，默认是 `index.sqlite3.sources/`。每个来源、每个内容版本有独立目录：`package/` 保存所有必要的 JSON/.canvas，包括局部导出保留的文件；`manifest.json` 保存哈希、输入位置和已解析的关系。原文件不改写，附件和无关文件不复制。

`source_history(source_id, limit?, offset?)`／CLI `history` 列出内容版本。内容及关系没变时复用同一版本；旧版本不覆盖、不自动清理。日常查询使用当前索引，`refresh=false` 并非历史版本选择器。

```sh
python3 <root>/src/cli.py history my-canvas
# 使用 history 返回的 snapshot_path，可在新数据库中恢复
python3 <root>/src/cli.py --db /data/recovered.sqlite3 sync /data/index.sqlite3.sources/<source>/<version>/package --source-id my-canvas --mode snapshot --completeness complete
```

恢复校验快照哈希并恢复组／副本关系。局部导出只改了栏目文件名、未提供新版画布时，关系映射单独保存在清单中，原始画布字节仍保留。旧版索引没有快照且原目录已消失时，可从 SQLite 保存的完整 JSON 恢复语义；`Recovered legacy JSON...` 警告表示原来的空白格式无法保留，输入哈希也会变化。

## 持续更新的时机与状态

MCP 连接后为已有 live 来源启动进程内检查；首次登记后也会启动。实现使用 Python 标准库轮询，默认每 1 秒检查协议文件，连续变化稳定 2 秒后同步；完整目录的文件删除需稳定 5 秒。借鉴的是 CodeGraph 的变化合并、待更新提示与重连补检查，未移植其原生文件事件监听器。

普通查询主动补查；有效且不涉及整文件删除的变化可以立即更新，删除仍等待稳定窗口。坏 JSON、非法路径、身份冲突或完整镜像中的未解析引用导致整次导入回滚。目录消失、暂时清空或 Git 写入锁存在时保留最后一次有效索引。空目录不自动清库；明确的空画布或空栏目可表达清空内容。手动 `sync` 是明确的导入动作，不使用后台删除等待窗口。

`index_status` 和本地查询的 `source` 返回以下状态：

| `state` | 含义 |
| --- | --- |
| `snapshot` | 已接入固定快照，不监控原下载文件 |
| `current` | 最近一次检查已同步；同时查看 `checked_at` |
| `pending` | 等待变化稳定或 Git 正在写入；`pending_files` 列出已识别的待更新文件 |
| `unchecked` | live 来源最近未检查，不能据此宣称已追上磁盘内容 |
| `unavailable` / `error` | 来源不可用或校验失败；`error` 说明原因，旧索引保留 |

默认 live 查询遇到 error/unavailable 返回错误；用户允许使用旧数据时用 `refresh=false`／`--no-refresh`。pending 查询可返回上次有效数据，必须同时说明待同步状态。新研究不会在 pending/error/unavailable 输入上冻结清单。

后台检查跟随宿主 MCP 进程，关闭后停止，重连后恢复，首次查询也会补查。独立 CLI 查询结束后退出，需要持续监控时运行 `python3 <root>/src/cli.py watch`，前台运行并用 Ctrl-C 停止。`watch` 支持 `--interval`、`--debounce`、`--deletion-grace` 秒数，输出状态变化的 JSON 行。使用一次性 CLI 的宿主不会自动获得常驻监控。

Git 拉取、推送和登录仍由原有同步系统或宿主负责，插件只读本地结果。多个 MCP 进程各用独立 SQLite 连接，由事务协调写入；查询使用一致的读取快照。ZIP 拒绝路径穿越、符号链接、重复成员和多包歧义；上限为单文件 64 MiB、总解压大小 256 MiB、10,000 个条目。

## 研究与 Wiki

索引更新不触发网页抓取、LLM 调用或 Wiki 改写。研究 inventory、正文和结论保持原版本。`research_status.source_freshness` 比较冻结输入与当前已同步索引，变化时 `requires_review=true`。Wiki 读取／lint 标注 `source_input_changed`，`wiki_get.validation.status` 为 `needs_review`，表示需要结合新输入复核，不直接判定旧结论错误。网页本身是否更新不在此检查范围内。

机制参考：[CodeGraph indexing](https://github.com/colbymchenry/codegraph/blob/main/site/src/content/docs/guides/indexing.md)、[watcher](https://github.com/colbymchenry/codegraph/blob/main/src/sync/watcher.ts)。这是公开文档与代码对照，未把 CodeGraph 运行测试当成本插件验收。
