"""doctor must catch an unwritable data directory before the first import fails.

An unwritable ``~/.local/share`` used to produce a fully green doctor followed by
a raw SQLite error from the first sync, with nothing naming the environment
variables that fix it.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cli
from settings import Settings


def can_make_read_only(path):
    if os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0:
        return False
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IXUSR)
    except OSError:
        return False
    writable = os.access(str(path), os.W_OK)
    return not writable


class StoragePreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="storage preflight ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def test_writable_directories_report_ready(self):
        settings = Settings(self.base / "config" / "settings.json")
        report = cli._storage_report(type("Args", (), {"db": str(self.base / "data" / "index.sqlite3")})(), settings)
        self.assertTrue(report["ready"])
        self.assertTrue(report["data_directory"]["writable"])
        self.assertTrue(report["config_directory"]["writable"])
        self.assertNotIn("next_step", report)
        # The probe must not leave anything behind.
        self.assertEqual([], list((self.base / "data").glob(".bookmark-research-write-probe-*")))

    def test_read_only_data_directory_is_reported_with_a_next_step(self):
        data = self.base / "data"
        data.mkdir()
        if not can_make_read_only(data):
            self.skipTest("cannot create a read-only directory in this environment")
        self.addCleanup(os.chmod, str(data), 0o755)
        settings = Settings(self.base / "config" / "settings.json")
        report = cli._storage_report(type("Args", (), {"db": str(data / "index.sqlite3")})(), settings)
        self.assertFalse(report["ready"])
        self.assertFalse(report["data_directory"]["writable"])
        self.assertIn("BOOKMARK_RESEARCH_DATA_DIR", report["next_step"])

    def test_read_only_config_directory_is_reported(self):
        config = self.base / "config"
        config.mkdir()
        if not can_make_read_only(config):
            self.skipTest("cannot create a read-only directory in this environment")
        self.addCleanup(os.chmod, str(config), 0o755)
        settings = Settings(config / "settings.json")
        report = cli._storage_report(type("Args", (), {"db": str(self.base / "data" / "index.sqlite3")})(), settings)
        self.assertFalse(report["ready"])
        self.assertFalse(report["config_directory"]["writable"])

    def test_read_only_existing_database_is_reported(self):
        data = self.base / "data"
        data.mkdir()
        database = data / "index.sqlite3"
        cli.sqlite3.connect(str(database)).close()
        if not can_make_read_only(database):
            self.skipTest("cannot create a read-only file in this environment")
        self.addCleanup(os.chmod, str(database), 0o644)
        settings = Settings(self.base / "config" / "settings.json")
        report = cli._storage_report(type("Args", (), {"db": str(database)})(), settings)
        self.assertFalse(report["ready"])
        self.assertFalse(report["database_writable"])
        self.assertIn("read-only", report["next_step"])

    def test_doctor_uses_the_storage_report(self):
        environment = {"BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "data"),
                       "BOOKMARK_RESEARCH_CONFIG": str(self.base / "config" / "settings.json")}
        original = {key: os.environ.get(key) for key in environment}
        os.environ.update(environment)
        try:
            import io
            from contextlib import redirect_stdout
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = cli.main(["doctor"])
            self.assertEqual(0, code)
            payload = json.loads(stream.getvalue())
            self.assertTrue(payload["storage"]["ready"])
            self.assertFalse(payload["database_created"])
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
