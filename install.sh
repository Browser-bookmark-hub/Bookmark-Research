#!/usr/bin/env bash
# Download the installer from Git, then let Codex own the installed source/cache.

usage() {
  if [ "${install_language:-en}" = zh ]; then
    cat <<'EOF'
用法：bash install.sh [install|update|verify] [选项]

不带参数：从默认分支 main 安装 Bookmark Research 到 Codex。
  install              安装或重新安装已登记的此 Git 仓库
  update               更新已登记的来源与 ref，并验证安装
  verify               检查安装、SQLite FTS5 与 MCP 工具

选项：
  --lang auto|en|zh     安装器语言；auto 按 LC_ALL、LC_MESSAGES、LANG 判断
  --ref TAG_OR_COMMIT   仅首次安装时选择 Git ref；默认 main
  --dry-run            预览安装或更新，不修改 Codex
  --codex PATH         Codex CLI 路径；默认 codex
  --timeout SECONDS    每条 Codex 命令的超时秒数，1–300；默认 60
  -h, --help           显示帮助，不下载文件

需要 Bash、Git、Python 3.9+、SQLite FTS5 和支持插件的 Codex CLI。
引导脚本会临时下载代码，--dry-run 也会下载。
已有登记保留其来源与 ref；update 不会自动升级固定 tag。
安装不依赖 GitHub Release 或 ZIP 附件。
EOF
    return
  fi
  cat <<'EOF'
Usage: bash install.sh [install|update|verify] [options]

No arguments: install Bookmark Research in Codex from the default branch (main).
  install              Install, or reinstall a registration of this Git repository
  update               Refresh the existing source/ref and verify the installation
  verify               Check the installed runtime, SQLite FTS5, and MCP tools

Options:
  --lang auto|en|zh     Installer language; auto follows LC_ALL, LC_MESSAGES, LANG
  --ref TAG_OR_COMMIT   Select a Git ref on FIRST install; default: main
  --dry-run            Print the install/update plan without changing Codex
  --codex PATH         Codex CLI executable; default: codex
  --timeout SECONDS    Timeout for each Codex command, 1-300; default: 60
  -h, --help           Show this help without downloading anything

Requires Bash, Git, Python 3.9+ with SQLite FTS5, and Codex CLI with plugin support.
The bootstrap downloads code to a temporary directory, even with --dry-run.
Existing registrations retain their source/ref; update does not advance a tag.
GitHub Release pages and ZIP assets are not used.
EOF
}

message() {
  if [ "${install_language:-en}" = zh ]; then printf '%s' "$2"; else printf '%s' "$1"; fi
}

fail() {
  printf 'Bookmark Research: %s\n' "$*" >&2
  exit 1
}

# A single final invocation keeps a partially downloaded function body inert.
main() (
  set -euo pipefail
  # Inspect --lang before --help so either flag order displays the chosen copy.
  requested_language=auto
  value_for=''
  for argument in "$@"; do
    if [ -n "$value_for" ]; then
      if [ "$value_for" = --lang ]; then requested_language=$argument; fi
      value_for=''
      continue
    fi
    case "$argument" in
      --lang|--codex|--ref|--timeout) value_for=$argument ;;
      --lang=*) requested_language=${argument#--lang=} ;;
    esac
  done
  case "${BOOKMARK_RESEARCH_INSTALL_LANG:-auto}" in
    en|zh) install_language=$BOOKMARK_RESEARCH_INSTALL_LANG ;;
    *) case "${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}" in
         [zZ][hH]*) install_language=zh ;; *) install_language=en ;;
       esac ;;
  esac
  case "$requested_language" in
    en|zh) install_language=$requested_language ;;
    auto) ;;
    *) fail "$(message '--lang must be auto, en, or zh.' '--lang 必须是 auto、en 或 zh。')" ;;
  esac
  action=install
  repository=https://github.com/Browser-bookmark-hub/Bookmark-Research.git
  ref=main
  explicit_ref=0
  codex_binary=codex
  dry_run=0
  timeout=60
  case "${1:-}" in
    install|update|verify) action=$1; shift ;;
  esac
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -h|--help) usage; exit 0 ;;
      --lang)
        [ "$#" -ge 2 ] && [ -n "$2" ] || fail "$(message 'Missing value for --lang.' '--lang 缺少取值。')"
        shift 2 ;;
      --lang=*) shift ;;
      --dry-run) dry_run=1; shift ;;
      --ref|--codex|--timeout)
        [ "$#" -ge 2 ] && [ -n "$2" ] || fail "$(message 'Missing value for' '选项缺少取值：') $1."
        case "$1" in
          --ref) ref=$2; explicit_ref=1 ;;
          --codex) codex_binary=$2 ;;
          --timeout) timeout=$2 ;;
        esac
        shift 2 ;;
      *) fail "$(message 'Unknown argument:' '未知参数：') $1. $(message 'Use --help for usage.' '用 --help 查看帮助。')" ;;
    esac
  done
  if [ "$explicit_ref" -eq 1 ]; then
    [ "$action" = install ] || fail "$(message '--ref is only for the first install; update retains the registered ref.' '--ref 仅用于首次安装；update 沿用已登记的 ref。')"
    case "$ref" in
      -*|*[!A-Za-z0-9_./-]*) fail "$(message 'Invalid Git ref:' '无效 Git ref：') $ref." ;;
    esac
  fi
  [ "$action" != verify ] || [ "$dry_run" -eq 0 ] || fail "$(message '--dry-run is only for install or update.' '--dry-run 仅用于 install 或 update。')"
  case "$timeout" in
    *[!0-9]*|????*) fail "$(message '--timeout must be between 1 and 300.' '--timeout 必须在 1 到 300 之间。')" ;;
  esac
  [ "$((10#$timeout))" -ge 1 ] && [ "$((10#$timeout))" -le 300 ] || fail "$(message '--timeout must be between 1 and 300.' '--timeout 必须在 1 到 300 之间。')"
  command -v git >/dev/null 2>&1 || fail "$(message 'Install Git and make it available on PATH.' '请安装 Git 并加入 PATH。')"
  command -v python3 >/dev/null 2>&1 || fail "$(message 'Install Python 3.9+ as python3 on PATH.' '请安装 Python 3.9+，确保 PATH 中可运行 python3。')"
  command -v "$codex_binary" >/dev/null 2>&1 || fail "$(message 'Codex CLI was not found; install it or pass --codex PATH.' '未找到 Codex CLI；请安装或用 --codex PATH 指定。')"
  python3 -B -c '
