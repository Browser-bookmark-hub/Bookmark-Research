"""Shared Canvas locate primitive.

The MCP transport and the command-line entry point should use this module so
query normalization, metadata inference, ranking and evidence explanations do
not diverge between hosts.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import tempfile
import zlib
from pathlib import Path

from ref_codec import register as register_ref


# Keep this list focused on conversational glue.  Note and Tag are metadata
# predicates, not free-text terms, so they are handled by ``locate_metadata``.
LOCATE_STOPWORDS = frozenset({
    "关于", "定位", "一个", "就是", "然后", "主要", "这种", "帮", "书签", "东西", "好像",
    "还有", "带", "有", "这个", "那个", "请", "帮忙", "者", "的", "和", "或", "与", "及",
    "note", "notes", "tag", "tags", "标签",
})

# The public locate contract is intentionally kept in one place for CLI/MCP
# adapters and parameter-matrix tests.
LOCATE_ARGUMENTS = (
    "text", "url", "in", "source_id", "section", "folder_id", "tags",
    "tag_colors", "has_note", "has_tags", "metadata_match", "limit", "offset", "handle", "refresh",
)
LOCATE_FIELD_WEIGHTS = {"title": 140, "url": 120, "tags": 110, "note": 90, "path": 60}
LOCATE_DIRECT_FIELDS = frozenset(("title", "url", "note", "tags"))

_LOCATE_HANDLE_PREFIX = "lh1."
_LOCATE_HANDLE_MAX_LENGTH = 16384
_LOCATE_HANDLE_MAX_PAYLOAD = 65536
_LOCATE_HANDLE_SIGNATURE_BYTES = 16


def locate_ref(source_id, section_id, item_id, version_id=None):
    """Return a collision-checked short Canvas ref."""
    return register_ref("b", (source_id, version_id or "", section_id, item_id))


def locate_why(item, terms):
    """Explain literal field hits using values from the indexed item.

    Metadata predicates are deliberately excluded here.  A ``has_note`` or
    ``has_tags`` filter is reported by the response's ``filters`` object; it is
    not evidence that the query term matched the note or tags field.
    """
    tags = item.get("tags") or []
    if isinstance(tags, (list, tuple)):
        tags = "\n".join(str(value) for value in tags)
    values = {
        "title": item.get("title") or "",
        "note": item.get("note") or "",
        "tags": tags,
        "path": item.get("folder_path") or "",
        "url": item.get("url") or "",
    }
    fields, matched_terms = [], []
    for term in terms:
        term = str(term)
        needle = term.casefold()
        if not needle:
            continue
        if term.isascii():
            pattern = r"(?<![0-9A-Za-z])" + re.escape(term) + r"(?![0-9A-Za-z])"
            term_fields = [field for field, value in values.items()
                           if re.search(pattern, str(value), re.I)]
        else:
            term_fields = [field for field, value in values.items()
                           if needle in str(value).casefold()]
        if term_fields:
            matched_terms.append(term)
            for field in term_fields:
                if field not in fields:
                    fields.append(field)
    weight = max((LOCATE_FIELD_WEIGHTS[field] for field in fields), default=0)
    return {
        "terms": matched_terms,
        "fields": fields,
        "field_weights": {field: LOCATE_FIELD_WEIGHTS[field] for field in fields},
        "weight": weight,
        "match_mode": "literal_boundary" if any(str(term).isascii() for term in terms)
        else "literal_substring",
    }


def locate_query(text):
    """Keep common Chinese digit-plus-D notation searchable as 3D/2D."""
    digits = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
    return re.sub(r"([一二三四五六七八九十])\s*[dD](?=\b|[^0-9A-Za-z])",
                  lambda match: digits[match.group(1)] + "D", text)


def locate_metadata(text):
    """Extract only unambiguous note/tag language as structured filters."""
    value = text.casefold()
    has_note = bool(re.search(r"(?:有|带|含|包含|还有)\s*(?:些?\s*)?notes?(?![0-9a-z])", value))
    has_tags = bool(re.search(r"(?:有|带|含|包含|还有)\s*(?:些?\s*)?(?:tags?|标签)(?![0-9a-z])", value))
    return has_note, has_tags


def locate_terms(terms):
    """Remove conversational terms while preserving index-provided ordering."""
    return [term for term in terms if str(term).casefold() not in LOCATE_STOPWORDS]


def locate_match_mode(terms):
    """Return the literal matching mode implied by normalized search terms."""
    return "literal_boundary" if any(str(term).isascii() for term in terms) else "literal_substring"


def _handle_request(arguments):
    """Return the query arguments that define a continuation stream."""
    return {key: value for key, value in arguments.items() if key not in ("handle", "offset")}


def _handle_key_path(database_path=None):
    """Return a stable per-database key path shared by CLI and MCP processes."""
    if database_path is not None and str(database_path) != ":memory:":
        database = Path(database_path).expanduser().resolve()
        directory = database.parent
        identity = str(database)
    else:
        selected = os.environ.get("BOOKMARK_RESEARCH_DATA_DIR")
        if selected:
            directory = Path(selected).expanduser().resolve()
        else:
            xdg_home = os.environ.get("XDG_DATA_HOME")
            base = (Path(xdg_home).expanduser()
                    if xdg_home and Path(xdg_home).is_absolute()
                    else Path.home() / ".local/share")
            directory = (base / "bookmark-research").resolve()
        directory = directory / "continuations"
        identity = str(directory / "index.sqlite3")
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return directory / (".bookmark-research-locate-" + digest + ".key")


def _fallback_handle_key_path(primary_path):
    """Return a per-user temp path for hosts that cannot write beside the index."""
    owner = str(os.getuid()) if hasattr(os, "getuid") else (
        os.environ.get("USERNAME") or os.environ.get("USER") or "default")
    owner_digest = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:12]
    return (Path(tempfile.gettempdir()) / ("bookmark-research-" + owner_digest)
            / "continuations" / primary_path.name)


def _load_or_create_handle_key(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("locate continuation key must not be a symbolic link")
    if not path.exists():
        descriptor, temporary = tempfile.mkstemp(prefix=".locate-key-", dir=str(path.parent))
        try:
            key = os.urandom(32)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Exclusive hard-link creation prevents concurrent callers
                # from replacing the key and invalidating each other's handles.
                os.link(temporary, str(path))
            except FileExistsError:
                pass
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    if path.is_symlink():
        raise ValueError("locate continuation key must not be a symbolic link")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("locate continuation signing key is invalid")
    return key


def _handle_key(database_path=None):
    """Load or atomically create a signing key, with a writable temp fallback."""
    primary = _handle_key_path(database_path)
    fallback = _fallback_handle_key_path(primary)
    try:
        return _load_or_create_handle_key(primary)
    except OSError:
        if fallback == primary:
            raise
    return _load_or_create_handle_key(fallback)


def _b64encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("invalid locate continuation encoding")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64encode(decoded) != value:
        raise ValueError("non-canonical locate continuation encoding")
    return decoded


def _remember_handle(arguments, database_path=None):
    """Encode query and filters into a signed, cross-process continuation handle."""
    body = {"v": 1, "request": _handle_request(arguments)}
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > _LOCATE_HANDLE_MAX_PAYLOAD:
        raise ValueError("locate continuation arguments exceed the handle payload limit")
    encoded = _b64encode(zlib.compress(payload, level=9))
    signed = (_LOCATE_HANDLE_PREFIX + encoded).encode("ascii")
    signature = hmac.new(_handle_key(database_path), signed, hashlib.sha256).digest()[:_LOCATE_HANDLE_SIGNATURE_BYTES]
    handle = _LOCATE_HANDLE_PREFIX + encoded + "." + _b64encode(signature)
    if len(handle) > _LOCATE_HANDLE_MAX_LENGTH:
        raise ValueError("locate continuation handle exceeds the maximum length")
    return handle


def _resolve_handle(handle, database_path=None):
    """Verify and decode a stateless continuation handle."""
    if not isinstance(handle, str) or len(handle) > _LOCATE_HANDLE_MAX_LENGTH:
        return None
    try:
        prefix, encoded, supplied_signature = handle.split(".", 2)
        if prefix != "lh1" or not encoded or not supplied_signature:
            return None
        signed = (prefix + "." + encoded).encode("ascii")
        expected_signature = hmac.new(
            _handle_key(database_path), signed, hashlib.sha256).digest()[:_LOCATE_HANDLE_SIGNATURE_BYTES]
        if not hmac.compare_digest(expected_signature, _b64decode(supplied_signature)):
            return None
        decoder = zlib.decompressobj()
        payload = decoder.decompress(_b64decode(encoded), _LOCATE_HANDLE_MAX_PAYLOAD + 1)
        if (len(payload) > _LOCATE_HANDLE_MAX_PAYLOAD or decoder.unconsumed_tail
                or decoder.unused_data or not decoder.eof):
            return None
        body = json.loads(payload.decode("utf-8"))
        if not isinstance(body, dict) or body.get("v") != 1 or not isinstance(body.get("request"), dict):
            return None
        return body["request"]
    except (OSError, ValueError, TypeError, UnicodeError, zlib.error, json.JSONDecodeError):
        return None


def continuation_scope(handle, database_path=None):
    """Return a continuation's original scope for transport adapters."""
    saved = _resolve_handle(handle, database_path) if handle else None
    request = saved or {}
    scope = request.get("in", ["canvas"])
    return scope if isinstance(scope, list) else ["canvas"]


