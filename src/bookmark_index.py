"""Read-only Bookmark Canvas package ingestion and a persistent SQL query API.

Only the derived database is written. JSON/Canvas remains the source of truth.
Absent section files are retained; a supplied canvas replaces the previous entry.
"""

import hashlib
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import storage
from package_paths import (
    PROTOCOL_DIRS,
    dir_matches_section_type,
    is_package_dir,
    resolve_protocol_reference,
)


# The trigram tokenizer indexes three-character sequences; shorter patterns
# cannot use it and keep the LIKE fallback.
TRIGRAM_MINIMUM = 3

# URL shape is a retrieval signal, not a claim about the page: a documentation
# or changelog page is usually a better citation than a vendor homepage, while
# a login or search-result URL is almost never the requested source.
URL_KIND_RANK = {"docs": 0, "changelog": 0, "repo": 1, "other": 2, "homepage": 3, "login": 4,
                 "search": 4, "local_file": 5}


def url_kind(url):
    """Classify a bookmark URL for preflight ordering; never fetch it."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        path = (parts.path or "").lower()
        scheme = (parts.scheme or "").lower()
    except (TypeError, ValueError):
        return "other"
    if scheme not in ("http", "https"):
        return "local_file"
    if any(token in path for token in ("changelog", "release-notes", "release_notes", "whats-new", "whatsnew")):
        return "changelog"
    if host in ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org"):
        return "repo"
    if host.startswith("login.") or any(token in path for token in ("/login", "/signin", "/auth/", "/oauth")):
        return "login"
    if path.rstrip("/") in ("", "/") or path in ("", "/"):
        return "homepage"
    if "search" in path and parts.query:
        return "search"
    if (host.startswith(("docs.", "developer.", "developers.", "documentation.", "help.")) or ".docs." in host
            or any(token in path for token in ("/docs/", "/doc/", "/document/", "/documentation/", "/api/", "/reference/"))):
        return "docs"
    return "other"



# A question is reduced to literal terms: ASCII runs whole, CJK runs expanded
# into bigrams because a phrase the user typed rarely appears verbatim.
PLAN_RUN = re.compile(r"[0-9A-Za-z][0-9A-Za-z+._-]*|[㐀-䶿一-鿿]+")
QUESTION_URL = re.compile(r"https?://[^\s<>()\"']+")
PLAN_CJK_SPLITTERS = re.compile(r"(?:有哪些|有什么|是什么|怎么|如何|为什么|怎样|[有的和在与或等及从到把被让我你他它这那])")
PLAN_MAX_TERMS = 12


def question_urls(text):
    """The URLs a question already contains; the one shared URL extractor."""
    return QUESTION_URL.findall(text) if isinstance(text, str) else []


def title_has_term(title, term):
    """Whether a title contains the term as a token, not merely a substring.

    ASCII terms use word boundaries so ``quantum`` does not match
    ``QuantumNous``. CJK has no whitespace boundary; a literal occurrence is the
    most this layer can honestly claim.
    """
    if not title or not term:
        return False
    if term.isascii():
        return re.search(r"(?<![0-9A-Za-z])" + re.escape(term) + r"(?![0-9A-Za-z])",
                         title, re.I) is not None
    return term in title

# Added-at is deliberately literal: a tempId_/syncId_ date segment is a
# generation clue, a dateAdded epoch is the bookmark's own add time, and an
# edge id ends with the millisecond it was created. Nothing here guesses a
# missing time, and each source keeps its own precision and confidence.
ID_DATE = re.compile(r"^(?:temp|sync)Id_(\d{8})_")
EPOCH_MS = (10 ** 12, 10 ** 13)  # 2001-09-09 .. 2286-11-20
ADDED_AT_SOURCES = {"dateAdded": ("millisecond", "high"), "edge_epoch": ("millisecond", "medium"),
                    "id_date_segment": ("day", "low")}


def _added_at_from_id(item_id):
    """The YYYYMMDD segment of a tempId_/syncId_ id as an ISO instant, or None."""
    match = ID_DATE.match(item_id if isinstance(item_id, str) else "")
    if match is None:
        return None
    try:
        moment = datetime.strptime(match.group(1), "%Y%m%d")
    except ValueError:
        return None
    return moment.replace(tzinfo=timezone.utc).isoformat()


def _added_at_from_epoch(value):
    """An epoch-millisecond number as an ISO instant, or None when implausible.

    The range check is what keeps a stray counter, such as the middle number of
    an edge id, from being read as a date.
    """
    if type(value) is not int or not EPOCH_MS[0] <= value < EPOCH_MS[1]:
        return None
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def _added_at_from_edge_id(edge_id):
    """The trailing millisecond of an ``edge - 9 -1782572278545`` id, or None."""
    tail = (edge_id if isinstance(edge_id, str) else "").rsplit("-", 1)[-1]
    return _added_at_from_epoch(int(tail)) if tail.strip().isdigit() else None


def _added_at_fields(item_id, raw):
    """(added_at, source, confidence) for one item; dateAdded wins over an id segment.

    dateAdded is when the bookmark was added; an id date segment is only a
    generation or import clue, so it is reported with low confidence and never
    overrides a real add time.
    """
    if isinstance(raw, dict):
        epoch = _added_at_from_epoch(raw.get("dateAdded"))
        if epoch is not None:
            return epoch, "dateAdded", ADDED_AT_SOURCES["dateAdded"][1]
    segment = _added_at_from_id(item_id)
    if segment is not None:
        return segment, "id_date_segment", ADDED_AT_SOURCES["id_date_segment"][1]
    return None, None, None


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _inside(path, directory):
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON value: " + value)


def _string(value, label, required=False):
    if not isinstance(value, str) or "\x00" in value or (required and not value):
        raise ValueError("Expected %s string" % label)
    return value


def _reference(reference, package_files=None):
    """Resolve the protocol directory suffix, not the referring file's parent.

    The vault root is external to an exported/moved package. Retaining the full
    protocol suffix accommodates its vault prefix without reading outside it.
    """
    return resolve_protocol_reference(reference, package_files=package_files)


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 source_id TEXT PRIMARY KEY, package_path TEXT NOT NULL,
 created_at TEXT NOT NULL, last_sync TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_redirects (
 old_source_id TEXT PRIMARY KEY, new_source_id TEXT NOT NULL,
 created_at TEXT NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
 source_id TEXT NOT NULL, file_path TEXT NOT NULL, kind TEXT NOT NULL,
 sha256 TEXT NOT NULL, raw_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(source_id,file_path),
 FOREIGN KEY(source_id) REFERENCES sources(source_id)
);
CREATE TABLE IF NOT EXISTS sections (
 source_id TEXT NOT NULL, section_id TEXT NOT NULL, file_path TEXT NOT NULL,
 section_type TEXT NOT NULL, label TEXT NOT NULL, slot TEXT NOT NULL,
 title TEXT NOT NULL, description_md TEXT NOT NULL, is_anchor INTEGER NOT NULL,
 inherit_path TEXT, canonical_id TEXT, raw_json TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(source_id,section_id),
 FOREIGN KEY(source_id) REFERENCES sources(source_id)
);
CREATE INDEX IF NOT EXISTS sections_file ON sections(source_id,file_path);
CREATE TABLE IF NOT EXISTS items (
 pk INTEGER PRIMARY KEY, source_id TEXT NOT NULL, section_id TEXT NOT NULL,
 item_id TEXT NOT NULL, parent_id TEXT, item_type TEXT NOT NULL,
 position INTEGER NOT NULL, preorder INTEGER NOT NULL, title TEXT NOT NULL,
 url TEXT NOT NULL, note TEXT NOT NULL, note_color TEXT,
 tags_json TEXT NOT NULL, tag_text TEXT NOT NULL, path_json TEXT NOT NULL,
 folder_path TEXT NOT NULL, ancestor_ids_json TEXT NOT NULL,
 raw_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
 added_at TEXT, added_at_source TEXT, added_at_confidence TEXT,
 revision INTEGER NOT NULL DEFAULT 1,
 UNIQUE(source_id,section_id,item_id),
 FOREIGN KEY(source_id,section_id) REFERENCES sections(source_id,section_id)
);
CREATE INDEX IF NOT EXISTS items_parent ON items(source_id,section_id,parent_id);
CREATE INDEX IF NOT EXISTS items_url ON items(source_id,url);
CREATE INDEX IF NOT EXISTS items_url_lookup ON items(url);
CREATE TABLE IF NOT EXISTS item_tags (
 item_pk INTEGER NOT NULL REFERENCES items(pk) ON DELETE CASCADE,
 position INTEGER NOT NULL, color TEXT NOT NULL, text TEXT NOT NULL,
 raw_json TEXT NOT NULL, PRIMARY KEY(item_pk,color,text)
);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
 title,url,note,tag_text,folder_path,content='items',content_rowid='pk'
);
CREATE TRIGGER IF NOT EXISTS items_fts_ai AFTER INSERT ON items BEGIN
 INSERT INTO items_fts(rowid,title,url,note,tag_text,folder_path)
 VALUES(new.pk,new.title,new.url,new.note,new.tag_text,new.folder_path);
END;
CREATE TRIGGER IF NOT EXISTS items_fts_ad AFTER DELETE ON items BEGIN
 INSERT INTO items_fts(items_fts,rowid,title,url,note,tag_text,folder_path)
 VALUES('delete',old.pk,old.title,old.url,old.note,old.tag_text,old.folder_path);
END;
CREATE TRIGGER IF NOT EXISTS items_fts_au AFTER UPDATE ON items BEGIN
 INSERT INTO items_fts(items_fts,rowid,title,url,note,tag_text,folder_path)
 VALUES('delete',old.pk,old.title,old.url,old.note,old.tag_text,old.folder_path);
 INSERT INTO items_fts(rowid,title,url,note,tag_text,folder_path)
 VALUES(new.pk,new.title,new.url,new.note,new.tag_text,new.folder_path);
END;
CREATE TABLE IF NOT EXISTS nodes (
 source_id TEXT NOT NULL, canvas_path TEXT NOT NULL, node_id TEXT NOT NULL,
 node_type TEXT NOT NULL, section_id TEXT, file_path TEXT, label TEXT NOT NULL,
 text TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, width REAL NOT NULL,
 height REAL NOT NULL, position INTEGER NOT NULL, raw_json TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(source_id,canvas_path,node_id)
);
CREATE TABLE IF NOT EXISTS edges (
 source_id TEXT NOT NULL, canvas_path TEXT NOT NULL, edge_id TEXT NOT NULL,
 from_node TEXT NOT NULL, to_node TEXT NOT NULL,
 from_end TEXT NOT NULL, to_end TEXT NOT NULL, label TEXT NOT NULL,
 raw_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(source_id,canvas_path,edge_id)
);
CREATE TABLE IF NOT EXISTS memberships (
 source_id TEXT NOT NULL, canvas_path TEXT NOT NULL,
 group_id TEXT NOT NULL, node_id TEXT NOT NULL,
 PRIMARY KEY(source_id,canvas_path,group_id,node_id)
);
PRAGMA user_version=2;
"""


