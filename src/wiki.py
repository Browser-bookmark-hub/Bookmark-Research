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
import shutil
import sqlite3
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from research import ResearchSessions
from settings import Settings
from wiki_search import WikiSearchIndex
from source_versions import SourceVersions


class WikiStore:
    """Publish immutable revisions, then atomically advance the current index."""

    MAX_PAGE_CLAIMS = 24
    MAX_SECTION_CLAIMS = 12
    MAX_SECTIONS = 16
    MAX_SECTION_CHARACTERS = 12000
    MAX_RECORD_BYTES = 900000
    ARTIFACT_FIELDS = ("body_file", "manifest_file", "response_file")
    REVIEW_RUBRIC = (
        "Check that each section is supported by its cited claims, preserves scope and uncertainty, "
        "identifies the correct entities, and does not conceal contrary evidence. "
        "Topic organization and semantic support are judgments by the named reviewer."
    )

    @staticmethod
    def _retrieved_at(row):
        """The source's retrieval time, falling back to a recorded fetch time.

        Imported evidence often carries ``provenance.fetched_at`` without a
        top-level ``retrieved_at``. Rendering that as "None" and warning
        ``source_capture_time_unknown`` hides a time the host actually recorded.
        """
        value = row.get("retrieved_at") if isinstance(row, dict) else None
        if value:
            return value
        provenance = (row.get("provenance") or {}) if isinstance(row, dict) else {}
        return provenance.get("retrieved_at") or provenance.get("fetched_at")

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
        required = {"title", "kind", "sections", "links", "review"}
        if not isinstance(page, dict) or not required <= set(page) or set(page) - required - {"aliases"}:
            raise ValueError("page needs title, kind, sections, links and review; aliases is optional")
        value = copy.deepcopy(page)
        if "aliases" in value:
            if not isinstance(value["aliases"], list) or len(value["aliases"]) > 30:
                raise ValueError("Wiki aliases must contain at most 30 names")
            value["aliases"] = list(dict.fromkeys(self._text(alias, "Wiki alias", 100, single_line=True)
                                                for alias in value["aliases"]))
        value["title"] = self._text(value["title"], "Wiki title", 300, single_line=True)
        if value["kind"] not in ("topic", "entity"):
            raise ValueError("Wiki kind must be topic or entity")
        if not isinstance(value["sections"], list) or not 1 <= len(value["sections"]) <= self.MAX_SECTIONS:
            raise ValueError("A Wiki page needs 1 to 16 authored sections")
        references = []
        for section in value["sections"]:
            if not isinstance(section, dict) or set(section) != {"heading", "text", "claims"}:
                raise ValueError("Each section needs heading, text and claims only")
            section["heading"] = self._text(section["heading"], "Section heading", 300, single_line=True)
            section["text"] = self._text(section["text"], "Section text", self.MAX_SECTION_CHARACTERS)
            if not isinstance(section["claims"], list) or not 1 <= len(section["claims"]) <= self.MAX_SECTION_CLAIMS:
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
        if len(references) > self.MAX_PAGE_CLAIMS:
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
                "provider": source["provider"], "retrieved_at": self._retrieved_at(source),
                "characters": source.get("characters"),
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
                        # A legacy record may store retrieved_at=null while its
                        # provenance already recorded the fetch time; normalize
                        # both sides before deciding the mapping changed.
                        citation["retrieved_at"] = self._retrieved_at(citation)
                        for key in ("review", "characters", *self.ARTIFACT_FIELDS):
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
            evidence = [saved for saved in record["evidence"] if saved["research_id"] == research_id]
            citations = [citation for saved in evidence for citation in saved["citations"]]
            # Inferences and local/aggregate evidence retain the complete scope.
            # Direct webpage claims can use their explicit bookmark dependencies.
            scoped = not any(saved.get("inference") for saved in evidence) and all(
                citation.get("bookmark_refs") and
                (citation.get("provenance") or {}).get("kind") not in ("local_document", "external_report")
                for citation in citations)
            refs = [ref for citation in citations for ref in citation.get("bookmark_refs", [])] if scoped else None
            ref_key = tuple(sorted({tuple(ref[name] for name in ("source_id", "section_id", "item_id"))
                                    for ref in refs})) if refs else None
            key = ("source_freshness", research_id, ref_key)
            if key not in cache:
                cache[key] = self.research.source_freshness(state=cache[research_id][1], bookmark_refs=refs,
                                                          snapshot_cache=cache)
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
            else:
                key = ("linked_validation", link["page_id"], latest["revision"])
                if key not in cache:
                    cache[key] = None  # Break cycles in legacy/manual records.
                    try:
                        target = self._revision(latest)
                        cache[key] = self._validation(self._issues(target, index, cache))
                    except (OSError, ValueError, KeyError, TypeError):
                        cache[key] = {"status": "stale"}
                if cache[key] and cache[key]["status"] != "current":
                    issues.append({"severity": "warning", "code": "linked_page_needs_review",
                                   "target_page_id": link["page_id"], "target_status": cache[key]["status"]})
            if not self._path(link["markdown_file"]).is_file():
                issues.append({"severity": "error", "code": "missing_link_artifact", "target_page_id": link["page_id"]})
        issues.extend(self._web_issues(record, cache))
        return issues

    def _web_issues(self, record, cache):
        issues = []
        settings = self.settings.load()
        age_limit = settings["wiki"]["max_source_age_days"]
        now = datetime.now(timezone.utc)
        stores = [self.research._source_versions(),
                  SourceVersions(Path(settings["archive"]["directory"]) / "source-versions.sqlite3")]
        stores = list({str(store.path): store for store in stores}.values())
        seen = set()
        for evidence in record["evidence"]:
            research_id = evidence["research_id"]
            state = cache.get(research_id, (None, {}))[1]
            if state.get("source_version_tracking", {}).get("status") == "unavailable":
                issues.append({"severity": "warning", "code": "source_version_index_unavailable",
                               "research_id": research_id})
            for citation in evidence["citations"]:
                if (citation.get("provenance") or {}).get("kind") == "local_document":
                    continue
                identity = (research_id, citation["source_id"])
                if identity in seen:
                    continue
                seen.add(identity)
                stamp = SourceVersions.timestamp(self._retrieved_at(citation))
                detail = {"url": citation["url"], "research_id": research_id, "source_id": citation["source_id"]}
                observations = []
                for store in stores if (citation.get("provenance") or {}).get("kind") != "external_report" else []:
                    key = ("web_version", str(store.path), identity, citation["source_sha256"], record["updated_at"])
                    try:
                        if key not in cache:
                            cache[key] = store.inspect(citation["url"], citation["source_sha256"],
                                self._retrieved_at(citation), record["updated_at"], research_id, citation["source_id"])
                        observation = cache[key]
                    except (OSError, ValueError, sqlite3.Error):
                        issues.append({**detail, "severity": "warning", "code": "source_version_index_unavailable"})
                        continue
                    observations.append(observation)
                def observed_order(observation):
                    latest = observation["latest"]
                    earliest = datetime.min.replace(tzinfo=timezone.utc)
                    return (SourceVersions.timestamp(latest.get("acquired_at")) or
                            SourceVersions.timestamp(latest["observed_at"]) or earliest,
                            SourceVersions.timestamp(latest["observed_at"]) or earliest, latest["seq"])
                latest = max((row for row in observations if row.get("latest")), key=observed_order, default=None)
                if latest and latest["newer"]:
                    issues.append({**detail, "severity": "warning", "code": "newer_source_snapshot",
                                   "new_source": latest["newer"],
                                   "message": "Newer extracted content is available. Review the affected claims before revising this page."})
                if latest and latest["latest"]["sha256"] == citation["source_sha256"]:
                    same_capture = SourceVersions.timestamp(latest["latest"].get("acquired_at"))
                    if same_capture and (same_capture - now).total_seconds() <= 300:
                        stamp = max(stamp, same_capture) if stamp else same_capture
                if stamp is None or (stamp - now).total_seconds() > 300:
                    issues.append({**detail, "severity": "warning", "code": "source_capture_time_unknown"})
                elif (now - stamp).total_seconds() > age_limit * 86400:
                    issues.append({**detail, "severity": "warning", "code": "source_capture_expired",
                                   "last_matching_capture_at": stamp.isoformat(), "max_age_days": age_limit})
                attempt = max((row["last_attempt"] for row in observations if row["last_attempt"]),
                              key=lambda row: row["attempted_at"], default=None)
                if attempt and attempt["status"] != "ok" and (
                        stamp is None or SourceVersions.timestamp(attempt["attempted_at"]) >= stamp):
                    issues.append({**detail, "severity": "warning", "code": "source_refresh_failed",
                                   "last_attempt": attempt})
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

    def _compile_page(self, page_id, page, sources, cleanup):
        """Keep ordinary source retention inside the existing evidence store.

        Callers supply authored sections, exact quotes and text they read (or
        an immutable capture). They need no research IDs or intermediate calls.
        Validate all inputs before creating a retained research record.
        """
        from archive import SourceArchive
        if not isinstance(sources, list) or not 1 <= len(sources) <= 16:
            raise ValueError("sources must contain 1 to 16 read sources")
        prepared = {}
        for source in sources:
            if not isinstance(source, dict) or set(source) - {
                    "id", "url", "text", "capture_id", "title", "retrieved_at", "kind"}:
                raise ValueError("Invalid Wiki source fields")
            identifier = ResearchSessions._identifier(source.get("id"), "Source id")
            if identifier in prepared:
                raise ValueError("Duplicate source id")
            url = self._text(source.get("url"), "Source URL", 8192)
            kind = source.get("kind", "page")
            if kind not in ("page", "local_document", "external_report"):
                raise ValueError("Invalid Wiki source kind")
            if kind == "page" or (kind == "local_document" and not url.startswith("file://")):
                SourceArchive._key(url)
            capture_id = source.get("capture_id")
            if capture_id and source.get("text") is not None:
                raise ValueError("Use capture_id or source text, not both")
            provenance = {"kind": kind, "provider": "host"}
            text = source.get("text")
            if capture_id:
                archive = SourceArchive(self.settings.load()["archive"]["directory"])
                saved = archive.read_capture(capture_id, [url])["pages"][0]
                if saved.get("content_state") != "usable":
                    raise ValueError("Wiki capture has no usable source text: " + url)
                text = archive.read_page(Path(saved["manifest_path"]).parent, saved)
                provenance.update(kind="archived_page", capture_id=capture_id,
                                  provider=saved.get("provider") or "archive",
                                  retrieved_at=saved.get("retrieved_at"))
            elif source.get("retrieved_at") is not None:
                provenance["retrieved_at"] = source["retrieved_at"]
            prepared[identifier] = {"url": url, "text": self._text(text, "Source text", 2000000),
                                    "title": self._text(source.get("title") or url, "Source title", 2000),
                                    "provenance": provenance}
        value = copy.deepcopy(page)
        if not isinstance(value, dict) or not isinstance(value.get("sections"), list):
            raise ValueError("page needs authored sections")
        citations, statements = [], []
        for section in value["sections"]:
            if not isinstance(section, dict) or set(section) != {"heading", "text", "citations"}:
                raise ValueError("With sources, each section needs heading, text and citations")
            rows = section.pop("citations")
            if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
                raise ValueError("Each section needs 1 to 12 exact citations")
            for row in rows:
                if not isinstance(row, dict) or set(row) != {"source_id", "quote"}:
                    raise ValueError("Each citation needs source_id and quote")
                source = prepared.get(row["source_id"])
                quote = self._text(row["quote"], "Quote")
                if source is None or quote not in source["text"]:
                    raise ValueError("Quote is absent from the supplied source")
            text = self._text(section["text"], "Section text", self.MAX_SECTION_CHARACTERS)
            chunks = [chunk.strip() for start in range(0, len(text), 4000)
                      if (chunk := text[start:start + 4000]).strip()]
            section["claims"] = [{"research_id": "r-0000000000000000", "claim_id": "c%d" % (len(statements) + i + 1)}
                                 for i in range(len(chunks))]
            statements.extend(chunks)
            citations.extend([rows] * len(chunks))
        value, _ = self._page(value)
        index = self._index()
        for link in value["links"]:
            if link["page_id"] == page_id or link["page_id"] not in index["pages"]:
                raise ValueError("Wiki links must target an existing different page")
            self._revision(index["pages"][link["page_id"]])
        used = {row["source_id"] for rows in citations for row in rows}
        if used != set(prepared):
            raise ValueError("Every supplied source must be cited by a section")
        # An explicit root keeps these internal records out of the task location
        # registry. Failed writes can remove their private record completely.
        retained = ResearchSessions(directory=self.research.directory, settings=self.settings)
        started = retained.start("Wiki: " + value["title"], [{"id": "wiki", "question": value["title"]}],
                                      budget={"max_search_calls": 0, "max_fetch_calls": 0})
        research_id = started["research_id"]
        cleanup.callback(self._discard_retained, page_id, retained._path(research_id))
        ids, entries = {}, []
        for number, (identifier, source) in enumerate(prepared.items()):
            saved = retained.import_evidence(research_id, "wiki-source-%d" % number, "wiki", **source)
            ids[identifier] = saved["sources"][0]["id"]
            entries.append({"kind": "source_review", "source_id": ids[identifier], "verdict": "accepted",
                            "text": value["review"]["note"]})
        for text, rows in zip(statements, citations):
            entries.append({"kind": "claim", "question_id": "wiki", "statement": text, "inference": True,
                            "citations": [{"source_id": ids[row["source_id"]], "quote": row["quote"]} for row in rows]})
        entries.append({"kind": "answer", "question_id": "wiki", "answer": value["title"],
                        "claim_ids": ["c%d" % (number + 1) for number in range(len(statements))]})
        retained.record(research_id, entries=entries)
        retained.finish(research_id, "Retained reviewed Wiki sources: " + value["title"])
        for section in value["sections"]:
            for claim in section["claims"]:
                claim["research_id"] = research_id
        return value

    def _discard_retained(self, page_id, path):
        # An error after index publication must preserve the committed evidence.
        try:
            pointer = self._index()["pages"].get(page_id)
            if pointer and any(reference["research_id"] == path.name
                               for section in self._revision(pointer)["page"]["sections"]
                               for reference in section["claims"]):
                return
        except (OSError, ValueError, KeyError, TypeError):
            return
        self.research._source_versions().discard_scope(path.name)
        shutil.rmtree(path)

    def write(self, page_id, page, change_note, expected_revision=0, reviewed_input_version=None,
              acknowledge_all=False, sources=None):
        if sources is None:
            return self._write_page(page_id, page, change_note, expected_revision,
                                    reviewed_input_version, acknowledge_all)
        page_id = self._slug(page_id)
        self._text(change_note, "Change note")
        ResearchSessions._integer(expected_revision, "expected_revision", 0, 10000)
        if reviewed_input_version is not None:
            raise ValueError("reviewed_input_version applies to existing research claims, not new sources")
        previous = self._index()["pages"].get(page_id)
        if expected_revision != (previous["revision"] if previous else 0):
            raise ValueError("Wiki revision changed; read the current page before updating")
        with ExitStack() as cleanup:
            compiled = self._compile_page(page_id, page, sources, cleanup)
            result = self._write_page(page_id, compiled, change_note, expected_revision,
                                      reviewed_input_version, acknowledge_all)
            cleanup.pop_all()
            return result

    def _write_page(self, page_id, page, change_note, expected_revision=0, reviewed_input_version=None,
                    acknowledge_all=False):
        """Create at revision 0, or update the explicit revision read by the caller.

        ``reviewed_input_version`` records that the page was checked against that
        already-synchronized input version, which closes ``source_input_changed``
        for the cited tasks at that version.
        """
        page_id = self._slug(page_id)
        change_note = self._text(change_note, "Change note")
        ResearchSessions._integer(expected_revision, "expected_revision", 0, 10000)
        page, references = self._page(page)
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
                       "title": page["title"], "kind": page["kind"], "updated_at": stamp,
                       "summary": self._line(page["sections"][0]["text"], 120), "claim_count": len(evidence)}
            ResearchSessions._write(self._path(pointer["record_file"]), raw.decode("utf-8"))
            ResearchSessions._write(self._path(pointer["markdown_file"]), markdown)
            index["pages"][page_id] = pointer
            # Backfill legacy catalog summaries once; future writes need no
            # unrelated revision/evidence reads to render the human catalog.
            for other in index["pages"].values():
                if "summary" not in other:
                    try:
                        old = self._revision(other)
                        other.update(summary=self._line(old["page"]["sections"][0]["text"], 120),
                                     claim_count=len(old["evidence"]))
                    except (OSError, ValueError, KeyError, TypeError, IndexError):
                        other.update(summary="Revision unreadable; run wiki_lint.", claim_count="?")
            ResearchSessions._write(self._path("index.json"), index)
            # Derived, human-readable views; index.json and revisions stay authoritative.
            ResearchSessions._write(self._path("index.md"), self._catalog(index))
            log = self._path("log.md")
            with log.open("a", encoding="utf-8") as stream:
                if stream.tell() == 0:
                    stream.write("# Wiki log\n\nAppend-only timeline of Wiki writes.\n")
                stream.write(self._log_entry(page_id, pointer, change_note, references))
                stream.flush()
                os.fsync(stream.fileno())
            search_index = "indexed"
            try:
                WikiSearchIndex(self._path("search.sqlite3")).update(page_id, pointer, record)
            except (OSError, ValueError, sqlite3.Error):
                search_index = "unavailable"
        from wiki_work import WikiWork
        return {"page_id": page_id, **pointer, "status": "written", "directory": str(self.directory),
                "artifacts": self._artifacts(pointer), "semantic_review": "caller_declared",
                "acknowledged": acknowledged, "search_index": search_index,
                "work_receipt": WikiWork.receipt(record, pointer),
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
                    if "summary" in pointer:
                        summary, claims = pointer["summary"], str(pointer["claim_count"])
                    else:
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
        web_codes = {"newer_source_snapshot", "source_capture_expired", "source_capture_time_unknown",
                     "source_version_index_unavailable", "source_refresh_failed"}
        review_codes = web_codes | {"source_input_changed", "source_input_unavailable", "link_has_newer_revision",
                                    "linked_page_needs_review"}
        return {"status": "stale" if any(item["severity"] == "error" for item in issues) else
                          "needs_review" if any(item["code"] in review_codes
                                                for item in issues) else "current",
                "integrity": "invalid" if any(item["severity"] == "error" for item in issues) else "valid",
                "freshness": {"status": "needs_review" if any(item["code"] in web_codes for item in issues)
                              else "within_capture_age_policy",
                              "origin_current_verified": False,
                              "basis": "Saved capture age and known versions; this is not a live origin guarantee."},
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

    def _affected(self, index, urls):
        try:
            return WikiSearchIndex(self._path("search.sqlite3")).affected(index, self._revision, urls)
        except (OSError, ValueError, sqlite3.Error):
            from archive import SourceArchive
            direct, incoming, invalid = set(), {}, []
            for page_id, pointer in index["pages"].items():
                try:
                    record = self._revision(pointer)
                    if any(SourceArchive._key(citation["url"]) in urls for evidence in record["evidence"]
                           for citation in evidence["citations"]
                           if (citation.get("provenance") or {}).get("kind") not in ("local_document", "external_report")):
                        direct.add(page_id)
                    for link in record["resolved_links"]:
                        incoming.setdefault(link["page_id"], set()).add(page_id)
                except (OSError, ValueError, KeyError, TypeError):
                    invalid.append(page_id)
            affected, pending = set(direct), list(direct)
            while pending:
                for page_id in incoming.get(pending.pop(), ()):
                    if page_id not in affected:
                        affected.add(page_id)
                        pending.append(page_id)
            return {"direct_page_ids": sorted(direct), "page_ids": sorted(affected), "unreadable_page_ids": invalid,
                    "search_index": "unavailable; using revision scan"}

    def work(self, kind=None, status=None, research_id=None, page_id=None, capture_id=None, offset=0, limit=20):
        from wiki_work import WikiWork
        return WikiWork(self).list(kind, status, research_id, page_id, capture_id, offset, limit)

    def refresh(self, page_id, provider=None, max_characters=None, offset=0, limit=8, expected_revision=None):
        """Capture cited pages for review; never rewrite claims or Wiki history."""
        from archive import SourceArchive
        ResearchSessions._integer(offset, "offset", 0, 10000000)
        ResearchSessions._integer(limit, "limit", 1, ResearchSessions.FETCH_BATCH_SIZE)
        if expected_revision is not None:
            ResearchSessions._integer(expected_revision, "expected_revision", 1, 10001)
        if provider is not None and provider not in Settings.PROVIDERS:
            raise ValueError("Unknown fetch provider")
        settings = self.settings.load()
        maximum = settings["fetch"]["max_characters"] if max_characters is None else max_characters
        ResearchSessions._integer(maximum, "max_characters", 100, 100000)
        record = self.get(page_id)
        if expected_revision is not None and record["revision"] != expected_revision:
            raise ValueError("Wiki revision changed; read the current page before refreshing")
        cited = {}
        for evidence in record["evidence"]:
            for citation in evidence["citations"]:
                if (citation.get("provenance") or {}).get("kind") in ("local_document", "external_report"):
                    continue
                cited.setdefault(SourceArchive._key(citation["url"]), set()).add(citation["source_sha256"])
        urls = sorted(cited)
        selected = urls[offset:offset + limit]
        result = {"page_id": record["page_id"], "revision": record["revision"], "offset": offset,
                  "total_urls": len(urls), "next_offset": offset + limit if offset + limit < len(urls) else None,
                  "status": "not_applicable", "checks": [], "origin_current_verified": False,
                  "work": {"tool": "wiki_work", "arguments": {"page_id": record["page_id"]}},
                  "next_action": "Read each saved capture, import changed evidence into research, review sources and claims, "
                                 "then wiki_write with expected_revision. Refresh does not rewrite authored knowledge."}
        if not selected:
            return result
        store = SourceArchive(settings["archive"]["directory"])
        try:
            fetched = self.research._web().fetch(selected, provider=provider, archive=True, max_characters=maximum)
            attempts = fetched.get("attempts", [fetched])
            for attempt in attempts:
                if isinstance(attempt.get("result"), dict) and attempt.get("archive", {}).get("status") != "saved":
                    try:
                        attempt["archive"] = store.save(attempt)
                    except (OSError, ValueError) as error:
                        attempt["archive"] = {"status": "error", "error": str(error)[:1000]}
            compact = SourceArchive.compact_fetch(fetched, max_characters=maximum)
            captured = {SourceArchive._key(page["url"]): page for page in compact.get("pages", [])}
        except (OSError, ValueError) as error:
            captured = {}
            result["error"] = str(error)[:1000]
        trackers = {str(tracker.path): tracker for tracker in (
            SourceVersions(store.directory / "source-versions.sqlite3"), self.research._source_versions())}
        for url in selected:
            page = captured.get(url, {})
            saved = bool(page.get("page_body_archived") and page.get("sha256") and page.get("text") is not None)
            status = ("unchanged" if cited[url] == {page["sha256"]} else "changed") if saved else "unverified"
            check = {"url": url, "status": status, "previous_sha256": sorted(cited[url]),
                     "sha256": page.get("sha256"), "capture_id": page.get("capture_id"),
                     "extraction_status": page.get("extraction_status", "request_failed")}
            if saved:
                check["read_capture"] = {"urls": [url], "capture_id": page["capture_id"], "offset": 0,
                                         "max_characters": maximum}
            tracked = False
            for tracker in trackers.values():
                try:
                    tracker.record_check(url, "ok" if saved else check["extraction_status"])
                    tracked = True
                except (OSError, ValueError, sqlite3.Error):
                    continue
            check["check_recorded"] = tracked
            result["checks"].append(check)
        count = sum(check["status"] != "unverified" for check in result["checks"])
        result["status"] = "ok" if count == len(selected) else "partial" if count else "error"
        current = self._index()
        affected = self._affected(current, set(selected))
        result["affected"] = {"total": len(affected["page_ids"]), "page_ids": affected["page_ids"][:100],
                              "truncated": len(affected["page_ids"]) > 100,
                              "unreadable_page_ids": affected["unreadable_page_ids"][:100],
                              "pagination": "wiki_list(source_url=..., offset=..., limit=...) includes linked dependents"}
        result["current_revision"] = current["pages"].get(record["page_id"], {}).get("revision")
        result["validation"] = self.get(record["page_id"])["validation"]
        if result["next_offset"] is not None:
            result["continuation"] = {"page_id": record["page_id"], "expected_revision": record["revision"],
                                      "offset": result["next_offset"], "limit": limit, "max_characters": maximum,
                                      **({"provider": provider} if provider is not None else {})}
        return result

    def list(self, offset=0, limit=20, source_url=None):
        ResearchSessions._integer(offset, "offset", 0, 10000000)
        ResearchSessions._integer(limit, "limit", 1, 100)
        index = self._index()
        affected = None
        if source_url is not None:
            from archive import SourceArchive
            affected = self._affected(index, {SourceArchive._key(source_url)})
        rows = sorted((key, value) for key, value in index["pages"].items()
                      if affected is None or key in affected["page_ids"])
        return {"directory": str(self.directory), "pages": [{"page_id": key, **value} for key, value in rows[offset:offset + limit]],
                "total": len(rows), "next_offset": offset + limit if offset + limit < len(rows) else None,
                **({"source_url": source_url, "includes_linked_dependents": True,
                    "unreadable_page_ids": affected["unreadable_page_ids"][:100]} if affected is not None else {})}

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
        groups = WikiSearchIndex.terms(query)
        index, matches, excluded, cache = self._index(), [], [], {}
        search_index = "indexed"
        try:
            candidates, invalid = WikiSearchIndex(self._path("search.sqlite3")).candidates(index, self._revision, groups)
        except (OSError, ValueError, sqlite3.Error):
            # The index is disposable. A damaged/unwritable cache must not make
            # committed knowledge inaccessible or skip evidence validation.
            search_index, candidates, invalid = "unavailable; using revision scan", [], []
            for page_id, pointer in index["pages"].items():
                try:
                    candidates.append(WikiSearchIndex.row(page_id, pointer, self._revision(pointer)))
                except (OSError, ValueError, KeyError, TypeError):
                    invalid.append(page_id)
        excluded.extend(invalid)
        checked = 0
        for candidate in candidates:
            match = WikiSearchIndex.match(candidate, query, groups)
            if match is None:
                continue
            page_id = candidate["page_id"]
            pointer = index["pages"][page_id]
            try:
                record = self._revision(pointer)
                match = WikiSearchIndex.match(WikiSearchIndex.row(page_id, pointer, record), query, groups)
                if match is None:
                    continue
                checked += 1
                validation = self._validation(self._issues(record, index, cache))
                if validation["status"] == "stale":
                    excluded.append(page_id)
                    continue
                page = record["page"]
                matches.append((match["rank"], {"page_id": page_id, "revision": pointer["revision"], "title": page["title"],
                                      "kind": page["kind"], "snippet": match["snippet"],
                                      "updated_at": pointer["updated_at"], "validation": validation,
                                      "whitespace_insensitive": match["whitespace_insensitive"],
                                      "alias_expanded": match["alias_expanded"],
                                      "artifacts": self._artifacts(pointer)}))
            except (OSError, ValueError, KeyError, TypeError):
                excluded.append(page_id)
        matches.sort(key=lambda row: (-row[0], row[1]["page_id"]))
        return {"query": query, "results": [row[1] for row in matches[offset:offset + limit]], "total": len(matches),
                "next_offset": offset + limit if offset + limit < len(matches) else None,
                "excluded_stale_pages": len(excluded), "excluded_page_ids": excluded[:100],
                "validation_scope": "matching_candidates", "candidates_found": len(candidates),
                "pages_validated": checked,
                "search_index": search_index,
                "method": "indexed character grams, casefolded literal and whitespace-insensitive matching "
                          "with explicit query/page aliases; no embedding-based semantic ranking"}

    def search_terms(self, terms, limit=3):
        """Find pages for several literal terms and merge them into one preflight.

        ``search`` requires every whitespace-separated term to occur, so passing
        a natural-language question finds nothing. The preflight has no single
        query string: it has terms extracted by ``plan_terms``. Each term is
        searched independently, pages are merged by ``page_id`` and scored by
        the terms they matched; the result is a pointer list, not full pages.
        """
        if not isinstance(terms, list) or not 1 <= len(terms) <= 24:
            raise ValueError("terms must be a list of 1 to 24 literal terms")
        ResearchSessions._integer(limit, "limit", 1, 20)
        ordered = []
        for term in terms:
            if not isinstance(term, str) or not term.strip() or len(term) > 100:
                raise ValueError("each term must be a nonempty string of at most 100 characters")
            if term not in ordered:
                ordered.append(term)
        merged = {}
        for term in ordered:
            result = self.search(term, limit=limit)
            for row in result["results"]:
                validation = row.get("validation") or {}
                status = validation.get("status")
                if status not in ("current", "needs_review"):
                    continue
                entry = merged.setdefault(row["page_id"], {
                    "page_id": row["page_id"], "revision": row.get("revision"),
                    "title": row.get("title"), "kind": row.get("kind"),
                    "updated_at": row.get("updated_at"), "score": 0.0,
                    "matched_terms": [], "summary": "",
                })
                entry["score"] += len(term) + (5 if term.casefold() in (row.get("title") or "").casefold() else 0)
                entry["matched_terms"].append(term)
                if not entry["summary"]:
                    entry["summary"] = " ".join((row.get("snippet") or "").split())[:200]
                issues = validation.get("issues") or []
                # A page is as fresh as its worst matching validation. Do not
                # let a later term with a cached/current view downgrade an
                # earlier needs_review status.
                if entry.get("status") == "needs_review" or status == "needs_review":
                    entry["status"] = "needs_review"
                else:
                    entry["status"] = status
                entry["issue_count"] = max(entry.get("issue_count", 0), len(issues))
                entry["expired_count"] = max(entry.get("expired_count", 0),
                                             sum(1 for issue in issues
                                                 if issue.get("code") == "source_capture_expired"))
        for entry in merged.values():
            actions = ["wiki_get"]
            if entry.get("status") == "needs_review":
                actions.append("wiki_acknowledge")
                if entry.get("expired_count"):
                    actions.append("wiki_refresh")
            entry["actions"] = actions
            entry["score"] = round(entry["score"], 6)
            entry["matched_terms"] = list(dict.fromkeys(entry["matched_terms"]))
        return sorted(merged.values(), key=lambda entry: (-entry["score"], entry["page_id"]))[:limit]

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
                characters = citation.get("characters")
                suffix = " · %s characters" % characters if characters is not None else ""
                lines.extend(["Source %s · %s · Retrieved %s%s" % (citation["source_id"], citation["url"],
                                                                   self._retrieved_at(citation) or "unknown", suffix),
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
