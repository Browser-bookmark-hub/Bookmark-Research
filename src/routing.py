"""Choose research entrypoints from observed host capabilities; never launch work."""

import os

from service_http import ResearchHttp
from settings import Settings


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
              available_commands=None, installed_extensions=None, provider=None):
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
        selected_depth = ({"lookup": "quick", "investigation": "agentic", "batch_research": "deep"}[task_shape]
                          if depth == "auto" else depth)
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
            native = {"codex": ("spawn_agent",), "claude_code": ("Agent", "Task", "subagent"),
                      "pi": ("subagent",), "dsh": ("subagent", "agent"), "unknown": ()}[host]
            if native and self._has(tools, *native):
                candidates.append({"route": "host_subagents", "entrypoint": " / ".join(native),
                    "available": True, "execution_owner": host, "run_mode": "host_defined",
                    "recipe": "hosts/codex/delegate.md" if host == "codex" else "skills/bookmark-research/references/host-workflows.md"})
            services = settings["professional_research"]
            if selected_depth == "deep" or provider is not None:
                for name in ([provider] if provider else [services["provider"]] if services["provider"] else ["openai", "parallel"]):
                    key = ResearchHttp.PROVIDERS[name]["key_env"]
                    credential = bool(os.environ.get(key))
                    candidates.append({"route": "professional_service", "provider": name,
                        "entrypoint": "research_service_start", "execution_owner": name, "run_mode": "provider_background",
                        "available": services["enabled"] and credential, "authentication_verified": False,
                        "missing": ([] if services["enabled"] else ["professional_research.enabled"])
                                   + ([] if credential else [key])})
            candidates.append({"route": "host_iterative_research", "entrypoint": "research_start / research_*",
                "available": True, "execution_owner": "host", "run_mode": "host_defined",
                "reason": "The host can continue reading, reasoning and recording gaps without an extra scheduler."})
        if provider is not None:
            choices = [c for c in candidates if c.get("provider") == provider]
            selected = next((c for c in choices if c["available"]), None)
        else:
            choices = candidates[:]
            if not settings["research"]["prefer_host_workflows"]:
                choices.sort(key=lambda c: c["route"] == "host_workflow")
            selected = next((c for c in choices if c["available"]), None)
        return {"depth": selected_depth, "host": host, "task_shape": task_shape, "selected": selected,
                "candidates": candidates, "missing_or_unconfirmed": missing,
                "observations": {"tools": tools, "commands": commands, "extensions": extensions,
                                 "basis": "caller_reported_current_host", "runtime_tested": False},
                "methods": [{"name": name, "reference": self.METHODS[name]} for name in settings["research"]["methods"]],
                "source_scope": "Keep the frozen research inventory complete across groups and rounds; finish checks coverage.",
                "execution_started": False, "configuration_changed": False,
                "provider_fallback": "An explicitly selected unavailable service is reported unavailable; never silently substituted."}
