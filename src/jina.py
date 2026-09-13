"""Jina Reader/Search HTTP access; no extra MCP server or model runtime."""

import concurrent.futures
import http.client
import json
import threading
import urllib.error
import urllib.request
from urllib.parse import urlencode

from remote_mcp import McpError, McpHttpClient
from service_http import ResearchHttp, _NoRedirect


class JinaClient:
    def __init__(self, headers=None, timeout=30):
        self.headers, self.timeout = dict(headers or {}), timeout
        self._lock = threading.Lock()
        self._requests = 0

    def snapshot_usage(self):
        with self._lock:
            return {"http_requests": self._requests, "tool_calls": self._requests}

    def _request(self, url, maximum):
        request = urllib.request.Request(url, headers={"Accept": "application/json",
            "User-Agent": "bookmark-research/0.4.0", "X-Timeout": str(int(self.timeout)), **self.headers})
        with self._lock:
            self._requests += 1
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                body = response.read(maximum + 1)
            if len(body) > maximum:
                raise McpError("Jina response exceeds size limit", "response_too_large")
            value = json.loads(body, object_pairs_hook=ResearchHttp._unique_object,
                               parse_constant=ResearchHttp._invalid_constant, parse_float=ResearchHttp._finite_float)
            if not isinstance(value, dict):
                raise McpError("Jina returned an unrecognized response", "result_format")
            code = value.get("code", 200)
            if type(code) is not int:
                raise McpError("Jina returned an invalid status", "result_format")
            if code >= 400:
                raise self._error(code)
            if "data" not in value:
                raise McpError("Jina returned an unrecognized response", "result_format")
            return value
        except urllib.error.HTTPError as error:
            failure = self._error(error.code, McpHttpClient._retry_after((error.headers or {}).get("Retry-After")))
            if error.fp is not None:
                try:
                    error.close()
                except OSError:
                    pass
            raise failure from None
        except TimeoutError:
            raise McpError("Jina request timed out", "timeout", True) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise McpError("Jina connection failed", "connection_error", True) from None
        except (ValueError, UnicodeError):
            raise McpError("Jina response is not valid JSON", "result_format") from None

    @staticmethod
    def _error(status, retry_after=None):
        kind = {401: "authentication_required", 403: "access_denied", 451: "access_denied",
                402: "quota_exhausted", 429: "rate_limited"}.get(status, "http_error")
        return McpError("Jina HTTP %s" % status, kind, status == 429 or status >= 500,
                        http_status=status, retry_after=retry_after)

    def call(self, purpose, query=None, urls=None):
        if purpose == "search":
            if not self.headers.get("Authorization"):
                raise McpError("Jina Search requires JINA_API_KEY", "authentication_required")
            value = self._request("https://s.jina.ai/?" + urlencode({"q": query}), McpHttpClient.MAX_BYTES)
            if not isinstance(value["data"], list):
                raise McpError("Jina Search returned invalid results", "result_format")
            return {"structuredContent": value}
        if purpose != "fetch":
            raise ValueError("Unknown Jina operation")

        def read(url):
            try:
                # Bound the combined raw response, allowing JSON wrapper overhead.
                value = self._request("https://r.jina.ai/" + url, McpHttpClient.MAX_BYTES // (2 * len(urls)))
                if not isinstance(value["data"], dict):
                    raise McpError("Jina Reader returned invalid page data", "result_format")
                return value, None
            except McpError as error:
                return None, {"url": url, **error.details()}

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(urls))) as pool:
            responses = list(pool.map(read, urls))
        # Keep successful HTTP envelopes intact. A failed sibling is not an
        # isError envelope that would discard other URLs' readable text.
        return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}
                            for value, error in responses if value is not None],
                "structuredContent": {"failed_results": [error for value, error in responses if error is not None]}}
