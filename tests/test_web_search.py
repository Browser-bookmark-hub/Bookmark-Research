"""Provider schemas, source parsing and failure isolation without live requests."""

import concurrent.futures
import copy
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from web_search import SearchProviders
from remote_mcp import McpError
from settings import Settings


EXA_SEARCH = {"name": "web_search_exa", "inputSchema": {"properties": {
    "query": {"type": "string"}, "numResults": {"type": "number"}}, "required": ["query"]}}
PARALLEL_SEARCH = {"name": "web_search", "inputSchema": {"properties": {
    "objective": {"type": "string"}, "search_queries": {"type": "array"}},
    "required": ["objective", "search_queries"]}}
EXA_FETCH = {"name": "web_fetch_exa", "inputSchema": {"properties": {
    "urls": {"type": "array"}, "maxCharacters": {"type": "number"}}, "required": ["urls"]}}
TAVILY_SEARCH = {"name": "tavily_search", "inputSchema": {"type": "object", "properties": {
    "query": {"type": "string"}, "max_results": {"type": "integer"},
    "search_depth": {"type": "string", "enum": ["basic", "advanced"]},
    "include_raw_content": {"type": "boolean"}}, "required": ["query"]}}
TAVILY_FETCH = {"name": "tavily_extract", "inputSchema": {"type": "object", "properties": {
    "urls": {"type": "array", "items": {"type": "string"}}, "format": {"enum": ["markdown", "text"]}},
    "required": ["urls"]}}


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

    def test_tavily_uses_keyless_header_or_optional_bearer_without_url_credentials(self):
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}), patch("web_search.McpHttpClient") as constructor:
            first = self.engine._client("tavily")
            self.assertIs(first, self.engine._client("tavily"))
            self.assertEqual(constructor.call_count, 1)
            self.assertEqual(constructor.call_args.kwargs["headers"], {"X-Tavily-Access-Mode": "keyless"})
            with patch.dict("os.environ", {"TAVILY_API_KEY": "private-placeholder"}):
                self.engine._client("tavily")
                self.assertEqual(constructor.call_count, 2)
                self.assertEqual(constructor.call_args.kwargs["headers"], {"Authorization": "Bearer private-placeholder"})
                self.assertNotIn("private-placeholder", constructor.call_args.args[0])
                description = self.engine.describe(["tavily"])
                self.assertNotIn("private-placeholder", json.dumps(description))
                self.assertEqual(description["providers"][0]["authentication_state"]["mode"], "api_key")
                self.assertFalse(description["providers"][0]["authentication_state"]["credential_validity_verified"])

    def test_catalog_reused_across_targets_and_fetch_until_expiry_or_change(self):
        value = Mock()
        value.catalog_version = 1
        value.list_tools.return_value = [EXA_SEARCH, EXA_FETCH]
        value.call_tool.return_value = {"structuredContent": {"results": []}}
        with patch.object(self.engine, "_client", return_value=value):
            searched = self.engine.search([{"target": "A", "query": "a"}, {"target": "B", "query": "b"}], ["exa"])
            self.engine.fetch(["https://example.test/"], "exa", archive=False)
            self.assertEqual(value.list_tools.call_count, 1)
            self.assertEqual(searched["usage"]["tool_calls"], 2)
            self.assertEqual(searched["usage"]["cache_hits"], 1)
            self.engine._states["exa"].catalog_expires = 0
            self.engine.search([{"target": "A", "query": "a"}], ["exa"])
            self.assertEqual(value.list_tools.call_count, 2)
            value.catalog_version = 2
            self.engine.search([{"target": "A", "query": "a"}], ["exa"])
            self.assertEqual(value.list_tools.call_count, 3)

    def test_probe_refreshes_catalog_and_distinguishes_search_fetch_and_research(self):
        value = Mock()
        value.list_tools.return_value = [TAVILY_SEARCH, {"name": "tavily_research"}]
        value.call_tool.return_value = {"structuredContent": {"results": []}}
        with patch.object(self.engine, "_client", return_value=value):
            self.engine.search([{"target": "A", "query": "a"}], ["tavily"])
            first = self.engine.probe(["tavily"])
            self.engine.probe(["tavily"])
        self.assertEqual(value.list_tools.call_count, 3)
        self.assertEqual(value.call_tool.call_count, 1)
        provider = first["providers"][0]
        self.assertEqual(provider["capabilities"]["search"]["status"], "supported")
        self.assertEqual(provider["capabilities"]["fetch"]["error_kind"], "capability_unavailable")
        self.assertFalse(provider["capabilities"]["search"]["execution_verified"])
        self.assertEqual(provider["native_research"]["advertised_tools"], ["tavily_research"])
        self.assertFalse(provider["native_research"]["execution_verified"])
        self.assertTrue(provider["native_research"]["authentication_required"])
        self.assertEqual(provider["usage"]["tool_calls"], 0)

    def test_schema_drift_stops_before_tool_call_and_does_not_guess_parallel_fields(self):
        variants = []
        changed = copy.deepcopy(EXA_SEARCH)
        changed["inputSchema"]["properties"]["query"] = {"type": "array"}
        variants.append(changed)
        changed = copy.deepcopy(EXA_SEARCH)
        changed["inputSchema"]["properties"]["numResults"]["maximum"] = 1
        variants.append(changed)
        changed = copy.deepcopy(EXA_SEARCH)
        changed["inputSchema"]["required"].append("new_required")
        variants.append(changed)
        for tool in variants:
            with self.subTest(tool=tool):
                value = Mock()
                value.list_tools.return_value = [tool]
                with patch.object(self.engine, "_client", return_value=value):
                    result = self.engine.search([{"target": "A", "query": "a"}], ["exa"])
                self.assertEqual(result["batches"][0]["error_kind"], "schema_mismatch")
                self.assertEqual(result["usage"]["tool_calls"], 0)
                value.call_tool.assert_not_called()
        incompatible = {"name": "web_search", "inputSchema": {"properties": {"query": {"type": "string"}}, "required": ["query"]}}
        with self.assertRaises(McpError):
            self.engine._arguments(incompatible, "search", query="a")

    def test_catalog_cache_rejects_oversized_schema_before_execution(self):
        value = Mock()
        value.list_tools.return_value = [EXA_SEARCH]
        with patch.object(self.engine, "MAX_CATALOG_BYTES", 10), patch.object(self.engine, "_client", return_value=value):
            result = self.engine.search([{"target": "A", "query": "a"}], ["exa"])
        self.assertEqual(result["batches"][0]["error_kind"], "response_too_large")
        value.call_tool.assert_not_called()

    def test_rate_limit_keeps_siblings_and_skips_provider_during_cooldown(self):
        exa, parallel = Mock(), Mock()
        exa.list_tools.return_value, parallel.list_tools.return_value = [EXA_SEARCH], [PARALLEL_SEARCH]
        exa.call_tool.side_effect = McpError("MCP HTTP 429", "rate_limited", True, http_status=429, retry_after=60)
        parallel.call_tool.return_value = {"structuredContent": {"results": [{"url": "https://valid.example/"}]}}
        with patch.object(self.engine, "_client", side_effect=lambda provider: exa if provider == "exa" else parallel):
            result = self.engine.search([{"target": letter, "query": letter} for letter in "ABC"])
        self.assertEqual(exa.call_tool.call_count, 1)
        self.assertEqual(parallel.call_tool.call_count, 3)
        self.assertEqual(result["usage"]["tool_calls"], 4)
        self.assertEqual([batch["skipped_due_to_cooldown"] for batch in result["batches"][:3]], [False, True, True])
        self.assertTrue(all(batch["retryable"] for batch in result["batches"][:3]))
        self.assertEqual([row["status"] for row in result["targets"]], ["partial"] * 3)

    def test_parallel_reuses_session_id_without_inventing_model_identity(self):
        value = Mock()
        search = copy.deepcopy(PARALLEL_SEARCH)
        search["inputSchema"]["properties"]["session_id"] = {"type": "string"}
        search["inputSchema"]["properties"]["model_name"] = {"type": "string"}
        fetch = {"name": "web_fetch", "inputSchema": {"properties": {"urls": {"type": "array"},
                 "session_id": {"type": "string"}, "full_content": {"type": "boolean"}}, "required": ["urls"]}}
        value.list_tools.return_value = [search, fetch]
        value.call_tool.return_value = {"structuredContent": {"results": []}}
        with patch.object(self.engine, "_client", return_value=value):
            self.engine.search([{"target": "A", "query": "a"}], ["parallel"])
            self.engine.fetch(["https://example.test/"], "parallel", archive=False)
        arguments = [call.args[1] for call in value.call_tool.call_args_list]
        self.assertEqual(arguments[0]["session_id"], arguments[1]["session_id"])
        self.assertEqual(len(arguments[0]["session_id"]), 32)
        self.assertNotIn("model_name", arguments[0])
        self.assertFalse(arguments[1]["full_content"])

    def test_catalog_probe_does_not_reset_a_tool_rate_limit(self):
        value = Mock()
        value.list_tools.return_value = [EXA_SEARCH]
        value.call_tool.side_effect = McpError("MCP HTTP 429", "rate_limited", True, retry_after=3600)
        with patch.object(self.engine, "_client", return_value=value):
            self.engine.search([{"target": "A", "query": "a"}], ["exa"])
            self.assertGreater(self.engine._states["exa"].cooldown_until - time.monotonic(), 3500)
            probe = self.engine.probe(["exa"])
            result = self.engine.search([{"target": "B", "query": "b"}], ["exa"])
        self.assertEqual(probe["providers"][0]["status"], "ok")
        self.assertTrue(result["batches"][0]["skipped_due_to_cooldown"])
        self.assertEqual(result["usage"]["tool_calls"], 0)
        self.assertEqual(value.call_tool.call_count, 1)

    def test_fetch_returns_classified_failure_without_retry_or_archive(self):
        value = Mock()
        value.list_tools.return_value = [EXA_FETCH]
        value.call_tool.side_effect = McpError("MCP HTTP 404", "session_expired", True, http_status=404)
        with patch.object(self.engine, "_client", return_value=value):
            result = self.engine.fetch(["https://example.test/"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_kind"], "session_expired")
        self.assertEqual(result["usage"]["tool_calls"], 1)
        self.assertEqual(value.call_tool.call_count, 1)
        self.assertEqual(result["archive"]["status"], "not_saved")
        self.assertFalse((self.base / "knowledge").exists())

    def test_single_url_schema_never_silently_drops_extra_fetch_urls(self):
        value = Mock()
        value.list_tools.return_value = [{"name": "web_fetch_exa", "inputSchema": {
            "properties": {"url": {"type": "string"}}, "required": ["url"]}}]
        with patch.object(self.engine, "_client", return_value=value):
            result = self.engine.fetch(["https://one.example/", "https://two.example/"], archive=False)
        self.assertEqual(result["error_kind"], "schema_mismatch")
        self.assertEqual(result["usage"]["tool_calls"], 0)
        value.call_tool.assert_not_called()

    def test_tavily_normalizes_results_and_preserves_partial_extraction(self):
        value = Mock()
        value.list_tools.return_value = [TAVILY_SEARCH, TAVILY_FETCH]
        value.call_tool.side_effect = [
            {"structuredContent": {"results": [{"url": "https://one.example/", "title": "One", "content": "Search excerpt"}]}},
            {"structuredContent": {"results": [{"url": "https://one.example/", "raw_content": "# Actual page"}],
                                   "failed_results": [{"url": "https://two.example/", "error": "unavailable"}]}}]
        with patch.object(self.engine, "_client", return_value=value):
            search = self.engine.search([{"target": "A", "query": "a"}], ["tavily"], 2)
            fetched = self.engine.fetch(["https://one.example/", "https://two.example/"], "tavily", archive=False)
        self.assertEqual(search["batches"][0]["results"][0]["snippet"], "Search excerpt")
        self.assertEqual(value.call_tool.call_args_list[0].args[1]["search_depth"], "basic")
        self.assertEqual(value.call_tool.call_args_list[0].args[1]["max_results"], 2)
        self.assertEqual(fetched["status"], "partial")
        self.assertEqual([row["status"] for row in fetched["per_url"]], ["ok", "error"])
        self.assertFalse(fetched["character_limit_applied"])
        self.assertEqual(fetched["usage"]["tool_calls"], 1)

    def test_providers_run_concurrently_and_same_provider_calls_are_serial(self):
        barrier = threading.Barrier(2)
        guard = threading.Lock()
        active, maximum, calls = {}, {}, {}
        clients = {}
        for name, schema in (("exa", EXA_SEARCH), ("parallel", PARALLEL_SEARCH)):
            value = Mock()
            value.list_tools.return_value = [schema]
            def execute(tool, arguments, provider=name):
                with guard:
                    active[provider] = active.get(provider, 0) + 1
                    maximum[provider] = max(maximum.get(provider, 0), active[provider])
                    calls[provider] = calls.get(provider, 0) + 1
                    first = calls[provider] == 1
                if first:
                    barrier.wait(timeout=3)
                time.sleep(0.005)
                with guard:
                    active[provider] -= 1
                return {"structuredContent": {"results": []}}
            value.call_tool.side_effect = execute
            clients[name] = value
        with patch.object(self.engine, "_client", side_effect=clients.get):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.engine.search, [{"target": "A", "query": "a"}, {"target": "B", "query": "b"}]) for _ in range(2)]
                results = [future.result(timeout=5) for future in futures]
        self.assertEqual(maximum, {"exa": 1, "parallel": 1})
        self.assertEqual(calls, {"exa": 4, "parallel": 4})
        self.assertTrue(all(result["usage"]["tool_calls"] == 4 for result in results))
        self.assertTrue(all(client.list_tools.call_count == 1 for client in clients.values()))

    def test_real_transport_usage_is_per_operation_and_not_mixed_between_providers(self):
        requests = []
        def opened(request, timeout):
            body = json.loads(request.data)
            requests.append((request.full_url, body["method"]))
            if body["method"] == "initialize":
                result = {"protocolVersion": "2025-03-26"}
            elif body["method"] == "tools/list":
                result = {"tools": [EXA_SEARCH] if "exa.ai" in request.full_url else [PARALLEL_SEARCH]}
            else:
                result = {"structuredContent": {"results": []}}
            response = io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode())
            response.headers, response.status = {"Content-Type": "application/json"}, 200
            return response
        with patch("remote_mcp.urllib.request.urlopen", side_effect=opened):
            result = self.engine.search([{"target": "A", "query": "a"}, {"target": "B", "query": "b"}])
        self.assertEqual(result["usage"], {"tool_calls": 4, "http_requests": 10, "initialize_requests": 2,
                         "list_requests": 2, "session_recoveries": 0, "cache_hits": 2})
        self.assertEqual([batch["usage"]["http_requests"] for batch in result["batches"]], [4, 1, 4, 1])
        self.assertEqual(len(requests), 10)

    def test_arbitrary_exception_text_cannot_leak_credentials(self):
        with patch.object(self.engine, "_client", side_effect=RuntimeError("URL contains private-key-placeholder")):
            result = self.engine.search([{"target": "A", "query": "a"}], ["exa"])
        self.assertNotIn("private-key-placeholder", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
