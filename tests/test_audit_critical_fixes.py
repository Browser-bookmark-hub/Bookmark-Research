import copy
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bookmark_index import BookmarkIndex
from browser_client import BrowserClient
from mcp_server import TOOL_SCHEMAS
from raw_library import RawLibrary
from remote_mcp import McpError
from research import ResearchSessions
from research_plan import ResearchPlan
from search_results import fuse_results
from settings import Settings
from wiki import WikiStore


class AuditCriticalFixesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="br-audit-fixes-"))
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True)
        self.settings = Settings(self.root / "settings.json")
        self.wiki_dir = self.root / "wiki"
        self.wiki_dir.mkdir(parents=True)
        self.research_dir = self.root / "research"
        self.research_dir.mkdir(parents=True)
        self.settings.update({
            "output": {"directory": str(self.research_dir)},
            "wiki": {"directory": str(self.wiki_dir), "after_research": "auto"},
            "browser": {"enabled": True, "driver": "cdp"}
        })
        self.db_path = self.data_dir / "index.sqlite3"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_non_ascii_title_slug_falls_back_to_research_id(self):
        self.assertEqual(ResearchSessions._slug("中文研究标题", "r-0123456789abcdef"),
                         "r-0123456789abcdef")

    def test_research_auto_save_slug_and_merge(self):
        """Fix 1.1 & 5.1: Auto-save creates page using store._slug and merges existing sections."""
        sessions = ResearchSessions(directory=self.research_dir, settings=self.settings, db_path=self.db_path)
        store = WikiStore(self.wiki_dir, settings=self.settings, research_sessions=sessions)

        # 1. Pre-create a wiki page with 1 section
        quote = "Topic Alpha is a modern fast database system."
        initial_page = {
            "title": "Topic Alpha",
            "kind": "topic",
            "sections": [{
                "heading": "Existing Section",
                "text": quote,
                "citations": [{"source_id": "src1", "quote": quote}],
            }],
            "links": [],
            "review": {"method": "human", "reviewer": "tester", "note": "initial"}
        }
        slug = sessions._slug("Topic Alpha")
        rid = sessions.start("Topic Alpha", [{"id": "q1", "question": "What is Topic Alpha?"}])["research_id"]
        
        # Add a source and claim
        ev = sessions.import_evidence(rid, "op1", "q1", "https://alpha.test", quote, {"provider": "test", "kind": "page"})
        s_id = ev["sources"][0]["id"]
        sessions.record(rid, entries=[
            {"kind": "source_review", "source_id": s_id, "verdict": "accepted", "text": "ok"},
            {"kind": "claim", "question_id": "q1", "statement": quote, "inference": False,
             "citations": [{"source_id": s_id, "quote": quote}]},
            {"kind": "answer", "question_id": "q1", "answer": quote, "claim_ids": ["c1"]}
        ])
        
        # Write initial page to store using internal compile
        store.write(slug, initial_page, change_note="initial", expected_revision=0,
                    sources=[{"id": "src1", "url": "https://alpha.test", "text": quote}])

        # Now finish research session with policy='auto'
        res = sessions.finish(rid, "Research on Topic Alpha finished")
        follow_up = res.get("wiki_follow_up", {})
        written = follow_up.get("written_page")
        self.assertIsNone(written.get("error"))
        self.assertEqual(written.get("status"), "written")
        self.assertEqual(written.get("page_id"), slug)

        # Verify that the existing section was NOT wiped out and the new section was merged
        updated = store.get(slug)
        sections = updated["page"]["sections"]
        headings = [s["heading"] for s in sections]
        self.assertIn("Existing Section", headings)
        self.assertGreater(len(sections), 1, "Sections should have merged rather than replaced")

    def test_cdp_no_fake_body_or_title_as_body(self):
        """Fix 1.2: CDP driver rejects empty body and never returns title as text."""
        client = BrowserClient(settings=self.settings)
        # Mock _cdp_ws_evaluate to return empty text
        with mock.patch.object(client, "_cdp_ws_evaluate", return_value={"title": "Page Title", "text": ""}):
            with mock.patch("urllib.request.urlopen") as mock_url:
                mock_version = mock.MagicMock()
                mock_version.read.return_value = b'{"Browser": "Chrome/120.0"}'
                mock_version.__enter__.return_value = mock_version

                mock_new = mock.MagicMock()
                mock_new.read.return_value = b'{"id": "t1", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/page"}'
                mock_new.__enter__.return_value = mock_new

                mock_list = mock.MagicMock()
                mock_list.read.return_value = b'[{"id": "t1", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/page", "title": "Page Title"}]'
                mock_list.__enter__.return_value = mock_list

                mock_close = mock.MagicMock()
                mock_close.read.return_value = b'"Target closed"'
                mock_close.__enter__.return_value = mock_close

                mock_url.side_effect = [mock_version, mock_new, mock_list, mock_close]
                with self.assertRaises(McpError) as ctx:
                    client._render_cdp("https://example.test", timeout=5)
                self.assertIn("no usable body text", str(ctx.exception))

    def test_preflight_metrics_single_entry(self):
        """Fix 1.3: wiki_preflight logs exactly one metric entry with true hit_count."""
        wiki = mock.MagicMock()
        wiki.search_terms.return_value = [
            {"page_id": "p1", "title": "P1"},
            {"page_id": "p2", "title": "P2"},
            {"page_id": "p3", "title": "P3"},
        ]
        plan = ResearchPlan(settings=self.settings, wiki=wiki)
        results, err = plan.wiki_preflight(["term1", "term2"])
        self.assertEqual(len(results), 3)
        self.assertIsNone(err)
        # Verify _log_metric was called EXACTLY ONCE with hit_count=3
        self.assertEqual(wiki._log_metric.call_count, 1)
        wiki._log_metric.assert_called_once_with(
            "plan_research",
            page_id=None,
            page_ids=["p1", "p2", "p3"],
            hit_count=3,
            reused=True
        )

    def test_chinese_stopword_filtering(self):
        """Fix 3.1: Stopwords and particles (的, 和, 有哪些, 我) are eliminated from plan_terms."""
        t1 = BookmarkIndex.plan_terms("我的书签和笔记")
        self.assertEqual(t1, ["书签", "笔记"])

        t2 = BookmarkIndex.plan_terms("本地部署有哪些路径")
        self.assertEqual(t2, ["本地部署", "本地", "部署", "路径"])
        self.assertNotIn("有哪些", t2)
        self.assertNotIn("的", t2)
        self.assertNotIn("和", t2)

    def test_raw_library_date_sorting_order(self):
        """Fix 4.2: Missing retrieved_at (None) must be sorted last, not first."""
        archive_dir = self.root / "archive"
        archive_dir.mkdir()
        raw_db = self.root / "raw.sqlite3"
        raw = RawLibrary(db_path=raw_db, archive_directory=archive_dir, data_directory=self.data_dir, settings=self.settings)
        
        # Test versions sort logic
        versions = [
            {"sha256": "s1", "retrieved_at": None, "title": "No Date"},
            {"sha256": "s2", "retrieved_at": "2026-01-01T00:00:00Z", "title": "Old"},
            {"sha256": "s3", "retrieved_at": "2026-02-01T00:00:00Z", "title": "New"},
        ]
        versions.sort(key=lambda v: (v["retrieved_at"] is not None, v["retrieved_at"] or ""), reverse=True)
        self.assertEqual(versions[0]["title"], "New")
        self.assertEqual(versions[1]["title"], "Old")
        self.assertEqual(versions[2]["title"], "No Date")

    def test_mcp_search_providers_no_browser(self):
        """Fix 4.4: browser is fetch-only and must not be in search_web PROVIDERS."""
        self.assertNotIn("browser", Settings.PROVIDERS)
        self.assertIn("browser", Settings.FETCH_PROVIDERS)
        search_web_schema = TOOL_SCHEMAS["search_web"]["properties"]["providers"]
        allowed_enums = search_web_schema["items"]["enum"]
        self.assertNotIn("browser", allowed_enums)

    def test_import_evidence_inventory_validation(self):
        """Fix 5.2: Non-internal sessions reject inventory_ids when session has no inventory."""
        sessions = ResearchSessions(directory=self.root / "research", settings=self.settings, db_path=self.db_path)
        rid = sessions.start("Public Research", [{"id": "q1", "question": "Q?"}])["research_id"]
        with self.assertRaises(ValueError):
            sessions.import_evidence(rid, "op1", "q1", "https://example.test", "text", {"provider": "test"},
                                     inventory_ids=["fake-id"])

    def test_search_results_duplicate_urls_merged(self):
        """Fix 5.4: Cross-target duplicates are not counted in duplicate_urls_merged."""
        batch1 = {
            "target": "target-A", "provider": "exa", "query": "q1", "status": "ok",
            "results": [
                {"url": "https://example.com/same", "title": "Same", "rank": 1},
                {"url": "https://example.com/a1", "title": "A1", "rank": 2},
            ]
        }
        batch2 = {
            "target": "target-B", "provider": "exa", "query": "q2", "status": "ok",
            "results": [
                {"url": "https://example.com/same", "title": "Same", "rank": 1},
                {"url": "https://example.com/b1", "title": "B1", "rank": 2},
            ]
        }
        merged = fuse_results({"batches": [batch1, batch2], "targets": ["target-A", "target-B"]})
        dedup = merged["deduplication"]
        # 4 submitted, 2 in target A, 2 in target B -> within each target 0 duplicates merged
        self.assertEqual(dedup["duplicate_urls_merged"], 0)
        self.assertEqual(dedup["cross_target_shared_urls"], 1)
        self.assertEqual(dedup["unique_canonical_urls"], 3)

    def test_traverse_affected_sections_dedup_and_canonical_id(self):
        """Fix 5.5: affected_sections deduplicates by section_id and handles empty canonical_id."""
        with BookmarkIndex(self.db_path) as index:
            # Create sources, sections, canvas nodes, and edges
            index.connection.execute("INSERT INTO sources (source_id, package_path, created_at, last_sync) VALUES ('src1', '/pkg', '2026-01-01', '2026-01-01')")
            index.connection.execute(
                "INSERT INTO sections (source_id, section_id, file_path, section_type, label, slot, title, description_md, is_anchor, inherit_path, canonical_id, raw_json) "
                "VALUES ('src1', 'sec1', 'sec1.json', 'custom', 'Sec 1', 'slot1', 'Title 1', '', 0, NULL, NULL, '{}')"
            )
            # Insert 3 bookmarks into sec1
            for i in range(1, 4):
                index.connection.execute(
                    "INSERT INTO items (source_id, section_id, item_id, item_type, position, preorder, title, url, note, tag_text, tags_json, path_json, folder_path, ancestor_ids_json, raw_json, metadata_json) "
                    f"VALUES ('src1', 'sec1', 'b{i}', 'bookmark', {i}, {i}, 'B{i}', 'http://{i}', '', '', '[]', '[]', '', '[]', '{{}}', '{{}}')"
                )

            # Insert canvas nodes pointing to sec1
            index.connection.execute("INSERT INTO nodes (source_id, canvas_path, node_id, node_type, section_id, label, text, x, y, width, height, position, raw_json) VALUES ('src1', 'c.canvas', 'start', 'text', NULL, 'Start', 'Hello', 0, 0, 100, 100, 1, '{}')")
            index.connection.execute("INSERT INTO nodes (source_id, canvas_path, node_id, node_type, section_id, label, text, x, y, width, height, position, raw_json) VALUES ('src1', 'c.canvas', 'node1', 'card', 'sec1', 'Card 1', '', 0, 0, 100, 100, 2, '{}')")
            index.connection.execute("INSERT INTO nodes (source_id, canvas_path, node_id, node_type, section_id, label, text, x, y, width, height, position, raw_json) VALUES ('src1', 'c.canvas', 'node2', 'card', 'sec1', 'Card 1 copy', '', 0, 0, 100, 100, 3, '{}')")

            # Connect start -> node1 and start -> node2
            index.connection.execute("INSERT INTO edges (source_id, canvas_path, edge_id, from_node, to_node, from_end, to_end, label, raw_json) VALUES ('src1', 'c.canvas', 'e1', 'start', 'node1', 'none', 'arrow', '', '{}')")
            index.connection.execute("INSERT INTO edges (source_id, canvas_path, edge_id, from_node, to_node, from_end, to_end, label, raw_json) VALUES ('src1', 'c.canvas', 'e2', 'start', 'node2', 'none', 'arrow', '', '{}')")
            index.connection.commit()

            res = index.traverse("src1", node_id="start", max_depth=2)
            aff_secs = res["affected_sections"]
            # Both node1 and node2 point to sec1; affected_sections should contain sec1 EXACTLY ONCE
            self.assertEqual(len(aff_secs), 1)
            self.assertEqual(aff_secs[0]["section_id"], "sec1")
            # And bookmark_count must be 3 (not 0, even though canonical_id was NULL)
            self.assertEqual(aff_secs[0]["bookmark_count"], 3)


if __name__ == "__main__":
    unittest.main()
