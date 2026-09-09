# 0.2.0 安装设计与依据

本版本借鉴 Qwen-MM-Plugins 的安装结构：把获取代码、客户端注册、更新、运行检查和发布分别实现；共享 Skill 和 MCP runtime 作为同一版本交付，个人数据与凭据保存在包外。

## 参考材料与采用范围

核对时间：2026-09-10。参考本地用户指定的 `Qwen-MM-Plugins-main` checkout；只读取其文件，没有修改该项目。

| 依据 | 原做法 | Bookmark Research 的对应决定 |
| --- | --- | --- |
| [Qwen README：Install](https://github.com/QwenLM/Qwen-MM-Plugins/blob/main/README.md#install) | 先给安装和更新入口，再链接详细指南；可把说明交给 agent 执行 | README 保留简明入口，完整路径、更新语义和客户端限制写在 installation.md |
| [Qwen installation](https://github.com/QwenLM/Qwen-MM-Plugins/blob/main/docs/zh/installation.md) | 区分 release、update、local 和 rollback；Skill 与 MCP 一起更新；共享配置包外 | `install / update / verify` 显式分工，Git ref 与本地 checkout 含义分开；保持现有外部数据和设置目录 |
| [Qwen install.sh](https://github.com/QwenLM/Qwen-MM-Plugins/blob/main/install.sh)，本地行 820–931 | Codex 调用原生 add / upgrade；Git 与 local 更新路径不同；前置步骤失败即停止 | scripts/install.py 以参数数组调用同一组原生命令，读 JSON 检查状态；来源冲突、升级错误或运行验证失败返回非零 |
| [Qwen pyproject.toml](https://github.com/QwenLM/Qwen-MM-Plugins/blob/main/pyproject.toml) | 一份 Python distribution、多个 capability extras 与 console scripts | 本插件只有一个共享 runtime、无第三方依赖；保留 Python 脚本入口，不为安装再加入 uv、setuptools 或 npm |
| [Qwen releasing](https://github.com/QwenLM/Qwen-MM-Plugins/blob/main/docs/en/releasing.md) 和本地 AGENTS.md 的 Release invariants | 一份版本目录，Skill、MCP、manifest、tag 保持一致；不可变发布 tag | `.codex-plugin/plugin.json` 是本插件唯一发布版本源；所有导出和 ZIP 实时读取，不各自硬编码版本 |
| [官方 OpenAI Codex CLI reference](https://developers.openai.com/codex/cli/reference#codex-plugin) | 原生 plugin add/list、marketplace add/list/upgrade；Git shorthand、ref、本地根目录；支持 JSON 输出 | 使用公开 CLI 契约管理配置，真实临时 Codex profile 核对 JSON 字段和本地安装行为 |

本地参考位于用户指定的 `Qwen-MM-Plugins-main/{README.md,AGENTS.md,install.sh,pyproject.toml,docs/zh/installation.md,docs/en/releasing.md}`。GitHub `main` 链接用于定位项目，未来内容可能变化。官方 CLI 文档在实现前通过 Exa 搜索并读取了全文，随后通过本机 `codex plugin ... --help` 和隔离 profile 的实际 JSON 响应交叉检查。

Qwen 的远程 `curl | bash` 入口依赖已经发布的安装脚本与独立能力发布目录。本次没有发布外网入口，也没有复制其多能力菜单、重型媒体依赖或自动配置密钥流程。使用本地 ZIP、checkout 和原生 Codex Git 安装，能够与现有标准库运行时保持一致。

## 命令边界

`scripts/install.py install` 默认使用脚本所在源码根目录，与当前 shell 工作目录无关；`--source` 可指定本地 marketplace 或 Git 仓库。`--ref` 只用于 Git，真实版本由实际安装结果报告。安装器先检查同名 marketplace 的来源，不自动执行 remove，也不编辑 `config.toml` 或个人 marketplace JSON。

Codex 0.153.4 实测 `marketplaceSource` 只公开 Git URL，不公开已注册 ref。因此 `--ref` 仅在首次注册时接受；已有 Git 来源重装需省略该参数，换 ref 使用原生来源管理。同一个 HEAD commit 也可能同时属于 branch 和 tag，不能据此证明未来更新仍固定到该 tag。

`update` 只操作已经安装的 `bookmark-research@bookmark-research`。Git 源使用原生 `marketplace upgrade` 刷新已注册 ref，然后 `plugin add`；本地源直接重新 `plugin add`。没有自动切换 Git ref，也不拉取本地工作树。客户端原生命令的错误和 JSON 中的升级错误都中止后续步骤。

`verify` 检查 Codex 已安装且启用的版本，读取安装缓存 manifest，用缓存中的 Python 文件执行 FTS5 检查，再以原生 MCP launch 配置执行初始化与工具列表查询。它不把导出结构测试称为 Claude Code / Pi / DSH 的实际客户端加载验证，也不把离线初始化称为 provider 网络可用性验证。

`--dry-run` 只使用原生读取接口与本地文件读取，然后返回将执行的命令数组。参数数组同时避免了空格、引号、中文或 shell 特殊字符改变命令含义。

## 发布包结构

新增 `--format codex` 生成独立的 `.codex-plugin/plugin.json` 和 `.agents/plugins/marketplace.json`，保留原生 Skill 展示元数据。其他格式保持各自入口，不把 Codex manifest 当作跨客户端通用格式。

导出和 ZIP 使用公共文件选择规则：`src/` 中的 Python、唯一公共 provider 配置、Skill Markdown 与明确的原生元数据。隐藏文件、测试、构建目录、缓存、数据库、归档、用户 JSON / `.canvas` 都不会经这些通配根目录进入分发。源文件符号链接会被拒绝，输出路径存在用户内容时不覆盖。

ZIP 额外包含 README、安装与兼容文档、安装/导出/构建脚本和许可，并生成 `MANIFEST.sha256`。默认 ZIP 不含私有书签、密钥、用户研究记录或开发测试；源码测试套件使用合成数据独立验证行为。所有发布格式从同一 manifest 读取版本。

## 可验证性

对应测试是 `tests/test_export_bundle.py` 和 `tests/test_install.py`。检查范围包括：

- 五种导出的入口、版本一致性、目录外启动、stdio MCP 初始化及独立数据目录。
- 原生 Codex JSON 契约、重复安装、本地更新、已注册来源冲突保护、Git 升级错误中止。
- 含中文、空格和 shell 字符的路径；失败时不覆盖现有文件或发布半成品目录。
- SQLite、用户 JSON、`.canvas`、缓存、环境密钥标记不进入干净导出或 ZIP。
- 固定 ZIP 内容、SHA-256 清单、解压后独立运行安装器与导出器。

真实 Codex 测试仅在系统安装了 Codex CLI 时运行，并使用测试临时 `CODEX_HOME` 管理专用 profile。它不会安装到日常使用的 Codex profile，也不访问网页服务。无 Codex 的环境仍运行导出、打包、运行时和命令契约测试；真实 CLI 测试会明确显示跳过。
