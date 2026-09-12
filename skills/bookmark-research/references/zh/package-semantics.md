# 书签画布阅读协议

[English](../package-semantics.md) · **中文阅读版**

这是插件内置的分析规则，涵盖 JSON 模式的文件、字段和关系；运行时导入器不读取 `AGENTS.md`。已知格式的包即使没有该文件，也能索引和查询。包内指南有新约定、字段语义冲突或用户要求核对时，才针对问题查阅原指南与实际数据；本参考不替代载体已加载且适用的目录指令。

## 文件与字段

栏目 JSON 的 `format` 为 `bookmark-canvas-section`，`sectionType` 区分 `permanent` / `temporary`；文件分别位于 `永久栏目/`、`临时栏目/`。入口 `.canvas` 保存 `nodes[]`、`edges[]` 与文件映射。JSON 模式的栏目正文不在独立 Markdown 文件里。

一个来源对应一个逻辑画布，每次提供的目录最多有一个入口 `.canvas`。对同一 `source_id` 提供改名后的入口时，会替换此前的画布布局记录；局部导出没有入口时继续保留此前布局。

| 用户概念 | 原始结构与查询方式 |
| --- | --- |
| 永久栏目卡片 | JSON 的 `slot` 是槽位，`title` 是标题，`tree` 是浏览器书签树快照；`section=A` 等可限定范围 |
| 临时栏目卡片 | JSON 的 `id`、`label`、`title`、`tempKind`、`source`、`items`；属于独立书签沙盒，`label` 可重复，不是唯一 ID |
| 书签与文件夹 | `children` 表达树层级，保留节点 ID、父子关系、同级顺序、标题、URL；临时项用 `type:folder/bookmark`，`sectionId` 对应所属栏目 |
| 永久节点身份 | `tree.id/parentId` 使用 `syncId_*`；浏览器根目录由 `folderType`、`syncing` 标识，这些 ID 不是本机 Chrome 数字 ID |
| 标签与笔记 | 永久项按 `identityMap[].syncId` 关联树节点；临时项的 `tags`、`note`、`noteColor` 直接在 item 上；文件夹也可以有这些元数据 |
| 副本卡片 | `fileRole:copy-anchor` / `inheritFrom` 指向主树；保留卡片自己的描述，复用主树，不复制计算书签总数 |
| 栏目说明与空白卡片 | `descriptionMd` 描述当前栏目；`.canvas` 的 `type:text` 节点保存 Markdown／安全 HTML 文本；都是上下文，不算书签 item |
| 卡片组 | `.canvas` 的 group 节点；完整几何包含关系确定组成员，不把视觉重叠自动认作成员 |
| 连线 | `.canvas.edges` 的端点与箭头定义方向，`edges[].label` 是关系文字；不要与栏目的 `label`、组的 `label` 混用 |
| 原始属性 | `raw_json` 保留未识别字段；`get_context` 的 section 头省略整棵树以限制重复输出 |

`tags` 是 `{color,text}` 数组，按颜色与文字的组合区分标签；`note` 是单条纯文本，`noteColor` 是它的并列字段。只有 note 而没有 tags 的元数据仍然有效。旧数据有 note 而无 noteColor 时显示颜色默认 `orange`。tag/note 的七种色名（red、orange、yellow、green、blue、purple、gray）与 `.canvas` 颜色是两套字段；颜色本身不能证明业务分类。

文件节点的 `file` 与 `inheritFrom` 使用 vault 相对路径，可能包含包名和 vault 子目录前缀，也可能直接从 `永久栏目/` 或 `临时栏目/` 开始。导入器按包内文件映射解析，不能把同名、断链或多义引用默认为任意一个匹配；外部附件不是栏目书签数据。

## 关系如何解释

- 普通链式标号 `A-1 → A-1-1` 是派生关系线索；子链可能承接大部分内容，也可能只保留子集。A/B 来源族只反映创建时线索，不能推断临时树与永久树一直同步，或凭标号虚构持久关联。结合说明、标题、URL 和实际 item 核对。
- 卡片组没有显式 `children` 清单，嵌套关系来自 `x/y/width/height` 的完整包含。组中放的是画布节点；书签通过所属栏目获得组上下文，不代表每个书签都有单独的画布节点。
- 边默认从 `fromNode` 指向 `toNode`（`fromEnd` 默认为 none，`toEnd` 默认为 arrow）。读取返回的 `direction` 及原始端点：forward、reverse、both、none；有 `label` 时结合文字解释，没有时只陈述连接，不能自动解释成依赖、竞争或推荐。
- 文件夹、组、链式标号、tag、note 与说明是不同层次的分类线索。清晰时沿用用户分类；相互冲突时指出冲突并区分推测与已存事实。分析请求本身不要求重组原数据。

## 查询与计数

`source_id` 是逻辑画布的索引命名空间；定位具体项时保留 `source_id + section_id + item_id`。相同 URL 出现在不同栏目、路径或多个 item 中，仍是多个书签实例。书签数、去重 URL 数、公司数需要分别计算和说明。

