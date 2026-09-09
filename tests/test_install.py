"""Native CLI contracts and isolated, repeatable Codex installation tests."""

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
import install


ROOT = Path(__file__).resolve().parents[1]


class ScriptedCli:
    binary = "codex path with spaces"
    timeout = 15

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def run(self, arguments):
        self.calls.append(arguments)
        expected, result = self.steps.pop(0)
        if arguments != expected:
            raise AssertionError((arguments, expected))
        if isinstance(result, Exception):
            raise result
        return result


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-install-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / '中文 source "quotes" $(literal)' / "bookmark-research"
        export_bundle.export_bundle("codex", self.source)
        self.version = export_bundle.read_plugin_manifest(self.source)["version"]
        self.registration = {"pluginId": install.SELECTOR, "installed": True, "enabled": True,
                             "version": self.version}
        self.local_marketplace = {"name": install.NAME, "root": str(self.source),
                                  "marketplaceSource": {"sourceType": "local", "source": str(self.source)}}
        self.git_marketplace = {"name": install.NAME, "root": str(self.source), "marketplaceSource": {
            "sourceType": "git", "source": "https://github.com/Browser-bookmark-hub/Bookmark-Research.git"}}
        environment = mock.patch.dict(os.environ, {
            "BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "user data"),
            "BOOKMARK_RESEARCH_CONFIG": str(self.base / "user settings.json"),
            "EXA_API_KEY": "environment-secret-marker", "TAVILY_API_KEY": "environment-secret-marker"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_dry_run_retains_paths_as_arguments_and_performs_no_mutations(self):
        cli = ScriptedCli([(["plugin", "marketplace", "list"], {"marketplaces": []})])
        result = install.manage("install", cli, source=self.source, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["commands"], [
            [cli.binary, "plugin", "marketplace", "add", str(self.source), "--json"],
            [cli.binary, "plugin", "add", install.SELECTOR, "--json"]])
        self.assertFalse(result.get("verified"))
        self.assertEqual(len(cli.calls), 1)
        self.assertNotIn("environment-secret-marker", json.dumps(result))
        self.assertFalse((self.base / "user data").exists())

    def test_install_checks_the_cached_runtime_and_registered_version(self):
        cli = ScriptedCli([
            (["plugin", "marketplace", "list"], {"marketplaces": []}),
            (["plugin", "marketplace", "add", str(self.source)], {"marketplaceName": install.NAME}),
            (["plugin", "add", install.SELECTOR], {"pluginId": install.SELECTOR, "installedPath": str(self.source)}),
            (["plugin", "list"], {"installed": [self.registration]}),
        ])
        result = install.manage("install", cli, source=self.source)
        self.assertTrue(result["verified"])
        self.assertEqual(result["version"], self.version)
        self.assertTrue(result["runtime"]["doctor"]["fts5"])
        self.assertIn("fetch_web", result["runtime"]["mcp_tools"])
        self.assertFalse(result["runtime"]["network_checked"])
        self.assertFalse((self.base / "user data").exists())
        self.assertEqual(cli.steps, [])

    def test_conflicting_source_stops_before_any_native_mutation(self):
        cli = ScriptedCli([(["plugin", "marketplace", "list"], {"marketplaces": [self.git_marketplace]})])
        with self.assertRaisesRegex(ValueError, "different source"):
            install.manage("install", cli, source=self.source)
        self.assertEqual(len(cli.calls), 1)

    def test_native_add_failure_does_not_attempt_plugin_add(self):
        cli = ScriptedCli([
            (["plugin", "marketplace", "list"], {"marketplaces": []}),
            (["plugin", "marketplace", "add", str(self.source)], RuntimeError("native install failed")),
        ])
        with self.assertRaisesRegex(RuntimeError, "native install failed"):
            install.manage("install", cli, source=self.source)
        self.assertEqual(len(cli.calls), 2)

    def test_git_update_errors_stop_before_reinstallation(self):
        cli = ScriptedCli([
            (["plugin", "marketplace", "list"], {"marketplaces": [self.git_marketplace]}),
            (["plugin", "list"], {"installed": [self.registration]}),
            (["plugin", "marketplace", "upgrade", install.NAME], {"errors": ["fetch failed"]}),
        ])
        with self.assertRaisesRegex(RuntimeError, "upgrade reported errors"):
            install.manage("update", cli)
        self.assertEqual(len(cli.calls), 3)

    def test_git_update_retains_the_registered_source_and_native_order(self):
        cli = ScriptedCli([
            (["plugin", "marketplace", "list"], {"marketplaces": [self.git_marketplace]}),
            (["plugin", "list"], {"installed": [self.registration]}),
        ])
        result = install.manage("update", cli, dry_run=True)
        self.assertEqual(result["commands"], [
            [cli.binary, "plugin", "marketplace", "upgrade", install.NAME, "--json"],
            [cli.binary, "plugin", "add", install.SELECTOR, "--json"]])
        self.assertEqual(result["source"], self.git_marketplace["marketplaceSource"])

    def test_first_git_install_passes_an_explicit_ref_to_codex(self):
        cli = ScriptedCli([(["plugin", "marketplace", "list"], {"marketplaces": []})])
        result = install.manage("install", cli, source="Browser-bookmark-hub/Bookmark-Research", ref="v0.2.0", dry_run=True)
        self.assertEqual(result["commands"][0], [cli.binary, "plugin", "marketplace", "add",
            "https://github.com/Browser-bookmark-hub/Bookmark-Research.git", "--ref", "v0.2.0", "--json"])
        self.assertFalse(result.get("verified"))

    def test_verify_refuses_disabled_or_mismatched_installs(self):
        cli = ScriptedCli([(["plugin", "list"], {"installed": [{**self.registration, "enabled": False}]})])
        with self.assertRaisesRegex(ValueError, "not installed and enabled"):
            install.verify(cli, self.source)
        cli = ScriptedCli([(["plugin", "list"], {"installed": [{**self.registration, "version": "9.0.0"}]})])
        with self.assertRaisesRegex(ValueError, "cache version differs"):
            install.verify(cli, self.source)

    def test_source_validation_rejects_credential_urls_and_local_refs(self):
        for value in ("https://user:secret@example.test/repo.git", "https://example.test/repo?token=secret",
                      "https://example.test/repo#token", "a\nsource"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                install._source(value)
        with self.assertRaisesRegex(ValueError, "--ref only applies"):
            install._source(self.source, ref="main")

    def test_existing_git_ref_cannot_be_assumed_from_repository_identity(self):
        cli = ScriptedCli([(["plugin", "marketplace", "list"], {"marketplaces": [self.git_marketplace]})])
        with self.assertRaisesRegex(ValueError, "retains its registered ref"):
            install.manage("install", cli, source="Browser-bookmark-hub/Bookmark-Research", ref="v0.2.0")
        self.assertEqual(len(cli.calls), 1)

    def test_json_contract_and_argument_array(self):
        cli = install.CodexCli("codex binary with spaces", timeout=12)
        completed = subprocess.CompletedProcess([], 0, '{"marketplaces": []}', "")
        with mock.patch.object(install.subprocess, "run", return_value=completed) as run:
            self.assertEqual(cli.run(["plugin", "marketplace", "list"]), {"marketplaces": []})
            self.assertEqual(run.call_args.args[0], [cli.binary, "plugin", "marketplace", "list", "--json"])
            self.assertFalse(run.call_args.kwargs.get("shell", False))
        completed.stdout = "not JSON"
        with mock.patch.object(install.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "must support"):
                cli.run(["plugin", "list"])


@unittest.skipUnless(shutil.which("codex"), "Codex CLI unavailable; native registration test skipped")
class NativeCodexInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-install-native-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / '中文 source $(literal) "quotes"' / "bookmark-research"
        export_bundle.export_bundle("codex", self.source)
        self.profile = self.base / "isolated codex profile"
        self.profile.mkdir()
        self.data = self.base / "user data"
        self.settings = self.base / "user settings.json"
        self.environment = dict(os.environ, CODEX_HOME=str(self.profile),
                                BOOKMARK_RESEARCH_DATA_DIR=str(self.data), BOOKMARK_RESEARCH_CONFIG=str(self.settings),
                                EXA_API_KEY="environment-secret-marker", TAVILY_API_KEY="environment-secret-marker",
                                PYTHONDONTWRITEBYTECODE="1")
        self.environment.pop("PYTHONPATH", None)
        self.environment.pop("PYTHONHOME", None)
        self.outside = self.base / "outside"
        self.outside.mkdir()

    def run_installer(self, *args, success=True):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/install.py"), *args],
                                cwd=self.outside, env=self.environment, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        self.assertNotIn("environment-secret-marker", result.stdout + result.stderr)
        return json.loads(result.stdout if success else result.stderr)

    def test_repeated_install_update_verify_and_conflict_protect_user_data(self):
        probe = self.source / "src/install_probe.py"
        probe.write_text("value = 'before'\n", encoding="utf-8")
        obsolete = self.source / "src/obsolete_probe.py"
        obsolete.write_text("value = 'removed in update'\n", encoding="utf-8")
        first = self.run_installer("install", "--source", str(self.source))
        self.assertTrue(first["verified"])
        self.assertFalse(self.data.exists())
        self.assertFalse(self.settings.exists())
        repeated = self.run_installer("install", "--source", str(self.source))
        self.assertEqual(first["installed_path"], repeated["installed_path"])
        self.data.mkdir()
        (self.data / "index.sqlite3").write_bytes(b"existing-user-index")
        self.settings.write_text('{"archive":{"enabled":false}}', encoding="utf-8")
        probe.write_text("value = 'after'\n", encoding="utf-8")
        obsolete.unlink()
        updated = self.run_installer("update")
        self.assertEqual(Path(updated["installed_path"], "src/install_probe.py").read_text(), "value = 'after'\n")
        self.assertFalse(Path(updated["installed_path"], "src/obsolete_probe.py").exists())
        manifest_path = self.source / ".codex-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "9.8.7"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        updated = self.run_installer("update")
        self.assertEqual(updated["version"], "9.8.7")
        verified = self.run_installer("verify")
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["installed_path"], updated["installed_path"])
        alternate = self.base / "other source" / "bookmark-research"
        export_bundle.export_bundle("codex", alternate)
        configuration = (self.profile / "config.toml").read_bytes()
        failed = self.run_installer("install", "--source", str(alternate), success=False)
        self.assertIn("different source", failed["error"])
        self.assertEqual((self.profile / "config.toml").read_bytes(), configuration)
        self.assertEqual((self.data / "index.sqlite3").read_bytes(), b"existing-user-index")
        self.assertEqual(self.settings.read_text(), '{"archive":{"enabled":false}}')
        self.assertTrue(self.run_installer("verify")["enabled"])

    def test_dry_run_and_absent_install_do_not_claim_success(self):
        result = self.run_installer("install", "--source", str(self.source), "--dry-run")
        self.assertTrue(result["dry_run"])
        self.assertFalse((self.profile / "plugins/cache").exists())
        self.assertFalse((self.profile / "config.toml").exists())
        self.assertFalse(self.run_installer("verify", success=False)["verified"])
        self.assertIn("run install first", self.run_installer("update", success=False)["error"])


if __name__ == "__main__":
    unittest.main()
