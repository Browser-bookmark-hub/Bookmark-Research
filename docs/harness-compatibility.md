# 宿主兼容、工作流与打包

更新日期：2026-10-21。**Pi 支持已移除；本文 Pi 相关段落仅作历史记录。** 三宿主共用同一 Skill、Python CLI、stdio MCP 和研究档案。当前宿主模型负责规划、搜索／阅读、判断证据、按缺口补查及综合；原生协作支持独立分工。Deep Research 在这条流程上增加持续调查、独立核验、覆盖检查和报告。外部研究 API 可承担具体子问题，缺少它们仍能研究。

**正文依据、文件生成、隔离脚本检查、真实 MCP 调用和宿主端到端研究是不同验证层级。** 本轮在 DSH 桌面版 profile `desktop` 上完成了一次真实安装，并观察到 Skill 注册与 MCP 工具实际应答；未改全局配置，未启动付费研究模型。具体脚本调用和研究规则见 [宿主工作流参考](../skills/bookmark-research/references/host-workflows.md)。

| 宿主 | 协作基础与本插件入口 | 生命周期与限制 |
| --- | --- | --- |
| Codex | `hosts/codex/delegate.md`＋原生子代理；`prepare.py` 读取全量分页、仅输出分组 | 使用当前会话原生工具，不假设有 JavaScript workflow runtime，不安装全局 agent 定义 |
| Claude Code | 普通 `Agent`／旧版 `Task`；可选已启用的 Agent Teams；整包可用 `/bookmark-research:bookmark-research` | 普通子代理可继承受过滤的 MCP 工具，Skill 需预载或读取；团队默认关闭且不继承主代理历史；Dynamic Workflow 为独立可选入口 |
| DSH | 已配置的 subagent；整包可将 `hosts/dsh/workflow-call.py` 生成的 `{meta,script,args}` 交给 `workflow` | profile 需提供相应服务与工具；`workflow` 等完整流程后返回结果，不能当作后台 start/poll 接口 |

本次通过插件的 Exa 检索并读取官方正文，新增依据为 [W12–W16]，并重读 [W3][W7]。这验证能力文档，没有执行三宿主完整研究。子代理须获得具体问题、范围、相关 Skill 内容和共享 MCP／CLI 数据入口，不能假定父代理上下文在三宿主间以相同方式继承。

本次默认流程调整通过 369 项单元测试、Skill／插件校验及新安装缓存的真实 stdio MCP 检查；5 个选路场景通过，61 个导出文件与缓存一致。这里只验证选路与工具接入，三宿主端到端研究仍未运行。记录见 [host-validation.json](host-validation.json) 的 `host_first_review`。

`research_route` 对普通 Agentic Search 优先选择当前模型的搜索／阅读循环，不强制完整研究会话；深度任务优先原生协作，整包 `batch_research` 才按偏好选择分组脚本。已保存 API 偏好只排列外部服务，显式 provider 才直接指定服务。路由依据当前工具和已加载能力，不凭宿主名称推断；没有子代理时主代理继续，并准确说明复核方式。

三种脚本和 Codex 委派均执行全量清单 → 分组阅读 → 独立核验 → 全量差集补查 → 保存完整分析 → 引用报告。保留全部 `u-` ID 及书签实例；`sN` 证据 ID 不能代替原始输入清单。每个 coverage filter 单独跟随 `next_offset` 到结束，差集长度须与 `difference_counts` 一致。抓取失败或全排除不能完成研究。

报告子代理通过 `research_record external_run` 保存完整分析 JSON，返回实际的 `recorded.result_path` 和 `recorded.result_sha256`。其中 `local:<run_key>` 明确是本地关联号；该观察记录已结束的分析阶段，不冒充原生宿主 run ID 或整项研究完成。最终仍由 `research_finish` 检查证据、问题和覆盖门槛。主代理收到宿主返回后，还须直接读取 `research_status` 和完整 coverage 分页，对照实际产物与附件哈希；脚本自身成功或报告子代理返回路径都不能代替核验。

| 本机检查（2026-09-11） | 结果与边界 |
| --- | --- |
| Codex 0.153.4 | `multi_agent` 为 stable、enabled；实际委派仍以会话可见工具为准 |
| Claude Code 2.1.247 | `claude plugin validate --strict` 通过、无警告；并未执行付费工作流 |
| 本地宿主测试 | 8 项通过，含 36 项隔离脚本检查；真实 stdio MCP 验证 207 项完整分页和完整结果附件回读 |
| DSH | PATH 中未安装 |
| 端到端研究 | 本轮未运行；不能由上述检查推断三宿主的完整研究已通过 |

