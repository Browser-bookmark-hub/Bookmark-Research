#!/usr/bin/env python3
"""Install, update, or verify Bookmark Research with a selected client's native CLI."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from export_bundle import NAME, SOURCE_ROOT, _copy_plan, read_plugin_manifest
from host_assets import read_asset


SELECTOR = NAME + "@" + NAME
CODEX_HOST_FILES = (
    "hosts/codex/delegate.md",
    "hosts/codex/prepare.py",
    "hosts/shared/research-call.py",
)


def resolve_language(language="auto", environment=None):
    """Choose installer copy without changing the process locale or user settings."""
    if language not in ("auto", "en", "zh"):
        raise ValueError("--lang must be auto, en, or zh")
    if language != "auto":
        return language
    environment = os.environ if environment is None else environment
    forwarded = environment.get("BOOKMARK_RESEARCH_INSTALL_LANG")
    if forwarded in ("en", "zh"):
        return forwarded
    locale = next((environment.get(key) for key in ("LC_ALL", "LC_MESSAGES", "LANG")
                   if environment.get(key)), "en")
    return "zh" if locale.lower().startswith("zh") else "en"


def _message(language, english, chinese):
    return chinese if language == "zh" else english


class CodexCli:
    def __init__(self, binary="codex", timeout=60):
        self.binary = binary
        self.timeout = timeout

    def run(self, arguments):
        command = [self.binary, *arguments, "--json"]
        result = subprocess.run(command, text=True, capture_output=True, timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("Codex command failed: " + " ".join(arguments[:3])
                               + "\n" + (result.stderr or result.stdout).strip()[-4000:])
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("Codex must support plugin commands with --json; update Codex CLI") from error
        if not isinstance(value, dict):
            raise RuntimeError("Unexpected Codex JSON response")
        return value


def _marketplace(cli):
    value = cli.run(["plugin", "marketplace", "list"])
    entries = value.get("marketplaces")
    if not isinstance(entries, list):
        raise RuntimeError("Codex did not return a marketplaces array")
    matches = [row for row in entries if row.get("name") == NAME]
    if len(matches) > 1:
        raise ValueError("Multiple bookmark-research marketplaces are in scope; resolve their names first")
    return matches[0] if matches else None


def _installed(cli):
    value = cli.run(["plugin", "list"])
    entries = value.get("installed")
    if not isinstance(entries, list):
        raise RuntimeError("Codex did not return an installed plugins array")
    return next((row for row in entries if row.get("pluginId") == SELECTOR), None)


def _repository(value):
    """Normalize public GitHub shorthand while preserving other Git sources."""
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        return "https://github.com/" + value.removesuffix(".git") + ".git"
    if value.startswith(("https://", "http://", "ssh://")):
        parsed = urlsplit(value)
        if parsed.password or parsed.query or parsed.fragment or (parsed.username and parsed.scheme != "ssh"):
            raise ValueError("Use a Git URL without credentials, query parameters, or fragments")
        if not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError("Invalid Git repository URL")
        return value.rstrip("/").removesuffix(".git") + ".git"
    if re.fullmatch(r"git@[^\s:]+:[^\s]+", value):
        return value.removesuffix(".git") + ".git"
    raise ValueError("Source must be a local marketplace root, owner/repo, or a Git URL")


def _source(value, ref=None):
    value = str(value)
    if not value or any(ord(char) < 32 for char in value):
        raise ValueError("Source must be a nonempty path or Git repository")
    path = Path(value).expanduser()
    if path.exists() or value.startswith(("/", "./", "../", "~", ".\\", "..\\")):
        if ref:
            raise ValueError("--ref only applies to a Git marketplace; checkout local sources yourself")
        root = path.resolve()
        manifest = read_plugin_manifest(root)
        _copy_plan(root)
        for relative in CODEX_HOST_FILES:
            read_asset(root, relative)
        marketplace_path = root / ".agents/plugins/marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        if not isinstance(marketplace, dict) or marketplace.get("name") != NAME:
            raise ValueError("The local marketplace must be named bookmark-research")
        plugin = next((entry for entry in marketplace.get("plugins", []) if entry.get("name") == NAME), None)
        if not plugin or plugin.get("source") != {"source": "local", "path": "./"}:
            raise ValueError("The local marketplace must point bookmark-research at its root (./)")
        return {"sourceType": "local", "source": str(root), "version": manifest["version"]}
    if ref and (ref.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./-]+", ref)):
        raise ValueError("--ref must be a Git branch, tag, or commit identifier")
    return {"sourceType": "git", "source": _repository(value), "ref": ref}


def _configured_source(marketplace):
    source = marketplace.get("marketplaceSource")
    if source is None:
        return {"sourceType": "local", "source": str(Path(marketplace["root"]).resolve())}
    if not isinstance(source, dict) or source.get("sourceType") not in ("local", "git"):
        raise RuntimeError("Unsupported Codex marketplace source metadata")
    return source


def _check_source(marketplace, requested):
    current = _configured_source(marketplace)
    if current["sourceType"] == requested["sourceType"] == "local":
        equal = Path(current["source"]).resolve() == Path(requested["source"]).resolve()
    elif current["sourceType"] == requested["sourceType"] == "git":
        equal = _repository(current["source"]) == requested["source"]
    else:
        equal = False
    if not equal:
        raise ValueError("Marketplace bookmark-research already uses a different source: "
                         + current["source"] + ". Keep it and run update, or explicitly resolve the source in Codex first.")


def _cached_path(installed):
    version = installed.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9.+_-]+", version):
        raise RuntimeError("Codex did not return a valid installed version")
    profile = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    return (profile / "plugins/cache" / NAME / NAME / version).resolve()


def _runtime_check(root, timeout=30):
    manifest = read_plugin_manifest(root)
    for relative in CODEX_HOST_FILES:
        read_asset(root, relative)
    command = [sys.executable, "-B", str(root / "src/cli.py"), "doctor"]
    doctor = subprocess.run(command, cwd=root.parent, text=True, capture_output=True, timeout=timeout)
    if doctor.returncode:
        raise RuntimeError("Installed runtime doctor failed: " + doctor.stderr.strip()[-2000:])
    health = json.loads(doctor.stdout)
    if health.get("fts5") is not True:
        raise RuntimeError("Installed runtime requires SQLite FTS5")
    server = manifest.get("mcpServers", {}).get(NAME, {})
    if server.get("command") != "python3" or server.get("args") != ["src/cli.py", "serve"] or server.get("cwd") != ".":
        raise ValueError("Unexpected native MCP launch configuration; verify it with Codex directly")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "bookmark-research-installer", "version": manifest["version"]}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    # Startup now monitors registered live sources. Tool discovery during an
    # installation check must use an empty store, not start syncing user data.
    with tempfile.TemporaryDirectory(prefix="bookmark-runtime-check-") as probe_data:
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", BOOKMARK_RESEARCH_DATA_DIR=probe_data)
        mcp = subprocess.run([server["command"], *server["args"]], cwd=root,
                             input="\n".join(json.dumps(row) for row in requests) + "\n",
                             text=True, capture_output=True, timeout=timeout, env=environment)
        if (Path(probe_data) / "index.sqlite3").exists():
            raise RuntimeError("MCP discovery unexpectedly created a database")
    if mcp.returncode:
        raise RuntimeError("Installed MCP startup failed: " + mcp.stderr.strip()[-2000:])
    responses = {row.get("id"): row for row in (json.loads(line) for line in mcp.stdout.splitlines())}
    tools = responses.get(2, {}).get("result", {}).get("tools", [])
    names = sorted(row["name"] for row in tools)
    if not {"search_bookmarks", "search_web", "fetch_web"} <= set(names):
        raise RuntimeError("Installed MCP did not expose the expected bookmark and research tools")
    if "result" not in responses.get(1, {}):
        raise RuntimeError("Installed MCP initialization failed")
    return {"doctor": health, "mcp_protocol": responses[1]["result"]["protocolVersion"],
            "mcp_tools": names, "network_checked": False, "database_created": False}


def verify(cli, installed_path=None):
    installed = _installed(cli)
    if not installed or not installed.get("installed") or not installed.get("enabled"):
        raise ValueError("bookmark-research is not installed and enabled in this Codex profile")
    root = Path(installed_path).expanduser().resolve() if installed_path else _cached_path(installed)
    if not root.is_dir():
        raise ValueError("Installed cache not found; pass --installed-path from codex plugin add --json")
    manifest = read_plugin_manifest(root)
    if manifest["version"] != installed.get("version"):
        raise ValueError("Installed cache version differs from Codex plugin list")
    runtime = _runtime_check(root, timeout=cli.timeout)
    return {"plugin": SELECTOR, "version": manifest["version"], "installed_path": str(root),
            "installed": True, "enabled": True, "verified": True, "runtime": runtime}


def _getting_started(installed_path, timeout=30, language="auto"):
    """Read the installed runtime's preferences without initializing user data."""
    language = resolve_language(language)
    message = lambda english, chinese: _message(language, english, chinese)
    command = [sys.executable, "-B", str(Path(installed_path) / "src/cli.py"), "config", "show"]
    guide = {
        "language": language,
        "first_prompt": message(
            'Use Bookmark Research to read my canvas package at "/absolute/path/to/my-canvas-package". '
            'First list its sections, folders, and bookmark counts offline.',
            '用 Bookmark Research 读取我的书签画布包 "/absolute/path/to/my-canvas-package"，先离线列出栏目、文件夹和书签数量。'),
        "settings_command": command,
        "guide_url": "https://github.com/Browser-bookmark-hub/Bookmark-Research/blob/main/docs/" + message(
            "installation.en.md#first-use-and-data-locations", "installation.md#首次使用与数据位置"),
        "configuration": None, "configuration_summary": [], "configuration_error": None,
    }
    try:
        checked = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
        if checked.returncode:
            raise ValueError("Installed config show failed")
        configuration = json.loads(checked.stdout)
        settings = configuration["settings"]
        summary = [
            message("Settings: ", "配置：") + (message("using saved preferences", "沿用已保存的设置")
                if configuration["config_exists"] else message("using defaults; no config file is required", "使用默认值，无需先创建配置文件")),
            message("Search: %s; %s results per target", "搜索：%s；每目标 %s 条结果") % (
                " + ".join(settings["search"]["providers"]), settings["search"]["limit_per_target"]),
            message("Page reading: %s; length parameter %s characters; timeout %s seconds", "正文读取：%s；长度参数 %s 字符；超时 %s 秒") % (
                settings["fetch"]["provider"], settings["fetch"]["max_characters"], settings["timeout_seconds"]),
            message("Archive ordinary page reads: ", "普通网页读取自动归档：") + (
                message("enabled", "开启") if settings["archive"]["enabled"] else message("disabled", "关闭")),
            message("Archive directory: ", "归档目录：") + settings["archive"]["directory"],
            message("Config file: ", "配置文件：") + configuration["config_path"],
        ]
        guide.update(configuration=configuration, configuration_summary=summary)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        # Installation is already verified. Keep an unreadable existing config
        # intact, and avoid exposing its contents or replacing it with defaults.
        guide["configuration_error"] = message(
            "Could not read existing settings. Run the config command below to diagnose and fix the file; the original was preserved.",
            "现有配置读取失败。请运行下方配置查询命令查看原因并修正文件；原文件已保留。")
    return guide


