import copy
import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bookmark_output import compact_search


def bookmark_row(item_id="one", section_id="A", **extra):
    row = {
        "source_id": "canvas-example", "section_id": section_id, "item_id": item_id,
        "parent_id": "folder-one", "item_type": "bookmark", "title": "Saved page",
        "url": "https://example.test/" + item_id, "note": "Saved note",
        "note_color": "green", "tags": [{"color": "purple", "text": "read"}],
        "position": 0, "path": ["Folder"], "folder_path": "Folder",
        "section_label": section_id, "file_path": section_id + ".json",
    }
    row.update(extra)
    return row


class CompactSearchTests(unittest.TestCase):
    def test_target_only_pages_share_rows_and_preserve_each_page_order(self):
        first, second, hidden = [bookmark_row(name) for name in ("first", "second", "hidden")]
        response = {
            "source_id": "canvas-example", "total": 3, "unique_urls": 3,
            "limit": 2, "offset": 0, "next_offset": 2, "results": [second, first],
            "targets": [
                {"target": "alpha", "total": 3, "unique_urls": 3,
                 "limit": 2, "offset": 1, "next_offset": None, "results": [hidden, second]},
                {"target": "beta", "total": 3, "unique_urls": 3,
                 "limit": 2, "offset": 0, "next_offset": 2, "results": [first, hidden]},
            ],
        }
        output = compact_search(response)
        rows = output["rows"]
        self.assertEqual(output["_compact"]["format"], "bookmark-search-v1")
        self.assertNotIn("results", output)
        self.assertEqual(len(rows), 3)
        for reference in rows:
            self.assertRegex(reference, r"^r[1-9][0-9]*$")
        self.assertEqual([rows[ref]["item_id"] for ref in output["result_refs"]], ["second", "first"])
        self.assertEqual([[rows[ref]["item_id"] for ref in target["result_refs"]]
                          for target in output["targets"]], [["hidden", "second"], ["first", "hidden"]])
        self.assertEqual(output["result_refs"][0], output["targets"][0]["result_refs"][1])
        self.assertEqual(output["targets"][0]["result_refs"][0], output["targets"][1]["result_refs"][1])
        self.assertEqual(output["next_offset"], 2)
        for old, new in zip(response["targets"], output["targets"]):
            self.assertNotIn("results", new)
            self.assertEqual({key: value for key, value in old.items() if key != "results"},
                             {key: value for key, value in new.items() if key != "result_refs"})

    def test_shared_urls_and_conflicting_versions_of_one_instance_do_not_merge(self):
        original = bookmark_row(url="https://example.test/shared")
        other_section = bookmark_row(section_id="B", url=original["url"], parent_id="another-folder")
        changed_note = {**original, "note": "Different stored evidence"}
        output = compact_search({
            "results": [original, other_section, changed_note],
            "targets": [{"target": "shared", "results": [copy.deepcopy(original)]}],
        })
        refs = output["result_refs"]
        self.assertEqual(len(set(refs)), 3)
        self.assertEqual(len(output["rows"]), 3)
        self.assertEqual(output["targets"][0]["result_refs"], [refs[0]])
        rows = [output["rows"][ref] for ref in refs]
        self.assertEqual([(row["section_id"], row["item_id"], row["parent_id"]) for row in rows],
                         [("A", "one", "folder-one"), ("B", "one", "another-folder"),
                          ("A", "one", "folder-one")])
        self.assertEqual([row["note"] for row in rows],
                         ["Saved note", "Saved note", "Different stored evidence"])

    def test_only_matching_aliases_and_redundant_raw_fields_are_removed(self):
        standard = bookmark_row(shown_in_anchors=["copy-B"])
        row = {
            **standard, "source": standard["source_id"], "section": standard["section_id"],
            "item": standard["item_id"],
            "raw_json": {
                "id": standard["item_id"], "parentId": standard["parent_id"],
                "sectionId": standard["section_id"], "type": standard["item_type"],
                "title": standard["title"], "url": standard["url"],
                "note": standard["note"], "noteColor": standard["note_color"],
                "tags": copy.deepcopy(standard["tags"]),
            },
            "metadata": {"syncId": standard["item_id"], "note": standard["note"],
                         "noteColor": standard["note_color"], "tags": copy.deepcopy(standard["tags"])},
        }
        output = compact_search({"results": [row]})
        saved = output["rows"][output["result_refs"][0]]
        self.assertEqual({key: saved[key] for key in standard}, standard)
        for alias in ("source", "section", "item"):
            self.assertNotIn(alias, saved)
        self.assertEqual(saved.get("raw_json", {}), {})
        self.assertEqual(saved.get("metadata", {}), {})

    def test_unknown_conflicts_and_nested_type_differences_remain_inline(self):
        tags = [{"color": "purple", "text": "read", "details": {"enabled": True, "levels": [1]}}]
        raw_tags, metadata_tags = copy.deepcopy(tags), copy.deepcopy(tags)
        raw_tags[0]["details"]["enabled"] = 1
        metadata_tags[0]["details"]["levels"][0] = 1.0
        row = bookmark_row(tags=tags, source="legacy-source", section="A", item="one")
        row["raw_json"] = {"id": "one", "title": "Conflicting raw title",
                           "folderType": "bookmarks-bar", "tags": raw_tags}
        row["metadata"] = {"syncId": "one", "note": "Conflicting metadata note",
                           "future": {"values": [True, 1, 1.0]}, "tags": metadata_tags}
        output = compact_search({"results": [row]})
        saved = output["rows"][output["result_refs"][0]]
        self.assertEqual(saved["source"], "legacy-source")
        self.assertNotIn("section", saved)
        self.assertNotIn("item", saved)
        self.assertEqual(saved["raw_json"], {"title": "Conflicting raw title",
                                             "folderType": "bookmarks-bar", "tags": raw_tags})
        self.assertEqual(saved["metadata"], {"note": "Conflicting metadata note",
                                             "future": {"values": [True, 1, 1.0]}, "tags": metadata_tags})
        self.assertIs(type(saved["tags"][0]["details"]["enabled"]), bool)
        self.assertIs(type(saved["raw_json"]["tags"][0]["details"]["enabled"]), int)
        self.assertIs(type(saved["metadata"]["tags"][0]["details"]["levels"][0]), float)

    def test_same_identity_with_deep_bool_int_or_float_values_stays_distinct(self):
        variants = [bookmark_row(tags=[{"color": "blue", "text": "typed", "details": [value]}])
                    for value in (True, 1, 1.0)]
        output = compact_search({"results": variants})
        self.assertEqual(len(output["rows"]), 3)
        self.assertEqual(len(set(output["result_refs"])), 3)
        values = [output["rows"][ref]["tags"][0]["details"][0] for ref in output["result_refs"]]
        self.assertEqual([type(value) for value in values], [bool, int, float])

    def test_source_state_canvas_matches_and_unknown_metadata_pass_through_without_mutation(self):
        row = bookmark_row(raw_json={"id": "one", "unfamiliar": {"enabled": True}},
                           metadata={"note": "Saved note"}, synthetic=False)
        response = {
            "source_id": "canvas-example", "results": [row],
            "targets": [{"target": "saved", "results": [row], "total": 1}],
            "source": {"state": "snapshot", "version_id": "v1", "input_exists": False,
                       "retained_missing_files": ["old.json"], "error": None},
            "refresh": {"performed": False, "state": "snapshot"},
            "counts": {"instances": 1, "unique_urls": 1},
            "query_scope": {"section": "A", "tags": ["read"]},
            "canvas_matches": {"total": 2, "limit": 1, "offset": 0, "next_offset": 1,
                               "results": [{"node_id": "text-one", "text": "A nearby note",
                                            "future": {"enabled": True}}]},
            "future_envelope_field": {"nested": [None, 1.0, {"flag": False}]},
        }
        before = copy.deepcopy(response)
        output = compact_search(response)
        for key, value in before.items():
            if key not in ("results", "targets"):
                self.assertEqual(output[key], value)
        self.assertEqual(json.dumps(response, sort_keys=True), json.dumps(before, sort_keys=True))
        self.assertEqual(len(output["rows"]), 1)
        self.assertEqual(output["result_refs"], output["targets"][0]["result_refs"])
        json.dumps(output)

    def test_empty_and_count_only_pages_preserve_totals_without_inventing_rows(self):
        for total in (0, 42):
            with self.subTest(total=total):
                response = {
                    "source_id": "canvas-example", "total": total, "unique_urls": total,
                    "counts": {"instances": total, "unique_urls": total},
                    "limit": 0, "offset": 0, "next_offset": None, "results": [],
                    "targets": [{"target": "counted", "total": total, "unique_urls": total,
                                 "limit": 0, "offset": 0, "next_offset": None, "results": []}],
                }
                output = compact_search(response)
                self.assertEqual(output["rows"], {})
                self.assertEqual(output["result_refs"], [])
                self.assertEqual(output["targets"][0]["result_refs"], [])
                self.assertNotIn("results", output)
                self.assertNotIn("results", output["targets"][0])
                self.assertEqual(output["counts"], response["counts"])
                self.assertEqual(output["total"], total)
                self.assertEqual(output["targets"][0]["total"], total)
                self.assertIsNone(output["next_offset"])
                self.assertIsNone(output["targets"][0]["next_offset"])


if __name__ == "__main__":
    unittest.main()
