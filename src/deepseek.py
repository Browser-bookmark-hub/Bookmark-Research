"""DeepSeek Search / Fetch HTTP client.

Both endpoints are raw JSON tools APIs, not Chat Completions. Search returns
structured results with a summary and optional content; Fetch returns one page
as Markdown. The client normalizes both into the shapes the aggregator already
uses and classifies failures without exposing credentials or upstream bodies.
"""

import concurrent.futures
import http.client
import json
import threading
import urllib.error
import urllib.request

from release import user_agent
from remote_mcp import McpError, McpHttpClient
from service_http import ResearchHttp, _NoRedirect


class DeepSeekClient:
    SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
    FETCH_URL = "https://api.deepseek.com/v1/tools/fetch"

    def __init__(self, headers=None, timeout=30, search_url=None, fetch_url=None):
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.search_url = search_url or self.SEARCH_URL
        self.fetch_url = fetch_url or self.FETCH_URL
        self._lock = threading.Lock()
        self._requests = 0

    def snapshot_usage(self):
        with self._lock:
            return {"http_requests": self._requests, "tool_calls": self._requests}

    def _request(self, url, payload):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": user_agent(), **self.headers})
        with self._lock:
            self._requests += 1
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                data = response.read(McpHttpClient.MAX_BYTES + 1)
            if len(data) > McpHttpClient.MAX_BYTES:
                raise McpError("DeepSeek response exceeds size limit", "response_too_large")
            value = json.loads(data, object_pairs_hook=ResearchHttp._unique_object,
                               parse_constant=ResearchHttp._invalid_constant,
                               parse_float=ResearchHttp._finite_float)
            if not isinstance(value, dict):
                raise McpError("DeepSeek returned an unrecognized response", "result_format")
            if value.get("error"):
                raise self._body_error(value["error"])
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
            raise McpError("DeepSeek request timed out", "timeout", True) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise McpError("DeepSeek connection failed", "connection_error", True) from None
        except (ValueError, UnicodeError):
            raise McpError("DeepSeek response is not valid JSON", "result_format") from None

    @staticmethod
    def _error(status, retry_after=None):
        kind = {400: "invalid_request", 401: "authentication_required", 402: "quota_exhausted",
                403: "access_denied", 404: "not_found", 408: "timeout",
                429: "rate_limited"}.get(status, "http_error")
        return McpError("DeepSeek HTTP %s" % status, kind, status == 429 or status >= 500,
                        http_status=status, retry_after=retry_after)

    @classmethod
    def _body_error(cls, error):
        if not isinstance(error, dict):
            return McpError("DeepSeek returned an error", "provider_error")
        code = error.get("code")
        message = error.get("message") if isinstance(error.get("message"), str) else "DeepSeek returned an error"
        kind = {401: "authentication_required", 402: "quota_exhausted", 403: "access_denied",
                404: "not_found", 429: "rate_limited"}.get(code, "provider_error")
        return McpError(message[:500], kind, code == 429 or (isinstance(code, int) and code >= 500))

    @staticmethod
    def _results(value):
        rows = value.get("results")
        if rows is None and isinstance(value.get("data"), dict):
            rows = value["data"].get("results")
        return rows if isinstance(rows, list) else None

    def call(self, purpose, query=None, urls=None, limit=None):
        if purpose == "search":
            if not self.headers.get("Authorization"):
                raise McpError("DeepSeek Search requires DEEPSEEK_API_KEY", "authentication_required")
            count = 10 if limit is None else max(1, min(int(limit), 50))
            value = self._request(self.search_url, {"query": query, "count": count, "need_content": False})
            rows = self._results(value)
            if rows is None:
                raise McpError("DeepSeek Search returned invalid results", "result_format")
            results = []
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("url"), str):
                    continue
                summary = row.get("summary") or row.get("snippet") or ""
                content = row.get("content") if isinstance(row.get("content"), str) else ""
                results.append({"url": row["url"], "title": row.get("title") or row["url"],
                                "snippet": summary if isinstance(summary, str) else "",
                                "content": content, "date": row.get("date"),
                                "authority": row.get("authority"),
                                "rerank_score": row.get("rerank_score")})
            return {"structuredContent": {"results": results}}
        if purpose != "fetch":
            raise ValueError("Unknown DeepSeek operation")
        if not self.headers.get("Authorization"):
            raise McpError("DeepSeek Fetch requires DEEPSEEK_API_KEY", "authentication_required")
        if not isinstance(urls, list) or not urls:
            raise ValueError("DeepSeek Fetch requires urls")

        def read(url):
            try:
                value = self._request(self.fetch_url, {"url": url})
                data = value.get("data") if isinstance(value.get("data"), dict) else value
                content = data.get("content") or data.get("text") or data.get("markdown") or ""
                return {"url": url, "title": data.get("title") or "",
                        "content": content if isinstance(content, str) else ""}
            except McpError as error:
                return {"url": url, "error": str(error), "error_kind": error.kind}

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(urls))) as pool:
            results = list(pool.map(read, urls))
        return {"structuredContent": {"results": results}}
