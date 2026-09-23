#!/usr/bin/env bash
# Download the installer from Git, then use the selected client's native installer.

usage() {
  if [ "${install_language:-en}" = zh ]; then
    cat <<'EOF'
用法：bash install.sh [install|update|verify] [选项]

不带参数：终端中引导选择宿主、偏好和服务；无终端时兼容默认 Codex。
  install              安装或重新安装已登记的此 Git 仓库
  update               更新已登记的来源与 ref，并验证安装
  verify               检查安装、SQLite FTS5 与 MCP 工具

选项：
  --lang auto|en|zh     安装器语言；auto 按 LC_ALL、LC_MESSAGES、LANG 判断
  --host HOST          codex、claude、pi 或 dsh；可重复或用逗号指定多个
  --interactive        始终打开终端向导（也支持 curl | bash）
  --non-interactive    Agent/CI 模式，不提示输入；请显式指定 --host
  --preferences FILE  偏好 JSON 文件（不含 API Key）
  --skip-checks        安装后仅检查本地配置，不联网验证服务
  --test-retrieval     实际搜索与示例网页读取自检；使用检索额度
  --scope SCOPE        Claude/Pi：user（默认）、project；local 仅限 Claude
  --project PATH       project/local 作用域对应的项目目录
  --profile NAME       DSH 目标 profile；向导可询问，非交互时必填
  --install-dir PATH   非 Codex 宿主的持久包与安装记录根目录
  --claude/--pi/--dsh PATH  对应宿主 CLI 路径
  --ref TAG_OR_COMMIT   仅首次安装时选择 Git ref；默认 main
  --dry-run            预览安装或更新，不修改宿主登记
  --codex PATH         Codex CLI 路径；默认 codex
  --timeout SECONDS    每条宿主命令的超时秒数，1–300；默认 60
  -h, --help           显示帮助，不下载文件

需要 Bash、Git、Python 3.9+、SQLite FTS5 和所选宿主 CLI。
示例：bash install.sh install --host claude --scope user
      bash install.sh install --host dsh --profile web
      bash install.sh install --host claude,dsh --profile web
引导脚本会临时下载代码，--dry-run 也会下载。
已有登记保留其来源与 ref；update 不会自动升级固定 tag。
安装不依赖 GitHub Release 或 ZIP 附件。
EOF
    return
  fi
  cat <<'EOF'
Usage: bash install.sh [install|update|verify] [options]

No arguments: guide host, preferences and service setup in a terminal.
Without a terminal, the legacy default is Codex; agents should pass --host.
  install              Install, or reinstall a registration of this Git repository
  update               Refresh the existing source/ref and verify the installation
  verify               Check the installed runtime, SQLite FTS5, and MCP tools

Options:
  --lang auto|en|zh     Installer language; auto follows LC_ALL, LC_MESSAGES, LANG
  --host HOST          codex, claude, pi, or dsh; repeat or comma-separate
  --interactive        Always open the terminal wizard (also with curl | bash)
  --non-interactive    Agent/CI mode, without prompts; pass --host explicitly
  --preferences FILE  Preferences JSON file (no API keys)
  --skip-checks        Inspect local settings without service network checks
  --test-retrieval     Test sample search/read; uses retrieval quota
  --scope SCOPE        Claude/Pi: user (default), project; local is Claude-only
  --project PATH       Project directory for project/local scope
  --profile NAME       DSH target profile; required without the wizard
  --install-dir PATH   Persistent exports/receipts root for non-Codex hosts
  --claude/--pi/--dsh PATH  Corresponding client executable
  --ref TAG_OR_COMMIT   Select a Git ref on FIRST install; default: main
  --dry-run            Preview install/update without changing client registration
  --codex PATH         Codex CLI executable; default: codex
  --timeout SECONDS    Timeout for each native command, 1-300; default: 60
  -h, --help           Show this help without downloading anything

Requires Bash, Git, Python 3.9+ with SQLite FTS5, and the selected client CLI.
Examples: bash install.sh install --host claude --scope user
          bash install.sh install --host dsh --profile web
          bash install.sh install --host claude,dsh --profile web
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
      --lang|--codex|--ref|--timeout|--host|--scope|--project|--profile|--install-dir|--claude|--pi|--dsh|--preferences) value_for=$argument ;;
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
  claude_binary=claude
  pi_binary=pi
  dsh_binary=dsh
  hosts=()
  interaction=auto
  setup_options=()
  skip_checks=0
  test_retrieval=0
  profile=''
  host_options=()
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
      --interactive|--non-interactive)
        [ "$interaction" = auto ] || fail "$(message 'Choose only one interaction mode.' '只能选择一种交互模式。')"
        interaction=$1; setup_options+=("$1"); shift ;;
      --skip-checks) skip_checks=1; setup_options+=("$1"); shift ;;
      --test-retrieval) test_retrieval=1; setup_options+=("$1"); shift ;;
      --ref|--codex|--timeout|--host|--scope|--project|--profile|--install-dir|--claude|--pi|--dsh|--preferences)
        [ "$#" -ge 2 ] && [ -n "$2" ] || fail "$(message 'Missing value for' '选项缺少取值：') $1."
        case "$1" in
          --ref) ref=$2; explicit_ref=1 ;;
          --codex) codex_binary=$2 ;;
          --timeout) timeout=$2 ;;
          --host)
            IFS=, read -r -a requested_hosts <<<"$2"
            for requested_host in "${requested_hosts[@]}"; do
              case "$requested_host" in
                codex|claude|pi|dsh) ;;
                *) fail "$(message '--host must be codex, claude, pi, or dsh.' '--host 必须是 codex、claude、pi 或 dsh。')" ;;
              esac
              duplicate=0
              for existing_host in ${hosts[@]+"${hosts[@]}"}; do
                [ "$existing_host" != "$requested_host" ] || duplicate=1
              done
              [ "$duplicate" -eq 1 ] || hosts+=("$requested_host")
            done ;;
          --preferences)
            [ "$2" != - ] || fail "$(message '--preferences requires a JSON file path.' '--preferences 需要 JSON 文件路径。')"
            setup_options+=("$1" "$2") ;;
          --claude) claude_binary=$2; host_options+=("$1" "$2") ;;
          --pi) pi_binary=$2; host_options+=("$1" "$2") ;;
          --dsh) dsh_binary=$2; host_options+=("$1" "$2") ;;
          --profile) profile=$2; host_options+=("$1" "$2") ;;
          *) host_options+=("$1" "$2") ;;
        esac
        shift 2 ;;
      *) fail "$(message 'Unknown argument:' '未知参数：') $1. $(message 'Use --help for usage.' '用 --help 查看帮助。')" ;;
    esac
  done
  [ "$skip_checks" -eq 0 ] || [ "$test_retrieval" -eq 0 ] || fail "$(message '--skip-checks conflicts with --test-retrieval.' '--skip-checks 与 --test-retrieval 冲突。')"
  [ "$action" = install ] || [ "${#setup_options[@]}" -eq 0 ] || fail "$(message 'Guided setup options apply to install only; use cli.py setup to change preferences later.' '引导选项仅用于 install；安装后可运行 cli.py setup 修改偏好。')"
  guided=0
  if [ "$action" = install ] && [ "$dry_run" -eq 0 ]; then
    if [ "$interaction" = --interactive ] || { [ "$interaction" = auto ] && [ -t 2 ]; }; then guided=1; fi
  fi
  explicit_host=0
  [ "${#hosts[@]}" -eq 0 ] || explicit_host=1
  if [ "$explicit_host" -eq 0 ] && [ "$guided" -eq 0 ]; then hosts=(codex); fi
  binary_for() {
    case "$1" in
      codex) printf '%s' "$codex_binary" ;;
      claude) printf '%s' "$claude_binary" ;;
      pi) printf '%s' "$pi_binary" ;;
      dsh) printf '%s' "$dsh_binary" ;;
    esac
  }
  codex_selected=0
  other_selected=0
  for host in ${hosts[@]+"${hosts[@]}"}; do
    if [ "$host" = codex ]; then codex_selected=1; else other_selected=1; fi
    if [ "$host" = dsh ]; then
      [ "$guided" -eq 1 ] || [ -n "$profile" ] || fail "$(message 'DSH requires --profile NAME.' 'DSH 需要 --profile NAME。')"
    fi
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
  if [ "$guided" -eq 0 ]; then
    for host in "${hosts[@]}"; do
      client_binary=$(binary_for "$host")
      if ! command -v "$client_binary" >/dev/null 2>&1; then
        if [ "$host" = codex ]; then
          fail "$(message 'Codex CLI was not found; install it or pass --codex PATH. Other clients: --host claude, --host pi, or --host dsh --profile NAME. Guide: https://github.com/Browser-bookmark-hub/Bookmark-Research/blob/main/docs/installation.en.md' '未找到 Codex CLI；请安装或用 --codex PATH 指定。其他宿主请选择 --host claude、--host pi 或 --host dsh --profile NAME。说明：https://github.com/Browser-bookmark-hub/Bookmark-Research/blob/main/docs/installation.md')"
        fi
        fail "$(message 'Selected client CLI was not found:' '未找到所选宿主 CLI：') $host ($client_binary)."
      fi
    done
  elif [ "$explicit_host" -eq 0 ]; then
    # The wizard detects hosts itself; only stop early when none is available.
    found_client=0
    for host in codex claude pi dsh; do
      if command -v "$(binary_for "$host")" >/dev/null 2>&1; then found_client=1; fi
    done
    [ "$found_client" -eq 1 ] || fail "$(message 'No supported client CLI (codex, claude, pi, dsh) was found; install one or pass --codex/--claude/--pi/--dsh PATH.' '未找到任何受支持的宿主 CLI（codex、claude、pi、dsh）；请先安装，或用 --codex/--claude/--pi/--dsh PATH 指定。')"
  fi
  probe_host=guided
  if [ "$guided" -eq 0 ] && [ "$codex_selected" -eq 1 ]; then probe_host=codex; fi
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
if sys.argv[3] != "codex":
    sys.exit(0)
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
' "$codex_binary" "$timeout" "$probe_host" || fail "$(message 'Prerequisite check failed; see the diagnostic above.' '环境检查失败，详见上方诊断。')"

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
  if [ "$other_selected" -eq 1 ]; then
    [ -f "$temporary/scripts/host_install.py" ] || fail "$(message 'This Git ref predates multi-host installation. Choose a ref containing the host installer.' '该 Git ref 尚未提供多宿主安装，请选择包含宿主安装器的版本。')"
  fi
  if [ "${#setup_options[@]}" -gt 0 ]; then
    [ -f "$temporary/src/onboarding.py" ] || fail "$(message 'This Git ref predates guided setup; choose a newer ref or omit setup options.' '该 Git ref 尚无安装向导；请使用新版或移除向导选项。')"
  fi

  arguments=("$action" --codex "$codex_binary" --timeout "$timeout")
  if [ "$other_selected" -eq 1 ] || { [ "$explicit_host" -eq 1 ] && [ -f "$temporary/scripts/host_install.py" ]; }; then
    for host in "${hosts[@]}"; do arguments+=(--host "$host"); done
  fi
  if [ "${#host_options[@]}" -gt 0 ]; then arguments+=("${host_options[@]}"); fi
  if [ "${#setup_options[@]}" -gt 0 ]; then arguments+=("${setup_options[@]}"); fi
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
