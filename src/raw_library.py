"""Derived full-text index of saved raw page text: knowledge archive plus research evidence.

The index is a rebuildable cache in its own SQLite file (default
``<data dir>/raw-library.sqlite3``); the main bookmark index is never touched.
One document is stored per distinct body (by SHA-256) with every place it
occurs: archive captures and research task sources.

Refresh strategy: every search first rescans cheaply. Each archive capture
(``manifest.json``) and each research task (``state.json``) is one scan unit
whose signature is the (mtime_ns, size) of that file plus every body file it
referenced last time. Unchanged units are skipped; new or changed units are
re-read, bodies are re-hashed and only bodies whose SHA-256 matches the
recorded value are indexed. Units that disappeared (deleted captures, moved or
missing task folders) drop out of the index. Archive writes do not update the
index directly; the next search picks them up.
"""

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from settings import Settings

SCHEMA_VERSION = 1
MAX_BODY_BYTES = 50 * 1024 * 1024
MAX_TERMS = 16
TRIGRAM_MINIMUM = 3


def _trigram_available():
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(body, tokenize='trigram')")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        connection.close()


def _stamp(path):
    try:
        stat = os.stat(str(path))
    except OSError:
        return None
    return [stat.st_mtime_ns, stat.st_size]


def _inside(root, target):
    return root == target or root in target.parents


def _text(value):
    return value if isinstance(value, str) and value else None


