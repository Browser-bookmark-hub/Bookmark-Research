# 多宿主安装改进方案

原始核查日期：2026-09-14，基线 `0f6696e`。2026-09-16 更新：下列统一接口、四宿主安装／更新／验证、终端向导和就绪检查已在当前工作树实现。使用方法以[安装指南](installation.md)为准；本文保留原始设计依据和当时的缺口，不代表这些改动已经发布到远程仓库。

本次补齐了偏好 JSON 的安装前校验、旧版安装兼容、服务状态与授权范围的区分、可选 MCP 的宿主接入指引，以及 DSH 子进程的配置／凭据变量转发。原生 Codex／Claude 安装使用隔离配置验证；Pi／DSH 另有隔离安装器与导出测试。真实模型研究和用户 OAuth 授权不属于这些安装测试的成功结论。

建议采用 **统一入口选择宿主，完整导出对应包，再调用宿主原生命令**。继续复用现有 Skill、Python runtime 和导出器；各宿主分别管理自己的安装登记、缓存和作用域。

优先补齐 Claude Code 和 Pi 的持久安装，再把 DSH 当前的本机 patch 升级为可安装 bundle。安装、更新和验证应一起交付。

## 开源项目怎么做

| 项目 | 本次读到的实际做法 | 本项目可采用的部分 |
| --- | --- | --- |
| [Qwen-MM-Plugins 安装器][qwen-script] | 先选择宿主，再检查对应客户端；Claude 分支调用 `plugin marketplace add/update`、`plugin install/update`，Codex 分支调用自己的原生命令。[安装说明][qwen-doc]仍把 Pi、DSH 等列为手动接入。 | 集中选择入口，按宿主分派检查和命令；明确列出自动安装覆盖范围。 |
| [Superpowers README][superpowers-readme] | 明确说明多宿主需分别安装；Claude 走 marketplace，Pi 使用 `pi install git:github.com/obra/superpowers`。其 [package.json][superpowers-package] 显式声明 `pi.skills` 和 Pi extension。 | 同一源码提供多个原生包入口；宿主负责登记和更新，插件保留共享资源。 |

这两个案例支持“共享源码、分别接入”，并不能证明任何一个现成安装器已覆盖本项目全部四个宿主。Qwen 的安装逻辑只作为分流参考；本项目已有的来源冲突保护仍需保留。

## 官方机制与项目缺口

| 宿主 | 官方安装机制 | 项目当前状态 | 建议补齐 |
| --- | --- | --- | --- |
| Codex | 已有原生 marketplace 安装流程 | `install.sh` 和 `scripts/install.py` 已实现安装、更新、验证 | 放入 Codex 分支；其他分支不检查或调用 Codex。 |
| Claude Code | [marketplace add → plugin install][claude-install]，可指定 user/project/local scope | 导出已有 `.claude-plugin/plugin.json`、`.mcp.json` 和 workflow；文档主路径是会话级 `--plugin-dir` | 为完整导出包生成 marketplace，增加原生持久安装与更新。 |
| Pi | [pi install][pi-packages] 支持 npm、Git 和本地路径；支持显式 `pi` manifest，也支持约定目录 | 导出已有 `package.json` 的 `pi.skills`；文档已有本地 `pi install`，但未接入统一安装器 | 自动准备稳定的完整包并调用 `pi install`；后续可增加直接 Git 分发。 |
| DSH | [dsh plugin --profile … add …][dsh-publish] 向 profile 安装声明 `dsh.bundle` 的包 | 当前只导出含本机绝对路径的 `cordis.patch.yml`；没有 bundle manifest | 增加 bundle manifest、可随安装位置解析路径的入口、Skill 注册和 MCP 接入，然后接原生安装。 |

### Claude Code

[官方 marketplace 文档][claude-marketplace]规定根目录使用 `.claude-plugin/marketplace.json`，插件 `source` 可指向该 marketplace 内的完整插件目录。宿主会将插件复制到自己的缓存，插件依赖的 Python、Skill 和 workflow 文件必须全部位于插件目录内。

建议先在导出器中增加本地 marketplace 包装，再让安装器调用以下原生命令。下面的路径须由安装器生成为持久目录：

```sh
claude plugin marketplace add /absolute/path/to/bookmark-research-marketplace
claude plugin install bookmark-research@bookmark-research --scope user
```

