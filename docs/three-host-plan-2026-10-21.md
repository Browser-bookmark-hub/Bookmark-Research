# 三宿主收敛计划（DSH / Claude Code / Codex，2026-10-21）

> 状态：核心删除已完成（2026-10-21）。目标：删除 Pi 支持，只保留 DSH、Claude Code、Codex 三个宿主；随后处理模型白名单和第三阶段工具可见性。
>
> 历史 release notes / 旧计划中出现的 Pi 记录保留，不重写历史；本计划只改当前代码、安装器、导出、测试和现行文档。

## 1. 目标

1. 当前支持宿主：**Codex、Claude Code、DSH**。
2. Pi 从主动代码中移除：
   - `hosts/pi/` 删除；
   - `package.json` 的 `pi` 字段与 `pi-package` keyword 删除；
   - 安装器、onboarding、readiness、routing、host installer、host clients、host assets、export bundle 不再接受或生成 Pi；
   - 测试不再把 Pi 当支持宿主；Pi 参数应报“不支持”。
3. 现行文档改为三宿主；历史 release notes 保留 Pi 记录并标注“当前已移除”。
4. 三宿主继续共享同一套 MCP 工具、Skill 和 workflow 资产。

## 2. 非目标

- 不删除历史 release notes、旧计划、旧验证记录里的 Pi 文字。
- 不重写 Bookmark Canvas 数据包格式。
- 不在本轮改 OpenAI 模型适配器（另列 §6 后续）。
- 不删除用户已有的 Pi 安装目录；只停止新安装/注册。

## 3. 受影响文件

### 代码

| 文件 | 动作 |
|---|---|
| `hosts/pi/runtime.js`、`hosts/pi/register-workflow.py` | 删除整个目录 |
| `package.json` | 删除 `pi` 字段、`pi-package` keyword |
| `src/onboarding.py` | HOSTS 去掉 Pi；报错文案/引导去掉 Pi |
| `src/readiness.py` | Pi 分支、host 映射去掉 |
| `src/routing.py` | HOSTS、Pi workflow 分支去掉 |
| `src/cli.py` | `--host` choices 去掉 pi |
| `src/mcp_server.py` | `research_route`/`research_readiness` host enum 去掉 pi |
| `scripts/install.py` | HOSTS、参数校验、帮助、交互选择去掉 Pi |
| `scripts/host_install.py` | host 集合去掉 pi |
| `scripts/host_clients.py` | Pi 路径/注册/验证分支删除 |
| `scripts/host_assets.py` | Pi 资产、workflow 构建删除 |
| `scripts/export_bundle.py` | FORMATS、Pi 导出分支、说明删除 |
| `install.sh` | Pi 相关参数/提示删除 |

### 测试

- `tests/test_install.py`、`test_host_install.py`、`test_onboarding.py`、`test_export_bundle.py`、`test_routing.py`、`test_launcher.py`、`test_bootstrap.py`、`test_npm_source.py`、`test_host_workflows.py`、`host-discovery.test.js`、`host-workflows.test.js`
- 删除 Pi 专有用例；host 枚举断言改为三宿主；Pi 输入应断言被拒绝。

### 文档

- 现行：`README.md`、`README.zh.md`、`docs/installation.md`、`docs/installation.en.md`、`docs/instructions.md`、`docs/instructions.en.md`、`docs/details.md`、`docs/details.en.md`、`docs/harness-compatibility.md`、`docs/distribution.md`、`skills/bookmark-research/references/host-workflows.md`、`zh/host-workflows.md`、`hosts/shared/*` 说明。
- 历史：`docs/release-notes-*`、旧 plan / audit 保留，不逐个改写。

## 4. 实施顺序

| 步 | 内容 | 完成标志 |
|---|---|---|
| 1 | 删 `hosts/pi`、package 的 Pi 字段 | 包内无 `hosts/pi` |
| 2 | 收窄代码 host 集合与路由 | `grep` 无主动 `"pi"` host 分支 |
| 3 | 收窄安装/导出 | `--host pi` 报错；export 无 pi 格式 |
| 4 | 更新测试 | 全量通过；Pi 断言为拒绝 |
| 5 | 更新现行文档 | 三宿主说明一致 |
| 6 | 全量测试 + 导出冒烟 | 见 §5 |

## 5. 验收结果（2026-10-21）

- 全量 Python 测试：**768 通过，3 跳过**（Pi 用例删除、模型/scope 测试增加后）。
- `hosts/pi/` 已删除；`package.json` 无 `pi` / `pi-package`。
- `--host pi` / `--format pi` 已不被接受。
- 现行 README、installation、details、distribution、instructions、prompt-reference、architecture、host-workflows、CLI/settings 参考已改三宿主；harness-compatibility 顶部标注 Pi 段落为历史。
- 历史 release notes、旧 plan、validation 记录保留，不重写。

## 6. 原验收清单

- `python3 -m unittest discover -s tests -p 'test_*.py'` 通过（预计测试数减少）。
- `python3 scripts/install.py --host pi` 明确报“unsupported host”。
- `python3 scripts/export_bundle.py --format pi` 明确报未知格式。
- `package.json` 无 `pi` / `pi-package`。
- `find hosts -maxdepth 2` 只有 codex / claude / dsh / shared。
- 三宿主导出冒烟：
  - Codex `.codex-plugin/plugin.json` + `.mcp.json`；
  - Claude `.claude-plugin/plugin.json` + `.mcp.json`；
  - DSH `bundle.patch.yml` + `hosts/dsh/plugin.js`。

## 7. 后续（本计划之后）

1. **模型白名单**：已完成代码——默认 `gpt-5.6-sol`，允许用户填 model ID；未知模型显式 `allow_untested_model`；仍兼容旧 o3/o4-mini 配置。
2. **Deep Research 适配器**：已完成代码——`gpt-5.6-sol` 使用 `web_search`，旧模型用 `web_search_preview`，保留 background / `max_tool_calls`；真实 key 验收待做。
3. **第三阶段可见性**：已完成；DSH/Codex 默认全量目录，`BOOKMARK_RESEARCH_TOOL_SCOPE`/`enabled_tools` 仍可收窄。
4. **三宿主实际情况核对**：DSH/Claude/Codex 各自的工具可见性、权限、API key 边界；不再假设四宿主一致。

## 8. 风险

| 风险 | 处理 |
|---|---|
| 测试大量依赖 Pi | 先删专有用例，再把 host 枚举断言改三宿主 |
| 历史文档仍有 Pi | 保留历史，现行文档加“Pi 已移除” |
| 用户已有 Pi 安装 | 不自动删除其本地目录；只停止新安装 |
| 导出格式破坏 | 保留 codex/claude/dsh 三种；Pi 格式报错而不是静默生成 |
| 8 工具 scope 仍藏研究工具 | 已改为默认全量；需要时可手动收窄 |
