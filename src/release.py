"""Release identity from the installed distribution's own manifest.

The npm, Pi and DSH packages carry ``package.json``. Codex, Claude and Agent
Plugins exports retain the release version in their native plugin manifest.
Read that identity for MCP and HTTP clients instead of hardcoding a version.
An absent or invalid manifest reports an unknown version; an invalid preferred
manifest never falls through to a different manifest that might hide damage.
"""

import json
from functools import lru_cache
from pathlib import Path


UNKNOWN_VERSION = "0+unknown"


def read_manifest_version(path):
    """Return ``version`` from a package manifest, or ``UNKNOWN_VERSION``."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return UNKNOWN_VERSION
    if not isinstance(value, str) or not value.strip():
        return UNKNOWN_VERSION
    return value.strip()


@lru_cache(maxsize=1)
def release_version():
    """Return this installation's manifest version."""
    root = Path(__file__).resolve().parents[1]
    for relative in ("package.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json", "plugin.json"):
        path = root / relative
        if path.exists() or path.is_symlink():
            return read_manifest_version(path)
    return UNKNOWN_VERSION


def user_agent(product="bookmark-research"):
    """Return the ``product/version`` user agent shared by outbound requests."""
    return product + "/" + release_version()
