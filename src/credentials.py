"""Optional private credential file; process environment always takes precedence."""

import json
import os
from pathlib import Path
import stat
import tempfile

from settings import Settings


class Credentials:
    NAMES = ("EXA_API_KEY", "PARALLEL_API_KEY", "TAVILY_API_KEY", "JINA_API_KEY", "OPENAI_API_KEY")

    def __init__(self, settings=None):
        settings = settings if settings is not None else Settings()
        self.path = Path(os.environ.get("BOOKMARK_RESEARCH_CREDENTIALS") or
                         settings.path.with_name("credentials.json")).expanduser().absolute()

    def _read(self):
        if self.path.is_symlink():
            raise ValueError("Credential file must not be a symlink")
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return {}
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and info.st_mode & 0o077):
                raise ValueError("Credential file must be a private regular file (chmod 600)")
            if info.st_size > 64000:
                raise ValueError("Credential file exceeds the size limit")
            try:
                value = json.load(stream, object_pairs_hook=Settings._unique_object)
            except (ValueError, UnicodeError):
                raise ValueError("Credential file is not valid JSON") from None
        self._validate(value)
        return value

    @classmethod
    def _validate(cls, value):
        if not isinstance(value, dict) or set(value) - set(cls.NAMES):
            raise ValueError("Credential file contains unsupported fields")
        if any(not isinstance(key, str) or not 1 <= len(key) <= 8192
               or any(not 33 <= ord(char) <= 126 for char in key) for key in value.values()):
            raise ValueError("Credentials must be nonempty printable API keys without whitespace")

    def get(self, name):
        if name not in self.NAMES:
            raise ValueError("Unsupported credential name")
        return os.environ.get(name) or self._read().get(name)

    def describe(self):
        saved = self._read()
        return {"path": str(self.path), "storage": "private_file_not_encrypted",
                "credentials": [{"name": name, "configured": bool(os.environ.get(name) or saved.get(name)),
                    "source": "environment" if os.environ.get(name) else "private_file" if saved.get(name) else None}
                    for name in self.NAMES]}

    def save(self, name, value):
        self._validate({name: value})
        if self.path.is_symlink():
            raise ValueError("Credential file must not be a symlink")
        path = Settings.external_path(str(self.path), "Credential file")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with Settings._update_lock(path):
            saved = {**self._read(), name: value}
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                                 prefix=".credentials-", delete=False) as stream:
                    temporary = Path(stream.name)
                    os.chmod(temporary, 0o600)
                    json.dump(saved, stream, ensure_ascii=False)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return {"name": name, "saved": True, "environment_takes_precedence": bool(os.environ.get(name))}
