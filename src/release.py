"""Single release-version source, read from the installed package manifest.

The plugin is distributed as an npm package, so ``package.json`` travels with
the code at the plugin root. Reading it here keeps the MCP handshake, remote
client identity and HTTP user agents on the same version as the published
manifest instead of drifting across hardcoded copies.

When the manifest is missing (an exotic layout, or a single file copied out of
the package) the version is reported as unknown rather than guessed, so a
mismatch stays visible instead of being silently papered over.
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
    return read_manifest_version(Path(__file__).resolve().parents[1] / "package.json")


def user_agent(product="bookmark-research"):
    """Return the ``product/version`` user agent shared by outbound requests."""
    return product + "/" + release_version()
