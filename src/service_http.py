"""Single-request HTTP transport for documented research APIs, without retries."""

import json
import http.client
import math
import os
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class ServiceError(RuntimeError):
    def __init__(self, kind, message, uncertain=False, http_status=None, retry_after=None):
        super().__init__(message)
        self.kind = kind
        self.uncertain = uncertain
        self.http_status = http_status
        self.retry_after = retry_after

    def details(self):
        return {"error_kind": self.kind, "error": str(self),
                "request_outcome_unknown": self.uncertain,
                "http_status": self.http_status, "retry_after_seconds": self.retry_after}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Provider credentials must never follow an unexpected redirect.
        return None


class ResearchHttp:
    PROVIDERS = {
        "openai": {"origin": "https://api.openai.com", "key_env": "OPENAI_API_KEY"},
        "parallel": {"origin": "https://api.parallel.ai", "key_env": "PARALLEL_API_KEY"},
    }
    MAX_RESPONSE_BYTES = 8 * 1024 * 1024

    def __init__(self, timeout=30):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("Research API timeout must be greater than 0 and at most 60 seconds")
        self.timeout = timeout

    @staticmethod
    def _unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON field")
            value[key] = item
        return value

    @staticmethod
    def _invalid_constant(value):
        raise ValueError("Non-finite JSON number")

    @staticmethod
    def _finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON number")
        return number

    @classmethod
    def _endpoint(cls, provider, method, path, payload):
        if not isinstance(provider, str) or provider not in cls.PROVIDERS:
            raise ValueError("Unsupported research provider")
        if not isinstance(path, str) or not isinstance(method, str):
            raise ValueError("Unsupported research API request")
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment or any(ord(char) < 32 for char in path):
            raise ValueError("Unsupported research API request")
        suffix = r"[A-Za-z0-9_-]{1,192}"
        if provider == "openai":
            create = path == "/v1/responses" and method == "POST"
            read = method == "GET" and re.fullmatch(r"/v1/responses/resp_" + suffix, path)
            cancel = method == "POST" and re.fullmatch(r"/v1/responses/resp_" + suffix + r"/cancel", path)
        else:
            create = path == "/v1/tasks/runs" and method == "POST"
            read = method == "GET" and re.fullmatch(r"/v1/tasks/runs/trun_" + suffix + r"(?:/result\?timeout=1)?", path)
            cancel = False
        if not (create or read or cancel):
            raise ValueError("Unsupported research API request")
        if (create and not isinstance(payload, dict)) or (read and payload is not None) or (cancel and payload not in (None, {})):
            raise ValueError("Invalid payload for this research API operation")

    def request(self, provider, method, path, payload=None):
        self._endpoint(provider, method, path, payload)
        info = self.PROVIDERS[provider]
        key = os.environ.get(info["key_env"])
        if not key or any(not 33 <= ord(char) <= 126 for char in key):
            raise ServiceError("authentication_required", "Set " + info["key_env"] + " in the host environment")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if provider == "openai":
            headers["Authorization"] = "Bearer " + key
        else:
            headers["x-api-key"] = key
        try:
            data = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise ValueError("Research API payload must contain valid JSON") from None
        request = urllib.request.Request(info["origin"] + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                body = response.read(self.MAX_RESPONSE_BYTES + 1)
            if len(body) > self.MAX_RESPONSE_BYTES:
                raise ServiceError("response_too_large", "Research API response exceeds the local size limit", uncertain=True)
            result = json.loads(body.decode("utf-8"), object_pairs_hook=self._unique_object,
                                parse_constant=self._invalid_constant, parse_float=self._finite_float)
            if not isinstance(result, dict):
                raise ServiceError("result_format", "Research API returned a non-object response", uncertain=True)
            return result
        except urllib.error.HTTPError as error:
            status = error.code
            kind = {401: "authentication_required", 403: "authentication_required", 404: "run_unavailable",
                    408: "result_pending", 429: "rate_limited", 400: "invalid_request", 422: "invalid_request"}.get(status, "http_error")
            retry = error.headers.get("Retry-After") if error.headers else None
            retry = int(retry) if isinstance(retry, str) and len(retry) <= 5 and retry.isascii() and retry.isdigit() and int(retry) <= 86400 else None
            try:
                error.close()
            except OSError:
                pass
            raise ServiceError(kind, "Research API HTTP " + str(status),
                               uncertain=status >= 500 or status == 408 or (method == "POST" and 300 <= status < 400),
                               http_status=status, retry_after=retry) from None
        except (TimeoutError, socket.timeout):
            raise ServiceError("timeout", "Research API observation timed out", uncertain=True) from None
        except urllib.error.URLError:
            raise ServiceError("connection_error", "Research API connection failed", uncertain=True) from None
        except (OSError, http.client.HTTPException):
            # IncompleteRead and low-level socket failures may carry response
            # bytes or request context. Never expose their exception strings.
            raise ServiceError("connection_error", "Research API connection failed or response was interrupted", uncertain=True) from None
        except (ValueError, UnicodeError):
            raise ServiceError("result_format", "Research API response is not valid JSON", uncertain=True) from None
