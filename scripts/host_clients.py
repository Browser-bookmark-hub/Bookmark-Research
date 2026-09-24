"""Native client commands and read-only registration checks for exported hosts."""

import json
import os
from pathlib import Path
import shutil
import subprocess

from export_bundle import NAME


SELECTOR = NAME + "@" + NAME


def executable(binary):
    """Resolve a CLI, including .cmd/.exe shims that Windows Python 3.9 misses for full paths."""
    found = shutil.which(binary)
    if os.name == "nt" and (not found or not Path(found).suffix):
        for extension in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";"):
            found = shutil.which(binary + extension) or found
            if found and Path(found).suffix:
                break
    return found


def read_json(path, default=None):
    if not path.exists():
        return default
    if path.is_symlink():
        raise ValueError("Refusing a symlink state file: " + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def local_path(value, base):
    if not isinstance(value, str):
        return None
    for prefix in ("link:", "file:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    if ":" in value and not value.startswith("/") and not Path(value).is_absolute():
        return None
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


class HostClient:
    def __init__(self, host, binary, timeout, scope=None, project=None, profile=None):
        self.host, self.binary, self.timeout = host, binary, timeout
        self.scope = scope or "user"
        self.cwd = Path(project).expanduser().resolve() if project else Path.cwd()
        self.profile = profile
        if host == "dsh":
            if scope or project:
                raise ValueError("DSH uses --profile, not --scope or --project")
            if not profile or not all(c.isalnum() or c in "._-" for c in profile) or profile.startswith("."):
                raise ValueError("DSH requires --profile NAME (letters, numbers, dots, underscores or hyphens)")
            self.home = Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh"))).expanduser().resolve()
            self.settings = self.home / "profiles" / profile / "package.json"
        else:
            if profile:
                raise ValueError("--profile is only supported for DSH")
            if self.scope not in (("user", "project", "local") if host == "claude" else ("user", "project")):
                raise ValueError("Unsupported installation scope for " + host)
            if self.scope != "user" and not project:
                raise ValueError("Project/local scope requires --project PATH")
            if not self.cwd.is_dir():
                raise ValueError("Project directory does not exist: " + str(self.cwd))
            variable, default = (("CLAUDE_CONFIG_DIR", Path.home() / ".claude") if host == "claude"
                                 else ("PI_CODING_AGENT_DIR", Path.home() / ".pi/agent"))
            self.home = Path(os.environ.get(variable, str(default))).expanduser().resolve()
            self.settings = (self.home / "settings.json" if self.scope == "user"
                             else self.cwd / ".pi/settings.json")

    @property
    def target(self):
        return {"host": self.host, "client_home": str(self.home),
                "scope": self.scope if self.host != "dsh" else None,
                "project": str(self.cwd) if self.host != "dsh" and self.scope != "user" else None,
                "profile": self.profile}

    def require(self):
        if not executable(self.binary):
            raise ValueError(self.host + " CLI was not found: " + self.binary)
        if self.host == "dsh" and not shutil.which("pnpm"):
            # dsh plugin forwards to pnpm; fail before creating a profile.
            raise ValueError("DSH installs profile plugins with pnpm, which was not found on PATH; "
                             "install it (npm install -g pnpm, or corepack enable pnpm) and retry")

    def run(self, arguments, structured=False, quiet_error=False):
        result = subprocess.run([executable(self.binary) or self.binary, *arguments], cwd=self.cwd, text=True, encoding="utf-8", errors="replace",
                                capture_output=True, timeout=self.timeout)
        if result.returncode:
            detail = "" if quiet_error else "\n" + (result.stderr or result.stdout).strip()[-3000:]
            raise RuntimeError(self.host + " command failed: " + " ".join(arguments[:3]) + detail)
        if not structured:
            return result.stdout
        return json.loads(result.stdout)

    def registration(self, bundle):
        """Reject another source before mutations, and return this target's native state."""
        if self.host == "claude":
            marketplaces = self.run(["plugin", "marketplace", "list", "--json"], True)
            plugins = self.run(["plugin", "list", "--json"], True)
            if not isinstance(marketplaces, list) or not isinstance(plugins, list):
                raise ValueError("Unexpected Claude plugin list JSON")
            if any(not isinstance(row, dict) for row in marketplaces + plugins):
                raise ValueError("Unexpected Claude plugin list entry")
            matches = [row for row in marketplaces if row.get("name") == NAME]
            if len(matches) > 1 or (matches and (matches[0].get("source") != "directory"
                    or local_path(matches[0].get("path"), self.cwd) != bundle.resolve())):
                raise ValueError("Claude marketplace bookmark-research uses another source; resolve it in Claude first")
            other = [row for row in plugins if row.get("scope") == self.scope
                     and str(row.get("id", "")).startswith(NAME + "@") and row.get("id") != SELECTOR]
            if other:
                raise ValueError("Bookmark Research is already installed from another Claude marketplace")
            rows = [row for row in plugins if row.get("id") == SELECTOR and row.get("scope") == self.scope]
            if len(rows) > 1:
                raise ValueError("Multiple Claude registrations match this scope")
            return {"marketplace": bool(matches), "installed": bool(rows), "plugin": rows[0] if rows else None}
        settings = read_json(self.settings, {})
        if not isinstance(settings, dict):
            raise ValueError("Unexpected client settings object: " + str(self.settings))
        if self.host == "pi":
            packages = settings.get("packages", [])
            if not isinstance(packages, list):
                raise ValueError("Pi packages must be an array")
            matches = []
            for entry in packages:
                source = entry.get("source") if isinstance(entry, dict) else entry
                path = local_path(source, self.settings.parent)
                if path == bundle.resolve():
                    if isinstance(entry, dict) and (entry.get("skills") == [] or entry.get("autoload") is False):
                        raise ValueError("The registered Pi package disables its Skill; enable it in Pi first")
                    matches.append(entry)
                elif path and path.is_dir():
                    metadata = read_json(path / "package.json", {})
                    if isinstance(metadata, dict) and metadata.get("name") == NAME:
                        raise ValueError("Pi already registers Bookmark Research at another path")
                elif isinstance(source, str) and ("/Bookmark-Research" in source or source.startswith("npm:" + NAME)):
                    raise ValueError("Pi already registers another Bookmark Research source")
            if len(matches) > 1:
                raise ValueError("Duplicate Pi registrations; resolve them in Pi first")
            return {"installed": bool(matches)}
        dependencies, dsh = settings.get("dependencies", {}), settings.get("dsh", {})
        if not isinstance(dependencies, dict) or not isinstance(dsh, dict) or not isinstance(dsh.get("profile", {}), dict):
            raise ValueError("Unexpected DSH profile manifest")
        dependency = dependencies.get(NAME)
        if dependency and local_path(dependency, self.settings.parent) != bundle.resolve():
            raise ValueError("DSH profile already installs Bookmark Research from another source")
        bundles = settings.get("dsh", {}).get("profile", {}).get("bundles", [])
        if not isinstance(bundles, list):
            raise ValueError("DSH profile bundles must be an array")
        return {"installed": bool(dependency), "enabled": NAME in bundles}

    def commands(self, bundle, registration, changed=False):
        if self.host == "claude":
            commands = []
            if not registration["marketplace"]:
                commands.append(["plugin", "marketplace", "add", str(bundle), "--scope", self.scope])
            if registration["installed"]:
                if changed:
                    commands.extend([["plugin", "marketplace", "update", NAME],
                                     ["plugin", "update", SELECTOR, "--scope", self.scope]])
                if not registration["plugin"].get("enabled"):
                    raise ValueError("The Claude plugin is disabled; enable it in Claude before reinstalling")
            else:
                commands.append(["plugin", "install", SELECTOR, "--scope", self.scope])
            return commands
        if self.host == "pi":
            return [] if registration["installed"] else [["install", str(bundle), *(["-l"] if self.scope == "project" else [])]]
        return [] if registration["installed"] and registration["enabled"] and not changed else [
            ["plugin", "--profile", self.profile, "add", str(bundle)]]

    def installed_path(self, bundle, version):
        registration = self.registration(bundle)
        if not registration["installed"]:
            raise RuntimeError(self.host + " did not confirm the expected native registration")
        if self.host == "claude":
            plugin = registration["plugin"]
            if not plugin.get("enabled") or plugin.get("version") != version:
                raise RuntimeError("Claude did not activate the expected plugin version")
            path = plugin.get("installPath")
            if not isinstance(path, str) or not Path(path).is_dir():
                raise RuntimeError("Claude did not return a valid installed cache path")
            return Path(path).resolve()
        if self.host == "dsh":
            if not registration["enabled"]:
                raise RuntimeError("DSH installed the dependency without enabling its bundle")
            composition = self.run(["--profile", self.profile, "--dump-config"], quiet_error=True)
            if not all(name in composition for name in ("bookmark-research-skill", "bookmark-research-mcp", "bookmarkResearchPaths")):
                raise RuntimeError("DSH composition is missing the Bookmark Research Skill or MCP configuration")
            package = self.settings.parent / "node_modules" / NAME
            if not package.is_dir():
                raise RuntimeError("DSH did not retain the installed bundle in its profile")
            return package.resolve()
        return bundle
