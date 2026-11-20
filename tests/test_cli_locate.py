"""CLI coverage for the shared Canvas locate primitive."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cli
from mcp_server import StdioMcpServer
from ref_codec import clear as clear_refs
from settings import Settings


class CliLocateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-cli-locate-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "Package" / "临时栏目" / "常规链式"
        self.package.mkdir(parents=True)
        document = {
            "format": "bookmark-canvas-section", "schemaVersion": 2,
            "sectionType": "temporary", "id": "temp-section-A-1",
            "label": "A-1", "title": "Test",
            "items": [{"id": "fixture-folder", "sectionId": "temp-section-A-1", "type": "folder",
                "title": "Collection", "children": [
                    {"id": "one", "sectionId": "temp-section-A-1", "type": "bookmark",
                     "title": "Needle one", "url": "https://example.test/one"},
                    {"id": "two", "sectionId": "temp-section-A-1", "type": "bookmark",
                     "title": "Needle two", "url": "https://example.test/two"},
                ]}],
        }
        (self.package / "A-1 demo.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        self.db = self.root / "index.sqlite3"
        self.config = self.root / "settings.json"

    def run_cli(self, *arguments):
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = cli.main(["--db", str(self.db), "--config", str(self.config), *arguments])
        return code, json.loads(output.getvalue())

    def run_cli_process(self, *arguments):
        process = subprocess.run(
            [sys.executable, str(Path(cli.__file__).resolve()),
             "--db", str(self.db), "--config", str(self.config), *arguments],
            capture_output=True, text=True, check=False)
        if process.returncode:
            self.fail("CLI exited %s: %s" % (process.returncode, process.stderr or process.stdout))
        return process.returncode, json.loads(process.stdout)

    def test_locate_and_continuation_use_shared_core(self):
        code, synced = self.run_cli("sync", str(self.root / "Package"), "--source-id", "fixture", "--mode", "live")
        self.assertEqual(0, code)
        self.assertEqual("fixture", synced["source_id"])

        code, first = self.run_cli_process("locate", "--text", "Needle", "--source-id", "fixture",
                                           "--limit", "1", "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual(2, first["total"])
        self.assertEqual(1, len(first["hits"]))
        self.assertEqual(1, first["more"]["offset"])
        self.assertTrue(first["more"]["handle"].startswith("lh1."))

        # A fresh interpreter has no shared Python state with the first call.
        code, second = self.run_cli_process("locate", "--handle", first["more"]["handle"],
                                            "--offset", "1")
        self.assertEqual(0, code)
        self.assertEqual(1, len(second["hits"]))
        self.assertNotEqual(first["hits"][0]["ref"], second["hits"][0]["ref"])

    def test_mcp_and_cli_locate_hits_are_byte_identical(self):
        code, synced = self.run_cli("sync", str(self.root / "Package"), "--source-id", "fixture", "--mode", "live")
        self.assertEqual(0, code)
        self.assertEqual("fixture", synced["source_id"])

        code, cli_result = self.run_cli_process("locate", "--text", "Needle", "--in", "canvas",
                                                "--source-id", "fixture", "--limit", "8", "--no-refresh")
        self.assertEqual(0, code)

        clear_refs()
        server = StdioMcpServer(self.db, stderr=io.StringIO(), settings=Settings(self.config))
        self.addCleanup(server.close)
        initialized = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "bookmark-tests", "version": "1.0"}}})
        self.assertNotIn("error", initialized)
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "locate", "arguments": {"text": "Needle", "in": ["canvas"],
                       "source_id": "fixture", "limit": 8, "refresh": False}}})
        self.assertNotIn("error", response)
        mcp_result = json.loads(response["result"]["content"][0]["text"])

        encode_hits = lambda hits: json.dumps(hits, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertEqual(encode_hits(cli_result["hits"]), encode_hits(mcp_result["hits"]))

    def test_cli_short_ref_reads_in_a_fresh_process(self):
        code, synced = self.run_cli("sync", str(self.root / "Package"), "--source-id", "fixture", "--mode", "live")
        self.assertEqual(0, code)
        self.assertEqual("fixture", synced["source_id"])

        code, located = self.run_cli_process("locate", "--text", "Needle", "--source-id", "fixture",
                                             "--limit", "1", "--no-refresh")
        self.assertEqual(0, code)
        ref = located["hits"][0]["ref"]

        code, context = self.run_cli_process("read", ref, "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual("fixture", context["source_id"])
        self.assertEqual(["one"], [item["item"] for item in context["items"]])

    def test_cli_locate_lists_direct_folder_children(self):
        code, synced = self.run_cli("sync", str(self.root / "Package"), "--source-id", "fixture", "--mode", "live")
        self.assertEqual(0, code)
        self.assertEqual("fixture", synced["source_id"])

        code, result = self.run_cli_process("locate", "--source-id", "fixture", "--folder-id",
                                           "fixture-folder", "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual("folder_children", result["match_mode"])
        self.assertEqual(["one", "two"], [hit["item_id"] for hit in result["hits"]])

    def write_package(self, items):
        document = {
            "format": "bookmark-canvas-section", "schemaVersion": 2,
            "sectionType": "temporary", "id": "temp-section-A-1",
            "label": "A-1", "title": "Test", "items": items}
        (self.package / "A-1 demo.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def sync_package(self):
        code, synced = self.run_cli("sync", str(self.root / "Package"), "--source-id", "fixture", "--mode", "live")
        self.assertEqual(0, code)
        self.assertEqual("fixture", synced["source_id"])

    def test_locate_url_falls_back_to_normalized_then_prefix_matches(self):
        self.write_package([
            {"id": "gh", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "CodeGraph", "url": "https://github.com/colbymchenry/codegraph"},
            {"id": "deep", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "Deep", "url": "https://github.com/colbymchenry/codegraph/wiki/page"},
        ])
        self.sync_package()

        code, exact = self.run_cli_process("locate", "--url", "https://github.com/colbymchenry/codegraph",
                                           "--source-id", "fixture", "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual("exact", exact["match_mode"])
        self.assertEqual(["gh"], [hit["item_id"] for hit in exact["hits"]])
        self.assertEqual("exact", exact["hits"][0]["why"]["match_mode"])

        code, loose = self.run_cli_process("locate", "--url", "github.com/colbymchenry/codegraph",
                                           "--source-id", "fixture", "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual("url_prefix", loose["match_mode"])
        self.assertEqual(["gh", "deep"], [hit["item_id"] for hit in loose["hits"]])
        self.assertEqual("url_normalized", loose["hits"][0]["why"]["match_mode"])
        self.assertEqual("url_prefix", loose["hits"][1]["why"]["match_mode"])

        code, www = self.run_cli_process("locate", "--url", "www.github.com/colbymchenry/codegraph",
                                         "--source-id", "fixture", "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual("url_prefix", www["match_mode"])
        self.assertEqual(["gh", "deep"], [hit["item_id"] for hit in www["hits"]])

        code, missing = self.run_cli_process("locate", "--url", "https://no-such.test/absent",
                                             "--source-id", "fixture", "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual(0, missing["total"])
        self.assertIn("No exact URL matches", missing["next"])

    def test_locate_ranks_by_phrase_and_query_coverage(self):
        self.write_package([
            {"id": "folder", "sectionId": "temp-section-A-1", "type": "folder",
             "title": "harness engineering", "children": [
                 {"id": "shared", "sectionId": "temp-section-A-1", "type": "bookmark",
                  "title": "Harness 分享", "url": "https://example.test/shared"},
             ]},
            {"id": "article", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "Codex article", "url": "https://example.com/index/harness-engineering/"},
            {"id": "blog", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "Engineering blog", "url": "https://example.test/blog"},
        ])
        self.sync_package()

        code, located = self.run_cli_process("locate", "--text", "harness engineering",
                                             "--source-id", "fixture", "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual("article", located["hits"][0]["item_id"])
        self.assertTrue(located["hits"][0]["why"]["phrase"])
        self.assertEqual(2, located["hits"][0]["why"]["coverage"])
        for hit in located["hits"]:
            self.assertIn("coverage", hit["why"])
            self.assertIn("phrase", hit["why"])
            self.assertIn("parent_id", hit)
            self.assertIn("path", hit)

        self.write_package([
            {"id": "one-cn", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "个人开发的扩展助手", "url": "https://example.test/cn-one"},
            {"id": "two-cn", "sectionId": "temp-section-A-1", "type": "bookmark",
             "title": "本地知识库工具", "url": "https://example.test/cn-two"},
        ])
        self.sync_package()
        code, chinese = self.run_cli_process("locate", "--text", "个人知识库",
                                             "--source-id", "fixture", "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual("two-cn", chinese["hits"][0]["item_id"])
        self.assertEqual(2, chinese["hits"][0]["why"]["coverage"])
        self.assertFalse(chinese["hits"][0]["why"]["phrase"])

        # A single-term query keeps the weight-first ordering of before.
        code, single = self.run_cli_process("locate", "--text", "知识库",
                                            "--source-id", "fixture", "--no-refresh")
        self.assertEqual(0, code)
        self.assertEqual("two-cn", single["hits"][0]["item_id"])
        self.assertFalse(single["hits"][0]["why"]["phrase"])

    def test_readonly_cli_continuation_uses_temp_key_when_database_directory_is_unwritable(self):
        code, synced = self.run_cli("sync", str(self.root / "Package"), "--source-id", "fixture", "--mode", "live")
        self.assertEqual(0, code)
        self.assertEqual("fixture", synced["source_id"])

        blocker = self.root / "not-a-directory"
        blocker.write_text("block", encoding="utf-8")
        fallback_tmp = self.root / "fallback-tmp"
        with patch("locate._handle_key_path", return_value=blocker / "key"), \
                patch("locate.tempfile.gettempdir", return_value=str(fallback_tmp)):
            code, first = self.run_cli("locate", "--text", "Needle", "--source-id", "fixture",
                                       "--limit", "1", "--no-refresh")
            self.assertEqual(0, code)
            self.assertIn("more", first)

            code, second = self.run_cli("locate", "--handle", first["more"]["handle"],
                                        "--offset", "1", "--no-refresh")
            self.assertEqual(0, code)
            self.assertEqual(1, len(second["hits"]))
            self.assertNotEqual(first["hits"][0]["ref"], second["hits"][0]["ref"])


if __name__ == "__main__":
    unittest.main()
