# 全量 diff 审计（2026-10-21）

> 范围：当前工作树相对 `HEAD` 的全部 tracked 修改、删除和新增文件。
>
> 规模：**66 个 tracked 文件，+1301 / −736；10 个新增文件**。
>
> 验证：**768 个 Python 测试通过，3 个跳过**；真实样本包网络/压测记录见文末。

## 1. 一句话结论

这次 diff 做完了四件事：

1. **预检与证据链**：`plan_research` 从“排卡片”升级为带 Wiki/归档/相关性/时效/URL 类型/预算的本地预检；`fetch_web` 修了多页预算饿死和证据回链。
2. **真实网络与规模验证**：真实包 URL 跑了 `search_web`/`fetch_web`/宿主 fetch，100k 书签跑了合成压测。
3. **宿主收敛**：删除 Pi，只保留 Codex / Claude Code / DSH。
4. **模型与工具面**：OpenAI 默认改为 `gpt-5.6-sol`，允许自填 model ID；DSH/Codex 默认不再藏第三阶段工具。

尚未完成的是**发布和真实宿主/真实 API 验收**，不是代码主体。

## 2. 按模块拆分

### A. 预检与索引（核心改动）

| 文件 | 变化 | 状态 |
|---|---|---|
| `src/research_plan.py` | 新增 relevance、freshness、priority terms、Wiki/archive 预检、URL 类型、fetch ownership、bounded output | 已实现，测试覆盖 |
| `src/bookmark_index.py` | `url_kind`、`title_has_term`、stale 缺文件、`newest_high`、`term_hits`/`term_title_hits`、homepage limit、URL 排序 | 已实现，测试覆盖 |
| `src/wiki.py` | `search_terms` 按词合并，worst-of 状态，needs_review 不被降级 | 已实现 |
| `src/raw_library.py` | `search_terms` 按词合并，只返回可复用 capture | 已实现 |
| `src/archive.py` | fair-share 预算、0 字页 unavailable、`pages_with_text`/`without` | 已实现 |
| `src/context_output.py` | `compact_context` 去 raw/description/revision | 已实现 |
| `src/mcp_server.py` | schema 扩展、`tool_scope`、capture hydration/SHA、fetch 默认预算、compact | 已实现 |
| `src/settings.py` | 新预检/fetch/plan/tool_scope 默认值与校验 | 已实现 |
| `src/cli.py` | `fetch-web` 使用设置预算，capture 支持 | 已实现 |

真实包验证暴露并修掉：

- `A-10-2` 缺文件仍占据 top 卡 → stale 标记，URL 保留但卡不占 top。
- 单字/双字 CJK 误命中，`quantum` 命中 `QuantumNous` → 相关性门禁。
- 长唯一词（`unique5000`）被分数门槛误杀 → token-aware 标题命中。
- `file://` 被排第一 → `local_file`，排最后，`fetch_web` 拒绝。
- 24k 预算被前几页吃光 → fair share，8/8 页都有正文。
- `AI` 这种两字母大写缩写被丢弃 → 计为 meaningful。

### B. 网络与性能验证

新增：

- `scripts/bench_preflight.py`
- `docs/bench-preflight-2026-10-21.md`
- `docs/network-test-2026-10-21.md`
- `docs/search-latency-provider-research-2026-10-21.md`

结论：

- 100k 书签预检 p50：`alpha` 388ms、`alpha beta` 507ms、唯一长词 123ms；输出约 1.9–4.1k 字符。
- 真实包 `search_web`：暖会话 20 URL 约 1.86s；冷启动约 5s（MCP 握手）。
- 真实 `fetch_web`：6–8 页单 provider 7–17s；Exa+Parallel 分片暖会话约 1.68s/6 页。
- 豆包官方文档标称 700ms/50 条且带正文；这是“搜索即带正文”的架构，不是本插件当前的单 provider 逐页 fetch。
- OpenAI Deep Research 官方标称 5–30 分钟；不能和 2–3 秒搜索混为一谈。

### C. 宿主收敛（Pi 删除）

- 删除 `hosts/pi/runtime.js`、`hosts/pi/register-workflow.py`。
- `package.json` 删除 `pi` / `pi-package`。
- 安装器、onboarding、readiness、routing、host installer、host assets、export bundle、CLI 全部只接受 Codex / Claude / DSH。
- `--host pi`、`--format pi` 被拒绝。
- 测试删除 Pi 用例，改为三宿主；全量 768 通过。
- 现行 README/installation/details/distribution/instructions/prompt/architecture/host-workflows 已改三宿主。
- 历史 release notes、旧 plan、`harness-sources.json`、`host-validation.json` 保留 Pi 记录；`harness-compatibility.md` 顶部标注历史。

### D. 模型与 Deep Research 适配器