class RawLibrary:
    """Literal full-text search over saved page bodies, merged by content hash."""

    def __init__(self, db_path=None, archive_directory=None, data_directory=None, settings=None,
                 research_roots=None):
        self.data_directory = Path(data_directory) if data_directory is not None else Settings.data_directory()
        self.db_path = Path(db_path) if db_path is not None else self.data_directory / "raw-library.sqlite3"
        preferences = settings.load() if settings is not None else None
        if archive_directory is None:
            archive_directory = (preferences["archive"]["directory"] if preferences
                                 else str(self.data_directory / "knowledge"))
        from archive import SourceArchive
        self.archive = SourceArchive(archive_directory)
        roots = [self.data_directory / "research"]
        output = (preferences or {}).get("output")
        if isinstance(output, dict) and isinstance(output.get("directory"), str):
            roots.append(Path(output["directory"]))
        roots.extend(Path(root) for root in (research_roots or []))
        self.research_roots = list(dict.fromkeys(roots))
        self.mode = "trigram" if _trigram_available() else "substring"

    # Storage -----------------------------------------------------------------

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (0, 1):
            connection = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                self._schema(connection)
                return connection
            except sqlite3.DatabaseError:
                connection.close()
                if attempt:
                    raise
                # A derived cache: a damaged file is discarded and rebuilt.
                for suffix in ("", "-wal", "-shm"):
                    candidate = Path(str(self.db_path) + suffix)
                    if candidate.exists():
                        candidate.unlink()

    def _schema(self, connection):
        connection.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        stored = dict(connection.execute("SELECT key, value FROM meta").fetchall())
        if stored == {"schema_version": str(SCHEMA_VERSION), "mode": self.mode}:
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table in ("page_text", "documents", "occurrences", "units"):
                connection.execute("DROP TABLE IF EXISTS " + table)
            connection.execute("CREATE TABLE documents(id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, "
                               "characters INTEGER NOT NULL)")
            if self.mode == "trigram":
                connection.execute("CREATE VIRTUAL TABLE page_text USING fts5(body, tokenize='trigram')")
            else:
                connection.execute("CREATE TABLE page_text(rowid INTEGER PRIMARY KEY, body TEXT NOT NULL)")
            connection.execute("CREATE TABLE occurrences(unit TEXT NOT NULL, position INTEGER NOT NULL, "
                               "sha256 TEXT NOT NULL, kind TEXT NOT NULL, capture_id TEXT, research_id TEXT, "
                               "source_id TEXT, path TEXT NOT NULL, url TEXT, title TEXT, retrieved_at TEXT, "
                               "PRIMARY KEY(unit, position))")
            connection.execute("CREATE INDEX occurrences_sha256 ON occurrences(sha256)")
            connection.execute("CREATE TABLE units(unit TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                               "signature TEXT NOT NULL, files TEXT NOT NULL, skipped INTEGER NOT NULL, "
                               "error TEXT)")
            connection.execute("DELETE FROM meta")
            connection.executemany("INSERT INTO meta(key, value) VALUES (?, ?)",
                                   [("schema_version", str(SCHEMA_VERSION)), ("mode", self.mode)])
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    # Discovery ---------------------------------------------------------------

    def _task_directories(self, report):
        candidates = []
        import research_locations
        try:
            registered = research_locations.load()
        except (OSError, ValueError) as error:
            registered = {}
            report["errors"].append({"kind": "registry", "error": str(error)[:500]})
        for entry in registered.values():
            path = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(path, str) or not Path(path).is_absolute():
                report["missing_tasks"] += 1
                continue
            candidates.append((Path(path), True))
        for root in self.research_roots:
            if root.is_symlink() or not root.is_dir():
                continue
            candidates.extend((child, False) for child in sorted(root.glob("r-*")))
        seen = set()
        for path, registered_entry in candidates:
            # Never follow a symlinked task folder: its contents live outside the roots.
            if path.is_symlink() or not (path / "state.json").is_file() or (path / "state.json").is_symlink():
                if registered_entry:
                    report["missing_tasks"] += 1
                continue
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved

    def _units(self, report):
        for capture_id, directory in self.archive.captures():
            yield "archive:" + str(directory.resolve()), "archive", directory.resolve() / "manifest.json", capture_id
        for directory in self._task_directories(report):
            yield "research:" + str(directory), "research", directory / "state.json", None

    # Indexing ----------------------------------------------------------------

    def _items(self, kind, primary, capture_id):
        """Return occurrence candidates: dicts with target path (or error), sha256 and metadata."""
        if primary.is_symlink():
            raise ValueError("Scan file must not be a symlink")
        value = json.loads(primary.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Unexpected JSON document")
        items = []
        if kind == "archive":
            directory = primary.parent
            for entry in value.get("pages") or []:
                if not isinstance(entry, dict) or not _text(entry.get("body_file")) or not _text(entry.get("sha256")):
                    continue
                item = {"sha256": entry["sha256"], "kind": "archive", "capture_id": capture_id,
                        "url": _text(entry.get("requested_url")), "title": _text(entry.get("title")),
                        "retrieved_at": _text(value.get("retrieved_at"))}
                try:
                    item["target"] = self.archive.page_path(directory, entry)
                except ValueError as error:
                    item["error"] = str(error)
                items.append(item)
        else:
            directory = primary.parent
            research_id = _text(value.get("research_id")) or directory.name
            for source in value.get("sources") or []:
                if not isinstance(source, dict) or not _text(source.get("body_file")) or not _text(source.get("sha256")):
                    continue
                item = {"sha256": source["sha256"], "kind": "research", "research_id": research_id,
                        "source_id": _text(source.get("id")), "url": _text(source.get("url")),
                        "title": _text(source.get("title")),
                        "retrieved_at": _text(source.get("retrieved_at")) or _text(source.get("imported_at"))}
                relative = source["body_file"]
                target = (directory / relative).resolve()
                if "\x00" in relative or Path(relative).is_absolute() or not _inside(directory, target) or target == directory:
                    item["error"] = "Research body is outside its task folder"
                else:
                    item["target"] = target
                items.append(item)
        return items

    def _index_unit(self, connection, unit, kind, primary, capture_id, report):
        connection.execute("DELETE FROM occurrences WHERE unit = ?", (unit,))
        stamps = [[str(primary), _stamp(primary)]]
        files, skipped, error = [], 0, None
        try:
            items = self._items(kind, primary, capture_id)
        except (OSError, ValueError, UnicodeDecodeError) as failure:
            items, error = [], str(failure)[:500]
            report["errors"].append({"unit": unit, "error": error})
        position = 0
        for item in items:
            target = item.get("target")
            if target is None:
                skipped += 1
                continue
            files.append(str(target))
            stamps.append([str(target), _stamp(target)])
            try:
                if target.stat().st_size > MAX_BODY_BYTES:
                    raise ValueError("Body file is too large to index")
                data = target.read_bytes()
                if hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise ValueError("SHA-256 mismatch")
                body = data.decode("utf-8")
            except (OSError, ValueError, UnicodeDecodeError):
                skipped += 1
                continue
            known = connection.execute("SELECT 1 FROM documents WHERE sha256 = ?", (item["sha256"],)).fetchone()
            if known is None:
                cursor = connection.execute("INSERT INTO documents(sha256, characters) VALUES (?, ?)",
                                            (item["sha256"], len(body)))
                connection.execute("INSERT INTO page_text(rowid, body) VALUES (?, ?)", (cursor.lastrowid, body))
                report["new_documents"] += 1
            connection.execute(
                "INSERT INTO occurrences(unit, position, sha256, kind, capture_id, research_id, source_id, path, "
                "url, title, retrieved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (unit, position, item["sha256"], item["kind"], item.get("capture_id"), item.get("research_id"),
                 item.get("source_id"), str(target), item["url"], item["title"], item["retrieved_at"]))
            position += 1
        connection.execute("INSERT OR REPLACE INTO units(unit, kind, signature, files, skipped, error) "
                           "VALUES (?, ?, ?, ?, ?, ?)",
                           (unit, kind, json.dumps(stamps), json.dumps(files), skipped, error))
        report["scanned_units"] += 1

    def _refresh(self, connection):
        report = {"scanned_units": 0, "removed_units": 0, "new_documents": 0, "missing_tasks": 0, "errors": []}
        connection.execute("BEGIN IMMEDIATE")
        try:
            known = {row[0]: (row[1], json.loads(row[2])) for row in
                     connection.execute("SELECT unit, signature, files FROM units")}
            current = set()
            for unit, kind, primary, capture_id in self._units(report):
                current.add(unit)
                previous = known.get(unit)
                if previous is not None:
                    signature = json.dumps([[str(primary), _stamp(primary)]] +
                                           [[path, _stamp(path)] for path in previous[1]])
                    if signature == previous[0]:
                        continue
                self._index_unit(connection, unit, kind, primary, capture_id, report)
            for unit in set(known) - current:
                connection.execute("DELETE FROM occurrences WHERE unit = ?", (unit,))
                connection.execute("DELETE FROM units WHERE unit = ?", (unit,))
                report["removed_units"] += 1
            orphaned = "SELECT id FROM documents WHERE sha256 NOT IN (SELECT sha256 FROM occurrences)"
            connection.execute("DELETE FROM page_text WHERE rowid IN (" + orphaned + ")")
            connection.execute("DELETE FROM documents WHERE id IN (" + orphaned + ")")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return report

    def _statistics(self, connection, report):
        documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        occurrences = connection.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0]
        skipped = connection.execute("SELECT COALESCE(SUM(skipped), 0) FROM units").fetchone()[0]
        errors = [{"unit": unit, "error": error} for unit, error in
                  connection.execute("SELECT unit, error FROM units WHERE error IS NOT NULL ORDER BY unit LIMIT 20")]
        return {"documents": documents, "occurrences": occurrences, "skipped": skipped,
                "missing_tasks": report["missing_tasks"], "scanned_units": report["scanned_units"],
                "removed_units": report["removed_units"], "new_documents": report["new_documents"],
                "errors": errors + [row for row in report["errors"] if "unit" not in row],
                "database": str(self.db_path), "archive_directory": str(self.archive.directory)}

    def refresh(self):
        """Bring the index up to date and return counts; skipped counts unverifiable bodies."""
        connection = self._connect()
        try:
            return self._statistics(connection, self._refresh(connection))
        finally:
            connection.close()

    # Search ------------------------------------------------------------------

    @staticmethod
    def _terms(query):
        if not isinstance(query, str) or "\x00" in query or not 1 <= len(query) <= 500 or not query.strip():
            raise ValueError("query must be 1 to 500 characters")
        stripped = query.strip()
        if len(stripped) > 1 and stripped.startswith('"') and stripped.endswith('"') and stripped[1:-1].strip():
            return [stripped[1:-1]]
        terms = list(dict.fromkeys(stripped.split()))
        if len(terms) > MAX_TERMS:
            raise ValueError("query may contain at most %s terms" % MAX_TERMS)
        return terms

    @staticmethod
    def _snippet(body, terms, width=240):
        positions = []
        for term in terms:
            match = re.search(re.escape(term), body, re.IGNORECASE)
            if match:
                positions.append(match.start())
        start = max(0, (min(positions) if positions else 0) - width // 3)
        text = body[start:start + width]
        text = re.sub(r"\s+", " ", text).strip()
        return ("…" if start > 0 else "") + text + ("…" if start + width < len(body) else "")

    def search(self, query, limit=10, offset=0, url=None):
        """Literal search over saved page text; every term must occur (quoted query = one phrase)."""
        terms = self._terms(query)
        for value, label, minimum, maximum in ((limit, "limit", 1, 50), (offset, "offset", 0, 10000000)):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("%s must be between %s and %s" % (label, minimum, maximum))
        if url is not None and (not isinstance(url, str) or not url or len(url) > 2048 or "\x00" in url):
            raise ValueError("url filter must be 1 to 2048 characters")
        connection = self._connect()
        try:
            report = self._refresh(connection)
            indexed = self._statistics(connection, report)
            fts = self.mode == "trigram" and all(len(term) >= TRIGRAM_MINIMUM for term in terms)
            clauses, parameters = [], []
            if fts:
                clauses.append("page_text MATCH ?")
                parameters.append(" ".join('"%s"' % term.replace('"', '""') for term in terms))
            else:
                for term in terms:
                    clauses.append("instr(lower(page_text.body), lower(?)) > 0")
                    parameters.append(term)
            if url is not None:
                clauses.append("d.sha256 IN (SELECT sha256 FROM occurrences WHERE instr(lower(url), lower(?)) > 0)")
                parameters.append(url)
            base = ("FROM page_text JOIN documents d ON d.id = page_text.rowid WHERE " + " AND ".join(clauses))
            total = connection.execute("SELECT COUNT(*) " + base, parameters).fetchone()[0]
            order = "bm25(page_text), d.id DESC" if fts else "d.id DESC"
            rows = connection.execute("SELECT d.sha256, d.characters, page_text.body " + base +
                                      " ORDER BY " + order + " LIMIT ? OFFSET ?",
                                      parameters + [limit, offset]).fetchall()
            results = []
            for sha256, characters, body in rows:
                occurrences = []
                for row in connection.execute(
                        "SELECT kind, capture_id, research_id, source_id, path, url, title, retrieved_at "
                        "FROM occurrences WHERE sha256 = ? ORDER BY unit, position", (sha256,)):
                    kind, capture_id, research_id, source_id, path, found_url, title, retrieved_at = row
                    entry = {"kind": kind}
                    if kind == "archive":
                        entry["capture_id"] = capture_id
                    else:
                        entry.update(research_id=research_id, source_id=source_id)
                    entry.update(path=path, url=found_url, title=title, retrieved_at=retrieved_at)
                    occurrences.append(entry)
                occurrences.sort(key=lambda entry: entry["retrieved_at"] or "", reverse=True)
                results.append({"sha256": sha256, "characters": characters,
                                "url": next((entry["url"] for entry in occurrences if entry["url"]), None),
                                "title": next((entry["title"] for entry in occurrences if entry["title"]), None),
                                "snippet": self._snippet(body, terms),
                                "occurrence_count": len(occurrences), "occurrences": occurrences[:50]})
        finally:
            connection.close()
        next_offset = offset + len(results)
        return {"query": query, "total": total, "offset": offset,
                "next_offset": next_offset if next_offset < total else None,
                "match": "fts_trigram" if fts else "substring", "results": results, "indexed": indexed,
                "note": "Literal matching over saved page text (knowledge archive and research evidence); "
                        "not web search and not semantic retrieval. Identical bodies are merged by SHA-256."}