def _print_getting_started(guide):
    language = resolve_language(guide.get("language", "auto"))
    message = lambda english, chinese: _message(language, english, chinese)
    lines = ["", message("Bookmark Research installed; runtime checks passed.", "Bookmark Research 安装完成，运行检查已通过。")]
    if guide["configuration_error"]:
        lines.extend([guide["configuration_error"], message("After fixing the configuration, start here:", "配置修正后，按以下步骤开始：")])
    else:
        lines.extend(guide["configuration_summary"])
    lines.extend([
        "", message("Next steps:", "下一步："),
        (message("1. Start a new Codex thread to load the plugin.", "1. 在 Codex 新建对话，让客户端加载插件。")
         if guide.get("host", "codex") == "codex" else message(
             "1. Restart %s to load the Skill and tools.", "1. 重启 %s 以加载 Skill 和工具。") % guide["host"]),
        message("2. Prepare your Bookmark Canvas directory, ZIP, or single-card JSON. Replace the path below and send:",
                "2. 准备自己的 Bookmark Canvas 目录、ZIP 或单卡 JSON，把下面的占位路径换成实际路径后发送："),
        "   " + guide["first_prompt"],
        message("   Manual exports become snapshots. For automatic local updates, identify a persistent live directory.",
                "   手动导出会保存为快照；需要自动更新时，说明这是持续同步目录。"),
        message("3. For web-only research, provide a topic directly. Research uses the current host model; no extra model address is required.",
                "3. 只做网页研究时可直接提出主题，无需先导入书签。研究使用当前对话的模型，无需另填模型名称或地址。"),
        "", message("Local queries require no API key. Web access depends on the selected provider's authentication and limits.",
                    "本地书签查询不需要 API Key。网页研究使用所选服务，匿名额度和认证要求由服务方决定。"),
        message("When needed, set EXA_API_KEY, PARALLEL_API_KEY, or TAVILY_API_KEY in the environment that launches the client.",
                "需要密钥时，在启动客户端的环境中配置 EXA_API_KEY、PARALLEL_API_KEY 或 TAVILY_API_KEY。"),
        "", message('Optional settings: ask "Show Bookmark Research settings" or "Use only Exa for future searches".',
                    "可选配置：在对话中说“显示 Bookmark Research 的配置”，或“以后只用 Exa 搜索”。"),
        message("You can change page archiving preferences in chat. Deep research always preserves its task evidence.",
                "归档偏好也可通过对话修改；深度研究始终保留任务证据。"),
        message("Config command (works from any directory):", "查看配置的终端命令（可从任意目录运行）："),
        "  " + shlex.join(guide["settings_command"]),
        message("First use and configuration: ", "首次使用与配置说明：") + guide["guide_url"],
        message("Ask in English or Chinese; specify a different answer/report language when needed. Original quotations are preserved.",
                "可以用中文或英文提问，也可以指定答复和报告语言；原始引用保留原文。"),
    ])
    if guide.get("setup_command"):
        lines.extend([message("Reopen guided setup:", "重新打开配置向导："),
                      "  " + shlex.join(guide["setup_command"])])
    print("\n".join(lines), file=sys.stderr)


