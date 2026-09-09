"""Small Streamable HTTP client for the selected public search MCPs.

This client declares no sampling/roots capabilities and does not implement OAuth.
Hosts remain responsible for interactive OAuth and general-purpose MCP sessions.
"""

import json
import time
import urllib.error
import urllib.request


class McpHttpClient:
    """A bounded initialize/list/call client accepting JSON or SSE responses."""

    MAX_BYTES = 2_000_000
    PROTOCOLS = {"2025-03-26", "2025-06-18", "2025-11-25"}

    def __init__(self, url, headers=None, timeout=30):
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError("MCP endpoint must use HTTPS")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 60:
            raise ValueError("timeout must be between 1 and 60 seconds")
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.session_id = None
        self.protocol = "2025-03-26"
        self.counter = 0
        self.initialized = False

    def _message(self, body):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "User-Agent": "bookmark-research/0.1.0"}
        if self.initialized:
            headers["MCP-Protocol-Version"] = self.protocol
        request = urllib.request.Request(
            self.url, json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST")
        # urllib follows redirects; credentials must stay on the configured endpoint.
        for header, value in self.headers.items():
            request.add_unredirected_header(header, value)
        if self.session_id:
            request.add_unredirected_header("Mcp-Session-Id", self.session_id)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                if "id" not in body or "method" not in body:
                    if response.status not in (200, 202, 204):
                        raise RuntimeError("MCP notification or response was not accepted")
                    return None
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    return self._read_sse(response, body["id"])
                data = response.read(self.MAX_BYTES + 1)
                if len(data) > self.MAX_BYTES:
                    raise RuntimeError("MCP response exceeds size limit")
                return self._result(json.loads(data), body["id"])
        except urllib.error.HTTPError as error:
            # Never echo response bodies/URLs: a service may reflect credentials.
            raise RuntimeError("MCP HTTP %s" % error.code) from None
        except urllib.error.URLError as error:
            raise RuntimeError("MCP connection failed (%s)" % type(error.reason).__name__) from None
        except (TimeoutError, OSError) as error:
            raise RuntimeError("MCP transport failed (%s)" % type(error).__name__) from None
        except (ValueError, UnicodeError) as error:
            raise RuntimeError("MCP returned invalid JSON or text") from error

    @staticmethod
    def _result(message, request_id):
        messages = message if isinstance(message, list) else [message]
        for item in messages:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("id"), bool) or item.get("id") != request_id:
                continue
            if item.get("jsonrpc") != "2.0" or ("result" in item and "error" in item):
                raise RuntimeError("MCP returned an invalid JSON-RPC response")
            if "error" in item:
                code = item["error"].get("code") if isinstance(item["error"], dict) else None
                if type(code) is not int:
                    raise RuntimeError("MCP returned an invalid JSON-RPC error")
                raise RuntimeError("MCP RPC error (%s)" % code)
            if "result" in item:
                return item["result"]
        raise RuntimeError("MCP response did not match request ID")

    def _read_sse(self, response, request_id):
        deadline = time.monotonic() + self.timeout
        event = []
        consumed = 0
        while time.monotonic() < deadline:
            line = response.readline(self.MAX_BYTES + 1)
            consumed += len(line)
            if consumed > self.MAX_BYTES:
                raise RuntimeError("MCP response exceeds size limit")
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
                    if not isinstance(incoming, dict) or "method" not in incoming or "id" not in incoming:
                        continue
                    if (incoming.get("jsonrpc") != "2.0" or
                            type(incoming["id"]) not in (int, str)):
                        raise RuntimeError("MCP returned an invalid JSON-RPC request")
                    # Ping does not depend on sampling, roots or other capabilities.
                    if incoming["method"] != "ping":
                        raise RuntimeError("MCP server requested an unsupported client capability")
                    self._message({"jsonrpc": "2.0", "id": incoming["id"], "result": {}})
                if any(isinstance(m, dict) and m.get("id") == request_id
                       and ("result" in m or "error" in m) for m in messages):
                    return self._result(message, request_id)
            if not line:
                break
        raise RuntimeError("MCP SSE ended or timed out without a matching response")

    def request(self, method, params=None):
        self.counter += 1
        body = {"jsonrpc": "2.0", "id": self.counter, "method": method}
        if params is not None:
            body["params"] = params
        return self._message(body)

    def initialize(self):
        self.initialized, self.session_id = False, None
        try:
            result = self.request("initialize", {
                "protocolVersion": self.protocol, "capabilities": {},
                "clientInfo": {"name": "bookmark-research", "version": "0.1.0"}})
            if (not isinstance(result, dict) or not isinstance(result.get("protocolVersion"), str)
                    or result["protocolVersion"] not in self.PROTOCOLS):
                raise RuntimeError("MCP server selected an unsupported protocol version")
            self.protocol = result["protocolVersion"]
            self.initialized = True
            self._message({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:
            self.initialized, self.session_id = False, None
            raise
        return result

    def list_tools(self):
        if not self.initialized:
            self.initialize()
        result = self.request("tools/list", {})
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise RuntimeError("MCP tools/list returned an invalid tool list")
        # Only selected, small provider catalogs are supported; fail on truncation.
        if result.get("nextCursor"):
            raise RuntimeError("MCP paginated tool catalogs require a host MCP client")
        return result["tools"]

    def call_tool(self, name, arguments):
        if not self.initialized:
            self.initialize()
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict) or result.get("isError"):
            raise RuntimeError("MCP tool returned an error")
        return result
