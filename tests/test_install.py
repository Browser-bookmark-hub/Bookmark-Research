"""Native CLI contracts and isolated, repeatable Codex installation tests."""

import io
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


class InstallerLanguageTests(unittest.TestCase):
    def test_explicit_language_and_locale_precedence(self):
        cases = [
            ("auto", {}, "en"),
            ("auto", {"LANG": "zh_CN.UTF-8"}, "zh"),
            ("auto", {"LANG": "en_US.UTF-8", "LC_MESSAGES": "zh_TW.UTF-8"}, "zh"),
            ("auto", {"LANG": "zh_CN.UTF-8", "LC_MESSAGES": "zh_TW.UTF-8", "LC_ALL": "C"}, "en"),
            ("auto", {"LANG": "zh_CN.UTF-8", "LC_ALL": ""}, "zh"),
            ("auto", {"LANG": "fr_FR.UTF-8"}, "en"),
            ("auto", {"LANG": "en", "BOOKMARK_RESEARCH_INSTALL_LANG": "zh"}, "zh"),
            ("en", {"LANG": "zh_CN.UTF-8", "BOOKMARK_RESEARCH_INSTALL_LANG": "zh"}, "en"),
            ("zh", {"LC_ALL": "C"}, "zh"),
        ]
        for requested, environment, expected in cases:
            with self.subTest(requested=requested, environment=environment):
                before = dict(environment)
                self.assertEqual(install.resolve_language(requested, environment), expected)
                self.assertEqual(environment, before)
        with self.assertRaises(ValueError):
            install.resolve_language("fr", {})

    def test_python_help_accepts_language_before_or_after_action_without_installing(self):
        for arguments, expected in ((["--lang", "en", "install", "--help"], "Installer language"),
                                    (["install", "--help", "--lang", "zh"], "安装器语言")):
            with self.subTest(arguments=arguments), mock.patch.object(install, "manage") as manage:
                output = io.StringIO()
                with mock.patch.object(install.sys, "stdout", output), self.assertRaises(SystemExit) as stopped:
                    install.main(arguments)
                self.assertEqual(stopped.exception.code, 0)
                self.assertIn(expected, output.getvalue())
                manage.assert_not_called()


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-install-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / ('中文 source ' + ('quotes' if os.name == 'nt' else '"quotes"') + ' $(literal)') / "bookmark-research"
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

    def test_invalid_preferences_stop_before_native_registration(self):
        path = self.base / "preferences.json"
        for value in ("[]", "{}", '{"OPENAI_API_KEY":"never-echo-this-secret"}', '{"readiness":{"mode":"invalid"}}', "{"):
            with self.subTest(value=value):
                path.write_text(value)
                output = io.StringIO()
                with mock.patch.object(install, "manage") as manage, mock.patch.object(sys, "stderr", output):
                    code = install.main(["install", "--host", "codex", "--non-interactive", "--preferences", str(path)])
                self.assertEqual(code, 1)
                manage.assert_not_called()
                self.assertNotIn("never-echo-this-secret", output.getvalue())
        self.assertFalse((self.base / "user settings.json").exists())

    def test_codex_alone_rejects_host_options_and_deduplicates_hosts(self):
        errors = io.StringIO()
        with mock.patch.object(install, "manage") as manage, mock.patch.object(sys, "stderr", errors):
            code = install.main(["install", "--host", "codex,codex", "--non-interactive", "--scope", "user"])
        self.assertEqual(code, 1)
        self.assertIn("Host-specific options", json.loads(errors.getvalue())["error"])
        manage.assert_not_called()
        output = io.StringIO()
        with mock.patch.object(install, "manage", return_value={"dry_run": True}) as manage, \
                mock.patch.object(sys, "stdout", output):
            code = install.main(["install", "--host", "codex", "--host", "codex", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"dry_run": True})
        manage.assert_called_once()

    def test_dry_run_validates_preferences_without_saving_them(self):
        path = self.base / "preferences.json"
        path.write_text('{"readiness":{"mode":"always"}}')
        output = io.StringIO()
        with mock.patch.object(install, "manage", return_value={"dry_run": True}), mock.patch.object(sys, "stdout", output):
            code = install.main(["install", "--host", "codex", "--dry-run", "--preferences", str(path)])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output.getvalue())["preferences_applied"])
        self.assertFalse((self.base / "user settings.json").exists())

    def test_historical_install_succeeds_without_silently_ignoring_requested_setup(self):
        (self.source / "src/onboarding.py").unlink()
        path = self.base / "preferences.json"
        path.write_text('{"research":{"depth":"quick"}}')
        for extra, expected in (([], 0), (["--preferences", str(path)], 1)):
            output = io.StringIO()
            with self.subTest(extra=extra), mock.patch.object(install, "manage", return_value={
                    "verified": True, "installed_path": str(self.source)}), \
                    mock.patch.object(install, "_getting_started", return_value={}), \
                    mock.patch.object(install, "_print_getting_started"), \
                    mock.patch.object(sys, "stdout", output), mock.patch.object(sys, "stderr", io.StringIO()):
                code = install.main(["install", "--non-interactive", *extra])
            self.assertEqual(code, expected)
            result = json.loads(output.getvalue())
            self.assertTrue(result["verified"])
            self.assertEqual(result["setup"]["status"], "unsupported")

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
        self.assertFalse(result["getting_started"]["configuration"]["config_exists"])
        self.assertEqual(result["getting_started"]["configuration"]["settings"]["search"]["providers"], ["exa", "parallel"])
        self.assertFalse((self.base / "user data").exists())
        self.assertFalse((self.base / "user settings.json").exists())
        self.assertEqual(cli.steps, [])

    def test_local_source_missing_host_assets_stops_before_native_mutation(self):
        for relative in ("hosts/codex/delegate.md", "hosts/codex/prepare.py", "hosts/shared/research-call.py"):
            with self.subTest(relative=relative):
                asset = self.source / relative
                original = asset.read_bytes()
                asset.unlink()
                cli = ScriptedCli([(["plugin", "marketplace", "list"], {"marketplaces": []})])
                try:
                    with self.assertRaisesRegex(ValueError, "Required host asset is missing") as caught:
                        install.manage("install", cli, source=self.source)
                    self.assertIn(relative, str(caught.exception))
                    self.assertEqual(cli.calls, [["plugin", "marketplace", "list"]])
                finally:
                    asset.write_bytes(original)

    def _check_invalid_cached_host_assets(self, missing):
        for action in ("install", "update"):
            for ordinal, relative in enumerate(("hosts/codex/delegate.md", "hosts/codex/prepare.py", "hosts/shared/research-call.py")):
                with self.subTest(action=action, relative=relative):
                    cached = self.base / (action + "-cache-" + str(ordinal))
                    shutil.copytree(self.source, cached)
                    asset = cached / relative
                    if missing:
                        asset.unlink()
                    else:
                        asset.write_bytes(asset.read_bytes() + b"\n# Stale cached host asset\n")
                    if action == "install":
                        steps = [
                            (["plugin", "marketplace", "list"], {"marketplaces": []}),
                            (["plugin", "marketplace", "add", str(self.source)], {"marketplaceName": install.NAME}),
                        ]
                    else:
                        steps = [
                            (["plugin", "marketplace", "list"], {"marketplaces": [self.local_marketplace]}),
                            (["plugin", "list"], {"installed": [self.registration]}),
                        ]
                    steps.extend([
                        (["plugin", "add", install.SELECTOR], {"pluginId": install.SELECTOR, "installedPath": str(cached)}),
                        (["plugin", "list"], {"installed": [self.registration]}),
                    ])
                    cli = ScriptedCli(steps)
                    with self.assertRaises((ValueError, RuntimeError)) as caught:
                        install.manage(action, cli, source=self.source if action == "install" else None)
                    self.assertIn(relative, str(caught.exception))
                    self.assertEqual(cli.steps, [])
                    self.assertFalse((self.base / "user data").exists())

    def test_local_install_and_update_reject_missing_cached_host_assets(self):
        self._check_invalid_cached_host_assets(missing=True)

    def test_local_install_and_update_reject_stale_cached_host_assets(self):
        self._check_invalid_cached_host_assets(missing=False)

    def test_onboarding_reads_actual_preferences_and_its_command_works_outside_source(self):
        settings_path = self.base / "user settings.json"
        original = '{"search":{"providers":["tavily"],"limit_per_target":3},"archive":{"enabled":false}}'
        settings_path.write_text(original)
        guide = install._getting_started(self.source)
        self.assertIsNone(guide["configuration_error"])
        self.assertTrue(guide["configuration"]["config_exists"])
        self.assertEqual(guide["configuration"]["settings"]["search"]["providers"], ["tavily"])
        self.assertFalse(guide["configuration"]["settings"]["archive"]["enabled"])
        checked = subprocess.run(guide["settings_command"], cwd=self.base, text=True,
                                 capture_output=True, check=True, timeout=15)
        self.assertEqual(json.loads(checked.stdout), guide["configuration"])
        output = io.StringIO()
        with mock.patch.object(install.sys, "stderr", output):
            install._print_getting_started(guide)
        self.assertIn("tavily", output.getvalue())
        self.assertNotIn("environment-secret-marker", output.getvalue() + json.dumps(guide))
        self.assertEqual(settings_path.read_text(), original)
        self.assertFalse((self.base / "user data").exists())

    def test_runtime_discovery_cannot_monitor_the_users_existing_sources(self):
        from test_bookmark_index import BookmarkIndex, TEMP, make_package, read_json, write_json
        from source_manager import SourceManager
        package = self.base / "user-package"
        make_package(package)
        database = Path(os.environ["BOOKMARK_RESEARCH_DATA_DIR"]) / "index.sqlite3"
        with BookmarkIndex(database) as index:
            SourceManager(index).sync(package, "user-source", mode="live")
        before = database.read_bytes()
        document = read_json(package, TEMP)
        document["items"][0]["children"][0]["note"] = "not-yet-synchronized"
        write_json(package, TEMP, document)
        result = install._runtime_check(self.source)
        self.assertIn("source_history", result["mcp_tools"])
        self.assertFalse(result["database_created"])
        self.assertEqual(database.read_bytes(), before)
        with BookmarkIndex(database) as index:
            self.assertEqual(index.search("user-source", targets=["not-yet-synchronized"])["total"], 0)

    def test_onboarding_languages_preserve_identical_settings_and_commands(self):
        path = self.base / "user settings.json"
        original = '{"search":{"providers":["tavily"]},"archive":{"enabled":false}}'
        path.write_text(original)
        guides = []
        for language, expected in (("en", "Next steps:"), ("zh", "下一步：")):
            guide = install._getting_started(self.source, language=language)
            output = io.StringIO()
            with mock.patch.object(install.sys, "stderr", output):
                install._print_getting_started(guide)
            self.assertIn(expected, output.getvalue())
            self.assertIn(guide["first_prompt"], output.getvalue())
            self.assertIn("tavily", output.getvalue())
            self.assertEqual(guide["language"], language)
            self.assertEqual(path.read_text(), original)
            guides.append(guide)
        self.assertEqual(guides[0]["configuration"], guides[1]["configuration"])
        self.assertEqual(guides[0]["settings_command"], guides[1]["settings_command"])
        self.assertIn("installation.en.md", guides[0]["guide_url"])
        self.assertFalse((self.base / "user data").exists())

    def test_onboarding_keeps_unreadable_settings_and_does_not_present_defaults(self):
        settings_path = self.base / "user settings.json"
        for original in ('{bad-json', '{"api_key":"environment-secret-marker"}'):
            with self.subTest(original=original):
                settings_path.write_text(original)
                guide = install._getting_started(self.source)
                self.assertIsNotNone(guide["configuration_error"])
                self.assertIsNone(guide["configuration"])
                self.assertEqual(guide["configuration_summary"], [])
                self.assertEqual(settings_path.read_text(), original)
                self.assertNotIn("environment-secret-marker", json.dumps(guide))
                self.assertFalse((self.base / "user data").exists())

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

    def test_standalone_verify_rejects_missing_or_symlinked_host_assets(self):
        for invalid_kind in ("missing", "symlink"):
            for ordinal, relative in enumerate(("hosts/codex/delegate.md", "hosts/codex/prepare.py", "hosts/shared/research-call.py")):
                with self.subTest(invalid_kind=invalid_kind, relative=relative):
                    cached = self.base / (invalid_kind + "-verify-cache-" + str(ordinal))
                    shutil.copytree(self.source, cached)
                    asset = cached / relative
                    asset.unlink()
                    if invalid_kind == "symlink":
                        asset.symlink_to(self.source / relative)
                    cli = ScriptedCli([(["plugin", "list"], {"installed": [self.registration]})])
                    with self.assertRaises(ValueError) as caught:
                        install.verify(cli, cached)
                    self.assertIn(relative, str(caught.exception))
                    self.assertEqual(cli.steps, [])
                    self.assertFalse((self.base / "user data").exists())

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
        self.source = self.base / ('中文 source $(literal) ' + ('quotes' if os.name == 'nt' else '"quotes"')) / "bookmark-research"
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
        setup_flags = ["--non-interactive", "--skip-checks"] if args[0] == "install" else []
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/install.py"), *args, *setup_flags],
                                cwd=self.outside, env=self.environment, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        self.assertNotIn("environment-secret-marker", result.stdout + result.stderr)
        self.last_stderr = result.stderr
        return json.loads(result.stdout if success else result.stderr)

    def test_repeated_install_update_verify_and_conflict_protect_user_data(self):
        probe = self.source / "src/install_probe.py"
        probe.write_text("value = 'before'\n", encoding="utf-8")
        obsolete = self.source / "src/obsolete_probe.py"
        obsolete.write_text("value = 'removed in update'\n", encoding="utf-8")
        first = self.run_installer("install", "--source", str(self.source))
        self.assertTrue(first["verified"])
        self.assertTrue(first["setup"]["completed"])
        self.assertFalse(first["setup"]["readiness"]["network_checked"])
        self.assertIn(first["getting_started"]["first_prompt"], self.last_stderr)
        self.assertEqual(first["getting_started"]["settings_command"][2], str(Path(first["installed_path"]) / "src/cli.py"))
        self.assertFalse(self.data.exists())
        self.assertFalse(self.settings.exists())
        repeated = self.run_installer("install", "--source", str(self.source))
        self.assertEqual(first["installed_path"], repeated["installed_path"])
        self.data.mkdir()
        (self.data / "index.sqlite3").write_bytes(b"existing-user-index")
        self.settings.write_text('{"archive":{"enabled":false}}', encoding="utf-8")
        probe.write_text("value = 'after'\n", encoding="utf-8")
        obsolete.unlink()
        updated_host_assets = {}
        for relative in ("hosts/codex/delegate.md", "hosts/codex/prepare.py", "hosts/shared/research-call.py"):
            asset = self.source / relative
            updated_host_assets[relative] = asset.read_bytes() + b"\n# Updated host asset\n"
            asset.write_bytes(updated_host_assets[relative])
        updated = self.run_installer("update")
        self.assertEqual(Path(updated["installed_path"], "src/install_probe.py").read_text(), "value = 'after'\n")
        self.assertFalse(Path(updated["installed_path"], "src/obsolete_probe.py").exists())
        for relative, expected in updated_host_assets.items():
            self.assertEqual((Path(updated["installed_path"]) / relative).read_bytes(), expected)
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
        self.assertNotIn("getting_started", result)
        self.assertNotIn("安装完成", self.last_stderr)
        self.assertFalse((self.profile / "plugins/cache").exists())
        self.assertFalse((self.profile / "config.toml").exists())
        self.assertFalse(self.run_installer("verify", success=False)["verified"])
        self.assertIn("run install first", self.run_installer("update", success=False)["error"])


if __name__ == "__main__":
    unittest.main()
