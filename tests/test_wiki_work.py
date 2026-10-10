"""Work recovery follows committed evidence, including interrupted and partial writes."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from archive import SourceArchive
from mcp_server import StdioMcpServer
from research import ResearchSessions
from settings import Settings
from wiki import WikiStore


class WikiWorkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.root / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.settings = Settings(self.root / "settings.json")
        self.settings.update({"archive": {"directory": str(self.root / "raw")},
                              "wiki": {"directory": str(self.root / "wiki")}})
        self.engine = Mock()
        self.engine.fetch.side_effect = self.fetched
        self.body = "Aurora costs 10. Aurora supports offline use."
        self.url = "https://example.test/aurora"
        self.now = datetime.now(timezone.utc)
        self.restart()

    def restart(self):
        self.research = ResearchSessions(self.root / "research", settings=self.settings, engine=self.engine,
                                         db_path=self.root / "bookmarks.sqlite3")
        self.wiki = WikiStore(settings=self.settings, research_sessions=self.research)

    def fetched(self, urls, provider=None, archive=True, max_characters=12000):
        return {"provider": provider or "exa", "urls": urls, "tool": "fixture", "status": "ok",
                "request_arguments": {"urls": urls}, "requested_max_characters": max_characters,
                "retrieved_at": self.now.isoformat(),
                "result": {"structuredContent": {"results": [{"url": url, "text": self.body} for url in urls]}}}

    def evidence(self, review=True, stamp=None, body=None, url=None):
        rid = self.research.start("Aurora evidence", [{"id": "q1", "question": "What does Aurora offer?"}],
                                  providers=["exa"])["research_id"]
        self.research.import_evidence(rid, "import", "q1", url or self.url, body or self.body,
            {"kind": "page", "provider": "fixture", "retrieved_at": stamp or self.now.isoformat()})
        if review:
            self.research.record(rid, {"kind": "source_review", "source_id": "s1", "verdict": "accepted",
                                      "text": "Checked exact synthetic test evidence."})
        return rid

    def claim(self, rid, quote="Aurora costs 10."):
        self.research.record(rid, {"kind": "claim", "question_id": "q1", "statement": quote,
                                  "citations": [{"source_id": "s1", "quote": quote}]})

    def page(self, rid, claims=("c1",), links=None):
        return {"title": "Aurora", "kind": "entity", "sections": [{"heading": "Facts",
            "text": "Reviewed Aurora information.", "claims": [{"research_id": rid, "claim_id": cid} for cid in claims]}],
            "links": links or [], "review": {"method": "human", "reviewer": "fixture", "note": "Synthetic test."}}

    def item(self, **kwargs):
        result = self.wiki.work(**kwargs)
        self.assertEqual(1, result["total"])
        return result["items"][0]

    def test_archive_pending_and_committed_states_survive_restart(self):
        capture = SourceArchive(self.root / "raw").save(self.fetched([self.url]))
        cid = capture["capture_id"]
        self.assertEqual("archived", self.item(capture_id=cid)["status"])
        rid = self.evidence()
        self.claim(rid)
        self.restart()
        self.assertEqual("pending", self.item(capture_id=cid)["status"])
        pending = self.item(research_id=rid)
        self.assertEqual(["c1"], pending["pending_claim_ids"])
        written = self.wiki.write("aurora", self.page(rid), "Compile")
        self.restart()
        for selector in ({"capture_id": cid}, {"research_id": rid}, {"page_id": "aurora"}):
            self.assertEqual("compiled", self.item(**selector)["status"])
        receipt = self.item(page_id="aurora")["receipt"]
        self.assertEqual(written["work_receipt"], receipt)
        self.assertEqual([{"research_id": rid, "claim_id": "c1"}], receipt["claims"])
        self.engine.fetch.assert_not_called()

    def test_partial_compilation_and_unreviewed_claims_are_distinguished(self):
        rid = self.evidence(review=False)
        self.claim(rid)
        self.assertEqual("archived", self.item(research_id=rid)["status"])
        self.research.record(rid, {"kind": "source_review", "source_id": "s1", "verdict": "accepted", "text": "Checked."})
        self.claim(rid, "Aurora supports offline use.")
        self.wiki.write("aurora", self.page(rid), "Only first claim")
        item = self.item(research_id=rid)
        self.assertEqual("pending", item["status"])
        self.assertEqual(["c2"], item["pending_claim_ids"])
        self.assertEqual(1, item["page_count"])
        self.wiki.write("aurora", self.page(rid, ("c1", "c2")), "Both claims", expected_revision=1)
        self.assertEqual("compiled", self.item(research_id=rid)["status"])

    def test_corrupted_archive_is_not_credited_from_an_intact_research_copy(self):
        archive = SourceArchive(self.root / "raw")
        capture = archive.save(self.fetched([self.url]))
        rid = self.evidence()
        self.claim(rid)
        self.wiki.write("aurora", self.page(rid), "Compile copied evidence")
        self.assertEqual("compiled", self.item(capture_id=capture["capture_id"])["status"])
        _, directory = next(archive.captures())
        manifest = json.loads((directory / "manifest.json").read_text())
        archive.page_path(directory, manifest["pages"][0]).write_text("damaged original archive")
        self.restart()
        item = self.item(capture_id=capture["capture_id"])
        self.assertEqual("needs_review", item["status"])
        self.assertIn("SHA-256", item["error"])
        self.assertEqual("compiled", self.item(research_id=rid)["status"])
        path, state = self.research._load(rid)
        self.assertEqual(self.body, self.research._artifact(path, state["sources"][0]["body_file"]).read_text())
        self.engine.fetch.assert_not_called()

    def test_instruction_only_follow_up_is_pending_and_preserves_preference(self):
        rid = self.evidence()
        self.claim(rid)
        self.settings.update({"wiki": {"after_research": "auto"}})
        _, state = self.research._load(rid)
        follow_up = self.research._wiki_follow_up(state)
        self.assertEqual("auto", follow_up["policy"])
        self.assertEqual({"research_id": rid}, follow_up["work"]["arguments"])
        self.restart()
        self.assertEqual("pending", self.item(research_id=rid)["status"])
        self.assertEqual({}, self.wiki._index()["pages"])

    def test_orphan_revision_before_index_commit_does_not_count(self):
        rid = self.evidence()
        self.claim(rid)
        write = ResearchSessions._write
        def fail_index(path, value):
            if path.name == "index.json":
                raise OSError("interrupted before commit")
            return write(path, value)
        with patch.object(ResearchSessions, "_write", side_effect=fail_index):
            with self.assertRaisesRegex(OSError, "before commit"):
                self.wiki.write("aurora", self.page(rid), "Interrupted")
        self.assertTrue(list((self.wiki.directory / "revisions").rglob("*.json")))
        self.restart()
        self.assertEqual("pending", self.item(research_id=rid)["status"])
        self.assertEqual(0, self.wiki.work(kind="page")["total"])

    def test_commit_before_lost_catalog_response_is_recovered_without_rewriting(self):
        rid = self.evidence()
        self.claim(rid)
        write = ResearchSessions._write
        def fail_catalog(path, value):
            if path.name == "index.md":
                raise OSError("interrupted after commit")
            return write(path, value)
        with patch.object(ResearchSessions, "_write", side_effect=fail_catalog):
            with self.assertRaisesRegex(OSError, "after commit"):
                self.wiki.write("aurora", self.page(rid), "Committed")
        self.restart()
        self.assertEqual("compiled", self.item(research_id=rid)["status"])
        self.assertEqual(1, self.item(page_id="aurora")["receipt"]["revision"])

    def test_changed_sources_and_linked_pages_remain_pending_until_revised(self):
        rid = self.evidence(stamp=(self.now - timedelta(days=1)).isoformat())
        self.claim(rid)
        self.wiki.write("aurora", self.page(rid), "Initial")
        other = self.evidence(url="https://example.test/other")
        self.claim(other)
        linked = self.page(other, links=[{"page_id": "aurora", "relation": "Pricing"}])
        self.wiki.write("overview", linked, "Link")
        self.body = "Aurora costs 20."
        refreshed = self.wiki.refresh("aurora")
        self.restart()
        self.assertEqual({"aurora", "overview"}, {row["page_id"] for row in self.wiki.work(
            kind="page", status="needs_review")["items"]})
        source_read = self.item(page_id="aurora")["source_reads"][0]
        self.assertEqual(refreshed["checks"][0]["capture_id"], source_read["arguments"]["capture_id"])
        updated = self.evidence()
        self.claim(updated, self.body)
        self.wiki.write("aurora", self.page(updated), "New source", expected_revision=1)
        self.assertEqual("compiled", self.item(page_id="aurora")["status"])
        self.assertEqual("needs_review", self.item(page_id="overview")["status"])
        self.wiki.write("overview", linked, "Review linked revision", expected_revision=1)
        self.assertEqual(0, self.wiki.work(kind="page", status="needs_review")["total"])
        self.assertEqual(1, self.wiki.get("aurora", revision=1)["revision"])

    def test_failed_refresh_and_corrupted_evidence_cannot_be_marked_complete(self):
        rid = self.evidence()
        self.claim(rid)
        self.wiki.write("aurora", self.page(rid), "Initial")
        self.engine.fetch.side_effect = TimeoutError("test outage")
        self.wiki.refresh("aurora")
        self.restart()
        self.assertEqual("needs_review", self.item(page_id="aurora")["status"])
        path, state = self.research._load(rid)
        self.research._artifact(path, state["sources"][0]["body_file"]).write_text("tampered")
        self.assertEqual("needs_review", self.item(research_id=rid)["status"])
        self.assertEqual("needs_review", self.item(page_id="aurora")["status"])

    def test_page_scope_pagination_and_validation_are_offline(self):
        rid = self.evidence()
        self.claim(rid)
        for slug in ("alpha", "beta", "gamma"):
            self.wiki.write(slug, self.page(rid), "Separate publication")
        with patch.object(self.research, "_sessions", side_effect=AssertionError("unnecessary scan")):
            self.assertEqual("beta", self.item(page_id="beta")["page_id"])
        first = self.wiki.work(kind="page", limit=2)
        second = self.wiki.work(kind="page", offset=first["next_offset"], limit=2)
        self.assertEqual(3, len({row["work_id"] for row in first["items"] + second["items"]}))
        for options in ({"kind": "bad"}, {"status": "done"}, {"kind": "page", "research_id": rid}, {"limit": 0}):
            with self.assertRaises(ValueError):
                self.wiki.work(**options)
        self.engine.fetch.assert_not_called()

    def test_mcp_and_cli_expose_the_same_recoverable_work(self):
        rid = self.evidence()
        self.claim(rid)
        server = StdioMcpServer(self.root / "index.sqlite3", settings=self.settings, stderr=io.StringIO())
        self.addCleanup(server.close)
        server._wiki_store = self.wiki
        self.assertEqual("pending", server._call("wiki_work", {"research_id": rid})["items"][0]["status"])
        result = subprocess.run([sys.executable, str(ROOT / "src/cli.py"), "--config", str(self.settings.path),
            "wiki", "--research-directory", str(self.research.directory), "work", "--research-id", rid],
            capture_output=True, text=True, check=True)
        self.assertEqual("pending", json.loads(result.stdout)["items"][0]["status"])


if __name__ == "__main__":
    unittest.main()