import json
import subprocess
import sys
if sys.version_info < (3, 9):
    sys.exit("Bookmark Research requires Python 3.9+.")
try:
    import sqlite3
except ImportError as error:
    sys.exit("Bookmark Research requires SQLite: " + str(error))
try:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(content)")
except sqlite3.Error as error:
    sys.exit("Bookmark Research requires SQLite FTS5: " + str(error))
try:
    result = subprocess.run([sys.argv[1], "plugin", "list", "--json"],
                            capture_output=True, text=True, timeout=int(sys.argv[2]))
    if result.returncode:
        sys.exit("Codex plugin list failed: " + (result.stderr or result.stdout).strip()[-2000:])
    installed = json.loads(result.stdout)["installed"]
    if not isinstance(installed, list) or any(not isinstance(row, dict) for row in installed):
        raise ValueError("Unexpected installed plugin list")
    others = [row["pluginId"] for row in installed if row.get("installed")
              and isinstance(row.get("pluginId"), str)
              and row["pluginId"].startswith("bookmark-research@")
              and row["pluginId"] != "bookmark-research@bookmark-research"]
    if others:
        sys.exit("Already installed as " + ", ".join(others)
                 + ". Use the existing marketplace update flow, or explicitly choose one source in Codex first.")
except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
    sys.exit("Codex must support plugin list --json: " + str(error))
' "$codex_binary" "$timeout" || fail "$(message 'Prerequisite check failed; see the diagnostic above.' '环境检查失败，详见上方诊断。')"

  temporary=$(mktemp -d "${TMPDIR:-/tmp}/bookmark-research-install.XXXXXXXX")
  trap 'rm -rf -- "$temporary"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  printf 'Bookmark Research: %s (%s).\n' "$(message 'fetching installer from Git' '正在从 Git 获取安装器')" "$ref" >&2
  git -C "$temporary" init --quiet
  git -C "$temporary" remote add origin "$repository"
  GIT_TERMINAL_PROMPT=0 git -C "$temporary" fetch --quiet --depth 1 origin "$ref" </dev/null || fail "$(message 'Could not fetch the installer from Git.' '无法从 Git 获取安装器。')"
  git -C "$temporary" checkout --quiet --detach FETCH_HEAD
  [ -f "$temporary/scripts/install.py" ] && [ -f "$temporary/scripts/export_bundle.py" ] || fail "$(message 'This Git ref has no installer; choose v0.2.0 or a later ref.' '该 Git ref 不含安装器，请选择 v0.2.0 或后续版本。')"

  arguments=("$action" --codex "$codex_binary" --timeout "$timeout")
  if [ "$action" = install ]; then
    # Never register the disposable checkout as a local marketplace.
    arguments+=(--source "$repository")
    [ "$explicit_ref" -eq 0 ] || arguments+=(--ref "$ref")
  fi
  [ "$dry_run" -eq 0 ] || arguments+=(--dry-run)
  # Older pinned installers ignore this environment hint, preserving their CLI contract.
  BOOKMARK_RESEARCH_INSTALL_LANG="$install_language" python3 -B "$temporary/scripts/install.py" "${arguments[@]}" </dev/null
)

main "$@"
