"""Plan and audit incremental Wiki compilation without writing pages.

The plugin has no model, so a compile run cannot author prose. This module does
the deterministic half: resolve a scope, drop noise, cluster folders, report
which items the current Wiki already covers, and name the pages a cluster would
touch. The host reads the plan, writes or merges pages with the existing gates,
then asks for status again; status is recomputed from committed revisions.
"""

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone

from archive import SourceArchive
from junk import is_junk
from research import ResearchSessions
from settings import Settings
from url_classify import is_search_result_url


class WikiCompile:
    SCHEMA_VERSION = 1
    MAX_ITEMS = 20000
    PAGE_SIZE = 2000
    MAX_NOTE = 400

    def __init__(self, index, wiki, settings=None):
        self.index = index
        self.wiki = wiki
        self.settings = settings

    def _require_enabled(self):
        if not self.wiki.enabled():
            raise ValueError("Wiki is disabled; enable wiki.enabled in settings to plan a compile")

    # ------------------------------------------------------------------ plan

    def run(self, action, **options):
        allowed = {
            "plan": ("source_id", "section", "folder_id", "tags", "query", "max_pages",
                     "min_cluster_size", "max_items_per_cluster", "include_covered"),
            "status": ("plan_id",),
            "gap": ("plan_id", "urls", "reason", "provider"),
        }
        required = {"plan": ("source_id",), "status": ("plan_id",),
                    "gap": ("plan_id", "urls", "reason")}
        if action not in allowed:
            raise ValueError("action must be plan, status or gap")
        extra = set(options) - set(allowed[action])
        if extra:
            raise ValueError("Unsupported fields for this action: " + ", ".join(sorted(extra)))
        missing = [field for field in required[action] if options.get(field) in (None, "", [])]
        if missing:
            raise ValueError("Missing required fields: " + ", ".join(missing))
        return getattr(self, action)(**options)

    def plan(self, source_id, section=None, folder_id=None, tags=None, query=None,
             max_pages=12, min_cluster_size=3, max_items_per_cluster=40,
             include_covered=False):
        self._require_enabled()
        source_id = self._identifier(source_id, "source_id")
        section = self._optional_text(section, "section", 300)
        folder_id = self._optional_text(folder_id, "folder_id", 300)
        query = self._optional_text(query, "query", 2000)
        tags = self._names(tags, "tags")
        max_pages = self._integer(max_pages, "max_pages", 1, 50)
        min_cluster_size = self._integer(min_cluster_size, "min_cluster_size", 1, 100)
        max_items_per_cluster = self._integer(max_items_per_cluster, "max_items_per_cluster", 1, 200)
        if type(include_covered) is not bool:
            raise ValueError("include_covered must be a boolean")

        source_version = self.index.input_version([source_id])
        items, excluded = self._collect(source_id, section, folder_id, tags, query)
        view = self._wiki_view()
        wiki_urls = set()
        for page in view.values():
            wiki_urls.update(page["urls"])
        for item in items:
            item["covered"] = item["key"] in wiki_urls

        root = self._tree(items)
        clusters, deferred = self._clusters(root, max_pages, max_items_per_cluster)
        clusters, deferred_small = self._merge_small(clusters, min_cluster_size, max_pages)
        for key, value in deferred_small.items():
            if key == "items":
                deferred["items"] = deferred.get("items", 0) + value
            elif key == "clusters":
                deferred["clusters"] = deferred.get("clusters", 0) + value
            elif key == "folders":
                deferred.setdefault("folders", []).extend(value)

        built = []
        for node in clusters:
            cluster = self._build_cluster(node, view, wiki_urls, max_items_per_cluster,
                                          include_covered)
            if cluster is not None:
                built.append(cluster)
        built.sort(key=lambda row: (-row["item_count"], row["folder_path"], row["title"]))

        basis = {
            "source_version": source_version,
            "wiki_pages": {page_id: page["revision"] for page_id, page in sorted(view.items())},
            "items": len(items),
            "unique_urls": len({item["key"] for item in items}),
        }
        identification = {
            "source_id": source_id, "section": section, "folder_id": folder_id,
            "tags": tags, "query": query, "max_pages": max_pages,
            "min_cluster_size": min_cluster_size,
            "max_items_per_cluster": max_items_per_cluster,
            "include_covered": include_covered,
            "source_version": source_version,
        }
        plan_id = hashlib.sha256(self._dump(identification).encode("utf-8")).hexdigest()[:16]
        plan = {
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": plan_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_id": source_id,
            "scope": {"section": section, "folder_id": folder_id, "tags": tags, "query": query},
            "budget": {"max_pages": max_pages, "min_cluster_size": min_cluster_size,
                       "max_items_per_cluster": max_items_per_cluster,
                       "include_covered": include_covered},
            "basis": basis,
            "summary": {
                "clusters": len(built),
                "items": len(items),
                "new_items": sum(1 for item in items if not item["covered"]),
                "covered_items": sum(1 for item in items if item["covered"]),
                "excluded": dict(sorted(excluded.items())),
                "pages": len(view),
                "deferred": deferred,
            },
            "excluded": dict(sorted(excluded.items())),
            "deferred": deferred,
            "clusters": built,
            "instruction": ("For each cluster, read its planned items and write or merge one page "
                            "with save(expected_revision=...); then run wiki_compile status. This "
                            "plan starts no fetch and writes no page."),
            "boundary": "Deterministic planning and coverage only; semantic synthesis stays with the host.",
        }
        path = self._path(plan_id)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            existing["reused"] = True
            return existing
        ResearchSessions._write(path, json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
        plan["reused"] = False
        return plan

    def gap(self, plan_id, urls, reason, provider=None):
        """Record planned URLs that were attempted but could not be read.

        A gap is not evidence and never covers an item; it only keeps status
        honest by separating "not attempted" from "attempted and unavailable".
        """
        self._require_enabled()
        plan_id = self._plan_id(plan_id)
        self._load_plan(plan_id)
        urls = self._urls(urls)
        reason = self._text(reason, "reason", 1000)
        provider = self._optional_text(provider, "provider", 100)
        path = self._gaps_path(plan_id)
        with Settings._update_lock(path):
            data = self._gaps(path, plan_id)
            stamp = datetime.now(timezone.utc).isoformat()
            for url in urls:
                data["gaps"][self._key(url)] = {
                    "url": url, "reason": reason, "provider": provider, "recorded_at": stamp}
            ResearchSessions._write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return {"plan_id": plan_id, "recorded": len(urls), "gap_urls": len(data["gaps"]),
                "file": str(path)}

    # ---------------------------------------------------------------- status

    def status(self, plan_id):
        self._require_enabled()
        plan_id = self._plan_id(plan_id)
        path = self._path(plan_id)
        if not path.is_file():
            raise ValueError("Unknown Wiki compile plan: " + plan_id)
        plan = json.loads(path.read_text(encoding="utf-8"))
        gaps = self._gaps(self._gaps_path(plan_id), plan_id)["gaps"]
        view = self._wiki_view()
        wiki_urls = set()
        for page in view.values():
            wiki_urls.update(page["urls"])
        clusters, covered_total, planned_total, gap_total = [], 0, 0, 0
        matched = set()
        pages = set()
        for cluster in plan.get("clusters", []):
            covered, gap_items, gap_rows = 0, 0, []
            direct = set()
            for item in cluster.get("items", []):
                try:
                    key = self._key(item.get("url", ""))
                except (TypeError, ValueError):
                    key = None
                if not key:
                    continue
                matched.add(key)
                if key in wiki_urls:
                    covered += 1
                    direct.update(self._direct_pages(view, {key}))
                elif key in gaps:
                    gap_items += 1
                    if len(gap_rows) < 5:
                        gap_rows.append({"url": gaps[key].get("url", item.get("url")),
                                         "reason": gaps[key].get("reason")})
            affected = self._affected_pages(view, direct)
            pages.update(affected)
            planned_total += len(cluster.get("items", []))
            covered_total += covered
            gap_total += gap_items
            clusters.append({
                "cluster_id": cluster["cluster_id"],
                "title": cluster["title"],
                "page_id_hint": cluster["page_id_hint"],
                "item_count": cluster["item_count"],
                "planned_items": len(cluster.get("items", [])),
                "covered_items": covered,
                "gap_items": gap_items,
                "pending_items": len(cluster.get("items", [])) - covered - gap_items,
                "gaps": gap_rows,
                "pages": [{"page_id": page_id, **{key: view[page_id][key]
                                                   for key in ("title", "revision")}}
                          for page_id in sorted(affected)],
            })
        try:
            source_version = self.index.input_version([plan["source_id"]])
        except (OSError, ValueError, KeyError):
            source_version = None
        return {
            "plan_id": plan_id,
            "created_at": plan.get("created_at"),
            "source_id": plan.get("source_id"),
            "scope": plan.get("scope"),
            "source_changed": (source_version is not None
                               and source_version != plan.get("basis", {}).get("source_version")),
            "clusters": clusters,
            "summary": {
                "clusters": len(clusters),
                "planned_items": planned_total,
                "covered_items": covered_total,
                "gap_items": gap_total,
                "pending_items": planned_total - covered_total - gap_total,
                "gap_urls": len(gaps),
                "unmatched_gaps": len(set(gaps) - matched),
                "coverage_basis": "planned_items (each cluster capped at max_items_per_cluster)",
                "pages": len(pages),
            },
            "next_action": ("Write or merge the pending clusters with save, then run status again. "
                            "Record unreadable planned URLs with action=gap so they stop looking pending; "
                            "a cluster with pending_items=0 may still need review."
                            if planned_total - covered_total - gap_total else
                            "All planned items are covered or recorded as gaps; run wiki_lint for freshness."),
            "plan_file": str(path),
            "boundary": "Coverage is URL-based against current revisions; it is not a semantic review.",
        }

    # ------------------------------------------------------------ internals

    def _collect(self, source_id, section, folder_id, tags, query):
        rows, excluded, offset = [], Counter(), 0
        while offset < self.MAX_ITEMS:
            page = self.index.bookmark_rows(source_id, section=section, folder_id=folder_id,
                                            tags=tags, limit=self.PAGE_SIZE, offset=offset)
            rows.extend(page)
            if len(page) < self.PAGE_SIZE:
                break
            offset += self.PAGE_SIZE
        items, seen = [], {}
        for row in rows:
            url = " ".join((row.get("url") or "").split())
            if not url:
                excluded["empty_url"] += 1
                continue
            if is_search_result_url(url):
                excluded["search_page"] += 1
                continue
            if is_junk(row.get("title", ""), url):
                excluded["junk"] += 1
                continue
            haystack = " ".join((row.get("title", ""), row.get("note", ""), url,
                                 row.get("folder_path", ""))).casefold()
            if query and query.casefold() not in haystack:
                excluded["query_miss"] += 1
                continue
            try:
                key = self._key(url)
            except (TypeError, ValueError):
                excluded["invalid_url"] += 1
                continue
            if key in seen:
                seen[key]["copies"] += 1
                excluded["duplicate_url"] += 1
                continue
            item = {"section_id": row.get("section_id"), "item_id": row.get("item_id"),
                    "title": row.get("title", ""), "url": url, "key": key,
                    "note": (row.get("note") or "")[:self.MAX_NOTE],
                    "folder_path": row.get("folder_path", ""),
                    "tags": row.get("tags", []), "added_at": row.get("added_at"),
                    "copies": 1, "covered": False}
            seen[key] = item
            items.append(item)
        return items, excluded

    def _tree(self, items):
        root = {"segment": "", "path": "", "children": {}, "items": []}
        for item in items:
            node = root
            path = []
            for segment in [part.strip() for part in (item["folder_path"] or "").split("/") if part.strip()]:
                path.append(segment)
                node = node["children"].setdefault(
                    segment, {"segment": segment, "path": "/".join(path),
                              "children": {}, "items": []})
            node["items"].append(item)
        return root

    def _size(self, node):
        return len(node["items"]) + sum(self._size(child) for child in node["children"].values())

    def _clusters(self, root, max_pages, max_items):
        """Choose the largest folder leaves that fit the page budget.

        A folder larger than the item budget is split into its children (and a
        leaf for its directly attached items) until each leaf fits. The largest
        leaves are kept; the rest are deferred instead of being merged into one
        unreadable bucket. A folder whose only child holds every item is a
        wrapper, not a topic, so it is unwrapped first.
        """
        leaves = []

        def visit(node):
            size = self._size(node)
            if not size:
                return
            if size <= max_items or not node["children"]:
                leaves.append(node)
                return
            if node["items"]:
                leaves.append({"segment": node["segment"] or "Direct items",
                               "path": node["path"], "children": {}, "items": node["items"]})
            for child in node["children"].values():
                visit(self._unwrap(child))

        for node in root["children"].values():
            visit(self._unwrap(node))
        if root["items"]:
            leaves.append({"segment": "Unfiled", "path": "", "children": {}, "items": root["items"]})
        unique = list({id(node): node for node in leaves}.values())
        unique.sort(key=lambda node: (-self._size(node), node["path"], node["segment"]))
        return unique[:max_pages], self._deferred(unique[max_pages:])

    def _unwrap(self, node):
        while not node["items"] and len(node["children"]) == 1:
            node = next(iter(node["children"].values()))
        return node

    def _deferred(self, nodes):
        if not nodes:
            return {}
        folders = [(node["path"] or node["segment"]) for node in nodes if (node["path"] or node["segment"])]
        return {"clusters": len(nodes), "items": sum(self._size(node) for node in nodes),
                "folders": folders[:50]}

    def _merge_small(self, clusters, min_size, max_pages):
        if not clusters:
            return [], {}
        big = [node for node in clusters if self._size(node) >= min_size]
        small = [node for node in clusters if self._size(node) < min_size]
        if not small:
            return clusters, {}
        if not big:
            return [{"segment": "Other folders", "path": "", "children": {},
                     "items": [item for node in small for item in self._flatten(node)]}], {}
        if len(big) < max_pages:
            big.append({"segment": "Other folders", "path": "", "children": {},
                        "items": [item for node in small for item in self._flatten(node)]})
            return big, {}
        return big, self._deferred(small)

    def _flatten(self, node):
        items = list(node["items"])
        for child in node["children"].values():
            items.extend(self._flatten(child))
        return items

    def _build_cluster(self, node, view, wiki_urls, max_items, include_covered):
        items = self._flatten(node)
        items.sort(key=lambda item: (0 if item["note"] else 1, item["copies"],
                                     -self._stamp(item.get("added_at")),
                                     item["title"] or item["url"]))
        new_items = [item for item in items if not item["covered"]]
        if not include_covered and not new_items:
            return None
        chosen = (items if include_covered else new_items)[:max_items]
        keys = {item["key"] for item in items}
        direct = self._direct_pages(view, keys)
        affected = self._affected_pages(view, direct)
        title = node["segment"] or "Unfiled"
        existing = self._matching_pages(view, title, node["path"])
        return {
            "cluster_id": hashlib.sha256((node["path"] or title).encode("utf-8")).hexdigest()[:12],
            "title": title,
            "folder_path": node["path"],
            "page_id_hint": self._slug(title),
            "item_count": len(items),
            "new_items": len(new_items),
            "covered_items": len(items) - len(new_items),
            "truncated": len(chosen) < (len(items) if include_covered else len(new_items)),
            "remaining_items": max(0, (len(items) if include_covered else len(new_items)) - len(chosen)),
            "items": [self._item_row(item) for item in chosen],
            "existing_pages": [{"page_id": page_id, "title": view[page_id]["title"],
                                "revision": view[page_id]["revision"]} for page_id in sorted(existing)],
            "affected_pages": [{"page_id": page_id, "title": view[page_id]["title"],
                                "revision": view[page_id]["revision"]} for page_id in sorted(affected)],
        }

    def _item_row(self, item):
        return {"section_id": item["section_id"], "item_id": item["item_id"],
                "title": item["title"], "url": item["url"], "note": item["note"],
                "folder_path": item["folder_path"], "tags": item["tags"],
                "added_at": item.get("added_at"), "copies": item["copies"]}

    def _wiki_view(self):
        index = self.wiki._index()
        view = {}
        for page_id, pointer in index["pages"].items():
            try:
                record = self.wiki._revision(pointer)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            urls = set()
            for evidence in record.get("evidence", []):
                for citation in evidence.get("citations", []):
                    try:
                        urls.add(self._key(citation.get("url", "")))
                    except (TypeError, ValueError):
                        continue
            view[page_id] = {
                "page_id": page_id,
                "title": record.get("page", {}).get("title", ""),
                "kind": record.get("page", {}).get("kind", ""),
                "aliases": record.get("page", {}).get("aliases", []),
                "revision": pointer["revision"],
                "urls": urls,
                "links": [link.get("page_id") for link in record.get("resolved_links", [])],
            }
        return view

    def _direct_pages(self, view, keys):
        return {page_id for page_id, page in view.items() if page["urls"] & keys}

    def _affected_pages(self, view, page_ids):
        incoming = {}
        for page_id, page in view.items():
            for target in page["links"]:
                incoming.setdefault(target, set()).add(page_id)
        affected, pending = set(page_ids), list(page_ids)
        while pending:
            for page_id in incoming.get(pending.pop(), ()):
                if page_id not in affected:
                    affected.add(page_id)
                    pending.append(page_id)
        return affected

    def _matching_pages(self, view, title, path):
        terms = self._tokens(title)
        if not terms:
            return set()
        matched = set()
        for page_id, page in view.items():
            haystack = self._tokens(" ".join([page["title"], *page["aliases"]]))
            if terms & haystack:
                matched.add(page_id)
        return matched

    @staticmethod
    def _tokens(value):
        text = (value or "").casefold()
        tokens = {token for token in re.findall(r"[a-z0-9]+", text) if len(token) >= 3}
        for run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", text):
            if len(run) > 1:
                tokens.update(run[index:index + 2] for index in range(len(run) - 1))
        return tokens

    @staticmethod
    def _stamp(value):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (AttributeError, TypeError, ValueError):
            return 0.0

    @staticmethod
    def _key(url):
        return SourceArchive._key(url)

    @staticmethod
    def _dump(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _slug(title):
        value = re.sub(r"[^a-z0-9]+", "-", (title or "").casefold()).strip("-")
        value = value[:60].strip("-")
        if value and value[0].isalnum():
            return value
        return "topic-" + hashlib.sha256((title or "").encode("utf-8")).hexdigest()[:8]

    def _load_plan(self, plan_id):
        path = self._path(plan_id)
        if not path.is_file():
            raise ValueError("Unknown Wiki compile plan: " + plan_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _gaps_path(self, plan_id):
        return self.wiki._path("compile/%s.gaps.json" % plan_id)

    def _gaps(self, path, plan_id):
        if not path.exists():
            return {"schema_version": 1, "plan_id": plan_id, "gaps": {}}
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("schema_version") != 1 or data.get("plan_id") != plan_id
                or not isinstance(data.get("gaps"), dict)):
            raise ValueError("Unsupported Wiki compile gap file")
        return data

    def _urls(self, values):
        if not isinstance(values, list) or not 1 <= len(values) <= 16:
            raise ValueError("urls must contain 1 to 16 URLs")
        result = []
        for value in values:
            url = self._text(value, "url", 8192)
            self._key(url)
            if url not in result:
                result.append(url)
        return result

    @staticmethod
    def _text(value, label, maximum):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
            raise ValueError("%s must be a non-empty string of at most %d characters" % (label, maximum))
        return value.strip()

    def _path(self, plan_id):
        return self.wiki._path("compile/%s.json" % plan_id)

    @staticmethod
    def _plan_id(value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{16}", value):
            raise ValueError("plan_id must be 16 lowercase hex characters")
        return value

    @staticmethod
    def _identifier(value, label):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(label + " must be a non-empty string of at most 200 characters")
        return value.strip()

    @staticmethod
    def _optional_text(value, label, maximum):
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(label + " must be a non-empty string when provided")
        if len(value) > maximum:
            raise ValueError(label + " is too long")
        return value.strip()

    @staticmethod
    def _names(values, label):
        if values is None:
            return []
        if (not isinstance(values, list) or len(values) > 100
                or any(not isinstance(value, str) or not value.strip() or len(value) > 200
                       for value in values)):
            raise ValueError(label + " must be a list of names")
        return list(dict.fromkeys(value.strip() for value in values))

    @staticmethod
    def _integer(value, label, minimum, maximum):
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError("%s must be an integer from %d to %d" % (label, minimum, maximum))
        return value
