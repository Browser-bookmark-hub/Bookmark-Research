# 载体兼容与最小打包方案

核验日期：2026-09-07；2026-09-08 补充 Codex 0.153.4 的实际启动路径规则。本文通过 Exa MCP 读取官方文档与源码，说明 Bookmark Research 可以怎样接入不同载体。**文档格式核验、包文件生成、CLI／MCP 测试、客户端实际加载，是不同的验证层级。** 本文没有在 Pi 或 DeepSeek Harness 中安装、启用或运行插件；下面的跨载体命令是可复用的配置说明，不代表这些客户端已通过端到端测试。来源及核验边界见 [harness-sources.json](harness-sources.json)。

建议复用一个核心：`skills/bookmark-research/SKILL.md` 描述工作流，`src/cli.py` 提供固定 CLI 与 stdio MCP，SQLite 保存持久索引。客户端包装不承担另一套书签解析、搜索或正文版本逻辑。

| 目标 | 真实入口 | Skill／MCP 如何接入 | 本项目的最小路线 |
| --- | --- | --- | --- |
| OpenAI Codex 插件 | `.codex-plugin/plugin.json` | manifest 指向 skills、MCP 配置等组件 | 原生 Codex 包；具体安装与验证按本项目 README |
| Claude Code 插件 | `.claude-plugin/plugin.json`；当前文档允许省略 manifest 后按约定发现组件 | 根 `skills/`、`.mcp.json` 或 manifest 配置 | 单独保留 Claude manifest／MCP 配置 |
| Agent Plugins 1.0.0 标准包 | **根 `plugin.json`**，必填 `$schema` 与 `name` | 固定发现根 `skills/`、`mcp.json` | 从同一源码独立导出标准包 |
| Pi | `package.json` 的 `pi` 字段，或资源目录约定 | 原生 skills／extensions；MCP 要靠扩展 | `pi.skills`＋Skill 调用 CLI |
| DeepSeek Harness（DSH） | `--patch` 加载 Cordis 配置；可发布 bundle 另有 `package.json` 的 `dsh.bundle.patch` | 原生 Skill provider；官方 `dsh-mcp-client` 桥接 MCP tools | 导出使用绝对路径的本机 `cordis.patch.yml` 适配文件 |

这些入口不是同一文件的不同别名。符合 Agent Skills 的 `SKILL.md` 和 MCP 协议是主要复用边界；某个客户端能加载 Skill，并不表示它已经支持 Agent Plugins 的根 manifest。[H01][H04][H05][P02][D02]

**1．稳定数据位置与共用入口**

本项目的 stdio MCP 启动方式：

```sh
python3 /absolute/path/to/bookmark-research/src/cli.py --db /absolute/path/to/plugin-data/index.sqlite3 serve
```

省略 `--db` 时，CLI 使用 `BOOKMARK_RESEARCH_DATA_DIR/index.sqlite3`；未设置时使用 `${XDG_DATA_HOME}/bookmark-research/index.sqlite3`，其中 `XDG_DATA_HOME` 默认是 `~/.local/share`。索引不放在插件安装缓存或原始书签包内。多个载体若要访问同一库，应明确指向同一个数据库路径；只保留相同插件名称并不会共享数据。

