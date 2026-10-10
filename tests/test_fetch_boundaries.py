"""Evidence boundaries and output budgets must hold independently of providers."""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from archive import SourceArchive
from raw_library import RawLibrary
from research import ResearchSessions
from settings import Settings


class FetchBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.archive = SourceArchive(Path(temporary.name) / "knowledge")

    def capture(self, response, urls, limit=200):
        fetched = {"provider": "exa", "tool": "fixture_fetch", "urls": urls, "result": response,
                   "request_arguments": {"urls": urls}, "requested_max_characters": limit,
                   "retrieved_at": "2026-10-10T00:00:00Z"}
        fetched["archive"] = self.archive.save(fetched)
        return fetched

    def test_a_later_page_cannot_close_a_truncated_previous_pages_fence(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        fence = chr(96) * 3
        for second_url in (urls[1], "https://redirect.test/b"):
            with self.subTest(second_url=second_url):
                text = ("# A\nURL: " + urls[0] + "\n\nFirst page.\n" + fence + "python\ntruncated\n\n"
                        "# B\nURL: " + second_url + "\n\nB_ONLY_EVIDENCE\n" + fence + "\nSecond page.")
                response = {"content": [{"type": "text", "text": text}]}
                fetched = self.capture(response, urls)
                self.assertTrue(all(p["body_path"] is None for p in fetched["archive"]["pages"]))
                self.assertTrue(all(p["text"] is None for p in SourceArchive.compact_fetch(fetched)["pages"]))
                self.assertEqual(json.loads(Path(fetched["archive"]["response_path"]).read_text()), response)

    def test_compact_budget_and_continuation_preserve_the_same_archived_body(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        bodies = ["甲" * 350, "乙" * 400]
        response = {"structuredContent": {"results": [
            {"url": url, "text": body} for url, body in zip(urls, bodies)]}}
        fetched = self.capture(response, urls)
        view = SourceArchive.compact_fetch(fetched, max_total_characters=250)
        self.assertEqual([len(p["text"]) for p in view["pages"]], [200, 50])
        self.assertEqual([p["source_characters"] for p in view["pages"]], [350, 400])
        for index, page in enumerate(view["pages"]):
            self.assertEqual(Path(page["body_path"]).read_text(), bodies[index])
            self.assertEqual(page["sha256"], hashlib.sha256(bodies[index].encode()).hexdigest())
            continuation = page["continuation"]
            rest = self.archive.read_capture(continuation["capture_id"], continuation["urls"],
                offset=continuation["offset"], max_characters=1000)
            self.assertFalse(rest["network_request_performed"])
            self.assertEqual(page["text"] + rest["pages"][0]["text"], bodies[index])
            self.assertIsNone(rest["pages"][0]["next_offset"])
        self.assertEqual(fetched["result"], response)

    def test_read_capture_rejects_modified_evidence_and_invalid_capture_ids(self):
        url = "https://example.test/a"
        fetched = self.capture({"structuredContent": {"url": url, "text": "Evidence."}}, [url])
        capture = fetched["archive"]
        with self.assertRaises(ValueError):
            self.archive.read_capture("../elsewhere", [url])
        Path(capture["pages"][0]["body_path"]).write_text("Changed.")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.archive.read_capture(capture["capture_id"], [url])

    def test_legacy_mixed_source_capture_is_rejected_on_read_citation_and_existing_archive_search(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        fence = chr(96) * 3
        mixed = "Page A\n" + fence + "python\n\n# B\nURL: " + urls[1] + "\n\nB_ONLY_EVIDENCE\n" + fence + "\n"
        response = {"content": [{"type": "text", "text": "# A\nURL: " + urls[0] + "\n\n" + mixed}]}
        # Emulate an immutable capture written by the old ambiguous parser.
        with patch.object(SourceArchive, "_extract", return_value=[{"url": urls[0], "text": mixed}]):
            fetched = self.capture(response, urls)
        capture = fetched["archive"]
        manifest_path = Path(capture["manifest_path"])
        manifest = json.loads(manifest_path.read_text())
        manifest.pop("source_attribution_version")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        original = manifest_path.read_bytes()
        library = RawLibrary(data_directory=self.archive.directory.parent, archive_directory=self.archive.directory)
        with patch.object(SourceArchive, "legacy_hashes", return_value=None):
            self.assertEqual(1, library.search("B_ONLY_EVIDENCE")["total"])
        # An old raw-library index has no extraction-version tag in its signature.
        connection = library._connect()
        for unit, signature in connection.execute("SELECT unit,signature FROM units"):
            connection.execute("UPDATE units SET signature=? WHERE unit=?",
                               (json.dumps(json.loads(signature)[1:]), unit))
        connection.commit()
        connection.close()
        self.assertEqual(0, library.search("B_ONLY_EVIDENCE")["total"])
        with self.assertRaisesRegex(ValueError, "source attribution"):
            self.archive.read_capture(capture["capture_id"], [urls[0]])
        source = {"url": urls[0], "sha256": capture["pages"][0]["sha256"], "extraction_status": "extracted",
                  "body_file": str(Path(capture["pages"][0]["body_path"]).relative_to(self.archive.directory)),
                  "manifest_file": str(manifest_path.relative_to(self.archive.directory))}
        research = ResearchSessions(self.archive.directory.parent / "research")
        with self.assertRaisesRegex(ValueError, "source attribution"):
            research._body(self.archive.directory, source)
        compact = SourceArchive.compact_fetch(fetched)
        self.assertTrue(all(page["text"] is None and page.get("sha256") is None for page in compact["pages"]))
        self.assertEqual(original, manifest_path.read_bytes())

    def test_capture_continuation_works_through_mcp_and_cli_without_fetching(self):
        from cli import main
        from mcp_server import StdioMcpServer
        url, body = "https://example.test/a", "甲乙" * 200
        capture = self.capture({"structuredContent": {"url": url, "text": body}}, [url])["archive"]
        settings = Settings(self.archive.directory.parent / "settings.json")
        settings.update({"archive": {"directory": str(self.archive.directory)}})
        server = StdioMcpServer(self.archive.directory.parent / "index.sqlite3", stderr=io.StringIO(), settings=settings)
        self.addCleanup(server.close)
        server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}})
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        with patch.object(server, "_web", side_effect=AssertionError("Must remain offline")):
            result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "fetch_web", "arguments": {"urls": [url], "capture_id": capture["capture_id"],
                           "offset": 100, "max_characters": 100}}})
        self.assertFalse(result["result"]["isError"], result)
        self.assertEqual(body[100:200], result["result"]["structuredContent"]["pages"][0]["text"])
        stdout = io.StringIO()
        with patch("web_search.SearchProviders.fetch", side_effect=AssertionError("Must remain offline")), redirect_stdout(stdout):
            code = main(["--config", str(settings.path), "fetch-web", url, "--capture-id", capture["capture_id"],
                         "--offset", "100", "--max-characters", "100"])
        self.assertEqual(0, code)
        self.assertEqual(body[100:200], json.loads(stdout.getvalue())["pages"][0]["text"])

    def test_capture_directory_symlink_cannot_escape_the_configured_archive(self):
        url = "https://example.test/a"
        fetched = self.capture({"structuredContent": {"url": url, "text": "Evidence."}}, [url])
        sources = self.archive.directory / "sources"
        moved = self.archive.directory.parent / "other-sources"
        sources.rename(moved)
        sources.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.archive.read_capture(fetched["archive"]["capture_id"], [url])
        with self.assertRaises(ValueError):
            self.archive.save(fetched)


if __name__ == "__main__":
    unittest.main()
