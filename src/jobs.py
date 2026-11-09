"""Durable local job queue and a single worker for long or batch work.

Short calls (locate/read/fetch) stay synchronous.  Anything that takes longer
than a tool step, or that should run N-at-a-time, is submitted here and observed
by id.  The queue lives beside the index, so the three hosts, the CLI and a
cron job all see the same rows.
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

JOB_STATES = ("queued", "running", "succeeded", "failed", "cancelled")
JOB_KINDS = ("fetch", "ingest", "research")
TERMINAL = ("succeeded", "failed", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  state TEXT NOT NULL,
  payload TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  priority INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 2,
  lease_owner TEXT,
  lease_until REAL,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  result TEXT,
  artifact_path TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs (state, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS jobs_kind ON jobs (kind, state);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


class JobStore:
    """One SQLite file, shared by every process that can see the data directory."""

    def __init__(self, path=None):
        from settings import Settings
        self.path = Path(path or (Settings.data_directory() / "jobs.sqlite3")).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(str(self.path), timeout=10.0, check_same_thread=False,
                                          isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        with self._lock:
            self.connection.executescript(SCHEMA)
            self.connection.commit()

    def close(self):
        with self._lock:
            self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # -- writes ---------------------------------------------------------
    def submit(self, kind, payload, idempotency_key=None, priority=0, max_attempts=2):
        if kind not in JOB_KINDS:
            raise ValueError("kind must be one of " + ", ".join(JOB_KINDS))
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        if idempotency_key is not None and (not isinstance(idempotency_key, str)
                                            or not idempotency_key.strip()):
            raise ValueError("idempotency_key must be a non-empty string")
        created = _now()
        with self._lock, self.connection:
            if idempotency_key is not None:
                existing = self.connection.execute(
                    "SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if existing is not None:
                    if existing["kind"] != kind or existing["payload"] != _json(payload):
                        raise ValueError("idempotency_key already refers to a different job")
                    return self._row(existing)
            job_id = "j-" + uuid.uuid4().hex[:12]
            self.connection.execute(
                "INSERT INTO jobs (job_id, kind, state, payload, idempotency_key, priority,"
                " max_attempts, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (job_id, kind, "queued", _json(payload), idempotency_key, int(priority),
                 int(max_attempts), created))
        return self.get(job_id)

    def claim(self, owner, lease_seconds=120.0):
        """Atomically move one queued job to running for this worker."""
        now = time.time()
        with self._lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                row = self.connection.execute(
                    "SELECT * FROM jobs WHERE state='queued'"
                    " ORDER BY priority DESC, created_at ASC LIMIT 1").fetchone()
                if row is None:
                    self.connection.execute("COMMIT")
                    return None
                updated = self.connection.execute(
                    "UPDATE jobs SET state='running', lease_owner=?, lease_until=?,"
                    " started_at=COALESCE(started_at, ?), attempts=attempts+1"
                    " WHERE job_id=? AND state='queued'",
                    (owner, now + lease_seconds, _now(), row["job_id"]))
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise
        return self.get(row["job_id"]) if updated.rowcount == 1 else None

    def heartbeat(self, job_id, owner, lease_seconds=120.0):
        with self._lock, self.connection:
            self.connection.execute(
                "UPDATE jobs SET lease_until=? WHERE job_id=? AND lease_owner=? AND state='running'",
                (time.time() + lease_seconds, job_id, owner))

    def finish(self, job_id, owner, state, result=None, artifact_path=None, error=None):
        if state not in TERMINAL:
            raise ValueError("finish state must be terminal")
        with self._lock, self.connection:
            self.connection.execute(
                "UPDATE jobs SET state=?, finished_at=?, lease_owner=NULL, lease_until=NULL,"
                " result=?, artifact_path=?, error=? WHERE job_id=? AND lease_owner=?",
                (state, _now(), None if result is None else _json(result),
                 artifact_path, error, job_id, owner))

    def release(self, job_id, owner, error=None, max_attempts=2):
        """Return a failed attempt to the queue until attempts run out."""
        with self._lock, self.connection:
            row = self.connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None or row["lease_owner"] != owner or row["state"] != "running":
                return None
            if row["attempts"] >= row["max_attempts"]:
                self.connection.execute(
                    "UPDATE jobs SET state='failed', finished_at=?, lease_owner=NULL,"
                    " lease_until=NULL, error=? WHERE job_id=?",
                    (_now(), error, job_id))
            else:
                self.connection.execute(
                    "UPDATE jobs SET state='queued', lease_owner=NULL, lease_until=NULL,"
                    " error=? WHERE job_id=?", (error, job_id))
        return self.get(job_id)

    def cancel(self, job_id):
        with self._lock, self.connection:
            row = self.connection.execute("SELECT state FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown job: " + job_id)
            if row["state"] in TERMINAL:
                return self.get(job_id)
            if row["state"] == "queued":
                self.connection.execute(
                    "UPDATE jobs SET state='cancelled', finished_at=?, cancel_requested=1"
                    " WHERE job_id=?", (_now(), job_id))
            else:
                self.connection.execute(
                    "UPDATE jobs SET cancel_requested=1 WHERE job_id=?", (job_id,))
        return self.get(job_id)

    def counts(self):
        rows = self.connection.execute(
            "SELECT state, COUNT(*) AS c FROM jobs GROUP BY state").fetchall()
        totals = {state: 0 for state in JOB_STATES}
        totals.update({row["state"]: row["c"] for row in rows})
        return totals

    def worker_running(self):
        """True when another process holds the worker lock."""
        path = Path(str(self.path) + ".lock")
        try:
            handle = open(path, "a+")
        except OSError:
            return False
        try:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
        finally:
            handle.close()

    def prune(self, keep_days=7, keep_latest=200):
        """Drop old terminal jobs; running and queued rows are never touched."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(keep_days)))).isoformat()
        with self._lock, self.connection:
            deleted = self.connection.execute(
                "DELETE FROM jobs WHERE state IN ('succeeded','failed','cancelled')"
                " AND finished_at IS NOT NULL AND finished_at < ?", (cutoff,)).rowcount
            deleted += self.connection.execute(
                "DELETE FROM jobs WHERE state IN ('succeeded','failed','cancelled')"
                " AND job_id NOT IN (SELECT job_id FROM jobs WHERE state IN"
                " ('succeeded','failed','cancelled') ORDER BY COALESCE(finished_at, created_at)"
                " DESC LIMIT ?)", (max(1, int(keep_latest)),)).rowcount
        return {"deleted": deleted, "keep_days": keep_days, "keep_latest": keep_latest}

    def recover_expired(self):
        """Requeue jobs whose worker died without finishing."""
        now = time.time()
        with self._lock, self.connection:
            self.connection.execute(
                "UPDATE jobs SET state='queued', lease_owner=NULL, lease_until=NULL"
                " WHERE state='running' AND lease_until IS NOT NULL AND lease_until < ?"
                " AND cancel_requested=0 AND attempts < max_attempts", (now,))
            self.connection.execute(
                "UPDATE jobs SET state='failed', finished_at=?, lease_owner=NULL, lease_until=NULL,"
                " error='lease expired' WHERE state='running' AND lease_until IS NOT NULL"
                " AND lease_until < ? AND (cancel_requested=1 OR attempts >= max_attempts)",
                (_now(), now))

    # -- reads ----------------------------------------------------------
    def get(self, job_id):
        with self._lock:
            row = self.connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return None if row is None else self._row(row)

    def list(self, state=None, kind=None, limit=20, offset=0):
        clauses, args = [], []
        if state is not None:
            if state not in JOB_STATES:
                raise ValueError("state must be one of " + ", ".join(JOB_STATES))
            clauses.append("state=?")
            args.append(state)
        if kind is not None:
            if kind not in JOB_KINDS:
                raise ValueError("kind must be one of " + ", ".join(JOB_KINDS))
            clauses.append("kind=?")
            args.append(kind)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM jobs" + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                args + [int(limit), int(offset)]).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row):
        value = {key: row[key] for key in row.keys()}
        value["payload"] = json.loads(value["payload"]) if value.get("payload") else {}
        value["result"] = json.loads(value["result"]) if value.get("result") else None
        value["cancel_requested"] = bool(value.get("cancel_requested"))
        return value


