# Deep Research API

**中文** · [English](../research-services.md)

需要持续深入调查时，可直接把完整问题提交给 OpenAI Responses 或 Parallel Task API。宿主负责选定范围、查询进度、审阅报告和最终表达；本地 `research_start` 会话是可选项。宿主已有的原生研究工具也可独立使用。

## 配置与准备

`research_services` 离线显示配置和缺少的凭据。启用所选 `professional_research` provider；OpenAI 使用 `OPENAI_API_KEY`，Parallel 使用 `PARALLEL_API_KEY`，通过终端 `setup` 或进程环境设置。

```json
{"changes":{"professional_research":{"enabled":true,"provider":"openai"}}}
```

`research_service_prepare` 不联网、不创建任务，返回将要发送的实际 payload：

```json
{"input":"使用原始文档比较指定产品，注明限制、版本、反面证据和引用，用中文报告。","provider":"openai","options":{"max_tool_calls":24}}
```

OpenAI 配置默认 `gpt-5.6-sol`，自定义模型需 `allow_untested_model:true`；旧模型标识仅为配置兼容而接受，不保证可用。Parallel 默认 `processor:"pro"`。权限、费用与配额取决于账户。

云端服务不能读取本地路径或本地 stdio MCP；提供必要的公开 URL 和明确问题。OpenAI 可引用当前账户最多两个现有 `vector_store_ids`，上传文档属于独立操作。

## 执行、观察与恢复

| 操作 | 工具与行为 |
| --- | --- |
| 准备 | `research_service_prepare`，离线审阅请求。 |
| 启动 | `research_service_start`，增加稳定的 `operation_id`，相同输入复用已保存操作。 |
| 进度 | `research_service_status`，默认只读本地；`refresh:true` 查询原任务一次。 |
| 结果 | `research_service_result`，保存并分页读取报告；`refresh:true` 观察一次。 |
| 取消 | `research_service_cancel`，支持 OpenAI；停止观察不代表取消远端任务。 |
| 恢复 | `research_service_attach`，提供 `operation_id`、`provider`、已知 `run_id`，不创建新任务。 |

已有授权时持续执行。后台任务由服务方运行，插件没有轮询 worker。超时或响应丢失后保留原 operation ID；检查 `unknown_outcome`，优先接回已知 run ID。观察失败保留上次可信状态。Parallel 结果请求的服务端等待为一秒。

OpenAI 使用 `store:false`、`background:true`，按服务方临时保留策略及时保存结果。本适配器不支持 Parallel 取消。失败或取消保留明确缺口，由宿主判断是否使用其他已获授权的路径。

## 回到 Wiki 或完整审计

完整阅读报告并核对关键原文；服务方引用未经插件验证。结果带正文、原始响应路径／哈希及已知 usage。引用预览有界，必要时检查 `citation_count`、`citations_truncated` 和完整 `citations_file`。

普通调研通过 `wiki_write` 一次提交审阅后的正文与精确引文。API 报告来源标记 `kind:"external_report"`，区分报告观点与原文核验。

只有已明确选择完整资料审计时，才传可选 `research_id`、`question_id`、`inventory_ids`。未指定 inventory IDs 时沿用该任务完整选定范围。高级 `research_service_import` 把完成报告接入原会话，不把报告引用的原始网页算作已读；原始覆盖检查单独完成。问题与清单 ID 必须和 research ID 一起使用。

请求与报告保存在画布外的 `service-runs/er-.../`。见 [Wiki](wiki.md) 与[可选完整审计](deep-research.md)。

接口参考：[OpenAI Deep Research](https://developers.openai.com/api/docs/guides/deep-research)、[background mode](https://developers.openai.com/api/docs/guides/background)、[Parallel Task API](https://docs.parallel.ai/task-api/guides/execute-task-run)。
