"""Source observations for invalidation only; never authority for a new claim."""
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class SourceVersions:
    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def timestamp(value):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        except (ValueError, TypeError, AttributeError):
            return None

    def _connect(self):
        if self.path.is_symlink():
            raise ValueError("Source version index must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE IF NOT EXISTS snapshots (seq INTEGER PRIMARY KEY, "
                           "url TEXT NOT NULL, scope_id TEXT NOT NULL, source_id TEXT NOT NULL, sha256 TEXT NOT NULL, "
                           "acquired_at TEXT, observed_at TEXT NOT NULL, provider TEXT, verdict TEXT, "
                           "UNIQUE(scope_id,source_id,sha256))")
        connection.execute("CREATE INDEX IF NOT EXISTS snapshots_url ON snapshots(url,seq)")
        connection.execute("CREATE TABLE IF NOT EXISTS checks (url TEXT PRIMARY KEY, attempted_at TEXT NOT NULL, "
                           "status TEXT NOT NULL)")
        return connection

    def record(self, scope_id, sources):
        from archive import SourceArchive
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for source in sources:
            if (not re.fullmatch(r"[a-f0-9]{64}", source.get("sha256") or "")
                    or (source.get("provenance") or {}).get("kind") in ("local_document", "external_report")
                    or source.get("evidence_kind", "page") != "page"):
                continue
            acquired = self.timestamp(source.get("retrieved_at"))
            rows.append((SourceArchive._key(source["url"]), scope_id, source["id"], source["sha256"],
                         acquired.astimezone(timezone.utc).isoformat(timespec="microseconds") if acquired else None,
                         now, source.get("provider"),
                         source.get("review", {}).get("verdict", "unreviewed")))
        if not rows:
            return
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                "INSERT INTO snapshots(url,scope_id,source_id,sha256,acquired_at,observed_at,provider,verdict) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(scope_id,source_id,sha256) "
                "DO UPDATE SET verdict=excluded.verdict WHERE snapshots.verdict != excluded.verdict", rows)

    def record_check(self, url, status):
        from archive import SourceArchive
        with closing(self._connect()) as connection, connection:
            connection.execute("INSERT INTO checks VALUES (?,?,?) ON CONFLICT(url) "
                               "DO UPDATE SET attempted_at=excluded.attempted_at,status=excluded.status",
                               (SourceArchive._key(url), datetime.now(timezone.utc).isoformat(), status))

    def inspect(self, url, sha256, acquired_at, published_at, scope_id=None, source_id=None):
        from archive import SourceArchive
        if not self.path.is_file():
            return {"available": False, "latest": None, "newer": None, "last_attempt": None}
        with closing(self._connect()) as connection:
            key = SourceArchive._key(url)
            baseline = connection.execute("SELECT seq FROM snapshots WHERE scope_id=? AND source_id=? AND sha256=?",
                                          (scope_id, source_id, sha256)).fetchone()
            latest = connection.execute("SELECT * FROM snapshots WHERE url=? AND verdict NOT IN ('rejected','uncertain') "
                                        "ORDER BY COALESCE(acquired_at,observed_at) DESC,seq DESC LIMIT 1",
                                        (key,)).fetchone()
            checked = connection.execute("SELECT * FROM checks WHERE url=?", (key,)).fetchone()
        newer = None
        if latest is not None and latest["sha256"] != sha256:
            after = baseline is not None and latest["seq"] > baseline["seq"]
            old_time, new_time = self.timestamp(acquired_at), self.timestamp(latest["acquired_at"])
            seen, published = self.timestamp(latest["observed_at"]), self.timestamp(published_at)
            if baseline is None:
                after = bool((old_time and new_time and new_time > old_time)
                             or (seen and published and seen > published))
            # Importing an older historical source must not supersede a newer
            # observation merely because the import happened later.
            if after and not (old_time and new_time and new_time < old_time):
                newer = dict(latest)
        return {"available": True, "latest": dict(latest) if latest else None, "newer": newer,
                "last_attempt": dict(checked) if checked else None}
