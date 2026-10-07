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
            "BOOKMARK_RESEARCH_INSTALL_DIR": str(self.base / "managed"),
            "BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "user data"),
            "BOOKMARK_RESEARCH_CONFIG": str(self.base / "user settings.json"),
            "EXA_API_KEY": "environment-secret-marker", "TAVILY_API_KEY": "environment-secret-marker"})
        environment.start()
        self.addCleanup(environment.stop)
        self.bundle = install._local_home() / "bundle"
        # PinnedInterpreterTests separately covers Windows interpreter selection.
        pin = mock.patch.object(install, "_pin_interpreter", return_value=False)
        pin.start()
        self.addCleanup(pin.stop)

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
            [cli.binary, "plugin", "marketplace", "add", str(self.bundle), "--json"],
            [cli.binary, "plugin", "add", install.SELECTOR, "--json"]])
        self.assertFalse(result.get("verified"))
        self.assertEqual(len(cli.calls), 1)
        self.assertNotIn("environment-secret-marker", json.dumps(result))
        self.assertFalse((self.base / "user data").exists())
        self.assertFalse((self.base / "managed").exists())

    def test_install_checks_the_cached_runtime_and_registered_version(self):
        cli = ScriptedCli([
            (["plugin", "marketplace", "list"], {"marketplaces": []}),
            (["plugin", "marketplace", "add", str(self.bundle)], {"marketplaceName": install.NAME}),
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
                            (["plugin", "marketplace", "add", str(self.bundle)], {"marketplaceName": install.NAME}),
                        ]
                    else:
                        steps = [
                            (["plugin", "marketplace", "list"], {"marketplaces": [self.local_marketplace]}),
                            (["plugin", "list"], {"installed": [self.registration]}),
                            (["plugin", "marketplace", "remove", install.NAME], {}),
                            (["plugin", "marketplace", "add", str(self.bundle)], {"marketplaceName": install.NAME}),
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
            (["plugin", "marketplace", "add", str(self.bundle)], RuntimeError("native install failed")),
        ])
        with self.assertRaisesRegex(RuntimeError, "native install failed"):
            install.manage("install", cli, source=self.source)
        self.assertEqual(len(cli.calls), 2)

    def test_migration_refuses_other_plugins_before_writing_a_bundle(self):
        path = self.source / ".agents/plugins/marketplace.json"
        catalog = json.loads(path.read_text())
        catalog["plugins"].append({"name": "another-plugin"})
        path.write_text(json.dumps(catalog))
        cli = ScriptedCli([(["plugin", "marketplace", "list"], {"marketplaces": [self.local_marketplace]})])
        with self.assertRaisesRegex(ValueError, "containing other plugins"):
            install.manage("install", cli, source=self.source)
        self.assertFalse(self.bundle.exists())
        self.assertEqual(cli.steps, [])

    def test_failed_migration_restores_original_marketplace_through_codex(self):
        cli = ScriptedCli([
            (["plugin", "marketplace", "list"], {"marketplaces": [self.local_marketplace]}),
            (["plugin", "marketplace", "remove", install.NAME], {}),
            (["plugin", "marketplace", "add", str(self.bundle)], RuntimeError("native add failed")),
            (["plugin", "marketplace", "add", str(self.source)], {"marketplaceName": install.NAME}),
        ])
        with self.assertRaisesRegex(RuntimeError, "native add failed"):
            install.manage("install", cli, source=self.source)
        self.assertEqual(cli.steps, [])

    def test_verification_rejects_unexpected_personal_files_in_native_cache(self):
        (self.source / ".claude").mkdir()
        (self.source / ".claude/settings.local.json").write_text('{"synthetic":true}')
        cli = ScriptedCli([
            (["plugin", "marketplace", "list"], {"marketplaces": []}),
            (["plugin", "marketplace", "add", str(self.bundle)], {"marketplaceName": install.NAME}),
            (["plugin", "add", install.SELECTOR], {"pluginId": install.SELECTOR, "installedPath": str(self.source)}),
            (["plugin", "list"], {"installed": [self.registration]}),
        ])
        with self.assertRaisesRegex(RuntimeError, "settings.local.json"):
            install.manage("install", cli, source=self.source)

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
            [cli.binary, "plugin", "add", install.SELECTOR,
             "-c", 'marketplaces.bookmark-research.source_type="local"',
             "-c", "marketplaces.bookmark-research.source=" + json.dumps(str(self.bundle)), "--json"]])
        self.assertEqual(result["origin"], self.git_marketplace["marketplaceSource"])

    def test_first_git_install_records_ref_and_registers_clean_export(self):
        cli = ScriptedCli([(["plugin", "marketplace", "list"], {"marketplaces": []})])
        result = install.manage("install", cli, source="Browser-bookmark-hub/Bookmark-Research", ref="v0.2.0", dry_run=True)
        self.assertEqual(result["commands"][0], [cli.binary, "plugin", "marketplace", "add",
            str(self.bundle), "--json"])
        self.assertEqual(result["origin"]["ref"], "v0.2.0")
        self.assertFalse(self.bundle.exists())
        self.assertFalse(result.get("verified"))

    def test_source_checkout_accepts_its_published_catalog_without_switching_to_npm(self):
        path = self.source / ".agents/plugins/marketplace.json"
        catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(catalog["plugins"][0]["source"], {
            "source": "npm", "package": install.NAME, "version": catalog["plugins"][0]["source"]["version"],
            "registry": "https://registry.npmjs.org"})
        path.write_text(json.dumps(catalog))
        requested = install._source(self.source)
        self.assertEqual(requested["sourceType"], "local")
        # Prepare a new source version before publishing it. The native catalog
        # must remain on an available release until npm publication succeeds.
        manifest_path = self.source / ".codex-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "99.0.0-unpublished"
        manifest_path.write_text(json.dumps(manifest))
        self.assertEqual(install._source(self.source), {
            "sourceType": "local", "source": str(self.source), "version": manifest["version"]})
        for field, value in (("package", "unrelated-package"), ("version", "latest"),
                             ("version", "^1.0.0"), ("version", None),
                             ("registry", "https://example.invalid")):
            modified = json.loads(json.dumps(catalog))
            modified["plugins"][0]["source"][field] = value
            path.write_text(json.dumps(modified))
            with self.assertRaisesRegex(ValueError, "pinned bookmark-research"):
                install._source(self.source)

    def test_native_release_update_keeps_the_catalog_package_instead_of_exporting_source(self):
        catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        (self.source / ".agents/plugins/marketplace.json").write_text(json.dumps(catalog))
        for marketplace in (self.local_marketplace, self.git_marketplace):
            commands = []
            if marketplace is self.git_marketplace:
                commands.append((["plugin", "marketplace", "upgrade", install.NAME], {}))
            cli = ScriptedCli([
                (["plugin", "marketplace", "list"], {"marketplaces": [marketplace]}),
                (["plugin", "list"], {"installed": [self.registration]}),
                *commands,
                (["plugin", "add", install.SELECTOR], {"pluginId": install.SELECTOR, "installedPath": str(self.source)}),
                (["plugin", "list"], {"installed": [self.registration]}),
            ])
            with self.subTest(source=marketplace["marketplaceSource"]), \
                    mock.patch.object(install, "_export_source", side_effect=AssertionError("must use native npm source")):
                result = install.manage("update", cli)
            self.assertTrue(result["verified"])
            self.assertEqual(cli.steps, [])
            self.assertFalse(self.bundle.exists())

    def test_git_upgrade_can_replace_a_legacy_root_catalog_with_a_release_catalog(self):
        catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        path = self.source / ".agents/plugins/marketplace.json"

        class UpgradingCli(ScriptedCli):
            def run(self, arguments):
                result = super().run(arguments)
                if arguments[:3] == ["plugin", "marketplace", "upgrade"]:
                    path.write_text(json.dumps(catalog))
                return result

        cli = UpgradingCli([
            (["plugin", "marketplace", "list"], {"marketplaces": [self.git_marketplace]}),
            (["plugin", "list"], {"installed": [self.registration]}),
            (["plugin", "marketplace", "upgrade", install.NAME], {}),
            (["plugin", "add", install.SELECTOR], {"pluginId": install.SELECTOR, "installedPath": str(self.source)}),
            (["plugin", "list"], {"installed": [self.registration]}),
        ])
        with mock.patch.object(install, "_export_source", side_effect=AssertionError("release needs no source export")):
            result = install.manage("update", cli)
        self.assertEqual(result["commands"][-1], [cli.binary, "plugin", "add", install.SELECTOR, "--json"])
        self.assertTrue(result["verified"])
        self.assertEqual(cli.steps, [])

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


