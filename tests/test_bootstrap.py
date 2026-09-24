"""Exercise the piped installer against a local Git remote and isolated profiles."""

import json
import os
import select
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import export_bundle


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
GIT = shutil.which("git")
CODEX = shutil.which("codex")
REPOSITORY = "https://github.com/Browser-bookmark-hub/Bookmark-Research.git"


@unittest.skipUnless(BASH and GIT, "Bash and Git are required for bootstrap tests")
@unittest.skipIf(os.name == "nt", "install.sh is the macOS/Linux entry; Windows uses the npm command")
class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-bootstrap-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.remote = self.base / "remote source"
        export_bundle.export_bundle("codex", self.remote)
        (self.remote / "scripts").mkdir()
        for name in ("install.py", "export_bundle.py", "host_assets.py", "host_install.py", "host_clients.py"):
            shutil.copyfile(ROOT / "scripts" / name, self.remote / "scripts" / name)
        shutil.copytree(ROOT / "hosts", self.remote / "hosts", dirs_exist_ok=True)
        (self.remote / "src/bootstrap_probe.py").write_text("value = 'before'\n")
        self.outside = self.base / ('中文 cwd $(literal) ' + ('quotes' if os.name == 'nt' else '"quotes"'))
        self.outside.mkdir()
        self.downloads = self.base / "temporary downloads"
        self.downloads.mkdir()
        self.profile = self.base / "codex profile"
        self.profile.mkdir()
        self.data = self.base / "user data"
        self.data.mkdir()
        (self.data / "index.sqlite3").write_bytes(b"existing-user-data")
        self.settings = self.base / "settings.json"
        self.settings.write_text('{"archive":{"enabled":false}}')
        self.calls = self.base / "codex-calls.jsonl"
        self.cli = self.base / 'codex with spaces $(literal)'
        self.cli.write_text("#!" + sys.executable + "\n" + '''
import json, os, sys
from pathlib import Path
with Path(os.environ["BOOTSTRAP_TEST_CALLS"]).open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("BOOTSTRAP_TEST_CLI_FAIL"):
    sys.exit("native-cli-failure")
if sys.argv[1:] == ["plugin", "marketplace", "list", "--json"]:
    print(json.dumps({"marketplaces": []}))
elif sys.argv[1:] == ["plugin", "list", "--json"]:
    print(json.dumps({"installed": json.loads(os.environ.get("BOOTSTRAP_TEST_INSTALLED", "[]"))}))
else:
    sys.exit("unexpected native mutation")
''')
        self.cli.chmod(0o755)
        self.environment = dict(os.environ, GIT_CONFIG_GLOBAL=str(self.base / "gitconfig"),
                                GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
                                CODEX_HOME=str(self.profile), TMPDIR=str(self.downloads),
                                BOOKMARK_RESEARCH_DATA_DIR=str(self.data),
                                BOOKMARK_RESEARCH_CONFIG=str(self.settings),
                                BOOTSTRAP_TEST_CALLS=str(self.calls), PYTHONDONTWRITEBYTECODE="1", LC_ALL="C")
        for name in ("GIT_CONFIG_COUNT", "PYTHONPATH", "PYTHONHOME", "BOOKMARK_RESEARCH_INSTALL_LANG"):
            self.environment.pop(name, None)
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Bootstrap Test")
        self.git("config", "user.email", "bootstrap@example.invalid")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Initial test source")
        self.git("tag", "v0.2.0")
        self.git("config", "--file", self.environment["GIT_CONFIG_GLOBAL"],
                 "url." + self.remote.as_uri() + ".insteadOf", REPOSITORY)

    def git(self, *arguments):
        return subprocess.run([GIT, "-C", str(self.remote), *arguments],
                              env=self.environment, text=True, capture_output=True,
                              check=True, timeout=20).stdout.strip()

    def run_bootstrap(self, *arguments, success=True):
        existing_downloads = set(self.downloads.iterdir())
        result = subprocess.run([BASH, "-s", "--", *arguments, "--codex", str(self.cli)],
                                input=(ROOT / "install.sh").read_text(), cwd=self.outside,
                                env=self.environment, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        self.assertEqual(set(self.downloads.iterdir()), existing_downloads, "temporary checkout was not cleaned")
        self.assertEqual((self.data / "index.sqlite3").read_bytes(), b"existing-user-data")
        self.assertEqual(self.settings.read_text(), '{"archive":{"enabled":false}}')
        return result

    def test_piped_dry_run_uses_remote_source_and_preserves_argument_boundaries(self):
        result = json.loads(self.run_bootstrap("--dry-run").stdout)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["source"], {"sourceType": "git", "source": REPOSITORY, "ref": None})
        self.assertEqual(result["commands"][0], [str(self.cli), "plugin", "marketplace", "add", REPOSITORY, "--json"])
        self.assertFalse((self.profile / "config.toml").exists())
        self.assertEqual(len(self.calls.read_text().splitlines()), 2)

    def test_language_selection_reaches_python_and_help_stays_offline(self):
        self.environment.update(LC_ALL="", LC_MESSAGES="zh_CN.UTF-8", LANG="en_US.UTF-8")
        self.assertIn("安装器语言", self.run_bootstrap("--help").stdout)
        self.assertIn("Installer language", self.run_bootstrap("--help", "--lang", "en").stdout)
        self.assertFalse(self.calls.exists())
        self.assertEqual(json.loads(self.run_bootstrap("--dry-run").stdout)["language"], "zh")
        self.assertEqual(json.loads(self.run_bootstrap("--dry-run", "--lang=en").stdout)["language"], "en")
        self.environment["LC_ALL"] = "C"
        self.assertIn("Installer language", self.run_bootstrap("--lang", "auto", "--help").stdout)

    def test_language_option_does_not_break_a_historical_installer(self):
        (self.remote / "scripts/install.py").write_text('''
import argparse, json
parser = argparse.ArgumentParser()
parser.add_argument("action")
parser.add_argument("--codex")
parser.add_argument("--timeout")
parser.add_argument("--source")
parser.add_argument("--ref")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()
print(json.dumps({"historical_installer": True, "ref": args.ref}))
''')
        self.git("add", "scripts/install.py")
        self.git("commit", "--quiet", "-m", "Installer without language flags")
        self.git("tag", "historical-installer")
        result = self.run_bootstrap("install", "--ref", "historical-installer", "--lang", "zh", "--dry-run")
        self.assertTrue(json.loads(result.stdout)["historical_installer"])

    def test_first_install_accepts_tag_and_commit_without_a_github_release(self):
        for ref in ("v0.2.0", self.git("rev-parse", "HEAD")):
            with self.subTest(ref=ref):
                plan = json.loads(self.run_bootstrap("install", "--ref", ref, "--dry-run").stdout)
                self.assertEqual(plan["source"]["ref"], ref)
                self.assertEqual(plan["commands"][0][-3:], ["--ref", ref, "--json"])

    def test_fetch_failure_stops_before_native_mutations_and_cleans_up(self):
        failed = self.run_bootstrap("--ref", "missing-tag", success=False)
        self.assertIn("Could not fetch", failed.stderr)
        self.assertEqual([json.loads(line) for line in self.calls.read_text().splitlines()],
                         [["plugin", "list", "--json"]])
        self.assertEqual(failed.stdout, "")

    def test_native_failure_propagates_and_cleans_up(self):
        self.environment["BOOTSTRAP_TEST_CLI_FAIL"] = "1"
        failed = self.run_bootstrap("--dry-run", success=False)
        self.assertIn("native-cli-failure", failed.stderr)
        self.assertFalse((self.profile / "config.toml").exists())

    def test_existing_personal_installation_prevents_a_duplicate(self):
        self.environment["BOOTSTRAP_TEST_INSTALLED"] = json.dumps([
            {"pluginId": "bookmark-research@personal", "installed": True, "enabled": True}])
        failed = self.run_bootstrap(success=False)
        self.assertIn("Already installed as bookmark-research@personal", failed.stderr)
        self.assertNotIn("fetching installer", failed.stderr)
        self.assertFalse((self.profile / "config.toml").exists())

    def test_missing_codex_has_an_actionable_error_before_download(self):
        self.cli = self.base / "missing codex"
        failed = self.run_bootstrap(success=False)
        self.assertIn("Codex CLI was not found", failed.stderr)
        self.assertNotIn("fetching installer", failed.stderr)

    @unittest.skipUnless(os.name == "posix", "A controlling terminal is required")
    def test_piped_installer_guides_pi_through_tty_without_codex(self):
        import fcntl
        import pty
        import termios
        from test_host_install import FAKE_CLIENT
        cli = self.base / "pi"
        cli.write_text("#!" + sys.executable + "\n" + FAKE_CLIENT)
        cli.chmod(0o755)
        environment = dict(self.environment, HOST_TEST_STATE=str(self.base),
                           PI_CODING_AGENT_DIR=str(self.base / "pi-profile"))
        arguments = [BASH, "-s", "--", "--interactive", "--skip-checks", "--pi", str(cli),
                     "--codex", str(self.base / "missing-codex"), "--claude", str(self.base / "missing-claude"),
                     "--dsh", str(self.base / "missing-dsh"), "--install-dir", str(self.base / "managed")]
        master, slave = pty.openpty()
        def attach_terminal():
            os.setsid()
            fcntl.ioctl(1, termios.TIOCSCTTY, 0)
        process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=slave, stderr=slave,
                                   env=environment, cwd=self.outside, preexec_fn=attach_terminal)
        os.close(slave)
        output = bytearray()
        try:
            process.stdin.write((ROOT / "install.sh").read_bytes())
            process.stdin.close()
            os.write(master, b"3\n" + b"\n" * 20)
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                elif process.poll() is not None:
                    break
            self.assertEqual(process.wait(timeout=2), 0, output.decode(errors="replace"))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            os.close(master)
        packages = json.loads((self.base / "pi-profile/settings.json").read_text())["packages"]
        self.assertEqual(len(packages), 1)
        self.assertTrue((Path(packages[0]) / "src/readiness.py").is_file())
        self.assertFalse(self.calls.exists(), "The Codex executable must never be called for Pi")
        self.assertFalse(list(self.downloads.glob("bookmark-research-install.*")))
        self.assertFalse(json.loads(self.settings.read_text())["archive"]["enabled"])

    def test_help_and_invalid_options_do_not_download_or_call_codex(self):
        self.assertIn("GitHub Release pages and ZIP assets are not used", self.run_bootstrap("--help").stdout)
        for args in (("--unknown",), ("update", "--ref", "main"), ("verify", "--dry-run"),
                     ("--ref", "--upload-pack=bad"), ("--timeout", "0"), ("--timeout", "301"),
                     ("--lang", "fr"), ("--lang=",), ("--lang",)):
            with self.subTest(args=args):
                failed = self.run_bootstrap(*args, success=False)
                self.assertNotIn("fetching installer", failed.stderr)
        self.assertFalse(self.calls.exists())

    @unittest.skipUnless(CODEX, "Codex CLI unavailable; native Git installation test skipped")
    def test_native_install_repeat_update_and_tag_pin_survive_temporary_cleanup(self):
        self.cli = Path(CODEX)
        installed = self.run_bootstrap("--skip-checks")
        first = json.loads(installed.stdout)
        self.assertTrue(first["verified"])
        self.assertEqual(first["source"]["sourceType"], "git")
        self.assertIn(first["getting_started"]["first_prompt"], installed.stderr)
        self.assertFalse(first["getting_started"]["configuration"]["settings"]["archive"]["enabled"])
        checked = subprocess.run(first["getting_started"]["settings_command"], cwd=self.outside,
                                 env=self.environment, capture_output=True, text=True, check=True, timeout=15)
        self.assertEqual(json.loads(checked.stdout), first["getting_started"]["configuration"])
        repeated = json.loads(self.run_bootstrap("--skip-checks").stdout)
        self.assertEqual(first["installed_path"], repeated["installed_path"])
        self.assertTrue(json.loads(self.run_bootstrap("verify").stdout)["verified"])
        configuration = (self.profile / "config.toml").read_text()
        self.assertIn(REPOSITORY, configuration)
        self.assertNotIn(str(self.downloads), configuration)

        pinned_profile = self.base / "pinned profile"
        pinned_profile.mkdir()
        self.environment["CODEX_HOME"] = str(pinned_profile)
        pinned = json.loads(self.run_bootstrap("install", "--ref", "v0.2.0", "--skip-checks").stdout)
        (self.remote / "src/bootstrap_probe.py").write_text("value = 'after'\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Update default branch")
        updated_pin = json.loads(self.run_bootstrap("update").stdout)
        self.assertEqual(updated_pin["installed_path"], pinned["installed_path"])
        self.assertEqual(Path(pinned["installed_path"], "src/bootstrap_probe.py").read_text(), "value = 'before'\n")
        self.environment["CODEX_HOME"] = str(self.profile)
        updated = json.loads(self.run_bootstrap("update").stdout)
        self.assertTrue(updated["verified"])
        self.assertEqual(Path(updated["installed_path"], "src/bootstrap_probe.py").read_text(), "value = 'after'\n")


if __name__ == "__main__":
    unittest.main()
