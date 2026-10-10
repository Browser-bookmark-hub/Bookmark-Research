# 深度研究：保存证据与报告

[English](../deep-research.md) · **中文阅读版**

用于需要持久证据、覆盖管理或恢复能力的深入持续调查，包括完整原始 URL 审阅。保存普通回答只需已有支持材料和要求的输出；保存一条 Wiki 结论不扩大为整库研究。调查由宿主执行，保存任务状态不产生后台代理。

## 建立任务与范围

用 `research_start` 保存可回答的问题、范围、语言和检索预算。已有任务按下方恢复说明继续。

```json
{
  "brief": "比较用户提供的工具，用中文输出报告。",
  "scope": "提供页面能证明的功能",
  "questions": [{"id": "q1", "question": "哪些能力符合用户用途？"}],
  "urls": ["https://example.com/one", "https://example.com/two"]
}
```

- 普通清单用 `urls`（1–10,000 项），画布用已注册 `source_ids`，二者选一。只写在 brief 里的 URL 不计入输入；没有原始链接集合时才省略两者。
- 默认 `scope_mode:"whole"` 保留全部输入、重复实例和非网页项。画布 `bookmark_refs` 仅标记关注点；明确要求子集时才用 `scope_mode:"subset"` 加 `inventory_ids` 或画布 `bookmark_refs`，保留遗漏 ID。
- 数据包 source ID、原始清单 ID（`u-…`）和证据快照 ID（`sN`）不可混用。`inventory.json` 固定 URL、实例及上次同步的画布上下文，`context.json` 保存摘要。本地笔记、路径不自动上传。
- 建立全量清单时，读取 `research_inventory` 到 `next_offset:null`。清单／覆盖率每页及 ID 过滤最多 100 项；预览不定义范围。超大上下文使用返回的产物路径与 JSON pointer。
- 中间文件放到返回的 `work_directory`，输出位置发生回退时说明。

## 证据循环

1. 已知 URL 用 `research_fetch`，缺少来源用 `research_search`；query 对应已有 `question_id`。服从服务限制，检查未解决的调用。
2. fetch 返回元数据；用 `research_source` 阅读正文，并按相关性继续分页。核对页面身份、日期／版本和适用性，拒绝登录壳或无关页面；摘录可能不完整。先保存 `source_review`，再写 claim。
3. claim 使用实际证据 ID 和已存正文的原句。原句／哈希只能验证存在，不能证明语义支持。推断标记 `inference:true`；综合答案保留条件和反证。多个服务返回同一页面不是独立来源。
4. 原始输入用 `inventory_review` 关联同一原 URL 的已接受正文。替代页面或外部报告可支持回答，但不能算读过原始 URL；失败或合理排除保留具体理由。
5. 已有充分依据时写 `answer` 并关联本题 claim ID。选择补查或结束时用 `research_coverage`，按相关差集继续，无需重复读取全部未变记录。解决矛盾或保留缺口。

复用仍有效的已读正文和完整 ID 集合。身份、语义、版本或矛盾不明确时回查原证据，交付前复核综合答案。独立复核按需要和授权选择；确定委派时才读[宿主流程](host-workflows.md)。

拒绝／存疑的证据应撤回受影响 claims，在剩余预算内只补查对应 URL／问题。新抓取使用新 operation ID，重放旧 ID 只返回旧文本；审阅不会自动联网。不要修改已存证据迎合结论。

宿主工具取得的原文可用 `research_import_evidence` 保存：`research_id, operation_id, question_id, url, text, provenance`，可选 `title, inventory_ids`。provenance.kind 为 `page`、`archived_page`、`local_document` 或 `external_report`；记录真实提供商、取得时间和位置。导入默认未审阅，摘要不能冒充原页；外部报告是二手证据。选定外部服务时才读[服务接口](research-services.md)。

## 记录类型

`research_record` 接受 `{research_id, entry}` 或 `{research_id, entries:[…], batch_id}`，只传对应类型的字段。

