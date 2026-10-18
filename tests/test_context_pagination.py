"""Large canvas views remain readable while inventories and counts stay complete."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from mcp_server import MAX_RESULT_CHARS, StdioMcpServer
from settings import Settings
from source_manager import SourceManager


class ContextPaginationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.root / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.db = self.root / "index.sqlite3"

    def test_mcp_can_read_all_5000_nodes_without_overflow_or_narrowing_the_inventory(self):
        package = self.root / "package"
        package.mkdir()
        nodes = [{"id": "n-%04d" % i, "type": "text", "text": "Context %d " % i + "x" * 200,
                  "x": i * 100, "y": 0, "width": 100, "height": 100} for i in range(5000)]
        (package / "map.canvas").write_text(json.dumps({"nodes": nodes, "edges": []}), encoding="utf-8")
        with BookmarkIndex(self.db) as index:
            sid = SourceManager(index).sync(package, mode="snapshot")["source_id"]
            frozen = index.inventory([sid])
            self.assertGreater(len(json.dumps(index.context(sid))), MAX_RESULT_CHARS)
        server = StdioMcpServer(self.db, settings=Settings(self.root / "settings.json"))
        self.addCleanup(server.close)
        server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                       "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                  "clientInfo": {"name": "fixture", "version": "1"}}})
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        def context(**arguments):
            response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "get_context", "arguments": {"source_id": sid, "refresh": False, **arguments}}})
            self.assertFalse(response["result"]["isError"], response)
            return response["result"]["structuredContent"]
        first = context()
        self.assertEqual(200, len(first["nodes"]))
        self.assertEqual(5000, first["pagination"]["nodes"]["total"])
        identifiers, offset = [], 0
        while offset is not None:
            page = context(collection="nodes", offset=offset, limit=333)
            identifiers.extend(row["node_id"] for row in page["nodes"])
            offset = page["pagination"]["nodes"]["next_offset"]
            self.assertNotIn("sections", page)
        self.assertEqual([row["id"] for row in nodes], identifiers)
        with BookmarkIndex(self.db) as index:
            current = index.inventory([sid])
            self.assertEqual(frozen["input_version"], current["input_version"])
            self.assertEqual(5000, len(current["nodes"]))

    def test_items_page_says_why_it_is_empty_instead_of_a_bare_zero(self):
        package = self.root / "A-1.json"
        package.write_text(json.dumps({"format": "bookmark-canvas-section", "schemaVersion": 2,
            "id": "temp-section-A-1", "sectionType": "temporary", "label": "A-1", "title": "References",
            "items": [{"id": "b%d" % i, "sectionId": "temp-section-A-1", "type": "bookmark",
                       "title": "Lumen %d" % i, "url": "https://example.test/%d" % i} for i in range(2)]}),
            encoding="utf-8")
        with BookmarkIndex(self.db) as index:
            sid = SourceManager(index).sync(package, mode="snapshot")["source_id"]
            item_id = index.search(sid, targets=["Lumen"])["results"][0]["item_id"]
        server = StdioMcpServer(self.db, settings=Settings(self.root / "settings.json"))
        self.addCleanup(server.close)
        server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                       "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                  "clientInfo": {"name": "fixture", "version": "1"}}})
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

        def context(**arguments):
            response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "get_context", "arguments": {"source_id": sid, "refresh": False, **arguments}}})
            self.assertFalse(response["result"]["isError"], response)
            return response["result"]["structuredContent"]

        # The unscoped response shows the card's bookmarks do exist: the zero was
        # a scope that needs one more parameter, not an empty tree.
        overview = context()
        self.assertEqual(2, overview["sections"][0]["bookmark_count"])
        self.assertIn("item_id", overview["pagination"]["items"]["scope_note"])
        self.assertEqual(0, overview["pagination"]["items"]["total"])
        page = context(collection="items")
        self.assertEqual(0, page["pagination"]["items"]["total"])
        self.assertIn("item_id", page["pagination"]["items"]["scope_note"])
        self.assertIn("search_bookmarks", page["pagination"]["items"]["scope_note"])
        self.assertIn("plan_research", page["pagination"]["items"]["scope_note"])
        scoped = context(collection="items", item_id=item_id)
        self.assertNotIn("scope_note", scoped["pagination"]["items"])
        self.assertEqual(["Lumen 0"], [row["title"] for row in scoped["items"]])

    def test_single_target_search_shares_counts_and_section_metadata_work(self):
        package = self.root / "A-1.json"
        package.write_text(json.dumps({"format": "bookmark-canvas-section", "schemaVersion": 2,
            "id": "temp-section-A-1", "sectionType": "temporary", "label": "A-1", "title": "References",
            "items": [{"id": "b%d" % i, "sectionId": "temp-section-A-1", "type": "bookmark",
                       "title": "Lumen %d" % i, "url": "https://example.test/%d" % i} for i in range(51)]}),
            encoding="utf-8")
        with BookmarkIndex(self.db) as index:
            sid = SourceManager(index).sync(package, mode="snapshot")["source_id"]
            statements = []
            index.connection.set_trace_callback(statements.append)
            result = index.search(sid, targets=["Lumen"], offset=20, limit=20)
            index.connection.set_trace_callback(None)
        self.assertEqual(51, result["total"])
        self.assertEqual(20, len(result["results"]))
        self.assertEqual(result["results"], result["targets"][0]["results"])
        self.assertEqual(1, sum("SELECT label,file_path FROM sections" in sql for sql in statements))
        self.assertEqual(1, sum("count(*) OVER ()" in sql for sql in statements))


if __name__ == "__main__":
    unittest.main()
