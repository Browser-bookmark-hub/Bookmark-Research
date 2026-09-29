"""Registry of research task folders, so tasks stay listed wherever they were created."""

import json
import os
from pathlib import Path
import tempfile

from settings import Settings


def registry_path():
    return Settings.data_directory() / "research-locations.json"


def load():
    """Return {research_id: {"path", "created_at", "placement"}}; missing registry is empty."""
    path = registry_path()
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("tasks"), dict):
        raise ValueError("Invalid research location registry: " + str(path))
    return value["tasks"]


def register(research_id, directory, created_at, placement):
    """Record a task folder. Entries are never removed, so moved or deleted tasks show as missing."""
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with Settings._update_lock(path):
        tasks = load()
        tasks[research_id] = {"path": str(Path(directory)), "created_at": created_at, "placement": placement}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=".research-locations-", delete=False) as stream:
            json.dump({"schema_version": 1, "tasks": tasks}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            temporary = Path(stream.name)
        os.replace(temporary, path)
