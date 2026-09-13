"""Minimal, synchronous stdio MCP tools server; no third-party SDK required.

Each stdin/stdout message is one JSON-RPC object on one line. This server
implements initialization, ping, tools/list and tools/call, not resources,
prompts, sampling, tasks, HTTP transports or arbitrary SQL/command execution.
"""

import json
import math
import sys
from pathlib import Path

from settings import Settings


PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MAX_MESSAGE_CHARS = 256 * 1024
MAX_RESULT_CHARS = 2 * 1024 * 1024
PROVIDER_NAMES = Settings.PROVIDERS


def _text_schema(maximum=2048):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _array_schema(item, maximum, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}


def _object_schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


IDENTIFIER = _text_schema(512)
PROVIDERS = dict(_array_schema({"type": "string", "enum": list(PROVIDER_NAMES)}, len(PROVIDER_NAMES), 1), uniqueItems=True)
SETTINGS_SCHEMA = _object_schema({
    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
    "search": _object_schema({"providers": PROVIDERS,
        "fallback_providers": {**PROVIDERS, "minItems": 0},
        "limit_per_target": {"type": "integer", "minimum": 1, "maximum": 20}}),
    "fetch": _object_schema({"provider": {"type": "string", "enum": list(PROVIDER_NAMES)},
        "providers": PROVIDERS,
        "max_characters": {"type": "integer", "minimum": 100, "maximum": 100000}}),
    "archive": _object_schema({"enabled": {"type": "boolean"}, "directory": _text_schema(4096)}),
    "research": _object_schema({"depth": {"type": "string", "enum": ["auto", "quick", "agentic", "deep"]},
        "prefer_host_workflows": {"type": "boolean"},
        "methods": dict(_array_schema({"type": "string", "enum": ["comparative_analysis", "fact_check", "benchmark_review", "wiki_synthesis"]}, 4, 1), uniqueItems=True)}),
    "professional_research": _object_schema({"enabled": {"type": "boolean"},
        "provider": {"type": ["string", "null"], "enum": ["openai", "parallel", None]},
        "openai": _object_schema({"model": {"type": "string", "enum": ["o3-deep-research", "o4-mini-deep-research"]},
            "max_tool_calls": {"type": "integer", "minimum": 1, "maximum": 1000}}),
        "parallel": _object_schema({"processor": _text_schema(64)})}),
    "wiki": _object_schema({"directory": _text_schema(4096)}),
})
TOOL_SCHEMAS = {
    "get_settings": _object_schema({}),
    "update_settings": _object_schema({"changes": SETTINGS_SCHEMA}, ["changes"]),
    "sync_package": _object_schema({"package_path": _text_schema(4096), "source_id": IDENTIFIER,
        "mode": {"type": "string", "enum": ["snapshot", "live"]},
        "completeness": {"type": "string", "enum": ["partial", "complete"]}}, ["package_path"]),
    "source_history": _object_schema({"source_id": IDENTIFIER,
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000000}}, ["source_id"]),
    "search_bookmarks": _object_schema({
        "source_id": IDENTIFIER, "targets": _array_schema(_text_schema(), 100),
        "section": IDENTIFIER, "group_id": IDENTIFIER, "folder_id": IDENTIFIER,
        "tags": _array_schema(_text_schema(), 100),
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 20},
        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000000, "default": 0},
        "refresh": {"type": "boolean", "default": True},
    }, ["source_id"]),
    "get_context": _object_schema({
        "source_id": IDENTIFIER, "section": IDENTIFIER, "group_id": IDENTIFIER,
        "item_id": IDENTIFIER, "refresh": {"type": "boolean", "default": True},
    }, ["source_id"]),
    "index_status": _object_schema({"source_id": IDENTIFIER}),
    "search_web": _object_schema({
        "targets": _array_schema(_object_schema({"target": _text_schema(200), "query": _text_schema(2000)}, ["target", "query"]), 12, 1),
        "providers": PROVIDERS,
        "limit_per_target": {"type": "integer", "minimum": 1, "maximum": 20},
    }, ["targets"]),
    "fetch_web": _object_schema({
        "urls": _array_schema(_text_schema(8192), 8, 1),
        "provider": {"type": "string", "enum": list(PROVIDER_NAMES)},
        "archive": {"type": "boolean"},
        "max_characters": {"type": "integer", "minimum": 100, "maximum": 100000},
    }, ["urls"]),
    "search_providers": _object_schema({
        "probe": {"type": "boolean", "default": False}, "providers": PROVIDERS,
    }),
}

