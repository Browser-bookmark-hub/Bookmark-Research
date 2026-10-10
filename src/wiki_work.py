"""Recover Wiki work from durable evidence and committed revisions, without a second queue."""
import json
from collections import Counter, defaultdict

from archive import SourceArchive


class WikiWork:
    STATUSES = ("archived", "pending", "compiled", "needs_review")
    KINDS = ("capture", "research", "page")

    def __init__(self, wiki):
        self.wiki = wiki
        self.research = wiki.research
        self.archive = SourceArchive(wiki.settings.load()["archive"]["directory"])

    @staticmethod
    def source_key(url, sha256):
        if not sha256:
            return None
        try:
            return SourceArchive._key(url), sha256
        except (ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def receipt(record, pointer):
        return {"page_id": record["page_id"], "revision": record["revision"],
                "updated_at": record["updated_at"], "record_sha256": pointer["sha256"],
                "claims": [{"research_id": row["research_id"], "claim_id": row["claim_id"]}
                           for row in record["evidence"]]}

    @staticmethod
    def _pages(receipts):
        unique = {(row["page_id"], row["revision"]): row for row in receipts}
        rows = [{key: row[key] for key in ("page_id", "revision", "updated_at", "record_sha256")}
                for _, row in sorted(unique.items())]
        return {"pages": rows[:50], "page_count": len(rows), "pages_truncated": len(rows) > 50}

    def _published(self, index, cache, selected_page_id=None):
        claims, sources, pages = defaultdict(list), defaultdict(list), []
        for page_id, pointer in sorted(index["pages"].items()):
            if selected_page_id is not None and page_id != selected_page_id:
                continue
            row = {"work_id": "page:" + page_id, "kind": "page", "page_id": page_id,
                   "title": pointer.get("title"), "revision": pointer["revision"],
                   "resume": {"tool": "wiki_get", "arguments": {"page_id": page_id}}}
            try:
                record = self.wiki._revision(pointer)
                if record["page_id"] != page_id:
                    raise ValueError("Wiki revision belongs to a different page")
                validation = self.wiki._validation(self.wiki._issues(record, index, cache))
                issues = validation["issues"]
                preview = [{key: issue[key] for key in ("severity", "code", "url", "research_id", "claim_id",
                           "source_id", "page_id", "message") if key in issue} for issue in issues[:20]]
                source_reads = []
                for issue in issues:
                    observed = issue.get("new_source", {})
                    scope = observed.get("scope_id", "")
                    if scope.startswith("capture:"):
                        source_reads.append({"tool": "fetch_web", "arguments": {
                            "urls": [issue["url"]], "capture_id": scope.removeprefix("capture:"), "offset": 0}})
                    elif scope.startswith("r-"):
                        source_reads.append({"tool": "research_source", "arguments": {
                            "research_id": scope, "source_id": observed["source_id"], "offset": 0}})
                row.update(status="compiled" if validation["status"] == "current" else "needs_review",
                           validation={**validation, "issues": preview, "issue_count": len(issues),
                                       "issues_truncated": len(issues) > 20},
                           source_reads=source_reads[:20], source_read_count=len(source_reads),
                           receipt=self.receipt(record, pointer))
                # An intact publication receipt is not sufficient when its evidence has failed.
                if validation["integrity"] == "valid":
                    for evidence in record["evidence"]:
                        claims[evidence["research_id"], evidence["claim_id"]].append(row["receipt"])
                        for citation in evidence["citations"]:
                            if (citation.get("provenance") or {}).get("kind") in ("local_document", "external_report"):
                                continue
                            key = self.source_key(citation["url"], citation["source_sha256"])
                            if key is not None:
                                sources[key].append(row["receipt"])
            except (OSError, ValueError, KeyError, TypeError) as error:
                row.update(status="needs_review", error=str(error)[:1000])
            pages.append(row)
        return claims, sources, pages

    def _research_rows(self, published, cache, research_id=None):
        pending_sources, rows = defaultdict(set), []
        sessions = [{"research_id": research_id}] if research_id else self.research._sessions()
        for session in sessions:
            rid = session["research_id"]
            row = {"work_id": "research:" + rid, "kind": "research", "research_id": rid,
                   "resume": {"tool": "research_status", "arguments": {"research_id": rid}}}
            try:
                if session.get("location_status") in ("missing", "invalid"):
                    raise ValueError(session.get("error") or "Research task folder is missing")
                if rid not in cache:
                    cache[rid] = self.research._load(rid)
                _, state = cache[rid]
                sources = {source["id"]: source for source in state["sources"]}
                eligible, pending, invalid, receipts = [], [], [], []
                for claim in state["claims"]:
                    citations = claim.get("citations", [])
                    if claim.get("status", "active") != "active" or not citations:
                        continue
                    if not all(sources.get(citation["source_id"], {}).get("review", {}).get("verdict")
                               == "accepted" for citation in citations):
                        continue
                    cid = claim["id"]
                    try:
                        self.wiki._evidence(rid, cid, cache)
                    except (OSError, ValueError, KeyError, TypeError):
                        invalid.append(cid)
                        continue
                    eligible.append(cid)
                    if published.get((rid, cid)):
                        receipts.extend(published[rid, cid])
                    else:
                        pending.append(cid)
                        for citation in citations:
                            source = sources[citation["source_id"]]
                            if (source.get("provenance") or {}).get("kind") in ("local_document", "external_report"):
                                continue
                            key = self.source_key(source["url"], source["sha256"])
                            if key is not None:
                                pending_sources[key].add(rid)
                row.update(status="needs_review" if invalid else "pending" if pending else
                           "compiled" if eligible else "archived", title=state["brief"],
                           research_status=state["status"], source_count=len(sources),
                           eligible_claim_count=len(eligible), pending_claim_count=len(pending),
                           pending_claim_ids=pending[:50], invalid_claim_ids=invalid[:50],
                           invalid_claim_count=len(invalid), claims_truncated=max(len(pending), len(invalid)) > 50,
                           **self._pages(receipts))
                if pending or invalid:
                    row["resume"] = {"tool": "research_status", "arguments": {
                        "research_id": rid, "section": "claims", "offset": 0, "limit": 50}}
            except (OSError, ValueError, KeyError, TypeError) as error:
                row.update(status="needs_review", error=str(error)[:1000])
            rows.append(row)
        return rows, pending_sources

    def _capture_rows(self, published, pending, capture_id=None):
        rows = []
        for cid, directory in self.archive.captures():
            if capture_id is not None and cid != capture_id:
                continue
            row = {"work_id": "capture:" + cid, "kind": "capture", "capture_id": cid}
            try:
                path = directory / "manifest.json"
                if path.is_symlink() or path.stat().st_size > 4000000:
                    raise ValueError("Archive manifest is invalid or too large")
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if manifest.get("capture_id") != cid:
                    raise ValueError("Archive manifest belongs to another capture")
                receipts, tasks, covered, readable, urls = [], set(), 0, 0, []
                for page in manifest["pages"]:
                    url = page["requested_url"]
                    urls.append(url)
                    if not page.get("body_file"):
                        continue
                    self.archive.read_page(directory, page, manifest)
                    readable += 1
                    key = self.source_key(url, page.get("sha256"))
                    if key in published:
                        covered += 1
                        receipts.extend(published[key])
                    tasks.update(pending.get(key, ()))
                row.update(status="pending" if tasks else "compiled" if covered == len(urls) and covered
                           else "archived", urls=urls[:8], url_count=len(urls),
                           extracted_page_count=readable, compiled_page_count=covered,
                           retrieved_at=manifest.get("retrieved_at"), pending_research_ids=sorted(tasks)[:50],
                           pending_research_count=len(tasks), **self._pages(receipts))
                row["resume"] = {"tool": "fetch_web", "arguments": {
                    "urls": urls[:8], "capture_id": cid, "offset": 0}}
            except (OSError, ValueError, KeyError, TypeError) as error:
                row.update(status="needs_review", error=str(error)[:1000])
            rows.append(row)
        return rows

    def list(self, kind=None, status=None, research_id=None, page_id=None, capture_id=None, offset=0, limit=20):
        self.research._integer(offset, "offset", 0, 10000000)
        self.research._integer(limit, "limit", 1, 100)
        if kind is not None and kind not in self.KINDS:
            raise ValueError("Unknown Wiki work kind")
        if status is not None and status not in self.STATUSES:
            raise ValueError("Unknown Wiki work status")
        selected = [(name, value) for name, value in (
            ("research", research_id), ("page", page_id), ("capture", capture_id)) if value is not None]
        if len(selected) > 1 or selected and kind is not None and kind != selected[0][0]:
            raise ValueError("Use one work identifier with its matching kind")
        if selected:
            kind = selected[0][0]
        if research_id is not None:
            self.research._research_id(research_id)
        if page_id is not None:
            self.wiki._slug(page_id)
        if capture_id is not None:
            self.research._text(capture_id, "capture_id", 128)
        cache = {}
        index = self.wiki._index()
        claims, sources, pages = self._published(index, cache, page_id)
        rows, pending = ([], {}) if kind == "page" else self._research_rows(claims, cache, research_id)
        if kind == "capture":
            rows = []
        if kind in (None, "capture"):
            rows.extend(self._capture_rows(sources, pending, capture_id))
        if kind in (None, "page"):
            rows.extend(row for row in pages if page_id is None or row["page_id"] == page_id)
        if selected and not rows:
            raise ValueError("Unknown Wiki work item")
        counts = dict(Counter(row["status"] for row in rows))
        filtered = sorted((row for row in rows if status is None or row["status"] == status),
                          key=lambda row: row["work_id"])
        result, size = [], 0
        for row in filtered[offset:offset + limit]:
            encoded = len(json.dumps(row, ensure_ascii=False))
            if size + encoded > 800000 and result:
                break
            result.append(row)
            size += encoded
        end = offset + len(result)
        return {"items": result, "total": len(filtered), "offset": offset,
                "next_offset": end if end < len(filtered) else None, "status_counts": counts,
                "policy": self.wiki.settings.load()["wiki"]["after_research"], "read_only": True,
                "basis": "Saved captures, recoverable research receipts, and current committed Wiki revisions. "
                         "Uncommitted files and instruction-only follow-ups never count as publication.",
                "note": "Pending claims are candidates, not mandatory writes or new authorization. "
                        "Compiled means cited by an intact current revision, not that every passage was synthesized; "
                        "check page work for freshness. "
                        "Historical revisions remain available through wiki_get. Listing does not fetch or write."}
