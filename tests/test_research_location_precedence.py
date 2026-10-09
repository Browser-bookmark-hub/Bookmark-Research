"""A copied data directory must resolve its own research tasks, not the origin's.

A same-machine clone carries ``research-locations.json`` with absolute paths
from the original installation. Resolution therefore prefers the task folder
that actually exists under the data directory in use, keeps the registry only
as a fallback for tasks created beside their input, and reports the duplicate.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import research_locations
from research import ResearchSessions
from settings import Settings


class ResearchLocationPrecedenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="research clone ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.origin_data = self.base / "data"
        self._patch_data(self.origin_data)
        self.origin = ResearchSessions(settings=Settings(self.base / "origin-settings.json"),
                                       db_path=self.origin_data / "index.sqlite3")
        self.research_id = self.origin.start("Origin task", [{"id": "q1", "question": "What?"}])["research_id"]
        self.origin_path = self.origin_data / "research" / self.research_id
        self.assertTrue((self.origin_path / "state.json").is_file())
        # The clone copies the whole data directory, location registry included.
        self.clone_data = self.base / "clone-data"
        shutil.copytree(self.origin_data, self.clone_data)
        self.clone_path = self.clone_data / "research" / self.research_id

    def _patch_data(self, path):
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(path)})
        environment.start()
        self.addCleanup(environment.stop)

    def _sessions(self, data_directory, directory=None):
        self._patch_data(data_directory)
        return ResearchSessions(directory=directory,
                                settings=Settings(self.base / "settings.json"),
                                db_path=Path(data_directory) / "index.sqlite3")

    def test_default_clone_reads_its_own_copy(self):
        clone = self._sessions(self.clone_data)
        self.assertEqual(str(self.clone_path), clone.status(self.research_id)["directory"])

    def test_explicit_directory_beats_the_copied_registry(self):
        clone = self._sessions(self.clone_data, directory=self.clone_data / "research")
        self.assertEqual(str(self.clone_path), clone.status(self.research_id)["directory"])

    def test_clone_write_lands_in_the_clone_not_the_origin(self):
        clone = self._sessions(self.clone_data)
        before = (self.origin_path / "state.json").read_bytes()
        clone.record(self.research_id, {"kind": "gap", "question_id": "q1", "text": "Clone-only note."})
        self.assertIn("Clone-only note.", (self.clone_path / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(before, (self.origin_path / "state.json").read_bytes())

    def test_duplicate_folder_is_reported_as_a_conflict(self):
        clone = self._sessions(self.clone_data)
        row = {item["research_id"]: item for item in clone.status()["sessions"]}[self.research_id]
        self.assertEqual(str(self.clone_path), row["path"])
        self.assertEqual("conflict", row["location_status"])
        self.assertEqual(str(self.origin_path), row["alternate_path"])
        # The origin copy is untouched and its registry entry is unchanged.
        self.assertEqual(str(self.origin_path), research_locations.load()[self.research_id]["path"])

    def test_registry_still_resolves_tasks_outside_the_data_directory(self):
        # Regression guard: a task created beside its input stays reachable.
        aside = self.base / "aside"
        rid = self.origin.start("Aside task", [{"id": "q1", "question": "What?"}],
                                output_directory=str(aside))["research_id"]
        self.assertEqual(str(aside / rid), research_locations.load()[rid]["path"])
        sessions = self._sessions(self.origin_data)
        self.assertEqual(str(aside / rid), sessions.status(rid)["directory"])

    def test_missing_local_copy_falls_back_to_the_registry(self):
        # Only the clone is inspected and its own copy is removed: the registry
        # is still the documented fallback.
        shutil.rmtree(self.clone_path)
        sessions = self._sessions(self.clone_data)
        self.assertEqual(str(self.origin_path), sessions.status(self.research_id)["directory"])


if __name__ == "__main__":
    unittest.main()
