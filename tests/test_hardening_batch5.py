"""Hardening Batch 5 tests.

Covers:
- P3-2: Archive URL grouping in RawLibrary.search (expand_versions=False vs True)
- P3-3: Bookmark-level citations in WikiStore._compile_page & wiki_get
- P3-4: Wiki search ranking with title/heading weights, IDF normalization & configurable aliases
- P0-3: Wiki append-only metrics logging & metrics_summary
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from raw_library import RawLibrary
from research import ResearchSessions
from research_plan import ResearchPlan
from settings import Settings
from wiki import WikiStore
from wiki_search import WikiSearchIndex


class HardeningBatch5Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="hardening-batch5-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name).resolve()

        self.data_dir = self.root / "data"
        patcher = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.data_dir)})
        patcher.start()
        self.addCleanup(patcher.stop)

        self.db_path = self.root / "index.sqlite3"
        self.index = BookmarkIndex(self.db_path)
        self.addCleanup(self.index.close)

        self.settings = Settings(self.root / "settings.json")
        self.archive_dir = self.root / "archive"
        self.research_dir = self.root / "research"
        self.wiki_dir = self.root / "wiki"
        self.settings.update({
            "archive": {"directory": str(self.archive_dir)},
            "output": {"directory": str(self.research_dir)},
            "wiki": {"directory": str(self.wiki_dir)},
        })

        self.research = ResearchSessions(self.research_dir, settings=self.settings, db_path=self.db_path)
        self.wiki = WikiStore(self.wiki_dir, settings=self.settings, research_sessions=self.research)
        self.raw = RawLibrary(db_path=self.root / "raw.sqlite3", archive_directory=self.archive_dir, data_directory=self.data_dir, settings=self.settings)

    def test_p3_2_archive_url_grouping(self):
        """P3-2: RawLibrary.search groups by URL by default, or expands when expand_versions=True."""
        from archive import SourceArchive
        archive = SourceArchive(self.archive_dir)
        url = "https://example.test/product"
        archive.save({
            "provider": "exa", "tool": "web_fetch_exa", "urls": [url],
            "result": {"structuredContent": {"url": url, "title": "Product Alpha", "text": "First capture body version alpha pricing details."}},
            "retrieved_at": "2026-01-01T10:00:00Z", "request_arguments": {"urls": [url]}, "requested_max_characters": 12000
        })
        archive.save({
            "provider": "exa", "tool": "web_fetch_exa", "urls": [url],
            "result": {"structuredContent": {"url": url, "title": "Product Beta", "text": "Second capture body version beta pricing details."}},
            "retrieved_at": "2026-01-05T10:00:00Z", "request_arguments": {"urls": [url]}, "requested_max_characters": 12000
        })
        self.raw.refresh()

        # Default search: expand_versions=False (grouped by URL)
        grouped = self.raw.search("pricing", expand_versions=False)
        self.assertEqual(grouped["total"], 1, "Should group the two versions under 1 URL result")
        res = grouped["results"][0]
        self.assertEqual(res["url"], url)
        self.assertEqual(res["version_count"], 2)
        self.assertIn("time_span", res)
        self.assertEqual(res["time_span"]["earliest"], "2026-01-01T10:00:00Z")
        self.assertEqual(res["time_span"]["latest"], "2026-01-05T10:00:00Z")
        self.assertEqual(len(res["versions"]), 2)

        # Expanded search: expand_versions=True (individual sha256 entries)
        expanded = self.raw.search("pricing", expand_versions=True)
        self.assertEqual(expanded["total"], 2, "Should return 2 distinct versions when expanded")
        self.assertEqual(len({r["sha256"] for r in expanded["results"]}), 2)

    def _seed_bookmark_item(self, source_id, section_id, item_id, url):
        self.index.connection.execute(
            "INSERT OR IGNORE INTO sources(source_id, package_path, created_at, last_sync) VALUES(?,?,'2026-01-01','2026-01-01')",
            (source_id, str(self.root / "pkg"))
        )
        self.index.connection.execute(
            "INSERT OR IGNORE INTO sections(source_id, section_id, file_path, section_type, label, slot, title, description_md, is_anchor, raw_json) "
            "VALUES(?,?,'file.json','temporary','Label','','Title','',0,'{}')",
            (source_id, section_id)
        )
        self.index.connection.execute(
            "INSERT OR REPLACE INTO items(source_id, section_id, item_id, item_type, position, preorder, title, url, note, tags_json, tag_text, path_json, folder_path, ancestor_ids_json, raw_json, metadata_json) "
            "VALUES(?,?,?,'bookmark',0,0,'Title',?,'','[]','','[]','','[]','{}','{}')",
            (source_id, section_id, item_id, url)
        )
        self.index.connection.commit()

    def test_p3_3_bookmark_level_citations_in_wiki(self):
        """P3-3: sources parameter allows bookmark_refs and inventory_ids, verifies existence and URL match."""
        source_id, section_id, item_id = "src-demo", "sec-1", "bkmk-101"
        url = "https://example.test/verified-article"
        self._seed_bookmark_item(source_id, section_id, item_id, url)

        # 1. Rejecting non-existent bookmark ref
        bad_sources = [{
            "id": "s-bad",
            "url": url,
            "text": "Article content for testing citations.",
            "bookmark_refs": [{"source_id": source_id, "section_id": section_id, "item_id": "non-existent-id"}]
        }]
        bad_page = {
            "title": "Bad Ref Page",
            "kind": "topic",
            "sections": [{
                "heading": "Intro",
                "text": "Article content for testing citations.",
                "citations": [{"source_id": "s-bad", "quote": "Article content"}]
            }],
            "links": [],
            "review": {"method": "model", "reviewer": "tester", "note": "verifying"}
        }
        with self.assertRaisesRegex(ValueError, "Bookmark reference does not exist"):
            self.wiki.write("bad-page", bad_page, "Should fail", sources=bad_sources)

        # 2. Rejecting URL mismatch between bookmark item and source url
        mismatched_sources = [{
            "id": "s-mismatch",
            "url": "https://example.test/completely-different-url",
            "text": "Different content for mismatch test.",
            "bookmark_refs": [{"source_id": source_id, "section_id": section_id, "item_id": item_id}]
        }]
        mismatch_page = {
            "title": "Mismatch Page",
            "kind": "topic",
            "sections": [{
                "heading": "Intro",
                "text": "Different content for mismatch test.",
                "citations": [{"source_id": "s-mismatch", "quote": "Different content"}]
            }],
            "links": [],
            "review": {"method": "model", "reviewer": "tester", "note": "verifying"}
        }
        with self.assertRaisesRegex(ValueError, "does not match source URL|belongs to"):
            self.wiki.write("mismatch-page", mismatch_page, "Should fail", sources=mismatched_sources)

        # 3. Successful write with valid bookmark_refs & inventory_ids
        valid_sources = [{
            "id": "s-good",
            "url": url,
            "text": "Article content for testing citations.",
            "bookmark_refs": [{"source_id": source_id, "section_id": section_id, "item_id": item_id}],
            "inventory_ids": ["inv-item-1"]
        }]
        valid_page = {
            "title": "Valid Ref Page",
            "kind": "topic",
            "sections": [{
                "heading": "Intro",
                "text": "Article content for testing citations.",
                "citations": [{"source_id": "s-good", "quote": "Article content"}]
            }],
            "links": [],
            "review": {"method": "model", "reviewer": "tester", "note": "verifying"}
        }
        receipt = self.wiki.write("good-page", valid_page, "Valid citation test", sources=valid_sources)
        self.assertEqual(receipt["status"], "written")

        # 4. Check that wiki_get exposes the bookmark_refs on the citations
        fetched = self.wiki.get("good-page")
        evidence = fetched["evidence"]
        self.assertTrue(len(evidence) >= 1)
        citation = evidence[0]["citations"][0]
        self.assertEqual(citation["url"], url)
        self.assertEqual(len(citation["bookmark_refs"]), 1)
        self.assertEqual(citation["bookmark_refs"][0]["item_id"], item_id)
        self.assertEqual(citation["bookmark_refs"][0]["source_id"], source_id)
        self.assertEqual(citation["bookmark_refs"][0]["section_id"], section_id)
        self.assertIn("inv-item-1", citation["inventory_ids"])

    def test_p3_4_wiki_search_ranking_and_aliases(self):
        """P3-4: WikiSearchIndex ranking weights title (+15) and headings (+8), normalizes by doc_freq, and respects aliases."""
        # Create page 1 with keyword in Title
        p1 = {
            "title": "PostgreSQL Architecture Guide",
            "kind": "topic",
            "sections": [{"heading": "Overview", "text": "Details about relational database internals and replication.",
                          "citations": [{"source_id": "s1", "quote": "relational database"}]}],
            "links": [],
            "review": {"method": "model", "reviewer": "test", "note": "ok"}
        }
        s1 = [{"id": "s1", "url": "https://example.test/pg", "text": "relational database internals"}]
        self.wiki.write("pg-guide", p1, "seed", sources=s1)

        # Create page 2 with keyword in Heading
        p2 = {
            "title": "Database Overview",
            "kind": "topic",
            "sections": [{"heading": "PostgreSQL", "text": "PostgreSQL storage and write-ahead logs.",
                          "citations": [{"source_id": "s2", "quote": "write-ahead logs"}]}],
            "links": [],
            "review": {"method": "model", "reviewer": "test", "note": "ok"}
        }
        s2 = [{"id": "s2", "url": "https://example.test/db", "text": "write-ahead logs storage"}]
        self.wiki.write("db-overview", p2, "seed", sources=s2)

        # Create page 3 with keyword only in Body
        p3 = {
            "title": "General Notes",
            "kind": "topic",
            "sections": [{"heading": "Random Section", "text": "Some mention of postgresql in the middle of a paragraph.",
                          "citations": [{"source_id": "s3", "quote": "mention of postgresql"}]}],
            "links": [],
            "review": {"method": "model", "reviewer": "test", "note": "ok"}
        }
        s3 = [{"id": "s3", "url": "https://example.test/notes", "text": "mention of postgresql in paragraph"}]
        self.wiki.write("gen-notes", p3, "seed", sources=s3)

        # Search for "PostgreSQL": title page must rank highest, followed by heading, then body
        results = self.wiki.search("postgresql")["results"]
        page_order = [r["page_id"] for r in results]
        self.assertEqual(page_order[0], "pg-guide", "Title hit (+15) should rank first")
        self.assertEqual(page_order[1], "db-overview", "Heading hit (+8) should rank second")
        self.assertEqual(page_order[2], "gen-notes", "Body-only hit should rank third")

        # Test configurable aliases from settings
        # Configure custom alias group: ["pgdb", "postgresql"]
        self.settings.update({"wiki": {"aliases": [["pgdb", "postgresql"]]}})
        alias_results = self.wiki.search("pgdb")["results"]
        self.assertEqual(len(alias_results), 3, "Query 'pgdb' should expand via configured alias to postgresql")
        self.assertEqual([r["page_id"] for r in alias_results], ["pg-guide", "db-overview", "gen-notes"])

    def test_p0_3_wiki_metrics_logging_and_summary(self):
        """P0-3: metrics.jsonl records writes, searches, gets, and plan_preflights, without recording queries."""
        # Fresh wiki
        metrics_file = self.wiki_dir / "metrics.jsonl"
        if metrics_file.exists():
            metrics_file.unlink()

        # 1. Write an article -> logs wiki_write
        page = {
            "title": "Metrics Test Page",
            "kind": "topic",
            "sections": [{"heading": "Metrics", "text": "Testing append-only telemetry logging.",
                          "citations": [{"source_id": "s1", "quote": "Testing append-only"}]}],
            "links": [],
            "review": {"method": "model", "reviewer": "test", "note": "ok"}
        }
        s1 = [{"id": "s1", "url": "https://example.test/telemetry", "text": "Testing append-only telemetry logging."}]
        self.wiki.write("metrics-page", page, "write page", sources=s1)

        # 2. Search wiki -> logs wiki_search
        search_res = self.wiki.search("telemetry")
        self.assertEqual(search_res["total"], 1)

        # 3. Get page -> logs wiki_get
        got = self.wiki.get("metrics-page")
        self.assertEqual(got["revision"], 1)

        # 4. Plan preflight -> logs plan_research
        planner = ResearchPlan(settings=self.settings, wiki=self.wiki, raw=self.raw)
        preflight_res, err = planner.wiki_preflight(["telemetry"])
        self.assertIsNone(err)
        self.assertTrue(len(preflight_res) >= 1)

        # Verify metrics.jsonl was created and contains no queries or prose
        self.assertTrue(metrics_file.is_file())
        lines = [json.loads(line) for line in metrics_file.read_text(encoding="utf-8").splitlines() if line.strip()]

        actions = [entry["action"] for entry in lines]
        self.assertIn("wiki_write", actions)
        self.assertIn("wiki_search", actions)
        self.assertIn("wiki_get", actions)
        self.assertIn("plan_research", actions)

        # Strict check: NO queries or prose in the metrics log
        for entry in lines:
            self.assertNotIn("query", entry)
            self.assertNotIn("telemetry", str(entry))
            self.assertNotIn("text", entry)

        # Test metrics_summary(days=30)
        summary = self.wiki.metrics_summary(days=30)
        self.assertEqual(summary["writes"], 1)
        self.assertEqual(summary["searches"], 2)  # 1 direct wiki_search + 1 from wiki_preflight search_terms
        self.assertEqual(summary["reads"], 1)
        self.assertEqual(summary["plan_preflights"], 1)
        self.assertIn("metrics-page", summary["reused_pages"])
        self.assertTrue(summary["total_hits"] >= 2)

        # Corrupted line tolerance test: corrupting metrics.jsonl must not crash search or summary
        with metrics_file.open("a", encoding="utf-8") as f:
            f.write("CORRUPTED JUNK LINE NOT JSON\n")
            f.write("{\"incomplete\": \n")

        res_after = self.wiki.search("telemetry")
        self.assertEqual(res_after["total"], 1)
        summary_after = self.wiki.metrics_summary(days=30)
        self.assertEqual(summary_after["writes"], 1)


if __name__ == "__main__":
    unittest.main()
