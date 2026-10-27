"""Bilingual Canvas protocol directory compatibility and regression tests."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex
from package_paths import (
    PERMANENT_DIRS,
    TEMPORARY_DIRS,
    PROTOCOL_DIRS,
    dir_matches_section_type,
    is_package_dir,
    protocol_dirs_for_type,
    resolve_protocol_reference,
    section_type_for_dir,
)
from settings import Settings
from source_inputs import read_input
from source_manager import SourceManager


class PackagePathsTests(unittest.TestCase):
    def test_protocol_dir_constants(self):
        self.assertIn("永久栏目", PERMANENT_DIRS)
        self.assertIn("Permanent", PERMANENT_DIRS)
        self.assertIn("临时栏目", TEMPORARY_DIRS)
        self.assertIn("Temporary", TEMPORARY_DIRS)
        for d in ("永久栏目", "临时栏目", "Permanent", "Temporary"):
            self.assertIn(d, PROTOCOL_DIRS)

    def test_section_type_mapping(self):
        self.assertEqual(section_type_for_dir("永久栏目"), "permanent")
        self.assertEqual(section_type_for_dir("Permanent"), "permanent")
        self.assertEqual(section_type_for_dir("临时栏目"), "temporary")
        self.assertEqual(section_type_for_dir("Temporary"), "temporary")
        self.assertIsNone(section_type_for_dir("Unknown"))

        self.assertEqual(set(protocol_dirs_for_type("permanent")), {"永久栏目", "Permanent"})
        self.assertEqual(set(protocol_dirs_for_type("temporary")), {"临时栏目", "Temporary"})
        self.assertEqual(protocol_dirs_for_type("other"), ())

    def test_dir_matches_section_type(self):
        self.assertTrue(dir_matches_section_type("永久栏目/A.json", "permanent"))
        self.assertTrue(dir_matches_section_type("Permanent/A.json", "permanent"))
        self.assertTrue(dir_matches_section_type("临时栏目/常规链式/A-1.json", "temporary"))
        self.assertTrue(dir_matches_section_type("Temporary/General Chain/A-1.json", "temporary"))
        self.assertTrue(dir_matches_section_type("Temporary/Special temporary/Add.json", "temporary"))

        # Mismatches
        self.assertFalse(dir_matches_section_type("Permanent/A.json", "temporary"))
        self.assertFalse(dir_matches_section_type("永久栏目/A.json", "temporary"))
        self.assertFalse(dir_matches_section_type("Temporary/A.json", "permanent"))
        self.assertFalse(dir_matches_section_type("临时栏目/A.json", "permanent"))
        self.assertFalse(dir_matches_section_type("", "permanent"))

    def test_resolve_protocol_reference(self):
        # Direct references
        self.assertEqual(resolve_protocol_reference("Permanent/A.json"), "Permanent/A.json")
        self.assertEqual(resolve_protocol_reference("永久栏目/A.json"), "永久栏目/A.json")
        self.assertEqual(
            resolve_protocol_reference("Temporary/General Chain/A-1.json"),
            "Temporary/General Chain/A-1.json",
        )
        self.assertEqual(
            resolve_protocol_reference("临时栏目/常规链式/A-1.json"),
            "临时栏目/常规链式/A-1.json",
        )

        # Vault-prefixed references
        self.assertEqual(
            resolve_protocol_reference("my-vault/subfolder/Permanent/A.json"),
            "Permanent/A.json",
        )
        self.assertEqual(
            resolve_protocol_reference("test1/bookmark-canvas/Permanent/A-PermanentBookmarks.json"),
            "Permanent/A-PermanentBookmarks.json",
        )
        self.assertEqual(
            resolve_protocol_reference("test1/bookmark-canvas/Temporary/Special temporary/存档.json"),
            "Temporary/Special temporary/存档.json",
        )
        self.assertEqual(
            resolve_protocol_reference("Permanent/collection/临时栏目/常规链式/Topic/T-1.json"),
            "临时栏目/常规链式/Topic/T-1.json",
        )
        self.assertEqual(
            resolve_protocol_reference("vault/Temporary/General Chain/Topic/T-1.json"),
            "Temporary/General Chain/Topic/T-1.json",
        )

        # Errors
        with self.assertRaises(ValueError):
            resolve_protocol_reference("")
        with self.assertRaises(ValueError):
            resolve_protocol_reference("Permanent/A.txt")
        with self.assertRaises(ValueError):
            resolve_protocol_reference("../outside/Permanent/A.json")
        with self.assertRaises(ValueError):
            resolve_protocol_reference("/Permanent/A.json")
        with self.assertRaises(ValueError):
            resolve_protocol_reference("https://example.com/Permanent/A.json")
        with self.assertRaises(ValueError):
            resolve_protocol_reference("random/folder/A.json")


class BilingualCanvasIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="bilingual-test-")
        self.base = Path(self.temp_dir.name)
        self.db_path = self.base / "index.db"
        self.index = BookmarkIndex(self.db_path)
        self.manager = SourceManager(self.index)

    def tearDown(self):
        self.index.close()
        self.temp_dir.cleanup()

    def _create_minimal_package(self, package_dir, is_english=True):
        package_dir.mkdir(parents=True, exist_ok=True)
        perm_name = "Permanent" if is_english else "永久栏目"
        temp_name = "Temporary" if is_english else "临时栏目"
        sub_name = "General Chain" if is_english else "常规链式"

        (package_dir / perm_name).mkdir(parents=True, exist_ok=True)
        (package_dir / temp_name / sub_name).mkdir(parents=True, exist_ok=True)

        perm_data = {
            "format": "bookmark-canvas-section",
            "schemaVersion": 3,
            "sectionType": "permanent",
            "slot": "A",
            "title": "Main Permanent",
            "tree": {
                "id": "syncId_root",
                "title": "Bookmarks",
                "folderType": "root",
                "children": [
                    {
                        "id": "syncId_bm1",
                        "title": "Example One",
                        "url": "https://example.com/one",
                        "dateAdded": 1700000000000,
                    }
                ],
            },
        }
        (package_dir / perm_name / "A.json").write_text(json.dumps(perm_data), encoding="utf-8")

        temp_data = {
            "format": "bookmark-canvas-section",
            "schemaVersion": 2,
            "sectionType": "temporary",
            "id": "temp-1",
            "label": "T-1",
            "title": "Temporary Research",
            "items": [
                {
                    "id": "item_1",
                    "type": "bookmark",
                    "title": "Example Two",
                    "url": "https://example.com/two",
                    "sectionId": "temp-1",
                }
            ],
        }
        (package_dir / temp_name / sub_name / "T-1.json").write_text(
            json.dumps(temp_data), encoding="utf-8"
        )

        canvas_name = "test.canvas"
        canvas_data = {
            "nodes": [
                {
                    "id": "node_perm",
                    "type": "file",
                    "file": f"{perm_name}/A.json",
                    "x": 0,
                    "y": 0,
                    "width": 200,
                    "height": 100,
                },
                {
                    "id": "node_temp",
                    "type": "file",
                    "file": f"{temp_name}/{sub_name}/T-1.json",
                    "x": 300,
                    "y": 0,
                    "width": 200,
                    "height": 100,
                },
            ],
            "edges": [
                {
                    "id": "edge_1",
                    "fromNode": "node_perm",
                    "toNode": "node_temp",
                    "label": "investigate",
                }
            ],
        }
        (package_dir / canvas_name).write_text(json.dumps(canvas_data), encoding="utf-8")

    def test_english_package_directory_ingestion(self):
        pkg = self.base / "en_pkg"
        self._create_minimal_package(pkg, is_english=True)

        res = self.manager.sync(str(pkg), mode="snapshot")
        self.assertEqual(res["state"], "snapshot")

        sections = self.index.connection.execute("SELECT * FROM sections").fetchall()
        self.assertEqual(len(sections), 2)
        paths = {s["file_path"] for s in sections}
        self.assertIn("Permanent/A.json", paths)
        self.assertIn("Temporary/General Chain/T-1.json", paths)

        items = self.index.connection.execute("SELECT * FROM items WHERE item_type='bookmark'").fetchall()
        self.assertEqual(len(items), 2)

        nodes = self.index.connection.execute("SELECT * FROM nodes").fetchall()
        self.assertEqual(len(nodes), 2)
        edges = self.index.connection.execute("SELECT * FROM edges").fetchall()
        self.assertEqual(len(edges), 1)

    def test_english_package_zip_ingestion(self):
        pkg = self.base / "en_pkg_for_zip"
        self._create_minimal_package(pkg, is_english=True)

        zip_path = self.base / "en_pkg.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for f in pkg.rglob("*"):
                if f.is_file():
                    # Place inside a nested folder in ZIP
                    zf.write(f, arcname="wrapped_folder/" + f.relative_to(pkg).as_posix())

        res = self.manager.sync(str(zip_path), mode="snapshot")
        self.assertEqual(res["state"], "snapshot")

        sections = self.index.connection.execute("SELECT * FROM sections").fetchall()
        self.assertEqual(len(sections), 2)
        nodes = self.index.connection.execute("SELECT * FROM nodes").fetchall()
        self.assertEqual(len(nodes), 2)

    def test_copy_anchor_with_english_inherit_from(self):
        pkg = self.base / "en_copy_pkg"
        self._create_minimal_package(pkg, is_english=True)

        # Add copy section B
        copy_data = {
            "format": "bookmark-canvas-section",
            "schemaVersion": 2,
            "sectionType": "permanent",
            "slot": "B",
            "title": "Copy B",
            "fileRole": "copy-anchor",
            "inheritFrom": "Permanent/A.json",
            "copyId": "b_anchor",
        }
        (pkg / "Permanent" / "B.json").write_text(json.dumps(copy_data), encoding="utf-8")

        res = self.manager.sync(str(pkg), mode="snapshot")
        self.assertEqual(res["state"], "snapshot")

        sections = self.index.connection.execute("SELECT * FROM sections").fetchall()
        self.assertEqual(len(sections), 3)

        b_section = [s for s in sections if s["slot"] == "B"][0]
        self.assertEqual(b_section["is_anchor"], 1)
        self.assertEqual(b_section["inherit_path"], "Permanent/A.json")

    def test_package_directory_guards(self):
        pkg = self.base / "guard_pkg"
        self._create_minimal_package(pkg, is_english=True)

        # BookmarkIndex should refuse to place a DB inside an English package dir
        inside_db = pkg / "Permanent" / "sub.db"
        with self.assertRaises(ValueError):
            BookmarkIndex(inside_db)

        # Settings.external_path should refuse inside English package
        with self.assertRaises(ValueError):
            Settings.external_path(str(pkg / "Permanent"), "data_dir")

    def test_resync_and_item_update(self):
        pkg = self.base / "resync_pkg"
        self._create_minimal_package(pkg, is_english=True)

        res1 = self.manager.sync(str(pkg), mode="snapshot")
        source_id = res1["source_id"]

        # Modify item in T-1
        temp_file = pkg / "Temporary" / "General Chain" / "T-1.json"
        data = json.loads(temp_file.read_text(encoding="utf-8"))
        data["items"][0]["title"] = "Updated Title"
        temp_file.write_text(json.dumps(data), encoding="utf-8")

        res2 = self.manager.sync(str(pkg), source_id=source_id, mode="snapshot")
        self.assertEqual(res2["source_id"], source_id)

        item = self.index.connection.execute(
            "SELECT title, revision FROM items WHERE item_id='item_1'"
        ).fetchone()
        self.assertEqual(item["title"], "Updated Title")
        self.assertEqual(item["revision"], 2)

    def test_mixed_bilingual_package(self):
        pkg = self.base / "mixed_pkg"
        self._create_minimal_package(pkg, is_english=True)

        # Add a Chinese temporary section alongside the English permanent section
        chinese_temp = pkg / "临时栏目" / "常规链式"
        chinese_temp.mkdir(parents=True, exist_ok=True)
        zh_data = {
            "format": "bookmark-canvas-section",
            "schemaVersion": 2,
            "sectionType": "temporary",
            "id": "zh-temp-1",
            "label": "ZH-1",
            "title": "中文临时栏目",
            "items": [],
        }
        (chinese_temp / "ZH-1.json").write_text(json.dumps(zh_data), encoding="utf-8")

        res = self.manager.sync(str(pkg), mode="snapshot")
        self.assertEqual(res["state"], "snapshot")

        sections = self.index.connection.execute("SELECT section_id FROM sections").fetchall()
        section_ids = {s["section_id"] for s in sections}
        self.assertIn("zh-temp-1", section_ids)
        self.assertIn("temp-1", section_ids)

    def test_formal_baseline_fixture_unmodified_and_accurate(self):
        formal_pkg = Path(__file__).resolve().parents[0] / "fixtures" / "canvas"
        self.assertTrue(formal_pkg.is_dir(), "Baseline fixtures must be present")

        def dir_hashes(p):
            h = {}
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    h[str(f.relative_to(p))] = hashlib.sha256(f.read_bytes()).hexdigest()
            return h

        hashes_before = dir_hashes(formal_pkg)

        isolated_db = self.base / "formal_baseline.db"
        with BookmarkIndex(isolated_db) as idx:
            sm = SourceManager(idx)
            res = sm.sync(str(formal_pkg), mode="snapshot")
            self.assertEqual(res["state"], "snapshot")

            sections = idx.connection.execute("SELECT * FROM sections").fetchall()
            self.assertEqual(len(sections), 4)

            bookmarks = idx.connection.execute(
                "SELECT * FROM items WHERE item_type='bookmark'"
            ).fetchall()
            self.assertEqual(len(bookmarks), 7)

            total_items = idx.connection.execute("SELECT * FROM items").fetchall()
            self.assertEqual(len(total_items), 10)

            nodes = idx.connection.execute("SELECT * FROM nodes").fetchall()
            self.assertEqual(len(nodes), 6)

            edges = idx.connection.execute("SELECT * FROM edges").fetchall()
            self.assertEqual(len(edges), 2)

        hashes_after = dir_hashes(formal_pkg)
        self.assertEqual(hashes_before, hashes_after, "Baseline fixture files must remain unmodified!")

    def test_external_user_package_if_configured(self):
        env_pkg = os.environ.get("BOOKMARK_CANVAS_TEST_DIR")
        if not env_pkg or not Path(env_pkg).is_dir():
            self.skipTest("No BOOKMARK_CANVAS_TEST_DIR configured")

        target = Path(env_pkg)
        def dir_hashes(p):
            h = {}
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    h[str(f.relative_to(p))] = hashlib.sha256(f.read_bytes()).hexdigest()
            return h

        hashes_before = dir_hashes(target)
        isolated_db = self.base / "external_pkg.db"
        with BookmarkIndex(isolated_db) as idx:
            sm = SourceManager(idx)
            res = sm.sync(str(target), mode="snapshot")
            self.assertEqual(res["state"], "snapshot")
        hashes_after = dir_hashes(target)
        self.assertEqual(hashes_before, hashes_after, "External package files must remain unmodified!")

    def test_vault_ancestor_folder_disambiguation(self):
        # Issue 1: Reference Permanent/collection/永久栏目/A.json should resolve to 永久栏目/A.json
        pkg = self.base / "ancestor_disambig_pkg"
        (pkg / "永久栏目").mkdir(parents=True, exist_ok=True)
        perm_data = {
            "format": "bookmark-canvas-section",
            "schemaVersion": 3,
            "sectionType": "permanent",
            "slot": "A",
            "title": "Main Permanent",
            "tree": {"id": "root", "title": "Bookmarks", "folderType": "root", "children": []},
        }
        (pkg / "永久栏目" / "A.json").write_text(json.dumps(perm_data), encoding="utf-8")

        canvas_data = {
            "nodes": [
                {
                    "id": "node_perm",
                    "type": "file",
                    "file": "Permanent/collection/永久栏目/A.json",
                    "x": 0, "y": 0, "width": 200, "height": 100,
                }
            ],
            "edges": [],
        }
        (pkg / "test.canvas").write_text(json.dumps(canvas_data), encoding="utf-8")

        res = self.manager.sync(str(pkg), mode="snapshot")
        self.assertEqual(res["state"], "snapshot")

        node = self.index.connection.execute("SELECT * FROM nodes WHERE node_id='node_perm'").fetchone()
        self.assertIsNotNone(node)
        self.assertEqual(node["file_path"], "永久栏目/A.json")
        self.assertEqual(node["section_id"], "permanent-section")

    def test_zip_with_protocol_wrapper_folder(self):
        # Issue 2: ZIP wrapped inside Permanent/ or Temporary/ should not report multiple roots
        for wrapper_name in ("Permanent", "Temporary"):
            pkg = self.base / f"zip_source_{wrapper_name}"
            self._create_minimal_package(pkg, is_english=True)

            zip_path = self.base / f"wrapped_{wrapper_name}.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                for f in pkg.rglob("*"):
                    if f.is_file():
                        zf.write(f, arcname=f"{wrapper_name}/" + f.relative_to(pkg).as_posix())

            isolated_db = self.base / f"zip_{wrapper_name}.db"
            with BookmarkIndex(isolated_db) as idx:
                sm = SourceManager(idx)
                res = sm.sync(str(zip_path), mode="snapshot")
                self.assertEqual(res["state"], "snapshot")
                sections = idx.connection.execute("SELECT * FROM sections").fetchall()
                self.assertEqual(len(sections), 2)
                nodes = idx.connection.execute("SELECT * FROM nodes").fetchall()
                self.assertEqual(len(nodes), 2)

    def test_config_directory_with_temporary_json_not_mistaken_as_package(self):
        # Issue 3: Temporary/settings.json without canvas protocol should not be mistaken as canvas package
        cfg_dir = self.base / "my_config_dir"
        (cfg_dir / "Temporary").mkdir(parents=True, exist_ok=True)
        (cfg_dir / "Temporary" / "settings.json").write_text(
            json.dumps({"schema_version": 1, "custom_key": "custom_value"}),
            encoding="utf-8"
        )

        self.assertFalse(is_package_dir(cfg_dir))
        # Settings.external_path should accept cfg_dir
        accepted = Settings.external_path(str(cfg_dir), "Config directory")
        self.assertEqual(accepted, cfg_dir.resolve())

    def test_deep_path_section_import_consistency_directory_and_zip(self):
        # Regression test: deep temporary section paths like 临时栏目/常规链式/Topic/T-1.json
        # must import identically from both directory and ZIP archives (including wrapped).
        for is_english in (False, True):
            pkg_name = f"deep_pkg_{'en' if is_english else 'zh'}"
            pkg = self.base / pkg_name
            pkg.mkdir(parents=True, exist_ok=True)
            perm_dir = "Permanent" if is_english else "永久栏目"
            temp_dir = "Temporary" if is_english else "临时栏目"
            chain_dir = "General Chain" if is_english else "常规链式"
            deep_rel_path = f"{temp_dir}/{chain_dir}/Topic/T-1.json"
            perm_rel_path = f"{perm_dir}/A.json"

            (pkg / perm_dir).mkdir(parents=True, exist_ok=True)
            (pkg / temp_dir / chain_dir / "Topic").mkdir(parents=True, exist_ok=True)

            perm_data = {
                "format": "bookmark-canvas-section",
                "schemaVersion": 3,
                "sectionType": "permanent",
                "slot": "A",
                "title": "Permanent Slot A",
                "tree": {"id": "root_id", "title": "Bookmarks", "folderType": "root", "children": []},
            }
            (pkg / perm_rel_path).write_text(json.dumps(perm_data), encoding="utf-8")

            deep_data = {
                "format": "bookmark-canvas-section",
                "schemaVersion": 2,
                "sectionType": "temporary",
                "id": "deep-temp-1",
                "label": "T-1",
                "title": "Deep Temporary Topic",
                "items": [
                    {
                        "id": "item_deep_1",
                        "type": "bookmark",
                        "title": "Deep Bookmark",
                        "url": "https://example.com/deep",
                        "sectionId": "deep-temp-1",
                    }
                ],
            }
            (pkg / deep_rel_path).write_text(json.dumps(deep_data), encoding="utf-8")

            canvas_data = {
                "nodes": [
                    {
                        "id": "node_perm",
                        "type": "file",
                        "file": perm_rel_path,
                        "x": 0, "y": 0, "width": 200, "height": 100,
                    },
                    {
                        "id": "node_deep",
                        "type": "file",
                        "file": deep_rel_path,
                        "x": 300, "y": 0, "width": 200, "height": 100,
                    },
                ],
                "edges": [
                    {
                        "id": "edge_deep",
                        "fromNode": "node_perm",
                        "toNode": "node_deep",
                        "label": "connects-to-deep",
                    }
                ],
            }
            (pkg / "test.canvas").write_text(json.dumps(canvas_data), encoding="utf-8")

            # 1. Directory import
            db_dir = self.base / f"{pkg_name}_dir.db"
            with BookmarkIndex(db_dir) as idx_dir:
                sm_dir = SourceManager(idx_dir)
                res_dir = sm_dir.sync(str(pkg), mode="snapshot")
                self.assertEqual(res_dir["state"], "snapshot")

                sec_dir = idx_dir.connection.execute("SELECT file_path FROM sections ORDER BY file_path").fetchall()
                paths_dir = [s["file_path"] for s in sec_dir]
                self.assertIn(perm_rel_path, paths_dir)
                self.assertIn(deep_rel_path, paths_dir)

                node_dir = idx_dir.connection.execute("SELECT file_path FROM nodes WHERE node_id='node_deep'").fetchone()
                self.assertEqual(node_dir["file_path"], deep_rel_path)

            # 2. ZIP import (unwrapped)
            zip_unwrapped = self.base / f"{pkg_name}_unwrapped.zip"
            with zipfile.ZipFile(zip_unwrapped, "w") as zf:
                for f in pkg.rglob("*"):
                    if f.is_file():
                        zf.write(f, arcname=f.relative_to(pkg).as_posix())

            db_zip = self.base / f"{pkg_name}_zip.db"
            with BookmarkIndex(db_zip) as idx_zip:
                sm_zip = SourceManager(idx_zip)
                res_zip = sm_zip.sync(str(zip_unwrapped), mode="snapshot")
                self.assertEqual(res_zip["state"], "snapshot")

                sec_zip = idx_zip.connection.execute("SELECT file_path FROM sections ORDER BY file_path").fetchall()
                paths_zip = [s["file_path"] for s in sec_zip]
                self.assertEqual(paths_zip, paths_dir)

                node_zip = idx_zip.connection.execute("SELECT file_path FROM nodes WHERE node_id='node_deep'").fetchone()
                self.assertEqual(node_zip["file_path"], deep_rel_path)

            # 3. ZIP import (wrapped with wrapper name and protocol wrapper name)
            for wrapper in ("wrapped_folder", perm_dir, temp_dir):
                zip_wrapped = self.base / f"{pkg_name}_wrapped_{wrapper}.zip"
                with zipfile.ZipFile(zip_wrapped, "w") as zf:
                    for f in pkg.rglob("*"):
                        if f.is_file():
                            zf.write(f, arcname=f"{wrapper}/" + f.relative_to(pkg).as_posix())

                db_wrapped = self.base / f"{pkg_name}_wrapped_{wrapper}.db"
                with BookmarkIndex(db_wrapped) as idx_wrapped:
                    sm_wrapped = SourceManager(idx_wrapped)
                    res_wrapped = sm_wrapped.sync(str(zip_wrapped), mode="snapshot")
                    self.assertEqual(res_wrapped["state"], "snapshot")

                    sec_wrapped = idx_wrapped.connection.execute("SELECT file_path FROM sections ORDER BY file_path").fetchall()
                    paths_wrapped = [s["file_path"] for s in sec_wrapped]
                    self.assertEqual(paths_wrapped, paths_dir)


if __name__ == "__main__":
    unittest.main()
