"""A slow provider request must not block other writers of the same research task.

The task lock used to be held across the whole bounded request, so a provider
that answered slowly made an independent process record a finding and time out
after ten seconds with a settings-worded error.
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from research import ResearchSessions
from settings import Settings


class ResearchLockScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="research lock ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.settings = Settings(self.base / "settings.json")
        self.engine = Mock()
        self.engine.fetch.side_effect = self._slow_fetch
        self.sessions = ResearchSessions(self.base / "research", settings=self.settings, engine=self.engine,
                                         db_path=self.base / "index.sqlite3")
        self.research_id = self.sessions.start(
            "Slow provider", [{"id": "q1", "question": "What is supported?"}],
            providers=["exa"])["research_id"]
        self.release = threading.Event()

    def _slow_fetch(self, urls, provider, archive, max_characters):
        # Stands in for a provider that takes a long time to answer.
        self.started.set()
        self.release.wait(10)
        return {"provider": provider, "urls": urls, "tool": "web_fetch", "request_arguments": {"urls": urls},
                "requested_max_characters": max_characters, "retrieved_at": "2026-10-09T00:00:00Z",
                "usage": {"tool_calls": 1}, "result": {"structuredContent": {"results": [
                    {"url": url, "title": "Slow document", "text": "Slow provider body text."} for url in urls]}}}

    def test_write_succeeds_while_a_slow_request_is_in_flight(self):
        self.started = threading.Event()
        outcome = {}

        def run_fetch():
            try:
                outcome["fetch"] = self.sessions.fetch(
                    self.research_id, "slow-1", "q1", ["https://example.test/slow"])
            except Exception as error:  # pragma: no cover - surfaced by the assertion below
                outcome["error"] = error

        worker = threading.Thread(target=run_fetch)
        worker.start()
        self.assertTrue(self.started.wait(5), "fetch never started")
        began = time.monotonic()
        try:
            self.sessions.record(self.research_id, {"kind": "gap", "question_id": "q1",
                                                    "text": "Written while the provider was still answering."})
            elapsed = time.monotonic() - began
        finally:
            self.release.set()
            worker.join(10)
        self.assertIn("fetch", outcome, outcome.get("error"))
        self.assertNotIn("error", outcome)
        # The write is serialized against the reservation and the commit only, so
        # it must finish long before the provider answer is released.
        self.assertLess(elapsed, 5, "record waited for the slow request: %.1fs" % elapsed)
        self.assertIn("still answering", (self.base / "research" / self.research_id / "state.json").read_text(encoding="utf-8"))

    def test_contention_reports_a_task_specific_retryable_error(self):
        with patch.object(Settings, "_update_lock",
                          side_effect=TimeoutError("Settings are being updated by another process")):
            with self.assertRaisesRegex(TimeoutError, "Research task is being written by another process"):
                self.sessions.record(self.research_id, {"kind": "gap", "question_id": "q1", "text": "blocked"})

    def test_operation_replays_without_resubmitting_after_the_refactor(self):
        self.started = threading.Event()
        self.release.set()
        first = self.sessions.fetch(self.research_id, "read-1", "q1", ["https://example.test/docs"])
        self.assertEqual("ok", first["status"], first)
        self.assertEqual(1, self.engine.fetch.call_count)
        replay = self.sessions.fetch(self.research_id, "read-1", "q1", ["https://example.test/docs"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(1, self.engine.fetch.call_count)
        store = self.sessions.status(self.research_id)
        self.assertEqual(self.research_id, store["research_id"])


if __name__ == "__main__":
    unittest.main()
