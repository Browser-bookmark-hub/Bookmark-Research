"""Exported manifests, independent runtime startup, and destination protection."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import export_bundle


ROOT = Path(__file__).resolve().parents[1]


class ExportBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bookmark-export-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source"
        for directory in export_bundle.SHARED_ROOTS:
            shutil.copytree(ROOT / directory, self.source / directory)
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.data = self.base / "shared-data"
        self.env = dict(os.environ, BOOKMARK_RESEARCH_DATA_DIR=str(self.data),
                        PYTHONDONTWRITEBYTECODE="1")
        self.env.pop("PYTHONPATH", None)
        self.env.pop("PYTHONHOME", None)

    def export(self, format_name, output=None):
        output = output or self.base / ("export " + format_name)
        result = export_bundle.export_bundle(format_name, output, self.source)
        self.assertFalse(result["installed"])
        self.assertEqual(result["output"], str(output.resolve()))
        return output

    def run_cli(self, output, *args, input_text=None):
        result = subprocess.run([sys.executable, "-B", str(output / "src/cli.py"), *args],
                                input=input_text, text=True, capture_output=True,
                                cwd=self.outside, env=self.env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    @staticmethod
    def read_json(root, path):
        return json.loads((root / path).read_text(encoding="utf-8"))

    def test_each_format_has_its_own_manifest_and_shared_files(self):
        expected_roots = {
            "agent-plugin": {"plugin.json", "mcp.json"},
            "claude": {".claude-plugin", ".mcp.json"},
            "pi": {"package.json"},
            "dsh": {"cordis.patch.yml"},
        }
        for format_name in export_bundle.FORMATS:
            with self.subTest(format=format_name):
                output = self.export(format_name)
                self.assertEqual({p.name for p in output.iterdir()},
                                 expected_roots[format_name] | {"src", "config", "skills", "README.md"})
                for required in export_bundle.REQUIRED_FILES:
                    self.assertEqual((output / required).read_bytes(), (self.source / required).read_bytes())
                self.assertFalse((output / "skills/bookmark-research/agents/openai.yaml").exists())
                if format_name == "agent-plugin":
                    manifest = self.read_json(output, "plugin.json")
                    self.assertEqual(set(manifest), {"$schema", "name", "version", "description"})
                    self.assertEqual(manifest["$schema"],
                                     "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
                    config = self.read_json(output, "mcp.json")
                    self.assertEqual(config["$schema"],
                                     "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json")
                    server = config["mcpServers"]["bookmark-research"]
                    self.assertEqual(server, {"type": "stdio", "command": "python3",
                                              "args": ["${PLUGIN_ROOT}/src/cli.py", "serve"]})
                elif format_name == "claude":
                    manifest = self.read_json(output, ".claude-plugin/plugin.json")
                    self.assertEqual(manifest["name"], "bookmark-research")
                    server = self.read_json(output, ".mcp.json")["mcpServers"]["bookmark-research"]
                    self.assertEqual(server, {"type": "stdio", "command": "python3",
                                              "args": ["${CLAUDE_PLUGIN_ROOT}/src/cli.py", "serve"]})
                elif format_name == "pi":
                    manifest = self.read_json(output, "package.json")
                    self.assertEqual(manifest["pi"], {"skills": ["./skills"]})
                    self.assertNotIn("dsh", manifest)
                    self.assertNotIn("scripts", manifest)
                else:
                    patch = (output / "cordis.patch.yml").read_text(encoding="utf-8")
                    self.assertIn(json.dumps(str(output / "src/cli.py"), ensure_ascii=False), patch)
                    self.assertIn("name: '@deepseek-ai/dsh-mcp-client'", patch)
                    self.assertNotIn("${", patch)
                    self.assertNotIn("--db", patch)
                    self.assertIn("absolute local paths", (output / "README.md").read_text(encoding="utf-8"))

    def test_exports_run_without_the_original_source_or_current_directory(self):
        outputs = [self.export(name) for name in export_bundle.FORMATS]
        shutil.rmtree(self.source)
        for output in outputs:
            with self.subTest(format=output.name):
                doctor = json.loads(self.run_cli(output, "doctor").stdout)
                self.assertEqual(doctor["database"], str(self.data / "index.sqlite3"))
                self.assertFalse(doctor["database_created"])
                self.assertFalse(doctor["network_checked"])
                providers = json.loads(self.run_cli(output, "providers").stdout)
                self.assertFalse(providers["probe_performed"])
                self.assertIn("exa", {row["provider"] for row in providers["providers"]})
                self.assertFalse(self.data.exists())

    def test_exported_mcp_initialization_and_shared_database_location(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "export-test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        output = self.export("agent-plugin")
        config = self.read_json(output, "mcp.json")["mcpServers"]["bookmark-research"]
        args = [arg.replace("${PLUGIN_ROOT}", str(output)) for arg in config["args"]]
        for create_database in (False, True):
            with self.subTest(create_database=create_database):
                requests = list(messages)
                if create_database:
                    requests.append({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                     "params": {"name": "index_status", "arguments": {}}})
                result = subprocess.run([sys.executable, "-B", *args], cwd=self.outside, env=self.env,
                                        input="\n".join(json.dumps(row) for row in requests) + "\n",
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                responses = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual([row["id"] for row in responses], [1, 2, 3] if create_database else [1, 2])
                self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
                tool_names = {row["name"] for row in responses[1]["result"]["tools"]}
                self.assertTrue({"search_bookmarks", "get_context", "search_web"} <= tool_names)
                self.assertEqual((self.data / "index.sqlite3").exists(), create_database)
                if create_database:
                    self.assertFalse(responses[-1]["result"]["isError"])
                    status = json.loads(responses[-1]["result"]["content"][0]["text"])
                    self.assertEqual(status["sources"], [])
        self.assertFalse(list(output.rglob("*.sqlite3")))

    def test_private_data_and_build_artifacts_are_not_exported(self):
        artifacts = ["src/__pycache__/cli.cpython.pyc", "src/cache/page.md", "src/.git/config",
                     "src/tests/example.py", "src/build/output.py", "config/.env",
                     "config/index.sqlite3", "config/index.sqlite3-wal", "config/index.db.bak",
                     "config/settings.json", "config/credentials.json", "src/knowledge/sources/page.md",
                     "src/private-package.json", "skills/bookmark-research/data.canvas",
                     "skills/bookmark-research/cache/secret.md", "skills/bookmark-research/debug.log"]
        for relative in artifacts:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"private-data-marker")
        extensionless = self.source / "config/private-store"
        extensionless.write_bytes(b"SQLite format 3\x00private-data-marker")
        support = self.source / "skills/bookmark-research/references/lookup.md"
        support.parent.mkdir(parents=True, exist_ok=True)
        support.write_text("Shared reference", encoding="utf-8")
        output = self.export("agent-plugin")
        for path in output.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"private-data-marker", path.read_bytes())
        self.assertTrue((output / support.relative_to(self.source)).is_file())

    def test_refuses_nonempty_file_and_symlink_outputs_without_changes(self):
        directory = self.base / "occupied"
        directory.mkdir()
        sentinel = directory / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        link = self.base / "linked"
        link.symlink_to(directory, target_is_directory=True)
        for output in (directory, sentinel, link):
            with self.subTest(output=output.name), self.assertRaises(ValueError):
                self.export("agent-plugin", output)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertEqual({p.name for p in directory.iterdir()}, {"keep.txt"})
        self.assertTrue(link.is_symlink())

    def test_accepts_empty_output_and_rejects_overlapping_source(self):
        output = self.base / "empty"
        output.mkdir()
        self.export("pi", output)
        overlap = self.source / "skills" / "new-output"
        with self.assertRaisesRegex(ValueError, "shared source root"):
            self.export("pi", overlap)
        self.assertFalse(overlap.exists())

    def test_invalid_source_does_not_publish_partial_files(self):
        output = self.base / "failed-export"
        secret = self.base / "external-secret"
        secret.write_text("external", encoding="utf-8")
        (self.source / "src/linked-secret.py").symlink_to(secret)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.export("claude", output)
        self.assertFalse(output.exists())
        (self.source / "src/linked-secret.py").unlink()
        output.mkdir()
        with mock.patch.object(export_bundle.shutil, "copy2", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(OSError, "copy failed"):
                self.export("claude", output)
        self.assertEqual(list(output.iterdir()), [])
        self.assertFalse(list(self.base.glob(".bookmark-research-export-*")))

    def test_missing_runtime_dependency_cannot_publish_a_broken_bundle(self):
        (self.source / "src/settings.py").unlink()
        output = self.base / "incomplete"
        with self.assertRaisesRegex(ValueError, "src/settings.py"):
            self.export("agent-plugin", output)
        self.assertFalse(output.exists())

    def test_dsh_quotes_absolute_path_and_cli_entry_point(self):
        output = self.base / 'DSH 本机 "目录"'
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/export_bundle.py"),
                                 "--format", "dsh", "--output", str(output)],
                                cwd=self.outside, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["format"], "dsh")
        patch = (output / "cordis.patch.yml").read_text(encoding="utf-8")
        path_line = next(line for line in patch.splitlines() if 'src/cli.py' in line)
        self.assertEqual(json.loads(path_line.strip()[2:]), str(output / "src/cli.py"))
        repeated = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/export_bundle.py"),
                                   "--format", "dsh", "--output", str(output)],
                                  cwd=self.outside, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("nonempty", json.loads(repeated.stderr)["error"])
        self.assertEqual((output / "cordis.patch.yml").read_text(encoding="utf-8"), patch)


if __name__ == "__main__":
    unittest.main()