Codex 的 stdio MCP 需要显式允许转发自定义环境变量（[官方说明](https://developers.openai.com/codex/mcp#stdio-servers)）。本插件原生 manifest 的 `env_vars` 列出 `BOOKMARK_RESEARCH_DATA_DIR`、`BOOKMARK_RESEARCH_CONFIG`、`XDG_DATA_HOME`、`XDG_CONFIG_HOME`、`EXA_API_KEY`、`PARALLEL_API_KEY`；只在启动进程中设置变量而未透传时，MCP 可能仍读取默认目录。已使用全新临时目录核验空来源列表和虚构数据导入。

本项目四种导出均保留上述 CLI 行为，**不强制传入 `--db` 或 `${PLUGIN_DATA}`**。需要共库时，在各载体实际启动 MCP／CLI 子进程的环境中设置相同的 `BOOKMARK_RESEARCH_DATA_DIR`，或修改启动参数，显式指定同一 `--db` 路径。客户端可能过滤环境变量，不能仅凭外部终端已设置就断言子进程一定继承。

Agent Plugins 标准的 `PLUGIN_DATA` 是**每个客户端管理的、属于该安装实例的数据目录**，规范要求升级时保留，但没有保证不同客户端的目录相同。如果使用者选择把数据库放入该目录，它可以跨该插件的升级保存，却不自动与 CLI 默认库或另一载体的库共享。[H01]

Skill 中应通过当前载体实际提供的工具或 CLI 调用能力，不把模型固定工具名前缀当成可移植协议。尤其 DSH 会把 MCP 工具映射成 `mcp__<serverName>__<tool>`；其他客户端的呈现方式由它们决定。[D04]

**2．Pi：先用 Skill＋CLI，MCP 桥不是必需前置条件**

本轮 Pi 官网与官方仓库指向 `earendil-works/pi`，当前包名是 `@earendil-works/pi-coding-agent`。历史教程里的 `badlogic/pi-mono`、`@mariozechner/...` 不应无核验地作为当前安装示例。[P01][P02]

Pi 的包声明可只包含共享 Skill：

```json
{
  "name": "bookmark-research",
  "version": "0.1.0",
  "keywords": ["pi-package"],
  "pi": {
    "skills": ["./skills"]
  }
}
```

这会让 Pi 发现 `skills/bookmark-research/SKILL.md`，不意味着注册了名为 `search_bookmarks` 的 Pi 原生工具。Skill 可以引导模型调用已有 Python CLI；此时复用的是同一个查询程序和数据库。[P02][P03]

先导出 Pi 的原生 Skill 包，再按实际导出路径单次加载：

```sh
python3 scripts/export_bundle.py --format pi --output /private/tmp/bookmark-research-pi
pi --skill /private/tmp/bookmark-research-pi/skills/bookmark-research/SKILL.md
```

进入 Pi 后用 `/skill:bookmark-research` 加载工作流。若以后决定持久注册此本地包，可使用：

```sh
pi install /private/tmp/bookmark-research-pi
```

`pi install` 默认修改 `~/.pi/agent/settings.json`；`-l` 使用项目 `.pi/settings.json`。本地路径包不复制文件，只将位置加入设置。本文未执行这些命令。[P02]

Pi 官方 `usage.md` 明确写明核心不内建 MCP；它希望通过扩展或包添加这种能力。不能把 Codex／Claude 的 `.mcp.json` 放进包里，就声称 Pi 会原生连接该服务器。[P05]

将来需要模型直接调用结构化 Pi 工具时，有两个扩展方向：

- 编写薄 Pi extension，通过 `pi.registerTool()` 调用本项目 CLI 或 MCP。官方扩展入口是接收 `ExtensionAPI` 的默认导出工厂函数；当前类型入口是 `@earendil-works/pi-coding-agent`，参数 schema 示例使用 `typebox`。[P04]
- 明确选择并验证一个 MCP adapter 扩展。Pi 官方包目录可以列出第三方 adapter，但收录不等于 Pi 核心实现，更不等于本项目已经测试该 adapter。本版不自动引入某个第三方桥。

只有实际提供相应文件后，才把 `pi.extensions` 指向扩展路径。当前仅声明 `pi.skills` 的包应称为“Pi Skill 包”，不能称为已完成原生 Pi 工具桥。

Pi 支持全局 `~/.pi/agent/skills/`、`~/.agents/skills/`、项目 `.pi/skills/`／`.agents/skills/`、包内 skills、设置路径与重复的 `--skill`。Pi 的递归发现比 Agent Plugins 标准宽松，但共享包仍应使用 `skills/<name>/SKILL.md` 的一层布局，并让目录名与 skill name 一致，兼顾更严格的客户端。[P03]

**3．DeepSeek Harness：配置 bundle 和运行插件是两层**

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

`command` 与 `args` 分开传递。不要在这个 DSH 片段里假设 `${PLUGIN_ROOT}` 会像 Codex／Agent Plugins 一样展开；本轮核实的 MCP 客户端并未定义这种插件根占位符约定。绝对路径片段适合本机 checkout；搬迁或重新安装到其他位置后需要重新生成。DSH 的 patch 文件位置也不会改变模块路径解析所依据的 profile 目录。[D03][D05]

本次 DSH 导出是**本机配置适配文件**，不生成声明 `dsh.bundle` 的 `package.json`，也不安装 DSH 或官方 MCP client。后续如果要发布可搬迁 npm bundle，需要增加按安装位置解析源码路径的适配器，并按官方规则声明 `dsh.bundle.patch`；不能发布硬编码本机路径的配置并称其可移植。[D02][D03]

导出及查看合并配置的形式是：

```sh
python3 scripts/export_bundle.py --format dsh --output /private/tmp/bookmark-research-dsh
dsh --profile web --patch /private/tmp/bookmark-research-dsh/cordis.patch.yml --dump-config
```

实际启动可使用 `dsh web --patch <绝对配置路径>`。这些命令要求 DSH 环境已具备对应 MCP client 依赖，属于待客户端验证的接入说明；本文没有安装或修改 DSH profile。新建任意名称的 profile 默认只有 base bundle；`web` profile 才会按官方模板包含 Web 表面，不应把“创建一个任意 profile”描述成自动创建了完整 Web 应用。[D02][D08]

`dsh plugin` 在 profile 目录中通过 pnpm 管理依赖，并把声明了 `dsh.bundle` 的包加入 `dsh.profile.bundles`。没有该声明的 npm 包仍能作为普通依赖安装，但不会自动增加插件配置层。后层 patch 会替换命中行的整个 `config`，不做深度合并。[D02][D08]

DSH 的 Skill 可直接复用共享 `SKILL.md`。本轮官方 Skill provider 的默认发现顺序为：

1. 项目 `.dsh/skills/`；
2. 项目 `.agents/skills/`；
3. 显式 `customSkillDirs`；
4. 用户 `$DSH_HOME/skills`，默认 `~/.dsh/skills`；
5. 用户 `$DSH_AGENTS_HOME/skills`，默认 `~/.agents/skills`；
6. 配置过的 bundled skill root。

目录包采用 `<name>/SKILL.md`，不递归寻找任意层级的 `**/SKILL.md`。要加载源码树中的 `skills/`，应由现有 Skill provider 的 `customSkillDirs` 指向其绝对路径，或通过被识别的 skills 根分发。仅把 `skills/` 放到任意 DSH npm 包根目录，不会因为它同时是 Codex／Pi 的 Skill 目录就自动被发现。[D06][D07]

**4．Agent Plugins 1.0.0：独立生成标准导出包**

规范的入口是根 `plugin.json`，不是 `.agents/plugin.json`、`.codex-plugin/plugin.json` 或 `.claude-plugin/plugin.json`。根 manifest 的顶层字段是封闭 schema，不能在其中加 Codex 风格的 `skills`、`mcpServers`、`interface` 字段。标准包从固定位置发现 skills 与 MCP。[H01][H02]

实际导出形状：

```text
bookmark-research-agent-plugins/
├── plugin.json
├── mcp.json
├── skills/
│   └── bookmark-research/
│       └── SKILL.md
├── src/
│   ├── cli.py
│   └── … 所需的共享 Python 模块
├── config/
│   └── providers.json
└── README.md
```

根 `plugin.json`：

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "bookmark-research",
  "version": "0.1.0",
  "description": "Query Bookmark Canvas packages through reusable skills and MCP tools."
}
```

根 `mcp.json`：

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "bookmark-research": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "${PLUGIN_ROOT}/src/cli.py",
        "serve"
      ]
    }
  }
}
```

