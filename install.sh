#!/usr/bin/env bash
# All supported hosts use the npm release and the same installer.
main() (
  set -euo pipefail
  language=${BOOKMARK_RESEARCH_INSTALL_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}}
  previous=''
  for argument in "$@"; do
    if [ "$previous" = --lang ]; then language=$argument; fi
    case "$argument" in --lang=*) language=${argument#--lang=} ;; esac
    previous=$argument
  done
  if [ "$language" = auto ]; then language=${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}; fi
  for argument in "$@"; do
    case "$argument" in
      -h|--help)
        case "$language" in
          [zZ][hH]*) cat <<'HELP'
用法：bash install.sh [install|update|verify] [选项]

四个宿主统一使用 npm 发布包，由各宿主原生命令登记。
  --host HOST           codex、claude、pi、dsh；可重复或逗号分隔
  --lang auto|en|zh      安装器语言
  --interactive         打开终端向导
  --non-interactive     不提示输入；请指定 --host
  --profile NAME        DSH 目标 profile
  --scope SCOPE         Claude/Pi 的安装作用域
  --project PATH        项目目录
  --source npm:bookmark-research@VERSION  固定插件版本
  --dry-run             预览，不修改宿主登记
其他参数原样传给 bookmark-research；完整选项见 npm 命令的 install --help。
需要 Node.js/npm、Python 3.9+（SQLite FTS5）及所选宿主。
GitHub 提供此入口脚本，安装内容来自 npm；--help 不下载。
开发源码使用 python3 scripts/install.py install --source PATH。
HELP
          ;;
          *) cat <<'HELP'
Usage: bash install.sh [install|update|verify] [options]

All four hosts use the npm release and their native registration commands.
  --host HOST           codex, claude, pi, dsh; repeat or comma-separate
  --lang auto|en|zh      Installer language
  --interactive         Open the terminal wizard
  --non-interactive     No prompts; specify --host
  --profile NAME        DSH profile
  --scope SCOPE         Claude/Pi installation scope
  --project PATH        Project directory
  --source npm:bookmark-research@VERSION  Pin the plugin version
  --dry-run             Preview without changing host registration
Other arguments pass through; see the npm command's install --help for all options.
Requires Node.js/npm, Python 3.9+ (SQLite FTS5), and the selected host.
GitHub serves this script; plugin files come from npm. --help stays offline.
For source development: python3 scripts/install.py install --source PATH.
HELP
          ;;
        esac
        exit 0 ;;
    esac
  done
  if ! command -v npx >/dev/null 2>&1; then
    printf '%s\n' 'Bookmark Research: install Node.js/npm so npx is available on PATH.' >&2
    exit 1
  fi
  case "${1:-}" in
    install|update|verify) ;;
    *) set -- install "$@" ;;
  esac
  # npm owns downloading/caching. The release installer records npm selectors,
  # and each client owns its own configuration and installed plugin cache.
  npx --yes --registry=https://registry.npmjs.org --package=bookmark-research@latest bookmark-research "$@" </dev/null
)
main "$@"
