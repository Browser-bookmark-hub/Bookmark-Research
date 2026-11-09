"""Host ladder template setup without pretending to run host traces."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cli
import mcp_server


class CliBenchTests(unittest.TestCase):
    def test_ladder_legacy_initializes_capture_template(self):
        with tempfile.TemporaryDirectory(prefix="bookmark-ladder-") as temporary:
            destination = Path(temporary) / "ladder.json"
            with mock.patch("mcp_server.release_version", return_value="0.6.2"):
                code = cli.main(["bench", "ladder", "--preset", "legacy", "--file", str(destination)])
            self.assertEqual(0, code)
            artifact = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual("legacy-25", artifact["tool_surface"])
            self.assertEqual("2026-11-legacy", artifact["baseline_id"])
            self.assertEqual(25, len(artifact["required_tool_scope"]))
            self.assertEqual(15, len(artifact["questions"]))
            self.assertEqual([], artifact["questions"][0]["runs"])

    def test_legacy_ladder_preset_expires_at_070(self):
        with tempfile.TemporaryDirectory(prefix="bookmark-ladder-") as temporary:
            destination = Path(temporary) / "ladder.json"
            with mock.patch("mcp_server.release_version", return_value="0.8.0"):
                code = cli.main(["bench", "ladder", "--preset", "legacy", "--file", str(destination)])
            self.assertEqual(1, code)
            self.assertFalse(destination.exists())

    def test_ladder_init_does_not_overwrite_existing_capture(self):
        with tempfile.TemporaryDirectory(prefix="bookmark-ladder-") as temporary:
            destination = Path(temporary) / "ladder.json"
            destination.write_text('{"preserve":true}', encoding="utf-8")
            code = cli.main(["bench", "ladder", "--preset", "quick", "--file", str(destination)])
            self.assertEqual(1, code)
            self.assertEqual('{"preserve":true}', destination.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