def continuation_refresh_requested(handle, database_path=None):
    """Return whether a continuation's original query requires writable refresh."""
    saved = _resolve_handle(handle, database_path) if handle else None
    return bool(saved and saved.get("refresh"))


def _query_terms(text):
    """Get conservative display terms for non-Canvas literal evidence."""
    return [part for part in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]*|[\u4e00-\u9fff]", text)
            if part.casefold() not in LOCATE_STOPWORDS]


def _why_for_result(row, terms, fields):
    values = {field: str(row.get(field) or "") for field in fields}
    matched, matched_fields = [], []
    for term in terms:
        found = [field for field, value in values.items() if term.casefold() in value.casefold()]
        if found:
            matched.append(term)
            for field in found:
                if field not in matched_fields:
                    matched_fields.append(field)
    return {"terms": matched, "fields": matched_fields, "match_mode": "literal_substring"}


def _locate_external(scope, text, url, offset, limit, wiki=None, raw=None):
    if scope == "wiki":
        if url is not None:
            raise ValueError("locate wiki scope accepts text, not url")
        if wiki is None:
            raise ValueError("wiki locate adapter is unavailable")
        payload = wiki.search(text, offset=offset, limit=limit)
        terms = _query_terms(text)
        hits = []
        for row in payload.get("results", []):
            page_id = row.get("page_id")
            revision = row.get("revision")
            if not page_id:
                continue
            evidence = {"ref": register_ref("w", (page_id, revision)),
                        "source_kind": "wiki", "source_id": page_id,
                        "wiki_revision": revision, "evidence_kind": "wiki_revision",
                        "title": row.get("title") or "", "snippet": row.get("snippet") or "",
                        "why": _why_for_result(row, terms, ("title", "snippet"))}
            validation = row.get("validation") or {}
            if validation:
                evidence["validation"] = validation
                if validation.get("status"):
                    evidence["content_state"] = ("usable" if validation["status"] == "ok"
                                                   else validation["status"])
            hits.append(evidence)
        total = payload.get("total", len(hits))
        next_offset = payload.get("next_offset")
        return hits, total, next_offset, terms
    if raw is None:
        raise ValueError("archive locate adapter is unavailable")
    query = text or url
    payload = raw.search(query, limit=limit, offset=offset, url=url)
    terms = _query_terms(query)
    hits = []
    for row in payload.get("results", []):
        occurrences = row.get("occurrences") or []
        capture_id = next((item.get("capture_id") for item in occurrences if item.get("capture_id")), None)
        archive_key = capture_id or row.get("sha256") or row.get("url")
        if not archive_key:
            continue
        evidence = {"ref": register_ref("a", (capture_id or "", row.get("sha256") or "",
                                                   row.get("url") or "")), "source_kind": "archive",
                    "source_id": row.get("url") or row.get("sha256"),
                    "evidence_kind": "archive_capture", "title": row.get("title") or "",
                    "url": row.get("url") or "", "snippet": row.get("snippet") or "",
                    "sha256": row.get("sha256"),
                    "capture_id": capture_id,
                    "content_state": "usable" if row.get("snippet") else "content_insufficient",
                    "why": _why_for_result(row, terms, ("title", "snippet", "url"))}
        hits.append({key: value for key, value in evidence.items() if value is not None})
    total = payload.get("total", len(hits))
    next_offset = payload.get("next_offset")
    return hits, total, next_offset, terms


