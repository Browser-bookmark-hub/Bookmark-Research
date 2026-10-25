# 三宿主接入与验证边界

Codex、Claude Code、DeepSeek Harness 共用同一 Skill、Python CLI、stdio MCP、归档和 Wiki。宿主负责推理、搜索策略、协作与最终表达；插件默认提供 21 个日常工具。研究 API 可独立使用，完整资料审计及持久化研究记录通过 `deep` 预设按需启用。

| 宿主 | 接入 | 协作 |
| --- | --- | --- |
| Codex | 原生插件 manifest、Skill、stdio MCP | 使用会话实际提供的子代理；`hosts/codex/delegate.md` 与 `prepare.py` 仅辅助完整审计 |
| Claude Code | 原生插件 manifest、Skill、stdio MCP、研究命令 | 使用实际可见的 Agent／Task；分组工作流需宿主启用 |
| DeepSeek Harness | npm 包的 `dsh.bundle.patch`、原生 Skill provider、MCP client | 当前 profile 提供 subagent／workflow；工具名采用宿主实际映射 |

MCP 默认命令为 `python3 <plugin-root>/src/cli.py serve`。数据库和存储位于插件与画布包外。多宿主共库时须显式共享相同数据目录和配置；插件同名不代表共享存储。Codex 的自定义环境变量须由 MCP 注册转发，DSH 由插件启动配置传递。

高级 MCP 工具需要 `tool_scope_preset:"deep"` 或显式白名单。CLI 工作流桥接只为本次高级子进程启用完整目录，保留显式范围，不改变保存的日常预设。所有子代理须收到问题、范围、相关 Skill 和实际数据入口；上下文继承以宿主实际行为为准。

分组工作流只有在用户要求完整清单和覆盖审计时使用，见[宿主工作流](../skills/bookmark-research/references/host-workflows.md)。普通调研按主 Skill 的上下文、检索、阅读、综合、Wiki 存储流程执行。

打包检查、协议测试、真实 stdio MCP 调用和三宿主模型的端到端研究属于不同验证层级。离线测试和导出成功不能证明原生代理或付费 API 执行成功。历史验证记录与旧版配置说明可从 Git 历史查阅；当前接口和步骤以本项目现有文档为准。
