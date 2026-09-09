"""Small Streamable HTTP client for the selected public search MCPs.

This client declares no sampling/roots capabilities and does not implement OAuth.
Hosts remain responsible for interactive OAuth and general-purpose MCP sessions.
"""

import json
import math
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit


class McpError(RuntimeError):
    """A safe, classified failure; upstream bodies and credentials are omitted."""

    def __init__(self, message, kind="protocol_error", retryable=False,
                 http_status=None, rpc_code=None, retry_after=None):
        super().__init__(message)
        self.kind, self.retryable = kind, retryable
        self.http_status, self.rpc_code = http_status, rpc_code
        self.retry_after = retry_after

    def details(self):
        result = {"error": str(self), "error_kind": self.kind, "retryable": self.retryable}
        for key, value in (("http_status", self.http_status), ("rpc_code", self.rpc_code),
                           ("retry_after_seconds", self.retry_after)):
            if value is not None:
                result[key] = value
        return result


class McpHttpClient:
    """A bounded initialize/list/call client accepting JSON or SSE responses."""

    MAX_BYTES = 2_000_000
    MAX_TOOL_PAGES = 8
    MAX_TOOLS = 256
    PROTOCOLS = {"2025-03-26", "2025-06-18", "2025-11-25"}

    def __init__(self, url, headers=None, timeout=30):
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            raise ValueError("MCP endpoint must use HTTPS")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("MCP endpoint must use HTTPS without embedded credentials")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 60:
            raise ValueError("timeout must be between 1 and 60 seconds")
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.session_id = None
        self.protocol = "2025-03-26"
        self.counter = 0
        self.initialized = False
        self.catalog_version = 0
        self._lock = threading.RLock()
        self._usage = {"http_requests": 0, "initialize_requests": 0,
                       "list_requests": 0, "tool_calls": 0, "session_recoveries": 0}

    def snapshot_usage(self):
        with self._lock:
            return dict(self._usage)

    def reset_session(self):
        with self._lock:
            self.initialized, self.session_id = False, None
            self.catalog_version += 1

    @staticmethod
    def _retry_after(value):
        if not isinstance(value, str) or len(value) > 100:
            return None
        try:
            seconds = float(value)
        except ValueError:
            try:
                stamp = parsedate_to_datetime(value)
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                seconds = (stamp - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return None
        return min(86400, max(0, math.ceil(seconds))) if math.isfinite(seconds) else None

    def _http_error(self, status, retry_after=None):
        kind, retryable = "http_error", False
        if status in (401, 403):
            kind = "authentication_required"
        elif status == 402:
            kind = "quota_exhausted"
        elif status == 404 and self.initialized and self.session_id:
            kind, retryable = "session_expired", True
            self.reset_session()
        elif status == 429:
            kind, retryable = "rate_limited", True
        elif status in (408, 500, 502, 503, 504):
            kind, retryable = "transient_http", True
        return McpError("MCP HTTP %s" % status, kind, retryable,
                        http_status=status, retry_after=retry_after)

    def _message(self, body):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "User-Agent": "bookmark-research/0.2.0"}
        if self.initialized:
            headers["MCP-Protocol-Version"] = self.protocol
        request = urllib.request.Request(
            self.url, json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers=headers, method="POST")
        # urllib follows redirects; credentials must stay on the configured endpoint.
        for header, value in self.headers.items():
            request.add_unredirected_header(header, value)
        if self.session_id:
            request.add_unredirected_header("Mcp-Session-Id", self.session_id)
        self._usage["http_requests"] += 1
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    if len(session) > 4096 or any(not 0x21 <= ord(c) <= 0x7E for c in session):
                        raise McpError("MCP server returned an invalid session identifier")
                    self.session_id = session
                if "id" not in body or "method" not in body:
                    if response.status not in (200, 202, 204):
                        raise McpError("MCP notification or response was not accepted")
                    return None
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    return self._read_sse(response, body["id"])
                data = response.read(self.MAX_BYTES + 1)
                if len(data) > self.MAX_BYTES:
                    raise McpError("MCP response exceeds size limit", "response_too_large")
                return self._result(json.loads(data), body["id"])
        except urllib.error.HTTPError as error:
            # Never echo response bodies/URLs: a service may reflect credentials.
            failure = self._http_error(error.code, self._retry_after((error.headers or {}).get("Retry-After")))
            if error.fp is not None:
                error.close()
            raise failure from None
        except urllib.error.URLError as error:
            kind = "timeout" if isinstance(error.reason, (TimeoutError, socket.timeout)) else "connection_error"
            raise McpError("MCP connection failed (%s)" % type(error.reason).__name__, kind, True) from None
        except (TimeoutError, OSError) as error:
            kind = "timeout" if isinstance(error, (TimeoutError, socket.timeout)) else "connection_error"
            raise McpError("MCP transport failed (%s)" % type(error).__name__, kind, True) from None
        except (ValueError, UnicodeError, RecursionError):
            raise McpError("MCP returned invalid JSON or text") from None

    @staticmethod
    def _result(message, request_id):
        messages = message if isinstance(message, list) else [message]
        for item in messages:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("id"), bool) or item.get("id") != request_id:
                continue
            if item.get("jsonrpc") != "2.0" or ("result" in item and "error" in item):
                raise McpError("MCP returned an invalid JSON-RPC response")
            if "error" in item:
                code = item["error"].get("code") if isinstance(item["error"], dict) else None
                if type(code) is not int:
                    raise McpError("MCP returned an invalid JSON-RPC error")
                kind = {-32602: "schema_mismatch", -32601: "tool_unavailable"}.get(code, "rpc_error")
                raise McpError("MCP RPC error (%s)" % code, kind, rpc_code=code)
            if "result" in item:
                return item["result"]
        raise McpError("MCP response did not match request ID")

    def _read_sse(self, response, request_id):
        deadline = time.monotonic() + self.timeout
        event = []
        consumed = 0
        while time.monotonic() < deadline:
            line = response.readline(self.MAX_BYTES + 1)
            consumed += len(line)
            if consumed > self.MAX_BYTES:
                raise McpError("MCP response exceeds size limit", "response_too_large")
            if not line and not event:
                break
            text = line.decode("utf-8").rstrip("\r\n")
            if text.startswith("data:"):
                event.append(text[5:].lstrip(" "))
            if (not text or not line) and event:
                data = "\n".join(event)
                event = []
                # 2025-11-25 servers may prime a resumable stream with empty data.
                if not data:
                    continue
                message = json.loads(data)
                messages = message if isinstance(message, list) else [message]
                for incoming in messages:
                    if (isinstance(incoming, dict) and incoming.get("jsonrpc") == "2.0"
                            and incoming.get("method") == "notifications/tools/list_changed"
                            and "id" not in incoming):
                        self.catalog_version += 1
                    if not isinstance(incoming, dict) or "method" not in incoming or "id" not in incoming:
                        continue
                    if (incoming.get("jsonrpc") != "2.0" or
                            type(incoming["id"]) not in (int, str)):
                        raise McpError("MCP returned an invalid JSON-RPC request")
                    # Ping does not depend on sampling, roots or other capabilities.
                    if incoming["method"] != "ping":
                        raise McpError("MCP server requested an unsupported client capability", "unsupported_capability")
                    self._message({"jsonrpc": "2.0", "id": incoming["id"], "result": {}})
                if any(isinstance(m, dict) and m.get("id") == request_id
                       and ("result" in m or "error" in m) for m in messages):
                    return self._result(message, request_id)
            if not line:
                break
        raise McpError("MCP SSE ended or timed out without a matching response", "incomplete_response", True)

    def request(self, method, params=None):
        with self._lock:
            self.counter += 1
            metric = {"initialize": "initialize_requests", "tools/list": "list_requests",
                      "tools/call": "tool_calls"}.get(method)
            if metric:
                self._usage[metric] += 1
            body = {"jsonrpc": "2.0", "id": self.counter, "method": method}
            if params is not None:
                body["params"] = params
            return self._message(body)

    def initialize(self):
        with self._lock:
            self.reset_session()
            try:
                result = self.request("initialize", {
                    "protocolVersion": self.protocol, "capabilities": {},
                    "clientInfo": {"name": "bookmark-research", "version": "0.2.0"}})
                if (not isinstance(result, dict) or not isinstance(result.get("protocolVersion"), str)
                        or result["protocolVersion"] not in self.PROTOCOLS):
                    raise McpError("MCP server selected an unsupported protocol version")
                self.protocol = result["protocolVersion"]
                self.initialized = True
                self._message({"jsonrpc": "2.0", "method": "notifications/initialized"})
            except Exception:
                self.reset_session()
                raise
            return result

    def list_tools(self):
        with self._lock:
            # An expired session definitively rejects metadata requests. Recover
            # once, discarding earlier pages; never splice two catalogs together.
            for recovery in range(2):
                try:
                    return self._tool_pages()
                except McpError as error:
                    if error.kind != "session_expired" or recovery:
                        raise
                    self._usage["session_recoveries"] += 1

    def _tool_pages(self):
        if not self.initialized:
            self.initialize()
        tools, names, cursors, cursor, size = [], set(), set(), None, 0
        for _ in range(self.MAX_TOOL_PAGES):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise McpError("MCP tools/list returned an invalid tool list")
            size += len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if size > self.MAX_BYTES or len(tools) + len(result["tools"]) > self.MAX_TOOLS:
                raise McpError("MCP tool catalog exceeds size limit", "response_too_large")
            for tool in result["tools"]:
                if (not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                        or not tool["name"] or len(tool["name"]) > 256 or tool["name"] in names):
                    raise McpError("MCP tools/list returned invalid or duplicate tool names")
                names.add(tool["name"])
                tools.append(tool)
            cursor = result.get("nextCursor")
            if cursor is None or cursor == "":
                return tools
            if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in cursors:
                raise McpError("MCP tools/list returned an invalid or repeated pagination cursor")
            cursors.add(cursor)
        raise McpError("MCP tool catalog exceeds pagination limit", "response_too_large")

    def call_tool(self, name, arguments):
        with self._lock:
            if not self.initialized:
                self.initialize()
            # One semantic attempt, including 404/429/timeouts. A response loss
            # does not prove a billable tool was not executed.
            result = self.request("tools/call", {"name": name, "arguments": arguments})
            if not isinstance(result, dict):
                raise McpError("MCP tool returned an invalid result")
            if result.get("isError"):
                raise McpError("MCP tool returned an error", "tool_error")
            return result
