"""Provider schemas, source parsing and failure isolation without live requests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from web_search import SearchProviders
from settings import Settings


EXA_SEARCH = {"name": "web_search_exa", "inputSchema": {"properties": {
    "query": {"type": "string"}, "numResults": {"type": "number"}}, "required": ["query"]}}
PARALLEL_SEARCH = {"name": "web_search", "inputSchema": {"properties": {
    "objective": {"type": "string"}, "search_queries": {"type": "array"}},
    "required": ["objective", "search_queries"]}}
EXA_FETCH = {"name": "web_fetch_exa", "inputSchema": {"properties": {
    "urls": {"type": "array"}, "maxCharacters": {"type": "number"}}, "required": ["urls"]}}


class SearchProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-web-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.settings = Settings(self.base / "settings.json")
        self.settings.update({"archive": {"directory": str(self.base / "knowledge")}})
        self.engine = SearchProviders(settings=self.settings)

    def test_description_never_contacts_services_or_echoes_credentials(self):
        with patch("web_search.McpHttpClient", side_effect=AssertionError("unexpected network")), \
                patch.dict("os.environ", {"EXA_API_KEY": "secret-value"}):
            result = self.engine.describe()
        self.assertFalse(result["probe_performed"])
        self.assertEqual(result["default_providers"], ["exa", "parallel"])
        self.assertNotIn("secret-value", json.dumps(result))

    def test_exa_text_and_parallel_structured_records_preserve_sources(self):
        exa = {"content": [{"type": "text", "text":
            "Title: Official A\nURL: https://a.example/page\nText: first\nMention https://not-a-result.example\n\n"
            "Title: Official B\nURL: https://b.example/\nText: second"}]}
        self.assertEqual([row["url"] for row in self.engine._normalize(exa)],
                         ["https://a.example/page", "https://b.example/"])
        parallel = {"structuredContent": {"results": [
            {"url": "https://a.example/page", "title": "Official A", "excerpts": ["one", "two"]}]}}
        rows = self.engine._normalize(parallel)
        self.assertEqual(rows[0]["snippet"], "one\ntwo")
        self.assertEqual(rows[0]["rank"], 1)
        wrapped = {"content": [{"type": "text", "text": json.dumps({"data": parallel["structuredContent"]})}]}
        self.assertEqual(self.engine._normalize(wrapped), rows)

    def test_empty_results_and_unrecognized_output_are_distinct(self):
        self.assertEqual(self.engine._normalize({"structuredContent": {"results": []}}), [])
        for result in ({"content": [{"type": "text", "text": "Go to https://example.com"}]},
                       {"content": [None, "invalid", {}]}, {"content": None},
                       {"structuredContent": {"results": [{"message": "no URL"}]}}):
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                self.engine._normalize(result)

    def test_schema_change_fails_instead_of_guessing_required_arguments(self):
        self.assertEqual(self.engine._arguments(PARALLEL_SEARCH, "search", query="a query", limit=3),
                         {"objective": "a query", "search_queries": ["a query"]})
        changed = {"inputSchema": {"properties": {"query": {}}, "required": ["query", "new_required"]}}
        with self.assertRaisesRegex(RuntimeError, "new_required"):
            self.engine._arguments(changed, "search", query="query")
        with self.assertRaises(RuntimeError):
            self.engine._arguments({"inputSchema": None}, "search", query="query")

    def test_malformed_required_schema_is_isolated_to_its_provider(self):
        for required in (None, 1, "query", [None], [{}]):
            with self.subTest(required=required):
                def client(provider):
                    value = Mock()
                    value.list_tools.return_value = [EXA_SEARCH] if provider == "exa" else [
                        {"name": "web_search", "inputSchema": {
                            "properties": {"query": {"type": "string"}}, "required": required}}]
                    value.call_tool.return_value = {"structuredContent": {"results": [
                        {"url": "https://valid.example/", "title": "Valid sibling"}]}}
                    return value
                with patch.object(self.engine, "_client", side_effect=client):
                    result = self.engine.search([{"target": "A", "query": "query"}])
                self.assertEqual(result["successful_provider_count"], 1)
                self.assertEqual(result["targets"][0]["status"], "partial")
                self.assertEqual(result["batches"][1]["status"], "error")
                self.assertIn("schema", result["batches"][1]["error"])

    def test_multi_target_search_retains_partial_failures_and_per_target_quota(self):
        def client(provider):
            if provider == "parallel":
                raise RuntimeError("MCP HTTP 429")
            value = Mock()
            value.list_tools.return_value = [EXA_SEARCH]
            value.call_tool.side_effect = lambda name, args: {"structuredContent": {"results": [
                {"url": "https://example.com/" + args["query"], "title": args["query"]},
                {"url": "https://example.com/shared", "title": "shared"}]}}
            return value
        with patch.object(self.engine, "_client", side_effect=client):
            result = self.engine.search([{"target": "A", "query": "alpha"},
                                         {"target": "B", "query": "beta"}], limit_per_target=1)
        self.assertEqual(result["provider_count"], 2)
        self.assertEqual(result["successful_provider_count"], 1)
        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual([row["status"] for row in result["targets"]], ["partial", "partial"])
        self.assertEqual([len(row["results"]) for row in result["targets"]], [1, 1])
        self.assertEqual({row["target"] for row in result["batches"]}, {"A", "B"})

    def test_duplicate_queries_do_not_create_duplicate_provider_calls(self):
        value = Mock()
        value.list_tools.return_value = [EXA_SEARCH]
        value.call_tool.return_value = {"structuredContent": {"results": []}}
        with patch.object(self.engine, "_client", return_value=value):
            result = self.engine.search([{"target": "A", "query": "first"},
                                         {"target": "A", "query": "first"},
                                         {"target": "A", "query": "second"}], providers=["exa", "exa"])
        self.assertEqual(value.call_tool.call_count, 2)
        self.assertEqual(result["target_count"], 1)
        self.assertEqual(result["mode"], "single_provider_multi_query")
        self.assertEqual(result["uncovered_targets"], ["A"])

    def test_invalid_input_is_rejected_before_contacting_services(self):
        with patch.object(self.engine, "_client", side_effect=AssertionError("unexpected network")):
            for targets in ([], ["text"], [{"target": "A", "query": ""}],
                            [{"target": "A", "query": "q", "other": True}],
                            [{"target": "A", "query": "q"}] * 13):
                with self.subTest(targets=targets), self.assertRaises(ValueError):
                    self.engine.search(targets)
            for url in ("file:///private/data", "https://user:secret@example.com", "https://:secret@example.com",
                        "https://example.com/\nother", "https://example.com/has space"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    self.engine.fetch([url])
            with self.assertRaises(ValueError):
                self.engine.search([{"target": "A", "query": "q"}], providers=["unknown"])
        for timeout in (True, "30", 0, 61):
            with self.assertRaises(ValueError):
                SearchProviders(timeout=timeout)

    def test_fetch_preserves_per_url_provider_errors_for_inspection(self):
        value = Mock()
        value.list_tools.return_value = [EXA_FETCH]
        raw = {"structuredContent": {"results": [{"url": "https://a.example", "text": "content"}],
                                     "errors": [{"url": "https://b.example", "error": "unavailable"}]}}
        value.call_tool.return_value = raw
        with patch.object(self.engine, "_client", return_value=value):
            result = self.engine.fetch(["https://a.example", "https://b.example"])
        self.assertEqual(result["result"], raw)
        self.assertIn("freshness", result)
        self.assertEqual(value.call_tool.call_args.args[1]["urls"], result["urls"])
        self.assertEqual(value.call_tool.call_args.args[1]["maxCharacters"], 12000)
        archive = result["archive"]
        self.assertEqual(archive["status"], "saved")
        self.assertEqual([row["page_body_archived"] for row in archive["pages"]], [True, False])
        self.assertEqual(json.loads(Path(archive["response_path"]).read_text()), raw)

    def test_persistent_defaults_reload_and_call_overrides_do_not_change_them(self):
        value = Mock()
        value.list_tools.return_value = [EXA_FETCH]
        value.call_tool.return_value = {"content": [{"type": "text", "text": "# Page\nURL: https://example.test/\n\nBody"}]}
        self.settings.update({"archive": {"enabled": False}, "fetch": {"max_characters": 3500},
                              "search": {"providers": ["exa"], "limit_per_target": 2}})
        with patch.object(self.engine, "_client", return_value=value):
            result = self.engine.fetch(["https://example.test/"])
            self.assertEqual(result["archive"]["status"], "disabled")
            self.assertEqual(value.call_tool.call_args.args[1]["maxCharacters"], 3500)
            self.assertFalse((self.base / "knowledge").exists())
            result = self.engine.fetch(["https://example.test/"], archive=True, max_characters=5000)
        self.assertEqual(result["archive"]["status"], "saved")
        self.assertEqual(value.call_tool.call_args.args[1]["maxCharacters"], 5000)
        self.assertFalse(self.settings.load()["archive"]["enabled"])
        self.assertEqual(self.engine.describe()["default_providers"], ["exa"])

    def test_archive_failure_does_not_hide_response_or_retry_fetch(self):
        value = Mock()
        value.list_tools.return_value = [EXA_FETCH]
        raw = {"structuredContent": {"results": [{"url": "https://example.test/", "text": "Actual text"}]}}
        value.call_tool.return_value = raw
        with patch.object(self.engine, "_client", return_value=value), \
                patch("archive.SourceArchive.save", side_effect=OSError("No space left")):
            result = self.engine.fetch(["https://example.test/"])
        self.assertEqual(value.call_tool.call_count, 1)
        self.assertEqual(result["result"], raw)
        self.assertEqual(result["archive"]["status"], "error")

    def test_search_does_not_create_archives_or_fetch_result_urls(self):
        value = Mock()
        value.list_tools.return_value = [EXA_SEARCH]
        value.call_tool.return_value = {"structuredContent": {"results": [{"url": "https://example.test/"}]}}
        with patch.object(self.engine, "_client", return_value=value):
            self.engine.search([{"target": "A", "query": "A"}], providers=["exa"])
        self.assertEqual(value.call_tool.call_count, 1)
        self.assertFalse((self.base / "knowledge").exists())


if __name__ == "__main__":
    unittest.main()
