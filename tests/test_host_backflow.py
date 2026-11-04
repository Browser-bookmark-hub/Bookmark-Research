"""Tests for the host search backflow contract and results fusion (P2-2)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archive import SourceArchive
from raw_library import RawLibrary
from search_results import fuse_results
from settings import Settings


class TestHostBackflow(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.settings = Settings(self.base / "settings.json")
        self.archive_dir = str(self.base / "knowledge")
        self.settings.update({"archive": {"directory": self.archive_dir}})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_fuse_results_deduplication_and_backflow_contract(self):
        # Two providers returning overlapping URLs and one duplicate content across different URLs
        payload = {
            "query": "vector databases",
            "streams": [
                {
                    "provider": "claude_web_search",
                    "results": [
                        {
                            "title": "Chroma DB Overview",
                            "url": "https://example.com/chroma#features",
                            "snippet": "Chroma is an open-source AI application database for embeddings.",
                        },
                        {
                            "title": "Milvus Vector DB",
                            "url": "https://example.com/milvus",
                            "snippet": "Milvus is a cloud-native vector database built for scale.",
                        },
                    ],
                },
                {
                    "provider": "search_web",
                    "results": [
                        {
                            "title": "Chroma DB Guide",
                            "url": "https://example.com/chroma",  # Same canonical URL
                            "snippet": "Chroma is an open-source AI application database for embeddings.",
                        },
                        {
                            "title": "Milvus Mirror",
                            "url": "https://mirror.example.com/milvus",  # Different URL, identical snippet
                            "snippet": "Milvus is a cloud-native vector database built for scale.",
                        },
                    ],
                },
            ],
        }

        fused = fuse_results(payload, archive=False, settings=self.settings)

        self.assertEqual(fused["backflow_contract"], "normalized_host_search_v1")
        self.assertIn("deduplication", fused)
        dedup = fused["deduplication"]
        self.assertEqual(dedup["submitted_results"], 4)
        self.assertEqual(dedup["unique_canonical_urls"], 3)
        self.assertEqual(dedup["duplicate_urls_merged"], 1)

        # Check content duplicates detection: chroma has 2 duplicates, milvus has 2 duplicates
        self.assertEqual(dedup["unique_content_hashes"], 2)
        content_dups = dedup["content_duplicates"]
        self.assertTrue(len(content_dups) >= 1)

        # Check ranked items
        items = fused["targets"][0]["results"]
        self.assertEqual(len(items), 3)

        # Chroma should be corroborated across both providers
        chroma = next(item for item in items if "chroma" in item["url"])
        self.assertTrue(chroma["corroborated"])
        self.assertIn("claude_web_search", chroma["providers"])
        self.assertIn("search_web", chroma["providers"])
        self.assertTrue(chroma["sha256"])

    def test_fuse_results_archival_and_raw_library_indexing(self):
        payload = {
            "query": "distributed consensus raft",
            "streams": [
                {
                    "provider": "host_codex",
                    "results": [
                        {
                            "title": "In Search of an Understandable Consensus Algorithm",
                            "url": "https://raft.github.io/raft.pdf",
                            "snippet": "Raft is a consensus algorithm for managing a replicated log.",
                        },
                        {
                            "title": "Raft GitHub Organization",
                            "url": "https://github.com/raft",
                            "snippet": "Open source implementations of the Raft consensus algorithm.",
                        },
                    ],
                }
            ],
        }

        fused = fuse_results(payload, archive=True, archive_dir=self.archive_dir, settings=self.settings)

        self.assertIn("archive", fused)
        arc = fused["archive"]
        self.assertEqual(arc["status"], "saved")
        self.assertTrue(arc["capture_id"])
        self.assertEqual(arc["pages_archived"], 2)

        # Verify capture directory on disk
        capture_path = Path(arc["directory"])
        self.assertTrue(capture_path.is_dir())
        self.assertTrue((capture_path / "manifest.json").is_file())
        self.assertTrue((capture_path / "response.json").is_file())

        manifest = json.loads((capture_path / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["capture_type"], "host_search_batch")
        self.assertEqual(manifest["query"], "distributed consensus raft")
        self.assertEqual(len(manifest["pages"]), 2)

        # Verify pages are saved content-addressed in pages/<sha256>.md
        pages_dir = Path(self.archive_dir) / "pages"
        self.assertTrue(pages_dir.is_dir())
        md_files = list(pages_dir.glob("*.md"))
        self.assertEqual(len(md_files), 2)

        # Verify RawLibrary can search these backflowed results immediately
        raw_lib = RawLibrary(archive_directory=self.archive_dir, data_directory=self.base, settings=self.settings)
        search_res = raw_lib.search(query="consensus algorithm")
        self.assertTrue(search_res["results"])
        hits = search_res["results"]
        urls = [h["url"] for h in hits]
        self.assertIn("https://raft.github.io/raft.pdf", urls)

    def test_mcp_server_merge_search_results_tool(self):
        from mcp_server import StdioMcpServer

        self.settings.update({"tool_scope_preset": "all"})
        server = StdioMcpServer(self.base / "index.sqlite3", settings=self.settings)
        server.ready = True

        call_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "merge_search_results",
                "arguments": {
                    "batches": [
                        {
                            "target": "local-first",
                            "provider": "host_claude",
                            "query": "local first software",
                            "status": "ok",
                            "results": [
                                {
                                    "title": "Ink & Switch Local-First",
                                    "url": "https://inkandswitch.com/local-first",
                                    "snippet": "Local-first software: You own your data, in spite of the cloud.",
                                }
                            ],
                        }
                    ],
                    "archive": True,
                },
            },
        }

        resp = server.handle(call_req)
        self.assertNotIn("error", resp)
        result_text = resp["result"]["content"][0]["text"]
        result = json.loads(result_text)

        self.assertEqual(result["backflow_contract"], "normalized_host_search_v1")
        self.assertEqual(result["archive"]["status"], "saved")
        results = result["targets"][0]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://inkandswitch.com/local-first")


if __name__ == "__main__":
    unittest.main()
