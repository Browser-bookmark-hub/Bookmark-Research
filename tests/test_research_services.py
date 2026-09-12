"""Durable external runs, receipt recovery and secondary evidence without API spend."""

import concurrent.futures
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from research import ResearchSessions
from research_services import ResearchServices
from service_http import ServiceError
from settings import Settings


def openai_response(status="queued", run_id="resp_fixture", text=None, citations=None):
    response = {"id": run_id, "status": status, "output": [], "usage": {"input_tokens": 10, "output_tokens": 20}}
    if text is not None:
        response["output"] = [{"type": "message", "content": [{"type": "output_text", "text": text, "annotations": citations or []}]}]
    return response


class ResearchServicesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="external services 中文 ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.settings = Settings(self.root / "settings.json")
        self.settings.update({"professional_research": {"enabled": True, "provider": "openai"}})
        self.sessions = ResearchSessions(self.root / "research", settings=self.settings, db_path=self.root / "index.sqlite3")
        self.rid = self.sessions.start("LOCAL_BRIEF_PRIVATE", [{"id": "q1", "question": "Which facts are supported?"}],
                                       providers=["exa"], scope="LOCAL_SCOPE_PRIVATE")["research_id"]
        self.transport = Mock()
        self.transport.request.return_value = openai_response()
        self.service = self.reopen()
        self.secret = "synthetic-api-credential-not-for-files"
        environment = patch.dict(os.environ, {"OPENAI_API_KEY": self.secret, "PARALLEL_API_KEY": self.secret})
        environment.start()
        self.addCleanup(environment.stop)

    def reopen(self):
        return ResearchServices(self.root / "services", settings=self.settings, research_sessions=self.sessions, transport=self.transport)

    def start(self, operation="start-once", **changes):
        arguments = {"research_id": self.rid, "operation_id": operation, "input": "Public research question", "question_id": "q1"}
        arguments.update(changes)
        return self.service.start(**arguments)

    def state(self, external_id):
        return json.loads((self.service.directory / external_id / "state.json").read_text())

    def test_prepare_preserves_207_urls_and_large_context_without_a_page_sized_scope(self):
        package = self.root / "package"
        section = package / "临时栏目" / "sources.json"
        section.parent.mkdir(parents=True)
        items = [{"id": "b" + str(i), "sectionId": "sources", "type": "bookmark",
                  "title": "Synthetic source " + str(i), "url": "https://example.test/source-" + str(i % 207)}
                 for i in range(223)]
        items[0]["note"] = "PRIVATE_INPUT_NOTE_" + "x" * 950000
        section.write_text(json.dumps({"format": "bookmark-canvas-section", "schemaVersion": 2,
            "sectionType": "temporary", "id": "sources", "label": "A-1", "title": "Synthetic inventory",
            "items": items}), encoding="utf-8")
        with BookmarkIndex(self.sessions.db_path) as index:
            index.sync(package, "fixture")
        started = self.sessions.start("LOCAL_BRIEF_PRIVATE", [{"id": "q1", "question": "Compare all sources."}],
            source_ids=["fixture"])
        research_id = started["research_id"]
        ids = started["source_scope"]["selected_inventory_ids"]
        for provider in ("openai", "parallel"):
            with self.subTest(provider=provider):
                prepared = self.service.prepare(research_id, "Public research question", provider=provider)
                payload = json.loads(prepared["payload"]["input"])
                self.assertEqual(prepared["source_scope"]["shared_url_count"], 207)
                self.assertCountEqual([row["source_id"] for row in payload["sources"]], ids)
                self.assertEqual(len({row["url"] for row in payload["sources"]}), 207)
                self.assertEqual(prepared["source_scope"]["local_only_inventory_ids"], [])
                self.assertNotIn("PRIVATE_INPUT_NOTE", prepared["payload"]["input"])
                self.assertNotIn(str(package), prepared["payload"]["input"])
                subset = self.service.prepare(research_id, "Public research question", provider=provider, inventory_ids=ids[:150])
                self.assertEqual(subset["source_scope"]["shared_url_count"], 150)
                self.assertCountEqual(subset["source_scope"]["remaining_inventory_ids"], ids[150:])
        self.assertEqual(started["source_scope"]["selected_instance_count"], 223)
        self.transport.request.assert_not_called()

    def test_start_publishes_real_id_and_concurrent_replay_never_resubmits(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.start(), range(2)))
        self.assertEqual(self.transport.request.call_count, 1)
        self.assertCountEqual([row["replayed"] for row in results], [False, True])
        self.assertEqual(results[0]["external_id"], results[1]["external_id"])
        self.assertTrue(all(row["research_record_error"] is None for row in results))
        external = self.sessions.status(self.rid, section="external_runs")["items"]
        self.assertEqual(len(external), 1)
        self.assertEqual(external[0]["run_id"], "resp_fixture")
        self.assertEqual(external[0]["status"], "queued")
        self.assertTrue(any("external run" in item for item in self.sessions.coverage(self.rid)["completion_blockers"]))

    def test_replay_uses_original_intent_after_settings_credentials_and_session_change(self):
        first = self.start()
        original = Path(first["request_path"]).read_bytes()
        self.settings.update({"professional_research": {"enabled": False, "provider": "parallel",
                                                       "openai": {"model": "o3-deep-research", "max_tool_calls": 2}}})
        self.sessions.finish(self.rid, "Continue later.", status="incomplete")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "PARALLEL_API_KEY": ""}):
            replay = self.reopen().start(self.rid, "start-once", "Public research question", question_id="q1")
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["provider"], "openai")
        self.assertEqual(replay["provider_run_id"], first["provider_run_id"])
        self.assertEqual(Path(first["request_path"]).read_bytes(), original)
        self.assertEqual(self.transport.request.call_count, 1)
        with self.assertRaisesRegex(ValueError, "different research service request"):
            self.service.start(self.rid, "start-once", "A different question", question_id="q1")
        self.assertEqual(self.transport.request.call_count, 1)

    def test_lost_create_response_remains_unknown_and_can_attach_without_restarting(self):
        self.transport.request.side_effect = ServiceError("timeout", "Synthetic lost response", uncertain=True)
        first = self.start()
        self.assertEqual(first["status"], "unknown_outcome")
        self.assertIsNone(first["provider_run_id"])
        self.assertEqual(self.sessions.status(self.rid, section="external_runs")["items"][0]["status"], "unknown_outcome")
        replay = self.start()
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.transport.request.call_count, 1)
        with self.assertRaisesRegex(ValueError, "No provider run ID"):
            self.service.status(first["external_id"], refresh=True)
        self.transport.request.side_effect = None
        attached = self.service.attach(self.rid, "start-once", "openai", "resp_fixture", question_id="q1")
        self.assertIsNone(attached["research_record_error"])
        self.assertEqual(attached["status"], "unknown_outcome")
        self.assertEqual(self.transport.request.call_count, 1)
        observed = self.service.status(first["external_id"], refresh=True)
        self.assertEqual(observed["status"], "queued")
        self.assertEqual(self.transport.request.call_args[0][1:3], ("GET", "/v1/responses/resp_fixture"))

    def test_interrupted_create_without_a_receipt_never_runs_again(self):
        self.transport.request.side_effect = SystemExit("Simulated process interruption")
        with self.assertRaises(SystemExit):
            self.start()
        external_id = self.service._external_id(self.rid, "start-once")
        current = self.reopen().status(external_id)
        self.assertEqual(current["status"], "unknown_outcome")
        self.assertEqual(self.start()["status"], "unknown_outcome")
        self.assertEqual(self.transport.request.call_count, 1)

    def test_create_receipt_recovers_after_state_checkpoint_failure(self):
        text = "Actual saved report.\r\n中文。\r\n"
        self.transport.request.return_value = openai_response("completed", text=text)
        save = self.service._save
        def fail_completed(path, state):
            if state.get("create_response_applied"):
                raise OSError("Injected create checkpoint failure")
            return save(path, state)
        with patch.object(self.service, "_save", side_effect=fail_completed), self.assertRaises(OSError):
            self.start()
        external_id = self.service._external_id(self.rid, "start-once")
        recovered = self.reopen().result(external_id)
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["text"], text)
        self.assertEqual(self.transport.request.call_count, 1)

    def test_invalid_create_receipts_remain_inspectable_and_do_not_block_attach(self):
        malformed = [None, [], {"id": "resp_fixture", "status": []}, {"id": "resp_fixture", "status": "completed", "output": None}]
        for i, response in enumerate(malformed):
            with self.subTest(response=response):
                self.transport.request.return_value = response
                first = self.start(operation="bad-" + str(i))
                self.assertEqual(first["status"], "unknown_outcome")
                self.assertEqual(self.reopen().status(first["external_id"])["status"], "unknown_outcome")
                calls = self.transport.request.call_count
                attached = self.service.attach(self.rid, "bad-" + str(i), "openai", "resp_fixture", question_id="q1")
                self.assertEqual(attached["provider_run_id"], "resp_fixture")
                self.assertIsNone(attached["research_record_error"])
                self.assertEqual(self.service.status(first["external_id"])["provider_run_id"], "resp_fixture")
                self.assertEqual(self.transport.request.call_count, calls)

    def test_mismatched_create_receipt_cannot_supply_a_run_id(self):
        self.transport.request.side_effect = SystemExit("Simulated interruption")
        with self.assertRaises(SystemExit):
            self.start()
        external_id = self.service._external_id(self.rid, "start-once")
        path = self.service.directory / external_id
        state = self.state(external_id)
        ResearchSessions._write(path / "create-receipt.json", {"external_id": "er-" + "0" * 24,
            "digest": state["digest"], "response": openai_response(run_id="resp_wrong")})
        current = self.reopen().status(external_id)
        self.assertEqual(current["status"], "unknown_outcome")
        self.assertIsNone(current["provider_run_id"])
        self.assertEqual(current["observation_error"]["error_kind"], "create_receipt_error")
        attached = self.service.attach(self.rid, "start-once", "openai", "resp_verified", question_id="q1")
        self.assertEqual(attached["provider_run_id"], "resp_verified")
        self.assertEqual(self.transport.request.call_count, 1)

    def test_malformed_observation_keeps_the_last_valid_state(self):
        first = self.start()
        self.transport.request.return_value = {"id": "resp_fixture", "status": "completed", "output": None}
        observed = self.service.status(first["external_id"], refresh=True)
        self.assertEqual(observed["status"], "queued")
        self.assertEqual(observed["provider_status"], "queued")
        self.assertEqual(observed["provider_run_id"], "resp_fixture")
        self.assertIsNone(observed["report_path"])
        self.assertIsNotNone(observed["observation_error"])
        self.assertEqual(self.reopen().status(first["external_id"])["status"], "queued")

    def test_report_write_failure_and_observation_checkpoint_recover_without_get(self):
        first = self.start()
        self.transport.request.return_value = openai_response("completed", text="Completed but storage temporarily failed.")
        with patch.object(self.service, "_write_bytes", side_effect=OSError("Injected report write failure")):
            failed = self.service.status(first["external_id"], refresh=True)
        self.assertEqual(failed["status"], "queued")
        self.assertIsNone(failed["report_path"])
        recovered = self.reopen().result(first["external_id"])
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["text"], "Completed but storage temporarily failed.")
        self.assertEqual(self.transport.request.call_count, 2)
        save = self.service._save
        def fail_final(path, state):
            if not state.get("pending_observation"):
                raise OSError("Injected observation checkpoint failure")
            return save(path, state)
        self.transport.request.return_value = openai_response("completed", text="A later report snapshot.")
        with patch.object(self.service, "_save", side_effect=fail_final), self.assertRaises(OSError):
            self.service.status(first["external_id"], refresh=True)
        self.assertEqual(self.reopen().result(first["external_id"])["text"], "A later report snapshot.")
        self.assertEqual(self.transport.request.call_count, 3)

    def test_observation_timeout_or_unavailable_run_does_not_become_terminal(self):
        first = self.start()
        for kind, uncertain, code in (("timeout", True, None), ("run_unavailable", False, 404), ("rate_limited", False, 429)):
            with self.subTest(kind=kind):
                self.transport.request.side_effect = ServiceError(kind, "Synthetic observation error", uncertain=uncertain, http_status=code)
                observed = self.service.status(first["external_id"], refresh=True)
                self.assertEqual(observed["status"], "queued")
                self.assertEqual(observed["provider_run_id"], "resp_fixture")
                self.assertEqual(observed["observation_error"]["error_kind"], kind)
        self.assertTrue(all(call[0][1] == "GET" for call in self.transport.request.call_args_list[1:]))

    def test_cancel_requires_provider_confirmation_and_parallel_remains_unchanged(self):
        first = self.start()
        self.transport.request.side_effect = ServiceError("timeout", "Cancellation observation timed out", uncertain=True)
        self.assertEqual(self.service.cancel(first["external_id"])["status"], "queued")
        self.transport.request.side_effect = None
        self.transport.request.return_value = openai_response("in_progress")
        self.assertEqual(self.service.cancel(first["external_id"])["status"], "in_progress")
        self.transport.request.return_value = openai_response("cancelled")
        self.assertEqual(self.service.cancel(first["external_id"])["status"], "cancelled")
        calls = self.transport.request.call_count
        self.service.cancel(first["external_id"])
        self.assertEqual(self.transport.request.call_count, calls)
        self.transport.request.return_value = {"run_id": "trun_fixture", "status": "running", "is_active": True}
        parallel = self.start(operation="parallel", provider="parallel")
        calls = self.transport.request.call_count
        with self.assertRaisesRegex(ValueError, "cancellation is not established"):
            self.service.cancel(parallel["external_id"])
        self.assertEqual(self.transport.request.call_count, calls)
        self.assertEqual(self.service.status(parallel["external_id"])["status"], "in_progress")

    def test_parallel_result_timeout_and_documented_output_basis(self):
        self.transport.request.return_value = {"run_id": "trun_fixture", "status": "running", "is_active": True}
        first = self.start(provider="parallel")
        self.transport.request.side_effect = ServiceError("result_pending", "Research API HTTP 408", uncertain=True, http_status=408)
        pending = self.service.result(first["external_id"], refresh=True)
        self.assertEqual(pending["status"], "in_progress")
        self.assertEqual(self.transport.request.call_args[0][2], "/v1/tasks/runs/trun_fixture/result?timeout=1")
        self.transport.request.side_effect = None
        citation = {"url": "https://example.test/evidence", "excerpts": ["The source says this."]}
        self.transport.request.return_value = {"run": {"run_id": "trun_fixture", "status": "completed", "is_active": False},
            "output": {"type": "text", "content": "Parallel's saved report.", "basis": [{"field": "result", "citations": [citation]}]}}
        completed = self.service.result(first["external_id"], refresh=True)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["text"], "Parallel's saved report.")
        self.assertEqual(completed["citations"], [citation])
        self.assertFalse(completed["citations_verified"])

    def test_mismatched_run_id_never_replaces_prior_status_or_report(self):
        self.transport.request.return_value = openai_response("completed", text="The valid report.")
        first = self.start()
        before = Path(first["report_path"]).read_bytes()
        self.transport.request.return_value = openai_response("cancelled", run_id="resp_other", text="Unrelated run text.")
        result = self.service.result(first["external_id"], refresh=True)
        self.assertEqual(result["provider_run_id"], "resp_fixture")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "The valid report.")
        self.assertEqual(Path(first["report_path"]).read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "different provider run"):
            self.service.attach(self.rid, "start-once", "openai", "resp_other")
        self.assertEqual(self.state(first["external_id"])["provider_run_id"], "resp_fixture")

    def test_report_hash_uses_exact_bytes_and_detects_newline_only_changes(self):
        text = "Café.\r\n中文。\r\n"
        self.transport.request.return_value = openai_response("completed", text=text)
        first = self.start()
        self.assertEqual(Path(first["report_path"]).read_bytes(), text.encode())
        self.assertEqual(first["report_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(self.service.result(first["external_id"])["text"], text)
        Path(first["report_path"]).write_bytes(text.replace("\r\n", "\n").encode())
        with self.assertRaisesRegex(ValueError, "hash does not match"):
            self.service.result(first["external_id"])
        with self.assertRaisesRegex(ValueError, "hash does not match"):
            self.service.import_result(first["external_id"], "import-once")
        self.assertEqual(self.sessions.status(self.rid)["counts"]["sources"], 0)

    def test_import_is_secondary_and_does_not_cover_original_pages(self):
        fixture = Path(__file__).parent / "fixtures/canvas"
        with BookmarkIndex(self.root / "index.sqlite3") as index:
            index.sync(fixture, "fixture")
        rid = self.sessions.start("Full fixture research", [{"id": "q1", "question": "Research the selected sources"}],
                                  source_ids=["fixture"], providers=["exa"])["research_id"]
        self.transport.request.return_value = openai_response("completed", text="An external report cites pages which still need to be read.")
        first = self.start(research_id=rid)
        imported = self.service.import_result(first["external_id"], "import-once")
        source = imported["evidence"]["sources"][0]
        self.assertEqual(source["evidence_kind"], "external_report")
        self.assertEqual(source["inventory_ids"], [])
        self.assertEqual(source["review"]["verdict"], "unreviewed")
        self.assertEqual(set(source["referenced_inventory_ids"]), set(first["source_scope"]["inventory_ids"]))
        self.sessions.record(rid, {"kind": "source_review", "source_id": source["id"], "verdict": "accepted", "text": "Accepted as a secondary report only."})
        coverage = self.sessions.coverage(rid)
        self.assertEqual(coverage["metrics"]["usable_text"]["count"], 0)
        self.assertEqual(coverage["metrics"]["substantive_review"]["count"], 0)
        self.assertGreater(coverage["scope_total"], 0)
        self.assertEqual(self.transport.request.call_count, 1)

    def test_import_checkpoint_failure_replays_existing_evidence(self):
        self.transport.request.return_value = openai_response("completed", text="A single saved report.\r\n")
        first = self.start()
        save = self.service._save
        def fail_import(path, state):
            if state.get("imported_evidence"):
                raise OSError("Injected import checkpoint failure")
            return save(path, state)
        with patch.object(self.service, "_save", side_effect=fail_import), self.assertRaises(OSError):
            self.service.import_result(first["external_id"], "import-once")
        replay = self.reopen().import_result(first["external_id"], "import-once")
        self.assertTrue(replay["evidence"]["replayed"])
        self.assertEqual(replay["evidence"]["sources"][0]["id"], "s1")
        self.assertEqual(self.sessions.status(self.rid)["counts"]["sources"], 1)
        self.assertEqual(self.sessions.source(self.rid, "s1")["text"], "A single saved report.\r\n")
        self.assertEqual(self.transport.request.call_count, 1)

    def test_large_citation_sets_keep_full_artifacts_and_bounded_import_metadata(self):
        citations = [{"type": "url_citation", "url": "https://example.test/" + str(i), "title": "Long source title " * 250,
                      "start_index": 0, "end_index": 6} for i in range(250)]
        self.transport.request.return_value = openai_response("completed", text="Report with a large bibliography.", citations=citations)
        first = self.start()
        result = self.service.result(first["external_id"])
        self.assertEqual(result["citation_count"], 250)
        self.assertTrue(result["citations_truncated"])
        self.assertEqual(json.loads(Path(result["citations_file"]).read_bytes()), citations)
        self.assertLess(len(json.dumps(result).encode()), 200000)
        imported = self.service.import_result(first["external_id"], "import-large")
        provenance = imported["evidence"]["sources"][0]["provenance"]
        self.assertEqual(provenance["provider_citation_count"], 250)
        self.assertEqual(provenance["provider_citations_file"], result["citations_file"])
        self.assertEqual(hashlib.sha256(Path(provenance["provider_citations_file"]).read_bytes()).hexdigest(), provenance["provider_citations_sha256"])
        self.assertLess(len(json.dumps(provenance).encode()), 64000)

    def test_prepare_excludes_private_context_and_rejects_credential_options(self):
        prepared = self.service.prepare(self.rid, "Explicit public question", provider="openai", question_id="q1")
        self.assertFalse(prepared["network_performed"])
        payload = json.loads(prepared["payload"]["input"])
        self.assertEqual(payload["research_question"], "Explicit public question")
        self.assertNotIn("LOCAL_BRIEF_PRIVATE", json.dumps(prepared))
        self.assertNotIn("LOCAL_SCOPE_PRIVATE", json.dumps(prepared))
        self.assertNotIn(str(self.root), json.dumps(prepared["payload"]))
        for options in ({"api_key": self.secret}, {"endpoint": "https://unrelated.example.test/"}, [], False):
            with self.subTest(options_type=type(options).__name__), self.assertRaises(ValueError):
                self.start(operation="invalid-options", options=options)
        self.transport.request.assert_not_called()
        first = self.start()
        for file in Path(first["directory"]).rglob("*.json"):
            self.assertNotIn(self.secret, file.read_text())
        request = json.loads(Path(first["request_path"]).read_text())
        self.assertEqual(request["payload"]["max_tool_calls"], 24)
        self.assertTrue(request["payload"]["background"])


if __name__ == "__main__":
    unittest.main()