def manage(action, cli, source=None, ref=None, dry_run=False, installed_path=None, language="auto"):
    language = resolve_language(language)
    if action == "verify":
        return verify(cli, installed_path)
    current = _marketplace(cli)
    if action == "install":
        requested = _source(source if source is not None else SOURCE_ROOT, ref)
        if current:
            _check_source(current, requested)
            if ref:
                # Native list JSON omits the registered ref. Equal commit IDs
                # cannot distinguish a moving branch from an immutable tag.
                raise ValueError("An existing Git marketplace retains its registered ref. Reinstall without --ref, or explicitly change the source in Codex first")
        commands = [["plugin", "marketplace", "add", requested["source"]]]
        if ref:
            commands[0].extend(["--ref", ref])
    else:
        if not current or not _installed(cli):
            raise ValueError("No existing bookmark-research installation; run install first")
        requested = _configured_source(current)
        if requested["sourceType"] == "git":
            commands = [["plugin", "marketplace", "upgrade", NAME]]
        else:
            # Validate the retained local source before touching the installed cache.
            requested = _source(requested["source"])
            commands = []
    commands.append(["plugin", "add", SELECTOR])
    plan = {"action": action, "source": requested, "dry_run": dry_run, "language": language,
            "commands": [[cli.binary, *command, "--json"] for command in commands]}
    if dry_run:
        return plan
    added = None
    for command in commands:
        result = cli.run(command)
        if command[:3] == ["plugin", "marketplace", "add"]:
            if result.get("marketplaceName") != NAME:
                raise RuntimeError("The selected source registered a different marketplace; bookmark-research was not installed")
        elif command[:3] == ["plugin", "marketplace", "upgrade"]:
            if result.get("errors"):
                raise RuntimeError("Marketplace upgrade reported errors; the plugin was not reinstalled")
        else:
            added = result
    if not added or not isinstance(added.get("installedPath"), str) or added.get("pluginId") != SELECTOR:
        raise RuntimeError("Codex did not confirm the expected installed plugin path")
    verified = verify(cli, added["installedPath"])
    if requested.get("version") and verified["version"] != requested["version"]:
        raise RuntimeError("Installed plugin version differs from the selected local source")
    if requested["sourceType"] == "local":
        source_root = Path(requested["source"])
        cached_root = Path(verified["installed_path"])
        for relative in [Path(".codex-plugin/plugin.json"), *_copy_plan(source_root, include_codex_metadata=True)]:
            if (source_root / relative).read_bytes() != (cached_root / relative).read_bytes():
                raise RuntimeError("Installed cache differs from the selected source: " + relative.as_posix())
        for relative in CODEX_HOST_FILES:
            if read_asset(source_root, relative) != read_asset(cached_root, relative):
                raise RuntimeError("Installed cache differs from the selected source: " + relative)
    result = {**plan, **verified, "next_step": _message(language,
        "Start a new Codex thread to load the updated Skill and MCP tools.", "在 Codex 新建对话以加载更新后的 Skill 和 MCP 工具。")}
    if action == "install":
        result["getting_started"] = _getting_started(verified["installed_path"], cli.timeout, language)
    return result


