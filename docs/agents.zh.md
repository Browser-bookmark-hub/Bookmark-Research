# Bookmark Research — 安装与开发说明（供 AI agent 与开发者）

[English](../AGENTS.md) · **中文阅读版**

> 实际执行以仓库根目录的英文 `AGENTS.md` 为准；本文件是对照阅读版，内容与之一致。

本文件分两部分：第 0 节给被用户要求安装本插件的 agent；第 1 节起是维护本项目的开发、测试与发布约定，适用于所有 AI 代理（包括 Codex、Claude Code、DeepSeek Harness、Devin、Antigravity 等）及开发者。修改代码、执行测试或准备发布时，必须严格遵守这些约定。

---

## 0. 安装到你当前运行的客户端

用户给了你本仓库或 npm 链接并要求安装时，在你当前运行的客户端里按以下步骤操作：

1. 先确认你自己是哪个客户端：`codex`、`claude`、`dsh`。其他任何能加载 [Agent Plugins 1.0.0](https://agent-plugins.org/specification) 插件包（根目录 `plugin.json`、`mcp.json`、`skills/`）的客户端，不论叫什么名字，都用 `other`。
2. 运行：`npx bookmark-research@latest install <客户端> --non-interactive --json`
   - `claude`：加 `--scope user`（或 `--scope project --project <目录>`）。
   - `dsh`：加 `--profile <名称>`；profile 名称先问用户。DeepSeek Harness 桌面版用 `--dsh "<桌面版自带 CLI 路径>" --profile desktop`。
   - `other`：结果里的 `installed_path` 是一个 [Agent Plugins 1.0.0](https://agent-plugins.org/specification) 插件目录（根目录 `plugin.json`、`mcp.json`、`skills/`）。用你自己的插件命令登记它；结果的 `register` 字段列出了已知命令（Devin：`devin plugins install --local <installed_path>`）。如果你只支持 MCP，就添加一个 stdio 服务 `python3 <installed_path>/src/cli.py serve`，并把 `<installed_path>/skills` 作为技能目录，或直接阅读其中的 `skills/bookmark-research/SKILL.md`。
3. 命令会输出 JSON。确认 `"verified": true`；有 `"error"` 就如实告诉用户，不要自行绕过。对 `other`，`verified: true` 只表示导出文件和 stdio 自检通过（`verified_scope: "files_and_stdio"`）；客户端登记是独立一步——看 `registration`。如果客户端登记命令失败（Devin 需要先 `devin auth login`），改用 `registration.fallback`。
4. 找出你自己的网页搜索和读页工具：查看你的工具列表，按工具说明里写的功能判断，不看名字（本插件的工具不算）。告诉用户找到了哪些，或者没有。Skill 会先用这些工具，再用插件的 `search`/`fetch`，并把实际用到的工具记录为 `provider:"host:<工具名>"`。
5. 不要在对话里向用户要 API Key（全部可选）。请用户在终端运行 `bookmark-research setup` 自己输入，或设置对应环境变量。
6. 提醒用户新建一个会话，让 Skill 和 MCP 工具生效。

不要把这个 Git 仓库本身直接当插件安装（例如 `devin plugins install Browser-bookmark-hub/Bookmark-Research`）：仓库根目录包含测试与开发文件，本文件也会被当作会话规则加载。始终通过上面的 `npx` 命令安装，它会生成干净的宿主包。

---

## 1. 开发与测试原则：本地优先，严禁频繁发布 npm

> [!IMPORTANT]
> **npm 发布仅用于面向全网用户的正式对外交付**。
> 日常开发、功能联调、Bug 修复或 PR 测试过程中，**绝对禁止**频繁递增版本并推送到 npm！必须在本地完成全量测试。

### 本地测试的三种标准方法

#### 方法一：本地源码直跑（最快捷，秒级生效）
直接从当前开发源码运行安装与测试，改完代码即时生效：
```sh
# 单独安装/更新到 Codex
python3 scripts/launcher.py install codex

# 启动交互式安装向导进行体验测试
python3 scripts/launcher.py install

# 快速验证本机所有宿主的安装和 MCP 工具状态
python3 scripts/launcher.py verify

# 离线环境与 SQLite 状态自检
python3 scripts/launcher.py doctor
```

#### 方法二：`npm pack` 本地模拟 npx（100% 还原真实安装，无需发包）
如果需要测试真实的 npm 打包和解压流，使用 `npm pack` 在本地生成压缩包，并通过 `npx` 直接加载本地文件：
```sh
# 1. 本地生成打包文件（如 bookmark-research-0.5.0-beta.19.tgz，不联网、不上传）
npm pack

# 2. 用本地压缩包模拟 npx 安装（需指定 --package 指向 tgz，后接二进制名 bookmark-research）
# npm 缓存若被其他用户创建过，先使用项目专用缓存，避免 npm-cache 权限干扰测试。
LOCAL_NPM_CACHE=/private/tmp/bookmark-research-npm-cache
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package ./bookmark-research-*.tgz bookmark-research install codex --non-interactive --json

# 或者测试交互模式
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package ./bookmark-research-*.tgz bookmark-research install
```
- **优势**：执行逻辑与线上 `npx bookmark-research install` 完全一致（包含 package 打包过滤、tarball 解压、软链注入和宿主注册）；
- **零成本**：纯本地运行，不污染 npm 线上版本库，无需等待 CDN 刷新，也不需要任何 2FA 登录验证。

##### 三宿主与 DSH Desktop/CLI 的本地验收

本地 tgz 必须分别验证三个宿主；DSH 的普通 CLI 和 Desktop CLI 是两个不同的安装目标，不能用一次 --profile 或一次 --dsh 路径代替。

~~~sh
LOCAL_NPM_CACHE=/private/tmp/bookmark-research-npm-cache
LOCAL_PACKAGE=./bookmark-research-0.6.5.tgz
CLI_PROFILE=web  # 替换为本机普通 DSH CLI 使用的 profile

# Codex
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research install codex --non-interactive --json

# Claude Code
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research install claude \
  --scope user --non-interactive --json

# 普通 DSH CLI：profile 名由 DSH 配置决定；需要 PATH 中可用的 dsh 和 pnpm。
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research install dsh \
  --profile "$CLI_PROFILE" --non-interactive --json

# DeepSeek Harness Desktop：必须使用桌面版自带 CLI 和保留的 desktop profile。
# macOS 路径如下；Windows/Linux 按本机 Desktop 安装位置替换。
DSH_DESKTOP_CLI="/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh"
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research install dsh \
  --dsh "$DSH_DESKTOP_CLI" --profile desktop --non-interactive --json
~~~

验收 JSON 必须逐项检查 host、profile、version、installed_path 和 verified；DSH Desktop 的 target 应为 desktop，并且使用桌面版 CLI。普通 DSH 的 profile 可以是已有名称或明确指定的新名称，不能把 desktop 交给 PATH 中的通用 CLI。

本地包测试新构建时使用 install：它会把当前运行的 tarball 保留为干净来源，并在已有目标上执行覆盖安装。update 继续使用目标收据中已登记的来源，适合验证已发布 npm、Git 或已登记本地来源的后续更新；不要用旧收据的 update 来判断一个全新的本地 tarball 是否已经被安装。

如果要测试已登记来源的升级，分别运行对应目标并确认版本：

~~~sh
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research update dsh \
  --profile "$CLI_PROFILE" --json
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research update dsh \
  --dsh "$DSH_DESKTOP_CLI" --profile desktop --json

npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research verify dsh \
  --profile "$CLI_PROFILE" --json
npm_config_cache="$LOCAL_NPM_CACHE" npx --yes --package "$LOCAL_PACKAGE" bookmark-research verify dsh \
  --dsh "$DSH_DESKTOP_CLI" --profile desktop --json
~~~

升级后必须重新打开对应宿主，并用同一个 profile 和同一个实际 CLI 跑 verify；只看到 Updated 或只检查安装器退出码不算通过。

#### 方法三：本地全量自动化单测
每次修改代码后必须运行全量单测，确保测试全部通过：
```sh
python3 -B -m unittest discover -s tests -p "test_*.py"
```

---

## 2. 交互体验（TUI）设计规范

维护 `src/onboarding.py` 和 `src/tui.py` 时，必须遵循以下用户体验守则：

1. **按键提示必须显眼（避免回车误触）**：
   - 多选框必须在题目标题与底部同时醒目标注操作方式：
     `安装到哪些宿主？（空格 勾选/取消，回车 确认）`
     底部以高亮颜色显示：`[空格] 勾选/取消  [a] 全选/全不选  [回车] 确认`。
2. **严禁设计“死胡同”交互，必须支持退回（Back / Re-select）**：
   - 宿主参数配置步骤（如 Claude Scope、DSH Profile）必须提供 `← 返回重新选择宿主` 选项；
   - 最终“安装计划确认（Install now?）”若用户选 `No`，不能直接抛出异常崩溃退出，必须提供 `重新选择宿主与选项？` 让用户返回第一步。

---

## 3. 发布与版本管理规范（正式发布时使用）

只有在所有功能和交互在本地完全验证无误后，才可发起正式发布：

### 版本一致性同步
递增版本号时，必须严格保持以下三处完全一致：
1. `package.json` 中的 `"version"`
2. `.codex-plugin/plugin.json` 中的 `"version"`
3. `.agents/plugins/marketplace.json` 中的 `"version"`

### npm 发布策略
- 发布统一使用最新标签（`latest`）：
  ```sh
  npm publish --tag latest
  ```
- 确保 `latest` dist-tag 始终指向最新稳定发布版，让用户通过 `npx bookmark-research install` 默认拉取到最新构建。

---

## 4. npm 历史包管理与隐藏约定

如需下架或在 npm 页面隐藏混乱的历史测试版本：

1. **强制下架删除（`unpublish`）**：
   - 规则：仅适用于发布在 **72 小时以内** 的构建；
   - 命令：
     ```sh
     npm unpublish bookmark-research@<version> --force
     ```
   - 注意：下架后该版本号不可复用，需 2FA 授权确认。
2. **批量折叠标记废弃（`deprecate`）**：
   - 规则：适用于发布超过 72 小时或不想硬删除的所有历史旧包；
   - 命令：
     ```sh
     npm deprecate bookmark-research@"<0.5.0-beta.19" "已废弃，请使用最新版本"
     ```
   - 效果：npm 官网上历史旧包会被折叠标记为废弃，npm 客户端在安装和搜索时会自动忽略它们。
