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
    def terms(cls, query, extra_aliases=None):
        alias_groups = list(cls.ALIASES)
        if extra_aliases:
            for group in extra_aliases:
                if isinstance(group, (list, tuple)):
                    cleaned = tuple(dict.fromkeys(str(term).strip() for term in group if str(term).strip()))
                    if cleaned and cleaned not in alias_groups:
                        alias_groups.append(cleaned)
        return [list(next((group for group in alias_groups if term in group), (term,)))
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
                               "title TEXT NOT NULL, body TEXT NOT NULL, aliases TEXT NOT NULL, headings TEXT NOT NULL DEFAULT '')")
            cols = {col[1] for col in connection.execute("PRAGMA table_info(documents)").fetchall()}
            if "headings" not in cols:
                connection.execute("ALTER TABLE documents ADD COLUMN headings TEXT NOT NULL DEFAULT ''")
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
        headings = "\n".join(section["heading"] for section in page.get("sections", []))
        body = "\n\n".join(section["heading"] + "\n" + section["text"] for section in page["sections"])
        aliases = "\n".join(page.get("aliases", []))
        return {"page_id": page_id, "sha256": pointer["sha256"], "title": page["title"],
                "body": body, "aliases": aliases, "headings": headings}

    def _put(self, connection, page_id, pointer, record):
        from archive import SourceArchive
        row = self.row(page_id, pointer, record)
        connection.execute("DELETE FROM documents WHERE page_id=?", (page_id,))
        connection.execute("INSERT INTO documents (page_id, sha256, title, body, aliases, headings) VALUES (?,?,?,?,?,?)",
                           tuple(row[key] for key in ("page_id", "sha256", "title", "body", "aliases", "headings")))
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

    def detect_duplicates(self, index, load_revision, page_id, title, urls):
        with self.connection() as connection:
            self._sync(connection, index, load_revision)
            rows = connection.execute("SELECT page_id, title FROM documents WHERE page_id != ?", (page_id,)).fetchall()
            url_matches = {}
            for url in (urls or ()):
                for row in connection.execute("SELECT page_id FROM dependencies WHERE url=? AND page_id != ?", (url, page_id)):
                    url_matches.setdefault(row[0], set()).add(url)
            norm_new = self.normalize(title) if title else ""
            tokens_new = set(re.findall(r"\w+", title.lower())) if title else set()
            duplicates = []
            for row in rows:
                other_id, other_title = row["page_id"], row["title"]
                reasons = []
                matched_urls = sorted(url_matches.get(other_id, set()))
                if matched_urls:
                    reasons.append("overlapping_urls")
                norm_other = self.normalize(other_title) if other_title else ""
                tokens_other = set(re.findall(r"\w+", other_title.lower())) if other_title else set()
                similar_title = False
                if norm_new and norm_other:
                    if norm_new == norm_other:
                        similar_title = True
                    elif (norm_new in norm_other or norm_other in norm_new) and min(len(norm_new), len(norm_other)) >= 4:
                        similar_title = True
                    elif tokens_new and tokens_other:
                        union = tokens_new | tokens_other
                        if union and (len(tokens_new & tokens_other) / len(union)) >= 0.7:
                            similar_title = True
                if similar_title:
                    reasons.append("similar_title")
                if reasons:
                    duplicates.append({
                        "page_id": other_id,
                        "title": other_title,
                        "reasons": reasons,
                        "overlapping_urls": matched_urls,
                        "candidate_merge_target": other_id,
                        "suggestion": f"Consider reviewing or merging with existing Wiki page '{other_id}' ({other_title})."
                    })
            return duplicates

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
    def match(cls, row, query, groups, doc_freq=None):
        text = (row["title"] + "\n" + row["body"] + "\n" + row["aliases"]).casefold()
        squashed = cls.normalize(text)
        terms = list(dict.fromkeys(query.casefold().split()))
        literal = all(term in text for term in terms)
        spacing = all(cls.normalize(term) in squashed for term in terms)
        chosen = [next((variant for variant in variants if cls.normalize(variant) in squashed), None)
                  for variants in groups]
        if not all(chosen):
            return None
        headings = row.get("headings", "").casefold()
        rank = sum(
            (min(text.count(term), 20) + (15 if term in row["title"].casefold() else 0) + (8 if term in headings else 0))
            * (float(max(1, len(term))) / max(1, doc_freq.get(term, 1)) if doc_freq else 1.0)
            for term in chosen
        ) + (10 if literal or spacing else 0)
        positions = [row["body"].casefold().find(term) for term in chosen if term in row["body"].casefold()]
        begin = max(0, min(positions, default=0) - 60)
        return {"rank": rank, "snippet": row["body"][begin:begin + 500],
                "whitespace_insensitive": bool(spacing and not literal),
                "alias_expanded": not (literal or spacing)}