TOOL_DESCRIPTIONS = {
    "get_settings": "Read effective user preferences and their persistent config path without network access or creating files. Per-call options override saved preferences.",
    "update_settings": "Persist requested preferences outside the plugin and canvas packages: retrieval, archiving, research routes/methods, optional professional services and Wiki storage. Applies to subsequent calls without restart. Does not store credentials or modify host integrations.",
    "sync_package": "Import a directory, ZIP or single section JSON, retaining a managed snapshot outside the original. Reuse source_id for a moved or partial export of the same canvas; path aliases are remembered. New exports default to snapshot; Git directories default to live monitoring. Existing sources retain their mode. completeness=partial preserves absent cards; complete reconciles a full mirror. Single cards must be partial. Source files are never modified.",
    "source_history": "List saved source versions and their complete managed snapshot paths, including data retained from partial imports. Reimport a snapshot path to recover its data and recorded relationships. This does not refresh sources or change existing research inventories.",
    "search_bookmarks": "Search bookmark metadata with literal title/URL/note/tag/folder-path matching and exact SQL scopes. Targets have independent totals and pages; this is not semantic webpage-body retrieval. Refresh checks live directories by default; snapshots remain usable after the original export disappears. Inspect source.state for pending changes or errors. refresh=false uses the last synchronized index, not an arbitrary historical version.",
    "get_context": "Read section headers, bookmark metadata, folder ancestry, geometric group membership and directed canvas edges. Copy anchors share their primary tree. Refresh is enabled by default.",
    "index_status": "Read source modes, original input availability, saved snapshots, pending files, last check/error, counts and local monitor status. Does not refresh or fetch webpages. unchecked means a live directory has not been checked recently.",
    "search_web": "Search with saved primary providers concurrently, then saved fallback providers only for queries with no usable result (defaults: Exa + Parallel, then Tavily + keyed Jina). Missing fallback credentials are skipped. Explicit providers restrict the call to that list. Search snippets are not verified page evidence; result pages are not automatically fetched.",
    "fetch_web": "Fetch known HTTP(S) URLs. Omit provider to try fetch.provider first, then other saved fetch.providers concurrently for unresolved URLs only (initially Exa, Parallel, Jina Reader). Explicit provider selects one service. Attempts keep separate responses and archives. archive=false disables saving. Extracts need source review; no pages or vectors are added to the bookmark index.",
    "search_providers": "Describe Exa/Parallel/Tavily MCP and Jina HTTP capabilities and authentication per operation. Jina Reader supports anonymous access; Jina Search requires JINA_API_KEY. probe=true discovers MCP catalogs; HTTP mappings are local. Discovery does not prove successful retrieval.",
}

RESEARCH_ID = _text_schema(80)
CLAIM_IDS = dict(_array_schema(RESEARCH_ID, 100, 1), uniqueItems=True)
RESEARCH_ENTRY = _object_schema({
    "kind": {"type": "string", "enum": ["claim", "answer", "gap", "conflict", "resolution", "question", "interruption", "source_review", "retraction", "resume", "inventory_review", "external_run"]},
    "question_id": RESEARCH_ID, "id": RESEARCH_ID, "question": _text_schema(4000),
    "statement": _text_schema(4000), "answer": _text_schema(12000), "text": _text_schema(4000),
    "claim_ids": dict(_array_schema(RESEARCH_ID, 100), uniqueItems=True), "conflict_id": RESEARCH_ID, "operation_id": RESEARCH_ID,
    "claim_id": RESEARCH_ID, "source_id": RESEARCH_ID,
    "verdict": {"type": "string", "enum": ["accepted", "rejected", "uncertain"]},
    "confidence": {"type": "string", "enum": ["low", "medium", "high"]}, "inference": {"type": "boolean"},
    "inventory_id": RESEARCH_ID, "disposition": {"type": "string", "enum": ["reviewed", "excluded", "blocked"]},
    "question_ids": dict(_array_schema(RESEARCH_ID, 24), uniqueItems=True),
    "source_ids": dict(_array_schema(RESEARCH_ID, 12), uniqueItems=True),
    "reason_code": {"type": "string", "enum": ["out_of_scope", "non_content"]},
    "provider": _text_schema(80), "run_id": _text_schema(512),
    "status": {"type": "string", "enum": ["prepared", "pending", "queued", "in_progress", "completed", "cancelled", "error", "unknown_outcome"]},
    "result": {"type": "object", "properties": {}, "additionalProperties": True},
    "artifact_path": _text_schema(4096),
    "citations": _array_schema(_object_schema({"source_id": RESEARCH_ID, "quote": _text_schema(4000)},
                                                ["source_id", "quote"]), 12),
}, ["kind"])
RESEARCH_BATCH_ENTRY = _object_schema({**RESEARCH_ENTRY["properties"], "kind": {
    "type": "string", "enum": [kind for kind in RESEARCH_ENTRY["properties"]["kind"]["enum"]
                              if kind not in ("resume", "external_run")]}}, ["kind"])
