# `bookmark-research` 命令与跨平台安装计划

日期：2026-09-24。目标：像 `claude`、`codex` 一样，在终端输入 `bookmark-research` 即可安装、配置、检查和更新插件；macOS、Linux、Windows 原生均可用。

## 决策

| 问题 | 决定 | 理由 |
| --- | --- | --- |
| 分发途径 | **npm 为主入口，GitHub 为源码与备选入口** | npm 在三个系统上自动生成可执行命令；Pi、DSH、Codex 用户基本已有 Node。`curl \| bash` 保留给不想用 Node 的 macOS/Linux 用户。 |
| 包名 | `bookmark-research`（2026-09-24 查询 npm 未被占用） | 与插件名一致。 |
| 运行时 | npm 包只是薄入口，调用包内 Python（3.9+，含 FTS5） | 不重写已测试的 Python 安装器与 MCP。 |
| 发布前 | `npx github:Browser-bookmark-hub/Bookmark-Research` 可直接从 GitHub 运行 | 不依赖 npm 账号即可试用。 |

## 命令设计

```
bookmark-research                 终端中打开主菜单；非终端输出 JSON 状态
bookmark-research install [HOST…] 安装到一个或多个宿主（无参数时进入向导）
bookmark-research update [HOST…]  更新已安装宿主（默认全部）
bookmark-research verify [HOST…]  验证已安装宿主
bookmark-research setup           配置向导（偏好、服务、隐藏输入 Key、可用性检查）
bookmark-research status          已安装宿主、服务与 Key 状态（JSON）
bookmark-research config show|set 查看或修改偏好（set 从 --input 读取 JSON）
bookmark-research doctor          检查 Python 与 SQLite FTS5
```

规则：

1. 命令不绑定版本号。所有操作都用 npm 包自带（或 checkout 中）的 Python 源码；配置与 Key 属于用户级数据，与宿主安装分离。
2. 已安装宿主从安装记录读取：Codex 读 `codex plugin list`，其他宿主读 `~/.local/share/bookmark-research/installations/*/receipt.json`。
3. 非终端（agent/CI）不弹菜单；需要的参数必须显式传入，输出 JSON。
4. API Key 仍只允许隐藏输入或环境变量，不接受命令参数与 JSON。

## Windows 原生适配

| 位置 | 问题 | 改法 |
| --- | --- | --- |
| `src/tui.py` | 用 `termios` 读按键 | Windows 用 `msvcrt.getwch()`，方向键前缀 `\xe0`/`\x00`；启用 VT 输��。无法读键时退回纯文本模式。 |
| `src/onboarding.py` | 从 `/dev/tty` 打开终端 | Windows 用 `CONIN$`/`CONOUT$`。 |
| `scripts/host_install.py` | `fcntl` 安装锁 | Windows 用 `msvcrt.locking`（与 `src/settings.py` 相同做法）。 |
| MCP 启动命令 | 写死 `python3` | 导出与安装时写入实际解析到的 Python（`python3` → `python` → `py -3`）；Codex 仓库清单保持 `python3`，Windows 上由安装器改写本地导出。 |
| 入口 | bash 脚本 | npm `bin` 为 Node 脚本，查找 Python 后转发参数。 |

## 实施与验收

1. `bin/bookmark-research.js`（Node）+ 根目录 `package.json` 的 `bin`/`files`；查找 Python，版本不足时给出安装说明。
2. `scripts/launcher.py`：子命令分派与主菜单，复用 `install.py`、`cli.py`。
3. Windows 适配（上表）。
4. 测试：launcher 分派、Python 探测、非终端行为；跨平台逻辑单元测试；GitHub Actions 矩阵（ubuntu / macos / windows）。本机只能验证 macOS。
5. README：安装、后续配置、插件包含的 MCP 与 Skill。

完成标准：本机全量测试通过；`npm pack` 后用 `npx ./bookmark-research-*.tgz` 在隔离目录跑通 `status`、`install --dry-run`；Windows 仅以 CI 配置和单元测试覆盖，真实 Windows 验证待 CI 运行。

## 完成情况（2026-09-24）

- 已实现：`bin/bookmark-research.js`、根目录 `package.json`（含 `bin` 与 `pi.skills`）、`scripts/launcher.py` 主菜单与子命令、Windows 按键／控制台／安装锁／Python 路径适配、`.github/workflows/test.yml` 三系统矩阵、README 与安装文档。
- 已验证（macOS）：全量 450 个测试通过；`npm pack` 后全局安装的 `bookmark-research` 真实完成 Claude Code 安装、`status`、`verify`（36 个 MCP 工具）；主菜单在伪终端中可用。
- 待验证：Windows 原生只由 CI 配置与模拟单元测试覆盖，需推送后看 CI；npm 包尚未发布；Codex 在 Windows 上仍使用仓库 manifest 中的 `python3` 启动 MCP，若系统没有 `python3` 命令需另行处理。
