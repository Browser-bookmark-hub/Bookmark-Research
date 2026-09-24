"""Bounded capability checks, honest auth status, and private expiring cache."""

import concurrent.futures
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time

from credentials import Credentials
from remote_mcp import McpError, McpHttpClient
from service_http import ResearchHttp, ServiceError
from settings import Settings
from web_search import SearchProviders


class Readiness:
    VERSION = 1

    def __init__(self, settings=None, web=None, transport=None, cache_path=None):
        self.settings = settings if settings is not None else Settings()
        self.credentials = Credentials(self.settings)
        timeout = self.settings.load()["readiness"]["timeout_seconds"]
        self.web = web if web is not None else SearchProviders(settings=self.settings, timeout=timeout)
        self.transport = transport if transport is not None else ResearchHttp(timeout, self.credentials)
        identity = hashlib.sha256(str(self.settings.path).encode()).hexdigest()[:16]
        self.cache_path = Path(cache_path or Settings.data_directory() / "readiness" / (identity + ".json"))

    def _cache(self):
        if self.cache_path.is_symlink():
            raise ValueError("Readiness cache must not be a symlink")
        try:
            if self.cache_path.stat().st_size > 256000:
                raise ValueError("Readiness cache exceeds size limit")
            cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if (isinstance(cache, dict) and cache.get("version") == self.VERSION
                    and isinstance(cache.get("salt"), str) and isinstance(cache.get("checks"), dict)):
                return cache
        except (FileNotFoundError, ValueError, UnicodeError):
            pass
        return {"version": self.VERSION, "salt": os.urandom(32).hex(), "checks": {}}

    def _save(self, cache):
        if self.cache_path.is_symlink():
            raise ValueError("Readiness cache must not be a symlink")
        path = Settings.external_path(str(self.cache_path), "Readiness cache")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                             prefix=".readiness-", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(cache, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _signature(self, row, salt):
        # Only a salted signature is persisted; no keys, headers, or signatures
        # are included in CLI/MCP results. Rotation invalidates cached checks.
        content = {"row": row, "settings": self.settings.load(),
                   "credential": self.credentials.get(row["credential_env"]),
                   "registry": self.web.registry, "version": self.VERSION}
        return hmac.new(salt.encode(), json.dumps(content, sort_keys=True).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _error(error):
        if isinstance(error, (ServiceError, McpError)):
            detail = error.details()
            # Only typed error metadata is needed for remediation. Never retain
            # response bodies or arbitrary exception text in the cache.
            return {key: detail[key] for key in ("error_kind", "http_status", "retry_after_seconds") if key in detail}
        return {"error_kind": "check_failed"}

    def _retrieval_rows(self, providers):
        preferences = self.settings.load()
        names = providers if providers is not None else list(dict.fromkeys(
            preferences["search"]["providers"] + preferences["search"]["fallback_providers"] +
            Settings.fetch_providers(preferences)))
        described = self.web.describe(names)["providers"]
        return [{"id": "retrieval:" + row["provider"], "kind": "retrieval", "provider": row["provider"],
                 "credential_env": row["provider"].upper() + "_API_KEY",
                 "credential_configured": row["authentication_state"]["credential_configured"],
                 "authentication_mode": row["authentication_state"]["mode"],
                 "authentication_verified": False, "execution_verified": False,
                 "status": "unchecked", "docs": row["docs"], "operations": row["operations"],
                 "installation": "included_adapter", "network_checked": False,
                 "next_step": "Run readiness --refresh for connection checks; --test-retrieval also uses retrieval quota."}
                for row in described]

    def _service_rows(self, service):
        config = self.settings.load()["professional_research"]
        rows = []
        for name in ([service] if service else ["openai", "parallel"]):
            key = ResearchHttp.PROVIDERS[name]["key_env"]
            enabled = config["enabled"] and (config["provider"] in (None, name) or service == name)
            configured = bool(self.credentials.get(key))
            rows.append({"id": "service:" + name, "kind": "professional_research", "provider": name,
                         "credential_env": key, "credential_configured": configured,
                         "authentication_verified": False, "execution_verified": False,
                         "network_checked": False, "enabled": enabled,
                         "status": "unchecked" if configured and enabled else "disabled" if not enabled else "missing_credentials",
                         "next_step": "Run setup to enable this optional service and configure " + key + ".",
                         "docs": "https://developers.openai.com/api/docs/guides/deep-research" if name == "openai"
                         else "https://docs.parallel.ai/task-api/guides/execute-task-run"})
        return rows

    def _probe_retrieval(self, row, test_retrieval):
        name = row["provider"]
        if test_retrieval:
            operations = copy.deepcopy(row["operations"])
            for purpose in ("search", "fetch"):
                if operations[purpose]["missing"]:
                    operations[purpose]["status"] = "missing_credentials"
                    continue
                if purpose == "search":
                    result = self.web.search([{"target": "readiness", "query": "example.com Example Domain"}],
                                             providers=[name], limit_per_target=1)["batches"][0]
                    verified = result["status"] == "ok" and bool(result.get("results"))
                else:
                    result = self.web.fetch(["https://example.com/"], provider=name, archive=False, max_characters=1000)
                    verified = result["status"] == "ok" and result.get("successful_url_count", 0) > 0
                operations[purpose].update(status="verified" if verified else "failed",
                                           error_kind=result.get("error_kind"))
            verified = any(operation.get("status") == "verified" for operation in operations.values())
            return {"status": "retrieval_verified" if verified else "failed", "operations": operations,
                    "network_checked": True, "execution_verified": verified,
                    "authentication_verified": verified and row["credential_configured"],
                    "verification_scope": "Only the successful search/fetch operations in this check.",
                    "next_step": "Use verified operations; configure missing credentials or address failed operations before relying on them."}
        probe = self.web.probe([name])["providers"][0]
        if probe["status"] == "ok":
            return {"status": "catalog_reachable", "network_checked": True,
                    "capabilities": probe["capabilities"],
                    "next_step": "Search/fetch can be attempted. Catalog discovery does not verify retrieval authorization or quota."}
        if probe["status"] == "not_probed":
            return {"status": "http_unchecked", "network_checked": False,
                    "next_step": "Reader can be attempted anonymously; Search needs JINA_API_KEY. Use --test-retrieval for an actual check."}
        return {"status": "failed", "network_checked": True,
                "error_kind": probe.get("error_kind", "check_failed"),
                "next_step": "Check credentials and connectivity, then refresh; another configured provider may remain available."}

    def _probe_service(self, row):
        name = row["provider"]
        if name == "openai":
            model = self.settings.load()["professional_research"]["openai"]["model"]
            result = self.transport.request("openai", "GET", "/v1/models/" + model)
            if result.get("id") != model or result.get("object") != "model":
                raise ValueError("Unexpected model metadata")
            return {"status": "model_access_verified", "authentication_verified": True,
                    "network_checked": True, "verification_scope": "GET /v1/models/" + model,
                    "next_step": "Model metadata is accessible. Research execution and billing quota remain untested; prepare the intended run before starting."}
        endpoint = self.web.registry["providers"]["parallel"]["native_research"]["url"]
        client = McpHttpClient(endpoint, headers={"Authorization": "Bearer " + self.credentials.get("PARALLEL_API_KEY")},
                               timeout=self.settings.load()["readiness"]["timeout_seconds"])
        tools = client.list_tools()
        required = self.web.registry["providers"]["parallel"]["native_research"]["required_tools"]
        if not isinstance(tools, list) or not set(required) <= {tool.get("name") for tool in tools if isinstance(tool, dict)}:
            raise ValueError("Task MCP catalog is incomplete")
        return {"status": "task_mcp_access_verified", "network_checked": True,
                "task_mcp_authentication_verified": True, "authentication_verified": False,
                "verification_scope": "Authenticated Task MCP initialize/tools/list; Task API execution was not tested.",
                "next_step": "Task MCP accepted this API key. Task API permission and billing quota still need verification on the intended run."}

    def _probe(self, row, test_retrieval):
        try:
            update = self._probe_retrieval(row, test_retrieval) if row["kind"] == "retrieval" else self._probe_service(row)
            return {**row, **update}
        except (RuntimeError, ValueError, OSError) as error:
            return {**row, "status": "failed", "network_checked": True, **self._error(error),
                    "next_step": "Check the selected provider's credential, permissions and connectivity; refresh after fixing it."}

    def _host_integrations(self, host, observed_tools):
        from routing import ResearchRouting
        if host not in ResearchRouting.HOSTS:
            raise ValueError("Unsupported host")
        tools = ResearchRouting._names(observed_tools, "observed_tools")
        rows = []
        for name, info in self.web.registry["providers"].items():
            native = info.get("native_research")
            if not native:
                continue
            required = native.get("required_tools", [])
            present = (all(ResearchRouting._has(tools, tool) for tool in required) if required else
                       any(ResearchRouting._has(tools, tool) for tool in native["tools"]))
            alias = "bookmark-" + name + "-research"
            if host == "codex":
                setup = {"inspect_command": ["codex", "mcp", "list", "--json"],
                         "add_command": ["codex", "mcp", "add", alias, "--url", native["url"]],
                         "login_command": ["codex", "mcp", "login", alias],
                         "login_instruction": "Use the host's OAuth flow if this endpoint supports it, then inspect /mcp in a new session.",
                         "reference": "https://developers.openai.com/codex/mcp"}
            elif host == "claude_code":
                setup = {"inspect_command": ["claude", "mcp", "list"],
                         "add_command": ["claude", "mcp", "add", "--scope", "user", "--transport", "http", alias, native["url"]],
                         "login_instruction": "Open /mcp in Claude Code and authenticate this server if OAuth is supported. Choose the intended scope when adding it.",
                         "reference": "https://code.claude.com/docs/en/mcp"}
            elif host == "dsh":
                setup = {"mcp_config": {"serverName": alias, "transport": "streamable-http", "url": native["url"]},
                         "credential_env": name.upper() + "_API_KEY",
                         "credential_header": "x-api-key" if name == "exa" else "Authorization: Bearer",
                         "login_instruction": "Add this optional server to the selected DSH profile with an environment-backed authentication header. The documented DSH bridge supports headers; OAuth support is not established.",
                         "reference": "https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md"}
            else:
                setup = {"login_instruction": "Pi uses the bundled CLI for ordinary research. Native research MCPs need a separately chosen MCP extension and its authentication flow. The plugin does not assume one is installed."
                         if host == "pi" else "Select --host when running setup, or inspect the MCP settings in your actual host.",
                         "reference": "skills/bookmark-research/references/host-workflows.md"}
            rows.append({"provider": name, "optional": True, "endpoint": native["url"],
                         "status": "needs_host_session" if observed_tools is None else "observed" if present else "not_observed",
                         "authentication_verified": False, "docs": native.get("docs", info["docs"]),
                         "setup": setup,
                         "next_step": "Inspect the current host's MCP tools; add this optional endpoint and complete its host-managed login if needed. Tool presence alone does not verify authorization."})
        collaboration_tools = {"codex": ("spawn_agent",), "claude_code": ("Agent", "Task", "Workflow"),
                               "pi": ("subagent", "pi_subagent_workflow"), "dsh": ("subagent", "workflow"), "unknown": ()}
        collaboration = {"optional": True,
            "status": "needs_host_session" if observed_tools is None or host == "unknown" else
                      "observed" if ResearchRouting._has(tools, *collaboration_tools[host]) else "not_observed",
            "next_step": "Use the host's own search/read loop when collaboration is unavailable. Enable the host's supported subagent/workflow capability only when needed.",
            "reference": "skills/bookmark-research/references/host-workflows.md"}
        return {"host": host, "session_observed": observed_tools is not None,
                "collaboration": collaboration, "native_research_mcps": rows}

    def check(self, providers=None, service=None, refresh=False, offline=False, test_retrieval=False,
              host="unknown", observed_tools=None):
        if service not in (None, "openai", "parallel"):
            raise ValueError("Select openai or parallel")
        if any(type(value) is not bool for value in (refresh, offline, test_retrieval)):
            raise ValueError("Readiness flags must be boolean")
        if offline and (refresh or test_retrieval):
            raise ValueError("Offline checks cannot refresh or test retrieval")
        integrations = self._host_integrations(host, observed_tools)
        policy = self.settings.load()["readiness"]
        rows = self._retrieval_rows(providers) + self._service_rows(service)
        cache_error = None
        try:
            cache = self._cache()
        except (OSError, ValueError):
            cache = {"version": self.VERSION, "salt": os.urandom(32).hex(), "checks": {}}
            cache_error = "Readiness cache could not be read; current checks remain usable."
        now, pending, output = time.time(), [], []
        for row in rows:
            if row["status"] in ("disabled", "missing_credentials"):
                output.append(row)
                continue
            signature = self._signature(row, cache["salt"])
            previous = cache["checks"].get(row["id"], {})
            fresh = (isinstance(previous, dict) and previous.get("signature") == signature
                     and type(previous.get("expires_at")) in (int, float) and previous["expires_at"] > now
                     and isinstance(previous.get("result"), dict))
            if fresh and not refresh and not test_retrieval and (offline or policy["mode"] != "always"):
                output.append({**previous["result"], "cached": True, "network_checked_this_call": False})
            elif offline or (policy["mode"] == "manual" and not refresh and not test_retrieval):
                output.append({**row, "cached": False, "network_checked_this_call": False,
                               "next_step": "Run readiness --refresh when a network check is wanted."})
            else:
                pending.append((row, signature))
        if pending:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(pending)) as pool:
                results = list(pool.map(lambda work: self._probe(work[0], test_retrieval), pending))
            for (row, signature), result in zip(pending, results):
                ttl = min(policy["ttl_seconds"], 60) if result["status"] == "failed" else policy["ttl_seconds"]
                result.update(checked_at=now, expires_at=now + ttl, cached=False,
                              network_checked_this_call=result["network_checked"])
                cache["checks"][row["id"]] = {"signature": signature, "expires_at": now + ttl, "result": result}
                output.append(result)
            if not cache_error:
                try:
                    self._save(cache)
                except (OSError, ValueError):
                    cache_error = "Readiness checks completed but their cache could not be saved."
        order = {row["id"]: index for index, row in enumerate(rows)}
        output.sort(key=lambda row: order[row["id"]])
        return {"policy": policy, "research_preferences": self.settings.load()["research"],
                "checks": output, "host_integrations": integrations,
                "offline_ready": True, "network_checked": any(row.get("network_checked_this_call") for row in output),
                "research_jobs_started": 0, "cache_error": cache_error,
                "note": "Optional service failures do not block local queries or other providers. Cached status is evidence from its timestamp, not a guarantee. Host OAuth stays in the host; no login tokens are imported. MCP setup commands are guidance: inspect existing registrations and reuse their names before adding a server."}
