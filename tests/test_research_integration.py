"""Whole-input research, authored Wiki and evaluation through real MCP/CLI APIs."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mcp_server import StdioMcpServer
from settings import Settings


ROOT = Path(__file__).resolve().parents[1]


class ResearchIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-flow 中文 ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "data"),
            "OPENAI_API_KEY": "", "PARALLEL_API_KEY": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.settings = Settings(self.base / "settings.json")
        self.db = self.base / "index.sqlite3"
        self.server = StdioMcpServer(self.db, settings=self.settings, stderr=io.StringIO())
        self.addCleanup(self.server.close)
        self.engine = Mock()
        self.server._providers = self.engine
        self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "1"}}})
        self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.package = self.base / "package"
        section = self.package / "临时栏目" / "A-1.json"
        section.parent.mkdir(parents=True)
        section.write_text(json.dumps({"format": "bookmark-canvas-section", "schemaVersion": 2,
            "id": "temp-section-A-1", "sectionType": "temporary", "label": "A-1", "title": "Test sources",
            "items": [{"id": "b" + str(i), "sectionId": "temp-section-A-1", "type": "bookmark",
                "url": "https://example.test/" + value, "title": value, "note": "Private local context " + str(i)}
                for i, value in enumerate(("aurora", "brook", "cobalt", "aurora"))]}), encoding="utf-8")
        self.source_hash = hashlib.sha256(section.read_bytes()).hexdigest()
        self.section = section
        self.call("sync_package", {"package_path": str(self.package), "source_id": "fixture"})
        self.rid = self.call("research_start", {"brief": "Review the entire synthetic package.",
            "questions": [{"id": "q1", "question": "What does each source state?"}],
            "source_ids": ["fixture"]})["research_id"]

    def call(self, name, arguments=None, fails=False):
        response = self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}})
        self.assertNotIn("error", response, response)
        self.assertEqual(response["result"]["isError"], fails, response)
        result = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(response["result"]["structuredContent"], result)
        return result

    def cli(self, *arguments, payload=None, returncode=0):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "src/cli.py"), "--db", str(self.db),
            "--config", str(self.settings.path), *arguments], text=True, capture_output=True,
            input=json.dumps(payload) if payload is not None else None, env=dict(os.environ), timeout=20)
        self.assertEqual(result.returncode, returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def record(self, entry):
        return self.call("research_record", {"research_id": self.rid, "entry": entry})["recorded"]

    def test_paginated_scope_evidence_completion_and_wiki_survive_cross_interface_use(self):
        first = self.call("research_inventory", {"research_id": self.rid, "limit": 2})
        second = self.cli("research", "inventory", self.rid, "--offset", str(first["next_offset"]), "--limit", "2")
        entries = first["items"] + second["items"]
        self.assertEqual(first["scope_total"], 3)
        self.assertIsNone(second["next_offset"])
        self.assertEqual(len({entry["id"] for entry in entries}), 3)
        self.assertEqual(sum(len(entry["instances"]) for entry in entries), 4)

        report = self.call("research_import_evidence", {"research_id": self.rid, "operation_id": "secondary",
            "question_id": "q1", "url": "external:fixture-report", "text": "A secondary report mentions every source.",
            "provenance": {"kind": "external_report", "provider": "synthetic-fixture"},
            "inventory_ids": [entry["id"] for entry in entries]})
        self.record({"kind": "source_review", "source_id": report["sources"][0]["id"],
            "verdict": "accepted", "text": "A secondary fixture report; original pages have not been read."})
        empty = self.call("research_coverage", {"research_id": self.rid})
        self.assertEqual(empty["metrics"]["usable_text"]["count"], 0)
        self.assertEqual(empty["metrics"]["substantive_review"]["count"], 0)

        claims = []
        for i, entry in enumerate(entries):
            statement = "Source %s explicitly documents search." % entry["original_url"].rsplit("/", 1)[1]
            imported = self.cli("research", "import-evidence", self.rid, "--input", "-", payload={
                "operation_id": "original-" + str(i), "question_id": "q1", "url": entry["original_url"],
                "text": statement, "provenance": {"kind": "page", "provider": "synthetic-fixture"},
                "inventory_ids": [entry["id"]]})
            sid = imported["sources"][0]["id"]
            self.record({"kind": "source_review", "source_id": sid, "verdict": "accepted",
                "text": "Synthetic original text matches the frozen URL and the quoted claim."})
            claim = self.record({"kind": "claim", "question_id": "q1", "statement": statement,
                "citations": [{"source_id": sid, "quote": statement}]})
            claims.append(claim["id"])
            self.record({"kind": "inventory_review", "inventory_id": entry["id"], "disposition": "reviewed",
                "question_ids": ["q1"], "source_ids": [sid], "claim_ids": [claim["id"]],
                "text": statement})
            self.record({"kind": "answer", "question_id": "q1", "answer": "The reviewed sources document search.",
                "claim_ids": claims})
            if i == 0:
                refused = self.call("research_finish", {"research_id": self.rid,
                    "summary": "Only one original source reviewed.", "status": "completed"}, fails=True)
                self.assertIn("coverage incomplete", refused["error"])
                gaps = self.cli("research", "coverage", self.rid, "--filter", "unreviewed")
                self.assertEqual(gaps["total"], 2)
                self.assertEqual(gaps["metrics"]["question_completion"]["count"], 1)

        done = self.call("research_finish", {"research_id": self.rid, "summary": "All synthetic original sources reviewed."})
        self.assertEqual(done["status"], "completed")
        for artifact in ("inventory", "coverage", "report", "sources"):
            self.assertTrue(Path(done["artifacts"][artifact]).is_file())
        coverage = self.cli("research", "coverage", self.rid)
        self.assertEqual(coverage["metrics"]["substantive_review"], {"count": 3, "total": 3, "rate": 1.0})

        page = {"title": "Synthetic source comparison", "kind": "topic", "sections": [
            {"heading": "Search", "text": "Each reviewed fixture source documents search.",
             "claims": [{"research_id": self.rid, "claim_id": claim_id} for claim_id in claims]}],
            "links": [], "review": {"method": "human", "reviewer": "Fixture author",
                "note": "Test data; no live semantic quality assertion."}}
        self.cli("wiki", "write", "search-capabilities", "--input", "-", payload={
            "page": page, "change_note": "Organize the reviewed synthetic findings."})
        read = self.call("wiki_get", {"page_id": "search-capabilities"})
        self.assertEqual(read["page"], page)
        self.assertEqual(self.call("wiki_search", {"query": "documents search"})["total"], 1)
        self.assertEqual(self.cli("wiki", "lint")["status"], "ok")
        self.assertEqual(hashlib.sha256(self.section.read_bytes()).hexdigest(), self.source_hash)
        self.engine.search.assert_not_called()
        self.engine.fetch.assert_not_called()

    def test_routing_configuration_and_evaluation_match_cli_and_mcp(self):
        changed = self.call("update_settings", {"changes": {"research": {"depth": "deep"},
            "professional_research": {"provider": None}, "wiki": {"directory": str(self.base / "wiki")}}})
        self.assertEqual(self.cli("config", "show"), changed)
        arguments = {"host": "codex", "task_shape": "batch_research", "observed_tools": ["collaboration.spawn_agent"]}
        expected = self.call("research_route", arguments)
        self.assertEqual(self.cli("research", "route", "--input", "-", payload=arguments), expected)
        self.assertEqual(self.cli("research", "service", "describe"), self.call("research_services"))
        fixture = json.loads((ROOT / "tests/fixtures/research-quality.json").read_text())
        payload = {key: fixture[key] for key in ("suite", "runs", "judgments")}
        evaluated = self.call("evaluate_research", payload)
        self.assertEqual(self.cli("evaluate", "--input", "-", payload=payload), evaluated)
        self.assertEqual(evaluated["kind"], "synthetic_demonstration")
        self.assertFalse(evaluated["provider_quality_claim"])


if __name__ == "__main__":
    unittest.main()
