"""A legitimate source change must be resolvable, not permanently red.

``source_input_changed`` is a warning about the frozen research input version.
Re-reviewing the page and re-writing it, or acknowledging it explicitly, must
close that warning for the version actually reviewed, and a later change must
reopen it.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from research import ResearchSessions
from settings import Settings
from source_manager import SourceManager
from wiki import WikiStore


def section(title, urls):
    return {"format": "bookmark-canvas-section", "schemaVersion": 2, "id": "temp-section-A-1",
            "sectionType": "temporary", "label": "A-1", "title": title,
            "items": [{"id": "b%d" % index, "sectionId": "temp-section-A-1", "type": "bookmark",
                       "url": url, "title": title + " " + str(index)} for index, url in enumerate(urls)]}


class WikiAcknowledgementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wiki acknowledge ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.data = self.base / "data"
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.data)})
        environment.start()
        self.addCleanup(environment.stop)
        self.settings = Settings(self.base / "settings.json")
        self.db = self.data / "index.sqlite3"
        self.package = self.base / "package"
        self.write_package("First title")
        with BookmarkIndex(self.db) as index:
            self.source_id = SourceManager(index).sync(self.package, mode="snapshot")["source_id"]
        self.sessions = ResearchSessions(settings=self.settings, db_path=self.db,
                                         engine=Mock(), directory=self.data / "research")
        self.rid = self.sessions.start("Count bookmarks", [{"id": "q1", "question": "What is saved?"}],
                                       source_ids=[self.source_id])["research_id"]
        self.store = WikiStore(directory=self.data / "wiki", settings=self.settings, research_sessions=self.sessions)
        self.sessions.import_evidence(self.rid, "import-1", "q1", "https://example.test/one",
            "First title 0 is saved in this exported package.",
            {"kind": "local_document", "provider": "tests", "acquired_at": "2026-10-09T00:00:00+00:00",
             "location": "package"})
        self.sessions.record(self.rid, {"kind": "source_review", "source_id": "s1", "verdict": "accepted",
            "text": "Local exported document; identity and wording checked."})
        self.claim = self._claim()

    def write_package(self, title):
        (self.package / "临时栏目").mkdir(parents=True, exist_ok=True)
        (self.package / "临时栏目" / "A-1.json").write_text(
            json.dumps(section(title, ["https://example.test/one"]), ensure_ascii=False), encoding="utf-8")

    def _claim(self):
        return self.sessions.record(self.rid, {"kind": "claim", "question_id": "q1",
            "statement": "One bookmark is saved.", "citations": [
                {"source_id": "s1", "quote": "First title 0 is saved"}]})["recorded"]["id"]

    def _page(self):
        return {"title": "Saved bookmarks", "kind": "topic", "sections": [{"heading": "Stored",
                "text": "The package stores one bookmark whose title is recorded locally.",
                "claims": [{"research_id": self.rid, "claim_id": self.claim}]}], "links": [],
                "review": {"method": "model", "reviewer": "tests", "note": "Checked the local bookmark input."}}

    def _input_version(self):
        return self.sessions.source_freshness(research_id=self.rid)["current_input_version"]

    def _status(self, page_id="saved-bookmarks"):
        return self.store.get(page_id)["validation"]["status"]

    def test_rewrite_with_the_reviewed_version_closes_needs_review(self):
        self.store.write("saved-bookmarks", self._page(), "Initial page")
        self.assertEqual("current", self._status())
        # A legitimate source change opens the warning.
        self.write_package("Second title")
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(self.package, source_id=self.source_id, mode="snapshot")
        self.assertEqual("needs_review", self._status())
        # Re-reviewing and re-writing against the new version closes it.
        result = self.store.write("saved-bookmarks", self._page(), "Reviewed the new input",
                                  expected_revision=1, reviewed_input_version=self._input_version())
        self.assertEqual(2, result["revision"])
        self.assertEqual(1, len(result["acknowledged"]))
        self.assertEqual(self._input_version(), result["acknowledged"][0]["input_version"])
        self.assertEqual("current", self._status())

    def test_acknowledge_closes_needs_review_without_editing_content(self):
        self.store.write("saved-bookmarks", self._page(), "Initial page")
        self.write_package("Third title")
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(self.package, source_id=self.source_id, mode="snapshot")
        self.assertEqual("needs_review", self._status())
        result = self.store.acknowledge("saved-bookmarks", "Re-read the exported bookmark and the page still holds.")
        self.assertEqual(2, result["revision"])
        self.assertEqual("current", self._status())
        # The page text is unchanged by an acknowledgement.
        self.assertEqual(self._page()["sections"], self.store.get("saved-bookmarks")["page"]["sections"])

    def test_a_later_change_reopens_the_warning(self):
        self.store.write("saved-bookmarks", self._page(), "Initial page")
        self.write_package("Fourth title")
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(self.package, source_id=self.source_id, mode="snapshot")
        self.store.acknowledge("saved-bookmarks", "Reviewed once.")
        self.assertEqual("current", self._status())
        self.write_package("Fifth title")
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(self.package, source_id=self.source_id, mode="snapshot")
        self.assertEqual("needs_review", self._status())

    def test_content_edit_carries_forward_a_still_current_acknowledgement(self):
        self.store.write("saved-bookmarks", self._page(), "Initial page")
        self.write_package("Sixth title")
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(self.package, source_id=self.source_id, mode="snapshot")
        self.store.acknowledge("saved-bookmarks", "Reviewed.")
        page = self.store.get("saved-bookmarks")["page"]
        page["sections"][0]["text"] = "The package stores one bookmark; wording clarified."
        self.store.write("saved-bookmarks", page, "Clarified wording", expected_revision=2)
        self.assertEqual("current", self._status())

    def test_unknown_reviewed_version_is_rejected(self):
        self.store.write("saved-bookmarks", self._page(), "Initial page")
        with self.assertRaisesRegex(ValueError, "reviewed_input_version does not match"):
            self.store.write("saved-bookmarks", self._page(), "Bad version", expected_revision=1,
                             reviewed_input_version="0" * 64)

    def test_acknowledged_change_is_reported_but_not_a_warning(self):
        self.store.write("saved-bookmarks", self._page(), "Initial page")
        self.write_package("Seventh title")
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(self.package, source_id=self.source_id, mode="snapshot")
        self.store.acknowledge("saved-bookmarks", "Reviewed.")
        issues = self.store.get("saved-bookmarks")["validation"]["issues"]
        self.assertEqual(["source_change_acknowledged"], [issue["code"] for issue in issues])
        self.assertEqual("info", issues[0]["severity"])


    def test_wiki_search_tolerates_differently_spaced_cjk_queries(self):
        page = self._page()
        page["title"] = "唯一 URL 统计"
        page["sections"][0]["text"] = "本页记录唯一 URL 的数量，并说明副本锚点为何不能重复计数。"
        self.store.write("unique-urls", page, "CJK spacing page")
        spaced = self.store.search("唯一 URL")
        squashed = self.store.search("唯一URL")
        self.assertEqual(1, spaced["total"])
        self.assertEqual(1, squashed["total"])
        self.assertFalse(spaced["results"][0].get("whitespace_insensitive", False))
        self.assertTrue(squashed["results"][0]["whitespace_insensitive"])
        self.assertIn("whitespace-insensitive", squashed["method"])


if __name__ == "__main__":
    unittest.main()
