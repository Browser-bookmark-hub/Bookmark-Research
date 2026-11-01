import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from credentials import Credentials
from grok_search import GrokSearch, OpenAICompatibleAgenticSearch, normalize_compatible_base_url
from perplexity import PerplexityClient
from remote_mcp import McpError
from settings import Settings
from web_search import SearchProviders


class Response:
    def __init__(self, value):
        self.data = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.data[:size]


class ThirdPartySearchTests(unittest.TestCase):
    def _custom_search(self, config):
        temporary = tempfile.TemporaryDirectory(prefix="custom-agentic-test-")
        self.addCleanup(temporary.cleanup)
        settings = Settings(path=Path(temporary.name) / "settings.json")
        settings.update({"custom_agentic": {"enabled": True, **config}})
        return OpenAICompatibleAgenticSearch(settings, Credentials(settings))

    def test_perplexity_search_is_normalized_by_existing_fusion(self):
        client = PerplexityClient(headers={"Authorization": "Bearer test"})
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = Response({"results": [
                {"title": "Example", "url": "https://example.com/page", "snippet": "Useful text", "date": "2026-01-01"},
                {"url": "javascript:alert(1)", "title": "unsafe"},
            ]})
            result = client.call("search", query="example", limit=5)
        engine = SearchProviders(settings=Settings(path="/tmp/bookmark-research-test-settings.json"))
        rows = engine._normalize(result)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://example.com/page")
        self.assertEqual(rows[0]["snippet"], "Useful text")

    def test_perplexity_rejects_fetch_and_missing_key(self):
        with self.assertRaises(McpError) as missing:
            PerplexityClient().call("search", query="example")
        self.assertEqual(missing.exception.kind, "authentication_required")
        with self.assertRaises(McpError) as fetch:
            PerplexityClient(headers={"Authorization": "Bearer test"}).call("fetch", urls=["https://example.com"])
        self.assertEqual(fetch.exception.kind, "capability_unavailable")

    def test_grok_response_keeps_answer_and_citations_separate(self):
        value = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Answer [1](https://example.com).",
                    "annotations": [{"type": "url_citation", "url_citation": {"url": "https://example.com", "title": "Example"}}]}]}],
                 "citations": ["https://example.com", "https://example.org"]}
        with patch.object(Credentials, "get", return_value="secret"), \
             patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = Response(value)
            result = GrokSearch(Credentials(Settings(path="/tmp/bookmark-research-test-settings.json"))).search("question")
        self.assertEqual(result["answer"], "Answer [1](https://example.com).")
        self.assertEqual([row["url"] for row in result["citations"]], ["https://example.com", "https://example.org"])

    def test_grok_does_not_echo_upstream_error_body(self):
        import urllib.error
        error = urllib.error.HTTPError("https://api.x.ai/v1/responses", 401, "failed", {}, io.BytesIO(b"secret leak"))
        with patch.object(Credentials, "get", return_value="secret"), \
             patch("urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(McpError) as raised:
                GrokSearch(Credentials(Settings(path="/tmp/bookmark-research-test-settings.json"))).search("question")
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("secret leak", str(raised.exception))

    def test_custom_chat_completion_returns_answer_and_unverified_citations(self):
        client = self._custom_search({"base_url": "https://gateway.example/v1/chat/completions",
            "model": "provider/model:online", "api_mode": "chat_completions", "search_mode": "prompt"})
        value = {"choices": [{"message": {"content": "Found this: https://example.com/page.",
                  "citations": [{"url": "https://example.org", "title": "Source"}]}}]}
        with patch.object(Credentials, "get", return_value="custom-secret"), \
             patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = Response(value)
            result = client.search("question")
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://gateway.example/v1/chat/completions")
        self.assertEqual(json.loads(request.data)["model"], "provider/model:online")
        self.assertEqual(result["provider"], "custom")
        self.assertEqual([row["url"] for row in result["citations"]],
                         ["https://example.org", "https://example.com/page"])
        self.assertIn("not independently verified", result["note"])

    def test_custom_responses_requests_native_search_only_when_configured(self):
        client = self._custom_search({"base_url": "https://gateway.example/v1", "model": "search-model",
            "api_mode": "responses", "search_mode": "native"})
        value = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Answer",
            "annotations": [{"type": "url_citation", "url_citation": {"url": "https://example.com"}}]}]}]}
        with patch.object(Credentials, "get", return_value="custom-secret"), \
             patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value = Response(value)
            result = client.search("question")
        request = opener.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://gateway.example/v1/responses")
        self.assertEqual(payload["tools"], [{"type": "web_search"}])
        self.assertEqual(result["citations"], [{"url": "https://example.com", "title": ""}])

    def test_custom_endpoint_requires_key_and_valid_base_url(self):
        client = self._custom_search({"base_url": "http://localhost:8317/v1", "model": "alias",
            "api_mode": "chat_completions", "search_mode": "prompt"})
        with patch.object(Credentials, "get", return_value=""):
            with self.assertRaises(McpError) as raised:
                client.search("question")
        self.assertEqual(raised.exception.kind, "authentication_required")
        self.assertEqual(normalize_compatible_base_url("http://localhost:8317/v1/responses"),
                         "http://localhost:8317/v1")
        for invalid in ("ftp://example.com/v1", "https://user:pass@example.com/v1",
                        "https://example.com/v1?key=x", "https://example.com/#fragment"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_compatible_base_url(invalid)


if __name__ == "__main__":
    unittest.main()
