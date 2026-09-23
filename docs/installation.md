# 安装与更新

[English](installation.en.md) · **中文**

执行 Skill 和方法参考以英文维护，配完整中文阅读版及双语宿主提示说明，见[指令索引](instructions.md)。安装导出会携带这些文件。

Bookmark Research 使用 Python 3.9+ 标准库和 SQLite FTS5。先安装 Python 与要使用的客户端；运行 `python3 src/cli.py doctor` 可以离线检查 Python 和 FTS5。当前 checkout 的四宿主工作流及验证范围见 [宿主兼容说明](harness-compatibility.md)。下文 v0.2.0 Release 链接是历史发布产物，不包含新增宿主脚本；使用这些工作流时从当前源码导出。

## `bookmark-research` 命令（推荐）

`npm install -g bookmark-research` 之后在终端输入 `bookmark-research`，即可打开主菜单：修改配置与 API Key、检查服务、安装到其他宿主、更新、查看状态。也可以直接带子命令：`install [宿主…]`、`update`、`verify`、`setup`、`status`、`config show|set`、`doctor`。npm 包只是入口，内部调用包内的 Python 安装器和运行时，因此仍需 Python 3.9+；Windows 原生、macOS、Linux 都可以用。npm 首次发布前可用 `npx github:Browser-bookmark-hub/Bookmark-Research`。不带参数且不在终端中运行时（agent／CI），它只输出状态 JSON，不弹菜单。

## 一条命令引导安装

已安装 Bash、Git、Python 3.9+（含 SQLite FTS5）和要使用的宿主 CLI 后，可以在任意工作目录执行；其他宿主不需要安装 Codex：

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash
```

终端向导检测可用 CLI，可多选 Codex、Claude Code、Pi、DSH：方向键移动、空格勾选、回车确认，已检测到的宿主默认勾选；随后逐个询问作用域／项目／profile，并显示摘要确认后再安装。`curl | bash` 从 `/dev/tty` 读取回答，不会误读脚本或 Agent 的输入；终端不支持或设置 `BOOKMARK_RESEARCH_PLAIN=1` 时改用普通编号提示。未找到任何受支持的 CLI 时，引导脚本在下载前停止。`--interactive` 要求终端，`--non-interactive` 不询问；没有终端且未指定宿主时保留默认 Codex 的旧行为，Agent 应显式传入 `--host`。

首次安装跟随 `main`，通过所选宿主的原生命令登记与验证。Codex 保留自己的 Git 源码／缓存；其他宿主的完整导出和安装记录持久保存在 `${XDG_DATA_HOME:-~/.local/share}/bookmark-research/installations/`，可用 `--install-dir` 改位置。随后清理临时下载目录，安装后新建宿主会话。

在 checkout 中也可直接选择目标：

```sh
bash install.sh install --host codex
bash install.sh install --host claude --scope user
bash install.sh install --host pi --scope project --project /absolute/path/to/project
bash install.sh install --host dsh --profile web
bash install.sh install --host claude --host dsh --profile web   # 等同 --host claude,dsh
```

重复 `--host` 或用逗号分隔可一次安装多个宿主。此时 `--scope`／`--project` 作用于 Claude／Pi（选中 Pi 时拒绝 `local`），`--profile` 作用于 DSH；不匹配任何所选宿主的选项会被拒绝。各宿主依次安装，单个失败会记录在该宿主结果中，其余继续。偏好与密钥是用户级的，因此引导配置只在最后运行一次。单宿主时 JSON 结果格式不变；多宿主输出 `{"results": [...], "setup": {...}}`，任一宿主或配置失败时退出码为 1。

Claude 支持 `user`／`project`／`local`，Pi 支持 `user`／`project`。project／local 需 `--project PATH`；DSH 需实际 `--profile NAME`。安装向导会询问未填写的目标。更新／验证时沿用同一 scope、project、profile 及自定义 `--install-dir`；`--codex`／`--claude`／`--pi`／`--dsh` 可指定 CLI 路径。

安装帮助和首次使用引导默认按 `LC_ALL` → `LC_MESSAGES` → `LANG` 判断语言：中文 locale 使用中文，其余或未设置时使用英文。显式选择中文可运行：

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- install --lang zh
python3 scripts/install.py install --lang zh
```

