# 经审阅的 Wiki 与有标注的研究评测

[English](wiki-quality.md) · **中文**

宿主负责撰写、审阅知识页；插件保存证据和修订，核对完整性并检索整理后的正文。评测使用明确标注的输出，不调用模型，也不从文字匹配推断语义支持。

## Wiki API

`WikiStore(directory=None, settings=None, research_sessions=None)` 优先使用显式目录，其次 `settings.wiki.directory`，默认数据目录中的 `wiki/`。插件目录和画布包目录会被拒绝。研究证据仍保存在原研究档案中，位于输入包之外。

```python
from wiki import WikiStore

wiki = WikiStore(research_sessions=sessions)
page = {
    "title": "可复用会话",
    "kind": "topic",  # 也可为 entity
    "sections": [{
        "heading": "已确认行为",
        "text": "宿主已审阅的综合说明，保留相关限制。",
        "claims": [{"research_id": research_id, "claim_id": "c1"}],
    }],
    "links": [],
    "review": {
        "method": "model",  # 也可为 human
        "reviewer": "真实模型及版本或人工审阅者",
        "note": "说明实际检查的范围和证据支持。",
    },
}
written = wiki.write("reusable-sessions", page, "整理已审阅结论", expected_revision=0)
current = wiki.get("reusable-sessions")
wiki.write("reusable-sessions", revised_page, "解释新增限制", expected_revision=current["revision"])
```

每节必须明确引用研究 claim。只有 claim 仍有效、所有来源均为 accepted、引文存在于已存正文且正文哈希一致时才接受。Wiki 快照保留 research ID、claim ID、source ID、原清单 ID、书签实例引用、原样引文、审阅、检索元数据和产物哈希。每页最多 24 个不同 claim，过大主题需拆分。

审阅声明说明正文是否受支持、实体与范围是否正确、是否保留不确定性和反证。程序记录声明及 rubric，不能证明署名的人或模型实际做了判断。写入成功不是独立语义认可。

导入的外部报告始终是二手证据，保留其 provenance 与报告原句；参考文献不会被扩充成声称已读的原始网页或覆盖来源。

### 修订、链接与检查

每次更新在 `revisions/<page_id>/` 写入不可变 JSON 和渲染 Markdown，再原子更新 `index.json`。索引是发布点。发布失败可能留下未引用文件，旧版仍可读取。expected_revision=0 用于创建；更新必须指定调用者实际读过的版本。写入中断后先检查当前 revision，再判断是否重试。

交叉链接形如 `{"page_id":"existing-page","relation":"宿主对关系的解释"}`，目标页必须已存在。渲染链接指向写入时的目标版本，保留历史含义。目标后续变化会产生 lint 提示，宿主可明确修订关系。旧页版本可通过 `get(page_id, revision=N)` 读取。

| 方法 | 返回 |
| --- | --- |
| `write(page_id, page, change_note, expected_revision=0)` | 修订元数据与绝对产物路径 |
| `get(page_id, revision=None)` | 正文、证据快照、更新记录与当前 provenance 核验 |
| `list(offset=0, limit=20)` | 当前页元数据的分页 |
| `lint(page_id=None)` | 来源审阅、有效 claim、引文、哈希、链接和历史问题 |
| `search(query, offset=0, limit=10)` | 匹配当前 Wiki 正文，排除已失效的页 |

Lint 检测后续来源拒绝、结论撤回、来源／claim 变化和缺失／改动的产物。历史正文保留并标记过时，明确返回 `semantic_support:"not_scored"`。

检索匹配标题、章节标题和整理后的正文，采用忽略大小写的字面词匹配（包含中文子串）及简单出现次数排序。仅保存 provider 摘录不会使它成为可检索的 Wiki 知识。没有 embedding 检索或语义重排，也不会未经实际问答评测就选择它们。

## 质量评测输入

