"""Settings changes must apply to later calls in one long-lived MCP server.

The stdio server caches a Wiki store; a cached store used to keep the directory
that was configured when it was first built, so ``update_settings`` appeared to
succeed while reads and writes continued against the old location.
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mcp_server import StdioMcpServer
from settings import Settings


class WikiSettingsReloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wiki settings reload ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.settings = Settings(self.base / "settings.json")
        self.server = StdioMcpServer(self.base / "index.sqlite3", stderr=io.StringIO(), settings=self.settings)
        self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "wiki-settings-tests", "version": "1"}}})
        self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def call(self, name, arguments=None):
        response = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                       "params": {"name": name, "arguments": arguments or {}}})
        self.assertFalse(response["result"].get("isError"), response)
        return json.loads(response["result"]["content"][0]["text"])

    def test_wiki_directory_change_applies_without_restart(self):
        default = self.call("wiki_list")["directory"]
        moved = self.base / "moved wiki"
        changed = self.call("update_settings", {"changes": {"wiki": {"directory": str(moved)}}})
        self.assertEqual(str(moved), changed["settings"]["wiki"]["directory"])
        self.assertEqual(str(moved), self.call("wiki_list")["directory"])
        self.assertNotEqual(default, self.call("wiki_list")["directory"])

    def test_wiki_directory_reverts_when_the_setting_reverts(self):
        default = self.call("wiki_list")["directory"]
        moved = self.base / "other wiki"
        self.call("update_settings", {"changes": {"wiki": {"directory": str(moved)}}})
        self.assertEqual(str(moved), self.call("wiki_list")["directory"])
        self.call("update_settings", {"changes": {"wiki": {"directory": default}}})
        self.assertEqual(default, self.call("wiki_list")["directory"])

    def test_other_settings_sections_do_not_invalidate_the_wiki_store(self):
        moved = self.base / "stable wiki"
        self.call("update_settings", {"changes": {"wiki": {"directory": str(moved)}}})
        store = self.server._wiki()
        self.call("update_settings", {"changes": {"search": {"limit_per_target": 3}}})
        self.assertIs(store, self.server._wiki())


if __name__ == "__main__":
    unittest.main()
