"""Read paths must survive a read-only data directory (shared index, ro mount, sandbox)."""

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from archive import SourceArchive
from raw_library import RawLibrary
from source_versions import SourceVersions
from wiki_search import WikiSearchIndex
import cli
import storage


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ReadOnlyStoreTests(unittest.TestCase):
    """Every derived store degrades to ``mode=ro`` instead of failing or writing."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-readonly-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        environment = mock.patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.addCleanup(self._restore)

    def _restore(self):
        # Restore permissions before TemporaryDirectory cleanup removes the tree.
        for path in sorted(self.base.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            try:
                if path.is_dir():
                    path.chmod(0o755)
                else:
                    path.chmod(0o644)
            except OSError:
                pass
        try:
            self.base.chmod(0o755)
        except OSError:
            pass

    def freeze(self, *paths):
        for path in paths:
            if Path(path).is_dir():
                Path(path).chmod(0o555)
            else:
                Path(path).chmod(0o444)

    def test_archive_search_reads_read_only_index_without_refreshing(self):
        archive = SourceArchive(self.base / "knowledge")
        archive.save({"provider": "exa", "tool": "web_fetch_exa", "urls": ["https://example.com/a"],
                      "result": {"structuredContent": {"url": "https://example.com/a",
                                                       "title": "Alpha", "text": "gaussian splatting notes"}},
                      "retrieved_at": "2026-09-29T00:00:00+00:00",
                      "request_arguments": {"urls": ["https://example.com/a"]},
                      "requested_max_characters": 12000})
        library = RawLibrary(archive_directory=self.base / "knowledge")
        self.assertEqual(1, library.search("gaussian")["total"])
        for suffix in ("-wal", "-shm"):
            Path(str(library.db_path) + suffix).unlink(missing_ok=True)
        before = {path.name for path in self.base.iterdir()}
        self.freeze(self.base, library.db_path)
        result = library.search("gaussian")
        self.assertEqual(1, result["total"])
        self.assertEqual("skipped_read_only", result["index_refresh"])
        self.assertEqual(before, {path.name for path in self.base.iterdir()},
                         "reading a read-only index must not create sidecar files")

    def test_wiki_search_index_answers_without_rebuilding(self):
        index_path = self.base / "search.sqlite3"
        index = WikiSearchIndex(index_path)
        with index.connection() as connection:
            connection.execute("INSERT INTO documents (page_id,sha256,title,body,aliases,headings) "
                               "VALUES ('p1',?,?,?,?,?)", (sha("a"), "Alpha", "body text", "", ""))
            connection.executemany("INSERT INTO postings VALUES (?,?)",
                                   ((gram, "p1") for gram in index.grams("Alpha\nbody text\n")))
        self.freeze(index_path.parent, index_path)
        rows, invalid = index.candidates({"pages": {"p1": {"sha256": sha("a")}}}, lambda pointer: {}, [["alpha"]])
        self.assertEqual(["p1"], [row["page_id"] for row in rows])
        self.assertEqual([], invalid)

    def test_source_versions_inspect_reads_read_only_index(self):
        versions = SourceVersions(self.base / "source-versions.sqlite3")
        versions.record_check("https://example.com/a", "ok")
        self.freeze(self.base, versions.path)
        report = versions.inspect("https://example.com/a", sha("a"),
                                  "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
        self.assertTrue(report["available"])
        self.assertEqual("ok", report["last_attempt"]["status"])

    def test_cli_context_and_traverse_skip_refresh_on_read_only_index(self):
        package = self.base / "Package" / "临时栏目" / "常规链式"
        package.mkdir(parents=True)
        document = {
            "format": "bookmark-canvas-section", "schemaVersion": 2,
            "sectionType": "temporary", "id": "temp-section-A-1", "label": "A-1", "title": "Test",
            "items": [{"id": "folder", "sectionId": "temp-section-A-1", "type": "folder",
                       "title": "Collection", "children": [
                           {"id": "one", "sectionId": "temp-section-A-1", "type": "bookmark",
                            "title": "Needle", "url": "https://example.test/one",
                            "note": "kept note"}]}],
        }
        (package / "A-1 demo.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        data = self.base / "data"
        data.mkdir()
        db = data / "index.sqlite3"
        config = self.base / "settings.json"

        def run(*arguments):
            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                code = cli.main(["--db", str(db), "--config", str(config), *arguments])
            return code, json.loads(output.getvalue())

        self.assertEqual(0, run("sync", str(self.base / "Package"), "--source-id", "fixture")[0])
        self.freeze(data, db)
        code, context = run("context", "fixture", "--item", "one")
        self.assertEqual(0, code)
        self.assertEqual("skipped", context["refresh"]["state"])
        self.assertEqual("Needle", context["items"][0]["title"])
        code, search = run("search", "fixture", "--target", "Needle")
        self.assertEqual(0, code)
        self.assertEqual("skipped", search["refresh"]["state"])
        self.assertEqual(1, search["total"])

    def test_read_only_connect_falls_back_to_immutable_without_sidecars(self):
        archive = SourceArchive(self.base / "knowledge")
        archive.save({"provider": "exa", "tool": "web_fetch_exa", "urls": ["https://example.com/b"],
                      "result": {"structuredContent": {"url": "https://example.com/b",
                                                       "title": "Beta", "text": "point cloud"}},
                      "retrieved_at": "2026-09-29T00:00:00+00:00",
                      "request_arguments": {"urls": ["https://example.com/b"]},
                      "requested_max_characters": 12000})
        library = RawLibrary(archive_directory=self.base / "knowledge")
        library.search("point")  # builds and checkpoints the index
        for suffix in ("-wal", "-shm"):
            Path(str(library.db_path) + suffix).unlink(missing_ok=True)
        self.freeze(library.db_path.parent, library.db_path)
        connection = storage.connect(library.db_path, readonly=True)
        try:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
