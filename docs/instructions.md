# Skill 与提示语言

[English](instructions.en.md) · **中文**

Bookmark Research 共用一个执行 Skill 和一套运行时。执行 Skill 及原有 11 篇方法参考以英文维护，完整中文阅读对照保留相同的范围、证据、预算和恢复规则。

## 阅读索引

| 内容 | English | 中文 |
| --- | --- | --- |
| 执行 Skill | [Read](../skills/bookmark-research/SKILL.md) | [阅读](../skills/bookmark-research/references/zh/skill-guide.md) |
| 数据包阅读协议 | [Read](../skills/bookmark-research/references/package-semantics.md) | [阅读](../skills/bookmark-research/references/zh/package-semantics.md) |
| 来源生命周期 | [Read](../skills/bookmark-research/references/source-lifecycle.md) | [阅读](../skills/bookmark-research/references/zh/source-lifecycle.md) |
| CLI 命令 | [Read](../skills/bookmark-research/references/cli.md) | [阅读](../skills/bookmark-research/references/zh/cli.md) |
| 研究与服务接入 | [Read](../skills/bookmark-research/references/research-workflow.md) | [阅读](../skills/bookmark-research/references/zh/research-workflow.md) |
| 深度研究 | [Read](../skills/bookmark-research/references/deep-research.md) | [阅读](../skills/bookmark-research/references/zh/deep-research.md) |
| 研究方法 | [Read](../skills/bookmark-research/references/research-methods.md) | [阅读](../skills/bookmark-research/references/zh/research-methods.md) |
| 宿主工作流 | [Read](../skills/bookmark-research/references/host-workflows.md) | [阅读](../skills/bookmark-research/references/zh/host-workflows.md) |
| 专业研究服务 | [Read](../skills/bookmark-research/references/research-services.md) | [阅读](../skills/bookmark-research/references/zh/research-services.md) |
| 配置与归档 | [Read](../skills/bookmark-research/references/settings-and-archive.md) | [阅读](../skills/bookmark-research/references/zh/settings-and-archive.md) |
| GitHub 与同步 | [Read](../skills/bookmark-research/references/github-and-sync.md) | [阅读](../skills/bookmark-research/references/zh/github-and-sync.md) |
| Wiki 与评测 | [Read](../skills/bookmark-research/references/wiki-and-evaluation.md) | [阅读](../skills/bookmark-research/references/zh/wiki-and-evaluation.md) |
| 宿主提示完整说明 | [Read](prompt-reference.en.md) | [阅读](prompt-reference.md) |
| Wiki API 与评测细节 | [Read](wiki-quality.md) | [阅读](wiki-quality.zh.md) |

只有根目录 `skills/bookmark-research/SKILL.md` 会被发现为 Skill。`references/zh/` 是 Markdown 阅读对照，没有第二个 Skill 入口或 manifest。按需读一种语言的参考即可，不必同时加载两份。

Codex 委派和 Claude／Pi／DSH 的共享提示模板以英文执行。双语提示说明覆盖共同上下文、清单、阅读、独立核验、覆盖、报告、主代理复核和 Codex 原生委派。文中的占位符对应真实任务数据，不是研究证据。

## 输出语言

优先用户明确要求，再跟随实际任务／对话，两者都没有选择语言时默认英文。将选择保存在研究 brief、各次委派和工作流的 `output_language` 中；专业研究服务输入也要包含语言要求。答复、报告正文、审阅说明和 Wiki 标题／章节遵循它。原引用、URL、标识符、代码、JSON 字段与状态值保持原样，译文另列。

语言选择不会限制检索语种或缩小整包范围。安装器 `--lang auto|en|zh` 只控制帮助和首次引导，不保存研究语言偏好。

插件界面和入口提示中英并列，日常使用见[中文指南](user-guide.md)或[English guide](user-guide.en.md)。技术诊断和报告／Wiki 固定元数据标签沿用运行时原文；历史调研／验证记录和原始资料保留原语言。

## 保持两种说明一致

先更新英文执行规则，再同步中文阅读版和受影响的提示说明。API 名、ID、枚举、数值限额、分页、范围／完成门槛、授权边界和引用语义保持一致。可以翻译说明和示例占位内容，不能翻译替换真实证据。

修改后检查链接和打包内容；工作流变更需运行宿主工作流测试，导出变更需运行导出／分发测试。独立的隔离使用验证可以检查 Skill 是否能指导真实操作；这些检查不能替代付费研究实跑，也不证明研究质量。
