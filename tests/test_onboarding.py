"""Guided setup, credential boundaries, cache invalidation and honest checks."""

import argparse
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import warnings
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import dsh_client
from cli import main
from credentials import Credentials
from onboarding import Console, Onboarding
from readiness import Readiness
from service_http import ServiceError
from settings import Settings
from web_search import SearchProviders


class SetupFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-setup-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        environment = mock.patch.dict(os.environ, {
            **dict.fromkeys(Credentials.NAMES, ""),
            "BOOKMARK_RESEARCH_CONFIG": str(self.base / "config/settings.json"),
            "BOOKMARK_RESEARCH_CREDENTIALS": str(self.base / "config/credentials.json"),
            "BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "data"),
            # Profile discovery must not read this machine's real Harness home.
            "DSH_HOME": str(self.base / "dsh-home")})
        environment.start()
        self.addCleanup(environment.stop)
        self.settings = Settings()
        self.credentials = Credentials(self.settings)


class CredentialTests(SetupFixture):
    def test_private_storage_environment_precedence_and_shared_adapters(self):
        secret = "test-key-never-printed"
        self.credentials.save("EXA_API_KEY", secret)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.credentials.path.stat().st_mode), 0o600)
        self.assertEqual(self.credentials.get("EXA_API_KEY"), secret)
        self.assertNotIn(secret, json.dumps(self.credentials.describe()))
        self.assertFalse(self.settings.path.exists())
        with mock.patch("web_search.McpHttpClient") as client:
            SearchProviders(settings=self.settings)._client("exa")
            self.assertEqual(client.call_args.kwargs["headers"]["x-api-key"], secret)
        with mock.patch.dict(os.environ, {"EXA_API_KEY": "environment-key"}):
            self.assertEqual(self.credentials.get("EXA_API_KEY"), "environment-key")
        self.assertEqual(self.credentials.get("EXA_API_KEY"), secret)

    @unittest.skipIf(os.name == "nt", "chmod modes and unprivileged symlinks are POSIX-only")
    def test_rejects_unsafe_files_and_never_echoes_bad_secret(self):
        self.credentials.save("OPENAI_API_KEY", "original")
        for name, value in (("arbitrary", "secret"), ("OPENAI_API_KEY", "secret\nheader")):
            with self.assertRaises(ValueError) as caught:
                self.credentials.save(name, value)
            self.assertNotIn(value, str(caught.exception))
        original = self.credentials.path.read_bytes()
        self.credentials.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "chmod 600"):
            self.credentials.get("OPENAI_API_KEY")
        self.credentials.path.chmod(0o600)
        alternate = self.base / "other-credentials.json"
        self.credentials.path.rename(alternate)
        self.credentials.path.symlink_to(alternate)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.credentials.save("OPENAI_API_KEY", "changed")
        self.assertEqual(alternate.read_bytes(), original)

    def test_settings_cannot_receive_credentials(self):
        with self.assertRaises(ValueError):
            self.settings.update({"OPENAI_API_KEY": "do-not-persist"})
        self.assertFalse(self.settings.path.exists())


