#!/usr/bin/env bash
# Download the installer from Git, then let Codex own the installed source/cache.

usage() {
  cat <<'EOF'
Usage: bash install.sh [install|update|verify] [options]

No arguments: install Bookmark Research in Codex from the default branch (main).
  install              Install, or reinstall a registration of this Git repository
  update               Refresh the existing source/ref and verify the installation
  verify               Check the installed runtime, SQLite FTS5, and MCP tools

Options:
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

fail() {
  printf 'Bookmark Research: %s\n' "$*" >&2
  exit 1
}

# A single final invocation keeps a partially downloaded function body inert.
main() (
  set -euo pipefail
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
      --dry-run) dry_run=1; shift ;;
      --ref|--codex|--timeout)
        [ "$#" -ge 2 ] && [ -n "$2" ] || fail "Missing value for $1."
        case "$1" in
          --ref) ref=$2; explicit_ref=1 ;;
          --codex) codex_binary=$2 ;;
          --timeout) timeout=$2 ;;
        esac
        shift 2 ;;
      *) fail "Unknown argument: $1. Use --help for usage." ;;
    esac
  done
  if [ "$explicit_ref" -eq 1 ]; then
    [ "$action" = install ] || fail "--ref is only for the first install; update retains the registered ref."
    case "$ref" in
      -*|*[!A-Za-z0-9_./-]*) fail "Invalid Git ref: $ref." ;;
    esac
  fi
  [ "$action" != verify ] || [ "$dry_run" -eq 0 ] || fail "--dry-run is only for install or update."
  case "$timeout" in
    *[!0-9]*|????*) fail "--timeout must be between 1 and 300." ;;
  esac
  [ "$((10#$timeout))" -ge 1 ] && [ "$((10#$timeout))" -le 300 ] || fail "--timeout must be between 1 and 300."
  command -v git >/dev/null 2>&1 || fail "Install Git and make it available on PATH."
  command -v python3 >/dev/null 2>&1 || fail "Install Python 3.9+ as python3 on PATH."
  command -v "$codex_binary" >/dev/null 2>&1 || fail "Codex CLI was not found; install it or pass --codex PATH."
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
' "$codex_binary" "$timeout" || fail "Prerequisite check failed."

  temporary=$(mktemp -d "${TMPDIR:-/tmp}/bookmark-research-install.XXXXXXXX")
  trap 'rm -rf -- "$temporary"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  printf 'Bookmark Research: fetching installer from Git (%s).\n' "$ref" >&2
  git -C "$temporary" init --quiet
  git -C "$temporary" remote add origin "$repository"
  GIT_TERMINAL_PROMPT=0 git -C "$temporary" fetch --quiet --depth 1 origin "$ref" </dev/null || fail "Could not fetch the installer from Git."
  git -C "$temporary" checkout --quiet --detach FETCH_HEAD
  [ -f "$temporary/scripts/install.py" ] && [ -f "$temporary/scripts/export_bundle.py" ] || fail "This Git ref has no installer; choose v0.2.0 or a later ref."

  arguments=("$action" --codex "$codex_binary" --timeout "$timeout")
  if [ "$action" = install ]; then
    # Never register the disposable checkout as a local marketplace.
    arguments+=(--source "$repository")
    [ "$explicit_ref" -eq 0 ] || arguments+=(--ref "$ref")
  fi
  [ "$dry_run" -eq 0 ] || arguments+=(--dry-run)
  python3 -B "$temporary/scripts/install.py" "${arguments[@]}" </dev/null
)

main "$@"
