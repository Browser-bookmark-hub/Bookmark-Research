"""Route ②'s plugin side: the budget decision and a bundle that degrades, never empties."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from discovery import DIGEST_CHARACTERS, EXCERPT_CHARACTERS, budget_check, evidence_bundle
from mcp_server import StdioMcpServer
from settings import Settings

TEXT = "A sentence of usable page text that a claim could quote. " * 40


def source(url, **extra):
    return {"url": url, "title": extra.pop("title", "Title"), "text": extra.pop("text", TEXT), **extra}


class BudgetTests(unittest.TestCase):
    def test_the_plan_limits_decide_when_to_stop(self):
        fresh = budget_check()
        self.assertTrue(fresh["continue"])
        self.assertIsNone(fresh["reason"])
        self.assertEqual({"max_steps": 6, "max_fetches": 8, "max_variants": 3, "max_seconds": 90}, fresh["limits"])
        self.assertEqual({"steps": 6, "fetches": 8, "variants": 3, "seconds": 90}, fresh["remaining"])
        for fields, reason in (({"steps": 6}, "steps_reached"), ({"fetches": 8}, "fetches_reached"),
                               ({"variants": 3}, "variants_reached"), ({"elapsed_seconds": 90}, "seconds_reached")):
            with self.subTest(fields=fields):
                stopped = budget_check(**fields)
                self.assertFalse(stopped["continue"])
                self.assertEqual(reason, stopped["reason"])
                self.assertEqual(0, stopped["remaining"][reason.split("_")[0]])
        self.assertTrue(budget_check(steps=5, fetches=7, variants=2, elapsed_seconds=89.5)["continue"])
        self.assertIn("plugin owns", budget_check()["note"])

    def test_limits_can_be_tightened_and_every_field_is_validated(self):
        self.assertFalse(budget_check(steps=2, limits={"max_steps": 2})["continue"])
        for limits in ({"max_steps": 0}, {"max_seconds": 4}, {"unknown": 1}):
            with self.assertRaises(ValueError):
                budget_check(limits=limits)
        for fields in ({"steps": -1}, {"fetches": True}, {"variants": "2"},
                       {"elapsed_seconds": -1}, {"elapsed_seconds": "90"}):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    budget_check(**fields)


class BundleTests(unittest.TestCase):
    def test_usable_pages_become_citable_evidence_with_stable_ids(self):
        bundle = evidence_bundle([source("https://a.example/1", published_at="2026-10-06"),
                                  source("https://a.example/2", provider_published_at="2026-01-02")])
        self.assertEqual("excerpts", bundle["degradation"])
        self.assertFalse(bundle["truncated"])
        self.assertEqual(["e1", "e2"], [row["id"] for row in bundle["evidence"]])
        self.assertEqual("2026-10-06", bundle["evidence"][0]["published_at"])
        self.assertEqual("2026-01-02", bundle["evidence"][1]["published_at"])
        self.assertEqual(len(TEXT), bundle["evidence"][0]["characters"])
        self.assertEqual(TEXT[:EXCERPT_CHARACTERS], bundle["evidence"][0]["excerpt"])
        self.assertTrue(bundle["evidence"][0]["excerpt_truncated"])
        self.assertEqual([], bundle["unavailable_sources"])
        self.assertEqual([], bundle["gaps"])
        self.assertIn("evidence[].id", bundle["citation_rule"])
        self.assertEqual("Report the evidence and the gaps.", bundle["next_action"])

    def test_non_usable_pages_are_listed_with_their_reason(self):
        bundle = evidence_bundle([source("https://a.example/1"),
                                  {"url": "https://a.example/shell", "title": "Shell", "content_state": "js_shell_suspected"},
                                  {"url": "https://a.example/failed", "error": "provider_error"}])
        self.assertEqual(1, bundle["evidence_count"])
        self.assertEqual([{"url": "https://a.example/shell", "reason": "js_shell_suspected", "title": "Shell"},
                          {"url": "https://a.example/failed", "reason": "provider_error", "title": ""}],
                         bundle["unavailable_sources"])

    def test_a_collection_without_usable_text_still_returns_the_url_list(self):
        bundle = evidence_bundle([{"url": "https://a.example/1", "content_state": "content_insufficient"},
                                  {"url": "https://a.example/2", "content_state": "challenge_blocked"}])
        self.assertEqual([], bundle["evidence"])
        self.assertEqual(2, bundle["unavailable_count"])
        self.assertEqual(["No usable page text was collected for this question"], bundle["gaps"])
        self.assertIn("do not answer from snippets", bundle["next_action"])
        self.assertGreater(bundle["characters"], 0)

    def test_the_bundle_degrades_to_fit_before_it_truncates(self):
        sources = [source("https://a.example/%d" % index) for index in range(6)]
        digest = evidence_bundle(sources, max_characters=3000)
        self.assertEqual("digest", digest["degradation"])
        self.assertEqual(DIGEST_CHARACTERS, len(digest["evidence"][0]["excerpt"]))
        self.assertLessEqual(digest["characters"], 3000)
        self.assertFalse(digest["truncated"])
        listed = evidence_bundle(sources, max_characters=1000)
        self.assertEqual("list", listed["degradation"])
        self.assertNotIn("excerpt", listed["evidence"][0])
        self.assertLessEqual(listed["characters"], 1000)
        self.assertFalse(listed["truncated"])

    def test_a_bundle_that_cannot_fit_even_as_a_list_is_marked_truncated(self):
        sources = [{"url": "https://a.example/" + "x" * 300, "title": "T"} for index in range(64)]
        bundle = evidence_bundle(sources, max_characters=1000)
        self.assertEqual("list", bundle["degradation"])
        self.assertTrue(bundle["truncated"])
        self.assertEqual(64, bundle["unavailable_count"])

    def test_inputs_are_validated(self):
        for bad in (None, "sources", {"url": "https://a.example/1"}):
            with self.assertRaises(ValueError):
                evidence_bundle(bad)
        with self.assertRaises(ValueError):
            evidence_bundle([{"title": "no url"}])
        with self.assertRaises(ValueError):
            evidence_bundle([source("https://a.example/1")] * 65)
        with self.assertRaises(ValueError):
            evidence_bundle([source("https://a.example/1")], max_characters=999)
        with self.assertRaises(ValueError):
            evidence_bundle([source("https://a.example/1")], excerpt_characters=79)


class DiscoveryToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.root / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.settings = Settings(self.root / "settings.json")
        self.server = StdioMcpServer(self.root / "index.sqlite3", settings=self.settings)
        self.addCleanup(self.server.close)
        self.server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                       "clientInfo": {"name": "fixture", "version": "1"}}})
        self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, name, arguments):
        return self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": name, "arguments": arguments}})

    def test_the_tool_returns_the_budget_decision_with_the_bundle(self):
        listing = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertIn("discovery_bundle", {tool["name"] for tool in listing})
        response = self.call("discovery_bundle", {
            "sources": [source("https://a.example/1"),
                        {"url": "https://a.example/shell", "content_state": "js_shell_suspected"}],
            "steps": 6, "fetches": 2, "variants": 1, "elapsed_seconds": 41})
        self.assertFalse(response["result"]["isError"], response)
        payload = response["result"]["structuredContent"]
        self.assertFalse(payload["budget"]["continue"])
        self.assertEqual("steps_reached", payload["budget"]["reason"])
        self.assertEqual({"steps": 6, "fetches": 2, "variants": 1, "seconds": 41}, payload["budget"]["used"])
        self.assertEqual(["e1"], [row["id"] for row in payload["evidence"]])
        self.assertEqual(1, payload["unavailable_count"])

    def test_invalid_arguments_never_reach_the_tool(self):
        self.assertEqual(-32602, self.call("discovery_bundle", {})["error"]["code"])
        self.assertEqual(-32602, self.call("discovery_bundle", {"sources": "all"})["error"]["code"])
        self.assertEqual(-32602, self.call("discovery_bundle", {"sources": [], "steps": 41})["error"]["code"])
        self.assertEqual(-32602, self.call("discovery_bundle", {"sources": [], "elapsed_seconds": -1})["error"]["code"])


if __name__ == "__main__":
    unittest.main()
