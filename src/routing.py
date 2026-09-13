"""Choose research entrypoints from observed host capabilities; never launch work."""

import os

from service_http import ResearchHttp
from settings import Settings
from web_search import SearchProviders


class ResearchRouting:
    HOSTS = ("codex", "claude_code", "pi", "dsh", "unknown")
    METHODS = {
        "comparative_analysis": "skills/bookmark-research/references/research-methods.md",
        "fact_check": "skills/bookmark-research/references/research-methods.md",
        "benchmark_review": "skills/bookmark-research/references/research-methods.md",
        "wiki_synthesis": "skills/bookmark-research/references/wiki-and-evaluation.md",
    }

    def __init__(self, settings=None):
        self.settings = settings if settings is not None else Settings()

    @staticmethod
    def _names(values, label):
        if values is None:
            return []
        if (not isinstance(values, list) or len(values) > 1000
                or any(not isinstance(x, str) or not x.strip() or len(x) > 300 for x in values)):
            raise ValueError(label + " must be a list of names observed in the current host")
        return list(dict.fromkeys(values))

    @staticmethod
    def _has(tools, *names):
        return any(tool == name or tool.endswith(("__" + name, "." + name, ":" + name))
                   for tool in tools for name in names)

    def route(self, depth=None, host="unknown", task_shape="investigation", observed_tools=None,
              available_commands=None, installed_extensions=None, provider=None, failed_routes=None):
        settings = self.settings.load()
        depth = settings["research"]["depth"] if depth is None else depth
        if depth not in ("auto", "quick", "agentic", "deep") or host not in self.HOSTS:
            raise ValueError("Unsupported research depth or host")
        if task_shape not in ("lookup", "investigation", "batch_research"):
            raise ValueError("task_shape must be lookup, investigation or batch_research")
        if provider not in (None, "openai", "parallel"):
            raise ValueError("Professional provider must be openai or parallel")
        tools = self._names(observed_tools, "observed_tools")
        commands = self._names(available_commands, "available_commands")
        extensions = self._names(installed_extensions, "installed_extensions")
        failed = self._names(failed_routes, "failed_routes")
        retrieval = SearchProviders(settings=self.settings)
        selected_depth = ({"lookup": "quick", "investigation": "agentic", "batch_research": "deep"}[task_shape]
                          if depth == "auto" else depth)
        if provider is not None:
            selected_depth = "deep"
        ordinary_agentic = selected_depth == "agentic" and task_shape != "batch_research"
        candidates = []
        missing = []
        if selected_depth == "quick":
            candidates.append({"route": "direct_retrieval", "entrypoint": "fetch_web / search_web",
                               "available": True, "execution_owner": "host",
                               "reason": "Read known URLs directly; use search when sources must be discovered."})
        else:
            if host == "claude_code":
                packaged = "/bookmark-research:bookmark-research" in commands
                if packaged or self._has(tools, "Workflow", "workflow"):
                    candidates.append({"route": "host_workflow",
                        "entrypoint": "/bookmark-research:bookmark-research" if packaged else "Workflow",
                        "available": True, "execution_owner": "claude_code", "run_mode": "background",
                        "resume_scope": "same_session_with_possible_child_replay",
                        "recipe": "hosts/claude/runtime.js"})
                else:
                    missing.append("Claude workflow tool or packaged workflow command is not observed")
                if "/deep-research" in commands and selected_depth == "deep" and task_shape != "batch_research":
                    candidates.append({"route": "host_deep_research", "entrypoint": "/deep-research",
                        "available": True, "execution_owner": "claude_code", "run_mode": "background",
                        "invocation": "explicit_command_required",
                        "scope_note": "Builtin question research does not guarantee enumeration of a local package."})
            elif host == "dsh":
                if self._has(tools, "workflow"):
                    candidates.append({"route": "host_workflow", "entrypoint": "workflow",
                        "available": True, "execution_owner": "dsh", "run_mode": "blocking",
                        "resume_scope": "not_established", "recipe": "hosts/dsh/workflow-call.py",
                        "result_note": "Persist the canonical result; rendered text may be truncated."})
                else:
                    missing.append("The loaded DSH profile does not expose a workflow tool")
            elif host == "pi":
                if self._has(tools, "pi_subagent_workflow"):
                    candidates.append({"route": "host_workflow", "entrypoint": "pi_subagent_workflow",
                        "available": True, "execution_owner": "pi_subagents_extension", "run_mode": "detached",
                        "resume_scope": "registry_does_not_add_replay", "recipe": "hosts/pi/register-workflow.py"})
                else:
                    missing.append("Pi workflow extension tool is not observed; installed package names alone are insufficient")
            elif host == "codex":
                missing.append("An equivalent standalone scripted workflow runtime was not established by the researched Codex docs")
            if selected_depth == "deep" and provider is None:
                for name, info in retrieval.registry["providers"].items():
                    native_research = info.get("native_research", {})
                    required = native_research.get("required_tools", [])
                    if required and all(self._has(tools, tool) for tool in required):
                        workflow_tools = [next(tool for tool in tools if self._has([tool], required_tool))
                                          for required_tool in native_research["workflow_tools"]]
                        candidates.append({"route": "host_research_mcp", "provider": name,
                            "entrypoint": workflow_tools[0], "workflow_tools": workflow_tools,
                            "available": True, "execution_owner": name, "invocation_owner": "host", "run_mode": "provider_background",
                            "availability_basis": "observed_tools", "authentication_verified": False,
                            "resume_note": "Keep the returned run ID. Resume or observe that run until terminal; a timeout is not a new submission."})
            native = {"codex": ("spawn_agent",), "claude_code": ("Agent", "Task", "subagent"),
                      "pi": ("subagent",), "dsh": ("subagent", "agent"), "unknown": ()}[host]
            native_tools = [tool for tool in tools if self._has([tool], *native)]
            if native_tools:
                candidates.append({"route": "host_subagents", "entrypoint": native_tools[0],
                    "available": True, "execution_owner": host, "run_mode": "host_defined",
                    "recipe": "hosts/codex/delegate.md" if host == "codex" else "skills/bookmark-research/references/host-workflows.md"})
            services = settings["professional_research"]
            if selected_depth == "deep" or provider is not None:
                for name in ([provider] if provider else ["openai", "parallel"]):
                    key = ResearchHttp.PROVIDERS[name]["key_env"]
                    credential = bool(os.environ.get(key))
                    candidates.append({"route": "professional_service", "provider": name,
                        "entrypoint": "research_service_start", "execution_owner": name, "run_mode": "provider_background",
                        "available": services["enabled"] and credential, "authentication_verified": False,
                        "missing": ([] if services["enabled"] else ["professional_research.enabled"])
                                   + ([] if credential else [key])})
            candidates.append({"route": "host_iterative_research",
                "entrypoint": "search_web / fetch_web" if ordinary_agentic else "research_start / research_*",
                "available": True, "execution_owner": "host", "run_mode": "host_defined",
                "reason": "The current host model plans the inquiry, reads evidence, evaluates it and follows gaps; retrieval services support this loop."})
        for candidate in candidates:
            candidate["route_id"] = candidate["route"] + (":" + candidate["provider"] if "provider" in candidate else "")
            if candidate["route_id"] in failed:
                candidate["available"] = False
                candidate["excluded_reason"] = "caller_reported_confirmed_failure"
        if provider is not None:
            choices = [c for c in candidates if c["route"] == "professional_service" and c.get("provider") == provider]
            selected = next((c for c in choices if c["available"]), None)
        else:
            choices = candidates[:]
            host_priority = (["host_workflow", "host_subagents", "host_iterative_research"]
                             if task_shape == "batch_research" and settings["research"]["prefer_host_workflows"] else
                             ["host_subagents", "host_iterative_research", "host_workflow"])
            if ordinary_agentic:
                host_priority.remove("host_iterative_research")
                host_priority.insert(0, "host_iterative_research")
            configured = settings["professional_research"]["provider"]
            # Host reasoning is the baseline. A saved API preference orders
            # optional services; only an explicit provider overrides host work.
            choices.sort(key=lambda c: host_priority.index(c["route"]) if c["route"] in host_priority else
                len(host_priority) if c["route"] == "professional_service" and c.get("provider") == configured else
                len(host_priority) + 1)
            selected = next((c for c in choices if c["available"]), None)
        if selected is None:
            next_action = ({"tool": "research_services", "arguments": {"provider": provider},
                            "reason": "Inspect the explicitly selected service's configuration or confirmed failure; it was not substituted."}
                           if provider is not None else {"tool": "research_status",
                            "reason": "No untried applicable route remains. Inspect the existing evidence and report the unresolved gaps."})
            workflow = []
        elif selected_depth == "quick":
            next_action = {"tools": ["fetch_web", "search_web"],
                           "reason": "Read known URLs; search only when a source must be discovered, then read it."}
            workflow = ["fetch_web", "answer_with_sources"]
        elif ordinary_agentic and selected["route"] == "host_iterative_research":
            next_action = {"tools": ["search_web", "fetch_web"],
                           "reason": "The current host model first plans from the question and available context. Read known sources or search for missing evidence, assess the pages, then target unresolved questions. Use persistent research records when the task needs a resumable report."}
            workflow = ["search_web", "fetch_web", "answer_with_sources"]
        else:
            next_action = {"tool": "research_start",
                           "reason": "The current host model first defines the questions, evidence gaps and work assignments. Freeze the full scope for new research; reuse existing research_status and evidence before delegating or retrieving more."}
            workflow = ["research_start", "research_inventory"]
            if selected["route"] == "professional_service":
                workflow += ["research_service_prepare", "research_service_start", "research_service_status",
                             "research_service_result", "research_service_import", "research_fetch"]
            elif selected["route"] == "host_research_mcp":
                workflow += selected["workflow_tools"] + ["research_record", "research_import_evidence", "research_fetch"]
            else:
                workflow += [selected["entrypoint"]] if selected["route"] != "host_iterative_research" else []
                workflow += ["research_search", "research_fetch"]
            workflow += ["research_source", "research_record", "research_coverage", "research_finish"]
        process = {"owner": "current_host_model",
                   "steps": (["read_or_search", "answer_with_sources"] if selected_depth == "quick" else
                             ["plan", "search_or_read", "assess_evidence", "follow_evidence_gaps"] +
                             (["independent_review", "coverage_check", "synthesize_report"] if selected_depth == "deep" else
                              ["synthesize_answer"])),
                   "collaboration": "Delegate independent questions, sources or verification only through currently available and permitted host capabilities. The parent plans and reviews the result; no subagent is required for the basic loop.",
                   "external_research": "Optional scoped support after host assessment, or an explicit user-selected service. Tool presence and saved API credentials do not replace the host's first pass."}
        return {"depth": selected_depth, "host": host, "task_shape": task_shape, "selected": selected,
                "candidates": candidates, "missing_or_unconfirmed": missing,
                "next_action": next_action, "workflow": workflow, "research_process": process,
                "fallback": {"execution_owner": "host", "failed_routes": failed,
                             "remaining_routes": [c["route_id"] for c in choices if c["available"] and c is not selected],
                             "on_confirmed_failure": "Call research_route again with cumulative failed_routes and current host observations; execute the next route in the same research session.",
                             "hold_on": ["pending", "queued", "in_progress", "unknown_outcome", "cancelled"],
                             "explicit_provider_is_exclusive": provider is not None},
                "retrieval": {"search": {"providers": settings["search"]["providers"],
                                         "fallback_providers": settings["search"]["fallback_providers"],
                                         "mode": "parallel_then_fallback" if settings["search"]["fallback_providers"] else "parallel"},
                              "fetch": {"providers": Settings.fetch_providers(settings), "mode": "primary_then_parallel_fallback"}},
                "observations": {"tools": tools, "commands": commands, "extensions": extensions,
                                 "basis": "caller_reported_current_host", "runtime_tested": False},
                "methods": [{"name": name, "reference": self.METHODS[name]} for name in settings["research"]["methods"]],
                "source_scope": "Keep the frozen research inventory complete across groups and rounds; finish checks coverage.",
                "execution_started": False, "configuration_changed": False,
                "provider_fallback": "An explicitly selected unavailable service is reported unavailable; never silently substituted."}
