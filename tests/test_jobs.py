"""Durable job queue and worker semantics (no network)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jobs import JobStore, JobWorker


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="br-jobs-test-")
        self.addCleanup(self.temp.cleanup)
        self.store = JobStore(Path(self.temp.name) / "jobs.sqlite3")
        self.addCleanup(self.store.close)

    def test_submit_is_idempotent_and_payload_bound(self):
        first = self.store.submit("fetch", {"urls": ["https://example.test/a"]}, idempotency_key="op-1")
        again = self.store.submit("fetch", {"urls": ["https://example.test/a"]}, idempotency_key="op-1")
        self.assertEqual(first["job_id"], again["job_id"])
        self.assertEqual("queued", again["state"])
        with self.assertRaises(ValueError):
            self.store.submit("fetch", {"urls": ["https://example.test/b"]}, idempotency_key="op-1")
        with self.assertRaises(ValueError):
            self.store.submit("nope", {})

    def test_claim_moves_one_job_to_running(self):
        first = self.store.submit("fetch", {"urls": ["https://example.test/a"]})
        second = self.store.submit("fetch", {"urls": ["https://example.test/b"]})
        claimed = self.store.claim("w-1", lease_seconds=60)
        self.assertEqual(first["job_id"], claimed["job_id"])
        self.assertEqual("running", claimed["state"])
        self.assertEqual("w-1", claimed["lease_owner"])
        self.assertEqual(second["job_id"], self.store.claim("w-1")["job_id"])
        self.assertIsNone(self.store.claim("w-1"))

    def test_cancel_queued_job_and_list_filters(self):
        job = self.store.submit("ingest", {"batches": []})
        cancelled = self.store.cancel(job["job_id"])
        self.assertEqual("cancelled", cancelled["state"])
        self.assertEqual([job["job_id"]], [row["job_id"] for row in self.store.list(state="cancelled")])
        self.assertEqual([], self.store.list(state="queued"))
        with self.assertRaises(ValueError):
            self.store.cancel("j-missing")

    def test_expired_lease_is_requeued_or_failed(self):
        job = self.store.submit("fetch", {"urls": ["https://example.test/a"]}, max_attempts=2)
        self.store.claim("w-dead", lease_seconds=-1)
        self.store.recover_expired()
        self.assertEqual("queued", self.store.get(job["job_id"])["state"])
        self.store.claim("w-dead", lease_seconds=-1)
        self.store.recover_expired()
        self.assertEqual("failed", self.store.get(job["job_id"])["state"])

    def test_worker_runs_job_and_records_result(self):
        seen = []

        def handler(payload, job):
            seen.append(payload)
            return {"result": {"ok": True, "count": len(payload["urls"])}}

        job = self.store.submit("fetch", {"urls": ["https://example.test/a"]})
        worker = JobWorker(self.store, handlers={"fetch": handler})
        self.assertEqual(job["job_id"], worker.run_once())
        stored = self.store.get(job["job_id"])
        self.assertEqual("succeeded", stored["state"])
        self.assertEqual({"ok": True, "count": 1}, stored["result"])
        self.assertEqual([{"urls": ["https://example.test/a"]}], seen)
        self.assertIsNone(worker.run_once())

    def test_worker_retries_then_fails(self):
        def handler(payload, job):
            raise RuntimeError("boom")

        job = self.store.submit("fetch", {"urls": ["https://example.test/a"]}, max_attempts=2)
        worker = JobWorker(self.store, handlers={"fetch": handler})
        worker.run_once()
        self.assertEqual("queued", self.store.get(job["job_id"])["state"])
        worker.run_once()
        stored = self.store.get(job["job_id"])
        self.assertEqual("failed", stored["state"])
        self.assertIn("boom", stored["error"])


if __name__ == "__main__":
    unittest.main()
