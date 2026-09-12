# GitHub 与同步边界

[English](../github-and-sync.md) · **中文阅读版**

本参考吸收公开数据包指南 S6.0、S6.4、P1、P2 中与研究相关的路由、持久偏好和同步边界；依据版本见 [阅读协议](package-semantics.md#依据与维护)。不把生成与回写流程加入本分析 Skill。

## 研究 GitHub 内容

插件未内置 GitHub MCP、GitHub OAuth 或 `gh`，也不安装它们。先识别宿主实际可用并已获授权的工具：

| 任务 | 采用的入口 |
| --- | --- |
| 读取公开 README、文档或 Gist | 已有 GitHub 文件读取工具；或 `fetch_web` 读取公开 URL |
| 精确查代码、指定分支/提交、issue、PR、release | 优先用宿主已有 GitHub MCP；有 `gh` 时也可通过宿主命令工具读取 |
| 查看用户提供的本地仓库历史与改动 | 宿主命令工具的 `git status`、`git diff`、`git log` |
| 提交、推送、拉取、创建 issue 或 PR | 属于另外的修改任务，按用户当前授权和该目录规则执行；本插件不提供这些操作接口 |

不要把网页成功抓取等同于查过仓库全部代码、全部评论或指定提交。未接入 GitHub 专项工具时，可读取相关公开网页并说明覆盖范围；涉及私有仓库时沿用宿主已有访问方式与任务范围，不把私有内容发给公开搜索服务。官方 GitHub MCP 项目可参考 https://github.com/github/github-mcp-server 。

宿主 GitHub MCP／`gh` 的结果不经过本插件 `fetch_web`，因此不会自动进入其归档。需要保存这些结果时，保存实际返回内容并记录仓库、文件路径、ref／commit（能取得时）、URL 与读取时间；不要伪造缺失字段。

## 数据包中的 Git 同步约束

`AGENTS.md` 提及 GitHub 不代表自动安装或授权 GitHub MCP。指南允许参考官方仓库，并约束用户数据包在 Git／同步目录中的处理方式。

普通本地查询无需做整库同步审计。只有任务实际涉及包内文件结构调整、回写或 commit/push/pull 时，才核对该包 `AGENTS.md` 的 P2：检查允许的包结构与 `.canvas`，按其规则处理外部 file 节点及无关文件，并验证本次改动；分析工具不得把检查变成未经请求的清理或提交。

研究报告、正文快照、配置和数据库放在画布包之外。不要为接入研究功能，在原画布同步目录添加 `knowledge/`、`raw/` 或 `wiki/`，避免这些文件受到画布同步清理。长期偏好保存到用户配置或 Skill；包内 `AGENTS.md` 可能在后续导出／同步时被模板重建。

持续同步到本地的画布目录可登记为 `mode:live`；明确是完整镜像时配合 `completeness:complete`。MCP 运行期间定期检查落盘变化，遇到 Git 写入锁、空目录或校验失败时保留有效索引。插件不执行 Git 拉取、推送或登录；同一画布的手动导出仍可作为 snapshot 接入。参数、删除等待窗口和重连行为见 [来源生命周期](source-lifecycle.md)。