永久副本 B 查询复用 A 的主树，但 B 有自己的说明与画布位置。逐卡片展示的 `bookmark_count` 可指向同一棵树，不能直接相加成整个库的唯一书签数；引用副本上下文时同时保留主树来源。

同时限定 `section` 与 `group_id` 时，先取实际卡片的交集，再解析副本所用的主树。只有 B 在组内时，指定 A 与该组的查询不会命中；指定 B 则返回其共享的书签。

`search_bookmarks` 只对书签标题、URL、note、tag 文字、文件夹路径做 SQL 子串匹配，加上栏目／组／文件夹／tag 过滤。它不搜索 `descriptionMd`、text 节点或 edge label；这些用 `get_context` 读取。短词会误匹配，例如 Exa 也会命中 URL 中的 examples，应检查结果字段并按上下文筛选。

`tags` 过滤器仅匹配文字；颜色保存在返回的 `tags[].color` 中。按颜色与文字组合统计时，需完整分页读取候选后按同一个 tag 对象筛选，不能把第一页的筛选数当作总数。

`section` 可以匹配 ID、slot、label 或文件路径；同一个 label 可能选中多张卡片，要唯一定位时用 section ID。`get_context` 不传 `item_id` 时返回栏目头、节点、组和边，`items` 为空不代表没有书签或文件夹。查询文件夹内书签，先从一个命中项的 `ancestors` 取文件夹 ID；需要完整文件夹清单时，读取相关栏目原 JSON，当前接口没有独立的文件夹列表工具。

已有 FTS5 派生表，但公开查询未使用 BM25 排名、embedding、网页正文检索或任意 SQL。未知字段保存在原始对象中，不意味着已有对应过滤器或模型理解规则。

## 同步与留存

`sync_package`／CLI 接受目录、ZIP 和单卡 JSON，保存原始快照、文件哈希与解析结果。快照来源在原导出移走后仍可查询；持续目录在 MCP 存活期间后台检查，默认查询前也会补查。坏 JSON、非法路径或循环引用失败并回滚。live 来源不可用时默认查询报错，用户允许使用旧索引才用 `refresh=false`。来源身份、模式、版本恢复与状态见 [来源生命周期](source-lifecycle.md)。

`completeness:partial` 中缺少某文件不意味着删除，保留未出现文件并在 sync 中列出；已提供的完整栏目内删除的 item 正常同步删除。`complete` 只用于明确完整的镜像，才删除缺失文件对应的记录；单卡固定为 partial。留意 `retained_missing_files`，不要宣称本次局部输入就是所有源数据。

栏目保留稳定 ID 而文件改名时，索引更新文件映射并移除被替代的旧路径哈希；随后改回原名也会重新解析。局部导出省略画布或副本文件时，沿用此前已解析的稳定栏目关系，并警告引用来自较早文件；一旦提供该文件，就以它实际写入的路径为准。原包中的 `.canvas.file` 与副本 `inheritFrom` 仍须与实际文件路径一致，索引不会代替源包修正引用。

来源身份独立于路径，同一画布的新导出沿用 `source_id`，已登记路径形成别名。managed snapshot 保存合并后的必要原始文件及已解析关系，可以通过 `source_history` 找到路径并恢复到新索引；不再要求用户凑齐历次局部导出。研究 inventory 保持冻结，来源变化通过研究／Wiki 的复核提示说明。

JSON/.canvas 始终是事实来源，SQLite 保存派生状态与来源登记。后台检查只处理本地文件，没有后台网页监控。数据库、原始快照、研究报告、路径别名与来源清单均在同步包之外。读取任务不触发原目录整理或生成流程。

## 依据与维护

阅读规则版本：`2026-09-09`。协议依据为 Bookmark Canvas 的公开 [AGENTS 模板](https://github.com/Browser-bookmark-hub/Bookmark-Canvas/tree/main/Bookmark-Canvas-main/history_html/transfer_AI_sync/AGENTS_template)；本参考提取适用于分析的格式语义，不绑定某个使用者的数据包、内容或文件路径。维护时核对上游协议与解析器，运行查询不需要访问该链接。

| 协议指南内容 | 本插件吸收的位置 |
| --- | --- |
| A1–A8、A9 的文本含义、R1/R6/R7 的读取语义 | 本参考的文件、字段、身份和关系规则 |
| S8、S7 的分析线索 | 本参考的关系判断、临时别名与来源定位 |
| S6 联网调研 | [研究与服务接入规则](research-workflow.md) |
| S1/P2 的相关存储边界与局部导出语义、P1 长期规则 | 本参考的同步边界与版本维护 |

当前测试覆盖的 `schemaVersion`：永久主树 3，永久副本锚点 2，临时栏目 2。导入器按实际字段校验，并非覆盖所有未来版本的 schema 验证器。新版本若改变含义，需要核对协议与解析器；只改文档不能增加程序能力。

创建／修改栏目、ID 生成、tag/note 写入、布局调整、导入前检查等规则留给未来的生成 Skill；该 Skill 可复用本阅读协议，再加入写入规则与验证程序。当前插件未提供这些生成能力。
