#!/usr/bin/env python3
"""Install, update, or verify Bookmark Research through Codex's native CLI."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from export_bundle import NAME, SOURCE_ROOT, _copy_plan, read_plugin_manifest


SELECTOR = NAME + "@" + NAME


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
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    mcp = subprocess.run([server["command"], *server["args"]], cwd=root,
                         input="\n".join(json.dumps(row) for row in requests) + "\n",
                         text=True, capture_output=True, timeout=timeout, env=environment)
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


def _getting_started(installed_path, timeout=30):
    """Read the installed runtime's preferences without initializing user data."""
    command = ["python3", "-B", str(Path(installed_path) / "src/cli.py"), "config", "show"]
    guide = {
        "first_prompt": '用 Bookmark Research 读取我的书签画布包 "/absolute/path/to/my-canvas-package"，'
                        '先离线列出栏目、文件夹和书签数量。',
        "settings_command": command,
        "guide_url": "https://github.com/Browser-bookmark-hub/Bookmark-Research/blob/main/docs/installation.md#首次使用与数据位置",
        "configuration": None, "configuration_summary": [], "configuration_error": None,
    }
    try:
        checked = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
        if checked.returncode:
            raise ValueError("Installed config show failed")
        configuration = json.loads(checked.stdout)
        settings = configuration["settings"]
        summary = [
            "配置：" + ("沿用已保存的设置" if configuration["config_exists"] else "使用默认值，无需先创建配置文件"),
            "搜索：%s；每目标 %s 条结果" % (" + ".join(settings["search"]["providers"]), settings["search"]["limit_per_target"]),
            "正文读取：%s；长度参数 %s 字符；超时 %s 秒" % (
                settings["fetch"]["provider"], settings["fetch"]["max_characters"], settings["timeout_seconds"]),
            "普通网页读取自动归档：" + ("开启" if settings["archive"]["enabled"] else "关闭"),
            "归档目录：" + settings["archive"]["directory"],
            "配置文件：" + configuration["config_path"],
        ]
        guide.update(configuration=configuration, configuration_summary=summary)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        # Installation is already verified. Keep an unreadable existing config
        # intact, and avoid exposing its contents or replacing it with defaults.
        guide["configuration_error"] = "现有配置读取失败。请运行下方配置查询命令查看原因并修正文件；原文件已保留。"
    return guide


def _print_getting_started(guide):
    lines = ["", "Bookmark Research 安装完成，运行检查已通过。"]
    if guide["configuration_error"]:
        lines.extend([guide["configuration_error"], "配置修正后，按以下步骤开始："])
    else:
        lines.extend(guide["configuration_summary"])
    lines.extend([
        "", "下一步：",
        "1. 在 Codex 新建对话，让客户端加载插件。",
        "2. 准备自己的 Bookmark Canvas 数据包，把下面的占位路径换成实际路径后发送：",
        "   " + guide["first_prompt"],
        "3. 只做网页研究时可直接提出主题，无需先导入书签。研究使用当前对话的模型，无需另填模型名称或地址。",
        "", "本地书签查询不需要 API Key。网页研究使用所选服务，匿名额度和认证要求由服务方决定。",
        "需要密钥时，在启动客户端的环境中配置 EXA_API_KEY、PARALLEL_API_KEY 或 TAVILY_API_KEY。",
        "", "可选配置：在对话中说“显示 Bookmark Research 的配置”，或“以后只用 Exa 搜索”。",
        "归档偏好也可通过对话修改；深度研究始终保留任务证据。",
        "查看配置的终端命令（可从任意目录运行）：",
        "  " + shlex.join(guide["settings_command"]),
        "首次使用与配置说明：" + guide["guide_url"],
    ])
    print("\n".join(lines), file=sys.stderr)


def manage(action, cli, source=None, ref=None, dry_run=False, installed_path=None):
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
    plan = {"action": action, "source": requested, "dry_run": dry_run,
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
    result = {**plan, **verified, "next_step": "Start a new Codex thread to load the updated Skill and MCP tools."}
    if action == "install":
        result["getting_started"] = _getting_started(verified["installed_path"], cli.timeout)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("install", "update", "verify"):
        command = subparsers.add_parser(action)
        command.add_argument("--codex", default="codex", help="Codex CLI executable, optionally an absolute path")
        command.add_argument("--timeout", type=int, default=60, help="Timeout for each native command in seconds (1-300)")
        if action == "install":
            command.add_argument("--source", help="Local marketplace root or Git repository; defaults to this source tree")
            command.add_argument("--ref", help="Optional Git tag, branch, or commit; local sources must be checked out separately")
        if action == "verify":
            command.add_argument("--installed-path", help="Override the native cache path returned by codex plugin add --json")
        else:
            command.add_argument("--dry-run", action="store_true", help="Read current registration and print commands without installing")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300")
    try:
        result = manage(args.action, CodexCli(args.codex, args.timeout),
                        source=getattr(args, "source", None), ref=getattr(args, "ref", None),
                        dry_run=getattr(args, "dry_run", False), installed_path=getattr(args, "installed_path", None))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": str(error), "verified": False}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if result.get("getting_started"):
        _print_getting_started(result["getting_started"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
