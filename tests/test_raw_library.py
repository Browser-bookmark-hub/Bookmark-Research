"""Content-addressed archive pages and the derived raw-material full-text index."""

import hashlib
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
import research_locations


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RawLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-raw-library-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.data = self.base / "data"
        environment = mock.patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.data)})
        environment.start()
        self.addCleanup(environment.stop)
        self.archive = SourceArchive(self.data / "knowledge")
        self.library = RawLibrary(archive_directory=self.data / "knowledge")

    def capture(self, url, text, retrieved_at="2026-09-29T00:00:00+00:00"):
        return self.archive.save({"provider": "exa", "tool": "web_fetch_exa", "urls": [url],
            "result": {"structuredContent": {"url": url, "title": "Title " + url, "text": text}},
            "retrieved_at": retrieved_at, "request_arguments": {"urls": [url]}, "requested_max_characters": 12000})

    def task(self, directory, research_id, bodies, register=True):
        """Write a research task folder shaped like research.py state (sources with body_file/sha256)."""
        sources = []
        for index, (url, text) in enumerate(bodies, 1):
            relative = "evidence/pages/%s.md" % sha(text)
            (directory / relative).parent.mkdir(parents=True, exist_ok=True)
            (directory / relative).write_text(text, encoding="utf-8")
            sources.append({"id": "s%s" % index, "url": url, "title": "Evidence %s" % index,
                            "retrieved_at": "2026-09-2%sT00:00:00+00:00" % index, "extraction_status": "extracted",
                            "sha256": sha(text), "body_file": relative})
        sources.append({"id": "s-failed", "url": "https://example.test/failed", "sha256": None, "body_file": None})
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "state.json").write_text(json.dumps({"schema_version": 1, "research_id": research_id,
                                                          "sources": sources}), encoding="utf-8")
        if register:
            research_locations.register(research_id, directory, "2026-09-29T00:00:00+00:00", "central")
        return directory

    def test_identical_bodies_are_stored_once_and_each_capture_keeps_its_manifest(self):
        first = self.capture("https://example.test/a", "Same body text")
        second = self.capture("https://example.test/b", "Same body text")
        self.assertNotEqual(first["directory"], second["directory"])
        pages = list((self.data / "knowledge" / "pages").glob("*.md"))
        self.assertEqual([page.name for page in pages], [sha("Same body text") + ".md"])
        self.assertEqual(first["pages"][0]["body_path"], second["pages"][0]["body_path"])
        for saved in (first, second):
            manifest = json.loads(Path(saved["manifest_path"]).read_text())
            self.assertEqual(manifest["schema_version"], 2)
            entry = manifest["pages"][0]
            self.assertEqual(entry["body_file"], "../../pages/%s.md" % entry["sha256"])
            self.assertEqual(self.archive.read_page(saved["directory"], entry), "Same body text")
            self.assertTrue(Path(saved["response_path"]).is_file())
        result = self.library.search("body text")
        self.assertEqual(result["total"], 1)
        self.assertEqual(sorted(row["url"] for row in result["results"][0]["occurrences"]),
                         ["https://example.test/a", "https://example.test/b"])
        self.assertEqual({row["capture_id"] for row in result["results"][0]["occurrences"]},
                         {first["capture_id"], second["capture_id"]})

    def test_damaged_shared_page_is_repaired_by_a_new_identical_capture(self):
        first = self.capture("https://example.test/a", "Original text")
        Path(first["pages"][0]["body_path"]).write_text("Tampered")
        manifest = json.loads(Path(first["manifest_path"]).read_text())
        with self.assertRaises(ValueError):
            self.archive.read_page(first["directory"], manifest["pages"][0])
        self.capture("https://example.test/a", "Original text")
        self.assertEqual(self.archive.read_page(first["directory"], manifest["pages"][0]), "Original text")

    def test_legacy_capture_layout_is_still_readable_and_indexed(self):
        capture = self.data / "knowledge" / "sources" / "20260901T000000000000Z-legacy"
        (capture / "pages").mkdir(parents=True)
        body = "Legacy capture body with marker"
        (capture / "pages" / "0123456789abcdef01234567.md").write_text(body)
        entry = {"requested_url": "https://legacy.test/", "title": "Legacy", "body_file": "pages/0123456789abcdef01234567.md",
                 "sha256": sha(body), "page_body_archived": True}
        (capture / "manifest.json").write_text(json.dumps({"schema_version": 1, "capture_id": capture.name,
            "retrieved_at": "2026-09-01T00:00:00+00:00", "pages": [entry]}))
        self.assertEqual(self.archive.read_page(capture, entry), body)
        self.assertEqual([name for name, _ in self.archive.captures()], [capture.name])
        result = self.library.search("marker")
        self.assertEqual(result["results"][0]["occurrences"][0]["capture_id"], capture.name)
        self.assertEqual(result["results"][0]["title"], "Legacy")
        escaping = dict(entry, body_file="../../../outside.md")
        (self.data / "outside.md").write_text(body)
        with self.assertRaises(ValueError):
            self.archive.page_path(capture, escaping)

    def test_archive_and_research_evidence_are_merged_by_content_hash(self):
        shared = "Shared evidence body about knowledge storage."
        self.capture("https://example.test/shared", shared)
        registered = self.task(self.base / "elsewhere" / "task.bookmark-research", "r-" + "a" * 16,
                               [("https://example.test/shared", shared), ("https://example.test/only", "Only research evidence here.")])
        self.task(self.data / "research" / ("r-" + "b" * 16), "r-" + "b" * 16,
                  [("https://example.test/legacy", "Legacy task evidence here.")], register=False)
        result = self.library.search("evidence")
        self.assertEqual(result["total"], 3)
        merged = next(row for row in result["results"] if row["sha256"] == sha(shared))
        kinds = sorted((row["kind"], row.get("research_id"), row.get("source_id")) for row in merged["occurrences"])
        self.assertEqual(kinds, [("archive", None, None), ("research", "r-" + "a" * 16, "s1")])
        research = next(row for row in merged["occurrences"] if row["kind"] == "research")
        self.assertEqual(research["path"], str(registered / "evidence" / "pages" / (sha(shared) + ".md")))
        self.assertEqual(research["retrieved_at"], "2026-09-21T00:00:00+00:00")
        self.assertIn("knowledge storage", merged["snippet"])
        self.assertEqual(result["indexed"]["documents"], 3)
        self.assertEqual(result["indexed"]["skipped"], 0)
        self.assertEqual(self.library.search("evidence", url="legacy")["total"], 1)
        self.assertEqual(self.library.search('"evidence body about"')["total"], 1)
        self.assertEqual(self.library.search("evidence nothing-like-this")["total"], 0)
        page = self.library.search("evidence", limit=2, offset=0)
        self.assertEqual((len(page["results"]), page["next_offset"]), (2, 2))

    def test_tampered_body_is_skipped_and_counted(self):
        directory = self.task(self.base / "task", "r-" + "c" * 16, [("https://example.test/x", "Original evidence")])
        self.assertEqual(self.library.search("Original")["total"], 1)
        body = directory / "evidence" / "pages" / (sha("Original evidence") + ".md")
        body.write_text("Changed evidence")
        result = self.library.search("evidence")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["indexed"]["skipped"], 1)
        self.assertEqual(result["indexed"]["documents"], 0)
        body.write_text("Original evidence")
        result = self.library.search("evidence")
        self.assertEqual((result["total"], result["indexed"]["skipped"]), (1, 0))

    def test_bodies_outside_the_task_folder_or_symlinked_tasks_are_not_followed(self):
        outside = self.base / "outside.md"
        outside.write_text("Secret outside text")
        directory = self.base / "task"
        directory.mkdir()
        (directory / "state.json").write_text(json.dumps({"research_id": "r-" + "d" * 16, "sources": [
            {"id": "s1", "url": "https://example.test/", "sha256": sha("Secret outside text"), "body_file": "../outside.md"}]}))
        research_locations.register("r-" + "d" * 16, directory, "2026-09-29T00:00:00+00:00", "central")
        linked = self.task(self.base / "real-task", "r-" + "e" * 16, [("https://example.test/", "Linked task text")], register=False)
        (self.data / "research").mkdir(parents=True, exist_ok=True)
        try:
            (self.data / "research" / ("r-" + "e" * 16)).symlink_to(linked, target_is_directory=True)
        except OSError:
            self.skipTest("Symlinks are not permitted on this system")
        result = self.library.search("text")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["indexed"]["skipped"], 1)

    def test_missing_or_removed_task_folders_are_tolerated(self):
        research_locations.register("r-" + "f" * 16, self.base / "moved-away", "2026-09-29T00:00:00+00:00", "central")
        directory = self.task(self.base / "task", "r-" + "1" * 16, [("https://example.test/", "Temporary evidence")])
        result = self.library.search("Temporary")
        self.assertEqual((result["total"], result["indexed"]["missing_tasks"]), (1, 1))
        for path in sorted(directory.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        directory.rmdir()
        result = self.library.search("Temporary")
        self.assertEqual((result["total"], result["indexed"]["missing_tasks"], result["indexed"]["documents"]), (0, 2, 0))

    def test_refresh_is_incremental(self):
        self.capture("https://example.test/one", "First incremental page")
        first = self.library.search("incremental")
        self.assertEqual((first["total"], first["indexed"]["scanned_units"]), (1, 1))
        again = self.library.search("incremental")
        self.assertEqual((again["indexed"]["scanned_units"], again["indexed"]["new_documents"]), (0, 0))
        self.capture("https://example.test/two", "Second incremental page")
        self.capture("https://example.test/three", "First incremental page")
        added = self.library.search("incremental")
        self.assertEqual(added["total"], 2)
        self.assertEqual((added["indexed"]["scanned_units"], added["indexed"]["new_documents"]), (2, 1))
        self.assertEqual(added["indexed"]["occurrences"], 3)

    def test_chinese_substrings_match(self):
        self.capture("https://example.test/zh", "# 知识库统一计划\n\n研究结果默认位置是统一目录。")
        self.capture("https://example.test/en", "English only page")
        for query in ("研究结果", "知识", "统一目录", "知识 目录"):
            with self.subTest(query=query):
                result = self.library.search(query)
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["results"][0]["url"], "https://example.test/zh")
        self.assertIn("研究结果", self.library.search("研究结果")["results"][0]["snippet"])
        self.assertEqual(self.library.search("研究结论")["total"], 0)

    def test_substring_fallback_without_trigram_tokenizer(self):
        self.capture("https://example.test/zh", "研究结果默认位置 and Mixed Case words")
        self.assertEqual(self.library.search("研究结果")["match"], "fts_trigram" if self.library.mode == "trigram" else "substring")
        with mock.patch("raw_library._trigram_available", return_value=False):
            fallback = RawLibrary(archive_directory=self.data / "knowledge")
        self.assertEqual(fallback.mode, "substring")
        for query in ("研究结果", "mixed case", "位置 words"):
            with self.subTest(query=query):
                result = fallback.search(query)
                self.assertEqual((result["total"], result["match"]), (1, "substring"))
        self.assertEqual(fallback.search("absent")["total"], 0)

    def test_index_is_rebuilt_when_damaged_and_rejects_invalid_queries(self):
        self.capture("https://example.test/", "Rebuildable page")
        self.assertEqual(self.library.search("Rebuildable")["total"], 1)
        self.library.db_path.write_bytes(b"not a database" * 100)
        for suffix in ("-wal", "-shm"):
            Path(str(self.library.db_path) + suffix).unlink(missing_ok=True)
        self.assertEqual(self.library.search("Rebuildable")["total"], 1)
        for query in ("", "   ", "x" * 501):
            with self.assertRaises(ValueError):
                self.library.search(query)
        with self.assertRaises(ValueError):
            self.library.search("page", limit=0)

    def test_cli_prints_json_results(self):
        import contextlib
        import io
        import cli
        self.capture("https://example.test/cli", "Command line archive page")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(["--config", str(self.base / "settings.json"), "search-archive", "archive page",
                             "--limit", "5", "--url", "/cli"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual((result["total"], result["results"][0]["url"]), (1, "https://example.test/cli"))

    def test_main_index_is_untouched(self):
        self.capture("https://example.test/", "Separate database page")
        self.library.search("Separate")
        self.assertTrue((self.data / "raw-library.sqlite3").is_file())
        self.assertFalse((self.data / "index.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
