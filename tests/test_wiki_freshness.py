"""Version changes, targeted refresh, indexed retrieval and dependency boundaries."""
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from archive import SourceArchive
from bookmark_index import BookmarkIndex
from research import ResearchSessions
from settings import Settings
from source_manager import SourceManager
from source_versions import SourceVersions
from wiki import WikiStore
from wiki_search import WikiSearchIndex


class WikiFreshnessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.root / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.settings = Settings(self.root / "settings.json")
        self.settings.update({"archive": {"directory": str(self.root / "raw")}})
        self.engine = Mock()
        self.engine.fetch.side_effect = self.fetched
        self.body = "Aurora price is 10."
        self.now = datetime.now(timezone.utc)
        self.db = self.root / "index.sqlite3"
        self.research = ResearchSessions(self.root / "research", settings=self.settings,
                                         engine=self.engine, db_path=self.db)
        self.wiki = WikiStore(self.root / "wiki", settings=self.settings, research_sessions=self.research)

    def fetched(self, urls, provider=None, archive=True, max_characters=12000):
        return {"provider": provider or "exa", "urls": urls, "tool": "fixture",
                "request_arguments": {"urls": urls}, "retrieved_at": self.now.isoformat(),
                "requested_max_characters": max_characters, "status": "ok",
                "result": {"structuredContent": {"results": [{"url": url, "text": self.body} for url in urls]}}}

    def evidence(self, body=None, stamp=None, url="https://example.test/price", source_ids=None):
        body = body or self.body
        rid = self.research.start("Pricing", [{"id": "q1", "question": "What does it cost?"}],
                                  providers=["exa"], source_ids=source_ids or [])["research_id"]
        self.research.import_evidence(rid, "import", "q1", url, body,
            {"kind": "page", "provider": "fixture", "retrieved_at": stamp or (self.now - timedelta(days=1)).isoformat()})
        self.research.record(rid, {"kind": "source_review", "source_id": "s1", "verdict": "accepted",
                                  "text": "Checked the saved fixture source and exact text."})
        self.research.record(rid, {"kind": "claim", "question_id": "q1", "statement": body,
                                  "citations": [{"source_id": "s1", "quote": body}]})
        return rid

    @staticmethod
    def page(rid, **changes):
        return {"title": "Aurora 定价", "kind": "topic",
                "sections": [{"heading": "价格", "text": "Aurora 的定价说明。",
                              "claims": [{"research_id": rid, "claim_id": "c1"}]}],
                "links": [], "review": {"method": "human", "reviewer": "fixture", "note": "Reviewed fixture."},
                **changes}

    def codes(self, page_id="price"):
        return {issue["code"] for issue in self.wiki.get(page_id)["validation"]["issues"]}

    def test_later_source_in_another_task_invalidates_and_historical_import_does_not_hide_it(self):
        rid = self.evidence(stamp=(self.now - timedelta(days=2)).isoformat())
        written = self.wiki.write("price", self.page(rid), "Initial")
        before = Path(written["artifacts"]["record_file"]).read_bytes()
        self.evidence("Aurora price is 20.")
        self.assertIn("newer_source_snapshot", self.codes())
        self.evidence(stamp="2020-01-01T00:00:00Z")
        self.assertIn("newer_source_snapshot", self.codes())
        self.assertEqual("needs_review", self.wiki.get("price")["validation"]["status"])
        self.assertEqual(before, Path(written["artifacts"]["record_file"]).read_bytes())

    def test_same_task_new_snapshot_invalidates_without_changing_the_published_claim(self):
        rid = self.evidence()
        self.wiki.write("price", self.page(rid), "Initial")
        self.research.import_evidence(rid, "new-version", "q1", "https://example.test/price",
            "Aurora price is 20.", {"kind": "page", "retrieved_at": self.now.isoformat()})
        self.assertIn("newer_source_snapshot", self.codes())
        self.assertEqual("Aurora price is 10.", self.wiki.get("price")["evidence"][0]["statement"])

    def test_archived_capture_alone_invalidates_wiki(self):
        rid = self.evidence()
        self.wiki.write("price", self.page(rid), "Initial")
        self.body = "Aurora price is 20."
        archive = SourceArchive(self.root / "raw").save(self.fetched(["https://example.test/price"]))
        self.assertEqual("indexed", archive["source_version_tracking"])
        self.assertIn("newer_source_snapshot", self.codes())

    def test_identical_refresh_renews_expired_capture_without_rewriting_history(self):
        rid = self.evidence(stamp="2020-01-01T00:00:00Z")
        written = self.wiki.write("price", self.page(rid), "Historical source")
        before = Path(written["artifacts"]["record_file"]).read_bytes()
        self.assertIn("source_capture_expired", self.codes())
        result = self.wiki.refresh("price", expected_revision=1)
        self.assertEqual("unchanged", result["checks"][0]["status"])
        self.assertEqual("current", result["validation"]["status"])
        self.assertFalse(result["validation"]["freshness"]["origin_current_verified"])
        self.assertEqual(before, Path(written["artifacts"]["record_file"]).read_bytes())
        capture = result["checks"][0]["read_capture"]
        saved = SourceArchive(self.root / "raw").read_capture(**capture)
        self.assertEqual(self.body, saved["pages"][0]["text"])
        self.assertEqual(1, self.engine.fetch.call_count)

    def test_changed_refresh_marks_linked_dependents_and_failed_refresh_remains_unknown(self):
        rid = self.evidence()
        self.wiki.write("price", self.page(rid), "Initial")
        other = self.evidence(body="A separate document.", url="https://example.test/other")
        self.wiki.write("overview", self.page(other, links=[{"page_id": "price", "relation": "Pricing details"}]), "Link")
        self.body = "Aurora price is 20."
        result = self.wiki.refresh("price")
        self.assertEqual("changed", result["checks"][0]["status"])
        self.assertEqual(["overview", "price"], result["affected"]["page_ids"])
        self.assertIn("linked_page_needs_review", self.codes("overview"))
        listing = self.wiki.list(source_url="https://example.test/price#cost", limit=1)
        self.assertEqual(2, listing["total"])
        self.assertEqual(1, listing["next_offset"])
        self.engine.fetch.side_effect = TimeoutError("fixture timeout")
        failed = self.wiki.refresh("price")
        self.assertEqual("error", failed["status"])
        self.assertIn("source_refresh_failed", self.codes())
        self.assertEqual(1, self.wiki.get("price")["revision"])

    def test_refresh_is_bounded_and_checks_expected_revision_before_network(self):
        rid = self.evidence()
        self.wiki.write("price", self.page(rid), "Initial")
        with self.assertRaisesRegex(ValueError, "revision changed"):
            self.wiki.refresh("price", expected_revision=2)
        with self.assertRaises(ValueError):
            self.wiki.refresh("price", limit=17)
        self.assertEqual([], self.wiki.refresh("price", offset=8)["checks"])
        self.engine.fetch.assert_not_called()

    def test_new_link_revision_changes_the_aggregate_status(self):
        rid = self.evidence()
        self.wiki.write("price", self.page(rid), "Initial")
        self.wiki.write("overview", self.page(rid, links=[{"page_id": "price", "relation": "Details"}]), "Link")
        self.wiki.write("price", self.page(rid), "Reviewed", expected_revision=1)
        self.assertEqual("needs_review", self.wiki.get("overview")["validation"]["status"])

    def test_mcp_accepts_authored_aliases_refresh_and_dependency_filter(self):
        from mcp_server import StdioMcpServer
        rid = self.evidence()
        self.settings.update({"wiki": {"directory": str(self.wiki.directory)}, "tool_scope_preset": "all"})
        server = StdioMcpServer(self.db, stderr=io.StringIO(), settings=self.settings)
        self.addCleanup(server.close)
        server._research_sessions, server._wiki_store = self.research, self.wiki
        server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}})
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        def call(name, arguments):
            result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": name, "arguments": arguments}})
            self.assertFalse(result["result"]["isError"], result)
            return result["result"]["structuredContent"]
        written = call("wiki_write", {"page_id": "price", "page": self.page(rid, aliases=["Aurora cost"]),
                                     "change_note": "Initial"})
        self.assertEqual(1, written["revision"])
        self.assertEqual("unchanged", call("wiki_refresh", {"page_id": "price", "expected_revision": 1})["checks"][0]["status"])
        self.assertEqual(1, call("wiki_list", {"source_url": "https://example.test/price"})["total"])

    def test_alias_recall_and_no_hit_search_do_not_validate_unrelated_evidence(self):
        rid = self.evidence()
        self.wiki.write("price", self.page(rid, aliases=["Aurora cost"]), "Initial")
        for index in range(12):
            self.wiki.write("topic-%02d" % index, self.page(rid, title="General notes"), "Initial")
        with patch.object(self.wiki, "_revision", wraps=self.wiki._revision) as revisions:
            self.wiki.write("new-topic", self.page(rid), "Incremental catalog update")
            self.assertEqual(0, revisions.call_count)
        with patch.object(self.wiki, "_evidence", wraps=self.wiki._evidence) as evidence:
            result = self.wiki.search("UnmatchedNebula")
            self.assertEqual((0, 0, 0), (result["total"], result["candidates_found"], result["pages_validated"]))
            self.assertEqual(0, evidence.call_count)
        self.assertGreater(self.wiki.search("多少钱")["total"], 0)
        self.assertTrue(self.wiki.search("多少钱")["results"][0]["alias_expanded"])
        self.assertEqual(["price"], [row["page_id"] for row in self.wiki.search("Aurora cost")["results"]])

    def test_invalid_candidate_does_not_use_up_result_limit(self):
        bad, good = self.evidence(), self.evidence()
        self.wiki.write("a-bad", self.page(bad), "Initial")
        self.wiki.write("z-good", self.page(good), "Initial")
        self.research.record(bad, {"kind": "source_review", "source_id": "s1", "verdict": "rejected", "text": "Rejected."})
        result = self.wiki.search("定价", limit=1)
        self.assertEqual(["z-good"], [row["page_id"] for row in result["results"]])
        self.assertEqual(["a-bad"], result["excluded_page_ids"])
        self.assertEqual(1, result["total"])

    def test_derived_index_failure_cannot_undo_a_commit_or_bypass_validation(self):
        rid = self.evidence()
        with patch.object(WikiSearchIndex, "update", side_effect=sqlite3.DatabaseError("fixture")):
            result = self.wiki.write("price", self.page(rid), "Initial")
        self.assertEqual(("written", "unavailable"), (result["status"], result["search_index"]))
        self.assertEqual(1, self.wiki.search("定价")["total"])
        (self.wiki.directory / "search.sqlite3").write_bytes(b"not a database")
        result = self.wiki.search("定价")
        self.assertEqual(1, result["total"])
        self.assertIn("revision scan", result["search_index"])
        self.research.record(rid, {"kind": "retraction", "claim_id": "c1", "text": "Withdrawn."})
        self.assertEqual(0, self.wiki.search("定价")["total"])

    def indexed_package(self):
        package = self.root / "package"
        path = package / "临时栏目" / "A-1.json"
        path.parent.mkdir(parents=True)
        document = {"format": "bookmark-canvas-section", "schemaVersion": 2, "id": "temp-section-A-1",
                    "sectionType": "temporary", "label": "A-1", "title": "References",
                    "items": [{"id": "b%d" % i, "sectionId": "temp-section-A-1", "type": "bookmark",
                               "url": url, "title": "Bookmark %d" % i} for i, url in enumerate(
                                   ["https://example.test/price", "https://example.test/unrelated"])]}
        path.write_text(json.dumps(document), encoding="utf-8")
        canvas = {"nodes": [{"id": "card", "type": "file", "file": "临时栏目/A-1.json",
                             "x": 0, "y": 0, "width": 300, "height": 300},
                            {"id": "note", "type": "text", "text": "Pricing context",
                             "x": 400, "y": 0, "width": 300, "height": 300}],
                  "edges": [{"id": "relation", "fromNode": "card", "toNode": "note", "label": "explains"}]}
        canvas_path = package / "map.canvas"
        canvas_path.write_text(json.dumps(canvas), encoding="utf-8")
        with BookmarkIndex(self.db) as index:
            sid = SourceManager(index).sync(package, mode="snapshot")["source_id"]
        rid = self.evidence(source_ids=[sid])
        self.wiki.write("price", self.page(rid), "Initial")
        return package, path, document, canvas_path, canvas, sid

    def test_unrelated_bookmark_rename_does_not_invalidate_but_cited_metadata_does(self):
        package, path, document, _, _, sid = self.indexed_package()
        document["items"][1]["title"] = "Unrelated renamed"
        path.write_text(json.dumps(document), encoding="utf-8")
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(package, source_id=sid, mode="snapshot")
        self.assertEqual("current", self.wiki.get("price")["validation"]["status"])
        document["items"][0]["title"] = "Cited renamed"
        path.write_text(json.dumps(document), encoding="utf-8")
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(package, source_id=sid, mode="snapshot")
        self.assertIn("source_input_changed", self.codes())

    def test_related_canvas_text_remains_a_dependency(self):
        package, _, _, canvas_path, canvas, sid = self.indexed_package()
        canvas["nodes"][1]["text"] = "Pricing context changed"
        canvas_path.write_text(json.dumps(canvas), encoding="utf-8")
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(package, source_id=sid, mode="snapshot")
        self.assertIn("source_input_changed", self.codes())


