"""Deterministic Wiki compile planning: scope, noise, coverage and audit."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bookmark_index import BookmarkIndex
from research import ResearchSessions
from settings import Settings
from test_bookmark_index import TEMP, make_package, read_json, write_json
from wiki import WikiStore
from wiki_compile import WikiCompile


class WikiCompileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wiki-compile-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        package = self.base / "package"
        package.mkdir()
        make_package(package)
        self.settings = Settings(self.base / "settings.json")
        self.settings.update({
            "wiki": {"directory": str(self.base / "wiki")},
            "archive": {"directory": str(self.base / "archive")},
            "output": {"directory": str(self.base / "research")},
        })
        self.index = BookmarkIndex(str(self.base / "index.sqlite3"))
        self.addCleanup(self.index.close)
        self.index.sync(str(package), source_id="fixture")
        self.wiki = WikiStore(directory=self.base / "wiki", settings=self.settings)
        self.compiler = WikiCompile(self.index, self.wiki, self.settings)
        self.wiki.write("alpha-topic", {
            "title": "Alpha", "kind": "topic", "links": [],
            "review": {"method": "model", "reviewer": "test", "note": "Checked"},
            "sections": [{"heading": "What", "text": "Alpha is a company.",
                          "citations": [{"source_id": "alpha", "quote": "Alpha is a company."}]}],
        }, change_note="Seed coverage", sources=[{
            "id": "alpha", "url": "https://example.test/alpha",
            "text": "Alpha is a company. It builds things."}])

    def test_plan_drops_noise_and_reports_existing_coverage(self):
        plan = self.compiler.plan("fixture", max_pages=5, min_cluster_size=1,
                                  max_items_per_cluster=10)
        self.assertEqual(4, plan["summary"]["items"])
        self.assertEqual(1, plan["summary"]["covered_items"])
        self.assertEqual(3, plan["summary"]["new_items"])
        self.assertEqual(1, plan["summary"]["excluded"]["duplicate_url"])
        self.assertEqual(2, plan["summary"]["clusters"])
        affected = {row["page_id"] for cluster in plan["clusters"]
                    for row in cluster["affected_pages"]}
        self.assertIn("alpha-topic", affected)
        path = self.base / "wiki" / "compile" / (plan["plan_id"] + ".json")
        self.assertTrue(path.is_file())
        self.assertFalse(plan["reused"])

    def test_plan_is_idempotent_for_the_same_scope_and_basis(self):
        first = self.compiler.plan("fixture", max_pages=5, min_cluster_size=1)
        second = self.compiler.plan("fixture", max_pages=5, min_cluster_size=1)
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertTrue(second["reused"])

    def test_folder_scope_limits_clusters_and_status_recomputes_coverage(self):
        plan = self.compiler.plan("fixture", folder_id="companies", max_pages=5,
                                  min_cluster_size=1, max_items_per_cluster=10,
                                  include_covered=True)
        self.assertEqual(1, plan["summary"]["clusters"])
        status = self.compiler.status(plan["plan_id"])
        self.assertFalse(status["source_changed"])
        self.assertEqual(3, status["summary"]["planned_items"])
        self.assertEqual(1, status["summary"]["covered_items"])
        self.assertEqual(2, status["summary"]["pending_items"])
        self.assertEqual(1, len(status["clusters"][0]["pages"]))
        self.assertIn("alpha-topic", [row["page_id"] for row in status["clusters"][0]["pages"]])

    def test_gap_records_unreadable_items_without_covering_them(self):
        plan = self.compiler.plan("fixture", max_pages=5, min_cluster_size=1,
                                  max_items_per_cluster=10, include_covered=True)
        cluster = plan["clusters"][0]
        url = next(item["url"] for item in cluster["items"] if item["url"] != "https://example.test/alpha")
        receipt = self.compiler.gap(plan["plan_id"], [url], "provider returned no content",
                                    provider="parallel")
        self.assertEqual(1, receipt["recorded"])
        again = self.compiler.gap(plan["plan_id"], [url], "provider returned no content")
        self.assertEqual(1, again["gap_urls"])
        status = self.compiler.status(plan["plan_id"])
        self.assertEqual("planned_items (each cluster capped at max_items_per_cluster)",
                         status["summary"]["coverage_basis"])
        self.assertGreaterEqual(status["summary"]["gap_items"], 1)
        self.assertEqual(1, status["summary"]["gap_items"])
        self.assertEqual(0, status["summary"]["unmatched_gaps"])

    def test_gap_rejects_unknown_plans_and_malformed_urls(self):
        plan = self.compiler.plan("fixture", max_pages=2, min_cluster_size=1)
        with self.assertRaises(ValueError):
            self.compiler.gap("0123456789abcdef", ["https://example.test/a"], "unreadable")
        with self.assertRaises(ValueError):
            self.compiler.gap(plan["plan_id"], [], "unreadable")
        with self.assertRaises(ValueError):
            self.compiler.gap(plan["plan_id"], ["not a url"], "unreadable")

    def test_cjk_titles_match_existing_pages_by_bigram(self):
        tokens = WikiCompile._tokens("TTS 语音模型")
        self.assertIn("语音", tokens)
        self.assertIn("音模", tokens)
        self.assertIn("模型", tokens)
        page = {"page_id": "voice", "title": "语音模型：TTS 与 ASR 的可用路线（2026-11）",
                "aliases": [], "revision": 1, "urls": set(), "links": []}
        matched = self.compiler._matching_pages({"voice": page}, "TTS 语音模型", "")
        self.assertEqual({"voice"}, matched)

    def test_plan_reports_deferred_clusters_and_status_detects_source_change(self):
        plan = self.compiler.plan("fixture", max_pages=1, min_cluster_size=1)
        self.assertGreaterEqual(plan["deferred"]["clusters"], 1)
        self.assertEqual(plan["deferred"], plan["summary"]["deferred"])
        document = read_json(self.base / "package", TEMP)
        document["items"][0]["children"].append({
            "id": "temp-three", "sectionId": "temp-section-A-1", "type": "bookmark",
            "title": "New item", "url": "https://example.test/new", "children": []})
        write_json(self.base / "package", TEMP, document)
        self.index.sync(str(self.base / "package"), source_id="fixture")
        status = self.compiler.status(plan["plan_id"])
        self.assertTrue(status["source_changed"])

    def test_status_rejects_unknown_or_malformed_plan_ids(self):
        with self.assertRaises(ValueError):
            self.compiler.status("not-a-plan")
        with self.assertRaises(ValueError):
            self.compiler.status("0123456789abcdef")
        with self.assertRaises(ValueError):
            self.compiler.plan("fixture", max_pages=0)

    def test_invalid_scope_values_are_rejected(self):
        with self.assertRaises(ValueError):
            self.compiler.plan("fixture", max_items_per_cluster=0)
        with self.assertRaises(ValueError):
            self.compiler.plan("fixture", tags="not-a-list")
        with self.assertRaises(ValueError):
            self.compiler.plan("fixture", include_covered="yes")

    def test_wiki_write_accepts_a_canvas_section_id_with_non_ascii_names(self):
        package = self.base / "package-zh"
        shutil.copytree(self.base / "package", package)
        document = read_json(package, TEMP)
        document["id"] = "temp-section-存档"

        def rename(items):
            for item in items:
                item["sectionId"] = "temp-section-存档"
                rename(item.get("children") or [])

        rename(document["items"])
        write_json(package, TEMP, document)
        database = self.base / "zh.sqlite3"
        index = BookmarkIndex(str(database))
        self.addCleanup(index.close)
        index.sync(str(package), source_id="zh")
        research = ResearchSessions(directory=self.base / "zh-research", settings=self.settings,
                                    db_path=str(database))
        wiki = WikiStore(directory=self.base / "zh-wiki", settings=self.settings,
                         research_sessions=research)
        receipt = wiki.write("alpha-zh", {
            "title": "Alpha", "kind": "topic", "links": [],
            "review": {"method": "model", "reviewer": "test", "note": "Checked"},
            "sections": [{"heading": "What", "text": "Alpha is a company.",
                          "citations": [{"source_id": "alpha", "quote": "Alpha is a company."}]}],
        }, change_note="Non-ASCII section ref", sources=[{
            "id": "alpha", "url": "https://example.test/alpha",
            "text": "Alpha is a company. It builds things."}])
        self.assertEqual("written", receipt["status"])
        page = wiki.get("alpha-zh")
        refs = [ref for evidence in page["evidence"] for citation in evidence["citations"]
                for ref in citation.get("bookmark_refs", [])]
        self.assertTrue(any(ref["section_id"] == "temp-section-存档" for ref in refs), refs)

    def test_plan_file_is_scoped_inside_the_wiki_directory(self):
        plan = self.compiler.plan("fixture", max_pages=1, min_cluster_size=1)
        stored = json.loads((self.base / "wiki" / "compile" / (plan["plan_id"] + ".json"))
                            .read_text(encoding="utf-8"))
        self.assertEqual(plan["plan_id"], stored["plan_id"])
        self.assertEqual("fixture", stored["source_id"])
        self.assertLessEqual(len(stored["clusters"]), 1)


if __name__ == "__main__":
    unittest.main()
