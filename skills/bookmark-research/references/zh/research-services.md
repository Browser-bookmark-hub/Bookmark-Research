# 专业研究服务：准备、运行与回收

[English](../research-services.md) · **中文阅读版**

Deep research 从当前宿主模型的调查开始。专业服务可承担宿主初步判断后的具体子问题，或用户明确交给它的任务。本插件提供 OpenAI Responses Deep Research 与 Parallel Task API 的薄客户端，也可使用宿主已有研究 MCP；报告回到宿主复核与综合。搜索接口与研究服务分别认证。

## 配置与入口

先用 `research_services` 读取当前状态，不联网。每家服务返回 `ready_to_start` 和具体缺失的配置／凭据名 `missing`；配置就绪不等于认证已验证，宿主原生研究仍可独立使用。OpenAI 使用 `OPENAI_API_KEY`；Parallel 使用 `PARALLEL_API_KEY`。通过终端 `setup` 或进程环境配置密钥，不写入项目、manifest、研究输入或报告。`research_readiness` 检查连接及授权范围，不创建任务；见[配置说明](settings-and-archive.md)。

选路和准备请求都不会执行研究。按返回的 `next_action` 启动一次、通过原 run ID 查询进度、取回完整报告，再导入并审阅原始来源。已保存的服务偏好只决定宿主研究之后的外部服务顺序；显式 `research_route.provider` 才独占指定服务。不能为了委派一个子问题而把宿主路线标成失败。

明确失败后，返回的下一步指向 `research_route`。把失败 `route_id` 加入累计的 `failed_routes`，传入当前宿主能力，沿用原研究会话执行下一条可用路线；保留用户明确指定的 provider 限制。未启用或缺凭据的 API 不参与执行；等待中、运行中、结果未知和已取消任务不触发替换。没有合适路线时保留证据、报告缺口。

宿主原生研究 MCP 方面，路由识别实际可见的 Exa `agent_run`，或完整的 Parallel `createDeepResearch` + `getStatus` + `getResultMarkdown`。插件不会安装这些 MCP，工具存在也不证明认证成功。按其实际 schema 调用，用 `research_record` 的 `external_run` 保存返回的 run ID 并更新状态。Exa 通过 `runId` 续查；Parallel 查询原任务，不重复创建。真实报告用 `research_import_evidence` 以 `external_report` 导入，再审阅原来源。这段续接由宿主按 Skill 执行，插件没有本地轮询 worker。

有效设置的 `professional_research` 默认 `enabled:false, provider:null`。用户选择服务后可更新相应配置，例如：

```json
{"changes":{"professional_research":{"enabled":true,"provider":"openai","openai":{"model":"o4-mini-deep-research","max_tool_calls":24}}}}
```

另一个支持的 OpenAI 模型为 `o3-deep-research`；Parallel 默认 `processor:"pro"`。模型／processor 可用性、费用与配额以当前账户为准。单次请求可用 options 覆盖受支持字段；配置和显式 provider 选择不自动启动任务，也不默默切换到别家。

## 准备真实材料

先建立本地 `research_start`，准备清楚的问题、范围、来源、时间要求、输出语言／交付格式与已知限制。`research_service_prepare` 接收：

```json
{
  "research_id": "r-实际ID",
  "question_id": "q1",
  "provider": "openai",
  "input": "完整研究问题、范围、评价维度与交付要求。用中文写报告，并保留原文引用。",
  "options": {"max_tool_calls": 24}
}
```

省略 `inventory_ids` 时采用该研究的完整选中清单；承担特定子问题时可传指定 ID，研究的总范围仍然保留。准备结果包含确切请求 payload、输入版本及共享来源范围；检查这些内容足够回答原问题。程序只加入显式 input 与原 URL，不自动上传原包、笔记、标签或路径。

云端不能读取本机文件路径或访问本地 stdio MCP。OpenAI 可传其账户已有的 `options.vector_store_ids`（至多 2 个）；实际上传资料与创建 vector store 是单独的有意操作。账号内网页或本地资料不能通过把路径放入 brief 就假定可达。服务没有读到的材料留在原始覆盖缺口中。

## 单次创建与状态观察

确认具体请求在当前授权范围内后，调用 `research_service_start`，参数与 prepare 一样，再加稳定的 `operation_id`。已获得用户服务使用授权时直接执行，不重复请求。创建保存 `external_id` 与真实 provider run ID；提供商负责后台执行，插件没有轮询循环。

| 动作 | 工具／行为 |
| --- | --- |
| 准备 | `research_service_prepare`，没有网络请求或计费创建 |
| 创建 | `research_service_start`，同 research_id＋operation_id＋输入重放既有结果，不重新提交 |
| 本地状态 | `research_service_status`，默认只读已保存观察 |
| 远端状态 | 同一工具 `refresh:true`，对已有 run ID 查询一次 |
| 结果 | `research_service_result`，保存／分页读取报告；`refresh:true` 观察同一运行一次 |
| 取消 | `research_service_cancel`；只实现文档确认的 OpenAI cancel |
| 关联外部运行 | `research_service_attach` 传 research_id、operation_id、provider、已知 run_id，可加 question_id；不创建远端任务 |
| 导入 | `research_service_import` 传 external_id、operation_id，可加 question_id；只导入已完成且保存的报告 |

请求超时或 create 响应丢失时，状态可能为 `unknown_outcome`。保存原操作号，读取状态；已知真实 run ID 可 attach 恢复，不用新操作号重复创建可能已经计费的任务。连接断开或停止等待不等于远端取消。status/result 观察失败保留上次可信状态；Parallel result 的服务端等待参数为 1 秒，超时仍可能运行中。

OpenAI 默认 `store:false`、`background:true`；背景任务依官方临时保留策略供查询，并非永久云端档案。及时保存返回结果。Parallel Task 在本适配器所核对的接口中没有已确认的取消端点，不能伪造取消成功。

## 报告回到证据流程

结果带报告正文、原始响应位置和哈希、提供商引用与能取得的用量。`citations` 是至多 100 项／约 100 KB 的预览；查看 `citation_count`、`citations_truncated`，并按返回的 `citations_file` 与哈希读取完整列表，不能将预览作为完整引用范围。报告中的引用尚未验证。`research_service_import` 将报告作为 `external_report` 写入原研究，默认未审阅；可支持“这份报告作出某结论”的二手引用，不能自动证明引用的原页面被读过。

阅读全文，核对原问题、遗漏维度、结论与反证；对关键引用实际读取原 URL，再做 `source_review`、claim、`inventory_review`。外部运行 completed 不意味着整包 completed。最终由 `research_coverage` 与 `research_finish` 检查原始来源和问题；专业服务使用量不可取得时保持未知。

状态与确切请求保存在数据目录 `service-runs/er-.../`，关联及导入证据保存在 `research/r-.../`，均位于原包之外。

依据：[OpenAI Deep Research](https://developers.openai.com/api/docs/guides/deep-research)、[OpenAI background mode](https://developers.openai.com/api/docs/guides/background)、[Parallel Task API](https://docs.parallel.ai/task-api/guides/execute-task-run)。接入契约验证与有凭据的真实任务验证分别报告。