本示例与实际导出器一致，保留 CLI 的数据位置规则。标准提供 `PLUGIN_DATA` 这一能力，并不要求应用必须把数据库放在那里；本项目没有用它覆盖 `BOOKMARK_RESEARCH_DATA_DIR`。

需要遵守的实际边界：

- 标准 `mcp.json` 必须同时有 `$schema` 与 `mcpServers`，每个 stdio server 必须有 `type: "stdio"` 与 `command`。[H03]
- `command` 是一个可执行名称或 `./` 开头的包内可执行路径；不会展开占位符。Python 是外部运行时，所以这里用裸名称 `python3`，脚本位置放入 args。
- `args`、`env`、`cwd` 可以展开 `${PLUGIN_ROOT}`／`${PLUGIN_DATA}`。省略 cwd 时使用插件根；不能假定任意 `${ENV_VAR}` 都会被标准客户端展开。
- 不在 env 中自行定义 `PLUGIN_ROOT`／`PLUGIN_DATA`；两者由客户端提供。客户端应在启动前创建并保留可写 `PLUGIN_DATA`。
- 包内可发现／执行文件的真实路径应留在插件根内。导出要复制需要的文件，不能用指向开发工作区外部的 symlink 冒充自包含包。
- `skills/` 只发现立即子目录中的 `SKILL.md`，标准不要求客户端递归寻找深层 Skill。
- §8 要求客户端专用数据放在客户端拥有的 reverse-domain namespace 中。标准导出包应排除 `.codex-plugin/`、`.claude-plugin/`、Pi／DSH 专用入口和 `skills/*/agents/openai.yaml` 等元数据；后者是为避免把客户端特定文件混入规范包而采取的保守导出策略。不要自行冒用 `com.openai` 或 `com.anthropic` namespace。
- 规范没有给整个文件系统根目录列一个封闭白名单；不能推导出通用 `src/`、`bin/`、`docs/` 被禁止。闭合的是 manifest JSON 字段，客户端专用文件另受 §8 约束。