class ReadinessTests(SetupFixture):
    def setUp(self):
        super().setUp()
        self.web = SearchProviders(settings=self.settings)
        self.web.probe = mock.Mock(return_value={"providers": [{"status": "ok", "provider": "exa",
            "capabilities": {purpose: {"status": "supported", "execution_verified": False} for purpose in ("search", "fetch")}}]})
        self.transport = mock.Mock()
        self.engine = Readiness(self.settings, self.web, self.transport)

    def test_offline_and_manual_checks_do_not_create_cache_or_contact_services(self):
        result = self.engine.check(providers=["exa"], offline=True)
        self.assertFalse(result["network_checked"])
        self.assertTrue(result["offline_ready"])
        self.assertFalse(self.engine.cache_path.exists())
        self.settings.update({"readiness": {"mode": "manual"}})
        self.engine.check(providers=["exa"])
        self.web.probe.assert_not_called()
        self.transport.request.assert_not_called()
        self.engine.check(providers=["exa"], refresh=True)
        self.web.probe.assert_called_once()

    def test_cache_reused_across_instances_and_invalidated_by_credentials_settings_and_time(self):
        with mock.patch("readiness.time.time", return_value=1000):
            first = self.engine.check(providers=["exa"])
            self.assertEqual(first["checks"][0]["status"], "catalog_reachable")
            self.assertFalse(first["checks"][0]["authentication_verified"])
            second = Readiness(self.settings, self.web, self.transport).check(providers=["exa"])
            self.assertTrue(second["checks"][0]["cached"])
            self.assertFalse(second["network_checked"])
            self.assertEqual(self.web.probe.call_count, 1)
            self.credentials.save("EXA_API_KEY", "secret-rotation-one")
            self.engine.check(providers=["exa"])
            self.assertEqual(self.web.probe.call_count, 2)
            self.credentials.save("EXA_API_KEY", "secret-rotation-two")
            result = self.engine.check(providers=["exa"])
            self.assertEqual(self.web.probe.call_count, 3)
            self.assertNotIn("secret-rotation", json.dumps(result) + self.engine.cache_path.read_text())
            self.assertNotIn("signature", json.dumps(result))
            self.settings.update({"readiness": {"timeout_seconds": 5}})
            self.engine.check(providers=["exa"])
            self.assertEqual(self.web.probe.call_count, 4)
        with mock.patch("readiness.time.time", return_value=2000):
            self.engine.check(providers=["exa"])
            self.assertEqual(self.web.probe.call_count, 5)

    def test_always_refreshes_and_failure_cache_is_short_and_sanitized(self):
        self.settings.update({"readiness": {"mode": "always"}})
        for _ in range(2):
            self.engine.check(providers=["exa"])
        self.assertEqual(self.web.probe.call_count, 2)
        self.settings.update({"readiness": {"mode": "cached"}})
        self.web.probe.side_effect = RuntimeError("provider reflected secret-do-not-show")
        with mock.patch("readiness.time.time", return_value=1000):
            failed = self.engine.check(providers=["exa"])
        check = failed["checks"][0]
        self.assertEqual(check["status"], "failed")
        self.assertEqual(check["expires_at"] - check["checked_at"], 60)
        self.assertNotIn("secret-do-not-show", json.dumps(failed) + self.engine.cache_path.read_text())
        with mock.patch("readiness.time.time", return_value=1061):
            self.engine.check(providers=["exa"])
        self.assertEqual(self.web.probe.call_count, 4)

    def test_openai_probe_is_a_model_get_not_a_research_job(self):
        self.settings.update({"professional_research": {"enabled": True, "provider": "openai"}})
        self.credentials.save("OPENAI_API_KEY", "test-openai-key")
        self.transport.request.return_value = {"id": "o4-mini-deep-research", "object": "model"}
        result = self.engine.check(providers=["exa"])
        check = next(row for row in result["checks"] if row["id"] == "service:openai")
        self.assertTrue(check["authentication_verified"])
        self.assertFalse(check["execution_verified"])
        self.assertEqual(result["research_jobs_started"], 0)
        self.transport.request.assert_called_once_with("openai", "GET", "/v1/models/o4-mini-deep-research")
        self.transport.request.side_effect = ServiceError("authentication_required", "unsafe provider text", http_status=401)
        failed = self.engine.check(providers=["exa"], refresh=True)
        check = next(row for row in failed["checks"] if row["id"] == "service:openai")
        self.assertFalse(check["authentication_verified"])
        self.assertEqual(check["http_status"], 401)
        self.assertNotIn("unsafe provider text", json.dumps(failed))

    def test_parallel_task_mcp_is_distinct_from_task_api_authorization(self):
        self.settings.update({"professional_research": {"enabled": True, "provider": "parallel"}})
        self.credentials.save("PARALLEL_API_KEY", "test-parallel-key")
        required = self.web.registry["providers"]["parallel"]["native_research"]["required_tools"]
        with mock.patch("readiness.McpHttpClient") as client:
            client.return_value.list_tools.return_value = [{"name": name} for name in required]
            result = self.engine.check(providers=["exa"])
            self.assertEqual(client.call_args.args[0], "https://task-mcp.parallel.ai/mcp")
            client.return_value.call_tool.assert_not_called()
        check = next(row for row in result["checks"] if row["id"] == "service:parallel")
        self.assertTrue(check["task_mcp_authentication_verified"])
        self.assertFalse(check["authentication_verified"])
        self.transport.request.assert_not_called()

    def test_optional_live_test_checks_real_results_without_archiving_samples(self):
        self.credentials.save("EXA_API_KEY", "sample-test-key")
        self.web.search = mock.Mock(return_value={"batches": [{"status": "ok", "results": [{"url": "https://example.com/"}]}]})
        self.web.fetch = mock.Mock(return_value={"status": "ok", "successful_url_count": 1})
        result = self.engine.check(providers=["exa"], test_retrieval=True)
        check = result["checks"][0]
        self.assertTrue(check["execution_verified"])
        self.assertTrue(check["authentication_verified"])
        self.assertEqual(check["operations"]["search"]["status"], "verified")
        self.assertFalse(self.web.fetch.call_args.kwargs["archive"])
        self.assertEqual(self.web.search.call_args.kwargs["providers"], ["exa"])
        self.web.probe.assert_not_called()
        self.assertNotIn("example.com", self.engine.cache_path.read_text())

    def test_missing_optional_keys_and_host_tools_do_not_claim_logged_in(self):
        self.settings.update({"professional_research": {"enabled": True, "provider": "openai"}})
        result = self.engine.check(providers=["jina"], offline=True, host="pi", observed_tools=[])
        self.assertEqual(result["checks"][0]["operations"]["search"]["missing"], ["JINA_API_KEY"])
        self.assertEqual(result["checks"][1]["status"], "missing_credentials")
        self.assertTrue(result["offline_ready"])
        self.assertTrue(all(row["status"] == "not_observed" for row in result["host_integrations"]["native_research_mcps"]))
        observed = self.engine.check(providers=["exa"], offline=True, host="codex", observed_tools=["mcp__exa__agent_run"])
        exa = observed["host_integrations"]["native_research_mcps"][0]
        self.assertEqual(exa["status"], "observed")
        self.assertFalse(exa["authentication_verified"])
        self.web.probe.assert_not_called()
        self.transport.request.assert_not_called()

    def test_host_remediation_uses_each_hosts_supported_connection_format(self):
        for host in ("codex", "claude_code", "pi", "dsh"):
            with self.subTest(host=host):
                result = self.engine.check(providers=["exa"], offline=True, host=host, observed_tools=[])
                for row in result["host_integrations"]["native_research_mcps"]:
                    setup = row["setup"]
                    self.assertFalse(row["authentication_verified"])
                    if host in ("codex", "claude_code"):
                        self.assertIn(row["endpoint"], setup["add_command"])
                        self.assertEqual(setup["add_command"][0], "claude" if host == "claude_code" else host)
                    elif host == "dsh":
                        self.assertEqual(setup["mcp_config"]["transport"], "streamable-http")
                        self.assertEqual(setup["mcp_config"]["url"], row["endpoint"])
                    else:
                        self.assertNotIn("add_command", setup)
        self.web.probe.assert_not_called()
        self.transport.request.assert_not_called()


