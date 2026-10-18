"""Added-at is read literally from ids, dateAdded and edge ids; nothing is guessed."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_bookmark_index import TEMP, make_package, write_json

from bookmark_index import (ADDED_AT_SOURCES, BookmarkIndex, _added_at_fields, _added_at_from_edge_id,
                            _added_at_from_epoch, _added_at_from_id)
from settings import Settings
from source_manager import SourceManager

PRIMARY = "永久栏目/A书签树（永久栏目）.json"
V1_ITEMS = """CREATE TABLE IF NOT EXISTS items (
 pk INTEGER PRIMARY KEY, source_id TEXT NOT NULL, section_id TEXT NOT NULL,
 item_id TEXT NOT NULL, parent_id TEXT, item_type TEXT NOT NULL,
 position INTEGER NOT NULL, preorder INTEGER NOT NULL, title TEXT NOT NULL,
 url TEXT NOT NULL, note TEXT NOT NULL, note_color TEXT,
 tags_json TEXT NOT NULL, tag_text TEXT NOT NULL, path_json TEXT NOT NULL,
 folder_path TEXT NOT NULL, ancestor_ids_json TEXT NOT NULL,
 raw_json TEXT NOT NULL, metadata_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 UNIQUE(source_id,section_id,item_id)
);"""


def permanent_card(root, date_added=1763356913791):
    write_json(root, PRIMARY, {"format": "bookmark-canvas-section", "schemaVersion": 3,
        "sectionType": "permanent", "slot": "A", "title": "主树", "fileRole": "primary",
        "tree": {"id": "root", "title": "", "children": [
            {"id": "syncId_20260613_hash_5d1x2t1", "parentId": "root", "title": "Lumen 收藏",
             "url": "https://example.test/alpha", "dateAdded": date_added}]}})


def dated_temp_card(root, section_id, label, item_id, title="Lumen", name=None):
    write_json(root, "临时栏目/常规链式/%s.json" % (name or label), {"format": "bookmark-canvas-section",
        "schemaVersion": 2, "id": section_id, "sectionType": "temporary", "label": label, "tempKind": "regular",
        "title": label + " card", "items": [{"id": item_id, "sectionId": section_id, "type": "bookmark",
        "title": title, "url": "https://example.test/%s" % label}]})


class AddedAtTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.root / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.db = self.root / "index.sqlite3"
        self.settings = Settings(self.root / "settings.json")

    def indexed(self, build=make_package):
        package = Path(tempfile.mkdtemp(dir=self.root))
        build(package)
        index = BookmarkIndex(self.db)
        self.addCleanup(index.close)
        return index, SourceManager(index).sync(package, mode="snapshot")["source_id"]

    def test_an_id_date_segment_is_day_precision_and_validated(self):
        self.assertEqual("2026-06-27T00:00:00+00:00", _added_at_from_id("tempId_20260627_hash_1se4a28"))
        self.assertEqual("2026-10-17T00:00:00+00:00", _added_at_from_id("syncId_20261017_hash_x"))
        for bad in ("tempId_20261340_hash_x", "tempId_2026062_hash_x", "bookmark-alpha", "", None, 17):
            self.assertIsNone(_added_at_from_id(bad))
        self.assertEqual(("day", "low"), ADDED_AT_SOURCES["id_date_segment"])

    def test_an_epoch_must_be_a_plausible_millisecond_value(self):
        self.assertEqual("2026-06-27T14:57:58.545000+00:00", _added_at_from_epoch(1782572278545))
        for bad in (9, 1782572278545.0, True, None, "1782572278545", 17825722785450000):
            self.assertIsNone(_added_at_from_epoch(bad))

    def test_only_the_trailing_number_of_an_edge_id_is_a_time(self):
        self.assertEqual("2026-06-27T14:57:58.545000+00:00", _added_at_from_edge_id("edge - 9 -1782572278545"))
        for bad in ("edge - 9", "edge - 9 -7", "edge-untimed", "", None):
            self.assertIsNone(_added_at_from_edge_id(bad))

    def test_a_real_add_time_wins_over_a_generation_clue(self):
        added, source, confidence = _added_at_fields("syncId_20260613_hash_5d1x2t1", {"dateAdded": 1763356913791})
        self.assertEqual("2025-11-17T05:21:53.791000+00:00", added)
        self.assertEqual("dateAdded", source)
        self.assertEqual("high", confidence)
        added, source, confidence = _added_at_fields("tempId_20260627_hash_1se4a28", {"title": "x"})
        self.assertEqual("2026-06-27T00:00:00+00:00", added)
        self.assertEqual("id_date_segment", source)
        self.assertEqual("low", confidence)
        self.assertEqual((None, None, None), _added_at_fields("temp-folder", {}))
        self.assertEqual((None, None, None), _added_at_fields("temp-folder", None))

    def test_a_version_1_index_gains_the_columns_and_backfills_from_stored_json(self):
        connection = sqlite3.connect(str(self.db))
        connection.executescript(V1_ITEMS)
        connection.execute("INSERT INTO items (source_id,section_id,item_id,item_type,position,preorder,"
            "title,url,note,tags_json,tag_text,path_json,folder_path,ancestor_ids_json,raw_json,metadata_json) "
            "VALUES ('s','temp-section-A-1','tempId_20260627_hash_1se4a28','bookmark',0,0,'x','u','',"
            "'[]','','[]','','[]',?,'{}')", (json.dumps({"title": "x"}),))
        connection.execute("INSERT INTO items (source_id,section_id,item_id,item_type,position,preorder,"
            "title,url,note,tags_json,tag_text,path_json,folder_path,ancestor_ids_json,raw_json,metadata_json) "
            "VALUES ('s','permanent-section','bookmark-alpha','bookmark',0,0,'y','u','',"
            "'[]','','[]','','[]',?,'{}')", (json.dumps({"dateAdded": 1763356913791}),))
        connection.execute("PRAGMA user_version=1")
        connection.commit()
        connection.close()
        with BookmarkIndex(self.db) as index:
            self.assertEqual(2, index.connection.execute("PRAGMA user_version").fetchone()[0])
            rows = {row["item_id"]: dict(row) for row in index.connection.execute("SELECT * FROM items")}
        self.assertEqual("2026-06-27T00:00:00+00:00", rows["tempId_20260627_hash_1se4a28"]["added_at"])
        self.assertEqual("id_date_segment", rows["tempId_20260627_hash_1se4a28"]["added_at_source"])
        self.assertEqual("low", rows["tempId_20260627_hash_1se4a28"]["added_at_confidence"])
        self.assertEqual("2025-11-17T05:21:53.791000+00:00", rows["bookmark-alpha"]["added_at"])
        self.assertEqual("dateAdded", rows["bookmark-alpha"]["added_at_source"])
        self.assertEqual("high", rows["bookmark-alpha"]["added_at_confidence"])

    def test_a_version_2_index_is_not_repaired_again(self):
        index, source_id = self.indexed(lambda root: dated_temp_card(
            root, "temp-section-A-1", "A-1", "tempId_20260627_hash_1se4a28"))
        index.close()
        with BookmarkIndex(self.db) as reopened:
            self.assertEqual(2, reopened.connection.execute("PRAGMA user_version").fetchone()[0])
            row = reopened.search(source_id, targets=["Lumen"])["results"][0]
        self.assertEqual("2026-06-27T00:00:00+00:00", row["added_at"])
        self.assertEqual("day", row["added_at_precision"])
        self.assertEqual("low", row["added_at_confidence"])

    def test_items_report_added_at_source_and_derived_precision(self):
        def both(root):
            permanent_card(root)
            dated_temp_card(root, "temp-section-A-1", "A-1", "tempId_20260627_hash_1se4a28")
        index, source_id = self.indexed(both)
        rows = {row["section_id"]: row for row in index.search(source_id, targets=["Lumen"])["results"]}
        stored = rows["permanent-section"]
        self.assertEqual("2025-11-17T05:21:53.791000+00:00", stored["added_at"])
        self.assertEqual("dateAdded", stored["added_at_source"])
        self.assertEqual("millisecond", stored["added_at_precision"])
        self.assertEqual("high", stored["added_at_confidence"])
        temporary = rows["temp-section-A-1"]
        self.assertEqual("2026-06-27T00:00:00+00:00", temporary["added_at"])
        self.assertEqual("id_date_segment", temporary["added_at_source"])
        self.assertEqual("day", temporary["added_at_precision"])
        self.assertEqual("low", temporary["added_at_confidence"])

    def test_edges_are_ordered_by_their_own_time_and_unparsed_ones_come_last(self):
        def package(root):
            permanent_card(root)
            dated_temp_card(root, "temp-section-A-1", "A-1", "tempId_20260627_hash_1se4a28", name="A-1 示例")
            write_json(root, "Demo.canvas", {"nodes": [
                {"id": "permanent-section", "type": "file", "file": PRIMARY, "x": 0, "y": 0, "width": 40, "height": 40},
                {"id": "temp-section-A-1", "type": "file", "file": TEMP, "x": 60, "y": 0, "width": 40, "height": 40}],
                "edges": [
                    {"id": "edge - 2 -1782572418511", "fromNode": "permanent-section", "toNode": "temp-section-A-1"},
                    {"id": "edge - 1 -1782572278545", "fromNode": "temp-section-A-1", "toNode": "permanent-section"},
                    {"id": "edge-untimed", "fromNode": "permanent-section", "toNode": "temp-section-A-1"}]})
        index, source_id = self.indexed(package)
        edges = index.context(source_id)["edges"]
        self.assertEqual(["edge - 1 -1782572278545", "edge - 2 -1782572418511", "edge-untimed"],
                         [edge["edge_id"] for edge in edges])
        self.assertEqual("edge_epoch", edges[0]["added_at_source"])
        self.assertEqual("millisecond", ADDED_AT_SOURCES[edges[0]["added_at_source"]][0])
        self.assertLess(edges[0]["added_at"], edges[1]["added_at"])
        self.assertIsNone(edges[2]["added_at"])
        self.assertIsNone(edges[2]["added_at_source"])

    def test_a_newer_card_wins_a_score_and_hit_tie(self):
        def package(root):
            dated_temp_card(root, "temp-section-A-1", "A-1", "tempId_20260101_hash_aaaaaaaa")
            dated_temp_card(root, "temp-section-A-2", "A-2", "tempId_20261001_hash_bbbbbbbb")
        index, source_id = self.indexed(package)
        cards = index.plan_scope(source_id, "Lumen")["cards"]
        self.assertEqual(["A-2", "A-1"], [card["label"] for card in cards])
        self.assertEqual(cards[0]["score"], cards[1]["score"])
        self.assertEqual(cards[0]["hits"], cards[1]["hits"])
        self.assertEqual("2026-10-01T00:00:00+00:00", cards[0]["newest_added_at"])
        self.assertEqual("2026-01-01T00:00:00+00:00", cards[1]["newest_added_at"])

    def test_cards_without_any_time_keep_the_deterministic_order(self):
        index, source_id = self.indexed()
        cards = index.plan_scope(source_id, "alpha")["cards"]
        self.assertEqual(2, len(cards))
        self.assertTrue(all(card["newest_added_at"] is None for card in cards))


if __name__ == "__main__":
    unittest.main()
