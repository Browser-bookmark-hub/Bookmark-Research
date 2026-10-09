"""Release identity stays on one source: the published package manifest.

These tests fail a release bump that forgets a manifest, and they compare the
real MCP handshake against the manifest instead of trusting a constant.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from release import UNKNOWN_VERSION, read_manifest_version, release_version, user_agent
from mcp_server import StdioMcpServer

import io
from settings import Settings


def manifest_version(relative):
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if relative.endswith("marketplace.json"):
        return value["plugins"][0]["source"]["version"]
    return value["version"]


class ReleaseVersionTests(unittest.TestCase):
    def test_runtime_version_matches_package_manifest(self):
        self.assertEqual(manifest_version("package.json"), release_version())

    def test_published_manifests_agree_with_package_manifest(self):
        expected = manifest_version("package.json")
        self.assertEqual(expected, manifest_version(".codex-plugin/plugin.json"))
        self.assertEqual(expected, manifest_version(".agents/plugins/marketplace.json"))

    def test_user_agent_carries_the_manifest_version(self):
        self.assertEqual("bookmark-research/" + manifest_version("package.json"), user_agent())

    def test_no_hardcoded_release_version_remains_in_runtime_sources(self):
        # release.py is the only allowed owner of the release version; the exact
        # published version reappearing in another module is the drift this
        # module exists to remove.
        expected = manifest_version("package.json")
        offenders = []
        for directory in ("src", "hosts", "bin", "scripts"):
            for path in sorted((ROOT / directory).rglob("*")):
                if not path.is_file() or path.suffix not in (".py", ".js", ".mjs", ".cjs"):
                    continue
                if path.name == "release.py":
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if expected in line:
                        offenders.append("%s:%d: %s" % (path.relative_to(ROOT), number, line.strip()[:80]))
        self.assertEqual([], offenders, "hardcoded release version: " + "; ".join(offenders))

    def test_unknown_version_is_reported_rather_than_guessed(self):
        with tempfile.TemporaryDirectory(prefix="bookmark-release-") as name:
            base = Path(name)
            self.assertEqual(UNKNOWN_VERSION, read_manifest_version(base / "package.json"))
            broken = base / "package.json"
            broken.write_text("{not json", encoding="utf-8")
            self.assertEqual(UNKNOWN_VERSION, read_manifest_version(broken))
            broken.write_text(json.dumps({"version": "   "}), encoding="utf-8")
            self.assertEqual(UNKNOWN_VERSION, read_manifest_version(broken))
            broken.write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            self.assertEqual("1.2.3", read_manifest_version(broken))

    def test_mcp_handshake_reports_the_manifest_version(self):
        with tempfile.TemporaryDirectory(prefix="bookmark-release-mcp-") as name:
            base = Path(name)
            server = StdioMcpServer(base / "index.sqlite3", stderr=io.StringIO(),
                                    settings=Settings(base / "settings.json"))
            response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "release-tests", "version": "1"}}})
            self.assertEqual("bookmark-research", response["result"]["serverInfo"]["name"])
            self.assertEqual(manifest_version("package.json"),
                             response["result"]["serverInfo"]["version"])


if __name__ == "__main__":
    unittest.main()
