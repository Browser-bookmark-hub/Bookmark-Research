"""Where new research tasks are placed, how every task stays listed, and the Wiki follow-up."""

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import research_locations
from bookmark_index import BookmarkIndex
from research import ResearchSessions
from settings import Settings
from source_manager import SourceManager


def section(label="A-1", values=("aurora", "brook")):
    return {"format": "bookmark-canvas-section", "schemaVersion": 2, "id": "temp-section-" + label,
            "sectionType": "temporary", "label": label, "title": "Test sources " + label,
            "items": [{"id": "b%s" % index, "sectionId": "temp-section-" + label, "type": "bookmark",
                       "url": "https://example.test/" + value, "title": value}
                      for index, value in enumerate(values)]}


class OutputLocationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="output location 中文 ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.settings = Settings(self.base / "settings.json")
        self.db = self.base / "data" / "index.sqlite3"
        self.sessions = ResearchSessions(settings=self.settings, db_path=self.db)
        self.inputs = self.base / "inputs"
        self.inputs.mkdir()

    def configure(self, **output):
        self.settings.update({"output": output})

    def sync(self, path, source_id):
        with BookmarkIndex(self.db) as index:
            SourceManager(index).sync(path, source_id)

    def section_file(self, path, **kwargs):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(section(**kwargs), ensure_ascii=False), encoding="utf-8")
        return path

    def package(self, path):
        self.section_file(path / "临时栏目" / "A-1.json")
        return path

    def start(self, sessions=None, **kwargs):
        return (sessions or self.sessions).start(
            "Place this research", [{"id": "q1", "question": "What does Aurora provide?"}], **kwargs)

    # Placement -----------------------------------------------------------------

    def test_central_default_uses_output_directory_and_creates_work_directory(self):
        central = self.base / "central results"
        self.configure(directory=str(central))
        result = self.start()
        rid = result["research_id"]
        self.assertEqual(result["output"], {"placement": "central", "path": str(central / rid), "fallback_reason": None})
        self.assertEqual(result["directory"], str(central / rid))
        self.assertEqual(result["work_directory"], str(central / rid / "work"))
        self.assertTrue((central / rid / "work").is_dir())
        self.assertEqual(research_locations.load()[rid]["path"], str(central / rid))
        self.assertEqual(research_locations.load()[rid]["placement"], "central")
        self.assertEqual(self.sessions.status(rid)["directory"], str(central / rid))

    def test_default_central_directory_is_in_the_data_directory(self):
        rid = self.start()["research_id"]
        self.assertEqual(self.start()["output"]["placement"], "central")
        self.assertTrue((self.base / "data" / "research" / rid / "state.json").is_file())

    def test_beside_input_for_single_file_directory_and_zip(self):
        self.configure(mode="beside_input")
        file_input = self.section_file(self.inputs / "a.json")
        directory_input = self.package(self.inputs / "pkg")
        zip_input = self.inputs / "export.zip"
        with zipfile.ZipFile(zip_input, "w") as archive:
            archive.writestr("导出包/临时栏目/A-1.json", json.dumps(section(), ensure_ascii=False))
        for source_id, source, expected in (("file", file_input, "a.bookmark-research"),
                                            ("directory", directory_input, "pkg.bookmark-research"),
                                            ("zip", zip_input, "export.bookmark-research")):
            with self.subTest(source_id):
                self.sync(source, source_id)
                result = self.start(source_ids=[source_id])
                rid = result["research_id"]
                task = self.inputs / expected / rid
                self.assertEqual(result["output"], {"placement": "beside_input", "path": str(task), "fallback_reason": None})
                self.assertTrue((task / "work").is_dir())
                self.assertEqual(research_locations.load()[rid]["placement"], "beside_input")
                # The task is self-contained and fully usable from its new place.
                evidence = self.sessions.import_evidence(rid, "read-1", "q1", "https://example.test/aurora",
                    "Aurora provides durable storage.", {"kind": "page", "provider": "fixture"})
                sid = evidence["sources"][0]["id"]
                self.assertTrue(evidence["sources"][0]["body_file"].startswith("evidence/"))
                self.assertEqual(self.sessions.source(rid, sid)["text"], "Aurora provides durable storage.")
                self.assertEqual(self.sessions.status(rid)["directory"], str(task))
        self.assertTrue(directory_input.is_dir() and not any(directory_input.glob("r-*")),
                        "Never write into the original folder")

    def test_beside_input_fallbacks_are_explained(self):
        central = self.base / "central"
        self.configure(mode="beside_input", directory=str(central))
        self.sync(self.section_file(self.inputs / "one.json"), "one")
        self.sync(self.section_file(self.inputs / "two.json", label="B-1"), "two")
        repository = self.inputs / "repo"
        (repository / ".git").mkdir(parents=True)
        self.sync(self.section_file(repository / "nested" / "in-git.json"), "git")
        canvas = self.package(self.inputs / "canvas-package")
        self.sync(canvas / "临时栏目" / "A-1.json", "in-canvas")
        cases = (("urls", {"urls": ["https://example.test/aurora"]}, "no_input_path"),
                 ("questions", {}, "no_input_path"),
                 ("multiple", {"source_ids": ["one", "two"]}, "multiple_sources"),
                 ("git", {"source_ids": ["git"]}, "inside_git_repository"),
                 ("canvas", {"source_ids": ["in-canvas"]}, "inside_canvas_package"))
        for label, kwargs, reason in cases:
            with self.subTest(label):
                result = self.start(**kwargs)
                self.assertEqual(result["output"], {"placement": "central", "fallback_reason": reason,
                                                    "path": str(central / result["research_id"])})
                self.assertTrue((central / result["research_id"] / "work").is_dir())
        self.assertFalse((repository / "nested" / "in-git.bookmark-research").exists())

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "POSIX permission bits do not restrict this user")
    def test_beside_input_falls_back_when_location_is_not_writable(self):
        central = self.base / "central"
        self.configure(mode="beside_input", directory=str(central))
        locked = self.inputs / "locked"
        self.sync(self.section_file(locked / "a.json"), "locked")
        locked.chmod(0o555)
        self.addCleanup(locked.chmod, 0o755)
        result = self.start(source_ids=["locked"])
        self.assertEqual(result["output"]["placement"], "central")
        self.assertEqual(result["output"]["fallback_reason"], "not_writable")
        self.assertFalse((locked / "a.bookmark-research").exists())

    def test_explicit_output_directory_overrides_mode(self):
        self.configure(mode="beside_input")
        self.sync(self.section_file(self.inputs / "a.json"), "file")
        custom = self.base / "custom place"
        result = self.start(source_ids=["file"], output_directory=str(custom))
        rid = result["research_id"]
        self.assertEqual(result["output"], {"placement": "explicit", "path": str(custom / rid), "fallback_reason": None})
        self.assertEqual(research_locations.load()[rid]["placement"], "explicit")
        self.assertEqual(self.sessions.status(rid)["research_id"], rid)
        for invalid in ("relative/path", "", 3):
            with self.assertRaises(ValueError):
                self.start(output_directory=invalid)

    def test_explicit_constructor_directory_keeps_legacy_behavior(self):
        self.configure(mode="beside_input", directory=str(self.base / "ignored"))
        self.sync(self.section_file(self.inputs / "a.json"), "file")
        legacy = ResearchSessions(self.base / "legacy", settings=self.settings, db_path=self.db)
        result = self.start(legacy, source_ids=["file"])
        rid = result["research_id"]
        self.assertEqual(result["output"], {"placement": "central", "path": str(self.base / "legacy" / rid),
                                            "fallback_reason": None})
        self.assertNotIn(rid, research_locations.load())
        self.assertEqual([row["research_id"] for row in legacy.status()["sessions"]], [rid])
        # A per-task explicit folder is still registered so it can be found again.
        explicit = self.start(legacy, output_directory=str(self.base / "elsewhere"))["research_id"]
        self.assertIn(explicit, research_locations.load())
        self.assertEqual(legacy.status(explicit)["directory"], str(self.base / "elsewhere" / explicit))

    # Listing and lookup --------------------------------------------------------

    def test_registry_lists_tasks_after_output_directory_changes(self):
        first_root, second_root = self.base / "first", self.base / "second"
        self.configure(directory=str(first_root))
        first = self.start()["research_id"]
        self.configure(directory=str(second_root))
        second = self.start()["research_id"]
        legacy_path = self.base / "data" / "research"
        legacy = self.start(ResearchSessions(legacy_path, settings=self.settings, db_path=self.db))["research_id"]
        listing = ResearchSessions(settings=self.settings, db_path=self.db).status()
        rows = {row["research_id"]: row for row in listing["sessions"]}
        self.assertEqual(listing["total"], 3)
        self.assertEqual(rows[first]["path"], str(first_root / first))
        self.assertEqual(rows[second]["path"], str(second_root / second))
        self.assertEqual(rows[legacy]["path"], str(legacy_path / legacy))
        self.assertEqual({row["location_status"] for row in rows.values()}, {"ok"})
        self.assertEqual(rows[first]["brief"], "Place this research")
        self.assertEqual(self.sessions.status(first)["directory"], str(first_root / first))

    def test_deleted_task_folder_is_listed_as_missing(self):
        kept = self.start()["research_id"]
        gone = self.start(output_directory=str(self.base / "temporary"))["research_id"]
        shutil.rmtree(self.base / "temporary" / gone)
        rows = {row["research_id"]: row for row in self.sessions.status()["sessions"]}
        self.assertEqual(rows[kept]["location_status"], "ok")
        self.assertEqual(rows[gone]["location_status"], "missing")
        self.assertEqual(rows[gone]["path"], str(self.base / "temporary" / gone))
        with self.assertRaisesRegex(ValueError, "missing"):
            self.sessions.status(gone)

    def test_untrusted_registry_entries_are_not_followed(self):
        victim = self.start(output_directory=str(self.base / "tasks"))["research_id"]
        other = self.start(output_directory=str(self.base / "tasks"))["research_id"]
        link = self.base / "link"
        link.symlink_to(self.base / "tasks", target_is_directory=True)
        registry = research_locations.registry_path()
        data = json.loads(registry.read_text(encoding="utf-8"))
        # Wrong folder name, a relative path and a symlinked parent are all rejected.
        data["tasks"][victim]["path"] = str(self.base / "tasks" / other)
        data["tasks"][other]["path"] = str(link / other)
        forged = "r-" + "0" * 16
        data["tasks"][forged] = {"path": "tasks/" + forged, "created_at": "x", "placement": "explicit"}
        registry.write_text(json.dumps(data), encoding="utf-8")
        for rid in (victim, other, forged):
            with self.assertRaises((ValueError, OSError)):
                self.sessions.status(rid)
        rows = {row["research_id"]: row for row in self.sessions.status()["sessions"]}
        self.assertEqual({rows[rid]["location_status"] for rid in (victim, other, forged)}, {"invalid"})

    def test_unreadable_registry_keeps_legacy_tasks_available(self):
        rid = self.start()["research_id"]
        research_locations.registry_path().write_text("not json", encoding="utf-8")
        self.assertEqual(self.sessions.status(rid)["research_id"], rid)
        self.assertEqual([row["research_id"] for row in self.sessions.status()["sessions"]], [rid])

    # Wiki follow-up ------------------------------------------------------------

    def reviewed_claim(self, rid):
        text = "Aurora provides durable storage."
        sid = self.sessions.import_evidence(rid, "read-1", "q1", "https://example.test/aurora", text,
                                            {"kind": "page", "provider": "fixture"})["sources"][0]["id"]
        self.sessions.record(rid, {"kind": "source_review", "source_id": sid, "verdict": "accepted", "text": "Checked."})
        return self.sessions.record(rid, {"kind": "claim", "question_id": "q1", "statement": text,
                                          "citations": [{"source_id": sid, "quote": text}]})["recorded"]["id"]

    def write_page(self, rid, claim):
        from wiki import WikiStore
        WikiStore(settings=self.settings, research_sessions=self.sessions).write("aurora", {
            "title": "Aurora", "kind": "entity", "links": [],
            "sections": [{"heading": "Storage", "text": "Aurora provides durable storage.",
                          "claims": [{"research_id": rid, "claim_id": claim}]}],
            "review": {"method": "human", "reviewer": "Fixture author", "note": "Synthetic test."}}, "Create page")

    def test_finish_returns_wiki_follow_up_for_each_policy(self):
        page_task = self.start()["research_id"]
        self.write_page(page_task, self.reviewed_claim(page_task))
        for policy in ("suggest", "auto", "off"):
            with self.subTest(policy):
                self.settings.update({"wiki": {"after_research": policy}})
                rid = self.start()["research_id"]
                claim = self.reviewed_claim(rid)
                follow_up = self.sessions.finish(rid, "Partial synthesis.", status="incomplete")["wiki_follow_up"]
                if policy == "off":
                    self.assertEqual(follow_up, {"policy": "off"})
                    continue
                self.assertEqual(follow_up["policy"], policy)
                self.assertEqual(follow_up["candidates"][0]["page_id"], "aurora")
                self.assertEqual(follow_up["candidates"][0]["title"], "Aurora")
                self.assertLessEqual(len(follow_up["candidates"]), 5)
                self.assertEqual(follow_up["eligible_claim_ids"], [claim])
                if policy == "suggest":
                    self.assertIn("only after the user confirms", follow_up["instruction"])
                else:
                    self.assertIn("Without asking the user", follow_up["instruction"])

    def test_wiki_failure_keeps_finish_successful(self):
        rid = self.start()["research_id"]
        wiki = Path(self.settings.load()["wiki"]["directory"])
        wiki.mkdir(parents=True)
        (wiki / "index.json").write_text("{broken", encoding="utf-8")
        result = self.sessions.finish(rid, "Nothing found.", status="incomplete")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["wiki_follow_up"]["candidates"], [])
        self.assertEqual(result["wiki_follow_up"]["policy"], "suggest")
        self.assertTrue(Path(result["artifacts"]["report"]).is_file())


if __name__ == "__main__":
    unittest.main()
