"""Exported manifests, independent runtime startup, and destination protection."""

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import export_bundle
import build_zip


ROOT = Path(__file__).resolve().parents[1]


class ExportBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bookmark-export-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source"
        for directory in export_bundle.SHARED_ROOTS:
            shutil.copytree(ROOT / directory, self.source / directory)
        for relative in export_bundle.SHARED_DOCUMENTS:
            (self.source / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, self.source / relative)
        shutil.copytree(ROOT / ".codex-plugin", self.source / ".codex-plugin")
        shutil.copytree(ROOT / "hosts", self.source / "hosts")
        shutil.copy2(ROOT / "LICENSE", self.source / "LICENSE")
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
            "codex": {".codex-plugin", ".agents", "hosts"},
            "agent-plugin": {"plugin.json", "mcp.json"},
            "claude": {".claude-plugin", ".mcp.json", "hosts", "workflows"},
            "pi": {"package.json", "hosts", "workflows"},
            "dsh": {"package.json", "bundle.patch.yml", "cordis.patch.yml", "hosts", "workflows"},
        }
        for format_name in export_bundle.FORMATS:
            with self.subTest(format=format_name):
                output = self.export(format_name)
                self.assertEqual({p.name for p in output.iterdir()},
                                 expected_roots[format_name] | {"src", "config", "skills", "docs", "README.md", "LICENSE"})
                for required in export_bundle.REQUIRED_FILES:
                    self.assertEqual((output / required).read_bytes(), (self.source / required).read_bytes())
                self.assertEqual(
                    [p.relative_to(output).as_posix() for p in (output / "skills").rglob("SKILL.md")],
                    ["skills/bookmark-research/SKILL.md"],
                    "Translations must not register duplicate Skills",
                )
                for reference in (self.source / "skills/bookmark-research/references").glob("*.md"):
                    translated = Path("skills/bookmark-research/references/zh") / reference.name
                    self.assertEqual((output / translated).read_bytes(), (self.source / translated).read_bytes())
                self.assertEqual((output / "skills/bookmark-research/references/zh/skill-guide.md").read_bytes(),
                                 (self.source / "skills/bookmark-research/references/zh/skill-guide.md").read_bytes())
                readme = (output / "README.md").read_text(encoding="utf-8")
                self.assertIn("[English user guide](docs/user-guide.en.md)", readme)
                self.assertIn("[中文使用指南](docs/user-guide.md)", readme)
                self.assertEqual((output / "skills/bookmark-research/agents/openai.yaml").exists(), format_name == "codex")
                if format_name == "codex":
                    manifest = self.read_json(output, ".codex-plugin/plugin.json")
                    self.assertEqual(manifest, self.read_json(self.source, ".codex-plugin/plugin.json"))
                    marketplace = self.read_json(output, ".agents/plugins/marketplace.json")
                    self.assertEqual(marketplace["plugins"][0]["source"], {"source": "local", "path": "./"})
                elif format_name == "agent-plugin":
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
                    self.assertEqual(manifest["workflows"], "./workflows")
                    self.assertIn("export const meta", (output / "workflows/bookmark-research.js").read_text())
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
                     "skills/bookmark-research/bookmarks.json", "skills/bookmark-research/credentials.json",
                     "skills/bookmark-research/knowledge/sources/page.md", "skills/bookmark-research/data/page.md",
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
        with mock.patch.dict(os.environ, {"EXA_API_KEY": "environment-secret-marker",
                                          "TAVILY_API_KEY": "environment-secret-marker"}):
            output = self.export("agent-plugin")
        for path in output.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"private-data-marker", path.read_bytes())
                self.assertNotIn(b"environment-secret-marker", path.read_bytes())
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
        for relative in ("src/settings.py", "src/research.py", "src/provider_adapters.py"):
            with self.subTest(relative=relative):
                path = self.source / relative
                original = path.read_bytes()
                path.unlink()
                output = self.base / "incomplete"
                with self.assertRaisesRegex(ValueError, relative):
                    self.export("agent-plugin", output)
                self.assertFalse(output.exists())
                path.write_bytes(original)

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

    def test_exports_read_version_from_native_manifest(self):
        path = self.source / ".codex-plugin/plugin.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["version"] = "0.2.3+codex.example"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        for format_name, relative in (("codex", ".codex-plugin/plugin.json"),
                                      ("agent-plugin", "plugin.json"),
                                      ("claude", ".claude-plugin/plugin.json"), ("pi", "package.json")):
            with self.subTest(format=format_name):
                self.assertEqual(self.read_json(self.export(format_name), relative)["version"], manifest["version"])


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bookmark-zip-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source with spaces"
        for directory in export_bundle.SHARED_ROOTS:
            shutil.copytree(ROOT / directory, self.source / directory)
        for name in dict.fromkeys((*build_zip.EXTRA_FILES, *export_bundle.SHARED_DOCUMENTS)):
            destination = self.source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)

    def test_reproducible_zip_has_integrity_manifest_and_standalone_installer(self):
        for relative in (".env", "config/settings.json", "src/cache/private.py",
                         "skills/bookmark-research/private.json", "tests/private.canvas",
                         "docs/research-sources-0.2.0.json"):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"private-data-marker")
        first = build_zip.build_zip(self.base / "release one.zip", self.source)
        second = build_zip.build_zip(self.base / "release two.zip", self.source)
        self.assertEqual(first["sha256"], second["sha256"])
        version = export_bundle.read_plugin_manifest(self.source)["version"]
        self.assertEqual(first["archive_root"], "bookmark-research-" + version)
        with zipfile.ZipFile(first["output"]) as archive:
            prefix = first["archive_root"] + "/"
            names = {name[len(prefix):] for name in archive.namelist()}
            self.assertTrue({".codex-plugin/plugin.json", ".agents/plugins/marketplace.json",
                             "scripts/install.py", "install.sh", "MANIFEST.sha256",
                             "README.md", "README.zh.md", "docs/installation.md",
                             "docs/installation.en.md", "docs/user-guide.md",
                             "docs/user-guide.en.md", "docs/instructions.en.md",
                             "docs/instructions.md", "docs/prompt-reference.en.md",
                             "docs/prompt-reference.md", "docs/wiki-quality.zh.md",
                             "skills/bookmark-research/references/zh/skill-guide.md"} <= names)
            checksums = archive.read(prefix + "MANIFEST.sha256").decode("utf-8").splitlines()
            self.assertEqual(len(checksums), len(names) - 1)
            for line in checksums:
                digest, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256(archive.read(prefix + name)).hexdigest(), digest)
            for name in archive.namelist():
                self.assertNotIn(b"private-data-marker", archive.read(name))
            archive.extractall(self.base / "extracted directory")
        source = self.base / "extracted directory" / first["archive_root"]
        result = subprocess.run([sys.executable, "-B", str(source / "scripts/install.py"), "--help"],
                                cwd=self.base, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("install,update,verify", result.stdout)
        for format_name in export_bundle.FORMATS:
            result = subprocess.run([sys.executable, "-B", str(source / "scripts/export_bundle.py"),
                                     "--format", format_name, "--output", str(self.base / ("再导出 " + format_name))],
                                    cwd=self.base, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["version"], version)

    def test_existing_output_and_source_links_are_preserved(self):
        output = self.base / "existing.zip"
        output.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "existing output"):
            build_zip.build_zip(output, self.source)
        self.assertEqual(output.read_bytes(), b"keep")
        script = self.source / "scripts/install.py"
        script.unlink()
        script.symlink_to(ROOT / "scripts/install.py")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            build_zip.build_zip(self.base / "invalid.zip", self.source)
        self.assertFalse((self.base / "invalid.zip").exists())

    def test_failed_zip_build_does_not_publish_a_partial_archive(self):
        output = self.base / "interrupted.zip"
        with mock.patch.object(build_zip.zipfile.ZipFile, "writestr", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                build_zip.build_zip(output, self.source)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.base.glob(".bookmark-research-zip-*")))

    def test_verification_pack_includes_fixtures_and_runs_offline_after_extraction(self):
        shutil.copytree(ROOT / "tests", self.source / "tests")
        shutil.copy2(ROOT / "scripts/verify_fixture.py", self.source / "scripts/verify_fixture.py")
        shutil.copy2(ROOT / "scripts/verify_quality.py", self.source / "scripts/verify_quality.py")
        marker = os.urandom(32)
        secret = self.source / "tests/.env"
        secret.write_bytes(marker)
        cached = self.source / "tests/__pycache__/private.pyc"
        cached.parent.mkdir(exist_ok=True)
        cached.write_bytes(marker)
        ordinary = build_zip.build_zip(self.base / "plugin.zip", self.source)
        packed = build_zip.build_zip(self.base / "test pack.zip", self.source, include_tests=True)
        self.assertFalse(ordinary["includes_tests"])
        self.assertTrue(packed["includes_tests"])
        with zipfile.ZipFile(ordinary["output"]) as archive:
            self.assertFalse(any("/tests/" in name for name in archive.namelist()))
        with zipfile.ZipFile(packed["output"]) as archive:
            names = archive.namelist()
            prefix = packed["archive_root"] + "/"
            self.assertIn(prefix + "scripts/verify_fixture.py", names)
            self.assertIn(prefix + "scripts/verify_quality.py", names)
            self.assertIn(prefix + "scripts/host_assets.py", names)
            self.assertIn(prefix + "hosts/pi/runtime.js", names)
            self.assertIn(prefix + "tests/host-workflows.test.js", names)
            self.assertIn(prefix + "tests/test_research.py", names)
            self.assertTrue(any(name.startswith(prefix + "tests/fixtures/canvas/") for name in names))
            self.assertTrue(any(name.startswith(prefix + "tests/fixtures/research-scenario.json") for name in names))
            for name in names:
                self.assertFalse(marker in archive.read(name), name)
            archive.extractall(self.base / "test pack extracted")
        extracted = self.base / "test pack extracted" / packed["archive_root"]
        result = subprocess.run([sys.executable, "-B", str(extracted / "scripts/verify_fixture.py"),
                                 "--output", str(self.base / "offline validation")],
                                cwd=self.base, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", str(extracted / "tests"),
                                 "-p", "test_host_workflows.py"], cwd=self.base, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
