# 0.2.0 验证记录与测试包

核验日期：2026-09-10。这里区分本地行为测试、真实数据包验证、服务连通性和客户端加载；某一层成功不替代其他层的验证。

## 需求与证据

| 需求 | 实现与可核对证据 |
| --- | --- |
| 保持独立插件、版本 0.2.0 | `.codex-plugin/plugin.json`；导出器从同一 manifest 读取版本；原项目只作资料参考 |
| 聚合 MCP | `src/provider_adapters.py`、`web_search.py`、`remote_mcp.py`；真实工具 schema fixture 与四个聚合相关测试模块 |
| 三层检索路由 | `skills/bookmark-research/SKILL.md` 与 `references/deep-research.md`；官方出处与设计取舍见 [调研报告](research-0.2.0.md) |
| 可继续的深度研究 | `src/research.py` 与 `tests/test_research.py`：规划、预算、检索、引用、冲突、修订、恢复与报告 |
| 保留书签语境 | `bookmark_refs` → `context.json` → source 的书签实例关联；同 URL 在不同栏目保持独立身份 |
| 有依据的结论 | 来源身份审阅、原句匹配、哈希校验、被拒绝来源拦截、撤回结论后重开问题 |
| 学习 Qwen 安装结构 | [安装设计](install-design-0.2.0.md)：原生 CLI、install/update/verify、来源选择、固定版本与配置分离 |
| 可下载和验证的包 | `scripts/build_zip.py` 生成普通 ZIP 与 `--include-tests` 验证包；确定性文件清单与 SHA-256 |
| 详细查看调研 URL | [完整来源清单](research-sources-0.2.0.json)：逐项读取、失败、私人链接处理和来源质量状态 |

## 离线测试

v0.2.0 发布快照测试：Python 3.9 / Codex CLI 0.153.4 环境中 **183 项全部通过，0 跳过**（6.010 秒）。Plugin validator、Skill quick validator、Python 编译检查与 `git diff --check` 通过。最终合成包验证完成两轮研究，输入 5 文件哈希未变。

发布后的 `main` 补充一条命令安装和首次使用引导；2026-09-10 的完整测试为 **193 项全部通过，0 跳过**（15.876 秒）。新增检查覆盖本地 Git 仓库的管道安装、临时目录清理后继续使用、固定 ref、已有 personal 安装识别，以及实际配置读取、默认配置无需文件、已有设置保留、配置损坏提示和 stdout JSON 与 stderr 引导分离。

在源码根目录或解压后的测试包根目录运行：

```sh
python3 -B -m unittest discover -s tests -v
python3 scripts/verify_fixture.py --output /tmp/bookmark-research-validation
```

测试包包含虚构域名、合成书签和录制的公开工具 schema，不包含个人书签库、API Key 或预建索引。默认不向网页服务发请求；系统有 Codex CLI 时，安装测试使用临时独立 profile 实际执行原生命令。没有 Codex 时相关客户端测试会 skip，不能把 skip 当作已验证安装。

`verify_fixture.py` 使用固定离线响应，验证如下可观察行为：

- 独立读取 JSON 计数并与 SQLite 对照；永久副本不增加总书签数。
- 同 URL 的不同实例、栏目、组、子文件夹范围均保留。
- 导入前后源文件 SHA-256 相同；第二次同步未变更。
- 完成两轮研究，保留缺口、实际引用、失败页面与研究来源映射。
- 关闭并重开运行时后，相同操作编号复用结果，不再次执行检索。
- 交付独立的 `context.json`、`report.md`、`sources.json` 与原响应／正文快照。

测试返回 `network_calls:0`；研究计数中的 4 search calls / 3 fetch calls 是合成适配器调用，不能当作真实服务质量或费用测试。

单元测试还覆盖预算被并发调用消耗、请求中断后保留预留、没有正文／引用原句不存在／正文被修改、来源被拒绝、结论撤回、冲突解决依据失效、未回答问题无法标记完成，以及 CLI 和 MCP 的输入边界。

独立审查发现并修复了回执已写但状态未提交时的来源恢复、超过 2 MiB 的研究状态返回、MCP 错误标记、撤回结论被脚注渲染隐藏等问题。回归用例包括 45 条 claim／540 段长引用的完整分页与完成响应；审查者另用实际 Markdown 渲染器确认历史结论和跳转链接可见。

另一位代理按 Skill 自主探索合成画布，没有读取预设验证流程或答案。它找到 Investigation 组的 4 个书签及后续连线，发现 scenario 缺少 update 页后诚实交付 incomplete。补齐合成资料后，评估又暴露 incomplete 报告缺少恢复入口；现通过 `research_record kind=resume` 在同一任务继续。原报告、状态和来源快照保留，补读后完成报告，fetch 预算从 2/4 增至 3/4，原 unknown_outcome 不退款。初次失败和修复后结果保存在 `/tmp/bookmark-research-skill-eval-0bclzs9d/`，没有把首次运行改写成全程成功。

恢复另经独立故障注入复核：连续两次恢复的 6 份快照逐字节一致，原报告的 9 个相对链接可解析；快照写入或状态保存失败时原产物保持完整，再次恢复不重复网络调用、不增加预算。

## 用户提供的数据包

实际在提供的示例画布上运行了：

```sh
python3 scripts/verify_fixture.py --output /tmp/bookmark-research-0.2.0-fixture-check \
  --package '/absolute/path/to/书签画布-20260906'
```

