"""Behavioral tests: package semantics, incremental persistence and isolation."""

import hashlib
import concurrent.futures
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex


PRIMARY = "永久栏目/A书签树（永久栏目）.json"
COPY = "永久栏目/B书签树（永久栏目）.json"
TEMP = "临时栏目/常规链式/A-1 示例.json"


def write_json(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(root, relative):
    return json.loads((root / relative).read_text(encoding="utf-8"))


def make_package(root):
    write_json(root, PRIMARY, {
        "format": "bookmark-canvas-section", "schemaVersion": 3, "sectionType": "permanent",
        "slot": "A", "title": "主树", "descriptionMd": "公司分类", "fileRole": "primary",
        "unknown_header": {"keep": True},
        "identityMap": [{"syncId": "bookmark-alpha", "note": "查询\n中文", "extra": "preserved",
            "tags": [{"color": "purple", "text": "关注"}]}],
        "tree": {"id": "root", "title": "", "children": [{"id": "companies", "parentId": "root",
            "title": "公司", "children": [
                {"id": "bookmark-alpha", "parentId": "companies", "title": "示例公司甲", "url": "https://example.test/alpha", "future": 1},
                {"id": "bookmark-beta", "parentId": "companies", "title": "ExampleBeta", "url": "https://example.test/beta"},
                {"id": "bookmark-literal", "parentId": "companies", "title": "100%_完成\\done", "url": "https://example.test/literal"},
            ]}]},
    })
    write_json(root, COPY, {
        "format": "bookmark-canvas-section", "schemaVersion": 2, "sectionType": "permanent",
        "slot": "B", "copyId": "copy-b", "fileRole": "copy-anchor", "anchorOnly": True,
        "descriptionMd": "视图 B", "inheritFrom": "vault/nested/Original/" + PRIMARY,
    })
    write_json(root, TEMP, {
        "format": "bookmark-canvas-section", "schemaVersion": 2, "sectionType": "temporary",
        "id": "temp-section-A-1", "label": "A-1", "title": "示例", "tempKind": "regular",
        "items": [{"id": "temp-folder", "sectionId": "temp-section-A-1", "type": "folder", "title": "研究", "children": [
            {"id": "temp-one", "sectionId": "temp-section-A-1", "type": "bookmark", "title": "模型资料",
                "url": "https://example.test/alpha", "note": "临时笔记", "noteColor": "blue", "tags": [{"color": "green", "text": "关注"}]},
            {"id": "temp-two", "sectionId": "temp-section-A-1", "type": "bookmark", "title": "100X完成", "url": "https://example.test/other"},
        ]}],
    })
    write_json(root, "Demo.canvas", {
        "nodes": [
            {"id": "permanent-section", "type": "file", "file": "vault/nested/Original/" + PRIMARY, "x": 200, "y": 0, "width": 40, "height": 40},
            {"id": "copy-view", "type": "file", "file": "vault/nested/Original/" + COPY, "x": 250, "y": 0, "width": 40, "height": 40},
            {"id": "group-one", "type": "group", "label": "研究组", "x": 0, "y": 0, "width": 100, "height": 100},
            {"id": "temp-section-A-1", "type": "file", "file": "vault/nested/Original/" + TEMP, "x": 10, "y": 10, "width": 80, "height": 80},
            {"id": "text-overlap", "type": "text", "text": "部分重叠不是成员", "x": 95, "y": 10, "width": 20, "height": 20},
        ],
        "edges": [{"id": "edge-forward", "fromNode": "permanent-section", "toNode": "group-one"},
            {"id": "edge-none", "fromNode": "copy-view", "toNode": "temp-section-A-1", "toEnd": "none"}],
    })


class IndexBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-index-test-")
        self.base = Path(self.temporary.name)
        self.package = self.base / "Package"
        make_package(self.package)
        self.db_path = self.base / "derived" / "index.sqlite3"
        self.index = BookmarkIndex(self.db_path)
        self.index.sync(self.package, "demo")

    def tearDown(self):
        self.index.close()
        self.temporary.cleanup()

    def revisions(self):
        return {row["item_id"]: (row["pk"], row["revision"]) for row in self.index.connection.execute("SELECT * FROM items")}

    def test_complete_inventory_preserves_instances_folders_and_copy_appearances(self):
        before = {path.relative_to(self.package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in self.package.rglob("*") if path.is_file()}
        with patch.object(self.index, "search", side_effect=AssertionError("Inventory must not depend on search limits")):
            inventory = self.index.inventory(["demo"])
        self.assertEqual(inventory["counts"]["unique_urls"], 4)
        self.assertEqual(inventory["counts"]["bookmark_instances"], 5)
        self.assertEqual(inventory["counts"]["folders"], 3)
        self.assertEqual(inventory["counts"]["nodes"], 5)
        self.assertEqual(inventory["counts"]["edges"], 2)
        self.assertEqual(inventory["counts"]["memberships"], 1)
        alpha = next(row for row in inventory["entries"] if row["original_url"].endswith("/alpha"))
        self.assertEqual(len(alpha["instances"]), 2)
        primary, temporary = alpha["instances"]
        self.assertEqual(primary["ancestor_ids"], ["root", "companies"])
        self.assertEqual(primary["metadata"]["extra"], "preserved")
        self.assertEqual({row["label"] for row in primary["appearances"]}, {"A", "B"})
        self.assertEqual({edge["direction"] for view in primary["appearances"] for edge in view["edges"]}, {"forward", "none"})
        self.assertEqual(temporary["appearances"][0]["memberships"][0]["group_id"], "group-one")
        self.assertEqual({row["file_path"]: row["sha256"] for row in inventory["files"]}, before)
        self.assertEqual(before, {path.relative_to(self.package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in self.package.rglob("*") if path.is_file()})
        self.index.refresh("demo")
        self.assertEqual(self.index.inventory(["demo"])["input_version"], inventory["input_version"])

    def test_inventory_keeps_exact_urls_separate_and_stable_across_input_versions(self):
        original = self.index.inventory(["demo"])
        section = read_json(self.package, TEMP)
        section["items"].extend([{"id": "fragment-1", "type": "bookmark", "title": "Anchor", "url": "https://example.test/alpha#one"},
                                  {"id": "local-document", "type": "bookmark", "title": "Local", "url": "file:///notes.pdf"},
                                  {"id": "separator", "type": "bookmark", "title": "Separator", "url": "---"}])
        write_json(self.package, TEMP, section)
        self.index.refresh("demo")
        current = self.index.inventory(["demo"])
        self.assertNotEqual(current["input_version"], original["input_version"])
        self.assertEqual(current["counts"]["unique_urls"], 7)
        self.assertTrue({row["id"] for row in original["entries"]} < {row["id"] for row in current["entries"]})
        by_url = {row["original_url"]: row for row in current["entries"]}
        self.assertNotEqual(by_url["https://example.test/alpha"]["id"], by_url["https://example.test/alpha#one"]["id"])
        self.assertEqual(by_url["https://example.test/alpha"]["retrieval_url"], by_url["https://example.test/alpha#one"]["retrieval_url"])
        self.assertEqual(by_url["file:///notes.pdf"]["url_kind"], "local")
        self.assertIsNone(by_url["---"]["retrieval_url"])
        moved = self.base / "Moved"
        shutil.copytree(self.package, moved)
        self.index.sync(moved, "demo")
        moved_inventory = self.index.inventory(["demo"])
        self.assertEqual(moved_inventory["input_version"], current["input_version"])
        self.assertEqual(moved_inventory["entries"], current["entries"])

    def test_inventory_is_one_consistent_read_during_concurrent_sync(self):
        self.index.connection.execute("PRAGMA journal_mode=WAL")
        initial = self.index.inventory(["demo"])
        reading, committed = threading.Event(), threading.Event()
        original_item_result = self.index._item_result

        def writer():
            if not reading.wait(5):
                raise AssertionError("Reader did not reach its snapshot")
            primary = read_json(self.package, PRIMARY)
            primary["tree"]["children"][0]["children"][0]["title"] = "Changed after snapshot"
            write_json(self.package, PRIMARY, primary)
            with BookmarkIndex(self.db_path) as index:
                index.refresh("demo")
            committed.set()

        def paused_item(row):
            if not reading.is_set():
                reading.set()
                if not committed.wait(5):
                    raise AssertionError("Concurrent writer did not commit")
            return original_item_result(row)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(writer)
            with patch.object(self.index, "_item_result", side_effect=paused_item):
                captured = self.index.inventory(["demo"])
            future.result(timeout=5)
        self.assertEqual(captured, initial)
        current = self.index.inventory(["demo"])
        self.assertNotEqual(current["input_version"], initial["input_version"])
        titles = [item["title"] for row in current["entries"] for item in row["instances"]]
        self.assertIn("Changed after snapshot", titles)

    def test_metadata_copies_context_order_and_literal_batch(self):
        self.assertEqual(self.index.status("demo")["bookmarks"], 5)
        self.assertEqual(self.index.status("demo")["unique_urls"], 4)
        self.assertEqual(self.index.search("demo", section="B")["total"], 3)
        results = self.index.search("demo", targets=["示例公司甲", "%_", "\\done"], limit=1)
        self.assertEqual(results["total"], 2)
        self.assertEqual([target["total"] for target in results["targets"]], [1, 1, 1])
        self.assertEqual(self.index.search("demo", targets=["%"], limit=20)["total"], 1)
        self.assertEqual(self.index.search("demo", targets=["_"], limit=20)["total"], 1)
        self.assertEqual(self.index.search("demo", targets=["' OR 1=1 --"])["total"], 0)
        self.assertEqual(self.index.search("demo", targets=["examplebeta"])["total"], 1)
        self.assertEqual(self.index.search("demo", targets=["查询"])["total"], 1)
        tagged = self.index.search("demo", tags=["关注"])
        self.assertEqual(tagged["total"], 2)
        self.assertEqual(self.index.search("demo", tags=["关注", "missing"])["total"], 0)
        rows = self.index.search("demo", folder_id="companies", limit=2, offset=1)
        self.assertEqual(rows["total"], 3)
        self.assertEqual([row["item_id"] for row in rows["results"]], ["bookmark-beta", "bookmark-literal"])
        context = self.index.context("demo", item_id="bookmark-alpha")
        item = context["items"][0]
        self.assertEqual(item["note_color"], "orange")
        self.assertEqual(item["path"], ["公司"])
        self.assertEqual(item["metadata"]["extra"], "preserved")
        self.assertEqual(item["raw_json"]["future"], 1)
        self.assertEqual([entry["item_id"] for entry in item["ancestors"]], ["root", "companies"])
        self.assertNotIn("tree", context["sections"][0]["raw_json"])
        self.assertTrue(context["sections"][0]["raw_json"]["unknown_header"]["keep"])

    def test_persistent_reopen_hash_skip_and_fts_content(self):
        old = self.revisions()
        self.index.close()
        self.index = BookmarkIndex(self.db_path)
        report = self.index.refresh("demo")
        self.assertEqual(report["changed_files"], 0)
        self.assertEqual(report["skipped_files"], 4)
        self.assertEqual(report["items_updated"], 0)
        self.assertEqual(self.revisions(), old)
        self.assertEqual(self.index.connection.execute("SELECT count(*) FROM items_fts WHERE items_fts MATCH 'ExampleBeta'").fetchone()[0], 1)

    def test_note_delta_preserves_row_ids_and_other_records(self):
        before = self.revisions()
        primary = read_json(self.package, PRIMARY)
        primary["identityMap"][0]["note"] = "ChangedMetadataOnly"
        write_json(self.package, PRIMARY, primary)
        summary = self.index.refresh("demo")
        self.assertEqual((summary["changed_files"], summary["skipped_files"]), (1, 3))
        self.assertEqual((summary["items_inserted"], summary["items_updated"], summary["items_deleted"]), (0, 1, 0))
        after = self.revisions()
        for item_id, (pk, revision) in before.items():
            self.assertEqual(after[item_id][0], pk)
            self.assertEqual(after[item_id][1], revision + (item_id == "bookmark-alpha"))
        self.assertEqual(self.index.search("demo", targets=["ChangedMetadataOnly"])["total"], 1)
        self.assertEqual(self.index.connection.execute("SELECT count(*) FROM items_fts WHERE items_fts MATCH 'ChangedMetadataOnly'").fetchone()[0], 1)
        full = json.loads(self.index.connection.execute("SELECT raw_json FROM files WHERE source_id='demo' AND file_path=?", (PRIMARY,)).fetchone()[0])
        self.assertTrue(full["tree"]["children"][0]["children"])

    def test_canvas_movement_updates_geometry_without_rewriting_items(self):
        self.assertEqual(self.index.search("demo", group_id="研究组")["total"], 2)
        context = self.index.context("demo", group_id="group-one")
        self.assertEqual([m["node_id"] for m in context["memberships"]], ["temp-section-A-1"])
        before = self.revisions()
        canvas = read_json(self.package, "Demo.canvas")
        canvas["nodes"][2]["x"] = 1000
        write_json(self.package, "Demo.canvas", canvas)
        report = self.index.refresh("demo")
        self.assertEqual(report["changed_files"], 1)
        self.assertEqual(report["items_updated"], 0)
        self.assertEqual(self.revisions(), before)
        self.assertEqual(self.index.search("demo", group_id="group-one")["total"], 0)
        self.assertEqual(self.index.context("demo")["memberships"], [])

    def test_nested_groups_and_explicit_arrow_ends(self):
        canvas = read_json(self.package, "Demo.canvas")
        canvas["nodes"].append({"id": "group-inner", "type": "group", "label": "内层",
            "x": 5, "y": 5, "width": 90, "height": 90})
        canvas["edges"][0]["fromEnd"] = "arrow"
        canvas["edges"][1]["fromEnd"] = "arrow"
        write_json(self.package, "Demo.canvas", canvas)
        self.index.refresh("demo")
        context = self.index.context("demo", group_id="group-one")
        self.assertEqual([edge["direction"] for edge in context["edges"]], ["both", "reverse"])
        self.assertEqual(self.index.search("demo", group_id="group-inner")["total"], 2)
        self.assertEqual(self.index.search("demo", group_id="group-one")["total"], 2)
        nodes = {node["node_id"] for node in context["nodes"] + context["related_nodes"]}
        for edge in context["edges"]:
            self.assertIn(edge["from_node"], nodes)
            self.assertIn(edge["to_node"], nodes)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.index.context("demo", group_id="group-one", item_id="bookmark-alpha")

    def test_bad_json_does_not_publish_any_changed_file(self):
        before = self.revisions()
        last_sync = self.index.status("demo")["last_sync"]
        primary = read_json(self.package, PRIMARY)
        primary["identityMap"][0]["note"] = "MustNotCommit"
        write_json(self.package, PRIMARY, primary)
        (self.package / TEMP).write_text('{"broken":', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid package file"):
            self.index.refresh("demo")
        self.assertEqual(self.revisions(), before)
        self.assertEqual(self.index.status("demo")["last_sync"], last_sync)
        self.assertEqual(self.index.search("demo", targets=["MustNotCommit"])["total"], 0)

    def test_transaction_rolls_back_on_late_inheritance_validation(self):
        before = self.revisions()
        last_sync = self.index.status("demo")["last_sync"]
        primary = read_json(self.package, PRIMARY)
        primary["identityMap"][0]["note"] = "MustRollBack"
        write_json(self.package, PRIMARY, primary)
        anchor = read_json(self.package, COPY)
        anchor["inheritFrom"] = "vault/Original/" + COPY
        write_json(self.package, COPY, anchor)
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.index.refresh("demo")
        self.assertEqual(self.revisions(), before)
        self.assertEqual(self.index.status("demo")["last_sync"], last_sync)
        self.assertEqual(self.index.search("demo", targets=["MustRollBack"])["total"], 0)

    def test_partial_export_retains_missing_files_but_removes_deleted_items(self):
        partial = self.base / "Partial"
        temp = read_json(self.package, TEMP)
        temp["items"][0]["children"].pop()
        write_json(partial, TEMP, temp)
        summary = self.index.sync(partial, "demo")
        self.assertEqual(summary["items_deleted"], 1)
        self.assertEqual(set(summary["retained_missing_files"]), {PRIMARY, COPY, "Demo.canvas"})
        self.assertEqual(self.index.status("demo")["bookmarks"], 4)
        self.assertEqual(self.index.search("demo", section="A")["total"], 3)
        self.assertEqual(self.index.search("demo", group_id="研究组")["total"], 1)
        self.assertEqual(self.index.refresh("demo")["changed_files"], 0)
        self.assertEqual(self.index.status("demo")["package_path"], str(partial.resolve()))

    def test_source_identity_and_moved_vault_prefix(self):
        moved = self.base / "MovedPackage"
        shutil.copytree(self.package, moved)
        summary = self.index.sync(moved)
        self.assertNotEqual(summary["source_id"], "demo")
        self.assertEqual(self.index.search(summary["source_id"], section="B")["total"], 3)
        summary = self.index.sync(moved, "demo")
        self.assertEqual(summary["items_inserted"], 0)
        self.assertEqual(self.index.status("demo")["package_path"], str(moved.resolve()))

    def test_section_rename_and_restore_preserve_identity_and_canvas_links(self):
        before = self.revisions()
        renamed = "临时栏目/常规链式/改名后的栏目.json"
        for old_path, new_path in ((TEMP, renamed), (renamed, TEMP)):
            (self.package / old_path).rename(self.package / new_path)
            canvas = read_json(self.package, "Demo.canvas")
            canvas["nodes"][3]["file"] = "vault/nested/Original/" + new_path
            write_json(self.package, "Demo.canvas", canvas)
            summary = self.index.refresh("demo")
            self.assertEqual(summary["warnings"], [])
            self.assertEqual(summary["retained_missing_files"], [])
            self.assertEqual(summary["counts"]["files"], 4)
            self.assertEqual(self.revisions(), before)
            context = self.index.context("demo", section="A-1")
            self.assertEqual(context["sections"][0]["file_path"], new_path)
            self.assertEqual([n["file_path"] for n in context["nodes"] if n["node_type"] == "file"], [new_path])
            self.assertEqual(self.index.search("demo", group_id="group-one")["total"], 2)

    def test_section_and_group_select_the_same_card_before_resolving_copies(self):
        canvas = read_json(self.package, "Demo.canvas")
        canvas["nodes"][1].update(x=20, y=20, width=20, height=20)
        write_json(self.package, "Demo.canvas", canvas)
        self.index.refresh("demo")
        self.assertEqual(self.index.search("demo", section="A", group_id="group-one")["total"], 0)
        self.assertEqual(self.index.search("demo", section="B", group_id="group-one")["total"], 3)
        self.assertEqual(self.index.search("demo", group_id="group-one")["total"], 5)
        context = self.index.context("demo", section="B", group_id="group-one")
        self.assertEqual([s["label"] for s in context["sections"]], ["B"])
        self.assertEqual({n["node_id"] for n in context["nodes"]}, {"group-one", "copy-view"})
        referenced_nodes = {n["node_id"] for n in context["nodes"] + context["related_nodes"]}
        for member in context["memberships"]:
            self.assertIn(member["group_id"], referenced_nodes)
            self.assertIn(member["node_id"], referenced_nodes)
        context = self.index.context("demo", item_id="bookmark-alpha", group_id="group-one")
        self.assertEqual([s["label"] for s in context["sections"]], ["B"])
        self.assertEqual({n["node_id"] for n in context["nodes"]}, {"group-one", "copy-view"})

    def test_canvas_entry_rename_replaces_previous_layout(self):
        before = self.revisions()
        for old, new in (("Demo.canvas", "Renamed.canvas"), ("Renamed.canvas", "Demo.canvas")):
            (self.package / old).rename(self.package / new)
            summary = self.index.refresh("demo")
            self.assertEqual(summary["retained_missing_files"], [])
            self.assertEqual(summary["counts"]["files"], 4)
            self.assertEqual(summary["counts"]["nodes"], 5)
            self.assertEqual(summary["counts"]["edges"], 2)
            self.assertEqual(self.index.search("demo", group_id="group-one")["total"], 2)
            self.assertEqual(self.revisions(), before)
        write_json(self.package, "Other.canvas", read_json(self.package, "Demo.canvas"))
        with self.assertRaisesRegex(ValueError, "one .canvas"):
            self.index.refresh("demo")
        self.assertEqual(self.index.status("demo")["counts"]["nodes"], 5)

    def test_partial_rename_retains_known_layout_until_canvas_is_supplied(self):
        partial = self.base / "Partial"
        renamed = "临时栏目/常规链式/改名.json"
        write_json(partial, renamed, read_json(self.package, TEMP))
        summary = self.index.sync(partial, "demo")
        self.assertEqual(self.index.search("demo", group_id="group-one")["total"], 2)
        self.assertTrue(any("Retained canvas" in warning for warning in summary["warnings"]))
        self.assertEqual(self.index.refresh("demo")["items_updated"], 0)
        self.assertEqual(self.index.search("demo", group_id="group-one")["total"], 2)
        # A supplied canvas must use its actual references, even if they are stale.
        write_json(partial, "Demo.canvas", read_json(self.package, "Demo.canvas"))
        self.assertTrue(any("Unresolved canvas" in warning for warning in self.index.refresh("demo")["warnings"]))
        self.assertEqual(self.index.search("demo", group_id="group-one")["total"], 0)
        canvas = read_json(partial, "Demo.canvas")
        canvas["nodes"][3]["file"] = renamed
        write_json(partial, "Demo.canvas", canvas)
        self.assertEqual(self.index.refresh("demo")["warnings"], [])
        self.assertEqual(self.index.search("demo", group_id="group-one")["total"], 2)

    def test_partial_primary_rename_preserves_retained_copy_anchor(self):
        partial = self.base / "Partial"
        renamed = "永久栏目/改名后的主树.json"
        write_json(partial, renamed, read_json(self.package, PRIMARY))
        summary = self.index.sync(partial, "demo")
        self.assertEqual(self.index.search("demo", section="B")["total"], 3)
        self.assertTrue(any("Retained copy-anchor" in warning for warning in summary["warnings"]))
        self.assertEqual(self.index.refresh("demo")["items_updated"], 0)
        self.assertEqual(self.index.search("demo", section="B")["total"], 3)

    def test_database_and_reference_boundaries(self):
        forbidden = self.package / "derived" / "index.sqlite3"
        with self.assertRaisesRegex(ValueError, "outside"):
            BookmarkIndex(forbidden)
        self.assertFalse(forbidden.exists())
        self.assertFalse(forbidden.parent.exists())
        canvas = read_json(self.package, "Demo.canvas")
        canvas["nodes"][0]["file"] = "../outside/" + PRIMARY
        write_json(self.package, "Demo.canvas", canvas)
        with self.assertRaisesRegex(ValueError, "Unsafe vault reference"):
            self.index.refresh("demo")

    def test_external_symlink_is_not_read_and_missing_path_is_error(self):
        original = self.package / TEMP
        outside = self.base / "outside.json"
        original.rename(outside)
        original.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "external symlink"):
            self.index.refresh("demo")
        shutil.rmtree(self.package)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.index.refresh("demo")
        self.assertEqual(self.index.search("demo")["total"], 5)


class PortablePackageTests(unittest.TestCase):
    def test_empty_index_and_queries_do_not_change_supplied_package(self):
        with tempfile.TemporaryDirectory(prefix="bookmark-portable-test-") as temp:
            package = Path(temp) / "UserSuppliedPackage"
            make_package(package)
            paths = sorted(path for path in package.rglob("*") if path.is_file())
            before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
            self.assertFalse((package / "AGENTS.md").exists())
            with BookmarkIndex(Path(temp) / "index.sqlite3") as index:
                self.assertEqual(index.status()["sources"], [])
                index.sync(package, "user-chosen-source")
                index.search("user-chosen-source", section="B")
                index.context("user-chosen-source", item_id="bookmark-alpha")
                again = index.refresh("user-chosen-source")
                self.assertEqual((again["changed_files"], again["items_updated"]), (0, 0))
            after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
