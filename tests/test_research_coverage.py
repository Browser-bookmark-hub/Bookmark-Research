"""Frozen scope, substantive coverage and bounded retrieval across real state files."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from research import ResearchSessions
from settings import Settings


class ResearchCoverageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="research coverage 中文 ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.package = self.base / "original"
        self.db = self.base / "derived/index.sqlite3"
        self.engine = Mock()
        self.engine.fetch.side_effect = self.fetch_response
        self.sessions = ResearchSessions(self.base / "research", settings=Settings(self.base / "settings.json"),
                                         engine=self.engine, db_path=self.db)

    @staticmethod
    def fetch_response(urls, provider, archive, max_characters):
        return {"provider": provider, "urls": urls, "tool": "fixture_fetch", "request_arguments": {"urls": urls},
                "requested_max_characters": max_characters,
                "retrieved_at": "2026-09-11T00:00:00Z", "usage": {"tool_calls": 1},
                "result": {"structuredContent": {"results": [
                    {"url": url, "title": "Synthetic original page", "text": "Saved evidence for " + url + "."}
                    for url in urls]}}}

    @staticmethod
    def url(index):
        return "https://coverage.example.test/" + str(index)

    def index_package(self, count):
        path = self.package / "临时栏目/常规链式/A-1 Sources.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"format": "bookmark-canvas-section", "schemaVersion": 2,
            "sectionType": "temporary", "id": "sources", "label": "A-1", "title": "Synthetic sources",
            "tempKind": "regular", "items": [{"id": "i-" + str(index), "sectionId": "sources",
                "type": "bookmark", "title": "Synthetic source " + str(index), "url": self.url(index)}
                for index in range(count)]}), encoding="utf-8")
        with BookmarkIndex(self.db) as index:
            index.sync(self.package, "fixture")

    def start(self, count=2, **kwargs):
        self.index_package(count)
        return self.sessions.start("Review all synthetic inputs", [{"id": "q1", "question": "What does each input say?"}],
                                   source_ids=["fixture"], providers=["exa"], **kwargs)["research_id"]

    def all_rows(self, research_id, filter=None):
        rows, offsets, offset = [], [], 0
        while offset is not None:
            self.assertNotIn(offset, offsets)
            offsets.append(offset)
            page = (self.sessions.inventory(research_id, offset=offset, limit=100) if filter is None else
                    self.sessions.coverage(research_id, filter=filter, offset=offset, limit=100))
            rows.extend(page["items"])
            offset = page["next_offset"]
        self.assertEqual(len(rows), page["total"])
        return rows, offsets

    def review(self, research_id, source):
        quote = self.sessions.source(research_id, source["id"])["text"]
        self.sessions.record(research_id, {"kind": "source_review", "source_id": source["id"],
            "verdict": "accepted", "text": "Synthetic source identity and quote checked."})
        claim_id = self.sessions.record(research_id, {"kind": "claim", "question_id": "q1", "statement": quote,
            "citations": [{"source_id": source["id"], "quote": quote}]})["recorded"]["id"]
        for inventory_id in source["inventory_ids"]:
            self.sessions.record(research_id, {"kind": "inventory_review", "inventory_id": inventory_id,
                "disposition": "reviewed", "text": quote, "question_ids": ["q1"], "source_ids": [source["id"]],
                "claim_ids": [claim_id]})
        return claim_id

    def review_all(self, research_id):
        rows, _ = self.all_rows(research_id)
        sources = self.sessions.fetch(research_id, "initial-read", "q1", [row["original_url"] for row in rows])["sources"]
        claims = [self.review(research_id, source) for source in sources]
        self.sessions.record(research_id, {"kind": "answer", "question_id": "q1", "answer": "All fixture pages were checked.",
            "claim_ids": claims})
        return sources, claims

    def test_all_inventory_and_difference_pages_remain_frozen_after_index_refresh(self):
        identifier = self.start(207)
        initial = self.sessions.status(identifier)
        rows, offsets = self.all_rows(identifier)
        self.assertEqual(offsets, [0, 100, 200])
        ids = [row["id"] for row in rows]
        self.assertEqual(len(set(ids)), 207)
        for filter_name in ("all", "missing", "unread", "unreviewed"):
            with self.subTest(filter=filter_name):
                differences, pages = self.all_rows(identifier, filter_name)
                self.assertEqual([row["id"] for row in differences], ids)
                self.assertEqual(pages, [0, 100, 200])
        self.index_package(208)
        self.assertEqual(self.sessions.status(identifier)["source_scope"], initial["source_scope"])
        self.assertEqual([row["id"] for row in self.all_rows(identifier)[0]], ids)

    def test_batched_reviews_retain_complete_per_url_coverage_and_claim_links(self):
        research_id = self.start(2)
        rows, _ = self.all_rows(research_id)
        sources = self.sessions.fetch(research_id, "read-all", "q1", [row["original_url"] for row in rows])["sources"]
        entries = []
        for source in sources:
            quote = self.sessions.source(research_id, source["id"])["text"]
            entries.extend([{"kind": "source_review", "source_id": source["id"], "verdict": "accepted", "text": "Original checked."},
                {"kind": "claim", "question_id": "q1", "statement": quote, "citations": [{"source_id": source["id"], "quote": quote}]}])
        result = self.sessions.record(research_id, entries=entries, batch_id="claims")
        claim_ids = [row["id"] for row in result["results"] if row["kind"] == "claim"]
        reviews = [{"kind": "inventory_review", "inventory_id": source["inventory_ids"][0], "disposition": "reviewed",
                    "text": "Original evidence supports the cited claim.", "question_ids": ["q1"], "source_ids": [source["id"]],
                    "claim_ids": [claim_id]} for source, claim_id in zip(sources, claim_ids)]
        self.sessions.record(research_id, entries=[*reviews, {"kind": "answer", "question_id": "q1", "answer": "All inputs checked.",
            "claim_ids": claim_ids}], batch_id="coverage-and-answer")
        events = self.sessions.status(research_id, section="events")["total"]
        replay = self.sessions.record(research_id, entries=reviews, batch_id="recheck")
        self.assertTrue(all(row["replayed"] for row in replay["results"]))
        self.assertEqual(self.sessions.status(research_id, section="events")["total"], events)
        coverage = self.sessions.coverage(research_id)
        self.assertTrue(coverage["completion_ready"])
        self.assertEqual(coverage["metrics"]["substantive_review"]["count"], 2)
        self.assertEqual(self.sessions.finish(research_id, "All original inputs reviewed.")["status"], "completed")

    def test_large_scope_previews_bound_responses_without_losing_saved_or_paginated_inputs(self):
        self.index_package(3000)
        with BookmarkIndex(self.db) as index:
            manifest = index.inventory(["fixture"])
        all_ids = [row["id"] for row in manifest["entries"]]
        for mode, selected_ids in (("whole", all_ids), ("subset", all_ids[:125])):
            with self.subTest(mode=mode):
                started = self.sessions.start("Review the selected synthetic inputs",
                    [{"id": "q1", "question": "What does each selected input say?"}],
                    source_ids=["fixture"], providers=["exa"], scope_mode=mode,
                    inventory_ids=selected_ids if mode == "subset" else None)
                identifier = started["research_id"]
                path = Path(started["directory"])
                saved = json.loads((path / "state.json").read_text())
                scope = saved["source_scope"]
                omitted_ids = sorted(set(all_ids) - set(selected_ids))
                self.assertEqual(scope["selected_inventory_ids"], selected_ids)
                self.assertEqual(scope["omitted_inventory_ids"], omitted_ids)
                self.assertEqual(json.loads((path / "inventory.json").read_text()), manifest)
                self.assertEqual(json.loads((path / "context.json").read_text())["source_scope"], scope)
                responses = (started, self.sessions.status(identifier),
                             self.sessions.inventory(identifier, limit=1),
                             self.sessions.coverage(identifier, limit=1))
                for response in responses:
                    preview = response["source_scope"]
                    for field in ("selected_inventory_ids", "omitted_inventory_ids", "focus_bookmark_refs"):
                        self.assertEqual(preview[field], scope[field][:20])
                        self.assertEqual(preview[field + "_total"], len(scope[field]))
                        self.assertEqual(preview[field + "_truncated"], len(scope[field]) > 20)
                    self.assertEqual(preview["artifact_path"], str(path / "context.json"))
                    self.assertEqual(preview["artifact_json_pointer"], "/source_scope")
                    self.assertLess(len(json.dumps(preview, ensure_ascii=False)), 5000)
                    self.assertLess(len(json.dumps(response, ensure_ascii=False)),
                                    50000 if "directory" in response else 10000)
                    if "coverage" in response:
                        self.assertEqual(response["coverage"]["source_scope"], preview)
                self.assertEqual(responses[-1]["metrics"]["substantive_review"],
                                 {"count": 0, "total": len(selected_ids), "rate": 0})
                self.assertFalse(responses[-1]["completion_ready"])
                rows, offsets = self.all_rows(identifier)
                self.assertEqual([row["id"] for row in rows], selected_ids)
                self.assertEqual(offsets, list(range(0, len(selected_ids), 100)))
                selected_set = set(selected_ids)
                self.assertEqual(rows, [row for row in manifest["entries"] if row["id"] in selected_set])
                self.assertEqual(self.sessions.inventory(identifier, inventory_ids=selected_ids[-2:])["items"], rows[-2:])
                self.assertEqual(self.sessions.status(identifier, section="inventory",
                    offset=len(selected_ids) - 1, limit=1)["items"], rows[-1:])
                finished = self.sessions.finish(identifier, "Synthetic sources remain unread.", status="incomplete")
                self.assertLess(len(json.dumps(finished, ensure_ascii=False)), 50000)
                for artifact in ("state", "context", "sources", "coverage"):
                    stored = json.loads(Path(finished["artifacts"][artifact]).read_text())
                    self.assertEqual(stored["source_scope"], scope)

    def test_scope_preview_keeps_small_lists_and_marks_the_boundary_for_focus_references(self):
        for count in (20, 21):
            with self.subTest(count=count):
                references = [{"source_id": "fixture", "section_id": "sources", "item_id": "i-" + str(index)}
                              for index in range(count)]
                identifier = self.start(count, bookmark_refs=references)
                result = self.sessions.status(identifier)
                saved = json.loads(Path(result["context_manifest"]).read_text())["source_scope"]
                scope = result["source_scope"]
                for field in ("selected_inventory_ids", "focus_bookmark_refs"):
                    self.assertEqual(scope[field], saved[field][:20])
                    self.assertEqual(scope[field + "_total"], count)
                    self.assertEqual(scope[field + "_truncated"], count > 20)
                self.assertEqual(scope["omitted_inventory_ids"], [])
                self.assertEqual(scope["omitted_inventory_ids_total"], 0)
                self.assertFalse(scope["omitted_inventory_ids_truncated"])

    def test_changed_frozen_manifest_is_rejected(self):
        identifier = self.start()
        manifest = Path(self.sessions.status(identifier)["inventory_manifest"])
        content = json.loads(manifest.read_text())
        content["entries"].pop()
        manifest.write_text(json.dumps(content))
        with self.assertRaisesRegex(ValueError, "inventory hash changed"):
            self.sessions.inventory(identifier)

    def test_scope_default_fetch_budget_covers_207_urls_in_default_reader_groups(self):
        identifier = self.start(207, budget={"max_search_calls": 2})
        state = self.sessions.status(identifier)
        self.assertEqual(state["budget"]["max_search_calls"], 2)
        self.assertEqual(state["budget"]["max_fetch_calls"], 38)
        self.assertEqual(state["initial_fetch_plan"]["minimum_required"], 26)
        self.assertEqual(state["initial_fetch_plan"]["call_shortfall"], 0)
        urls = [row["original_url"] for row in self.all_rows(identifier)[0]]
        calls = 0
        for start in range(0, len(urls), 12):
            group = urls[start:start + 12]
            for offset in range(0, len(group), 8):
                self.sessions.fetch(identifier, "group-read-" + str(calls), "q1", group[offset:offset + 8])
                calls += 1
        self.assertEqual(calls, 35)
        self.assertEqual(self.sessions.status(identifier)["counts"]["sources"], 207)
        self.assertEqual(self.engine.fetch.call_count, calls)
        self.assertEqual(self.sessions.coverage(identifier)["metrics"]["substantive_review"]["count"], 0)

    def test_explicit_insufficient_budget_is_preserved_and_disclosed_without_narrowing(self):
        identifier = self.start(207, budget={"max_fetch_calls": 12})
        state = self.sessions.status(identifier)
        self.assertEqual(state["budget"]["max_fetch_calls"], 12)
        self.assertEqual(state["initial_fetch_plan"]["budget_source"], "explicit")
        self.assertEqual(state["initial_fetch_plan"]["minimum_required"], 26)
        self.assertEqual(state["initial_fetch_plan"]["call_shortfall"], 14)
        self.assertEqual(state["initial_fetch_plan"]["urls_beyond_capacity"], 111)
        self.assertEqual(state["source_scope"]["selected_url_count"], 207)
        finished = self.sessions.finish(identifier, "Insufficient caller budget; scope retained.", status="incomplete")
        report = Path(finished["artifacts"]["report"]).read_text()
        self.assertIn("minimum_required=26", report)
        self.assertIn("call_shortfall=14", report)

    def test_hard_fetch_limit_reports_gap_and_keeps_all_641_inputs(self):
        identifier = self.start(641)
        state = self.sessions.status(identifier)
        self.assertEqual(state["budget"]["max_fetch_calls"], 80)
        self.assertEqual(state["initial_fetch_plan"]["minimum_required"], 81)
        self.assertEqual(state["initial_fetch_plan"]["call_shortfall"], 1)
        self.assertEqual(state["initial_fetch_plan"]["urls_beyond_capacity"], 1)
        self.assertEqual(len(self.all_rows(identifier)[0]), 641)
        self.assertEqual(state["source_scope"]["omitted_inventory_ids"], [])

    def test_accounting_and_failed_fetches_do_not_satisfy_substantive_coverage(self):
        identifier = self.start()
        response = self.fetch_response([self.url(0), self.url(1)], "exa", False, 12000)
        response["result"]["structuredContent"]["results"][1] = {"url": self.url(1), "error": "Synthetic retrieval failure"}
        self.engine.fetch.side_effect = None
        self.engine.fetch.return_value = response
        fetched = self.sessions.fetch(identifier, "partial-read", "q1", [self.url(0), self.url(1)])["sources"]
        initial = self.sessions.coverage(identifier)
        self.assertEqual(initial["metrics"]["accounted_for"]["count"], 2)
        self.assertEqual(initial["metrics"]["usable_text"]["count"], 0)
        self.assertEqual(initial["metrics"]["substantive_review"]["count"], 0)
        claim_id = self.review(identifier, fetched[0])
        failed_id = fetched[1]["inventory_ids"][0]
        with self.assertRaises(ValueError):
            self.sessions.record(identifier, {"kind": "inventory_review", "inventory_id": failed_id,
                "disposition": "reviewed", "text": "Cannot substantiate this failed page.", "question_ids": ["q1"],
                "source_ids": [fetched[1]["id"]], "claim_ids": [claim_id]})
        self.sessions.record(identifier, {"kind": "inventory_review", "inventory_id": failed_id,
            "disposition": "blocked", "text": "Synthetic retrieval failed; no body exists."})
        self.sessions.record(identifier, {"kind": "answer", "question_id": "q1", "answer": "One page was checked.", "claim_ids": [claim_id]})
        coverage = self.sessions.coverage(identifier)
        self.assertEqual(coverage["metrics"]["accounted_for"]["rate"], 1)
        self.assertEqual(coverage["metrics"]["substantive_review"]["rate"], 0.5)
        self.assertEqual(coverage["metrics"]["question_completion"]["rate"], 1)
        self.assertFalse(coverage["completion_ready"])
        with self.assertRaisesRegex(ValueError, "coverage incomplete"):
            self.sessions.finish(identifier, "A failed page must keep this incomplete.")

    def test_all_exclusions_cannot_complete_even_with_an_answer_from_other_evidence(self):
        identifier = self.start()
        for row in self.all_rows(identifier)[0]:
            self.sessions.record(identifier, {"kind": "inventory_review", "inventory_id": row["id"],
                "disposition": "excluded", "reason_code": "out_of_scope", "text": "Synthetic exclusion for this gate test."})
        source = self.sessions.fetch(identifier, "other-evidence", "q1", ["https://other.example.test/evidence"])["sources"][0]
        claim_id = self.review(identifier, source)
        self.sessions.record(identifier, {"kind": "answer", "question_id": "q1", "answer": "Other evidence is available.", "claim_ids": [claim_id]})
        coverage = self.sessions.coverage(identifier)
        self.assertEqual(coverage["difference_counts"]["excluded"], 2)
        self.assertEqual(coverage["difference_counts"]["unread"], 0)
        self.assertEqual(coverage["metrics"]["accounted_for"]["rate"], 1)
        self.assertFalse(coverage["completion_ready"])
        with self.assertRaisesRegex(ValueError, "No original input"):
            self.sessions.finish(identifier, "Excluding everything is not complete research.")

    def test_review_retraction_requires_revised_grounding_before_completion(self):
        identifier = self.start()
        sources, claims = self.review_all(identifier)
        self.assertTrue(self.sessions.coverage(identifier)["completion_ready"])
        self.sessions.record(identifier, {"kind": "retraction", "claim_id": claims[0], "text": "Recheck this claim."})
        coverage = self.sessions.coverage(identifier)
        self.assertFalse(coverage["completion_ready"])
        self.assertEqual(coverage["metrics"]["substantive_review"]["count"], 1)
        revised = self.review(identifier, sources[0])
        self.sessions.record(identifier, {"kind": "answer", "question_id": "q1", "answer": "Revised answer after rechecking.",
            "claim_ids": [claims[1], revised]})
        finished = self.sessions.finish(identifier, "All original inputs have accepted, quoted reviews.")
        self.assertEqual(finished["status"], "completed")
        self.assertTrue(Path(finished["artifacts"]["coverage"]).is_file())

    def test_wrong_page_and_imported_report_do_not_establish_original_page_coverage(self):
        identifier = self.start(1)
        inventory_id = self.all_rows(identifier)[0][0]["id"]
        wrong = self.sessions.fetch(identifier, "wrong-page", "q1", ["https://other.example.test/wrong"])["sources"][0]
        report = self.sessions.import_evidence(identifier, "secondary-report", "q1", "https://reports.example.test/run",
            "A secondary report cites the original page.", {"kind": "external_report", "provider": "fixture"},
            inventory_ids=[inventory_id])["sources"][0]
        for source in (wrong, report):
            with self.subTest(kind=source["evidence_kind"]):
                claim_id = self.review(identifier, source)
                with self.assertRaises(ValueError):
                    self.sessions.record(identifier, {"kind": "inventory_review", "inventory_id": inventory_id,
                        "disposition": "reviewed", "text": "This evidence is not the original page.", "question_ids": ["q1"],
                        "source_ids": [source["id"]], "claim_ids": [claim_id]})
        coverage = self.sessions.coverage(identifier)
        self.assertEqual(coverage["difference_counts"]["unread"], 1)
        self.assertEqual(coverage["metrics"]["substantive_review"]["count"], 0)

    def test_coverage_rechecks_the_saved_body_hash(self):
        identifier = self.start(1)
        sources, _ = self.review_all(identifier)
        directory = Path(self.sessions.status(identifier)["directory"])
        (directory / sources[0]["body_file"]).write_text("Changed after review.")
        coverage = self.sessions.coverage(identifier)
        self.assertEqual(coverage["metrics"]["usable_text"]["count"], 0)
        self.assertEqual(coverage["metrics"]["substantive_review"]["count"], 0)
        self.assertFalse(coverage["completion_ready"])
        with self.assertRaises(ValueError):
            self.sessions.finish(identifier, "Tampered evidence cannot complete.")

    def test_provider_placeholder_can_resolve_without_recreating_the_run(self):
        identifier = self.start(1)
        self.review_all(identifier)
        for index, (provider, prefix, status) in enumerate((provider, prefix, status)
                for provider, prefix in (("openai", "resp_"), ("parallel", "trun_"))
                for status in ("prepared", "pending", "unknown_outcome")):
            reference = "er-" + format(index, "024x")
            entry = {"kind": "external_run", "id": reference, "provider": provider, "run_id": reference,
                     "status": status, "text": "Observed provider placeholder."}
            self.sessions.record(identifier, entry)
            if status != "prepared":
                self.assertFalse(self.sessions.coverage(identifier)["completion_ready"])
                with self.assertRaisesRegex(ValueError, "cannot return to prepared"):
                    self.sessions.record(identifier, {**entry, "status": "prepared"})
            for invalid_id in ("resp_wrong" if provider == "parallel" else "trun_wrong", "arbitrary", "../resp_bad"):
                with self.assertRaisesRegex(ValueError, "another provider or run_id"):
                    self.sessions.record(identifier, {**entry, "run_id": invalid_id, "status": "completed"})
            real_id = prefix + "fixture_" + str(index)
            self.sessions.record(identifier, {**entry, "run_id": real_id, "status": "completed"})
            with self.assertRaisesRegex(ValueError, "another provider or run_id"):
                self.sessions.record(identifier, {**entry, "run_id": real_id + "_changed", "status": "completed"})
        self.assertTrue(self.sessions.coverage(identifier)["completion_ready"])

    def test_real_provider_id_and_noncanonical_placeholder_are_never_reassigned(self):
        identifier = self.start(1)
        for reference, run_id, status in (("er-" + "f" * 24, "resp_known", "prepared"),
                                          ("custom-reference", "custom-reference", "unknown_outcome")):
            entry = {"kind": "external_run", "id": reference, "provider": "openai", "run_id": run_id,
                     "status": status, "text": "Existing run identity."}
            self.sessions.record(identifier, entry)
            with self.assertRaisesRegex(ValueError, "another provider or run_id"):
                self.sessions.record(identifier, {**entry, "run_id": "resp_replacement", "status": "completed"})


if __name__ == "__main__":
    unittest.main()
