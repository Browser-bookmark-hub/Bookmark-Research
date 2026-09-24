"""The `bookmark-research` command: install, configure, check and update from one entry."""

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

USAGE = """usage: bookmark-research [--lang auto|en|zh] [COMMAND] [ARGS...]

  (no command)          Open the menu in a terminal; print status JSON otherwise
  install [HOST...]     Install into hosts: codex, claude, pi, dsh (wizard when omitted)
  update [HOST...]      Update installed hosts (all when omitted)
  verify [HOST...]      Verify installed hosts (all when omitted)
  setup                 Preferences, services, hidden API-key entry and checks
  status                Installed hosts, preferences and key status as JSON
  config show|set       View or change preferences (set reads --input FILE or -)
  doctor                Check Python and SQLite FTS5

Other options are passed through, e.g. install claude dsh --profile web --non-interactive.
API keys are never accepted as arguments: use setup or environment variables.
"""


def install_home():
    data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))).expanduser()
    if not data.is_absolute():
        data = Path.home() / ".local/share"
    return Path(os.environ.get("BOOKMARK_RESEARCH_INSTALL_DIR", str(data / "bookmark-research/installations"))).expanduser()


def installed_targets(codex="codex"):
    """Read managed receipts and the Codex registry; never contacts a network service."""
    rows = []
    home = install_home()
    for receipt in sorted(home.glob("*/receipt.json")) if home.is_dir() else []:
        try:
            value = json.loads(receipt.read_text(encoding="utf-8"))
            target = value["target"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        rows.append({"host": target.get("host"), "scope": target.get("scope"), "project": target.get("project"),
                     "profile": target.get("profile"), "version": value.get("version"), "state": value.get("state")})
    try:
        from install import CodexCli, _installed
        import shutil
        if shutil.which(codex):
            plugin = _installed(CodexCli(codex, 30))
            if plugin:
                rows.insert(0, {"host": "codex", "scope": None, "project": None, "profile": None,
                                "version": plugin.get("version"), "state": "installed"})
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        pass
    return rows


def status():
    from credentials import Credentials
    from settings import Settings
    settings = Settings()
    current = settings.load()
    return {"hosts": installed_targets(),
            "preferences": {"depth": current["research"]["depth"], "language": current["research"]["response_language"],
                            "search": current["search"]["providers"], "fallback": current["search"]["fallback_providers"],
                            "readers": Settings.fetch_providers(current), "archive": current["archive"]["enabled"]},
            "credentials": {row["name"]: row["source"] or "missing" for row in Credentials(settings).describe()["credentials"]},
            "settings_path": str(settings.path)}


def _split(arguments):
    hosts, rest = [], []
    for index, value in enumerate(arguments):
        if value.startswith("-"):
            rest = arguments[index:]
            break
        hosts.extend(part for part in value.split(",") if part)
    return hosts, rest


def _install_action(action, arguments, language):
    import install
    hosts, rest = _split(arguments)
    if not hosts and action != "install" and "--host" not in rest:
        targets = installed_targets()
        if not targets:
            print(json.dumps({"error": "Nothing is installed yet; run bookmark-research install"}), file=sys.stderr)
            return 1
        codes = []
        for row in targets:
            extra = ["--host", row["host"]]
            for key in ("scope", "project", "profile"):
                if row.get(key):
                    extra += ["--" + key, row[key]]
            codes.append(install.main([action, "--lang", language, *extra, *rest]))
        return max(codes)
    return install.main([action, "--lang", language, *[item for host in hosts for item in ("--host", host)], *rest])


def _cli(arguments, language):
    command = [sys.executable, str(ROOT / "src/cli.py"), *arguments]
    if arguments and arguments[0] == "setup" and "--lang" not in arguments:
        command += ["--lang", language]
    return subprocess.call(command)


def run(arguments, language):
    if not arguments:
        return menu(language)
    command, rest = arguments[0], arguments[1:]
    if command in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if command in ("install", "update", "verify"):
        return _install_action(command, rest, language)
    if command == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0
    if command in ("setup", "config", "doctor"):
        return _cli([command, *rest], language)
    print(USAGE, file=sys.stderr)
    return 2


def menu(language):
    from onboarding import Console
    with Console.open("auto", Console.resolve_language(language)) as console:
        if console is None:
            print(json.dumps(status(), ensure_ascii=False, indent=2))
            return 0
        console.intro("Bookmark Research", "Bookmark Research")
        while True:
            current = status()
            hosts = ", ".join(row["host"] + ("(" + (row["profile"] or row["scope"] or "") + ")" if row["profile"] or row["scope"] else "")
                              for row in current["hosts"]) or console.text("none", "无")
            missing = [name.split("_")[0].lower() for name, source in current["credentials"].items() if source == "missing"]
            console.say("Installed: " + hosts, "已安装：" + hosts)
            console.say("Search: " + ", ".join(current["preferences"]["search"]) + ("  · keys missing: " + ", ".join(missing) if missing else ""),
                        "搜索服务：" + ", ".join(current["preferences"]["search"]) + ("  · 未配置密钥：" + ", ".join(missing) if missing else ""))
            choice = console.select("What would you like to do?", "要做什么？", _menu_options(), "setup")
            if choice == "exit":
                console.outro("Bye.", "再见。")
                return 0
            code = {"setup": lambda: _cli(["setup"], console.language),
                    "check": lambda: _cli(["setup", "--non-interactive"], console.language),
                    "install": lambda: _install_action("install", ["--interactive"], console.language),
                    "update": lambda: _install_action("update", [], console.language),
                    "status": lambda: print(json.dumps(status(), ensure_ascii=False, indent=2)) or 0}[choice]()
            if code:
                console.warn("Finished with exit code %s." % code, "结束，退出码 %s。" % code)


def _menu_options():
    from tui import Option
    return [Option("setup", "Change preferences and API keys", "修改配置与 API Key"),
            Option("check", "Check services", "检查服务是否可用"),
            Option("install", "Install into another host", "安装到其他宿主"),
            Option("update", "Update installed hosts", "更新已安装宿主"),
            Option("status", "Show status JSON", "查看状态（JSON）"),
            Option("exit", "Exit", "退出")]


def main(argv=None):
    from textio import utf8_stdio
    utf8_stdio()
    arguments = list(sys.argv[1:] if argv is None else argv)
    language = "auto"
    if arguments[:1] == ["--lang"] and len(arguments) > 1:
        language, arguments = arguments[1], arguments[2:]
    elif arguments and arguments[0].startswith("--lang="):
        language, arguments = arguments[0].split("=", 1)[1], arguments[1:]
    if language not in ("auto", "en", "zh"):
        print("--lang must be auto, en or zh", file=sys.stderr)
        return 2
    from install import resolve_language
    try:
        return run(arguments, resolve_language(language))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
