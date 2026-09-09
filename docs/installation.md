# 安装与更新

Bookmark Research 0.2.0 使用 Python 3.9+ 标准库和 SQLite FTS5。先安装 Python 与要使用的客户端；运行 `python3 src/cli.py doctor` 可以离线检查 Python 和 FTS5。客户端兼容范围见 [README](../README.md#client-support)。

## 取得代码

从 [v0.2.0 Release](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases/tag/v0.2.0) 下载 [插件 ZIP](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases/download/v0.2.0/bookmark-research-0.2.0.zip)；需要运行离线验证时下载 [测试包](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases/download/v0.2.0/bookmark-research-test-pack-0.2.0.zip)。两个包均包含 `MANIFEST.sha256`，Release 另提供 ZIP 的 `SHA256SUMS`。解压时保留 `.codex-plugin/` 和 `.agents/` 等隐藏目录，并把目录放在一个稳定位置。

仓库地址：<https://github.com/Browser-bookmark-hub/Bookmark-Research>。复现本版本使用 `v0.2.0` 标签；`main` 跟随开发更新。本项目通过 GitHub Release 和源码分发。

```sh
git clone --branch v0.2.0 https://github.com/Browser-bookmark-hub/Bookmark-Research.git
cd Bookmark-Research
python3 src/cli.py doctor
```

请在包含 `scripts/install.py` 的 0.2.0 checkout 或 ZIP 中使用下方安装入口。旧提交仍可使用原生 Codex 命令或各自版本的导出器。

## Codex CLI 安装

在当前源码或解压目录运行：

```sh
python3 scripts/install.py install
python3 scripts/install.py verify
```

安装器会调用 Codex 原生 `plugin marketplace add`、`plugin add` 和 JSON 查询接口；Codex 管理其配置和安装缓存。安装完成后新建 Codex thread，以载入新 Skill 和 MCP 工具。Python 必须能以 `python3` 被 Codex 的 MCP 子进程找到。需要支持这些子命令和 `--json` 的 Codex CLI；本仓库验证环境为 0.153.4。

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

远程安装本版本时，使用 `codex plugin marketplace add Browser-bookmark-hub/Bookmark-Research --ref v0.2.0`，再执行 `codex plugin add bookmark-research@bookmark-research`。`--ref main` 跟随开发分支，固定版本则使用标签或 commit。已有同名来源先按上文核对其注册状态。

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

### Claude Code

```sh
python3 scripts/export_bundle.py --format claude --output exports/claude/bookmark-research
claude --plugin-dir ./exports/claude/bookmark-research
```

包含 `.claude-plugin/plugin.json`、`.mcp.json` 和共享 Skill；`--plugin-dir` 为当前会话加载插件。参见 [Claude Code plugin reference](https://code.claude.com/docs/en/plugins-reference)。

### Pi

```sh
python3 scripts/export_bundle.py --format pi --output exports/pi/bookmark-research
pi --skill ./exports/pi/bookmark-research/skills/bookmark-research/SKILL.md
```

用 `/skill:bookmark-research` 加载工作流。需要持久注册时执行 `pi install /absolute/path/to/exports/pi/bookmark-research`。Pi 适配器声明 `pi.skills`，Skill 调用 Python CLI；没有 Pi MCP bridge 或原生工具 extension。参见 [Pi package documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md)。

### DSH / DeepSeek Harness

先在 DSH 环境安装官方 `@deepseek-ai/dsh-mcp-client`。把以下占位路径换成最终保留的目录：

```sh
python3 scripts/export_bundle.py --format dsh --output /absolute/path/to/bookmark-research-dsh
dsh --profile web --patch /absolute/path/to/bookmark-research-dsh/cordis.patch.yml --dump-config
dsh web --patch /absolute/path/to/bookmark-research-dsh/cordis.patch.yml
```

`cordis.patch.yml` 连接 MCP；Skill 发现仍需把现有 Skill provider 的 `customSkillDirs` 指向该导出的 `skills/`。补丁包含绝对路径，移动目录后必须重新生成。它是本机适配器，不是可搬移的 `dsh.bundle` npm 包。参见 [官方 MCP client 文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)。

Claude Code、Pi、DSH 的导出结构和独立运行时有测试覆盖；各客户端内的加载和实际工具调用仍需客户端验证。

### Agent Plugins 1.0.0

```sh
python3 scripts/export_bundle.py --format agent-plugin --output exports/agent-plugin/bookmark-research
```

此格式使用根目录 `plugin.json` 和 `mcp.json`，供实现 [Agent Plugins 1.0.0](https://agent-plugins.org/specification) 的客户端使用。它与 Codex 原生格式分别导出。

## 首次使用与数据位置

插件不附带用户书签或预建索引。安装后提供自己的数据包路径：

```text
用 Bookmark Research 导入 /absolute/path/to/my-canvas-package，来源名为 my-canvas。
先离线列出栏目与卡片，再搜索“我的研究主题”，保留文件夹及卡片语境。
```

网页研究使用 Exa、Parallel，以及可选的 Tavily。按使用的服务在启动 MCP / CLI 的进程环境中设置 `EXA_API_KEY`、`PARALLEL_API_KEY`、`TAVILY_API_KEY`；本地书签查询不需要这些密钥。安装和导出不会收集或写入凭据。

索引、页面归档和研究任务保存在 `BOOKMARK_RESEARCH_DATA_DIR`，默认 `~/.local/share/bookmark-research/`，并遵循 `XDG_DATA_HOME`。用户设置通过 `BOOKMARK_RESEARCH_CONFIG` 指定，默认 `~/.config/bookmark-research/settings.json`，并遵循 `XDG_CONFIG_HOME`。保持这些目录位于插件和安装缓存之外，多个客户端可通过相同配置共享它们。详见 [设置与归档](../skills/bookmark-research/references/settings-and-archive.md)。

## 更新

```sh
python3 scripts/install.py update --dry-run
python3 scripts/install.py update
python3 scripts/install.py verify
```

Git marketplace 的 `update` 保持已注册的仓库与 ref，刷新其快照；固定到不可变 tag/commit 时不会自动跳到另一个版本。本地 marketplace 的 `update` 使用该目录当前内容，不替你执行 `git pull`。先取得目标源码版本，再更新插件。源码目录改变不等于已经更新了正在运行的会话；完成后新建 Codex thread。

本机开发如使用 `$plugin-creator`，按该 Skill 的 cachebuster 与重装流程处理已注册的个人插件；无需为了刷新缓存改变正式发布版本。共享 Skill 和运行时应一起更新，用户数据和配置留在原位置。

## 本地构建 ZIP

维护者从已验证的工作树构建，输出路径必须不存在：

```sh
python3 -m unittest discover -s tests
python3 scripts/build_zip.py --output dist/bookmark-research-0.2.0.zip
```

ZIP 包含原生插件、marketplace、共享运行时、Skill、安装入口、导出器、文档和许可；不包含测试、数据库、页面归档、用户配置或书签数据包。测试与合成测试包留在源码仓库。

构建结果打印 ZIP 的 SHA-256；相同内容以固定文件顺序、时间和权限打包，在相同 Python/zlib 环境中可重现相同字节。解压后的 `MANIFEST.sha256` 列出包内文件校验和，可在解压目录运行 `shasum -a 256 -c MANIFEST.sha256`。校验和用于发现损坏，来源真实性仍取决于你下载的仓库或发行渠道。

构建只在本地生成文件。发布 GitHub Release、创建 tag 或推送 npm/PyPI 都不是构建器的行为。安装设计的参考依据和验证范围见 [0.2.0 安装设计](install-design-0.2.0.md)。
