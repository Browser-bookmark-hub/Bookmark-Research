"""Regression checks for historical tool-surface capture presets."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bench_tools_list import LEGACY_TOOLS, capture


class BenchToolsListTests(unittest.TestCase):
    def test_legacy_preset_replays_frozen_2026_11_06_catalog(self):
        self.assertEqual(25, len(LEGACY_TOOLS))
        self.assertEqual(len(LEGACY_TOOLS), len(set(LEGACY_TOOLS)))
        with mock.patch("mcp_server.release_version", return_value="0.6.2"):
            _, _, tools = capture("legacy")
        self.assertEqual(list(LEGACY_TOOLS), [tool["name"] for tool in tools])

    def test_legacy_preset_expires_at_070(self):
        with mock.patch("mcp_server.release_version", return_value="0.8.0"):
            with self.assertRaisesRegex(ValueError, "ended at 0.8.0"):
                capture("legacy")


if __name__ == "__main__":
    unittest.main()
