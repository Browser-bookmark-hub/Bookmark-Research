"""Evidence and snapshots must stay consistent across lifecycle boundaries."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from research import ResearchSessions
from settings import Settings
from source_manager import SourceManager
from wiki import WikiStore
import source_manager


def package(root, url="https://example.test/one"):
    card = {"format": "bookmark-canvas-section", "schemaVersion": 2,
            "id": "temp-section-A-1", "sectionType": "temporary", "label": "A-1", "title": "Saved",
            "items": [{"id": "b0", "sectionId": "temp-section-A-1", "type": "bookmark",
                       "url": url, "title": "Saved bookmark"}]}
    (root / "临时栏目").mkdir(parents=True, exist_ok=True)
    (root / "临时栏目" / "A-1.json").write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    return root


class IsolatedLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark lifecycle ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.base / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.settings = Settings(self.base / "settings.json")
        self.db = self.base / "data" / "index.sqlite3"


class ResearchLifecycleTests(IsolatedLifecycleTests):
    def setUp(self):
        super().setUp()
        self.engine = Mock()
        self.sessions = ResearchSessions(self.base / "research", settings=self.settings,
                                         engine=self.engine, db_path=self.db)

    def start(self, providers=None):
        return self.sessions.start("Lifecycle", [{"id": "q1", "question": "What is supported?"}],
                                   providers=providers or ["exa"])["research_id"]

    def slow_fetch(self, rid, fails=False):
        started, release = threading.Event(), threading.Event()
        outcome = {}

        def fetched(urls, provider, archive, max_characters):
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test request was not released")
            if fails:
                raise RuntimeError("Synthetic provider failure")
            return {"provider": provider, "urls": urls, "tool": "web_fetch",
                    "request_arguments": {"urls": urls}, "requested_max_characters": max_characters,
                    "retrieved_at": "2026-10-09T00:00:00Z", "usage": {"tool_calls": 1},
                    "result": {"structuredContent": {"results": [
                        {"url": url, "title": "Saved page", "text": "Saved page body."} for url in urls]}}}

        def run():
            try:
                outcome["result"] = self.sessions.fetch(rid, "slow", "q1", ["https://example.test/one"])
            except Exception as error:
                outcome["error"] = error

        self.engine.fetch.side_effect = fetched
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(started.wait(5))
        return release, worker, outcome

    def test_terminal_reports_reject_late_results_without_changing_saved_artifacts(self):
        for status in ("cancelled", "incomplete"):
            with self.subTest(status=status):
                rid = self.start()
                release, worker, outcome = self.slow_fetch(rid)
                try:
                    result = self.sessions.finish(rid, "Stopped while a request was in flight.", status=status)
                    paths = [Path(result["artifacts"][name]) for name in ("report", "sources", "state", "coverage")]
                    saved = {path: path.read_bytes() for path in paths}
                finally:
                    release.set()
                    worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertIsInstance(outcome.get("error"), ValueError, outcome)
                self.assertEqual(saved, {path: path.read_bytes() for path in paths})

    def test_interruption_acknowledgement_rejects_a_late_result(self):
        rid = self.start()
        release, worker, outcome = self.slow_fetch(rid)
        try:
            self.sessions.record(rid, {"kind": "interruption", "operation_id": "slow",
                                      "text": "The request outcome is unknown; do not retry it."})
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcome.get("error"), ValueError, outcome)
        _, state = self.sessions._load(rid)
        self.assertEqual("unknown_outcome", state["operations"][0]["status"])
        self.assertEqual([], state["sources"])

    def test_cancel_prevents_an_additional_fallback_request_and_budget_reservation(self):
        rid = self.start(providers=["exa", "jina"])
        release, worker, outcome = self.slow_fetch(rid, fails=True)
        try:
            self.sessions.finish(rid, "Cancel before fallback.", status="cancelled")
            path, _ = self.sessions._load(rid)
            saved = (path / "state.json").read_bytes()
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcome.get("error"), ValueError, outcome)
        self.assertEqual(1, self.engine.fetch.call_count)
        self.assertEqual(saved, (path / "state.json").read_bytes())

    def test_concurrent_import_manifests_use_the_final_source_id_and_replay_it(self):
        rid = self.start()
        started, release = threading.Event(), threading.Event()
        outcome = {}
        original_write = self.sessions._write
        provenance = {"kind": "local_document", "provider": "tests"}

        def gated_write(path, value):
            original_write(path, value)
            if path.name == "response.json" and value.get("url") == "https://example.test/slow":
                started.set()
                if not release.wait(5):
                    raise RuntimeError("Test import was not released")

        def run():
            try:
                outcome["result"] = self.sessions.import_evidence(rid, "slow-import", "q1",
                    "https://example.test/slow", "Slow document.", provenance)
            except Exception as error:
                outcome["error"] = error

        with patch.object(self.sessions, "_write", side_effect=gated_write):
            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(started.wait(5))
            try:
                self.sessions.import_evidence(rid, "fast-import", "q1", "https://example.test/fast",
                                               "Fast document.", provenance)
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertNotIn("error", outcome)
        path, state = self.sessions._load(rid)
        self.assertEqual(["s1", "s2"], [source["id"] for source in state["sources"]])
        for source in state["sources"]:
            manifest = json.loads((path / source["manifest_file"]).read_text(encoding="utf-8"))
            self.assertEqual(source, manifest["source"])
        replay = self.sessions.import_evidence(rid, "slow-import", "q1", "https://example.test/slow",
                                                "Slow document.", provenance)
        self.assertTrue(replay["replayed"])
        self.assertEqual("s2", replay["sources"][0]["id"])


class SourceLifecycleTests(IsolatedLifecycleTests):
    def setUp(self):
        super().setUp()
        self.index = BookmarkIndex(self.db)
        self.addCleanup(self.index.close)
        self.other_index = BookmarkIndex(self.db)
        self.addCleanup(self.other_index.close)
        self.manager, self.other = SourceManager(self.index), SourceManager(self.other_index)

    def crash_removal(self, source_id, after_commit=False):
        script = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from bookmark_index import BookmarkIndex
from source_manager import SourceManager
import source_manager
index = BookmarkIndex(sys.argv[2])
manager = SourceManager(index)
original_rename = Path.rename
original_rmtree = source_manager.shutil.rmtree
def rename_and_exit(path, target):
    result = original_rename(path, target)
    if Path(target).name.startswith('.removed-'):
        os._exit(91)
    return result
def exit_before_cleanup(path, *args, **kwargs):
    if Path(path).name.startswith('.removed-'):
        os._exit(92)
    return original_rmtree(path, *args, **kwargs)
if sys.argv[4] == 'after-commit':
    source_manager.shutil.rmtree = exit_before_cleanup
else:
    Path.rename = rename_and_exit
manager.remove(sys.argv[3], confirm=True)
"""
        result = subprocess.run([sys.executable, "-B", "-c", script,
            str(Path(__file__).resolve().parents[1] / "src"), str(self.db), source_id,
            "after-commit" if after_commit else "before-commit"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(92 if after_commit else 91, result.returncode, result.stderr)

    def test_startup_restores_referenced_versions_after_process_exit_before_commit(self):
        input_path = package(self.base / "crash-before-commit")
        first = self.manager.sync(input_path, mode="snapshot")
        package(input_path, "https://example.test/second-version")
        current = self.manager.sync(input_path, source_id=first["source_id"], mode="snapshot")
        saved = {row["snapshot_path"]: (Path(row["snapshot_path"]).parent / "manifest.json").read_bytes()
                 for row in (first, current)}
        self.crash_removal(first["source_id"])
        self.assertTrue(all(not Path(path).exists() for path in saved))
        with BookmarkIndex(self.db) as reopened:
            recovered = SourceManager(reopened)
            self.assertEqual(current["version_id"], recovered._record(first["source_id"])["version_id"])
            for path, manifest in saved.items():
                self.assertTrue(Path(path).is_dir())
                self.assertEqual(manifest, (Path(path).parent / "manifest.json").read_bytes())

    def test_startup_does_not_revive_a_source_deleted_before_process_exit(self):
        source = self.manager.sync(package(self.base / "crash-after-commit"), mode="snapshot")
        self.crash_removal(source["source_id"], after_commit=True)
        retired = list(self.manager.storage.glob(".removed-*"))
        self.assertTrue(retired)
        with BookmarkIndex(self.db) as reopened:
            SourceManager(reopened)
            self.assertIsNone(reopened.connection.execute(
                "SELECT 1 FROM sources WHERE source_id=?", (source["source_id"],)).fetchone())
        self.assertFalse(Path(source["snapshot_path"]).exists())
        self.assertTrue(all(path.is_dir() for path in retired))

    def test_startup_keeps_new_snapshots_when_a_deleted_source_id_is_reused(self):
        for changed_content in (False, True):
            with self.subTest(changed_content=changed_content):
                input_path = package(self.base / ("reused-source-" + str(changed_content)))
                old = self.manager.sync(input_path, mode="snapshot")
                self.crash_removal(old["source_id"], after_commit=True)
                if changed_content:
                    package(input_path, "https://example.test/new-source-content")
                new = self.manager.sync(input_path, source_id=old["source_id"], mode="snapshot")
                new_manifest = Path(new["snapshot_path"]).parent / "manifest.json"
                saved = new_manifest.read_bytes()
                with BookmarkIndex(self.db) as reopened:
                    recovered = SourceManager(reopened)
                    self.assertEqual(new["version_id"], recovered._record(old["source_id"])["version_id"])
                    self.assertEqual(1, reopened.connection.execute(
                        "SELECT COUNT(*) FROM source_snapshots WHERE source_id=?", (old["source_id"],)).fetchone()[0])
                self.assertEqual(saved, new_manifest.read_bytes())
                if changed_content:
                    self.assertFalse(Path(old["snapshot_path"]).exists())

    def test_startup_recovers_old_referenced_versions_without_overwriting_a_new_one(self):
        input_path = package(self.base / "new-version-before-recovery")
        old = self.manager.sync(input_path, mode="snapshot")
        self.crash_removal(old["source_id"])
        package(input_path, "https://example.test/published-before-recovery")
        new = self.manager.sync(input_path, source_id=old["source_id"], mode="snapshot")
        new_manifest = Path(new["snapshot_path"]).parent / "manifest.json"
        saved = new_manifest.read_bytes()
        with BookmarkIndex(self.db) as reopened:
            recovered = SourceManager(reopened)
            self.assertEqual(new["version_id"], recovered._record(old["source_id"])["version_id"])
        self.assertTrue(Path(old["snapshot_path"]).is_dir())
        self.assertEqual(saved, new_manifest.read_bytes())

    def test_startup_skips_malformed_or_symlinked_recovery_paths(self):
        for unsafe in ("name", "retired", "version", "package", "canonical"):
            with self.subTest(unsafe=unsafe):
                source = self.manager.sync(package(self.base / ("unsafe-" + unsafe)), mode="snapshot")
                canonical = Path(source["snapshot_path"]).parents[1]
                retired = canonical.with_name(".removed-" + canonical.name + "-" + "a" * 32)
                if unsafe == "name":
                    retired = canonical.with_name(".removed-" + canonical.name + "-invalid")
                canonical.rename(retired)
                external = self.base / ("external-" + unsafe)
                if unsafe == "retired":
                    retired.rename(external)
                    retired.symlink_to(external, target_is_directory=True)
                elif unsafe in ("version", "package"):
                    target = retired / source["version_id"]
                    if unsafe == "package":
                        target = target / "package"
                    target.rename(external)
                    target.symlink_to(external, target_is_directory=True)
                elif unsafe == "canonical":
                    external.mkdir()
                    canonical.symlink_to(external, target_is_directory=True)
                with BookmarkIndex(self.db) as reopened:
                    SourceManager(reopened)
                self.assertFalse(Path(source["snapshot_path"]).exists())
                self.assertTrue(retired.exists())

    def test_merge_revalidates_versions_inside_its_write_transaction(self):
        target = self.manager.sync(package(self.base / "target"), mode="snapshot")
        duplicate_path = package(self.base / "duplicate")
        duplicate = self.manager.sync(duplicate_path, mode="snapshot")
        original_transaction = self.index.transaction
        changed = {}

        @contextmanager
        def update_before_begin():
            if not changed:
                package(duplicate_path, "https://example.test/new-unique")
                changed.update(self.other.sync(duplicate_path, source_id=duplicate["source_id"], mode="snapshot"))
            with original_transaction():
                yield

        with patch.object(self.index, "transaction", side_effect=update_before_begin):
            with self.assertRaisesRegex(ValueError, "different content versions"):
                self.manager.merge(duplicate["source_id"], target["source_id"], confirm=True)
        self.assertNotEqual(target["version_id"], changed["version_id"])
        self.assertTrue(Path(changed["snapshot_path"]).is_dir())
        self.assertEqual(changed["version_id"], self.manager._record(duplicate["source_id"])["version_id"])

    def test_unversioned_legacy_sources_cannot_be_merged_as_duplicates(self):
        first = self.index.sync(package(self.base / "legacy-one"))
        other = self.index.sync(package(self.base / "legacy-two", "https://example.test/other"))
        with self.assertRaisesRegex(ValueError, "version"):
            self.manager.merge(other["source_id"], first["source_id"], confirm=True)
        self.assertEqual(2, self.index.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])

    def test_cleanup_preserves_a_concurrently_reimported_source_snapshot(self):
        for operation in ("remove", "merge"):
            with self.subTest(operation=operation):
                input_path = package(self.base / operation)
                original = self.manager.sync(input_path, mode="snapshot")
                sid = original["source_id"]
                target = self.manager.sync(package(self.base / (operation + "-target")), mode="snapshot")
                original_rmtree = source_manager.shutil.rmtree
                imported = {}

                def import_before_cleanup(path, *args, **kwargs):
                    if Path(path).parent == self.manager.storage and not imported:
                        imported["started"] = True
                        imported.update(self.other.sync(input_path, source_id=sid, mode="snapshot"))
                    return original_rmtree(path, *args, **kwargs)

                with patch.object(source_manager.shutil, "rmtree", side_effect=import_before_cleanup):
                    if operation == "remove":
                        self.manager.remove(sid, confirm=True)
                    else:
                        self.manager.merge(sid, target["source_id"], confirm=True)
                self.assertTrue(imported)
                current = self.manager._record(sid)
                self.assertEqual(imported["snapshot_path"], current["snapshot_path"])
                self.assertTrue(Path(current["snapshot_path"]).is_dir())
                self.assertTrue((Path(current["snapshot_path"]).parent / "manifest.json").is_file())

    def test_failed_transaction_restores_the_source_and_snapshot(self):
        source = self.manager.sync(package(self.base / "rollback"), mode="snapshot")
        original_transaction = self.index.transaction
        failed = []

        @contextmanager
        def fail_commit_once():
            with original_transaction():
                yield
                if not failed:
                    failed.append(True)
                    raise RuntimeError("Synthetic transaction failure")

        with patch.object(self.index, "transaction", side_effect=fail_commit_once):
            with self.assertRaisesRegex(RuntimeError, "Synthetic transaction failure"):
                self.manager.remove(source["source_id"], confirm=True)
        self.assertEqual(source["snapshot_path"], self.manager._record(source["source_id"])["snapshot_path"])
        self.assertTrue(Path(source["snapshot_path"]).is_dir())
        self.assertFalse(any(path.name.startswith(".removed-") for path in self.manager.storage.iterdir()))

    def test_rollback_recovery_preserves_a_snapshot_published_after_the_rollback(self):
        input_path = package(self.base / "rollback-with-new-version")
        source = self.manager.sync(input_path, mode="snapshot")
        original_transaction = self.index.transaction
        failed, changed = [], {}

        @contextmanager
        def update_after_rollback():
            first = not failed
            if first:
                failed.append(True)
            try:
                with original_transaction():
                    yield
                    if first:
                        raise RuntimeError("Synthetic transaction failure")
            except RuntimeError:
                if first:
                    package(input_path, "https://example.test/new-after-rollback")
                    changed.update(self.other.sync(input_path, source_id=source["source_id"], mode="snapshot"))
                raise

        with patch.object(self.index, "transaction", side_effect=update_after_rollback):
            with self.assertRaisesRegex(RuntimeError, "Synthetic transaction failure"):
                self.manager.remove(source["source_id"], confirm=True)
        current = self.manager._record(source["source_id"])
        self.assertEqual(changed["version_id"], current["version_id"])
        self.assertTrue(Path(changed["snapshot_path"]).is_dir())
        self.assertTrue(Path(source["snapshot_path"]).is_dir())
        saved = Path(changed["snapshot_path"]) / "临时栏目" / "A-1.json"
        self.assertIn("new-after-rollback", saved.read_text(encoding="utf-8"))

    def test_removal_does_not_publish_inside_an_outer_transaction_that_can_roll_back(self):
        source = self.manager.sync(package(self.base / "outer-transaction"), mode="snapshot")
        with self.index.transaction():
            with self.assertRaisesRegex(ValueError, "outside another index transaction"):
                self.manager.remove(source["source_id"], confirm=True)
        self.assertEqual(source["snapshot_path"], self.manager._record(source["source_id"])["snapshot_path"])
        self.assertTrue(Path(source["snapshot_path"]).is_dir())


class WikiLifecycleTests(IsolatedLifecycleTests):
    def setUp(self):
        super().setUp()
        with BookmarkIndex(self.db) as index:
            self.sid = SourceManager(index).sync(package(self.base / "package"), mode="snapshot")["source_id"]
        self.sessions = ResearchSessions(self.base / "research", settings=self.settings,
                                         engine=Mock(), db_path=self.db)
        self.rid = self.sessions.start("Saved bookmarks", [{"id": "q1", "question": "What is saved?"}],
                                       source_ids=[self.sid])["research_id"]
        self.source = self.sessions.import_evidence(self.rid, "import", "q1", "https://example.test/one",
            "One bookmark is saved.", {"kind": "local_document", "provider": "tests"})["sources"][0]
        self.sessions.record(self.rid, {"kind": "source_review", "source_id": "s1", "verdict": "accepted",
                                        "text": "Checked the saved package."})
        self.cid = self.sessions.record(self.rid, {"kind": "claim", "question_id": "q1",
            "statement": "One bookmark is saved.", "citations": [
                {"source_id": "s1", "quote": "One bookmark is saved."}]})["recorded"]["id"]
        self.store = WikiStore(self.base / "wiki", settings=self.settings, research_sessions=self.sessions)
        self.store.write("saved", {"title": "Saved bookmarks", "kind": "topic", "sections": [
            {"heading": "Stored", "text": "One bookmark is saved.",
             "claims": [{"research_id": self.rid, "claim_id": self.cid}]}], "links": [],
            "review": {"method": "model", "reviewer": "tests", "note": "Original review."}}, "Initial page")

    def test_deleted_input_requires_review_and_cannot_be_acknowledged_current(self):
        with BookmarkIndex(self.db) as index:
            SourceManager(index).remove(self.sid, confirm=True)
        current = self.store.get("saved")
        self.assertEqual("needs_review", current["validation"]["status"])
        self.assertIn("source_input_unavailable", [issue["code"] for issue in current["validation"]["issues"]])
        self.store.acknowledge("saved", "The input could not be resolved.")
        self.assertEqual("needs_review", self.store.get("saved")["validation"]["status"])

    def test_acknowledge_cannot_replace_changed_evidence_hashes(self):
        path = self.sessions._path(self.rid) / self.source["response_file"]
        response = json.loads(path.read_text(encoding="utf-8"))
        response["text"] = "Modified after publication."
        path.write_text(json.dumps(response), encoding="utf-8")
        self.assertEqual("stale", self.store.get("saved")["validation"]["status"])
        with self.assertRaisesRegex(ValueError, "invalid evidence"):
            self.store.acknowledge("saved", "Only checking input freshness.")
        self.assertEqual(1, self.store.get("saved")["revision"])

    def test_acknowledge_checks_previous_evidence_again_inside_the_research_lock(self):
        path = self.sessions._path(self.rid) / self.source["response_file"]
        original_locks = self.store._research_locks

        @contextmanager
        def change_before_lock(references):
            path.write_text('{"changed_after_get":true}', encoding="utf-8")
            with original_locks(references):
                yield

        with patch.object(self.store, "_research_locks", side_effect=change_before_lock):
            with self.assertRaisesRegex(ValueError, "invalid evidence"):
                self.store.acknowledge("saved", "Only checking input freshness.")
        self.assertEqual(1, self.store.get("saved")["revision"])

    def test_acknowledge_records_the_note_from_this_review(self):
        note = "Checked the current input and its saved evidence today."
        result = self.store.acknowledge("saved", note)
        self.assertEqual(note, result["acknowledged"][0]["note"])
        self.assertEqual(note, self.store.get("saved")["page"]["review"]["note"])


if __name__ == "__main__":
    unittest.main()
