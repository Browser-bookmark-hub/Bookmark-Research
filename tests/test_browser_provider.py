"""Tests for the browser rendering fetch provider (P2-1)."""

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from browser_client import BrowserClient
from settings import Settings
from web_search import SearchProviders


SAMPLE_PROSE = (
    "This is rendered article content from the web page. It contains multiple full sentences with punctuation. "
    "Sentence two explains the core architecture in rich detail. Sentence three outlines performance tradeoffs. "
    "Sentence four highlights future development goals and next steps. "
    "Sentence five provides deep context on browser automation and headless rendering pipelines. "
) * 3


class TestBrowserProvider(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = Settings(Path(self.temp_dir.name) / "settings.json")
        self.engine = SearchProviders(settings=self.settings)

    def tearDown(self):
        BrowserClient.clear_mock()
        self.temp_dir.cleanup()

    def test_browser_disabled_by_default_reports_capability_unavailable(self):
        # Default settings have browser.enabled = False
        result = self.engine.fetch(["https://example.test/spa"], provider="browser", archive=False)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_kind"], "capability_unavailable")
        self.assertIn("disabled in settings", result["error"])

    def test_browser_mock_fetch_and_snapshot_usage(self):
        self.settings.update({"browser": {"enabled": True}})

        def mock_render(url):
            return {
                "url": url,
                "title": "Hydrated SPA",
                "markdown": "# Hydrated SPA\n\n" + SAMPLE_PROSE,
                "text": SAMPLE_PROSE,
                "status_code": 200,
            }

        BrowserClient.set_mock(mock_render)
        result = self.engine.fetch(["https://example.test/spa"], provider="browser", archive=False)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["provider"], "browser")
        self.assertEqual(len(result["per_url"]), 1)
        row = result["per_url"][0]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["content_state"], "usable")
        self.assertGreaterEqual(row["characters"], 400)

    def test_browser_waterfall_fallback_from_js_shell_suspected(self):
        # Configure waterfall: primary is exa (returns JS shell), fallback is browser
        self.settings.update({
            "browser": {"enabled": True},
            "fetch": {"providers": ["exa", "browser"]},
        })

        exa_client = Mock()
        exa_client.list_tools.return_value = [{"name": "exa_fetch", "description": "Exa fetch"}]
        # Exa returns an empty shell
        exa_client.call_tool.return_value = {
            "structuredContent": {
                "results": [
                    {
                        "url": "https://example.test/spa",
                        "title": "React App",
                        "text": "<div id=\"root\"></div> Please enable JavaScript to view this application.",
                    }
                ]
            }
        }

        def mock_browser(url):
            return {
                "url": url,
                "title": "Interactive Web App",
                "markdown": "# Welcome to the App\n\n" + SAMPLE_PROSE,
                "text": SAMPLE_PROSE,
            }

        BrowserClient.set_mock(mock_browser)

        orig_client = self.engine._client
        with patch.object(self.engine, "_client") as mock_get_client:
            def client_factory(name, **kwargs):
                if name == "exa":
                    return exa_client
                return orig_client(name, **kwargs)

            mock_get_client.side_effect = client_factory
            result = self.engine.fetch(["https://example.test/spa"], archive=False)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["per_url"]), 1)
        row = result["per_url"][0]
        self.assertEqual(row["provider"], "browser")
        self.assertEqual(row["content_state"], "usable")
        self.assertGreaterEqual(row["characters"], 400)
        self.assertIn("Sentence two explains", result["attempts"][1]["result"]["structuredContent"]["results"][0]["text"])

    def test_browser_error_and_timeout_handling(self):
        self.settings.update({"browser": {"enabled": True}})

        def mock_render(url):
            if "timeout" in url:
                raise TimeoutError("Render timed out after 20s")
            raise RuntimeError("Browser crash")

        BrowserClient.set_mock(mock_render)
        result = self.engine.fetch(
            ["https://example.test/timeout", "https://example.test/crash"],
            provider="browser",
            archive=False,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(result["per_url"]), 2)
        r1, r2 = result["per_url"][0], result["per_url"][1]
        self.assertEqual(r1["status"], "error")
        self.assertEqual(r1["extraction_status"], "provider_error")
        self.assertEqual(r2["status"], "error")
        self.assertEqual(r2["extraction_status"], "provider_error")

        failed_results = result["result"]["structuredContent"]["failed_results"]
        self.assertEqual(len(failed_results), 2)
        failed_by_url = {item["url"]: item for item in failed_results}
        self.assertEqual(failed_by_url["https://example.test/timeout"]["error_kind"], "timeout")
        self.assertEqual(failed_by_url["https://example.test/crash"]["error_kind"], "browser_error")

    def test_browser_max_concurrency_bounding(self):
        self.settings.update({"browser": {"enabled": True, "max_concurrency": 2}})

        active_count = 0
        max_active = 0
        lock = threading.Lock()

        def mock_render(url):
            nonlocal active_count, max_active
            with lock:
                active_count += 1
                if active_count > max_active:
                    max_active = active_count
            time.sleep(0.05)
            with lock:
                active_count -= 1
            return {"url": url, "title": "Page", "markdown": SAMPLE_PROSE, "text": SAMPLE_PROSE}

        BrowserClient.set_mock(mock_render)
        urls = [f"https://example.test/page/{i}" for i in range(5)]
        result = self.engine.fetch(urls, provider="browser", archive=False)

        self.assertEqual(result["status"], "ok")
        self.assertLessEqual(max_active, 2)
        self.assertGreaterEqual(max_active, 1)

    def test_browser_probe(self):
        # When disabled:
        probe = self.engine.probe(["browser"])
        self.assertEqual(probe["providers"][0]["status"], "not_configured")

        # When enabled:
        self.settings.update({"browser": {"enabled": True}})
        probe = self.engine.probe(["browser"])
        self.assertEqual(probe["providers"][0]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
