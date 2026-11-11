"""Regression checks for tool-surface capture presets."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bench_tools_list import PRESETS, capture
from mcp_server import REPLACED_TOOLS
from settings import Settings


class BenchToolsListTests(unittest.TestCase):
    def test_quick_preset_captures_the_primitives(self):
        _, _, tools = capture("quick")
        self.assertEqual(list(Settings.QUICK_TOOLS), [tool["name"] for tool in tools])

    def test_full_catalog_never_lists_replaced_names(self):
        self.assertNotIn("legacy", PRESETS)
        _, _, tools = capture("all")
        self.assertFalse(REPLACED_TOOLS.keys() & {tool["name"] for tool in tools})


if __name__ == "__main__":
    unittest.main()
