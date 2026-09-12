"""Export lifetimes, source identity, recovery and live synchronization behavior."""

import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
import warnings
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from source_inputs import read_input
from source_manager import SourceManager
from source_watcher import SourceWatcher
from test_bookmark_index import COPY, PRIMARY, TEMP, make_package, read_json, write_json


class SourceManagerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-sources-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "export"
        make_package(self.package)
        self.db = self.root / "data" / "index.sqlite3"
        self.index = BookmarkIndex(self.db)
        self.addCleanup(self.index.close)
        self.now = 1000.0
        self.sources = SourceManager(self.index, clock=lambda: self.now)

    def archive(self, wrapper="导出包/"):
        path = self.root / "export.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for file in sorted(self.package.rglob("*")):
                if file.is_file():
                    archive.write(file, wrapper + file.relative_to(self.package).as_posix())
        return path

    def change_note(self, note="updated"):
        doc = read_json(self.package, TEMP)
        doc["items"][0]["children"][0]["note"] = note
        write_json(self.package, TEMP, doc)

    def remove_temporary(self):
        (self.package / TEMP).unlink()
        canvas = read_json(self.package, "Demo.canvas")
        canvas["nodes"] = [node for node in canvas["nodes"] if node["id"] != "temp-section-A-1"]
        canvas["edges"] = [edge for edge in canvas["edges"] if edge["toNode"] != "temp-section-A-1"]
        write_json(self.package, "Demo.canvas", canvas)

    def revisions(self):
        return {row["item_id"]: (row["pk"], row["revision"]) for row in self.index.connection.execute("SELECT * FROM items")}

    def test_directory_snapshot_survives_original_deletion_and_reopen(self):
        original = read_input(self.package)["hashes"]
        report = self.sources.sync(self.package, "study")
        self.assertEqual(report["mode"], "snapshot")
        self.assertEqual(read_input(self.package)["hashes"], original)
        self.assertEqual(read_input(report["snapshot_path"])["hashes"], original)
        shutil.rmtree(self.package)
        with BookmarkIndex(self.db) as reopened:
            sources = SourceManager(reopened)
            self.assertEqual(sources.refresh("study")["state"], "snapshot")
            self.assertEqual(reopened.search("study")["total"], 5)
            status = sources.status("study")["source"]
            self.assertFalse(status["input_exists"])
            self.assertTrue(status["snapshot_exists"])

    def test_zip_wrapper_and_unwrapped_packages_keep_all_files_and_raw_bytes(self):
        original = read_input(self.package)["hashes"]
        for wrapper in ("", "中文导出/"):
            path = self.archive(wrapper)
            report = self.sources.sync(path, "study")
            self.assertEqual(report["counts"]["bookmarks"], 5)
            self.assertEqual(read_input(report["snapshot_path"])["hashes"], original)
            path.unlink()
            self.assertEqual(self.sources.refresh("study")["state"], "snapshot")
        self.assertEqual(self.sources.history("study")["total"], 1)

    def test_repeated_import_preserves_ids_hash_skips_and_one_version(self):
        first = self.sources.sync(self.package)
        before = self.revisions()
        again = self.sources.sync(self.package)
        self.assertEqual(again["source_id"], first["source_id"])
        self.assertEqual(again["changed_files"], 0)
        self.assertEqual(again["skipped_files"], 4)
        self.assertEqual(self.revisions(), before)
        self.assertEqual(self.sources.history(first["source_id"])["total"], 1)

    def test_moved_export_reuses_explicit_identity_and_remembers_both_paths(self):
        first = self.sources.sync(self.package)
        moved = self.root / "next-date"
        shutil.copytree(self.package, moved)
        self.sources.sync(moved, first["source_id"])
        self.assertEqual(self.sources.sync(self.package)["source_id"], first["source_id"])
        self.assertEqual(set(self.sources.status(first["source_id"])["source"]["aliases"]), {str(self.package.resolve()), str(moved.resolve())})
        self.assertEqual(len(self.sources.status()["sources"]), 1)

    def test_identical_titles_urls_and_section_ids_do_not_merge_distinct_canvases(self):
        original = self.sources.sync(self.package)
        copied = self.root / "different-canvas"
        shutil.copytree(self.package, copied)
        second = self.sources.sync(copied)
        self.assertNotEqual(second["source_id"], original["source_id"])
        self.sources.sync(copied, original["source_id"])
        with self.assertRaisesRegex(ValueError, "Multiple sources"):
            self.sources.sync(copied)

    def test_single_temporary_card_updates_known_path_without_losing_other_cards(self):
        first = self.sources.sync(self.package, "study")
        self.change_note()
        card = self.root / "downloaded-card.json"
        shutil.copyfile(self.package / TEMP, card)
        report = self.sources.sync(card, "study")
        self.assertEqual(report["items_updated"], 1)
        self.assertEqual(report["counts"]["bookmarks"], 5)
        self.assertEqual(self.index.search("study", group_id="group-one", targets=["updated"])["total"], 1)
        self.assertIn(PRIMARY, report["retained_missing_files"])
        self.assertNotEqual(report["version_id"], first["version_id"])
        self.assertEqual(self.sources.history("study")["total"], 2)
        with self.assertRaisesRegex(ValueError, "partial"):
            self.sources.sync(card, "study", completeness="complete")
        with self.assertRaisesRegex(ValueError, "directory"):
            self.sources.sync(card, "study", mode="live")

    def test_single_permanent_primary_and_copy_keep_shared_tree_semantics(self):
        self.sources.sync(self.package, "study")
        card = self.root / "permanent.json"
        doc = read_json(self.package, PRIMARY)
        doc["identityMap"][0]["note"] = "New primary note"
        card.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self.sources.sync(card, "study")
        self.assertEqual(self.index.search("study", section="B", targets=["New primary note"])["total"], 1)
        anchor = self.root / "anchor.json"
        shutil.copyfile(self.package / COPY, anchor)
        self.sources.sync(anchor, "study")
        self.assertEqual(self.index.search("study", section="B")["total"], 3)
        self.assertEqual(self.index.status("study")["bookmarks"], 5)

    def test_new_single_card_and_single_card_zip_do_not_require_package_folders(self):
        card = self.root / "only-card.json"
        shutil.copyfile(self.package / TEMP, card)
        report = self.sources.sync(card, "card")
        self.assertEqual(report["counts"]["bookmarks"], 2)
        archive = self.root / "card.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.write(card, "download/only-card.json")
        self.assertEqual(self.sources.sync(archive, "card")["changed_files"], 0)

    def test_merged_snapshot_rebuilds_without_any_previous_export_or_database(self):
        self.sources.sync(self.package, "study")
        self.change_note()
        card = self.root / "one.json"
        shutil.copyfile(self.package / TEMP, card)
        snapshot = self.sources.sync(card, "study")["snapshot_path"]
        shutil.rmtree(self.package)
        card.unlink()
        with BookmarkIndex(self.root / "recovered.sqlite3") as index:
            result = SourceManager(index).sync(snapshot, "study", completeness="complete")
            self.assertEqual(result["counts"]["bookmarks"], 5)
            self.assertEqual(index.search("study", group_id="group-one", targets=["updated"])["total"], 1)

    def test_partial_rename_snapshot_recovers_earlier_layout_bindings(self):
        self.sources.sync(self.package, "study")
        partial = self.root / "partial"
        new_name = "临时栏目/renamed.json"
        write_json(partial, new_name, read_json(self.package, TEMP))
        report = self.sources.sync(partial, "study")
        self.assertTrue(report["warnings"])
        with BookmarkIndex(self.root / "restored.sqlite3") as restored:
            SourceManager(restored).sync(report["snapshot_path"], "study", completeness="complete")
            self.assertEqual(restored.search("study", group_id="group-one")["total"], 2)
            self.assertEqual(restored.context("study", section="A-1")["sections"][0]["file_path"], new_name)

    def test_invalid_export_rolls_back_items_registration_and_snapshot_pointer(self):
        self.sources.sync(self.package, "study")
        before = self.sources.status("study")
        revisions = self.revisions()
        self.change_note()
        (self.package / PRIMARY).write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.sources.sync(self.package, "study")
        self.assertEqual(self.revisions(), revisions)
        self.assertEqual(self.sources.status("study"), before)
        self.assertEqual(self.sources.history("study")["total"], 1)

    def test_snapshot_tampering_cannot_be_reimported_or_reused_for_partial_update(self):
        report = self.sources.sync(self.package, "study")
        saved = Path(report["snapshot_path"])
        (saved / PRIMARY).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.sources.sync(saved, "study")
        card = self.root / "one.json"
        shutil.copyfile(self.package / TEMP, card)
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            self.sources.sync(card, "study")
        self.assertEqual(self.index.status("study")["bookmarks"], 5)

    def test_zip_rejects_traversal_symlinks_duplicates_multiple_roots_and_oversize(self):
        cases = [([("../outside.json", b"{}")], "Unsafe"),
                 ([("/absolute.json", b"{}")], "Unsafe"),
                 ([("C:/drive.json", b"{}")], "Unsafe"),
                 ([("a\\file.json", b"{}")], "Unsafe"),
                 ([("a/" + TEMP, b"{}"), ("b/" + TEMP, b"{}")], "multiple package roots")]
        for entries, message in cases:
            archive = self.root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as output:
                for name, raw in entries:
                    output.writestr(name, raw)
            with self.assertRaisesRegex(ValueError, message):
                self.sources.sync(archive)
        archive = self.root / "link.zip"
        with zipfile.ZipFile(archive, "w") as output:
            entry = zipfile.ZipInfo(TEMP)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(entry, "/etc/passwd")
        with self.assertRaisesRegex(ValueError, "links"):
            self.sources.sync(archive)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr(TEMP, b"{}")
                output.writestr(TEMP, b"{}")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.sources.sync(archive)
        with patch("source_inputs.MAX_TOTAL_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "size limits"):
                self.sources.sync(self.archive())
        self.assertFalse((self.root / "outside.json").exists())
        self.assertEqual(self.sources.status()["sources"], [])

    def test_complete_mirror_removes_files_but_partial_import_retains_them(self):
        self.sources.sync(self.package, "study")
        self.remove_temporary()
        partial = self.sources.sync(self.package, "study")
        self.assertEqual(partial["counts"]["bookmarks"], 5)
        complete = self.sources.sync(self.package, "study", completeness="complete")
        self.assertEqual(complete["counts"]["bookmarks"], 3)
        self.assertIn(TEMP, complete["removed_files"])
        self.assertEqual(complete["retained_missing_files"], [])

    def test_loose_card_mixed_with_package_is_not_silently_omitted(self):
        shutil.copyfile(self.package / TEMP, self.package / "loose-card.json")
        with self.assertRaisesRegex(ValueError, "Loose section"):
            self.sources.sync(self.package)
        with self.assertRaisesRegex(ValueError, "loose card"):
            self.sources.sync(self.archive())
        self.assertEqual(self.sources.status()["sources"], [])

    def test_complete_mirror_rename_preserves_item_identity_and_removes_old_file(self):
        self.sources.sync(self.package, "study", mode="live", completeness="complete")
        before = self.revisions()
        new_name = "临时栏目/new.json"
        (self.package / TEMP).rename(self.package / new_name)
        canvas = read_json(self.package, "Demo.canvas")
        canvas["nodes"][3]["file"] = new_name
        write_json(self.package, "Demo.canvas", canvas)
        report = self.sources.sync(self.package, "study")
        self.assertEqual(self.revisions(), before)
        self.assertEqual(report["counts"]["files"], 4)
        self.assertEqual(self.index.search("study", group_id="group-one")["total"], 2)

    def test_single_card_defaults_to_partial_even_after_a_complete_snapshot(self):
        self.sources.sync(self.package, "study", completeness="complete")
        report = self.sources.sync(self.package / TEMP, "study")
        self.assertEqual(report["completeness"], "partial")
        self.assertEqual(report["counts"]["bookmarks"], 5)

    def test_complete_mirror_can_remove_layout_without_removing_bookmarks(self):
        self.sources.sync(self.package, "study", completeness="complete")
        (self.package / "Demo.canvas").unlink()
        report = self.sources.sync(self.package, "study")
        self.assertEqual(report["counts"]["bookmarks"], 5)
        self.assertEqual(report["counts"]["nodes"], 0)
        self.assertEqual(report["counts"]["edges"], 0)
        self.assertEqual(report["counts"]["memberships"], 0)

    def test_complete_directory_with_dangling_references_does_not_delete_saved_items(self):
        self.sources.sync(self.package, "study", mode="live", completeness="complete")
        (self.package / TEMP).unlink()
        self.sources.refresh("study")
        self.now += 6
        self.assertEqual(self.sources.refresh("study")["state"], "error")
        self.assertEqual(self.index.status("study")["bookmarks"], 5)

    def test_live_query_checks_changes_and_reuses_unchanged_rows_after_reopen(self):
        self.sources.sync(self.package, "study", mode="live")
        before = self.revisions()
        self.change_note()
        with BookmarkIndex(self.db) as reopened:
            update = SourceManager(reopened).refresh("study")
            self.assertEqual(update["items_updated"], 1)
            self.assertEqual(reopened.search("study", targets=["updated"])["total"], 1)
        after = self.revisions()
        self.assertEqual(after["bookmark-alpha"], before["bookmark-alpha"])
        self.assertEqual(after["temp-one"][0], before["temp-one"][0])

    def test_deletion_grace_preserves_transient_missing_files_and_then_reconciles(self):
        self.sources.sync(self.package, "study", mode="live", completeness="complete")
        self.remove_temporary()
        pending = self.sources.refresh("study")
        self.assertEqual(pending["state"], "pending")
        self.assertIn(TEMP, pending["pending_files"])
        self.now += 4.9
        self.assertEqual(self.sources.refresh("study")["state"], "pending")
        self.assertEqual(self.index.status("study")["bookmarks"], 5)
        self.now += .2
        self.assertEqual(self.sources.refresh("study")["state"], "current")
        self.assertEqual(self.index.status("study")["bookmarks"], 3)

    def test_disappearing_root_empty_directory_and_invalid_files_keep_last_index(self):
        self.sources.sync(self.package, "study", mode="live", completeness="complete")
        moved = self.root / "temporarily-moved"
        self.package.rename(moved)
        self.assertEqual(self.sources.refresh("study")["state"], "unavailable")
        self.package.mkdir()
        self.now += 60
        self.assertEqual(self.sources.refresh("study")["state"], "unavailable")
        self.package.rmdir()
        moved.rename(self.package)
        (self.package / TEMP).write_text("{broken", encoding="utf-8")
        self.assertEqual(self.sources.refresh("study")["state"], "error")
        self.assertEqual(self.index.status("study")["bookmarks"], 5)

    def test_git_lock_defers_updates_and_releases_without_a_git_command(self):
        metadata = self.root / ".git"
        metadata.mkdir()
        report = self.sources.sync(self.package, "study")
        self.assertEqual(report["mode"], "live")
        self.change_note()
        (metadata / "index.lock").touch()
        self.assertEqual(self.sources.refresh("study")["state"], "pending")
        self.assertEqual(self.index.search("study", targets=["updated"])["total"], 0)
        (metadata / "index.lock").unlink()
        self.assertEqual(self.sources.refresh("study")["items_updated"], 1)

    def test_live_change_during_import_is_not_published(self):
        self.sources.sync(self.package, "study", mode="live")
        self.change_note("first")
        real_sync = self.index.sync
        def racing(*args, **kwargs):
            result = real_sync(*args, **kwargs)
            self.change_note("second")
            return result
        with patch.object(self.index, "sync", side_effect=racing):
            result = self.sources.refresh("study")
        self.assertEqual(result["state"], "error")
        self.assertEqual(self.index.search("study", targets=["first", "second"])["total"], 0)
        self.assertEqual(self.sources.history("study")["total"], 1)
        self.assertEqual(self.sources.refresh("study")["items_updated"], 1)

    def test_legacy_index_upgrades_without_losing_source_ids_or_rows(self):
        self.index.sync(self.package, "legacy")
        before = self.revisions()
        self.assertTrue(self.sources.status("legacy")["source"]["legacy"])
        report = self.sources.sync(self.package)
        self.assertEqual(report["source_id"], "legacy")
        self.assertEqual(report["mode"], "live")
        self.assertEqual(self.revisions(), before)
        self.assertEqual(report["changed_files"], 0)

    def test_legacy_partial_recovery_records_loss_of_original_whitespace(self):
        self.index.sync(self.package, "legacy")
        card = self.root / "one.json"
        shutil.copyfile(self.package / TEMP, card)
        shutil.rmtree(self.package)
        report = self.sources.sync(card, "legacy", mode="snapshot")
        self.assertTrue(any("Recovered legacy JSON" in warning for warning in report["warnings"]))
        with BookmarkIndex(self.root / "recovered.sqlite3") as recovered:
            SourceManager(recovered).sync(report["snapshot_path"], "legacy", completeness="complete")
            self.assertEqual(recovered.search("legacy")["total"], 5)
            self.assertEqual(recovered.search("legacy", group_id="group-one")["total"], 2)

    def test_legacy_move_remembers_the_original_path_without_prior_migration(self):
        self.index.sync(self.package, "legacy")
        moved = self.root / "moved"
        shutil.copytree(self.package, moved)
        self.sources.sync(moved, "legacy", mode="snapshot")
        self.assertEqual(self.sources.sync(self.package)["source_id"], "legacy")

    def test_background_watcher_updates_without_queries_and_stops_cleanly(self):
        self.sources.sync(self.package, "study", mode="live")
        events = []
        watcher = SourceWatcher(self.db, interval=.02, debounce=.04, deletion_grace=.08, on_change=events.append).start()
        self.addCleanup(watcher.close)
        self.assertTrue(watcher.ready.wait(3))
        self.change_note("background-only")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if any(event.get("performed") and event["state"] == "current" for event in events):
                break
            time.sleep(.02)
        self.assertEqual(self.index.search("study", targets=["background-only"])["total"], 1)
        self.assertTrue(any(event["state"] == "pending" for event in events))
        self.assertIsNone(watcher.last_error)
        watcher.close()
        self.assertFalse(watcher.status()["running"])

    def test_mcp_reconnection_starts_monitor_for_previously_registered_live_source(self):
        from mcp_server import StdioMcpServer
        self.sources.sync(self.package, "study", mode="live")
        server = StdioMcpServer(self.db)
        self.addCleanup(server.close)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}})
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertTrue(server._source_watcher.ready.wait(3))
        self.change_note("idle-mcp-update")
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if self.index.search("study", targets=["idle-mcp-update"])["total"]:
                break
            time.sleep(.05)
        self.assertEqual(self.index.search("study", targets=["idle-mcp-update"])["total"], 1)
        self.assertIsNone(server._index, "No query or local MCP call should be necessary")

    def test_research_and_wiki_flag_changed_input_without_rewriting_evidence(self):
        from research import ResearchSessions
        from settings import Settings
        from wiki import WikiStore
        self.sources.sync(self.package, "study")
        settings = Settings(self.root / "settings.json")
        research = ResearchSessions(self.root / "research", settings=settings, db_path=self.db)
        rid = research.start("Frozen fixture", [{"id": "q1", "question": "What does the fixture say?"}], source_ids=["study"])["research_id"]
        inventory_path = research.directory / rid / "inventory.json"
        frozen = inventory_path.read_bytes()
        self.assertEqual(research.status(rid)["source_freshness"]["state"], "unchanged")
        quote = "Alpha documents this synthetic fixture."
        evidence = research.import_evidence(rid, operation_id="fixture", question_id="q1",
            url="https://example.test/alpha", text=quote, provenance={"kind": "page", "provider": "synthetic-fixture"})
        sid = evidence["sources"][0]["id"]
        research.record(rid, {"kind": "source_review", "source_id": sid, "verdict": "accepted", "text": "Reviewed synthetic text."})
        claim = research.record(rid, {"kind": "claim", "question_id": "q1", "statement": quote,
            "citations": [{"source_id": sid, "quote": quote}]})["recorded"]["id"]
        wiki = WikiStore(self.root / "wiki", settings=settings, research_sessions=research)
        written = wiki.write("alpha", {"title": "Alpha", "kind": "entity", "sections": [
            {"heading": "Fixture", "text": quote, "claims": [{"research_id": rid, "claim_id": claim}]}],
            "links": [], "review": {"method": "human", "reviewer": "Fixture author", "note": "Synthetic test only."}}, "Create fixture")
        artifacts = {path: Path(path).read_bytes() for path in written["artifacts"].values()}
        self.change_note()
        self.sources.sync(self.package, "study")
        self.assertTrue(research.status(rid)["source_freshness"]["requires_review"])
        self.assertEqual(wiki.get("alpha")["validation"]["status"], "needs_review")
        self.assertEqual(inventory_path.read_bytes(), frozen)
        for path, raw in artifacts.items():
            self.assertEqual(Path(path).read_bytes(), raw)

    def test_new_research_waits_for_complete_source_deletion_to_settle(self):
        from research import ResearchSessions
        from settings import Settings
        self.sources.sync(self.package, "study", mode="live", completeness="complete")
        self.remove_temporary()
        research = ResearchSessions(self.root / "research", settings=Settings(self.root / "settings.json"), db_path=self.db)
        with self.assertRaisesRegex(ValueError, "pending"):
            research.start("Fixture", [{"id": "q1", "question": "Investigate all sources"}], source_ids=["study"])
        self.assertFalse(research.directory.exists())

    def test_cli_snapshot_and_history_work_after_original_is_removed(self):
        cli = Path(__file__).resolve().parents[1] / "src/cli.py"
        def call(*arguments):
            output = subprocess.run([sys.executable, "-B", str(cli), "--db", str(self.db), *arguments],
                                    text=True, capture_output=True, timeout=15)
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr)
            return json.loads(output.stdout)
        report = call("sync", str(self.archive()), "--source-id", "study")
        shutil.rmtree(self.package)
        (self.root / "export.zip").unlink()
        result = call("search", "study")
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["source"]["mode"], "snapshot")
        self.assertEqual(call("history", "study")["versions"][0]["version_id"], report["version_id"])


if __name__ == "__main__":
    unittest.main()
