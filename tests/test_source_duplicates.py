"""Duplicate imports are reported, and imported sources can be cleaned up.

Importing the same canvas from a new folder used to add a second, identical
source with no warning and no way to undo it, so a long-lived knowledge base
silently accumulated duplicate copies of the same content.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from source_manager import SourceManager


def package(root, label="A-1", urls=("https://example.test/one",)):
    section = {"format": "bookmark-canvas-section", "schemaVersion": 2, "id": "temp-section-" + label,
               "sectionType": "temporary", "label": label, "title": "Sources " + label,
               "items": [{"id": "b%d" % index, "sectionId": "temp-section-" + label, "type": "bookmark",
                          "url": url, "title": "Title " + url} for index, url in enumerate(urls)]}
    (root / "临时栏目").mkdir(parents=True, exist_ok=True)
    (root / "临时栏目" / (label + ".json")).write_text(json.dumps(section, ensure_ascii=False), encoding="utf-8")
    return root


class DuplicateSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="duplicate sources ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.db = self.base / "data" / "index.sqlite3"
        self.db.parent.mkdir(parents=True)
        self.index = BookmarkIndex(self.db)
        self.addCleanup(self.index.close)
        self.manager = SourceManager(self.index)

    def test_new_source_with_identical_content_is_reported_as_a_duplicate(self):
        first = self.manager.sync(package(self.base / "first"), mode="snapshot")
        self.assertEqual([], first["warnings"])
        # A different folder with byte-identical content is a duplicate.
        copy = self.base / "copy"
        shutil.copytree(self.base / "first", copy)
        second = self.manager.sync(copy, mode="snapshot")
        self.assertIn(first["source_id"], second["duplicate_source_ids"])
        self.assertTrue(any("Identical content is already indexed" in warning for warning in second["warnings"]),
                        second["warnings"])
        self.assertEqual(first["version_id"], second["version_id"])

    def test_reusing_source_id_updates_instead_of_duplicating(self):
        first = self.manager.sync(package(self.base / "first"), mode="snapshot")
        copy = self.base / "copy"
        shutil.copytree(self.base / "first", copy)
        again = self.manager.sync(copy, source_id=first["source_id"], mode="snapshot")
        self.assertNotIn("duplicate_source_ids", again)
        self.assertEqual(0, again["items_inserted"])
        self.assertEqual(1, len(self.manager.status()["sources"]))

    def test_remove_requires_confirmation_and_then_deletes_everything(self):
        result = self.manager.sync(package(self.base / "first"), mode="snapshot")
        source_id = result["source_id"]
        planned = self.manager.remove(source_id)
        self.assertEqual("confirmation_required", planned["status"])
        self.assertEqual(1, planned["would_remove"]["items"])
        self.assertEqual(1, len(self.manager.status()["sources"]))
        removed = self.manager.remove(source_id, confirm=True)
        self.assertEqual("removed", removed["status"])
        self.assertEqual([], self.manager.status()["sources"])
        snapshot = Path(result["snapshot_path"]).parents[1]
        self.assertFalse(snapshot.exists(), snapshot)
        with self.index.read_snapshot():
            self.assertEqual(0, self.index.connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])
            self.assertEqual(0, self.index.connection.execute("SELECT COUNT(*) FROM items_fts").fetchone()[0])

    def test_merge_drops_a_duplicate_and_moves_its_paths(self):
        first = self.manager.sync(package(self.base / "first"), mode="snapshot")
        copy = self.base / "copy"
        shutil.copytree(self.base / "first", copy)
        duplicate = self.manager.sync(copy, mode="snapshot")
        planned = self.manager.merge(duplicate["source_id"], first["source_id"])
        self.assertEqual("confirmation_required", planned["status"])
        self.assertEqual(2, len(self.manager.status()["sources"]))
        merged = self.manager.merge(duplicate["source_id"], first["source_id"], confirm=True)
        self.assertEqual("merged", merged["status"])
        survivors = self.manager.status()["sources"]
        self.assertEqual([first["source_id"]], [row["source_id"] for row in survivors])
        # The duplicate's folder now updates the survivor instead of re-adding a source.
        again = self.manager.sync(copy, mode="snapshot")
        self.assertEqual(first["source_id"], again["source_id"])
        self.assertEqual(1, len(self.manager.status()["sources"]))

    def test_merge_refuses_sources_with_different_content(self):
        first = self.manager.sync(package(self.base / "first", urls=("https://example.test/one",)), mode="snapshot")
        other = self.manager.sync(package(self.base / "other", urls=("https://example.test/two",)), mode="snapshot")
        with self.assertRaisesRegex(ValueError, "different content versions"):
            self.manager.merge(other["source_id"], first["source_id"], confirm=True)

    def test_unknown_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown source_id"):
            self.manager.remove("source-" + "0" * 16, confirm=True)


if __name__ == "__main__":
    unittest.main()
