"""Atomic record batches, stable retries and compact protocol/CLI results."""

import concurrent.futures
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from research import ResearchSessions
from settings import Settings


class ResearchRecordBatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="record batch 中文 ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.settings = Settings(self.base / "settings.json")
        self.sessions = ResearchSessions(self.base / "research", settings=self.settings)
        self.research_id = self.sessions.start("Check saved evidence", [{"id": "q1", "question": "What is supported?"}])["research_id"]
        self.state_path = self.sessions.directory / self.research_id / "state.json"
        self.quote = "The service supports search and fetch."
        self.sessions.import_evidence(self.research_id, "import-1", "q1", "https://example.test/docs", self.quote,
                                      {"kind": "page", "retrieved_at": "2026-09-12T00:00:00Z"})
        self.review = {"kind": "source_review", "source_id": "s1", "verdict": "accepted", "text": "Read and checked page identity."}
        self.claim = {"kind": "claim", "question_id": "q1", "statement": "Search and fetch are supported.",
                      "citations": [{"source_id": "s1", "quote": self.quote}]}

    def record(self, entries, batch_id="batch-1"):
        return self.sessions.record(self.research_id, entries=entries, batch_id=batch_id)

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def test_ordered_batch_preserves_events_and_returns_compact_stable_ids(self):
        entries = [self.review, self.claim, {"kind": "question", "id": "q2", "question": "Is the page complete?"},
                   {"kind": "gap", "question_id": "q2", "text": "Completeness remains unknown."}]
        with patch.object(self.sessions, "_save", wraps=self.sessions._save) as save:
            result = self.record(entries)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(result["count"], 4)
        self.assertEqual([(row["index"], row["kind"], row["id"]) for row in result["results"]],
                         [(0, "source_review", "s1"), (1, "claim", "c1"), (2, "question", "q2"), (3, "gap", "q2")])
        self.assertNotIn(self.quote, json.dumps(result))
        state = self.state()
        self.assertEqual([event["kind"] for event in state["events"]], [entry["kind"] for entry in entries])
        self.assertEqual(state["events"][2]["value"]["status"], "open")
        self.assertEqual(state["questions"][1]["status"], "unresolved")
        self.assertEqual(state["claims"][0]["citations"][0]["quote"], self.quote)
        answer = self.record([{"kind": "answer", "question_id": "q1", "answer": "Search and fetch.",
                               "claim_ids": [result["results"][1]["id"]]}], "answers-1")
        self.assertEqual(answer["results"][0]["id"], "q1")
        self.assertEqual(self.state()["questions"][0]["status"], "answered")

    def test_invalid_later_entry_leaves_no_partial_review_claim_or_receipt(self):
        before = self.state_path.read_bytes()
        bad_claim = {**self.claim, "citations": [{"source_id": "s1", "quote": "This quote is absent."}]}
        with self.assertRaisesRegex(ValueError, r"entries\[2\].*no entries were saved"):
            self.record([self.review, self.claim, bad_claim])
        self.assertEqual(self.state_path.read_bytes(), before)
        result = self.record([self.review, self.claim])
        self.assertEqual(result["results"][1]["id"], "c1")

    def test_replay_survives_reopen_and_closed_session_without_duplicate_claims(self):
        entries = [self.review, self.claim]
        first = self.record(entries)
        self.sessions.finish(self.research_id, "More evidence needed.", status="incomplete")
        before = self.state_path.read_bytes()
        reopened = ResearchSessions(self.sessions.directory, settings=self.settings)
        replay = reopened.record(self.research_id, entries=copy.deepcopy(entries), batch_id="batch-1")
        self.assertEqual(replay, {**first, "replayed": True})
        self.assertEqual(self.state_path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "different entries"):
            reopened.record(self.research_id, entries=[self.review], batch_id="batch-1")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            reopened.record(self.research_id, entries=entries, batch_id="new-batch")
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_concurrent_batches_share_the_lock_and_replay_receipt(self):
        def attempt(batch_id):
            sessions = ResearchSessions(self.sessions.directory, settings=self.settings)
            return sessions.record(self.research_id, entries=[self.claim], batch_id=batch_id)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            same = list(pool.map(attempt, ["same"] * 4))
            different = list(pool.map(attempt, ["different-1", "different-2"]))
        self.assertEqual(sum(not row["replayed"] for row in same), 1)
        self.assertEqual({row["results"][0]["id"] for row in same}, {"c1"})
        self.assertEqual({row["results"][0]["id"] for row in different}, {"c2", "c3"})
        self.assertEqual([row["id"] for row in self.state()["claims"]], ["c1", "c2", "c3"])

    def test_batch_cannot_create_resume_or_external_artifacts(self):
        entries = [{"kind": "resume", "text": "Continue the report."},
                   {"kind": "external_run", "id": "run-1", "provider": "codex", "run_id": "local:1",
                    "status": "completed", "text": "Saved output.", "result": {"body": "Full output"}}]
        before = self.state_path.read_bytes()
        files = {path.relative_to(self.state_path.parent) for path in self.state_path.parent.rglob("*") if path.is_file()}
        for entry in entries:
            with self.subTest(kind=entry["kind"]), self.assertRaisesRegex(ValueError, "single entry"):
                self.record([self.review, entry])
            self.assertEqual(self.state_path.read_bytes(), before)
            self.assertEqual({path.relative_to(self.state_path.parent) for path in self.state_path.parent.rglob("*") if path.is_file()}, files)

    def test_boundaries_and_event_limit_reject_the_entire_batch(self):
        before = self.state_path.read_bytes()
        cases = [{}, {"entry": self.review, "entries": [self.review]}, {"entries": []},
                 {"entries": {}}, {"entries": [self.review] * 51}, {"entries": [None]},
                 {"entry": self.review, "batch_id": "batch-1"}, {"entries": [self.review], "batch_id": "../bad"}]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.sessions.record(self.research_id, **arguments)
            self.assertEqual(self.state_path.read_bytes(), before)
        gap = {"kind": "gap", "question_id": "q1", "text": "Evidence remains missing."}
        state = self.state()
        state["events"] = [{"kind": "gap", "at": "fixture", "value": {}}] * 499
        self.sessions._save(self.state_path.parent, state)
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, r"entries\[1\].*event limit"):
            self.record([gap, gap])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_maximum_batch_does_not_echo_large_review_text(self):
        entries = [{**self.review, "text": "Reviewed evidence. " * 200}] * self.sessions.RECORD_BATCH_SIZE
        result = self.record(entries, batch_id=None)
        self.assertEqual(result["count"], 50)
        self.assertLess(len(json.dumps(result)), 6000)
        self.assertEqual(len(self.state()["events"]), 50)
        self.assertNotIn("record_batches", self.state())

    def test_cli_accepts_legacy_entry_and_batch_envelope(self):
        cli = [sys.executable, str(Path(__file__).resolve().parents[1] / "src/cli.py"), "--config", str(self.settings.path),
               "research", "--directory", str(self.sessions.directory), "record", self.research_id, "--input", "-"]
        def run(payload):
            result = subprocess.run(cli, input=json.dumps(payload), capture_output=True, text=True, cwd=self.base, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        single = run(self.review)
        self.assertEqual(single["recorded"]["review"]["verdict"], "accepted")
        payload = {"entries": [self.claim], "batch_id": "cli-batch"}
        first = run(payload)
        self.assertEqual(first["results"][0]["id"], "c1")
        self.assertEqual(run(payload), {**first, "replayed": True})


if __name__ == "__main__":
    unittest.main()