HOSTS = ("codex", "claude", "pi", "dsh")


def _setup_host(host):
    return "claude_code" if host == "claude" else host


def _normalize_hosts(values):
    """Accept repeated and comma-separated --host values; dedupe in order."""
    if not values:
        return None
    hosts = []
    for value in values:
        for name in str(value).split(","):
            name = name.strip()
            if not name:
                continue
            if name not in HOSTS:
                raise ValueError("--host must be codex, claude, pi, or dsh: " + name)
            if name not in hosts:
                hosts.append(name)
    if not hosts:
        raise ValueError("--host requires at least one of codex, claude, pi, or dsh")
    return hosts


def _targets_from_args(args):
    hosts = args.host or ["codex"]
    others = [host for host in hosts if host != "codex"]
    if hosts == ["codex"]:
        if any((args.scope, args.project, args.profile, args.install_dir, args.claude, args.pi, args.dsh)):
            raise ValueError("Host-specific options require --host claude, pi, or dsh")
    if others and getattr(args, "installed_path", None):
        raise ValueError("--installed-path is only supported for Codex")
    if len(hosts) == 1:
        # A single host keeps its historical option handling and native errors.
        return [{"host": hosts[0], "scope": args.scope, "project": args.project, "profile": args.profile}]
    # CLI paths for unselected hosts are harmless locators and are ignored.
    if (args.scope or args.project) and not {"claude", "pi"} & set(hosts):
        raise ValueError("--scope and --project require --host claude or pi")
    if args.scope == "local" and "pi" in hosts:
        raise ValueError("Unsupported installation scope for pi: local is Claude-only")
    if args.profile and "dsh" not in hosts:
        raise ValueError("--profile is only supported for DSH")
    if args.install_dir and not others:
        raise ValueError("Host-specific options require --host claude, pi, or dsh")
    return [{"host": host,
             "scope": args.scope if host in ("claude", "pi") else None,
             "project": args.project if host in ("claude", "pi") else None,
             "profile": args.profile if host == "dsh" else None} for host in hosts]


