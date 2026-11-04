"""Audit gap coverage tests (P4-1).

Covers edge cases identified during index and store hardening:
1. Same section_id with changed label or title
2. Concurrent live sync on the same source
3. Interrupted publish transaction rollback
4. Oversized incremental sync (1,000+ items)
5. Multiple sources registered on the same package directory
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from source_manager import SourceManager
from research import ResearchSessions
from settings import Settings
from wiki import WikiStore


def build_package(root, label="Sec-A", title="Section A", item_count=5):
    section_id = "section-" + label.lower().replace(" ", "-")
    items = []
    for i in range(item_count):
        items.append({
            "id": f"item-{i:04d}",
            "sectionId": section_id,
            "type": "bookmark",
            "url": f"https://example.test/{label.lower()}/page-{i}",
            "title": f"Bookmark {i} in {title}",
            "comment": f"Note for item {i}",
        })
    data = {
        "format": "bookmark-canvas-section",
        "schemaVersion": 2,
        "id": section_id,
        "sectionType": "temporary",
        "label": label,
        "title": title,
        "items": items,
    }
    target_dir = root / "临时栏目"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / (label + ".json")
    target_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return root, section_id, target_file


class AuditGapCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="audit-gap-tests-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name).resolve()
        self.db_path = self.root / "index.sqlite3"
        self.index = BookmarkIndex(self.db_path)
        self.addCleanup(self.index.close)
        self.manager = SourceManager(self.index)

    def test_section_label_and_title_change_on_same_section_id(self):
        """Scenario 1: changing label/title on same section_id updates without duplicating."""
        pkg_dir = self.root / "pkg1"
        pkg_dir, sec_id, file_path = build_package(pkg_dir, label="Sec-Old", title="Old Section Title", item_count=3)

        first_sync = self.manager.sync(pkg_dir, mode="live")
        source_id = first_sync["source_id"]

        row = self.index.connection.execute(
            "SELECT label, title FROM sections WHERE source_id=? AND section_id=?",
            (source_id, sec_id)
        ).fetchone()
        self.assertEqual(row["label"], "Sec-Old")
        self.assertEqual(row["title"], "Old Section Title")

        # Now edit file: keep section_id same, update label and title
        data = json.loads(file_path.read_text(encoding="utf-8"))
        data["label"] = "Sec-New"
        data["title"] = "New Section Title"
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        refresh_result = self.manager.refresh(source_id)
        self.assertIn(refresh_result["state"], ("current", "live"))

        rows = self.index.connection.execute(
            "SELECT label, title FROM sections WHERE source_id=? AND section_id=?",
            (source_id, sec_id)
        ).fetchall()
        self.assertEqual(len(rows), 1, "Section should not be duplicated")
        self.assertEqual(rows[0]["label"], "Sec-New")
        self.assertEqual(rows[0]["title"], "New Section Title")

        # Bookmarks under this section are preserved
        items = self.index.connection.execute(
            "SELECT count(*) FROM items WHERE source_id=? AND section_id=?",
            (source_id, sec_id)
        ).fetchone()[0]
        self.assertEqual(items, 3)

    def test_concurrent_live_sync_on_same_source(self):
        """Scenario 2: concurrent refresh on the same live source doesn't lock or corrupt DB."""
        pkg_dir = self.root / "pkg2"
        pkg_dir, sec_id, file_path = build_package(pkg_dir, label="Concurrent", title="Concurrent Test", item_count=10)

        initial = self.manager.sync(pkg_dir, mode="live")
        source_id = initial["source_id"]

        errors = []
        results = []

        def worker(w_id):
            try:
                # Open isolated index connection for each thread to simulate real multi-process/multi-client access
                with BookmarkIndex(self.db_path) as thread_index:
                    thread_mgr = SourceManager(thread_index)
                    res = thread_mgr.refresh(source_id)
                    results.append(res)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Concurrent workers failed with errors: {errors}")
        self.assertEqual(len(results), 4)

        # Confirm data consistency
        item_count = self.index.connection.execute(
            "SELECT count(*) FROM items WHERE source_id=?", (source_id,)
        ).fetchone()[0]
        self.assertEqual(item_count, 10)

    def test_interrupted_publish_transaction_rollback(self):
        """Scenario 3: interrupted publish transaction rolls back cleanly without dirty state."""
        settings = Settings(self.root / "settings.json")
        wiki_dir = self.root / "wiki"
        research_dir = self.root / "research"
        sessions = ResearchSessions(research_dir, settings=settings, db_path=self.db_path)
        wiki = WikiStore(wiki_dir, settings=settings, research_sessions=sessions)

        rid = sessions.start("Test Rollback", [{"id": "q1", "question": "What is X?"}],
                             providers=["exa"])["research_id"]
        sessions.import_evidence(rid, "imp1", "q1", "https://example.test/page",
                                 "Evidence body text for rollback test",
                                 {"kind": "page", "provider": "test"})
        sessions.record(rid, {"kind": "source_review", "source_id": "s1", "verdict": "accepted",
                             "text": "Review accepted"})
        sessions.record(rid, {"kind": "claim", "question_id": "q1", "statement": "Claim statement",
                             "citations": [{"source_id": "s1", "quote": "Evidence body text"}]})

        first = wiki.write("test-page", {
            "title": "Initial Revision",
            "kind": "topic",
            "sections": [{
                "heading": "Section 1",
                "text": "First version text.",
                "claims": [{"research_id": rid, "claim_id": "c1"}]
            }],
            "links": [],
            "review": {"method": "model", "reviewer": "tester", "note": "initial"}
        }, "Initial commit")
        self.assertEqual(first["revision"], 1)

        # Inject failure during index.json write for revision 2
        orig_write = ResearchSessions._write

        def fail_on_index_json(path, value):
            if path == wiki_dir / "index.json":
                raise OSError("Simulated crash right before index publication")
            return orig_write(path, value)

        with patch.object(ResearchSessions, "_write", side_effect=fail_on_index_json):
            with self.assertRaisesRegex(OSError, "Simulated crash"):
                wiki.write("test-page", {
                    "title": "Interrupted Revision",
                    "kind": "topic",
                    "sections": [{
                        "heading": "Section 1",
                        "text": "Second version text.",
                        "claims": [{"research_id": rid, "claim_id": "c1"}]
                    }],
                    "links": [],
                    "review": {"method": "model", "reviewer": "tester", "note": "rev2"}
                }, "Failed update", expected_revision=1)

        # Index.json and get() must cleanly remain at revision 1
        page = wiki.get("test-page")
        self.assertEqual(page["revision"], 1)
        self.assertEqual(page["page"]["title"], "Initial Revision")

        # Retrying cleanly succeeds as revision 2
        second = wiki.write("test-page", {
            "title": "Succeeded Revision",
            "kind": "topic",
            "sections": [{
                "heading": "Section 1",
                "text": "Second version text.",
                "claims": [{"research_id": rid, "claim_id": "c1"}]
            }],
            "links": [],
            "review": {"method": "model", "reviewer": "tester", "note": "rev2"}
        }, "Successful update", expected_revision=1)
        self.assertEqual(second["revision"], 2)

    def test_oversized_incremental_sync(self):
        """Scenario 4: single incremental sync with 500+ items handles scale accurately."""
        pkg_dir = self.root / "pkg4"
        pkg_dir, sec_id, file_path = build_package(pkg_dir, label="Base", title="Base Section", item_count=10)

        initial = self.manager.sync(pkg_dir, mode="live")
        source_id = initial["source_id"]
        self.assertEqual(initial["counts"]["bookmarks"], 10)

        # Now inflate the section to 600 bookmarks
        data = json.loads(file_path.read_text(encoding="utf-8"))
        for i in range(10, 610):
            data["items"].append({
                "id": f"item-{i:05d}",
                "sectionId": sec_id,
                "type": "bookmark",
                "url": f"https://example.test/scale/item-{i}",
                "title": f"Large scale item {i}",
            })
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        refreshed = self.manager.refresh(source_id)
        self.assertEqual(refreshed["counts"]["bookmarks"], 610)

        # Verify DB counts and retrieval
        total_items = self.index.connection.execute(
            "SELECT count(*) FROM items WHERE source_id=?", (source_id,)
        ).fetchone()[0]
        self.assertEqual(total_items, 610)

        # Verify search works over the large dataset
        search = self.index.search(source_id, targets=["Large scale item 555"])
        self.assertEqual(search["total"], 1)
        self.assertEqual(search["results"][0]["item_id"], "item-00555")

    def test_multiple_sources_registered_on_same_directory(self):
        """Scenario 5: registering duplicate sources on same path is handled and mergeable."""
        pkg_dir = self.root / "pkg5"
        pkg_dir, sec_id, file_path = build_package(pkg_dir, label="Multi", title="Multi Source", item_count=5)

        # First source
        first = self.manager.sync(pkg_dir, source_id="src-original", mode="snapshot")
        self.assertEqual(first["source_id"], "src-original")

        # Second source on identical content (different source_id)
        # Copy to simulate duplicate directory or aliased import
        dup_dir = self.root / "pkg5-dup"
        shutil.copytree(pkg_dir, dup_dir)
        second = self.manager.sync(dup_dir, source_id="src-duplicate", mode="snapshot")
        self.assertEqual(second["source_id"], "src-duplicate")
        self.assertIn("src-original", second["duplicate_source_ids"])

        # Check content duplicates detection
        duplicates = self.manager._content_duplicates("src-duplicate", second["version_id"])
        self.assertIn("src-original", duplicates)

        # Merge duplicate into original
        merge_res = self.manager.merge("src-duplicate", "src-original", confirm=True)
        self.assertEqual(merge_res["status"], "merged")

        # Confirm duplicate source was dropped and original retains items
        dup_count = self.index.connection.execute("SELECT count(*) FROM sources WHERE source_id='src-duplicate'").fetchone()[0]
        orig_count = self.index.connection.execute("SELECT count(*) FROM sources WHERE source_id='src-original'").fetchone()[0]
        self.assertEqual(dup_count, 0)
        self.assertEqual(orig_count, 1)
        self.assertEqual(self.index.connection.execute(
            "SELECT count(*) FROM items WHERE source_id='src-original'"
        ).fetchone()[0], 5)


if __name__ == "__main__":
    unittest.main()
