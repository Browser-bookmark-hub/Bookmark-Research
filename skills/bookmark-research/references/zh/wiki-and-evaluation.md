# Wiki 与研究质量评测

[English](../wiki-and-evaluation.md) · **中文阅读版**

Wiki 是经审阅的跨来源知识，正文归档是原始证据，两者分别保存。评测计算已有运行和标注，不会替模型执行研究，也不自动判断引用语义。

## 恢复整理和复核

恢复整理、核对写入是否提交时用 `wiki_work`。按 `research_id`、`capture_id` 或 `page_id` 定位，也可按 `kind`（`research`、`capture`、`page`）和 `status` 分页。`work_id` 稳定；全量清单是本地审计，不必每次回答都运行。

- `archived`：材料已保存，尚无已识别的合格待写论点；不表示已经阅读或审核。
- `pending`：已审核的有效论点尚未被当前完整 Wiki 修订引用。按 `pending_claim_ids` 和 `resume` 继续；候选清单不产生发布授权，也不要求写入每条论点。
- `compiled`：对应论点或快照正文被当前完整 Wiki 修订引用，不表示快照中的每段内容都已整理；`pages` 和 `work_receipt` 给出实际页面、修订号和记录哈希。新鲜度另外查看页面工作项。
- `needs_review`：页面有时效性或完整性问题，或任务／快照无法核验。页面返回有限的问题预览，以及读取已保存新证据的 `source_reads`，不必重复抓取；修订前仍需阅读页面和证据。

清单依据持久快照、可恢复的研究回执和当前已提交 Wiki 索引重建，不另存容易失配的完成开关。重启后可恢复，未提交的孤立修订不算完成，提交后响应丢失仍能找回。当前页删除某条引用后，该论点可能重新待整理；历史版本用 `wiki_get` 读取。分页期间其他进程可能更新资料，写入前重新核对对应 ID。

研究结果需要沉淀时，遵循原有 `suggest`／`auto`／`off` 偏好及会话授权；先读匹配页面，整理合格论点和相关链接，用 `expected_revision` 写入。`wiki_follow_up.instruction` 只是下一步指引，不是写入完成。报告实际 `work_receipt` 中的页面与修订；中断后先查 `wiki_work`，再决定是否重试。

网页变化时，读取 `source_reads` 的新证据或继续 `wiki_refresh` 剩余批次，导入并审核后修订受影响页面。之后检查对应 ID 或 `wiki_work(kind="page", status="needs_review")`；目标页更新后，关联页可能仍待复核。抓取返回响应本身不能消除复核要求。该流程不启动后台模型、监控或自动发布。

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

`wiki_get` 返回正文、结论与来源映射、书签实例和 inventory ID。`validation.integrity` 检查旧证据是否完整，`validation.freshness` 检查快照年龄和已知来源版本。新正文、过期／未知抓取时间、刷新失败和关联 Wiki 变化会产生 `needs_review`。直接引用网页的结论检查对应书签及相关画布上下文；推断和本地文档结论仍检查完整输入范围。检索排除失效／撤回的证据，并明确返回 `semantic_support:"not_scored"` 与 `origin_current_verified:false`。

`wiki_list` 和 `wiki_search` 分页返回。检索使用可重建的 SQLite 字符索引，包含标题、章节、正文和可选 `page.aliases`（最多 30 个别名），支持字面／空白差异匹配及价格／定价／pricing 等显式查询别名；不使用向量或语义重排。只对匹配候选核验证据，完整巡检用 `wiki_lint`。写入只更新一页的检索索引，并复用目录摘要；派生索引失败不撤销已提交修订，查询退回版本扫描。Wiki 默认在数据目录 `wiki/`，可用 `settings.wiki.directory` 改路径。

时效性知识可用 `wiki_refresh(page_id, expected_revision, offset=0, limit=8)` 分批抓取该页引用的 URL，按 continuation 继续覆盖。结果区分 changed、unchanged、unverified，提供归档续读参数及受影响页面；`wiki_list(source_url=..., offset=..., limit=...)` 可分页查看直接引用和关联页面。用带 `capture_id` 的 `fetch_web` 读取新快照，经 `research_import_evidence` 导入实际证据并保留原 `retrieved_at`，审阅来源与结论后再用 `expected_revision` 更新 Wiki。刷新不会改写正文或原书签包。

`wiki.max_source_age_days` 默认 30 天，可设 1–3650 天。相同正文的新快照可以延长有效期，内容变化仍需审阅，旧历史资料的导入不会覆盖较新的版本判断。版本登记覆盖同一研究根目录中的任务，以及当前配置的网页归档根目录。提供商可能返回缓存，所以新快照和 `current` 都不保证网页源站实时有效；目前没有自动后台网页监控。

新修订记录使用相对于研究任务的证据路径；`wiki_get` 将已验证的证据解析到当前任务位置，旧绝对路径记录也可读取，不改写历史。迁移／同步时同时保留 Wiki 索引、修订及其引用的研究 state、inventory 和证据，并保留相对布局以维持 Markdown 链接。在目标机器配置本地数据／研究路径；仅复制 Wiki Markdown 不足以保留可验证的知识库。Git 同步交给宿主，存放位置避开画布管理目录。

每次写入会重新生成 `index.md`（按 kind 列出当前页面：链接、标题、一行摘要、版本、日期、结论数），并向 `log.md` 追加 `## [日期] write | 标题 (rN)` 及 page ID、修改说明和研究 ID。可阅读或 grep 它们了解全貌；`index.json` 与版本文件仍是准确数据，`index.md` 过期或缺失时 `wiki_lint` 给出 `catalog_stale`／`catalog_missing` 警告，下次写入即重新生成。

已有 Wiki 写入授权时，使用合格且已审阅的 claims 直接完成，不重复询问。否则 `research_finish.wiki_follow_up` 按 `settings.wiki.after_research` 处理：`suggest` 先提出候选，`auto` 更新或创建合格页面，`off` 跳过。更新仍需当前 `expected_revision`，完成后说明实际写入。`eligible_claims` 标出每条结论的首句原文与是否为推断；`draft.page` 更进一步：按问题分组，正文就是 claim 原句，每节已带好 `{research_id, claim_id}` 列表并按写入上限切分，确认一次 + `wiki_write` 一次（`review` 填真实审阅人）即可成页。不要加入该列表之外的 claim。

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