def _run_target(args, target, language):
    host = target["host"]
    if host == "codex":
        return manage(args.action, CodexCli(args.codex, args.timeout),
                      source=getattr(args, "source", None), ref=getattr(args, "ref", None),
                      dry_run=getattr(args, "dry_run", False), installed_path=getattr(args, "installed_path", None),
                      language=language)
    from host_install import manage_host
    if getattr(args, "installed_path", None):
        raise ValueError("--installed-path is only supported for Codex")
    result = manage_host(args.action, host, binary=getattr(args, host), timeout=args.timeout,
                         source=getattr(args, "source", None), ref=getattr(args, "ref", None),
                         dry_run=getattr(args, "dry_run", False), scope=target.get("scope"),
                         project=target.get("project"), profile=target.get("profile"), install_dir=args.install_dir)
    result["language"] = language
    return result


def _run_setup(args, installed, host, language, guided):
    command = [sys.executable, "-B", str(installed / "src/cli.py"), "setup", "--lang", language,
               "--host", _setup_host(host), "--interactive" if guided else "--non-interactive"]
    if args.preferences:
        command.extend(["--input", args.preferences])
    if args.skip_checks:
        command.append("--skip-checks")
    if args.test_retrieval:
        command.append("--test-retrieval")
    if not (installed / "src/onboarding.py").is_file():
        requested = guided or bool(args.preferences) or args.test_retrieval
        return {"completed": False if requested else None, "status": "unsupported",
                "message": "The installed version predates guided setup; install a newer version to use setup."}
    # The installed version owns its settings schema. Do not use the
    # bootstrap checkout's runtime or impose a timeout on human input.
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE)
    try:
        setup = json.loads(completed.stdout)
        if not isinstance(setup, dict):
            raise ValueError("Setup result must be an object")
    except ValueError:
        setup = {"error": "Setup did not return a valid result"}
    setup["completed"] = completed.returncode == 0 and "error" not in setup
    setup["exit_code"] = completed.returncode
    return setup