`evaluation.evaluate(suite, runs, judgments=None)` 只计算传入数据。完整可运行输入为 [research-quality.json](https://github.com/Browser-bookmark-hub/Bookmark-Research/blob/main/tests/fixtures/research-quality.json)，源码和验证包也包含 `tests/fixtures/research-quality.json`。

- **suite** 定义任务、原始来源／问题 ID、金标准和版本化 rubric。gold_answers:null 表示没有答案集合基准。rubric 定义答案身份匹配、引用支持和 0–4 分的报告维度。
- **run** 记录 task、system、mode、repeat、最终报告、原子答案／claims／citations、覆盖 ID 和测量，并保留模型、工具、预算、输入快照／版本、时间窗口及宿主版本。引文按唯一 claim/source 对计算。
- **judgment** 标识 rubric 版本与真实人工／模型评审者，给出预测答案到 gold ID 的匹配、supported/unsupported/uncertain 引用标签及理由、报告维度分数及理由。合成样例的评审必须自报 synthetic。

答案匹配是标注任务。评审者必须阅读真实预测，核对身份与范围；错误实体用 gold_id:null。评分器不猜别名，也不把正则匹配当语义裁判。多个预测匹配同一 gold 实体时，集合 precision/recall 只计算一次；未匹配预测算假阳性，重复匹配另行报告。

每条引用判断针对完整命题及来源上下文，包括身份、日期和范围。supported 表示文本支持命题；unsupported 与 uncertain 都留在完整准确率分母中。原句匹配不能代替支持性判断。

### 指标与缺失信息

| 输出 | 含义与边界 |
| --- | --- |
| 答案 precision、recall、F1 | 需要金标准与完整答案匹配，否则 null |
| 语义引用准确率 | 完整标注时为 supported／全部引文；局部标注另行显示 |
| 结论语义支持 | 全部引文已标注后，有 supported 引文的 claim／全部 claim |
| 引用存在率 | 有任意引文的 claim／全部 claim，仅是结构指标 |
| 报告质量 | 全部 rubric 维度已评分时，将提供的 0–4 分均值归一化 |
| accounted/text/reviewed 覆盖 | 各自相对原始来源集合计算，失败来源仍留在分母 |
| 问题覆盖 | 已记录回答的问题 ID／原始问题 ID，不判断答案真假 |
| 成本与时延 | 提供的美元／秒，注明 observed、reported 或 synthetic；未知保持 null |
| 重复运行波动 | 相同声明条件下的数量、均值、样本方差、样本标准差和极差 |

覆盖必须满足 reviewed ⊆ text ⊆ accounted ⊆ original scope。报告的 ID 仍需证据审计，输入标签本身不证明实际阅读。插件无法取得的外部工具和模型用量保持未知。

比较按同一任务分组。模型、工具、预算、输入版本、时间窗口、宿主、评审者或测量依据不同会被披露，并分开聚合。未知预算不能声称受控比较。只有一次观察时没有方差估计，缺失费用不会当 0 求均值。失败和未完成输出仍保留在运行集合中。

输出固定 suite、run 和 judgment 哈希，保留评审者／rubric 身份及 null 分数原因。它不会生成 provider 排名、因果结论、RACE／FACT 分数或公共榜单分数。声称研究质量提高需要真实任务运行与可辩护的独立标注。

## 重现离线演示

以下命令需要源码或验证包；运行时导出带指南，但不含测试资料和验证脚本。

```sh
python3 -B scripts/verify_quality.py
python3 -B -m unittest discover -s tests -p 'test_wiki.py'
python3 -B -m unittest discover -s tests -p 'test_evaluation.py'
```

验证脚本在数据目录的新运行目录下写入 inputs.json、evaluation.json 和可读的 evaluation.md。`--output /absolute/external/directory` 可另选目录；`--fixture /path/input.json` 接受含 suite、runs、judgments 和可选已知样例期望的包装对象。

示例包含四条虚构来源、两个 gold 实体和六份手写输出，标成 direct、workflow、professional。一个来源不可用，部分输出遗漏或虚构答案，一个引文范围不确定。费用和时长是合成值，其中一个费用故意未知。这些情况验证分母、语义标签完整性、重复方差及缺失测量，**不测量这三条路线或任何真实宿主／模型／服务**。

Wiki 测试另覆盖不可变历史、索引发布失败、交叉链接、中文正文检索、来源拒绝／结论撤回、二手报告 provenance 及来源／包边界。真实宿主研究、专业服务比较和独立语义评审仍是另外的验证工作。