class OnboardingTests(SetupFixture):
    def test_key_entry_stops_when_the_terminal_cannot_hide_input(self):
        import getpass
        console = Console(io.StringIO("5\n"), io.StringIO())
        def unavailable(*args, **kwargs):
            warnings.warn("Password input may be echoed", getpass.GetPassWarning)
            self.fail("Must stop before reading an echoed secret")
        with mock.patch("getpass.getpass", side_effect=unavailable), self.assertRaisesRegex(ValueError, "Cannot hide"):
            Onboarding(self.settings, console)._keys()
        self.assertFalse(self.credentials.path.exists())

    def test_enter_preserves_enabled_services_without_a_default_provider(self):
        self.settings.update({"professional_research": {"enabled": True, "provider": None},
                              "fetch": {"provider": "jina", "providers": ["jina"]}})
        console = Console(io.StringIO("\n" * 30), io.StringIO())
        Onboarding(self.settings, console).run(checks=False)
        current = self.settings.load()
        self.assertTrue(current["professional_research"]["enabled"])
        self.assertIsNone(current["professional_research"]["provider"])
        # The single services question keeps the saved search list and derives reading from it.
        self.assertEqual(current["search"]["providers"], ["exa", "parallel"])
        self.assertEqual(current["fetch"]["provider"], "exa")
        self.assertEqual(current["fetch"]["providers"], ["exa", "parallel"])

    def test_invalid_setup_input_does_not_change_settings(self):
        for preferences in ([], {}, {"OPENAI_API_KEY": "secret"}):
            with self.subTest(preferences=preferences), self.assertRaises(ValueError):
                Onboarding(self.settings).run(preferences=preferences, checks=False)
        with self.assertRaises(ValueError):
            Onboarding(self.settings).run(preferences={"research": {"depth": "quick"}}, checks=False, test_retrieval=True)
        self.assertFalse(self.settings.path.exists())

    def test_selected_optional_mcp_guidance_has_a_usable_quoted_command(self):
        output = io.StringIO()
        onboarding = Onboarding(self.settings, Console(io.StringIO("2\n"), output))
        result = Readiness(self.settings).check(providers=["exa"], offline=True, host="codex")
        onboarding._integrations(result)
        self.assertIn("codex mcp add bookmark-exa-research --url 'https://mcp.exa.ai/mcp?tools=agent_run'", output.getvalue())
        self.assertIn("codex mcp login bookmark-exa-research", output.getvalue())
        self.assertFalse(self.settings.path.exists())

    def test_terminal_defaults_preserve_existing_preferences_without_echoing_keys(self):
        self.settings.update({"research": {"depth": "agentic", "response_language": "zh"},
                              "search": {"providers": ["tavily"], "fallback_providers": []},
                              "archive": {"enabled": False}, "readiness": {"mode": "manual"}})
        self.credentials.save("TAVILY_API_KEY", "hidden-key-in-store")
        output = io.StringIO()
        result = Onboarding(self.settings, Console(io.StringIO("\n" * 20), output, "zh")).run(checks=False)
        self.assertEqual(self.settings.load()["search"]["providers"], ["tavily"])
        self.assertEqual(self.settings.load()["research"]["response_language"], "zh")
        self.assertFalse(result["readiness"]["network_checked"])
        self.assertNotIn("hidden-key-in-store", output.getvalue() + json.dumps(result))

    def test_storage_question_sets_archive_and_output_together(self):
        default_output = self.settings.load()["output"]["directory"]
        # Prompts: depth, language, services, storage, professional API.
        defaults = Onboarding(self.settings, Console(io.StringIO("\n" * 5), io.StringIO()))._preferences()
        for section in ("archive", "output", "wiki", "readiness"):
            self.assertNotIn(section, defaults)
        root = self.base / "store"
        output = io.StringIO()
        answers = "\n\n\n2\n" + str(root) + "\n\n"
        chosen = Onboarding(self.settings, Console(io.StringIO(answers), output))._preferences()
        self.assertEqual(chosen["archive"], {"directory": str(root / "knowledge")})
        self.assertEqual(chosen["output"], {"mode": "central", "directory": str(root / "research")})
        self.assertIn(default_output, output.getvalue())
        self.assertIn("new research tasks only", output.getvalue())
        beside = Onboarding(self.settings, Console(io.StringIO("\n\n\n3\n\n"), io.StringIO(), "zh"))._preferences()
        self.assertEqual(beside["output"], {"mode": "beside_input"})
        self.assertNotIn("archive", beside)
        # A saved custom location is reset only when the default folder is chosen.
        self.settings.update({"archive": {"directory": str(root / "knowledge")},
                              "output": {"mode": "beside_input", "directory": str(root / "research")}})
        reset = Onboarding(self.settings, Console(io.StringIO("\n\n\n1\n\n"), io.StringIO()))._preferences()
        defaults = Settings.defaults()
        self.assertEqual(reset["archive"], {"directory": defaults["archive"]["directory"]})
        self.assertEqual(reset["output"], {"mode": "central", "directory": defaults["output"]["directory"]})

    def test_noninteractive_cli_applies_json_preferences_and_returns_missing_steps(self):
        preferences = self.base / "preferences.json"
        preferences.write_text(json.dumps({"professional_research": {"enabled": True, "provider": "openai"},
                                           "readiness": {"mode": "always"}}))
        output = io.StringIO()
        with mock.patch.object(sys, "stdout", output), mock.patch("getpass.getpass") as secret:
            code = main(["setup", "--non-interactive", "--input", str(preferences), "--skip-checks"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["settings"]["settings"]["readiness"]["mode"], "always")
        check = next(row for row in result["readiness"]["checks"] if row["id"] == "service:openai")
        self.assertEqual(check["status"], "missing_credentials")
        self.assertIn("OPENAI_API_KEY", check["next_step"])
        secret.assert_not_called()
        self.assertFalse((self.base / "data/index.sqlite3").exists())

    def test_conflicting_network_options_and_cancel_do_not_write_preferences(self):
        output = io.StringIO()
        with mock.patch.object(sys, "stdout", output):
            code = main(["setup", "--non-interactive", "--skip-checks", "--test-retrieval"])
        self.assertEqual(code, 1)
        self.assertFalse(self.settings.path.exists())
        with self.assertRaises(KeyboardInterrupt):
            Onboarding(self.settings, Console(io.StringIO(""), io.StringIO())).run(checks=False)
        self.assertFalse(self.settings.path.exists())


class InstallTargetTests(SetupFixture):
    def setUp(self):
        super().setUp()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        path = mock.patch.dict(os.environ, {"PATH": str(self.bin)})
        path.start()
        self.addCleanup(path.stop)
        # Host detection must not depend on whether this machine has the app.
        self.discover_desktop()

    def tool(self, *names):
        for name in names:
            name += ".cmd" if os.name == "nt" else ""
            (self.bin / name).write_text("#!/bin/sh\n")
            (self.bin / name).chmod(0o755)

    def discover_desktop(self, *paths):
        """Point DSH Desktop discovery at given CLIs, empty by default."""
        patcher = mock.patch.object(dsh_client, "desktop_candidates", lambda *arguments, **keywords: list(paths))
        patcher.start()
        self.addCleanup(patcher.stop)

    def desktop(self, pnpm=True):
        """A DeepSeek Harness Desktop layout: bundled CLI beside its own pnpm."""
        runtime = self.base / "DeepSeek Harness.app" / "Contents" / "Resources" / "runtime"
        cli = runtime / "cli" / "bin" / ("dsh.cmd" if os.name == "nt" else "dsh")
        cli.parent.mkdir(parents=True)
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
        if pnpm:
            (runtime / "pnpm" / "bin").mkdir(parents=True)
            (runtime / "pnpm" / "bin" / "pnpm.mjs").write_text("// Desktop's own pnpm\n")
        self.discover_desktop(cli)
        return cli

    def profile(self, name, dependency=None, bundles=()):
        """An initialized DSH profile under the fixture's own Harness home."""
        directory = Path(os.environ["DSH_HOME"]) / "profiles" / name
        directory.mkdir(parents=True, exist_ok=True)
        value = {"name": "dsh-profile-" + name}
        if dependency:
            value["dependencies"] = {"bookmark-research": dependency}
        if bundles:
            value["dsh"] = {"profile": {"bundles": list(bundles)}}
        (directory / "package.json").write_text(json.dumps(value))
        return directory

    def args(self, **values):
        base = dict(host=None, scope=None, project=None, profile=None, codex="codex", claude=None, pi=None, dsh=None)
        base.update(values)
        return argparse.Namespace(**base)

    def test_detected_hosts_are_preselected_and_missing_disabled(self):
        self.tool("pi", "codex")
        output = io.StringIO()
        args = self.args()
        targets = Console(io.StringIO("\n\n\n"), output).install_targets(args)
        self.assertEqual([row["host"] for row in targets], ["codex", "pi"])
        self.assertEqual(targets[1]["scope"], "user")
        self.assertIn("CLI not found", output.getvalue())
        self.assertEqual((args.host, args.scope), ("codex", None))
        with self.assertRaises(KeyboardInterrupt):
            Console(io.StringIO("2\n"), io.StringIO()).install_targets(self.args())

    def test_multi_host_with_project_scope_and_profile_validation(self):
        self.tool("claude", "dsh", "pnpm")
        answers = "2,4\n2\n" + str(self.base / "missing") + "\n" + str(self.base) + "\n.bad\nweb\ny\n"
        output = io.StringIO()
        targets = Console(io.StringIO(answers), output).install_targets(self.args())
        self.assertEqual(targets, [{"host": "claude", "scope": "project", "project": str(self.base), "profile": None},
                                   {"host": "dsh", "scope": None, "project": None, "profile": "web"}])
        self.assertIn("existing directory", output.getvalue())
        self.assertIn("do not start with a dot", output.getvalue())

    def test_disabled_host_cannot_be_chosen_and_no_hosts_raises(self):
        self.tool("pi")
        output = io.StringIO()
        targets = Console(io.StringIO("1\n3\n\n\n"), output).install_targets(self.args())
        self.assertEqual([row["host"] for row in targets], ["pi"])
        (self.bin / ("pi.cmd" if os.name == "nt" else "pi")).unlink()
        with self.assertRaisesRegex(ValueError, "--pi"):
            Console(io.StringIO(""), io.StringIO()).install_targets(self.args())

    def test_dsh_without_pnpm_is_disabled_with_install_hint(self):
        self.tool("claude", "dsh")
        output = io.StringIO()
        targets = Console(io.StringIO("4\n\n\n\n"), output).install_targets(self.args())
        self.assertEqual([row["host"] for row in targets], ["claude"])
        self.assertIn("needs pnpm", output.getvalue())

    def test_desktop_cli_is_used_when_path_dsh_has_no_pnpm(self):
        # A generic `dsh` on PATH cannot run `dsh plugin` without pnpm; the
        # Desktop CLI carries its own, so it is selected and recorded for install.
        self.tool("claude", "dsh")
        cli = self.desktop()
        output = io.StringIO()
        args = self.args()
        targets = Console(io.StringIO("\n\n\n\n"), output).install_targets(args)
        self.assertEqual([row["host"] for row in targets], ["claude", "dsh"])
        self.assertEqual(targets[1]["profile"], "desktop")
        self.assertEqual(args.dsh, str(cli))
        self.assertIn(str(cli), output.getvalue())
        self.assertIn("DeepSeek Harness Desktop CLI", output.getvalue())

    def test_desktop_only_installation_is_detected_without_a_path_cli(self):
        self.desktop()
        output = io.StringIO()
        args = self.args()
        targets = Console(io.StringIO("\n\n\n"), output).install_targets(args)
        self.assertEqual([row["host"] for row in targets], ["dsh"])
        self.assertEqual(targets[0]["profile"], "desktop")

    def test_reserved_desktop_profile_requires_the_desktop_cli(self):
        self.tool("dsh", "pnpm")
        output = io.StringIO()
        args = self.args(host=["dsh"])
        targets = Console(io.StringIO("desktop\nweb\n\n"), output).install_targets(args)
        self.assertEqual(targets[0]["profile"], "web")
        self.assertIn("--dsh", output.getvalue())
        self.assertIsNone(args.dsh)

    def test_explicit_desktop_cli_accepts_the_reserved_profile(self):
        cli = self.desktop()
        output = io.StringIO()
        args = self.args(host=["dsh"], dsh=str(cli))
        targets = Console(io.StringIO("\n\n"), output).install_targets(args)
        self.assertEqual(targets[0]["profile"], "desktop")
        self.assertEqual(args.dsh, str(cli))
        self.assertNotIn("--dsh", output.getvalue())

    def test_initialized_profiles_are_listed_with_their_registration(self):
        cli = self.desktop()
        self.profile("desktop", dependency="0.5.0-beta.7", bundles=["@deepseek-ai/dsh-base", "bookmark-research"])
        self.profile("web")
        output = io.StringIO()
        args = self.args(host=["dsh"], dsh=str(cli))
        targets = Console(io.StringIO("2\n\n"), output).install_targets(args)
        self.assertEqual(targets[0]["profile"], "web")
        self.assertIn("0.5.0-beta.7", output.getvalue())
        self.assertIn("no bookmark-research yet", output.getvalue())

    def test_the_desktop_profile_is_the_default_for_the_desktop_cli(self):
        cli = self.desktop()
        self.profile("desktop")
        self.profile("web")
        args = self.args(host=["dsh"], dsh=str(cli))
        targets = Console(io.StringIO("\n\n"), io.StringIO()).install_targets(args)
        self.assertEqual(targets[0]["profile"], "desktop")

    def test_a_generic_cli_is_not_offered_the_reserved_profile(self):
        self.tool("dsh", "pnpm")
        self.profile("desktop")
        self.profile("web")
        output = io.StringIO()
        args = self.args(host=["dsh"])
        targets = Console(io.StringIO("\n\n"), output).install_targets(args)
        self.assertEqual(targets[0]["profile"], "web")
        self.assertNotIn("desktop", output.getvalue().split("Install into which DSH profile?")[-1])

    def test_explicit_host_list_skips_host_prompt(self):
        args = self.args(host=["codex", "pi"], scope="user")
        output = io.StringIO()
        target = Console(io.StringIO("\n"), output).install_target(args)
        self.assertEqual(target["host"], "codex")
        self.assertNotIn("Install into which hosts", output.getvalue())
        self.assertEqual((args.host, args.scope), ("codex", None))

    def test_rich_mode_key_stream(self):
        self.tool("pi")
        console = Console(io.StringIO(" \x1b[B \r\r\r"), io.StringIO(), rich=True)
        self.assertTrue(console.rich)
        self.assertEqual([row["host"] for row in console.install_targets(self.args())], ["pi"])


class RecheckTests(SetupFixture):
    def test_failed_readiness_offers_key_reentry_and_rechecks_once(self):
        failed = {"checks": [{"id": "retrieval:exa", "status": "failed", "next_step": "fix", "docs": "d"}],
                  "host_integrations": {"host": "codex", "native_research_mcps": []}}
        fixed = {"checks": [{"id": "retrieval:exa", "status": "retrieval_verified"}],
                 "host_integrations": {"host": "codex", "native_research_mcps": []}}
        output = io.StringIO()
        # 6 preference/key prompts accept defaults, then re-enter yes, keep EXA preselected, secret, integrations.
        console = Console(io.StringIO("\n" * 6 + "y\n\n\n"), output)
        with mock.patch("onboarding.Readiness") as engine, mock.patch("getpass.getpass", return_value="new-exa-key"):
            engine.return_value.check.side_effect = [failed, fixed]
            result = Onboarding(self.settings, console).run()
        self.assertEqual(engine.return_value.check.call_count, 2)
        self.assertEqual(result["needs_attention"], [])
        self.assertEqual(self.credentials.get("EXA_API_KEY"), "new-exa-key")
        self.assertIn("retrieval:exa: failed", output.getvalue())
        self.assertIn("Re-enter keys", output.getvalue())


if __name__ == "__main__":
    unittest.main()
