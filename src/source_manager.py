"""Stable source registration, managed snapshots and conservative live refresh."""

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from bookmark_index import _dump, _inside, _string
from source_inputs import fingerprint, git_busy, git_directory, hashes, read_input


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS source_records (
        source_id TEXT PRIMARY KEY REFERENCES sources(source_id), record_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS source_aliases (
        source_id TEXT NOT NULL REFERENCES sources(source_id), input_path TEXT NOT NULL,
        PRIMARY KEY(source_id,input_path))""",
    """CREATE TABLE IF NOT EXISTS source_snapshots (
        source_id TEXT NOT NULL REFERENCES sources(source_id), version_id TEXT NOT NULL,
        created_at TEXT NOT NULL, snapshot_path TEXT NOT NULL, manifest_json TEXT NOT NULL,
        PRIMARY KEY(source_id,version_id))""",
)


class SourceManager:
    def __init__(self, index, clock=time.time, debounce=2.0, deletion_grace=5.0):
        self.index, self.connection = index, index.connection
        self.clock, self.debounce, self.deletion_grace = clock, debounce, deletion_grace
        self.storage = index.db_path.with_name(index.db_path.name + ".sources") if index.db_path else None
        with index.transaction():
            for statement in SCHEMA:
                self.connection.execute(statement)

    def _now(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()

    def _record(self, source_id):
        row = self.connection.execute("SELECT record_json FROM source_records WHERE source_id=?", (source_id,)).fetchone()
        if row:
            return json.loads(row[0])
        source = self.index._source(source_id)
        # Existing installations retain their original refresh/partial behavior.
        return {"mode": "live", "completeness": "partial", "input_path": source["package_path"],
                "input_kind": "directory", "state": "unchecked", "legacy": True,
                "observed_hashes": {}, "pending_files": [], "version_id": None,
                "snapshot_path": None, "checked_at": None, "error": None}

    def _save(self, source_id, record):
        self.connection.execute("""INSERT INTO source_records VALUES(?,?)
            ON CONFLICT(source_id) DO UPDATE SET record_json=excluded.record_json""", (source_id, _dump(record)))

    def _identity(self, path, source_id):
        if source_id is not None:
            _string(source_id, "source_id", True)
            if len(source_id) > 512:
                raise ValueError("source_id exceeds 512 characters")
            return source_id
        matches = {row[0] for row in self.connection.execute("""SELECT source_id FROM source_aliases WHERE input_path=?
            UNION SELECT source_id FROM sources WHERE package_path=?
            UNION SELECT source_id FROM source_snapshots WHERE snapshot_path=?""", (str(path), str(path), str(path)))}
        if len(matches) > 1:
            raise ValueError("Multiple sources use this path; provide source_id")
        return next(iter(matches)) if matches else "source-" + uuid.uuid4().hex[:16]

    def _section_paths(self, source_id):
        return {row[0]: row[1] for row in self.connection.execute(
            "SELECT section_id,file_path FROM sections WHERE source_id=?", (source_id,))}

    @staticmethod
    def _write_files(root, files):
        for relative, raw in files.items():
            path = root / relative
            if not _inside(path.resolve(), root.resolve()) or path == root:
                raise ValueError("Snapshot file escaped its directory")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def _bindings(self, source_id):
        return {
            "anchors": [dict(row) for row in self.connection.execute(
                "SELECT section_id,canonical_id FROM sections WHERE source_id=? AND is_anchor=1 ORDER BY section_id", (source_id,))],
            "nodes": [dict(row) for row in self.connection.execute("""SELECT canvas_path,node_id,file_path,section_id
                FROM nodes WHERE source_id=? AND node_type='file' ORDER BY canvas_path,node_id""", (source_id,))],
        }

    @staticmethod
    def _imported_snapshot(prepared):
        path = Path(prepared["path"])
        manifest_path = path.parent / "manifest.json"
        if prepared["kind"] != "directory" or path.name != "package" or not manifest_path.is_file():
            return None
        if manifest_path.is_symlink() or manifest_path.stat().st_size > 8000000:
            raise ValueError("Invalid managed snapshot manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Invalid managed snapshot manifest")
        if manifest.get("format") != "bookmark-research-snapshot":
            return None
        content = {"files": prepared["hashes"], "bindings": manifest.get("bindings")}
        if (manifest.get("files") != prepared["hashes"] or
                manifest.get("version_id") != "v-" + fingerprint(content)):
            raise ValueError("Managed snapshot integrity check failed")
        return manifest

    def _restore_bindings(self, source_id, bindings):
        """Preserve earlier layout mappings when a partial export renamed a card.

        Raw files remain byte-for-byte unchanged. Only validated, in-source
        associations from the hash-checked snapshot manifest are restored.
        """
        if not isinstance(bindings, dict) or set(bindings) != {"anchors", "nodes"}:
            raise ValueError("Invalid snapshot bindings")
        for key, expected in (("anchors", {"section_id", "canonical_id"}),
                              ("nodes", {"canvas_path", "node_id", "file_path", "section_id"})):
            if not isinstance(bindings[key], list) or len(bindings[key]) > 10000:
                raise ValueError("Invalid snapshot binding list")
            seen = set()
            for entry in bindings[key]:
                if not isinstance(entry, dict) or set(entry) != expected:
                    raise ValueError("Invalid snapshot binding entry")
                for field, value in entry.items():
                    if value is None and (field == "canonical_id" or key == "nodes" and field == "section_id"):
                        continue
                    _string(value, "snapshot binding " + field, True)
                identity = entry["section_id"] if key == "anchors" else (entry["canvas_path"], entry["node_id"])
                if identity in seen:
                    raise ValueError("Duplicate snapshot binding")
                seen.add(identity)
        sections = {row["section_id"]: dict(row) for row in self.connection.execute(
            "SELECT * FROM sections WHERE source_id=?", (source_id,))}
        for anchor in bindings["anchors"]:
            sid, target = anchor["section_id"], anchor["canonical_id"]
            if sid not in sections or not sections[sid]["is_anchor"] or (target is not None and
                    (target not in sections or sections[target]["is_anchor"] or sections[target]["section_type"] != "permanent")):
                raise ValueError("Snapshot anchor target is not a primary section")
            self.connection.execute("UPDATE sections SET canonical_id=? WHERE source_id=? AND section_id=?", (target, source_id, sid))
        for node in bindings["nodes"]:
            sid = node["section_id"]
            if sid is not None and sid not in sections:
                raise ValueError("Snapshot node target is not in this source")
            row = self.connection.execute("SELECT file_path FROM nodes WHERE source_id=? AND canvas_path=? AND node_id=? AND node_type='file'",
                (source_id, node["canvas_path"], node["node_id"])).fetchone()
            if row is None or row[0] != node["file_path"]:
                raise ValueError("Snapshot node binding does not match its raw file")
            self.connection.execute("UPDATE nodes SET section_id=? WHERE source_id=? AND canvas_path=? AND node_id=?",
                (sid, source_id, node["canvas_path"], node["node_id"]))

    def sync(self, package_path, source_id=None, mode=None, completeness=None):
        path = Path(package_path).expanduser().resolve()
        if mode not in (None, "snapshot", "live") or completeness not in (None, "partial", "complete"):
            raise ValueError("Use mode=snapshot/live and completeness=partial/complete")
        if self.storage is None:
            raise ValueError("Managed sources require a persistent database")
        if path.is_dir() and (_inside(self.index.db_path, path) or _inside(self.storage, path)):
            raise ValueError("Keep the database and snapshots outside the imported package")
        with self.index.transaction():
            source_id = self._identity(path, source_id)
            exists = self.connection.execute("SELECT 1 FROM sources WHERE source_id=?", (source_id,)).fetchone()
            previous = self._record(source_id) if exists else None
            prepared = read_input(path, self._section_paths(source_id))
            imported = self._imported_snapshot(prepared)
            if imported and mode == "live":
                raise ValueError("Managed snapshots are immutable; use mode=snapshot")
            mode = mode or ("snapshot" if imported else previous["mode"] if previous else
                            "live" if prepared["kind"] == "directory" and git_directory(path) else "snapshot")
            if mode == "live" and prepared["kind"] != "directory":
                raise ValueError("Live sources require a directory; pass mode=snapshot to replace this source with an export")
            if prepared["single_section"]:
                if completeness == "complete":
                    raise ValueError("A single card is a partial export; use completeness=partial")
                completeness = "partial"
            completeness = completeness or (previous["completeness"] if previous else "partial")
            return self._ingest(prepared, source_id, mode, completeness, previous)

    def _ingest(self, prepared, source_id, mode, completeness, previous):
        if mode == "live" and git_busy(prepared["path"]):
            raise ValueError("Git is updating this directory; retry after its lock is released")
        imported = self._imported_snapshot(prepared)
        old_source = self.index._source(source_id) if previous else None
        old_files = {row["file_path"]: dict(row) for row in self.connection.execute(
            "SELECT * FROM files WHERE source_id=?", (source_id,))}
        if self.storage.is_symlink():
            raise ValueError("Snapshot storage must not be a symlink")
        self.storage.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ingest-", dir=self.storage) as staging:
            incoming = Path(staging) / "incoming"
            incoming.mkdir()
            self._write_files(incoming, prepared["files"])
            summary = self.index.sync(incoming, source_id, completeness=completeness)
            if imported:
                self._restore_bindings(source_id, imported["bindings"])
                summary["warnings"].append("Restored recorded snapshot relationships; raw files were not rewritten")
            elif completeness == "complete" and any(warning.startswith("Unresolved") for warning in summary["warnings"]):
                raise ValueError("Complete export contains unresolved references; retain the previous index until all files agree")
            files, recovered = {}, []
            for row in self.connection.execute("SELECT * FROM files WHERE source_id=? ORDER BY file_path", (source_id,)).fetchall():
                name = row["file_path"]
                raw = prepared["files"].get(name)
                if raw is None:
                    root = Path(previous["snapshot_path"] or old_source["package_path"])
                    candidate = root / name
                    if candidate.is_file() and not candidate.is_symlink() and _inside(candidate.resolve(), root.resolve()):
                        raw = candidate.read_bytes()
                    if raw is None or hashlib.sha256(raw).hexdigest() != old_files[name]["sha256"]:
                        if previous.get("snapshot_path"):
                            raise ValueError("Saved snapshot is missing or changed: " + name)
                        # Legacy SQLite retained complete JSON, but not its
                        # original whitespace. Record this recovery explicitly.
                        raw = row["raw_json"].encode("utf-8")
                        recovered.append(name)
                        self.connection.execute("UPDATE files SET sha256=?,revision=revision+1 WHERE source_id=? AND file_path=?",
                            (hashlib.sha256(raw).hexdigest(), source_id, name))
                files[name] = raw
            content = {"files": hashes(files), "bindings": self._bindings(source_id)}
            version_id = "v-" + fingerprint(content)
            source_directory = self.storage / hashlib.sha256(source_id.encode("utf-8")).hexdigest()
            destination = source_directory / version_id
            snapshot_path = destination / "package"
            manifest = {"format": "bookmark-research-snapshot", "schema_version": 1,
                "source_id": source_id, "version_id": version_id, "created_at": self._now(),
                "input_path": prepared["path"], "input_kind": prepared["kind"], "completeness": completeness,
                "provided_files": sorted(prepared["files"]), "recovered_legacy_files": recovered, **content}
            staged_snapshot = Path(staging) / "snapshot"
            self._write_files(staged_snapshot / "package", files)
            (staged_snapshot / "manifest.json").write_bytes(_dump(manifest).encode("utf-8"))
            if source_directory.is_symlink() or destination.is_symlink():
                raise ValueError("Managed snapshot directories must not be symlinks")
            source_directory.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                saved = read_input(snapshot_path)
                existing = self._imported_snapshot(saved)
                if existing is None or existing["version_id"] != version_id:
                    raise ValueError("Existing managed snapshot integrity check failed")
            else:
                os.replace(staged_snapshot, destination)
            # Recheck the source after staging. A Git pull or editor save in
            # flight must not publish a mixture of file generations.
            if mode == "live" and (git_busy(prepared["path"]) or
                    read_input(prepared["path"])["fingerprint"] != prepared["fingerprint"]):
                raise ValueError("Source changed during import; retry after its files settle")
            self.connection.execute("INSERT OR IGNORE INTO source_snapshots VALUES(?,?,?,?,?)",
                (source_id, version_id, manifest["created_at"], str(snapshot_path), _dump(manifest)))
            if previous:
                self.connection.execute("INSERT OR IGNORE INTO source_aliases VALUES(?,?)", (source_id, previous["input_path"]))
            self.connection.execute("INSERT OR IGNORE INTO source_aliases VALUES(?,?)", (source_id, prepared["path"]))
            record = {"mode": mode, "completeness": completeness, "input_path": prepared["path"],
                "input_kind": prepared["kind"], "version_id": version_id, "snapshot_path": str(snapshot_path),
                "observed_hashes": prepared["hashes"], "checked_at": self._now(),
                "state": "snapshot" if mode == "snapshot" else "current", "error": None,
                "pending_files": [], "pending_fingerprint": None, "pending_since": None,
                "retained_missing_files": summary["retained_missing_files"], "legacy": False}
            self._save(source_id, record)
            active_path = str(snapshot_path) if mode == "snapshot" else prepared["path"]
            self.connection.execute("UPDATE sources SET package_path=? WHERE source_id=?", (active_path, source_id))
            if recovered:
                summary["warnings"].append("Recovered legacy JSON from SQLite without original whitespace: " + ", ".join(recovered))
            summary.update(package_path=active_path, input_path=prepared["path"], input_kind=prepared["kind"],
                           mode=mode, completeness=completeness, version_id=version_id,
                           snapshot_path=str(snapshot_path), state=record["state"], performed=True)
            return summary

    def _observation(self, source_id, record, state, **fields):
        record.update(state=state, checked_at=self._now(), **fields)
        self._save(source_id, record)
        return {"source_id": source_id, "mode": record["mode"], "state": state, "performed": False,
                "changed_files": 0, "items_inserted": 0, "items_updated": 0, "items_deleted": 0,
                "pending_files": record.get("pending_files", []), "error": record.get("error"),
                "version_id": record.get("version_id"), "checked_at": record["checked_at"]}

    def refresh(self, source_id, force=True):
        record = self._record(source_id)
        if record["mode"] == "snapshot":
            return {"source_id": source_id, "mode": "snapshot", "state": "snapshot", "performed": False,
                    "changed_files": 0, "version_id": record["version_id"], "snapshot_path": record["snapshot_path"]}
        try:
            with self.index.transaction():
                record = self._record(source_id)
                if record["mode"] == "snapshot":
                    return self.refresh(source_id, force)
                if git_busy(record["input_path"]):
                    return self._observation(source_id, record, "pending", error="Git is updating the source",
                        pending_fingerprint=None, pending_since=None)
                prepared = read_input(record["input_path"])
                before = record["observed_hashes"] or {row[0]: row[1] for row in self.connection.execute(
                    "SELECT file_path,sha256 FROM files WHERE source_id=?", (source_id,))}
                after = prepared["hashes"]
                pending = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
                if not pending:
                    return self._observation(source_id, record, "current", observed_hashes=after, pending_files=[],
                        pending_fingerprint=None, pending_since=None, error=None)
                deletion = bool(before.keys() - after.keys()) and record["completeness"] == "complete"
                delay = self.deletion_grace if deletion else self.debounce
                same = record.get("pending_fingerprint") == prepared["fingerprint"]
                since = record.get("pending_since") if same else self.clock()
                if not (force and not deletion) and (since is None or self.clock() - since < delay):
                    return self._observation(source_id, record, "pending", pending_files=pending,
                        pending_fingerprint=prepared["fingerprint"], pending_since=since, error=None)
                return self._ingest(prepared, source_id, "live", record["completeness"], record)
        except (ValueError, OSError, sqlite3.Error) as exc:
            with self.index.transaction():
                record = self._record(source_id)
                unavailable = not Path(record["input_path"]).is_dir() or "No protocol" in str(exc)
                return self._observation(source_id, record, "unavailable" if unavailable else "error", error=str(exc)[:2000],
                    pending_fingerprint=None, pending_since=None)

    def status(self, source_id=None):
        result = self.index.status(source_id)
        if source_id is None:
            result["source_schema_version"] = 1
            result["sources"] = [self.status(row["source_id"]) for row in result["sources"]]
            return result
        record = self._record(source_id)
        visible = {key: value for key, value in record.items() if key not in ("observed_hashes", "pending_fingerprint", "pending_since")}
        checked = record.get("checked_at")
        if record["mode"] == "live" and record["state"] == "current" and (not checked or
                self.clock() - datetime.fromisoformat(checked).timestamp() > 10):
            visible["state"] = "unchecked"
        visible["input_exists"] = Path(record["input_path"]).exists()
        visible["snapshot_exists"] = bool(record.get("snapshot_path") and Path(record["snapshot_path"]).is_dir())
        visible["aliases"] = [row[0] for row in self.connection.execute(
            "SELECT input_path FROM source_aliases WHERE source_id=? ORDER BY input_path", (source_id,))]
        result["source"] = visible
        return result

    def history(self, source_id, limit=20, offset=0):
        record = self._record(source_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100 or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("history needs limit=1..100 and a nonnegative offset")
        total = self.connection.execute("SELECT count(*) FROM source_snapshots WHERE source_id=?", (source_id,)).fetchone()[0]
        rows = self.connection.execute("SELECT * FROM source_snapshots WHERE source_id=? ORDER BY created_at DESC,version_id LIMIT ? OFFSET ?",
            (source_id, limit, offset)).fetchall()
        versions = []
        for row in rows:
            manifest = json.loads(row["manifest_json"])
            versions.append({key: row[key] for key in ("version_id", "created_at", "snapshot_path")})
            versions[-1].update(current=row["version_id"] == record["version_id"], file_count=len(manifest["files"]),
                input_path=manifest["input_path"], input_kind=manifest["input_kind"], completeness=manifest["completeness"])
        return {"source_id": source_id, "versions": versions, "total": total,
                "next_offset": offset + limit if offset + limit < total else None}

    def live_sources(self):
        return [row[0] for row in self.connection.execute("SELECT source_id FROM sources ORDER BY source_id")
                if self._record(row[0])["mode"] == "live"]
