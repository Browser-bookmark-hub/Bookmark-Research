"""Tests for Batch 4 hardening items: P2-3, P2-4, P2-5, P3-1, P3-5."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from credentials import Credentials
from grok_search import GrokSearch, OpenAICompatibleAgenticSearch
from mcp_server import SETTINGS_SCHEMA, TOOL_SCHEMAS
from readiness import Readiness
from research import ResearchSessions
from settings import Settings
from wiki import WikiStore


class TestHardeningBatch4(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.settings = Settings(self.base / "settings.json")
        self.archive_dir = self.base / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_dir = self.base / "wiki"
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        self.research_dir = self.base / "research"
        self.research_dir.mkdir(parents=True, exist_ok=True)
        self.settings.update({
            "archive": {"directory": str(self.archive_dir)},
            "wiki": {"directory": str(self.wiki_dir), "after_research": "auto"},
            "output": {"mode": "central", "directory": str(self.research_dir)},
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    # --- P2-3: Agentic Search Budget & Rewrite Query ---

    def test_p2_3_agentic_search_max_iterations_validation(self):
        credentials = Credentials(self.settings)
        agentic = OpenAICompatibleAgenticSearch(self.settings, credentials)
        with self.assertRaises(ValueError):
            agentic.search("test query", max_iterations=0)
        with self.assertRaises(ValueError):
            agentic.search("test query", max_iterations=6)

    def test_p2_3_agentic_search_rewrite_and_budget_bounds(self):
        self.settings.update({
            "custom_agentic": {
                "enabled": True,
                "base_url": "https://api.example.com/v1",
                "model": "model-x",
                "api_mode": "chat_completions",
                "search_mode": "prompt",
            }
        })
        credentials = Credentials(self.settings)
        agentic = OpenAICompatibleAgenticSearch(self.settings, credentials)

        mock_response_body = json.dumps({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Analysis of the query\n\nFinal Answer: Comprehensive overview of topic.",
                }
            }],
            "usage": {"total_tokens": 150},
        }).encode("utf-8")

        mock_cm = Mock()
        mock_cm.read.return_value = mock_response_body
        mock_cm.__enter__ = Mock(return_value=mock_cm)
        mock_cm.__exit__ = Mock(return_value=None)

        with patch.dict("os.environ", {"CUSTOM_AGENTIC_API_KEY": "mock-key"}, clear=True):
            with patch("urllib.request.OpenerDirector.open", return_value=mock_cm) as mock_open:
                result = agentic.search("high level architecture of kubernetes", max_iterations=3, rewrite_query=True)
                self.assertEqual(result["provider"], "custom")
                self.assertEqual(result["iterations"], 1)
                self.assertEqual(result["budget"]["max_iterations"], 3)
                self.assertTrue(result["rewritten"])
                self.assertIn("Final Answer", result["answer"])
                # Verify request payload contains decomposition instruction
                req = mock_open.call_args[0][0]
                payload = json.loads(req.data.decode("utf-8"))
                user_msg = payload["messages"][-1]["content"]
                self.assertIn("Decompose and rewrite", user_msg)

    # --- P2-4: Deep Research Readiness Diagnostics ---

    def test_p2_4_deep_research_readiness_diagnostics(self):
        # 1. Disabled and no credential in env -> disabled_and_unconfigured
        checker = Readiness(self.settings)
        with patch.dict("os.environ", {}, clear=True):
            rows = checker._service_rows("openai")
            openai_row = rows[0]
            self.assertEqual(openai_row["diagnosis"], "disabled_and_unconfigured")
            self.assertIn("Run setup to enable professional_research", openai_row["next_step"])

        # 2. Disabled but credential present in env -> disabled_with_credential_present
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-mock-key"}, clear=True):
            rows = checker._service_rows("openai")
            openai_row = rows[0]
            self.assertEqual(openai_row["diagnosis"], "disabled_with_credential_present")
            self.assertIn("Enable via settings.professional_research.enabled=true", openai_row["next_step"])

        # 3. Enabled but credential missing -> enabled_missing_credential
        self.settings.update({"professional_research": {"enabled": True, "provider": "openai"}})
        with patch.dict("os.environ", {}, clear=True):
            rows = checker._service_rows("openai")
            openai_row = rows[0]
            self.assertEqual(openai_row["diagnosis"], "enabled_missing_credential")
            self.assertIn("Configure OPENAI_API_KEY", openai_row["next_step"])

        # 4. Enabled and credential present -> ready_for_check
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-mock-key"}, clear=True):
            rows = checker._service_rows("openai")
            openai_row = rows[0]
            self.assertEqual(openai_row["diagnosis"], "ready_for_check")
            self.assertIn("Ready for deep research", openai_row["next_step"])

    # --- P2-5: Cache Defaults Documentation & Schema ---

    def test_p2_5_cache_schema_descriptions(self):
        search_cache = SETTINGS_SCHEMA["properties"]["search"]["properties"]["cache_seconds"]
        self.assertIn("description", search_cache)
        self.assertEqual(search_cache["maximum"], 3600)

        fetch_reuse = SETTINGS_SCHEMA["properties"]["fetch"]["properties"]["reuse_seconds"]
        self.assertIn("description", fetch_reuse)
        self.assertEqual(fetch_reuse["maximum"], 86400)

    # --- P3-1: Auto-save Research to Wiki 'auto' Mode ---

    def test_p3_1_wiki_after_research_auto_default(self):
        defaults = Settings.defaults()
        self.assertEqual(defaults["wiki"]["after_research"], "auto")

    def test_p3_1_auto_save_flow_and_skip_reasons(self):
        research = ResearchSessions(directory=self.research_dir, settings=self.settings)
        # Verify skip reasons on _wiki_follow_up
        state_no_claims = {"research_id": "res-1", "topic": "No claims", "claims": [], "sources": []}
        result_no_claims = research._wiki_follow_up(state_no_claims)
        self.assertEqual(result_no_claims["status"], "skipped")
        self.assertEqual(result_no_claims["skip_reason"], "insufficient_evidence")

        state_unaccepted = {
            "research_id": "res-unaccepted",
            "topic": "Unaccepted",
            "claims": [{"id": "c1", "statement": "X is Y", "confidence": "high", "inference": False,
                        "citations": [{"source_id": "s1", "quote": "X is Y"}]}],
            "sources": [{"id": "s1", "review": {"verdict": "rejected"}}],
        }
        result_unaccepted = research._wiki_follow_up(state_unaccepted)
        self.assertEqual(result_unaccepted["status"], "skipped")
        self.assertEqual(result_unaccepted["skip_reason"], "no_accepted_claims")

        state_dry_run = {
            "research_id": "res-2",
            "topic": "Dry run topic",
            "dry_run": True,
            "questions": [{"id": "q1", "question": "What is X?"}],
            "claims": [{"id": "c1", "question_id": "q1", "statement": "X is Y", "confidence": "high", "inference": False,
                        "citations": [{"source_id": "s1", "quote": "X is Y"}]}],
            "sources": [{"id": "s1", "review": {"verdict": "accepted"}}],
        }
        result_dry_run = research._wiki_follow_up(state_dry_run)
        self.assertEqual(result_dry_run["status"], "skipped")
        self.assertEqual(result_dry_run["skip_reason"], "dry_run")

    def test_p3_1_auto_merge_preserves_the_authored_title_and_kind(self):
        existing = {"title": "Aurora sessions", "kind": "entity",
                    "sections": [{"heading": "Reuse", "text": "Authored.", "claims": []}],
                    "links": [{"page_id": "overview", "relation": "Part of"}]}
        draft = {"title": "What is supported?", "kind": "topic",
                 "sections": [{"heading": "Reuse", "text": "Duplicate heading.", "claims": []},
                              {"heading": "Pricing", "text": "New section.", "claims": []}],
                 "links": [{"page_id": "pricing", "relation": "Cites"}]}
        merged = ResearchSessions._merge_wiki_page(existing, draft, max_sections=16)
        self.assertEqual("Aurora sessions", merged["title"])
        self.assertEqual("entity", merged["kind"])
        self.assertEqual(["Reuse", "Pricing"], [section["heading"] for section in merged["sections"]])
        self.assertEqual("Authored.", merged["sections"][0]["text"])
        self.assertEqual(["overview", "pricing"], [link["page_id"] for link in merged["links"]])

    # --- P3-5: Duplicate Concept Prompt on Wiki Write ---

    def test_p3_5_duplicate_concept_detection_and_ignore(self):
        wiki = WikiStore(self.wiki_dir, settings=self.settings)

        source_a = {
            "id": "src-vector-db",
            "url": "https://example.com/vector-db-guide",
            "text": "Vector databases index high dimensional embeddings for fast nearest neighbor search.",
            "title": "Vector DB Guide",
        }
        page_a = {
            "title": "Vector Databases Overview",
            "kind": "topic",
            "links": [],
            "review": {"method": "human", "reviewer": "expert", "note": "Verified"},
            "sections": [{
                "heading": "Introduction",
                "text": "Vector databases are specialized storage engines.",
                "citations": [{"source_id": "src-vector-db", "quote": "Vector databases index high dimensional embeddings for fast nearest neighbor search."}],
            }],
        }

        # 1. Write page A (no existing pages, should have no warnings)
        receipt_a = wiki.write("vector-databases", page_a, change_note="Initial write", sources=[source_a])
        self.assertEqual(receipt_a["status"], "written")
        self.assertNotIn("duplicate_concept_warning", receipt_a)

        # 2. Write page B with overlapping URL and similar title -> must trigger duplicate concept warning
        source_b = {
            "id": "src-vdb-dup",
            "url": "https://example.com/vector-db-guide",
            "text": "Vector databases index high dimensional embeddings for fast nearest neighbor search.",
            "title": "Vector DB Guide Duplicate",
        }
        page_b = {
            "title": "Vector Databases",
            "kind": "topic",
            "links": [],
            "review": {"method": "human", "reviewer": "expert", "note": "Verified"},
            "sections": [{
                "heading": "Concept",
                "text": "Vector databases are specialized storage engines.",
                "citations": [{"source_id": "src-vdb-dup", "quote": "Vector databases index high dimensional embeddings for fast nearest neighbor search."}],
            }],
        }

        receipt_b = wiki.write("vector-db-alt", page_b, change_note="Alternate write", sources=[source_b])
        self.assertEqual(receipt_b["status"], "written")
        self.assertIn("duplicate_concept_warning", receipt_b)
        warnings = receipt_b["duplicate_concept_warning"]
        self.assertTrue(len(warnings) >= 1)
        warning_target = next((w for w in warnings if w["page_id"] == "vector-databases"), None)
        self.assertIsNotNone(warning_target)
        self.assertIn("overlapping_urls", warning_target["reasons"])
        self.assertIn("similar_title", warning_target["reasons"])

        # 3. Write page C with completely different URL and title -> no warnings (no noise)
        source_c = {
            "id": "src-compiler",
            "url": "https://example.com/compiler-design",
            "text": "Compilers translate high level language source code into machine code.",
            "title": "Compiler Design",
        }
        page_c = {
            "title": "Compiler Optimizations",
            "kind": "topic",
            "links": [],
            "review": {"method": "human", "reviewer": "expert", "note": "Verified"},
            "sections": [{
                "heading": "Pipeline",
                "text": "Optimization happens during intermediate representation passes.",
                "citations": [{"source_id": "src-compiler", "quote": "Compilers translate high level language source code into machine code."}],
            }],
        }
        receipt_c = wiki.write("compiler-optimizations", page_c, change_note="Initial write", sources=[source_c])
        self.assertEqual(receipt_c["status"], "written")
        self.assertNotIn("duplicate_concept_warning", receipt_c)

        # 4. Write page D with overlapping URL but ignore_duplicate_warning=True -> warning suppressed
        source_d = {
            "id": "src-vdb-ignored",
            "url": "https://example.com/vector-db-guide",
            "text": "Vector databases index high dimensional embeddings for fast nearest neighbor search.",
            "title": "Vector DB Guide Again",
        }
        page_d = {
            "title": "Vector Databases Deep Dive",
            "kind": "topic",
            "links": [],
            "review": {"method": "human", "reviewer": "expert", "note": "Verified"},
            "sections": [{
                "heading": "Deep Dive",
                "text": "Vector databases are specialized storage engines.",
                "citations": [{"source_id": "src-vdb-ignored", "quote": "Vector databases index high dimensional embeddings for fast nearest neighbor search."}],
            }],
        }
        receipt_d = wiki.write(
            "vector-databases-deep", page_d, change_note="Explicitly ignoring warning",
            sources=[source_d], ignore_duplicate_warning=True
        )
        self.assertEqual(receipt_d["status"], "written")
        self.assertNotIn("duplicate_concept_warning", receipt_d)

        # 5. Updating page A to revision 2 does NOT warn against itself
        page_a_rev2 = dict(page_a)
        page_a_rev2["sections"] = [{
            "heading": "Introduction Updated",
            "text": "Vector databases are specialized storage engines for embeddings.",
            "citations": [{"source_id": "src-vector-db", "quote": "Vector databases index high dimensional embeddings for fast nearest neighbor search."}],
        }]
        receipt_a_rev2 = wiki.write(
            "vector-databases", page_a_rev2, change_note="Update to rev 2",
            expected_revision=1, sources=[source_a]
        )
        self.assertEqual(receipt_a_rev2["revision"], 2)
        # vector-databases should not warn against itself (only maybe against vector-db-alt or vector-databases-deep)
        if "duplicate_concept_warning" in receipt_a_rev2:
            self.assertFalse(any(w["page_id"] == "vector-databases" for w in receipt_a_rev2["duplicate_concept_warning"]))


if __name__ == "__main__":
    unittest.main()
