"""Reviewed knowledge, stale evidence, immutable history and authored-text search."""

import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from research import ResearchSessions
from settings import Settings
from wiki import WikiStore


class WikiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wiki tests 中文 ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(self.root / "settings.json")
        self.engine = Mock()
        self.engine.fetch.side_effect = self.fetched
        self.research = ResearchSessions(self.root / "research", settings=self.settings, engine=self.engine)
        self.rid = self.research.start("Synthetic Wiki evidence", [{"id": "q1", "question": "What is supported?"}],
                                       providers=["exa"])["research_id"]
        self.research.fetch(self.rid, "read-once", "q1", ["https://example.test/docs"])
        self.research.record(self.rid, {"kind": "claim", "question_id": "q1", "statement": "Aurora supports reusable sessions.",
                                       "citations": [{"source_id": "s1", "quote": "Aurora supports reusable sessions."}]})
        self.wiki = WikiStore(self.root / "wiki", settings=self.settings, research_sessions=self.research)

    @staticmethod
    def fetched(urls, provider, archive, max_characters):
        return {"provider": provider, "urls": urls, "tool": "synthetic_fixture", "request_arguments": {"urls": urls},
                "retrieved_at": "2026-09-11T00:00:00Z", "requested_max_characters": max_characters,
                "usage": {"tool_calls": 1}, "result": {"structuredContent": {"results": [
                    {"url": url, "text": "Aurora supports reusable sessions.\nArchive-only token: UnorganizedNebula."}
                    for url in urls]}}}

    def review(self, verdict="accepted"):
        self.research.record(self.rid, {"kind": "source_review", "source_id": "s1", "verdict": verdict,
                                       "text": "Explicit review of the synthetic source identity and evidence."})

    def page(self, **changes):
        page = {"title": "Reusable research sessions", "kind": "topic",
                "sections": [{"heading": "Session reuse", "text": "Aurora supports reusable sessions. 可恢复的知识整理。",
                              "claims": [{"research_id": self.rid, "claim_id": "c1"}]}], "links": [],
                "review": {"method": "human", "reviewer": "Synthetic test author", "note": "Fixture assertion only; not a live semantic evaluation."}}
        page.update(changes)
        return page

    def test_only_explicitly_accepted_active_material_can_be_written(self):
        for verdict in ("unreviewed", "uncertain", "rejected"):
            with self.subTest(verdict=verdict):
                if verdict != "unreviewed":
                    self.review(verdict)
                with self.assertRaisesRegex(ValueError, "accepted source"):
                    self.wiki.write("sessions", self.page(), "First organization")
                self.assertFalse(self.wiki.directory.exists())
        self.review()
        self.research.record(self.rid, {"kind": "retraction", "claim_id": "c1", "text": "Retract this fixture claim."})
        with self.assertRaisesRegex(ValueError, "retracted"):
            self.wiki.write("sessions", self.page(), "Retracted material")

    def test_provenance_inventory_and_exact_evidence_are_preserved_offline(self):
        self.review()
        path, state = self.research._load(self.rid)
        state["sources"][0]["inventory_ids"] = ["u-synthetic-url"]
        state["sources"][0]["bookmark_refs"] = [{"source_id": "fixture", "section_id": "section", "item_id": "item"}]
        self.research._save(path, state)
        written = self.wiki.write("sessions", self.page(), "Organized reviewed evidence")
        page = self.wiki.get("sessions")
        self.assertEqual(page["revision"], 1)
        citation = page["evidence"][0]["citations"][0]
        self.assertEqual(citation["inventory_ids"], ["u-synthetic-url"])
        self.assertEqual(citation["bookmark_refs"][0]["item_id"], "item")
        self.assertEqual(citation["quote"], "Aurora supports reusable sessions.")
        self.assertEqual(page["evidence"][0]["research_id"], self.rid)
        self.assertEqual(citation["source_id"], "s1")
        self.assertEqual(self.wiki.lint()["status"], "ok")
        self.assertEqual(self.wiki.lint()["semantic_support"], "not_scored")
        self.assertEqual(page["validation"]["status"], "current")
        markdown = Path(written["artifacts"]["markdown_file"])
        for target in re.findall(r"\]\(([^)]+)\)", markdown.read_text()):
            if not target.startswith("#"):
                self.assertTrue((markdown.parent / target).is_file(), target)
        self.assertEqual(self.engine.fetch.call_count, 1)
        self.engine.search.assert_not_called()

    def test_incremental_revisions_and_crosslinks_keep_history_readable(self):
        self.review()
        entity = self.wiki.write("aurora", self.page(title="Aurora", kind="entity"), "Create entity")
        topic = self.page(links=[{"page_id": "aurora", "relation": "Documents an example of session reuse"}])
        first = self.wiki.write("sessions", topic, "Create topic")
        original_files = {key: Path(value).read_bytes() for key, value in first["artifacts"].items()}
        updated = copy.deepcopy(topic)
        updated["sections"][0]["text"] += " This organization is a revision."
        self.wiki.write("sessions", updated, "Clarify organization", expected_revision=1)
        self.assertEqual(self.wiki.get("sessions")["revision"], 2)
        self.assertEqual(self.wiki.get("sessions", revision=1)["page"], topic)
        for key, value in first["artifacts"].items():
            self.assertEqual(Path(value).read_bytes(), original_files[key])
        self.wiki.write("aurora", self.page(title="Aurora", kind="entity"), "Refresh entity review", expected_revision=1)
        lint = self.wiki.lint("sessions")
        self.assertEqual(lint["status"], "ok")
        self.assertTrue(any(issue["code"] == "link_has_newer_revision" for issue in lint["issues"]))
        self.assertTrue(Path(entity["artifacts"]["markdown_file"]).is_file())
        self.assertEqual(self.wiki.list(limit=1)["next_offset"], 1)
        with self.assertRaisesRegex(ValueError, "revision changed"):
            self.wiki.write("sessions", topic, "Would overwrite a newer change", expected_revision=1)

    def test_failed_index_commit_does_not_publish_or_destroy_a_revision(self):
        self.review()
        first = self.wiki.write("sessions", self.page(), "Original revision")
        index_before = (self.wiki.directory / "index.json").read_bytes()
        record_before = Path(first["artifacts"]["record_file"]).read_bytes()
        write = ResearchSessions._write
        def fail_index(path, value):
            if path == self.wiki.directory / "index.json":
                raise OSError("Injected index publication failure")
            return write(path, value)
        with patch.object(ResearchSessions, "_write", side_effect=fail_index):
            with self.assertRaisesRegex(OSError, "publication failure"):
                self.wiki.write("sessions", self.page(), "Failed update", expected_revision=1)
        self.assertEqual((self.wiki.directory / "index.json").read_bytes(), index_before)
        self.assertEqual(Path(first["artifacts"]["record_file"]).read_bytes(), record_before)
        self.assertEqual(self.wiki.get("sessions")["revision"], 1)
        self.assertEqual(self.wiki.write("sessions", self.page(), "Retry locally", expected_revision=1)["revision"], 2)
        self.assertEqual(self.wiki.lint()["status"], "ok")

    def test_stale_evidence_is_visible_and_excluded_from_search(self):
        self.review()
        self.wiki.write("sessions", self.page(), "Initial page")
        self.assertEqual(self.wiki.search("可恢复")["total"], 1)
        self.assertEqual(self.wiki.search("UnorganizedNebula")["total"], 0)
        self.review("rejected")
        self.assertEqual(self.wiki.get("sessions")["validation"]["status"], "stale")
        self.assertEqual(self.wiki.lint()["status"], "error")
        search = self.wiki.search("reusable")
        self.assertEqual(search["total"], 0)
        self.assertEqual(search["excluded_page_ids"], ["sessions"])
        self.review()
        self.research.record(self.rid, {"kind": "retraction", "claim_id": "c1", "text": "Withdraw the finding."})
        self.assertEqual(self.wiki.search("reusable")["excluded_stale_pages"], 1)

    def test_changed_source_or_wiki_artifacts_fail_lint(self):
        self.review()
        written = self.wiki.write("sessions", self.page(), "Initial page")
        page = self.wiki.get("sessions")
        source = Path(page["evidence"][0]["citations"][0]["response_file"])
        source.write_text("Altered response")
        self.assertEqual(self.wiki.lint()["status"], "error")
        markdown = Path(written["artifacts"]["markdown_file"])
        markdown.write_text("Direct edits are not explicit revisions")
        with self.assertRaisesRegex(ValueError, "Markdown hash changed"):
            self.wiki.get("sessions")
        self.assertEqual(self.wiki.search("sessions")["excluded_stale_pages"], 1)

    def test_external_report_stays_secondary_and_does_not_expand_sources(self):
        self.review()
        path, state = self.research._load(self.rid)
        provenance = {"kind": "external_report", "run_id": "synthetic-run", "reported_citations": ["https://example.test/unread"]}
        state["sources"][0]["provenance"] = provenance
        self.research._save(path, state)
        written = self.wiki.write("report-topic", self.page(), "Summarize reviewed secondary evidence")
        page = self.wiki.get("report-topic")
        self.assertEqual(len(page["evidence"][0]["citations"]), 1)
        self.assertEqual(page["evidence"][0]["citations"][0]["provenance"], provenance)
        self.assertIn("Secondary evidence", Path(written["artifacts"]["markdown_file"]).read_text())
        self.assertEqual(self.research.status(self.rid)["counts"]["sources"], 1)

    def test_invalid_structure_and_package_paths_cannot_create_pages(self):
        self.review()
        for identifier in ("../escape", "/absolute", "UpperCase"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                self.wiki.write(identifier, self.page(), "Invalid identifier")
        ungrounded = self.page()
        ungrounded["sections"][0]["claims"] = []
        with self.assertRaisesRegex(ValueError, "claim references"):
            self.wiki.write("ungrounded", ungrounded, "No evidence")
        with self.assertRaisesRegex(ValueError, "existing different page"):
            self.wiki.write("missing-link", self.page(links=[{"page_id": "absent", "relation": "Unknown"}]), "Missing target")
        package = self.root / "canvas-package"
        package.mkdir()
        (package / "Example.canvas").write_text("{}")
        with self.assertRaisesRegex(ValueError, "canvas package"):
            WikiStore(package / "wiki", settings=self.settings)
        with self.assertRaisesRegex(ValueError, "plugin directories"):
            WikiStore(Path(__file__).resolve().parents[1] / "private-wiki", settings=self.settings)

    def test_configured_directory_and_explicit_override(self):
        configured = self.root / "configured-wiki"
        with patch.object(self.settings, "load", return_value={"wiki": {"directory": str(configured)}}):
            self.assertEqual(WikiStore(settings=self.settings).directory, configured.resolve())
            self.assertEqual(WikiStore(self.root / "override", settings=self.settings).directory, (self.root / "override").resolve())


if __name__ == "__main__":
    unittest.main()
