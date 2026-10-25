"""Stdio MCP tools server with bounded network workers; no third-party SDK required.

Each stdin/stdout message is one JSON-RPC object on one line. This server
implements initialization, ping, tools/list and tools/call, not resources,
prompts, sampling, tasks, HTTP transports or arbitrary SQL/command execution.
"""

import hashlib
import json
import math
import os
import sys
import threading
from pathlib import Path

from release import release_version
from settings import Settings


PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MAX_MESSAGE_CHARS = 256 * 1024
MAX_RESULT_CHARS = 2 * 1024 * 1024
NETWORK_WORKERS = 4
MAX_PENDING_CALLS = 16
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
        "limit_per_target": {"type": "integer", "minimum": 1, "maximum": 20},
        "strategy": {"type": "string", "enum": ["hedged", "staggered", "sequential", "wait_all"]},
        "grace_seconds": {"type": ["number", "null"], "minimum": 0, "maximum": 60},
        "deadline_seconds": {"type": ["number", "null"], "minimum": 0, "maximum": 60},
        "cache_seconds": {"type": "integer", "minimum": 0, "maximum": 3600}}),
    "fetch": _object_schema({"provider": {"type": "string", "enum": list(PROVIDER_NAMES)},
        "providers": PROVIDERS,
        "max_characters": {"type": "integer", "minimum": 100, "maximum": 100000},
        "max_total_characters": {"type": "integer", "minimum": 100, "maximum": 800000},
        "fair_share_min": {"type": "integer", "minimum": 0, "maximum": 100000},
        "strategy": {"type": "string", "enum": ["sequential", "staggered", "hedged"]},
        "grace_seconds": {"type": ["number", "null"], "minimum": 0, "maximum": 60},
        "deadline_seconds": {"type": ["number", "null"], "minimum": 0, "maximum": 60},
        "reuse_seconds": {"type": "integer", "minimum": 0, "maximum": 86400}}),
    "server": _object_schema({"network_workers": {"type": "integer", "minimum": 1, "maximum": 16},
        "max_pending_calls": {"type": "integer", "minimum": 1, "maximum": 64}}),
    "archive": _object_schema({"enabled": {"type": "boolean"}, "directory": _text_schema(4096)}),
    "research": _object_schema({"depth": {"type": "string", "enum": ["auto", "quick", "agentic", "deep"]},
        "prefer_host_workflows": {"type": "boolean"},
        "response_language": {"type": "string", "enum": ["auto", "en", "zh"]},
        "methods": dict(_array_schema({"type": "string", "enum": ["comparative_analysis", "fact_check", "benchmark_review", "wiki_synthesis"]}, 4, 1), uniqueItems=True)}),
    "professional_research": _object_schema({"enabled": {"type": "boolean"},
        "provider": {"type": ["string", "null"], "enum": ["openai", "parallel", None]},
        "openai": _object_schema({"model": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{1,80}$"},
            "max_tool_calls": {"type": "integer", "minimum": 1, "maximum": 1000},
            "allow_untested_model": {"type": "boolean"}}),
        "parallel": _object_schema({"processor": _text_schema(64)})}),
    "wiki": _object_schema({"directory": _text_schema(4096),
        "max_source_age_days": {"type": "integer", "minimum": 1, "maximum": 3650},
        "after_research": {"type": "string", "enum": ["suggest", "auto", "off"]}}),
    "wiki_preflight": {"type": "boolean"},
    "freshness_days": {"type": "integer", "minimum": 1, "maximum": 3650},
    "plan": _object_schema({"max_characters": {"type": "integer", "minimum": 1000, "maximum": 50000},
        "min_relevance": {"type": "number", "minimum": 0, "maximum": 1},
        "homepage_limit": {"type": "integer", "minimum": 0, "maximum": 8}}),
    "tool_scope": _array_schema(_text_schema(128), 100),
    "tool_scope_preset": {"type": "string", "enum": list(Settings.TOOL_SCOPE_PRESETS)},
    "output": _object_schema({"mode": {"type": "string", "enum": ["central", "beside_input"]},
        "directory": _text_schema(4096)}),
    "readiness": _object_schema({"mode": {"type": "string", "enum": ["cached", "always", "manual"]},
        "ttl_seconds": {"type": "integer", "minimum": 60, "maximum": 86400},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 30}}),
})
TOOL_SCHEMAS = {
    "get_settings": _object_schema({}),
    "update_settings": _object_schema({"changes": SETTINGS_SCHEMA}, ["changes"]),
    "research_readiness": _object_schema({"providers": PROVIDERS,
        "service": {"type": "string", "enum": ["openai", "parallel"]},
        "refresh": {"type": "boolean", "default": False}, "offline": {"type": "boolean", "default": False},
        "test_retrieval": {"type": "boolean", "default": False},
        "host": {"type": "string", "enum": ["codex", "claude_code", "dsh", "unknown"]},
        "observed_tools": _array_schema(_text_schema(300), 1000)}),
    "sync_package": _object_schema({"package_path": _text_schema(4096), "source_id": IDENTIFIER,
        "mode": {"type": "string", "enum": ["snapshot", "live"]},
        "completeness": {"type": "string", "enum": ["partial", "complete"]}}, ["package_path"]),
    "source_history": _object_schema({"source_id": IDENTIFIER,
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000000}}, ["source_id"]),
    "source_remove": _object_schema({"source_id": IDENTIFIER, "confirm": {"type": "boolean", "default": False}},
        ["source_id"]),
    "source_merge": _object_schema({"source_id": IDENTIFIER, "into_source_id": IDENTIFIER,
        "confirm": {"type": "boolean", "default": False}}, ["source_id", "into_source_id"]),
    "search_bookmarks": _object_schema({
        "source_id": IDENTIFIER, "targets": _array_schema(_text_schema(), 100),
        "section": IDENTIFIER, "group_id": IDENTIFIER, "folder_id": IDENTIFIER,
        "tags": _array_schema(_text_schema(), 100),
        "tag_colors": _array_schema(_text_schema(), 20),
        "item_types": {"type": "array", "items": {"type": "string", "enum": ["bookmark", "folder"]},
                       "minItems": 1, "maxItems": 2, "uniqueItems": True,
                       "description": "Defaults to bookmark; pass [\"folder\"] to enumerate folders."},
        "limit": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 20},
        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000000, "default": 0},
        "count_only": {"type": "boolean", "default": False},
        "compact": {"type": "boolean", "default": False},
        "refresh": {"type": "boolean", "default": True},
    }, ["source_id"]),
    "get_context": _object_schema({
        "source_id": IDENTIFIER, "section": IDENTIFIER, "group_id": IDENTIFIER,
        "item_id": IDENTIFIER, "refresh": {"type": "boolean", "default": True},
        "collection": {"type": "string", "enum": ["sections", "items", "nodes", "groups", "edges", "related_nodes", "memberships"]},
        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000000, "default": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
        "compact": {"type": "boolean", "default": False},
    }, ["source_id"]),
    "plan_research": _object_schema({
        "source_id": IDENTIFIER, "question": _text_schema(2000),
        "max_cards": {"type": "integer", "minimum": 1, "maximum": 3, "default": 3},
        "max_urls": {"type": "integer", "minimum": 1, "maximum": 8, "default": 8},
        "include_wiki": {"type": "boolean", "default": True},
        "include_archive": {"type": "boolean", "default": True},
        "max_wiki": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
        "max_archive": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
        "refresh": {"type": "boolean", "default": True},
    }, ["question"]),
    "discovery_bundle": _object_schema({
        "sources": {"type": "array", "items": {"type": "object"}, "minItems": 0, "maxItems": 64},
        "max_characters": {"type": "integer", "minimum": 1000, "maximum": 50000, "default": 50000},
        "steps": {"type": "integer", "minimum": 0, "maximum": 40, "default": 0},
        "fetches": {"type": "integer", "minimum": 0, "maximum": 80, "default": 0},
        "variants": {"type": "integer", "minimum": 0, "maximum": 20, "default": 0},
        "elapsed_seconds": {"type": "integer", "minimum": 0, "maximum": 3600, "default": 0},
    }, ["sources"]),
    "index_status": _object_schema({"source_id": IDENTIFIER}),
    "search_web": _object_schema({
        "targets": _array_schema({"type": ["string", "object"], "minLength": 1, "maxLength": 2000,
            "properties": {"target": _text_schema(200), "query": _text_schema(2000)},
            "required": ["target", "query"], "additionalProperties": False}, 12, 1),
        "providers": PROVIDERS,
        "limit_per_target": {"type": "integer", "minimum": 1, "maximum": 20},
    }, ["targets"]),
    "fetch_web": _object_schema({
        "urls": _array_schema(_text_schema(8192), 16, 1),
        "provider": {"type": "string", "enum": list(PROVIDER_NAMES)},
        "archive": {"type": "boolean"},
        "max_characters": {"type": "integer", "minimum": 100, "maximum": 100000},
        "max_total_characters": {"type": "integer", "minimum": 100, "maximum": 800000,
                                 "description": "Total text budget across selected pages; defaults to 100000."},
        "capture_id": _text_schema(128),
        "offset": {"type": "integer", "minimum": 0, "maximum": 100000000,
                   "description": "Continue an archived page using its capture_id; no new network request."},
        "raw": {"type": "boolean", "default": False,
                "description": "Return full provider envelopes instead of one selected text per URL. Archives always retain actual responses when enabled."},
    }, ["urls"]),
    "search_providers": _object_schema({
        "probe": {"type": "boolean", "default": False}, "providers": PROVIDERS,
    }),
    "search_archive": _object_schema({
        "query": {**_text_schema(500), "description": "Literal text; every whitespace-separated term must occur. Wrap in double quotes for one exact phrase."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000, "default": 0},
        "url": {**_text_schema(2048), "description": "Only bodies saved for a URL containing this substring (case-insensitive)."},
        "occurrence_limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 50,
            "description": "Occurrences listed per merged body. Each result reports occurrence_count, occurrences_truncated and occurrences_next_offset."},
        "occurrence_offset": {"type": "integer", "minimum": 0, "maximum": 10000000, "default": 0,
            "description": "Continue a body's occurrence list from this offset."},
    }, ["query"]),
}

