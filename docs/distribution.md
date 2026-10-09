# 发布与安装约定

正式发布只使用 npm 的 `bookmark-research` 包。它包含共享 Python 运行时、Skill 和各宿主适配文件；不维护四份独立源码或四个发布版本。GitHub 用于源码、问题跟踪、版本说明及安装清单。GitHub Release 可选，仅保留版本说明和 npm 链接，不再附安装包、测试包或配套校验文件；历史附件已备份撤下。

| 入口 | 插件内容来源 | 登记和缓存 |
| --- | --- | --- |
| `npx bookmark-research@latest install codex` | npm 发布包 → Codex 格式 | Codex 原生命令 |
| `npx bookmark-research@latest install claude` | 同一个 npm 包 → Claude 格式 | Claude Code 原生命令 |
| `npx bookmark-research@latest install pi` | 同一个 npm 包 → Pi 格式 | `pi install` |
| `npx bookmark-research@latest install dsh --profile web` | 同一个 npm 包 → DSH bundle | `dsh plugin --profile web add` |
| GitHub `install.sh` | 转交上述 npm 入口 | 所选宿主原生命令 |
| Codex GitHub marketplace | 清单中固定的 npm 版本 | Codex 直接下载和登记 |

统一的是发布内容和来源。不同宿主需要不同清单，安装器只生成所需格式，用户配置、宿主登记及缓存仍交给宿主命令。Pi 的基础路径提供 Skill 和 CLI；其他宿主按各自适配提供 MCP。

默认安装器记录 `npm:bookmark-research`（`latest`），更新时重新下载，不依赖已清理的 npx 缓存。显式 `--source npm:bookmark-research@VERSION` 会保留版本；要测试同一个固定发布版，在四个宿主使用相同参数。Codex 原生 marketplace 使用清单固定版本，跟随清单更新。需要新版安装器时运行 `npx bookmark-research@latest update`，或先更新全局 npm 安装。

源码开发使用 `python3 scripts/install.py install --source PATH`，也可显式选择 Git 仓库和 `--ref`。旧 Git／本地安装保留来源，不静默转成 npm；切换时先用宿主命令处理旧登记。源码导出、ZIP 和测试包脚本保留为开发工具，CI 的验证产物仍可包含 npm `.tgz` 与 SHA-256 校验文件，但不作为 GitHub Release 下载入口。GitHub 自动生成的 Source code 压缩包是源码快照，不能单独关闭，不作为安装包。

发布顺序：修改源码版本并完成 CI，发布已经验证的 npm 包，确认 registry 可取得该版本，再更新 GitHub marketplace 的固定版本。未发布源码不能通过 npm 入口安装；需要先用源码入口测试。

测试版使用 npm 的 `beta` 标签；若创建 GitHub 版本说明，则标记为预发布。不会自动移动 npm 的 `latest` 标签。安装测试版时同时固定安装器与内容来源，例如 `npx bookmark-research@0.5.0-beta.7 install --source npm:bookmark-research@0.5.0-beta.7`。仅将 npx 改为 `@beta` 不会改变默认内容来源 `latest`；已固定的旧版安装也不会自动换成测试版。

## 官方资料与项目实例

2026-10-08 通过网页搜索并读取以下页面。它们支持多种发行方式，**没有“所有插件都只用 npm”的行业要求**；这里选择 npm 是为了减少本项目的发行分支。

- [OpenAI：Package your plugin](https://developers.openai.com/plugins/build/plugins)：marketplace 可指向本地、Git 或 npm；npm 内容下载不执行生命周期脚本。
- [Claude Code：Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces#npm-packages)：支持 npm、GitHub、Git URL 和本地目录等来源。
- [Pi：Packages](https://pi.dev/docs/latest/packages)：支持 npm、Git 和本地路径；版本化 npm 来源保持固定。
- [DSH：Package and install a plugin](https://deepseek-harness.github.io/deepseek-harness/en/develop/basic/publish)：支持 Git 安装，也建议发布已构建的 npm 包或 tarball，免去用户安装时构建。
- [Superpowers](https://github.com/obra/superpowers)：按宿主提供不同安装方式，Pi 使用 Git 仓库，Claude Code 使用 marketplace，并非 npm 唯一来源。
- [pi-skills](https://github.com/badlogic/pi-skills)：跨宿主 Skill 集合，文档仍提供 Git 克隆安装。

这些资料说明“宿主安装方式不同”是正常的；本项目统一发布包后仍保留必要的宿主适配。
