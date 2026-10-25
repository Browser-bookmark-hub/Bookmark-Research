"""Query selected existing search MCPs and retain provider/target provenance."""

import concurrent.futures
import copy
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from remote_mcp import McpError, McpHttpClient
from provider_adapters import ProviderAdapter
from search_results import _canonical_url, fuse_results
from settings import Settings
from credentials import Credentials


class _ProviderState:
    def __init__(self):
        self.lock = threading.RLock()
        self.client, self.identity = None, None
        self.catalog, self.catalog_client, self.catalog_version = None, None, None
        self.catalog_expires, self.observed_at = 0, None
        self.cooldown_error, self.cooldown_until = None, 0
        self.empty_attempts = 0


class SearchProviders:
    """Aggregate retrieval providers; no model, crawler, or OAuth implementation."""

    SCHEMA_CACHE_SECONDS = 300
    SEARCH_CACHE_MAX_ENTRIES = 512
    MAX_CATALOG_BYTES = 1_000_000
    MAX_CATALOG_TOOLS = 256
    USAGE_FIELDS = ("tool_calls", "http_requests", "initialize_requests", "list_requests", "session_recoveries", "cache_hits")

    def __init__(self, timeout=None, settings=None):
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 60):
            raise ValueError("timeout must be between 1 and 60 seconds")
        self.timeout = timeout
        self.settings = settings if settings is not None else Settings()
        self.credentials = Credentials(self.settings)
        self.registry = json.loads(
            (Path(__file__).resolve().parent.parent / "config/providers.json").read_text(encoding="utf-8"))
        self._states = {name: _ProviderState() for name in self.registry["providers"]}
        self.session_id = uuid.uuid4().hex
        # Short-TTL reuse of identical searches; empty unless search.cache_seconds is set.
        self._search_cache = {}
        self._cache_lock = threading.Lock()

    def _selected(self, providers):
        selected = self.settings.load()["search"]["providers"] if providers is None else providers
        if not isinstance(selected, list) or not selected or not all(isinstance(x, str) for x in selected):
            raise ValueError("providers must be a nonempty list of names")
        selected = list(dict.fromkeys(selected))
        unknown = set(selected) - set(self.registry["providers"])
        if unknown:
            raise ValueError("Unknown providers: " + ", ".join(sorted(unknown)))
        return selected

    def describe(self, providers=None):
        names = self._selected(providers) if providers is not None else list(self.registry["providers"])
        preferences = self.settings.load()
        return {"probe_performed": False, "default_providers": preferences["search"]["providers"],
                "search_fallback_providers": preferences["search"]["fallback_providers"],
                "default_fetch_providers": Settings.fetch_providers(preferences),
                "providers": [{"provider": name, **self.registry["providers"][name],
                               "availability": "not_probed", "authentication_state": self._authentication(name),
                               "operations": {purpose: {"credential_required": bool(variable),
                                   "credential_configured": bool(self.credentials.get(variable)) if variable else None,
                                   "default_role": ("primary" if name in preferences["search"]["providers"] else
                                       "fallback" if name in preferences["search"]["fallback_providers"] else "not_selected") if purpose == "search" else
                                       ("primary" if name == preferences["fetch"]["provider"] else
                                        "fallback" if name in preferences["fetch"]["providers"] else "not_selected"),
                                   "missing": [variable] if variable and not self.credentials.get(variable) else []}
                                   for purpose in ("search", "fetch")
                                   for variable in [self.registry["providers"][name].get("required_env", {}).get(purpose)]}}
                              for name in names],
                "schema_cache_seconds": self.SCHEMA_CACHE_SECONDS,
                "note": "Configuration is not proof of connection, authentication, or service availability. No OAuth flow is implemented."}

    def _authentication(self, provider):
        info = self.registry["providers"][provider]
        variables = list(info.get("optional_header_env", {}).values()) + [info.get("optional_bearer_env")]
        configured = any(self.credentials.get(variable) for variable in variables if variable)
        return {"mode": "api_key" if configured else ("keyless" if info.get("keyless_headers") else "anonymous"),
                "credential_configured": configured, "credential_validity_verified": False,
                "oauth_implemented": False}

    def _client(self, provider):
        info = self.registry["providers"][provider]
        if not info["direct_client"]:
            raise McpError("This provider requires a host-managed MCP client", "unsupported_capability")
        headers = {}
        for header, variable in info.get("optional_header_env", {}).items():
            if self.credentials.get(variable):
                headers[header] = self.credentials.get(variable)
        variable = info.get("optional_bearer_env")
        if variable and self.credentials.get(variable):
            headers["Authorization"] = "Bearer " + self.credentials.get(variable)
        if not headers:
            headers.update(info.get("keyless_headers", {}))
        timeout = self.timeout if self.timeout is not None else self.settings.load()["timeout_seconds"]
        # Identity stays in memory. Neither headers nor credential fingerprints
        # are included in metadata, usage reports, logs or persisted settings.
        identity = (info["url"], tuple(sorted(headers.items())), timeout)
        state = self._states[provider]
        with state.lock:
            if state.client is None or state.identity != identity:
                if info.get("transport") == "http":
                    if info.get("client") == "deepseek":
                        from deepseek import DeepSeekClient
                        state.client = DeepSeekClient(headers=headers, timeout=timeout,
                                                      search_url=info.get("search_url"),
                                                      fetch_url=info.get("fetch_url"))
                    else:
                        from jina import JinaClient
                        state.client = JinaClient(headers=headers, timeout=timeout)
                else:
                    state.client = McpHttpClient(info["url"], headers=headers, timeout=timeout)
                state.identity = identity
                state.catalog = None
                state.cooldown_error, state.cooldown_until = None, 0
            return state.client

    def _adapter(self, provider):
        return ProviderAdapter(provider, self.registry["providers"][provider])

    def _catalog(self, provider, client, usage, refresh=False):
        state = self._states[provider]
        version = getattr(client, "catalog_version", None)
        version = version if type(version) is int else None
        if (not refresh and state.catalog is not None and state.catalog_client is client
                and state.catalog_version == version and state.catalog_expires > time.monotonic()):
            usage["cache_hits"] += 1
            return state.catalog
        usage["list_requests"] += 1
        tools = client.list_tools()
        if not isinstance(tools, list) or len(tools) > self.MAX_CATALOG_TOOLS:
            raise McpError("Provider tool catalog is invalid", "protocol_error")
        if len(json.dumps(tools, ensure_ascii=False).encode("utf-8")) > self.MAX_CATALOG_BYTES:
            raise McpError("Provider tool catalog exceeds cache size limit", "response_too_large")
        state.catalog, state.catalog_client = copy.deepcopy(tools), client
        version = getattr(client, "catalog_version", None)
        state.catalog_version = version if type(version) is int else None
        state.catalog_expires = time.monotonic() + self.SCHEMA_CACHE_SECONDS
        state.observed_at = datetime.now(timezone.utc).isoformat()
        return state.catalog

    @classmethod
    def _empty_usage(cls):
        return dict.fromkeys(cls.USAGE_FIELDS, 0)

    @staticmethod
    def _snapshot(client):
        snapshot = getattr(client, "snapshot_usage", None)
        result = snapshot() if callable(snapshot) else None
        return result if isinstance(result, dict) else None

    def _usage(self, client, before, fallback):
        after = self._snapshot(client) if client is not None and before is not None else None
        if after is None:
            return fallback
        return {key: max(0, after.get(key, 0) - before.get(key, 0)) if key != "cache_hits" else fallback[key]
                for key in self.USAGE_FIELDS}

    @staticmethod
    def _unparsed_excerpt(result, limit=400):
        """Bounded, whitespace-collapsed head of a response we could not normalize."""
        if not isinstance(result, dict):
            return None
        parts = []
        blocks = result.get("content")
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict) and isinstance(block.get("text"), str) and block["text"].strip():
                    parts.append(block["text"])
        if not parts and isinstance(result.get("structuredContent"), (dict, list)) and result["structuredContent"]:
            try:
                parts = [json.dumps(result["structuredContent"], ensure_ascii=False)]
            except (TypeError, ValueError):
                return None
        text = re.sub(r"\s+", " ", "\n".join(parts)).strip()
        return text[:limit] or None

    @staticmethod
    def _failure(error):
        if isinstance(error, McpError):
            return error.details()
        # Never return arbitrary exception messages: a transport, fake adapter,
        # or service may reflect an endpoint containing credentials.
        return {"error": "Provider operation failed (%s)" % type(error).__name__,
                "error_kind": "provider_error", "retryable": False}

    def _probe_one(self, provider):
        state = self._states[provider]
        with state.lock:
            client, before, usage = None, None, self._empty_usage()
            try:
                if self.registry["providers"][provider].get("transport") == "http":
                    return {"provider": provider, "status": "not_probed", "tools": [],
                            "network_probe_performed": False, "catalog_source": "documented_http_api",
                            "capabilities": {purpose: {"status": "supported", "execution_verified": False}
                                             for purpose in ("search", "fetch")},
                            "authentication_state": self._authentication(provider), "usage": usage}
                client = self._client(provider)
                before = self._snapshot(client)
                tools = self._catalog(provider, client, usage, refresh=True)
                native = self.registry["providers"][provider].get("native_research", {})
                return {"provider": provider, "status": "ok", "tools": copy.deepcopy(tools),
                        "capabilities": self._adapter(provider).capabilities(tools, self.session_id),
                        "native_research": {**native, "advertised_tools": [tool["name"] for tool in tools
                                             if tool.get("name") in native.get("tools", [])],
                                            "execution_verified": False, "invoked_by_aggregator": False},
                        "catalog_observed_at": state.observed_at,
                        "authentication_state": self._authentication(provider),
                        "usage": self._usage(client, before, usage)}
            except (RuntimeError, ValueError, OSError) as error:
                state.catalog = None
                return {"provider": provider, "status": "error", **self._failure(error),
                        "usage": self._usage(client, before, usage)}

    def probe(self, providers=None):
        names = self._selected(providers)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as pool:
            results = list(pool.map(self._probe_one, names))
        return {"probe_performed": True, "providers": results,
                "successful_provider_count": sum(row["status"] == "ok" for row in results),
                "note": "MCP probes perform initialize/tools/list; HTTP providers report their local API mapping without a request. Neither proves successful retrieval."}

    def _tool(self, provider, purpose, tools):
        return self._adapter(provider).select(purpose, tools)

    @staticmethod
    def _arguments(tool, purpose, query=None, urls=None, limit=5, max_characters=12000):
        # Preserve the old helper for callers/tests; runtime routing always
        # selects the provider explicitly, never by overlapping field names.
        name = tool.get("name", "")
        provider = "tavily" if name.startswith("tavily") else ("parallel" if name in ("web_search", "web_fetch") else "exa")
        return ProviderAdapter(provider, {}).arguments(tool, purpose, query, urls, limit, max_characters)

    @staticmethod
    def _records(value):
        if isinstance(value, list):
            if all(isinstance(x, dict) and "url" in x for x in value):
                return value
        if isinstance(value, dict):
            for key in ("results", "search_results", "items"):
                if isinstance(value.get(key), list):
                    return value[key]
            for key in ("data", "result"):
                if isinstance(value.get(key), (dict, list)):
                    rows = SearchProviders._records(value[key])
                    if rows is not None:
                        return rows
        return None

    @staticmethod
    def _result_error(result):
        """Recognize provider error envelopes even when MCP isError is false.

        A keyless endpoint can return a successful HTTP/MCP response containing
        a quota error. Treat that as a failed retrieval, not an empty result or
        an unknown search format. Never interpret next_actions as instructions.
        """
        candidates = [result.get("structuredContent")]
        content = result.get("content", [])
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                try:
                    candidates.append(json.loads(block.get("text", "")))
                except (ValueError, TypeError):
                    pass
        codes = {
            "monthly_cap_reached_bonus_eligible": "quota_exhausted",
            "monthly_cap_reached": "quota_exhausted",
            "usage_limit_exceeded": "quota_exhausted",
            "insufficient_quota": "quota_exhausted",
            "rate_limit_exceeded": "rate_limited",
            "rate_limited": "rate_limited",
            "invalid_api_key": "authentication_required",
            "missing_api_key": "authentication_required",
            "unauthorized": "authentication_required",
        }
        for value in candidates:
            if not isinstance(value, dict):
                continue
            detail = value.get("error") if isinstance(value.get("error"), dict) else value
            code = detail.get("code")
            kind = codes.get(code) if isinstance(code, str) else None
            if kind is not None:
                delay = detail.get("retry_after_seconds")
                delay = delay if type(delay) is int and 0 <= delay <= 86400 else None
                messages = {"quota_exhausted": "Search provider quota exhausted",
                            "rate_limited": "Search provider rate limited this request",
                            "authentication_required": "Search provider requires valid authentication"}
                return McpError(messages[kind], kind, kind == "rate_limited", retry_after=delay)
            if value.get("error") and SearchProviders._records(value) is None:
                return McpError("Search provider returned an error envelope", "tool_error")
        if result.get("isError") is True:
            return McpError("Search provider tool reported an error", "tool_error")
        return None

    @staticmethod
    def _normalize(result):
        failure = SearchProviders._result_error(result)
        if failure is not None:
            raise failure
        rows = SearchProviders._records(result.get("structuredContent"))
        content = result.get("content", [])
        if not isinstance(content, list):
            raise McpError("Provider tool returned an invalid content array", "result_format")
        texts = [block["text"] for block in content
                 if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)]
        if rows is None:
            for text in texts:
                try:
                    rows = SearchProviders._records(json.loads(text))
                except ValueError:
                    continue
                if rows is not None:
                    break
        if rows is None:
            # Exa's documented text output uses record headers, not every URL in prose.
            records = []
            for text in texts:
                for block in re.split(r"(?m)(?=^Title:\s)", text):
                    match = re.search(r"(?m)^URL:\s*(https?://\S+)\s*$", block)
                    title = re.search(r"(?m)^Title:\s*(.+)$", block)
                    if match and title:
                        records.append({"url": match.group(1), "title": title.group(1),
                                        "snippet": block[match.end():].strip()})
            rows = records or None
        if rows is None:
            raise McpError("Unrecognized provider result format; use native MCP output with merge-results", "result_format")
        normalized = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("url"), str):
                continue
            try:
                _canonical_url(row["url"])
            except ValueError:
                continue
            snippet = row.get("snippet") or row.get("text") or row.get("content") or row.get("excerpts") or ""
            if isinstance(snippet, list):
                snippet = "\n".join(x for x in snippet if isinstance(x, str))
            if not isinstance(snippet, str):
                snippet = ""
            title = row.get("title") if isinstance(row.get("title"), str) else row["url"]
            normalized.append({"url": row["url"], "title": title, "snippet": snippet,
                               "rank": len(normalized) + 1})
        if rows and not normalized:
            raise McpError("Provider returned no parseable search results", "result_format")
        return normalized

    def _execute(self, provider, purpose, query=None, urls=None, limit=5, max_characters=12000):
        state = self._states[provider]
        with state.lock:
            client, before, tool, arguments = None, None, None, {}
            usage, skipped = self._empty_usage(), False
            try:
                client = self._client(provider)
                before = self._snapshot(client)
                credential = self.registry["providers"][provider].get("required_env", {}).get(purpose)
                if credential and not self.credentials.get(credential):
                    raise McpError("This operation requires " + credential, "authentication_required")
                if state.cooldown_error is not None and time.monotonic() < state.cooldown_until:
                    skipped = True
                    raise state.cooldown_error
                if self.registry["providers"][provider].get("transport") == "http":
                    tool = {"name": self.registry["providers"][provider][purpose + "_tools"][0]}
                    arguments = {"query": query} if purpose == "search" else {"urls": urls}
                    if purpose == "search":
                        arguments["limit"] = limit
                    result = client.call(purpose, **arguments)
                else:
                    catalog = self._catalog(provider, client, usage)
                    adapter = self._adapter(provider)
                    tool = adapter.select(purpose, catalog)
                    arguments = adapter.arguments(tool, purpose, query, urls, limit, max_characters, self.session_id)
                    usage["tool_calls"] += 1
                    result = client.call_tool(tool["name"], arguments)
                if not isinstance(result, dict):
                    raise McpError("Provider tool returned an invalid result", "result_format")
                failure = self._result_error(result)
                if failure is not None:
                    raise failure
                return {"status": "ok", "result": result, "tool": tool["name"], "request_arguments": arguments,
                        "usage": self._usage(client, before, usage)}
            except (RuntimeError, ValueError, OSError) as error:
                if isinstance(error, McpError):
                    if error.kind in ("session_expired", "schema_mismatch", "tool_unavailable", "protocol_error"):
                        state.catalog = None
                    if error.kind in ("rate_limited", "quota_exhausted") and not skipped:
                        state.cooldown_error = error
                        delay = 300 if error.kind == "quota_exhausted" else 5
                        state.cooldown_until = time.monotonic() + (error.retry_after if error.retry_after is not None else delay)
                return {"status": "error", **self._failure(error), "skipped_due_to_cooldown": skipped,
                        "tool": tool["name"] if tool else None, "request_arguments": arguments,
                        "usage": self._usage(client, before, usage)}

    def _note_empty_attempt(self, provider, message):
        """Stall a provider briefly after repeated unreadable or empty batches.

        Two consecutive batches without usable output are treated as a provider
        problem rather than a query or page problem; the provider is skipped
        with a classified error until the stall expires, and any usable result
        clears the counter. In-process only: a restart retries every provider.
        """
        state = self._states[provider]
        with state.lock:
            state.empty_attempts += 1
            if state.empty_attempts >= 2 and time.monotonic() >= state.cooldown_until:
                state.cooldown_error = McpError(message, "provider_stalled", True)
                state.cooldown_until = time.monotonic() + 300
                state.empty_attempts = 0

    def _note_usable_result(self, provider):
        state = self._states[provider]
        with state.lock:
            state.empty_attempts = 0

    def _cached_search(self, provider, query, limit, margin=0.0):
        """Return (retrieved_at, rows) for a fresh identical search, else None."""
        ttl = self.settings.load()["search"]["cache_seconds"]
        if not ttl:
            return None
        with self._cache_lock:
            entry = self._search_cache.get((provider, query, limit))
        if entry is None or entry["expires"] <= time.monotonic() + margin:
            return None
        return entry["retrieved_at"], entry["rows"]

    def _store_search(self, provider, query, limit, retrieved_at, rows):
        ttl = self.settings.load()["search"]["cache_seconds"]
        if not ttl or not rows:
            return
        now = time.monotonic()
        with self._cache_lock:
            if len(self._search_cache) >= self.SEARCH_CACHE_MAX_ENTRIES:
                for key in [key for key, entry in self._search_cache.items() if entry["expires"] <= now]:
                    self._search_cache.pop(key, None)
                while len(self._search_cache) >= self.SEARCH_CACHE_MAX_ENTRIES:
                    self._search_cache.pop(next(iter(self._search_cache)))
            self._search_cache[(provider, query, limit)] = {
                "expires": now + ttl, "retrieved_at": retrieved_at, "rows": rows}

    def cached_search_pairs(self, targets, providers, limit):
        """Count provider jobs a fresh cache would serve without a request.

        Research reserves provider budget before the request phase; entries
        close to expiry are reported as uncached so the reservation stays
        honest even if the cache turns over before execution.
        """
        names = self._selected(providers)
        return sum(1 for name in names for row in targets
                   if self._cached_search(name, row["query"], limit, margin=5.0))

    def _search_one(self, work):
        provider, target, query, limit = work
        base = {"provider": provider, "target": target, "query": query,
                "retrieved_at": datetime.now(timezone.utc).isoformat()}
        cached = self._cached_search(provider, query, limit)
        if cached is not None:
            # A repeated identical search returns the saved rows unchanged; the
            # original retrieval time is kept and no provider is called.
            retrieved_at, rows = cached
            return {**base, "retrieved_at": retrieved_at, "status": "ok", "results": rows,
                    "result_state": "nonempty", "cached": True, "tool": None,
                    "request_arguments": {}, "usage": self._empty_usage()}
        outcome = self._execute(provider, "search", query=query, limit=limit)
        if outcome["status"] == "error":
            if outcome.get("error_kind") == "result_format" and not outcome.get("skipped_due_to_cooldown"):
                self._note_empty_attempt(provider, "Provider repeatedly returned unreadable search results; skipped briefly")
            return {**base, **outcome, "results": [], "result_state": "failed"}
        result = None
        try:
            result = outcome.pop("result")
            rows = self._normalize(result)[:limit]
            self._note_usable_result(provider)
            self._store_search(provider, query, limit, base["retrieved_at"], rows)
            return {**base, **outcome, "results": rows, "result_state": "nonempty" if rows else "empty"}
        except (RuntimeError, ValueError, OSError) as error:
            failure = self._failure(error)
            batch = {**base, **outcome, "status": "error", "results": [], "result_state": "failed", **failure}
            if failure.get("error_kind") == "result_format":
                self._note_empty_attempt(provider, "Provider repeatedly returned unreadable search results; skipped briefly")
                # Search responses are not archived; keep a bounded head of the
                # unreadable payload in the receipt so a shape failure can be
                # attributed after the fact.
                excerpt = self._unparsed_excerpt(result)
                if excerpt is not None:
                    batch["unparsed_excerpt"] = excerpt
            return batch

    def _search_provider(self, work):
        provider, queries, limit = work
        return [self._search_one((provider, target, query, limit)) for target, query in queries]

    def _search_batches(self, jobs, limit):
        grouped = {}
        for provider, target, query in jobs:
            grouped.setdefault(provider, []).append((target, query))
        # One worker per provider avoids starving independent providers with
        # multiple queued calls waiting for the same provider's session lock.
        work = [(provider, queries, limit) for provider, queries in grouped.items()]
        if not work:
            return []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(work)) as pool:
            return [batch for results in pool.map(self._search_provider, work) for batch in results]

    def _search_batches_hedged(self, jobs, limit, queries, grace, deadline):
        """Race primary providers; abandon the slow ones once every query is resolved.

        All provider workers start together. Once each query has a usable
        result, a provider still running after the grace window (or any
        provider past the total deadline) is abandoned. Abandoned requests may
        still complete and consume provider quota; their results and usage are
        not collected. Collected batches keep provider order.
        """
        grouped = {}
        for provider, target, query in jobs:
            grouped.setdefault(provider, []).append((target, query))
        work = [(provider, provider_queries, limit) for provider, provider_queries in grouped.items()]
        if not work:
            return [], []
        deadline_at = time.monotonic() + deadline if deadline is not None else None
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(work))
        futures = {pool.submit(self._search_provider, item): item[0] for item in work}
        collected, seen, abandoned, first_completed = {}, [], [], None
        try:
            while futures:
                resolved = not self._unresolved_queries(queries, seen)
                limits = []
                if resolved and first_completed is not None and grace is not None:
                    limits.append(first_completed + grace)
                if deadline_at is not None:
                    limits.append(deadline_at)
                wait_until = min(limits) if limits else None
                timeout = None if wait_until is None else max(0.0, wait_until - time.monotonic())
                done, pending = concurrent.futures.wait(futures, timeout=timeout,
                                                        return_when=concurrent.futures.FIRST_COMPLETED)
                if not done:
                    now = time.monotonic()
                    if deadline_at is not None and now >= deadline_at:
                        reason = "deadline"
                    elif resolved and first_completed is not None and grace is not None:
                        reason = "grace_expired"
                    else:
                        continue
                    abandoned = [{"provider": futures[future], "reason": reason}
                                 for future in sorted(pending, key=lambda item: futures[item])]
                    break
                for future in done:
                    provider = futures.pop(future)
                    rows = future.result()
                    collected[provider] = rows
                    seen.extend(rows)
                if first_completed is None:
                    first_completed = time.monotonic()
        finally:
            pool.shutdown(wait=False)
        batches = [batch for provider, _, _ in work for batch in collected.get(provider, ())]
        return batches, abandoned

    def _search_batches_staggered(self, jobs, limit, queries, grace, deadline):
        """Submit providers one at a time, each held back by the grace window.

        The first provider starts immediately; the next is submitted only when
        queries remain unresolved after the delay, so a provider that already
        resolved everything leaves the rest uncalled. Once every query is
        resolved the call returns after the grace window, and providers past
        the deadline are abandoned.
        """
        grouped = {}
        for provider, target, query in jobs:
            grouped.setdefault(provider, []).append((target, query))
        work = [(provider, provider_queries, limit) for provider, provider_queries in grouped.items()]
        if not work:
            return [], [], []
        delay = grace if grace is not None else 0.0
        deadline_at = time.monotonic() + deadline if deadline is not None else None
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(work))
        queue = list(work)
        futures = {}
        collected, seen, abandoned, first_completed = {}, [], [], None

        def dispatch():
            item = queue.pop(0)
            futures[pool.submit(self._search_provider, item)] = item[0]
            return time.monotonic()

        last_dispatch = dispatch()
        try:
            while futures or queue:
                resolved = not self._unresolved_queries(queries, seen)
                if not futures:
                    if resolved:
                        break
                    now = time.monotonic()
                    fire_at = last_dispatch + delay
                    if deadline_at is not None:
                        fire_at = min(fire_at, deadline_at)
                    if now < fire_at:
                        time.sleep(fire_at - now)
                    if deadline_at is not None and time.monotonic() >= deadline_at:
                        break
                    last_dispatch = dispatch()
                    continue
                limits = []
                if resolved and first_completed is not None and grace is not None:
                    limits.append(first_completed + grace)
                if deadline_at is not None:
                    limits.append(deadline_at)
                if queue and not resolved:
                    limits.append(last_dispatch + delay)
                wait_until = min(limits) if limits else None
                timeout = None if wait_until is None else max(0.0, wait_until - time.monotonic())
                done, pending = concurrent.futures.wait(futures, timeout=timeout,
                                                        return_when=concurrent.futures.FIRST_COMPLETED)
                if done:
                    for future in done:
                        provider = futures.pop(future)
                        rows = future.result()
                        collected[provider] = rows
                        seen.extend(rows)
                    if first_completed is None:
                        first_completed = time.monotonic()
                    continue
                now = time.monotonic()
                if deadline_at is not None and now >= deadline_at:
                    reason = "deadline"
                elif resolved and first_completed is not None and grace is not None:
                    reason = "grace_expired"
                elif queue and not resolved and now >= last_dispatch + delay:
                    last_dispatch = dispatch()
                    continue
                else:
                    continue
                abandoned = [{"provider": futures[future], "reason": reason}
                             for future in sorted(pending, key=lambda item: futures[item])]
                break
        finally:
            pool.shutdown(wait=False)
        batches = [batch for provider, _, _ in work if provider in collected for batch in collected[provider]]
        return batches, abandoned, [provider for provider, _, _ in queue]

    def _search_sequential(self, jobs, limit, queries):
        """Consult providers in order; later ones receive only unresolved queries.

        The frugal strategy: a provider that resolves every query ends the
        stage, and providers never called are reported as not attempted.
        """
        grouped = {}
        for provider, target, query in jobs:
            grouped.setdefault(provider, []).append((target, query))
        work = [(provider, provider_queries, limit) for provider, provider_queries in grouped.items()]
        batches, not_attempted = [], []
        for index, (provider, provider_queries, provider_limit) in enumerate(work):
            pending = self._unresolved_queries(queries, batches)
            if batches and not pending:
                not_attempted = [name for name, _, _ in work[index:]]
                break
            remaining = [pair for pair in provider_queries if pair in pending]
            if not remaining:
                continue
            batches.extend(self._search_provider((provider, remaining, provider_limit)))
        return batches, not_attempted

    @staticmethod
    def _unresolved_queries(queries, batches):
        found = set()
        for batch in batches:
            if batch.get("status") != "ok":
                continue
            for row in batch.get("results", []):
                try:
                    _canonical_url(row.get("url"))
                except (ValueError, AttributeError):
                    continue
                found.add((batch["target"], batch["query"]))
                break
        return [pair for pair in queries if pair not in found]

    def search(self, targets, providers=None, limit_per_target=None, *, fallback_providers=None,
               reserve_fallback=None, hedge=None):
        preferences = self.settings.load()
        if limit_per_target is None:
            limit_per_target = preferences["search"]["limit_per_target"]
        if not isinstance(targets, list) or not 1 <= len(targets) <= 12:
            raise ValueError("targets must contain 1 to 12 target/query objects or plain query strings")
        if type(limit_per_target) is not int or not 1 <= limit_per_target <= 20:
            raise ValueError("limit_per_target must be between 1 and 20")
        queries = []
        for row in targets:
            if isinstance(row, str):
                # Plain strings are shorthand: the query is its own target label.
                row = {"target": row, "query": row}
            if not isinstance(row, dict) or set(row) - {"target", "query"}:
                raise ValueError("Each target must be a target/query object or a plain query string")
            if not all(isinstance(row.get(key), str) and row[key].strip() for key in ("target", "query")):
                raise ValueError("Each target needs nonempty target and query strings")
            if len(row["query"]) > 2000 or len(row["target"]) > 200:
                raise ValueError("Target or query is too long")
            queries.append((row["target"].strip(), row["query"].strip()))
        queries = list(dict.fromkeys(queries))
        names = self._selected(preferences["search"]["providers"] if providers is None else providers)
        if fallback_providers is None:
            fallback_providers = preferences["search"]["fallback_providers"] if providers is None else []
        if not isinstance(fallback_providers, list):
            raise ValueError("fallback_providers must be a list of names")
        fallbacks = [name for name in self._selected(fallback_providers) if name not in names] if fallback_providers else []
        strategy = preferences["search"]["strategy"]
        grace = preferences["search"]["grace_seconds"]
        deadline = preferences["search"]["deadline_seconds"]
        if hedge is False:
            # Complete-scope callers (research) keep the wait-for-all behavior.
            strategy, grace, deadline = "wait_all", None, None
        if strategy in ("hedged", "staggered") and grace is None and deadline is None:
            strategy = "wait_all"
        primary_jobs = [(name, target, query) for name in names for target, query in queries]
        not_attempted = []
        if strategy == "wait_all":
            batches, abandoned = self._search_batches(primary_jobs, limit_per_target), []
        elif strategy == "sequential":
            batches, not_attempted = self._search_sequential(primary_jobs, limit_per_target, queries)
            abandoned = []
        elif strategy == "staggered":
            batches, abandoned, not_attempted = self._search_batches_staggered(
                primary_jobs, limit_per_target, queries, grace, deadline)
        else:
            batches, abandoned = self._search_batches_hedged(primary_jobs, limit_per_target, queries, grace, deadline)
        pending = self._unresolved_queries(queries, batches)
        skipped, jobs = [], []
        if pending:
            for name in fallbacks:
                credential = self.registry["providers"][name].get("required_env", {}).get("search")
                if credential and not self.credentials.get(credential):
                    skipped.append({"provider": name, "reason": "authentication_required", "missing": [credential]})
                else:
                    jobs.extend((name, target, query) for target, query in pending)
        selected = reserve_fallback(jobs) if jobs and reserve_fallback is not None else jobs
        unattempted = [job for job in jobs if job not in selected]
        batches.extend(self._search_batches(selected, limit_per_target))
        unresolved = self._unresolved_queries(queries, batches)
        fused = fuse_results({"batches": batches, "targets": list(dict.fromkeys(t for t, _ in queries)),
                              "limit_per_target": limit_per_target})
        return {**fused, "batches": batches,
                "routing": {"mode": "parallel_then_fallback" if fallbacks else "parallel",
                            "primary_providers": names, "fallback_providers": fallbacks,
                            "fallback_triggered": bool(pending and fallbacks), "skipped_providers": skipped,
                            "strategy": strategy,
                            "hedge": {"grace_seconds": grace, "deadline_seconds": deadline},
                            "abandoned_providers": abandoned, "not_attempted_providers": not_attempted},
                "unresolved_queries": [{"target": target, "query": query} for target, query in unresolved],
                "remaining_attempts": [{"provider": name, "target": target, "query": query, "reason": "budget"}
                                       for name, target, query in unattempted if (target, query) in unresolved],
                "usage": {key: sum(batch["usage"][key] for batch in batches) for key in self.USAGE_FIELDS},
                "retry_policy": "Try configured fallback providers only for queries with no usable URL from the primary group. Each provider/target/query is attempted once; failures remain visible and cooldown may skip calls. search.strategy selects how the primary group runs: hedged (default) starts all providers together and abandons one still running after every query is resolved plus the grace window, or past the total deadline; staggered starts each next provider only while queries remain unresolved; sequential consults providers in order for unresolved queries only; wait_all awaits every provider. Abandoned requests may still consume provider quota.",
                "freshness": "retrieved_at is retrieval time; origin freshness is not established",
                "evidence_note": "Provider agreement is not independent fact verification; read source pages."}

    # A probe answers one question only: does this page still exist? Everything
    # else, including a successful HEAD, stays unknown, because a probe is not a
    # fetch and must never be reported as one. Only URLs that produced no body
    # are probed, and only 404/410 count as gone.
    DEAD_STATUSES = (404, 410)
    HEAD_REFUSALS = (403, 405, 501)
    PROBE_TIMEOUT = 10

    @classmethod
    def _probe_opener(cls):
        """The one place probe requests go through, so tests can replace them."""
        import urllib.request
        return urllib.request.urlopen

    @classmethod
    def _liveness(cls, url, timeout=None):
        import urllib.error
        import urllib.request
        timeout = cls.PROBE_TIMEOUT if timeout is None else timeout
        opener = cls._probe_opener()
        for method in ("HEAD", "GET"):
            try:
                with opener(urllib.request.Request(url, method=method), timeout=timeout) as response:
                    response.read(0)
            except urllib.error.HTTPError as error:
                if error.code in cls.DEAD_STATUSES:
                    return "dead"
                if method == "HEAD" and error.code in cls.HEAD_REFUSALS:
                    continue
            except Exception:
                pass
            return "unknown"
        return "unknown"

    @classmethod
    def _with_liveness(cls, fetched):
        """Probe the URLs that produced no body; mark the gone ones as dead.

        Called once, after every attempt has settled, so a probe can never sit
        inside a provider attempt: that would add real I/O to a path tests run
        offline and would re-time the attempts the waterfall races.
        """
        dead = []
        for row in fetched.get("per_url") or []:
            if row.get("status") == "ok":
                row.setdefault("liveness", "not_probed")
                continue
            row["liveness"] = cls._liveness(row["url"])
            if row["liveness"] == "dead":
                dead.append(row["url"])
        fetched["dead_urls"] = dead
        return fetched

    @staticmethod
    def _fetch_coverage(result, urls, reference=None):
        # Share the archive's conservative URL/body association rules even when
        # archival is disabled; a redirected or unidentified body is unverified.
        from archive import SourceArchive, content_state, published_at
        by_url, rows = {}, SourceArchive._extract(result, urls)
        for row in rows:
            try:
                key = SourceArchive._key(row["url"])
            except (ValueError, TypeError, KeyError):
                continue
            by_url.setdefault(key, []).append(row)
        empty_status = SourceArchive._empty_status(rows, result)
        coverage = []
        for url in urls:
            row, body, extraction, kind = SourceArchive._select(by_url.get(SourceArchive._key(url)), empty_status)
            title = (row or {}).get("title")
            provider_published = ((row or {}).get("publishedDate") or (row or {}).get("published_at")
                                  or (row or {}).get("publishedTime"))
            published = published_at(body, provider_published, reference=reference)
            status = "ok" if body is not None and kind != "provider_excerpts" else (
                "error" if extraction == "provider_error" else "unverified")
            coverage.append({"url": url, "status": status, "extraction_status": extraction,
                             "content_kind": kind, "content_state": content_state(title, body, extraction),
                             "characters": len(body) if body is not None else 0,
                             "published_at": published[0], "published_at_source": published[1],
                             "published_at_confidence": published[2],
                             "complete_page_verified": False})
        successful = sum(row["status"] == "ok" for row in coverage)
        status = "ok" if successful == len(urls) else ("partial" if successful else
                 ("error" if all(row["status"] == "error" for row in coverage) else "unverified"))
        return {"status": status, "per_url": coverage, "successful_url_count": successful}

    @classmethod
    def _fetch_waterfall(cls, urls, providers, fetch_one, reserve_fallback=None,
                         strategy="sequential", grace=None, deadline=None):
        """Try the preferred provider, then the selected alternatives.

        sequential waits for each provider before trying the next; staggered
        hands unresolved URLs to the next provider once the current one stalls
        past the grace window; hedged starts every provider at once. First good
        extraction wins and earlier providers break quality ties; providers
        still running when every URL is resolved, or when the deadline passes,
        are abandoned and disclosed. Staggered without a grace bound behaves
        like sequential, and the deadline only bounds staggered and hedged.
        """
        if strategy not in ("sequential", "staggered", "hedged"):
            raise ValueError("Unknown fetch strategy: %s" % strategy)
        if strategy == "staggered" and grace is None:
            strategy = "sequential"
        attempts, coverage, ranks = [], {}, {}

        def quality(row):
            return (row["status"] == "ok", row.get("characters", 0) > 0,
                    row["extraction_status"] not in ("request_failed", "unrecognized_or_not_returned",
                                                     "no_content_returned", "content_present_unparsed"))

        def run(name, pending):
            try:
                fetched = fetch_one(name, pending)
            except (RuntimeError, OSError, ValueError) as error:
                fetched = {"status": "error", **cls._failure(error), "usage": cls._empty_usage()}
            fetched = {**fetched, "provider": name, "urls": pending}
            if "result" in fetched:
                fetched.update(cls._fetch_coverage(fetched["result"], pending, fetched.get("retrieved_at")))
            else:
                fetched["per_url"] = [{"url": url, "status": "unverified", "content_state": "unavailable",
                                       "extraction_status": "request_failed", "characters": 0}
                                      for url in pending]
            return fetched

        def merge(fetched):
            rank = providers.index(fetched["provider"])
            for row in fetched["per_url"]:
                current = coverage.get(row["url"])
                # Provider order breaks ties; a later failure never erases
                # usable text, and successful primary URLs leave the queue.
                if current is None or (quality(row), -rank) > (quality(current), -ranks[row["url"]]):
                    coverage[row["url"]] = {**row, "provider": fetched["provider"]}
                    ranks[row["url"]] = rank

        def unresolved():
            return [url for url in urls if coverage.get(url, {}).get("status") != "ok"]

        def assemble(abandoned=()):
            pending = unresolved()
            successful = len(urls) - len(pending)
            return {"mode": "waterfall", "urls": urls, "providers": providers, "attempts": attempts,
                    "status": "ok" if not pending else "partial" if successful else "error",
                    "per_url": [coverage.get(url, {"url": url, "status": "unverified",
                                                   "extraction_status": "request_failed", "characters": 0})
                                for url in urls],
                    "successful_url_count": successful, "unresolved_urls": pending,
                    "abandoned_providers": sorted(abandoned),
                    "remaining_providers": [name for name in providers if name not in {a["provider"] for a in attempts}]
                                           if pending else [],
                    "usage": {key: sum(a.get("usage", {}).get(key, 0) for a in attempts) for key in cls.USAGE_FIELDS}}

        if strategy == "sequential":
            for stage, names in enumerate((providers[:1], providers[1:])):
                pending = [url for url in urls if coverage.get(url, {}).get("status") != "ok"]
                if not pending or not names:
                    break
                if stage and reserve_fallback is not None:
                    names = reserve_fallback(names, pending)
                if not names:
                    break
                if len(names) == 1:
                    batch = [run(names[0], pending)]
                else:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as pool:
                        batch = list(pool.map(lambda name: run(name, pending), names))
                attempts.extend(batch)
                for fetched in batch:
                    merge(fetched)
            return assemble()

        deadline_at = None if deadline is None else time.monotonic() + deadline
        if strategy == "hedged":
            selected = list(providers[:1])
            if len(providers) > 1:
                rest = (reserve_fallback(providers[1:], list(urls)) if reserve_fallback is not None
                        else list(providers[1:]))
                selected += list(rest)
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(selected))
            try:
                futures = {pool.submit(run, name, list(urls)): name for name in selected}
                while futures:
                    remaining = None if deadline_at is None else deadline_at - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        break
                    done, _ = concurrent.futures.wait(list(futures), timeout=remaining,
                                                      return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        futures.pop(future)
                        fetched = future.result()
                        attempts.append(fetched)
                        merge(fetched)
                    if not futures or not unresolved():
                        break
                abandoned = list(futures.values())
            except BaseException:
                # Surface a worker failure only after every attempt settled.
                pool.shutdown(wait=True)
                raise
            # Abandoned requests keep running in the background; their usage
            # and results are not counted in this response.
            pool.shutdown(wait=not abandoned)
            return assemble(abandoned)

        # staggered: dispatch the primary, then overlap the next provider when
        # the current one stalls past the grace window, or hand every remaining
        # provider the unresolved URLs at once when one completes early.
        queue, futures, last_dispatch = list(providers), {}, None

        def start(names, pending):
            nonlocal last_dispatch
            for name in names:
                futures[pool.submit(run, name, pending)] = name
            if names:
                last_dispatch = time.monotonic()

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(providers))
        try:
            start([queue.pop(0)], unresolved())
            while futures:
                fire_at = last_dispatch + grace if queue else None
                if deadline_at is not None:
                    fire_at = deadline_at if fire_at is None else min(fire_at, deadline_at)
                timeout = None if fire_at is None else max(0.0, fire_at - time.monotonic())
                done, _ = concurrent.futures.wait(list(futures), timeout=timeout,
                                                  return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    futures.pop(future)
                    fetched = future.result()
                    attempts.append(fetched)
                    merge(fetched)
                if not unresolved():
                    break
                if deadline_at is not None and time.monotonic() >= deadline_at:
                    break
                if done:
                    # One provider finished with work left: reserve and hand the
                    # pending URLs to every remaining provider at once, exactly
                    # like the sequential fallback stage.
                    pending = unresolved()
                    names = queue[:]
                    if names and reserve_fallback is not None:
                        names = list(reserve_fallback(names, pending))
                    queue[:] = []
                    start(names, pending)
                elif queue and last_dispatch is not None and time.monotonic() >= last_dispatch + grace:
                    pending = unresolved()
                    names = [queue.pop(0)]
                    if reserve_fallback is not None:
                        names = list(reserve_fallback(names, pending))
                    start(names, pending)
            abandoned = list(futures.values())
        except BaseException:
            # Surface a worker failure only after every attempt settled.
            pool.shutdown(wait=True)
            raise
        # Abandoned requests keep running in the background; their usage and
        # results are not counted in this response.
        pool.shutdown(wait=not abandoned)
        return assemble(abandoned)

    def fetch(self, urls, provider=None, archive=None, max_characters=None, probe=True):
        preferences = self.settings.load()
        automatic = provider is None
        provider = preferences["fetch"]["provider"] if provider is None else provider
        archive = preferences["archive"]["enabled"] if archive is None else archive
        max_characters = preferences["fetch"]["max_characters"] if max_characters is None else max_characters
        if type(archive) is not bool:
            raise ValueError("archive must be a boolean")
        if type(max_characters) is not int or not 100 <= max_characters <= 100000:
            raise ValueError("max_characters must be between 100 and 100000")
        self._selected([provider])
        if not isinstance(urls, list) or not 1 <= len(urls) <= 16:
            raise ValueError("urls must contain 1 to 16 HTTP(S) URLs")
        for url in urls:
            if not isinstance(url, str):
                raise ValueError("Every URL must be a string")
            if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url) or "\\" in url:
                raise ValueError("URLs must not contain whitespace, control characters or backslashes")
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError("Every URL must be HTTP(S) without embedded credentials")
        urls = list(dict.fromkeys(urls))
        if automatic:
            names = self._selected(Settings.fetch_providers(preferences))
            fetched = self._fetch_waterfall(urls, names, lambda name, pending:
                self.fetch(pending, provider=name, archive=archive, max_characters=max_characters, probe=False),
                strategy=preferences["fetch"]["strategy"], grace=preferences["fetch"]["grace_seconds"],
                deadline=preferences["fetch"]["deadline_seconds"])
            if len(fetched["attempts"]) == 1 and not fetched["abandoned_providers"]:
                return self._with_liveness(fetched["attempts"][0])
            # Keep the waterfall shape whenever a provider was abandoned so the
            # disclosure and per-URL provider attribution stay visible.
            return self._with_liveness(fetched)
        from archive import SourceArchive
        store = SourceArchive(preferences["archive"]["directory"]) if archive else None
        outcome = self._execute(provider, "fetch", urls=urls, max_characters=max_characters)
        arguments = outcome["request_arguments"]
        fetched = {"provider": provider, "urls": urls, **outcome,
                   "requested_max_characters": max_characters,
                   "character_limit_applied": any(key in arguments for key in ("maxCharacters", "max_chars")),
                   "retrieved_at": datetime.now(timezone.utc).isoformat(),
                   "freshness": "Origin freshness is not established; inspect per-URL provider statuses."}
        fetched["archive"] = {"status": "disabled"}
        if outcome["status"] == "error":
            fetched["per_url"] = [{"url": url, "status": "unverified", "content_state": "unavailable",
                                   "extraction_status": "request_failed"} for url in urls]
            fetched["successful_url_count"] = 0
            if store is not None:
                fetched["archive"] = {"status": "not_saved", "reason": "No provider response was obtained"}
            return fetched
        fetched.update(self._fetch_coverage(outcome["result"], urls, fetched.get("retrieved_at")))
        if probe:
            fetched = self._with_liveness(fetched)
        rows = fetched["per_url"]
        if any(row.get("status") == "ok" and row.get("extraction_status") not in
               ("request_failed", "unrecognized_or_not_returned",
                "no_content_returned", "content_present_unparsed") for row in rows):
            self._note_usable_result(provider)
        elif rows and all(row.get("extraction_status") == "no_content_returned" for row in rows):
            # Only genuinely empty responses feed the breaker. Content this
            # parser could not turn into records is our problem, not the
            # provider's; cooling it would skip a healthy provider and hide
            # the parse gap behind a fallback.
            self._note_empty_attempt(provider, "Provider repeatedly returned no usable page text; skipped briefly")
        if store is not None:
            try:
                fetched["archive"] = store.save(fetched)
            except (OSError, ValueError) as error:
                # The response is still usable; never hide a fetch or repeat a paid call
                # just because local persistence failed.
                fetched["archive"] = {"status": "error", "error": str(error)}
        return fetched
