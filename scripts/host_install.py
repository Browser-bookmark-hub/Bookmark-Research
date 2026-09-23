"""Persist complete host exports and delegate registration to native clients."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from export_bundle import SOURCE_ROOT, _write_adapter, export_bundle, read_plugin_manifest
from host_clients import HostClient, read_json


def _write_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _files(root):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in ("__pycache__", "node_modules", ".git") for part in relative.parts) or path.suffix in (".pyc", ".pyo"):
            continue
        if path.is_symlink():
            raise ValueError("Unexpected link in managed package: " + str(relative))
        if path.is_file():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _check_files(root, expected, exact=False):
    if exact and _files(root) != expected:
        raise RuntimeError("Installed package differs from its verified source; preserve local edits before updating")
    for relative, digest in expected.items():
        path = root / relative
        current = root
        for part in Path(relative).parts:
            if current.is_symlink():
                raise RuntimeError("Unexpected link in installed package: " + relative)
            current = current / part
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("Installed package differs from its verified source: " + relative)


def _source(value, ref=None):
    # Keep Git URL normalization identical to the existing Codex installer.
    from install import _repository
    value = str(value)
    if not value or any(ord(char) < 32 for char in value):
        raise ValueError("Source must be a nonempty path or Git repository")
    path = Path(value).expanduser()
    if path.exists() or value.startswith(("/", "./", "../", "~")):
        if ref:
            raise ValueError("--ref only applies to Git; update local source files yourself")
        root = path.resolve()
        read_plugin_manifest(root)
        return {"sourceType": "local", "source": str(root)}
    if ref and (ref.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./-]+", ref)):
        raise ValueError("Invalid Git ref")
    return {"sourceType": "git", "source": _repository(value), "ref": ref}


@contextmanager
def _checkout(source, timeout):
    if source["sourceType"] == "local":
        yield Path(source["source"]), None
        return
    with tempfile.TemporaryDirectory(prefix="bookmark-host-source-") as directory:
        root = Path(directory)
        environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        for arguments in (["init", "--quiet"], ["remote", "add", "origin", source["source"]],
                          ["fetch", "--quiet", "--depth", "1", "origin", source.get("ref") or "HEAD"],
                          ["checkout", "--quiet", "--detach", "FETCH_HEAD"]):
            completed = subprocess.run(["git", "-C", str(root), *arguments], env=environment,
                                       capture_output=True, text=True, timeout=timeout)
            if completed.returncode:
                raise RuntimeError("Could not prepare the registered Git source: " + completed.stderr.strip()[-2000:])
        revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                                  text=True, check=True, timeout=timeout).stdout.strip()
        yield root, revision


def runtime_check(root, timeout):
    """Check the exported CLI and stdio protocol using an empty, disposable store."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "bookmark-host-installer", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    with tempfile.TemporaryDirectory(prefix="bookmark-host-probe-") as directory:
        data = Path(directory)
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                           BOOKMARK_RESEARCH_DATA_DIR=str(data / "data"),
                           BOOKMARK_RESEARCH_CONFIG=str(data / "settings.json"))
        command = [sys.executable, "-B", str(root / "src/cli.py")]
        doctor = subprocess.run([*command, "doctor"], cwd=data, env=environment, capture_output=True,
                                text=True, timeout=timeout)
        if doctor.returncode or json.loads(doctor.stdout).get("fts5") is not True:
            raise RuntimeError("Exported Python runtime requires Python 3.9+ and SQLite FTS5")
        mcp = subprocess.run([*command, "serve"], cwd=data, env=environment, capture_output=True,
                             text=True, input="".join(json.dumps(row) + "\n" for row in requests), timeout=timeout)
        if mcp.returncode:
            raise RuntimeError("Exported MCP runtime failed to start")
        responses = {row.get("id"): row for row in map(json.loads, mcp.stdout.splitlines())}
        names = sorted(row["name"] for row in responses.get(2, {}).get("result", {}).get("tools", []))
        if "result" not in responses.get(1, {}) or not {"search_bookmarks", "search_web", "fetch_web"} <= set(names):
            raise RuntimeError("Exported MCP runtime did not expose the expected tools")
        if (data / "data/index.sqlite3").exists():
            raise RuntimeError("Runtime discovery unexpectedly created a database")
        return {"fts5": True, "mcp_tools": names, "network_checked": False,
                "database_created": False, "host_session_checked": False}


def _load_receipt(path, target):
    receipt = read_json(path)
    if receipt is None:
        return None
    if not isinstance(receipt, dict) or receipt.get("schema") != 1 or receipt.get("target") != target:
        raise ValueError("Invalid or mismatched installation receipt: " + str(path))
    files = receipt.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Installation receipt has no package checksums")
    for relative, digest in files.items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts or not re.fullmatch(r"[a-f0-9]{64}", str(digest)):
            raise ValueError("Invalid package checksum in installation receipt")
    if receipt.get("source", {}).get("sourceType") not in ("git", "local"):
        raise ValueError("Invalid source in installation receipt")
    return receipt


def _verify(client, bundle, receipt):
    _check_files(bundle, receipt["files"], exact=True)
    root = client.installed_path(bundle, receipt["version"])
    _check_files(root, receipt["files"])
    return {"host": client.host, "installed": True, "verified": True,
            "version": receipt["version"], "release_version": receipt["release_version"],
            "installed_path": str(root), "source": receipt["source"], "target": client.target,
            "runtime": runtime_check(root, client.timeout)}


