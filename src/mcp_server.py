"""Minimal, synchronous stdio MCP tools server; no third-party SDK required.

Each stdin/stdout message is one JSON-RPC object on one line. This server
implements initialization, ping, tools/list and tools/call, not resources,
prompts, sampling, tasks, HTTP transports or arbitrary SQL/command execution.
"""

import json
import sys

from settings import Settings


PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MAX_MESSAGE_CHARS = 256 * 1024
MAX_RESULT_CHARS = 2 * 1024 * 1024
PROVIDER_NAMES = ("exa", "parallel", "tavily")


def _text_schema(maximum=2048):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _array_schema(item, maximum, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}


def _object_schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


IDENTIFIER = _text_schema(512)
PROVIDERS = dict(_array_schema({"type": "string", "enum": list(PROVIDER_NAMES)}, 3, 1), uniqueItems=True)
SETTINGS_SCHEMA = _object_schema({
    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
    "search": _object_schema({"providers": PROVIDERS,
        "limit_per_target": {"type": "integer", "minimum": 1, "maximum": 20}}),
    "fetch": _object_schema({"provider": {"type": "string", "enum": list(PROVIDER_NAMES)},
        "max_characters": {"type": "integer", "minimum": 100, "maximum": 100000}}),
    "archive": _object_schema({"enabled": {"type": "boolean"}, "directory": _text_schema(4096)}),
})
TOOL_SCHEMAS = {
    "get_settings": _object_schema({}),
    "update_settings": _object_schema({"changes": SETTINGS_SCHEMA}, ["changes"]),
    "sync_package": _object_schema({"package_path": _text_schema(4096), "source_id": IDENTIFIER}, ["package_path"]),
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
    "update_settings": "Persist the requested preference changes outside the plugin and canvas packages. Supports default search providers, fetch provider/length, timeout, and automatic source archival. Applies to subsequent calls without restart. Does not store credentials or modify host integrations.",
    "sync_package": "Read a Bookmark Canvas JSON/.canvas package into a persistent derived index. Source files are never modified. Supply an existing source_id explicitly when importing a moved or partial export of that source. Absent section files are retained; a supplied canvas entry replaces the previous layout.",
    "search_bookmarks": "Search bookmark metadata with literal title/URL/note/tag/folder-path matching and exact SQL scopes. Targets have independent totals and pages; this is not semantic webpage-body retrieval. Refresh checks the registered package by default; refresh=false uses the last synchronized index. Historical package versions are not stored.",
    "get_context": "Read section headers, bookmark metadata, folder ancestry, geometric group membership and directed canvas edges. Copy anchors share their primary tree. Refresh is enabled by default.",
    "index_status": "Read registered sources, counts and package availability without refreshing or fetching webpages.",
    "search_web": "Search the requested targets through selected public web providers, using saved defaults when options are omitted (initially Exa and Parallel). Search snippets are not verified full-page evidence; search does not automatically fetch or archive result pages.",
    "fetch_web": "Fetch known HTTP(S) URLs using saved defaults. By default, archive the actual provider response, identified Markdown extracts and provenance outside the canvas package. archive=false disables saving for this call. Extraction may be partial. Does not add pages or vectors to the bookmark index.",
    "search_providers": "Describe configured Exa/Parallel/Tavily provider metadata without network access by default. probe=true explicitly performs capability discovery; discovery does not prove execution permission or successful retrieval.",
}

