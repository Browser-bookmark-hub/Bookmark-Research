"""Host packaging, native-script contracts, and the actual shared MCP bridge."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import host_assets
import export_bundle


class HostWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="host workflow 中文 ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.env = dict(os.environ, BOOKMARK_RESEARCH_DATA_DIR=str(self.base / "data"),
                        BOOKMARK_RESEARCH_CONFIG=str(self.base / "settings.json"), PYTHONDONTWRITEBYTECODE="1")

    def run_python(self, script, *args, input=None, success=True):
        result = subprocess.run([sys.executable, "-B", str(script), *args], input=input,
                                text=True, capture_output=True, env=self.env, cwd=self.base, timeout=20)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    @unittest.skipUnless(shutil.which("node"), "Node is required for script syntax/contract tests")
    def test_choreography_preserves_207_ids_failures_and_complete_results(self):
        scripts = {host: host_assets.build_workflow(ROOT, host)[1] for host in ("claude", "dsh", "pi")}
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/host-workflows.test.js")],
                                input=json.dumps(scripts), text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["checks"], 63)
        self.assertNotRegex(scripts["pi"], r"\basync\b", "Pi rejects nested async helpers; use Promise chains")

    def test_dsh_call_contains_plain_script_meta_and_object_args(self):
        output = self.base / "dsh export"
        export_bundle.export_bundle("dsh", output)
        result = self.run_python(output / "hosts/dsh/workflow-call.py", "--research-id", "r-fixture", "--run-key", "run-1",
                                 "--output-language", "zh")
        call = json.loads(result.stdout)
        self.assertEqual(set(call), {"meta", "script", "args"})
        self.assertIsInstance(call["args"], dict)
        self.assertEqual(call["args"]["research_id"], "r-fixture")
        self.assertEqual(call["args"]["output_language"], "zh")
        self.assertNotIn("export const meta", call["script"])
        self.assertIn("pipeline(jobs", call["script"])
        self.assertEqual(call["args"]["bridge_path"], str(output / "hosts/shared/research-call.py"))

    def test_dsh_language_validation_happens_before_preparing_a_call(self):
        script = ROOT / "hosts/dsh/workflow-call.py"
        for language in ("", "   ", "en\nzh", "x" * 81):
            with self.subTest(language=repr(language)):
                result = self.run_python(script, "--research-id", "r-fixture", "--run-key", "run-1",
                                         "--output-language", language, success=False)
                self.assertEqual(result.stdout, "")
                self.assertIn("output-language", result.stderr)

    def test_pi_registration_is_project_scoped_idempotent_and_preserves_conflicts(self):
        output = self.base / "pi export"
        export_bundle.export_bundle("pi", output)
        project = self.base / "project 中文 $(literal)"
        project.mkdir()
        script = output / "hosts/pi/register-workflow.py"
        first = self.run_python(script, "--project", str(project))
        self.assertTrue(json.loads(first.stdout)["changed"])
        target = project / ".pi/subagent-workflows/bookmark-research"
        manifest = json.loads((target / "workflow.json").read_text())
        self.assertEqual(manifest["parameters"]["bridge_path"]["default"], str(output / "hosts/shared/research-call.py"))
        self.assertEqual(manifest["parameters"]["output_language"]["default"], "auto")
        self.assertIn("runs.all", (target / "script.js").read_text())
        self.assertFalse((project / ".pi/settings.json").exists())
        second = self.run_python(script, "--project", str(project))
        self.assertFalse(json.loads(second.stdout)["changed"])
        (target / "script.js").write_text("keep my workflow")
        conflict = self.run_python(script, "--project", str(project), success=False)
        self.assertIn("Existing workflow differs", conflict.stderr)
        self.assertEqual((target / "script.js").read_text(), "keep my workflow")

    def test_pi_registration_rejects_symlink_destination(self):
        project = self.base / "project"
        project.mkdir()
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        (project / ".pi").symlink_to(elsewhere, target_is_directory=True)
        result = self.run_python(ROOT / "hosts/pi/register-workflow.py", "--project", str(project), success=False)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_shared_bridge_calls_real_mcp_and_preserves_domain_errors(self):
        bridge = ROOT / "hosts/shared/research-call.py"
        listed = self.run_python(bridge, input=json.dumps({"name": "research_status", "arguments": {}}))
        value = json.loads(listed.stdout)
        self.assertFalse(value["isError"])
        self.assertEqual(value["result"]["sessions"], [])
        failed = self.run_python(bridge, input=json.dumps({"name": "research_status", "arguments": {
            "research_id": "r-nonexistent"}}), success=False)
        self.assertTrue(json.loads(failed.stdout)["isError"])
        rejected = self.run_python(bridge, input=json.dumps({"name": "sync_package", "arguments": {}}), success=False)
        self.assertIn("research_*", rejected.stdout)

    def test_complete_external_result_survives_real_mcp_round_trip_and_replay(self):
        bridge = ROOT / "hosts/shared/research-call.py"
        started = self.run_python(bridge, input=json.dumps({"name": "research_start", "arguments": {
            "brief": "Save the host's observed analysis", "questions": [{"id": "q1", "question": "What was verified?"}]}}))
        research_id = json.loads(started.stdout)["result"]["research_id"]
        analysis = {"inventory_ids": ["u-" + str(index) for index in range(207)],
                    "attempts": [{"ok": False, "error": "Observed child failure", "data": None}],
                    "coverage": {"missing_ids": ["u-206"]}, "remaining_ids": ["u-206"]}
        request = {"name": "research_record", "arguments": {"research_id": research_id, "entry": {
            "kind": "external_run", "id": "host-analysis", "provider": "dsh", "run_id": "local:fixture",
            "status": "completed", "text": "Analysis settled; this does not mark research completed.", "result": analysis}}}
        recorded = json.loads(self.run_python(bridge, input=json.dumps(request)).stdout)["result"]["recorded"]
        artifact = Path(recorded["result_path"])
        self.assertIn(self.base / "data", artifact.parents)
        self.assertEqual(json.loads(artifact.read_text()), analysis)
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), recorded["result_sha256"])
        replay = json.loads(self.run_python(bridge, input=json.dumps(request)).stdout)["result"]
        self.assertTrue(replay["replayed"])
        status = json.loads(self.run_python(bridge, input=json.dumps({"name": "research_status", "arguments": {
            "research_id": research_id, "section": "external_runs"}})).stdout)["result"]
        self.assertEqual(status["total"], 1)
        self.assertEqual(status["items"][0]["result_path"], str(artifact))

    def test_missing_or_linked_host_asset_cannot_publish_partial_export(self):
        source = self.base / "source"
        for directory in (*export_bundle.SHARED_ROOTS, "hosts", ".codex-plugin"):
            shutil.copytree(ROOT / directory, source / directory)
        for relative in export_bundle.SHARED_DOCUMENTS:
            (source / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, source / relative)
        shutil.copy2(ROOT / "LICENSE", source / "LICENSE")
        asset = source / "hosts/pi/runtime.js"
        asset.unlink()
        output = self.base / "incomplete"
        with self.assertRaisesRegex(ValueError, "Required host asset"):
            export_bundle.export_bundle("pi", output, source)
        self.assertFalse(output.exists())
        asset.symlink_to(ROOT / "hosts/pi/runtime.js")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            export_bundle.export_bundle("pi", output, source)
        self.assertFalse(output.exists())

    def test_codex_prepare_consumes_real_inventory_pagination(self):
        package = self.base / "package"
        package.mkdir()
        section = package / "临时栏目/常规链式/A-1 Sources.json"
        section.parent.mkdir(parents=True)
        section.write_text(json.dumps({
            "format": "bookmark-canvas-section", "schemaVersion": 2, "sectionType": "temporary",
            "id": "sources", "label": "A-1", "title": "Synthetic inventory", "tempKind": "regular",
            "items": [{"id": "i-" + str(index), "sectionId": "sources", "type": "bookmark",
                       "title": "Source " + str(index), "url": "https://example.test/" + str(index)}
                      for index in range(207)]}), encoding="utf-8")
        self.run_python(ROOT / "src/cli.py", "sync", str(package), "--source-id", "host-fixture")
        started = self.run_python(ROOT / "hosts/shared/research-call.py", input=json.dumps({
            "name": "research_start", "arguments": {"brief": "Review synthetic sources",
            "questions": [{"id": "q1", "question": "What do the sources show?"}], "source_ids": ["host-fixture"]}}))
        research_id = json.loads(started.stdout)["result"]["research_id"]
        prepared = self.run_python(ROOT / "hosts/codex/prepare.py", "--research-id", research_id)
        result = json.loads(prepared.stdout)
        self.assertEqual(result["total"], 207)
        self.assertEqual(len(set(result["inventory_ids"])), 207)
        self.assertEqual([identifier for group in result["groups"] for identifier in group["inventory_ids"]], result["inventory_ids"])
        self.assertEqual(result["agents_started"], 0)


if __name__ == "__main__":
    unittest.main()