def _manage(action, client, base, source, ref, dry_run):
    bundle, receipt_path = base / "bundle", base / "receipt.json"
    receipt = _load_receipt(receipt_path, client.target)
    if action == "verify":
        if not receipt:
            raise ValueError("No managed installation for this host and scope/profile; run install first")
        result = _verify(client, bundle, receipt)
        if receipt.get("state") != "verified":
            receipt["state"] = "verified"
            _write_json(receipt_path, receipt)
        return result
    if receipt:
        if source is not None:
            requested = _source(source, ref)
            old = receipt["source"]
            if (requested["sourceType"], requested["source"]) != (old["sourceType"], old["source"]) or (ref is not None and ref != old.get("ref")):
                raise ValueError("Existing installation retains its source and ref; choose a separate installation directory for another source")
        elif ref is not None and ref != receipt["source"].get("ref"):
            raise ValueError("Existing installation retains its registered ref")
        requested = receipt["source"]
        if bundle.exists():
            _check_files(bundle, receipt["files"], exact=True)
    else:
        if action == "update":
            raise ValueError("No managed installation for this target; run install first with the intended scope/profile")
        if bundle.exists() or bundle.is_symlink():
            raise ValueError("Refusing an existing package without an installation receipt")
        requested = _source(source if source is not None else SOURCE_ROOT, ref)
    if requested["sourceType"] == "local" and (Path(requested["source"]) == base or Path(requested["source"]) in base.parents):
        raise ValueError("The managed installation directory must be outside the source checkout")
    registration = client.registration(bundle)
    with _checkout(requested, client.timeout) as (root, revision), tempfile.TemporaryDirectory(
            prefix=".bookmark-stage-", dir=base if not dry_run else None) as temporary:
        stage = Path(temporary) / "bundle"
        # Windows has no python3 alias by default; pin the interpreter running the installer.
        python = sys.executable if os.name == "nt" else "python3"
        export_bundle(client.host, stage, root, python)
        manifest = read_plugin_manifest(root)
        # Render path-dependent manual instructions for the persistent location.
        _write_adapter(stage, client.host, bundle, manifest, python)
        content = _files(stage)
        digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
        version = manifest["version"]
        if client.host == "claude":
            # Claude caches explicit versions. Content changes on main must get a
            # new native cache entry without modifying the source release version.
            version = version.split("+", 1)[0] + "+source." + digest[:16]
            path = stage / ".claude-plugin/plugin.json"
            metadata = read_json(path)
            metadata["version"] = version
            _write_json(path, metadata)
            for relative in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
                client.run(["plugin", "validate", "--strict", str(stage / relative)])
        files = _files(stage)
        runtime_check(stage, client.timeout)
        changed = not receipt or files != receipt["files"]
        commands = client.commands(bundle, registration, changed or (receipt and receipt.get("state") != "verified"))
        plan = {"host": client.host, "action": action, "source": requested, "target": client.target,
                "bundle_path": str(bundle), "receipt_path": str(receipt_path), "dry_run": dry_run,
                "version": version, "release_version": manifest["version"], "revision": revision,
                "commands": [[client.binary, *arguments] for arguments in commands], "changed": changed}
        if dry_run:
            return plan
        new_receipt = {"schema": 1, "state": "pending", "target": client.target, "source": requested,
                       "revision": revision, "version": version, "release_version": manifest["version"], "files": files}
        previous = Path(temporary) / "previous"
        if bundle.exists():
            bundle.rename(previous)
        try:
            stage.rename(bundle)
            _write_json(receipt_path, new_receipt)
            for arguments in commands:
                client.run(arguments)
            checked = _verify(client, bundle, new_receipt)
            new_receipt["state"] = "verified"
            _write_json(receipt_path, new_receipt)
        except BaseException:
            if previous.exists():
                if bundle.exists():
                    bundle.rename(Path(temporary) / "failed")
                previous.rename(bundle)
                failed_receipt = dict(receipt)
            else:
                # A native command may already reference this path. Keep it for
                # recovery instead of leaving a newly registered package dangling.
                failed_receipt = new_receipt
            failed_receipt["state"] = "needs_verification"
            _write_json(receipt_path, failed_receipt)
            raise
        return {**plan, **checked, "next_step": "Restart " + client.host + " to load the installed Skill and tools."}


def manage_host(action, host, binary=None, timeout=60, source=None, ref=None, dry_run=False,
                scope=None, project=None, profile=None, install_dir=None):
    if host not in ("claude", "pi", "dsh"):
        raise ValueError("Unsupported host: " + host)
    client = HostClient(host, binary or host, timeout, scope, project, profile)
    client.require()
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))).expanduser()
    if not data_home.is_absolute():
        data_home = Path.home() / ".local/share"
    home = Path(install_dir or os.environ.get("BOOKMARK_RESEARCH_INSTALL_DIR", str(data_home / "bookmark-research/installations"))).expanduser().resolve()
    key = hashlib.sha256(json.dumps(client.target, sort_keys=True).encode()).hexdigest()[:16]
    base = home / (host + "-" + key)
    if base.is_symlink():
        raise ValueError("Refusing a symlink installation directory")
    if dry_run or (action == "verify" and not base.exists()):
        return _manage(action, client, base, source, ref, dry_run)
    base.mkdir(parents=True, exist_ok=True)
    # The OS releases these locks on a crash; they stop two installers from
    # replacing the same persistent package.
    with (base / "install.lock").open("a") as lock:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("Another installer is already changing this target") from error
        return _manage(action, client, base, source, ref, dry_run)