更新目录内容后，使用对应的 marketplace 和 plugin 更新命令：

```sh
claude plugin marketplace update bookmark-research
claude plugin update bookmark-research@bookmark-research --scope user
```

关键约束：

- marketplace 登记的来源必须稳定；bootstrap 的临时下载目录清理后，后续更新仍需可用。
- 同名 marketplace 指向不同来源时先报告冲突，不自动替换来源或移除其他插件。
- 官方文档说明，显式设置插件 `version` 后，用户只在版本字符串变化时收到版本更新。当前导出器复制固定的发布版本，因此正式发布必须同步升版；开发调试继续使用 `--plugin-dir`。若要支持同一发布版本下追踪每个 Git commit，需要另行实现并验证开发版本策略。
- 安装记录应保留 scope；更新不能默认改为另一个作用域。

### Pi

[官方包文档][pi-packages]明确：本地路径登记到 settings，**不会复制源码**。所以不能执行 `pi install <临时导出目录>` 后清理该目录。

首版可自动化现有导出路径：

```sh
pi install /absolute/path/to/stable-bookmark-research-pi
```

默认写入用户 settings；项目安装使用 `-l`，并从用户指定的项目目录执行。项目和用户安装范围应显式对应，避免将 bootstrap 工作目录当作用户项目。

更新要区分来源：

- 本地导出：安装器负责获取原登记来源、重新生成并更新稳定包目录；单独调用 Pi 更新命令不能替代这一步。
- Git/npm 包：用指定包的 `pi update <source>`，保持该包的 ref/version 语义。
- 本次读取的官方文档中，裸 `pi update` 更新 Pi 自身；`pi update --extensions` 更新所有包。两者均不适合作为只更新 Bookmark Research 的实现。

原生 Skill + CLI 安装可以独立完成。`pi-subagents`、`pi-subagents-workflows` 和项目工作流登记继续作为可选功能检查，基础安装不应因缺少这些扩展而失败。

### DSH

[官方发布教程][dsh-publish]区分两种文件：bundle 的 `package.json` 声明 `dsh.bundle.patch`，profile 的 `package.json` 由 DSH 维护其依赖和 bundle 顺序。没有 `dsh.bundle` 的包只能作为普通依赖安装，不会自动启用配置层。

因此，当前导出包需要补齐：

1. `package.json` 中的 `dsh.bundle.patch` 声明。
2. 从安装后的模块位置解析 Python runtime 和 Skill 资源路径的入口，替代导出机器上的固定路径。
3. 使用官方 MCP client 的接入，以及按 [Skill registry 契约][dsh-skills]提供共享 Skill；只连上 MCP 不代表已加载 Skill。
4. 完整的 runtime、Skill 和工作流资源，支持移动后重新安装。

补齐后才可使用以下持久安装路径：

```sh
dsh plugin --profile web add /absolute/path/to/bookmark-research-dsh-bundle
dsh --profile web --dump-config
```

`web` 是示例，安装器应要求选择实际 profile。[CLI 文档][dsh-cli]说明 `dsh plugin` 转发 pnpm 命令并维护 bundle 列表；任意新 profile 并不自动具有完整的 Web 或 workflow 配置。更新须针对该 profile 中的本插件，更新后重启相应 profile。

Python 标准库 runtime 和简单 JavaScript 入口可以随包交付，不必为此引入 TypeScript 构建流程或先发布 npm 包。本次读取的 DSH CLI 文档还说明其安装包已携带官方 MCP client；应按实际宿主版本检查可用性，避免无条件重复安装。

## 方案中的统一接口（现已实现）

当前安装器支持以下接口；在终端运行 install 还可交互选择宿主、偏好和服务：

```sh
bash install.sh install --host codex
bash install.sh install --host claude --scope user
bash install.sh install --host pi --scope user
bash install.sh install --host dsh --profile web
bash install.sh update --host claude --scope user
bash install.sh verify --host pi
```

实现规则：

