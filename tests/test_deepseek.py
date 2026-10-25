"""DeepSeek Search/Fetch client: request shape, normalization and failures."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from deepseek import DeepSeekClient
from remote_mcp import McpError
from settings import Settings
from web_search import SearchProviders


class DeepSeekTests(unittest.TestCase):
    def test_search_uses_count_and_summary(self):
        client = DeepSeekClient(headers={"Authorization": "Bearer test"})
        with patch.object(client, "_request", return_value={"results": [{
                "url": "https://example.test/a", "title": "A", "summary": "A summary",
                "date": "2026-10-01", "authority": "high"}]}) as request:
            result = client.call("search", query="question", limit=5)
        self.assertEqual({"query": "question", "count": 5, "need_content": False},
                         request.call_args[0][1])
        row = result["structuredContent"]["results"][0]
        self.assertEqual("A summary", row["snippet"])
        self.assertEqual("https://example.test/a", row["url"])

    def test_fetch_normalizes_content_and_keeps_sibling_failures(self):
        client = DeepSeekClient(headers={"Authorization": "Bearer test"})

        def fake(url, payload):
            if payload["url"].endswith("bad"):
                raise McpError("missing", "not_found")
            return {"title": "Page", "content": "# Page\nBody"}

        with patch.object(client, "_request", side_effect=fake):
            result = client.call("fetch", urls=["https://example.test/good", "https://example.test/bad"])
        rows = {row["url"]: row for row in result["structuredContent"]["results"]}
        self.assertEqual("# Page\nBody", rows["https://example.test/good"]["content"])
        self.assertEqual("not_found", rows["https://example.test/bad"]["error_kind"])

    def test_missing_key_and_http_errors_are_classified(self):
        with self.assertRaisesRegex(McpError, "DEEPSEEK_API_KEY"):
            DeepSeekClient().call("search", query="q")
        self.assertEqual("authentication_required", DeepSeekClient._error(401).kind)
        self.assertEqual("quota_exhausted", DeepSeekClient._error(402).kind)
        self.assertEqual("rate_limited", DeepSeekClient._error(429).kind)
        self.assertTrue(DeepSeekClient._error(503).retryable)


    def test_search_provider_passes_limit_and_normalizes_results(self):
        temporary = tempfile.TemporaryDirectory(prefix="deepseek-search-")
        self.addCleanup(temporary.cleanup)
        settings = Settings(Path(temporary.name) / "settings.json")
        engine = SearchProviders(settings=settings)
        fake = Mock()
        fake.snapshot_usage.return_value = {"http_requests": 1, "tool_calls": 1}
        fake.call.return_value = {"structuredContent": {"results": [
            {"url": "https://example.test/a", "title": "A", "snippet": "Summary"}]}}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), \
                patch.object(engine, "_client", return_value=fake):
            result = engine.search([{"target": "q", "query": "q"}],
                                   providers=["deepseek"], limit_per_target=3)
        fake.call.assert_called_once_with("search", query="q", limit=3)
        self.assertEqual("ok", result["targets"][0]["status"])
        self.assertEqual("https://example.test/a", result["targets"][0]["results"][0]["url"])

    def test_registry_exposes_deepseek_as_an_optional_provider(self):
        temporary = tempfile.TemporaryDirectory(prefix="deepseek-provider-")
        self.addCleanup(temporary.cleanup)
        settings = Settings(Path(temporary.name) / "settings.json")
        described = SearchProviders(settings=settings).describe(["deepseek"])["providers"][0]
        self.assertEqual("deepseek", described["provider"])
        self.assertEqual("http", described["transport"])
        self.assertEqual("DEEPSEEK_API_KEY", described["operations"]["search"]["missing"][0])
        self.assertNotIn("deepseek", settings.load()["search"]["providers"])


if __name__ == "__main__":
    unittest.main()
