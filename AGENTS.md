# Bookmark Research — Agent 指导规范与开发约定

本文档供维护本项目的所有 AI 代理（包括 Codex、Claude Code、DeepSeek Harness、Antigravity 等）及开发者参考。修改代码、执行测试或准备发布时，必须严格遵守以下约定。

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

# 2. 用本地压缩包模拟 npx 安装
npx ./bookmark-research-*.tgz install codex --non-interactive

# 或者测试交互模式
npx ./bookmark-research-*.tgz install
```
- **优势**：执行逻辑与线上 `npx bookmark-research install` 完全一致（包含 package 打包过滤、tarball 解压、软链注入和宿主注册）；
- **零成本**：纯本地运行，不污染 npm 线上版本库，无需等待 CDN 刷新，也不需要任何 2FA 登录验证。

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
