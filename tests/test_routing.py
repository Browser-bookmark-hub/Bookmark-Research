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


if __name__ == "__main__":
    unittest.main()