def locate(index, source_manager, arguments, wiki=None, raw=None):
    """Run the P0 Canvas locate operation against an indexed source.

    ``source_manager`` is passed in by the host so this module remains
    transport-independent. Continuation handles contain a signed, compressed
    copy of the original query and filters, so page traversal works across CLI
    invocations and MCP restarts.
    """
    supplied = dict(arguments)
    handle = supplied.get("handle")
    offset = supplied.get("offset", 0)
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if handle is not None:
        database_path = getattr(index, "db_path", None)
        saved = _resolve_handle(handle, database_path)
        if saved is None:
            raise ValueError("unknown locate continuation handle")
        # A handle owns the original query and filters.  Only offset may vary
        # on a continuation request, preventing accidental cross-query reads.
        supplied = dict(saved, offset=offset, handle=handle)
    request = _handle_request(supplied)
    database_path = getattr(index, "db_path", None)
    text = request.get("text")
    url = request.get("url")
    requested = request.get("in", ["canvas"])
    if not isinstance(requested, list) or not requested or any(scope not in ("canvas", "wiki", "archive") for scope in requested):
        raise ValueError('locate in must contain canvas, wiki or archive')
    if len(requested) != 1:
        raise ValueError("locate currently requires exactly one scope in")
    source_id = request.get("source_id")
    section = request.get("section")
    folder_id = request.get("folder_id")
    folder_listing = text is None and url is None and folder_id is not None
    if not folder_listing and (text is None) == (url is None):
        raise ValueError("locate requires exactly one of text or url, or folder_id without either")
    tags = request.get("tags")
    tag_colors = request.get("tag_colors")
    has_note = request.get("has_note")
    has_tags = request.get("has_tags")
    metadata_match = request.get("metadata_match", "all")
    limit = request.get("limit", 8)
    refresh = request.get("refresh", False)
    if requested[0] != "canvas":
        if folder_listing:
            raise ValueError("folder_id-only locate is supported for canvas scope")
        unsupported = ("source_id", "section", "folder_id", "tags", "tag_colors",
                       "has_note", "has_tags", "metadata_match")
        if any(request.get(key) is not None and not (key == "metadata_match" and request.get(key) == "all")
               for key in unsupported):
            raise ValueError("metadata filters are only supported for canvas locate")
        if refresh:
            raise ValueError("refresh is only supported for canvas locate")
        hits, total_hits, next_offset, terms = _locate_external(
            requested[0], text, url, offset, limit, wiki=wiki, raw=raw)
        result = {"hits": hits, "total": total_hits, "in": requested,
                  "match_mode": "literal_substring", "source_ids": [],
                  "candidates": [], "filters": {}}
        if text is not None:
            result["query"] = text
        else:
            result["url"] = url
        if next_offset is not None and next_offset < total_hits:
            continuation = _remember_handle(request, database_path)
            result["more"] = {"handle": continuation, "offset": next_offset, "total": total_hits}
            result["next"] = {"tool": "locate", "handle": continuation,
                               "offset": next_offset, "reason": "continue_results"}
        return result
    if source_id is None:
        source_ids = source_manager.live_sources()
        if len(source_ids) != 1:
            raise ValueError("source_required: locate requires source_id when the index has zero or multiple live sources")
    else:
        source_ids = [index.resolve_source_id(source_id)]
    source_ids = sorted(dict.fromkeys(source_ids))
    statuses = {}
    for identifier in source_ids:
        update = source_manager.refresh(identifier) if refresh else None
        if update and update.get("state") in ("error", "unavailable"):
            raise ValueError(update.get("error", "source is unavailable") + "; use refresh=false to read the saved index")
        statuses[identifier] = source_manager.source_status(identifier)

    hits, seen, candidates = [], set(), []
    folder_rows, hint_rows = {}, {}
    terms_by_source = {}
    text_match_mode = "literal_substring"
    query = locate_query(text) if text is not None else None
    inferred_note, inferred_tags = locate_metadata(query) if query is not None else (False, False)
    if has_note is None and inferred_note:
        has_note = True
    if has_tags is None and inferred_tags:
        has_tags = True
    filters = {"section": section, "folder_id": folder_id, "tags": tags,
               "tag_colors": tag_colors, "has_note": has_note, "has_tags": has_tags,
               "metadata_match": metadata_match}
    has_filters = any(value is not None for key, value in filters.items()
                      if key != "metadata_match") or metadata_match != "all"
    metadata_requested = any(value is not None for key, value in filters.items()
                             if key in ("tags", "tag_colors", "has_note", "has_tags"))
    with index.read_snapshot():
        if folder_listing:
            identifier = source_ids[0]
            found = index.folder_children(
                identifier, folder_id, section=section, tags=tags, tag_colors=tag_colors,
                has_note=has_note, has_tags=has_tags, metadata_match=metadata_match,
                limit=limit, offset=offset)
            version = statuses[identifier].get("version_id")
            parent = found["folder"]
            parent_ref = locate_ref(identifier, parent["section_id"], folder_id, version)
            folder = {"ref": parent_ref, "folder_id": folder_id,
                      "section_id": parent["section_id"], "title": parent.get("title") or "",
                      "path": list(parent.get("path") or []) +
                              ([parent["title"]] if parent.get("title") else [])}
            if version is not None:
                folder["version_id"] = version
            page_hits = []
            for child in found["results"]:
                hit = {"ref": locate_ref(identifier, child["section_id"], child["item_id"], version),
                       "kind": child["item_type"], "source_kind": "canvas", "source_id": identifier,
                       "evidence_kind": "folder_child", "section_id": child["section_id"],
                       "item_id": child["item_id"], "parent_id": child.get("parent_id"),
                       "title": child.get("title") or "",
                       "path": list(child.get("path") or []) +
                               ([child["title"]] if child.get("title") else []),
                       "position": child.get("position")}
                if child.get("url"):
                    hit["url"] = child["url"]
                if child.get("note"):
                    hit["note"] = child["note"]
                if child.get("note_color"):
                    hit["note_color"] = child["note_color"]
                if child.get("tags"):
                    hit["tags"] = child["tags"]
                if version is not None:
                    hit["version_id"] = version
                page_hits.append(hit)
            total_hits = found["total"]
            coverage = {"matched": total_hits, "shown": len(page_hits),
                        "hidden": max(0, total_hits - len(page_hits))}
            result = {"hits": page_hits, "total": total_hits, "in": ["canvas"],
                      "match_mode": "folder_children", "source_ids": source_ids,
                      "folder": folder, "coverage": coverage,
                      "filters": {key: value for key, value in filters.items()
                                  if value is not None and not (key == "metadata_match" and value == "all")}}
            next_offset = offset + len(page_hits)
            next_message = ("%d direct children; read a child ref for its full context" % total_hits
                            if total_hits else "No direct children match this folder scope")
            if next_offset < total_hits:
                continuation = _remember_handle(request, database_path)
                result["more"] = {"handle": continuation, "offset": next_offset, "total": total_hits}
                result["next"] = {"tool": "locate", "handle": continuation,
                                   "offset": next_offset, "reason": "continue_results",
                                   "message": next_message}
            else:
                result["next"] = next_message
            return result
        if url is not None:
            for identifier in source_ids:
                if has_filters:
                    found = index.search(identifier, targets=[url], section=section, folder_id=folder_id,
                                         tags=tags, tag_colors=tag_colors, limit=1000, offset=0,
                                         score=True, has_note=has_note, has_tags=has_tags,
                                         metadata_match=metadata_match)
                    if found["total"] > len(found["results"]):
                        raise ValueError("locate URL result exceeds the bounded page; narrow the URL or use the P0b continuation handle")
                    instances = [item for item in found["results"] if item.get("url") == url]
                else:
                    found = index.lookup_url(url, source_id=identifier, limit=1000, offset=0)
                    if found["total_instances"] > len(found["instances"]):
                        raise ValueError("locate URL result exceeds the bounded page; narrow the URL or use the P0b continuation handle")
                    instances = found["instances"]
                for item in instances:
                    key = (identifier, item["section_id"], item["item_id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    version = statuses[identifier].get("version_id")
                    hit = {"ref": locate_ref(*key, version), "source_kind": "canvas",
                           "kind": "bookmark",
                           "source_id": identifier, "evidence_kind": "bookmark_instance",
                           "section_id": item["section_id"], "item_id": item["item_id"],
                           "title": item.get("title") or "", "url": item.get("url") or "",
                           "why": {"terms": [url], "fields": ["url"],
                                  "field_weights": {"url": LOCATE_FIELD_WEIGHTS["url"]},
                                  "weight": LOCATE_FIELD_WEIGHTS["url"], "match_mode": "exact"}}
                    if version is not None:
                        hit["version_id"] = version
                    hits.append(hit)
        else:
            for identifier in source_ids:
                scope = index.plan_scope(identifier, query, max_cards=3, max_urls=8)
                terms = locate_terms(scope.get("terms", []))
                terms_by_source[identifier] = terms
                if locate_match_mode(terms) == "literal_boundary":
                    text_match_mode = "literal_boundary"
                candidates.append({
                    "source_id": identifier,
                    "terms": terms,
                    "cards": [{"section_id": card.get("section_id"),
                               "matched_terms": locate_terms(card.get("matched_terms", []))}
                              for card in scope.get("cards", [])[:3]],
                    "urls": [{"url": row.get("url"),
                              "matched_terms": locate_terms(row.get("matched_terms", []))}
                             for row in scope.get("urls", [])[:3]],
                })
                term_cards = scope.get("term_cards", {})
                card_ranks = {card.get("section_id"): rank for rank, card in enumerate(scope.get("cards", []))}
                for card in scope.get("cards", []):
                    result_section = section or card["section_id"]
                    targets = locate_terms(card.get("matched_terms", [])) or terms
                    found = index.search(identifier, targets=targets, section=result_section,
                                         folder_id=folder_id, tags=tags, tag_colors=tag_colors,
                                         limit=1000, offset=0, score=True, has_note=has_note,
                                         has_tags=has_tags, metadata_match=metadata_match)
                    if found["total"] > len(found["results"]):
                        raise ValueError("locate text result exceeds the bounded page; narrow the query or use the P0b continuation handle")
                    for item in found["results"]:
                        key = (identifier, item["section_id"], item["item_id"])
                        if key in seen:
                            continue
                        why = locate_why(item, terms)
                        why["match_mode"] = text_match_mode
                        if not why["terms"] and not metadata_requested:
                            continue
                        seen.add(key)
                        rarity = sum(1.0 / max(term_cards.get(term, 1), 1)
                                      for term in why["terms"])
                        version = statuses[identifier].get("version_id")
                        hit = {"ref": locate_ref(*key, version), "source_kind": "canvas",
                               "kind": "bookmark",
                               "source_id": identifier, "evidence_kind": "bookmark_instance",
                               "section_id": item["section_id"], "item_id": item["item_id"],
                               "title": item.get("title") or "", "url": item.get("url") or "",
                               "why": why}
                        hit["_locate_weight"] = why["weight"]
                        hit["_locate_rarity"] = rarity
                        hit["_locate_card_rank"] = card_ranks.get(item["section_id"], len(card_ranks))
                        hit["_locate_parent_id"] = item.get("parent_id")
                        if version is not None:
                            hit["version_id"] = version
                        hits.append(hit)
        if url is None:
            for hit in hits:
                if set(hit["why"]["fields"]) != {"path"}:
                    continue
                scope_key = (hit["source_id"], hit["section_id"])
                if scope_key in folder_rows:
                    continue
                found_folders = index.search(
                    hit["source_id"], section=hit["section_id"], folder_id=folder_id,
                    item_types=["folder"], limit=1000, offset=0)
                if found_folders["total"] > len(found_folders["results"]):
                    raise ValueError("locate folder inventory exceeds the bounded page; narrow the section")
                folder_rows[scope_key] = {row["item_id"]: row for row in found_folders["results"]}
            if not hits:
                for identifier in source_ids:
                    for term in terms_by_source.get(identifier, []):
                        found_folders = index.search(
                            identifier, targets=[term], section=section, folder_id=folder_id,
                            item_types=["folder"], limit=1000, offset=0)
                        if found_folders["total"] > len(found_folders["results"]):
                            continue
                        for folder in found_folders["results"]:
                            if not locate_why(folder, [term])["terms"]:
                                continue
                            hint_key = (term, identifier, folder["section_id"], folder["item_id"])
                            hint_rows[hint_key] = {
                                "folder_id": folder["item_id"], "ref": locate_ref(
                                    identifier, folder["section_id"], folder["item_id"],
                                    statuses[identifier].get("version_id")),
                                "title": folder.get("title") or "",
                                "path": list(folder.get("path") or []) +
                                        ([folder["title"]] if folder.get("title") else []),
                            }
    hits.sort(key=lambda hit: (-hit.pop("_locate_weight", 0),
                               -hit.pop("_locate_rarity", 0.0),
                               hit.pop("_locate_card_rank", 0), hit["source_id"],
                               hit["section_id"], hit["item_id"]))
    direct_hits, inherited_hits, unclassified_hits = [], [], []
    for hit in hits:
        fields = set(hit["why"]["fields"])
        if fields.intersection(LOCATE_DIRECT_FIELDS):
            direct_hits.append(hit)
        elif fields == {"path"}:
            inherited_hits.append(hit)
        else:
            unclassified_hits.append(hit)
    direct_hits.extend(unclassified_hits)

    folder_groups = {}
    unresolved_inherited = []
    for hit in inherited_hits:
        folders = folder_rows[(hit["source_id"], hit["section_id"])]
        path_terms = hit["why"]["terms"]
        current = folders.get(hit.get("_locate_parent_id"))
        nearest = None
        while current is not None:
            folder_why = locate_why(current, path_terms)
            if len(folder_why["terms"]) == len(path_terms):
                nearest = current
                break
            current = folders.get(current.get("parent_id"))
        if nearest is None and folder_id is not None:
            nearest = folders.get(folder_id)
        if nearest is None:
            unresolved_inherited.append(hit)
            continue
        key = (hit["source_id"], hit["section_id"], nearest["item_id"])
        group = folder_groups.setdefault(key, {"folder": nearest, "members": [], "terms": []})
        group["members"].append(hit)
        group["terms"] = list(dict.fromkeys(group["terms"] + path_terms))

    folder_hits = []
    for (identifier, section_id, folder_id), group in folder_groups.items():
        folder = group["folder"]
        version = statuses[identifier].get("version_id")
        sample = []
        for member in group["members"][:3]:
            member.pop("_locate_parent_id", None)
            sample.append({key: member[key] for key in
                           ("ref", "source_id", "section_id", "item_id", "title", "url", "why")})
        folder_hit = {
            "kind": "folder", "ref": locate_ref(identifier, section_id, folder_id, version),
            "source_kind": "canvas", "source_id": identifier,
            "evidence_kind": "inherited_matches", "section_id": section_id,
            "folder_id": folder_id, "item_id": folder_id,
            "title": folder.get("title") or "",
            "path": list(folder.get("path") or []) + ([folder["title"]] if folder.get("title") else []),
            "count": len(group["members"]), "sample": sample,
            "why": {"terms": group["terms"], "fields": ["path"],
                    "field_weights": {"path": LOCATE_FIELD_WEIGHTS["path"]},
                    "weight": LOCATE_FIELD_WEIGHTS["path"], "match_mode": text_match_mode},
        }
        if version is not None:
            folder_hit["version_id"] = version
        folder_hits.append(folder_hit)
    folder_hits.sort(key=lambda hit: (hit["count"], hit["source_id"], hit["section_id"], hit["folder_id"]))

    for hit in direct_hits + unresolved_inherited:
        hit.pop("_locate_parent_id", None)
    ranked_hits = direct_hits + folder_hits + unresolved_inherited[:2]
    total_hits = len(ranked_hits)
    page_hits = ranked_hits[offset:offset + limit]
    direct_match_count = sum(bool(LOCATE_DIRECT_FIELDS.intersection(hit["why"]["fields"]))
                             for hit in direct_hits)
    inherited_count = len(inherited_hits)
    shown_direct = sum(hit.get("kind") != "folder" for hit in page_hits)
    shown_samples = sum(len(hit.get("sample", [])) for hit in page_hits if hit.get("kind") == "folder")
    shown = shown_direct + shown_samples
    coverage = {
        "matched": len(direct_hits) + inherited_count,
        "shown": shown,
        "hidden": max(0, len(direct_hits) + inherited_count - shown),
        "folders": len(folder_hits),
        "direct": {"matched": direct_match_count, "shown": sum(
            bool(LOCATE_DIRECT_FIELDS.intersection(hit["why"]["fields"])) for hit in page_hits)},
        "inherited": {"matched": inherited_count, "folders": len(folder_hits), "sampled": shown_samples},
    }

    if not direct_match_count:
        for folder in folder_hits:
            for term in folder["why"]["terms"]:
                key = (term, folder["source_id"], folder["section_id"], folder["folder_id"])
                hint_rows[key] = {"folder_id": folder["folder_id"], "ref": folder["ref"],
                                  "title": folder["title"], "path": folder["path"]}
    by_term = {}
    for (term, _, _, _), folder in hint_rows.items():
        by_term.setdefault(term, []).append(folder)
    hints = [{"term": term, "folders": folders} for term, folders in by_term.items()]
    query_terms = list(dict.fromkeys(term for terms in terms_by_source.values() for term in terms))
    matched_terms = {term for hit in direct_hits for term in hit["why"]["terms"]}
    matched_terms.update(term for hit in folder_hits for term in hit["why"]["terms"])
    missing_terms = [term for term in query_terms if term not in matched_terms]
    if total_hits and not missing_terms:
        hints = []
    result = {"hits": page_hits, "total": total_hits,
              "in": ["canvas"], "match_mode": "exact" if url is not None else text_match_mode,
              "source_ids": source_ids, "candidates": candidates if total_hits == 0 else [],
              "filters": {key: value for key, value in filters.items()
                          if value is not None and not (key == "metadata_match" and value == "all")}}
    result["coverage"] = coverage
    if hints:
        result["hints"] = hints
    next_offset = offset + len(page_hits)
    if (total_hits == 1 and has_note is True and page_hits
            and page_hits[0].get("kind") != "folder"
            and "title" in page_hits[0]["why"]["fields"]):
        next_message = "1 hit with title+note; stop if it matches"
    elif direct_match_count and inherited_count:
        top_score = max(hit["why"]["weight"] for hit in direct_hits
                        if LOCATE_DIRECT_FIELDS.intersection(hit["why"]["fields"]))
        next_message = "%d direct hits, top score %d vs %d; read the first direct hit and stop if it matches" % (
            direct_match_count, top_score, LOCATE_FIELD_WEIGHTS["path"])
    elif direct_match_count:
        next_message = "%d direct hits; read the first direct hit and stop if it matches" % direct_match_count
    elif folder_hits and missing_terms and hints:
        hint = hints[0]
        next_message = "No full match for %r; %r appears in %d folders; try folder_id" % (
            text, hint["term"], len(hint["folders"]))
    elif folder_hits:
        next_message = "All matches are inherited; use folder_id to narrow a folder"
    elif hints:
        hint = hints[0]
        next_message = "No match for %r; %r appears in %d folders; try folder_id" % (
            text, hint["term"], len(hint["folders"]))
    elif unresolved_inherited:
        next_message = "Inherited matches need a folder scope; inspect the reported sample and narrow by folder_id"
    elif url is not None:
        next_message = "No exact URL matches; verify the URL string"
    else:
        next_message = "No direct or inherited matches; refine the text query"
    if next_offset < total_hits:
        continuation = _remember_handle(request, database_path)
        result["more"] = {"handle": continuation, "offset": next_offset, "total": total_hits}
        result["next"] = {"tool": "locate", "handle": continuation,
                           "offset": next_offset, "reason": "continue_results",
                           "message": next_message}
    else:
        result["next"] = next_message
    if text is not None:
        result["query"] = text
    else:
        result["url"] = url
    return result

