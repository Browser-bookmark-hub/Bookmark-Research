"""The `bookmark-research` command entry: dispatch, status and the Node wrapper."""

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import launcher
import tui

NODE = shutil.which("node")


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-launcher-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        environment = mock.patch.dict(os.environ, {
            "BOOKMARK_RESEARCH_INSTALL_DIR": str(self.base / "installs"),
            "BOOKMARK_RESEARCH_CONFIG": str(self.base / "settings.json"),
            "BOOKMARK_RESEARCH_CREDENTIALS": str(self.base / "credentials.json"),
            "BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "data"),
            "EXA_API_KEY": "secret-value-never-printed", "PATH": str(self.base / "empty-bin")})
        environment.start()
        self.addCleanup(environment.stop)

    def receipt(self, host, **target):
        folder = self.base / "installs" / (host + "-key")
        folder.mkdir(parents=True)
        (folder / "receipt.json").write_text(json.dumps({"target": {"host": host, **target},
                                                         "version": "0.4.0", "state": "verified"}))

    def run_main(self, *arguments):
        output = io.StringIO()
        with mock.patch.object(sys, "stdout", output):
            code = launcher.main(list(arguments))
        return code, output.getvalue()

    def test_status_reads_receipts_and_hides_secret_values(self):
        self.receipt("dsh", profile="web")
        code, output = self.run_main("status")
        self.assertEqual(code, 0)
        value = json.loads(output)
        self.assertEqual(value["hosts"][0]["host"], "dsh")
        self.assertEqual(value["hosts"][0]["profile"], "web")
        self.assertEqual(value["credentials"]["EXA_API_KEY"], "environment")
        self.assertNotIn("secret-value-never-printed", output)

    def test_no_arguments_without_terminal_prints_status(self):
        with mock.patch("onboarding.Console.open") as opened:
            opened.return_value.__enter__.return_value = None
            code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("hosts", json.loads(output))

    def test_hosts_become_repeated_host_flags(self):
        import install
        with mock.patch.object(install, "main", return_value=0) as main:
            self.assertEqual(launcher.main(["--lang", "en", "install", "claude,dsh", "pi", "--profile", "web"]), 0)
        main.assert_called_once_with(["install", "--lang", "en", "--host", "claude", "--host", "dsh",
                                      "--host", "pi", "--profile", "web"])

    def test_update_without_hosts_covers_each_installed_target(self):
        import install
        self.receipt("claude", scope="project", project="/work")
        self.receipt("dsh", profile="web")
        with mock.patch.object(install, "main", side_effect=[0, 1]) as main:
            self.assertEqual(launcher.main(["--lang", "en", "update"]), 1)
        self.assertEqual([call.args[0] for call in main.call_args_list], [
            ["update", "--lang", "en", "--host", "claude", "--scope", "project", "--project", "/work"],
            ["update", "--lang", "en", "--host", "dsh", "--profile", "web"]])

    def test_update_with_nothing_installed_fails_clearly(self):
        errors = io.StringIO()
        with mock.patch.object(sys, "stderr", errors):
            self.assertEqual(launcher.main(["update"]), 1)
        self.assertIn("Nothing is installed", errors.getvalue())

    def test_help_unknown_command_and_language(self):
        self.assertIn("install [HOST...]", self.run_main("--help")[1])
        with mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertEqual(launcher.main(["bogus"]), 2)
            self.assertEqual(launcher.main(["--lang", "fr", "status"]), 2)

    @unittest.skipUnless(NODE, "Node.js unavailable")
    def test_node_wrapper_finds_python_and_forwards_exit_codes(self):
        node = NODE
        environment = dict(os.environ, BOOKMARK_RESEARCH_PYTHON=sys.executable)
        script = str(ROOT / "bin/bookmark-research.js")
        status = subprocess.run([node, script, "status"], env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("hosts", json.loads(status.stdout))
        self.assertEqual(subprocess.run([node, script, "bogus"], env=environment, capture_output=True,
                                        timeout=60).returncode, 2)
        missing = dict(environment, BOOKMARK_RESEARCH_PYTHON=str(self.base / "no-python"), PATH=str(self.base))
        failed = subprocess.run([node, script, "status"], env=missing, capture_output=True, text=True, timeout=60)
        self.assertEqual(failed.returncode, 1)
        self.assertIn("Python 3.9+", failed.stderr)


class WindowsKeyTests(unittest.TestCase):
    def test_msvcrt_scan_codes_map_to_navigation(self):
        keys = iter(["\xe0", "P", " ", "\x00", "H", "\r"])
        fake = mock.Mock(getwch=lambda: next(keys), kbhit=lambda: True)
        prompter = tui.Prompter(io.StringIO(), io.StringIO(), rich=True)
        options = [tui.Option("a", "A"), tui.Option("b", "B")]
        with mock.patch.object(tui, "termios", None), mock.patch.object(tui, "msvcrt", fake), \
                mock.patch.object(tui, "_isatty", return_value=True), mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertEqual(prompter.multiselect("Q", None, options), ["b"])

    def test_windows_console_names_and_lock(self):
        import onboarding
        source = Path(onboarding.__file__).read_text(encoding="utf-8")
        self.assertIn('"CONIN$", "CONOUT$"', source)
        self.assertIn("msvcrt.locking", (ROOT / "scripts/host_install.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
