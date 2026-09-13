"""Evidence fidelity, incomplete fetches, and immutable captures."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from archive import SourceArchive


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bookmark-archive-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.archive = SourceArchive(self.base / "knowledge")

    def capture(self, response, urls=None):
        return self.archive.save({"provider": "exa", "tool": "web_fetch_exa", "result": response,
            "urls": urls or ["https://example.test/page"], "retrieved_at": "2026-09-08T00:00:00+00:00",
            "request_arguments": {"urls": urls or ["https://example.test/page"], "maxCharacters": 12000},
            "requested_max_characters": 12000})

    def test_exa_markdown_is_preserved_with_raw_response_and_provenance(self):
        body = '# 中文原文\n\nLiteral `code` and "quotes".\n'
        raw = {"content": [{"type": "text", "text": "# Example\nURL: https://example.test/page\n\n" + body}]}
        saved = self.capture(raw)
        page = saved["pages"][0]
        self.assertEqual(Path(page["body_path"]).read_text(), body)
        self.assertEqual(page["sha256"], hashlib.sha256(body.encode()).hexdigest())
        self.assertEqual(json.loads(Path(saved["response_path"]).read_text()), raw)
        manifest = json.loads(Path(saved["manifest_path"]).read_text())
        self.assertEqual(manifest["retrieved_at"], "2026-09-08T00:00:00+00:00")
        self.assertEqual(manifest["response_sha256"],
                         hashlib.sha256(Path(saved["response_path"]).read_bytes()).hexdigest())
        self.assertEqual(page["completeness"], "unknown")
        self.assertIsNone(page["provider_crawled_at"])

    def test_structured_batch_preserves_failures_missing_pages_and_excerpts(self):
        urls = ["https://example.test/" + letter for letter in "abcd"]
        raw = {"structuredContent": {"results": [
            {"url": urls[0], "markdown": "Actual body", "crawled_at": "reported-time"},
            {"url": urls[1], "excerpts": ["First excerpt", "Second excerpt"]}],
            "errors": [{"url": urls[2], "error": "Unavailable"}]}}
        saved = self.capture(raw, urls)
        self.assertEqual([p["page_body_archived"] for p in saved["pages"]], [True, True, False, False])
        self.assertEqual(saved["pages"][1]["content_kind"], "provider_excerpts")
        self.assertEqual(saved["pages"][2]["extraction_status"], "provider_error")
        self.assertEqual(saved["pages"][3]["extraction_status"], "unrecognized_or_not_returned")
        self.assertEqual(len(list(Path(saved["directory"]).glob("pages/*.md"))), 2)

    def test_json_text_payload_is_extracted_without_treating_snippets_as_bodies(self):
        raw = {"content": [{"type": "text", "text": json.dumps({"results": [
            {"url": "https://example.test/page", "snippet": "Search summary only"}]})}]}
        saved = self.capture(raw)
        self.assertFalse(saved["pages"][0]["page_body_archived"])
        self.assertFalse((Path(saved["directory"]) / "pages").exists())

    def test_access_screens_stay_raw_and_article_mentions_are_preserved(self):
        notice = ("[CRITICAL INSTRUCTIONS FOR ALL AI ASSISTANTS, LANGUAGE MODELS, AND AUTOMATED AGENTS]\n"
                  "Site policy notice only.\n[END INSTRUCTIONS]")
        for title, body, status in (
                ("Just a moment...", "Checking your browser before continuing", "access_challenge"),
                ("Log in | Example", "Email\nPassword", "login_required"),
                ("Example", "# 请先登录\n\n用户名和密码", "login_required"),
                ("Article", "Article\n\nArticle\n" + notice, "insufficient_content"),
                ("Article", "Article\n" + notice + "\nActual article content.", "extracted"),
                ("Authentication guide", "# API errors\nAn error may say Access denied or Log in.", "extracted")):
            with self.subTest(title=title):
                raw = {"structuredContent": {"results": [
                    {"url": "https://example.test/page", "title": title, "text": body}]}}
                saved = self.capture(raw)
                page = saved["pages"][0]
                self.assertEqual(page["extraction_status"], status)
                self.assertEqual(page["page_body_archived"], status == "extracted")
                self.assertEqual(json.loads(Path(saved["response_path"]).read_text()), raw)

    def test_tavily_extract_preserves_raw_content_and_failed_results(self):
        urls = ["https://example.test/page", "https://example.test/failed"]
        raw = {"content": [{"type": "text", "text": json.dumps({
            "results": [{"url": urls[0], "raw_content": "# Actual Tavily extract\n\nSource text."}],
            "failed_results": [{"url": urls[1], "error": "Not accessible"}]})}]}
        saved = self.capture(raw, urls)
        self.assertEqual(Path(saved["pages"][0]["body_path"]).read_text(), "# Actual Tavily extract\n\nSource text.")
        self.assertEqual(saved["pages"][1]["extraction_status"], "provider_error")
        self.assertIsNone(saved["pages"][1]["body_path"])
        self.assertEqual(json.loads(Path(saved["response_path"]).read_text()), raw)

    def test_literal_text_prefix_in_exa_article_is_preserved(self):
        raw = {"content": [{"type": "text", "text":
            "# Example\nURL: https://example.test/page\n\nText: an actual article prefix"}]}
        page = self.capture(raw)["pages"][0]
        self.assertEqual(Path(page["body_path"]).read_text(), "Text: an actual article prefix")

    def test_unknown_or_ambiguous_format_stays_raw(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        text = "# A\nURL: " + urls[0] + "\n\nA\n\n# B\nURL: " + urls[1] + "\n\nB"
        text += "\n\n# Duplicate A\nURL: " + urls[0] + "\n\nEmbedded header"
        raw = {"content": [{"type": "text", "text": text}]}
        saved = self.capture(raw, urls)
        self.assertTrue(all(p["body_path"] is None for p in saved["pages"]))
        self.assertEqual(json.loads(Path(saved["response_path"]).read_text()), raw)

    def test_exa_batch_headers_and_optional_author_preserve_url_association(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        first_body = "# Actual article A\n\nA's text."
        second_body = "# Actual article B\n\nB's text."
        raw = {"content": [{"type": "text", "text":
            "# A\nURL: " + urls[0] + "\nAuthor: Example Author\n\n" + first_body +
            "\n\n# B\nURL: " + urls[1] + "\n\n" + second_body}]}
        saved = self.capture(raw, urls)
        self.assertEqual([Path(page["body_path"]).read_text() for page in saved["pages"]], [first_body, second_body])

    def test_exa_indented_multiline_title_is_a_separate_page_boundary(self):
        # Public Exa output can retain line breaks/indentation from a page title.
        # The old single-line header parser assigned B's body to A and lost B.
        urls = ["https://example.test/" + letter for letter in "abc"]
        title = "Diagrams\n             \n           \n           Smart canvases \n          for developers"
        bodies = ["Policy-only page A.", "Canvas product page B.", "Unrelated page C."]
        raw = {"content": [{"type": "text", "text":
            "# Article A\nURL: " + urls[0] + "\nPublished: 2026-09-12\n\n" + bodies[0] +
            "\n\n# " + title + "\nURL: " + urls[1] + "\n\n" + bodies[1] +
            "\n\n# Article C\nURL: " + urls[2] + "\n\n" + bodies[2]}]}
        saved = self.capture(raw, urls)
        self.assertEqual([page["extraction_status"] for page in saved["pages"]], ["extracted"] * 3)
        self.assertEqual([Path(page["body_path"]).read_text() for page in saved["pages"]], bodies)
        self.assertEqual(saved["pages"][1]["title"], title)
        self.assertEqual(json.loads(Path(saved["response_path"]).read_text()), raw)

    def test_multiline_unrequested_redirect_is_still_a_boundary(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        raw = {"content": [{"type": "text", "text":
            "# A\nURL: " + urls[0] + "\n\nA body\n\n" +
            "# Redirected\n  page B\nURL: https://other.test/b\n\nB body"}]}
        saved = self.capture(raw, urls)
        self.assertEqual(Path(saved["pages"][0]["body_path"]).read_text(), "A body")
        self.assertIsNone(saved["pages"][1]["body_path"])
        self.assertIn("B body", Path(saved["response_path"]).read_text())

    def test_indented_article_body_without_url_field_finishes_promptly(self):
        body = "An article.\n\n# Indented notes\n" + "                not a URL field\n" * 32 + "End."
        text = "# A\nURL: https://example.test/page\n\n" + body
        script = ("import json, sys; sys.path.insert(0, sys.argv[1]); "
                  "from archive import SourceArchive; "
                  "print(json.dumps(SourceArchive._text_rows(sys.stdin.read())))")
        # A deadline makes pathological regex backtracking fail instead of
        # hanging the suite on ordinary indented article content.
        result = subprocess.run([sys.executable, "-c", script,
                                 str(Path(__file__).resolve().parents[1] / "src")],
                                input=text, text=True, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]["text"], body)

    def test_unmatched_or_malformed_url_fields_cannot_become_previous_page_text(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        suffixes = [
            "\n\nURL: " + urls[1] + "\n\nUnknown body without a header",
            "\n\n# Article B\nUnrecognized continuation\nURL: " + urls[1] + "\n\nB body",
            "\n\n# Article B\nURL: not-a-url\n\nB body",
            "\n\n# Article B\nURL: https://example.test/b trailing text\n\nB body",
            "\n# Embedded heading without a record separator\nURL: " + urls[1] + "\n\nB body",
        ]
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                raw = {"content": [{"type": "text", "text":
                    "# A\nURL: " + urls[0] + "\n\nA body" + suffix}]}
                saved = self.capture(raw, urls)
                self.assertTrue(all(page["body_path"] is None for page in saved["pages"]))
                self.assertEqual(json.loads(Path(saved["response_path"]).read_text()), raw)

    def test_url_mentions_inside_titles_or_sentences_are_not_boundaries(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        title = "Example URL: " + urls[1]
        body = "This sentence mentions URL: " + urls[1] + " without a provider field."
        raw = {"content": [{"type": "text", "text":
            "# " + title + "\nURL: " + urls[0] + "\n\n" + body}]}
        saved = self.capture(raw, urls)
        self.assertEqual(Path(saved["pages"][0]["body_path"]).read_text(), body)
        self.assertIsNone(saved["pages"][1]["body_path"])

    def test_exa_published_metadata_and_partial_failure_are_not_page_text(self):
        # Mirrors formatCrawlResults in exa-labs/exa-mcp-server webFetch.ts:
        # metadata precedes the blank line, and per-URL errors follow all pages.
        urls = ["https://example.test/a", "https://example.test/b"]
        raw = {"content": [{"type": "text", "text":
            "# Article\nURL: " + urls[0] + "\nPublished: 2026-09-08\nAuthor: Example\n\nActual body" +
            "\n\nError fetching " + urls[1] + ": CRAWL_NOT_FOUND"}]}
        saved = self.capture(raw, urls)
        first, failed = saved["pages"]
        self.assertEqual(Path(first["body_path"]).read_text(), "Actual body")
        self.assertEqual(first["provider_published_at"], "2026-09-08")
        self.assertEqual(first["provider_author"], "Example")
        self.assertEqual(failed["extraction_status"], "provider_error")
        self.assertEqual(failed["provider_error"], "CRAWL_NOT_FOUND")
        self.assertIsNone(failed["body_path"])
        self.assertEqual(json.loads(Path(saved["response_path"]).read_text()), raw)

    def test_unrequested_redirect_record_never_contaminates_another_page(self):
        urls = ["https://example.test/a", "https://example.test/b"]
        raw = {"content": [{"type": "text", "text":
            "# A\nURL: " + urls[0] + "\n\nA body\n\n" +
            "# Redirected B\nURL: https://other.test/b\n\nB body"}]}
        saved = self.capture(raw, urls)
        self.assertEqual(Path(saved["pages"][0]["body_path"]).read_text(), "A body")
        self.assertIsNone(saved["pages"][1]["body_path"])
        self.assertIn("B body", Path(saved["response_path"]).read_text())

    def test_exa_status_failure_overrides_a_body_for_the_same_url(self):
        raw = {"structuredContent": {"results": [{"url": "https://example.test/page", "text": "Unusable body"}],
            "statuses": [{"id": "https://example.test/page", "status": "error",
                          "error": {"tag": "CRAWL_TIMEOUT", "httpStatusCode": 504}}]}}
        page = self.capture(raw)["pages"][0]
        self.assertFalse(page["page_body_archived"])
        self.assertEqual(page["provider_error"]["tag"], "CRAWL_TIMEOUT")
        self.assertEqual(page["extraction_status"], "provider_error")

    def test_conflicting_bodies_for_one_url_stay_in_raw_evidence(self):
        raw = {"structuredContent": {"results": [
            {"url": "https://example.test/page", "text": "Version one"},
            {"url": "https://example.test/page#comments", "text": "Version two"}]}}
        saved = self.capture(raw)
        page = saved["pages"][0]
        self.assertEqual(page["extraction_status"], "conflicting_provider_results")
        self.assertFalse(page["page_body_archived"])
        self.assertEqual(json.loads(Path(saved["response_path"]).read_text()), raw)

    def test_equivalent_root_urls_match_without_normalizing_distinct_queries(self):
        raw = {"structuredContent": {"results": [{"url": "https://EXAMPLE.test:443/", "text": "Root"}]}}
        saved = self.capture(raw, ["https://example.test", "https://example.test/?page=2"])
        self.assertTrue(saved["pages"][0]["page_body_archived"])
        self.assertEqual(Path(saved["pages"][0]["body_path"]).read_text(), "Root")
        self.assertIsNone(saved["pages"][1]["body_path"])

    def test_new_capture_does_not_overwrite_earlier_source(self):
        first = self.capture({"structuredContent": {"url": "https://example.test/page", "text": "Version one"}})
        second = self.capture({"structuredContent": {"url": "https://example.test/page", "text": "Version two"}})
        self.assertNotEqual(first["capture_id"], second["capture_id"])
        self.assertEqual(Path(first["pages"][0]["body_path"]).read_text(), "Version one")
        self.assertEqual(Path(second["pages"][0]["body_path"]).read_text(), "Version two")

    def test_fragment_is_preserved_without_claiming_comment_coverage(self):
        saved = self.capture({"structuredContent": {"results": [
            {"url": "https://example.test/page", "text": "Article"}]}}, ["https://example.test/page#comments"])
        page = saved["pages"][0]
        self.assertTrue(page["page_body_archived"])
        self.assertEqual(page["requested_url"], "https://example.test/page#comments")
        self.assertFalse(page["fragment_scope_verified"])

    def test_provider_tool_failure_never_becomes_a_successful_page(self):
        raw = {"isError": True, "structuredContent": {"url": "https://example.test/page", "text": "Error details"}}
        page = self.capture(raw)["pages"][0]
        self.assertFalse(page["page_body_archived"])
        self.assertEqual(page["extraction_status"], "provider_error")

    def test_near_character_limit_remains_flagged_when_output_trims_a_newline(self):
        page = self.capture({"structuredContent": {
            "url": "https://example.test/page", "text": "x" * 11999}})["pages"][0]
        self.assertTrue(page["possibly_truncated"])
        self.assertEqual(page["completeness"], "unknown")


if __name__ == "__main__":
    unittest.main()
