"""The Wiki switch: defaults, validation, storage guards and follow-up skip."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research import ResearchSessions
from settings import Settings
from wiki import WikiStore
from wiki_compile import WikiCompile


class WikiDisabledTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wiki-disabled-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.settings = Settings(self.base / "settings.json")
        self.settings.update({
            "wiki": {"directory": str(self.base / "wiki")},
            "archive": {"directory": str(self.base / "archive")},
            "output": {"directory": str(self.base / "research")},
        })
        self.wiki = WikiStore(directory=self.base / "wiki", settings=self.settings)

    def test_default_is_enabled_and_validation_requires_a_boolean(self):
        self.assertTrue(Settings.defaults()["wiki"]["enabled"])
        self.assertTrue(self.wiki.enabled())
        with self.assertRaises(ValueError):
            self.settings.update({"wiki": {"enabled": "yes"}})

    def test_storage_reads_and_writes_are_rejected_when_disabled(self):
        self.settings.update({"wiki": {"enabled": False}})
        self.assertFalse(self.wiki.enabled())
        calls = [
            lambda: self.wiki.write("alpha", {"title": "A", "kind": "topic", "links": [],
                                              "review": {"method": "model", "reviewer": "t", "note": "n"},
                                              "sections": []}, "note"),
            lambda: self.wiki.list(),
            lambda: self.wiki.get("alpha"),
            lambda: self.wiki.search("alpha"),
            lambda: self.wiki.lint(),
            lambda: self.wiki.work(),
        ]
        for call in calls:
            with self.assertRaisesRegex(ValueError, "Wiki is disabled"):
                call()

    def test_compile_and_research_follow_up_report_disabled(self):
        self.settings.update({"wiki": {"enabled": False}})
        compiler = WikiCompile(None, self.wiki, self.settings)
        with self.assertRaisesRegex(ValueError, "Wiki is disabled"):
            compiler.plan("fixture")
        sessions = ResearchSessions(directory=str(self.base / "research"), settings=self.settings)
        follow_up = sessions._wiki_follow_up({"research_id": "r-x", "claims": [], "sources": [],
                                              "questions": [], "topic": "Topic"})
        self.assertEqual("disabled", follow_up["policy"])
        self.assertEqual("wiki_disabled", follow_up["skip_reason"])


if __name__ == "__main__":
    unittest.main()
