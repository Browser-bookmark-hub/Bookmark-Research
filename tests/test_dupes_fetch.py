"""Duplicate-URL reports and fetch routing (search pages, TTL cache)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from settings import Settings
from source_manager import SourceManager
from url_classify import is_search_result_url
from web_search import SearchProviders
from test_bookmark_index import make_package


def index_rows(base):
    import sqlite3
    conn = sqlite3.connect(str(Path(base) / "index.sqlite3"))
    conn.row_factory = sqlite3.Row
    try:
        return {row["title"]: dict(row) for row in
                conn.execute("SELECT title, folder_path FROM items")}
    finally:
        conn.close()


class UrlClassifyTests(unittest.TestCase):
    def test_search_pages_are_recognised(self):
        for url in ("https://www.bing.com/search?q=3d", "https://cn.bing.com/search?q=3d",
                    "https://www.google.com/search?q=3d", "https://duckduckgo.com/?q=3d",
                    "https://www.baidu.com/s?wd=3d"):
            self.assertTrue(is_search_result_url(url), url)

    def test_documents_are_not_search_pages(self):
        for url in ("https://github.com/Tencent-Hunyuan/HunyuanWorld-Voyager",
                    "https://arxiv.org/pdf/2510.19944", "https://www.bing.com/",
                    "https://www.google.com/maps", "", "not a url"):
            self.assertFalse(is_search_result_url(url), url)


class DuplicateReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-dupes-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        package = self.base / "package"
        make_package(package)
        with BookmarkIndex(self.base / "index.sqlite3") as index:
            self.source_id = SourceManager(index).sync(package, mode="snapshot")["source_id"]
        self.index = BookmarkIndex(self.base / "index.sqlite3", readonly=True)
        self.addCleanup(self.index.close)

    def test_duplicate_groups_keep_a_proposed_copy(self):
        result = self.index.duplicate_urls(self.source_id)
        self.assertGreaterEqual(result["total_groups"], 1)
        group = next(item for item in result["groups"]
                     if item["url"] == "https://example.test/alpha")
        self.assertGreaterEqual(group["copies"], 2)
        self.assertEqual(group["copies"], len(group["instances"]))
        self.assertIn(group["keep"]["item_id"],
                      [instance["item_id"] for instance in group["instances"]])
        self.assertIsNone(result["next_offset"])

    def test_min_count_must_be_a_real_duplicate_threshold(self):
        with self.assertRaises(ValueError):
            self.index.duplicate_urls(self.source_id, min_count=1)


class FetchCacheTests(unittest.TestCase):
    def test_prune_drops_expired_and_excess_rows(self):
        from fetch_cache import FetchCache
        with tempfile.TemporaryDirectory(prefix="bookmark-cache-test-") as temporary:
            cache = FetchCache(Path(temporary) / "cache.sqlite3")
            try:
                cache.put("a", ["https://example.test/a"], "exa", {"retrieved_at": "x"})
                cache.put("b", ["https://example.test/b"], "exa", {"retrieved_at": "x"})
                with cache.connection:
                    cache.connection.execute(
                        "UPDATE fetch_cache SET stored_at=0 WHERE cache_key='a'")
                self.assertEqual(1, cache.prune(ttl_seconds=60))
                self.assertIsNone(cache.get("a", 60))
                self.assertIsNotNone(cache.get("b", 60))
            finally:
                cache.close()



class FetchRoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-fetch-route-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.settings = Settings(self.base / "settings.json")
        self.settings.update({"archive": {"directory": str(self.base / "knowledge")}})
        self.engine = SearchProviders(settings=self.settings)

    def test_search_pages_are_skipped_without_calling_a_provider(self):
        with patch.object(self.engine, "_fetch", side_effect=AssertionError("network")):
            result = self.engine.fetch(["https://www.bing.com/search?q=3d"], archive=False)
        self.assertEqual("error", result["status"])
        self.assertEqual(1, result["skipped_url_count"])
        self.assertEqual("search_result_page", result["per_url"][0]["extraction_status"])

    def test_mixed_batch_fetches_only_documents(self):
        fake = {"provider": "exa", "status": "ok", "retrieved_at": "2026-01-01T00:00:00+00:00",
                "per_url": [{"url": "https://example.test/a", "status": "ok",
                             "content_state": "usable"}],
                "successful_url_count": 1}
        with patch.object(self.engine, "_fetch", return_value=fake) as inner:
            result = self.engine.fetch(["https://www.bing.com/search?q=x",
                                        "https://example.test/a"], archive=False)
        inner.assert_called_once()
        self.assertEqual(["https://example.test/a"], inner.call_args[0][0])
        self.assertEqual(2, len(result["per_url"]))
        self.assertEqual(1, result["skipped_url_count"])

    def test_cache_reuses_an_identical_batch(self):
        preferences = self.settings.load()
        preferences["fetch"]["reuse_seconds"] = 60
        fake = {"provider": "exa", "status": "ok", "retrieved_at": "2026-01-01T00:00:00+00:00",
                "per_url": [{"url": "https://example.test/a", "status": "ok",
                             "content_state": "usable"}],
                "successful_url_count": 1}
        with patch.object(self.settings, "load", return_value=preferences), \
                patch.object(self.engine, "_fetch", return_value=fake) as inner:
            self.engine.fetch(["https://example.test/a"], archive=False)
            second = self.engine.fetch(["https://example.test/a"], archive=False)
        self.assertEqual(1, inner.call_count)
        self.assertTrue(second.get("cached"))


class SingleFileExportTests(unittest.TestCase):
    """The canvas right-click export: section JSON without ids, and Netscape HTML."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-export-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def _sync(self, path, source="export"):
        index = BookmarkIndex(self.base / "index.sqlite3")
        self.addCleanup(index.close)
        return SourceManager(index).sync(path, source_id=source, mode="snapshot")

    def test_section_json_export_without_ids_imports(self):
        payload = {"format": "bookmark-canvas-section", "schemaVersion": 2,
                   "sectionType": "temporary", "title": "批量导出的书签", "tempKind": "special",
                   "source": "batch", "label": "批量", "items": [
                       {"title": "Example A", "url": "https://example.test/a", "type": "bookmark", "children": []},
                       {"title": "Folder", "url": None, "type": "folder", "children": [
                           {"title": "Example B", "url": "https://example.test/b", "type": "bookmark",
                            "children": [], "note": "n", "noteColor": "yellow",
                            "tags": [{"color": "red", "text": "t"}]}]}]}
        path = self.base / "export.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = self._sync(path)
        self.assertEqual(3, result["counts"]["items"])
        self.assertEqual(2, result["counts"]["bookmarks"])
        index = BookmarkIndex(self.base / "index.sqlite3", readonly=True)
        self.addCleanup(index.close)
        summary = index.source_summary("export")
        self.assertEqual(1, summary["notes"])
        self.assertEqual(1, summary["notes_bookmarks"])
        self.assertEqual(0, summary["notes_folders"])

    def test_netscape_html_export_imports_nested_folders(self):
        path = self.base / "bookmarks.html"
        path.write_text("""<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3>工具</H3>
    <DL><p>
        <DT><A HREF="https://example.test/a">Example A</A>
        <DT><H3>子目录</H3>
        <DL><p>
            <DT><A HREF="https://example.test/b">Example B</A>
        </DL><p>
    </DL><p>
    <DT><A HREF="https://example.test/c">Example C</A>
</DL><p>
""", encoding="utf-8")
        result = self._sync(path)
        self.assertEqual(5, result["counts"]["items"])
        self.assertEqual(3, result["counts"]["bookmarks"])
        rows = {title: row["folder_path"] for title, row in index_rows(self.base).items()}
        self.assertEqual("工具 / 子目录", rows["Example B"])
        self.assertEqual("工具", rows["Example A"])

    def test_wrapped_envelope_and_bare_list_import(self):
        section = {"format": "bookmark-canvas-section", "schemaVersion": 2,
                   "sectionType": "temporary", "title": "Wrapped", "label": "添加",
                   "items": [{"title": "A", "url": "https://example.test/a"}]}
        wrapped = self.base / "wrapped.json"
        wrapped.write_text(json.dumps({"data": section}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(1, self._sync(wrapped, "wrapped")["counts"]["items"])

        bare = self.base / "bare.json"
        bare.write_text(json.dumps([{"title": "B", "url": "https://example.test/b"},
                                    {"title": "C", "url": "https://example.test/c"}]),
                        encoding="utf-8")
        self.assertEqual(2, self._sync(bare, "bare")["counts"]["items"])

    def test_divider_rows_are_excluded_from_duplicates_and_counted(self):
        divider = "https://www.bing.com/search?q=%E2%94%80%E2%94%80%E2%94%80&cvid=1"
        payload = {"format": "bookmark-canvas-section", "schemaVersion": 2,
                   "sectionType": "temporary", "title": "Dividers", "label": "添加",
                   "source": "batch", "tempKind": "special", "items": [
                       {"title": "───────────── - 搜索", "url": divider, "type": "bookmark"},
                       {"title": "───────────── - 搜索", "url": divider, "type": "bookmark"},
                       {"title": "Real A", "url": "https://example.test/a", "type": "bookmark"},
                       {"title": "Real A copy", "url": "https://example.test/a", "type": "bookmark"}]}
        path = self.base / "dividers.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._sync(path)

        index = BookmarkIndex(self.base / "index.sqlite3", readonly=True)
        self.addCleanup(index.close)
        source_id = index.resolve_source_id("export")
        report = index.duplicate_urls(source_id)
        self.assertEqual(["https://example.test/a"],
                         [group["url"] for group in report["groups"]])
        self.assertEqual(2, report["junk_instances_excluded"])

        summary = index.source_summary(source_id)
        self.assertEqual(2, summary["junk_items"])
        self.assertEqual(0, summary["notes"])
        self.assertEqual(0, summary["notes_bookmarks"])
        self.assertEqual("batch", summary["sections"][0]["source"])
        self.assertEqual("special", summary["sections"][0]["temp_kind"])


if __name__ == "__main__":
    unittest.main()
