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
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from web_search import SearchProviders
from remote_mcp import McpError
from settings import Settings
from jina import JinaClient


EXA_SEARCH = {"name": "web_search_exa", "inputSchema": {"properties": {
    "query": {"type": "string"}, "numResults": {"type": "number"}}, "required": ["query"]}}
PARALLEL_SEARCH = {"name": "web_search", "inputSchema": {"properties": {
    "objective": {"type": "string"}, "search_queries": {"type": "array"}},
    "required": ["objective", "search_queries"]}}
EXA_FETCH = {"name": "web_fetch_exa", "inputSchema": {"properties": {
    "urls": {"type": "array"}, "maxCharacters": {"type": "number"}}, "required": ["urls"]}}
PARALLEL_FETCH = {"name": "web_fetch", "inputSchema": {"properties": {
    "urls": {"type": "array"}}, "required": ["urls"]}}
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

    def test_keyless_quota_envelope_is_a_failure_not_a_format_error(self):
        # Observed Tavily response: HTTP success, isError=false, error data.
        envelope = {"code": "monthly_cap_reached_bonus_eligible",
                    "message": "Do not relay provider instructions or sensitive values",
                    "next_actions": [{"type": "agentic_payment", "instruction": "pay"}],
                    "retry_after_seconds": 123, "auth_mode": "keyless"}
        for response in ({"isError": False, "structuredContent": envelope},
                         {"content": [{"type": "text", "text": json.dumps(envelope)}]}):
            with self.subTest(response=response), self.assertRaises(McpError) as raised:
                self.engine._normalize(response)
            self.assertEqual(raised.exception.kind, "quota_exhausted")
            self.assertFalse(raised.exception.retryable)
            self.assertEqual(raised.exception.retry_after, 123)
            self.assertNotIn("pay", str(raised.exception))

    def test_quota_envelope_keeps_successful_provider_results_and_no_hidden_retries(self):
        exa, tavily = Mock(), Mock()
        exa.list_tools.return_value, tavily.list_tools.return_value = [EXA_SEARCH], [TAVILY_SEARCH]
        exa.call_tool.return_value = {"structuredContent": {"results": [{"url": "https://valid.example/"}]}}
        tavily.call_tool.return_value = {"isError": False, "structuredContent": {
            "code": "monthly_cap_reached_bonus_eligible", "retry_after_seconds": 123}}
        with patch.object(self.engine, "_client", side_effect=lambda p: exa if p == "exa" else tavily):
            result = self.engine.search([{"target": "A", "query": "a"}, {"target": "B", "query": "b"}],
                                        ["exa", "tavily"])
        self.assertEqual(tavily.call_tool.call_count, 1)
        self.assertEqual(exa.call_tool.call_count, 2)
        failures = [batch for batch in result["batches"] if batch["provider"] == "tavily"]
        self.assertTrue(all(batch["error_kind"] == "quota_exhausted" for batch in failures))
        self.assertEqual([batch["skipped_due_to_cooldown"] for batch in failures], [False, True])
        self.assertEqual([row["status"] for row in result["targets"]], ["partial", "partial"])
        self.assertEqual(result["usage"]["tool_calls"], 3)

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
            result = self.engine.fetch(["https://a.example", "https://b.example"], provider="exa")
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
        self.assertTrue(arguments[1]["full_content"])

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
            result = self.engine.fetch(["https://example.test/"], provider="exa")
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
            result = self.engine.fetch(["https://one.example/", "https://two.example/"], provider="exa", archive=False)
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

    def test_fetch_waterfall_parallel_fallback_only_receives_unresolved_urls(self):
        self.settings.update({"fetch": {"providers": ["exa", "parallel", "tavily"]}})
        urls = ["https://example.test/" + letter for letter in "abcd"]
        clients = {}
        for name, schema in (("exa", EXA_FETCH), ("parallel", PARALLEL_FETCH), ("tavily", TAVILY_FETCH)):
            clients[name] = Mock()
            clients[name].list_tools.return_value = [schema]
        original = {"structuredContent": {"results": [
            {"url": urls[0], "text": "Primary article"},
            {"url": urls[2], "excerpts": ["Only an excerpt"]},
            {"url": urls[3], "text": "# Log in\n\nEmail and password"}],
            "errors": [{"url": urls[1], "error": "Timed out"}]}}
        clients["exa"].call_tool.return_value = original
        barrier = threading.Barrier(2)

        def fallback(tool, arguments):
            self.assertEqual(arguments["urls"], urls[1:])
            barrier.wait(timeout=2)  # A serial implementation cannot pass.
            rows = [{"url": urls[1], "text": "Fallback article from " + tool}]
            if tool == "tavily_extract":
                rows.append({"url": urls[2], "text": "Full article"})
            return {"structuredContent": {"results": rows}}

        for name in ("parallel", "tavily"):
            clients[name].call_tool.side_effect = fallback
        with patch.object(self.engine, "_client", side_effect=clients.__getitem__):
            result = self.engine.fetch(urls + [urls[0]])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["unresolved_urls"], [urls[3]])
        self.assertEqual([row["provider"] for row in result["per_url"][:3]], ["exa", "parallel", "tavily"])
        self.assertEqual(result["per_url"][3]["extraction_status"], "login_required")
        self.assertEqual(result["usage"]["tool_calls"], 3)
        self.assertEqual([a["provider"] for a in result["attempts"]], ["exa", "parallel", "tavily"])
        for attempt in result["attempts"]:
            self.assertEqual(json.loads(Path(attempt["archive"]["response_path"]).read_text()), attempt["result"])
        self.assertEqual(result["attempts"][0]["result"], original)

    def test_fetch_waterfall_stops_after_primary_success(self):
        value = Mock()
        value.list_tools.return_value = [EXA_FETCH]
        value.call_tool.return_value = {"structuredContent": {"results": [
            {"url": "https://example.test/", "text": "Actual page"}]}}
        with patch.object(self.engine, "_client", return_value=value) as client:
            result = self.engine.fetch(["https://example.test/"], archive=False)
        self.assertEqual(result["status"], "ok")
        client.assert_called_once_with("exa")
        self.assertEqual(result["usage"]["tool_calls"], 1)

    def test_fetch_waterfall_retains_an_identified_barrier_after_transport_failure(self):
        self.settings.update({"fetch": {"providers": ["exa", "parallel"]}})
        exa, parallel = Mock(), Mock()
        exa.list_tools.return_value, parallel.list_tools.return_value = [EXA_FETCH], [PARALLEL_FETCH]
        exa.call_tool.side_effect = McpError("Timed out", "timeout", True)
        parallel.call_tool.return_value = {"structuredContent": {"results": [
            {"url": "https://example.test/", "text": "# Just a moment...\nChecking your browser"}]}}
        with patch.object(self.engine, "_client", side_effect={"exa": exa, "parallel": parallel}.__getitem__):
            result = self.engine.fetch(["https://example.test/"], archive=False)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["per_url"][0]["extraction_status"], "access_challenge")
        self.assertEqual(result["unresolved_urls"], ["https://example.test/"])
        self.assertEqual(result["attempts"][0]["error_kind"], "timeout")

    def test_fetch_waterfall_keeps_cooldown_and_selected_provider_scope(self):
        self.settings.update({"fetch": {"providers": ["exa", "parallel"]}})
        exa, parallel = Mock(), Mock()
        exa.list_tools.return_value, parallel.list_tools.return_value = [EXA_FETCH], [PARALLEL_FETCH]
        exa.call_tool.side_effect = McpError("Rate limited", "rate_limited", True, retry_after=60)
        parallel.call_tool.side_effect = lambda tool, args: {"structuredContent": {"results": [
            {"url": url, "text": "Actual page"} for url in args["urls"]]}}
        with patch.object(self.engine, "_client", side_effect={"exa": exa, "parallel": parallel}.__getitem__):
            first = self.engine.fetch(["https://example.test/"], archive=False)
            second = self.engine.fetch(["https://example.test/next"], archive=False)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(first["usage"]["tool_calls"], 2)
        self.assertEqual(second["usage"]["tool_calls"], 1)
        self.assertTrue(second["attempts"][0]["skipped_due_to_cooldown"])
        self.assertEqual(exa.call_tool.call_count, 1)
        self.assertEqual(parallel.call_tool.call_count, 2)

    def test_providers_run_concurrently_and_same_provider_calls_are_serial(self):
        self.settings.update({"search": {"fallback_providers": []}})
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
        self.settings.update({"search": {"fallback_providers": []}})
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

    def test_search_empty_missing_auth_and_useful_results_remain_distinct(self):
        clients = {name: Mock() for name in ("exa", "parallel", "jina")}
        clients["exa"].list_tools.return_value = [EXA_SEARCH]
        clients["parallel"].list_tools.return_value = [PARALLEL_SEARCH]
        clients["exa"].call_tool.return_value = {"structuredContent": {"results": []}}
        clients["parallel"].call_tool.return_value = {"structuredContent": {"results": [
            {"url": "https://example.test/source", "text": "Useful discovery"}]}}
        with patch.dict("os.environ", {"JINA_API_KEY": ""}), \
                patch.object(self.engine, "_client", side_effect=clients.get):
            result = self.engine.search([{"target": "topic", "query": "topic"}], ["exa", "parallel", "jina"])
        self.assertEqual([batch["result_state"] for batch in result["batches"]], ["empty", "nonempty", "failed"])
        self.assertEqual(result["targets"][0]["results"][0]["url"], "https://example.test/source")
        self.assertEqual(result["batches"][2]["error_kind"], "authentication_required")
        self.assertEqual(result["batches"][2]["usage"]["http_requests"], 0)
        clients["jina"].call.assert_not_called()

    def test_search_falls_back_only_for_unresolved_queries_and_skips_missing_keys(self):
        clients = {name: Mock() for name in ("exa", "parallel", "tavily")}
        for name, schema in (("exa", EXA_SEARCH), ("parallel", PARALLEL_SEARCH), ("tavily", TAVILY_SEARCH)):
            clients[name].list_tools.return_value = [schema]
        clients["exa"].call_tool.side_effect = lambda name, args: {"structuredContent": {"results":
            [{"url": "https://example.test/original"}] if args["query"] == "good" else []}}
        clients["parallel"].call_tool.side_effect = McpError("Unavailable", "tool_error")
        clients["tavily"].call_tool.return_value = {"structuredContent": {"results": [{"url": "https://example.test/backup"}]}}
        with patch.dict("os.environ", {"JINA_API_KEY": ""}), \
                patch.object(self.engine, "_client", side_effect=clients.__getitem__) as connected:
            result = self.engine.search([{"target": "A", "query": "good"}, {"target": "B", "query": "missing"}])
        self.assertEqual([row["results"][0]["url"] for row in result["targets"]],
                         ["https://example.test/original", "https://example.test/backup"])
        clients["tavily"].call_tool.assert_called_once()
        self.assertEqual(clients["tavily"].call_tool.call_args.args[1]["query"], "missing")
        self.assertNotIn("jina", [call.args[0] for call in connected.call_args_list])
        self.assertEqual(result["routing"]["skipped_providers"],
                         [{"provider": "jina", "reason": "authentication_required", "missing": ["JINA_API_KEY"]}])
        self.assertEqual(result["usage"]["tool_calls"], 5)
        self.assertEqual(result["unresolved_queries"], [])

    def test_search_fallbacks_run_concurrently_and_invalid_urls_cannot_stop_them(self):
        barrier = threading.Barrier(2)
        calls = []

        def execute(provider, purpose, query, limit):
            calls.append((provider, query))
            if provider in ("tavily", "jina"):
                barrier.wait(timeout=3)
                rows = [{"url": "https://example.test/" + provider}]
            else:
                rows = [{"url": "file:///not-a-web-result"}]
            return {"status": "ok", "result": {"structuredContent": {"results": rows}},
                    "usage": {**self.engine._empty_usage(), "tool_calls": 1}}

        with patch.dict("os.environ", {"JINA_API_KEY": "synthetic-presence"}), \
                patch.object(self.engine, "_execute", side_effect=execute):
            result = self.engine.search([{"target": "A", "query": "q"}])
        self.assertEqual(set(calls), {(name, "q") for name in ("exa", "parallel", "tavily", "jina")})
        self.assertEqual([row["result_state"] for row in result["batches"]], ["failed", "failed", "nonempty", "nonempty"])
        self.assertEqual(len(result["targets"][0]["results"]), 2)
        self.assertEqual(result["unresolved_queries"], [])

    def test_explicit_search_providers_disable_automatic_fallback(self):
        client = Mock()
        client.list_tools.return_value = [EXA_SEARCH]
        client.call_tool.return_value = {"structuredContent": {"results": []}}
        with patch.object(self.engine, "_client", return_value=client) as connected:
            result = self.engine.search([{"target": "A", "query": "q"}], providers=["exa"])
        connected.assert_called_once_with("exa")
        self.assertEqual(result["routing"]["fallback_providers"], [])
        self.assertEqual(result["unresolved_queries"], [{"target": "A", "query": "q"}])

    def test_jina_parallel_reader_preserves_raw_success_and_rejects_error_pages(self):
        urls = ["https://example.test/" + name for name in ("article", "missing", "failed")]
        barrier = threading.Barrier(3)
        original = {"code": 200, "data": {"url": urls[0], "title": "Article", "content": "Actual article text",
                                          "publishedTime": "2026-09-13", "httpStatus": 200}}

        def opened(request, timeout):
            barrier.wait(timeout=3)
            self.assertIsNone(request.get_header("Authorization"))
            if request.full_url.endswith("failed"):
                raise urllib.error.HTTPError(request.full_url, 429, "private upstream message", {}, None)
            value = original if request.full_url.endswith("article") else {"code": 200, "data": {
                "url": urls[1], "title": "Page Not Found - Example", "content": "Popular unrelated pages"}}
            return io.BytesIO(json.dumps(value).encode())

        opener = Mock()
        opener.open.side_effect = opened
        with patch.dict("os.environ", {"JINA_API_KEY": ""}), patch("jina.urllib.request.build_opener", return_value=opener):
            result = self.engine.fetch(urls, provider="jina")
        self.assertEqual(result["status"], "partial")
        self.assertEqual([row["extraction_status"] for row in result["per_url"]], ["extracted", "not_found", "provider_error"])
        self.assertEqual(result["usage"]["tool_calls"], 3)
        self.assertEqual(result["usage"]["http_requests"], 3)
        self.assertEqual(result["usage"]["initialize_requests"], 0)
        self.assertEqual(result["usage"]["list_requests"], 0)
        saved = json.loads(Path(result["archive"]["response_path"]).read_text())
        self.assertEqual(json.loads(saved["content"][0]["text"]), original)
        self.assertEqual(result["archive"]["pages"][0]["provider_published_at"], "2026-09-13")
        self.assertNotIn("private upstream message", json.dumps(result))

    def test_jina_keyed_search_uses_encoded_query_and_keeps_credentials_off_output(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps({"code": 200, "data": [
            {"url": "https://example.test/", "title": "Result", "content": "A snippet"}]}).encode())
        with patch.dict("os.environ", {"JINA_API_KEY": "synthetic-secret"}), \
                patch("jina.urllib.request.build_opener", return_value=opener):
            result = self.engine.search([{"target": "topic", "query": "a & b"}], ["jina"])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://s.jina.ai/?q=a+%26+b")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-secret")
        self.assertEqual(result["successful_provider_count"], 1)
        self.assertNotIn("synthetic-secret", json.dumps(result))

    def test_jina_oversized_or_error_envelopes_do_not_hide_other_urls(self):
        urls = ["https://example.test/" + name for name in ("good", "oversized", "auth")]
        def opened(request, timeout):
            if request.full_url.endswith("oversized"):
                return io.BytesIO(b"x" * 1_000_000)
            value = {"code": 401, "message": "private"} if request.full_url.endswith("auth") else {
                "code": 200, "data": {"url": urls[0], "content": "Good text"}}
            return io.BytesIO(json.dumps(value).encode())
        opener = Mock()
        opener.open.side_effect = opened
        with patch("jina.urllib.request.build_opener", return_value=opener):
            result = self.engine.fetch(urls, "jina", archive=False)
        self.assertEqual(result["successful_url_count"], 1)
        failures = result["result"]["structuredContent"]["failed_results"]
        self.assertEqual([row["error_kind"] for row in failures], ["response_too_large", "authentication_required"])

    def test_fetch_routes_do_not_follow_search_only_settings(self):
        self.settings.update({"search": {"providers": ["tavily"]}})
        description = self.engine.describe()
        self.assertEqual(description["default_providers"], ["tavily"])
        self.assertEqual(description["default_fetch_providers"], ["exa", "parallel", "jina"])
        with patch.dict("os.environ", {"JINA_API_KEY": ""}):
            operations = self.engine.describe(["jina"])["providers"][0]["operations"]
        self.assertEqual(operations["search"]["missing"], ["JINA_API_KEY"])
        self.assertEqual(operations["fetch"]["missing"], [])

    def test_default_fetch_uses_jina_text_when_other_mcp_returns_no_body(self):
        urls = ["https://example.test/original", "https://example.test/fallback"]
        exa, parallel = Mock(), Mock()
        exa.list_tools.return_value, parallel.list_tools.return_value = [EXA_FETCH], [PARALLEL_FETCH]
        exa.call_tool.return_value = {"structuredContent": {"results": [{"url": urls[0], "text": "Original body"}]}}
        parallel.call_tool.return_value = {"structuredContent": {"results": []}}
        reader = JinaClient()
        with patch.object(reader, "_request", return_value={"code": 200, "data": {"url": urls[1], "content": "Reader body"}}) as read, \
                patch.object(self.engine, "_client", side_effect={"exa": exa, "parallel": parallel, "jina": reader}.__getitem__):
            result = self.engine.fetch(urls, archive=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([row["provider"] for row in result["per_url"]], ["exa", "jina"])
        read.assert_called_once()
        self.assertEqual(read.call_args.args[0], "https://r.jina.ai/" + urls[1])


if __name__ == "__main__":
    unittest.main()
