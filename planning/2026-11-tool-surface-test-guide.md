# Tool Surface 验收与速度测试

本文用于当前 `0.6.x` 本地包验收和 legacy/quick 对照。测试数据必须来自同一份 Canvas/Wiki/Git 快照；将占位符替换成实际 URL、卡片、仓库和目标 ref 后，冻结问题文本，不要在两个工具面之间改写。

## 1. 全量单测

在隔离用户目录下运行，避免写入真实 `~/.local/share` 或 `~/.config`：

```sh
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
export XDG_CONFIG_HOME="$TEST_ROOT/config"
export XDG_DATA_HOME="$TEST_ROOT/data"
export BOOKMARK_RESEARCH_CONFIG="$TEST_ROOT/config/bookmark-research/settings.json"
export BOOKMARK_RESEARCH_DATA_DIR="$TEST_ROOT/data/bookmark-research"
python3 -B -m unittest discover -s tests -p "test_*.py"
```

记录通过数、失败数、error 数和 skipped 数。失败若仍指向真实 home 路径，先检查测试是否显式覆盖了 `XDG_*` / `BOOKMARK_RESEARCH_*`；不要把权限 error 直接计作代码通过。

## 2. 本地 npm 包

不发布 npm。当前工作区包是 `.bench/bookmark-research-0.6.4.tgz`。用隔离的 Codex 配置目录模拟 npx 安装：

```sh
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
export CODEX_HOME="$TEST_ROOT/codex"
export BOOKMARK_RESEARCH_CONFIG="$TEST_ROOT/config/bookmark-research/settings.json"
export BOOKMARK_RESEARCH_DATA_DIR="$TEST_ROOT/data/bookmark-research"
npm_config_cache=/tmp/bookmark-research-npm-cache npx --yes --package "$PWD/.bench/bookmark-research-0.6.4.tgz" bookmark-research doctor
npm_config_cache=/tmp/bookmark-research-npm-cache npx --yes --package "$PWD/.bench/bookmark-research-0.6.4.tgz" bookmark-research install codex --non-interactive
```

如需重打当前工作区包：`npm pack --cache /tmp/bookmark-research-npm-cache --pack-destination .bench`。确认包内 CLI 能启动、安装自检能识别新原语目录，并且宿主配置只写入临时 `CODEX_HOME`。若 `package.json` 版本变化，同步替换 tarball 文件名。Codex/Claude/dsh 的真实宿主 verify 另行记录，不以单测替代。

## 3. 准备速度测试

模板文件：[.bench/ladder.json](../.bench/ladder.json)。它目前只有题目槽位，尚未填真实 prompt、目标 ref 或 traces。每个任务在 `legacy-25` 与 `quick-10` 各执行 3 次，共 90 次运行。模板的 `required_tool_scope` 是该轮 MCP 进程应使用的 `BOOKMARK_RESEARCH_TOOL_SCOPE` 名单；quick 轮用默认 quick 面也可以。

固定模型、宿主版本、仓库/数据快照、网络条件和提示文本。每次记录工具调用步数、wall time、目标是否命中、引用数、响应截断/续读情况、provider 覆盖缺口。交替运行两种面或随机顺序，避免只把缓存热身收益算给后一组。写操作任务每次使用独立临时 Wiki/数据副本。

Legacy preset 恢复旧 25 个工具名，但使用当前版本带弃用标记的 schema 描述；它是名称集对照，不是旧版 tools/list 字节级重放。0.7.0 起 legacy preset 会被关闭。

### L1 精确定位

1. 精确 URL：`在本地书签中查找这个 URL：<真实 URL>。给出命中的标题、所属文件夹和来源版本；没有命中就明确说未命中。` 目标 ref：`<ref>` / 无命中。
2. 精确标题：`查找标题为“<真实卡片标题>”的书签，读取该卡片和它的文件夹祖先，不要展开整节内容。` 目标 ref：`<ref>`。
3. 精确无结果：`查找“<确认不存在的唯一字符串>”，说明是否命中；不要用近似标题猜测。` 目标 ref：无。

### L2 模糊检索与元数据

4. 中英与 Note：`我记得有个和“<主题>”有关的书签，可能写作 <中文别名>/<英文别名>，而且卡片带 Note。找出目标并说明命中词和字段。` 目标 ref：`<ref>`。
5. 数字/字母变体：`找出提到 <3D/2D 或真实变体> 的书签；我记不清原文写法，可能是“三D/二D”。列出最相关的命中和 why。` 目标 ref：`<ref>`。
6. Tag 过滤：`在包含标签 <真实标签> 的书签中查找 <主题词>，说明标签条件和文本命中分别是什么。` 目标 ref：`<ref>`。

### L3 空间关系

7. 出向连接：`从 <起始卡片 ref> 出发走一层，列出它通过画布连线直接指向的节点，并标明方向。` 目标节点：`<node ref/id>`。
8. 分组关系：`<目标卡片 ref> 属于哪个组？给出组名、包含关系和所在 section。` 目标组：`<group ref/id>`。
9. 两跳路径：`判断 <卡片 A ref> 是否能沿画布关系到达 <卡片 B ref>；若能，给出最短路径和每条边的方向。` 目标路径：`<预期节点/边序列>`。

### L4 时间与 Git

10. 最近新增：`在 <source id> 中找出过去 7 天新增的 <主题> 书签，列出 added_at 日期和来源版本；日期缺失时明确说明。` 目标 refs：`<refs>`。
11. Git 时间线：`检查仓库 <真实仓库路径> 最近 7 天的提交，找出改变 <文件/Canvas 节点> 的提交，并区分 Git commit 时间与导入快照时间。` 目标 commit：`<sha>`。
12. 快照差异：`比较 <当前 live source> 与 <冻结 snapshot/version> 中 <目标卡片 ref> 的变化，给出字段差异和各自版本，不要把两种时间线混为一谈。` 目标版本/字段：`<预期>`。

### L5 调研与沉淀

13. 搜索回流：`围绕 <真实问题> 搜索官方资料和一个独立来源；说明覆盖到哪些子问题、哪些 provider 失败，再把宿主搜索结果归并并保留来源。` 目标来源/缺口：`<预期>`。
14. 多 URL 阅读：`读取这 3 个已知 URL：<URL 1>、<URL 2>、<URL 3>。比较它们对 <问题> 的证据，区分可引用正文与不可用页面，并给出逐字引用。` 目标引用：`<预期 quotes>`。
15. Wiki 复用：`根据 <来源 refs> 回答 <问题>，创建或更新 Wiki 页面 <测试专用 page id>，写入可核验引用；随后读取刚保存的 revision 并确认来源仍可追溯。` 目标 revision/引用：`<预期>`。

## 4. 结果记录

每题的三次运行都写入 `.bench/ladder.json` 的对应 surface/run，不能只保留中位数：

| 字段 | 记录方式 |
|---|---|
| steps / wall_seconds | 宿主实际工具调用数与端到端秒数 |
| target_refs / found_refs | 预先冻结目标和实际返回 ref |
| Q1 | 引用 quote 是否逐字存在于指定 source text/capture |
| Q2 | 对中位步数那次输出逐条标 claim、source_ids、supported |
| Q3/Q4/Q5 | 非 usable 内容误引、无续读截断、未声明 provider/target 缺口的次数 |

速度结论看 15 题的中位步数，并检查至少 3 类任务重复受益。Q1/Q3/Q4/Q5 任一不达门槛，或 Q2 未完成人工标注时，不得判定 P0 通过。
