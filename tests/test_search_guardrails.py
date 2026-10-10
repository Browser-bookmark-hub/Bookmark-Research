"""Question-shaped calls must expose the counts a host needs to answer safely.

Summing per-card bookmark counts used to over-report by 95% (a copy anchor
reports the shared tree), folders could not be enumerated at all, a count-only
question needed a synthetic limit, and a tag could not be filtered by color.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_index import BookmarkIndex


PRIMARY = "永久栏目/A书签树（永久栏目）.json"
COPY = "永久栏目/B书签树（永久栏目）.json"
TEMP = "临时栏目/常规链式/A-1 示例.json"


def write_json(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class SearchGuardrailTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="search guardrails ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        package = self.base / "package"
        write_json(package, PRIMARY, {
            "format": "bookmark-canvas-section", "schemaVersion": 3, "sectionType": "permanent",
            "slot": "A", "title": "Main", "fileRole": "primary", "descriptionMd": "",
            "tree": {"id": "root", "title": "", "children": [
                {"id": "companies", "parentId": "root", "title": "公司", "children": [
                    {"id": "one", "parentId": "companies", "title": "示例一", "url": "https://example.test/one"},
                    {"id": "two", "parentId": "companies", "title": "示例二", "url": "https://example.test/two"},
                ]}]}})
        write_json(package, COPY, {
            "format": "bookmark-canvas-section", "schemaVersion": 2, "sectionType": "permanent",
            "slot": "B", "copyId": "copy-b", "fileRole": "copy-anchor", "anchorOnly": True,
            "descriptionMd": "", "inheritFrom": PRIMARY})
        write_json(package, TEMP, {
            "format": "bookmark-canvas-section", "schemaVersion": 2, "sectionType": "temporary",
            "id": "temp-section-A-1", "label": "A-1", "title": "临时", "tempKind": "regular",
            "items": [{"id": "temp-one", "sectionId": "temp-section-A-1", "type": "bookmark",
                       "title": "临时书签", "url": "https://example.test/three",
                       "tags": [{"color": "green", "text": "关注"}]}]})
        self.index = BookmarkIndex(self.base / "data" / "index.sqlite3")
        self.addCleanup(self.index.close)
        with self.index.transaction():
            self.index.sync(package)
        self.source_id = self.index.connection.execute("SELECT source_id FROM sources").fetchone()[0]
        self.copy_section = self.index.connection.execute(
            "SELECT section_id FROM sections WHERE is_anchor=1").fetchone()[0]

    def test_copy_anchor_is_excluded_from_counted_totals(self):
        context = self.index.context(self.source_id)
        # Primary (2 bookmarks) plus the temporary card (1) = 3 counted instances.
        self.assertEqual(3, context["counts"]["instances"])
        self.assertEqual(3, context["counts"]["unique_urls"])
        anchor = next(row for row in context["sections"] if row["is_anchor"])
        self.assertFalse(anchor["counted_in_totals"])
        self.assertEqual(anchor["canonical_id"], anchor["anchor_of"])
        counted = [row for row in context["sections"] if row["counted_in_totals"]]
        self.assertEqual(3, sum(row["bookmark_count"] for row in counted))
        # The naive sum over every card is what used to mislead.
        self.assertEqual(5, sum(row["bookmark_count"] for row in context["sections"]))

    def test_search_reports_scope_counts_and_the_anchor(self):
        result = self.index.search(self.source_id, limit=1)
        self.assertEqual({"instances", "unique_urls", "note"}, set(result["counts"]))
        self.assertEqual(3, result["counts"]["instances"])
        self.assertEqual(3, result["counts"]["unique_urls"])
        anchor = self.index.search(self.source_id, section=self.copy_section, limit=0)
        self.assertEqual(2, anchor["total"])
        self.assertEqual({self.copy_section: "permanent-section"}, anchor["anchor_of"])

    def test_count_only_returns_counts_without_rows_or_pagination(self):
        result = self.index.search(self.source_id, targets=["示例"], limit=0)
        self.assertEqual(2, result["total"])
        self.assertEqual([], result["results"])
        self.assertIsNone(result["next_offset"])
        self.assertEqual(2, self.index.search(self.source_id, targets=["示例"], count_only=True)["total"])

    def test_next_offset_appears_for_a_truncated_page(self):
        first = self.index.search(self.source_id, limit=1)
        self.assertEqual(1, len(first["results"]))
        self.assertEqual(1, first["next_offset"])
        last = self.index.search(self.source_id, limit=10)
        self.assertIsNone(last["next_offset"])

    def test_folders_can_be_enumerated_and_the_tree_root_is_marked(self):
        folders = self.index.search(self.source_id, item_types=["folder"], limit=10)
        self.assertEqual(2, folders["total"])  # the synthetic tree root and "公司"
        root = next(row for row in folders["results"] if row["synthetic"])
        self.assertEqual("", root["title"])
        self.assertFalse(any(row.get("synthetic") for row in folders["results"] if row["title"]))
        status = self.index.status(self.source_id)
        self.assertEqual(2, status["counts"]["folders"])
        self.assertEqual(1, status["counts"]["tree_roots"])
        self.assertEqual(1, status["counts"]["user_folders"])

    def test_tag_colors_are_filterable(self):
        self.assertEqual(1, self.index.search(self.source_id, tag_colors=["green"], limit=0)["total"])
        self.assertEqual(0, self.index.search(self.source_id, tag_colors=["purple"], limit=0)["total"])

    def test_canvas_labels_and_text_cards_are_reported_separately(self):
        # The canvas carries a group and an edge labelled "123" and a text card.
        canvas = {"nodes": [
            {"id": "permanent-section", "type": "file", "file": PRIMARY, "x": 0, "y": 0, "width": 10, "height": 10},
            {"id": "temp-section-A-1", "type": "file", "file": TEMP, "x": 20, "y": 0, "width": 10, "height": 10},
            {"id": "card-group-24", "type": "group", "label": "123", "x": 0, "y": 0, "width": 100, "height": 100},
            {"id": "note-1", "type": "text", "text": "空白栏目 可用markdown渲染", "x": 0, "y": 120, "width": 10, "height": 10}],
            "edges": [{"id": "edge-1", "fromNode": "permanent-section", "toNode": "temp-section-A-1", "label": "123"}]}
        (self.base / "package" / "示例.canvas").write_text(json.dumps(canvas, ensure_ascii=False), encoding="utf-8")
        with self.index.transaction():
            self.index.sync(self.base / "package")
        result = self.index.search(self.source_id, targets=["123"], limit=5)
        kinds = {row["kind"] for row in result["canvas_matches"]}
        self.assertEqual({"group", "edge"}, kinds)
        self.assertIn("not bookmark items", result["canvas_match_note"])
        # Canvas matches never inflate the bookmark totals.
        self.assertEqual(0, result["total"])
        text = self.index.search(self.source_id, targets=["markdown"], limit=5)
        self.assertEqual(1, len(text["canvas_matches"]))
        self.assertEqual("text", text["canvas_matches"][0]["kind"])
        self.assertTrue(text["canvas_matches"][0]["text"].startswith("空白栏目"))

    def test_items_report_which_copy_cards_display_them(self):
        result = self.index.search(self.source_id, targets=["示例一"], limit=5)
        item = result["results"][0]
        self.assertEqual("permanent-section", item["section"])
        self.assertEqual([self.copy_section], item["shown_in_anchors"])
        # A bookmark that no copy displays carries no such key.
        only_temp = self.index.search(self.source_id, targets=["临时书签"], limit=5)["results"][0]
        self.assertNotIn("shown_in_anchors", only_temp)

    def test_canvas_matches_preserve_literal_wildcards_and_backslashes(self):
        marker = r"Release_100%\notes"
        canvas = {"nodes": [
            {"id": "permanent-section", "type": "file", "file": PRIMARY,
             "x": 0, "y": 0, "width": 10, "height": 10},
            {"id": "literal-group", "type": "group", "label": marker,
             "x": 0, "y": 0, "width": 100, "height": 100},
            {"id": "literal-text", "type": "text", "text": marker,
             "x": 0, "y": 120, "width": 10, "height": 10}],
            "edges": [{"id": "literal-edge", "fromNode": "permanent-section",
                       "toNode": "literal-text", "label": marker}]}
        write_json(self.base / "package", "literal.canvas", canvas)
        with self.index.transaction():
            self.index.sync(self.base / "package")
        targets = ["Release", "Release_100%", "100%", r"\notes", marker, "%", "_", "\\"]
        result = self.index.search(self.source_id, targets=targets, limit=5)
        actual = {(row["target"], row["kind"]) for row in result["canvas_matches"]}
        self.assertEqual({(target, kind) for target in targets for kind in ("text", "group", "edge")}, actual)
        self.assertEqual(0, result["total"])
        missing = self.index.search(self.source_id, targets=["ReleaseX100%"], limit=5)
        self.assertNotIn("canvas_matches", missing)

    def test_item_type_and_tag_color_inputs_are_validated(self):
        for compact in (1, "false", None):
            with self.subTest(compact=compact), self.assertRaisesRegex(ValueError, "compact"):
                self.index.search(self.source_id, compact=compact)
        with self.assertRaisesRegex(ValueError, "item_types"):
            self.index.search(self.source_id, item_types=["bookmark", "bookmark"])
        with self.assertRaisesRegex(ValueError, "item_types"):
            self.index.search(self.source_id, item_types=["other"])
        with self.assertRaisesRegex(ValueError, "limit"):
            self.index.search(self.source_id, limit=-1)
        with self.assertRaisesRegex(ValueError, "tag_colors"):
            self.index.search(self.source_id, tag_colors="green")


if __name__ == "__main__":
    unittest.main()
