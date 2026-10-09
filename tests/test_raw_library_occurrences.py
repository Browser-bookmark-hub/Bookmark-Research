"""A merged body must let callers enumerate every occurrence.

Occurrences used to be truncated to the first 50 with no marker and no way to
continue, while the document-level next_offset referred to documents.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from archive import SourceArchive
from raw_library import RawLibrary


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class OccurrencePaginationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="raw occurrence ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.data = self.base / "data"
        environment = mock.patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.data)})
        environment.start()
        self.addCleanup(environment.stop)
        self.archive = SourceArchive(self.data / "knowledge")
        self.library = RawLibrary(archive_directory=self.data / "knowledge")

    def capture(self, url, text, second):
        return self.archive.save({"provider": "exa", "tool": "web_fetch_exa", "urls": [url],
            "result": {"structuredContent": {"url": url, "title": "Title " + url, "text": text}},
            "retrieved_at": "2026-09-29T00:%02d:00+00:00" % second,
            "request_arguments": {"urls": [url]}, "requested_max_characters": 12000})

    def test_more_occurrences_than_the_page_are_counted_and_pageable(self):
        body = "Repeated archived body"
        for index in range(52):
            self.capture("https://example.test/page/%d" % index, body, index)
        first = self.library.search("Repeated", occurrence_limit=50)
        self.assertEqual(1, first["total"])
        result = first["results"][0]
        self.assertEqual(52, result["occurrence_count"])
        self.assertEqual(50, len(result["occurrences"]))
        self.assertTrue(result["occurrences_truncated"])
        self.assertEqual(50, result["occurrences_next_offset"])
        self.assertEqual(0, result["occurrence_offset"])
        seen = {entry["capture_id"] for entry in result["occurrences"]}
        second = self.library.search("Repeated", occurrence_limit=50, occurrence_offset=50)
        tail = second["results"][0]
        self.assertEqual(52, tail["occurrence_count"])
        self.assertEqual(2, len(tail["occurrences"]))
        self.assertFalse(tail["occurrences_truncated"])
        self.assertIsNone(tail["occurrences_next_offset"])
        # The two pages enumerate distinct occurrences without loss or overlap.
        remaining = {entry["capture_id"] for entry in tail["occurrences"]}
        self.assertEqual(52, len(seen | remaining))
        self.assertEqual(set(), seen & remaining)

    def test_complete_occurrence_list_is_not_marked_truncated(self):
        body = "Only one archived body"
        self.capture("https://example.test/only", body, 1)
        result = self.library.search("archived", occurrence_limit=50)["results"][0]
        self.assertEqual(1, result["occurrence_count"])
        self.assertFalse(result["occurrences_truncated"])
        self.assertIsNone(result["occurrences_next_offset"])

    def test_occurrence_arguments_are_validated(self):
        with self.assertRaisesRegex(ValueError, "occurrence_limit"):
            self.library.search("x", occurrence_limit=0)
        with self.assertRaisesRegex(ValueError, "occurrence_offset"):
            self.library.search("x", occurrence_offset=-1)


if __name__ == "__main__":
    unittest.main()