TOOL_DESCRIPTIONS = {
    "get_settings": "Read saved preferences and config path without network access or file creation. Per-call options override preferences. tool_scope is the server-side MCP catalog allowlist; empty means every tool.",
    "update_settings": "Save requested retrieval, output, research or Wiki preferences outside source packages. Applies to later calls; output changes affect new tasks. Does not store credentials or change host integrations.",
    "research_readiness": "Diagnose retrieval/auth availability or inspect an external research route; reuse current results. Respects cached/always/manual preferences; refresh forces checks, offline prevents network. Tool visibility is not login. test_retrieval uses quota; no research job starts.",
    "sync_package": "Import a directory, ZIP or section JSON into an external managed snapshot; originals stay unchanged. Reuse source_id for moved/partial exports. partial preserves absent cards; complete reconciles a full mirror. Single cards must be partial. Defaults: snapshots for exports, live for Git directories; existing modes persist.",
    "source_history": "List saved source versions and managed snapshot paths, including partial-import data. Reimport a snapshot to recover it. Does not refresh sources or rewrite research inventories.",
    "source_remove": "Preview deletion of an imported source, index rows and managed snapshots; confirm=true performs it. Frozen research inventories remain, but item resolution stops and citing Wiki pages need review. For identical duplicates, prefer source_merge.",
    "source_merge": "Preview merging an identical source into into_source_id; confirm=true transfers path aliases and drops the duplicate. Synchronized content versions must match; synchronize legacy sources first.",
    "search_bookmarks": "Literal all-term search with independent target totals/pages; canvas_matches reports text/group/edge hits separately. compact=true returns shared rows plus ordered result_refs per page; row raw_json/metadata then contain extra/conflicting fields. Default false keeps full rows. Keep instances distinct from unique_urls and shared copies. count_only or limit=0 omits rows; item_types=[\"folder\"] includes synthetic roots. Live inputs refresh by default; inspect source.state. refresh=false reads the saved index.",
    "get_context": "Read section headers, bookmark metadata, folder ancestry, groups and directed edges. Defaults to 200 rows per collection; follow each collection's next_offset with the same scope. Counts cover the full scope. Copy anchors share their primary tree. Live inputs refresh by default. compact=true drops raw_json, description_md and revision; pair it with a collection to reach the smallest budget.",
    "plan_research": "Read local candidates for a question: matching bookmarks and canvas text/group/edge labels, independently searched Wiki pages and archived sources, and source dates. source_id is optional. Scores rank candidates without rejecting them; the host decides relevance, depth and whether to search. question_urls lists known URLs to read directly. No network or research task is started.",
    "discovery_bundle": "Assemble the route-② evidence bundle and decide the budget. Pass every source the host collected: only content_state=usable pages become evidence, the rest are listed with the reason they cannot be cited. The bundle is built at the richest level that fits max_characters (excerpts, then digest, then a plain URL list) and always keeps the URL list, so it degrades instead of returning nothing. steps, fetches, variants and elapsed_seconds are the host's own counters, and the plugin owns the decision: stop when budget.continue is false (steps ≤ 6, fetches ≤ 8, variants ≤ 3, 90 seconds). Cite evidence[].id in the answer; never cite a URL that has no evidence entry.",
    "index_status": "Read source modes, snapshots, counts, input availability, pending changes and monitor errors. No refresh or web fetch; unchecked means a live directory needs a recent check.",
    "search_web": "Discover sources for public queries with saved primary providers, then fallbacks for unresolved queries. search.strategy selects hedged (default), staggered, sequential or wait_all; search.grace_seconds and search.deadline_seconds bound the hedged and staggered runs, and dropped or uncalled providers are listed in routing. Explicit providers restrict the call. Targets accept target/query objects or plain query strings. Results are discovery snippets; pages are not fetched. Each result carries provider_count and corroborated: two or more providers returning one URL means link overlap, never confirmation of its content.",
    "fetch_web": "Read known URLs directly (up to 16 per call) with per-page and total text budgets. Continue saved text using capture_id and offset without refetching. Omit provider for the saved fallback order (fetch.strategy overlaps a stalled provider); specifying one restricts it. raw returns provider envelopes; archive=false skips saving. Check page identity before citing. Every page carries content_state, the page's own shape: usable, content_insufficient (under 400 characters or an empty-page marker), js_shell_suspected (a title and navigation but no prose), challenge_blocked, login_required (an SSO or sign-in wall), soft_404 or paywall_suspected; only usable pages are worth citing, and unavailable means no body was obtained. published_at is a day-precision date with published_at_source (provider_metadata, structured_metadata or body_date) and published_at_confidence; a bare date in the text is low confidence and never later than the fetch day. A URL with no body carries liveness: dead only for 404/410, otherwise unknown, and dead_urls lists them.",
    "search_providers": "Describe retrieval capabilities and per-operation auth. probe=true checks MCP catalogs, not successful retrieval. Jina Reader allows anonymous access; Jina Search needs a key. Configure credentials through CLI setup, never chat.",
    "search_archive": "Search saved page text across local archives and research tasks using literal terms. No network. Identical bodies are merged by hash; occurrences have their own pagination. Hash-mismatched bodies are skipped and counted; the index refreshes incrementally.",
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
        "urls": {**_array_schema(_text_schema(8192), 10000, 1),
                 "description": "Original bookmark URL list instead of indexed source_ids. Freezes every URL and duplicate position for coverage; no package import required."},
        "scope_mode": {"type": "string", "enum": ["whole", "subset"]},
        "inventory_ids": dict(_array_schema(RESEARCH_ID, 10000), uniqueItems=True),
        "bookmark_refs": _array_schema(_object_schema({"source_id": IDENTIFIER, "section_id": IDENTIFIER,
                                                        "item_id": IDENTIFIER}, ["source_id", "section_id", "item_id"]), 100),
        "budget": _object_schema({"max_search_calls": {"type": "integer", "minimum": 0, "maximum": 120},
            "max_fetch_calls": {"type": "integer", "minimum": 0, "maximum": 80},
            "max_rounds": {"type": "integer", "minimum": 0, "maximum": 40}}),
        "output_directory": {**_text_schema(4096), "description": "Absolute folder for this task only; overrides the output setting. Omit to follow it."},
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
        "urls": _array_schema(_text_schema(8192), 16, 1),
        "provider": {"type": "string", "enum": list(PROVIDER_NAMES)},
        "max_characters": {"type": "integer", "minimum": 100, "maximum": 100000},
        "reuse_seconds": {"type": "integer", "minimum": 0, "maximum": 86400},
    }, ["research_id", "operation_id", "question_id", "urls"]),
    "research_source": _object_schema({
        "research_id": RESEARCH_ID, "source_id": RESEARCH_ID,
        "source_ids": dict(_array_schema(RESEARCH_ID, 8, 1), uniqueItems=True),
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50000},
    }, ["research_id"]),
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
    "research_start": "Create a saved task with questions, budgets and frozen urls or indexed Canvas source_ids. Preserves all input instances; only an explicit subset uses scope_mode=subset. Without inputs, tracks questions only. Returns output path/fallback_reason and work_directory for scratch files. No network or worker starts.",
    "research_status": "List saved tasks or read progress and input freshness. Overview contains truncated previews; use section and pagination for full records. Changed input needs review; frozen evidence stays unchanged. No network; pending state does not prove a worker is running.",
    "research_search": "Search with task providers and fallbacks for unresolved queries, reserving provider/question/query attempts against budget. Explicit providers restrict the call. Identical operation_id and arguments replay saved results. Inspect unresolved_queries and remaining_attempts.",
    "research_fetch": "Fetch up to 16 URLs into task evidence with per-attempt budget accounting and fallback for unresolved URLs (fetch.strategy controls provider overlap; abandoned providers are disclosed). reuse_seconds returns text saved within that window as reused_sources without a new request and reserves no budget. Explicit provider restricts the call. Returns metadata; read text with research_source. Reuse operation_id to retrieve the saved outcome; inspect unresolved_urls and remaining_providers.",
    "research_source": "Read saved extracted text by source ID, or up to 8 source_ids in one call, with pagination and SHA-256 verification. Extraction may be partial. No network.",
    "research_record": "Record evidence decisions; fields by kind are in deep-research.md#record-types. Supply entry or 1–50 entries, not both. Batches validate atomically and return ordered IDs; batch_id permits identical retries. Use returned IDs for dependent records. resume/external_run require entry. Quote matching checks presence, not meaning.",
    "research_inventory": "Read frozen original URLs, stable inventory IDs, duplicate instances and context. Follow next_offset to cover the requested scope.",
    "research_coverage": "Compare frozen input with accounted, usable-text, reviewed and answered coverage. Paginate missing/unread/unreviewed IDs as needed. A completed provider run does not establish original-source coverage.",
    "research_import_evidence": "Save supplied text and provenance using an idempotent operation_id. Imports start unreviewed; external reports do not count as reading cited originals. No fetch or source-package changes.",
    "research_finish": "Write report, source manifest and coverage. completed requires supported answers, reviewed original input and no unresolved conflicts, pending operations or active/unknown external runs. Exclusions stay in scope; use incomplete for material gaps. An incomplete or cancelled result also carries insufficiency (the fixed-shape gap list: question statuses and gaps, open conflicts, pending operations, coverage blockers; a question with no recorded gap gets a derived one and gap_source says which) and wiki_follow_up (candidate pages, eligible_claims with exact first quotes and inference marks, and draft: a page skeleton grouped by question whose sections are already split to wiki_write limits, remaining_claim_ids identifies claims that need another page; write within existing authorization after review).",
})


