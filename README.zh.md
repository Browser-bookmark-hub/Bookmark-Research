# Bookmark Research 0.4.0

[English](README.md) · **中文**

用自然语言查询 [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas) 数据包，保留书签的文件夹、卡片和画布关系，结合 Exa、Parallel、Jina Reader 和 Tavily 调查来源，保存报告与 Wiki。

Codex、Claude Code、Pi 和 DSH 共用一套 Skill、Python 运行时与本地数据，分别使用对应适配。**0.4.0** 整合全量研究工作流、可选专业研究 API、Wiki 与评测、目录／ZIP／单卡接入、来源版本快照和长期目录增量同步。输入变化后会提示研究／Wiki 复核；英文执行指令配完整中文阅读版，研究输出遵循用户的语言要求。

新用户从[安装说明](docs/installation.md)和[使用指南](docs/user-guide.md)开始。需要理解内部关系时看[结构与触发流程](docs/bookmark-research-architecture.md)。本地 0.4.0 的验证范围见[验证记录](docs/validation-0.4.0.md)，已公开发布的版本以 [Releases](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases) 为准。

## 安装到 Codex

准备 Bash、Git、Python 3.9+、SQLite FTS5 和支持插件的 Codex CLI，然后运行：

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash
```

首次安装读取仓库默认分支 `main`，由 Codex 原生插件命令登记与验证，不依赖 GitHub Release 或下载 ZIP。安装后会显示实际配置、首次提问示例和配置查询命令。新建 Codex 对话，再提供自己的数据包路径。

安装器自动按系统 locale 选择中英文；可以显式选择：

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- install --lang zh
```

`--lang en` 使用英文，`--lang auto` 依次读取 `LC_ALL`、`LC_MESSAGES`、`LANG`。研究输出的语言由实际对话或明确要求决定；安装语言不限制研究语言。