| 指标 | 实际结果 |
| --- | --- |
| 书签实例 | 638 |
| 不同原始 URL | 557 |
| 文件夹 | 122 |
| 栏目／画布节点／连线 | 5／7／3 |
| 已检查源文件 | 7，含包内指南 |
| 源文件变化 | 无；逐文件 SHA-256 一致 |
| 第二次同步 | `changed_files:0` |

计数使用原 JSON 的独立遍历与导入后的 SQLite 交叉核对。这里没有联网抓取这 557 个 URL。完整个人路径与逐文件哈希保存在本地验证输出，公开测试包只收录合成数据。

另一个 AI 升级调研包的 223 个书签实例／207 个去重 URL，其研究覆盖与无法读取项单独列在 [来源清单](research-sources-0.2.0.json)，不把这些实例数混作公司或独立证据数。

## 真实服务验证

运行命令需要显式打开网络验证：

```sh
python3 tests/live_provider_smoke.py --run-live --output /tmp/bookmark-provider-smoke.json
```

一次最多三次搜索与三次提取，测试进程清除服务密钥并使用临时设置。观察结果见 [provider-smoke-0.2.0.json](provider-smoke-0.2.0.json)：三家工具目录与提取成功；Parallel、Tavily 搜索成功；首次 Exa 搜索连接失败，另一次明确发起的 Exa 搜索成功。原始集合保留 `passed:false`，成功复验单列，未把自动重试或持续可用性当成已验证。

这些检查未执行供应商托管 Deep Research、OAuth 或付费研究任务。Exa Agent、Parallel Task MCP、Tavily Research 的独立接口与认证依据见 [MCP 接入说明](mcp-aggregation-0.2.0.md)。本插件第三层是宿主模型使用可恢复研究工具执行的流程。

## 真实研究流程

使用工作区 0.2.0 的 `ResearchSessions`，由宿主模型实际完成“核验三层搜索与原生深度研究服务的边界”。任务 `r-e7090e9833194564` 位于本机 `/tmp/bookmark-research-0.2.0-live-research/sessions/`；网络步骤在不同进程中继续，读取已存来源、审核正文、记录原句后综合报告。

| 观察项 | 实际结果 |
| --- | --- |
| 问题／搜索轮次 | 2／2 |
| 已预留检索调用 | 4 search calls、3 fetch calls |
| 实际来源快照 | 4，来自 3 个不同官方 URL |
| 主张与修订 | 10 条，其中 1 条拆分后撤回；历史原句保留 |
| 冲突 | 1 项，同 URL 摘录写 basic／fast；结论明确保留模式未知 |
| 最终状态 | completed，报告、来源清单、操作回执与原文均存在 |

这次不是脚本预置回答：第二轮根据第一轮定义补读接口，发现不同快照的模式差异后额外读取并记录冲突。Exa 和 Parallel 的真实 search/fetch 调用均成功。完成标准是回答两道接口边界问题；不能据此声称已经运行供应商原生研究任务、核实服务器默认模式或通过通用研究质量基准。

实际摘录的 Search MCP 模式证据：Parallel 快照 SHA-256 `fbff308d1ca7bf7cdaa1fffc001dcb27cf2faa63a52423f2d6a1aa202d4bf925` 写 `Anonymous free-tier searches run in [fast mode] by default`（原 Markdown 带链接）；Exa 快照 SHA-256 `cc9ab5f5e83ca5e7186ce1701f8567e2bae9626c2737990a3fa56c13ec0f49e2` 写 `Search runs in basic mode`（原 Markdown 带代码标记）。保存的逐字原句和限制见该任务 `report.md`。

调研来源清单另经复核：207 个原 URL 指纹、223 个实例映射、191 份正文／响应文件哈希和 16 处短引用全部匹配；原调研包 9 个文件哈希未变。覆盖不足和身份错配仍按原记录保留。

## 安装、更新与包完整性

安装测试使用 Codex CLI 0.153.4 和 Python 3.9：中文、空格、引号与字面 `$()` 路径；重复安装；同版本内容更新；版本更新；已存在索引和用户设置保留；来源冲突；安装缓存中的 doctor 与 MCP 初始化／工具发现。

普通发行 ZIP 与测试包使用同一版本源码构建，并作为 [v0.2.0 Release](https://github.com/Browser-bookmark-hub/Bookmark-Research/releases/tag/v0.2.0) 附件分发。Release 的 `SHA256SUMS` 校验整个 ZIP，各包的 `MANIFEST.sha256` 校验内部文件。复现构建：

```sh
python3 scripts/build_zip.py --output dist/bookmark-research-0.2.0.zip
python3 scripts/build_zip.py --include-tests --output dist/bookmark-research-test-pack-0.2.0.zip
```

输出路径应不存在；需要重新构建时用新路径或先自行移动旧产物。解压后核对 `MANIFEST.sha256`，再运行验证：

```sh
shasum -a 256 -c MANIFEST.sha256
python3 src/cli.py doctor
python3 scripts/install.py verify
```

最后一条要求已在该客户端安装插件。测试包还可运行 `verify_fixture.py`；普通插件包不含测试资料。导出测试覆盖 Codex、Claude Code、Pi、DSH 与 Agent Plugins 五种目录结构，以及从任意工作目录启动。Claude Code、Pi、DSH 的客户端内实际加载仍未验证，不能仅凭导出成功宣称原生客户端已工作。