- `src/settings.py`：默认 `gpt-5.6-sol`；`allow_untested_model`。
- `src/research_services.py`：`gpt-5.6-sol` 用 `web_search`；旧 o3/o4 用 `web_search_preview`；`background`/`max_tool_calls` 保留。
- `src/mcp_server.py`：设置 schema 允许 model 模式串和 `allow_untested_model`。
- 测试：默认模型、未知模型拒绝/显式放行、`web_search` payload。
- **未验证**：真实 `OPENAI_API_KEY` 的 Deep Research 任务。

### E. 工具面

- DSH `hosts/dsh/plugin.js`：默认不再设 8 项 scope，改为全量目录；环境变量仍可收窄。
- Codex `.codex/config.toml`：移除 8 项 `enabled_tools`，默认全量。
- `BOOKMARK_RESEARCH_TOOL_SCOPE` 空值 = 全量；逗号列表 = 收窄。

## 3. 哪些是“做了但没验证”

| 项目 | 代码 | 验证 |
|---|---|---|
| 预检/索引/预算/证据链 | 完成 | 768 测试 + 真实包 |
| Pi 删除/三宿主导出 | 完成 | 单测/导出测试；**未重装真实宿主** |
| `gpt-5.6-sol` Deep Research | 完成请求体 | **无真实 API key** |
| DSH/Codex 全量工具面 | 完成配置 | **当前安装仍是旧版** |
| Claude 项目 scope 路径 | 改动 | **未做真实 Claude 项目安装** |
| `fetch_web` 分片并发 | 未实现 | 仅手工并行实验 1.68s |

## 4. 当前实际安装状态

| 宿主 | 已安装 | 说明 |
|---|---|---|
| DSH | `0.5.0-beta.15` | 旧代码，需更新/重装 |
| Claude Code | `0.5.0-beta.13+source...` | 更旧，需更新 |
| Codex | 插件旧版；项目配置已改 | 新线程 + 插件更新 |
| 仓库 | `0.5.0-beta.15`（未 bump） | 发布前需升到 beta.16 |

**注意**：DSH 已安装版本与源码版本相同（beta.15），直接 `add` 可能不刷新；需要移除后重加，或先 bump 版本。Claude 是内容派生版本，更新会刷新。

## 5. 还没做的（按优先级）

### P0：发布前

1. **版本号**：`package.json`、`.codex-plugin/plugin.json`、release notes 统一到 beta.16。
2. **发布**：npm publish / git tag（用户负责）。
3. **重装三宿主**：
   - DSH 移除/重加 profile bundle；
   - Claude 更新插件；
   - Codex 更新插件 + 新线程。

### P1：真实验收

4. **OpenAI Deep Research**：用真实 key 跑 1 个小任务，验证 `gpt-5.6-sol` + `web_search` + background + citations；不要压测。
5. **DSH 自带搜索**：与插件 `search_web` 对比真实延迟/质量；决定是否需要 DeepSeek provider。
6. **Claude 项目 scope**：验证 `.claude/settings.local.json` 路径和注册行为。

### P2：后续增强

7. **`fetch_web` 分片并发**：把 6–8 页从 7–17s 降到约 2–4s；需改 archive/证据合并契约。
8. **可选 DeepSeek Search provider**：搜索即带正文；当前未接入，非必需。
9. **历史 Pi 文档**：release notes / 旧 plan / validation 保留；如要全清需单独决定。
10. **文档旧计数**：个别历史文档仍写四宿主/旧测试数，属历史记录，不阻断发布。

## 6. 风险 / 需要复核

| 风险 | 说明 |
|---|---|
| DSH 同版本不刷新 | beta.15 → beta.15 可能 no-op；需移除重加或 bump |
| `gpt-5.6-sol` 不是专用 deep research 模型 | 官方指南称其为替代；真实工具/参数仍需 key 验收 |
| 44 工具全量 | 第三阶段可见，但模型工具面变大；需要时可用 scope 收窄 |
| Claude 项目路径改动 | 未真实跑过 project/local scope |
| 历史文档仍提 Pi | 已标注历史；不影响当前代码 |
| `docs/details.en.md` 等有非本次写入规则改动 | 属于工作树中既有/并行改动，未混入核心逻辑；发布前应确认是否要一起提交 |

## 7. 复核命令

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests \
  python3 -B -m unittest discover -s tests -p 'test_*.py'
# 768 passed, 3 skipped

git diff --check
python3 scripts/bench_preflight.py --repeats 3
```

相关报告：

- [预检压测](bench-preflight-2026-10-21.md)
- [真实网络测试](network-test-2026-10-21.md)
- [搜索时延官方核对](search-latency-provider-research-2026-10-21.md)
- [三宿主计划](three-host-plan-2026-10-21.md)
