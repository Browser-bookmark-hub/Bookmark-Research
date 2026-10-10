"""A rebuildable SQLite candidate index; revisions and evidence remain authoritative."""
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class WikiSearchIndex:
    # Explicit query aliases, not an assertion of semantic equivalence of pages.
    ALIASES = (("定价", "价格", "收费标准", "多少钱", "费用", "pricing", "price"),
               ("检索", "搜索", "search", "retrieval"),
               ("安装", "installation", "install"))

    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def normalize(text):
        return re.sub(r"\s+", "", text.casefold())

    @classmethod
    def terms(cls, query):
        return [list(next((group for group in cls.ALIASES if term in group), (term,)))
                for term in dict.fromkeys(query.casefold().split())]

    @classmethod
    def grams(cls, text):
        value = cls.normalize(text)
        return {"1" + char for char in value} | {"2" + value[i:i + 2] for i in range(len(value) - 1)}

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Wiki search index must not be a symlink")
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("CREATE TABLE IF NOT EXISTS documents (page_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, "
                               "title TEXT NOT NULL, body TEXT NOT NULL, aliases TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS postings (gram TEXT NOT NULL, page_id TEXT NOT NULL "
                               "REFERENCES documents(page_id) ON DELETE CASCADE, PRIMARY KEY(gram,page_id)) WITHOUT ROWID")
            connection.execute("CREATE INDEX IF NOT EXISTS postings_page ON postings(page_id)")
            connection.execute("CREATE TABLE IF NOT EXISTS dependencies (url TEXT NOT NULL, page_id TEXT NOT NULL "
                               "REFERENCES documents(page_id) ON DELETE CASCADE, PRIMARY KEY(url,page_id)) WITHOUT ROWID")
            connection.execute("CREATE TABLE IF NOT EXISTS links (target TEXT NOT NULL, page_id TEXT NOT NULL "
                               "REFERENCES documents(page_id) ON DELETE CASCADE, PRIMARY KEY(target,page_id)) WITHOUT ROWID")
            connection.execute("CREATE INDEX IF NOT EXISTS dependencies_page ON dependencies(page_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS links_page ON links(page_id)")
            with connection:
                if connection.execute("PRAGMA user_version").fetchone()[0] == 0:
                    connection.execute("DELETE FROM documents")
                    connection.execute("PRAGMA user_version=1")
                yield connection
        finally:
            connection.close()

    @staticmethod
    def row(page_id, pointer, record):
        page = record["page"]
        body = "\n\n".join(section["heading"] + "\n" + section["text"] for section in page["sections"])
        aliases = "\n".join(page.get("aliases", []))
        return {"page_id": page_id, "sha256": pointer["sha256"], "title": page["title"], "body": body, "aliases": aliases}

    def _put(self, connection, page_id, pointer, record):
        from archive import SourceArchive
        row = self.row(page_id, pointer, record)
        connection.execute("DELETE FROM documents WHERE page_id=?", (page_id,))
        connection.execute("INSERT INTO documents VALUES (?,?,?,?,?)",
                           tuple(row[key] for key in ("page_id", "sha256", "title", "body", "aliases")))
        connection.executemany("INSERT INTO postings VALUES (?,?)",
                               ((gram, page_id) for gram in self.grams(row["title"] + "\n" + row["body"] + "\n" + row["aliases"])))
        urls = {SourceArchive._key(citation["url"]) for evidence in record["evidence"]
                for citation in evidence["citations"]
                if (citation.get("provenance") or {}).get("kind") not in ("local_document", "external_report")}
        connection.executemany("INSERT INTO dependencies VALUES (?,?)", ((url, page_id) for url in sorted(urls)))
        connection.executemany("INSERT INTO links VALUES (?,?)",
                               ((link["page_id"], page_id) for link in record["resolved_links"]))

    def update(self, page_id, pointer, record):
        with self.connection() as connection:
            self._put(connection, page_id, pointer, record)

    def _sync(self, connection, index, load_revision):
        invalid = []
        existing = dict(connection.execute("SELECT page_id,sha256 FROM documents"))
        for page_id in existing.keys() - index["pages"].keys():
            connection.execute("DELETE FROM documents WHERE page_id=?", (page_id,))
        for page_id, pointer in index["pages"].items():
            if existing.get(page_id) == pointer["sha256"]:
                continue
            try:
                record = load_revision(pointer)
            except (OSError, ValueError, KeyError, TypeError):
                invalid.append(page_id)
                connection.execute("DELETE FROM documents WHERE page_id=?", (page_id,))
                continue
            self._put(connection, page_id, pointer, record)
        return invalid

    def affected(self, index, load_revision, urls):
        with self.connection() as connection:
            invalid = self._sync(connection, index, load_revision)
            direct = {row[0] for url in urls for row in connection.execute(
                "SELECT page_id FROM dependencies WHERE url=?", (url,))}
            affected, pending = set(direct), list(direct)
            while pending:
                target = pending.pop()
                for row in connection.execute("SELECT page_id FROM links WHERE target=?", (target,)):
                    if row[0] not in affected:
                        affected.add(row[0])
                        pending.append(row[0])
        return {"direct_page_ids": sorted(direct), "page_ids": sorted(affected), "unreadable_page_ids": invalid}

    def candidates(self, index, load_revision, groups):
        with self.connection() as connection:
            invalid = self._sync(connection, index, load_revision)
            candidates = None
            for variants in groups:
                possible = set()
                for variant in variants:
                    normalized = self.normalize(variant)
                    grams = sorted(self.grams(normalized))
                    # A bounded subset is a safe superset filter. Full literal
                    # matching below still decides whether a document matches.
                    grams = [g for g in grams if g.startswith("2")] or grams
                    grams = grams[:128]
                    if not grams:
                        continue
                    placeholders = ",".join("?" for _ in grams)
                    possible.update(row[0] for row in connection.execute(
                        "SELECT page_id FROM postings WHERE gram IN (" + placeholders + ") "
                        "GROUP BY page_id HAVING count(*)=?", (*grams, len(grams))))
                candidates = possible if candidates is None else candidates & possible
                if not candidates:
                    break
            rows = [dict(connection.execute("SELECT * FROM documents WHERE page_id=?", (page_id,)).fetchone())
                    for page_id in sorted(candidates or ())]
        return rows, invalid

    @classmethod
    def match(cls, row, query, groups):
        text = (row["title"] + "\n" + row["body"] + "\n" + row["aliases"]).casefold()
        squashed = cls.normalize(text)
        terms = list(dict.fromkeys(query.casefold().split()))
        literal = all(term in text for term in terms)
        spacing = all(cls.normalize(term) in squashed for term in terms)
        chosen = [next((variant for variant in variants if cls.normalize(variant) in squashed), None)
                  for variants in groups]
        if not all(chosen):
            return None
        rank = sum(min(text.count(term), 20) + (5 if term in row["title"].casefold() else 0)
                   for term in chosen) + (10 if literal or spacing else 0)
        positions = [row["body"].casefold().find(term) for term in chosen if term in row["body"].casefold()]
        begin = max(0, min(positions, default=0) - 60)
        return {"rank": rank, "snippet": row["body"][begin:begin + 500],
                "whitespace_insensitive": bool(spacing and not literal),
                "alias_expanded": not (literal or spacing)}