class JobWorker:
    """Claim jobs from one store and run them; one instance per data directory."""

    def __init__(self, store, handlers=None, concurrency=2, lease_seconds=120.0,
                 poll_seconds=0.5, owner=None):
        self.store = store
        self.handlers = handlers if handlers is not None else default_handlers()
        self.concurrency = max(1, int(concurrency))
        self.lease_seconds = float(lease_seconds)
        self.poll_seconds = float(poll_seconds)
        self.owner = owner or ("w-" + uuid.uuid4().hex[:8])
        self._lock_handle = None

    def execute(self, job):
        handler = self.handlers.get(job["kind"])
        if handler is None:
            self.store.finish(job["job_id"], self.owner, "failed",
                              error="no handler for kind " + job["kind"])
            return None
        try:
            outcome = handler(job["payload"], job) or {}
        except Exception as error:  # keep the queue alive on handler bugs
            self.store.release(job["job_id"], self.owner,
                               error=(type(error).__name__ + ": " + str(error))[:2000])
            return None
        self.store.finish(job["job_id"], self.owner, "succeeded",
                          result=outcome.get("result"), artifact_path=outcome.get("artifact_path"))
        return job["job_id"]

    def run_once(self):
        self.store.recover_expired()
        job = self.store.claim(self.owner, self.lease_seconds)
        if job is None:
            return None
        return self.execute(job)

    def serve(self, stop=None, max_jobs=None):
        """Single-writer loop with a bounded thread pool."""
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
        lock = self._acquire_singleton()
        if lock is None:
            raise RuntimeError("another job worker already owns this data directory")
        self.store.prune()
        finished = 0
        pending = set()
        try:
            with ThreadPoolExecutor(max_workers=self.concurrency,
                                    thread_name_prefix="br-job") as pool:
                while stop is None or not stop.is_set():
                    self.store.recover_expired()
                    while (len(pending) < self.concurrency
                           and (max_jobs is None or finished + len(pending) < max_jobs)):
                        job = self.store.claim(self.owner, self.lease_seconds)
                        if job is None:
                            break
                        pending.add(pool.submit(self.execute, job))
                    if max_jobs is not None and finished >= max_jobs and not pending:
                        break
                    if pending:
                        done, pending = wait(pending, timeout=self.poll_seconds,
                                             return_when=FIRST_COMPLETED)
                        finished += len(done)
                    else:
                        time.sleep(self.poll_seconds)
        finally:
            self._release_singleton()

    # -- singleton ------------------------------------------------------
    def _acquire_singleton(self):
        path = Path(str(self.store.path) + ".lock")
        handle = open(path, "a+")
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, OSError):
            handle.close()
            return None
        self._lock_handle = handle
        return handle

    def _release_singleton(self):
        handle, self._lock_handle = self._lock_handle, None
        if handle is None:
            return
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        handle.close()


def default_handlers(settings_factory=None):
    """Lazy imports: a worker run must not import the whole network stack for a test."""
    def fetch(payload, job):
        from settings import Settings
        from web_search import SearchProviders
        settings = Settings() if settings_factory is None else settings_factory()
        prefs = settings.load()["fetch"]
        result = SearchProviders(settings=settings).fetch(
            payload["urls"], provider=payload.get("provider"),
            archive=payload.get("archive"),
            max_characters=payload.get("max_characters", prefs["max_characters"]),
            probe=payload.get("probe", True))
        return {"result": result}

    def ingest(payload, job):
        from search_results import fuse_results
        from settings import Settings
        settings = Settings() if settings_factory is None else settings_factory()
        archive_dir = settings.load()["archive"]["directory"] if payload.get("archive") else None
        result = fuse_results(payload, archive=bool(payload.get("archive")),
                              archive_dir=archive_dir, settings=settings)
        return {"result": result}

    def research(payload, job):
        from research_services import ResearchServices
        from settings import Settings
        settings = Settings() if settings_factory is None else settings_factory()
        result = ResearchServices(settings=settings).start(**payload)
        return {"result": result}

    return {"fetch": fetch, "ingest": ingest, "research": research}