RESEARCH_ID = _text_schema(80)
CLAIM_IDS = dict(_array_schema(RESEARCH_ID, 100, 1), uniqueItems=True)
RESEARCH_ENTRY = _object_schema({
    "kind": {"type": "string", "enum": ["claim", "answer", "gap", "conflict", "resolution", "question", "interruption", "source_review", "retraction", "resume"]},
    "question_id": RESEARCH_ID, "id": RESEARCH_ID, "question": _text_schema(4000),
    "statement": _text_schema(4000), "answer": _text_schema(12000), "text": _text_schema(4000),
    "claim_ids": CLAIM_IDS, "conflict_id": RESEARCH_ID, "operation_id": RESEARCH_ID,
    "claim_id": RESEARCH_ID, "source_id": RESEARCH_ID,
    "verdict": {"type": "string", "enum": ["accepted", "rejected", "uncertain"]},
    "confidence": {"type": "string", "enum": ["low", "medium", "high"]}, "inference": {"type": "boolean"},
    "citations": _array_schema(_object_schema({"source_id": RESEARCH_ID, "quote": _text_schema(4000)},
                                                ["source_id", "quote"]), 12, 1),
}, ["kind"])
TOOL_SCHEMAS.update({
    "research_start": _object_schema({
        "brief": _text_schema(12000), "scope": {"type": "string", "maxLength": 12000},
        "questions": _array_schema(_object_schema({"id": RESEARCH_ID, "question": _text_schema(4000)},
                                                  ["id", "question"]), 24, 1),
        "providers": PROVIDERS, "source_ids": _array_schema(IDENTIFIER, 100),
        "bookmark_refs": _array_schema(_object_schema({"source_id": IDENTIFIER, "section_id": IDENTIFIER,
                                                        "item_id": IDENTIFIER}, ["source_id", "section_id", "item_id"]), 100),
        "budget": _object_schema({"max_search_calls": {"type": "integer", "minimum": 0, "maximum": 120},
            "max_fetch_calls": {"type": "integer", "minimum": 0, "maximum": 80},
            "max_rounds": {"type": "integer", "minimum": 0, "maximum": 40}}),
    }, ["brief", "questions"]),
    "research_status": _object_schema({"research_id": RESEARCH_ID,
        "section": {"type": "string", "enum": ["questions", "claims", "sources", "operations", "conflicts", "bookmark_context", "events"]},
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
    "research_record": _object_schema({"research_id": RESEARCH_ID, "entry": RESEARCH_ENTRY}, ["research_id", "entry"]),
    "research_finish": _object_schema({
        "research_id": RESEARCH_ID, "summary": _text_schema(16000),
        "status": {"type": "string", "enum": ["completed", "incomplete", "cancelled"]},
        "limitations": _array_schema(_text_schema(4000), 100),
    }, ["research_id", "summary"]),
})
TOOL_DESCRIPTIONS.update({
    "research_start": "Start a durable host-led deep research session with explicit questions and retrieval budgets. Creates local state outside packages, performs no network calls, and starts no background model. Scope and local source labels are not sent to providers.",
    "research_status": "List saved research sessions or read a bounded progress overview. For complete entries, select section and paginate with offset/limit; overview shows at most 20 previews per collection. Performs no network requests. A pending intent is not proof that a worker is running.",
    "research_search": "Execute and save one search round for specified research questions. Reserve one search attempt per unique provider/question/query before access. Reusing operation_id with identical arguments returns the recorded outcome without resubmission.",
    "research_fetch": "Read selected URLs for a research question and persist actual responses and identifiable text in this session's evidence directory. This research tool always retains evidence, independently of fetch_web archiving settings. Reuse operation_id for safe outcome lookup.",
    "research_source": "Read a saved research source by ID with pagination and SHA-256 verification. This reads extracted text, which may be partial; it does not contact a provider.",
    "research_record": "Record quoted claims, source reviews, retractions, supported answers, gaps, conflicts/resolutions, questions, or interrupted operations. kind=resume with text reopens an incomplete report, preserving prior artifacts and budgets. Kinds have different required fields; see deep-research.md. Quote matching proves text presence, not factual entailment.",
    "research_finish": "Write a report and source manifest. Completed requires supported answers to every question and no open conflicts or pending operations. Use incomplete when evidence or budgets are insufficient. Validates cited text hashes; never fabricates a finished research report.",
})


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _validate(schema, value, location="arguments"):
    kind = schema["type"]
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool)}[kind]
    if not valid:
        raise RpcError(-32602, "%s must be %s" % (location, kind))
    if "enum" in schema and value not in schema["enum"]:
        raise RpcError(-32602, "%s has an unsupported value" % location)
    if kind == "object":
        properties = schema["properties"]
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
    elif kind == "integer":
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
        self._providers = None
        self._research_sessions = None
        self.settings = settings if settings is not None else Settings()

    def close(self):
        if self._index is not None:
            self._index.close()
            self._index = None

    def _local(self):
        if self._index is None:
            from bookmark_index import BookmarkIndex
            self._index = BookmarkIndex(self.db_path)
        return self._index

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

    def _call(self, name, arguments):
        # Explicit dispatch ensures input can never select a Python method,
        # executable, SQL statement, or unadvertised capability.
        research_methods = {"research_start": "start", "research_status": "status", "research_search": "search",
                            "research_fetch": "fetch", "research_source": "source", "research_record": "record",
                            "research_finish": "finish"}
        if name in research_methods:
            return getattr(self._research(), research_methods[name])(**arguments)
        if name == "get_settings":
            return self.settings.describe()
        if name == "update_settings":
            return self.settings.update(arguments["changes"])
        if name == "sync_package":
            return self._local().sync(**arguments)
        if name in ("search_bookmarks", "get_context"):
            options = dict(arguments)
            refresh = options.pop("refresh", True)
            index = self._local()
            update = index.refresh(options["source_id"]) if refresh else None
            method = index.search if name == "search_bookmarks" else index.context
            result = method(**options)
            result["refresh"] = {"performed": refresh, "mode": "checked_package" if refresh else "saved_snapshot", "sync": update}
            return result
        if name == "index_status":
            return self._local().status(**arguments)
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
            raise ValueError("Tool result exceeds size limit; narrow the scope or lower the result limit")
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
                    "serverInfo": {"name": "bookmark-research", "version": "0.2.0"}}
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
