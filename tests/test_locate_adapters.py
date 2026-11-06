"""Contract tests for the non-Canvas locate adapters."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from locate import continuation_scope, locate
from ref_codec import resolve


class _Wiki:
    def search(self, query, offset=0, limit=10):
        return {"results": [{"page_id": "research", "revision": 3,
                              "title": "React notes", "snippet": "React hooks"}],
                "total": 1, "next_offset": None}


class _Archive:
    def search(self, query, limit=10, offset=0, url=None):
        return {"results": [{"url": "https://example.test/react", "title": "React",
                              "snippet": "React hooks", "sha256": "abc",
                              "occurrences": [{"kind": "archive", "capture_id": "cap-1"}]}],
                "total": 1, "next_offset": None}


class _PaginatedWiki:
    def search(self, query, offset=0, limit=10):
        rows = [
            {"page_id": "research-1", "revision": 3, "title": "React first", "snippet": "React hooks"},
            {"page_id": "research-2", "revision": 4, "title": "React second", "snippet": "React state"},
        ]
        page = rows[offset:offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(rows) else None
        return {"results": page, "total": len(rows), "next_offset": next_offset}


class LocateAdapterTests(unittest.TestCase):
    def test_wiki_preserves_revision_evidence(self):
        result = locate(object(), object(), {"text": "React", "in": ["wiki"]}, wiki=_Wiki())
        hit = result["hits"][0]
        self.assertLessEqual(len(hit["ref"]), 8)
        self.assertEqual({"kind": "w", "identity": ["research", "3"]}, resolve(hit["ref"]))
        self.assertEqual("wiki_revision", hit["evidence_kind"])
        self.assertEqual(3, hit["wiki_revision"])
        self.assertEqual(result["match_mode"], hit["why"]["match_mode"])

    def test_archive_preserves_capture_evidence(self):
        result = locate(object(), object(), {"text": "React", "in": ["archive"]}, raw=_Archive())
        hit = result["hits"][0]
        self.assertLessEqual(len(hit["ref"]), 8)
        self.assertEqual({"kind": "a", "identity": ["cap-1", "abc", "https://example.test/react"]},
                         resolve(hit["ref"]))
        self.assertEqual("archive_capture", hit["evidence_kind"])
        self.assertEqual("cap-1", hit["capture_id"])
        self.assertEqual("usable", hit["content_state"])
        self.assertEqual(result["match_mode"], hit["why"]["match_mode"])

    def test_signed_wiki_continuation_preserves_scope_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory(prefix="bookmark-locate-handle-") as directory:
            database = Path(directory) / "index.sqlite3"
            index = SimpleNamespace(db_path=database)
            wiki = _PaginatedWiki()
            first = locate(index, object(), {"text": "React", "in": ["wiki"], "limit": 1}, wiki=wiki)
            handle = first["more"]["handle"]
            self.assertEqual(["wiki"], continuation_scope(handle, database))

            second = locate(index, object(), {"handle": handle, "offset": 1}, wiki=wiki)
            self.assertEqual("React second", second["hits"][0]["title"])
            self.assertNotEqual(first["hits"][0]["ref"], second["hits"][0]["ref"])

            tampered = handle[:-1] + ("A" if handle[-1] != "A" else "B")
            self.assertEqual(["canvas"], continuation_scope(tampered, database))
            with self.assertRaisesRegex(ValueError, "unknown locate continuation handle"):
                locate(index, object(), {"handle": tampered, "offset": 1}, wiki=wiki)


if __name__ == "__main__":
    unittest.main()