def _guide(installed, host, timeout, language):
    guide = {**_getting_started(installed, timeout, language), "host": host}
    if (installed / "src/onboarding.py").is_file():
        guide["setup_command"] = ["python3", str(installed / "src/cli.py"), "setup",
                                  "--host", _setup_host(host), "--lang", language]
    return guide


def main(argv=None):
    language_parser = argparse.ArgumentParser(add_help=False)
    language_parser.add_argument("--lang", choices=("auto", "en", "zh"), default="auto")
    preliminary, _ = language_parser.parse_known_args(argv)
    language = resolve_language(preliminary.lang)
    message = lambda english, chinese: _message(language, english, chinese)
    parser = argparse.ArgumentParser(description=message(__doc__, "通过所选宿主的原生 CLI 安装、更新或验证 Bookmark Research。"))
    language_help = message("Installer language; auto follows LC_ALL, LC_MESSAGES, then LANG", "安装器语言；auto 依次读取 LC_ALL、LC_MESSAGES、LANG")
    parser.add_argument("--lang", choices=("auto", "en", "zh"), default=argparse.SUPPRESS, help=language_help)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("install", "update", "verify"):
        command = subparsers.add_parser(action)
        command.add_argument("--lang", choices=("auto", "en", "zh"), default=argparse.SUPPRESS, help=language_help)
        command.add_argument("--host", action="append", help=message(
            "Target client: codex, claude, pi, or dsh; repeat or comma-separate for several. Guided selection in a terminal, otherwise codex",
            "目标宿主：codex、claude、pi 或 dsh；可重复或用逗号指定多个。终端中引导选择，非交互时默认 codex"))
        command.add_argument("--codex", default="codex", help=message("Codex CLI executable, optionally an absolute path", "Codex CLI 程序名或绝对路径"))
        for host in ("claude", "pi", "dsh"):
            command.add_argument("--" + host, help=message("Path to the " + host + " CLI", host + " CLI 路径"))
        command.add_argument("--scope", choices=("user", "project", "local"), help=message(
            "Claude/Pi scope; default user (local is Claude-only)", "Claude/Pi 作用域，默认 user；local 仅限 Claude"))
        command.add_argument("--project", help=message("Project directory for project/local scope", "project/local 作用域对应的项目目录"))
        command.add_argument("--profile", help=message("Required DSH profile name", "DSH 必填的 profile 名称"))
        command.add_argument("--install-dir", help=message("Managed export/receipt root for non-Codex hosts", "非 Codex 宿主的持久包与安装记录根目录"))
        command.add_argument("--timeout", type=int, default=60, help=message("Timeout for each native command in seconds (1-300)", "每条原生命令的超时秒数（1–300）"))
        if action == "install":
            interaction = command.add_mutually_exclusive_group()
            interaction.add_argument("--interactive", dest="interaction", action="store_const", const="always",
                                     help=message("Always open the terminal wizard", "始终打开终端向导"))
            interaction.add_argument("--non-interactive", dest="interaction", action="store_const", const="never",
                                     help=message("Agent/CI mode: explicit flags and JSON output", "Agent/CI 模式：显式参数和 JSON 输出"))
            command.set_defaults(interaction="auto")
            command.add_argument("--preferences", help=message("Preferences JSON file (no credentials)", "偏好 JSON 文件（不含密钥）"))
            command.add_argument("--skip-checks", action="store_true", help=message("Skip network readiness checks", "跳过联网就绪检查"))
            command.add_argument("--test-retrieval", action="store_true", help=message("Test sample search/read; uses retrieval quota", "实际搜索与阅读自检；使用检索额度"))
            command.add_argument("--source", help=message("Local marketplace root or Git repository; defaults to this source tree", "本地 marketplace 根目录或 Git 仓库；默认当前源码目录"))
            command.add_argument("--ref", help=message("Optional Git tag, branch, or commit; local sources must be checked out separately", "可选 Git tag、分支或提交；本地来源需自行 checkout"))
        if action == "verify":
            command.add_argument("--installed-path", help=message("Override the native cache path returned by codex plugin add --json", "指定 codex plugin add --json 返回的安装缓存路径"))
        else:
            command.add_argument("--dry-run", action="store_true", help=message("Read current registration and print commands without installing", "读取登记状态并预览命令，不执行安装"))
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 300:
        parser.error(message("--timeout must be between 1 and 300", "--timeout 必须在 1 到 300 之间"))
    try:
        args.host = _normalize_hosts(args.host)
        guided = False
        targets = None
        if args.action == "install":
            if args.skip_checks and args.test_retrieval:
                raise ValueError("--skip-checks cannot be combined with --test-retrieval")
            sys.path.insert(0, str(SOURCE_ROOT / "src"))
            if args.preferences:
                from settings import Settings
                if args.preferences == "-":
                    raise ValueError("--preferences requires a file path; use cli.py setup --input - for stdin")
                path = Path(args.preferences).expanduser().resolve()
                if path.stat().st_size > 1024 * 1024:
                    raise ValueError("Preferences file exceeds the size limit")
                changes = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=Settings._unique_object)
                if not isinstance(changes, dict) or not changes:
                    raise ValueError("Preferences must be a nonempty JSON object without credentials")
                # Validate before registering a plugin or changing user settings.
                Settings._validate(Settings._merge(Settings().load(), changes))
                args.preferences = str(path)
            if not args.dry_run:
                from onboarding import Console
                with Console.open(args.interaction, language) as console:
                    if console:
                        guided = True
                        targets = console.install_targets(args)
        if targets is None:
            targets = _targets_from_args(args)
        single = len(targets) == 1
        results = []
        for target in targets:
            try:
                results.append(_run_target(args, target, language))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                if single:
                    raise
                results.append({"host": target["host"], "error": str(error), "verified": False})
        verified = [(target["host"], result) for target, result in zip(targets, results)
                    if args.action == "install" and result.get("verified") and "error" not in result]
        setup = None
        if verified:
            first_host, first = verified[0]
            setup = _run_setup(args, Path(first["installed_path"]), first_host, language, guided)
            for host, result in verified:
                result["getting_started"] = _guide(Path(result["installed_path"]), host, args.timeout, language)
            if setup.get("completed") is not True:
                print(message("Plugin installation passed; guided setup is incomplete or unavailable. See setup in the JSON result.",
                              "插件安装检查已通过；引导配置未完成或此版本不支持。请查看 JSON 中的 setup 结果。"), file=sys.stderr)
        if single:
            result = results[0]
            if setup is not None:
                result["setup"] = setup
        else:
            result = {"results": results, "language": language}
            if setup is not None:
                result["setup"] = setup
        if args.action == "install" and getattr(args, "dry_run", False) and args.preferences:
            result["preferences_file"] = str(Path(args.preferences).expanduser().resolve())
            result["preferences_applied"] = False
    except KeyboardInterrupt:
        print(json.dumps({"cancelled": True, "message": "Setup cancelled; completed installation steps are retained."}), file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": str(error), "verified": False}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    for row in results:
        if row.get("getting_started"):
            _print_getting_started(row["getting_started"])
    if (setup or {}).get("exit_code") == 130:
        return 130
    if any("error" in row for row in results):
        return 1
    return 1 if (setup or {}).get("completed") is False else 0

if __name__ == "__main__":
    raise SystemExit(main())
