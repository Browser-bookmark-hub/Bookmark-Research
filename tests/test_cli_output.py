"""Stable CLI machine output, projection, file output and exit codes."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cli


class CliOutputTests(unittest.TestCase):
    def test_json_fields_and_out_work_after_nested_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_path = Path(temporary) / "doctor.json"
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                code = cli.main(["doctor", "--json", "--fields", "python,sqlite", "--out", str(output_path), "--quiet"])
            self.assertEqual(0, code)
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual({"python", "sqlite"}, set(saved))
            receipt = json.loads(stdout.getvalue())
            self.assertEqual(str(output_path), receipt["written"])
            self.assertEqual("", stderr.getvalue())

    def test_nested_wiki_command_accepts_output_options(self):
        parser = cli._parser()
        args = parser.parse_args(["wiki", "search", "needle", "--json", "--fields", "total"])
        self.assertTrue(args.json)
        self.assertEqual("total", args.fields)

    def test_field_projection_preserves_null_values_and_dotted_paths(self):
        self.assertEqual({"meta.revision": None, "total": 2},
                         cli._project_fields({"meta": {"revision": None}, "total": 2},
                                             "meta.revision,total,missing"))

    def test_runtime_error_is_stderr_and_exit_one(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = cli.main(["locate", "--text", "needle", "--source-id", "missing", "--no-refresh"])
        self.assertEqual(1, code)
        self.assertEqual("", stdout.getvalue())
        self.assertIn('"error"', stderr.getvalue())

    def test_ingest_accepts_file_input_without_inline_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "host-results.json"
            source.write_text(json.dumps({"batches": []}), encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                code = cli.main(["ingest", "--input", str(source), "--json"])
            self.assertEqual(0, code)
            self.assertEqual("", stderr.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual("no_provider", result["mode"])


if __name__ == "__main__":
    unittest.main()
