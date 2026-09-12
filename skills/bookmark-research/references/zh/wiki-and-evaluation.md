# Wiki 与研究质量评测

[English](../wiki-and-evaluation.md) · **中文阅读版**

Wiki 是经审阅的跨来源知识，正文归档是原始证据，两者分别保存。评测计算已有运行和标注，不会替模型执行研究，也不自动判断引用语义。

## 从研究整理 Wiki

使用 `research_source` 读正文、`source_review` 接受有效材料、`claim` 保存原子结论。把相互支持或冲突的结论组织为主题／实体页；保留版本、条件、反证和未解决项，不把来源堆叠成无结构摘录。

`wiki_write` 的输入示例（替换为本次实际内容与 ID）：

```json
{
  "page_id": "research-execution",
  "expected_revision": 0,
  "change_note": "将已审阅研究整理为主题页",
  "page": {
    "title": "研究执行方式",
    "kind": "topic",
    "sections": [{
      "heading": "可用能力与边界",
      "text": "由下面结论支持的综合说明，保留限制与不确定性。",
      "claims": [{"research_id": "r-实际ID", "claim_id": "c1"}]
    }],
    "links": [],
    "review": {"method": "model", "reviewer": "实际评审模型与版本", "note": "说明实际核对的页面身份、引用语义和范围。"}
  }
}
```

kind 为 topic 或 entity。每节必须有有效 claim；每页至多 24 个不同 claim，过大主题拆成有明确关系的页面。写入检查 claim 未撤回、来源 accepted、原句存在和正文哈希。`review` 如实记录谁做了语义核验；程序不能证明该核验已经发生。

标题、章节、综合正文和审阅说明使用本次任务要求的语言。标识符与原始引用保持原样，译文另列。

先写被引用的实体／主题页，再用 `links:[{page_id,relation}]` 建立关系。更新先 `wiki_get` 读当前 revision，将它作为 `expected_revision` 写入；冲突时重新读取合并，不覆盖他人更新。历史修订和当时引用目标版本保持不变。

`wiki_get` 返回正文、结论与来源映射、书签实例和 inventory ID。`wiki_lint` 检查哈希、撤回／拒绝、源材料变化、链接与版本问题；`semantic_support:"not_scored"` 表示它不是语义裁判。旧证据失效的页保留历史，但 `wiki_search` 不把它作为当前可靠知识返回。

`wiki_list` 和 `wiki_search` 分页返回；搜索对象是整理后的标题、章节和正文，采用字面词匹配，可查询中文。保存一份网页正文不会自动写 Wiki；当前不提供 embedding、向量检索、重排或监控。Wiki 默认数据目录 `wiki/`，可通过 `settings.wiki.directory` 改路径，不能放回原包。

## 评测真实运行

在同一问题、冻结输入和可比较预算下分别运行宿主普通研究、宿主工作流、专业服务；记录实际模型、工具、宿主版本、输入版本、时间窗口、失败和可获得用量。无法等同的条件写明，不删失败样本，也不把未知成本当 0。

独立评审者按版本化 rubric 阅读真实报告和证据，提供：

- 每个原子答案与 gold answer ID 的对应；错误项标 null，没有标注保持未知。
- 每个 claim/source 引用对的 supported、unsupported 或 uncertain 标签与依据；原句子串匹配不等于语义支持。
- 报告各维度 0–4 的实际评分与理由，包括事实可靠性、完整性和不确定性处理。

调用 `evaluate_research`，输入 `{suite,runs,judgments}`。suite 定义 task、gold answers（无金标准可为 null）、原始来源／问题 ID 与 rubric；runs 保存原子答案、结论、引用、覆盖、最终文本、条件与测量；judgments 保存真实评审者身份、版本及上述标签。完整输入说明见插件根目录 `docs/wiki-quality.zh.md`，源仓库的 `tests/fixtures/research-quality.json` 是明确标记、可运行的合成样例。

| 输出 | 必要依据与边界 |
| --- | --- |
| 答案 precision／recall／F1 | 金标准和完整答案匹配；缺失时 null |
| 语义引用准确率 | 完整语义标签，uncertain 仍在分母；部分标注另行显示 |
| 报告质量 | 版本化 rubric 的全部维度评分；不会自动推断分数 |
| 四类覆盖 | 原来源／问题分母，reviewed ⊆ text ⊆ accounted；须另核查真实阅读证据 |
| 成本、时延 | 实测或提供商报告值，注明 basis；没有则 null |
| 波动 | 同条件重复运行的均值、样本方差等；只有一次时无方差估计 |

评测固定输入与标注哈希，并报告比较条件差异。它不自动发布排行榜，也不能把本地 rubric 冒称 RACE／FACT。随包合成示例只验证计算，不证明哪个宿主、workflow 或 API 更好。宣称质量提升之前需真实运行与独立可辩护的标注。