TOOL_SCHEMAS.update({
    "research_start": _object_schema({
        "brief": _text_schema(12000), "scope": {"type": "string", "maxLength": 12000},
        "questions": _array_schema(_object_schema({"id": RESEARCH_ID, "question": _text_schema(4000)},
                                                  ["id", "question"]), 24, 1),
        "providers": PROVIDERS, "source_ids": _array_schema(IDENTIFIER, 100),
        "scope_mode": {"type": "string", "enum": ["whole", "subset"]},
        "inventory_ids": dict(_array_schema(RESEARCH_ID, 10000), uniqueItems=True),
        "bookmark_refs": _array_schema(_object_schema({"source_id": IDENTIFIER, "section_id": IDENTIFIER,
                                                        "item_id": IDENTIFIER}, ["source_id", "section_id", "item_id"]), 100),
        "budget": _object_schema({"max_search_calls": {"type": "integer", "minimum": 0, "maximum": 120},
            "max_fetch_calls": {"type": "integer", "minimum": 0, "maximum": 80},
            "max_rounds": {"type": "integer", "minimum": 0, "maximum": 40}}),
    }, ["brief", "questions"]),
    "research_status": _object_schema({"research_id": RESEARCH_ID,
        "section": {"type": "string", "enum": ["questions", "claims", "sources", "operations", "conflicts", "bookmark_context", "events", "inventory", "inventory_reviews", "external_runs"]},
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
    "research_search": _object_schema({
        "research_id": RESEARCH_ID, "operation_id": RESEARCH_ID, "providers": PROVIDERS,
        "queries": _array_schema(_object_schema({"question_id": RESEARCH_ID, "query": _text_schema(2000)},
                                                ["question_id", "query"]), 12, 1),
        "limit_per_target": {"type": "integer", "minimum": 1, "maximum": 20},
    }, ["research_id", "operation_id", "queries"]),
    "research_fetch": _object_schema({
        "research_id": RESEARCH_ID, "operation_id": RESEARCH_ID, "question_id": RESEARCH_ID,
        "urls": _array_schema(_text_schema(8192), 8, 1),
        "provider": {"type": "string", "enum": list(PROVIDER_NAMES)},
        "max_characters": {"type": "integer", "minimum": 100, "maximum": 100000},
    }, ["research_id", "operation_id", "question_id", "urls"]),
    "research_source": _object_schema({
        "research_id": RESEARCH_ID, "source_id": RESEARCH_ID,
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50000},
    }, ["research_id", "source_id"]),
    "research_record": _object_schema({"research_id": RESEARCH_ID, "entry": RESEARCH_ENTRY,
        "entries": _array_schema(RESEARCH_BATCH_ENTRY, 50, 1),
        "batch_id": {**RESEARCH_ID, "description": "Optional stable ID for safe batch retries; reuse only with identical entries."}},
        ["research_id"]),
    "research_inventory": _object_schema({"research_id": RESEARCH_ID,
        "inventory_ids": dict(_array_schema(RESEARCH_ID, 100, 1), uniqueItems=True),
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["research_id"]),
    "research_coverage": _object_schema({"research_id": RESEARCH_ID,
        "filter": {"type": "string", "enum": ["all", "missing", "unread", "unreviewed", "blocked", "excluded", "reviewed"]},
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["research_id"]),
    "research_import_evidence": _object_schema({"research_id": RESEARCH_ID, "operation_id": RESEARCH_ID,
        "question_id": RESEARCH_ID, "url": _text_schema(8192), "text": _text_schema(200000),
        "provenance": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["page", "archived_page", "local_document", "external_report"]}},
                       "required": ["kind"], "additionalProperties": True},
        "inventory_ids": dict(_array_schema(RESEARCH_ID, 10000), uniqueItems=True),
        "title": {"type": "string", "maxLength": 2000}},
        ["research_id", "operation_id", "question_id", "url", "text", "provenance"]),
    "research_finish": _object_schema({
        "research_id": RESEARCH_ID, "summary": _text_schema(16000),
        "status": {"type": "string", "enum": ["completed", "incomplete", "cancelled"]},
        "limitations": _array_schema(_text_schema(4000), 100),
    }, ["research_id", "summary"]),
})
TOOL_DESCRIPTIONS.update({
    "research_start": "Start host-led research with explicit questions, budgets and a frozen source inventory. Indexed source_ids select their whole packages by default, preserving all URL instances and canvas context. A subset requires scope_mode=subset explicitly. Creates no model or worker and makes no network calls.",
    "research_status": "List saved research sessions or read a bounded progress overview, including source_freshness against the current indexed input. Requires review when the input changed; frozen evidence is not rewritten. For complete entries, select section and paginate; overview shows at most 20 previews per collection. No network requests. A pending intent is not proof that a research worker is running.",
    "research_search": "Execute one search round using frozen primary providers and fallbacks for unresolved queries. Explicit providers disable fallback. Reserve each provider/question/query before access, including budget-limited fallbacks; inspect unresolved_queries and remaining_attempts. Identical operation_id and arguments replay the saved outcome without resubmission.",
    "research_fetch": "Read URLs and retain each provider's actual response and identified text as session evidence. Omit provider to try session providers in a waterfall: first provider, then remaining providers concurrently for unresolved URLs, reserving each attempt within the fetch budget. Explicit provider selects one service. Inspect unresolved_urls and remaining_providers. Reuse operation_id for safe outcome lookup.",
    "research_source": "Read a saved research source by ID with pagination and SHA-256 verification. This reads extracted text, which may be partial; it does not contact a provider.",
    "research_record": "Prefer entries for 1-50 evidence records in one call. Provide exactly one of entry or entries. A batch validates in order and saves atomically; any invalid entry saves nothing. Returns compact IDs in input order. Use batch_id for safe retries with identical entries. Only single entry supports resume/external_run; resume preserves prior reports and budgets. Kinds have different required fields; see deep-research.md. Quote matching proves presence, not entailment.",
    "research_inventory": "Read the frozen original URL scope with stable inventory IDs, all bookmark instances and context. Paginate until next_offset is null; a page is not the whole research scope.",
    "research_coverage": "Compare substantive source reviews against the frozen input. Reports accounted, usable-text, reviewed and question coverage separately; paginate missing/unread/unreviewed IDs for follow-up. A provider or host run completing does not complete source coverage.",
    "research_import_evidence": "Import explicitly supplied original text or an external report with provenance and idempotent operation_id. Evidence starts unreviewed. External reports never count as reading the original URLs they cite. Does not fetch remote content or modify packages.",
    "research_finish": "Write a report, source manifest and coverage. Completed requires evidence-backed input reviews, supported answers and no unresolved conflicts, pending operations or active/unknown external runs. Explicit exclusions remain visible and do not increase substantive coverage. Use incomplete for material gaps.",
})


