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
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from archive import SourceArchive
from research_coverage import ResearchCoverage
from settings import Settings


class ResearchSessions:
    """Keep research artifacts outside the plugin and original canvas packages."""

    DEFAULT_BUDGET = {"max_search_calls": 16, "max_fetch_calls": 12, "max_rounds": 8}
    LIMITS = {"max_search_calls": 120, "max_fetch_calls": 80, "max_rounds": 40}
    FETCH_BATCH_SIZE = 8
    RECORD_BATCH_SIZE = 50
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
        if state.get("schema_version") not in (1, 2) or state.get("research_id") != research_id:
            raise ValueError("Unsupported or inconsistent research state")
        if state["schema_version"] == 2:
            manifest_bytes = self._artifact(path, "inventory.json").read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != state.get("inventory_manifest_sha256"):
                raise ValueError("Frozen input inventory hash changed")
            manifest = json.loads(manifest_bytes)
            scope = state.get("source_scope", {})
            selected = scope.get("selected_inventory_ids", [])
            entries = {entry["id"]: entry for entry in manifest["entries"]}
            if (len(set(selected)) != len(selected) or set(selected) - entries.keys()
                    or scope.get("input_version") != manifest["input_version"]
                    or (scope.get("mode") == "whole" and set(selected) != entries.keys())
                    or state.get("inventory") != [entries[identifier] for identifier in selected]):
                raise ValueError("Research scope is inconsistent with its frozen complete inventory")
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
        if section in ("claims", "inventory_reviews"):
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
        if section == "inventory":
            value["instance_count"] = len(value.pop("instances"))
        for field in ("answer", "question", "statement", "text", "title"):
            if isinstance(value.get(field), str) and len(value[field]) > 2000:
                value[field] = value[field][:2000]
                value[field + "_truncated"] = True
        return value

    @staticmethod
    def _scope_preview(path, scope):
        """Bound response metadata without changing frozen scope or saved artifacts."""
        if scope is None:
            return None
        preview = {}
        for field, value in scope.items():
            if isinstance(value, list):
                preview[field] = copy.deepcopy(value[:20])
                preview[field + "_total"] = len(value)
                preview[field + "_truncated"] = len(value) > 20
            else:
                preview[field] = copy.deepcopy(value)
        preview.update(artifact_path=str(path / "context.json"), artifact_json_pointer="/source_scope",
                       detail_note="Scope lists preview at most 20 entries; read the full source_scope from the artifact. "
                                   "Paginate research_inventory to read every selected item.")
        return preview

    def _summary(self, path, state):
        remaining = {key.removeprefix("max_"): state["budget"][key] - state["usage"][key.removeprefix("max_")]
                     for key in self.DEFAULT_BUDGET}
        collections = ("questions", "claims", "conflicts", "sources", "operations", "bookmark_context",
                       "inventory", "inventory_reviews", "external_runs")
        coverage = self._coverage(path, state)
        coverage["source_scope"] = self._scope_preview(path, state.get("source_scope"))
        return {"research_id": state["research_id"], "directory": str(path),
                "status": state["status"], "brief": state["brief"], "scope": state["scope"],
                "source_ids": state["source_ids"], "providers": state["providers"],
                "context_manifest": str(path / "context.json"),
                "inventory_manifest": str(path / "inventory.json") if state.get("source_scope") else None,
                "source_scope": coverage["source_scope"],
                "coverage": {key: value for key, value in coverage.items() if key != "rows"},
                "created_at": state["created_at"], "updated_at": state["updated_at"],
                "budget": state["budget"], "usage": state["usage"], "remaining": remaining,
                "initial_fetch_plan": state.get("initial_fetch_plan"),
                **{section: [self._preview(section, row) for row in state.get(section, [])[:20]] for section in collections},
                "counts": {section: len(state.get(section, [])) for section in (*collections, "events")},
                "pagination": {section: {"total": len(state.get(section, [])), "next_offset": 20 if len(state.get(section, [])) > 20 else None}
                               for section in collections},
                "detail_note": "Overview includes at most 20 previews per collection. Use research_status section with offset/limit for full entries, research_source for page text.",
                "artifacts": state.get("artifacts"),
                "execution": "Host model must choose each next action; no background worker is running.",
                "budget_unit": "Reserved provider search/fetch tool attempts; search batches also consume a round. Failures and unknown outcomes keep their reservation.",
                "evidence_note": "Quotes are checked against saved extracts. Relevance, factual support and independence require model review; provider agreement is not confirmation."}

    def _bookmark_scope(self, source_ids, references, scope_mode, inventory_ids):
        references = [] if references is None else references
        if not isinstance(references, list) or len(references) > 100:
            raise ValueError("bookmark_refs must be a list of at most 100 bookmark references")
        for reference in references:
            if not isinstance(reference, dict) or set(reference) != {"source_id", "section_id", "item_id"}:
                raise ValueError("Each bookmark_ref requires source_id, section_id and item_id only")
            for name, value in reference.items():
                self._text(value, name, 512)
        if scope_mode not in ("whole", "subset"):
            raise ValueError("scope_mode must be whole or subset")
        if inventory_ids is not None:
            if not isinstance(inventory_ids, list) or not inventory_ids:
                raise ValueError("inventory_ids must be a nonempty list")
            inventory_ids = [self._identifier(value, "Inventory id") for value in inventory_ids]
            if len(set(inventory_ids)) != len(inventory_ids):
                raise ValueError("inventory_ids must be unique")
            if scope_mode != "subset":
                raise ValueError("inventory_ids selection requires explicit scope_mode=subset")
        source_ids = sorted(set(source_ids + [reference["source_id"] for reference in references]))
        if source_ids:
            if not self.db_path.is_file():
                raise ValueError("Sync the bookmark package before selecting source_ids or bookmark_refs")
            from bookmark_index import BookmarkIndex
            with BookmarkIndex(self.db_path) as index:
                from source_manager import SourceManager
                manager = SourceManager(index)
                for source_id in source_ids:
                    update = manager.refresh(source_id)
                    if update["state"] not in ("current", "snapshot"):
                        raise ValueError("Source %s is %s; wait for a settled input before starting research" % (source_id, update["state"]))
                manifest = index.inventory(source_ids)
        else:
            manifest = {"schema_version": 1, "index_state": "none", "source_ids": [],
                        "input_version": hashlib.sha256(b"[]").hexdigest(),
                        "entries": [], "counts": {"unique_urls": 0, "bookmark_instances": 0},
                        **{key: [] for key in ("sources", "files", "sections", "folders", "nodes", "edges", "memberships")}}
        reference_ids = set()
        for reference in references:
            matches = []
            for entry in manifest["entries"]:
                for item in entry["instances"]:
                    selectors = {item["section_id"]}
                    selectors.update(appearance[key] for appearance in item["appearances"]
                                     for key in ("section_id", "label", "file_path"))
                    if (item["source_id"] == reference["source_id"] and item["item_id"] == reference["item_id"]
                            and reference["section_id"] in selectors):
                        matches.append(entry["id"])
            if len(matches) != 1:
                raise ValueError("bookmark_ref must identify one bookmark in its source and section")
            reference_ids.update(matches)
        all_ids = {entry["id"] for entry in manifest["entries"]}
        if scope_mode == "subset":
            if inventory_ids is not None and references:
                raise ValueError("Choose inventory_ids or bookmark_refs for an explicit subset, not both")
            selected = set(inventory_ids) if inventory_ids is not None else reference_ids
            if not selected or selected - all_ids:
                raise ValueError("An explicit subset needs existing inventory_ids or bookmark_refs")
        else:
            selected = all_ids
        entries = [entry for entry in manifest["entries"] if entry["id"] in selected]
        context = []
        for entry in entries:
            for item in entry["instances"]:
                record = {key: item[key] for key in ("source_id", "section_id", "item_id", "title", "url", "path", "section_label")}
                record.update(canonical_section_id=item["canonical_section_id"], inventory_id=entry["id"],
                              index_state="last_synchronized", memberships=[], edges=[])
                for appearance in item["appearances"]:
                    for key in ("memberships", "edges"):
                        for row in appearance[key]:
                            if row not in record[key]:
                                record[key].append(row)
                context.append(record)
        selection = {"mode": scope_mode if source_ids else "questions", "input_version": manifest["input_version"],
                     "input_url_count": len(manifest["entries"]), "selected_url_count": len(entries),
                     "input_instance_count": manifest["counts"]["bookmark_instances"],
                     "selected_instance_count": len(context),
                     "selected_inventory_ids": [entry["id"] for entry in entries],
                     "omitted_inventory_ids": sorted(all_ids - selected), "focus_bookmark_refs": references}
        return manifest, entries, context, selection

    def start(self, brief, questions, budget=None, providers=None, scope="", source_ids=None,
              bookmark_refs=None, scope_mode="whole", inventory_ids=None):
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
            raise ValueError("source_ids must be a list of at most 100 indexed package IDs")
        source_ids = list(dict.fromkeys(self._text(value, "Source id", 512) for value in source_ids))
        manifest, inventory, bookmark_context, selection = self._bookmark_scope(source_ids, bookmark_refs, scope_mode, inventory_ids)
        source_ids = manifest["source_ids"]
        minimum_fetch_calls = (len(inventory) + self.FETCH_BATCH_SIZE - 1) // self.FETCH_BATCH_SIZE
        explicit_fetch_budget = budget is not None and "max_fetch_calls" in budget
        if not explicit_fetch_budget and inventory:
            selected_budget["max_fetch_calls"] = min(self.LIMITS["max_fetch_calls"],
                max(self.DEFAULT_BUDGET["max_fetch_calls"], minimum_fetch_calls + self.DEFAULT_BUDGET["max_fetch_calls"]))
        fetch_limit = selected_budget["max_fetch_calls"]
        fetch_plan = {"selected_urls": len(inventory), "max_urls_per_call": self.FETCH_BATCH_SIZE,
                      "minimum_required": minimum_fetch_calls, "configured_limit": fetch_limit,
                      "hard_limit": self.LIMITS["max_fetch_calls"],
                      "budget_source": "explicit" if explicit_fetch_budget else "scope_default",
                      "additional_calls": max(0, fetch_limit - minimum_fetch_calls),
                      "call_shortfall": max(0, minimum_fetch_calls - fetch_limit),
                      "urls_beyond_capacity": max(0, len(inventory) - fetch_limit * self.FETCH_BATCH_SIZE),
                      "scope_preserved": True,
                      "basis": "Initial lower bound assuming full batches. Grouping, failures and supplementary reads can need more calls; imported evidence may need fewer."}
        research_id = "r-" + uuid.uuid4().hex[:16]
        path = self._path(research_id)
        state = {"schema_version": 2, "research_id": research_id, "status": "active",
                 "brief": brief, "scope": scope, "source_ids": source_ids, "providers": names,
                 "bookmark_context": bookmark_context,
                 "source_scope": selection, "inventory": inventory, "inventory_reviews": [], "external_runs": [],
                 "created_at": self._now(), "budget": selected_budget,
                 "initial_fetch_plan": fetch_plan,
                 "usage": {"search_calls": 0, "fetch_calls": 0, "rounds": 0},
                 "questions": rows, "claims": [], "conflicts": [], "sources": [],
                 "operations": [], "events": []}
        path.mkdir(parents=True, mode=0o700)
        self._write(path / "inventory.json", manifest)
        state["inventory_manifest_sha256"] = hashlib.sha256((path / "inventory.json").read_bytes()).hexdigest()
        self._write(path / "context.json", {"schema_version": 1, "captured_at": self._now(),
                    "kind": "local_bookmark_metadata", "bookmarks": bookmark_context, "source_scope": selection,
                    "boundary": "Frozen research scope from the last synchronized index; never automatically sent to web providers. Full input structure is in inventory.json."})
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
            if section not in ("questions", "claims", "sources", "operations", "conflicts", "bookmark_context", "events",
                               "inventory", "inventory_reviews", "external_runs"):
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
        result = self._summary(path, state)
        result["source_freshness"] = self.source_freshness(state=state)
        return result

    def source_freshness(self, research_id=None, state=None):
        """Compare current indexed input to frozen scope; never rewrite evidence."""
        if state is None:
            _, state = self._load(research_id)
        ids = state.get("source_ids", [])
        frozen = state.get("source_scope", {}).get("input_version")
        result = {"frozen_input_version": frozen, "current_input_version": None,
                  "state": "not_applicable" if not ids else "unknown", "requires_review": False if not ids else None,
                  "basis": "Last synchronized local index; no webpage refetch or inventory mutation"}
        if not ids or not frozen or not self.db_path.is_file():
            return result
        try:
            from bookmark_index import BookmarkIndex
            from source_manager import SourceManager
            with BookmarkIndex(self.db_path) as index:
                manager = SourceManager(index)
                with index.read_snapshot():
                    current = index.input_version(ids)
                    states = {source_id: manager.status(source_id)["source"]["state"] for source_id in ids}
            changed = current != frozen
            result.update(current_input_version=current, state="changed" if changed else "unchanged",
                          requires_review=changed, source_states=states)
        except (OSError, ValueError, sqlite3.Error) as exc:
            result["error"] = str(exc)[:1000]
        return result

    @staticmethod
    def _page(rows, offset, limit, artifact):
        page, size = [], 0
        for row in rows[offset:offset + limit]:
            length = len(json.dumps(row, ensure_ascii=False))
            if size + length > 900000:
                if not page:
                    page.append({"id": row["id"], "oversized_entry": True, "artifact_path": str(artifact),
                                 "note": "Read this full entry from the saved artifact by its stable ID."})
                break
            page.append(row)
            size += length
        following = offset + len(page)
        return {"items": page, "inventory_ids": [row["id"] for row in page], "offset": offset,
                "total": len(rows), "next_offset": following if following < len(rows) else None}

    def inventory(self, research_id, inventory_ids=None, offset=0, limit=100):
        self._integer(offset, "offset", 0, 10000000)
        self._integer(limit, "limit", 1, 100)
        path, state = self._load(research_id)
        rows = state.get("inventory", [])
        if inventory_ids is not None:
            if not isinstance(inventory_ids, list) or not 1 <= len(inventory_ids) <= 100:
                raise ValueError("inventory_ids must contain 1 to 100 IDs per read")
            identifiers = [self._identifier(value, "Inventory id") for value in inventory_ids]
            if len(set(identifiers)) != len(identifiers):
                raise ValueError("inventory_ids must be unique")
            for identifier in identifiers:
                self._find(rows, identifier, "inventory item")
            rows = [row for row in rows if row["id"] in identifiers]
        return {"research_id": research_id, "available": "source_scope" in state,
                "source_scope": self._scope_preview(path, state.get("source_scope")),
                "scope_total": len(state.get("inventory", [])),
                "manifest_path": str(path / "inventory.json") if "source_scope" in state else None,
                **self._page(rows, offset, limit, path / "inventory.json")}

    def _coverage(self, path, state):
        return ResearchCoverage(state, lambda source: self._body(path, source)).evaluate()

    def coverage(self, research_id, filter=None, offset=0, limit=100):
        self._integer(offset, "offset", 0, 10000000)
        self._integer(limit, "limit", 1, 100)
        selected = "all" if filter is None else filter
        if selected not in ResearchCoverage.FILTERS:
            raise ValueError("Unknown coverage filter")
        path, state = self._load(research_id)
        result = self._coverage(path, state)
        result["source_scope"] = self._scope_preview(path, result["source_scope"])
        rows = result.pop("rows")
        scope_total = len(rows)
        if selected != "all":
            rows = [row for row in rows if row[selected]]
        return {"research_id": research_id, "filter": selected, "scope_total": scope_total,
                **result, **self._page(rows, offset, limit, path / "state.json")}

    @staticmethod
    def _source_links(state, url):
        try:
            canonical = SourceArchive._key(url)
        except (ValueError, UnicodeError):
            canonical = None
        entries = [entry for entry in state.get("inventory", [])
                   if entry["original_url"] == url or (canonical is not None and entry["retrieval_url"] == canonical)]
        references = []
        if entries:
            for entry in entries:
                references.extend({key: item[key] for key in ("source_id", "section_id", "item_id")}
                                  for item in entry["instances"])
        else:
            # Legacy explicit-context sessions remain readable and useful.
            for bookmark in state.get("bookmark_context", []):
                try:
                    same_url = SourceArchive._key(bookmark["url"]) == canonical
                except (ValueError, UnicodeError):
                    same_url = bookmark["url"] == url
                if same_url:
                    references.append({key: bookmark[key] for key in ("source_id", "section_id", "item_id")})
        return [entry["id"] for entry in entries], references

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
        if not isinstance(urls, list) or not 1 <= len(urls) <= self.FETCH_BATCH_SIZE:
            raise ValueError("urls must contain 1 to %s HTTP(S) URLs" % self.FETCH_BATCH_SIZE)
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
                          "evidence_kind": "page",
                          "content_kind": page["content_kind"], "completeness": page["completeness"],
                          "possibly_truncated": page.get("possibly_truncated", False),
                          "published_at": page.get("provider_published_at"), "crawled_at": page.get("provider_crawled_at"),
                          "sha256": page["sha256"],
                          "body_file": str(Path(page["body_path"]).relative_to(path)) if page["body_path"] else None,
                          "manifest_file": str(Path(archive["manifest_path"]).relative_to(path)),
                          "response_file": str(Path(archive["response_path"]).relative_to(path))}
                source["review"] = {"verdict": "unreviewed", "text": None}
                source["inventory_ids"], source["bookmark_refs"] = self._source_links(current, source["url"])
                current["sources"].append(source)
                sources.append(source)
            extracted = sum(source["body_file"] is not None for source in sources)
            return {"status": "ok" if extracted == len(sources) else "partial" if extracted else "error",
                    "sources": sources, "usage": fetched.get("usage", {}),
                    "next_action": "Read saved text with research_source, then record exact quotes and findings. Unread search snippets cannot support a claim."}

        return self._operation(research_id, operation_id, "fetch", parameters, {"fetch_calls": 1}, execute)

    def import_evidence(self, research_id, operation_id, question_id, url, text, provenance,
                        inventory_ids=None, title=""):
        """Save host-read page text or a secondary report without fetching it.

        A report can cite original input IDs, but those references never count
        as reading the cited pages. All imported evidence starts unreviewed.
        """
        _, state = self._load(research_id)
        self._find(state["questions"], question_id, "question")
        url = self._text(url, "URL", 8192)
        self._text(text, "Imported text", 2000000)
        if not isinstance(title, str) or len(title) > 12000 or "\x00" in title:
            raise ValueError("title must be a string of at most 12000 characters")
        if not isinstance(provenance, dict) or provenance.get("kind") not in (
                "page", "archived_page", "local_document", "external_report"):
            raise ValueError("provenance.kind must be page, archived_page, local_document or external_report")
        try:
            serialized = json.dumps(provenance, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as error:
            raise ValueError("provenance must contain JSON metadata") from error
        if len(serialized) > 64000:
            raise ValueError("provenance metadata is too large")
        provenance = json.loads(serialized)
        kind = provenance["kind"]
        if kind == "external_report":
            canonical = url
        elif kind == "local_document" and url.startswith("file://"):
            canonical = url
        else:
            canonical = SourceArchive._key(url)
        if "provider" in provenance:
            self._text(provenance["provider"], "Provenance provider", 512)
        if "run_id" in provenance:
            self._text(provenance["run_id"], "External run id", 2000)
        supplied_ids = None
        if inventory_ids is not None:
            if not isinstance(inventory_ids, list):
                raise ValueError("inventory_ids must be a list")
            supplied_ids = list(dict.fromkeys(self._identifier(value, "Inventory id") for value in inventory_ids))
            for identifier in supplied_ids:
                self._find(state.get("inventory", []), identifier, "inventory item")
        linked_ids, _ = self._source_links(state, url)
        if kind != "external_report" and supplied_ids is not None and set(supplied_ids) - set(linked_ids):
            raise ValueError("Imported page URL does not match the selected original inventory URL")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if "text_sha256" in provenance and provenance["text_sha256"] != digest:
            raise ValueError("Imported text does not match provenance.text_sha256")
        parameters = {"question_id": question_id, "url": url, "text_sha256": digest, "title": title,
                      "provenance": provenance, "inventory_ids": supplied_ids}

        def execute(path, current, operation):
            capture = path / "evidence" / ("import-" + uuid.uuid4().hex[:16])
            imported_at = self._now()
            body_file, response_file, manifest_file = (capture / name for name in ("body.txt", "response.json", "manifest.json"))
            self._write(body_file, text)
            self._write(response_file, {"kind": "host_evidence_import", "url": url, "text": text,
                                        "title": title, "provenance": provenance, "imported_at": imported_at})
            identifiers, refs = self._source_links(current, url)
            if supplied_ids is not None:
                identifiers = supplied_ids
            source = {"id": "s%s" % (len(current["sources"]) + 1), "question_id": question_id,
                      "operation_id": operation_id, "url": url, "canonical_url": canonical,
                      "provider": provenance.get("provider", "host_import"),
                      "retrieved_at": provenance.get("retrieved_at"), "imported_at": imported_at,
                      "title": title, "extraction_status": "extracted", "evidence_kind":
                          "external_report" if kind == "external_report" else "local_document" if kind == "local_document" else "page",
                      "content_kind": kind if kind in ("external_report", "local_document") else "imported_page_text",
                      "completeness": "unknown", "possibly_truncated": True,
                      "published_at": provenance.get("published_at"), "crawled_at": provenance.get("crawled_at"),
                      "sha256": digest, "body_file": str(body_file.relative_to(path)),
                      "manifest_file": str(manifest_file.relative_to(path)), "response_file": str(response_file.relative_to(path)),
                      "provenance": provenance, "review": {"verdict": "unreviewed", "text": None},
                      "inventory_ids": [] if kind == "external_report" else identifiers,
                      "referenced_inventory_ids": (supplied_ids or []) if kind == "external_report" else [],
                      "bookmark_refs": [] if kind == "external_report" else refs}
            self._write(manifest_file, {"schema_version": 1, "kind": "host_evidence_import", "source": source})
            current["sources"].append(source)
            return {"status": "ok", "sources": [source], "next_action":
                    "Read and review the saved text. An imported report is one secondary source and does not mark its referenced original pages as read."}

        return self._operation(research_id, operation_id, "import_evidence", parameters, {}, execute)

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

    def _inventory_review(self, path, state, entry):
        identifier = self._identifier(entry.get("inventory_id"), "Inventory id")
        self._find(state.get("inventory", []), identifier, "inventory item")
        disposition = entry.get("disposition")
        if disposition not in ("reviewed", "excluded", "blocked"):
            raise ValueError("disposition must be reviewed, excluded or blocked")
        reason = entry.get("reason_code")
        if disposition == "excluded" and reason not in ("out_of_scope", "non_content"):
            raise ValueError("Excluded inputs need reason_code=out_of_scope or non_content and a specific explanation")
        if reason is not None:
            reason = self._identifier(reason, "Reason code")
        recorded = {"id": identifier, "inventory_id": identifier, "disposition": disposition,
                    "text": self._text(entry.get("text"), "Inventory review"), "reason_code": reason}
        for key, collection, maximum in (("question_ids", "questions", 24), ("source_ids", "sources", 12)):
            values = entry.get(key, [])
            if not isinstance(values, list) or len(values) > maximum:
                raise ValueError("%s must contain at most %s IDs" % (key, maximum))
            values = [self._identifier(value, key) for value in values]
            if len(set(values)) != len(values):
                raise ValueError(key + " must be unique")
            for value in values:
                self._find(state[collection], value, collection)
            recorded[key] = values
        recorded["claim_ids"] = self._claims(state, entry.get("claim_ids", []), minimum=0,
                                              allow_retracted=disposition != "reviewed")
        citations = entry.get("citations", [])
        if not isinstance(citations, list):
            raise ValueError("citations must be a list")
        recorded["citations"] = self._citations(path, state, citations, allow_rejected=disposition != "reviewed") if citations else []
        issues = ResearchCoverage(state, lambda source: self._body(path, source)).review_issues(recorded)
        if issues:
            raise ValueError("Inventory review is not substantiated: " + "; ".join(issues))
        previous = next((row for row in state.get("inventory_reviews", []) if row["inventory_id"] == identifier), None)
        if previous and all(previous.get(key) == value for key, value in recorded.items()):
            return previous, True
        recorded["updated_at"] = self._now()
        if previous is None:
            state.setdefault("inventory_reviews", []).append(recorded)
        else:
            previous.clear()
            previous.update(recorded)
        return recorded, False

    def _external_run(self, path, state, entry):
        identifier = self._identifier(entry.get("id"), "External reference id")
        provider = self._identifier(entry.get("provider"), "External provider")
        run_id = self._text(entry.get("run_id"), "External run id", 2000)
        status = entry.get("status")
        if status not in ("prepared", "pending", "queued", "in_progress", "completed", "cancelled", "error", "unknown_outcome"):
            raise ValueError("Unknown external run status")
        previous = next((row for row in state.get("external_runs", []) if row["id"] == identifier), None)
        if previous:
            remote_pattern = {"openai": r"resp_[A-Za-z0-9_-]{1,192}",
                              "parallel": r"trun_[A-Za-z0-9_-]{1,192}"}.get(provider)
            placeholder_transition = (remote_pattern and previous["run_id"] == previous["id"]
                and re.fullmatch(r"er-[a-f0-9]{24}", previous["id"])
                and previous["status"] in ("prepared", "pending", "unknown_outcome")
                and re.fullmatch(remote_pattern, run_id))
            local_prepared_transition = (not remote_pattern and previous["status"] == "prepared"
                and (previous["run_id"] == previous["id"] or previous["run_id"].startswith("local:")))
            if (previous["provider"] != provider or
                    previous["run_id"] != run_id and not (placeholder_transition or local_prepared_transition)):
                raise ValueError("External reference id already belongs to another provider or run_id")
            if status == "prepared" and previous["status"] != "prepared":
                raise ValueError("An observed external run cannot return to prepared; preserve its actual outcome")
        recorded = {**(previous or {}), "id": identifier, "provider": provider, "run_id": run_id,
                    "status": status, "text": self._text(entry.get("text"), "External observation")}
        result_text = None
        if "result" in entry:
            if not isinstance(entry["result"], dict):
                raise ValueError("External result must be a JSON object")
            try:
                result_text = json.dumps(entry["result"], ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
            except (ValueError, TypeError) as error:
                raise ValueError("External result must contain JSON data") from error
            if len(result_text) > 10000000:
                raise ValueError("External result is too large; use artifact_path for a saved file")
            digest = hashlib.sha256(result_text.encode("utf-8")).hexdigest()
            result_file = "external-runs/" + hashlib.sha256(identifier.encode()).hexdigest()[:24] + "-" + digest[:24] + ".json"
            recorded.update(result_file=result_file, result_path=str(path / result_file), result_sha256=digest)
        if "artifact_path" in entry:
            artifact = Settings.external_path(self._text(entry["artifact_path"], "External artifact path", 8192), "External result artifact")
            if not artifact.is_file():
                raise ValueError("External artifact_path must name an existing file outside source packages")
            recorded.update(artifact_path=str(artifact), artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())
        if previous and all(previous.get(key) == value for key, value in recorded.items()):
            return previous, True
        if result_text is not None:
            artifact = path / recorded["result_file"]
            if artifact.exists() and hashlib.sha256(artifact.read_bytes()).hexdigest() != recorded["result_sha256"]:
                raise ValueError("Saved external result artifact hash changed")
            if not artifact.exists():
                self._write(artifact, result_text)
        recorded["observed_at"] = self._now()
        if previous is None:
            state.setdefault("external_runs", []).append(recorded)
        else:
            previous.clear()
            previous.update(recorded)
        return recorded, False

    def record(self, research_id, entry=None, entries=None, batch_id=None):
        if (entry is None) == (entries is None):
            raise ValueError("Provide exactly one of entry or entries")
        if entries is not None:
            if not isinstance(entries, list) or not 1 <= len(entries) <= self.RECORD_BATCH_SIZE:
                raise ValueError("entries must contain 1 to %s objects" % self.RECORD_BATCH_SIZE)
        elif batch_id is not None:
            raise ValueError("batch_id is only supported with entries")
        digest = None
        if batch_id is not None:
            batch_id = self._identifier(batch_id, "Batch id")
            try:
                payload = json.dumps(entries, sort_keys=True, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError) as error:
                raise ValueError("entries must contain JSON data") from error
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        path = self._path(research_id)
        if not (path / "state.json").is_file():
            raise ValueError("Unknown research session")
        with Settings._update_lock(path / "state.json"):
            _, state = self._load(research_id)
            if entries is None:
                result = self._record_entry(path, state, entry)
                if not result.get("replayed"):
                    self._save(path, state)
                return result
            batches = state.get("record_batches", {})
            if batch_id is not None and batch_id in batches:
                previous = batches[batch_id]
                if previous["digest"] != digest:
                    raise ValueError("batch_id already used with different entries")
                return {**copy.deepcopy(previous["result"]), "replayed": True}
            if batch_id is not None and len(batches) >= max(500, 10 * len(state.get("inventory", []))):
                raise ValueError("Research record batch limit reached; finish this session")
            results = []
            for index, item in enumerate(entries):
                try:
                    # These two kinds write artifacts outside state.json and
                    # therefore cannot participate in this atomic state update.
                    if isinstance(item, dict) and item.get("kind") in ("resume", "external_run"):
                        raise ValueError("resume and external_run require a single entry call")
                    result = self._record_entry(path, state, item)
                except ValueError as error:
                    raise ValueError("entries[%s]: %s; no entries were saved" % (index, error)) from error
                results.append({"index": index, "kind": result["kind"], "id": result["recorded"]["id"],
                                "replayed": result.get("replayed", False)})
            response = {"research_id": research_id, "count": len(results), "results": results, "replayed": False}
            if batch_id is not None:
                response["batch_id"] = batch_id
                state.setdefault("record_batches", {})[batch_id] = {"digest": digest, "result": response}
            # All validation and in-batch dependencies run against the same
            # in-memory state. The entries and retry receipt commit together.
            self._save(path, state)
            return response

    def _record_entry(self, path, state, entry):
        research_id = state["research_id"]
        if not isinstance(entry, dict):
            raise ValueError("entry must be an object")
        shapes = {"claim": {"kind", "question_id", "statement", "citations", "confidence", "inference"},
                  "answer": {"kind", "question_id", "answer", "claim_ids"},
                  "gap": {"kind", "question_id", "text"},
                  "conflict": {"kind", "claim_ids", "text"},
                  "resolution": {"kind", "conflict_id", "claim_ids", "text"},
                  "source_review": {"kind", "source_id", "verdict", "text"},
                  "inventory_review": {"kind", "inventory_id", "disposition", "text", "question_ids", "source_ids", "claim_ids", "citations", "reason_code"},
                  "external_run": {"kind", "id", "provider", "run_id", "status", "text", "result", "artifact_path"},
                  "retraction": {"kind", "claim_id", "text"},
                  "question": {"kind", "id", "question"},
                  "interruption": {"kind", "operation_id", "text"},
                  "resume": {"kind", "text"}}
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in shapes or set(entry) - shapes[kind]:
            raise ValueError("Unknown research entry kind or fields")
        if kind != "resume":
            self._active(state)
        if len(state["events"]) >= max(500, 10 * len(state.get("inventory", []))):
            raise ValueError("Research event limit reached; finish this session")
        question = self._find(state["questions"], entry.get("question_id"), "question") if kind in ("claim", "answer", "gap") else None
        if kind in ("inventory_review", "external_run"):
            recorded, replayed = (self._inventory_review(path, state, entry) if kind == "inventory_review"
                                  else self._external_run(path, state, entry))
            if replayed:
                return {"research_id": research_id, "kind": kind, "recorded": recorded, "replayed": True}
        elif kind == "resume":
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
            if len(state["claims"]) >= max(100, 2 * len(state.get("inventory", []))):
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
            if verdict == "accepted":
                self._body(path, recorded)
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
                coverage = self._coverage(path, state)
                if not coverage["completion_ready"]:
                    raise ValueError("Research coverage incomplete: " + "; ".join(coverage["completion_blockers"]))
            # A report must never cite a missing or altered extract, even when partial.
            for claim in state["claims"]:
                self._citations(path, state, [{"source_id": c["source_id"], "quote": c["quote"]}
                                             for c in claim["citations"]], allow_rejected=claim.get("status") == "retracted")
            for run in state.get("external_runs", []):
                for field, hash_field in (("result_file", "result_sha256"), ("artifact_path", "artifact_sha256")):
                    if run.get(field):
                        artifact = self._artifact(path, run[field]) if field == "result_file" else Settings.external_path(run[field], "External result artifact")
                        if hashlib.sha256(artifact.read_bytes()).hexdigest() != run[hash_field]:
                            raise ValueError("Saved external result artifact hash changed")
            coverage = self._coverage(path, state)
            state.update(status=status, summary=summary, limitations=limitations, finished_at=self._now())
            coverage_text = json.dumps(coverage, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
            coverage_name = "coverage-" + hashlib.sha256(coverage_text.encode("utf-8")).hexdigest()[:24] + ".json"
            state["artifacts"] = {"report": str(path / "report.md"), "sources": str(path / "sources.json"),
                                  "state": str(path / "state.json"), "context": str(path / "context.json"),
                                  "coverage": str(path / coverage_name)}
            if state.get("source_scope"):
                state["artifacts"]["inventory"] = str(path / "inventory.json")
            self._write(path / coverage_name, coverage_text)
            self._write(path / "report.md", self._report(state, coverage))
            self._write(path / "sources.json", {"schema_version": state["schema_version"], "research_id": research_id,
                        "status": status, "sources": state["sources"], "claims": state["claims"],
                        "conflicts": state["conflicts"], "operations": state["operations"],
                        "questions": state["questions"], "limitations": limitations,
                        "source_scope": state.get("source_scope"), "inventory_manifest_sha256": state.get("inventory_manifest_sha256"),
                        "inventory_reviews": state.get("inventory_reviews", []), "external_runs": state.get("external_runs", []),
                        "coverage": {key: value for key, value in coverage.items() if key != "rows"}})
            self._save(path, state)
            return self._summary(path, state)

    @staticmethod
    def _report(state, coverage=None):
        lines = ["# " + state["brief"], "", "Status: **%s** · %s" % (state["status"], state["finished_at"]),
                 "", state["summary"], "", "## Scope", "", state["scope"] or "See the research questions below.",
                 "", "Indexed input sources: " + (", ".join(state["source_ids"]) or "None"),
                 "", "[Bookmark context in the research scope](context.json)", ""]
        scope = state.get("source_scope")
        if scope:
            lines.extend(["Input scope: **%s** · %s / %s exact original URLs · %s / %s bookmark instances." %
                          (scope["mode"], scope["selected_url_count"], scope["input_url_count"],
                           scope["selected_instance_count"], scope["input_instance_count"]), "",
                          "Input version: `%s` · [Complete frozen inventory](inventory.json)" % scope["input_version"], ""])
        else:
            lines.extend(["Legacy session: no complete input inventory was captured; original-package coverage cannot be inferred.", ""])
        fetch_plan = state.get("initial_fetch_plan")
        if fetch_plan and fetch_plan["selected_urls"]:
            lines.extend(["Initial fetch budget: minimum_required=%s calls at up to %s URLs/call; configured=%s; "
                          "call_shortfall=%s; URLs beyond that capacity=%s. The complete scope is retained." %
                          (fetch_plan["minimum_required"], fetch_plan["max_urls_per_call"], fetch_plan["configured_limit"],
                           fetch_plan["call_shortfall"], fetch_plan["urls_beyond_capacity"]),
                          fetch_plan["basis"], ""])
        if coverage:
            lines.extend(["| Coverage measure | Count / scope | Rate |", "| --- | ---: | ---: |"])
            for label, key in (("Accounted for", "accounted_for"), ("Usable accepted text", "usable_text"),
                               ("Substantive review", "substantive_review"), ("Questions completed", "question_completion")):
                metric = coverage["metrics"][key]
                rate = "n/a" if metric["rate"] is None else "%.1f%%" % (100 * metric["rate"])
                lines.append("| %s | %s / %s | %s |" % (label, metric["count"], metric["total"], rate))
            lines.extend(["", "Failure notes and explicit exclusions count only toward accounting. A substantive review requires accepted original-page text and a quoted judgment; these checks do not independently judge its reasoning quality.", "",
                          "[Per-input reviews and gaps](%s)" % Path(state["artifacts"]["coverage"]).name, ""])
            lines.extend("- " + blocker for blocker in coverage["completion_blockers"])
            lines.append("")
        lines.extend(["## Research questions", ""])
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
                      "Saved evidence may contain page extracts, local documents or secondary external reports; each source records its evidence kind and provenance. Sources have unknown completeness and origin freshness unless established separately. Retrieval dates are not publication dates. Multiple providers returning the same URL are one page, not independent confirmation.", ""])
        lines.extend("- " + limitation for limitation in state["limitations"])
        for operation in state["operations"]:
            if operation["status"] != "ok":
                lines.append("- %s (%s): %s; inspect %s" % (operation["id"], operation["kind"], operation["status"],
                                                           operation["result_file"] or "state.json"))
        if state.get("external_runs"):
            lines.extend(["", "## External run observations", "",
                          "These references record host or provider observations. Run completion does not establish input coverage.", ""])
            for run in state["external_runs"]:
                lines.append("- %s · %s / %s · %s: %s" % (run["id"], run["provider"], run["run_id"], run["status"], run["text"]))
                if run.get("result_file"):
                    lines.append("  [Saved complete result](%s) · SHA-256: `%s`" % (run["result_file"], run["result_sha256"]))
        lines.extend(["", "Budget reservations: " + json.dumps(state["usage"], ensure_ascii=False), "",
                      "## Sources", ""])
        for source in state["sources"]:
            lines.extend(["### Source " + source["id"], "", source["url"], "",
                          "Provider: %s · Retrieved: %s · Status: %s · Evidence: %s · Content: %s" %
                          (source["provider"], source["retrieved_at"] or "unknown", source["extraction_status"],
                           source.get("evidence_kind", "page"), source["content_kind"]), "",
                          "Content review: " + source.get("review", {}).get("verdict", "unreviewed") +
                          (" — " + source["review"]["text"] if source.get("review", {}).get("text") else ""), "",
                          "[Manifest](%s) · [Actual response](%s)" % (source["manifest_file"], source["response_file"])])
            if source["body_file"]:
                lines.append(" · [Saved text](%s) · SHA-256: `%s`" % (source["body_file"], source["sha256"]))
            if source.get("evidence_kind") == "external_report":
                lines.extend(["", "Secondary external report; its referenced original pages are not marked as read."])
            lines.append("")
        resumes = [event["value"] for event in state["events"] if event["kind"] == "resume"]
        if resumes:
            lines.extend(["## Earlier reports", ""])
            for resumed in resumes:
                lines.append("- [Previous incomplete report](%s): %s" %
                             (Path(resumed["previous_artifacts"]["report"]).name, resumed["text"]))
            lines.append("")
        return "\n".join(lines) + "\n"
