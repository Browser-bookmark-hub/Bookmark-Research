# 用户配置 JSON

[English](configuration.en.md) · **中文**

Bookmark Research 使用一份插件自己的 `settings.json` 保存跨宿主共享的偏好。首次安装可在终端向导中配置；之后可运行 `bookmark-research setup`，或复制本页的 [部分配置示例](../config/settings.example.json) 并导入。配置路径默认为 `~/.config/bookmark-research/settings.json`，可用 `BOOKMARK_RESEARCH_CONFIG` 或 `XDG_CONFIG_HOME` 更改。多个宿主使用同一路径即可共享设置。

```sh
bookmark-research config show
bookmark-research config set --input /absolute/path/to/my-settings.json
```

`config set` 会按字段合并示例里的部分 JSON，不会清掉未提及的设置。provider 名称和选择写在 `settings.json`；API Key 放在同目录的独立 `credentials.json`，也可通过 `setup` 隐藏输入或环境变量设置；环境变量优先。`config set --input` 只导入偏好，不接受 Key。`config show` 会显示生效后的设置和配置路径，不显示密钥。

## 放在这份 JSON 中的内容

这份文件适合保存 Bookmark Research 自己读取的长期偏好和连接参数：

- 搜索与读取来源：`search.providers`、`search.fallback_providers`、`fetch.provider`、`fetch.providers` 和并发策略。Perplexity 可用于结构化 URL 搜索，不能作为网页正文读取器。
- 用户习惯：`research.depth`、`research.response_language`、`research.methods`、`archive.enabled`、`wiki.after_research`、`output.mode` 以及缓存、限额和可用性检查选项。
- 模型端点：`custom_agentic` 中的 Base URL、模型名、协议和搜索模式。它通过独立 `agentic_search` 返回模型回答，不参加 `search_web` 的 URL 聚合。
- 插件直接调用的专业研究服务：`professional_research` 中的 OpenAI Deep Research 或 Parallel Task API 选择。

`config/settings.example.json` 是可导入的部分配置，可按需删除或修改字段。字段必须符合当前版本的设置 schema；无效值会被拒绝。配置项说明、默认值和完整有效设置结构见 [配置与归档参考](../skills/bookmark-research/references/zh/settings-and-archive.md)。

## MCP 与认证的边界

不要把所有 MCP 都塞进插件的 `settings.json`。Exa Agent、Parallel Task、Tavily Research 等由宿主直接启动或授权的 MCP，其 endpoint、启动命令、OAuth 和 header 格式由 Codex、Claude Code 或 DSH 自己管理；不同宿主格式不同，OAuth 凭据也应留在宿主。安装器/向导可以给出对应的接入步骤，但插件 JSON 不会注册或保存这些 host MCP。

如果某个服务由 Bookmark Research 自己通过 API 调用，它的选择和非敏感连接参数可以保存在插件 JSON 中，密钥仍单独管理。例如自定义模型：

```json
{
  "custom_agentic": {
    "enabled": true,
    "base_url": "https://gateway.example/v1",
    "model": "provider/model-name",
    "api_mode": "responses",
    "search_mode": "native"
  }
}
```

`search_mode: "native"` 会请求 Responses `web_search` 工具，需要上游实现该工具；Chat Completions 只能提示上游搜索，不能保证它联网。把对应密钥单独设置为 `CUSTOM_AGENTIC_API_KEY`，不要写入 JSON、命令行参数或对话。

插件支持的 API Key 与服务对应如下。只需配置已启用服务所需的 Key；用 `bookmark-research setup` 输入时会隐藏显示并自动保存。也可以手动维护凭据 JSON：

| Key | 插件调用的服务 |
| --- | --- |
| `EXA_API_KEY` | Exa 搜索与网页读取 |
| `PARALLEL_API_KEY` | Parallel 搜索与网页读取 |
| `TAVILY_API_KEY` | Tavily 备用搜索与提取 |
| `JINA_API_KEY` | Jina 搜索；Reader 可匿名读取 |
| `DEEPSEEK_API_KEY` | DeepSeek Search / Fetch |
| `PERPLEXITY_API_KEY` | Perplexity 结构化搜索 |
| `XAI_API_KEY` | Grok `agentic_search` |
| `CUSTOM_AGENTIC_API_KEY` | 自定义 OpenAI 兼容模型端点 |
| `OPENAI_API_KEY` | OpenAI Deep Research |

```json
{
  "EXA_API_KEY": "your-exa-key",
  "PARALLEL_API_KEY": "your-parallel-key",
  "PERPLEXITY_API_KEY": "your-perplexity-key",
  "CUSTOM_AGENTIC_API_KEY": "your-custom-endpoint-key"
}
```

默认凭据路径为 `~/.config/bookmark-research/credentials.json`，文件为未加密的本地明文，权限要求为 `0600`（仅当前用户可读）。建议用 `setup` 写入，避免手动编辑后权限不正确。可用 `BOOKMARK_RESEARCH_CREDENTIALS` 改路径。宿主直接运行的 MCP 不读取这份凭据文件；它需要的 Key 应按该宿主的方式配置。

其他入口：在宿主会话中调用 `update_settings` 改长期设置；用 `bookmark-research config show` 查看当前配置。安装或升级后，收据会打印本指南和重开向导的命令。