`--lang en` 选择英文，`--lang auto` 恢复自动判断。Shell 用 `BOOKMARK_RESEARCH_INSTALL_LANG` 向 Python 安装器传递选择；Python 的显式 `--lang` 优先。该选项只影响安装引导，不保存研究语言设置；Git、Codex 和运行时的技术诊断保留原文。固定到旧 tag 时使用该版本的安装器，旧版本可能仍显示当时的引导语言。

更新、检查和预览使用同一入口：

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- update --host codex
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- verify --host codex
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- --host codex --dry-run
```

`--dry-run` 仍会下载安装器、读取登记和准备临时导出，但不安装、不保存偏好或修改宿主登记。`--help` 只显示帮助；curl 自身仍需下载入口。`--timeout 60` 限制每条原生命令，范围 1–300 秒，不限制人类输入；服务检查另有超时设置。使用本地 `scripts/install.py verify --host HOST` 可省去 bootstrap 下载。

需要固定版本时，在**首次登记来源**时选择 tag 或 commit：

```sh
curl -fsSL https://raw.githubusercontent.com/Browser-bookmark-hub/Bookmark-Research/main/install.sh | bash -s -- install --ref v0.2.0
```

`--ref` 同时选择 Git 中的安装器和待安装插件，所选版本须包含 `scripts/install.py`（从 v0.2.0 开始）。再次安装时省略 `--ref`；已登记的分支、tag 或 commit 会保留。`update` 也保持该 ref，固定 tag 不会自动升级到其他版本。默认跟随 `main` 适合接收开发更新，固定 tag/commit 适合复现。

Codex 分支管理 `bookmark-research@bookmark-research`。已通过 `personal` 等来源安装时沿用原更新流程。其他宿主也会检查来源冲突并保留原有设置。Claude 用内容派生的原生版本刷新缓存，同一发布版本下的源码变化也能生效；Pi 使用持久本地包；DSH 向指定 profile 安装可搬移 bundle。更新失败保留原包并记录待验证状态，之后可重试安装／更新。

**Git tag、GitHub Release 和安装脚本是三个独立部分。** Git tag 标记源码版本；Release 提供说明、ZIP 和校验文件；`install.sh` 负责取得源码并安装。上述命令直接使用 Git，不访问 Release API 或 ZIP 资产，只有仓库也能安装和更新。

## 向导与就绪检查

安装成功后可依次设置研究深度、答复语言、主要／备用搜索服务、正文读取服务、归档目录、检查频率和可选专业 API。回车保留显示的偏好。API Key 掩码输入并立即检查，失败可重新输入；密钥单独保存为配置旁权限 `0600` 的 `credentials.json`，是本地明文文件；可用 `BOOKMARK_RESEARCH_CREDENTIALS` 指定位置。环境变量优先于保存的密钥，密钥不进入偏好 JSON、安装包、安装记录或就绪检查输出。ChatGPT／Codex 登录与 OpenAI API Key 分开。

以后随时运行 `python3 <安装路径>/src/cli.py setup` 重开向导，完整命令（JSON 结果中的 `getting_started.setup_command`）会在安装结束时打印；在源码中可运行：

```sh
python3 src/cli.py setup --host claude_code --lang zh
python3 src/cli.py setup --non-interactive --input /absolute/path/to/preferences.json --skip-checks
python3 src/cli.py readiness --host codex --refresh
python3 src/cli.py readiness --provider exa --test-retrieval
```

Agent 可使用 `install --host pi --non-interactive --preferences FILE --skip-checks`。偏好文件是部分配置对象，例如：

```json
{"research":{"depth":"agentic","response_language":"zh"},"readiness":{"mode":"cached","ttl_seconds":900},"professional_research":{"enabled":false}}
```

默认检查所选检索服务的目录与已启用的专业服务，分别报告密钥配置、目录可达、实际检索和授权范围。`--skip-checks` 阻止服务检查联网，但下载／宿主安装仍可能需要网络。`--test-retrieval` 选择执行样例搜索及 example.com 阅读，可能使用服务额度。OpenAI 检查仅查询模型元数据；Parallel 检查认证后的 Task MCP 目录；二者不证明付费研究任务权限或额度，检查不会创建专业任务。

每个联网研究新问题前，Skill 调用 `research_readiness`，传入实际宿主和已观察到的工具。`cached` 在首次、密钥／配置变化或 15 分钟过期后刷新；`always` 每个新问题检查；`manual` 等待手动 `--refresh`。同一调查复用检查，本地书签查询不联网；直接使用 CLI 时先执行 `readiness`，再调用搜索／读取命令。

搜索／读取适配器已包含。可选 Exa Agent、Parallel Task、Tavily Research MCP 由宿主管理：向导展示对应的添加／授权步骤，检查结果也返回结构化指引。先检查已有登记并复用名称。Codex 用 `codex mcp list`，支持 OAuth 时用 `codex mcp login`；Claude 用 `claude mcp list` 和 `/mcp`。Pi 的原生研究 MCP 需另选 MCP 扩展；DSH 使用官方 MCP client 的 profile 配置和认证 header。工具可见不等于登录成功，插件保存的 Key 也不会自动授权另行登记的宿主 MCP。完整说明见[配置与排障](../skills/bookmark-research/references/zh/settings-and-archive.md)。

可选服务故障显示在 `setup.needs_attention`，不阻塞本地查询或其他服务。原生安装或配置失败返回非零，JSON 分别报告安装与 setup 状态。未主动请求新版向导时，缺少 setup 的历史版本仍可正常安装。

## 取得代码或 ZIP

以下下载示例固定到已发布的 [v0.2.0 Release](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases/tag/v0.2.0)：[插件 ZIP](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases/download/v0.2.0/bookmark-research-0.2.0.zip) 和用于离线验证的 [测试包](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases/download/v0.2.0/bookmark-research-test-pack-0.2.0.zip)。其他已发布版本以 [Releases](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases) 为准；本地 0.4.0 构建及验证见 [验证记录](validation-0.4.0.md)。两个包均包含 `MANIFEST.sha256`，Release 另提供 ZIP 的 `SHA256SUMS`。解压时保留 `.codex-plugin/` 和 `.agents/` 等隐藏目录，并把目录放在一个稳定位置。

仓库地址：<https://github.com/Browser-bookmark-hub/Bookmark-Research>。复现该历史快照使用 `v0.2.0` 标签；`main` 跟随开发更新。ZIP 是可选的分发形式，也可以直接克隆源码：

```sh
git clone --branch v0.2.0 https://github.com/Browser-bookmark-hub/Bookmark-Research.git
cd Bookmark-Research
python3 src/cli.py doctor
```

请在包含 `scripts/install.py` 的 0.2.0 或后续版本 checkout、ZIP 中使用下方安装入口。旧提交仍可使用原生 Codex 命令或各自版本的导出器。

## Codex CLI 安装

在当前源码或解压目录运行：

```sh
python3 scripts/install.py install
python3 scripts/install.py verify
```

安装器会调用 Codex 原生 `plugin marketplace add`、`plugin add` 和 JSON 查询接口；Codex 管理其配置和安装缓存。当前 `main` 的安装器在成功后显示当前配置、首次提问模板和配置查询命令；已有配置会照实显示，读取失败时明确提示修正。stdout 保持 JSON，面向用户的引导写到 stderr，管道执行时也会显示。v0.2.0 固定快照保留当时的安装输出。

安装完成后新建 Codex thread，以载入新 Skill 和 MCP 工具。Python 必须能以 `python3` 被 Codex 的 MCP 子进程找到。需要支持这些子命令和 `--json` 的 Codex CLI；本仓库验证环境为 0.153.4。

安装入口从自身文件位置查找源码，因此也可以在其他工作目录运行。含空格或中文的路径使用引号：

```sh
python3 "/absolute/path/Bookmark Research/scripts/install.py" install
```

| 命令 | 行为 |
| --- | --- |
| `install` | 安装当前脚本所属目录；可重复执行 |
| `install --source /absolute/path/to/source` | 安装另一个有效的本地 marketplace 根目录 |
| `install --source owner/repo --ref TAG_OR_COMMIT` | 让 Codex 安装指定 Git 来源；占位符需替换为实际已存在的版本 |
| `install --dry-run` | 读取现有注册状态，打印计划，不运行安装命令 |
| `update` | 更新当前已安装来源；Git 源先执行 `marketplace upgrade`，本地源重新安装其当前文件 |
| `update --dry-run` | 查看现有来源的更新计划 |
| `verify` | 检查已启用注册、安装缓存版本、FTS5、MCP 初始化和工具发现 |

每个动作可指定 `--codex /absolute/path/to/codex` 和 `--timeout 60`。输出为 JSON；验证或前置步骤失败时返回非零退出码。`verify --installed-path PATH` 可明确指定 `codex plugin add --json` 返回的 `installedPath`，用于 Codex 缓存布局发生变化的情况。

安装器不会把已有同名 marketplace 自动切换到另一个 Git 仓库或本地目录。遇到来源冲突，先用 `codex plugin marketplace list --json` 和 `codex plugin list --json` 核对要保留的来源，再在 Codex 中处理来源选择。这样不会因更新本插件而连带移除 marketplace 中的其他插件。

`--ref` 用于首次注册 Git marketplace。已有 Git 来源再次安装时省略 `--ref`，保持其原注册版本；如要换 tag 或分支，先在 Codex 中处理来源变更。当前原生 JSON 不返回已注册 ref，安装器不会把“同一个仓库”推断成“同一个固定版本”。

`verify` 启动安装缓存中的 Python 运行时，并按插件的原生配置执行 stdio MCP 初始化与 `tools/list`。它不调用网页服务、不导入书签、不创建索引；服务账号是否有效、模型能否调用工具，需要在实际会话中另行验证。

## 使用 Codex 原生命令

如果不使用本仓库的安装入口，在本地 marketplace 根目录运行：

```sh
codex plugin marketplace add .
codex plugin add bookmark-research@bookmark-research
codex plugin list --json
```

固定安装 v0.2.0 时，使用 `codex plugin marketplace add Browser-bookmark-hub/Bookmark-Research --ref v0.2.0`，再执行 `codex plugin add bookmark-research@bookmark-research`。`--ref main` 跟随开发分支，其他固定版本使用实际已存在的标签或 commit。已有同名来源先按上文核对其注册状态。

原生命令依据 [OpenAI plugin packaging documentation](https://developers.openai.com/plugins/build/plugins) 和 [Codex CLI reference](https://developers.openai.com/codex/cli/reference#codex-plugin)。默认个人 marketplace `~/.agents/plugins/marketplace.json` 是 Codex 的隐式发现机制；上面的 `marketplace add` 用于本仓库自己的显式 marketplace，二者不要混淆。

## 干净导出与其他客户端

导出器只生成目录，不修改客户端设置。目标必须是不存在或为空的目录；更新时导出到新目录，再调整客户端使用的路径。所有适配器共享同一 Skill 和运行时，版本从 `.codex-plugin/plugin.json` 读取。

### Codex 干净目录

需要把运行时与开发工作树分开时：

```sh
python3 scripts/export_bundle.py --format codex --output /absolute/path/to/bookmark-research
python3 scripts/install.py install --source /absolute/path/to/bookmark-research
```

这份导出包含原生插件和本地 marketplace。选择稳定路径后再安装；不要直接把 Codex 已注册目录移动到别处。

多组研究沿用当前会话的原生子代理，规则位于 `hosts/codex/delegate.md`。`python3 hosts/codex/prepare.py --research-id RID` 经共享 MCP 读取全部清单分页并输出分组，不启动子代理。原生委派和等待工具必须在会话中实际可见；插件不安装全局 agent 定义或自建 JavaScript 工作流引擎。

### Claude Code

持久安装可直接运行 `python3 scripts/install.py install --host claude --scope user`。手动导出或会话级开发仍可使用：

```sh
python3 scripts/export_bundle.py --format claude --output exports/claude/bookmark-research
claude plugin validate --strict ./exports/claude/bookmark-research
claude --plugin-dir ./exports/claude/bookmark-research
```

包含 `.claude-plugin/plugin.json`、`.mcp.json`、共享 Skill 和 `workflows/bookmark-research.js`；`--plugin-dir` 为当前会话加载插件。先创建研究取得 `research_id`，再明确调用：

```text
运行 /bookmark-research:bookmark-research，传入
{"research_id":"RID","run_key":"review-1","group_size":12,"max_gap_rounds":1}。
```

`RID` 替换为真实任务 ID，`run_key` 在新运行保持唯一，同一次恢复保持不变。需要 Claude Code 2.1.154+ 及已启用的 Dynamic Workflows；Pro 还需在 `/config` 开启。通过 `/workflows` 管理运行，恢复限于同一会话，退出后需重开。自带 `/deep-research` 为独立的显式入口，不自动保证本插件书签清单覆盖。参见 [Claude workflows](https://code.claude.com/docs/en/workflows)。

### Pi

持久安装可直接运行 `python3 scripts/install.py install --host pi`；基础 Skill + CLI 不需要子代理扩展。手动导出可使用：

```sh
python3 scripts/export_bundle.py --format pi --output exports/pi/bookmark-research
pi --skill ./exports/pi/bookmark-research/skills/bookmark-research/SKILL.md
```

用 `/skill:bookmark-research` 加载 Skill。需要持久注册 Skill 时执行 `pi install /absolute/path/to/exports/pi/bookmark-research`；这条命令会修改 Pi settings。Pi 适配器声明 `pi.skills`，另附保存工作流及 Python stdio 工具桥；不提供 Pi 原生 MCP extension。

保存工作流需要 Node 22.19+、Pi 0.83+、`pi-subagents` 0.43.0+，以及同一父会话加载的 `pi-subagents-workflows`。选定稳定导出位置后，只向指定项目登记：

```sh
python3 exports/pi/bookmark-research/hosts/pi/register-workflow.py --project /absolute/path/to/project
```

登记器创建 `.pi/subagent-workflows/bookmark-research/workflow.json` 和 `script.js`，不安装扩展或更改 settings。已有不同定义会保留并报冲突；重复相同登记幂等。项目须受信任，从该项目启动 Pi 后调用：

```js
pi_subagent_workflow({action:"run",name:"bookmark-research",args:{research_id:"RID",run_key:"review-1"}});
```

运行以 detached 模式启动，主代理须使用扩展的等待、状态和 artifacts 功能等到终态。`delegate` 需要 Bash 访问已绑定的 Python bridge，或已有研究 MCP 工具。搬迁包后需重新登记；注册表不提供跨会话 journal replay。参见 [Pi workflow registry](https://pi.dev/packages/pi-subagents-workflows)。

### DSH / DeepSeek Harness

所选 DSH profile 需提供 Skill registry 和官方 `@deepseek-ai/dsh-mcp-client`。`dsh plugin` 由 pnpm 执行，请先安装（`npm install -g pnpm` 或 `corepack enable pnpm`）；缺少时安装器会在创建 profile 前停止，向导中 DSH 显示为不可选。统一安装器生成可搬移的 `dsh.bundle`，调用原生 `dsh plugin --profile web add PATH`，注册 Skill 并从安装后位置解析 Python／MCP 路径：

```sh
python3 scripts/install.py install --host dsh --profile web
python3 scripts/install.py verify --host dsh --profile web
```

手动分发时使用 `export_bundle.py --format dsh`，再用上述原生命令安装稳定导出目录。保留的旧 `cordis.patch.yml` 仍含绝对路径，需单独配置 Skill 发现；移动后应重新生成。多组研究另需 workflow service、worker-thread engine 和 `workflow` tool。参见 [官方 MCP client 文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)。

生成可直接传给宿主 `workflow` 工具的完整 JSON：

```sh
python3 /absolute/path/to/bookmark-research-dsh/hosts/dsh/workflow-call.py --research-id RID --run-key review-1
```

结果由独立的 `meta`、无 export 的 `script`、对象 `args` 组成。DSH 等待完整流程后返回 `{runId,agentsStarted,result}`，取消是错误，渲染可能截断。报告子代理会通过共享研究工具保存完整分析附件并返回实际路径；不能假设宿主自动提供全文句柄。导出和生成参数均不启动宿主任务。

本机已通过 Claude Code 2.1.247 原生 strict manifest 校验、宿主隔离检查与真实 MCP 分页/附件检查。Pi、DSH 未安装，本机 Node 22.17.0 低于 Pi workflow 要求；四宿主付费研究端到端均未运行。完整边界见 [验证记录](host-validation.json)。

### Agent Plugins 1.0.0

```sh
python3 scripts/export_bundle.py --format agent-plugin --output exports/agent-plugin/bookmark-research
```

此格式使用根目录 `plugin.json` 和 `mcp.json`，供实现 [Agent Plugins 1.0.0](https://agent-plugins.org/specification) 的客户端使用。它与 Codex 原生格式分别导出。

## 首次使用与数据位置

全新用户可以先用默认设置，**本地书签查询无需填写配置或 API Key**。安装完成后的引导会显示实际生效的设置和保存位置；第一次主动修改设置时才创建配置文件。安装器读取这些设置时不会导入书签或创建索引。

1. 安装成功后，在所选宿主新建会话，让客户端加载插件。
2. 准备自己的 Bookmark Canvas 目录、ZIP 或单卡 JSON。插件不附带书签或预建索引；把下面的占位路径换成实际路径后发送。
3. 先查看本地栏目与书签，再提出需要联网核验的研究问题。只做网页研究时可以直接提出主题，无需先导入书签。插件使用当前客户端中的模型，无需再填写一套 LLM 模型名称或地址。

```text
用 Bookmark Research 读取我的书签画布包 "/absolute/path/to/my-canvas-package"，
先离线列出栏目、文件夹和书签数量。
```

手动导出会保存为快照，下载文件移走后仍能查询。同一画布的新导出直接说“沿用刚才的来源”；插件会复用来源 ID 和未变的索引。单卡按局部数据处理，其他卡片不会因未提供而删除。

持续同步目录可直接说：“把这个目录作为持续来源，它是完整的画布同步目录。”宿主会使用 `mode:live, completeness:complete` 登记，MCP 运行期间自动检查变化；关闭宿主后停止，下次连接／查询补查。默认不需要填写轮询参数。不同形态和恢复方法见 [来源生命周期](../skills/bookmark-research/references/source-lifecycle.md)。

联网研究可以直接说“快速查证这个书签”“比较这组工具”或“全量研究这个包，交付报告和 Wiki”。默认由宿主根据请求选择快速查证、主动搜索或深度研究，不需要固定提示词；范围以本次请求为准，研究整包时保留全部原始 URL。三种方式、配置与语言示例见[使用指南](user-guide.md)，内部关系见[结构与触发流程](bookmark-research-architecture.md)。

宿主自身执行多轮研究可以使用现有搜索与正文工具；OpenAI／Parallel 专业研究 API 是另需启用并配置凭据的路线。更新插件后，旧会话可能仍只暴露部分旧版工具：所需功能可先通过同包 CLI 执行，新建会话后加载新版 Skill 和完整 MCP 工具。仅设置研究深度或取得路由建议不会自动启动任务。

以下是没有自定义设置时的默认值，可以在对话中按需修改：

| 项目 | 默认值 | 修改示例 |
| --- | --- | --- |
| 搜索服务商 | Exa + Parallel，每目标 5 条结果 | “以后只用 Exa 搜索，每目标返回 10 条结果” |
| 正文读取 | Exa，长度参数 12000 字符 | “以后默认用 Parallel 读取网页” |
| 请求超时 | 30 秒 | “把网页请求超时改为 45 秒” |
| 普通网页读取归档 | 开启 | “普通网页读取以后不要自动归档” |
| 配置和保存位置 | 使用下方默认目录 | “显示 Bookmark Research 的配置和保存位置” |

长度参数是否受支持及实际返回量取决于 provider，不能据此保证完整页面。深度研究会始终保存其任务证据，普通网页归档开关只影响 `fetch_web`。

网页研究的匿名额度和认证要求由服务方决定。认证失败时重新运行 `setup` 隐藏输入密钥，或在启动客户端的环境中设置对应 API Key，再刷新检查。导出不包含凭据；安装向导仅按用户选择保存密钥。

终端用户可执行安装结束时打印的绝对路径命令查看配置或重开向导；它指向宿主保留的安装路径，临时下载目录清理后仍可用。在源码中也可运行 `python3 src/cli.py config show` 或 `setup`。完整参数见 [CLI 说明](../skills/bookmark-research/references/cli.md)。

索引、页面归档和研究任务保存在 `BOOKMARK_RESEARCH_DATA_DIR`，默认 `~/.local/share/bookmark-research/`，并遵循 `XDG_DATA_HOME`；来源原始快照在数据库旁的 `index.sqlite3.sources/`。用户设置通过 `BOOKMARK_RESEARCH_CONFIG` 指定，默认 `~/.config/bookmark-research/settings.json`，并遵循 `XDG_CONFIG_HOME`。保持这些目录位于插件和安装缓存之外，多个客户端可通过相同配置共享它们。详见 [设置与归档](../skills/bookmark-research/references/settings-and-archive.md)。

## 更新

```sh
python3 scripts/install.py update --host claude --scope user --dry-run
python3 scripts/install.py update --host claude --scope user
python3 scripts/install.py verify --host claude --scope user
```

Git marketplace 的 `update` 保持已注册的仓库与 ref，刷新其快照；固定到不可变 tag/commit 时不会自动跳到另一个版本。本地 marketplace 的 `update` 使用该目录当前内容，不替你执行 `git pull`。先取得目标源码版本，再更新插件。源码目录改变不等于已经更新了正在运行的会话；完成后新建 Codex thread。

本机开发如使用 `$plugin-creator`，按该 Skill 的 cachebuster 与重装流程处理已注册的个人插件；无需为了刷新缓存改变正式发布版本。共享 Skill 和运行时应一起更新，用户数据和配置留在原位置。

## 本地构建 ZIP

维护者从已验证的工作树构建，输出路径必须不存在：

```sh
python3 -m unittest discover -s tests
python3 scripts/build_zip.py --output dist/bookmark-research-0.4.0.zip
```

ZIP 包含原生插件、marketplace、共享运行时、Skill、四宿主源文件及组装器、安装入口、导出器、文档和许可；不包含测试、数据库、页面归档、用户配置或书签数据包。加 `--include-tests` 可另建测试包，包含合成 fixture、宿主 JS 检查、`verify_fixture.py` 和 `verify_quality.py`，可解压后再次导出宿主包。

构建结果打印 ZIP 的 SHA-256；相同内容以固定文件顺序、时间和权限打包，在相同 Python/zlib 环境中可重现相同字节。解压后的 `MANIFEST.sha256` 列出包内文件校验和，可在解压目录运行 `shasum -a 256 -c MANIFEST.sha256`。校验和用于发现损坏，来源真实性仍取决于你下载的仓库或发行渠道。

构建只在本地生成文件。发布 GitHub Release、创建 tag 或推送 npm/PyPI 都不是构建器的行为。安装设计的参考依据和验证范围见 [0.2.0 安装设计](install-design-0.2.0.md)。
