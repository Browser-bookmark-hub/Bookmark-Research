"""Perplexity Search API client; returns structured sources, not a model answer."""

import http.client
import json
import threading
import urllib.error
import urllib.request

from release import user_agent
from remote_mcp import McpError, McpHttpClient
from service_http import ResearchHttp, _NoRedirect


class PerplexityClient:
    SEARCH_URL = "https://api.perplexity.ai/search"

    def __init__(self, headers=None, timeout=30, search_url=None):
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.search_url = search_url or self.SEARCH_URL
        self._lock = threading.Lock()
        self._requests = 0

    def snapshot_usage(self):
        with self._lock:
            return {"http_requests": self._requests, "tool_calls": self._requests}

    def _request(self, query, limit):
        payload = json.dumps({"query": query, "max_results": max(1, min(int(limit), 20))},
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(self.search_url, data=payload, method="POST", headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": user_agent(), **self.headers})
        with self._lock:
            self._requests += 1
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                body = response.read(McpHttpClient.MAX_BYTES + 1)
            if len(body) > McpHttpClient.MAX_BYTES:
                raise McpError("Perplexity response exceeds size limit", "response_too_large")
            value = json.loads(body, object_pairs_hook=ResearchHttp._unique_object,
                               parse_constant=ResearchHttp._invalid_constant,
                               parse_float=ResearchHttp._finite_float)
            if not isinstance(value, dict) or not isinstance(value.get("results"), list):
                raise McpError("Perplexity returned invalid search results", "result_format")
            rows = []
            for item in value["results"]:
                if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                    continue
                snippet = item.get("snippet")
                rows.append({"url": item["url"], "title": item.get("title") or item["url"],
                             "snippet": snippet if isinstance(snippet, str) else "",
                             "date": item.get("date"), "last_updated": item.get("last_updated")})
            return {"structuredContent": {"results": rows}}
        except urllib.error.HTTPError as error:
            status = error.code
            kind = {400: "invalid_request", 401: "authentication_required", 403: "access_denied",
                    408: "timeout", 429: "rate_limited"}.get(status, "http_error")
            retry = McpHttpClient._retry_after((error.headers or {}).get("Retry-After"))
            try:
                error.close()
            except OSError:
                pass
            raise McpError("Perplexity Search HTTP " + str(status), kind,
                           status == 429 or status >= 500, http_status=status, retry_after=retry) from None
        except TimeoutError:
            raise McpError("Perplexity Search timed out", "timeout", True) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise McpError("Perplexity Search connection failed", "connection_error", True) from None
        except (ValueError, UnicodeError):
            raise McpError("Perplexity returned invalid JSON", "result_format") from None

    def call(self, purpose, query=None, urls=None, limit=5):
        if purpose != "search":
            raise McpError("Perplexity Search does not provide URL extraction", "capability_unavailable")
        if not self.headers.get("Authorization"):
            raise McpError("Perplexity Search requires PERPLEXITY_API_KEY", "authentication_required")
        return self._request(query, limit)
