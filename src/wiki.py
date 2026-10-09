"""Versioned, externally stored knowledge pages authored and reviewed by a host.

This module checks provenance, never semantic support. A saved extract is not a
Wiki page: the caller supplies topic/entity organization, prose and a declared
human or model review. Only active claims backed by accepted sources may enter.
Each write also regenerates index.md (catalog) and appends to log.md (timeline);
both are derived views, while index.json stays the source of truth.
"""

import copy
import hashlib
import json
import os
import re
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

from research import ResearchSessions
from settings import Settings


class WikiStore:
    """Publish immutable revisions, then atomically advance the current index."""

    MAX_RECORD_BYTES = 900000
    ARTIFACT_FIELDS = ("body_file", "manifest_file", "response_file")
    REVIEW_RUBRIC = (
        "Check that each section is supported by its cited claims, preserves scope and uncertainty, "
        "identifies the correct entities, and does not conceal contrary evidence. "
        "Topic organization and semantic support are judgments by the named reviewer."
    )

    def __init__(self, directory=None, settings=None, research_sessions=None):
        self.settings = settings if settings is not None else Settings()
        selected = directory if directory is not None else self.selected_directory(self.settings)
        self.directory = Settings.external_path(str(selected), "Wiki directory")
        self.research = research_sessions if research_sessions is not None else ResearchSessions(settings=self.settings)

    @classmethod
    def selected_directory(cls, settings):
        """Return the configured Wiki directory without building a store.

        A long-lived MCP server caches its store, so it compares this value on
        every call: ``update_settings`` applies to later calls without a restart.
        """
        return settings.load().get("wiki", {}).get("directory", Settings.data_directory() / "wiki")

    @staticmethod
    def _slug(value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", value):
            raise ValueError("page_id must use 1 to 80 lowercase letters, digits or hyphens")
        return value

    @staticmethod
    def _text(value, label, maximum=4000, single_line=False):
        value = ResearchSessions._text(value, label, maximum)
        if single_line and ("\n" in value or "\r" in value):
            raise ValueError(label + " must be a single line")
        return value

    def _path(self, relative):
        relative = Path(relative)
        path = self.directory / relative
        if relative.is_absolute() or self.directory not in path.resolve().parents:
            raise ValueError("Wiki artifact must stay inside its directory")
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != self.directory):
            raise ValueError("Wiki artifacts must not use symlinks")
        return path

    def _index(self):
        path = self._path("index.json")
        if not path.exists():
            return {"schema_version": 1, "pages": {}}
        if path.stat().st_size > 8000000:
            raise ValueError("Wiki index exceeds its size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or not isinstance(value.get("pages"), dict):
            raise ValueError("Unsupported Wiki index")
        return value

    def _revision(self, pointer):
        raw = self._path(pointer["record_file"]).read_bytes()
        if len(raw) > self.MAX_RECORD_BYTES or hashlib.sha256(raw).hexdigest() != pointer["sha256"]:
            raise ValueError("Wiki revision hash changed or size limit exceeded")
        value = json.loads(raw)
        if value.get("schema_version") != 1 or value.get("revision") != pointer["revision"]:
            raise ValueError("Unsupported or inconsistent Wiki revision")
        markdown = self._path(pointer["markdown_file"]).read_bytes()
        if hashlib.sha256(markdown).hexdigest() != pointer["markdown_sha256"]:
            raise ValueError("Wiki Markdown hash changed; publish an explicit revision")
        return value

    def _page(self, page):
        if not isinstance(page, dict) or set(page) != {"title", "kind", "sections", "links", "review"}:
            raise ValueError("page needs title, kind, sections, links and review only")
        value = copy.deepcopy(page)
        value["title"] = self._text(value["title"], "Wiki title", 300, single_line=True)
        if value["kind"] not in ("topic", "entity"):
            raise ValueError("Wiki kind must be topic or entity")
        if not isinstance(value["sections"], list) or not 1 <= len(value["sections"]) <= 16:
            raise ValueError("A Wiki page needs 1 to 16 authored sections")
        references = []
        for section in value["sections"]:
            if not isinstance(section, dict) or set(section) != {"heading", "text", "claims"}:
                raise ValueError("Each section needs heading, text and claims only")
            section["heading"] = self._text(section["heading"], "Section heading", 300, single_line=True)
            section["text"] = self._text(section["text"], "Section text", 12000)
            if not isinstance(section["claims"], list) or not 1 <= len(section["claims"]) <= 12:
                raise ValueError("Each section needs 1 to 12 explicit claim references")
            seen = set()
            for reference in section["claims"]:
                if not isinstance(reference, dict) or set(reference) != {"research_id", "claim_id"}:
                    raise ValueError("Each claim reference needs research_id and claim_id only")
                self.research._path(reference["research_id"])
                ResearchSessions._identifier(reference["claim_id"], "Claim id")
                pair = (reference["research_id"], reference["claim_id"])
                if pair in seen:
                    raise ValueError("Duplicate claim reference in a section")
                seen.add(pair)
                if pair not in references:
                    references.append(pair)
        if len(references) > 24:
            raise ValueError("A Wiki page may cite at most 24 distinct claims")
        if not isinstance(value["links"], list) or len(value["links"]) > 32:
            raise ValueError("Wiki links must contain at most 32 page relationships")
        seen_links = set()
        for link in value["links"]:
            if not isinstance(link, dict) or set(link) != {"page_id", "relation"}:
                raise ValueError("Each Wiki link needs page_id and relation only")
            self._slug(link["page_id"])
            link["relation"] = self._text(link["relation"], "Link relation", 500)
            if link["page_id"] in seen_links:
                raise ValueError("Duplicate Wiki link")
            seen_links.add(link["page_id"])
        review = value["review"]
        if not isinstance(review, dict) or set(review) != {"method", "reviewer", "note"}:
            raise ValueError("Wiki review needs method, reviewer and note only")
        if review["method"] not in ("human", "model"):
            raise ValueError("Wiki review method must be human or model")
        review["reviewer"] = self._text(review["reviewer"], "Reviewer", 300, single_line=True)
        review["note"] = self._text(review["note"], "Review note")
        return value, references

    def _evidence(self, research_id, claim_id, cache):
        if research_id not in cache:
            cache[research_id] = self.research._load(research_id)
        path, state = cache[research_id]
        claim = self.research._find(state["claims"], claim_id, "claim")
        if claim.get("status", "active") != "active":
            raise ValueError("Wiki cannot use a retracted claim: " + claim_id)
        citations = []
        for citation in claim["citations"]:
            source = self.research._find(state["sources"], citation["source_id"], "source")
            if source.get("review", {}).get("verdict") != "accepted":
                raise ValueError("Wiki requires an accepted source review: " + source["id"])
            if citation["source_sha256"] != source["sha256"] or citation["quote"] not in self.research._body(path, source):
                raise ValueError("Wiki citation no longer matches saved evidence")
            artifacts = {key: self.research._artifact(path, source[key]) for key in self.ARTIFACT_FIELDS}
            artifact_hashes = {key: hashlib.sha256(value.read_bytes()).hexdigest() for key, value in artifacts.items()}
            citations.append({
                "source_id": source["id"], "inventory_ids": source.get("inventory_ids", []),
                "bookmark_refs": source.get("bookmark_refs", []), "url": source["url"],
                "quote": citation["quote"], "source_sha256": source["sha256"],
                "provider": source["provider"], "retrieved_at": source["retrieved_at"],
                "review": copy.deepcopy(source["review"]),
                "content_kind": source["content_kind"], "provenance": copy.deepcopy(source.get("provenance")),
                "artifact_sha256": artifact_hashes,
                **{key: value.relative_to(path).as_posix() for key, value in artifacts.items()}
            })
        if not citations:
            raise ValueError("Wiki claims require saved citations")
        return {"research_id": research_id, "claim_id": claim_id, "statement": claim["statement"],
                "confidence": claim["confidence"], "inference": claim["inference"], "citations": citations}

    def _issues(self, record, index, cache=None, resolve_paths=False):
        cache = {} if cache is None else cache
        issues = []
        for saved in record["evidence"]:
            try:
                current = self._evidence(saved["research_id"], saved["claim_id"], cache)
                # Locations and review explanations may change. Stable IDs,
                # accepted verdicts, quotes, content and artifact hashes must hold.
                def substantive(value):
                    value = copy.deepcopy(value)
                    for citation in value["citations"]:
                        for key in ("review", *self.ARTIFACT_FIELDS):
                            citation.pop(key, None)
                    return value
                if substantive(current) != substantive(saved):
                    raise ValueError("Claim or source mapping changed after Wiki publication")
                if resolve_paths:
                    # Resolve only verified evidence for this returned view;
                    # immutable records (including legacy absolute paths) stay intact.
                    path = cache[saved["research_id"]][0]
                    for previous, now in zip(saved["citations"], current["citations"]):
                        for key in self.ARTIFACT_FIELDS:
                            previous[key] = str(self.research._artifact(path, now[key]))
            except (OSError, ValueError, KeyError, TypeError) as error:
                issues.append({"severity": "error", "code": "invalid_evidence", "research_id": saved["research_id"],
                               "claim_id": saved["claim_id"], "message": str(error)[:1000]})
        for research_id in sorted({saved["research_id"] for saved in record["evidence"]}):
            if research_id not in cache:
                continue
            key = ("source_freshness", research_id)
            if key not in cache:
                cache[key] = self.research.source_freshness(state=cache[research_id][1])
            freshness = cache[key]
            if freshness.get("state") == "unknown":
                issues.append({"severity": "warning", "code": "source_input_unavailable", "research_id": research_id,
                    "message": "The cited bookmark input cannot be checked; restore or synchronize its source before reviewing this page.",
                    "source_freshness": freshness})
            elif freshness["requires_review"]:
                # A recorded review of this exact input version closes the
                # warning. A later change produces a new version and reopens it.
                acknowledged = next((row for row in self._acknowledged(record)
                                     if row["research_id"] == research_id
                                     and row["input_version"] == freshness.get("current_input_version")), None)
                if acknowledged is not None:
                    issues.append({"severity": "info", "code": "source_change_acknowledged",
                        "research_id": research_id,
                        "message": "The bookmark input changed after the cited research; this page was reviewed against the new source version.",
                        "acknowledged_at": acknowledged.get("acknowledged_at"), "note": acknowledged.get("note"),
                        "source_freshness": freshness})
                else:
                    issues.append({"severity": "warning", "code": "source_input_changed", "research_id": research_id,
                        "message": "The bookmark input changed after the cited research; review this page against the new source version, then re-write it with reviewed_input_version or run wiki acknowledge.",
                        "source_freshness": freshness})
        for link in record["resolved_links"]:
            latest = index["pages"].get(link["page_id"])
            if latest is None:
                issues.append({"severity": "error", "code": "missing_link", "target_page_id": link["page_id"]})
            elif latest["revision"] != link["revision"]:
                issues.append({"severity": "warning", "code": "link_has_newer_revision", "target_page_id": link["page_id"],
                               "linked_revision": link["revision"], "current_revision": latest["revision"]})
            if not self._path(link["markdown_file"]).is_file():
                issues.append({"severity": "error", "code": "missing_link_artifact", "target_page_id": link["page_id"]})
        return issues

    @contextmanager
    def _research_locks(self, references):
        # Research mutations use these same locks. Keep accepted reviews and
        # active claims stable through the Wiki publication transaction.
        with ExitStack() as stack:
            for research_id in sorted({reference[0] for reference in references}):
                stack.enter_context(Settings._update_lock(self.research._path(research_id) / "state.json"))
            yield

    @staticmethod
    def _acknowledged(record):
        """Return well-formed acknowledgments from a revision record."""
        rows = record.get("acknowledged")
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)
                and isinstance(row.get("research_id"), str) and isinstance(row.get("input_version"), str)]

    def _acknowledgements(self, references, cache, reviewed_input_version, acknowledge_all, note,
                          prior_record=None):
        """Record which current input versions this revision was reviewed against."""
        if not acknowledge_all and reviewed_input_version is None:
            # A content edit does not invalidate a source-version review that is
            # still current, so valid acknowledgements carry forward.
            carried = []
            for row in self._acknowledged(prior_record or {}):
                if row["research_id"] not in cache:
                    continue
                key = ("source_freshness", row["research_id"])
                if key not in cache:
                    cache[key] = self.research.source_freshness(state=cache[row["research_id"]][1])
                if cache[key].get("current_input_version") == row["input_version"]:
                    carried.append(row)
            return carried
        versions = {}
        for research_id in sorted({reference[0] for reference in references}):
            key = ("source_freshness", research_id)
            if key not in cache:
                cache[key] = self.research.source_freshness(state=cache[research_id][1])
            versions[research_id] = cache[key].get("current_input_version")
        if acknowledge_all:
            selected = {key: value for key, value in versions.items() if isinstance(value, str)}
        else:
            if (not isinstance(reviewed_input_version, str) or not reviewed_input_version.strip()
                    or len(reviewed_input_version) > 200):
                raise ValueError("reviewed_input_version must be a nonempty string of at most 200 characters")
            selected = {key: value for key, value in versions.items() if value == reviewed_input_version}
            if not selected:
                raise ValueError("reviewed_input_version does not match the current input version of any cited "
                                 "research task; read the page again or omit it")
        stamp = ResearchSessions._now()
        return [{"research_id": key, "input_version": value, "acknowledged_at": stamp, "note": note}
                for key, value in sorted(selected.items())]

    def write(self, page_id, page, change_note, expected_revision=0, reviewed_input_version=None,
              acknowledge_all=False):
        """Create at revision 0, or update the explicit revision read by the caller.

        ``reviewed_input_version`` records that the page was checked against that
        already-synchronized input version, which closes ``source_input_changed``
        for the cited tasks at that version.
        """
        page_id = self._slug(page_id)
        page, references = self._page(page)
        change_note = self._text(change_note, "Change note")
        ResearchSessions._integer(expected_revision, "expected_revision", 0, 10000)
        cache = {}
        for reference in references:
            self._evidence(*reference, cache)
        Settings.external_path(str(self.directory), "Wiki directory")
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        with self._research_locks(references), Settings._update_lock(self._path("index.json")):
            index = self._index()
            cache = {}
            evidence = [self._evidence(*reference, cache) for reference in references]
            previous = index["pages"].get(page_id)
            if expected_revision != (previous["revision"] if previous else 0):
                raise ValueError("Wiki revision changed; read the current page before updating")
            prior_record = self._revision(previous) if previous else None
            if acknowledge_all and prior_record is not None:
                # A freshness acknowledgement must preserve the previously
                # published evidence baseline, even if it changed after get().
                if any(issue["severity"] == "error" for issue in self._issues(prior_record, index, cache)):
                    raise ValueError("Wiki acknowledgement cannot accept invalid evidence or links; repair them before reviewing input changes")
            acknowledged = self._acknowledgements(references, cache, reviewed_input_version, acknowledge_all,
                                                  page["review"]["note"], prior_record)
            if prior_record is None and len(index["pages"]) >= 5000:
                raise ValueError("Wiki page limit reached")
            resolved_links = []
            for link in page["links"]:
                if link["page_id"] == page_id or link["page_id"] not in index["pages"]:
                    raise ValueError("Wiki links must target an existing different page")
                target = index["pages"][link["page_id"]]
                self._revision(target)
                resolved_links.append({**link, "revision": target["revision"], "title": target["title"],
                                       "markdown_file": target["markdown_file"]})
            revision = expected_revision + 1
            stamp = ResearchSessions._now()
            stem = "revisions/%s/%s-%s" % (page_id, revision, uuid.uuid4().hex[:12])
            record = {"schema_version": 1, "page_id": page_id, "revision": revision,
                      "updated_at": stamp, "change_note": change_note, "previous": previous,
                      "page": page, "evidence": evidence, "acknowledged": acknowledged,
                      "resolved_links": resolved_links, "review_rubric": self.REVIEW_RUBRIC}
            raw = (json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
            if len(raw) > self.MAX_RECORD_BYTES:
                raise ValueError("Wiki page and citation snapshots exceed 900000 bytes; split the topic")
            markdown = self._markdown(record, self._path(stem + ".md"))
            pointer = {"revision": revision, "record_file": stem + ".json", "sha256": hashlib.sha256(raw).hexdigest(),
                       "markdown_file": stem + ".md", "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
                       "title": page["title"], "kind": page["kind"], "updated_at": stamp}
            ResearchSessions._write(self._path(pointer["record_file"]), raw.decode("utf-8"))
            ResearchSessions._write(self._path(pointer["markdown_file"]), markdown)
            index["pages"][page_id] = pointer
            ResearchSessions._write(self._path("index.json"), index)
            # Derived, human-readable views; index.json and revisions stay authoritative.
            ResearchSessions._write(self._path("index.md"), self._catalog(index))
            ResearchSessions._write(self._path("log.md"), self._log_text() + self._log_entry(page_id, pointer, change_note, references))
        return {"page_id": page_id, **pointer, "status": "written", "directory": str(self.directory),
                "artifacts": self._artifacts(pointer), "semantic_review": "caller_declared",
                "acknowledged": acknowledged,
                "catalog": {key: str(self._path(key)) for key in ("index.md", "log.md")}}

    def acknowledge(self, page_id, note, expected_revision=None):
        """Re-publish a page unchanged, recording that its sources were re-reviewed.

        This is the remedy for ``source_input_changed`` when the content still
        holds: the page text is not edited, a new immutable revision records who
        reviewed which input version, and history is preserved.
        """
        page_id = self._slug(page_id)
        note = self._text(note, "Acknowledge note")
        current = self.get(page_id)
        revision = current["revision"] if expected_revision is None else expected_revision
        current["page"]["review"]["note"] = note
        result = self.write(page_id, current["page"], "Reviewed against the current input: " + note,
                            expected_revision=revision, acknowledge_all=True)
        result["acknowledged_note"] = note
        return result

    @staticmethod
    def _line(value, limit=None):
        value = " ".join(str(value).split())
        return value if limit is None or len(value) <= limit else value[:limit - 1].rstrip() + "…"

    def _catalog(self, index):
        """Deterministic Markdown catalog of current pages, derived only from index.json and records."""
        escape = lambda text: re.sub(r"([\\\[\]])", r"\\\1", text)
        lines = ["# Wiki index", "", "Generated from index.json after each Wiki write. Do not edit; "
                 "index.json and the revision files are authoritative.", ""]
        for kind, heading in (("topic", "Topics"), ("entity", "Entities")):
            rows = sorted(((key, value) for key, value in index["pages"].items() if value["kind"] == kind),
                          key=lambda row: (row[1]["title"].casefold(), row[0]))
            lines.extend(["## %s (%s)" % (heading, len(rows)), ""])
            for page_id, pointer in rows:
                try:
                    record = self._revision(pointer)
                    summary = self._line(record["page"]["sections"][0]["text"], 120)
                    claims = str(len(record["evidence"]))
                except (OSError, ValueError, KeyError, TypeError, IndexError):
                    summary, claims = "Revision unreadable; run wiki_lint.", "?"
                lines.append("- [%s](%s) `%s` · r%s · %s · %s claims — %s" % (
                    escape(pointer["title"]), pointer["markdown_file"], page_id, pointer["revision"],
                    pointer["updated_at"][:10], claims, summary))
            lines.extend([""] if rows else ["None yet.", ""])
        return "\n".join(lines).rstrip("\n") + "\n"

    def _log_text(self):
        path = self._path("log.md")
        if not path.is_file():
            return "# Wiki log\n\nAppend-only timeline of Wiki writes.\n"
        return path.read_bytes().decode("utf-8")

    def _log_entry(self, page_id, pointer, change_note, references):
        research_ids = ", ".join(sorted({reference[0] for reference in references}))
        return "\n".join(["", "## [%s] write | %s (r%s)" % (pointer["updated_at"][:10], pointer["title"], pointer["revision"]),
                          "", "- page_id: `%s`" % page_id, "- change_note: " + self._line(change_note),
                          "- research: " + research_ids, ""])

    def _catalog_issue(self, index):
        if not self._path("index.json").exists():
            return []
        path = self._path("index.md")
        try:
            current = path.read_bytes().decode("utf-8") if path.is_file() else None
        except (OSError, UnicodeDecodeError):
            current = None
        if current == self._catalog(index):
            return []
        return [{"page_id": None, "severity": "warning", "code": "catalog_missing" if current is None else "catalog_stale",
                 "regenerable": True, "message": "index.md is derived from index.json; the next Wiki write regenerates it."}]

    def _artifacts(self, pointer):
        return {key: str(self._path(pointer[key])) for key in ("record_file", "markdown_file")}

    @staticmethod
    def _validation(issues):
        return {"status": "stale" if any(item["severity"] == "error" for item in issues) else
                          "needs_review" if any(item["code"] in ("source_input_changed", "source_input_unavailable")
                                                for item in issues) else "current",
                "issues": issues, "semantic_review": "caller_declared; not evaluated by lint"}

    def get(self, page_id, revision=None):
        page_id = self._slug(page_id)
        if revision is not None:
            ResearchSessions._integer(revision, "revision", 1, 10001)
        index = self._index()
        pointer = index["pages"].get(page_id)
        while pointer is not None:
            record = self._revision(pointer)
            if record["page_id"] != page_id:
                raise ValueError("Wiki revision belongs to a different page")
            if revision is None or record["revision"] == revision:
                issues = self._issues(record, index, resolve_paths=True)
                return {**record, "artifacts": self._artifacts(pointer), "validation": self._validation(issues)}
            if record["previous"] is not None and record["previous"]["revision"] >= record["revision"]:
                raise ValueError("Invalid Wiki revision history")
            pointer = record["previous"]
        raise ValueError("Unknown Wiki page or revision")

    def list(self, offset=0, limit=20):
        ResearchSessions._integer(offset, "offset", 0, 10000000)
        ResearchSessions._integer(limit, "limit", 1, 100)
        rows = sorted(self._index()["pages"].items())
        return {"directory": str(self.directory), "pages": [{"page_id": key, **value} for key, value in rows[offset:offset + limit]],
                "total": len(rows), "next_offset": offset + limit if offset + limit < len(rows) else None}

    def lint(self, page_id=None):
        index = self._index()
        ids = [self._slug(page_id)] if page_id is not None else sorted(index["pages"])
        issues, cache = [], {}
        for identifier in ids:
            try:
                if identifier not in index["pages"]:
                    raise ValueError("Unknown Wiki page")
                record = self._revision(index["pages"][identifier])
                if record["page_id"] != identifier:
                    raise ValueError("Wiki revision belongs to a different page")
                issues.extend({"page_id": identifier, **issue} for issue in self._issues(record, index, cache))
                previous = record["previous"]
                while previous is not None:
                    older = self._revision(previous)
                    if older["page_id"] != identifier or older["revision"] >= record["revision"]:
                        raise ValueError("Invalid Wiki revision history")
                    record, previous = older, older["previous"]
            except (OSError, ValueError, KeyError, TypeError) as error:
                issues.append({"page_id": identifier, "severity": "error", "code": "artifact_error", "message": str(error)[:1000]})
        if page_id is None:
            issues.extend(self._catalog_issue(index))
        return {"status": "error" if any(item["severity"] == "error" for item in issues) else "ok",
                "pages_checked": len(ids), "issues": issues, "semantic_support": "not_scored",
                "boundary": "Checks current source reviews, active claims, saved quotes, hashes, links and revision history only."}

    def search(self, query, offset=0, limit=10):
        query = self._text(query, "Wiki query", 500)
        ResearchSessions._integer(offset, "offset", 0, 10000000)
        ResearchSessions._integer(limit, "limit", 1, 100)
        terms = list(dict.fromkeys(query.casefold().split()))
        index, matches, excluded, cache = self._index(), [], [], {}
        for page_id, pointer in index["pages"].items():
            try:
                record = self._revision(pointer)
                validation = self._validation(self._issues(record, index, cache))
                if validation["status"] == "stale":
                    excluded.append(page_id)
                    continue
                page = record["page"]
                body = "\n\n".join(section["heading"] + "\n" + section["text"] for section in page["sections"])
                text = (page["title"] + "\n" + body).casefold()
                # CJK writers do not put spaces where an author did ("唯一URL" vs
                # "唯一 URL"), so a whitespace-insensitive pass runs in addition
                # to the literal one. It only widens matches when spacing differs.
                squashed = re.sub(r"\s+", "", text)
                squashed_terms = [re.sub(r"\s+", "", term) for term in terms]
                squashed_match = all(term and term in squashed for term in squashed_terms)
                if not (all(term in text for term in terms) or squashed_match):
                    continue
                rank = sum(min(text.count(term), 20) + (5 if term in page["title"].casefold() else 0) for term in terms)
                positions = [body.casefold().find(term) for term in terms if term in body.casefold()]
                begin = max(0, min(positions, default=0) - 60)
                matches.append((rank, {"page_id": page_id, "revision": pointer["revision"], "title": page["title"],
                                      "kind": page["kind"], "snippet": body[begin:begin + 500],
                                      "updated_at": pointer["updated_at"], "validation": validation,
                                      "whitespace_insensitive": bool(squashed_match and not all(term in text for term in terms)),
                                      "artifacts": self._artifacts(pointer)}))
            except (OSError, ValueError, KeyError, TypeError):
                excluded.append(page_id)
        matches.sort(key=lambda row: (-row[0], row[1]["page_id"]))
        return {"query": query, "results": [row[1] for row in matches[offset:offset + limit]], "total": len(matches),
                "next_offset": offset + limit if offset + limit < len(matches) else None,
                "excluded_stale_pages": len(excluded), "excluded_page_ids": excluded[:100],
                "method": "casefolded literal terms over authored Wiki text, plus a whitespace-insensitive pass so CJK "
                          "queries match differently spaced text; no semantic ranking"}

    def _markdown(self, record, location):
        page = record["page"]
        link = lambda target: os.path.relpath(target, location.parent).replace(os.sep, "/")
        refs = {(item["research_id"], item["claim_id"]): i + 1 for i, item in enumerate(record["evidence"])}
        lines = ["# " + page["title"], "", "Kind: %s · Revision: %s · %s" % (page["kind"], record["revision"], record["updated_at"]),
                 "", "Reviewed by %s (%s). %s" % (page["review"]["reviewer"], page["review"]["method"], page["review"]["note"]),
                 "", "This revision preserves the review at publication. Run Wiki lint to check later source changes.", ""]
        for section in page["sections"]:
            lines.extend(["## " + section["heading"], "", section["text"], "", "Evidence: " + " ".join(
                "[%s/%s](#evidence-%s)" % (item["research_id"], item["claim_id"], refs[(item["research_id"], item["claim_id"])])
                for item in section["claims"]), ""])
        if record["resolved_links"]:
            lines.extend(["## Related pages", ""])
            for target in record["resolved_links"]:
                lines.append("- [%s](%s): %s (revision %s)" %
                             (target["title"], link(self._path(target["markdown_file"])), target["relation"], target["revision"]))
            lines.append("")
        lines.extend(["## Evidence", ""])
        for i, evidence in enumerate(record["evidence"], 1):
            root = self.research._path(evidence["research_id"])
            lines.extend(["### Evidence %s" % i, "", "%s / %s: %s" %
                          (evidence["research_id"], evidence["claim_id"], evidence["statement"]), ""])
            for citation in evidence["citations"]:
                artifacts = {key: link(self.research._artifact(root, citation[key])) for key in self.ARTIFACT_FIELDS}
                lines.extend(["Source %s · %s · Retrieved %s" % (citation["source_id"], citation["url"], citation["retrieved_at"]),
                              "", "Inventory IDs: " + (", ".join(citation["inventory_ids"]) or "Not associated with a frozen inventory"), ""])
                if (citation["provenance"] or {}).get("kind") == "external_report":
                    lines.extend(["Secondary evidence: an external report. Pages cited by that report have not been read by importing it.", ""])
                lines.extend("> " + line for line in citation["quote"].splitlines())
                lines.extend(["", "[Saved text](%s) · [Manifest](%s) · [Response](%s) · SHA-256: `%s`" %
                              (artifacts["body_file"], artifacts["manifest_file"], artifacts["response_file"],
                               citation["source_sha256"]), ""])
        lines.extend(["## Update record", "", record["change_note"], ""])
        if record["previous"]:
            lines.extend(["[Previous revision](%s)" % link(self._path(record["previous"]["markdown_file"])), ""])
        return "\n".join(lines) + "\n"
