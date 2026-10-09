"""Bookmark search must stay literal-substring while using the full-text index.

The FTS table shipped with the default tokenizer, which treats a whole run of
CJK characters as one token, so it could not answer ``推理`` inside ``推理加速``
and the query path used LIKE only. The index now uses the substring-based
trigram tokenizer where available, keeps LIKE for one- and two-character terms,
and ANDs whitespace-separated terms instead of matching them as one phrase.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import TRIGRAM_MINIMUM, BookmarkIndex


def section(items):
    return {"format": "bookmark-canvas-section", "schemaVersion": 2, "id": "temp-section-A-1",
            "sectionType": "temporary", "label": "A-1", "title": "Search sources",
            "items": [{"id": "b%d" % index, "sectionId": "temp-section-A-1", "type": "bookmark",
                       "title": title, "url": "https://example.test/%d" % index}
                      for index, title in enumerate(items)]}


class BookmarkSearchIndexTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark search ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.package = self.base / "package"
        (self.package / "临时栏目").mkdir(parents=True)
        (self.package / "临时栏目" / "A-1.json").write_text(json.dumps(section([
            "华为默默开源了所有的盘古模型 推理加速方案",
            "Cloudflare推出AutoRAG服务，Beta阶段免费",
            "推理 与 加速 的独立说明",
        ]), ensure_ascii=False), encoding="utf-8")
        self.index = BookmarkIndex(self.base / "data" / "index.sqlite3")
        self.addCleanup(self.index.close)
        with self.index.transaction():
            self.index.sync(self.package)
        self.source_id = self.index.connection.execute("SELECT source_id FROM sources").fetchone()[0]

    def total(self, target):
        return self.index.search(self.source_id, targets=[target], limit=1)["total"]

    def test_substring_semantics_survive_the_index_switch(self):
        # 'RAG' must still find 'AutoRAG': the contract is substring, not token.
        self.assertEqual(1, self.total("RAG"))
        self.assertEqual(1, self.total("AutoRAG"))

    def test_long_terms_use_the_full_text_index(self):
        if self.index._fts_mode != "trigram":
            self.skipTest("trigram tokenizer unavailable on this SQLite build")
        self.assertEqual(1, self.total("推理加速"))
        predicate, parameters = self.index._match("推理加速")
        self.assertIn("items_fts MATCH", predicate)
        self.assertEqual(['"推理加速"'], parameters)
        # The same term is really in the index, not only in the LIKE fallback.
        rows = self.index.connection.execute(
            "SELECT COUNT(*) FROM items_fts WHERE items_fts MATCH ?", ('"推理加速"',)).fetchone()[0]
        self.assertEqual(1, rows)

    def test_short_terms_keep_the_like_fallback(self):
        predicate, parameters = self.index._match("推理")
        self.assertNotIn("items_fts", predicate)
        self.assertEqual(["%推理%"] * 5, parameters)
        self.assertEqual(2, self.total("推理"))

    def test_whitespace_separated_terms_are_required_together(self):
        # '推理 加速' must not be one literal phrase, and must AND its terms.
        predicate, _ = self.index._match("推理 加速")
        self.assertIn(" AND ", predicate)
        # Two bookmarks contain both terms; the third contains neither.
        self.assertEqual(2, self.total("推理 加速"))
        # A pair that never co-occurs matches nothing rather than everything.
        self.assertEqual(0, self.total("AutoRAG 盘古"))

    def test_trigram_minimum_matches_the_documented_boundary(self):
        self.assertEqual(3, TRIGRAM_MINIMUM)
        if self.index._fts_mode == "trigram":
            self.assertIn("items_fts MATCH", self.index._match("a" * TRIGRAM_MINIMUM)[0])
            self.assertNotIn("items_fts", self.index._match("a" * (TRIGRAM_MINIMUM - 1))[0])

    def test_existing_index_is_upgraded_in_place(self):
        # A database created with the default tokenizer is rebuilt on open.
        path = self.base / "legacy" / "index.sqlite3"
        legacy = BookmarkIndex(path)
        with legacy.transaction():
            legacy.sync(self.package)
        legacy.connection.execute("DROP TABLE items_fts")
        legacy.connection.execute("CREATE VIRTUAL TABLE items_fts USING fts5("
                                  "title,url,note,tag_text,folder_path,content='items',content_rowid='pk')")
        legacy.connection.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
        legacy.close()
        upgraded = BookmarkIndex(path)
        self.addCleanup(upgraded.close)
        self.assertEqual("trigram", upgraded._fts_mode)
        self.assertEqual(1, upgraded.connection.execute(
            "SELECT COUNT(*) FROM items_fts WHERE items_fts MATCH ?", ('"推理加速"',)).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
