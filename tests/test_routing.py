"""Research routes depend on observed capabilities, not a host's brand name."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from routing import ResearchRouting
from settings import Settings


class RoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-route-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.settings = Settings(self.base / "settings.json")
        self.router = ResearchRouting(self.settings)
        environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "PARALLEL_API_KEY": "",
            "BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "data")})
        environment.start()
        self.addCleanup(environment.stop)

    def test_offline_lookup_needs_no_host_extension_or_configuration_write(self):
        result = self.router.route(task_shape="lookup")
        self.assertEqual(result["depth"], "quick")
        self.assertEqual(result["selected"]["route"], "direct_retrieval")
        self.assertFalse(result["execution_started"])
        self.assertFalse(result["observations"]["runtime_tested"])
        self.assertFalse(self.settings.path.exists())
        self.assertFalse((self.base / "data").exists())

    def test_codex_uses_observed_native_delegation_without_inventing_runtime(self):
        result = self.router.route(host="codex", task_shape="batch_research",
                                   observed_tools=["collaboration.spawn_agent"])
        self.assertEqual(result["selected"]["route"], "host_subagents")
        self.assertFalse(any(row["route"] == "host_workflow" for row in result["candidates"]))
        absent = self.router.route(host="codex", task_shape="batch_research")
        self.assertEqual(absent["selected"]["route"], "host_iterative_research")

    def test_pi_installed_names_do_not_prove_tools_are_loaded(self):
        installed = ["pi-subagents", "pi-subagents-workflows"]
        result = self.router.route(host="pi", installed_extensions=installed)
        self.assertEqual(result["selected"]["route"], "host_iterative_research")
        result = self.router.route(host="pi", installed_extensions=installed,
                                   observed_tools=["pi_subagent_workflow"])
        self.assertEqual(result["selected"]["run_mode"], "detached")
        self.assertEqual(result["selected"]["resume_scope"], "registry_does_not_add_replay")

    def test_dsh_keeps_blocking_result_and_no_claim_of_resume(self):
        result = self.router.route(host="dsh", observed_tools=["mcp__dsh__workflow"])
        self.assertEqual(result["selected"]["run_mode"], "blocking")
        self.assertEqual(result["selected"]["resume_scope"], "not_established")

    def test_claude_builtin_requires_explicit_command_and_cannot_cover_a_package(self):
        result = self.router.route(host="claude_code", depth="deep", available_commands=["/deep-research"])
        self.assertEqual(result["selected"]["route"], "host_deep_research")
        self.assertEqual(result["selected"]["invocation"], "explicit_command_required")
        result = self.router.route(host="claude_code", task_shape="batch_research",
                                   available_commands=["/deep-research"])
        self.assertEqual(result["selected"]["route"], "host_iterative_research")
        result = self.router.route(host="claude_code", task_shape="batch_research",
                                   available_commands=["/bookmark-research:bookmark-research", "/deep-research"])
        self.assertEqual(result["selected"]["route"], "host_workflow")
        self.assertEqual(result["selected"]["resume_scope"], "same_session_with_possible_child_replay")

    def test_explicit_unavailable_service_never_substitutes_a_host_or_another_provider(self):
        result = self.router.route(host="codex", observed_tools=["spawn_agent"], provider="openai", depth="deep")
        self.assertIsNone(result["selected"])
        chosen = [row for row in result["candidates"] if row.get("provider") == "openai"][0]
        self.assertEqual(chosen["missing"], ["professional_research.enabled", "OPENAI_API_KEY"])
        self.settings.update({"professional_research": {"enabled": True, "provider": "openai"}})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-presence-only"}):
            result = self.router.route(provider="openai", depth="deep")
        self.assertEqual(result["selected"]["provider"], "openai")
        self.assertFalse(result["selected"]["authentication_verified"])
        self.assertNotIn("synthetic-presence-only", str(result))

    def test_user_workflow_preference_and_method_references_are_respected(self):
        self.settings.update({"research": {"prefer_host_workflows": False, "methods": ["wiki_synthesis"]}})
        result = self.router.route(host="claude_code", observed_tools=["Workflow", "Agent"])
        self.assertEqual(result["selected"]["route"], "host_subagents")
        self.assertEqual(result["methods"][0]["name"], "wiki_synthesis")
        for arguments in ({"observed_tools": "workflow"}, {"host": "unresearched-host"},
                          {"installed_extensions": [None]}, {"provider": "tavily"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.router.route(**arguments)

    def test_deep_service_preference_leads_to_the_real_lifecycle(self):
        self.settings.update({"professional_research": {"enabled": True, "provider": "parallel"}})
        with patch.dict(os.environ, {"PARALLEL_API_KEY": "synthetic-presence"}):
            result = self.router.route(depth="deep", host="codex", observed_tools=["spawn_agent"])
        self.assertEqual(result["selected"]["route"], "professional_service")
        self.assertEqual(result["selected"]["provider"], "parallel")
        self.assertEqual(result["next_action"]["tool"], "research_start")
        steps = result["workflow"]
        self.assertLess(steps.index("research_service_prepare"), steps.index("research_service_start"))
        self.assertLess(steps.index("research_service_start"), steps.index("research_service_result"))
        self.assertLess(steps.index("research_service_import"), steps.index("research_source"))
        self.assertFalse(result["execution_started"])

    def test_missing_deep_api_does_not_disable_native_research_or_silently_replace_explicit_api(self):
        native = self.router.route(depth="deep")
        self.assertEqual(native["selected"]["route"], "host_iterative_research")
        self.assertIn("research_fetch", native["workflow"])
        explicit = self.router.route(provider="openai", task_shape="lookup")
        self.assertEqual(explicit["depth"], "deep")
        self.assertIsNone(explicit["selected"])
        self.assertEqual(explicit["next_action"]["tool"], "research_services")
        self.assertEqual(explicit["next_action"]["arguments"], {"provider": "openai"})

    def test_observed_research_mcp_is_used_then_excluded_after_confirmed_failure(self):
        arguments = {"depth": "deep", "host": "codex", "observed_tools": ["mcp__exa__agent_run"]}
        first = self.router.route(**arguments)
        self.assertEqual(first["selected"]["route_id"], "host_research_mcp:exa")
        self.assertIn("mcp__exa__agent_run", first["workflow"])
        self.assertIn("research_import_evidence", first["workflow"])
        self.assertFalse(first["selected"]["authentication_verified"])
        fallback = self.router.route(**arguments, failed_routes=[first["selected"]["route_id"]])
        self.assertEqual(fallback["selected"]["route_id"], "host_iterative_research")
        self.assertIn("unknown_outcome", fallback["fallback"]["hold_on"])
        exhausted = self.router.route(**arguments, failed_routes=[first["selected"]["route_id"], "host_iterative_research"])
        self.assertIsNone(exhausted["selected"])
        self.assertFalse(exhausted["execution_started"])

    def test_task_mcp_requires_observed_creation_status_and_result_tools(self):
        tools = ["mcp__parallel__createDeepResearch", "mcp__parallel__getStatus", "mcp__parallel__getResultMarkdown"]
        self.assertEqual(self.router.route(depth="deep", observed_tools=tools[:1])["selected"]["route"], "host_iterative_research")
        self.assertEqual(self.router.route(depth="deep", observed_tools=tools)["selected"]["route_id"], "host_research_mcp:parallel")

    def test_default_service_can_fall_back_but_explicit_service_remains_exclusive(self):
        self.settings.update({"professional_research": {"enabled": True, "provider": "openai"}})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic", "PARALLEL_API_KEY": "synthetic"}):
            first = self.router.route(depth="deep")
            self.assertEqual(first["selected"]["route_id"], "professional_service:openai")
            fallback = self.router.route(depth="deep", failed_routes=[first["selected"]["route_id"]])
            self.assertEqual(fallback["selected"]["route_id"], "professional_service:parallel")
            explicit = self.router.route(provider="openai", failed_routes=[first["selected"]["route_id"]])
        self.assertIsNone(explicit["selected"])
        self.assertEqual(explicit["fallback"]["remaining_routes"], [])
        self.assertTrue(explicit["fallback"]["explicit_provider_is_exclusive"])


if __name__ == "__main__":
    unittest.main()