class PinnedInterpreterTests(unittest.TestCase):
    """Windows pins the detected interpreter; simulated with the running Python."""
    setUp = InstallerTests.setUp

    def test_install_registers_a_pinned_copy_and_update_refreshes_it(self):
        home = self.base / "managed"
        bundle = install._local_home() / "bundle"
        with mock.patch.dict(os.environ, {"BOOKMARK_RESEARCH_INSTALL_DIR": str(home)}), \
                mock.patch.object(install, "_pin_interpreter", return_value=True):
            cli = ScriptedCli([
                (["plugin", "marketplace", "list"], {"marketplaces": []}),
                (["plugin", "marketplace", "add", str(bundle)], {"marketplaceName": install.NAME}),
                (["plugin", "add", install.SELECTOR], {"pluginId": install.SELECTOR, "installedPath": str(bundle)}),
                (["plugin", "list"], {"installed": [self.registration]}),
            ])
            result = install.manage("install", cli, source=self.source)
            self.assertTrue(result["verified"])
            self.assertIn("fetch_web", result["runtime"]["mcp_tools"])
            server = export_bundle.read_plugin_manifest(bundle)["mcpServers"][install.NAME]
            self.assertEqual(server["command"], sys.executable)
            self.assertLessEqual({"SystemRoot", "windir"}, set(server["env_vars"]))
            self.assertEqual(export_bundle.read_plugin_manifest(self.source)["mcpServers"][install.NAME]["command"], "python3")
            self.assertEqual(json.loads((bundle.parent / "origin.json").read_text(encoding="utf-8")),
                             {"sourceType": "local", "source": str(self.source)})
            (self.source / "src/pinned_marker.py").write_text("marker = 1\n", encoding="utf-8")
            marketplace = {"name": install.NAME, "root": str(bundle),
                           "marketplaceSource": {"sourceType": "local", "source": str(bundle)}}
            cli = ScriptedCli([
                (["plugin", "marketplace", "list"], {"marketplaces": [marketplace]}),
                (["plugin", "list"], {"installed": [self.registration]}),
                (["plugin", "add", install.SELECTOR], {"pluginId": install.SELECTOR, "installedPath": str(bundle)}),
                (["plugin", "list"], {"installed": [self.registration]}),
            ])
            self.assertTrue(install.manage("update", cli)["verified"])
            self.assertTrue((bundle / "src/pinned_marker.py").is_file())
            self.assertEqual(cli.steps, [])

    def test_runtime_check_rejects_unpinned_commands_other_than_python3(self):
        manifest_path = self.source / ".codex-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for command in ("python", "relative/python3", str(self.base / "missing-python")):
            with self.subTest(command=command):
                manifest["mcpServers"][install.NAME]["command"] = command
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Unexpected native MCP launch configuration"):
                    install._runtime_check(self.source)


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
                                BOOKMARK_RESEARCH_INSTALL_DIR=str(self.base / "managed"),
                                BOOKMARK_RESEARCH_DATA_DIR=str(self.data), BOOKMARK_RESEARCH_CONFIG=str(self.settings),
                                EXA_API_KEY="environment-secret-marker", TAVILY_API_KEY="environment-secret-marker",
                                PYTHONDONTWRITEBYTECODE="1")
        self.environment.pop("PYTHONPATH", None)
        self.environment.pop("PYTHONHOME", None)
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.private_files = (".claude/settings.local.json", ".codex/config.toml", ".pi/settings.json",
                              ".agent/local.txt", ".git/probe", "exports/old/private.txt", "dist/old.zip")
        for relative in self.private_files:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic private file; exclude from installation\n")

    def run_installer(self, *args, success=True):
        setup_flags = ["--non-interactive", "--skip-checks"] if args[0] == "install" else []
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/install.py"), *args, *setup_flags],
                                cwd=self.outside, env=self.environment, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        self.assertNotIn("environment-secret-marker", result.stdout + result.stderr)
        self.last_stderr = result.stderr
        return json.loads(result.stdout if success else result.stderr)

    def prepare_git(self):
        self.repository = "https://example.invalid/bookmark-research.git"
        self.environment.update(GIT_CONFIG_GLOBAL=str(self.base / "gitconfig"),
                                GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
        self.environment.pop("GIT_CONFIG_COUNT", None)
        for args in (("init", "--quiet", "--initial-branch=main"),
                     ("config", "user.name", "Installer Test"),
                     ("config", "user.email", "installer@example.invalid")):
            self.git(*args)
        (self.source / "src/git_probe.py").write_text("value = 'before'\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Initial source")
        self.git("tag", "fixed")
        self.git("config", "--file", self.environment["GIT_CONFIG_GLOBAL"],
                 "url." + self.source.as_uri() + ".insteadOf", self.repository)
        return self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run([shutil.which("git"), "-C", str(self.source), *args],
                              env=self.environment, text=True, capture_output=True,
                              check=True, timeout=20).stdout.strip()

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_git_exports_preserve_branch_tag_commit_and_repeated_install(self):
        commit = self.prepare_git()
        installs = []
        for i, ref in enumerate((None, "main", "fixed", commit)):
            profile = self.base / ("git-profile-" + str(i))
            profile.mkdir()
            self.environment["CODEX_HOME"] = str(profile)
            args = ["--ref", ref] if ref else []
            first = self.run_installer("install", "--source", self.repository, *args)
            self.assertEqual(first["source"]["sourceType"], "local")
            self.assertEqual(first["origin"]["ref"], ref)
            for relative in self.private_files:
                self.assertFalse((Path(first["installed_path"]) / relative).exists(), relative)
            repeated = self.run_installer("install", "--source", self.repository, *args)
            self.assertEqual(first["installed_path"], repeated["installed_path"])
            retained = self.run_installer("install", "--source", self.repository)
            self.assertEqual(retained["origin"]["ref"], ref)
            conflict = self.run_installer("install", "--source", self.repository,
                                          "--ref", "other-branch", success=False)
            self.assertIn("retains its registered ref", conflict["error"])
            installs.append((profile, ref, first))
        (self.source / "src/git_probe.py").write_text("value = 'after'\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Advance branch")
        for profile, ref, first in installs:
            self.environment["CODEX_HOME"] = str(profile)
            updated = self.run_installer("update")
            expected = "after" if ref in (None, "main") else "before"
            self.assertEqual(Path(updated["installed_path"], "src/git_probe.py").read_text(),
                             "value = '" + expected + "'\n")
        # A failed fetch must leave the last working bundle and cache usable.
        moved = self.source.with_name("offline-source")
        self.source.rename(moved)
        try:
            self.assertIn("Could not prepare", self.run_installer("update", success=False)["error"])
            self.assertTrue(self.run_installer("verify")["verified"])
            self.assertEqual(Path(first["source"]["source"], "src/git_probe.py").read_text(), "value = 'before'\n")
        finally:
            moved.rename(self.source)

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_legacy_git_ref_stays_host_owned_while_cache_is_cleaned(self):
        self.prepare_git()
        for ref in ("main", "fixed"):
            profile = self.base / ("legacy-" + ref)
            profile.mkdir()
            self.environment["CODEX_HOME"] = str(profile)
            for args in (("marketplace", "add", self.repository, "--ref", ref),
                         ("add", install.SELECTOR)):
                subprocess.run([shutil.which("codex"), "plugin", *args, "--json"],
                               env=self.environment, capture_output=True, check=True, timeout=30)
            configuration = (profile / "config.toml").read_bytes()
            (self.source / "src/git_probe.py").write_text("value = '" + ref + "'\n")
            self.git("add", ".")
            self.git("commit", "--quiet", "-m", "Advance " + ref)
            updated = self.run_installer("update")
            self.assertEqual((profile / "config.toml").read_bytes(), configuration)
            expected = "main" if ref == "main" else "before"
            self.assertEqual(Path(updated["installed_path"], "src/git_probe.py").read_text(),
                             "value = '" + expected + "'\n")
            for relative in self.private_files:
                self.assertFalse((Path(updated["installed_path"]) / relative).exists(), relative)
            self.assertTrue(self.run_installer("update")["verified"])

    @unittest.skipUnless(os.environ.get("BOOKMARK_RESEARCH_TEST_PUBLISHED_NPM") == "1"
                         and shutil.which("npm") and shutil.which("git"),
                         "Published npm source test is opt-in and requires npm and Git")
    def test_native_git_catalog_installs_published_package_and_stays_clean_on_update(self):
        self.prepare_git()
        self.git("add", "-f", ".claude/settings.local.json")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Track synthetic development file")
        self.environment["npm_config_cache"] = str(self.base / "npm-cache")

        def native(*args):
            completed = subprocess.run([shutil.which("codex"), "plugin", *args, "--json"],
                                       env=self.environment, text=True, capture_output=True, timeout=90)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            return json.loads(completed.stdout)

        native("marketplace", "add", self.repository, "--ref", "main")
        old = native("add", install.SELECTOR)
        self.assertTrue(Path(old["installedPath"], ".claude/settings.local.json").exists())
        # Move the Git catalog to the production npm source. The development
        # file remains tracked, so a root-directory copy would fail this test.
        catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        (self.source / ".agents/plugins/marketplace.json").write_text(json.dumps(catalog))
        self.git("add", ".agents/plugins/marketplace.json")
        self.git("commit", "--quiet", "-m", "Select published package")
        native("marketplace", "upgrade", install.NAME)
        expected_version = catalog["plugins"][0]["source"]["version"]
        for fresh_profile in (False, True):
            if fresh_profile:
                profile = self.base / "fresh native release profile"
                profile.mkdir()
                self.environment["CODEX_HOME"] = str(profile)
                native("marketplace", "add", self.repository, "--ref", "main")
            for _ in range(2):
                installed = native("add", install.SELECTOR)
                self.assertEqual(installed["version"], expected_version)
                cache = Path(installed["installedPath"])
                files = {p.relative_to(cache).as_posix() for p in cache.rglob("*") if p.is_file()}
                hidden = {p for p in files if any(part.startswith(".") for part in Path(p).parts)}
                self.assertEqual(hidden, {".agents/plugins/marketplace.json", ".codex-plugin/plugin.json"})
                self.assertFalse(any(set(Path(p).parts) & {"tests", "exports", "dist", "node_modules"} for p in files))
                native("marketplace", "upgrade", install.NAME)
        # The published package's Python runtime works independently of the
        # catalog checkout. Interpreter pinning is tested by the installer suite.
        doctor = subprocess.run([sys.executable, "-B", str(cache / "src/cli.py"), "doctor"],
                                env=self.environment, text=True, capture_output=True, check=True, timeout=30)
        self.assertTrue(json.loads(doctor.stdout)["fts5"])
        self.assertFalse(self.data.exists())

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
        self.assertEqual(first["origin"]["source"], str(self.source))
        for relative in self.private_files:
            self.assertFalse((Path(first["installed_path"]) / relative).exists(), relative)
            self.assertTrue((self.source / relative).is_file(), relative)
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

    def test_update_migrates_old_source_install_using_native_commands(self):
        for arguments in (["plugin", "marketplace", "add", str(self.source)],
                          ["plugin", "add", install.SELECTOR]):
            result = subprocess.run([shutil.which("codex"), *arguments, "--json"], env=self.environment,
                                    text=True, capture_output=True, check=True, timeout=30)
        cache = Path(json.loads(result.stdout)["installedPath"])
        self.assertTrue((cache / ".claude/settings.local.json").is_file())
        before = {str(p.relative_to(self.source)): p.read_bytes() for p in self.source.rglob("*") if p.is_file()}
        planned = self.run_installer("update", "--dry-run")
        self.assertEqual(planned["commands"][0][1:5], ["plugin", "marketplace", "remove", install.NAME])
        self.assertFalse((self.base / "managed").exists())
        migrated = self.run_installer("update")
        self.assertTrue(migrated["verified"])
        self.assertEqual(migrated["commands"], planned["commands"])
        for relative in self.private_files:
            self.assertFalse((Path(migrated["installed_path"]) / relative).exists(), relative)
        self.assertEqual(before, {str(p.relative_to(self.source)): p.read_bytes()
                                  for p in self.source.rglob("*") if p.is_file()})
        self.assertTrue(self.run_installer("update")["verified"])

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