class BookmarkIndex:
    def __init__(self, db_path, readonly=False):
        self.db_path = None if str(db_path) == ":memory:" else Path(db_path).expanduser().resolve()
        self.connection = None
        self.readonly = False
        if self.db_path is not None:
            # Refuse before connecting, so even an accidentally chosen package
            # path does not acquire an empty database, journal or WAL file.
            for parent in self.db_path.parents:
                if is_package_dir(parent):
                    raise ValueError("Database must be outside imported package directories")
        modes = [bool(readonly), not bool(readonly)] if self.db_path is not None else [False]
        first_error = None
        for mode in modes:
            try:
                self._initialize(mode)
                break
            except (OSError, sqlite3.DatabaseError) as error:
                self.close()
                if first_error is None:
                    first_error = error
                if not mode and not self._read_only_open_failure(error):
                    raise
            except Exception:
                self.close()
                raise
        else:
            raise first_error

    @staticmethod
    def _read_only_open_failure(error):
        return storage.is_readonly_failure(error)

    def _initialize(self, readonly):
        if self.db_path is None:
            connection = sqlite3.connect(":memory:")
        elif readonly:
            connection = storage.connect(self.db_path, readonly=True)
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.db_path))
        self.connection = connection
        self.readonly = readonly
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            raise ValueError("Unsupported bookmark index schema version: %s" % version)
        if readonly:
            if version != 2:
                raise sqlite3.OperationalError("Read-only bookmark index requires schema version 2")
            row = self.connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='items_fts'").fetchone()
            self._fts_mode = "trigram" if row is not None and "trigram" in (row["sql"] or "") else "plain"
        else:
            if version == 1:
                # Add the added-at columns and fill them from stored raw_json before
                # the schema script runs: CREATE TABLE IF NOT EXISTS cannot add a
                # column, and the script would advance the version past this repair.
                self._upgrade_items_added_at()
            self.connection.executescript(SCHEMA)
            self._fts_mode = self._prepare_search_index()
        self._window_functions = self._supports_window_functions()

    def _upgrade_items_added_at(self):
        """v1 → v2: derive added-at for existing rows without touching the package.

        The index is derived data, but its package may be gone or unreadable, so
        the backfill reads the stored raw_json and item_id rather than re-importing.
        """
        with self.transaction():
            for column in ("added_at", "added_at_source", "added_at_confidence"):
                self.connection.execute("ALTER TABLE items ADD COLUMN %s TEXT" % column)
            for row in self.connection.execute("SELECT pk,item_id,raw_json FROM items").fetchall():
                try:
                    raw = json.loads(row["raw_json"])
                except ValueError:
                    raw = {}
                added_at, source, confidence = _added_at_fields(row["item_id"], raw)
                self.connection.execute(
                    "UPDATE items SET added_at=?,added_at_source=?,added_at_confidence=? WHERE pk=?",
                    (added_at, source, confidence, row["pk"]))
            self.connection.execute("PRAGMA user_version=2")

    def _supports_window_functions(self):
        """SQLite 3.25+ can return the pre-LIMIT count alongside the page."""
        try:
            self.connection.execute("SELECT row_number() OVER () FROM (SELECT 1)").fetchone()
        except sqlite3.DatabaseError:
            return False
        return True

    def _prepare_search_index(self):
        """Keep items_fts able to answer literal substring searches.

        The default FTS5 tokenizer treats a whole run of CJK characters as one
        token, so ``MATCH '推理'`` cannot find ``推理加速``. The trigram tokenizer
        does substring matching, which is the same contract as the LIKE fallback
        used for short terms; when it is unavailable the index stays usable and
        every term falls back to LIKE.
        """
        row = self.connection.execute("SELECT sql FROM sqlite_master WHERE name='items_fts'").fetchone()
        existing = (row["sql"] or "") if row is not None else ""
        if row is not None and "trigram" in existing:
            return "trigram"
        if row is not None and not self._trigram_available():
            return "plain"
        with self.transaction():
            self.connection.execute("DROP TABLE IF EXISTS items_fts")
            self.connection.execute("CREATE VIRTUAL TABLE items_fts USING fts5("
                                    "title,url,note,tag_text,folder_path,content='items',content_rowid='pk',"
                                    "tokenize='trigram')")
            self.connection.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
        return "trigram"

    def _trigram_available(self):
        try:
            self.connection.execute("CREATE VIRTUAL TABLE temp.__trigram_probe USING fts5(body, tokenize='trigram')")
        except sqlite3.DatabaseError:
            return False
        finally:
            try:
                self.connection.execute("DROP TABLE IF EXISTS temp.__trigram_probe")
            except sqlite3.DatabaseError:
                pass
        return True

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def resolve_source_id(self, source_id):
        """Resolve retired source IDs to their surviving merge target."""
        current, seen = source_id, set()
        while current not in seen:
            seen.add(current)
            row = self.connection.execute(
                "SELECT new_source_id FROM source_redirects WHERE old_source_id=?", (current,)).fetchone()
            if row is None:
                return current
            current = row[0]
        raise ValueError("Source redirect cycle: " + str(source_id))

    def _source(self, source_id):
        resolved = self.resolve_source_id(source_id)
        row = self.connection.execute("SELECT * FROM sources WHERE source_id=?", (resolved,)).fetchone()
        if row is None:
            raise ValueError("Unknown source_id: " + str(source_id))
        return dict(row)

    def _input_path(self, source_id, fallback):
        """Use the live input for live sources and the managed copy for snapshots."""
        try:
            row = self.connection.execute(
                "SELECT record_json FROM source_records WHERE source_id=?", (source_id,)).fetchone()
        except sqlite3.OperationalError:
            # Direct BookmarkIndex.sync() callers do not have the optional
            # source_records table; the package path fallback is exact for them.
            row = None
        if row is not None:
            try:
                record = json.loads(row[0])
                if record.get("mode") == "snapshot":
                    return Path(fallback)
                value = record.get("input_path")
                if isinstance(value, str) and value:
                    path = Path(value).expanduser()
                    if path.is_dir():
                        return path
            except (TypeError, ValueError, KeyError):
                pass
        return Path(fallback)

    def _upsert(self, table, keys, values):
        """Internal table/column names only; user values are always parameters."""
        where = " AND ".join(key + "=?" for key in keys)
        row = self.connection.execute("SELECT * FROM %s WHERE %s" % (table, where), tuple(keys.values())).fetchone()
        if row is not None and all(row[key] == value for key, value in values.items()):
            return "unchanged"
        if row is None:
            fields = dict(keys, **values)
            self.connection.execute("INSERT INTO %s (%s) VALUES (%s)" % (
                table, ",".join(fields), ",".join("?" for _ in fields)), tuple(fields.values()))
            return "inserted"
        self.connection.execute("UPDATE %s SET %s,revision=revision+1 WHERE %s" % (
            table, ",".join(key + "=?" for key in values), where), tuple(values.values()) + tuple(keys.values()))
        return "updated"

    @staticmethod
    def _section(file_path, obj, package_files=None):
        if obj.get("format") != "bookmark-canvas-section":
            raise ValueError("Not a Bookmark Canvas section: " + file_path)
        section_type = obj.get("sectionType")
        if section_type not in ("permanent", "temporary"):
            raise ValueError("Unknown sectionType in " + file_path)
        if not dir_matches_section_type(file_path, section_type):
            raise ValueError("sectionType does not match protocol directory: " + file_path)
        anchor = obj.get("fileRole") == "copy-anchor" or obj.get("anchorOnly") is True
        slot = _string(obj.get("slot", ""), "slot")
        if section_type == "permanent":
            if not slot:
                raise ValueError("Permanent section needs slot: " + file_path)
            if anchor:
                if "tree" in obj:
                    raise ValueError("Copy anchors must not duplicate a tree")
                copy_id = _string(obj.get("copyId"), "copyId", True)
                section_id = obj.get("id", "permanent-section-copy-" + copy_id)
            else:
                section_id = obj.get("id", "permanent-section" if slot == "A" else "permanent-section-" + slot)
            label = slot
        else:
            if anchor:
                raise ValueError("Only permanent sections can be copy anchors")
            label = obj.get("label", "unknown")
            section_id = obj.get("id")
            if not section_id:
                # The canvas right-click export omits ids; derive a stable one so
                # re-importing the same file keeps refs and duplicate groups.
                digest = hashlib.sha256(("temporary|" + str(label) + "|" + _string(obj.get("title", ""), "section title") + "|" + file_path).encode("utf-8")).hexdigest()[:12]
                section_id = "temp-section-export-" + digest
        _string(section_id, "section id", True)
        _string(label, "section label", True)
        return section_id, {
            "file_path": file_path, "section_type": section_type, "label": label,
            "slot": slot, "title": _string(obj.get("title", ""), "section title"),
            "description_md": _string(obj.get("descriptionMd", ""), "descriptionMd"),
            "is_anchor": int(anchor), "inherit_path": _reference(obj.get("inheritFrom"), package_files=package_files) if anchor else None,
            "raw_json": _dump(obj),
        }

    @staticmethod
    def _items(section_id, section, obj):
        if section["is_anchor"]:
            return []
        permanent = section["section_type"] == "permanent"
        roots = obj.get("tree") if permanent else obj.get("items")
        if permanent and isinstance(roots, dict):
            roots = [roots]
        if not isinstance(roots, list):
            raise ValueError("Section needs a complete tree/items value: " + section_id)
        metadata = obj.get("identityMap", []) if permanent else []
        if isinstance(metadata, dict):
            meta = {}
            for key, value in metadata.items():
                if not isinstance(value, dict):
                    raise ValueError("identityMap entries must be objects")
                if value.get("syncId", key) != key:
                    raise ValueError("identityMap key/syncId mismatch")
                meta[key] = value
        elif isinstance(metadata, list):
            meta = {}
            for value in metadata:
                if not isinstance(value, dict):
                    raise ValueError("identityMap entries must be objects")
                key = _string(value.get("syncId"), "identityMap syncId", True)
                if key in meta:
                    raise ValueError("Duplicate identityMap syncId: " + key)
                meta[key] = value
        else:
            raise ValueError("identityMap must be an array or keyed object")
        result, seen = [], set()

        def visit(nodes, parent_id=None, titles=(), ancestor_ids=()):
            for position, node in enumerate(nodes):
                if not isinstance(node, dict):
                    raise ValueError("Items must be JSON objects")
                if node.get("id") is None:
                    # Exported items carry no id; derive one from position and
                    # content so re-imports stay stable and duplicates still group.
                    seed = "|".join([section_id, parent_id or "", str(position),
                                     str(node.get("url") or ""), str(node.get("title") or "")])
                    item_id = ("tempId_" if not permanent else "persistId_") + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
                else:
                    item_id = _string(node.get("id"), "item id", True)
                if item_id in seen:
                    raise ValueError("Duplicate item id in section: " + item_id)
                seen.add(item_id)
                if permanent and "parentId" in node and node["parentId"] != parent_id:
                    raise ValueError("parentId disagrees with tree position: " + item_id)
                if not permanent and node.get("sectionId", section_id) != section_id:
                    raise ValueError("Temporary item sectionId mismatch: " + item_id)
                title = _string(node.get("title", ""), "item title")
                url = _string(node.get("url") or "", "item URL")
                item_type = (("bookmark" if url else "folder") if permanent
                             else (node.get("type") or ("bookmark" if url else "folder")))
                if item_type not in ("bookmark", "folder") or (item_type == "bookmark" and not url):
                    raise ValueError("Invalid bookmark/folder type: " + item_id)
                children = node.get("children", [])
                if not isinstance(children, list) or (children and item_type == "bookmark"):
                    raise ValueError("Invalid item children: " + item_id)
                item_meta = meta.get(item_id, {}) if permanent else node
                tags = item_meta.get("tags", [])
                if not isinstance(tags, list):
                    raise ValueError("tags must be an array")
                normalized, tag_keys = [], set()
                for tag in tags:
                    if not isinstance(tag, dict):
                        raise ValueError("tags must contain color/text objects")
                    key = (_string(tag.get("color"), "tag color", True), _string(tag.get("text", ""), "tag text"))
                    if key not in tag_keys:
                        normalized.append(tag)
                        tag_keys.add(key)
                note = _string(item_meta.get("note", ""), "note").strip()
                note_color = item_meta.get("noteColor", "orange") if note else None
                if note_color is not None:
                    _string(note_color, "noteColor")
                added = _added_at_fields(item_id, node)
                result.append((item_id, {
                    "parent_id": parent_id, "item_type": item_type, "position": position,
                    "preorder": len(result), "title": title, "url": url, "note": note,
                    "note_color": note_color, "tags_json": _dump(normalized),
                    "tag_text": "\n".join(tag["text"] for tag in normalized),
                    "path_json": _dump(list(titles)), "folder_path": " / ".join(titles),
                    "ancestor_ids_json": _dump(list(ancestor_ids)),
                    # Keep tree structure in parent_id/path/position and in the
                    # source-file snapshot; duplicating descendants here makes
                    # every ancestor appear changed when one child is edited.
                    "raw_json": _dump({key: value for key, value in node.items()
                                       if key != "children"
                                       and not (item_type == "folder" and key == "url" and value == "")}),
                    "metadata_json": _dump(item_meta if permanent else {key: node[key] for key in ("tags", "note", "noteColor") if key in node}),
                    "added_at": added[0], "added_at_source": added[1], "added_at_confidence": added[2],
                }))
                visit(children, item_id, titles + ((title,) if title else ()), ancestor_ids + (item_id,))

        visit(roots)
        return result

    @staticmethod
    def _canvas(obj, package_files=None):
        if not isinstance(obj.get("nodes"), list) or not isinstance(obj.get("edges"), list):
            raise ValueError("Canvas requires nodes[] and edges[]")
        nodes, edges, seen = [], [], set()
        for position, node in enumerate(obj["nodes"]):
            if not isinstance(node, dict):
                raise ValueError("Canvas nodes must be objects")
            node_id = _string(node.get("id"), "node id", True)
            if node_id in seen:
                raise ValueError("Duplicate canvas node: " + node_id)
            seen.add(node_id)
            node_type = node.get("type")
            if node_type not in ("file", "text", "group"):
                raise ValueError("Unsupported package canvas node type: " + str(node_type))
            geometry = {}
            for key in ("x", "y", "width", "height"):
                value = node.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("Invalid canvas geometry: " + key)
                if key in ("width", "height") and value <= 0:
                    raise ValueError("Canvas dimensions must be positive")
                geometry[key] = value
            nodes.append((node_id, dict(geometry, node_type=node_type,
                file_path=_reference(node.get("file"), package_files=package_files) if node_type == "file" else None,
                label=_string(node.get("label", ""), "node label"),
                text=_string(node.get("text", ""), "node text"), position=position, raw_json=_dump(node))))
        edge_ids = set()
        for edge in obj["edges"]:
            if not isinstance(edge, dict):
                raise ValueError("Edges must be objects")
            edge_id = _string(edge.get("id"), "edge id", True)
            if edge_id in edge_ids:
                raise ValueError("Duplicate edge id")
            edge_ids.add(edge_id)
            if edge.get("fromNode") not in seen or edge.get("toNode") not in seen:
                raise ValueError("Canvas edge endpoint does not exist: " + edge_id)
            from_end, to_end = edge.get("fromEnd", "none"), edge.get("toEnd", "arrow")
            if from_end not in ("none", "arrow") or to_end not in ("none", "arrow"):
                raise ValueError("Unknown canvas edge end")
            edges.append((edge_id, {"from_node": edge["fromNode"], "to_node": edge["toNode"],
                "from_end": from_end, "to_end": to_end, "label": _string(edge.get("label", ""), "edge label"),
                "raw_json": _dump(edge)}))
        return nodes, edges

    @contextmanager
    def read_snapshot(self):
        self.connection.execute("SAVEPOINT bookmark_read")
        try:
            yield
        finally:
            self.connection.execute("RELEASE SAVEPOINT bookmark_read")

    @contextmanager
    def transaction(self):
        """Serialize writers; allow an importer to publish metadata atomically."""
        if self.readonly:
            raise sqlite3.OperationalError("attempt to write a readonly bookmark index")
        nested = self.connection.in_transaction
        if nested:
            self.connection.execute("SAVEPOINT bookmark_sync")
        else:
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            if nested:
                self.connection.execute("RELEASE SAVEPOINT bookmark_sync")
            else:
                self.connection.commit()
        except BaseException:
            if nested:
                self.connection.execute("ROLLBACK TO SAVEPOINT bookmark_sync")
                self.connection.execute("RELEASE SAVEPOINT bookmark_sync")
            else:
                self.connection.rollback()
            raise

    def sync(self, package_path, source_id=None, completeness="partial"):
        with self.transaction():
            return self._sync(package_path, source_id, completeness)

    def _sync(self, package_path, source_id, completeness):
        if completeness not in ("partial", "complete"):
            raise ValueError("completeness must be partial or complete")
        package = Path(package_path).expanduser().resolve()
        if not package.is_dir():
            raise ValueError("Package directory does not exist: " + str(package))
        if self.db_path is not None and _inside(self.db_path, package):
            raise ValueError("Database must be outside the imported package")
        if source_id is None:
            existing = self.connection.execute("SELECT source_id FROM sources WHERE package_path=?", (str(package),)).fetchall()
            if len(existing) > 1:
                raise ValueError("Multiple sources use this path; provide source_id")
            source_id = existing[0][0] if existing else "source-" + hashlib.sha256(str(package).encode()).hexdigest()[:12]
        _string(source_id, "source_id", True)
        paths = list(package.glob("*.canvas"))
        if len(paths) > 1:
            raise ValueError("A package must have at most one .canvas entry; use separate sources for separate canvases")
        canvas_path = paths[0].relative_to(package).as_posix() if paths else None
        for directory in PROTOCOL_DIRS:
            paths.extend((package / directory).rglob("*.json"))
        paths = sorted(paths)
        if not paths:
            raise ValueError("No protocol JSON or .canvas files in package")
        old_files = {row["file_path"]: dict(row) for row in self.connection.execute(
            "SELECT * FROM files WHERE source_id=?", (source_id,))}
        indexed_section_files = {row[0] for row in self.connection.execute(
            "SELECT file_path FROM sections WHERE source_id=?", (source_id,))}
        package_section_files = {p.relative_to(package).as_posix() for p in paths if p.suffix == ".json"} | indexed_section_files
        changed, observed, section_ids = [], set(), set()
        # Parse and validate every changed file before starting the mutation.
        for path in paths:
            if not _inside(path.resolve(), package):
                raise ValueError("Package contains an external symlink: " + str(path))
            relative = path.relative_to(package).as_posix()
            observed.add(relative)
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if (relative in old_files and old_files[relative]["sha256"] == digest
                    and (path.suffix == ".canvas" or relative in indexed_section_files)):
                continue
            try:
                obj = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
                if not isinstance(obj, dict):
                    raise ValueError("File must contain one JSON object")
                if path.suffix == ".canvas":
                    parsed = self._canvas(obj, package_files=package_section_files)
                else:
                    section_id, section = self._section(relative, obj, package_files=package_section_files)
                    if section_id in section_ids:
                        raise ValueError("Duplicate section ID in package: " + section_id)
                    section_ids.add(section_id)
                    parsed = (section_id, section, self._items(section_id, section, obj))
            except (ValueError, TypeError, RecursionError) as exc:
                raise ValueError("Invalid package file %s: %s" % (relative, exc)) from exc
            changed.append((relative, digest, obj, parsed))
        summary = {"source_id": source_id, "package_path": str(package),
            "changed_files": len(changed), "skipped_files": len(observed) - len(changed),
            "items_inserted": 0, "items_updated": 0, "items_deleted": 0,
            "retained_missing_files": sorted(set(old_files) - observed), "warnings": []}
        summary["replaced_canvas_files"] = [relative for relative, record in old_files.items()
            if canvas_path is not None and record["kind"] == "canvas" and relative != canvas_path]
        timestamp = _now()
        with self.transaction():
            self.connection.execute("""INSERT INTO sources VALUES(?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET package_path=excluded.package_path,last_sync=excluded.last_sync""",
                (source_id, str(package), timestamp, timestamp))
            # One logical source has one canvas entry. A supplied entry replaces
            # its prior path, while a partial export without one retains the layout.
            for previous in summary["replaced_canvas_files"]:
                for table in ("memberships", "edges", "nodes"):
                    self.connection.execute("DELETE FROM %s WHERE source_id=? AND canvas_path=?" % table,
                                            (source_id, previous))
                self.connection.execute("DELETE FROM files WHERE source_id=? AND file_path=?", (source_id, previous))
            for relative, digest, obj, parsed in changed:
                if relative.endswith(".canvas"):
                    continue
                section_id, values, items = parsed
                # A renamed file may retain its stable section ID. A second
                # currently observed file with that ID is ambiguous, however.
                prior = self.connection.execute("SELECT file_path FROM sections WHERE source_id=? AND section_id=?", (source_id, section_id)).fetchone()
                if prior and prior[0] != relative and prior[0] in observed:
                    raise ValueError("Two present files share section ID: " + section_id)
                self._upsert("sections", {"source_id": source_id, "section_id": section_id}, values)
                present_items = set()
                for item_id, item in items:
                    present_items.add(item_id)
                    action = self._upsert("items", {"source_id": source_id, "section_id": section_id, "item_id": item_id}, item)
                    if action != "unchanged":
                        summary["items_" + action] += 1
                        pk = self.connection.execute("SELECT pk FROM items WHERE source_id=? AND section_id=? AND item_id=?", (source_id, section_id, item_id)).fetchone()[0]
                        self.connection.execute("DELETE FROM item_tags WHERE item_pk=?", (pk,))
                        for position, tag in enumerate(json.loads(item["tags_json"])):
                            self.connection.execute("INSERT INTO item_tags VALUES(?,?,?,?,?)", (pk, position, tag["color"], tag["text"], _dump(tag)))
                for row in self.connection.execute("SELECT pk,item_id FROM items WHERE source_id=? AND section_id=?", (source_id, section_id)).fetchall():
                    if row["item_id"] not in present_items:
                        self.connection.execute("DELETE FROM items WHERE pk=?", (row["pk"],))
                        summary["items_deleted"] += 1
            # A complete directory is a mirror. Resolve renames by section ID
            # first so moving a file preserves item row IDs and revisions.
            summary["removed_files"] = []
            if completeness == "complete":
                for row in self.connection.execute("SELECT section_id,file_path FROM sections WHERE source_id=?", (source_id,)).fetchall():
                    if row["file_path"] not in observed:
                        summary["items_deleted"] += self.connection.execute(
                            "DELETE FROM items WHERE source_id=? AND section_id=?", (source_id, row["section_id"])).rowcount
                        self.connection.execute("DELETE FROM sections WHERE source_id=? AND section_id=?", (source_id, row["section_id"]))
                for previous in set(old_files) - observed:
                    for table in ("memberships", "edges", "nodes"):
                        self.connection.execute("DELETE FROM %s WHERE source_id=? AND canvas_path=?" % table, (source_id, previous))
                    self.connection.execute("DELETE FROM files WHERE source_id=? AND file_path=?", (source_id, previous))
                    summary["removed_files"].append(previous)
                summary["removed_files"].sort()
            sections = {row["section_id"]: dict(row) for row in self.connection.execute("SELECT * FROM sections WHERE source_id=?", (source_id,))}
            by_file = {}
            for sid, section in sections.items():
                if section["file_path"] in by_file:
                    raise ValueError("A section file changed identity; use a new source or preserve its ID")
                by_file[section["file_path"]] = sid

            def canonical(sid, visiting=()):
                if sid in visiting:
                    raise ValueError("Copy-anchor inheritance cycle")
                section = sections[sid]
                if not section["is_anchor"]:
                    return sid
                target = by_file.get(section["inherit_path"])
                if target is None:
                    # A retained anchor still identifies its previously resolved
                    # tree when a partial export renames that stable section ID.
                    prior = section["canonical_id"]
                    if section["file_path"] not in observed and prior in sections:
                        summary["warnings"].append("Retained copy-anchor uses prior file reference: " + sid)
                        target = prior
                    else:
                        return None
                if sections[target]["section_type"] != "permanent":
                    raise ValueError("Copy anchor must inherit a permanent section")
                return canonical(target, visiting + (sid,))

            for sid, section in sections.items():
                resolved = canonical(sid)
                if resolved != section["canonical_id"]:
                    self.connection.execute("UPDATE sections SET canonical_id=? WHERE source_id=? AND section_id=?", (resolved, source_id, sid))
                if resolved is None:
                    summary["warnings"].append("Unresolved copy-anchor target: " + sid)
            for relative, digest, obj, parsed in changed:
                if relative.endswith(".canvas"):
                    nodes, edges = parsed
                    for table, id_column, rows in (("nodes", "node_id", nodes), ("edges", "edge_id", edges)):
                        retained = set()
                        for identifier, values in rows:
                            retained.add(identifier)
                            if table == "nodes":
                                values = dict(values, section_id=by_file.get(values["file_path"]))
                            self._upsert(table, {"source_id": source_id, "canvas_path": relative, id_column: identifier}, values)
                        old = self.connection.execute("SELECT %s FROM %s WHERE source_id=? AND canvas_path=?" % (id_column, table), (source_id, relative)).fetchall()
                        for row in old:
                            if row[0] not in retained:
                                self.connection.execute("DELETE FROM %s WHERE source_id=? AND canvas_path=? AND %s=?" % (table, id_column), (source_id, relative, row[0]))
                    self._memberships(source_id, relative)
                self._upsert("files", {"source_id": source_id, "file_path": relative}, {
                    "kind": "canvas" if relative.endswith(".canvas") else "section", "sha256": digest, "raw_json": _dump(obj)})
            # A stable section ID moving to a new path supersedes its old file
            # hash. Keeping that hash would skip parsing if it later moved back.
            # Missing sections themselves remain retained for partial exports.
            self.connection.execute("""DELETE FROM files WHERE source_id=? AND kind='section'
                AND NOT EXISTS (SELECT 1 FROM sections s
                    WHERE s.source_id=files.source_id AND s.file_path=files.file_path)""", (source_id,))
            # A partial package can supply a previously unresolved referenced
            # section without changing any canvas bytes.
            for node in self.connection.execute("SELECT * FROM nodes WHERE source_id=? AND node_type='file'", (source_id,)).fetchall():
                resolved = by_file.get(node["file_path"])
                if resolved is None and node["canvas_path"] not in observed and node["section_id"] in sections:
                    # Keep known card identity for an omitted (older) layout; a
                    # currently supplied canvas always resolves its actual paths.
                    resolved = node["section_id"]
                    summary["warnings"].append("Retained canvas uses prior file reference: " + node["file_path"])
                if resolved != node["section_id"]:
                    self.connection.execute("UPDATE nodes SET section_id=? WHERE source_id=? AND canvas_path=? AND node_id=?", (resolved, source_id, node["canvas_path"], node["node_id"]))
                if resolved is None:
                    summary["warnings"].append("Unresolved canvas file: " + node["file_path"])
            if self.connection.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Derived database failed relationship validation")
        summary["counts"] = self.status(source_id)["counts"]
        summary["retained_missing_files"] = sorted(row[0] for row in self.connection.execute(
            "SELECT file_path FROM files WHERE source_id=?", (source_id,)) if row[0] not in observed)
        return summary

    def _memberships(self, source_id, canvas_path):
        nodes = self.connection.execute("SELECT * FROM nodes WHERE source_id=? AND canvas_path=?", (source_id, canvas_path)).fetchall()
        expected = set()
        for group in nodes:
            if group["node_type"] != "group":
                continue
            for node in nodes:
                if group["node_id"] == node["node_id"]:
                    continue
                if (group["x"] <= node["x"] and group["y"] <= node["y"]
                        and node["x"] + node["width"] <= group["x"] + group["width"]
                        and node["y"] + node["height"] <= group["y"] + group["height"]):
                    # Equal rectangles do not define reciprocal group nesting.
                    if node["node_type"] == "group" and all(node[k] == group[k] for k in ("x", "y", "width", "height")):
                        continue
                    expected.add((group["node_id"], node["node_id"]))
        old = {(r[0], r[1]) for r in self.connection.execute("SELECT group_id,node_id FROM memberships WHERE source_id=? AND canvas_path=?", (source_id, canvas_path))}
        for pair in old - expected:
            self.connection.execute("DELETE FROM memberships WHERE source_id=? AND canvas_path=? AND group_id=? AND node_id=?", (source_id, canvas_path) + pair)
        for pair in expected - old:
            self.connection.execute("INSERT INTO memberships VALUES(?,?,?,?)", (source_id, canvas_path) + pair)

    def refresh(self, source_id):
        return self.sync(self._source(source_id)["package_path"], source_id=source_id)

    def _sections(self, source_id, selector=None):
        rows = self.connection.execute("SELECT * FROM sections WHERE source_id=? ORDER BY file_path,section_id", (source_id,)).fetchall()
        if selector is not None:
            rows = [row for row in rows if selector in (row["section_id"], row["label"], row["slot"], row["file_path"])]
            if not rows:
                raise ValueError("Unknown section: " + str(selector))
        return rows

    def _group(self, source_id, group_id):
        rows = self.connection.execute("SELECT * FROM nodes WHERE source_id=? AND node_type='group' AND node_id=?", (source_id, group_id)).fetchall()
        if not rows:
            rows = self.connection.execute("SELECT * FROM nodes WHERE source_id=? AND node_type='group' AND label=?", (source_id, group_id)).fetchall()
        if len(rows) != 1:
            raise ValueError("Unknown or ambiguous group; use a unique group ID: " + str(group_id))
        return rows[0]

    def _scope(self, source_id, section=None, group_id=None, folder_id=None, tags=None, tag_colors=None,
               item_types=None, has_note=None, has_tags=None, metadata_match="all"):
        source_id = self.resolve_source_id(source_id)
        self._source(source_id)
        selected_types = list(item_types) if item_types else ["bookmark"]
        clauses = ["i.source_id=?", "i.item_type IN (%s)" % ",".join("?" for _ in selected_types)]
        args = [source_id, *selected_types]
        sections = self._sections(source_id, section) if section is not None or group_id is not None else None
        if group_id is not None:
            group = self._group(source_id, group_id)
            members = {row[0] for row in self.connection.execute("""SELECT n.section_id FROM memberships m
              JOIN nodes n ON n.source_id=m.source_id AND n.canvas_path=m.canvas_path AND n.node_id=m.node_id
              WHERE m.source_id=? AND m.canvas_path=? AND m.group_id=?""",
                (source_id, group["canvas_path"], group["node_id"]))}
            # Intersect the requested cards before following copy anchors to
            # the shared tree: a copy's group does not contain its primary card.
            sections = [row for row in sections if row["section_id"] in members]
        if sections is not None:
            ids = {row["canonical_id"] for row in sections if row["canonical_id"]}
            clauses.append("i.section_id IN (%s)" % (",".join("?" for _ in ids) or "NULL"))
            args.extend(sorted(ids))
        if folder_id is not None:
            folders = self.connection.execute("SELECT section_id FROM items WHERE source_id=? AND item_id=? AND item_type='folder'", (source_id, folder_id)).fetchall()
            if not folders:
                raise ValueError("Unknown folder ID: " + str(folder_id))
            # Use relational ancestry rather than requiring SQLite's optional
            # JSON1 extension or inferring ancestry from folder-name strings.
            clauses.append("""EXISTS (WITH RECURSIVE subtree(section_id,item_id) AS (
                SELECT section_id,item_id FROM items
                WHERE source_id=? AND item_id=? AND item_type='folder'
                UNION ALL
                SELECT child.section_id,child.item_id FROM items child JOIN subtree p
                ON child.section_id=p.section_id AND child.parent_id=p.item_id
                WHERE child.source_id=?
            ) SELECT 1 FROM subtree d WHERE d.section_id=i.section_id AND d.item_id=i.item_id)""")
            args.extend((source_id, folder_id, source_id))
        for tag in tags or []:
            _string(tag, "tag", True)
            clauses.append("EXISTS (SELECT 1 FROM item_tags t WHERE t.item_pk=i.pk AND t.text=?)")
            args.append(tag)
        for color in tag_colors or []:
            _string(color, "tag color", True)
            clauses.append("EXISTS (SELECT 1 FROM item_tags t WHERE t.item_pk=i.pk AND t.color=?)")
            args.append(color)
        metadata_clauses = []
        if has_note is not None:
            metadata_clauses.append("trim(i.note)<>''" if has_note else "trim(i.note)=''")
        if has_tags is not None:
            metadata_clauses.append("EXISTS (SELECT 1 FROM item_tags t WHERE t.item_pk=i.pk)"
                                    if has_tags else
                                    "NOT EXISTS (SELECT 1 FROM item_tags t WHERE t.item_pk=i.pk)")
        if metadata_clauses:
            clauses.append("(" + (" OR " if metadata_match == "any" else " AND ").join(metadata_clauses) + ")")
        return clauses, args

    def bookmark_rows(self, source_id, section=None, folder_id=None, tags=None, limit=2000, offset=0):
        """Return lightweight bookmark rows for planning; raw JSON stays out.

        This is the paging surface for derived work that needs every bookmark's
        title, URL, note, folder path and tags, but not the full item payload.
        """
        source_id = self.resolve_source_id(source_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
            raise ValueError("limit must be an integer from 1 to 5000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        self._source(source_id)
        clauses, args = self._scope(source_id, section, None, folder_id, tags, None,
                                    ["bookmark"], None, None, "all")
        rows = self.connection.execute(
            "SELECT i.section_id, i.item_id, i.title, i.url, i.note, i.folder_path, i.tags_json, i.added_at"
            " FROM items i WHERE " + " AND ".join(clauses) +
            " ORDER BY i.section_id, i.preorder, i.item_id LIMIT ? OFFSET ?",
            args + [limit, offset]).fetchall()
        return [{"section_id": row["section_id"], "item_id": row["item_id"],
                 "title": row["title"] or "", "url": row["url"] or "",
                 "note": row["note"] or "", "folder_path": row["folder_path"] or "",
                 "tags": json.loads(row["tags_json"] or "[]"), "added_at": row["added_at"]}
                for row in rows]

    def source_summary(self, source_id):
        """Recognise a freshly imported package: counts, sections, noise, duplicates."""
        source_id = self.resolve_source_id(source_id)
        from url_classify import is_search_result_url
        counts = {}
        for row in self.connection.execute(
                "SELECT item_type, COUNT(*) AS c FROM items WHERE source_id=? GROUP BY item_type",
                (source_id,)):
            counts[row["item_type"]] = row["c"]
        notes = self.connection.execute(
            "SELECT COUNT(*) FROM items WHERE source_id=? AND note!=''", (source_id,)).fetchone()[0]
        notes_bookmarks = self.connection.execute(
            "SELECT COUNT(*) FROM items WHERE source_id=? AND note!='' AND item_type='bookmark'",
            (source_id,)).fetchone()[0]
        tagged = self.connection.execute(
            "SELECT COUNT(*) FROM items WHERE source_id=? AND tag_text!=''", (source_id,)).fetchone()[0]
        section_counts = {row["section_id"]: row["c"] for row in self.connection.execute(
            "SELECT section_id, COUNT(*) AS c FROM items WHERE source_id=? GROUP BY section_id",
            (source_id,))}
        sections = []
        for row in self.connection.execute(
                "SELECT section_id, label, title, section_type, file_path, raw_json FROM sections"
                " WHERE source_id=? ORDER BY section_id", (source_id,)):
            try:
                raw = json.loads(row["raw_json"]) if row["raw_json"] else {}
            except ValueError:
                raw = {}
            sections.append({**dict(row), "items": section_counts.get(row["section_id"], 0),
                             "source": raw.get("source") or "",
                             "temp_kind": raw.get("tempKind") or ""})
            sections[-1].pop("raw_json", None)
        urls = [row["url"] for row in self.connection.execute(
            "SELECT DISTINCT url FROM items WHERE source_id=? AND url!=''", (source_id,))]
        search_pages = sum(1 for url in urls if is_search_result_url(url))
        from junk import is_junk
        junk_items = 0
        for row in self.connection.execute(
                "SELECT title, url FROM items WHERE source_id=? AND item_type='bookmark'",
                (source_id,)):
            if is_junk(row["title"], row["url"]):
                junk_items += 1
        duplicates = self.duplicate_urls(source_id, include_search=False, limit=1)
        return {"source_id": source_id,
                "counts": {"items": sum(counts.values()), "bookmarks": counts.get("bookmark", 0),
                           "folders": counts.get("folder", 0)},
                "notes": notes, "notes_bookmarks": notes_bookmarks,
                "notes_folders": notes - notes_bookmarks, "tagged": tagged, "unique_urls": len(urls),
                "search_pages": search_pages, "junk_items": junk_items,
                "duplicate_url_groups": duplicates["total_groups"],
                "sections": sections}

    def duplicate_urls(self, source_id, min_count=2, limit=50, offset=0, include_search=False):
        """Group bookmarks that point at the same URL and suggest which copy to keep.

        The suggestion prefers an instance with a note, then the earliest added
        copy, then the shallowest folder path.  It is a proposal, never an edit.
        """
        source_id = self.resolve_source_id(source_id)
        if isinstance(min_count, bool) or not isinstance(min_count, int) or min_count < 2:
            raise ValueError("min_count must be an integer of at least 2")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 to 500")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if type(include_search) is not bool:
            raise ValueError("include_search must be a boolean")
        from junk import is_junk
        from url_classify import is_search_result_url
        base = ("FROM items WHERE source_id=? AND item_type='bookmark'"
                " AND url IS NOT NULL AND url!=''")
        rows = self.connection.execute(
            "SELECT url, COUNT(*) AS copies, MIN(added_at) AS first_added " + base +
            " GROUP BY url HAVING copies>=? ORDER BY copies DESC, first_added, url",
            (source_id, min_count)).fetchall()
        groups = [dict(row) for row in rows]
        # Placeholder rows (divider searches) are not real duplicates; drop them
        # before counting groups so the report stays honest.
        junk_seen = 0
        kept_groups = []
        for group in groups:
            if is_junk("", group["url"]):
                junk_seen += group["copies"]
                continue
            kept_groups.append(group)
        groups = kept_groups
        if not include_search:
            groups = [group for group in groups if not is_search_result_url(group["url"])]
        urls = [group["url"] for group in groups]
        by_url = {}
        if urls:
            placeholders = ",".join("?" for _ in urls)
            instance_rows = self.connection.execute(
                "SELECT section_id, item_id, url, title, note, note_color, folder_path, added_at, position "
                + base + " AND url IN (" + placeholders + ") ORDER BY url, added_at, folder_path, item_id",
                [source_id, *urls]).fetchall()
            for row in instance_rows:
                by_url.setdefault(row["url"], []).append(dict(row))
        kept = []
        for group in groups:
            copies = []
            for instance in by_url.get(group["url"], []):
                if is_junk(instance.get("title"), instance.get("url")):
                    junk_seen += 1
                    continue
                instance["depth"] = (instance.get("folder_path") or "").count("/") + 1
                copies.append(instance)
            if len(copies) < min_count:
                continue
            keep = sorted(copies, key=lambda item: (
                0 if item.get("note") else 1, item.get("added_at") or "9999",
                item["depth"], item["section_id"], item["item_id"]))[0]
            group["copies"] = len(copies)
            group["keep"] = {key: keep[key] for key in ("section_id", "item_id", "title",
                                                        "folder_path", "note", "added_at")}
            group["instances"] = copies
            kept.append(group)
        total_groups = len(kept)
        page = kept[offset:offset + limit]
        shown = offset + len(page)
        return {"source_id": source_id, "total_groups": total_groups, "groups": page,
                "limit": limit, "offset": offset,
                "next_offset": shown if shown < total_groups else None,
                "include_search": include_search, "junk_instances_excluded": junk_seen}

    def folder_children(self, source_id, folder_id, section=None, tags=None, tag_colors=None,
                        has_note=None, has_tags=None, metadata_match="all", limit=8, offset=0):
        """List one folder's direct bookmark/folder children with stable pagination."""
        source_id = self.resolve_source_id(source_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        self._source(source_id)
        rows = self.connection.execute(
            "SELECT * FROM items WHERE source_id=? AND item_type='folder' AND item_id=?",
            (source_id, folder_id)).fetchall()
        if section is not None:
            selected_sections = {row["canonical_id"] or row["section_id"]
                                 for row in self._sections(source_id, section)}
            rows = [row for row in rows if row["section_id"] in selected_sections]
        unique = {(row["section_id"], row["item_id"]): row for row in rows}
        if not unique:
            raise ValueError("Unknown folder ID: " + str(folder_id))
        if len(unique) > 1:
            raise ValueError("Ambiguous folder ID; pass section to select one: " + str(folder_id))
        folder = next(iter(unique.values()))
        clauses, parameters = self._scope(
            source_id, section=folder["section_id"], tags=tags, tag_colors=tag_colors,
            item_types=["bookmark", "folder"], has_note=has_note, has_tags=has_tags,
            metadata_match=metadata_match)
        clauses.append("i.parent_id=?")
        parameters.append(folder_id)
        where = " AND ".join(clauses)
        total = self.connection.execute("SELECT count(*) FROM items i WHERE " + where, parameters).fetchone()[0]
        children = self.connection.execute(
            "SELECT i.* FROM items i WHERE " + where +
            " ORDER BY i.position,i.preorder,i.item_id LIMIT ? OFFSET ?",
            parameters + [limit, offset]).fetchall()
        anchors = self._section_anchors(source_id)
        return {"source_id": source_id, "folder": self._item_result(folder, anchors),
                "total": total, "limit": limit, "offset": offset,
                "results": [self._item_result(row, anchors) for row in children]}

    @staticmethod
    def plan_terms(question):
        """Question text into literal search terms; no semantics, no guessing.

        ASCII runs of two or more characters are kept whole. A CJK run of four
        or fewer characters is kept whole as well, with boundary-aligned bigrams
        when exactly four characters. A longer run contributes boundary-aligned
        bigrams without cross-word fragments, so 本地部署 still reaches a card
        that only says 部署.
        A single ASCII character is dropped, because it would match almost
        everything; a single CJK character is kept, because it is often the
        whole entity. The order is the order of appearance and the list is
        capped, because a bounded OR is cheaper than an unbounded one and a
        fixed order is testable.
        """
        if not isinstance(question, str):
            raise ValueError("question must be a string")
        if not question.strip():
            raise ValueError("question must not be empty")
        # A URL in the question is an instruction to read it, not a search term:
        # its scheme and host would otherwise match half the package.
        terms = []
        for run in PLAN_RUN.findall(QUESTION_URL.sub(" ", question)):
            if run[0].isascii():
                candidates = [run] if len(run) >= 2 else []
            else:
                candidates = []
                sub_segments = [s for s in PLAN_CJK_SPLITTERS.split(run) if s]
                for segment in sub_segments:
                    if len(segment) <= 4:
                        candidates.append(segment)
                        if len(segment) == 4:
                            candidates.extend([segment[:2], segment[2:]])
                    else:
                        if len(segment) % 2 == 0:
                            candidates.extend(segment[i:i + 2] for i in range(0, len(segment) - 1, 2))
                        else:
                            for i in range(0, len(segment) - 1, 2):
                                candidates.append(segment[i:i + 2])
                            candidates.append(segment[-2:])
            for candidate in candidates:
                if candidate not in terms:
                    terms.append(candidate)
        return terms[:PLAN_MAX_TERMS]

    def plan_scope(self, source_id, question, max_cards=3, max_urls=8, homepage_limit=0, field_score=False):
        """Rank the cards a question touches and the bookmarks inside them.

        Local only: literal matching over indexed metadata, no fetch and no
        reasoning. ``cards`` is ranked by term weight scaled by the card's own
        density, not by raw hits: a term contributes its length divided by the
        number of cards it matches (so a specific name outranks a common word
        that appears everywhere), and the sum is multiplied by hits/bookmarks
        (so a 1,053-bookmark tree cannot win on its size alone). One card per
        canonical tree is kept, so a copy anchor cannot occupy two of the
        limited slots, and each card reports the terms it matched, its density
        and its weight. ``term_cards`` counts the canonical trees each term
        points at, which is how ``plan_research`` tells a name (one tree) from
        a common word. ``urls`` holds the matched bookmarks of the selected
        cards, deduplicated by URL, with the terms each URL's own rows matched
        and the source-wide instance count, which is not the selected scope.
        """
        source_id = self.resolve_source_id(source_id)
        source = self._source(source_id)
        package = self._input_path(source_id, source["package_path"])
        # Partial imports keep cards whose file disappeared. They stay indexed,
        # but ranking them above current cards hides the fact that their text is
        # no longer in the package. Their URLs remain useful as a supplement.
        missing_files = {row[0] for row in self.connection.execute(
            "SELECT file_path FROM files WHERE source_id=?", (source_id,))
            if not (package / row[0]).is_file()}
        if type(max_cards) is not int or not 1 <= max_cards <= 3:
            raise ValueError("max_cards must be an integer from 1 to 3")
        if type(max_urls) is not int or not 1 <= max_urls <= 8:
            raise ValueError("max_urls must be an integer from 1 to 8")
        if type(homepage_limit) is not int or not 0 <= homepage_limit <= 8:
            raise ValueError("homepage_limit must be an integer from 0 to 8")
        if type(field_score) is not bool:
            raise ValueError("field_score must be a boolean")
        terms = self.plan_terms(question)
        result = {"source_id": source_id, "terms": terms, "term_cards": {}, "cards": [], "urls": [],
                  "truncated": False, "errors": []}
        if not terms:
            result["errors"].append("The question has no searchable term: a single ASCII character is not "
                                    "searched. Ask with a longer name, a phrase or a URL")
            return result
        clauses = [self._match(term) for term in terms]
        where = " OR ".join(clause for clause, _ in clauses)
        parameters = [value for _, values in clauses for value in values]
        # One grouped count per term answers both questions at once: how many
        # cards a term touches (its weight denominator) and which cards matched
        # it. No per-card loop is needed.
        per_term = {}
        for term, (clause, values) in zip(terms, clauses):
            per_term[term] = {row["section_id"]: row["hits"] for row in self.connection.execute(
                "SELECT i.section_id AS section_id, count(*) AS hits FROM items i"
                " WHERE i.source_id=? AND i.item_type='bookmark' AND " + clause + " GROUP BY i.section_id",
                (source_id, *values))}
        hits = {row["section_id"]: row["hits"] for row in self.connection.execute(
            "SELECT i.section_id AS section_id, count(*) AS hits FROM items i"
            " WHERE i.source_id=? AND i.item_type='bookmark' AND (" + where + ")"
            " GROUP BY i.section_id", (source_id, *parameters))}
        if not hits:
            result["errors"].append("No bookmark in this source matches the question terms")
            return result
        sections = {row["section_id"]: row for row in self._sections(source_id)}
        scores = {}
        for term, matched in per_term.items():
            if not matched:
                continue
            weight = float(len(term)) / len(matched)
            for section_id in matched:
                scores[section_id] = scores.get(section_id, 0.0) + weight
        # A title occurrence is a stronger signal than a note/URL hit. Only
        # longer terms need it, and the check is token-aware for ASCII so
        # "quantum" does not count inside "QuantumNous".
        # A term that reaches exactly one canonical tree names that tree; a term
        # that reaches many is a common word, whatever it looks like.
        for term, matched in per_term.items():
            result["term_cards"][term] = len({sections[value]["canonical_id"] or value
                                              for value in matched}) if matched else 0
        # A title occurrence is a stronger signal than a note/URL hit. Only
        # terms that reach a few trees need the extra scan; a common word that
        # appears across the whole package cannot be a name.
        title_hits = {}
        for term in terms:
            if len(term) < 4 or result["term_cards"].get(term, 0) > 3:
                continue
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            counts = {}
            for row in self.connection.execute(
                    "SELECT section_id, title FROM items WHERE source_id=? AND item_type='bookmark'"
                    " AND title LIKE ? ESCAPE '\\'", (source_id, "%" + escaped + "%")):
                if title_has_term(row["title"], term):
                    counts[row["section_id"]] = counts.get(row["section_id"], 0) + 1
            title_hits[term] = counts
        bookmarks = {row["section_id"]: row["count"] for row in self.connection.execute(
            "SELECT section_id, count(*) AS count FROM items WHERE source_id=? AND item_type='bookmark'"
            " GROUP BY section_id", (source_id,))}
        newest = {row["section_id"]: (row["newest"], row["newest_high"]) for row in self.connection.execute(
            "SELECT section_id, max(added_at) AS newest,"
            " max(CASE WHEN added_at_confidence='high' THEN added_at END) AS newest_high"
            " FROM items WHERE source_id=? AND item_type='bookmark'"
            " AND added_at IS NOT NULL GROUP BY section_id", (source_id,))}
        # Size must not win by itself: the term weight is scaled by the card's own
        # hit density, so an 82-of-107 topic card outranks an 18-of-1,053 tree.
        density = {value: (hits[value] / bookmarks[value]) if bookmarks.get(value) else 0.0
                   for value in scores}
        # Two passes keep mixed sort directions readable: the first fixes the
        # ascending tie-breaks, the second orders by score, hits and freshness,
        # and equal rows keep the order the first pass gave them.
        ordered = sorted(hits, key=lambda value: (sections[value]["file_path"], value))
        if field_score:
            card_field_scores = {}
            for sid in scores:
                sec_items = [dict(r) for r in self.connection.execute(
                    "SELECT * FROM items i WHERE i.source_id=? AND i.section_id=? AND i.item_type='bookmark' AND (" + where + ")",
                    (source_id, sid, *parameters)).fetchall()]
                total_f = sum(BookmarkIndex.score_item(r, terms)[0] for r in sec_items)
                card_field_scores[sid] = total_f / (bookmarks.get(sid) or 1)
            ordered.sort(key=lambda value: (card_field_scores.get(value, 0.0) * density[value],
                                            scores[value] * density[value], hits[value],
                                            (newest.get(value) or (None, None))[0] or ""), reverse=True)
        else:
            ordered.sort(key=lambda value: (scores[value] * density[value], hits[value],
                                            (newest.get(value) or (None, None))[0] or ""), reverse=True)
        trees, ranked = set(), []
        for section_id in ordered:
            row = sections[section_id]
            tree = row["canonical_id"] or section_id
            if tree in trees:
                continue
            trees.add(tree)
            ranked.append({"section_id": section_id, "label": row["label"], "title": row["title"] or "",
                "file_path": row["file_path"],
                "hits": hits[section_id], "score": round(scores[section_id] * density[section_id], 6),
                "density": round(density[section_id], 6),
                "newest_added_at": (newest.get(section_id) or (None, None))[0],
                "newest_high_added_at": (newest.get(section_id) or (None, None))[1],
                "bookmarks": bookmarks.get(section_id, 0),
                "matched_terms": [term for term in terms if section_id in per_term[term]],
                "term_hits": {term: per_term[term][section_id] for term in terms
                              if section_id in per_term[term]},
                "term_title_hits": {term: title_hits.get(term, {}).get(section_id, 0) for term in terms
                                    if title_hits.get(term, {}).get(section_id)},
                "stale_missing_file": row["file_path"] in missing_files,
                "anchor_of": row["canonical_id"] if row["is_anchor"] else None})
        eligible = [card for card in ranked if not card["stale_missing_file"]]
        stale = [card for card in ranked if card["stale_missing_file"]]
        # A stale card never takes a top slot while a current card exists; its
        # URLs still join the candidate pool below, so a deleted card's precise
        # entry points are not lost.
        result["cards"] = (eligible or ranked)[:max_cards]
        result["stale_missing_files"] = sorted(missing_files)
        selected = [card["section_id"] for card in result["cards"]]
        stale_sections = [card["section_id"] for card in stale[:max_cards]
                          if card["section_id"] not in selected]
        selected_for_urls = selected + stale_sections
        placeholders = ",".join("?" for _ in selected_for_urls)
        rows = [dict(row) for row in self.connection.execute(
            "SELECT i.url AS url, count(*) AS instances, min(i.title) AS title,"
            " group_concat(DISTINCT i.section_id) AS sections FROM items i"
            " WHERE i.source_id=? AND i.item_type='bookmark' AND i.url<>''"
            " AND i.section_id IN (" + placeholders + ") AND (" + where + ")"
            " GROUP BY i.url", (source_id, *selected_for_urls, *parameters))]
        # A URL is as relevant as the most specific term its own rows matched, so
        # a bookmark that matched a name comes before incidental hits on a common
        # word, wherever inside the selection it lives. Card score, raw instance
        # counts and the URL itself only break ties.
        url_weight, url_terms = {}, {}
        for term, (clause, values) in zip(terms, clauses):
            if not per_term[term]:
                continue
            weight = float(len(term)) / len(per_term[term])
            for url, in self.connection.execute(
                    "SELECT DISTINCT i.url FROM items i WHERE i.source_id=? AND i.item_type='bookmark'"
                    " AND i.url<>'' AND i.section_id IN (" + placeholders + ") AND " + clause,
                    (source_id, *selected_for_urls, *values)):
                url_weight[url] = max(url_weight.get(url, 0.0), weight)
                url_terms.setdefault(url, []).append(term)
        card_score = {card["section_id"]: card["score"] for card in result["cards"] + stale}
        rows.sort(key=lambda row: (-url_weight.get(row["url"], 0.0), URL_KIND_RANK[url_kind(row["url"])],
            -max(card_score.get(value, 0.0) for value in row["sections"].split(",")),
            -row["instances"], row["url"]))
        if homepage_limit:
            kept, homepage_counts = [], {}
            for row in rows:
                if url_kind(row["url"]) == "homepage":
                    sections = row["sections"].split(",")
                    if any(homepage_counts.get(section, 0) >= homepage_limit for section in sections):
                        continue
                    for section in sections:
                        homepage_counts[section] = homepage_counts.get(section, 0) + 1
                kept.append(row)
            rows = kept
        result["truncated"] = len(rows) > max_urls
        stale_ids = set(stale_sections) | {card["section_id"] for card in result["cards"]
                                           if card["stale_missing_file"]}
        for row in rows[:max_urls]:
            row["section_ids"] = sorted(row.pop("sections").split(","))
            row["matched_terms"] = url_terms.get(row["url"], [])
            row["url_kind"] = url_kind(row["url"])
            row["stale"] = bool(row["section_ids"]) and all(value in stale_ids for value in row["section_ids"])
            row["source_instances"] = self.connection.execute(
                "SELECT count(*) FROM items WHERE source_id=? AND item_type='bookmark' AND url=?",
                (source_id, row["url"])).fetchone()[0]
            result["urls"].append(row)
        # Defensive invariant: the importer refuses a bookmark without a URL, so
        # a matching card always yields at least one URL.
        if not result["urls"]:
            result["errors"].append("Matched cards contain no bookmark matching the question terms")
        return result

    def _match(self, target):
        """Literal substring matching: every whitespace-separated term must occur.

        Terms of three or more characters use the trigram full-text index, which
        is substring-based and case-insensitive. Shorter terms (and every term
        when trigram is unavailable) keep the LIKE fallback, because a two
        character CJK term cannot be answered by a trigram index.
        """
        terms = target.split() or [target]
        clauses, parameters = [], []
        for term in terms:
            if self._fts_mode == "trigram" and len(term) >= TRIGRAM_MINIMUM:
                clauses.append("i.pk IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)")
                parameters.append('"' + term.replace('"', '""') + '"')
                continue
            # Escape all SQL wildcard characters; FTS query syntax is not exposed.
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            fields = ("title", "url", "note", "tag_text", "folder_path")
            clauses.append("(" + " OR ".join("i.%s LIKE ? ESCAPE '\\'" % field for field in fields) + ")")
            parameters.extend(["%" + escaped + "%"] * len(fields))
        return "(" + " AND ".join(clauses) + ")", parameters

    def _section_anchors(self, source_id):
        """Map a canonical section to the copy-anchor sections that share its tree."""
        anchors = {}
        for row in self.connection.execute(
                "SELECT section_id, canonical_id, is_anchor FROM sections WHERE source_id=?", (source_id,)):
            if row["is_anchor"] and row["canonical_id"] and row["canonical_id"] != row["section_id"]:
                anchors.setdefault(row["canonical_id"], []).append(row["section_id"])
        return anchors

    def _item_result(self, row, anchors=None, section_cache=None):
        keys = row.keys()
        result = {key: row[key] for key in ("source_id", "section_id", "item_id", "parent_id", "item_type", "title",
                                            "note", "note_color", "position")
                  + (("added_at", "added_at_source", "added_at_confidence") if "added_at" in keys else ())}
        if row["item_type"] != "folder" or row["url"]:
            result["url"] = row["url"]
        result["added_at_precision"] = ADDED_AT_SOURCES.get(result.get("added_at_source"), (None,))[0]
        result.update(source=row["source_id"], section=row["section_id"], item=row["item_id"],
            path=json.loads(row["path_json"]), folder_path=row["folder_path"], tags=json.loads(row["tags_json"]),
            raw_json=json.loads(row["raw_json"]), metadata=json.loads(row["metadata_json"]))
        # An untitled parentless folder is the tree container a canvas package
        # synthesizes, not a folder the user created. Mark it so counts and
        # listings can tell them apart.
        if row["item_type"] == "folder" and not row["title"] and not row["parent_id"]:
            result["synthetic"] = True
        if anchors:
            # Which copy cards display this bookmark; the query just answers one
            # of them, so "which cards contain it" would otherwise be incomplete.
            shown = anchors.get(row["section_id"])
            if shown:
                result["shown_in_anchors"] = sorted(shown)
        key = row["source_id"], row["section_id"]
        cache = {} if section_cache is None else section_cache
        if key not in cache:
            cache[key] = self.connection.execute("SELECT label,file_path FROM sections WHERE source_id=? AND section_id=?", key).fetchone()
        section = cache[key]
        result["section_label"], result["file_path"] = section[0], section[1]
        return result

    @staticmethod
    def score_item(row, targets=None):
        """Compute non-binding weighted scoring hints for a candidate item.

        Scoring tiers:
        - title_prefix: 140
        - title_contains: 135
        - url: 120
        - tag: 110
        - note: 90
        - folder_path: inherited evidence only; it is not an item score
        Time confidence tier bonus:
        - high: +10
        - medium: +5
        - low: +2
        """
        targets = targets or []
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        title = (row["title"] if "title" in keys and row["title"] else "").casefold()
        note = (row["note"] if "note" in keys and row["note"] else "").casefold()
        folder_path = (row["folder_path"] if "folder_path" in keys and row["folder_path"] else "").casefold()
        url = (row["url"] if "url" in keys and row["url"] else "").casefold()
        tag_text = (row["tag_text"] if "tag_text" in keys and row["tag_text"] else "").casefold()

        field_hits = []
        score = 0
        for target in targets:
            t = (target or "").casefold().strip()
            if not t:
                continue
            if title.startswith(t):
                if "title_prefix" not in field_hits:
                    field_hits.append("title_prefix")
                    score += 140
            elif t in title:
                if "title_contains" not in field_hits:
                    field_hits.append("title_contains")
                    score += 135
            if t in tag_text:
                if "tag" not in field_hits:
                    field_hits.append("tag")
                    score += 110
            if t in note:
                if "note" not in field_hits:
                    field_hits.append("note")
                    score += 90
            if t in folder_path and "folder_path" not in field_hits:
                field_hits.append("folder_path")
            if t in url:
                if "url" not in field_hits:
                    field_hits.append("url")
                    score += 120

        conf = row["added_at_confidence"] if "added_at_confidence" in keys else None
        if conf == "high":
            score += 10
            field_hits.append("time_high")
        elif conf == "medium":
            score += 5
            field_hits.append("time_medium")
        elif conf == "low":
            score += 2
            field_hits.append("time_low")

        return score, field_hits

    def search(self, source_id, targets=None, section=None, group_id=None, folder_id=None, tags=None,
               limit=20, offset=0, tag_colors=None, item_types=None, count_only=False, compact=False,
               score=False, has_note=None, has_tags=None, metadata_match="all", sort_by="default"):
        """Literal structured search. ``limit=0`` or ``count_only`` returns counts only."""
        source_id = self.resolve_source_id(source_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 1000:
            raise ValueError("limit must be an integer from 0 to 1000; 0 returns counts only")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if type(compact) is not bool:
            raise ValueError("compact must be a boolean")
        if type(score) is not bool:
            raise ValueError("score must be a boolean")
        if has_note is not None and type(has_note) is not bool:
            raise ValueError("has_note must be a boolean or null")
        if has_tags is not None and type(has_tags) is not bool:
            raise ValueError("has_tags must be a boolean or null")
        if metadata_match not in ("all", "any"):
            raise ValueError("metadata_match must be all or any")
        if sort_by not in ("default", "added_at_desc", "added_at_asc"):
            raise ValueError("sort_by must be default, added_at_desc or added_at_asc")
        if isinstance(targets, str) or isinstance(tags, str) or isinstance(tag_colors, str):
            raise ValueError("targets, tags and tag_colors must be lists of strings")
        targets = list(dict.fromkeys(targets or []))
        if len(targets) > 100:
            raise ValueError("At most 100 targets per request")
        for target in targets:
            _string(target, "target", True)
        if item_types is not None:
            if (not isinstance(item_types, list) or not 1 <= len(item_types) <= 2
                    or any(value not in ("bookmark", "folder") for value in item_types)
                    or len(set(item_types)) != len(item_types)):
                raise ValueError("item_types must select bookmark and/or folder without duplicates")
        clauses, args = self._scope(source_id, section, group_id, folder_id, tags, tag_colors, item_types,
                                    has_note, has_tags, metadata_match)
        page_size = 0 if count_only else limit
        anchors_by_section = self._section_anchors(source_id)
        section_cache = {}

        def query(chosen, page=True):
            predicates, parameters = list(clauses), list(args)
            if chosen:
                matches = [self._match(target) for target in chosen]
                predicates.append("(" + " OR ".join(match[0] for match in matches) + ")")
                parameters.extend(value for _, values in matches for value in values)
            where = " AND ".join(predicates)
            rows, total = [], None
            if page and page_size:
                if score:
                    total = self.connection.execute(
                        "SELECT count(*) FROM items i WHERE " + where, parameters).fetchone()[0]
                    candidate_limit = max(1000, offset + page_size * 5)
                    if total > candidate_limit:
                        all_rows = self.connection.execute(
                            "SELECT i.* FROM items i WHERE " + where +
                            " ORDER BY (i.added_at IS NULL), i.added_at DESC, i.section_id, i.preorder LIMIT ?",
                            parameters + [candidate_limit]).fetchall()
                    else:
                        all_rows = self.connection.execute(
                            "SELECT i.* FROM items i WHERE " + where, parameters).fetchall()
                    scored_rows = []
                    for r in all_rows:
                        s_val, s_hits = BookmarkIndex.score_item(r, chosen)
                        scored_rows.append((r, s_val, s_hits))
                    scored_rows.sort(key=lambda t: (t[0]["section_id"], t[0]["preorder"], t[0]["item_id"]))
                    if sort_by == "default":
                        scored_rows.sort(key=lambda t: t[0]["added_at"] or "", reverse=True)
                        scored_rows.sort(key=lambda t: 0 if t[0]["added_at"] is not None else 1)
                        scored_rows.sort(key=lambda t: t[1], reverse=True)
                    else:
                        scored_rows.sort(key=lambda t: t[1], reverse=True)
                        scored_rows.sort(key=lambda t: t[0]["added_at"] or "",
                                         reverse=sort_by == "added_at_desc")
                        scored_rows.sort(key=lambda t: 0 if t[0]["added_at"] is not None else 1)

                    page_slice = scored_rows[offset : offset + page_size]
                    rows_result = []
                    for r, s_val, s_hits in page_slice:
                        item = self._item_result(r, anchors_by_section, section_cache)
                        item["score"] = s_val
                        item["score_hint"] = True
                        item["field_hits"] = s_hits
                        rows_result.append(item)
                elif self._window_functions:
                    # One statement returns the page and its pre-LIMIT count, so a
                    # batch of targets does not pay a second scan per target.
                    order = ("(i.added_at IS NULL),i.added_at " + ("DESC" if sort_by == "added_at_desc" else "ASC")
                             if sort_by != "default" else "i.section_id,i.preorder,i.item_id")
                    rows = self.connection.execute(
                        "SELECT i.*, count(*) OVER () AS computed_total FROM items i WHERE " + where +
                        " ORDER BY " + order + (",i.section_id,i.preorder,i.item_id" if sort_by != "default" else "") +
                        " LIMIT ? OFFSET ?",
                        parameters + [page_size, offset]).fetchall()
                    total = rows[0]["computed_total"] if rows else self.connection.execute(
                        "SELECT count(*) FROM items i WHERE " + where, parameters).fetchone()[0]
                    rows_result = [self._item_result(row, anchors_by_section, section_cache) for row in rows]
                else:
                    total = self.connection.execute("SELECT count(*) FROM items i WHERE " + where, parameters).fetchone()[0]
                    order = ("(i.added_at IS NULL),i.added_at " + ("DESC" if sort_by == "added_at_desc" else "ASC")
                             if sort_by != "default" else "i.section_id,i.preorder,i.item_id")
                    rows = self.connection.execute(
                        "SELECT i.* FROM items i WHERE " + where + " ORDER BY " + order +
                        (",i.section_id,i.preorder,i.item_id" if sort_by != "default" else "") + " LIMIT ? OFFSET ?",
                        parameters + [page_size, offset]).fetchall()
                    rows_result = [self._item_result(row, anchors_by_section, section_cache) for row in rows]
            else:
                total = self.connection.execute("SELECT count(*) FROM items i WHERE " + where, parameters).fetchone()[0]
                rows_result = []
            unique = self.connection.execute(
                "SELECT count(DISTINCT i.url) FROM items i WHERE " + where + " AND i.url<>''", parameters).fetchone()[0]
            return {"total": total, "unique_urls": unique, "limit": limit, "offset": offset,
                    "results": rows_result}

        result = query(targets)
        if score:
            result["score_mode"] = "hint"
            result["score_candidate_pool"] = {
                "truncated": result["total"] > max(1000, offset + page_size * 5),
                "selection": "newest_added_at_first",
                "candidate_limit": max(1000, offset + page_size * 5),
            }
            result["score_note"] = (
                "Item scores are non-binding ranking hints based on field weights "
                "(title_prefix: 140, title_contains: 135, url: 120, tag: 110, note: 90) "
                "plus time confidence bonus (high: +10, medium: +5, low: +2). folder_path is inherited evidence "
                "for folder aggregation and does not increase an item's score. Filter matching remains literal substring. "
                "When score_candidate_pool.truncated is true, only the newest-added candidates were ranked."
            )
        section_rows = self._sections(source_id, section) if section is not None else []
        anchors = {row["section_id"]: row["canonical_id"] for row in section_rows if row["is_anchor"]}
        result.update(source_id=source_id,
            query_scope={"section": section, "group_id": group_id, "folder_id": folder_id,
                         "tags": list(tags or []), "tag_colors": list(tag_colors or []),
                         "item_types": list(item_types) if item_types else ["bookmark"],
                         "has_note": has_note, "has_tags": has_tags,
                         "metadata_match": metadata_match, "sort_by": sort_by},
            match_mode="literal_substring", match_index="fts_trigram+like" if self._fts_mode == "trigram" else "like",
            searched_fields=["title", "url", "note", "tags.text", "folder_path"])
        result["counts"] = {"instances": result["total"], "unique_urls": result["unique_urls"],
            "note": "instances counts rows of query_scope.item_types, including synthetic folders when selected; unique_urls counts distinct non-empty "
                    "URLs. Per-section totals must not be summed when a copy anchor shares another card's tree."}
        if anchors:
            result["anchor_of"] = anchors
            result["anchor_note"] = ("The requested card is a copy anchor of another card; this result is the shared "
                                     "tree, so it already appears under that card's own section.")
        canvas_matches = self._canvas_matches(source_id, targets)
        if canvas_matches:
            result["canvas_matches"] = canvas_matches
            result["canvas_match_note"] = ("Canvas text cards, group labels and edge labels matching a target. They are "
                                           "not bookmark items, so they are excluded from item totals and result pages; "
                                           "use get_context for the surrounding layout.")
        shown = offset + len(result["results"]) if result["results"] else offset
        result["next_offset"] = None if page_size == 0 else (shown if shown < result["total"] else None)
        # A single-target union is identical to its per-target page.
        result["targets"] = [dict(target=target, **({key: result[key] for key in
            ("total", "unique_urls", "limit", "offset", "results")} if len(targets) == 1 else query([target])))
            for target in targets]
        if compact:
            from bookmark_output import compact_search
            return compact_search(result)
        return result

    def _canvas_matches(self, source_id, targets):
        """Find canvas text nodes, group labels and edge labels for these targets.

        These are not bookmark items, so they never enter ``results`` or
        ``total``. They are reported separately because a user asking about
        "the card labelled 123" otherwise gets unrelated short-substring
        bookmark hits and no sign that 123 is a group or edge label.
        """
        if not targets:
            return []
        patterns = []
        for target in targets:
            escaped = target.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            patterns.append("%" + escaped + "%")
        # One query per canvas table for the whole batch, not two per target.
        clause = " OR ".join("label LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\'" for _ in patterns)
        found = []
        for row in self.connection.execute(
                "SELECT canvas_path,node_id,node_type,label,text FROM nodes WHERE source_id=? AND (" + clause + ") "
                "ORDER BY canvas_path,position", (source_id, *[value for pattern in patterns for value in (pattern, pattern)])):
            found.append({"kind": "text" if row["node_type"] == "text" else "group",
                          "canvas_path": row["canvas_path"], "node_id": row["node_id"],
                          "label": row["label"], "text": row["text"], "node_type": row["node_type"]})
        clause = " OR ".join("label LIKE ? ESCAPE '\\'" for _ in patterns)
        for row in self.connection.execute(
                "SELECT canvas_path,edge_id,from_node,to_node,label FROM edges WHERE source_id=? AND (" + clause + ") "
                "ORDER BY canvas_path,edge_id", (source_id, *patterns)):
            found.append({"kind": "edge", "canvas_path": row["canvas_path"], "edge_id": row["edge_id"],
                          "label": row["label"], "from_node": row["from_node"], "to_node": row["to_node"]})
        # Attribute each canvas hit to every target it answers.
        matches = []
        for row in found:
            haystack = ((row.get("label") or "") + "\n" + (row.get("text") or "")).casefold()
            for target in targets:
                needle = target.casefold()
                if needle and needle in haystack:
                    matches.append({"target": target, **row})
        return matches

    def context(self, source_id, section=None, group_id=None, item_id=None):
        source_id = self.resolve_source_id(source_id)
        source = self._source(source_id)
        sections = self._sections(source_id, section)
        nodes = [dict(row) for row in self.connection.execute("SELECT * FROM nodes WHERE source_id=? ORDER BY canvas_path,position", (source_id,))]
        all_nodes = list(nodes)
        memberships = [dict(row) for row in self.connection.execute("SELECT * FROM memberships WHERE source_id=? ORDER BY canvas_path,group_id,node_id", (source_id,))]
        edges = [dict(row) for row in self.connection.execute("SELECT * FROM edges WHERE source_id=? ORDER BY canvas_path,edge_id", (source_id,))]
        item_rows = []
        if item_id is not None:
            canonical_ids = {row["canonical_id"] for row in sections}
            item_rows = [row for row in self.connection.execute("SELECT * FROM items WHERE source_id=? AND item_id=?", (source_id, item_id)) if row["section_id"] in canonical_ids]
            if not item_rows:
                raise ValueError("Unknown item in requested scope: " + str(item_id))
            ids = {row["section_id"] for row in item_rows}
            sections = [row for row in sections if row["canonical_id"] in ids]
        if group_id is not None:
            group = self._group(source_id, group_id)
            member_ids = {m["node_id"] for m in memberships if m["canvas_path"] == group["canvas_path"] and m["group_id"] == group["node_id"]}
            selected = [node for node in nodes if node["canvas_path"] == group["canvas_path"] and node["node_id"] in member_ids | {group["node_id"]}]
            section_ids = {node["section_id"] for node in selected if node["section_id"]}
            sections = [row for row in sections if row["section_id"] in section_ids]
            if item_id is not None:
                canonical_ids = {row["canonical_id"] for row in sections}
                item_rows = [row for row in item_rows if row["section_id"] in canonical_ids]
                if not item_rows:
                    raise ValueError("Item is outside the requested group")
            if section is not None or item_id is not None:
                section_ids = {row["section_id"] for row in sections}
                selected = [node for node in selected
                    if node["section_id"] in section_ids or node["node_id"] == group["node_id"]]
            nodes = selected
        elif section is not None or item_id is not None:
            section_ids = {row["section_id"] for row in sections}
            selected_ids = {(node["canvas_path"], node["node_id"]) for node in nodes if node["section_id"] in section_ids}
            selected_ids.update((m["canvas_path"], m["group_id"]) for m in memberships if (m["canvas_path"], m["node_id"]) in selected_ids)
            nodes = [node for node in nodes if (node["canvas_path"], node["node_id"]) in selected_ids]
        if section is not None or group_id is not None or item_id is not None:
            selected_ids = {(node["canvas_path"], node["node_id"]) for node in nodes}
            edges = [edge for edge in edges if (edge["canvas_path"], edge["from_node"]) in selected_ids or (edge["canvas_path"], edge["to_node"]) in selected_ids]
            memberships = [m for m in memberships if (m["canvas_path"], m["group_id"]) in selected_ids or (m["canvas_path"], m["node_id"]) in selected_ids]
        for edge in edges:
            edge["direction"] = ("both" if edge["from_end"] == edge["to_end"] == "arrow" else
                "forward" if edge["to_end"] == "arrow" else "reverse" if edge["from_end"] == "arrow" else "none")
            edge["raw_json"] = json.loads(edge["raw_json"])
            edge["added_at"] = _added_at_from_edge_id(edge["edge_id"])
            edge["added_at_source"] = "edge_epoch" if edge["added_at"] else None
            edge["added_at_confidence"] = ADDED_AT_SOURCES["edge_epoch"][1] if edge["added_at"] else None
        # Chronological inside each canvas; an edge whose id carries no time
        # stays in stable id order at the end instead of being invented a date.
        edges.sort(key=lambda edge: (edge["canvas_path"], edge["added_at"] is None,
                                     edge["added_at"] or "", edge["edge_id"]))
        for node in nodes:
            node["raw_json"] = json.loads(node["raw_json"])
        selected_node_ids = {(node["canvas_path"], node["node_id"]) for node in nodes}
        endpoint_ids = {(edge["canvas_path"], edge[end]) for edge in edges for end in ("from_node", "to_node")}
        endpoint_ids.update((member["canvas_path"], member[end])
            for member in memberships for end in ("group_id", "node_id"))
        related_nodes = [node for node in all_nodes
            if (node["canvas_path"], node["node_id"]) in endpoint_ids - selected_node_ids]
        for node in related_nodes:
            node["raw_json"] = json.loads(node["raw_json"])
        section_results = []
        for row in sections:
            entry = dict(row)
            # Context is bounded to section headers. The entire source object,
            # including all unknown fields, remains in the database raw_json.
            entry["raw_json"] = {key: value for key, value in json.loads(entry["raw_json"]).items()
                if key not in ("tree", "items", "identityMap")}
            entry["bookmark_count"] = self.connection.execute("SELECT count(*) FROM items WHERE source_id=? AND section_id=? AND item_type='bookmark'", (source_id, entry["canonical_id"])).fetchone()[0]
            # A copy anchor reports the shared tree's count, so summing section
            # counts double counts. Say so explicitly instead of leaving a
            # self-consistent but inflated total.
            entry["anchor_of"] = entry["canonical_id"] if entry["is_anchor"] else None
            entry["counted_in_totals"] = not bool(entry["is_anchor"])
            section_results.append(entry)
        items = [self._item_result(row) for row in item_rows]
        for item, row in zip(items, item_rows):
            item["ancestors"] = []
            for ancestor in json.loads(row["ancestor_ids_json"]):
                ancestor_row = self.connection.execute("SELECT * FROM items WHERE source_id=? AND section_id=? AND item_id=?", (source_id, row["section_id"], ancestor)).fetchone()
                if ancestor_row:
                    item["ancestors"].append(self._item_result(ancestor_row))
        return {"source_id": source_id, "source": source, "sections": section_results,
            "counts": self._scope_counts(source_id, section_results),
            "items": items, "nodes": nodes, "groups": [node for node in nodes if node["node_type"] == "group"],
            "edges": edges, "related_nodes": related_nodes, "memberships": memberships}

    def _scope_counts(self, source_id, section_results):
        """Distinct totals for the returned sections, so copy anchors are not summed twice."""
        counted = [row for row in section_results if row["counted_in_totals"]]
        instances, urls = 0, set()
        for row in counted:
            instances += row["bookmark_count"]
            urls.update(value for value in self.connection.execute(
                "SELECT DISTINCT url FROM items WHERE source_id=? AND section_id=? AND item_type='bookmark' AND url<>''",
                (source_id, row["canonical_id"])))
        return {"sections": len(section_results), "counted_sections": len(counted),
                "instances": instances, "unique_urls": len(urls),
                "note": "Section totals, not item or folder subtree totals. Sum of counted_sections only; copy anchors share another card's tree and are excluded."}

    def lookup_url(self, url, source_id=None, limit=100, offset=0):
        """Find all instances of a bookmark URL across sections and sources.

        Returns matching item instances with source, section, folder path,
        chronological added_at, and associated copy anchor cards.
        """
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be a non-empty string")
        url = url.strip()
        if source_id is not None:
            _string(source_id, "source_id", True)
            source_id = self.resolve_source_id(source_id)
            self._source(source_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer between 1 and 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")

        clauses = ["i.item_type = 'bookmark'", "i.url = ?"]
        params = [url]
        if source_id is not None:
            clauses.append("i.source_id = ?")
            params.append(source_id)
        where = " AND ".join(clauses)

        total = self.connection.execute(f"SELECT count(*) FROM items i WHERE {where}", params).fetchone()[0]
        distinct_sources = [r[0] for r in self.connection.execute(
            f"SELECT DISTINCT i.source_id FROM items i WHERE {where} ORDER BY i.source_id", params).fetchall()]

        first_seen_row = self.connection.execute(
            f"SELECT min(i.added_at) FROM items i WHERE {where} AND i.added_at IS NOT NULL", params).fetchone()
        first_seen = first_seen_row[0] if first_seen_row and first_seen_row[0] else None

        if source_id is not None:
            anchors_by_section = self._section_anchors(source_id)
        else:
            anchors_by_section = {}
            for row in self.connection.execute(
                    "SELECT source_id, section_id, canonical_id FROM sections WHERE is_anchor=1 AND canonical_id IS NOT NULL AND canonical_id != section_id"):
                anchors_by_section.setdefault((row["source_id"], row["canonical_id"]), []).append(row["section_id"])

        order_by = "ORDER BY (i.added_at IS NULL), i.added_at ASC, i.source_id ASC, i.section_id ASC, i.preorder ASC, i.item_id ASC"
        query_sql = f"""
            SELECT i.source_id, i.section_id, i.item_id, i.parent_id, i.title, i.url,
                   i.note, i.folder_path, i.path_json, i.added_at, i.added_at_source,
                   i.added_at_confidence, s.label AS section_label, s.title AS section_title,
                   s.file_path, s.is_anchor, s.canonical_id
            FROM items i
            LEFT JOIN sections s ON i.source_id = s.source_id AND i.section_id = s.section_id
            WHERE {where}
            {order_by}
            LIMIT ? OFFSET ?
        """
        rows = self.connection.execute(query_sql, params + [limit, offset]).fetchall()

        instances = []
        for row in rows:
            sid = row["source_id"]
            sec_id = row["section_id"]
            if source_id is not None:
                anchors = anchors_by_section.get(sec_id, [])
            else:
                anchors = anchors_by_section.get((sid, sec_id), [])
            try:
                path = json.loads(row["path_json"]) if row["path_json"] else []
            except (ValueError, TypeError):
                path = []
            instances.append({
                "source_id": sid,
                "section_id": sec_id,
                "section_label": row["section_label"] or "",
                "section_title": row["section_title"] or "",
                "file_path": row["file_path"] or "",
                "item_id": row["item_id"],
                "parent_id": row["parent_id"],
                "title": row["title"],
                "url": row["url"],
                "folder_path": row["folder_path"],
                "path": path,
                "added_at": row["added_at"],
                "added_at_source": row["added_at_source"],
                "added_at_confidence": row["added_at_confidence"],
                "shown_in_anchors": sorted(anchors),
            })

        next_offset = (offset + len(instances)) if (offset + len(instances)) < total else None
        return {
            "url": url,
            "source_filter": source_id,
            "total_instances": total,
            "unique_sources": len(distinct_sources),
            "sources": distinct_sources,
            "first_seen": first_seen,
            "instances": instances,
            "limit": limit,
            "offset": offset,
            "next_offset": next_offset,
        }

    def traverse(self, source_id, section=None, group_id=None, item_id=None, node_id=None,
                 max_depth=2, direction="all", limit=100, offset=0):
        """Multi-hop graph traversal starting from nodes, sections, groups, or items.

        Traverses along canvas edges and group memberships up to max_depth hops.
        Returns the impact surface: affected sections, groups, text cards,
        and traversed paths with deterministic sorting and pagination.
        """
        source_id = self.resolve_source_id(source_id)
        source = self._source(source_id)
        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 1 <= max_depth <= 10:
            raise ValueError("max_depth must be an integer between 1 and 10")
        if direction not in ("all", "out", "in"):
            raise ValueError("direction must be 'all', 'out', or 'in'")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer between 1 and 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")

        all_nodes = [dict(row) for row in self.connection.execute(
            "SELECT * FROM nodes WHERE source_id=? ORDER BY canvas_path,position", (source_id,))]
        all_edges = [dict(row) for row in self.connection.execute(
            "SELECT * FROM edges WHERE source_id=? ORDER BY canvas_path,edge_id", (source_id,))]
        all_memberships = [dict(row) for row in self.connection.execute(
            "SELECT * FROM memberships WHERE source_id=? ORDER BY canvas_path,group_id,node_id", (source_id,))]
        sections_map = {row["section_id"]: dict(row) for row in self._sections(source_id)}

        for edge in all_edges:
            edge["direction"] = ("both" if edge["from_end"] == edge["to_end"] == "arrow" else
                                 "forward" if edge["to_end"] == "arrow" else
                                 "reverse" if edge["from_end"] == "arrow" else "none")
            try:
                edge["raw_json"] = json.loads(edge["raw_json"])
            except (ValueError, TypeError):
                edge["raw_json"] = {}
            edge["added_at"] = _added_at_from_edge_id(edge["edge_id"])

        for node in all_nodes:
            try:
                node["raw_json"] = json.loads(node["raw_json"])
            except (ValueError, TypeError):
                node["raw_json"] = {}

        node_map = {(n["canvas_path"], n["node_id"]): n for n in all_nodes}
        start_nodes = []
        start_scope = {}

        if item_id is not None:
            start_scope["item_id"] = item_id
            item_rows = self.connection.execute(
                "SELECT section_id FROM items WHERE source_id=? AND item_id=?", (source_id, item_id)).fetchall()
            if not item_rows:
                raise ValueError("Unknown item in requested scope: " + str(item_id))
            item_sections = {r[0] for r in item_rows}
            start_nodes = [n for n in all_nodes if n["section_id"] in item_sections]
        elif group_id is not None:
            start_scope["group_id"] = group_id
            group = self._group(source_id, group_id)
            start_nodes = [n for n in all_nodes if n["canvas_path"] == group["canvas_path"] and n["node_id"] == group["node_id"]]
        elif node_id is not None:
            start_scope["node_id"] = node_id
            start_nodes = [n for n in all_nodes if n["node_id"] == node_id]
        elif section is not None:
            start_scope["section"] = section
            matched_sections = self._sections(source_id, section)
            if not matched_sections:
                raise ValueError("Unknown section: " + str(section))
            sec_ids = {r["section_id"] for r in matched_sections}
            start_nodes = [n for n in all_nodes if n["section_id"] in sec_ids]
            # Match get_context: include enclosing group containers in start nodes (depth 0)
            group_ids = {m["group_id"] for m in all_memberships if any(
                n["canvas_path"] == m["canvas_path"] and n["node_id"] == m["node_id"] for n in start_nodes)}
            for n in all_nodes:
                if n["node_type"] == "group" and n["node_id"] in group_ids and n not in start_nodes:
                    start_nodes.append(n)
        else:
            raise ValueError("Specify at least one of section, group_id, item_id, or node_id")

        if not start_nodes:
            raise ValueError("No matching canvas nodes found for the specified start target")

        adj = {}
        for edge in all_edges:
            cp = edge["canvas_path"]
            u = (cp, edge["from_node"])
            v = (cp, edge["to_node"])
            edir = edge["direction"]
            adj.setdefault(u, []).append(("edge", v, edge, "out", edir))
            adj.setdefault(v, []).append(("edge", u, edge, "in", edir))

        for m in all_memberships:
            cp = m["canvas_path"]
            grp = (cp, m["group_id"])
            mbr = (cp, m["node_id"])
            adj.setdefault(grp, []).append(("membership", mbr, m, "contains", None))
            adj.setdefault(mbr, []).append(("membership", grp, m, "member_of", None))

        start_keys = {(n["canvas_path"], n["node_id"]) for n in start_nodes}
        visited = {key: {"depth": 0, "node": node_map[key], "path": []} for key in start_keys if key in node_map}
        queue = [(key, 0, []) for key in visited]

        traversed_edges = {}
        traversed_memberships = set()

        while queue:
            curr_key, curr_d, curr_path = queue.pop(0)
            if curr_d >= max_depth:
                continue

            for hop_type, neighbor_key, obj, rel_or_dir, edge_dir in adj.get(curr_key, []):
                if neighbor_key not in node_map:
                    continue

                if hop_type == "edge":
                    if direction == "out":
                        if rel_or_dir == "out" and edge_dir not in ("forward", "both", "none"):
                            continue
                        if rel_or_dir == "in" and edge_dir not in ("reverse", "both", "none"):
                            continue
                    elif direction == "in":
                        if rel_or_dir == "out" and edge_dir not in ("reverse", "both", "none"):
                            continue
                        if rel_or_dir == "in" and edge_dir not in ("forward", "both", "none"):
                            continue

                    traversed_edges[obj["edge_id"]] = obj
                    step = {
                        "hop": curr_d + 1,
                        "type": "edge",
                        "edge_id": obj["edge_id"],
                        "label": obj.get("label", ""),
                        "direction": obj["direction"],
                        "from_node": obj["from_node"],
                        "to_node": obj["to_node"],
                    }
                else:
                    traversed_memberships.add((obj["canvas_path"], obj["group_id"], obj["node_id"]))
                    step = {
                        "hop": curr_d + 1,
                        "type": "membership",
                        "relation": rel_or_dir,
                        "group_id": obj["group_id"],
                        "node_id": obj["node_id"],
                    }

                if neighbor_key not in visited:
                    new_path = curr_path + [step]
                    visited[neighbor_key] = {
                        "depth": curr_d + 1,
                        "node": node_map[neighbor_key],
                        "path": new_path,
                    }
                    queue.append((neighbor_key, curr_d + 1, new_path))

        seen_affected_sections = {}
        affected_groups = []
        affected_text_cards = []
        all_visited_nodes = []

        max_depth_reached = max(v["depth"] for v in visited.values()) if visited else 0

        sorted_nodes = sorted(
            visited.values(),
            key=lambda item: (item["depth"], item["node"]["canvas_path"], item["node"]["position"], item["node"]["node_id"])
        )

        for entry in sorted_nodes:
            d = entry["depth"]
            n = entry["node"]
            node_repr = {
                "depth": d,
                "canvas_path": n["canvas_path"],
                "node_id": n["node_id"],
                "node_type": n["node_type"],
                "label": n["label"],
                "text": n["text"],
                "section_id": n["section_id"],
                "path": entry["path"],
            }
            if n["section_id"] and n["section_id"] in sections_map:
                s = sections_map[n["section_id"]]
                target_sec_id = s.get("canonical_id") or s["section_id"]
                b_count = self.connection.execute(
                    "SELECT count(*) FROM items WHERE source_id=? AND section_id=? AND item_type='bookmark'",
                    (source_id, target_sec_id)).fetchone()[0]
                node_repr["section"] = {
                    "section_id": s["section_id"],
                    "label": s["label"],
                    "title": s["title"],
                    "file_path": s["file_path"],
                    "is_anchor": bool(s["is_anchor"]),
                    "canonical_id": s["canonical_id"],
                    "bookmark_count": b_count,
                }
                if d > 0:
                    sec_id = s["section_id"]
                    if sec_id not in seen_affected_sections:
                        seen_affected_sections[sec_id] = dict(depth=d, **node_repr["section"])
                    elif d < seen_affected_sections[sec_id]["depth"]:
                        seen_affected_sections[sec_id]["depth"] = d

            if d > 0:
                if n["node_type"] == "group":
                    affected_groups.append({"depth": d, "canvas_path": n["canvas_path"], "node_id": n["node_id"], "label": n["label"]})
                elif n["node_type"] == "text":
                    affected_text_cards.append({"depth": d, "canvas_path": n["canvas_path"], "node_id": n["node_id"], "text": n["text"]})

            all_visited_nodes.append(node_repr)

        affected_sections = list(seen_affected_sections.values())

        reached_only = [n for n in all_visited_nodes if n["depth"] > 0]
        total_reached = len(reached_only)
        paged_nodes = reached_only[offset : offset + limit]
        next_offset = (offset + len(paged_nodes)) if (offset + len(paged_nodes)) < total_reached else None

        return {
            "source_id": source_id,
            "start_scope": start_scope,
            "start_nodes": [{"node_id": n["node_id"], "canvas_path": n["canvas_path"], "node_type": n["node_type"], "label": n["label"], "section_id": n["section_id"]} for n in start_nodes],
            "max_depth": max_depth,
            "direction": direction,
            "depth_reached": max_depth_reached,
            "counts": {
                "start_nodes": len(start_nodes),
                "total_visited": len(visited),
                "reached_nodes": total_reached,
                "affected_sections": len(affected_sections),
                "affected_groups": len(affected_groups),
                "affected_text_cards": len(affected_text_cards),
                "traversed_edges": len(traversed_edges),
                "traversed_memberships": len(traversed_memberships),
            },
            "affected_sections": affected_sections,
            "affected_groups": affected_groups,
            "affected_text_cards": affected_text_cards,
            "traversed_edges": sorted(traversed_edges.values(), key=lambda e: (e["canvas_path"], e["edge_id"])),
            "traversed_memberships": [{"canvas_path": cp, "group_id": gid, "node_id": nid} for cp, gid, nid in sorted(traversed_memberships)],
            "nodes": paged_nodes,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total_reached,
                "next_offset": next_offset,
            }
        }

    def inventory(self, source_ids):
        """Freeze the complete indexed input, independently of query previews.

        Exact URLs identify research rows; bookmarks remain distinct instances.
        Copy anchors add appearances of a canonical tree, never extra instances.
        One SQLite read transaction keeps files, items and canvas links coherent
        when another client synchronizes the index at the same time.
        """
        if not isinstance(source_ids, list) or not source_ids:
            raise ValueError("source_ids must contain indexed package IDs")
        identifiers = sorted(set(self.resolve_source_id(_string(value, "source_id", True)) for value in source_ids))
        from archive import SourceArchive
        result = {"schema_version": 1, "index_state": "last_synchronized",
                  "source_ids": identifiers, "sources": [], "files": [],
                  "sections": [], "folders": [], "nodes": [], "edges": [],
                  "memberships": [], "entries": []}
        by_url = {}
        section_cache = {}
        self.connection.execute("SAVEPOINT inventory_snapshot")
        try:
            for source_id in identifiers:
                context = self.context(source_id)
                files = [dict(row) for row in self.connection.execute(
                    "SELECT source_id,file_path,kind,sha256,revision FROM files "
                    "WHERE source_id=? ORDER BY file_path", (source_id,))]
                version_files = [{key: row[key] for key in ("file_path", "kind", "sha256")} for row in files]
                result["sources"].append({**context["source"], "input_version":
                    hashlib.sha256(_dump(version_files).encode("utf-8")).hexdigest()})
                result["files"].extend(files)
                for collection in ("sections", "nodes", "edges", "memberships"):
                    result[collection].extend(context[collection])
                appearances = {}
                for section in context["sections"]:
                    if not section["canonical_id"]:
                        continue
                    nodes = [node for node in context["nodes"] if node["section_id"] == section["section_id"]]
                    node_ids = {(node["canvas_path"], node["node_id"]) for node in nodes}
                    appearance = {key: section[key] for key in
                        ("section_id", "file_path", "label", "title", "description_md", "is_anchor", "canonical_id")}
                    appearance["nodes"] = [{"canvas_path": node["canvas_path"], "node_id": node["node_id"]} for node in nodes]
                    appearance["memberships"] = [member for member in context["memberships"]
                        if (member["canvas_path"], member["node_id"]) in node_ids]
                    appearance["edges"] = [edge for edge in context["edges"]
                        if any((edge["canvas_path"], edge[end]) in node_ids for end in ("from_node", "to_node"))]
                    appearances.setdefault(section["canonical_id"], []).append(appearance)
                rows = self.connection.execute("SELECT * FROM items WHERE source_id=? "
                    "ORDER BY section_id,preorder,item_id", (source_id,)).fetchall()
                for row in rows:
                    item = self._item_result(row, section_cache=section_cache)
                    item.update(ancestor_ids=json.loads(row["ancestor_ids_json"]),
                                revision=row["revision"], preorder=row["preorder"])
                    if row["item_type"] == "folder":
                        # Descendants are preserved as individual rows; avoid
                        # duplicating an entire nested tree at each ancestor.
                        item["raw_json"] = {key: value for key, value in item["raw_json"].items() if key != "children"}
                        result["folders"].append(item)
                        continue
                    original = row["url"]
                    if original not in by_url:
                        try:
                            retrieval = SourceArchive._key(original)
                        except (ValueError, UnicodeError):
                            retrieval = None
                        try:
                            scheme = urlsplit(original).scheme
                        except ValueError:
                            scheme = ""
                        by_url[original] = {"id": "u-" + hashlib.sha256(original.encode("utf-8")).hexdigest()[:32],
                            "original_url": original, "retrieval_url": retrieval,
                            "url_kind": "web" if retrieval else "local" if scheme == "file" else "unsupported",
                            "instances": []}
                    identity = [source_id, row["section_id"], row["item_id"]]
                    item.update(instance_id="b-" + hashlib.sha256(_dump(identity).encode("utf-8")).hexdigest()[:32],
                                canonical_section_id=row["section_id"],
                                appearances=appearances.get(row["section_id"], []))
                    by_url[original]["instances"].append(item)
            result["entries"] = sorted(by_url.values(), key=lambda row: row["id"])
            version = [{key: row[key] for key in ("source_id", "file_path", "kind", "sha256")}
                       for row in result["files"]]
            result["input_version"] = hashlib.sha256(_dump(version).encode("utf-8")).hexdigest()
            result["counts"] = {"unique_urls": len(result["entries"]),
                "bookmark_instances": sum(len(row["instances"]) for row in result["entries"]),
                **{key: len(result[key]) for key in ("sources", "files", "sections", "folders", "nodes", "edges", "memberships")}}
            return result
        finally:
            self.connection.execute("RELEASE SAVEPOINT inventory_snapshot")

    def input_version(self, source_ids):
        """Fingerprint the indexed input without rebuilding the full inventory."""
        records = []
        self.connection.execute("SAVEPOINT input_version_snapshot")
        try:
            for source_id in sorted(set(source_ids)):
                source_id = self.resolve_source_id(source_id)
                self._source(source_id)
                records.extend(dict(row) for row in self.connection.execute(
                    "SELECT source_id,file_path,kind,sha256 FROM files WHERE source_id=? ORDER BY file_path", (source_id,)))
            return hashlib.sha256(_dump(records).encode("utf-8")).hexdigest()
        finally:
            self.connection.execute("RELEASE SAVEPOINT input_version_snapshot")

    def status(self, source_id=None):
        if source_id is None:
            ids = [row[0] for row in self.connection.execute("SELECT source_id FROM sources ORDER BY source_id")]
            return {"database": str(self.db_path) if self.db_path else ":memory:", "schema_version": 1,
                "sources": [self.status(identifier) for identifier in ids]}
        requested_source_id = source_id
        source_id = self.resolve_source_id(source_id)
        result = self._source(source_id)
        counts = dict(self.connection.execute("""SELECT count(*) AS items,
            coalesce(sum(item_type='bookmark'),0) AS bookmarks,
            coalesce(sum(item_type='folder'),0) AS folders,
            coalesce(sum(item_type='folder' AND parent_id IS NULL AND title=''),0) AS tree_roots,
            count(DISTINCT CASE WHEN item_type='bookmark' THEN url END) AS unique_urls
            FROM items WHERE source_id=?""", (source_id,)).fetchone())
        # "folders" is the raw row count, which includes the synthetic tree
        # container; user_folders is what a person sees in the canvas.
        counts["user_folders"] = counts["folders"] - counts["tree_roots"]
        for table in ("sections", "files", "nodes", "edges", "memberships"):
            counts[table] = self.connection.execute("SELECT count(*) FROM " + table + " WHERE source_id=?", (source_id,)).fetchone()[0]
        result["counts"] = counts
        result.update(bookmarks=counts["bookmarks"], unique_urls=counts["unique_urls"])
        if requested_source_id != source_id:
            result["resolved_via_redirect"] = True
            result["requested_source_id"] = requested_source_id
        package = Path(result["package_path"])
        result["package_exists"] = package.is_dir()
        result["retained_missing_files"] = [row[0] for row in self.connection.execute("SELECT file_path FROM files WHERE source_id=? ORDER BY file_path", (source_id,)) if not (package / row[0]).is_file()]
        if result["retained_missing_files"]:
            # partial imports keep removed cards on purpose; say so at the top
            # level so the stale rows are not mistaken for current content.
            result["retained_missing_note"] = ("%d imported file(s) are no longer in the package and were kept because "
                "completeness=partial. Re-import with completeness=complete to reconcile the full mirror, or ignore "
                "them deliberately." % len(result["retained_missing_files"]))
        result["sections"] = [{"section_id": row["section_id"], "label": row["label"], "is_anchor": bool(row["is_anchor"]), "canonical_id": row["canonical_id"]} for row in self._sections(source_id)]
        return result