可共用同一源码树并生成多种包，但“标准包通过 schema 检查”不等于 Codex、Claude、Pi、DSH 的现有版本都能直接安装它。本文没有核实这些客户端已经将根 `plugin.json` 作为它们原生 manifest 的等价入口。[H01]

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

这项修正用于 Codex 原生包装。Agent Plugins 标准格式由另一套解析器处理，Claude 也有自己的变量约定，因此保留这两种导出的既有路径配置。修复后的插件安装与实际调用结果以本项目的客户端验证记录为准。[H01][H05][H06]

Claude 当前文档的 manifest 路径是 `.claude-plugin/plugin.json`；有 manifest 时 name 必填，manifest 本身可省略。它还支持更多客户端组件。Claude 的根 `.mcp.json` 配置与 `CLAUDE_PLUGIN_ROOT` 等约定属于其原生格式；canonical Agent Plugins 采用的文件名是无点前缀的 `mcp.json`，占位符是 `PLUGIN_ROOT`／`PLUGIN_DATA`，不能机械复制后宣称格式相同。[H05]

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
python3 scripts/export_bundle.py --format agent-plugin --output /private/tmp/bookmark-research-standard
python3 scripts/export_bundle.py --format claude --output /private/tmp/bookmark-research-claude
python3 scripts/export_bundle.py --format pi --output /private/tmp/bookmark-research-pi
python3 scripts/export_bundle.py --format dsh --output /private/tmp/bookmark-research-dsh
```

`--output` 必须是新目录或空目录。已存在的非空目录、文件及 symlink 会被拒绝；导出先在临时目录组装，再发布到输出路径，不向已有内容合并文件。要重新导出，请选择另一个新目录，或自行归档旧产物后使用空目录。

导出范围仅为共享 `src/`、`config/`、`skills/` 及按格式生成的 manifest／README。导出器过滤数据库、常见缓存、隐藏文件、测试与构建产物，拒绝源目录中的可导出 symlink；四种跨客户端包均排除 `agents/openai.yaml` 这一 Codex 显示元数据。现有数据库、网页缓存和运行时 API key 不打包，也不会安装客户端或更改其配置。

本地验证命令：

```sh
python3 -B -m unittest discover -s tests -p test_export_bundle.py -v
```

测试检查四种入口文件的形状，在移除源 fixture 后从独立工作目录运行导出 CLI，并验证 provider 配置、stdio MCP 初始化与工具发现、继承指定的数据目录、缓存过滤及不覆盖已有内容。它验证的是导出产物与共享运行时，不能替代 Pi／DSH／Claude 客户端的实际加载测试。
