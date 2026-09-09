"""Persistent user preferences, stored separately from plugins and canvas packages."""

import copy
import errno
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


class Settings:
    """Load on each operation so MCP clients can change preferences without restart."""

    def __init__(self, path=None):
        config_home = self._xdg_home("XDG_CONFIG_HOME", Path.home() / ".config")
        selected = path or os.environ.get("BOOKMARK_RESEARCH_CONFIG") or config_home / "bookmark-research/settings.json"
        self.path = Path(selected).expanduser().resolve()

    @staticmethod
    def _xdg_home(variable, fallback):
        value = os.environ.get(variable)
        # XDG base directories must be absolute; empty or relative values use
        # the specification's home-directory defaults, never the process cwd.
        return Path(value) if value and Path(value).is_absolute() else fallback

    @staticmethod
    def data_directory():
        selected = os.environ.get("BOOKMARK_RESEARCH_DATA_DIR")
        if selected:
            return Path(selected).expanduser().resolve()
        return (Settings._xdg_home("XDG_DATA_HOME", Path.home() / ".local/share") / "bookmark-research").resolve()

    @staticmethod
    def external_path(value, purpose):
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError(purpose + " must be an absolute path (or start with ~)")
        path = path.resolve()
        plugin = Path(__file__).resolve().parents[1]
        for parent in (path, *path.parents):
            if (parent == plugin or (parent / ".codex-plugin/plugin.json").is_file()
                    or (parent / ".claude-plugin/plugin.json").is_file()):
                raise ValueError(purpose + " must be outside plugin directories")
            if ((parent / "永久栏目").is_dir() or (parent / "临时栏目").is_dir()
                    or any(parent.glob("*.canvas"))):
                raise ValueError(purpose + " must be outside canvas package directories")
        return path

    @classmethod
    def defaults(cls):
        return {"schema_version": 1, "timeout_seconds": 30,
                "search": {"providers": ["exa", "parallel"], "limit_per_target": 5},
                "fetch": {"provider": "exa", "max_characters": 12000},
                "archive": {"enabled": True, "directory": str(cls.data_directory() / "knowledge")}}

    @staticmethod
    def _merge(base, patch):
        if not isinstance(patch, dict):
            raise ValueError("Settings must be a JSON object")
        merged = copy.deepcopy(base)
        for key, value in patch.items():
            if isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key] = Settings._merge(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    @classmethod
    def _validate(cls, value):
        defaults = cls.defaults()
        if set(value) - set(defaults):
            raise ValueError("Unknown settings fields; credentials belong in the process environment")
        for section in ("search", "fetch", "archive"):
            if not isinstance(value.get(section), dict) or set(value[section]) != set(defaults[section]):
                raise ValueError("Invalid settings fields in " + section)
        for label, number, minimum, maximum in (
                ("schema_version", value["schema_version"], 1, 1),
                ("timeout_seconds", value["timeout_seconds"], 1, 60),
                ("search.limit_per_target", value["search"]["limit_per_target"], 1, 20),
                ("fetch.max_characters", value["fetch"]["max_characters"], 100, 100000)):
            if type(number) is not int or not minimum <= number <= maximum:
                raise ValueError("%s must be an integer between %s and %s" % (label, minimum, maximum))
        providers = value["search"]["providers"]
        if (not isinstance(providers, list) or not 1 <= len(providers) <= 3
                or any(p not in ("exa", "parallel", "tavily") for p in providers) or len(set(providers)) != len(providers)):
            raise ValueError("search.providers must select exa, parallel and/or tavily without duplicates")
        if value["fetch"]["provider"] not in ("exa", "parallel", "tavily"):
            raise ValueError("fetch.provider must be exa, parallel or tavily")
        if type(value["archive"]["enabled"]) is not bool:
            raise ValueError("archive.enabled must be a boolean")
        directory = value["archive"]["directory"]
        if not isinstance(directory, str) or not directory.strip() or "\x00" in directory:
            raise ValueError("archive.directory must be a nonempty path")
        value["archive"]["directory"] = str(cls.external_path(directory, "Archive directory"))
        return value

    @staticmethod
    def _unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate settings field")
            result[key] = value
        return result

    def _read(self):
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=self._unique_object)
        if not isinstance(value, dict):
            raise ValueError("Settings file must contain a JSON object")
        return value

    def load(self):
        return self._validate(self._merge(self.defaults(), self._read()))

    def describe(self):
        return {"config_path": str(self.path), "config_exists": self.path.is_file(), "settings": self.load()}

    @staticmethod
    @contextmanager
    def _update_lock(path):
        # Keep the lock inode across updates: replacing or deleting it would let
        # another CLI/MCP process lock a different file and lose an update.
        lock_path = path.with_name("." + path.name + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "r+b") as lock:
            if os.name == "nt":
                import msvcrt
                if lock.seek(0, os.SEEK_END) == 0:
                    lock.write(b"\x00")
                    lock.flush()
                lock.seek(0)
                acquire = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                release = lambda: msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                acquire = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                release = lambda: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            deadline = time.monotonic() + 10
            while True:
                try:
                    acquire()
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Settings are being updated by another process") from error
                    time.sleep(0.05)
            try:
                yield
            finally:
                release()

    def update(self, changes):
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Provide at least one settings change")
        stored = self._merge(self._read(), changes)
        self._validate(self._merge(self.defaults(), stored))
        path = self.external_path(str(self.path), "Settings file")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Persist only overrides; inherited defaults still follow the user's environment.
        with self._update_lock(path):
            stored = self._merge(self._read(), changes)
            self._validate(self._merge(self.defaults(), stored))
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                                 prefix=".settings-", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(json.dumps(stored, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return self.describe()
