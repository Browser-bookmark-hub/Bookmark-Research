"""Durable, host-led research: bounded retrieval, grounded claims and reports.

The calling model plans and interprets evidence. This module does not run a model
or an autonomous background worker. Every network operation has a durable intent
and an idempotency key; a lost response is never silently submitted again.
"""

import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from archive import SourceArchive
from settings import Settings


class ResearchSessions:
    """Keep research artifacts outside the plugin and original canvas packages."""

    DEFAULT_BUDGET = {"max_search_calls": 16, "max_fetch_calls": 12, "max_rounds": 8}
    LIMITS = {"max_search_calls": 120, "max_fetch_calls": 80, "max_rounds": 40}
    PROVIDERS = ("exa", "parallel", "tavily")

    def __init__(self, directory=None, settings=None, engine=None, db_path=None):
        self.settings = settings if settings is not None else Settings()
        self.directory = Settings.external_path(
            str(directory or (Settings.data_directory() / "research")), "Research directory")
        self.engine = engine
        self.db_path = Path(db_path) if db_path is not None else Settings.data_directory() / "index.sqlite3"

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _text(value, label, maximum=4000):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
            raise ValueError(label + " must be a nonempty string of at most %s characters" % maximum)
        return value.strip()

    @classmethod
    def _identifier(cls, value, label):
        value = cls._text(value, label, 80)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            raise ValueError(label + " must use letters, digits, dots, hyphens or underscores")
        return value

    @classmethod
    def _providers(cls, value):
        if (not isinstance(value, list) or not 1 <= len(value) <= 3
                or any(not isinstance(p, str) or p not in cls.PROVIDERS for p in value)
                or len(set(value)) != len(value)):
            raise ValueError("providers must select exa, parallel and/or tavily without duplicates")
        return value[:]

    @staticmethod
    def _integer(value, label, minimum, maximum):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("%s must be an integer between %s and %s" % (label, minimum, maximum))
        return value

    @classmethod
    def _question(cls, value):
        if not isinstance(value, dict) or set(value) != {"id", "question"}:
            raise ValueError("Each question must contain id and question only")
        return {"id": cls._identifier(value["id"], "Question id"),
                "question": cls._text(value["question"], "Question"),
                "status": "open", "answer": None, "claim_ids": [], "gap": None}

    def _path(self, research_id):
        if not isinstance(research_id, str) or not re.fullmatch(r"r-[a-f0-9]{16}", research_id):
            raise ValueError("Invalid research_id")
        path = self.directory / research_id
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise ValueError("Research session must stay inside its data directory")
        return Settings.external_path(str(path), "Research session")

    def _load(self, research_id):
        path = self._path(research_id)
        state_path = path / "state.json"
        if state_path.is_symlink():
            raise ValueError("Research state must not be a symlink")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("schema_version") != 1 or state.get("research_id") != research_id:
            raise ValueError("Unsupported or inconsistent research state")
        # A complete receipt is an atomic commit record. Materialize it if the
        # process exited between receipt publication and the state checkpoint.
        # Every later mutation loads this view before assigning new source IDs.
        for operation in state["operations"]:
            if operation["status"] != "pending":
                continue
            receipt = path / self._receipt_file(operation["id"])
            if not receipt.is_file():
                continue
            result = json.loads(self._artifact(path, str(receipt.relative_to(path))).read_text(encoding="utf-8"))
            commit = result.get("_commit")
            if not isinstance(commit, dict):
                continue
            completed = commit.get("operation", {})
            if (result.get("research_id") != research_id or result.get("operation_id") != operation["id"]
                    or completed.get("id") != operation["id"] or completed.get("digest") != operation["digest"]
                    or completed.get("status") not in ("ok", "partial", "error")):
                raise ValueError("Research receipt does not match its pending operation")
            for source in commit.get("sources", []):
                prior = next((row for row in state["sources"] if row["id"] == source["id"]), None)
                if prior is not None and prior != source:
                    raise ValueError("Research receipt conflicts with an existing source ID")
                if prior is None:
                    state["sources"].append(source)
            operation.update(completed)
            state["updated_at"] = completed["finished_at"]
        return path, state

    @staticmethod
    def _receipt_file(operation_id):
        return "operations/" + hashlib.sha256(operation_id.encode()).hexdigest()[:24] + ".json"

    @staticmethod
    def _write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".research-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(value if isinstance(value, str) else
                             json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _save(self, path, state):
        state["updated_at"] = self._now()
        self._write(path / "state.json", state)

    def _web(self):
        if self.engine is None:
            from web_search import SearchProviders
            self.engine = SearchProviders(settings=self.settings)
        return self.engine

    @staticmethod
    def _active(state):
        if state["status"] == "incomplete":
            raise ValueError("Research has an incomplete report; use research_record kind=resume with a reason to continue")
        if state["status"] != "active":
            raise ValueError("Research is closed; inspect its report or start a new session")

    @staticmethod
    def _find(rows, identifier, label):
        for row in rows:
            if row["id"] == identifier:
                return row
        raise ValueError("Unknown %s: %s" % (label, identifier))

    @staticmethod
    def _preview(section, row):
        value = copy.deepcopy(row)
        if section == "claims":
            for citation in value["citations"]:
                citation["quote_truncated"] = len(citation["quote"]) > 300
                citation["quote"] = citation["quote"][:300]
        if section == "sources":
            value["bookmark_ref_count"] = len(value.pop("bookmark_refs", []))
            if isinstance(value.get("title"), str):
                value["title"] = value["title"][:500]
        if section == "operations":
            value.pop("parameters", None)
        if section == "bookmark_context":
            value = {key: row[key] for key in ("source_id", "section_id", "item_id", "title", "url")}
        for field in ("answer", "question", "statement", "text", "title"):
            if isinstance(value.get(field), str) and len(value[field]) > 2000:
                value[field] = value[field][:2000]
                value[field + "_truncated"] = True
        return value

    def _summary(self, path, state):
        remaining = {key.removeprefix("max_"): state["budget"][key] - state["usage"][key.removeprefix("max_")]
                     for key in self.DEFAULT_BUDGET}
        collections = ("questions", "claims", "conflicts", "sources", "operations", "bookmark_context")
        return {"research_id": state["research_id"], "directory": str(path),
                "status": state["status"], "brief": state["brief"], "scope": state["scope"],
                "source_ids": state["source_ids"], "providers": state["providers"],
                "context_manifest": str(path / "context.json"),
                "created_at": state["created_at"], "updated_at": state["updated_at"],
                "budget": state["budget"], "usage": state["usage"], "remaining": remaining,
                **{section: [self._preview(section, row) for row in state.get(section, [])[:20]] for section in collections},
                "counts": {section: len(state.get(section, [])) for section in (*collections, "events")},
                "pagination": {section: {"total": len(state.get(section, [])), "next_offset": 20 if len(state.get(section, [])) > 20 else None}
                               for section in collections},
                "detail_note": "Overview includes at most 20 previews per collection. Use research_status section with offset/limit for full entries, research_source for page text.",
                "artifacts": state.get("artifacts"),
                "execution": "Host model must choose each next action; no background worker is running.",
                "budget_unit": "Reserved provider search/fetch tool attempts; search batches also consume a round. Failures and unknown outcomes keep their reservation.",
                "evidence_note": "Quotes are checked against saved extracts. Relevance, factual support and independence require model review; provider agreement is not confirmation."}

    def _bookmark_context(self, references):
        if references is None:
            return []
        if not isinstance(references, list) or len(references) > 100:
            raise ValueError("bookmark_refs must be a list of at most 100 bookmark references")
        for reference in references:
            if not isinstance(reference, dict) or set(reference) != {"source_id", "section_id", "item_id"}:
                raise ValueError("Each bookmark_ref requires source_id, section_id and item_id only")
            for name, value in reference.items():
                self._text(value, name, 512)
        if not references:
            return []
        if not self.db_path.is_file():
            raise ValueError("Sync the bookmark package before selecting bookmark_refs")
        from bookmark_index import BookmarkIndex
        context = []
        with BookmarkIndex(self.db_path) as index:
            for reference in references:
                value = index.context(reference["source_id"], section=reference["section_id"], item_id=reference["item_id"])
                items = [item for item in value["items"] if item["item_type"] == "bookmark"]
                if len(items) != 1:
                    raise ValueError("bookmark_ref must identify one bookmark in its source and section")
                item = items[0]
                record = {**reference, "canonical_section_id": item["section_id"],
                          "title": item["title"], "url": item["url"], "path": item["path"],
                          "section_label": item["section_label"], "index_state": "last_synchronized",
                          "memberships": [{key: row[key] for key in ("group_id", "node_id")}
                                          for row in value["memberships"]],
                          "edges": [{key: row[key] for key in ("edge_id", "from_node", "to_node", "direction", "label")}
                                    for row in value["edges"]]}
                if record not in context:
                    context.append(record)
        return context

    def start(self, brief, questions, budget=None, providers=None, scope="", source_ids=None, bookmark_refs=None):
        brief = self._text(brief, "Research brief", 12000)
        if not isinstance(questions, list) or not 1 <= len(questions) <= 24:
            raise ValueError("questions must contain 1 to 24 questions")
        rows = [self._question(question) for question in questions]
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError("Question ids must be unique")
        if budget is not None and (not isinstance(budget, dict) or set(budget) - set(self.DEFAULT_BUDGET)):
            raise ValueError("Unknown research budget fields")
        selected_budget = {**self.DEFAULT_BUDGET, **(budget or {})}
        for key, limit in selected_budget.items():
            self._integer(limit, key, 0, self.LIMITS[key])
        names = self._providers(providers if providers is not None else self.settings.load()["search"]["providers"])
        if not isinstance(scope, str) or len(scope) > 12000 or "\x00" in scope:
            raise ValueError("scope must be a string of at most 12000 characters")
        source_ids = [] if source_ids is None else source_ids
        if not isinstance(source_ids, list) or len(source_ids) > 100:
            raise ValueError("source_ids must be a list of at most 100 local source labels")
        source_ids = list(dict.fromkeys(self._text(value, "Source id", 512) for value in source_ids))
        bookmark_context = self._bookmark_context(bookmark_refs)
        source_ids = list(dict.fromkeys(source_ids + [entry["source_id"] for entry in bookmark_context]))
        research_id = "r-" + uuid.uuid4().hex[:16]
        path = self._path(research_id)
        state = {"schema_version": 1, "research_id": research_id, "status": "active",
                 "brief": brief, "scope": scope, "source_ids": source_ids, "providers": names,
                 "bookmark_context": bookmark_context,
                 "created_at": self._now(), "budget": selected_budget,
                 "usage": {"search_calls": 0, "fetch_calls": 0, "rounds": 0},
                 "questions": rows, "claims": [], "conflicts": [], "sources": [],
                 "operations": [], "events": []}
        path.mkdir(parents=True, mode=0o700)
        self._write(path / "context.json", {"schema_version": 1, "captured_at": self._now(),
                    "kind": "local_bookmark_metadata", "bookmarks": bookmark_context,
                    "boundary": "Explicit selection from the last synchronized index; never automatically sent to web providers."})
        self._save(path, state)
        return self._summary(path, state)

    def status(self, research_id=None, section=None, offset=0, limit=20):
        self._integer(offset, "offset", 0, 10000000)
        self._integer(limit, "limit", 1, 100)
        if research_id is None:
            if section is not None:
                raise ValueError("section requires research_id")
            sessions = []
            for path in sorted(self.directory.glob("r-*/state.json")) if self.directory.exists() else []:
                _, state = self._load(path.parent.name)
                sessions.append({key: state[key] for key in
                                 ("research_id", "brief", "status", "updated_at", "usage")})
            return {"directory": str(self.directory), "sessions": sessions[offset:offset + limit], "total": len(sessions),
                    "next_offset": offset + limit if offset + limit < len(sessions) else None}
        path, state = self._load(research_id)
        if section is not None:
            if section not in ("questions", "claims", "sources", "operations", "conflicts", "bookmark_context", "events"):
                raise ValueError("Unknown research status section")
            rows, consumed = [], 0
            collection = state.get(section, [])
            for row in collection[offset:offset + limit]:
                size = len(json.dumps(row, ensure_ascii=False))
                if consumed + size > 900000:
                    if not rows:
                        rows.append({"oversized_entry": True, "state_file": str(path / "state.json"),
                                     "entry_index": offset, "note": "Read this unusually large entry from the state artifact."})
                    break
                rows.append(row)
                consumed += size
            next_offset = offset + len(rows)
            return {"research_id": research_id, "section": section, "items": rows, "total": len(collection),
                    "offset": offset, "next_offset": next_offset if next_offset < len(collection) else None}
        return self._summary(path, state)

    def _operation(self, research_id, operation_id, kind, parameters, cost, execute):
        operation_id = self._identifier(operation_id, "operation_id")
        path = self._path(research_id)
        if not (path / "state.json").is_file():
            raise ValueError("Unknown research session")
        digest = hashlib.sha256(json.dumps({"kind": kind, "parameters": parameters}, sort_keys=True,
                                          ensure_ascii=False).encode("utf-8")).hexdigest()
        # Hold the OS lock through the bounded request. Status reads remain available.
        # Once this lock is released after a crash, an explicit interruption record
        # can acknowledge a durable pending operation without resubmitting it.
        with Settings._update_lock(path / "state.json"):
            _, state = self._load(research_id)
            for previous in state["operations"]:
                if previous["id"] != operation_id:
                    continue
                if previous["digest"] != digest:
                    raise ValueError("operation_id already exists with different arguments")
                if previous.get("result_file"):
                    result = json.loads(self._artifact(path, previous["result_file"]).read_text(encoding="utf-8"))
                    return {**{key: value for key, value in result.items() if key != "_commit"}, "replayed": True}
                return {"research_id": research_id, "operation": previous, "replayed": True,
                        "next_action": "Inspect the saved operation; acknowledge interruption with research_record before using a new operation_id. No automatic retry or budget refund."}
            self._active(state)
            for key, amount in cost.items():
                if state["usage"][key] + amount > state["budget"]["max_" + key]:
                    raise ValueError("Research budget exhausted: " + key + "; synthesize available evidence or finish incomplete")
            operation = {"id": operation_id, "kind": kind, "digest": digest, "parameters": parameters,
                         "status": "pending", "reserved": cost, "started_at": self._now(), "result_file": None}
            state["operations"].append(operation)
            for key, amount in cost.items():
                state["usage"][key] += amount
            self._save(path, state)  # The reservation survives lost responses and process exits.
            source_count = len(state["sources"])
            try:
                payload = execute(path, state, operation)
                operation["status"] = payload.get("status", "ok")
            except (RuntimeError, OSError, ValueError) as error:
                payload = {"status": "error", "error": str(error)[:2000], "error_type": type(error).__name__}
                operation["status"] = "error"
            operation["finished_at"] = self._now()
            operation["result_file"] = self._receipt_file(operation_id)
            if "error" in payload:
                operation["error"] = payload["error"]
            if "usage" in payload:
                operation["actual_usage"] = payload["usage"]
            result = {"research_id": research_id, "operation_id": operation_id,
                      "replayed": False, **payload}
            self._write(path / operation["result_file"], {**result, "_commit": {
                "operation": copy.deepcopy(operation), "sources": state["sources"][source_count:]}})
            self._save(path, state)
            return result

    def search(self, research_id, operation_id, queries, providers=None, limit_per_target=5):
        _, state = self._load(research_id)
        if not isinstance(queries, list) or not 1 <= len(queries) <= 12:
            raise ValueError("queries must contain 1 to 12 question_id/query objects")
        targets = []
        for query in queries:
            if not isinstance(query, dict) or set(query) != {"question_id", "query"}:
                raise ValueError("Each query needs question_id and query only")
            self._find(state["questions"], query["question_id"], "question")
            row = {"target": query["question_id"], "query": self._text(query["query"], "Query", 2000)}
            if row not in targets:
                targets.append(row)
        names = self._providers(providers if providers is not None else state["providers"])
        self._integer(limit_per_target, "limit_per_target", 1, 20)
        parameters = {"targets": targets, "providers": names, "limit_per_target": limit_per_target}

        def execute(path, current, operation):
            result = self._web().search(**parameters)
            success = result.get("successful_provider_count", 0)
            failed = any(row.get("status") == "error" for row in result.get("batches", []))
            return {"status": "partial" if success and failed else "ok" if success else "error",
                    "result": result, "usage": result.get("usage", {})}

        return self._operation(research_id, operation_id, "search", parameters,
                               {"search_calls": len(targets) * len(names), "rounds": 1}, execute)

    def fetch(self, research_id, operation_id, question_id, urls, provider=None, max_characters=12000):
        _, state = self._load(research_id)
        self._find(state["questions"], question_id, "question")
        name = provider if provider is not None else state["providers"][0]
        self._providers([name])
        self._integer(max_characters, "max_characters", 100, 100000)
        if not isinstance(urls, list) or not 1 <= len(urls) <= 8:
            raise ValueError("urls must contain 1 to 8 HTTP(S) URLs")
        for url in urls:
            self._text(url, "URL", 8192)
            SourceArchive._key(url)
        urls = list(dict.fromkeys(urls))
        parameters = {"question_id": question_id, "urls": urls, "provider": name,
                      "max_characters": max_characters}

        def execute(path, current, operation):
            fetched = self._web().fetch(urls, provider=name, archive=False, max_characters=max_characters)
            if "result" not in fetched:
                return {"status": "error", "error": fetched.get("error", "Provider returned no response"),
                        "error_kind": fetched.get("error_kind", "no_response"),
                        "retryable": fetched.get("retryable", False), "usage": fetched.get("usage", {}),
                        "provider_outcome": fetched}
            try:
                archive = SourceArchive(path / "evidence").save(fetched)
            except (OSError, ValueError) as error:
                # Preserve the actual response in the operation receipt when page
                # archival fails. Never repeat a completed retrieval to fix storage.
                return {"status": "error", "error": str(error), "error_kind": "archive_error",
                        "usage": fetched.get("usage", {}), "provider_outcome": fetched}
            sources = []
            for page in archive["pages"]:
                source = {"id": "s%s" % (len(current["sources"]) + 1),
                          "question_id": question_id, "operation_id": operation_id,
                          "url": page["requested_url"], "canonical_url": SourceArchive._key(page["requested_url"]),
                          "provider": name, "retrieved_at": fetched["retrieved_at"],
                          "title": page["title"], "extraction_status": page["extraction_status"],
                          "content_kind": page["content_kind"], "completeness": page["completeness"],
                          "possibly_truncated": page.get("possibly_truncated", False),
                          "published_at": page.get("provider_published_at"), "crawled_at": page.get("provider_crawled_at"),
                          "sha256": page["sha256"],
                          "body_file": str(Path(page["body_path"]).relative_to(path)) if page["body_path"] else None,
                          "manifest_file": str(Path(archive["manifest_path"]).relative_to(path)),
                          "response_file": str(Path(archive["response_path"]).relative_to(path))}
                source["review"] = {"verdict": "unreviewed", "text": None}
                source["bookmark_refs"] = []
                for bookmark in current.get("bookmark_context", []):
                    try:
                        same_url = SourceArchive._key(bookmark["url"]) == source["canonical_url"]
                    except ValueError:
                        same_url = False
                    if same_url:
                        source["bookmark_refs"].append({key: bookmark[key] for key in ("source_id", "section_id", "item_id")})
                current["sources"].append(source)
                sources.append(source)
            extracted = sum(source["body_file"] is not None for source in sources)
            return {"status": "ok" if extracted == len(sources) else "partial" if extracted else "error",
                    "sources": sources, "usage": fetched.get("usage", {}),
                    "next_action": "Read saved text with research_source, then record exact quotes and findings. Unread search snippets cannot support a claim."}

        return self._operation(research_id, operation_id, "fetch", parameters, {"fetch_calls": 1}, execute)

    @staticmethod
    def _artifact(path, relative):
        target = (path / relative).resolve()
        if path not in target.parents:
            raise ValueError("Research artifact is outside the session")
        return target

    def _body(self, path, source):
        if not source["body_file"] or source["extraction_status"] != "extracted":
            raise ValueError("Source has no extracted page text; it cannot support a quoted claim")
        body = self._artifact(path, source["body_file"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != source["sha256"]:
            raise ValueError("Saved source hash changed; fetch a new snapshot before citing it")
        return body.decode("utf-8")

    def source(self, research_id, source_id, offset=0, limit=12000):
        self._integer(offset, "offset", 0, 10000000)
        self._integer(limit, "limit", 1, 50000)
        path, state = self._load(research_id)
        source = self._find(state["sources"], source_id, "source")
        body = self._body(path, source)
        return {"research_id": research_id, "source": source, "offset": offset,
                "text": body[offset:offset + limit], "total_characters": len(body),
                "next_offset": offset + limit if offset + limit < len(body) else None}

    def _citations(self, path, state, citations, allow_rejected=False):
        if not isinstance(citations, list) or not 1 <= len(citations) <= 12:
            raise ValueError("A claim needs 1 to 12 citations from fetched sources")
        checked = []
        for citation in citations:
            if not isinstance(citation, dict) or set(citation) != {"source_id", "quote"}:
                raise ValueError("Each citation needs source_id and quote only")
            source = self._find(state["sources"], citation["source_id"], "source")
            if source.get("review", {}).get("verdict") == "rejected" and not allow_rejected:
                raise ValueError("Source was rejected during content review: " + source["id"])
            quote = self._text(citation["quote"], "Quote")
            if quote not in self._body(path, source):
                raise ValueError("Quote is absent from saved source " + source["id"])
            checked.append({"source_id": source["id"], "quote": quote,
                            "source_sha256": source["sha256"], "quote_verified": True})
        return checked

    def _claims(self, state, identifiers, minimum=1, allow_retracted=False):
        if not isinstance(identifiers, list) or not minimum <= len(identifiers) <= 100:
            raise ValueError("claim_ids must contain %s to 100 existing claim IDs" % minimum)
        for identifier in identifiers:
            claim = self._find(state["claims"], identifier, "claim")
            if claim.get("status") == "retracted" and not allow_retracted:
                raise ValueError("Retracted claims cannot support an answer or resolution")
            if not allow_retracted:
                for citation in claim["citations"]:
                    source = self._find(state["sources"], citation["source_id"], "source")
                    if source.get("review", {}).get("verdict") == "rejected":
                        raise ValueError("Claim cites a rejected source; retract and replace the claim")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("claim_ids must be unique")
        return identifiers[:]

    def record(self, research_id, entry):
        if not isinstance(entry, dict):
            raise ValueError("entry must be an object")
        shapes = {"claim": {"kind", "question_id", "statement", "citations", "confidence", "inference"},
                  "answer": {"kind", "question_id", "answer", "claim_ids"},
                  "gap": {"kind", "question_id", "text"},
                  "conflict": {"kind", "claim_ids", "text"},
                  "resolution": {"kind", "conflict_id", "claim_ids", "text"},
                  "source_review": {"kind", "source_id", "verdict", "text"},
                  "retraction": {"kind", "claim_id", "text"},
                  "question": {"kind", "id", "question"},
                  "interruption": {"kind", "operation_id", "text"},
                  "resume": {"kind", "text"}}
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in shapes or set(entry) - shapes[kind]:
            raise ValueError("Unknown research entry kind or fields")
        path = self._path(research_id)
        if not (path / "state.json").is_file():
            raise ValueError("Unknown research session")
        with Settings._update_lock(path / "state.json"):
            _, state = self._load(research_id)
            if kind != "resume":
                self._active(state)
            if len(state["events"]) >= 500:
                raise ValueError("Research event limit reached; finish this session")
            question = self._find(state["questions"], entry.get("question_id"), "question") if kind in ("claim", "answer", "gap") else None
            if kind == "resume":
                if state["status"] != "incomplete":
                    raise ValueError("Only an incomplete report can be resumed; active sessions already accept steps")
                reason = self._text(entry.get("text"), "Resume reason")
                snapshot = uuid.uuid4().hex[:12]
                artifacts = {}
                # Keep earlier deliverables in the session root so their
                # relative evidence links still resolve after a later finish.
                for name, suffix in (("report", ".md"), ("sources", ".json"), ("state", ".json")):
                    saved = path / (name + "-" + snapshot + suffix)
                    self._write(saved, self._artifact(path, name + suffix).read_text(encoding="utf-8"))
                    artifacts[name] = str(saved)
                recorded = {"status": "active", "text": reason, "previous_status": "incomplete",
                            "previous_artifacts": artifacts}
                state["status"] = "active"
                for field in ("summary", "limitations", "finished_at", "artifacts"):
                    state.pop(field, None)
            elif kind == "claim":
                confidence = entry.get("confidence", "medium")
                if confidence not in ("low", "medium", "high") or type(entry.get("inference", False)) is not bool:
                    raise ValueError("Invalid confidence or inference field")
                if len(state["claims"]) >= 100:
                    raise ValueError("Research claim limit reached")
                recorded = {"id": "c%s" % (len(state["claims"]) + 1), "question_id": question["id"],
                            "statement": self._text(entry.get("statement"), "Statement"),
                            "citations": self._citations(path, state, entry.get("citations")),
                            "confidence": confidence, "inference": entry.get("inference", False), "status": "active"}
                state["claims"].append(recorded)
            elif kind == "answer":
                claims = self._claims(state, entry.get("claim_ids"))
                if any(self._find(state["claims"], identifier, "claim")["question_id"] != question["id"] for identifier in claims):
                    raise ValueError("Answer claims must belong to this question")
                question.update(status="answered", answer=self._text(entry.get("answer"), "Answer", 12000),
                                claim_ids=claims, gap=None)
                recorded = question
            elif kind == "gap":
                question.update(status="unresolved", gap=self._text(entry.get("text"), "Evidence gap"))
                recorded = question
            elif kind == "question":
                if len(state["questions"]) >= 24:
                    raise ValueError("Research question limit reached")
                recorded = self._question({"id": entry.get("id"), "question": entry.get("question")})
                if any(row["id"] == recorded["id"] for row in state["questions"]):
                    raise ValueError("Question id already exists")
                state["questions"].append(recorded)
            elif kind == "conflict":
                recorded = {"id": "x%s" % (len(state["conflicts"]) + 1), "status": "open",
                            "claim_ids": self._claims(state, entry.get("claim_ids"), minimum=2, allow_retracted=True),
                            "text": self._text(entry.get("text"), "Conflict"), "resolution": None}
                state["conflicts"].append(recorded)
            elif kind == "resolution":
                recorded = self._find(state["conflicts"], entry.get("conflict_id"), "conflict")
                recorded.update(status="resolved", resolution={"text": self._text(entry.get("text"), "Resolution"),
                                "claim_ids": self._claims(state, entry.get("claim_ids"))})
            elif kind == "source_review":
                verdict = entry.get("verdict")
                if verdict not in ("accepted", "rejected", "uncertain"):
                    raise ValueError("verdict must be accepted, rejected or uncertain")
                recorded = self._find(state["sources"], entry.get("source_id"), "source")
                recorded["review"] = {"verdict": verdict, "text": self._text(entry.get("text"), "Source review")}
                if verdict == "rejected":
                    affected = {claim["id"] for claim in state["claims"]
                                if any(citation["source_id"] == recorded["id"] for citation in claim["citations"])}
                    for question in state["questions"]:
                        if affected.intersection(question["claim_ids"]):
                            question.update(status="unresolved", gap="A supporting source was rejected; review and replace affected claims.")
                    for conflict in state["conflicts"]:
                        if conflict["resolution"] and affected.intersection(conflict["resolution"]["claim_ids"]):
                            conflict["status"] = "open"
            elif kind == "retraction":
                recorded = self._find(state["claims"], entry.get("claim_id"), "claim")
                recorded.update(status="retracted", retraction=self._text(entry.get("text"), "Retraction reason"))
                for question in state["questions"]:
                    if recorded["id"] in question["claim_ids"]:
                        question.update(status="unresolved", gap="A supporting claim was retracted; a revised answer is needed.")
                for conflict in state["conflicts"]:
                    if conflict["resolution"] and recorded["id"] in conflict["resolution"]["claim_ids"]:
                        conflict["status"] = "open"
            else:
                recorded = self._find(state["operations"], entry.get("operation_id"), "operation")
                if recorded["status"] != "pending":
                    raise ValueError("Only an interrupted pending operation can be acknowledged")
                recorded.update(status="unknown_outcome", explanation=self._text(entry.get("text"), "Interruption explanation"))
            state["events"].append({"at": self._now(), "kind": kind, "value": copy.deepcopy(recorded)})
            self._save(path, state)
            return {"research_id": research_id, "kind": kind, "recorded": recorded}

    def finish(self, research_id, summary, status="completed", limitations=None):
        summary = self._text(summary, "Summary", 16000)
        if status not in ("completed", "incomplete", "cancelled"):
            raise ValueError("status must be completed, incomplete or cancelled")
        limitations = [] if limitations is None else limitations
        if not isinstance(limitations, list) or len(limitations) > 100:
            raise ValueError("limitations must be a list of at most 100 strings")
        limitations = [self._text(item, "Limitation") for item in limitations]
        path = self._path(research_id)
        if not (path / "state.json").is_file():
            raise ValueError("Unknown research session")
        with Settings._update_lock(path / "state.json"):
            _, state = self._load(research_id)
            self._active(state)
            if status == "completed":
                if any(question["status"] != "answered" for question in state["questions"]):
                    raise ValueError("Unanswered research questions remain; record answers or finish incomplete")
                if any(conflict["status"] == "open" for conflict in state["conflicts"]):
                    raise ValueError("Unresolved evidence conflicts remain; resolve them or finish incomplete")
                if any(operation["status"] == "pending" for operation in state["operations"]):
                    raise ValueError("An interrupted operation needs acknowledgement before completion")
                for question in state["questions"]:
                    self._claims(state, question["claim_ids"])
            # A report must never cite a missing or altered extract, even when partial.
            for claim in state["claims"]:
                self._citations(path, state, [{"source_id": c["source_id"], "quote": c["quote"]}
                                             for c in claim["citations"]], allow_rejected=claim.get("status") == "retracted")
            state.update(status=status, summary=summary, limitations=limitations, finished_at=self._now())
            state["artifacts"] = {"report": str(path / "report.md"), "sources": str(path / "sources.json"),
                                  "state": str(path / "state.json"), "context": str(path / "context.json")}
            self._write(path / "report.md", self._report(state))
            self._write(path / "sources.json", {"schema_version": 1, "research_id": research_id,
                        "status": status, "sources": state["sources"], "claims": state["claims"],
                        "conflicts": state["conflicts"], "operations": state["operations"],
                        "questions": state["questions"], "limitations": limitations})
            self._save(path, state)
            return self._summary(path, state)

    @staticmethod
    def _report(state):
        lines = ["# " + state["brief"], "", "Status: **%s** · %s" % (state["status"], state["finished_at"]),
                 "", state["summary"], "", "## Scope", "", state["scope"] or "See the research questions below.",
                 "", "Local source labels: " + (", ".join(state["source_ids"]) or "None"),
                 "", "[Selected bookmark context](context.json)", "", "## Research questions", ""]
        for question in state["questions"]:
            references = " ".join("[%s](#claim-%s)" % (identifier, identifier) for identifier in question["claim_ids"])
            answer = question["answer"] or "No supported answer recorded."
            if question["answer"] and question["status"] != "answered":
                answer = "Previous answer (requires revision): " + answer
            lines.extend(["### " + question["id"] + ": " + question["question"], "",
                          "Status: " + question["status"], "",
                          answer + " " + references, ""])
            if question["gap"]:
                lines.extend(["Unresolved: " + question["gap"], ""])
        lines.extend(["## Claims and evidence", ""])
        for claim in state["claims"]:
            lines.extend(["### Claim " + claim["id"], "", "%s (confidence: %s; %s; status: %s)" % (claim["statement"], claim["confidence"],
                          "model inference" if claim["inference"] else "source-backed finding", claim.get("status", "active")), ""])
            if claim.get("retraction"):
                lines.extend(["Retracted: " + claim["retraction"], ""])
            for citation in claim["citations"]:
                lines.extend(["Source [%s](#source-%s); exact saved quote:" % (citation["source_id"], citation["source_id"]), ""])
                lines.extend("> " + line for line in citation["quote"].splitlines())
                lines.append("")
        lines.extend(["## Conflicts", ""])
        for conflict in state["conflicts"]:
            lines.extend(["- %s (%s): %s — claims %s" % (conflict["id"], conflict["status"], conflict["text"],
                                                       ", ".join("[%s](#claim-%s)" % (identifier, identifier) for identifier in conflict["claim_ids"]))])
            if conflict["resolution"]:
                references = ", ".join("[%s](#claim-%s)" % (identifier, identifier) for identifier in conflict["resolution"]["claim_ids"])
                lines.append("  Resolution: " + conflict["resolution"]["text"] + " (" + references + ")")
        if not state["conflicts"]:
            lines.append("No conflicts recorded; this does not prove that none exist.")
        lines.extend(["", "## Limitations and retrieval coverage", "",
                      "Saved text is a provider extract or excerpt with unknown completeness and origin freshness. Retrieval dates are not publication dates. Multiple providers returning the same URL are one page, not independent confirmation.", ""])
        lines.extend("- " + limitation for limitation in state["limitations"])
        for operation in state["operations"]:
            if operation["status"] != "ok":
                lines.append("- %s (%s): %s; inspect %s" % (operation["id"], operation["kind"], operation["status"],
                                                           operation["result_file"] or "state.json"))
        lines.extend(["", "Budget reservations: " + json.dumps(state["usage"], ensure_ascii=False), "",
                      "## Sources", ""])
        for source in state["sources"]:
            lines.extend(["### Source " + source["id"], "", source["url"], "",
                          "Provider: %s · Retrieved: %s · Status: %s · Kind: %s" %
                          (source["provider"], source["retrieved_at"], source["extraction_status"], source["content_kind"]), "",
                          "Content review: " + source.get("review", {}).get("verdict", "unreviewed") +
                          (" — " + source["review"]["text"] if source.get("review", {}).get("text") else ""), "",
                          "[Manifest](%s) · [Actual response](%s)" % (source["manifest_file"], source["response_file"])])
            if source["body_file"]:
                lines.append(" · [Saved text](%s) · SHA-256: `%s`" % (source["body_file"], source["sha256"]))
            lines.append("")
        resumes = [event["value"] for event in state["events"] if event["kind"] == "resume"]
        if resumes:
            lines.extend(["## Earlier reports", ""])
            for resumed in resumes:
                lines.append("- [Previous incomplete report](%s): %s" %
                             (Path(resumed["previous_artifacts"]["report"]).name, resumed["text"]))
            lines.append("")
        return "\n".join(lines) + "\n"
