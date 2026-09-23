"""Persistent host installation, native state, source pins, and failure recovery."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import export_bundle
import host_install


ROOT = Path(__file__).resolve().parents[1]
CLAUDE = shutil.which("claude")

FAKE_CLIENT = r'''
import json, os, shutil, sys
from pathlib import Path
host = Path(sys.argv[0]).name
args = sys.argv[1:]
base = Path(os.environ['HOST_TEST_STATE'])
log = base / 'calls.jsonl'
with log.open('a') as stream:
    stream.write(json.dumps([host, *args]) + '\n')
def read(path, fallback):
    return json.loads(path.read_text()) if path.exists() else fallback
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
if host == 'claude':
    state_path = base / 'claude-state.json'
    state = read(state_path, {'marketplaces': [], 'plugins': []})
    if args[:3] == ['plugin', 'marketplace', 'list']:
        print(json.dumps(state['marketplaces']))
    elif args[:2] == ['plugin', 'list']:
        print(json.dumps(state['plugins']))
    elif args[:3] == ['plugin', 'marketplace', 'add']:
        state['marketplaces'] = [{'name': 'bookmark-research', 'source': 'directory', 'path': args[3]}]
    elif args[:2] in (['plugin', 'install'], ['plugin', 'update']):
        root = Path(state['marketplaces'][0]['path'])
        version = read(root / '.claude-plugin/plugin.json', {})['version']
        cache = base / 'claude-cache' / version
        shutil.copytree(root, cache, dirs_exist_ok=True)
        state['plugins'] = [{'id': 'bookmark-research@bookmark-research', 'version': version,
                             'scope': args[args.index('--scope') + 1], 'enabled': True, 'installPath': str(cache)}]
    elif args[:2] == ['plugin', 'validate']:
        sys.exit(0)
    elif args[:3] != ['plugin', 'marketplace', 'update']:
        sys.exit('unexpected Claude command: ' + str(args))
    if args[:2] != ['plugin', 'list'] and args[:3] != ['plugin', 'marketplace', 'list']:
        write(state_path, state)
elif host == 'pi':
    if args[0] != 'install':
        sys.exit('unexpected Pi command: ' + str(args))
    path = Path.cwd() / '.pi/settings.json' if '-l' in args else Path(os.environ['PI_CODING_AGENT_DIR']) / 'settings.json'
    settings = read(path, {'other': 'preserved'})
    packages = settings.setdefault('packages', [])
    if args[1] not in packages:
        packages.append(args[1])
    write(path, settings)
elif host == 'dsh':
    profile = args[args.index('--profile') + 1]
    root = Path(os.environ['DSH_HOME']) / 'profiles' / profile
    if args[0] == 'plugin' and args[3] == 'add':
        settings = read(root / 'package.json', {'other': 'preserved'})
        settings.setdefault('dependencies', {})['bookmark-research'] = 'link:' + args[4]
        settings.setdefault('dsh', {}).setdefault('profile', {}).setdefault('bundles', [])[:] = ['bookmark-research']
        write(root / 'package.json', settings)
        link = root / 'node_modules/bookmark-research'
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to(args[4], target_is_directory=True)
    elif '--dump-config' in args:
        print((root / 'node_modules/bookmark-research/bundle.patch.yml').read_text())
    else:
        sys.exit('unexpected DSH command: ' + str(args))
else:
    sys.exit('unexpected host')
if os.environ.get('HOST_TEST_FAIL') == host and ('install' in args or 'update' in args or 'add' in args):
    sys.exit('injected failure after native mutation')
'''


class HostInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-host-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / '源码 with spaces $(literal)'
        self.source.mkdir()
        for directory in (*export_bundle.SHARED_ROOTS, "hosts", ".codex-plugin"):
            shutil.copytree(ROOT / directory, self.source / directory)
        for relative in (*export_bundle.SHARED_DOCUMENTS, "LICENSE"):
            (self.source / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, self.source / relative)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for host in ("claude", "pi", "dsh"):
            path = self.bin / host
            path.write_text("#!" + sys.executable + "\n" + FAKE_CLIENT)
            path.chmod(0o755)
        # DSH delegates to pnpm; the fake client never runs it, but the installer requires it.
        (self.bin / "pnpm").write_text("#!/bin/sh\n")
        (self.bin / "pnpm").chmod(0o755)
        self.home = self.base / "persistent installs"
        self.project = self.base / "项目"
        self.project.mkdir()
        environment = mock.patch.dict(os.environ, {
            "HOST_TEST_STATE": str(self.base), "CLAUDE_CONFIG_DIR": str(self.base / "claude-config"),
            "PI_CODING_AGENT_DIR": str(self.base / "pi-config"), "DSH_HOME": str(self.base / "dsh-config"),
            "BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "personal-data"),
            "BOOKMARK_RESEARCH_CONFIG": str(self.base / "personal-settings.json"),
            "PYTHONDONTWRITEBYTECODE": "1", "EXA_API_KEY": "must-not-appear-in-install-receipts",
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
        })
        environment.start()
        self.addCleanup(environment.stop)

    def manage(self, host, action="install", **kwargs):
        options = {"install_dir": self.home, "binary": str(self.bin / host), "timeout": 15}
        if host == "dsh":
            options["profile"] = "web"
        if action == "install":
            options["source"] = self.source
        options.update(kwargs)
        return host_install.manage_host(action, host, **options)

    def calls(self):
        path = self.base / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_each_host_installs_repeats_updates_and_verifies_without_codex(self):
        (self.bin / "python3").symlink_to(sys.executable)
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}):
            self.assertIsNone(shutil.which("codex"))
            for host in ("claude", "pi", "dsh"):
                with self.subTest(host=host):
                    first = self.manage(host)
                    self.assertTrue(first["verified"])
                    self.assertTrue(self.manage(host)["verified"])
                    self.assertFalse(self.manage(host)["changed"])
                    marker = self.source / "src/installer_marker.py"
                    marker.write_text("value = " + repr(host) + "\n")
                    updated = self.manage(host, "update")
                    self.assertTrue(updated["changed"])
                    self.assertEqual((Path(updated["installed_path"]) / "src/installer_marker.py").read_text(), marker.read_text())
                    self.assertTrue(self.manage(host, "verify")["verified"])
                    self.assertFalse(updated["runtime"]["host_session_checked"])
                    receipt = json.loads(Path(updated["receipt_path"]).read_text())
                    self.assertEqual(receipt["state"], "verified")
                    self.assertNotIn("must-not-appear-in-install-receipts", json.dumps(receipt))
        self.assertFalse((self.base / "personal-data").exists())
        self.assertFalse((self.base / "personal-settings.json").exists())
        self.assertFalse(any("codex" in row[0] for row in self.calls()))

    def test_claude_content_version_changes_with_code_not_repeated_installs(self):
        first = self.manage("claude")
        repeated = self.manage("claude")
        self.assertEqual(first["version"], repeated["version"])
        (self.source / "src/marker.py").write_text("marker = True\n")
        updated = self.manage("claude", "update")
        self.assertNotEqual(first["version"], updated["version"])
        self.assertEqual(first["release_version"], updated["release_version"])

    def test_dry_run_does_not_register_or_create_persistent_state(self):
        for host in ("claude", "pi", "dsh"):
            plan = self.manage(host, dry_run=True)
            self.assertTrue(plan["dry_run"])
            self.assertNotIn("verified", plan)
        self.assertFalse(self.home.exists())
        self.assertFalse((self.base / "pi-config").exists())
        self.assertFalse((self.base / "dsh-config").exists())
        self.assertFalse((self.base / "claude-state.json").exists())

    def test_project_scope_uses_explicit_project_and_preserves_other_settings(self):
        settings_path = self.project / ".pi/settings.json"
        settings_path.parent.mkdir()
        settings_path.write_text('{"other":"untouched","packages":[]}')
        result = self.manage("pi", scope="project", project=self.project)
        settings = json.loads(settings_path.read_text())
        self.assertEqual(settings["other"], "untouched")
        self.assertEqual(settings["packages"], [result["bundle_path"]])
        self.assertTrue(self.manage("pi", "verify", scope="project", project=self.project)["verified"])
        self.assertFalse((self.base / "pi-config/settings.json").exists())
        with self.assertRaisesRegex(ValueError, "--project"):
            self.manage("pi", scope="project")

    def test_failed_update_restores_old_package_and_can_resume(self):
        first = self.manage("claude")
        old_files = host_install._files(Path(first["bundle_path"]))
        (self.source / "src/new_content.py").write_text("changed = True\n")
        with mock.patch.dict(os.environ, {"HOST_TEST_FAIL": "claude"}):
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                self.manage("claude", "update")
        self.assertEqual(host_install._files(Path(first["bundle_path"])), old_files)
        self.assertEqual(json.loads(Path(first["receipt_path"]).read_text())["state"], "needs_verification")
        self.assertTrue(self.manage("claude", "update")["verified"])

    def test_failed_first_install_keeps_registered_paths_for_recovery(self):
        with mock.patch.dict(os.environ, {"HOST_TEST_FAIL": "pi"}):
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                self.manage("pi")
        settings = json.loads((self.base / "pi-config/settings.json").read_text())
        self.assertTrue(Path(settings["packages"][0]).is_dir())
        self.assertTrue(self.manage("pi")["verified"])

    def test_missing_or_changed_source_cannot_overwrite_existing_install(self):
        first = self.manage("pi")
        with self.assertRaisesRegex(ValueError, "retains its source"):
            self.manage("pi", source=ROOT)
        installed = Path(first["bundle_path"]) / "src/cli.py"
        installed.write_text("user edit\n")
        with self.assertRaisesRegex(RuntimeError, "differs"):
            self.manage("pi", "update")
        self.assertEqual(installed.read_text(), "user edit\n")

    def test_native_source_conflicts_stop_before_installation(self):
        other = self.base / "foreign-package"
        other.mkdir()
        (other / "package.json").write_text('{"name":"bookmark-research"}')
        settings = self.base / "pi-config/settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"packages": [str(other)]}))
        with self.assertRaisesRegex(ValueError, "another path"):
            self.manage("pi")
        self.assertFalse(self.calls())
        self.assertEqual(json.loads(settings.read_text())["packages"], [str(other)])

    def test_verification_survives_removal_of_original_checkout(self):
        self.manage("pi")
        shutil.rmtree(self.source)
        self.assertTrue(self.manage("pi", "verify")["verified"])

    def test_dsh_profile_is_required_and_does_not_accept_scope(self):
        with self.assertRaisesRegex(ValueError, "--profile"):
            self.manage("dsh", profile=None)
        with self.assertRaisesRegex(ValueError, "--scope"):
            self.manage("dsh", scope="user")

    def test_git_ref_is_retained_across_reinstall_and_update(self):
        environment = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(self.base / "gitconfig"))
        def git(*args):
            return subprocess.run(["git", "-C", str(self.source), *args], env=environment,
                                  capture_output=True, text=True, check=True).stdout.strip()
        git("init", "--quiet", "--initial-branch=main")
        git("config", "user.name", "Installer Test")
        git("config", "user.email", "test@example.invalid")
        git("add", ".")
        git("commit", "--quiet", "-m", "First")
        git("tag", "v1")
        repository = "https://github.com/example/Bookmark-Research.git"
        git("config", "--file", environment["GIT_CONFIG_GLOBAL"], "url." + self.source.as_uri() + ".insteadOf", repository)
        with mock.patch.dict(os.environ, environment):
            first = self.manage("pi", source=repository, ref="v1")
            (self.source / "src/later.py").write_text("later = True\n")
            git("add", ".")
            git("commit", "--quiet", "-m", "Later")
            updated = self.manage("pi", "update")
            self.assertEqual(first["revision"], updated["revision"])
            self.assertFalse((Path(updated["bundle_path"]) / "src/later.py").exists())
            self.assertEqual(self.manage("pi", source=repository)["source"]["ref"], "v1")
            with self.assertRaisesRegex(ValueError, "retains its source"):
                self.manage("pi", source=repository, ref="main")


class DshPrerequisiteTests(unittest.TestCase):
    setUp = HostInstallerTests.setUp
    manage = HostInstallerTests.manage
    calls = HostInstallerTests.calls

    def test_missing_pnpm_fails_before_creating_a_profile(self):
        (self.bin / "pnpm").unlink()
        with mock.patch("shutil.which", lambda name, *a, **k: None if name == "pnpm" else str(self.bin / name)):
            with self.assertRaisesRegex(ValueError, "pnpm"):
                self.manage("dsh", profile="web")
        self.assertFalse(self.calls())
        self.assertFalse((self.base / "dsh-config").exists())


class MultiHostInstallerTests(unittest.TestCase):
    setUp = HostInstallerTests.setUp
    calls = HostInstallerTests.calls

    def main(self, *arguments):
        import install
        output, errors = io.StringIO(), io.StringIO()
        setup = mock.Mock(return_value={"completed": True, "exit_code": 0})
        with mock.patch.object(install, "_run_setup", setup), \
                mock.patch.object(install, "_print_getting_started"), \
                mock.patch.object(sys, "stdout", output), mock.patch.object(sys, "stderr", errors):
            code = install.main(["install", "--non-interactive", "--skip-checks", "--source", str(self.source),
                                 "--install-dir", str(self.home), "--timeout", "30",
                                 "--claude", str(self.bin / "claude"), "--pi", str(self.bin / "pi"),
                                 "--dsh", str(self.bin / "dsh"), *arguments])
        return code, output.getvalue(), errors.getvalue(), setup

    def test_repeated_and_comma_hosts_install_each_and_run_setup_once(self):
        for hosts in (["--host", "claude", "--host", "dsh,claude"], ["--host", "claude,dsh"]):
            with self.subTest(hosts=hosts):
                code, output, errors, setup = self.main(*hosts, "--profile", "web")
                self.assertEqual(code, 0, errors)
                result = json.loads(output)
                self.assertEqual([row["host"] for row in result["results"]], ["claude", "dsh"])
                self.assertTrue(all(row["verified"] for row in result["results"]))
                self.assertTrue(result["setup"]["completed"])
                setup.assert_called_once()
                self.assertEqual(setup.call_args.args[2], "claude")
                self.assertEqual(Path(setup.call_args.args[1]), Path(result["results"][0]["installed_path"]))
                for row in result["results"]:
                    self.assertEqual(row["getting_started"]["host"], row["host"])
                    self.assertEqual(row["getting_started"]["setup_command"][4],
                                     "claude_code" if row["host"] == "claude" else row["host"])

    def test_single_host_keeps_the_historical_result_shape(self):
        code, output, errors, setup = self.main("--host", "pi")
        self.assertEqual(code, 0, errors)
        result = json.loads(output)
        self.assertNotIn("results", result)
        self.assertEqual(result["host"], "pi")
        self.assertTrue(result["verified"])
        self.assertTrue(result["setup"]["completed"])
        self.assertEqual(result["getting_started"]["host"], "pi")
        setup.assert_called_once()

    def test_mismatched_host_options_are_rejected_before_installation(self):
        for arguments, expected in ((["--host", "pi,dsh", "--profile", "web", "--scope", "local"], "local"),
                                    (["--host", "claude,pi", "--profile", "web"], "--profile"),
                                    (["--host", "codex,dsh", "--profile", "web", "--scope", "user"], "--scope"),
                                    (["--host", "claude,nope"], "--host")):
            with self.subTest(arguments=arguments):
                code, output, errors, setup = self.main(*arguments)
                self.assertEqual(code, 1)
                self.assertIn(expected, json.loads(errors)["error"])
                setup.assert_not_called()
        self.assertFalse(self.calls())

    def test_one_failing_host_does_not_stop_the_next(self):
        with mock.patch.dict(os.environ, {"HOST_TEST_FAIL": "claude"}):
            code, output, errors, setup = self.main("--host", "claude", "--host", "pi")
        self.assertEqual(code, 1)
        result = json.loads(output)
        self.assertIn("injected failure", result["results"][0]["error"])
        self.assertEqual(result["results"][0]["host"], "claude")
        self.assertTrue(result["results"][1]["verified"])
        setup.assert_called_once()
        self.assertEqual(setup.call_args.args[2], "pi")

    def test_multi_host_dry_run_plans_each_host(self):
        code, output, errors, setup = self.main("--host", "pi,dsh", "--profile", "web", "--dry-run")
        self.assertEqual(code, 0, errors)
        result = json.loads(output)
        self.assertEqual([row["host"] for row in result["results"]], ["pi", "dsh"])
        self.assertTrue(all(row["dry_run"] for row in result["results"]))
        self.assertNotIn("setup", result)
        setup.assert_not_called()
        self.assertFalse(self.home.exists())


@unittest.skipUnless(CLAUDE, "Claude Code unavailable; native installation check skipped")
class NativeClaudeInstallationTests(unittest.TestCase):
    setUp = HostInstallerTests.setUp

    def test_native_claude_install_repeat_update_and_cache(self):
        options = {"host": "claude", "binary": CLAUDE, "install_dir": self.home, "timeout": 30}
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}):
            first = host_install.manage_host("install", source=self.source, **options)
            self.assertTrue(first["verified"])
            self.assertTrue(host_install.manage_host("install", source=self.source, **options)["verified"])
            (self.source / "src/native_marker.py").write_text("native_update = True\n")
            updated = host_install.manage_host("update", **options)
            self.assertNotEqual(first["version"], updated["version"])
            self.assertTrue((Path(updated["installed_path"]) / "src/native_marker.py").exists())
            self.assertTrue(host_install.manage_host("verify", **options)["verified"])


@unittest.skipUnless(os.environ.get("BOOKMARK_NATIVE_HOST_BIN"), "Set BOOKMARK_NATIVE_HOST_BIN for native Pi/DSH checks")
class NativePackageInstallationTests(unittest.TestCase):
    setUp = HostInstallerTests.setUp

    def test_native_pi_and_dsh_install_repeat_update_verify(self):
        native_bin = Path(os.environ["BOOKMARK_NATIVE_HOST_BIN"])
        environment = {"PATH": str(native_bin) + os.pathsep + os.environ["PATH"],
                       "npm_config_store_dir": str(self.base / "pnpm-store"),
                       "XDG_CACHE_HOME": str(self.base / "cache"),
                       "PI_TELEMETRY_DISABLED": "1", "DO_NOT_TRACK": "1"}
        with mock.patch.dict(os.environ, environment):
            for host in ("pi", "dsh"):
                with self.subTest(host=host):
                    options = {"host": host, "binary": str(native_bin / host), "timeout": 60,
                               "install_dir": self.home}
                    if host == "dsh":
                        options["profile"] = "bookmark-native-test"
                    first = host_install.manage_host("install", source=self.source, **options)
                    self.assertTrue(first["verified"])
                    self.assertFalse(host_install.manage_host("install", source=self.source, **options)["changed"])
                    marker = self.source / "src/native_package_marker.py"
                    marker.write_text("native_host = " + repr(host) + "\n")
                    updated = host_install.manage_host("update", **options)
                    self.assertEqual((Path(updated["installed_path"]) / marker.relative_to(self.source)).read_text(), marker.read_text())
                    self.assertTrue(host_install.manage_host("verify", **options)["verified"])


if __name__ == "__main__":
    unittest.main()
