"""Codex client discovery across PATH, candidate version managers, and explicit paths."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import codex_client


class CodexClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-codex-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.execute_flags = {}
        if sys.platform == "win32":
            def posix_which(binary, path=None):
                for directory in (path or "").split(os.pathsep):
                    candidate = Path(directory) / binary
                    if candidate.is_file() and self.execute_flags.get(str(candidate), False):
                        return str(candidate)
                return None
            for patcher in (
                mock.patch.object(codex_client.shutil, "which", side_effect=posix_which),
                mock.patch.object(codex_client.os, "access", side_effect=lambda path, mode:
                                  self.execute_flags.get(str(path), False)),
            ):
                patcher.start()
                self.addCleanup(patcher.stop)

    def tool(self, name, directory=None, executable=True):
        path = (directory or self.bin) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755 if executable else 0o644)
        self.execute_flags[str(path)] = executable
        return path

    def environment(self, **values):
        environment = {"PATH": str(self.bin), "HOME": str(self.base / "home"), "PATHEXT": ".COM;.EXE;.BAT;.CMD"}
        environment.update(values)
        return environment

    def test_explicit_valid_path(self):
        cli = self.tool("my-codex")
        found = codex_client.resolve(str(cli), self.environment(), "darwin")
        self.assertEqual(found, {"binary": str(cli), "source": "explicit", "usable": True})

    def test_explicit_missing_path(self):
        missing = str(self.base / "nonexistent" / "codex")
        found = codex_client.resolve(missing, self.environment(), "darwin")
        self.assertEqual(found, {"binary": missing, "source": "explicit", "usable": False})

    def test_path_cli_preferred(self):
        cli = self.tool("codex")
        found = codex_client.resolve("codex", self.environment(), "darwin")
        self.assertEqual(found, {"binary": str(cli), "source": "path", "usable": True})

    def test_discovered_from_nvm_when_not_on_path(self):
        env = self.environment()
        home = Path(env["HOME"])
        nvm_cli = self.tool("codex", home / ".nvm" / "versions" / "node" / "v24.21.0" / "bin")
        found = codex_client.resolve("codex", env, "darwin")
        self.assertEqual(found, {"binary": str(nvm_cli), "source": "discovered", "usable": True})

    def test_discovered_from_daemon_releases_when_not_on_path(self):
        env = self.environment()
        home = Path(env["HOME"])
        daemon_cli = self.tool("codex", home / ".codex" / "packages" / "app-server-daemon" / "releases" / "0.167.0" / "bin")
        found = codex_client.resolve("codex", env, "darwin")
        self.assertEqual(found, {"binary": str(daemon_cli), "source": "discovered", "usable": True})

    def test_discovered_from_local_bin_when_not_on_path(self):
        env = self.environment()
        home = Path(env["HOME"])
        local_cli = self.tool("codex", home / ".local" / "bin")
        found = codex_client.resolve("codex", env, "darwin")
        self.assertEqual(found, {"binary": str(local_cli), "source": "discovered", "usable": True})

    def test_discovered_from_windows_appdata(self):
        appdata = self.base / "AppData" / "Roaming"
        win_cli = self.tool("codex.cmd", appdata / "npm")
        env = {"PATH": "", "USERPROFILE": str(self.base / "home"), "APPDATA": str(appdata), "PATHEXT": ".CMD;.EXE"}
        found = codex_client.resolve("codex", env, "win32")
        self.assertEqual(found, {"binary": str(win_cli), "source": "discovered", "usable": True})

    def test_no_carrier_reports_missing(self):
        found = codex_client.resolve("codex", self.environment(), "darwin")
        self.assertEqual(found, {"binary": None, "source": "missing", "usable": False})

    def test_windows_extensionless_full_path_retries_pathext(self):
        cli = self.tool("codex.cmd")
        env = self.environment(PATHEXT=".COM;.EXE;.BAT;.CMD")
        self.assertEqual(codex_client.executable(str(cli)[:-4], env, "win32"), str(cli))
        self.assertIsNone(codex_client.executable(str(cli)[:-4], env, "darwin"))

    def test_non_executable_posix_candidate_is_not_offered(self):
        path = self.tool("codex", executable=False)
        self.assertIsNone(codex_client.executable(str(path), self.environment(), "darwin"))