| 类型 | 字段与约束 |
| --- | --- |
| `source_review` | `source_id, verdict:accepted/rejected/uncertain, text`；被拒绝的正文不能支持 claim |
| `claim` | `question_id, statement, citations:[{source_id,quote}]`；可选 `confidence:low/medium/high`、`inference:boolean`；返回 claim ID |
| `inventory_review` | `inventory_id, disposition:reviewed/excluded/blocked, text`；reviewed 还需 `question_ids, source_ids` 和来自已接受原页的 `claim_ids` 或 `citations`；excluded 需 `reason_code:out_of_scope/non_content`；blocked 需具体原因 |
| `answer` | `question_id, answer, claim_ids`；claim 须属于该问题 |
| `question` | `id, question`；最多 24 题 |
| `gap` | `question_id, text`；后续回答可以解决 |
| `conflict` | 至少两个 `claim_ids` 与 `text`；返回 conflict ID |
| `resolution` | `conflict_id, claim_ids, text`；保留原冲突 |
| `retraction` | `claim_id, text`；保留历史，重开受影响问题／冲突 |
| `external_run` | `id, provider, run_id, status, text`，可选 `result` 或 `artifact_path`；状态为 prepared、pending、queued、in_progress、completed、cancelled、error、unknown_outcome；仅保存引用和哈希 |
| `interruption` | `operation_id, text`；确认 pending 操作中断后标记结果未知，不退款、不重跑 |
| `resume` | `text`；恢复 incomplete 任务，保留报告、证据和预算 |

已就绪的记录批量提交（1–50 条），按顺序验证并原子保存，任一无效 `entries[i]` 会拒绝整批。同一批可先 source_review 再 claim；需要新 claim／conflict ID 的后续记录必须先读取返回值。长引文较多时减小批次。

稳定的 `batch_id` 可在重启或完成后重放相同记录，内容变化会失败。未提供时，响应不明应先检查保存状态，claim 不自动去重。批量结果含按顺序的 `index, kind, id, replayed`；完整记录通过 `research_status` section 分页读取。`resume` 和 `external_run` 必须单条调用。

## 预算与重试

预算限制插件检索尝试，不保证费用或模型 token：

| 计数 | 单位 | 默认／上限 |
| --- | --- | --- |
| `search_calls` | 去重后的 provider + question + query 尝试 | 16／120 |
| `fetch_calls` | 按服务尝试；Exa／Parallel／Tavily 每批最多 8 URL，Jina 每个 URL 一次 | 无输入时 12，否则首次容量加 12 次补查，硬上限 80 |
| `rounds` | 一批 `research_search` | 8／40 |

搜索最多 12 query，每题最多返回 20 URL；2 query × 2 服务消耗 4 search calls 和 1 round。3 URL 的 Exa → Parallel + Jina 回退消耗 1 + 1 + 3 fetch calls。

未指定 `max_fetch_calls` 时默认 `min(80,max(12,ceil(URL数/8)+12))`，Jina 优先时把批次项换成 URL 数。`initial_fetch_plan` 给出容量和缺口；预算不足也保留原始范围，显式预算不扩大。读已存来源、写记录和报告不消耗检索额度，预算可为 0；宿主／服务之外的消耗另记。

每个联网步骤用稳定 `operation_id`；参数相同重放原结果，参数改变报错。认证／网络失败和结果未知仍保留预算预留。不要仅为查看结果扩大预算或重新提交。

联网前保存 pending 意图，提交状态前保存完成回执；后续读取可恢复已有回执，没有回执则仍是 pending，不重发。记录 `interruption` 前检查操作是否还在执行；确需重试才用新 ID 和预算。活动或结果未知的外部任务应先观察状态，避免重复创建。

## 恢复和交付

`active` 直接继续；已导出的 `incomplete` 先记录 `{"kind":"resume","text":"继续的原因"}`。恢复保留报告快照和消耗，不扩大预算。`completed`、`cancelled` 为终态；额度耗尽仍可整理已存证据，继续检索需要另行确定新任务与预算。

不带 ID 的 `research_status` 列出任务，带 ID 返回有界预览；完整记录选择所需 `section` 并跟随 `next_offset`，不能根据页长判断结束。超大条目用产物位置，正文用 `research_source`。

覆盖分开统计 `accounted_for`、`usable_text`、`substantive_review`、`question_completion`。失败原因只增加逐项交代率；排除项保留在原始总数，不增加阅读／审阅覆盖。旧任务未冻结清单时，原始覆盖未知。

`research_finish` 使用 `completed` 要求每题有支持充分的回答、完整原始范围已实质审阅，且无开放冲突、pending 操作或活动／未知的外部任务。重要缺口用 `incomplete`，全失败／全排除不能完成整包研究。证据失效可重开已解决冲突。

finish 返回报告／来源／覆盖产物路径和 `wiki_follow_up`。已有 Wiki 写入授权时，使用合格已审阅 claims 继续完成；否则按保存的 suggest／auto／off 偏好处理。写入细节见 [Wiki](wiki-and-evaluation.md)。

搬迁时保留完整任务目录。使用返回的输出位置，位置偏好见[设置](settings-and-archive.md#研究结果位置与-wiki-后续整理)。对外分享服从用户范围，档案可能含私有材料。抓取时间不证明原站时效，保存任务不能迁移宿主代理的内部状态。
