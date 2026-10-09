"""Fetch the common release package; native clients still own registration."""

from contextlib import contextmanager
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

from export_bundle import NAME, VERSION_PATTERN, read_plugin_manifest


REGISTRY = "https://registry.npmjs.org"
DEFAULT_SOURCE = "npm:" + NAME
CACHE_PERMISSION = re.compile(r"EACCES|EPERM")
CACHE_HINT = ("Hint: npm's cache may contain files owned by another user (a known npm state after a "
              "privileged install); repair it with `sudo chown -R $(id -u):$(id -g) \"$(npm config get cache)\"` "
              "or point npm_config_cache at a writable directory.")


def _cache_permission_failure(detail):
    """Whether npm failed because its cache directory is not writable."""
    text = detail or ""
    return "cache" in text.casefold() and CACHE_PERMISSION.search(text) is not None


def source(value, ref=None):
    if not str(value).startswith("npm:"):
        return None
    spec = str(value)[4:]
    package, separator, version = spec.partition("@")
    version = version if separator else "latest"
    if ref or package != NAME or not (version == "latest" or VERSION_PATTERN.fullmatch(version)):
        raise ValueError("Use npm:bookmark-research or npm:bookmark-research@VERSION; --ref is Git-only")
    return {"sourceType": "npm", "source": NAME, "ref": version}


@contextmanager
def checkout(requested, timeout):
    from host_clients import executable
    selected = source("npm:" + requested["source"] + "@" + requested["ref"])
    npm = executable("npm")
    if not npm:
        raise ValueError("npm is required to download Bookmark Research releases")
    with tempfile.TemporaryDirectory(prefix="bookmark-npm-source-") as directory:
        base = Path(directory)

        def pack(cache=None):
            command = [
                npm, "pack", NAME + "@" + selected["ref"], "--ignore-scripts", "--json",
                "--registry", REGISTRY, "--pack-destination", str(base),
            ]
            if cache is not None:
                command += ["--cache", str(cache)]
            return subprocess.run(command, cwd=base, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout)

        result = pack()
        if result.returncode and _cache_permission_failure(result.stderr):
            # One retry in a scratch cache: a machine whose npm cache is unwritable
            # otherwise cannot install any release, and the failure is not the release's.
            with tempfile.TemporaryDirectory(prefix="bookmark-npm-cache-") as cache:
                retry = pack(cache)
            if retry.returncode == 0:
                result = retry
            else:
                raise RuntimeError("Could not download the npm release: "
                                   + result.stderr.strip()[-2000:] + "\n" + CACHE_HINT)
        if result.returncode:
            raise RuntimeError("Could not download the npm release: " + result.stderr.strip()[-2000:])
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("name") != NAME:
            raise ValueError("npm returned an unexpected release package")
        row = rows[0]
        filename = row.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename or "\\" in filename:
            raise ValueError("npm returned an invalid archive filename")
        root = base / "package"
        with tarfile.open(base / filename, "r:gz") as archive:
            # Python 3.9 has no portable tar extraction filter. Accept regular
            # package files/directories only, and validate before writing any.
            members = archive.getmembers()
            for member in members:
                path = PurePosixPath(member.name)
                if (not path.parts or path.parts[0] != "package" or ".." in path.parts
                        or "\\" in member.name or ":" in member.name
                        or not (member.isfile() or member.isdir())):
                    raise ValueError("Unsafe entry in npm release archive: " + member.name)
            for member in members:
                path = base.joinpath(*PurePosixPath(member.name).parts)
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as incoming, path.open("wb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
        manifest = read_plugin_manifest(root)
        if manifest["version"] != row.get("version") or (
                selected["ref"] != "latest" and manifest["version"] != selected["ref"]):
            raise ValueError("Downloaded npm release version does not match its manifest or requested pin")
        yield root, manifest["version"]
