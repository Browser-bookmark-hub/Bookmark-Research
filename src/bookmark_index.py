"""Read-only Bookmark Canvas package ingestion and a persistent SQL query API.

Only the derived database is written. JSON/Canvas remains the source of truth.
Absent section files are retained; a supplied canvas replaces the previous entry.
"""

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


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


def _reference(reference):
    """Resolve the protocol directory suffix, not the referring file's parent.

    The vault root is external to an exported/moved package. Retaining the full
    protocol suffix accommodates its vault prefix without reading outside it.
    """
    _string(reference, "vault-relative reference", True)
    parts = PurePosixPath(reference).parts
    if reference.startswith(("/", "\\")) or "\\" in reference or ".." in parts:
        raise ValueError("Unsafe vault reference: " + reference)
    if parts and ":" in parts[0]:
        raise ValueError("Absolute/URI references are not package files")
    for index, part in enumerate(parts):
        if part in ("永久栏目", "临时栏目"):
            relative = PurePosixPath(*parts[index:])
            if relative.suffix != ".json":
                break
            return str(relative)
    raise ValueError("Reference must name an internal section JSON: " + reference)


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 source_id TEXT PRIMARY KEY, package_path TEXT NOT NULL,
 created_at TEXT NOT NULL, last_sync TEXT NOT NULL
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
 raw_json TEXT NOT NULL, metadata_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 UNIQUE(source_id,section_id,item_id),
 FOREIGN KEY(source_id,section_id) REFERENCES sections(source_id,section_id)
);
CREATE INDEX IF NOT EXISTS items_parent ON items(source_id,section_id,parent_id);
CREATE INDEX IF NOT EXISTS items_url ON items(source_id,url);
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
PRAGMA user_version=1;
"""


class BookmarkIndex:
    def __init__(self, db_path):
        self.db_path = None if str(db_path) == ":memory:" else Path(db_path).expanduser().resolve()
        if self.db_path is not None:
            # Refuse before connecting, so even an accidentally chosen package
            # path does not acquire an empty database, journal or WAL file.
            for parent in self.db_path.parents:
                if ((parent / "永久栏目").is_dir() or (parent / "临时栏目").is_dir()
                        or any(parent.glob("*.canvas"))):
                    raise ValueError("Database must be outside imported package directories")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.db_path) if self.db_path else ":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.close()
            raise ValueError("Unsupported bookmark index schema version: %s" % version)
        try:
            self.connection.executescript(SCHEMA)
        except Exception:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _source(self, source_id):
        row = self.connection.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown source_id: " + str(source_id))
        return dict(row)

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
    def _section(file_path, obj):
        if obj.get("format") != "bookmark-canvas-section":
            raise ValueError("Not a Bookmark Canvas section: " + file_path)
        section_type = obj.get("sectionType")
        if section_type not in ("permanent", "temporary"):
            raise ValueError("Unknown sectionType in " + file_path)
        expected = "永久栏目/" if section_type == "permanent" else "临时栏目/"
        if not file_path.startswith(expected):
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
            section_id = obj.get("id")
            label = obj.get("label", "unknown")
        _string(section_id, "section id", True)
        _string(label, "section label", True)
        return section_id, {
            "file_path": file_path, "section_type": section_type, "label": label,
            "slot": slot, "title": _string(obj.get("title", ""), "section title"),
            "description_md": _string(obj.get("descriptionMd", ""), "descriptionMd"),
            "is_anchor": int(anchor), "inherit_path": _reference(obj.get("inheritFrom")) if anchor else None,
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
                item_id = _string(node.get("id"), "item id", True)
                if item_id in seen:
                    raise ValueError("Duplicate item id in section: " + item_id)
                seen.add(item_id)
                if permanent and "parentId" in node and node["parentId"] != parent_id:
                    raise ValueError("parentId disagrees with tree position: " + item_id)
                if not permanent and node.get("sectionId", section_id) != section_id:
                    raise ValueError("Temporary item sectionId mismatch: " + item_id)
                title = _string(node.get("title", ""), "item title")
                url = _string(node.get("url", ""), "item URL")
                item_type = ("bookmark" if url else "folder") if permanent else node.get("type")
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
                result.append((item_id, {
                    "parent_id": parent_id, "item_type": item_type, "position": position,
                    "preorder": len(result), "title": title, "url": url, "note": note,
                    "note_color": note_color, "tags_json": _dump(normalized),
                    "tag_text": "\n".join(tag["text"] for tag in normalized),
                    "path_json": _dump(list(titles)), "folder_path": " / ".join(titles),
                    "ancestor_ids_json": _dump(list(ancestor_ids)),
                    # Full child arrays also survive in files/sections.raw_json.
                    "raw_json": _dump({key: value for key, value in node.items() if key != "children"}),
                    "metadata_json": _dump(item_meta if permanent else {key: node[key] for key in ("tags", "note", "noteColor") if key in node}),
                }))
                visit(children, item_id, titles + ((title,) if title else ()), ancestor_ids + (item_id,))

        visit(roots)
        return result

    @staticmethod
    def _canvas(obj):
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
                file_path=_reference(node.get("file")) if node_type == "file" else None,
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

    def sync(self, package_path, source_id=None):
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
        for directory in ("永久栏目", "临时栏目"):
            paths.extend((package / directory).rglob("*.json"))
        paths = sorted(paths)
        if not paths:
            raise ValueError("No protocol JSON or .canvas files in package")
        old_files = {row["file_path"]: dict(row) for row in self.connection.execute(
            "SELECT * FROM files WHERE source_id=?", (source_id,))}
        indexed_section_files = {row[0] for row in self.connection.execute(
            "SELECT file_path FROM sections WHERE source_id=?", (source_id,))}
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
                    parsed = self._canvas(obj)
                else:
                    section_id, section = self._section(relative, obj)
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
        with self.connection:
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

    def _scope(self, source_id, section=None, group_id=None, folder_id=None, tags=None):
        self._source(source_id)
        clauses, args = ["i.source_id=?", "i.item_type='bookmark'"], [source_id]
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
        return clauses, args

    @staticmethod
    def _match(target):
        # LIKE provides a literal substring fallback for Chinese short names.
        # Escape all SQL wildcard characters; FTS query syntax is not exposed.
        escaped = target.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        fields = ("title", "url", "note", "tag_text", "folder_path")
        return "(" + " OR ".join("i.%s LIKE ? ESCAPE '\\'" % field for field in fields) + ")", ["%" + escaped + "%"] * len(fields)

    def _item_result(self, row):
        result = {key: row[key] for key in ("source_id", "section_id", "item_id", "parent_id", "item_type", "title", "url", "note", "note_color", "position")}
        result.update(source=row["source_id"], section=row["section_id"], item=row["item_id"],
            path=json.loads(row["path_json"]), folder_path=row["folder_path"], tags=json.loads(row["tags_json"]),
            raw_json=json.loads(row["raw_json"]), metadata=json.loads(row["metadata_json"]))
        section = self.connection.execute("SELECT label,file_path FROM sections WHERE source_id=? AND section_id=?", (row["source_id"], row["section_id"])).fetchone()
        result["section_label"], result["file_path"] = section[0], section[1]
        return result

    def search(self, source_id, targets=None, section=None, group_id=None, folder_id=None, tags=None, limit=20, offset=0):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if isinstance(targets, str) or isinstance(tags, str):
            raise ValueError("targets and tags must be lists of strings")
        targets = list(dict.fromkeys(targets or []))
        if len(targets) > 100:
            raise ValueError("At most 100 targets per request")
        for target in targets:
            _string(target, "target", True)
        clauses, args = self._scope(source_id, section, group_id, folder_id, tags)

        def query(chosen):
            predicates, parameters = list(clauses), list(args)
            if chosen:
                matches = [self._match(target) for target in chosen]
                predicates.append("(" + " OR ".join(match[0] for match in matches) + ")")
                parameters.extend(value for _, values in matches for value in values)
            where = " AND ".join(predicates)
            total = self.connection.execute("SELECT count(*) FROM items i WHERE " + where, parameters).fetchone()[0]
            rows = self.connection.execute("SELECT i.* FROM items i WHERE " + where + " ORDER BY i.section_id,i.preorder,i.item_id LIMIT ? OFFSET ?", parameters + [limit, offset]).fetchall()
            return {"total": total, "limit": limit, "offset": offset, "results": [self._item_result(row) for row in rows]}

        result = query(targets)
        result.update(source_id=source_id, query_scope={"section": section, "group_id": group_id, "folder_id": folder_id, "tags": list(tags or [])},
            match_mode="literal_substring", searched_fields=["title", "url", "note", "tags.text", "folder_path"])
        result["targets"] = [dict(target=target, **query([target])) for target in targets]
        return result

    def context(self, source_id, section=None, group_id=None, item_id=None):
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
            section_results.append(entry)
        items = [self._item_result(row) for row in item_rows]
        for item, row in zip(items, item_rows):
            item["ancestors"] = []
            for ancestor in json.loads(row["ancestor_ids_json"]):
                ancestor_row = self.connection.execute("SELECT * FROM items WHERE source_id=? AND section_id=? AND item_id=?", (source_id, row["section_id"], ancestor)).fetchone()
                if ancestor_row:
                    item["ancestors"].append(self._item_result(ancestor_row))
        return {"source_id": source_id, "source": source, "sections": section_results,
            "items": items, "nodes": nodes, "groups": [node for node in nodes if node["node_type"] == "group"],
            "edges": edges, "related_nodes": related_nodes, "memberships": memberships}

    def status(self, source_id=None):
        if source_id is None:
            ids = [row[0] for row in self.connection.execute("SELECT source_id FROM sources ORDER BY source_id")]
            return {"database": str(self.db_path) if self.db_path else ":memory:", "schema_version": 1,
                "sources": [self.status(identifier) for identifier in ids]}
        result = self._source(source_id)
        counts = dict(self.connection.execute("""SELECT count(*) AS items,
            coalesce(sum(item_type='bookmark'),0) AS bookmarks,
            coalesce(sum(item_type='folder'),0) AS folders,
            count(DISTINCT CASE WHEN item_type='bookmark' THEN url END) AS unique_urls
            FROM items WHERE source_id=?""", (source_id,)).fetchone())
        for table in ("sections", "files", "nodes", "edges", "memberships"):
            counts[table] = self.connection.execute("SELECT count(*) FROM " + table + " WHERE source_id=?", (source_id,)).fetchone()[0]
        result["counts"] = counts
        result.update(bookmarks=counts["bookmarks"], unique_urls=counts["unique_urls"])
        package = Path(result["package_path"])
        result["package_exists"] = package.is_dir()
        result["retained_missing_files"] = [row[0] for row in self.connection.execute("SELECT file_path FROM files WHERE source_id=? ORDER BY file_path", (source_id,)) if not (package / row[0]).is_file()]
        result["sections"] = [{"section_id": row["section_id"], "label": row["label"], "is_anchor": bool(row["is_anchor"]), "canonical_id": row["canonical_id"]} for row in self._sections(source_id)]
        return result
