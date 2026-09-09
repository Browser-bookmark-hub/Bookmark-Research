"""Query selected existing search MCPs and retain provider/target provenance."""

import concurrent.futures
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from remote_mcp import McpHttpClient
from search_results import fuse_results
from settings import Settings


class SearchProviders:
    """Aggregate existing provider tools; no model, crawler, or OAuth implementation."""

    def __init__(self, timeout=None, settings=None):
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 60):
            raise ValueError("timeout must be between 1 and 60 seconds")
        self.timeout = timeout
        self.settings = settings if settings is not None else Settings()
        self.registry = json.loads(
            (Path(__file__).resolve().parent.parent / "config/providers.json").read_text(encoding="utf-8"))

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
        return {"probe_performed": False, "default_providers": self.settings.load()["search"]["providers"],
                "providers": [{"provider": name, **self.registry["providers"][name]} for name in names],
                "note": "Configuration is not proof of connection, authentication, or service availability."}

    def _client(self, provider):
        info = self.registry["providers"][provider]
        if not info["direct_client"]:
            raise ValueError("Tavily uses host-managed OAuth; call its native MCP and use merge-results")
        headers = {}
        for header, variable in info.get("optional_header_env", {}).items():
            if os.environ.get(variable):
                headers[header] = os.environ[variable]
        variable = info.get("optional_bearer_env")
        if variable and os.environ.get(variable):
            headers["Authorization"] = "Bearer " + os.environ[variable]
        timeout = self.timeout if self.timeout is not None else self.settings.load()["timeout_seconds"]
        return McpHttpClient(info["url"], headers=headers, timeout=timeout)

    def _probe_one(self, provider):
        try:
            tools = self._client(provider).list_tools()
            return {"provider": provider, "status": "ok", "tools": tools}
        except (RuntimeError, ValueError, OSError) as error:
            return {"provider": provider, "status": "error", "error": str(error)}

    def probe(self, providers=None):
        names = self._selected(providers)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(names))) as pool:
            results = list(pool.map(self._probe_one, names))
        return {"probe_performed": True, "providers": results,
                "successful_provider_count": sum(row["status"] == "ok" for row in results)}

    def _tool(self, provider, purpose, tools):
        names = self.registry["providers"][provider][purpose + "_tools"]
        for tool in tools:
            if isinstance(tool, dict) and tool.get("name") in names:
                return tool
        raise RuntimeError("Provider does not expose its expected %s tool" % purpose)

    @staticmethod
    def _arguments(tool, purpose, query=None, urls=None, limit=5, max_characters=12000):
        schema = tool.get("inputSchema", {})
        if not isinstance(schema, dict) or not isinstance(schema.get("properties", {}), dict):
            raise RuntimeError("Provider tool returned an invalid input schema")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(field, str) for field in required):
            raise RuntimeError("Provider tool returned an invalid required-fields schema")
        if purpose == "search":
            candidates = {"query": query, "objective": query, "search_queries": [query],
                          "numResults": limit, "num_results": limit, "max_results": limit}
        else:
            candidates = {"urls": urls, "url": urls[0] if len(urls) == 1 else None,
                          "maxCharacters": max_characters, "max_chars": max_characters}
        arguments = {key: value for key, value in candidates.items()
                     if key in properties and value is not None}
        missing = set(required) - set(arguments)
        if missing:
            raise RuntimeError("Provider tool schema changed; unsupported required fields: " +
                               ", ".join(sorted(missing)))
        if purpose == "search" and not any(k in arguments for k in ("query", "objective", "search_queries")):
            raise RuntimeError("Provider search tool has no supported query field")
        if purpose == "fetch" and not any(k in arguments for k in ("urls", "url")):
            raise RuntimeError("Provider fetch tool has no supported URL field")
        return arguments

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
    def _normalize(result):
        rows = SearchProviders._records(result.get("structuredContent"))
        content = result.get("content", [])
        if not isinstance(content, list):
            raise RuntimeError("Provider tool returned an invalid content array")
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
            raise RuntimeError("Unrecognized provider result format; use native MCP output with merge-results")
        normalized = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("url"), str):
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
            raise RuntimeError("Provider returned no parseable search results")
        return normalized

    def _search_one(self, work):
        provider, target, query, limit = work
        base = {"provider": provider, "target": target, "query": query,
                "retrieved_at": datetime.now(timezone.utc).isoformat()}
        try:
            client = self._client(provider)
            tool = self._tool(provider, "search", client.list_tools())
            arguments = self._arguments(tool, "search", query=query, limit=limit)
            result = client.call_tool(tool["name"], arguments)
            return {**base, "status": "ok", "results": self._normalize(result)[:limit],
                    "tool": tool["name"]}
        except (RuntimeError, ValueError, OSError) as error:
            return {**base, "status": "error", "results": [], "error": str(error)}

    def search(self, targets, providers=None, limit_per_target=None):
        if limit_per_target is None:
            limit_per_target = self.settings.load()["search"]["limit_per_target"]
        if not isinstance(targets, list) or not 1 <= len(targets) <= 12:
            raise ValueError("targets must contain 1 to 12 target/query objects")
        if type(limit_per_target) is not int or not 1 <= limit_per_target <= 20:
            raise ValueError("limit_per_target must be between 1 and 20")
        queries = []
        for row in targets:
            if not isinstance(row, dict) or set(row) - {"target", "query"}:
                raise ValueError("Each target must contain only target and query")
            if not all(isinstance(row.get(key), str) and row[key].strip() for key in ("target", "query")):
                raise ValueError("Each target needs nonempty target and query strings")
            if len(row["query"]) > 2000 or len(row["target"]) > 200:
                raise ValueError("Target or query is too long")
            queries.append((row["target"].strip(), row["query"].strip()))
        queries = list(dict.fromkeys(queries))
        names = self._selected(providers)
        work = [(name, target, query, limit_per_target) for name in names for target, query in queries]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(work))) as pool:
            batches = list(pool.map(self._search_one, work))
        fused = fuse_results({"batches": batches, "targets": list(dict.fromkeys(t for t, _ in queries)),
                              "limit_per_target": limit_per_target})
        return {**fused, "batches": batches,
                "freshness": "retrieved_at is retrieval time; origin freshness is not established",
                "evidence_note": "Provider agreement is not independent fact verification; read source pages."}

    def fetch(self, urls, provider=None, archive=None, max_characters=None):
        preferences = self.settings.load()
        provider = preferences["fetch"]["provider"] if provider is None else provider
        archive = preferences["archive"]["enabled"] if archive is None else archive
        max_characters = preferences["fetch"]["max_characters"] if max_characters is None else max_characters
        if type(archive) is not bool:
            raise ValueError("archive must be a boolean")
        if type(max_characters) is not int or not 100 <= max_characters <= 100000:
            raise ValueError("max_characters must be between 100 and 100000")
        self._selected([provider])
        if not isinstance(urls, list) or not 1 <= len(urls) <= 8:
            raise ValueError("urls must contain 1 to 8 HTTP(S) URLs")
        for url in urls:
            if not isinstance(url, str):
                raise ValueError("Every URL must be a string")
            if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url) or "\\" in url:
                raise ValueError("URLs must not contain whitespace, control characters or backslashes")
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError("Every URL must be HTTP(S) without embedded credentials")
        from archive import SourceArchive
        store = SourceArchive(preferences["archive"]["directory"]) if archive else None
        client = self._client(provider)
        tool = self._tool(provider, "fetch", client.list_tools())
        arguments = self._arguments(tool, "fetch", urls=urls, max_characters=max_characters)
        result = client.call_tool(tool["name"], arguments)
        fetched = {"provider": provider, "urls": urls, "tool": tool["name"], "result": result,
                   "request_arguments": arguments, "requested_max_characters": max_characters,
                   "character_limit_applied": any(key in arguments for key in ("maxCharacters", "max_chars")),
                   "retrieved_at": datetime.now(timezone.utc).isoformat(),
                   "freshness": "Origin freshness is not established; inspect per-URL provider statuses."}
        fetched["archive"] = {"status": "disabled"}
        if store is not None:
            try:
                fetched["archive"] = store.save(fetched)
            except (OSError, ValueError) as error:
                # The response is still usable; never hide a fetch or repeat a paid call
                # just because local persistence failed.
                fetched["archive"] = {"status": "error", "error": str(error)}
        return fetched
