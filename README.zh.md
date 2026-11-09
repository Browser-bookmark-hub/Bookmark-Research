# Bookmark Research

[English](README.md) · **中文**

[![GitHub Bookmark-Canvas](https://img.shields.io/badge/GitHub-Bookmark--Canvas-181717?logo=github&logoColor=white)](https://github.com/Browser-bookmark-hub/Bookmark-Canvas)
[![npm version](https://img.shields.io/npm/v/bookmark-research?logo=npm)](https://www.npmjs.com/package/bookmark-research)

带着书签上下文调研，把结论留成可复用知识。读取 [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas) 数据包，使用宿主模型或研究 API 调查，再保存带来源的 Wiki 页面。支持 **Codex、Claude Code、DeepSeek Harness (dsh)**。

[安装说明](docs/installation.md) · [使用指南](docs/user-guide.md) · [详细说明](docs/details.md) · [npm](https://www.npmjs.com/package/bookmark-research)

## 0.7.0 正式版

0.7.0 把 CLI 与 MCP 合并成同一套工具面：默认 10 个原语、持久化本地作业队列、卡片导出（JSON 或 Netscape HTML）导入、搜索引擎页跳过与 fetch TTL 缓存。全量目录仍保留 57 个名字；旧名从默认目录隐藏并标记 deprecated，将在 0.8.0 拒绝。升级保留已有配置、密钥和研究数据。

## 它是怎么工作的

- **本地理解层。** 数据包按结构读，而不是一张平铺的 URL 清单：卡片与分组的位置、连线的方向与标签、同一书签在不同卡片的出现位置（空间上下文）；日期字段、ID 中协议定义的日期段，以及真正改过内容的 Git 提交（时间上下文）。这些都是离线查询。
- **外部调研走三条路线。** 读取已知 URL 不需要推理；Agentic 搜索由宿主模型自己规划、搜索、阅读并追查缺口；Deep Research 可直接调用 OpenAI／Parallel 研究 API；完整清单与覆盖审计在明确需要时启用。`search_web` 聚合已配置的 URL 搜索来源（可选 Perplexity Search）；`agentic_search` 可按需返回 Grok 或用户自定义 OpenAI 兼容模型的回答与引用。自定义模型是否真正联网取决于上游能力，且不参加 URL 排名。
- **可复核的知识存储。** 完成的研究可以沉淀成 Wiki：带历史版本和相互链接的已审核页面，之后提问直接复用，不必重新搜索网页。

## 环境要求

- Python 3.9+，含 SQLite FTS5（用 `bookmark-research doctor` 检查）
- 至少一个宿主的 CLI：Codex、Claude Code 或 DeepSeek Harness (dsh)。DeepSeek Harness (dsh) 另需 `pnpm`；若用 DeepSeek Harness 桌面版自带 CLI，则它自带 pnpm，无需另装
- 安装发布版需要 Node 18+ 和 npm
- 安装和本地查书签都不需要 API Key

## 安装

```sh
npx bookmark-research@latest install
```

默认安装最新正式版。固定安装本版可用 `npx bookmark-research@0.7.0 install`。加 `--lang zh` 可让向导显示中文。想一直能用 `bookmark-research` 命令，运行 `npm install -g bookmark-research@latest`；GitHub 便捷脚本使用同一 npm 发布版（macOS/Linux/WSL）：

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash
```

### 安装向导会问你什么

1. **装到哪些宿主** —— 方向键移动、空格勾选；检测到的 CLI 默认已勾选，随后显示安装计划让你确认。
2. **默认研究深度（可选）** —— 保持 `auto` 就会按每次请求自动定档；只有想钉死一个默认时才改成 `quick`、`agentic` 或 `deep`。
3. **答复和报告语言** —— 跟随提问语言、中文或英文。
4. **搜索来源** —— 一个有序多选列表；未选中的服务自动作为备用搜索层。Perplexity 只提供搜索结果，网页读取由其他服务完成。
5. **存放位置** —— 默认数据目录、自定义统一目录（归档与研究报告），或研究报告放在书签文件／文件夹旁边。
6. **可选专业研究 API** —— 默认关闭：OpenAI Deep Research 或 Parallel Task API。
7. **自定义模型端点（可选）** —— 输入兼容 Base URL、模型和协议；联网能力取决于上游。
8. **API Key** —— 空格勾选上面所选服务需要的 Key，回车继续，再逐个隐藏输入；全部可选，可跳过。Key 与偏好分开保存。
9. **服务检查** —— 报告已配置服务；样例搜索／阅读自检需另行选择。

回车即保留当前选项，所以整轮可能只需按几次回车。装好后新建一个宿主会话，让 Skill 和 MCP 工具生效。Wiki 默认建议整理；已有保存授权时直接执行。服务诊断保留 15 分钟缓存，按需调用。

### 指定宿主、不弹提示

| 宿主 | 命令 | 实际登记方式 |
| --- | --- | --- |
| Codex | `npx bookmark-research@latest install codex --non-interactive` | `codex plugin add` |
| Claude Code | `npx bookmark-research@latest install claude --scope user --non-interactive` | `claude plugin install` |
| DeepSeek Harness (dsh) | `npx bookmark-research@latest install dsh --profile web --non-interactive` | `dsh plugin add` |

一次装多个：`npx bookmark-research@latest install claude dsh --profile web --non-interactive`。装到指定项目：`--scope project --project /path/to/project`（Claude Code）。全部参数见[安装说明](docs/installation.md)。

**让 agent 帮你装。** 把下面这段粘贴给 Codex、Claude Code 或 DeepSeek Harness (dsh)：

```text
请把 Bookmark Research 插件安装到你当前运行的这个宿主里。

1. 先确认你自己是哪个宿主：codex、claude 或 dsh。
2. 运行：npx bookmark-research@latest install <宿主> --non-interactive --json
   - Claude Code：加 --scope user（或 --scope project --project <目录>）。
   - DeepSeek Harness (dsh)：加 --profile <名称>；profile 名称请先问我。
3. 命令会输出 JSON。确认 "verified": true，有 "error" 就告诉我。
4. 不要在对话里向我要 API Key。请让我在终端运行 `bookmark-research setup` 自己输入。
5. 提醒我新建一个会话，让 Skill 和 MCP 工具生效。
```

安装补充说明：

- **npm 是三个宿主唯一的发布来源**，包内含共享运行时、Skill 和宿主适配文件。安装器下载发布包、生成该宿主需要的格式，再调用宿主原生命令登记。GitHub 提供源码、版本说明和安装清单；未发布源码用 Python 安装器。见[发布约定](docs/distribution.md)。
- **DeepSeek Harness (dsh) 可直接安装发布包。** 包内声明 `dsh.bundle.patch`，`dsh plugin --profile <名称> add bookmark-research@<版本>` 无需先导出即可安装。`desktop` profile 保留给 DeepSeek Harness 桌面版，请用桌面版自带 CLI 安装；安装器与向导会自行定位该 CLI。
- **Windows** 上常常没有能用的 `python3`，所以安装器会把检测到的 Python 路径写进各宿主的 MCP 配置。Codex 请用 `bookmark-research install codex` 安装，不要直接把仓库加进 Codex；`bookmark-research status` 可以查看实际使用的 Python。

## 配置页与更新

**进入配置页。** 在终端里不带参数运行 `bookmark-research` 就会打开菜单：修改配置与 API Key、检查服务、安装到其他宿主、更新、查看状态。别名 `bookmark`（或 `bookmark research`）等价，`bookmark-research setup` 直接进入向导。

| 要做什么 | 命令 |
| --- | --- |
| 修改偏好和 API Key | `bookmark-research setup` |
| 打开菜单 | `bookmark-research` · `bookmark` · `bookmark research` |
| 查看已装宿主、偏好、保存位置、最近研究、Key 状态 | `bookmark-research status` |
| 用脚本改偏好 | `bookmark-research config show` · `bookmark-research config set --input prefs.json` |
| JSON 配置说明与示例 | [配置指南](docs/configuration.md) · [部分配置 JSON](config/settings.example.json) |
| 更新或验证所有宿主 | `bookmark-research update` · `bookmark-research verify` |

没有全局安装时，在前面加 `npx bookmark-research@latest`。偏好和 Key 是用户级的，改一次就对所有已安装宿主生效；改完新建宿主会话即可。加 `--lang zh` 可让向导和菜单显示中文。默认 `quick` 只暴露 CLI 与 MCP 共用的 10 个原语；`deep`（或 `all`）启用完整目录（57 个名字，含 deprecated 别名），供明确需要的完整资料审计使用。显式 `tool_scope` 仍优先于预设。

**更新。** 运行 `npx bookmark-research@latest install`，在向导中确认升级覆盖，即可为已安装宿主采用最新发布版。Codex 无交互升级可用 `npx bookmark-research@latest install codex --non-interactive --replace-source`。`bookmark-research update` 刷新的是已登记来源：Git／npm 选择器沿用所选 ref，随包保留的构建或固定版本仍留在该构建。两种方式均保留偏好、Key 和数据；完成后新建宿主会话。

**API Key 都是可选的。** 在 `bookmark-research setup` 里输入（隐藏显示，输完当场检查，保存在仅当前用户可读的本地文件），或者设置环境变量（优先于已保存的 Key）。

| 环境变量 | 服务 | 不配置时 |
| --- | --- | --- |
| `EXA_API_KEY` | Exa 搜索与网页读取 | 在 Exa 允许的范围内匿名使用 |
| `PARALLEL_API_KEY` | Parallel 搜索与网页读取 | 免费匿名使用，额度较低 |
| `TAVILY_API_KEY` | Tavily 备用搜索与提取 | 使用免 Key 模式 |
| `JINA_API_KEY` | Jina 搜索 | Jina Reader 仍可匿名读取网页 |
| `DEEPSEEK_API_KEY` | 可选的 DeepSeek Search / Fetch | 不选择即可；其他 provider 仍可用 |
| `PERPLEXITY_API_KEY` | 可选的 Perplexity 结构化 Search | 只提供搜索来源，不提供网页抓取 |
| `XAI_API_KEY` | 可选的 Grok Agentic 搜索 | 独立 `agentic_search` 工具，不参与 URL 聚合 |
| `CUSTOM_AGENTIC_API_KEY` | 可选的用户自定义 OpenAI 兼容端点 | 单独的 `agentic_search` 通道；在 setup 中配置 Base URL／模型／协议 |
| `OPENAI_API_KEY` | 可选的 OpenAI Deep Research 任务 | 功能关闭；宿主自己的研究不受影响 |

在 setup 的密钥步骤，用空格勾选已启用服务所需的 Key，再在隐藏输入框逐个输入；不选即可跳过。Key 保存在独立的私有 `credentials.json`，也可由环境变量提供，且环境变量优先。Key 不放进 `prefs.json` 或 `settings.json`；设置 JSON 导入会拒绝凭据字段。每个 Key 对应的服务见[配置指南](docs/configuration.md)。偏好也可以直接在宿主会话里让 agent 改（「显示 Bookmark Research 的配置」「以后只用 Exa 搜索」），它会调用 `update_settings` 工具（需 deep 目录）。

## 数据保存在哪里

不会写入你的书签文件或插件目录。数据目录为 `$BOOKMARK_RESEARCH_DATA_DIR`，未设置时为 `${XDG_DATA_HOME:-~/.local/share}/bookmark-research`。

| 位置 | 内容 |
| --- | --- |
| `research/`（或输入旁边的 `<输入名>.bookmark-research/`） | 每个研究任务一个文件夹：报告、来源、证据，以及存放 agent 中间文件的 `work/` |
| `research-locations.json` | 所有任务文件夹的位置，改了位置设置后旧任务仍能列出 |
| `knowledge/` | 保存的网页读取：`sources/` 按每次读取保存，`pages/` 中相同正文只存一份 |
| `wiki/` | 审核后的知识页面与历史版本；`index.md` 目录、`log.md` 时间线 |
| `index.sqlite3`、`index.sqlite3.sources/` | 书签检索索引，以及导入数据包的托管快照 |
| `raw-library.sqlite3` | `locate(in=["archive"])` 背后的全文索引，可重建 |
| `${XDG_CONFIG_HOME:-~/.config}/bookmark-research/` | `settings.json` 和 `credentials.json`（仅当前用户可读） |

位置设置只影响新的研究任务，已有任务留在原处。

## Agent 循环与子代理

宿主模型负责规划、搜索／阅读、评估证据，再追查未解决的问题。Skill 指导这个循环，MCP 保存输入范围、证据、预算和进度；保存研究任务不会启动后台代理。

对于分组报告，插件提供“阅读代理 → 新的验证代理 → 覆盖检查 → 补查 → 报告”的流程。Codex 使用原生子代理和附带的委派指南；Claude Code、DeepSeek Harness (dsh) 使用已加载的宿主工作流接口。并发、取消和代理生命周期由宿主管理。每个子代理都需要拿到相关指令，并访问同一个研究存储。

工作流适配已有模拟接口测试，但安装成功不代表所有宿主都已跑通完整的多代理任务。所需条件见[宿主工作流](skills/bookmark-research/references/zh/host-workflows.md)；历史验证记录可从 Git 历史查阅。

## 插件包含什么

由 1 个 Skill、1 个本地 MCP 服务，以及这个服务内部连接的远程 MCP 和网页服务组成。宿主里只需要登记这 1 个本地 MCP。

| 层 | 组成 | 运行方式 | 需要配置 |
| --- | --- | --- | --- |
| Skill | [`bookmark-research`](skills/bookmark-research/SKILL.md) 及 11 份方法参考，每份都有[中文版](skills/bookmark-research/references/zh/skill-guide.md) | 由宿主加载 | 不需要 |
| 本地 MCP | `bookmark-research`，默认 10 个工具（见下表） | 宿主启动的 Python 进程 | 安装器自动完成 |
| 本地 MCP 调用的远程 MCP | [Exa](https://exa.ai)（搜索、网页读取）、[Parallel](https://parallel.ai)（搜索、备用读取）、[Tavily](https://tavily.com)（备用搜索） | HTTPS，不启动本地进程 | 可选 API Key |
| 本地 MCP 调用的 HTTP 服务 | [Jina Reader](https://jina.ai/reader)（备用读取；有 Key 时可搜索）；[DeepSeek Search / Fetch](https://api-docs.deepseek.com/guides/search/)；[Perplexity Search](https://docs.perplexity.ai/api-reference/search-post)（结构化结果） | HTTPS | 可选 provider Key |
| 模型搜索 API | [xAI Grok Responses](https://docs.x.ai/developers/tools/web-search)，可选网页与 X 搜索 | HTTPS | 可选 `XAI_API_KEY`；通过独立 `agentic_search` 调用 |
| 自定义模型 API | 用户配置的 OpenAI 兼容 Chat Completions／Responses 端点 | 用户配置的 HTTP(S) Base URL | `CUSTOM_AGENTIC_API_KEY`；须配置模型与协议，联网由上游决定 |
| 可选的宿主 MCP | Exa Agent、Parallel Task MCP、Tavily Research | 需自行加到宿主里 | `bookmark-research setup` 会给出步骤 |

本地 MCP 的工具：

| 分类 | 工具 | 回答什么 |
| --- | --- | --- |
| 本地画布 | `locate`、`read`、`walk` | 按文本／URL／目录子项／纯元数据定位；打开卡片或目录子项；沿画布关系遍历 |
| 诊断 | `health` | 有界的就绪摘要（不联网、不写索引） |
| 联网 | `search`、`fetch`、`ingest` | 发现结果；带 `content_state`/`capture_id` 的有界正文；宿主结果确定性归并 |
| 长任务 | `spawn`、`job` | 提交到本地持久化队列，观察或取消 |
| 知识 | `save` | 通过校验的 Wiki 修订与逐字引用 |

`locate(package_path=...)` 是“首次接触”：导入一个包、单卡或卡片导出（无 id 的 JSON，或 Netscape 书签 HTML），返回条目数、栏目（含 `source`/`temp_kind`）、Note、搜索引擎页、分隔符噪音行与重复组。`read` 打开命中，`walk` 沿画布边遍历，`save` 一次接收章节、精确引文与来源正文或 capture ID。

长任务或批量任务不会占住工具步：`spawn(task="fetch"|"ingest"|"research", args)` 入队，单例 `bookmark-research job worker` 用有界线程池执行，`job(job_id)` 查看状态与结果；队列由三个宿主与 CLI 共享。

`deep` 预设额外提供 deprecated 别名（`search_bookmarks`、`get_context`、`fetch_web`、`wiki_write` 等）、来源维护、完整研究记录、选路诊断与 Wiki 维护。旧名从默认目录隐藏，0.8.0 起拒绝。Git 时间上下文由宿主 shell 查询。

## 更多

- [安装说明](docs/installation.md)：全部安装方式、npm 更新与源码开发
- [使用指南](docs/user-guide.md)：首次使用、三种研究方式、语言
- [详细说明](docs/details.md)：使用方式、数据包与保存位置、宿主与验证范围、开发
- [结构与触发流程](docs/bookmark-research-architecture.md)

项目源自 [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas)。许可证：[GPL-3.0](LICENSE)。
