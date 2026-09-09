"""Compatibility against explicitly recorded public tools/list schemas."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from provider_adapters import ProviderAdapter
from remote_mcp import McpError


class ProviderSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / "tests/fixtures/provider-schemas-0.2.0.json").read_text())
        cls.registry = json.loads((ROOT / "config/providers.json").read_text())["providers"]

    def test_recorded_schemas_accept_search_and_extraction_arguments(self):
        self.assertEqual({row["provider"] for row in self.fixture["providers"]}, {"exa", "parallel", "tavily"})
        for row in self.fixture["providers"]:
            adapter = ProviderAdapter(row["provider"], self.registry[row["provider"]])
            for purpose in ("search", "fetch"):
                with self.subTest(provider=row["provider"], purpose=purpose):
                    tool = adapter.select(purpose, row["tools"])
                    arguments = adapter.arguments(tool, purpose, query="official MCP documentation",
                        urls=["https://example.com/", "https://example.org/"], limit=2, session_id="a" * 32)
                    self.assertLessEqual(set(tool["inputSchema"].get("required", [])), set(arguments))
                    self.assertLessEqual(set(arguments), set(tool["inputSchema"]["properties"]))
                    self.assertNotIn("model_name", arguments)
                    self.assertTrue(arguments)

    def test_new_required_field_is_not_populated_from_remote_defaults(self):
        for row in self.fixture["providers"]:
            adapter = ProviderAdapter(row["provider"], self.registry[row["provider"]])
            tool = copy.deepcopy(adapter.select("search", row["tools"]))
            tool["inputSchema"]["required"].append("billing_account")
            tool["inputSchema"]["properties"]["billing_account"] = {"type": "string", "default": "untrusted"}
            with self.subTest(provider=row["provider"]), self.assertRaisesRegex(McpError, "billing_account"):
                adapter.arguments(tool, "search", query="test")

    def test_supplied_values_are_checked_against_typed_constraints(self):
        for schema, value in (({"type": "number"}, True),
                ({"type": "array", "items": {"type": "string"}}, [1]),
                ({"type": "number", "maximum": 2}, 3),
                ({"anyOf": [{"type": "string"}, {"type": "null"}]}, ["text"]),
                ({"type": "string", "minLength": 3}, "a"),
                ({"type": "string", "$ref": "https://untrusted.example/schema"}, "a")):
            with self.subTest(schema=schema, value=value), self.assertRaises(McpError):
                ProviderAdapter._validate(schema, value)
        ProviderAdapter._validate({"anyOf": [{"type": "string"}, {"type": "null"}]}, "valid")

    def test_advertised_native_research_tools_are_never_selected_for_retrieval(self):
        row = next(row for row in self.fixture["providers"] if row["provider"] == "tavily")
        self.assertIn("tavily_research", row["advertised_tool_names"])
        adapter = ProviderAdapter("tavily", self.registry["tavily"])
        research_only = [{"name": "tavily_research", "inputSchema": {"type": "object", "properties": {}}}]
        for purpose in ("search", "fetch"):
            with self.subTest(purpose=purpose), self.assertRaises(McpError) as caught:
                adapter.select(purpose, research_only)
            self.assertEqual(caught.exception.kind, "capability_unavailable")


if __name__ == "__main__":
    unittest.main()