更新同一来源或从源码安装：

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- update --lang zh
python3 scripts/install.py install --lang zh
python3 scripts/install.py verify --lang zh
```

已通过 `personal` 安装时沿用其更新流程，避免重复登记。固定 tag 的安装不会因 `update` 自动切换到新版本；历史版本保留当时的功能与引导语言。详见[安装参数和其他客户端](docs/installation.md)。

## 怎样使用

**本地查询无需 API Key。** 插件没有预置个人书签，先提供目录、ZIP 或单卡 JSON：

> 用 Bookmark Research 读取我的数据包 "/absolute/path/to/my-package"，先离线列出卡片、文件夹和书签数量。

之后直接说明任务：

| 需要 | 示例 | 执行方式 |
| --- | --- | --- |
| 本地查找 | “这个书签在哪张卡片里？” | 查询 SQLite 中的元数据和结构关系。 |
| 快速查证 | “读取这个书签，确认它是否支持 MCP。” | 读取 URL，必要时搜索发现来源。 |
| 主动搜索 | “比较这些卡片里的工具，查清它们的区别。” | 宿主拆问题、搜索、读文并持续补查。 |
| 深度研究 | “研究整个包，核验排行榜，交付报告和 Wiki。” | 保留完整清单，组织调查、证据审阅和覆盖核验。 |

不需要固定提示词。完整数据包研究保留所有原始 URL 和重复书签语境；只有明确限定卡片、分组或专题时才缩小范围。搜索摘要、搜索结果的第一页和外部报告都不能代替原始网页审阅。

一个插件保留一个 MCP 聚合入口和一个执行 Skill；后端服务数量与入口数量无关。MCP 内置 Exa、Parallel、Tavily 搜索／读取适配器、Jina HTTP 接口和 OpenAI／Parallel 研究 API 客户端。Skill 负责根据任务选择并执行三种流程：

| 场景 | 基础流程 | 检索与委派支持 |
| --- | --- | --- |
| URL 直读 | 当前模型读取已知页面并回答 | Exa 未读到的 URL 交给 Parallel + Jina Reader 并发读取；可配置 Tavily 提取。 |
| Agentic Web Search | 当前宿主模型先规划 → 搜索／读文 → 判断证据 → 针对缺口补查 | Exa + Parallel 提供搜索结果；无有效网址的查询再交给 Tavily + 有 key 的 Jina。普通问题无需完整研究会话。 |
| Deep Research | 在宿主研究循环上增加持续调查、按需协作、独立核验、覆盖检查与报告 | 优先利用宿主现有子代理／工作流；外部 Research MCP／API 可承担宿主判断后的子问题或用户明确指定的任务。 |

四个基座共用这套方法：Codex 原生子代理、Claude 普通子代理或已启用团队、Pi 扩展、已配置的 DSH 子代理／工作流；具体差异与官方依据见 [宿主兼容说明](docs/harness-compatibility.md)。整包脚本用于分组研究。保存的 API 偏好只排列外部服务，显式 provider 才直接指定服务；明确路线失败可继续换路，运行中、结果未知或已取消任务不自动重建。

“备用”表示已加入回退列表；“需要配置”表示条件未满足时跳过；“仅调研”表示没有接入，失败也不会自动安装。OpenAI／Parallel 研究 API 默认关闭，需启用并提供凭据。宿主已加载的 Exa `agent_run`、完整 Parallel Task MCP 会被路由识别，实际认证仍以调用结果为准。Scrapling、Firecrawl、MarkItDown 等调研项目没有集成成自动后端。

## 数据包与保存位置

JSON／`.canvas` 是源数据，SQLite 是可重建的本地查询索引，无需单独数据库服务器。插件不会回写原始画布包。

| 来源 | 默认行为 |
| --- | --- |
| 手动导出目录、ZIP、单卡 | 保存为 `snapshot`；原下载文件移走后仍可查询。 |
| Git 仓库内长期目录 | 登记为 `live`；MCP 运行期间及查询前检查本地变化。 |
| 同一画布的新路径导出 | 明确沿用原 `source_id`，保留稳定身份和路径别名。 |
| 局部导出 | 默认 `partial`，保留未提供的文件；提供的完整栏目内删除正常同步。 |
| 明确的完整镜像 | 使用 `complete`，同步缺失文件的删除。 |

两种来源模式都会保存可恢复版本。live 监控跟随 MCP 进程，默认每秒检查、普通变化稳定 2 秒、整文件删除稳定 5 秒后同步；独立 CLI 持续监控使用 `watch`。Git 拉取和推送由原有同步系统负责。

默认数据目录为 `~/.local/share/bookmark-research/`：

- `index.sqlite3`：来源登记、书签和画布关系索引。
- `index.sqlite3.sources/`：原始协议文件和关系清单的版本快照。
- `knowledge/`：普通网页响应、正文和来源记录。
- `research/`：完整输入清单、任务、证据、覆盖与报告。
- `wiki/`：主题／实体页和不可变修订。

配置默认为 `~/.config/bookmark-research/settings.json`。支持 XDG 和显式路径覆盖，多宿主可共享数据。索引更新不会自动抓网页、运行 LLM 或改写 Wiki；来源变化时提示复核，旧研究与证据保留。

`research_record` 支持单条 `entry` 或每批至多 50 条的 `entries`，按顺序校验后一次保存，返回精简编号；稳定的 `batch_id` 可避免重试产生重复记录。依赖新 claim ID 的记录在读取返回值后另批提交。`resume` 和 `external_run` 仍需单条调用，详见 [证据记录](skills/bookmark-research/references/zh/deep-research.md)。

## 搜索、配置与语言

`search.providers` 为第一轮，`search.fallback_providers` 为无结果时的备用列表；设为空数组可关闭搜索回退。读取单独配置 `fetch.provider` 和 `fetch.providers`。调用时明确指定 provider／providers 则只用指定服务。已有配置若只设置过搜索 providers，会保留原来的服务范围；新研究冻结当时的选择，旧记录重放不会增加请求。瀑布流按轮补缺，同轮服务并发；已发出的请求仍需等待结束或超时。普通网页归档开启，深度研究始终保存任务证据。

可以读取公开 GitHub 仓库页面、README、文件和 issues；读取 README 不等于遍历整个代码仓库。代码审查按任务选择具体文件或宿主已有 GitHub 工具，插件未额外安装 GitHub MCP。

网络访问依赖服务方的认证与额度。需要时在启动宿主的环境中设置 `EXA_API_KEY`、`PARALLEL_API_KEY`、`TAVILY_API_KEY`、`JINA_API_KEY` 或专业研究所需的 `OPENAI_API_KEY`。无需给宿主研究额外填写一套模型地址。

中英文用户共用一个插件；回答、报告正文和 Wiki 章节跟随用户指定语言。原始引用和 URL 保留原文，译文另列。执行 Skill 和 11 篇方法参考以英文维护，配完整中文阅读对照；子代理和工作流也会接收本次输出语言。详见[指令与提示索引](docs/instructions.md)。工具字段、技术诊断和部分固定元数据标签使用英文。

## 宿主与验证范围

| 宿主 | 接入 | 当前验证边界 |
| --- | --- | --- |
| Codex | 原生 Plugin + Skill + MCP | 本机安装、35 个 MCP 工具及来源生命周期已验证。 |
| Claude Code | 原生插件和 Dynamic Workflow | 先前验证已加载工作流和工具；真实模型请求遭遇 429，未完成研究。 |
| Pi | Skill + CLI／stdio 桥 | 适配器隔离验证；子代理工作流依赖已有扩展。 |
| DSH | MCP 与工作流适配 | 适配器隔离验证；需配置工作流服务及 Skill 发现。 |

另有 Agent Plugins 1.0.0 标准格式导出。适配器存在不代表每个宿主都已完成真实研究。Wiki 保存引用、审阅和修订；评测根据实际运行数据及显式评审标签计算，示例分数不能证明研究质量。

## 开发与来源

```sh
python3 -m unittest discover -s tests -v
python3 scripts/verify_fixture.py --output /tmp/bookmark-research-verification
python3 scripts/export_bundle.py --format codex --output exports/codex/bookmark-research
```

研究来源与演进见[设计调研](docs/research-0.2.0.md)、[宿主兼容性](docs/harness-compatibility.md)和[Wiki／评测](docs/wiki-quality.zh.md)。项目源自 Bookmark Canvas，沿用 [GPL-3.0](LICENSE)。