OPEN_OBJECT = {"type": "object", "properties": {}, "additionalProperties": True}
SERVICE_PROVIDER = {"type": "string", "enum": ["openai", "parallel"]}
SERVICE_OPTIONS = _object_schema({
    "model": _text_schema(81),
    "allow_untested_model": {"type": "boolean"},
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
    "aliases": _array_schema(_text_schema(100), 30),
    "sections": _array_schema(_object_schema({"heading": _text_schema(300), "text": _text_schema(12000),
        "claims": _array_schema(_object_schema({"research_id": RESEARCH_ID, "claim_id": RESEARCH_ID},
            ["research_id", "claim_id"]), 12, 1),
        "citations": _array_schema(_object_schema({"source_id": RESEARCH_ID, "quote": _text_schema(4000)},
                                                  ["source_id", "quote"]), 12, 1)}, ["heading", "text"]), 16, 1),
    "links": _array_schema(_object_schema({"page_id": RESEARCH_ID, "relation": _text_schema(500)}, ["page_id", "relation"]), 32),
    "review": _object_schema({"method": {"type": "string", "enum": ["human", "model"]},
        "reviewer": _text_schema(300), "note": _text_schema(4000)}, ["method", "reviewer", "note"]),
}, ["title", "kind", "sections", "links", "review"])
TOOL_SCHEMAS.update({
    "research_route": _object_schema({
        "depth": {"type": "string", "enum": ["auto", "quick", "agentic", "deep"]},
        "host": {"type": "string", "enum": ["codex", "claude_code", "dsh", "unknown"]},
        "task_shape": {"type": "string", "enum": ["lookup", "investigation", "batch_research"]},
        "observed_tools": _array_schema(_text_schema(300), 1000),
        "available_commands": _array_schema(_text_schema(300), 1000),
        "installed_extensions": _array_schema(_text_schema(300), 1000),
        "failed_routes": dict(_array_schema(_text_schema(300), 1000), uniqueItems=True),
        "provider": SERVICE_PROVIDER,
    }),
    "research_services": _object_schema({"provider": SERVICE_PROVIDER}),
    "research_service_prepare": _object_schema(SERVICE_INPUT, ["input"]),
    "research_service_start": _object_schema({**SERVICE_INPUT, "operation_id": RESEARCH_ID},
                                             ["operation_id", "input"]),
    "research_service_status": _object_schema({"external_id": RESEARCH_ID, "refresh": {"type": "boolean"}}, ["external_id"]),
    "research_service_result": _object_schema({"external_id": RESEARCH_ID, "refresh": {"type": "boolean"},
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50000}}, ["external_id"]),
    "research_service_cancel": _object_schema({"external_id": RESEARCH_ID}, ["external_id"]),
    "research_service_attach": _object_schema({"research_id": RESEARCH_ID, "operation_id": RESEARCH_ID,
        "provider": SERVICE_PROVIDER, "run_id": _text_schema(200), "question_id": RESEARCH_ID},
        ["operation_id", "provider", "run_id"]),
    "research_service_import": _object_schema({"external_id": RESEARCH_ID, "operation_id": RESEARCH_ID,
        "question_id": RESEARCH_ID}, ["external_id", "operation_id"]),
    "wiki_write": _object_schema({"page_id": RESEARCH_ID, "page": WIKI_PAGE, "change_note": _text_schema(4000),
        "sources": _array_schema(_object_schema({"id": RESEARCH_ID, "url": _text_schema(8192),
            "text": _text_schema(2000000), "capture_id": _text_schema(128), "title": _text_schema(2000),
            "retrieved_at": _text_schema(64), "kind": {"type": "string", "enum": ["page", "local_document", "external_report"]}},
            ["id", "url"]), 16, 1),
        "expected_revision": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "reviewed_input_version": {**_text_schema(200), "description": "The already-synchronized input version this page was checked against; closes source_input_changed for cited tasks at that version."}},
        ["page_id", "page", "change_note"]),
    "wiki_acknowledge": _object_schema({"page_id": RESEARCH_ID, "note": _text_schema(4000),
        "expected_revision": {"type": "integer", "minimum": 1, "maximum": 1000000}},
        ["page_id", "note"]),
    "wiki_get": _object_schema({"page_id": RESEARCH_ID, "revision": {"type": "integer", "minimum": 1, "maximum": 1000000}}, ["page_id"]),
    "wiki_list": _object_schema({"offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "source_url": _text_schema(8192)}),
    "wiki_work": _object_schema({
        "kind": {"type": "string", "enum": ["capture", "research", "page"]},
        "status": {"type": "string", "enum": ["archived", "pending", "compiled", "needs_review"]},
        "research_id": RESEARCH_ID, "page_id": RESEARCH_ID, "capture_id": _text_schema(128),
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
    "wiki_refresh": _object_schema({"page_id": RESEARCH_ID,
        "expected_revision": {"type": "integer", "minimum": 1, "maximum": 10001},
        "provider": {"type": "string", "enum": list(PROVIDER_NAMES)},
        "max_characters": {"type": "integer", "minimum": 100, "maximum": 100000},
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 16}}, ["page_id"]),
    "wiki_search": _object_schema({"query": _text_schema(500), "offset": {"type": "integer", "minimum": 0, "maximum": 10000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, ["query"]),
    "wiki_lint": _object_schema({"page_id": RESEARCH_ID}),
})
TOOL_DESCRIPTIONS.update({
    "research_route": "Describe available quick, agentic or deep routes without starting work. Collaboration and external services are optional; explicit provider is exclusive. failed_routes is cumulative and requires confirmed failures; observe active/unknown runs before choosing another route.",
    "research_services": "Describe optional OpenAI Deep Research and Parallel Task API configuration offline. Configured keys do not prove auth; anonymous Search MCP access is separate.",
    "research_service_prepare": "Preview a Deep Research API request without network. Pass input and optional provider/options. research_id is optional and adds an existing frozen scope; ordinary API research needs no local session.",
    "research_service_start": "Submit a provider-managed research task once using input and a stable operation_id; research_id is optional. Requires the configured service and credentials. Reusing the same operation returns its receipt; unknown outcomes are observed or attached, never automatically resubmitted.",
    "research_service_status": "Read saved provider-run state; refresh=true observes that same run once. Timeouts preserve last known state and never create a new run.",
    "research_service_result": "Read a saved provider report with pagination, provenance and unverified citations. refresh requests its result once; Parallel waits at most one server-side second. Original-source reviews are unchanged.",
    "research_service_cancel": "Request provider cancellation. Supported for OpenAI; not established for Parallel Task. An observation failure does not mean the job was cancelled.",
    "research_service_attach": "Attach a known provider run ID without submitting work, including recovery after a lost create response. Status stays unverified until observed.",
    "research_service_import": "Import a completed provider report as unreviewed secondary evidence. Original-URL coverage stays unchanged; read cited originals separately.",
    "wiki_write": "Save an authored, reviewed Wiki page with versioned citations. For ordinary sources, pass sources:[{id,url,text or capture_id,title?,retrieved_at?,kind?}] and section citations:[{source_id,quote}]; exact quotes are checked and retained internally in one call. Existing research claims are also supported. Read the current expected_revision before updates; review must name the actual reviewer.",
    "wiki_acknowledge": "Write an unchanged Wiki revision acknowledging review against current input versions. expected_revision prevents overwrites; note records the review. Repair invalid evidence/links first; unavailable input still needs review. No network or semantic scoring.",
    "wiki_get": "Read Wiki text with evidence links and separate integrity/freshness checks. Newer snapshots, expired/failed captures and relevant bookmark or linked-page changes need review. Current does not guarantee the live origin is unchanged; no fetch occurs.",
    "wiki_list": "List paginated Wiki pages offline. source_url filters direct citations and linked dependents for reviewing a changed webpage.",
    "wiki_work": "Recover archived, pending, compiled and needs_review work from saved captures, research and committed Wiki revisions. Returns pending claims, page/revision receipts and resume calls. Prefer an ID or kind to scope the audit. Read-only; no fetching, automatic writing or new authorization.",
    "wiki_refresh": "Fetch and archive up to 16 cited webpage URLs from one Wiki revision. Reports changed/unchanged/unverified captures and affected pages; follow continuation for more. Uses retrieval quota. Read saved captures and review new claims before wiki_write; authored text and bookmark packages stay unchanged.",
    "wiki_search": "Find authored Wiki text using an incremental character index, literal/spacing matching and explicit aliases. Validates matching candidates; invalid/retracted evidence is excluded. Freshness warnings remain visible. No embeddings or network calls.",
    "wiki_lint": "Audit all selected Wiki evidence, hashes, source freshness, crosslinks and history. Mechanical integrity and declared semantic review are reported separately; no network.",
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
        self._raw_library = None
        self._initialization_lock = threading.RLock()
        self._log_lock = threading.Lock()
        self._cancel_pending = None
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
        with self._initialization_lock:
            if self._providers is None:
                from web_search import SearchProviders
                self._providers = SearchProviders(settings=self.settings)
            return self._providers

    def _research(self):
        with self._initialization_lock:
            if self._research_sessions is None:
                from research import ResearchSessions
                self._research_sessions = ResearchSessions(settings=self.settings, engine=self._providers, db_path=self.db_path)
            return self._research_sessions

    def _log(self, message):
        with self._log_lock:
            self.stderr.write("bookmark-research MCP: " + message + "\n")
            self.stderr.flush()

    def _services(self):
        with self._initialization_lock:
            if self._research_services is None:
                from research_services import ResearchServices
                self._research_services = ResearchServices(settings=self.settings, research_sessions=self._research())
            return self._research_services

    def _wiki(self):
        from wiki import WikiStore
        # Settings can change under a long-lived stdio server, so a cached store
        # is rebound whenever the effective Wiki directory differs.
        with self._initialization_lock:
            selected = WikiStore.selected_directory(self.settings)
            if self._wiki_store is None or self._wiki_store.directory != Settings.external_path(
                    str(selected), "Wiki directory"):
                self._wiki_store = WikiStore(directory=selected, settings=self.settings,
                                             research_sessions=self._research())
            return self._wiki_store

    def _raw(self):
        # Rebuilt per call so archive/output setting changes apply without restart.
        if self._raw_library is not None:
            return self._raw_library
        from raw_library import RawLibrary
        return RawLibrary(settings=self.settings)

    def _tool_scope(self):
        """Environment override first, then the saved preference.

        DSH's plugin passes BOOKMARK_RESEARCH_TOOL_SCOPE to its child; an empty
        value deliberately restores the full catalog. The preference remains
        available for explicit profiles and tests.
        """
        override = os.environ.get("BOOKMARK_RESEARCH_TOOL_SCOPE")
        if override is not None:
            return [name.strip() for name in override.split(",") if name.strip()]
        preferences = self.settings.load()
        explicit = preferences.get("tool_scope") or []
        if explicit:
            return explicit
        if preferences.get("tool_scope_preset", "quick") == "quick":
            return list(Settings.QUICK_TOOLS)
        return []

    def _tool_names(self):
        """The tool surface this profile exposes; empty scope means all tools.

        Some hosts (notably DSH's MCP client) register every advertised tool and
        offer no allowlist. The server-side scope keeps the model-facing catalog
        small without deleting any implementation.
        """
        scope = self._tool_scope()
        return [name for name in TOOL_SCHEMAS if not scope or name in scope]

    def _tool_enabled(self, name):
        scope = self._tool_scope()
        return not scope or name in scope

    def _hydrate_sources(self, sources):
        """Turn capture pointers into verified evidence before bundling.

        A source may be a host-provided text (``text_origin=host``) or a saved
        capture (``capture_id``). Archive text is read from the immutable
        capture, hashed here, and checked against a caller-supplied
        ``text_sha256``; a mismatch is reported as unavailable, never silently
        accepted. The bundle itself stays pure and never opens a file.
        """
        if not isinstance(sources, list):
            return sources
        from archive import SourceArchive
        archive = SourceArchive(self.settings.load()["archive"]["directory"])
        hydrated = []
        for source in sources:
            if not isinstance(source, dict):
                hydrated.append(source)
                continue
            row = dict(source)
            capture_id = row.get("capture_id")
            if not capture_id:
                row.setdefault("text_origin", "host")
                row["quote_verified"] = False
                hydrated.append(row)
                continue
            try:
                result = archive.read_capture(capture_id, [row["url"]],
                    max_characters=100000, max_total_characters=800000)
                page = result["pages"][0]
                text = page.get("text")
                if text is None:
                    row.update(content_state="unavailable", error="no_text")
                else:
                    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    expected = row.get("text_sha256")
                    # A capture page may be longer than the per-page read cap.
                    # Accept a caller hash of the complete saved body, while
                    # still reporting the hash of the text actually returned.
                    full_digest = page.get("sha256")
                    if expected and expected not in (digest, full_digest):
                        row.update(content_state="unavailable", error="sha256_mismatch")
                    else:
                        row.update(text=text, text_origin="archive", text_sha256=digest,
                                   quote_verified=True, characters=len(text))
                        # Carry the capture's own page metadata into the bundle.
                        # Otherwise a verified archive read loses its title,
                        # publication date and content state on the way out.
                        for field in ("title", "published_at", "published_at_source",
                                      "published_at_confidence", "provider", "retrieved_at"):
                            if page.get(field) is not None and not row.get(field):
                                row[field] = page[field]
                        if page.get("content_state"):
                            row["content_state"] = page["content_state"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                row.update(content_state="unavailable", error="capture_unreadable: " + str(exc)[:200])
            hydrated.append(row)
        return hydrated

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
        wiki_methods = {"wiki_write": "write", "wiki_get": "get", "wiki_list": "list", "wiki_search": "search",
                        "wiki_lint": "lint", "wiki_acknowledge": "acknowledge", "wiki_refresh": "refresh", "wiki_work": "work"}
        if name in wiki_methods:
            return getattr(self._wiki(), wiki_methods[name])(**arguments)
        if name == "research_route":
            from routing import ResearchRouting
            return ResearchRouting(self.settings).route(**arguments)
        if name == "discovery_bundle":
            from discovery import budget_check, evidence_bundle
            options = dict(arguments)
            sources = self._hydrate_sources(options.pop("sources"))
            budget = budget_check(steps=options.pop("steps", 0), fetches=options.pop("fetches", 0),
                                  variants=options.pop("variants", 0),
                                  elapsed_seconds=options.pop("elapsed_seconds", 0))
            return {"budget": budget, **evidence_bundle(sources, **options)}
        if name == "get_settings":
            return self.settings.describe()
        if name == "update_settings":
            return self.settings.update(arguments["changes"])
        if name == "research_readiness":
            from readiness import Readiness
            return Readiness(settings=self.settings).check(**arguments)
        if name == "sync_package":
            result = self._sources().sync(**arguments)
            self._start_watcher()
            return result
        if name == "source_history":
            return self._sources().history(**arguments)
        if name == "source_remove":
            return self._sources().remove(**arguments)
        if name == "source_merge":
            return self._sources().merge(**arguments)
        if name == "plan_research" and not arguments.get("source_id"):
            from research_plan import ResearchPlan
            options = dict(arguments)
            options.pop("refresh", None)
            return ResearchPlan(settings=self.settings, wiki=self._wiki(), raw=self._raw()).build(**options)
        if name in ("search_bookmarks", "get_context", "plan_research"):
            options = dict(arguments)
            refresh = options.pop("refresh", True)
            pagination = {key: options.pop(key, default) for key, default in (
                ("collection", None), ("offset", 0), ("limit", 200), ("compact", False))
                } if name == "get_context" else None
            scope_notes = None if name != "get_context" or "item_id" in options else {
                "items": "get_context fills items only for one item_id; read a card's bookmarks with "
                         "search_bookmarks(section=...) or plan_research."}
            index = self._local()
            update = self._sources().refresh(options["source_id"]) if refresh else None
            if update and update["state"] in ("error", "unavailable"):
                raise ValueError(update["error"] + "; use refresh=false to read the saved index")
            with index.read_snapshot():
                if name == "plan_research":
                    from research_plan import ResearchPlan
                    result = ResearchPlan(index=index, settings=self.settings,
                                          wiki=self._wiki(), raw=self._raw()).build(**options)
                else:
                    method = index.search if name == "search_bookmarks" else index.context
                    result = method(**options)
                    if pagination is not None:
                        from context_output import compact_context, page_context
                        compact = pagination.pop("compact", False)
                        result = page_context(result, scope_notes=scope_notes, **pagination)
                        if compact:
                            result = compact_context(result)
                result["source"] = self._sources().source_status(options["source_id"])
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
            from archive import SourceArchive
            options = dict(arguments)
            raw = options.pop("raw", False)
            capture_id = options.pop("capture_id", None)
            offset = options.pop("offset", 0)
            prefs = self.settings.load()["fetch"]
            total = options.pop("max_total_characters", prefs["max_total_characters"])
            fair = prefs["fair_share_min"]
            if capture_id is not None:
                if raw or "provider" in options or "archive" in options:
                    raise ValueError("capture_id reads a saved extract; omit raw, provider and archive")
                return SourceArchive(self.settings.load()["archive"]["directory"]).read_capture(
                    capture_id, options["urls"],
                    max_characters=options.get("max_characters", prefs["max_characters"]),
                    max_total_characters=total, offset=offset, fair_share_min=fair)
            if offset:
                raise ValueError("offset requires capture_id so continued reads use the same saved evidence")
            result = self._web().fetch(**options)
            return result if raw else SourceArchive.compact_fetch(
                result, max_total_characters=total, fair_share_min=fair)
        if name == "search_archive":
            return self._raw().search(**arguments)
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

    def background_call(self, message):
        """Only tools without the transport thread's SQLite handle can run here."""
        if (not self.ready or message.get("jsonrpc") != "2.0" or message.get("method") != "tools/call"
                or set(message) - {"jsonrpc", "id", "method", "params"}):
            return False
        try:
            params = _params(message.get("params", {}), ("name", "arguments"), ("name",))
            name, arguments = params["name"], params.get("arguments", {})
            _validate(_text_schema(128), name, "name")
            if name not in TOOL_SCHEMAS:
                return False
            if not self._tool_enabled(name):
                return False
            _validate(TOOL_SCHEMAS[name], arguments)
        except RpcError:
            return False
        if name == "fetch_web":
            return "capture_id" not in arguments
        if name == "search_providers":
            return arguments.get("probe", False)
        if name == "research_readiness":
            return not arguments.get("offline", False)
        return name in {"search_web", "research_search", "research_fetch", "wiki_refresh",
                        "research_service_start", "research_service_status", "research_service_result",
                        "research_service_cancel", "research_service_attach", "research_service_import"}

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
                elif method == "notifications/cancelled":
                    _params(params, ("requestId", "reason"), ("requestId",))
                    _validate({"type": ["integer", "string"]}, params["requestId"], "requestId")
                    if "reason" in params:
                        _validate(_text_schema(1000), params["reason"], "reason")
                    if self._cancel_pending is not None:
                        self._cancel_pending(params["requestId"])
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
                # Some hosts prepend initialize.instructions to every tool.
                # Keep shared guidance in the Skill and specifics on each tool.
                result = {"protocolVersion": self.protocol, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "bookmark-research", "version": release_version()}}
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
                result = {"tools": [{"name": name, "description": TOOL_DESCRIPTIONS[name],
                                      "inputSchema": TOOL_SCHEMAS[name]}
                                     for name in self._tool_names()]}
            else:
                _params(params, ("name", "arguments"), ("name",))
                name = params["name"]
                _validate(_text_schema(128), name, "name")
                if name not in TOOL_SCHEMAS:
                    raise RpcError(-32602, "Unknown tool: " + name)
                if not self._tool_enabled(name):
                    raise RpcError(-32602, "Tool is outside this profile's tool_scope: " + name)
                arguments = params.get("arguments", {})
                _validate(TOOL_SCHEMAS[name], arguments)
                try:
                    value = self._call(name, arguments)
                    failed = ((name in ("fetch_web", "research_search", "research_fetch", "wiki_refresh") and value.get("status") == "error")
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


def serve(db_path, stdin=None, stdout=None, stderr=None, settings=None, workers=None, max_pending=None):
    """Serve line-delimited JSON-RPC until EOF; stdout contains protocol only."""
    incoming = stdin if stdin is not None else sys.stdin
    outgoing = stdout if stdout is not None else sys.stdout
    def emit(value):
        outgoing.write(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        outgoing.flush()

    server = StdioMcpServer(db_path, stderr=stderr, settings=settings)
    from mcp_dispatch import StdioRequestQueue
    queue = StdioRequestQueue(server, emit, workers=NETWORK_WORKERS if workers is None else workers,
                              max_pending=MAX_PENDING_CALLS if max_pending is None else max_pending)
    server._cancel_pending = queue.cancel
    interrupted = False
    try:
        while True:
            line = incoming.readline(MAX_MESSAGE_CHARS + 1)
            if not line:
                break
            if len(line) > MAX_MESSAGE_CHARS:
                queue.emit(_error(None, -32700, "JSON-RPC message exceeds size limit; connection closed"))
                interrupted = True
                break
            if not line.strip():
                continue
            try:
                request = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
            except (ValueError, RecursionError):
                queue.emit(_error(None, -32700, "Parse error: invalid JSON"))
                continue
            queue.submit(request)
            if queue.output_closed:
                interrupted = True
                break
    except (BrokenPipeError, KeyboardInterrupt):
        interrupted = True
    finally:
        queue.close(cancel_pending=interrupted)
        server.close()
