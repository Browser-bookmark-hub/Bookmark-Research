"""Persistent configuration behavior, CLI parity, and package path boundaries."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from settings import Settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-settings-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.environment = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.base / "config"),
            "BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "data")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.settings = Settings(self.base / "preferences/settings.json")

    def test_default_view_is_read_only_and_paths_follow_runtime(self):
        result = self.settings.describe()
        self.assertFalse(result["config_exists"])
        self.assertTrue(result["settings"]["archive"]["enabled"])
        self.assertEqual(result["settings"]["archive"]["directory"], str(self.base / "data/knowledge"))
        self.assertFalse(self.settings.path.parent.exists())
        self.assertFalse((self.base / "data").exists())

    def test_partial_updates_preserve_other_preferences_and_reload(self):
        self.settings.update({"search": {"providers": ["exa"]}, "archive": {"enabled": False}})
        second = Settings(self.settings.path)
        second.update({"fetch": {"max_characters": 25000}})
        result = self.settings.load()
        self.assertEqual(result["search"], {"providers": ["exa"], "limit_per_target": 5})
        self.assertFalse(result["archive"]["enabled"])
        self.assertEqual(result["fetch"]["max_characters"], 25000)
        stored = json.loads(self.settings.path.read_text())
        self.assertNotIn("directory", stored["archive"])
        with patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "new-data")}):
            self.assertEqual(self.settings.load()["archive"]["directory"], str(self.base / "new-data/knowledge"))

    def test_concurrent_processes_preserve_independent_preference_updates(self):
        script = r"""
import json, os, sys, time
from pathlib import Path
from settings import Settings
config, ready, release, phase, patch = sys.argv[1:]
if phase == 'replace':
    original = Path.replace
    def replace(source, destination):
        Path(ready).touch()
        while not Path(release).exists():
            time.sleep(0.01)
        return original(source, destination)
    Path.replace = replace
else:
    original = Settings._read
    def read(self):
        value = original(self)
        Path(ready).touch()
        return value
    Settings._read = read
Settings(config).update(json.loads(patch))
"""
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        release = self.base / "release"
        processes = []
        try:
            for number, (phase, changes) in enumerate((
                    ("replace", {"fetch": {"provider": "parallel"}}),
                    ("read", {"archive": {"enabled": False}}))):
                ready = self.base / ("ready-" + str(number))
                process = subprocess.Popen([sys.executable, "-B", "-c", script, str(self.settings.path),
                    str(ready), str(release), phase, json.dumps(changes)],
                    env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                processes.append(process)
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not ready.exists() and process.poll() is not None:
                    self.fail("Worker exited before overlap: " + "".join(process.communicate()))
                self.assertTrue(ready.exists(), "Worker did not reach the scheduled overlap")
            release.touch()
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stdout + stderr)
        finally:
            release.touch()
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
        self.assertEqual(self.settings.load()["fetch"]["provider"], "parallel")
        self.assertFalse(self.settings.load()["archive"]["enabled"])

    def test_unknown_fields_bad_types_and_credentials_fail_without_writes(self):
        invalid = [{"api_key": "do-not-store"}, {"archive": {"enabled": "false"}},
                   {"search": {"providers": ["tavily"]}}, {"search": {"providers": ["exa", "exa"]}},
                   {"fetch": {"max_characters": True}}, {"fetch": {"max_characters": 100001}},
                   {"timeout_seconds": 0}, {"schema_version": 2}, {"archive": {"directory": "relative/path"}},
                   {"wiki": {"enabled": True}}, {"search": []}]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.settings.update(changes)
        self.assertFalse(self.settings.path.exists())

    def test_canvas_plugin_and_symlink_destinations_are_rejected(self):
        package = self.base / "canvas"
        package.mkdir()
        (package / "entry.canvas").write_text('{"nodes":[],"edges":[]}')
        plugin = Path(__file__).resolve().parents[1]
        alias = self.base / "alias"
        alias.symlink_to(package, target_is_directory=True)
        for directory in (package / "knowledge", alias / "knowledge", plugin / "knowledge"):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                self.settings.update({"archive": {"directory": str(directory)}})
            self.assertFalse(directory.exists())
        with self.assertRaises(ValueError):
            Settings(package / "settings.json").update({"archive": {"enabled": False}})
        self.assertFalse((package / "settings.json").exists())

    def test_environment_config_selection_and_explicit_override(self):
        with patch.dict(os.environ, {"BOOKMARK_RESEARCH_CONFIG": str(self.base / "env.json")}):
            self.assertEqual(Settings().path, self.base / "env.json")
            self.assertEqual(Settings(self.base / "explicit.json").path, self.base / "explicit.json")

    def test_empty_or_relative_xdg_paths_use_home_defaults(self):
        user_home = self.base / "user-home"
        for value in ("", "relative-directory", "~/.configured"):
            environment = {"XDG_CONFIG_HOME": value, "XDG_DATA_HOME": value,
                           "BOOKMARK_RESEARCH_CONFIG": "", "BOOKMARK_RESEARCH_DATA_DIR": ""}
            with self.subTest(value=value), patch.dict(os.environ, environment), patch.object(Path, "home", return_value=user_home):
                self.assertEqual(Settings().path, user_home / ".config/bookmark-research/settings.json")
                self.assertEqual(Settings.data_directory(), user_home / ".local/share/bookmark-research")
        absolute = self.base / "xdg"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(absolute), "XDG_DATA_HOME": str(absolute),
                                     "BOOKMARK_RESEARCH_CONFIG": "", "BOOKMARK_RESEARCH_DATA_DIR": ""}):
            self.assertEqual(Settings().path, absolute / "bookmark-research/settings.json")
            self.assertEqual(Settings.data_directory(), absolute / "bookmark-research")

    def test_invalid_existing_config_is_not_silently_replaced(self):
        self.settings.path.parent.mkdir()
        for original in ('[]', '{"timeout_seconds":30,"timeout_seconds":10}', '{invalid'):
            self.settings.path.write_text(original)
            with self.subTest(original=original), self.assertRaises(ValueError):
                self.settings.update({"archive": {"enabled": False}})
            self.assertEqual(self.settings.path.read_text(), original)

    def test_cli_set_and_show_share_the_persistent_format(self):
        cli = Path(__file__).resolve().parents[1] / "src/cli.py"
        prefix = [sys.executable, str(cli), "--config", str(self.settings.path), "config"]
        changed = subprocess.run(prefix + ["set", "--search-provider", "exa", "--archive", "false"],
                                 check=True, text=True, capture_output=True)
        shown = subprocess.run(prefix + ["show"], check=True, text=True, capture_output=True)
        self.assertEqual(json.loads(changed.stdout), json.loads(shown.stdout))
        self.assertEqual(self.settings.load()["search"]["providers"], ["exa"])
        self.assertFalse(self.settings.load()["archive"]["enabled"])


if __name__ == "__main__":
    unittest.main()