正文 SHA-256、原生校验和检查记录见 [host-validation.json](host-validation.json)。本轮 [W1–W8] 来自 2026-09-10 保存的 Exa 提取正文，完整性为 unknown，来源站实时新鲜度未建立；补充接口资料于 2026-09-11 读取。

| ID | 已读依据 |
| --- | --- |
| W1 | [Claude Workflows](https://code.claude.com/docs/en/workflows) |
| W2 | [Introducing dynamic workflows](https://claude.com/blog/introducing-dynamic-workflows-in-claude-code) |
| W3 | [Codex customization](https://developers.openai.com/codex/concepts/customization) |
| W4 | [Codex workflows](https://developers.openai.com/codex/workflows) |
| W5 | [pi-subagents-workflows](https://pi.dev/packages/pi-subagents-workflows) |
| W6 | [pi-subagents](https://github.com/nicobailon/pi-subagents) |
| W7 | [DSH Workflow subsystem](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/workflow) |
| W8 | [DSH workflow tool](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/workflow/tool-workflow/README.md) |
| W9 | [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)（旧官方 URL 重定向后的已读页面） |
| W10 | [Pi extension workflows](https://github.com/nicobailon/pi-subagents/blob/main/docs/workflows.md) |
| W11 | [Pi extension tool reference](https://github.com/nicobailon/pi-subagents/blob/main/docs/tool-reference.md) |
| W12 | [Codex subagents](https://developers.openai.com/codex/subagents)，2026-09-13 经 Exa 重读：并发委派、等待、配置继承及显式委派规则 |
| W13 | [Claude subagents](https://code.claude.com/docs/en/sub-agents)：普通子代理、MCP 工具过滤、Skill 预载与任务上下文 |
| W14 | [Claude Agent Teams](https://code.claude.com/docs/en/agent-teams)：实验开关、共享任务、代理通信及上下文边界 |
| W15 | [Pi usage](https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/docs/usage.md)：核心不内置 MCP／子代理，通过扩展和包提供 |
| W16 | [Pi 官方 subagent 示例](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/examples/extensions/subagent)：单任务、并发和链式调用 |

下文保留 2026-09-07 至 09-10 的基础打包核验及 Codex 路径规则。H / P / D 来源见 [harness-sources.json](harness-sources.json)，历史版本测试见 `docs/archive/validation-0.2.0.md`。

| 目标 | 真实入口 | Skill／MCP 如何接入 | 本项目的最小路线 |
| --- | --- | --- | --- |
| OpenAI Codex 插件 | `.codex-plugin/plugin.json` | manifest 指向 skills、MCP 配置等组件 | 原生 Codex 包；具体安装与验证按本项目 README |
| Claude Code 插件 | `.claude-plugin/plugin.json`；当前文档允许省略 manifest 后按约定发现组件 | 根 `skills/`、`.mcp.json` 或 manifest 配置 | 单独保留 Claude manifest／MCP 配置 |
| DeepSeek Harness（DSH） | 包在 `package.json` 声明 `dsh.bundle.patch`，由 `dsh plugin` 或插件管理器安装；`--patch` 仍可手工加载 Cordis 配置 | 原生 Skill provider；官方 `dsh-mcp-client` 桥接 MCP tools | 发布包自带按安装位置解析的 `bundle.patch.yml`，registry 可直接安装；绝对路径 `cordis.patch.yml` 仅作手工适配 |

这些入口不是同一文件的不同别名。符合 Agent Skills 的 `SKILL.md` 和 MCP 协议是主要复用边界。

**1．稳定数据位置与共用入口**

本项目的 stdio MCP 启动方式：

```sh
python3 /absolute/path/to/bookmark-research/src/cli.py --db /absolute/path/to/plugin-data/index.sqlite3 serve
```

省略 `--db` 时，CLI 使用 `BOOKMARK_RESEARCH_DATA_DIR/index.sqlite3`；未设置时使用 `${XDG_DATA_HOME}/bookmark-research/index.sqlite3`，其中 `XDG_DATA_HOME` 默认是 `~/.local/share`。索引不放在插件安装缓存或原始书签包内。多个载体若要访问同一库，应明确指向同一个数据库路径；只保留相同插件名称并不会共享数据。

Codex 的 stdio MCP 需要显式允许转发自定义环境变量（[官方说明](https://developers.openai.com/codex/mcp#stdio-servers)）。本插件原生 manifest 的 `env_vars` 列出 `BOOKMARK_RESEARCH_DATA_DIR`、`BOOKMARK_RESEARCH_CONFIG`、`XDG_DATA_HOME`、`XDG_CONFIG_HOME`、`EXA_API_KEY`、`PARALLEL_API_KEY`、`TAVILY_API_KEY`；只在启动进程中设置变量而未透传时，MCP 可能仍读取默认目录。已使用全新临时目录核验空来源列表和虚构数据导入。

本项目五种导出均保留上述 CLI 行为，**不强制传入 `--db` 或 `${PLUGIN_DATA}`**。需要共库时，在各载体实际启动 MCP／CLI 子进程的环境中设置相同的 `BOOKMARK_RESEARCH_DATA_DIR`，或修改启动参数，显式指定同一 `--db` 路径。客户端可能过滤环境变量，不能仅凭外部终端已设置就断言子进程一定继承。

Skill 中应通过当前载体实际提供的工具或 CLI 调用能力，不把模型固定工具名前缀当成可移植协议。尤其 DSH 会把 MCP 工具映射成 `mcp__<serverName>__<tool>`；其他客户端的呈现方式由它们决定。[D04]

**3．DeepSeek Harness：配置 bundle 和运行插件是两层**

当前导出还提供原生工作流调用定义。`python3 hosts/dsh/workflow-call.py --research-id RID --run-key review-1` 输出完整工具参数，`meta`、无 export 的 `script` 与对象 `args` 分开。所选 profile 必须预先配置 workflow service、worker-thread engine 和 tool；只加载下方 MCP patch 不会自动启用 workflow。普通失败保留，fatal schema / cap 错误由宿主传播。完整分析结果显式保存到共享研究档案，不依赖宿主渲染摘要。[W7][W8]

DSH 当前官方 README 将项目标为 developer preview，并明确存在兼容性变化；因此这里依据当前 `master` 文档描述接口，没有承诺未来版本保持不变。[D01]

DSH 的原生运行插件是 Cordis 模块，可导出 `name`、`inject` 和 `apply(ctx, config)`。如果使用 tools 服务，就声明 `inject = ['tools']`；框架等依赖就绪后加载。对象和类形式也受支持。这与 Codex／Claude 的“目录 manifest 包装一组 Skill 和 MCP”不是同一个运行入口。[D03]

但本项目**无需为了接入 DSH 重写原生查询插件**。官方 `@deepseek-ai/dsh-mcp-client` 已经负责连接 stdio 或 Streamable HTTP MCP，调用 `tools/list` 并注册工具。它每个实例接一个 MCP server，支持取消、超时、重连及工具重新同步；本轮文档明确只桥接 tools，Resources／Prompts 尚未提供对应消费者。[D04][D05]

下面是导出到 `/private/tmp/bookmark-research-dsh` 时的 `cordis.patch.yml` 内容：

```yaml
- insert:
    - id: bookmark-research-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: bookmark-research
        transport: stdio
        command: python3
        args:
          - /private/tmp/bookmark-research-dsh/src/cli.py
          - serve
        failOnStartupError: true
```

`command` 与 `args` 分开传递。不要在这个 DSH 片段里假设 `${PLUGIN_ROOT}` 会像 Codex 一样展开；本轮核实的 MCP 客户端并未定义这种插件根占位符约定。绝对路径片段适合本机 checkout；搬迁或重新安装到其他位置后需要重新生成。DSH 的 patch 文件位置也不会改变模块路径解析所依据的 profile 目录。[D03][D05]

发布包现在**自带** `bundle.patch.yml` 并在 `package.json` 声明 `dsh.bundle.patch`，因此 `dsh plugin --profile <name> add bookmark-research@<version>`（以及 DSH 插件管理界面）可以直接从 registry 安装；`dsh` 的 bundle 对账逻辑会把声明了 `dsh.bundle` 且 patch 存在的包自动加入 `dsh.profile.bundles`。层内不写死本机路径：`command`、`args`、`cwd` 与转发的环境变量都由入口模块 `hosts/dsh/plugin.js` 在加载时提供（`bookmarkResearchPaths.python/mcpArgs/env`），模块用与 npm 启动器相同的顺序发现 Python 3.9+／SQLite，所以导出副本、registry 安装和 Windows 都不需要重生成 patch。统一安装器仍导出带校验和的固定副本，用于可验证的托管安装；对不含该文件的旧发布包或旧 Git ref，导出器按模块的旧契约生成等价层，安装不回归。[D02][D03]

DSH 桌面版把 profile 名 `desktop` 保留给 Electron 载体：启动器对该名字拒绝一切 boot／dump（`--dump-config` 亦然），只有载体自身可以管理其插件。因此对 `desktop` 的安装须用桌面版自带 CLI（它自带 pnpm，无需 PATH 中的 pnpm）。安装器与向导会自行定位该 CLI——PATH 中的 `dsh`、macOS 的 `/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh`（含 `~/Applications`）、Windows 的 `%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd` 与 `ProgramFiles` 同一布局、Linux 的 `/opt/DeepSeek Harness/resources/runtime/cli/bin/dsh`——并在 PATH 中的 CLI 缺少 pnpm 时改用桌面版，所以 `--dsh "<App>/Contents/Resources/runtime/cli/bin/dsh"` 现在只在非常规安装位置才需要。安装器的验证改为读取持久层：profile 依赖指向该包、`dsh.bundle.patch` 与入口模块按包目录相对解析且文件存在、层内包含 Skill 与 MCP 行。2026-10-08 在本机（macOS、桌面运行时 0.2.0-rc.2、发布包 0.5.0-beta.5）实测：注册后 Skill 出现在宿主目录，`mcp__bookmark-research__*` 工具正常应答，运行中的 MCP 子进程解析到已安装包目录。[D02][D08]

导出及查看合并配置的形式是：

```sh
python3 scripts/export_bundle.py --format dsh --output /private/tmp/bookmark-research-dsh
dsh --profile web --patch /private/tmp/bookmark-research-dsh/cordis.patch.yml --dump-config
```

实际启动可使用 `dsh web --patch <绝对配置路径>`。该手工路线仍属待客户端验证的接入说明，且不覆盖保留的 `desktop` profile。新建任意名称的 profile 默认只有 base bundle；`web` profile 才会按官方模板包含 Web 表面，不应把“创建一个任意 profile”描述成自动创建了完整 Web 应用。[D02][D08]

`dsh plugin` 在 profile 目录中通过 pnpm 管理依赖，并把声明了 `dsh.bundle` 的包加入 `dsh.profile.bundles`。没有该声明的 npm 包仍能作为普通依赖安装，但不会自动增加插件配置层。后层 patch 会替换命中行的整个 `config`，不做深度合并。[D02][D08]

DSH 的 Skill 可直接复用共享 `SKILL.md`。本轮官方 Skill provider 的默认发现顺序为：

1. 项目 `.dsh/skills/`；
2. 项目 `.agents/skills/`；
3. 显式 `customSkillDirs`；
4. 用户 `$DSH_HOME/skills`，默认 `~/.dsh/skills`；
5. 用户 `$DSH_AGENTS_HOME/skills`，默认 `~/.agents/skills`；
6. 配置过的 bundled skill root。

目录包采用 `<name>/SKILL.md`，不递归寻找任意层级的 `**/SKILL.md`。要加载源码树中的 `skills/`，应由现有 Skill provider 的 `customSkillDirs` 指向其绝对路径，或通过被识别的 skills 根分发。仅把 `skills/` 放到任意 DSH npm 包根目录，不会因为它同时是 Codex／Pi 的 Skill 目录就自动被发现。[D06][D07]

**5．Codex 与 Claude：保留各自原生包装，不混用校验规则**

OpenAI 官方文档要求 `.codex-plugin/plugin.json`。只把这个文件放进该隐藏目录，skills、MCP 配置、hooks 等留在插件根。当前官方文档对 MCP 文件示例采用 direct server map 或 `mcp_servers` wrapper；本地插件工具与客户端版本可能使用不同表示，应该分别验证实际生成的包装，不把一种文档示例自动当成所有客户端的通用形状。[H04]

**Codex 0.153.4 的原生 MCP 路径需要显式设置 `cwd`。** 本次本机启动诊断确认：原生配置中的 `args: ["${PLUGIN_ROOT}/src/cli.py", "serve"]` 被原样传给子进程，未指定 `cwd` 时仍使用会话目录，子进程也没有收到 `PLUGIN_ROOT`／`CLAUDE_PLUGIN_ROOT` 注入。改用下面的 server 配置，使相对脚本路径基于安装后的插件目录解析：

```json
{
  "command": "python3",
  "args": ["src/cli.py", "serve"],
  "cwd": "."
}
```

精确版本源码 [`rust-v0.153.4` 的 `plugin_config.rs`](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/codex-mcp/src/plugin_config.rs) 中，`normalize_plugin_mcp_server_value` 对 Host 来源只把显式相对 `cwd` 改成 `root.join(cwd)`，不展开 `command`／`args` 中的插件根占位符。Host 未设置 `cwd` 时，本函数保持未设置；executor-owned 分支另有默认根目录逻辑，不能把这一默认值套用于所有本机加载。官方文档对 hooks 的变量注入说明也不能直接用于原生 MCP。[H04][H06]

这项修正用于 Codex 原生包装。Claude 有自己独立的变量约定，因此保留其导出的既有路径配置。修复后的插件安装与实际调用结果以本项目的客户端验证记录为准。[H01][H05][H06]

Claude 当前文档的 manifest 路径是 `.claude-plugin/plugin.json`；有 manifest 时 name 必填，manifest 本身可省略。它还支持更多客户端组件。Claude 的根 `.mcp.json` 配置与 `CLAUDE_PLUGIN_ROOT` 等约定属于其原生格式。[H05]

当前 Claude 导出还在 manifest 中声明 `workflows: "./workflows"`。脚本包含 `export const meta`，通过 `/bookmark-research:bookmark-research` 接收结构化 `args`。自带 `/deep-research` 从 2.1.218 起需要显式调用，不能自动保证插件的全量清单覆盖。把 `ultracode` 写进 Skill、普通 `-p` 输入或未标注 human origin 的 SDK 输入不能触发工作流；插件不修改用户的 effort 或启用设置。[W1]

本项目应分别记录：

| 验证层级 | 可以宣称什么 |
| --- | --- |
| 阅读官方文档／源码 | 已核实入口与接口形状 |
| 生成 manifest 和配置 | 已提供对应格式的包／适配文件 |
| 运行 CLI、协议与本地数据测试 | 已验证本项目核心功能与 MCP 行为 |
| 在目标客户端实际加载并调用 | 该版本客户端的实际兼容性已验证 |

只有最后一层经过实际执行后，才应写“Pi／DSH／Claude 已验证可用”。本文对这些载体提供的是有第一方依据的导出包与适配说明；不会因为它们具备扩展机制就把尚未测试的客户端接入写成现成功能。

**6．实际导出与验证方式**

在仓库工作区根目录运行：

```sh
python3 scripts/export_bundle.py --format codex --output /private/tmp/bookmark-research-codex
python3 scripts/export_bundle.py --format claude --output /private/tmp/bookmark-research-claude
python3 scripts/export_bundle.py --format dsh --output /private/tmp/bookmark-research-dsh
```

`--output` 必须是新目录或空目录。已存在的非空目录、文件及 symlink 会被拒绝；导出先在临时目录组装，再发布到输出路径，不向已有内容合并文件。要重新导出，请选择另一个新目录，或自行归档旧产物后使用空目录。

导出范围仅为共享 `src/`、`config/`、`skills/` 及按格式生成的 manifest／README。导出器过滤数据库、常见缓存、隐藏文件、测试与构建产物，拒绝源目录中的可导出 symlink；三种跨客户端包均排除 `agents/openai.yaml` 这一 Codex 显示元数据。现有数据库、网页缓存和运行时 API key 不打包，也不会安装客户端或更改其配置。

本地验证命令：

```sh
python3 -B -m unittest discover -s tests -p test_export_bundle.py -v
```

测试检查五种入口文件的形状，在移除源 fixture 后从独立工作目录运行导出 CLI，并验证 provider 配置、stdio MCP 初始化与工具发现、继承指定的数据目录、缓存过滤及不覆盖已有内容。三种跨客户端导出排除 Codex 显示元数据，Codex 导出保留它。它验证的是导出产物与共享运行时，不能替代 DSH／Claude 客户端的实际加载测试。
