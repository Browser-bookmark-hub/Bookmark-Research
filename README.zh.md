# Bookmark Research

[English](README.md) · **中文**

用联网查证来研究你的书签。给它一份书签 URL 列表或 [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas) 数据包，它会逐条核对链接、搜索和阅读网页，写出带引用、可以接着做的研究报告。

支持 **Codex、Claude Code、Pi、DSH（DeepSeek Harness）**。

[安装说明](docs/installation.md) · [使用指南](docs/user-guide.md) · [详细说明](docs/details.md) · [npm](https://www.npmjs.com/package/bookmark-research) · [Releases](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases)

> [!NOTE]
> **0.5.0 是测试版。** 遇到问题请到 [GitHub Issues](https://github.com/Browser-bookmark-hub/Bookmark-Research/issues) 反馈。

## 环境要求

- Python 3.9+，含 SQLite FTS5（可用 `bookmark-research doctor` 检查）
- 至少一个宿主的 CLI：Codex、Claude Code、Pi 或 DSH（DSH 另需 `pnpm`）
- `bookmark-research` 命令需要 Node 18+；macOS/Linux 上可不用
- 安装和本地查书签都不需要 API Key

## 安装

**交互安装**（macOS、Linux、Windows）：

```sh
npx bookmark-research install
```

用方向键和空格选择宿主，确认汇总后安装，再选择搜索服务、输入 API Key。装好后新建一个宿主会话。

想一直能用 `bookmark-research` 命令：`npm install -g bookmark-research`。不用 Node（macOS/Linux/WSL）：`curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash`。

**指定宿主、不弹提示：**

| 宿主 | 命令 | 实际登记方式 |
| --- | --- | --- |
| Codex | `npx bookmark-research install codex --non-interactive` | `codex plugin add` |
| Claude Code | `npx bookmark-research install claude --scope user --non-interactive` | `claude plugin install` |
| Pi | `npx bookmark-research install pi --non-interactive` | `pi install` |
| DSH | `npx bookmark-research install dsh --profile web --non-interactive` | `dsh plugin add` |

一次装多个：`npx bookmark-research install claude dsh --profile web --non-interactive`。装到指定项目：`--scope project --project /path/to/project`（Claude Code、Pi）。全部参数见[安装说明](docs/installation.md)。

**让 agent 帮你装。** 把下面这段粘贴给 Codex、Claude Code、Pi 或 DSH：

```text
请把 Bookmark Research 插件安装到你当前运行的这个宿主里。

1. 先确认你自己是哪个宿主：codex、claude、pi 或 dsh。
2. 运行：npx bookmark-research install <宿主> --non-interactive
   - Claude Code 或 Pi：加 --scope user（或 --scope project --project <目录>）。
   - DSH：加 --profile <名称>；profile 名称请先问我。
3. 命令会输出 JSON。确认 "verified": true，有 "error" 就告诉我。
4. 不要在对话里向我要 API Key。请让我在终端运行 `bookmark-research setup`
   （或 `npx bookmark-research setup`）自己输入。
5. 提醒我新建一个会话，让 Skill 和 MCP 工具生效。
```

## 配置与 API Key

不需要重新安装。配置和 Key 对所有已安装的宿主生效，修改后新建宿主会话即可。

| 要做什么 | 命令 |
| --- | --- |
| 主菜单：配置、检查、安装、更新 | `bookmark-research` |
| 修改偏好和 API Key | `bookmark-research setup` |
| 查看已装宿主、偏好、Key 状态 | `bookmark-research status` |
| 用脚本改偏好 | `bookmark-research config show` · `bookmark-research config set --input prefs.json` |
| 更新或验证所有宿主 | `bookmark-research update` · `bookmark-research verify` |

没有全局安装时，在前面加 `npx`，例如 `npx bookmark-research setup`。

**API Key 都是可选的。** 在 `bookmark-research setup` 里输入（隐藏显示，输完当场检查，保存在仅当前用户可读的本地文件），或者设置环境变量（优先于已保存的 Key）。Key 不接受对话、命令参数或 JSON 文件。

| 环境变量 | 服务 | 不配置时 |
| --- | --- | --- |
| `EXA_API_KEY` | Exa 搜索与网页读取 | 在 Exa 允许的范围内匿名使用 |
| `PARALLEL_API_KEY` | Parallel 搜索与网页读取 | 免费匿名使用，额度较低 |
| `TAVILY_API_KEY` | Tavily 备用搜索与提取 | 使用免 Key 模式 |
| `JINA_API_KEY` | Jina 搜索 | Jina Reader 仍可匿名读取网页 |
| `OPENAI_API_KEY` | 可选的 OpenAI Deep Research 任务 | 功能关闭；宿主自己的研究不受影响 |

研究深度、答复语言、服务选择、归档这些偏好，也可以直接在宿主会话里让 agent 改，它会调用 `update_settings` 工具。

## 插件包含什么

### Skill

| Skill | 用途 |
| --- | --- |
| [`bookmark-research`](skills/bookmark-research/SKILL.md) | 查书签、核对链接、对每条书签做完整研究并写出带引用的报告。英文执行版，另有[中文阅读版](skills/bookmark-research/references/zh/skill-guide.md)。 |

### MCP 服务

一个本地 stdio 服务 `bookmark-research`（`python3 src/cli.py serve`），共 36 个工具：

| 分类 | 工具 |
| --- | --- |
| 书签 | `sync_package`、`index_status`、`source_history`、`search_bookmarks`、`get_context` |
| 网页 | `search_web`、`fetch_web`、`search_providers` |
| 研究 | `research_readiness`、`research_start`、`research_status`、`research_search`、`research_fetch`、`research_source`、`research_record`、`research_inventory`、`research_coverage`、`research_import_evidence`、`research_finish`、`research_route` |
| 专业研究服务（可选） | `research_services`、`research_service_prepare`、`_start`、`_status`、`_result`、`_cancel`、`_attach`、`_import` |
| 设置 | `get_settings`、`update_settings` |
| Wiki 与评测 | `wiki_write`、`wiki_get`、`wiki_list`、`wiki_search`、`wiki_lint`、`evaluate_research` |

### 网页服务

由插件自带的 MCP 服务直接调用，不需要另外添加它们的 MCP。

| 服务 | 作用 |
| --- | --- |
| [Exa](https://exa.ai) | 主要搜索；首选网页读取 |
| [Parallel](https://parallel.ai) | 主要搜索；备用网页读取 |
| [Tavily](https://tavily.com) | 备用搜索 |
| [Jina Reader](https://jina.ai/reader) | 备用网页读取；有 Key 时可搜索 |

另有可选的研究 MCP 可以自己加到宿主里：Exa Agent、Parallel Task、Tavily Research。`bookmark-research setup` 会给出各宿主的接入步骤。

## 更多

- [安装说明](docs/installation.md)：全部安装方式、更新、ZIP 下载
- [使用指南](docs/user-guide.md)：首次使用、三种研究方式、语言
- [详细说明](docs/details.md)：使用方式、数据包与保存位置、宿主与验证范围、开发
- [结构与触发流程](docs/bookmark-research-architecture.md)

项目源自 [Bookmark Canvas](https://github.com/Browser-bookmark-hub/Bookmark-Canvas)。许可证：[GPL-3.0](LICENSE)。