OPEN_OBJECT = {"type": "object", "properties": {}, "additionalProperties": True}
SERVICE_PROVIDER = {"type": "string", "enum": ["openai", "parallel"]}
SERVICE_OPTIONS = _object_schema({
    "model": {"type": "string", "enum": ["o3-deep-research", "o4-mini-deep-research"]},
    "max_tool_calls": {"type": "integer", "minimum": 1, "maximum": 1000},
    "store": {"type": "boolean"},
    "vector_store_ids": _array_schema(_text_schema(100), 2, 1),
    "processor": _text_schema(64), "output_schema": _text_schema(12000),
})
SERVICE_INPUT = {"research_id": RESEARCH_ID, "input": _text_schema(50000), "provider": SERVICE_PROVIDER,
    "question_id": RESEARCH_ID, "inventory_ids": dict(_array_schema(RESEARCH_ID, 10000), uniqueItems=True),
    "options": SERVICE_OPTIONS}
WIKI_PAGE = _object_schema({
    "title": _text_schema(300), "kind": {"type": "string", "enum": ["topic", "entity"]},
    "sections": _array_schema(_object_schema({"heading": _text_schema(300), "text": _text_schema(12000),
        "claims": _array_schema(_object_schema({"research_id": RESEARCH_ID, "claim_id": RESEARCH_ID},
            ["research_id", "claim_id"]), 12, 1)}, ["heading", "text", "claims"]), 16, 1),
    "links": _array_schema(_object_schema({"page_id": RESEARCH_ID, "relation": _text_schema(500)}, ["page_id", "relation"]), 32),
    "review": _object_schema({"method": {"type": "string", "enum": ["human", "model"]},
        "reviewer": _text_schema(300), "note": _text_schema(4000)}, ["method", "reviewer", "note"]),
}, ["title", "kind", "sections", "links", "review"])
TOOL_SCHEMAS.update({
    "research_route": _object_schema({
        "depth": {"type": "string", "enum": ["auto", "quick", "agentic", "deep"]},
        "host": {"type": "string", "enum": ["codex", "claude_code", "pi", "dsh", "unknown"]},
        "task_shape": {"type": "string", "enum": ["lookup", "investigation", "batch_research"]},
        "observed_tools": _array_schema(_text_schema(300), 1000),
        "available_commands": _array_schema(_text_schema(300), 1000),
        "installed_extensions": _array_schema(_text_schema(300), 1000),
        "failed_routes": dict(_array_schema(_text_schema(300), 1000), uniqueItems=True),
        "provider": SERVICE_PROVIDER,
    }),
    "research_services": _object_schema({"provider": SERVICE_PROVIDER}),
    "research_service_prepare": _object_schema(SERVICE_INPUT, ["research_id", "input"]),
    "research_service_start": _object_schema({**SERVICE_INPUT, "operation_id": RESEARCH_ID},
                                             ["research_id", "operation_id", "input"]),
    "research_service_status": _object_schema({"external_id": RESEARCH_ID, "refresh": {"type": "boolean"}}, ["external_id"]),
    "research_service_result": _object_schema({"external_id": RESEARCH_ID, "refresh": {"type": "boolean"},
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50000}}, ["external_id"]),
    "research_service_cancel": _object_schema({"external_id": RESEARCH_ID}, ["external_id"]),
    "research_service_attach": _object_schema({"research_id": RESEARCH_ID, "operation_id": RESEARCH_ID,
        "provider": SERVICE_PROVIDER, "run_id": _text_schema(200), "question_id": RESEARCH_ID},
        ["research_id", "operation_id", "provider", "run_id"]),
    "research_service_import": _object_schema({"external_id": RESEARCH_ID, "operation_id": RESEARCH_ID,
        "question_id": RESEARCH_ID}, ["external_id", "operation_id"]),
    "wiki_write": _object_schema({"page_id": RESEARCH_ID, "page": WIKI_PAGE, "change_note": _text_schema(4000),
        "expected_revision": {"type": "integer", "minimum": 0, "maximum": 1000000}},
        ["page_id", "page", "change_note"]),
    "wiki_get": _object_schema({"page_id": RESEARCH_ID, "revision": {"type": "integer", "minimum": 1, "maximum": 1000000}}, ["page_id"]),
    "wiki_list": _object_schema({"offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
    "wiki_search": _object_schema({"query": _text_schema(2000), "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["query"]),
    "wiki_lint": _object_schema({"page_id": RESEARCH_ID}),
    "evaluate_research": _object_schema({"suite": OPEN_OBJECT, "runs": _array_schema(OPEN_OBJECT, 1000, 1),
        "judgments": _array_schema(OPEN_OBJECT, 1000)}, ["suite", "runs"]),
})
TOOL_DESCRIPTIONS.update({
    "research_route": "Select research from observed host workflows, Exa Agent/Parallel Task MCP tools, configured APIs or native iterative research. After a confirmed failure, pass cumulative failed_routes from route_id to select the next path. Active/unknown runs must be observed, not replaced. Explicit provider is exclusive. Returns steps for the host to execute; this call starts no work.",
    "research_services": "Describe optional OpenAI Deep Research and Parallel Task API configuration. No network access; configured credentials are not proof of authentication. These APIs are separate from anonymous Search MCP access.",
    "research_service_prepare": "Prepare the exact provider payload and source scope without network access. Only the explicit input and source URLs are shared; local bookmark notes, paths and files are not uploaded. Inspect this payload before starting a service run.",
    "research_service_start": "Start one configured, authenticated provider research run and save its reference. operation_id prevents automatic duplicate submission, including lost responses. Remote execution belongs to the provider; the plugin starts no worker or polling loop.",
    "research_service_status": "Read the saved provider-run reference. refresh=true observes the same remote run once. Observation timeouts preserve the last known state and never create another run.",
    "research_service_result": "Read the archived provider report with pagination, raw result provenance and unverified citations. refresh=true makes one result request; Parallel result waits at most one server-side second. Does not mark original sources reviewed.",
    "research_service_cancel": "Request cancellation through the provider's documented interface. OpenAI supports this; Parallel Task cancellation is not established by this adapter. Local observation failure never means the remote job was cancelled.",
    "research_service_attach": "Attach an independently known provider run ID without starting remote work. Can recover a missing create response or reference a run started through an existing host integration. Status remains unverified until observed.",
    "research_service_import": "Import a saved completed provider report into a research session as unreviewed external-report evidence. Original URL coverage is unchanged; read and assess cited originals separately.",
    "wiki_write": "Publish an authored topic/entity page outside source packages, with reviewed active claims, source provenance, relationships and an immutable revision. Supply the current expected_revision when updating. Semantic support requires the named human/model review.",
    "wiki_get": "Read a Wiki page or an immutable earlier revision with source/claim links and revision metadata. validation.status=needs_review signals changed bookmark input after the cited research; this does not automatically revise the page or refetch webpages.",
    "wiki_list": "List paginated Wiki pages and current revision metadata without network access.",
    "wiki_search": "Search authored Wiki body text and return provenance. Invalidated or retracted evidence is excluded; this is literal full-text retrieval, not vector search.",
    "wiki_lint": "Check Wiki evidence hashes, active claims, source review states and cross-page links. Reports semantic review declarations separately from mechanical integrity checks.",
    "evaluate_research": "Evaluate explicit benchmark outputs and reviewer labels against a supplied rubric. Computes coverage, labeled answer precision/recall/F1, semantic citation-label rates, report scores and measured cost/latency/variance. Missing judgments remain unknown; this tool runs no models or providers.",
})


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _validate(schema, value, location="arguments"):
    declared = schema["type"]
    kinds = declared if isinstance(declared, list) else [declared]
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, float) and math.isfinite(value)),
        "null": value is None}
    kind = next((name for name in kinds if matches.get(name, False)), None)
    if kind is None:
        raise RpcError(-32602, "%s must be %s" % (location, " or ".join(kinds)))
    if "enum" in schema and value not in schema["enum"]:
        raise RpcError(-32602, "%s has an unsupported value" % location)
    if kind == "object":
        properties = schema.get("properties", {})
        unknown = set(value) - set(properties)
        if unknown and schema.get("additionalProperties") is False:
            raise RpcError(-32602, "%s contains unknown fields: %s" % (location, ", ".join(sorted(unknown))))
        for key in schema.get("required", []):
            if key not in value:
                raise RpcError(-32602, "%s.%s is required" % (location, key))
        for key, child in value.items():
            if key in properties:
                _validate(properties[key], child, location + "." + key)
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", MAX_MESSAGE_CHARS):
            raise RpcError(-32602, "%s has too few or too many entries" % location)
        if schema.get("uniqueItems") and len(set(json.dumps(item, sort_keys=True) for item in value)) != len(value):
            raise RpcError(-32602, "%s must contain unique entries" % location)
        for index, item in enumerate(value):
            _validate(schema["items"], item, "%s[%s]" % (location, index))
    elif kind == "string":
        if "\x00" in value or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", MAX_MESSAGE_CHARS):
            raise RpcError(-32602, "%s has invalid length or contains NUL" % location)
        if schema.get("minLength", 0) > 0 and not value.strip():
            raise RpcError(-32602, "%s must not be blank" % location)
    elif kind in ("integer", "number"):
        if not schema.get("minimum", value) <= value <= schema.get("maximum", value):
            raise RpcError(-32602, "%s is out of range" % location)


