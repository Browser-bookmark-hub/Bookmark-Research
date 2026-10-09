# Bookmark Research

[English](README.md) · **中文**

用联网查证来研究你的书签。给它一份书签 URL 列表或 [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas) 数据包，它会逐条核对链接、搜索和阅读网页，写出带引用、可以接着做的研究报告。

支持 **Codex、Claude Code、Pi、DSH（DeepSeek Harness）**。

[安装说明](docs/installation.md) · [使用指南](docs/user-guide.md) · [详细说明](docs/details.md) · [npm](https://www.npmjs.com/package/bookmark-research)

> [!NOTE]
> **0.5.0 是测试版。** 遇到问题请到 [GitHub Issues](https://github.com/Browser-bookmark-hub/Bookmark-Research/issues) 反馈。

**发布版统一从 [npm](https://www.npmjs.com/package/bookmark-research) 安装。** GitHub Releases 保留版本说明和 npm 链接，安装包／测试包附件已撤下。GitHub 自动生成的 **Source code** 压缩包是源码快照，不是安装包。

## 环境要求

- Python 3.9+，含 SQLite FTS5（可用 `bookmark-research doctor` 检查）
- 至少一个宿主的 CLI：Codex、Claude Code、Pi 或 DSH（DSH 另需 `pnpm`）
- 发布版安装需要 Node 18+ 和 npm（GitHub 便捷脚本也需要）
- 安装和本地查书签都不需要 API Key

## 安装

**当前测试版（`0.5.0-beta.7`）**，支持 macOS、Linux、Windows 交互安装：

```sh
npx bookmark-research@0.5.0-beta.7 install --source npm:bookmark-research@0.5.0-beta.7
```

这条命令同时固定安装器和插件内容。下面的 `@latest` 示例使用默认渠道，目前仍为 `0.5.0-beta.3`；`@beta` 当前指向 `0.5.0-beta.7`。只改 npx 的版本选择，不会改变安装器默认下载的内容来源。

**默认渠道的交互安装：**

```sh
npx bookmark-research@latest install
```

用方向键和空格选择宿主，确认汇总后安装，再选择搜索服务、输入 API Key。装好后新建一个宿主会话。

想一直能用 `bookmark-research` 命令：`npm install -g bookmark-research`。GitHub 便捷脚本也使用同一 npm 发布版（macOS/Linux/WSL）：`curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash`。

**指定宿主、不弹提示：**

| 宿主 | 命令 | 实际登记方式 |
| --- | --- | --- |
| Codex | `npx bookmark-research@latest install codex --non-interactive` | `codex plugin add` |
| Claude Code | `npx bookmark-research@latest install claude --scope user --non-interactive` | `claude plugin install` |
| Pi | `npx bookmark-research@latest install pi --non-interactive` | `pi install` |
| DSH | `npx bookmark-research@latest install dsh --profile web --non-interactive` | `dsh plugin add` |

**四个宿主统一发布来源：** npm 包包含共享运行时、Skill 和宿主适配。安装器下载发布包，生成所选宿主格式，再调用宿主原生命令；更新记录 npm 来源，不依赖 npx 临时缓存。GitHub 提供源码和安装清单，未发布源码用 Python 安装器。见[发布约定与官方依据](docs/distribution.md)。

**DSH 可直接安装发布包：** 发布包声明 `dsh.bundle.patch`，`dsh plugin --profile <名称> add bookmark-research@<版本>`（或 DSH 插件管理界面）无需先导出即可安装，Python 与 MCP 路径按安装位置解析。DeepSeek Harness 桌面版把 `desktop` profile 保留给自身载体，该 profile 请用桌面版自带 CLI 安装。详见[安装说明](docs/installation.md)。

**Windows：** Windows 上常常没有能用的 `python3`，所以安装器会把检测到的 Python 路径写进各宿主的 MCP 配置。Codex 请用 `bookmark-research install codex` 安装，不要直接把仓库加进 Codex。`bookmark-research status` 可以查看实际使用的 Python。

一次装多个：`npx bookmark-research@latest install claude dsh --profile web --non-interactive`。装到指定项目：`--scope project --project /path/to/project`（Claude Code、Pi）。全部参数见[安装说明](docs/installation.md)。

**让 agent 帮你装。** 把下面这段粘贴给 Codex、Claude Code、Pi 或 DSH：

```text
请把 Bookmark Research 插件安装到你当前运行的这个宿主里。

1. 先确认你自己是哪个宿主：codex、claude、pi 或 dsh。
2. 运行：npx bookmark-research@latest install <宿主> --non-interactive
   - Claude Code 或 Pi：加 --scope user（或 --scope project --project <目录>）。
   - DSH：加 --profile <名称>；profile 名称请先问我。
3. 命令会输出 JSON。确认 "verified": true，有 "error" 就告诉我。
4. 不要在对话里向我要 API Key。请让我在终端运行 `bookmark-research setup`
   （或 `npx bookmark-research@latest setup`）自己输入。
5. 提醒我新建一个会话，让 Skill 和 MCP 工具生效。
```

## 配置与 API Key

不需要重新安装。配置和 Key 对所有已安装的宿主生效，修改后新建宿主会话即可。

| 要做什么 | 命令 |
| --- | --- |
| 主菜单：配置、检查、安装、更新 | `bookmark-research` |
| 修改偏好和 API Key | `bookmark-research setup` |
| 查看已装宿主、偏好、保存位置、最近研究、Key 状态 | `bookmark-research status` |
| 用脚本改偏好 | `bookmark-research config show` · `bookmark-research config set --input prefs.json` |
| 更新或验证所有宿主 | `bookmark-research update` · `bookmark-research verify` |

没有全局安装时，在前面加 `npx`，例如 `npx bookmark-research@latest setup`。

**API Key 都是可选的。** 在 `bookmark-research setup` 里输入（隐藏显示，输完当场检查，保存在仅当前用户可读的本地文件），或者设置环境变量（优先于已保存的 Key）。Key 不接受对话、命令参数或 JSON 文件。

| 环境变量 | 服务 | 不配置时 |
| --- | --- | --- |
| `EXA_API_KEY` | Exa 搜索与网页读取 | 在 Exa 允许的范围内匿名使用 |
| `PARALLEL_API_KEY` | Parallel 搜索与网页读取 | 免费匿名使用，额度较低 |
| `TAVILY_API_KEY` | Tavily 备用搜索与提取 | 使用免 Key 模式 |
| `JINA_API_KEY` | Jina 搜索 | Jina Reader 仍可匿名读取网页 |
| `OPENAI_API_KEY` | 可选的 OpenAI Deep Research 任务 | 功能关闭；宿主自己的研究不受影响 |

setup 还会问研究报告和证据放在哪里：统一目录（默认 `<数据目录>/research`，路径可改），或放在书签文件／文件夹旁边（放不了时退回统一目录）。只影响新的研究，已有任务留在原处。接着问研究结束后是否整理进 Wiki：给出建议并先问你（默认）、自动、关闭。

研究深度、答复语言、服务选择、归档、结果位置、Wiki 整理这些偏好，也可以直接在宿主会话里让 agent 改，它会调用 `update_settings` 工具。

## 数据保存在哪里

不会写入你的书签文件或插件目录。数据目录为 `$BOOKMARK_RESEARCH_DATA_DIR`，未设置时为 `${XDG_DATA_HOME:-~/.local/share}/bookmark-research`。

| 位置 | 内容 |
| --- | --- |
| `research/`（或输入旁边的 `<输入名>.bookmark-research/`） | 每个研究任务一个文件夹：报告、来源、证据，以及存放 agent 中间文件的 `work/` |
| `research-locations.json` | 所有任务文件夹的位置，改了位置设置后旧任务仍能列出 |
| `knowledge/` | 保存的网页读取：`sources/` 按每次读取保存，`pages/` 中相同正文只存一份 |
| `wiki/` | 审核后的知识页面与历史版本；`index.md` 目录、`log.md` 时间线 |
| `index.sqlite3`、`index.sqlite3.sources/` | 书签检索索引，以及导入数据包的托管快照 |
| `raw-library.sqlite3` | `search_archive` 使用的全文索引，可重建 |
| `${XDG_CONFIG_HOME:-~/.config}/bookmark-research/` | `settings.json` 和 `credentials.json`（仅当前用户可读） |

## Agent 循环与子代理

宿主模型负责规划、搜索／阅读、评估证据，再追查未解决的问题。Skill 指导这个循环，MCP 保存输入范围、证据、预算和进度；保存研究任务不会启动后台代理。

对于分组报告，插件提供“阅读代理 → 新的验证代理 → 覆盖检查 → 补查 → 报告”的流程。Codex 使用原生子代理和附带的委派指南；Claude Code、DSH 使用已加载的宿主工作流接口；Pi 需要加载相应的子代理／工作流扩展。并发、取消和代理生命周期由宿主管理。每个子代理都需要拿到相关指令，并访问同一个研究存储。

工作流适配已有模拟接口测试，但安装成功不代表所有宿主都已跑通完整的多代理任务。所需条件见[宿主工作流](skills/bookmark-research/references/zh/host-workflows.md)，实际验证范围见[验证记录](docs/validation-0.4.0.md#host-and-provider-boundaries)。

## 插件包含什么

由 1 个 Skill、1 个本地 MCP 服务，以及这个服务内部连接的远程 MCP 和网页服务组成。宿主里只需要登记这 1 个本地 MCP。

| 层 | 组成 | 运行方式 | 需要配置 |
| --- | --- | --- | --- |
| Skill | [`bookmark-research`](skills/bookmark-research/SKILL.md) 及 11 份方法参考，每份都有[中文版](skills/bookmark-research/references/zh/skill-guide.md) | 由宿主加载 | 不需要 |
| 本地 MCP | `bookmark-research`，40 个工具（见下表；随能力增长） | 宿主启动的 Python 进程 | 安装器自动完成 |
| 本地 MCP 调用的远程 MCP | [Exa](https://exa.ai)（搜索、网页读取）、[Parallel](https://parallel.ai)（搜索、备用读取）、[Tavily](https://tavily.com)（备用搜索） | HTTPS，不启动本地进程 | 可选 API Key |
| 本地 MCP 调用的 HTTP 服务 | [Jina Reader](https://jina.ai/reader)（备用读取；有 Key 时可搜索） | HTTPS | 可选 `JINA_API_KEY` |
| 可选的宿主 MCP | Exa Agent、Parallel Task MCP、Tavily Research | 需自行加到宿主里 | `bookmark-research setup` 会给出步骤 |

本地 MCP 的工具：

| 分类 | 工具 |
| --- | --- |
| 书签 | `sync_package`、`index_status`、`source_history`、`source_remove`、`source_merge`、`search_bookmarks`、`get_context` |
| 网页 | `search_web`、`fetch_web`、`search_archive`、`search_providers` |
| 研究 | `research_readiness`、`research_start`、`research_status`、`research_search`、`research_fetch`、`research_source`、`research_record`、`research_inventory`、`research_coverage`、`research_import_evidence`、`research_finish`、`research_route` |
| 专业研究服务（可选） | `research_services`、`research_service_prepare`、`_start`、`_status`、`_result`、`_cancel`、`_attach`、`_import` |
| 设置 | `get_settings`、`update_settings` |
| Wiki 与评测 | `wiki_write`、`wiki_get`、`wiki_list`、`wiki_search`、`wiki_lint`、`wiki_acknowledge`、`evaluate_research` |

## 更多

- [安装说明](docs/installation.md)：全部安装方式、npm 更新与源码开发
- [使用指南](docs/user-guide.md)：首次使用、三种研究方式、语言
- [详细说明](docs/details.md)：使用方式、数据包与保存位置、宿主与验证范围、开发
- [结构与触发流程](docs/bookmark-research-architecture.md)

项目源自 [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas)。许可证：[GPL-3.0](LICENSE)。