class SourceVersionTests(unittest.TestCase):
    def test_equal_capture_timestamps_still_detect_change_and_rejected_or_historical_rows_do_not_supersede_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            versions = SourceVersions(Path(temporary) / "versions.sqlite3")
            old = {"id": "s1", "url": "https://example.test/doc", "sha256": hashlib.sha256(b"old").hexdigest(),
                   "retrieved_at": "2026-10-01T00:00:00Z", "review": {"verdict": "accepted"}}
            newer = {**old, "id": "s2", "sha256": hashlib.sha256(b"new").hexdigest()}
            versions.record("task", [old, newer])
            versions.record("task", [old])
            historical = {**old, "id": "s3", "retrieved_at": "2020-01-01T00:00:00Z"}
            versions.record("task", [historical])
            inspected = versions.inspect(old["url"], old["sha256"], old["retrieved_at"],
                                         "2026-10-01T00:00:00Z", "task", "s1")
            self.assertEqual("s2", inspected["newer"]["source_id"])
            newer["review"] = {"verdict": "rejected"}
            versions.record("task", [newer])
            self.assertIsNone(versions.inspect(old["url"], old["sha256"], old["retrieved_at"],
                                               "2026-10-01T00:00:00Z", "task", "s1")["newer"])


if __name__ == "__main__":
    unittest.main()
