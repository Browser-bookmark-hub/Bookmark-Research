"""Find the `dsh` command an installation should use, on every platform.

A DSH profile installs plugins through pnpm: `dsh plugin` forwards its
arguments to the pnpm it finds on PATH, so a CLI installed by npm alone cannot
manage a profile without one. DeepSeek Harness Desktop ships the same CLI
together with its own pnpm and runs package operations with that copy, so this
carrier needs none. Desktop can also register its bundled CLI as `dsh` from its
application menu — macOS writes `/usr/local/bin/dsh`, Windows prepends the
bundled directory to the user PATH — but Linux has no such registration and a
user may never run it, so the installation layouts are probed directly as well.

DeepSeek Harness Desktop reserves the profile name `desktop` for its own
carrier and rejects boot, config dump and (for the npm CLI) plugin management
for that name, so installations into `desktop` can only use the app's bundled
CLI.

Only the standard library is imported here: the published package ships `src/`
without `scripts/`, and the installed plugin runs `setup` from that copy.
"""

import json
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


def desktop_candidates(environment=None, platform=None):
    """DeepSeek Harness Desktop's bundled CLI in each platform's install layout.

    The packaged app always keeps it at `<resources>/runtime/cli/bin/`, so only
    the resources root differs; `dsh.cmd` on Windows is the name the app's own
    command registration checks for.
    """
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        roots = [Path("/Applications/DeepSeek Harness.app")]
        home = environment.get("HOME")
        if home:
            roots.append(Path(home) / "Applications" / "DeepSeek Harness.app")
        return [root / "Contents/Resources/runtime/cli/bin/dsh" for root in roots]
    if _windows(platform):
        bases = []
        local = environment.get("LOCALAPPDATA")
        if local:
            # The official Windows installer is per-user, so this is the default.
            bases.append(Path(local) / "Programs" / "DeepSeek Harness")
        for key in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            value = environment.get(key)
            if value:
                bases.append(Path(value) / "DeepSeek Harness")
        return [base / "resources" / "runtime" / "cli" / "bin" / "dsh.cmd" for base in bases]
    # Desktop packaging is official for macOS and Windows; the Linux builds are
    # community repackaging, which installs under one of these roots.
    return [Path("/opt/DeepSeek Harness/resources/runtime/cli/bin/dsh"),
            Path("/usr/lib/deepseek-harness/resources/runtime/cli/bin/dsh")]


def bundled_pnpm(binary):
    """The package manager a DSH CLI carries itself, if it ships one.

    Desktop places it beside the bundled CLI — `resources/runtime/pnpm` next to
    `resources/runtime/cli/bin/dsh`, or the primary runtime's copy of the same
    distribution. A generic CLI installs profile plugins by forwarding to the
    pnpm it finds on PATH instead.
    """
    if not binary:
        return None
    try:
        path = Path(binary).resolve()
    except OSError:
        return None
    relatives = (Path("pnpm/bin/pnpm.mjs"), Path("primary-runtime/dependencies/pnpm/bin/pnpm.mjs"))
    # Desktop layout: <resources>/runtime/cli/bin/dsh beside <resources>/runtime.
    for parent in list(path.parents)[:5]:
        for relative in relatives:
            candidate = parent / relative
            if candidate.is_file():
                return candidate
    return None


def profiles(package="bookmark-research", home=None):
    """Initialized DSH profiles under `$DSH_HOME/profiles`, and this plugin in each.

    `dsh plugin` initializes a profile on first use, so only a directory holding
    a `package.json` is a profile; the pnpm store beside them is not. `dependency`
    is the recorded spec for `package` and `enabled` says whether the composed
    bundle list activates it, which is what tells an existing registration from a
    fresh profile before the installer touches anything.
    """
    root = Path(home or os.environ.get("DSH_HOME", str(Path.home() / ".dsh"))).expanduser() / "profiles"
    rows = []
    if not root.is_dir():
        return rows
    for directory in sorted(root.iterdir()):
        manifest = directory / "package.json"
        if (directory.name.startswith(".") or directory.name == "node_modules"
                or directory.is_symlink() or not manifest.is_file()):
            continue
        row = {"name": directory.name, "path": str(directory), "initialized": False,
               "dependency": None, "enabled": False}
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows.append(row)
            continue
        dependencies = value.get("dependencies") if isinstance(value, dict) else None
        bundles = value.get("dsh", {}).get("profile", {}).get("bundles") if isinstance(value, dict) else None
        dependency = dependencies.get(package) if isinstance(dependencies, dict) else None
        row.update(initialized=True, dependency=dependency if isinstance(dependency, str) else None,
                   enabled=isinstance(bundles, list) and package in bundles)
        rows.append(row)
    return rows


def _client(binary, source, pnpm, reserved=False):
    bundled = bundled_pnpm(binary) if binary else None
    # The reserved `desktop` profile is composable only by the Desktop carrier,
    # the one that ships its own package manager; the npm CLI refuses it.
    blocked = reserved and bundled is None
    usable = bool(binary) and (bool(pnpm) or bundled is not None) and not blocked
    if usable:
        reason = "ok"
    elif not binary:
        reason = "missing"
    elif blocked:
        reason = "reserved"
    else:
        reason = "pnpm"
    return {"binary": binary, "source": source, "pnpm": pnpm,
            "bundled_pnpm": str(bundled) if bundled is not None else None,
            "usable": usable, "reason": reason}


def resolve(binary=None, environment=None, platform=None, profile=None):
    """Choose the `dsh` a profile installation should run.

    An explicit path is never substituted: it is reported as unusable rather
    than silently switching carriers. Otherwise a usable `dsh` on PATH wins, and
    a PATH command that cannot run `dsh plugin` is replaced by a DeepSeek
    Harness Desktop installation carrying its own pnpm. The reserved `desktop`
    profile accepts only that Desktop carrier.
    """
    environment = os.environ if environment is None else environment
    platform = sys.platform if platform is None else platform
    pnpm = executable("pnpm", environment, platform)
    if binary and str(binary) != "dsh":
        return _client(executable(binary, environment, platform), "argument", pnpm)
    reserved = str(profile or "").casefold() == "desktop"
    on_path = executable("dsh", environment, platform)
    located = [found for found in (executable(candidate, environment, platform)
                                   for candidate in desktop_candidates(environment, platform)) if found]
    available = ([_client(on_path, "path", pnpm, reserved)] if on_path else []) \
        + [_client(found, "desktop", pnpm, reserved) for found in located]
    for client in available:
        if client["usable"]:
            return client
    # Report whichever carrier exists, so its path and reason still reach the user.
    return available[0] if available else _client(None, None, pnpm, reserved)
