"""Small TTL cache for identical fetch batches.

Repeating the same research within the window should not pay the provider twice.
The cache stores the compact result the caller would have received, and callers
mark reused rows so provenance stays explicit.
"""
import hashlib
import json
import sqlite3
import time
from pathlib import Path


class FetchCache:
    def __init__(self, path=None):
        from settings import Settings
        self.path = Path(path or (Settings.data_directory() / "fetch-cache.sqlite3")).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path), timeout=5.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS fetch_cache ("
            " cache_key TEXT PRIMARY KEY, urls TEXT NOT NULL, provider TEXT,"
            " result TEXT NOT NULL, stored_at REAL NOT NULL, retrieved_at TEXT NOT NULL)")
        self.connection.commit()

    def close(self):
        self.connection.close()

    @staticmethod
    def key(urls, provider, archive, max_characters):
        payload = json.dumps({"urls": list(urls), "provider": provider,
                              "archive": bool(archive), "max_characters": max_characters},
                             ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, cache_key, ttl_seconds):
        if not ttl_seconds or ttl_seconds <= 0:
            return None
        row = self.connection.execute(
            "SELECT result, stored_at FROM fetch_cache WHERE cache_key=?", (cache_key,)).fetchone()
        if row is None:
            return None
        age = time.time() - row["stored_at"]
        if age > ttl_seconds:
            return None
        try:
            return json.loads(row["result"]), age
        except ValueError:
            return None

    MAX_ROWS = 500

    def prune(self, ttl_seconds=0):
        cutoff = time.time() - max(0, float(ttl_seconds or 0))
        deleted = self.connection.execute(
            "DELETE FROM fetch_cache WHERE stored_at < ?", (cutoff,)).rowcount if ttl_seconds else 0
        deleted += self.connection.execute(
            "DELETE FROM fetch_cache WHERE cache_key NOT IN ("
            "SELECT cache_key FROM fetch_cache ORDER BY stored_at DESC LIMIT ?)",
            (self.MAX_ROWS,)).rowcount
        self.connection.commit()
        return deleted

    def put(self, cache_key, urls, provider, result):
        self.connection.execute(
            "INSERT OR REPLACE INTO fetch_cache (cache_key, urls, provider, result, stored_at, retrieved_at)"
            " VALUES (?,?,?,?,?,?)",
            (cache_key, json.dumps(list(urls), ensure_ascii=False), provider,
             json.dumps(result, ensure_ascii=False, allow_nan=False),
             time.time(), result.get("retrieved_at") or ""))
        self.connection.commit()
        self.prune(86400)
