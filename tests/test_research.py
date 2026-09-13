"""Observable research lifecycle, budget, resumption and citation fidelity."""

import concurrent.futures
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from research import ResearchSessions
from settings import Settings


class ResearchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="research tests 中文 ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.settings = Settings(self.base / "settings.json")
        self.engine = Mock()
        self.engine.search.side_effect = self.search_response
        self.engine.fetch.side_effect = self.fetch_response
        self.sessions = ResearchSessions(self.base / "research", settings=self.settings, engine=self.engine,
                                         db_path=self.base / "index.sqlite3")

    @staticmethod
    def search_response(targets, providers, limit_per_target):
        return {"successful_provider_count": len(providers), "usage": {"tool_calls": len(targets) * len(providers)},
                "batches": [{"provider": provider, "target": target["target"], "query": target["query"],
                             "status": "ok", "results": [{"url": "https://example.test/docs", "snippet": "Discovery only"}]}
                            for provider in providers for target in targets]}

    @staticmethod
    def fetch_response(urls, provider, archive, max_characters):
        return {"provider": provider, "urls": urls, "tool": "web_fetch", "request_arguments": {"urls": urls},
                "requested_max_characters": max_characters, "retrieved_at": "2026-09-10T00:00:00Z",
                "usage": {"tool_calls": 1}, "result": {"structuredContent": {"results": [
                    {"url": url, "title": "Actual document", "text": "Current docs: the service supports search and fetch.\nCalls may return partial excerpts."}
                    for url in urls]}}}

    def start(self, **kwargs):
        options = {"brief": "Compare retrieval with research", "questions": [{"id": "q1", "question": "What is supported?"}],
                   "providers": ["exa", "parallel"]}
        options.update(kwargs)
        return self.sessions.start(**options)["research_id"]

    def fetch(self, research_id, operation_id="read-1", **kwargs):
        return self.sessions.fetch(research_id, operation_id, "q1", ["https://example.test/docs"], **kwargs)

    def claim(self, research_id, source_id="s1", quote="the service supports search and fetch", **kwargs):
        entry = {"kind": "claim", "question_id": "q1", "statement": "The service exposes retrieval.",
                 "citations": [{"source_id": source_id, "quote": quote}]}
        entry.update(kwargs)
        return self.sessions.record(research_id, entry)["recorded"]["id"]

    def answer(self, research_id, claim_ids=None):
        return self.sessions.record(research_id, {"kind": "answer", "question_id": "q1",
            "answer": "Search and fetch are supported.", "claim_ids": claim_ids or ["c1"]})

    def test_status_is_offline_and_start_keeps_private_scope_out_of_queries(self):
        self.assertEqual(self.sessions.status()["sessions"], [])
        self.assertFalse(self.sessions.directory.exists())
        from bookmark_index import BookmarkIndex
        from test_bookmark_index import make_package
        package = self.base / "private canvas"
        make_package(package)
        with BookmarkIndex(self.sessions.db_path) as index:
            index.sync(package, "my-private-canvas")
        research_id = self.start(scope="PRIVATE_NOTE must stay local", source_ids=["my-private-canvas"])
        self.engine.search.assert_not_called()
        self.assertFalse((self.base / "settings.json").exists())
        self.sessions.search(research_id, "search-1", [{"question_id": "q1", "query": "public docs"}])
        self.assertNotIn("PRIVATE_NOTE", str(self.engine.search.call_args))
        self.assertNotIn("my-private-canvas", str(self.engine.search.call_args))
        self.assertEqual(len(self.sessions.status()["sessions"]), 1)

    def test_invalid_briefs_budgets_and_questions_create_nothing(self):
        cases = [{"brief": " "}, {"questions": []},
                 {"questions": [{"id": "q", "question": "A"}, {"id": "q", "question": "B"}]},
                 {"budget": {"max_fetch_calls": True}}, {"budget": {"max_rounds": -1}},
                 {"budget": {"max_rounds": 41}}, {"budget": {"model": "invented"}},
                 {"providers": ["exa", "exa"]}, {"providers": ["unknown"]},
                 {"source_ids": [None]}, {"scope": None}]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.start(**options)
        self.assertFalse(self.sessions.directory.exists())

    def test_search_idempotency_persists_across_process_objects(self):
        research_id = self.start()
        queries = [{"question_id": "q1", "query": "official docs"}]
        first = self.sessions.search(research_id, "round1-search", queries)
        reopened = ResearchSessions(self.sessions.directory, settings=self.settings, engine=self.engine)
        second = reopened.search(research_id, "round1-search", queries)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(first["result"], second["result"])
        self.assertEqual(self.engine.search.call_count, 1)
        self.assertEqual(reopened.status(research_id)["usage"], {"search_calls": 2, "fetch_calls": 0, "rounds": 1})
        with self.assertRaisesRegex(ValueError, "different arguments"):
            reopened.search(research_id, "round1-search", [{"question_id": "q1", "query": "changed"}])

    def test_unique_queries_reserve_per_provider_and_budget_blocks_before_network(self):
        research_id = self.start(budget={"max_search_calls": 2, "max_rounds": 1})
        query = {"question_id": "q1", "query": "official docs"}
        self.sessions.search(research_id, "first", [query, query])
        before = self.sessions.status(research_id)
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.sessions.search(research_id, "second", [query])
        self.assertEqual(self.engine.search.call_count, 1)
        self.assertEqual(before, self.sessions.status(research_id))

    def test_failed_network_keeps_reservation_and_is_not_automatically_retried(self):
        research_id = self.start(budget={"max_fetch_calls": 1})
        self.engine.fetch.side_effect = RuntimeError("MCP HTTP 429")
        result = self.fetch(research_id)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.sessions.status(research_id)["usage"]["fetch_calls"], 1)
        self.assertTrue(self.fetch(research_id)["replayed"])
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.fetch(research_id, "retry-explicit")
        self.assertEqual(self.engine.fetch.call_count, 1)

    def test_partial_provider_failures_retain_actual_batches(self):
        research_id = self.start()
        self.engine.search.side_effect = None
        self.engine.search.return_value = {"successful_provider_count": 1, "batches": [
            {"provider": "exa", "status": "ok", "results": [{"url": "https://example.test/docs"}]},
            {"provider": "parallel", "status": "error", "error_kind": "authentication", "results": []}]}
        result = self.sessions.search(research_id, "partial", [{"question_id": "q1", "query": "docs"}])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["result"]["batches"][1]["error_kind"], "authentication")
        state = self.sessions.status(research_id)
        receipt = Path(state["directory"]) / state["operations"][0]["result_file"]
        self.assertEqual(json.loads(receipt.read_text())["result"], self.engine.search.return_value)
        self.assertEqual(state["sources"], [])
        with self.assertRaises(ValueError):
            self.claim(research_id)

    def test_jina_reserves_each_url_before_network_and_replays_without_resubmission(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        limited = self.start(providers=["jina"], budget={"max_fetch_calls": 1})
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.sessions.fetch(limited, "too-many", "q1", urls)
        self.engine.fetch.assert_not_called()

        research_id = self.start(providers=["exa", "jina", "parallel"], budget={"max_fetch_calls": 3})
        def fetch(urls, provider, archive, max_characters):
            result = self.fetch_response(urls, provider, archive, max_characters)
            if provider == "exa":
                result["result"] = {"structuredContent": {"results": []}}
            else:
                self.assertEqual(provider, "jina")
                state = self.sessions.status(research_id)
                self.assertEqual(state["usage"]["fetch_calls"], 3)
                result["usage"]["tool_calls"] = len(urls)
            return result
        self.engine.fetch.side_effect = fetch
        result = self.sessions.fetch(research_id, "bounded", "q1", urls)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["usage"]["tool_calls"], 3)
        self.assertEqual([call.kwargs["provider"] for call in self.engine.fetch.call_args_list], ["exa", "jina"])
        self.assertTrue(self.sessions.fetch(research_id, "bounded", "q1", urls)["replayed"])
        self.assertEqual(self.engine.fetch.call_count, 2)

    def test_new_session_freezes_separate_fetch_defaults_and_old_session_keeps_its_providers(self):
        research_id = self.start(providers=None)
        current = self.sessions.status(research_id)
        self.assertEqual(current["providers"], ["exa", "parallel"])
        self.assertEqual(current["search_fallback_providers"], ["tavily", "jina"])
        self.assertEqual(current["fetch_providers"], ["exa", "parallel", "jina"])
        self.settings.update({"fetch": {"provider": "tavily", "providers": ["tavily"]}})
        self.assertEqual(self.sessions.status(research_id)["fetch_providers"], current["fetch_providers"])
        path, state = self.sessions._load(research_id)
        state.pop("fetch_providers")  # An existing pre-upgrade session.
        state.pop("search_fallback_providers")
        self.sessions._save(path, state)
        self.assertEqual(self.sessions.status(research_id)["fetch_providers"], ["exa", "parallel"])
        self.assertEqual(self.sessions.status(research_id)["search_fallback_providers"], [])

    def test_search_fallback_budget_is_durable_partial_and_replay_keeps_frozen_routes(self):
        from web_search import SearchProviders
        self.sessions.engine = SearchProviders(settings=self.settings)
        research_id = self.start(providers=None, budget={"max_search_calls": 5})
        queries = [{"question_id": "q1", "query": query} for query in ("first", "second")]
        calls = []

        def execute(provider, purpose, query, limit):
            calls.append((provider, query))
            rows = []
            if provider == "tavily":
                saved = json.loads((self.sessions.directory / research_id / "state.json").read_text())
                self.assertEqual(saved["usage"]["search_calls"], 5)
                self.assertEqual(saved["operations"][0]["reserved"]["search_calls"], 5)
                self.assertEqual(saved["operations"][0]["status"], "pending")
                self.assertEqual(query, "first")
                rows = [{"url": "https://example.test/recovered"}]
            return {"status": "ok", "result": {"structuredContent": {"results": rows}},
                    "usage": {**SearchProviders._empty_usage(), "tool_calls": 1}}

        with patch.dict("os.environ", {"JINA_API_KEY": ""}), \
                patch.object(self.sessions.engine, "_execute", side_effect=execute):
            first = self.sessions.search(research_id, "with-fallback", queries)
            self.settings.update({"search": {"fallback_providers": []}})
            replay = self.sessions.search(research_id, "with-fallback", queries)
        self.assertEqual(len(calls), 5)
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["result"], replay["result"])
        self.assertEqual(first["result"]["unresolved_queries"], [{"target": "q1", "query": "second"}])
        self.assertEqual(first["result"]["remaining_attempts"],
                         [{"provider": "tavily", "target": "q1", "query": "second", "reason": "budget"}])
        self.assertEqual(self.sessions.status(research_id)["usage"]["rounds"], 1)
        self.assertEqual(self.sessions.status(research_id)["search_fallback_providers"], ["tavily", "jina"])

    def test_structured_transport_failure_and_archive_error_keep_receipts(self):
        research_id = self.start()
        self.engine.fetch.side_effect = None
        self.engine.fetch.return_value = {"status": "error", "error": "MCP HTTP 401", "error_kind": "authentication",
                                          "usage": {"tool_calls": 0}, "retryable": False}
        failure = self.fetch(research_id, "unauthenticated", provider="exa")
        self.assertEqual(failure["error_kind"], "authentication")
        self.assertEqual(self.sessions.status(research_id)["operations"][0]["status"], "error")
        self.engine.fetch.return_value = self.fetch_response(["https://example.test/docs"], "exa", False, 12000)
        with patch("research.SourceArchive.save", side_effect=ValueError("archive failed")):
            failure = self.fetch(research_id, "archive-failed")
        self.assertEqual(failure["error_kind"], "archive_error")
        self.assertEqual(failure["provider_outcome"]["result"], self.engine.fetch.return_value["result"])
        self.assertTrue(self.fetch(research_id, "archive-failed")["replayed"])
        self.assertEqual(self.engine.fetch.call_count, 2)

    def test_waterfall_reserves_only_available_budget_and_preserves_each_response(self):
        research_id = self.start(providers=["exa", "parallel", "tavily"], budget={"max_fetch_calls": 2})
        urls = ["https://example.test/good", "https://example.test/failed"]
        raw_responses = {}

        def fetch(urls, provider, archive, max_characters):
            result = self.fetch_response(urls, provider, archive, max_characters)
            if provider == "exa":
                result["result"]["structuredContent"]["results"].pop()
                result["result"]["structuredContent"]["errors"] = [{"url": urls[-1], "error": "Timeout"}]
            else:
                self.assertEqual(provider, "parallel")
                self.assertEqual(urls, ["https://example.test/failed"])
                persisted = json.loads((self.sessions.directory / research_id / "state.json").read_text())
                self.assertEqual(persisted["usage"]["fetch_calls"], 2)
                self.assertEqual(persisted["operations"][0]["reserved"]["fetch_calls"], 2)
                self.assertEqual(persisted["operations"][0]["status"], "pending")
            raw_responses[provider] = result["result"]
            return result

        self.engine.fetch.side_effect = fetch
        result = self.sessions.fetch(research_id, "waterfall", "q1", urls)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["usage"]["tool_calls"], 2)
        self.assertEqual([source["provider"] for source in result["sources"]], ["exa", "exa", "parallel"])
        for source in result["sources"]:
            raw = json.loads((self.sessions.directory / research_id / source["response_file"]).read_text())
            self.assertEqual(raw, raw_responses[source["provider"]])
        reopened = ResearchSessions(self.sessions.directory, settings=self.settings, engine=self.engine)
        self.assertTrue(reopened.fetch(research_id, "waterfall", "q1", urls)["replayed"])
        self.assertEqual(self.engine.fetch.call_count, 2)
        self.assertEqual(reopened.status(research_id)["usage"]["fetch_calls"], 2)

    def test_waterfall_budget_stop_keeps_remaining_providers_visible(self):
        research_id = self.start(budget={"max_fetch_calls": 1})
        self.engine.fetch.side_effect = None
        self.engine.fetch.return_value = {"status": "error", "error": "Timed out", "error_kind": "timeout"}
        result = self.fetch(research_id)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["unresolved_urls"], ["https://example.test/docs"])
        self.assertEqual(result["remaining_providers"], ["parallel"])
        self.assertEqual(self.engine.fetch.call_count, 1)
        self.assertEqual(self.sessions.status(research_id)["usage"]["fetch_calls"], 1)

    def test_waterfall_interruption_keeps_group_reservation_without_resubmitting(self):
        research_id = self.start(providers=["exa", "parallel", "tavily"], budget={"max_fetch_calls": 3})

        def interrupted(urls, provider, archive, max_characters):
            if provider == "exa":
                return {"status": "error", "error_kind": "timeout"}
            persisted = json.loads((self.sessions.directory / research_id / "state.json").read_text())
            self.assertEqual(persisted["usage"]["fetch_calls"], 3)
            self.assertEqual(len(persisted["operations"][0]["fallback_attempts"]), 2)
            raise SystemExit("Simulated interruption after reservation")

        self.engine.fetch.side_effect = interrupted
        with self.assertRaises(SystemExit):
            self.fetch(research_id)
        calls = self.engine.fetch.call_count
        reopened = ResearchSessions(self.sessions.directory, settings=self.settings, engine=self.engine)
        result = reopened.fetch(research_id, "read-1", "q1", ["https://example.test/docs"])
        self.assertTrue(result["replayed"])
        self.assertEqual(result["operation"]["status"], "pending")
        self.assertEqual(reopened.status(research_id)["usage"]["fetch_calls"], 3)
        self.assertEqual(self.engine.fetch.call_count, calls)

    def test_legacy_single_provider_receipt_replays_without_adding_fallbacks(self):
        research_id = self.start()
        self.engine.fetch.side_effect = None
        self.engine.fetch.return_value = {"status": "error", "error_kind": "timeout"}
        self.fetch(research_id, provider="exa")
        self.assertTrue(self.fetch(research_id)["replayed"])
        self.assertEqual(self.engine.fetch.call_count, 1)

    def test_fetch_archives_raw_response_and_paginates_verified_extract(self):
        self.settings.update({"archive": {"enabled": False}})
        research_id = self.start()
        result = self.fetch(research_id)
        source = result["sources"][0]
        path = Path(self.sessions.status(research_id)["directory"])
        raw = json.loads((path / source["response_file"]).read_text())
        self.assertEqual(raw["structuredContent"]["results"][0]["url"], source["url"])
        self.assertEqual(self.engine.fetch.call_args.kwargs["archive"], False)
        first = self.sessions.source(research_id, source["id"], limit=8)
        second = self.sessions.source(research_id, source["id"], offset=first["next_offset"], limit=50000)
        self.assertEqual(first["text"] + second["text"], raw["structuredContent"]["results"][0]["text"])
        self.assertIsNone(second["next_offset"])
        self.assertEqual(source["completeness"], "unknown")
        self.assertIsNone(source["published_at"])
        self.assertTrue(self.fetch(research_id)["replayed"])
        self.assertEqual(self.engine.fetch.call_count, 1)

    def test_completed_receipt_recovers_sources_after_checkpoint_failure(self):
        research_id = self.start()
        save = self.sessions._save
        saves = 0

        def fail_checkpoint(path, state):
            nonlocal saves
            saves += 1
            if saves == 2:
                raise OSError("Simulated state checkpoint failure")
            save(path, state)

        with patch.object(self.sessions, "_save", side_effect=fail_checkpoint):
            with self.assertRaisesRegex(OSError, "checkpoint"):
                self.fetch(research_id)
        state_path = self.sessions.directory / research_id / "state.json"
        persisted = json.loads(state_path.read_text())
        self.assertEqual(persisted["operations"][0]["status"], "pending")
        self.assertEqual(persisted["sources"], [])

        reopened = ResearchSessions(self.sessions.directory, settings=self.settings, engine=self.engine)
        recovered = reopened.status(research_id)
        self.assertEqual(recovered["operations"][0]["status"], "ok")
        self.assertEqual([source["id"] for source in recovered["sources"]], ["s1"])
        self.assertIn("the service supports search and fetch", reopened.source(research_id, "s1")["text"])
        replay = reopened.fetch(research_id, "read-1", "q1", ["https://example.test/docs"])
        self.assertTrue(replay["replayed"])
        self.assertNotIn("_commit", replay)
        self.assertEqual(self.engine.fetch.call_count, 1)

        following = reopened.fetch(research_id, "read-2", "q1", ["https://example.test/next"])
        self.assertEqual(following["sources"][0]["id"], "s2")
        self.assertEqual(self.engine.fetch.call_count, 2)
        persisted = json.loads(state_path.read_text())
        self.assertEqual([source["id"] for source in persisted["sources"]], ["s1", "s2"])
        self.assertEqual(persisted["usage"]["fetch_calls"], 2)

    def test_quotes_must_exist_in_successfully_fetched_untampered_sources(self):
        research_id = self.start()
        self.fetch(research_id)
        with self.assertRaisesRegex(ValueError, "absent"):
            self.claim(research_id, quote="A plausible claim missing from the page")
        self.assertEqual(self.sessions.status(research_id)["claims"], [])
        self.claim(research_id)
        source = self.sessions.status(research_id)["sources"][0]
        path = Path(self.sessions.status(research_id)["directory"]) / source["body_file"]
        path.write_text("altered")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.sessions.source(research_id, "s1")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.sessions.finish(research_id, "Partial report", status="incomplete")

    def test_source_identity_rejection_retracts_support_and_requires_revised_answer(self):
        research_id = self.start()
        self.fetch(research_id)
        self.claim(research_id)
        self.answer(research_id)
        self.sessions.record(research_id, {"kind": "source_review", "source_id": "s1", "verdict": "rejected",
            "text": "Provider text describes another site despite the requested URL."})
        self.assertEqual(self.sessions.status(research_id)["questions"][0]["status"], "unresolved")
        with self.assertRaisesRegex(ValueError, "rejected"):
            self.claim(research_id)
        with self.assertRaisesRegex(ValueError, "rejected"):
            self.answer(research_id)
        self.sessions.record(research_id, {"kind": "retraction", "claim_id": "c1", "text": "Source identity was wrong."})
        with self.assertRaisesRegex(ValueError, "Retracted"):
            self.answer(research_id)
        self.fetch(research_id, "new-page")
        self.sessions.record(research_id, {"kind": "source_review", "source_id": "s2", "verdict": "accepted",
            "text": "Title, subject and origin match the requested document."})
        self.claim(research_id, source_id="s2")
        self.answer(research_id, ["c2"])
        finished = self.sessions.finish(research_id, "Revised conclusion from the matching document.")
        report = Path(finished["artifacts"]["report"]).read_text()
        self.assertIn("status: retracted", report)
        self.assertIn("### Claim c1\n", report)
        self.assertIn("### Claim c2\n", report)
        historical_claim = report.split("### Claim c1\n", 1)[1].split("### Claim c2\n", 1)[0]
        self.assertIn("Retracted: Source identity was wrong.", historical_claim)
        self.assertIn("> the service supports search and fetch", historical_claim)
        self.assertNotIn("[^c1]:", report)
        self.assertIn("Content review: rejected", report)
        self.assertEqual(finished["questions"][0]["claim_ids"], ["c2"])

    def test_explicit_subset_context_preserves_duplicates_and_focus_does_not_narrow_whole_scope(self):
        from bookmark_index import BookmarkIndex
        from test_bookmark_index import make_package
        package = self.base / "user canvas"
        make_package(package)
        database = self.base / "derived" / "index.sqlite3"
        with BookmarkIndex(database) as index:
            index.sync(package, "fixture")
            rows = index.search("fixture", targets=["https://example.test/alpha"])["results"]
        self.sessions.db_path = database
        refs = [{key: row[key] for key in ("source_id", "section_id", "item_id")} for row in rows]
        whole_id = self.start(bookmark_refs=refs)
        whole = self.sessions.status(whole_id)
        self.assertEqual(whole["source_scope"]["mode"], "whole")
        self.assertEqual(whole["source_scope"]["selected_url_count"], 4)
        self.assertEqual(whole["source_scope"]["selected_instance_count"], 5)
        research_id = self.start(bookmark_refs=refs, scope_mode="subset")
        current = self.sessions.status(research_id)
        self.assertEqual(current["source_scope"]["mode"], "subset")
        self.assertEqual(current["source_scope"]["selected_url_count"], 1)
        self.assertEqual(len(current["source_scope"]["omitted_inventory_ids"]), 3)
        self.assertEqual(len(current["bookmark_context"]), 2)
        context = json.loads(Path(current["context_manifest"]).read_text())
        self.assertEqual(len(context["bookmarks"]), 2)
        for bookmark in context["bookmarks"]:
            self.assertNotIn("note", bookmark)
            self.assertNotIn("tags", bookmark)
            self.assertNotIn("raw_json", bookmark)
        self.assertTrue(context["bookmarks"][0]["edges"])
        fetched = self.sessions.fetch(research_id, "linked-page", "q1", ["https://example.test/alpha"])
        self.assertEqual(fetched["sources"][0]["bookmark_refs"], refs)
        self.assertNotIn("fixture", str(self.engine.fetch.call_args))
        self.assertNotIn("公司", str(self.engine.fetch.call_args))
        with self.assertRaises(ValueError):
            self.start(bookmark_refs=[{"source_id": "fixture", "section_id": "missing", "item_id": rows[0]["item_id"]}])

    def test_failed_fetch_and_snippets_cannot_be_cited_as_page_evidence(self):
        research_id = self.start()
        result = self.fetch_response(["https://example.test/docs"], "tavily", False, 12000)
        result["result"] = {"structuredContent": {"results": [
            {"url": "https://example.test/docs", "snippet": "a search snippet"}],
            "failed_results": [{"url": "https://example.test/docs", "error": "Unavailable"}]}}
        self.engine.fetch.side_effect = None
        self.engine.fetch.return_value = result
        fetched = self.fetch(research_id, provider="tavily")
        self.assertEqual(fetched["status"], "error")
        self.assertEqual(fetched["sources"][0]["extraction_status"], "provider_error")
        with self.assertRaisesRegex(ValueError, "no extracted"):
            self.claim(research_id, quote="a search snippet")

    def test_iterative_questions_conflict_resolution_and_final_artifact(self):
        research_id = self.start()
        self.sessions.search(research_id, "round-1", [{"question_id": "q1", "query": "search API"}])
        self.fetch(research_id)
        self.claim(research_id)
        self.answer(research_id)
        self.sessions.record(research_id, {"kind": "question", "id": "q2", "question": "Is content complete?"})
        self.sessions.record(research_id, {"kind": "gap", "question_id": "q2", "text": "Need extraction limits."})
        with self.assertRaisesRegex(ValueError, "Unanswered"):
            self.sessions.finish(research_id, "Premature report")
        self.sessions.search(research_id, "round-2", [{"question_id": "q2", "query": "official extraction limitations"}])
        self.sessions.fetch(research_id, "read-2", "q2", ["https://example.test/limits"], provider="parallel")
        self.sessions.record(research_id, {"kind": "claim", "question_id": "q2", "statement": "Extracts may be partial.",
            "citations": [{"source_id": "s2", "quote": "Calls may return partial excerpts."}], "confidence": "high"})
        self.sessions.record(research_id, {"kind": "answer", "question_id": "q2", "answer": "Completeness is unknown.", "claim_ids": ["c2"]})
        self.sessions.record(research_id, {"kind": "conflict", "claim_ids": ["c1", "c2"], "text": "Does fetch imply a complete page?"})
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.sessions.finish(research_id, "Premature report")
        self.sessions.record(research_id, {"kind": "resolution", "conflict_id": "x1", "claim_ids": ["c2"],
            "text": "Support for fetch does not imply complete extraction."})
        finished = self.sessions.finish(research_id, "Retrieval supports research; content may be partial.",
            limitations=["This synthetic fixture does not assert any real provider behavior."])
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["usage"], {"search_calls": 4, "fetch_calls": 2, "rounds": 2})
        report = Path(finished["artifacts"]["report"]).read_text()
        self.assertIn("[c1](#claim-c1)", report)
        self.assertIn("[c2](#claim-c2)", report)
        self.assertIn("https://example.test/limits", report)
        self.assertIn("unknown completeness", report)
        self.assertIn("Support for fetch", report)
        manifest = json.loads(Path(finished["artifacts"]["sources"]).read_text())
        self.assertEqual(len(manifest["claims"]), 2)
        self.assertEqual(manifest["conflicts"][0]["status"], "resolved")
        with self.assertRaisesRegex(ValueError, "closed"):
            self.fetch(research_id, "read-after-finish")

    def test_incomplete_and_cancelled_report_do_not_invent_answers(self):
        for status in ("incomplete", "cancelled"):
            with self.subTest(status=status):
                research_id = self.start(budget={"max_search_calls": 0, "max_fetch_calls": 0})
                self.sessions.record(research_id, {"kind": "gap", "question_id": "q1", "text": "No retrieval budget."})
                result = self.sessions.finish(research_id, "No verified conclusion.", status=status)
                text = Path(result["artifacts"]["report"]).read_text()
                self.assertIn("No supported answer recorded", text)
                self.assertIn("No retrieval budget", text)
                self.assertEqual(result["claims"], [])

    def test_incomplete_report_resumes_with_prior_evidence_budget_and_report_preserved(self):
        research_id = self.start(budget={"max_fetch_calls": 2})
        self.fetch(research_id)
        self.claim(research_id)
        self.sessions.record(research_id, {"kind": "gap", "question_id": "q1", "text": "Need a follow-up source."})
        incomplete = self.sessions.finish(research_id, "Evidence collected; answer still pending.", status="incomplete")
        original = {key: Path(value).read_bytes() for key, value in incomplete["artifacts"].items()}
        reopened = ResearchSessions(self.sessions.directory, settings=self.settings, engine=self.engine)
        resumed = reopened.record(research_id, {"kind": "resume", "text": "The missing follow-up is now available."})
        current = reopened.status(research_id)
        self.assertEqual(current["status"], "active")
        self.assertEqual(current["usage"], incomplete["usage"])
        self.assertEqual(current["budget"], incomplete["budget"])
        self.assertEqual(current["questions"][0]["gap"], "Need a follow-up source.")
        self.assertIsNone(current["artifacts"])
        self.assertEqual(self.engine.fetch.call_count, 1)
        self.assertTrue(reopened.fetch(research_id, "read-1", "q1", ["https://example.test/docs"])["replayed"])
        following = reopened.fetch(research_id, "read-followup", "q1", ["https://example.test/followup"])
        self.assertEqual(following["sources"][0]["id"], "s2")
        reopened.record(research_id, {"kind": "answer", "question_id": "q1", "answer": "Retrieval confirmed.", "claim_ids": ["c1"]})
        finished = reopened.finish(research_id, "Answered after explicit resumption.")
        self.assertEqual(finished["usage"]["fetch_calls"], 2)
        for key, value in resumed["recorded"]["previous_artifacts"].items():
            self.assertEqual(Path(value).read_bytes(), original[key])
        report = Path(finished["artifacts"]["report"]).read_text()
        prior_report = Path(resumed["recorded"]["previous_artifacts"]["report"])
        self.assertIn("[Previous incomplete report](%s)" % prior_report.name, report)

    def test_resume_cannot_reopen_final_reports_or_refund_exhausted_budget(self):
        research_id = self.start(budget={"max_fetch_calls": 1})
        with self.assertRaisesRegex(ValueError, "Only an incomplete"):
            self.sessions.record(research_id, {"kind": "resume", "text": "Already active."})
        self.fetch(research_id)
        self.claim(research_id)
        self.answer(research_id)
        self.sessions.finish(research_id, "More inspection desired.", status="incomplete")
        self.sessions.record(research_id, {"kind": "resume", "text": "Review the saved evidence."})
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.fetch(research_id, "no-new-budget")
        self.sessions.finish(research_id, "Existing evidence is sufficient.")
        with self.assertRaisesRegex(ValueError, "Only an incomplete"):
            self.sessions.record(research_id, {"kind": "resume", "text": "Cannot reopen a completed report."})
        cancelled = self.start()
        self.sessions.finish(cancelled, "Cancelled by user.", status="cancelled")
        with self.assertRaisesRegex(ValueError, "Only an incomplete"):
            self.sessions.record(cancelled, {"kind": "resume", "text": "Cannot reopen a cancelled task."})
        self.assertEqual(self.engine.fetch.call_count, 1)

    def test_process_interruption_never_reexecutes_pending_request(self):
        research_id = self.start(budget={"max_fetch_calls": 2})
        self.fetch(research_id, "good")
        self.claim(research_id)
        self.answer(research_id)
        self.engine.fetch.side_effect = KeyboardInterrupt("simulated lost response")
        with self.assertRaises(KeyboardInterrupt):
            self.fetch(research_id, "lost")
        reopened = ResearchSessions(self.sessions.directory, settings=self.settings, engine=self.engine)
        outcome = reopened.fetch(research_id, "lost", "q1", ["https://example.test/docs"])
        self.assertTrue(outcome["replayed"])
        self.assertEqual(outcome["operation"]["status"], "pending")
        self.assertEqual(self.engine.fetch.call_count, 2)
        with self.assertRaisesRegex(ValueError, "interrupted"):
            reopened.finish(research_id, "Ready except interrupted request")
        reopened.record(research_id, {"kind": "interruption", "operation_id": "lost", "text": "Client process ended; outcome is unknown."})
        result = reopened.finish(research_id, "Conclusion based on the earlier saved source.")
        self.assertEqual(result["usage"]["fetch_calls"], 2)
        self.assertIn("unknown_outcome", Path(result["artifacts"]["report"]).read_text())

    def test_concurrent_callers_cannot_overspend_a_shared_budget(self):
        research_id = self.start(providers=["exa"], budget={"max_search_calls": 1})
        def attempt(number):
            sessions = ResearchSessions(self.sessions.directory, settings=self.settings, engine=self.engine)
            try:
                return sessions.search(research_id, "op-%s" % number, [{"question_id": "q1", "query": "docs"}])["status"]
            except ValueError:
                return "budget-denied"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [1, 2]))
        self.assertCountEqual(results, ["ok", "budget-denied"])
        self.assertEqual(self.engine.search.call_count, 1)

    def test_invalid_step_arguments_never_reserve_budget(self):
        research_id = self.start()
        before = self.sessions.status(research_id)
        calls = [lambda: self.sessions.search(research_id, "op", [{"question_id": "missing", "query": "docs"}]),
                 lambda: self.sessions.search(research_id, "op", [{"question_id": "q1", "query": "docs", "extra": True}]),
                 lambda: self.sessions.fetch(research_id, "op", "q1", ["https://user:pass@example.test"]),
                 lambda: self.sessions.fetch(research_id, "../escape", "q1", ["https://example.test"]),
                 lambda: self.sessions.fetch(research_id, "op", "q1", ["https://example.test"], max_characters=True),
                 lambda: self.sessions.record(research_id, {"kind": []})]
        for call in calls:
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(before, self.sessions.status(research_id))
        self.engine.fetch.assert_not_called()

    def test_storage_guards_prevent_source_or_plugin_writes(self):
        package = self.base / "canvas package"
        package.mkdir()
        (package / "test.canvas").write_text('{"nodes":[],"edges":[]}')
        for directory in (package / "research", Path(__file__).resolve().parents[1] / "research-data"):
            with self.assertRaisesRegex(ValueError, "outside"):
                ResearchSessions(directory)
        with self.assertRaises(ValueError):
            self.sessions.status("../../state")

    def test_cli_can_start_reopen_and_finish_from_an_unrelated_directory(self):
        root = Path(__file__).resolve().parents[1]
        cli = [sys.executable, str(root / "src/cli.py"), "--config", str(self.settings.path),
               "research", "--directory", str(self.sessions.directory)]
        def run(arguments, data=None):
            result = subprocess.run(cli + arguments, input=json.dumps(data) if data else None,
                                    capture_output=True, text=True, cwd=self.base, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        started = run(["start", "--input", "-"], {"brief": "CLI test", "questions": [{"id": "q1", "question": "Any evidence?"}],
                                                   "urls": ["https://example.test/one", "https://example.test/two"]})
        self.assertEqual(started["source_scope"]["selected_url_count"], 2)
        self.assertEqual(run(["status", started["research_id"]])["questions"][0]["id"], "q1")
        finished = run(["finish", started["research_id"], "--summary", "No evidence collected.", "--status", "incomplete"])
        self.assertTrue(Path(finished["artifacts"]["report"]).is_file())


if __name__ == "__main__":
    unittest.main()