def _params(value, allowed, required=()):
    if not isinstance(value, dict):
        raise RpcError(-32602, "params must be an object")
    unknown = set(value) - set(allowed) - {"_meta"}
    if unknown:
        raise RpcError(-32602, "Unknown params: " + ", ".join(sorted(unknown)))
    if "_meta" in value and not isinstance(value["_meta"], dict):
        raise RpcError(-32602, "params._meta must be an object")
    for key in required:
        if key not in value:
            raise RpcError(-32602, "Missing param: " + key)
    return value


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class StdioMcpServer:
    """One client connection, with lazy local-index and web-provider handles."""

    def __init__(self, db_path, stderr=None, settings=None):
        self.db_path = db_path
        self.stderr = stderr if stderr is not None else sys.stderr
        self.protocol = None
        self.ready = False
        self._index = None
        self._source_manager = None
        self._source_watcher = None
        self._providers = None
        self._research_sessions = None
        self._research_services = None
        self._wiki_store = None
        self.settings = settings if settings is not None else Settings()

    def close(self):
        if self._source_watcher is not None:
            self._source_watcher.close()
            self._source_watcher = None
        self._source_manager = None
        if self._index is not None:
            self._index.close()
            self._index = None

    def _local(self):
        if self._index is None:
            from bookmark_index import BookmarkIndex
            self._index = BookmarkIndex(self.db_path)
        return self._index

    def _sources(self):
        if self._source_manager is None:
            from source_manager import SourceManager
            self._source_manager = SourceManager(self._local())
        return self._source_manager

    def _start_watcher(self):
        if self._source_watcher is None and str(self.db_path) != ":memory:" and Path(self.db_path).is_file():
            from source_watcher import SourceWatcher
            self._source_watcher = SourceWatcher(self.db_path).start()

    def _web(self):
        if self._providers is None:
            from web_search import SearchProviders
            self._providers = SearchProviders(settings=self.settings)
        return self._providers

    def _research(self):
        if self._research_sessions is None:
            from research import ResearchSessions
            self._research_sessions = ResearchSessions(settings=self.settings, engine=self._web(), db_path=self.db_path)
        return self._research_sessions

    def _log(self, message):
        self.stderr.write("bookmark-research MCP: " + message + "\n")
        self.stderr.flush()

    def _services(self):
        if self._research_services is None:
            from research_services import ResearchServices
            self._research_services = ResearchServices(settings=self.settings, research_sessions=self._research())
        return self._research_services

    def _wiki(self):
        if self._wiki_store is None:
            from wiki import WikiStore
            self._wiki_store = WikiStore(settings=self.settings, research_sessions=self._research())
        return self._wiki_store

    def _call(self, name, arguments):
        # Explicit dispatch ensures input can never select a Python method,
        # executable, SQL statement, or unadvertised capability.
        research_methods = {"research_start": "start", "research_status": "status", "research_search": "search",
                            "research_fetch": "fetch", "research_source": "source", "research_record": "record",
                            "research_finish": "finish", "research_inventory": "inventory",
                            "research_coverage": "coverage", "research_import_evidence": "import_evidence"}
        if name in research_methods:
            return getattr(self._research(), research_methods[name])(**arguments)
        service_methods = {"research_services": "describe", "research_service_prepare": "prepare",
            "research_service_start": "start", "research_service_status": "status", "research_service_result": "result",
            "research_service_cancel": "cancel", "research_service_attach": "attach", "research_service_import": "import_result"}
        if name in service_methods:
            return getattr(self._services(), service_methods[name])(**arguments)
        wiki_methods = {"wiki_write": "write", "wiki_get": "get", "wiki_list": "list", "wiki_search": "search", "wiki_lint": "lint"}
        if name in wiki_methods:
            return getattr(self._wiki(), wiki_methods[name])(**arguments)
        if name == "research_route":
            from routing import ResearchRouting
            return ResearchRouting(self.settings).route(**arguments)
        if name == "evaluate_research":
            from evaluation import evaluate
            return evaluate(**arguments)
        if name == "get_settings":
            return self.settings.describe()
        if name == "update_settings":
            return self.settings.update(arguments["changes"])
        if name == "sync_package":
            result = self._sources().sync(**arguments)
            self._start_watcher()
            return result
        if name == "source_history":
            return self._sources().history(**arguments)
        if name in ("search_bookmarks", "get_context"):
            options = dict(arguments)
            refresh = options.pop("refresh", True)
            index = self._local()
            update = self._sources().refresh(options["source_id"]) if refresh else None
            if update and update["state"] in ("error", "unavailable"):
                raise ValueError(update["error"] + "; use refresh=false to read the saved index")
            method = index.search if name == "search_bookmarks" else index.context
            with index.read_snapshot():
                result = method(**options)
                result["source"] = self._sources().status(options["source_id"])["source"]
            result["refresh"] = {"performed": bool(refresh and result["source"]["mode"] == "live"),
                "index_updated": bool(update and update.get("performed")),
                "requested": refresh, "mode": "checked_package" if refresh and result["source"]["mode"] == "live" else "saved_snapshot", "sync": update}
            return result
        if name == "index_status":
            result = self._sources().status(**arguments)
            result["monitor"] = self._source_watcher.status() if self._source_watcher else {"running": False, "mechanism": "poll"}
            return result
        if name == "search_web":
            return self._web().search(**arguments)
        if name == "fetch_web":
            return self._web().fetch(**arguments)
        if name == "search_providers":
            options = dict(arguments)
            probe = options.pop("probe", False)
            return self._web().probe(**options) if probe else self._web().describe(**options)
        raise RpcError(-32602, "Unknown tool: " + name)

    def _tool_result(self, value, is_error=False):
        rendered = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(rendered) > MAX_RESULT_CHARS:
            raise ValueError("Tool result exceeds size limit; paginate with a lower result limit while preserving the research scope")
        result = {"content": [{"type": "text", "text": rendered}], "isError": is_error}
        # structuredContent was introduced after the 2025-03-26 protocol.
        if self.protocol in ("2025-06-18", "2025-11-25"):
            result["structuredContent"] = value if isinstance(value, dict) else {"data": value}
        return result

    def handle(self, message):
        """Return a response object, or None for a valid notification."""
        if not isinstance(message, dict):
            return _error(None, -32600, "Expected one JSON-RPC request object")
        request_id = message.get("id")
        notification = "id" not in message
        if (not notification and (isinstance(request_id, bool) or not isinstance(request_id, (int, str)))):
            return _error(None, -32600, "Request id must be a string or integer")
        if (message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str)
                or not message.get("method") or set(message) - {"jsonrpc", "id", "method", "params"}):
            return _error(request_id, -32600, "Invalid JSON-RPC request")
        method, params = message["method"], message.get("params", {})
        try:
            if notification:
                if method == "notifications/initialized":
                    _params(params, ())
                    if self.protocol is None:
                        raise RpcError(-32600, "Initialize before notifications/initialized")
                    self.ready = True
                    self._start_watcher()
                elif method in ("initialize", "tools/call", "tools/list", "ping"):
                    # These are request methods. Never execute a tool sent as
                    # a notification: it has no response/error channel.
                    self._log("Ignored request method without an id: " + method)
                return None
            if method == "initialize":
                _params(params, ("protocolVersion", "capabilities", "clientInfo"), ("protocolVersion", "capabilities", "clientInfo"))
                _validate(_text_schema(64), params["protocolVersion"], "protocolVersion")
                if not isinstance(params["capabilities"], dict) or not isinstance(params["clientInfo"], dict):
                    raise RpcError(-32602, "capabilities and clientInfo must be objects")
                for key in ("name", "version"):
                    _validate(_text_schema(256), params["clientInfo"].get(key), "clientInfo." + key)
                if self.protocol is not None:
                    raise RpcError(-32600, "This connection is already initialized")
                requested = params["protocolVersion"]
                self.protocol = requested if requested in PROTOCOLS else PROTOCOLS[-1]
                result = {"protocolVersion": self.protocol, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "bookmark-research", "version": "0.4.0"}}
            elif method == "ping":
                _params(params, ())
                result = {}
            elif method == "notifications/initialized":
                raise RpcError(-32600, "notifications/initialized must not have an id")
            elif method not in ("tools/list", "tools/call"):
                raise RpcError(-32601, "Method not found: " + method)
            elif not self.ready:
                raise RpcError(-32002, "Server is not initialized")
            elif method == "tools/list":
                # All tools fit in one response; no pagination is advertised.
                _params(params, ("cursor",))
                if "cursor" in params:
                    raise RpcError(-32602, "This tool list has no pagination cursor")
                result = {"tools": [{"name": name, "description": TOOL_DESCRIPTIONS[name], "inputSchema": schema}
                    for name, schema in TOOL_SCHEMAS.items()]}
            else:
                _params(params, ("name", "arguments"), ("name",))
                name = params["name"]
                _validate(_text_schema(128), name, "name")
                if name not in TOOL_SCHEMAS:
                    raise RpcError(-32602, "Unknown tool: " + name)
                arguments = params.get("arguments", {})
                _validate(TOOL_SCHEMAS[name], arguments)
                try:
                    value = self._call(name, arguments)
                    failed = ((name in ("fetch_web", "research_search", "research_fetch") and value.get("status") == "error")
                              or (name == "search_web" and value.get("successful_provider_count") == 0))
                    result = self._tool_result(value, is_error=failed)
                except Exception as exc:
                    # No raw arguments, tracebacks, credentials or provider
                    # payloads are written to stderr.
                    self._log("Tool failed: %s (%s)" % (name, type(exc).__name__))
                    result = self._tool_result({"tool": name, "error": str(exc)[:4000], "error_type": type(exc).__name__}, is_error=True)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            if notification:
                self._log("Ignored invalid notification (%s)" % exc.code)
                return None
            return _error(request_id, exc.code, str(exc))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Non-finite JSON value")


def serve(db_path, stdin=None, stdout=None, stderr=None, settings=None):
    """Serve line-delimited JSON-RPC until EOF; stdout contains protocol only."""
    incoming = stdin if stdin is not None else sys.stdin
    outgoing = stdout if stdout is not None else sys.stdout
    server = StdioMcpServer(db_path, stderr=stderr, settings=settings)

    def emit(value):
        outgoing.write(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        outgoing.flush()

    try:
        while True:
            line = incoming.readline(MAX_MESSAGE_CHARS + 1)
            if not line:
                break
            if len(line) > MAX_MESSAGE_CHARS:
                emit(_error(None, -32700, "JSON-RPC message exceeds size limit; connection closed"))
                break
            if not line.strip():
                continue
            try:
                request = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
            except (ValueError, RecursionError):
                emit(_error(None, -32700, "Parse error: invalid JSON"))
                continue
            try:
                response = server.handle(request)
            except Exception as exc:
                server._log("Request handler failed (%s)" % type(exc).__name__)
                request_id = request.get("id") if isinstance(request, dict) else None
                response = _error(request_id, -32603, "Internal server error")
            if response is not None:
                emit(response)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        server.close()
