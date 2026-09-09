# 配置与来源归档

用户可直接在对话中改配置，CLI 与 MCP 使用同一套实现。当前没有独立图形设置页。

搜索 provider 可选 `exa`、`parallel`、`tavily`，默认前两者；fetch 默认 Exa。Tavily 有 `TAVILY_API_KEY` 时使用 Bearer，否则发送 keyless header；公共访问取决于当时限额，不能保证免密执行。密钥只从进程环境读取。

## 配置入口

`get_settings` 返回有效设置及 `config_path`，只读不创建文件。`update_settings` 接收 `changes`，按字段合并并持久保存；后续调用立即读取新设置，不需重启 MCP。例如用户要求以后仅用 Exa 并打开归档：

```json
{"changes":{"search":{"providers":["exa"]},"archive":{"enabled":true}}}
```

多个 CLI／MCP 进程同时更新同一配置时，通过配置旁的 `.<文件名>.lock` 串行合并，再原子替换配置文件；不同字段的更新不会互相覆盖。锁文件会保留，锁等待超过 10 秒则返回超时。

支持的有效配置形状如下；`directory` 的示例路径须换成使用者选择的绝对路径，也支持 `~`：

```json
{
  "schema_version": 1,
  "timeout_seconds": 30,
  "search": {"providers": ["exa", "parallel"], "limit_per_target": 5},
  "fetch": {"provider": "exa", "max_characters": 12000},
  "archive": {"enabled": true, "directory": "/absolute/path/to/knowledge"}
}
```

优先级为本次调用参数 → 用户持久配置 → 内置默认值。`fetch_web.archive=false` 只禁用这次保存；改变今后默认值用 `update_settings`。`max_characters` 范围为 100–100000，只有 provider 支持对应参数时才会传递限制，实际请求参数记录在归档中；`character_limit_applied: false` 表示服务未提供本插件支持的长度参数。加大限额不保证得到完整页面。

配置文件路径：CLI `--config` → `BOOKMARK_RESEARCH_CONFIG` → `${XDG_CONFIG_HOME:-~/.config}/bookmark-research/settings.json`。归档默认目录为 `${BOOKMARK_RESEARCH_DATA_DIR}/knowledge`；未指定数据目录时采用 `${XDG_DATA_HOME:-~/.local/share}/bookmark-research/knowledge`。不同载体指向同一配置文件和数据目录即可共享偏好及档案。API key 仍交给宿主或进程环境，不写进配置文件。

`XDG_CONFIG_HOME` 与 `XDG_DATA_HOME` 必须是绝对路径；空值或相对路径按 XDG 规范忽略，使用用户主目录下的默认位置，避免随客户端工作目录漂移。

长期偏好存这里；不修改可能由导出模板覆盖的数据包 `AGENTS.md`。配置文件、知识目录和 SQLite 都位于插件及画布包之外，插件升级不打包这些用户数据。当前没有 Wiki、embedding 或后台监控开关，因为尚未实现对应功能。

## 一次读取怎样保存

`fetch_web` 自动保存它自己收到的实际 provider 响应。搜索命中本身不触发抓取或存档，宿主另外配置的 Exa／GitHub MCP 响应也不会被本插件自动截获。

认证、传输或工具契约失败且没有取得实际响应时，返回 `status:"error"`、`error_kind` 和 `usage`，不包含 `result`，也不生成虚构归档。已经取得响应但没有提取出正文时，仍保留实际 `result` 与逐页状态。MCP 将完整调用失败标为 `isError:true`；部分成功保留可用结果。

```text
knowledge/
  sources/
    <本次抓取时间与唯一 ID>/
      response.json
      manifest.json
      pages/<URL 哈希>.md
```

- `response.json` 是 MCP 返回的原始结果对象，包含文本块和 provider 状态；不是网页原始 HTML，也不包含本插件的认证请求头。
- Markdown 保存能确认关联到指定 URL 的实际提取文本，不让模型凭摘要补全文。来源信息放在 `manifest.json`，避免混入原文。
- manifest 记录请求 URL、返回 URL、provider、tool、实际请求参数、检索时间、响应哈希 `response_sha256`、正文路径与哈希，以及失败、缺失、摘录或可能截断的标记。服务返回的发布时间与作者分别放在 `provider_published_at`、`provider_author`，不混入正文。`completeness: "unknown"` 表示不能证明完整。`possibly_truncated: false` 也不是完整性保证。
- `#comments` 等锚点会保留，但网页提取不保证所有评论已加载；`fragment_scope_verified: false` 明示这一点。检索时间不等于网页发布时间、更新时间或缓存时间。
- 返回格式无法识别时仍保存响应与 manifest，正文路径为空；部分 URL 失败时只保存成功识别的正文。每页的 `extraction_status: "provider_error"` 表示服务报告失败；同一 URL 的正文冲突时为 `conflicting_provider_results`，不自动挑选一份正文。归档失败会在 `archive.status: "error"` 明示，工具仍返回已收到的内容，不自动重复付费抓取。
- 再读同一 URL 会追加新快照，不覆盖旧档案；这只是按调用保存，不是后台版本监控。

报告来源清单可引用 `archive.manifest_path` 和各页 `body_path`。这些档案不会自动加入书签 SQLite，也不会自动生成跨来源 Wiki。外部工具结果如需留存，由当前任务另外保存其实际返回内容并标明来源；本版没有独立的外部响应导入工具。

深度研究使用独立的 `research/` 目录保存状态和证据。`research_fetch` 始终保存已取得的研究响应和正文，普通 fetch 的 archive 开关不影响它；任务恢复和引用校验需要这些快照。会话详情与分页见 [深度研究流程](deep-research.md)。