1. 先解析宿主再做宿主前置检查；公共下载检查与客户端检查分开。`--help` 保持离线可用。
2. 首版保留旧命令的 Codex 默认行为和 `--codex PATH`，新文档显式写 `--host`。缺少 Codex 时给出其他宿主的用法和安装文档链接。不要自动安装到机器上的所有宿主。
3. 继续用 `scripts/export_bundle.py` 生成完整包。导出器目前拒绝非空目标，更新应先在新目录生成并验证，再更新安装器拥有的稳定来源；失败保留旧版本。
4. 宿主原生命令管理宿主登记；安装器只管理自己需要持久保留的来源和生成物。记录 host、source/ref、scope/profile 和路径，以便更新沿用原安装选择。
5. `--dry-run` 显示实际路径、目标宿主、scope/profile 和原生命令，不写宿主登记。不要把仅导出完成报告为安装完成。
6. Git tag/commit 的固定语义、发布版本与本地源码更新规则分别处理；不把所有宿主的更新映射到同一个通用命令。

## 改动顺序与验收

| 顺序 | 改动 | 验收条件 |
| --- | --- | --- |
| 1 | `install.sh` 增加宿主分派与定向错误提示；Python 安装层保留现有 Codex 流程 | PATH 无 Codex 时，Claude/Pi/DSH 目标不查找或调用 Codex；旧命令行为保持兼容。 |
| 2 | Claude 导出增加 marketplace；接安装、更新、验证；自动化 Pi 完整包的本地安装 | 重复安装不重复登记；作用域正确；临时目录清理后仍能启动；升级后实际加载新内容。 |
| 3 | DSH 导出升级为原生 bundle，再接入相同入口 | 移动包后可重新安装；`--dump-config`、MCP 工具发现和 Skill 发现均通过。 |
| 4 | 更新中英文 README、安装指南、导出 README 和相关行为测试 | 清楚区分自动安装、会话加载、导出与可选工作流；失败不报告成功。 |

每个宿主还需覆盖来源冲突、含空格或中文的路径、下载失败、固定 ref、原生安装失败和已有用户配置保留。涉及 scope/project/profile 的选择，须验证它针对用户目标而非临时 checkout。

## 本次已完成的验证

- 检查了当前安装器、导出器、宿主资源组装器和 Pi 项目登记脚本。
- 上一轮在不含 Codex 的隔离 PATH 中复现了默认安装、更新、验证、dry-run 的拒绝；同一环境中的 Claude/Pi/DSH 导出和离线 `doctor` 均通过。
- 本机 Claude Code 为 `2.1.247`；核对了 `plugin install`、`plugin update`、`marketplace add/update`、`plugin validate` 的 CLI 帮助。
- 在临时 Claude 导出中加入 marketplace 原型后，marketplace 和 plugin manifest 均通过 `claude plugin validate --strict`。严格校验还要求提供 marketplace description；实施时应一并生成。
- 本次没有执行宿主安装。Pi、DSH 不在本机 PATH 中；其原生持久安装、更新和加载仍属于实施验收项，不能从文档或 manifest 校验推断已经成功。

## 来源

以下为本次实际读取的正文或源码。主分支和在线文档会变化，实施测试还需记录选定客户端版本。

- [Claude：发现和安装插件][claude-install]
- [Claude：创建和分发 marketplace][claude-marketplace]
- [Pi：Packages][pi-packages]
- [DSH：Package and install a plugin][dsh-publish]
- [DSH：CLI behavior reference][dsh-cli]
- [DSH：MCP client][dsh-mcp]
- [DSH：Skills][dsh-skills]
- [Qwen：install.sh，已读取宿主选择及 Claude/Codex 安装更新分支][qwen-script]
- [Qwen：Installation][qwen-doc]
- [Superpowers：README 安装章节][superpowers-readme]
- [Superpowers：package.json][superpowers-package]

[claude-install]: https://code.claude.com/docs/en/discover-plugins
[claude-marketplace]: https://code.claude.com/docs/en/plugin-marketplaces
[pi-packages]: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md
[dsh-publish]: https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md
[dsh-cli]: https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md
[dsh-mcp]: https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md
[dsh-skills]: https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md
[qwen-script]: https://github.com/QwenLM/Qwen-MM-Plugins/blob/main/install.sh
[qwen-doc]: https://github.com/QwenLM/Qwen-MM-Plugins/blob/main/docs/en/installation.md
[superpowers-readme]: https://github.com/obra/superpowers
[superpowers-package]: https://github.com/obra/superpowers/blob/main/package.json
