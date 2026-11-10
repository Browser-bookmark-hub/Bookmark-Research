"""Find the `codex` command an installation should use, on every platform.

When a user installs Codex via npm (e.g. `@openai/codex`), version managers
like NVM, fnm, Volta, or asdf place the executable inside a specific Node
version's bin directory. Switching or upgrading Node versions leaves that
executable behind, causing `codex` to disappear from the active `$PATH`.

This module probes `$PATH` first, then scans common version-manager pools,
system user bin directories, and Codex's internal runtime releases across
macOS, Linux, and Windows so installations and updates can locate Codex
even when the active terminal environment has not exported it.

Only the standard library is imported here: the published package ships `src/`
without `scripts/`.
"""

import os
from pathlib import Path
import shutil
import sys


def _windows(platform):
    return platform.startswith("win")


def _accessible(path, platform):
    """A usable probe is a regular file, and on POSIX an executable one."""
    try:
        if not path.is_file():
            return False
    except OSError:
        return False
    return _windows(platform) or os.access(path, os.X_OK)


def _with_extensions(path, platform, environment):
    """A Windows path without an extension also names its PATHEXT candidate."""
    names = [path]
    if _windows(platform) and not path.suffix:
        extensions = [item for item in environment.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if item]
        names += [Path(str(path) + extension.lower()) for extension in extensions]
        names += [Path(str(path) + extension.upper()) for extension in extensions]
    return names


def executable(binary, environment=None, platform=None):
    """Resolve a CLI name or path the way the invoking shell would.

    Windows Python misses extensionless full paths, so those retry through
    PATHEXT instead of being reported missing.
    """
    if not binary:
        return None
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform
    text = str(binary)
    separators = [item for item in (os.sep, os.altsep) if item]
    path = Path(text).expanduser()
    if not any(separator in text for separator in separators) and not path.is_absolute():
        return shutil.which(text, path=environment.get("PATH"))
    for candidate in _with_extensions(path, platform, environment):
        if _accessible(candidate, platform):
            return str(candidate)
    return None


def codex_candidates(environment=None, platform=None):
    """Common installation locations for Codex CLI across platforms when not on PATH."""
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform
    candidates = []

    home = environment.get("USERPROFILE" if _windows(platform) else "HOME")
    if home:
        home_path = Path(home)
        if _windows(platform):
            appdata = environment.get("APPDATA")
            localappdata = environment.get("LOCALAPPDATA")
            if appdata:
                candidates.append(Path(appdata) / "npm" / "codex.cmd")
            if localappdata:
                nvm_dir = Path(localappdata) / "nvm"
                if nvm_dir.is_dir():
                    try:
                        candidates.extend(sorted(nvm_dir.glob("*/codex.cmd"), reverse=True))
                    except OSError:
                        pass
            candidates.append(home_path / ".volta" / "bin" / "codex.cmd")
            daemon_root = home_path / ".codex" / "packages" / "app-server-daemon" / "releases"
            if daemon_root.is_dir():
                try:
                    candidates.extend(sorted(daemon_root.glob("*/bin/codex.cmd"), reverse=True))
                    candidates.extend(sorted(daemon_root.glob("*/bin/codex.exe"), reverse=True))
                except OSError:
                    pass
        else:
            # POSIX: check NVM versions in reverse order (newest node versions first)
            nvm_dir = home_path / ".nvm" / "versions" / "node"
            if nvm_dir.is_dir():
                try:
                    candidates.extend(sorted(nvm_dir.glob("*/bin/codex"), reverse=True))
                except OSError:
                    pass
            candidates.extend([
                home_path / ".local" / "share" / "fnm" / "current" / "bin" / "codex",
                home_path / ".fnm" / "current" / "bin" / "codex",
                home_path / ".volta" / "bin" / "codex",
                home_path / ".asdf" / "shims" / "codex",
                home_path / ".local" / "bin" / "codex",
            ])
            if platform == "darwin":
                candidates.extend([
                    Path("/opt/homebrew/bin/codex"),
                    Path("/usr/local/bin/codex"),
                ])
            else:
                candidates.extend([
                    Path("/usr/local/bin/codex"),
                    Path("/usr/bin/codex"),
                ])
            daemon_root = home_path / ".codex" / "packages" / "app-server-daemon" / "releases"
            if daemon_root.is_dir():
                try:
                    candidates.extend(sorted(daemon_root.glob("*/bin/codex"), reverse=True))
                except OSError:
                    pass

    return candidates


def resolve(binary=None, environment=None, platform=None):
    """Find the Codex CLI an installation should use.

    An explicit path is checked directly. Otherwise a `codex` on PATH wins.
    If none is found on PATH, common version-manager and system candidate
    locations are probed automatically.
    """
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform

    if binary and binary != "codex":
        found = executable(binary, environment, platform)
        if found:
            return {"binary": found, "source": "explicit", "usable": True}
        return {"binary": binary, "source": "explicit", "usable": False}

    found = executable("codex", environment, platform)
    if found:
        return {"binary": found, "source": "path", "usable": True}

    for candidate in codex_candidates(environment, platform):
        for candidate_variant in _with_extensions(candidate, platform, environment):
            if _accessible(candidate_variant, platform):
                return {"binary": str(candidate_variant), "source": "discovered", "usable": True}

    return {"binary": None, "source": "missing", "usable": False}

