"""Content state and published-at come from the page, never from the transport."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from archive import CONTENT_MINIMUM, SourceArchive, content_state, published_at
from web_search import SearchProviders

PROSE = ("A paragraph long enough to be prose rather than navigation, so the page counts as carrying a body "
         "that a claim could quote. ")
BODY = PROSE * 4
NAV = "Docs\n\nMenu\n\nHome\n\nAPI\n\nAbout\n"
CJK = "这是一段完整的中文段落，用来验证短行也按句号计入正文。\n" * 15


class ContentStateTests(unittest.TestCase):
    def test_a_fetch_failure_is_unavailable_not_a_content_verdict(self):
        for extraction in ("request_failed", "provider_error", "unrecognized_or_not_returned"):
            self.assertEqual("unavailable", content_state("Title", BODY, extraction))
        self.assertEqual("unavailable", content_state("Title", None, "extracted"))
        self.assertEqual("unavailable", content_state("Title", 17, "extracted"))

    def test_short_pages_are_insufficient_and_navigation_without_prose_is_a_shell(self):
        self.assertEqual("content_insufficient", content_state("", "No additional info available", "extracted"))
        self.assertEqual("content_insufficient", content_state("Title", "x" * (CONTENT_MINIMUM - 1), "extracted"))
        self.assertEqual("js_shell_suspected", content_state("Docs", NAV, "extracted"))
        # Without a title there is nothing to call a shell of.
        self.assertEqual("content_insufficient", content_state("", NAV, "extracted"))
        self.assertEqual("usable", content_state("Title", BODY, "extracted"))

    def test_short_cjk_lines_still_count_as_prose(self):
        self.assertLess(len(CJK), 800)
        self.assertEqual("usable", content_state("中文页", CJK, "extracted"))

    def test_a_long_page_of_link_chrome_is_still_a_shell(self):
        # The real shape of developers.google.com/edge/foresight: a title, a
        # language switcher and hundreds of links, and no prose paragraph. Its
        # own length is the reason the old 800-character bound missed it.
        chrome = ("# Page info\n\nfullscreen close_fullscreen close\n["
                  + "\n![" + "A" * 120 + "](https://www.gstatic.com/" + "b" * 200 + ")\n[English](https://example.test/en)\n"
                  + "* [Deutsch](https://example.test/de)\n" * 30)
        self.assertGreater(len(chrome), 800)
        self.assertEqual("js_shell_suspected", content_state("Google AI Edge Foresight", chrome, "extracted"))

    def test_markers_count_near_the_top_but_not_deep_in_a_long_body(self):
        # A short challenge page, or one that opens with the challenge text.
        self.assertEqual("challenge_blocked", content_state("T", "Enable JavaScript and cookies to continue" + NAV, "extracted"))
        self.assertEqual("challenge_blocked", content_state("T", "Just a moment... " + NAV, "extracted"))
        # The same words deep inside a long article are its subject, not its state.
        self.assertEqual("usable", content_state("T", PROSE * 7 + "Enable JavaScript and cookies to continue", "extracted"))
        self.assertEqual("usable", content_state("T", PROSE * 7 + "Just a moment...", "extracted"))

    def test_paywall_and_not_found_keep_their_own_names(self):
        self.assertEqual("paywall_suspected", content_state("T", "Subscribe to continue " + "x" * 200, "extracted"))
        self.assertEqual("usable", content_state("T", PROSE * 6 + " subscribe to continue", "extracted"))
        self.assertEqual("soft_404", content_state("T", "Page not found " + "x" * 50, "extracted"))
        self.assertEqual("soft_404", content_state("404 Not Found", BODY, "extracted"))
        self.assertEqual("usable", content_state("T", PROSE * 7 + " page not found", "extracted"))

    def test_a_login_wall_is_its_own_state_not_usable_prose(self):
        login = ("Sign in to continue\n\nEmail\n\nPassword\n\n"
                 "[Forgot password](https://example.test/reset)\n")
        self.assertEqual("login_required", content_state("Sign in - Example", login, "extracted"))
        self.assertEqual("login_required", content_state("统一身份认证", "请登录\n\n账号\n\n密码\n", "extracted"))
        # The same words deep inside a long article are its subject, not its state.
        self.assertEqual("usable", content_state("T", PROSE * 7 + "Sign in to continue", "extracted"))


class PublishedAtTests(unittest.TestCase):
    def test_provider_metadata_wins_and_is_normalized_to_a_day(self):
        for value in ("2026-09-08", "September 8, 2026", "2026-09-08T10:00:00Z", "2026/9/8"):
            with self.subTest(value=value):
                self.assertEqual(("2026-09-08", "provider_metadata", "high"), published_at(BODY, value))

    def test_an_unparseable_provider_value_falls_through_to_the_page(self):
        self.assertEqual(("2026-10-06", "body_date", "low"),
                         published_at("Posted on 2026-10-06 by Example", "not a date"))

    def test_labelled_page_fields_are_structured_metadata(self):
        for text in ('prefix {"datePublished": "2026-10-06"}',
                     '<meta property="article:published_time" content="2026-10-06">',
                     '<time datetime="2026-10-06">',
                     "Published: 2026-10-06\n\nbody",
                     "发布日期：2026年10月6日\n\n正文"):
            with self.subTest(text=text):
                self.assertEqual(("2026-10-06", "structured_metadata", "high"), published_at(text, None))

    def test_a_bare_date_near_the_top_is_low_confidence(self):
        self.assertEqual(("2026-10-06", "body_date", "low"), published_at("OCT. 6, 2026\n" + BODY, None))
        self.assertEqual((None, None, None), published_at("x" * 1600 + " OCT. 6, 2026", None))
        self.assertEqual((None, None, None), published_at("no dates here", None))
        self.assertEqual((None, None, None), published_at(None, None))
        self.assertEqual((None, None, None), published_at(BODY, "2026-13-40"))

    def test_a_bare_future_date_is_not_a_publication_date_but_a_labelled_one_is(self):
        self.assertIsNone(published_at("OCT. 6, 2026", None, reference="2026-10-05T00:00:00+00:00")[0])
        self.assertEqual("2026-10-06", published_at("OCT. 6, 2026", None, reference="2026-10-06T08:00:00+00:00")[0])
        self.assertEqual("2026-10-06", published_at(BODY, "2026-10-06", reference="2026-01-01T00:00:00+00:00")[0])


class EvidenceWiringTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-evidence-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.archive = SourceArchive(self.base / "knowledge")

    def capture(self, response, urls):
        return self.archive.save({"provider": "exa", "tool": "web_fetch_exa", "result": response,
            "urls": urls, "retrieved_at": "2026-10-18T00:00:00+00:00",
            "request_arguments": {"urls": urls, "maxCharacters": 12000}, "requested_max_characters": 12000})

    def test_a_capture_manifest_records_state_and_date_for_each_page(self):
        urls = ["https://example.test/dated", "https://example.test/empty"]
        raw = {"content": [{"type": "text", "text":
            "# Dated\nURL: " + urls[0] + "\nPublished: 2026-10-06\n\n" + BODY +
            "\n\n# Empty\nURL: " + urls[1] + "\n\nNo additional info available"}]}
        first, second = self.capture(raw, urls)["pages"]
        self.assertEqual("usable", first["content_state"])
        self.assertEqual("2026-10-06", first["published_at"])
        self.assertEqual("provider_metadata", first["published_at_source"])
        self.assertEqual("high", first["published_at_confidence"])
        self.assertEqual("content_insufficient", second["content_state"])
        self.assertIsNone(second["published_at"])
        self.assertIsNone(second["published_at_source"])

    def test_compact_fetch_pages_carry_the_same_fields(self):
        urls = ["https://example.test/page"]
        raw = {"content": [{"type": "text", "text": "# Dated\nURL: " + urls[0] + "\nPublished: 2026-10-06\n\n" + BODY}]}
        successful = {"provider": "exa", "urls": urls, "result": raw,
                      "archive": self.capture(raw, urls), "status": "ok"}
        fetched = SearchProviders._fetch_waterfall(urls, ["exa"], lambda name, pending: successful)
        page = SourceArchive.compact_fetch(fetched)["pages"][0]
        self.assertEqual("usable", page["content_state"])
        self.assertEqual("2026-10-06", page["published_at"])
        self.assertEqual("provider_metadata", page["published_at_source"])
        self.assertEqual("high", page["published_at_confidence"])
        self.assertEqual(page["published_at"], page["provider_published_at"])

    def test_fetch_coverage_reports_state_and_date_per_url(self):
        urls = ["https://example.test/dated", "https://example.test/missing"]
        data = {"results": [{"url": urls[0], "markdown": BODY, "publishedDate": "2026-10-06"}],
                "errors": [{"url": urls[1], "error": "Not available"}]}
        raw = {"structuredContent": data, "content": [{"type": "text", "text": json.dumps(data)}]}
        coverage = SearchProviders._fetch_coverage(raw, urls, "2026-10-18T00:00:00+00:00")
        rows = {row["url"]: row for row in coverage["per_url"]}
        self.assertEqual("usable", rows[urls[0]]["content_state"])
        self.assertEqual("2026-10-06", rows[urls[0]]["published_at"])
        self.assertEqual("provider_metadata", rows[urls[0]]["published_at_source"])
        self.assertEqual("unavailable", rows[urls[1]]["content_state"])
        self.assertIsNone(rows[urls[1]]["published_at"])

    def test_the_saved_fixture_reproduces_the_three_plan_cases(self):
        # The raw Exa response captured on 2026-10-18 for the three URLs the
        # beta.15 plan named, replayed offline so the verdicts cannot drift.
        fixture = json.loads((Path(__file__).parent / "fixtures"
                              / "exa-fetch-evidence-states-20261018.json").read_text(encoding="utf-8"))
        urls = ["https://developers.googleblog.com/embeddinggemma-2-the-developer-guide/",
                "https://developers.google.com/edge/foresight",
                "https://www.deepseek.com/harness/"]
        pages = {page["requested_url"]: page for page in self.capture(fixture, urls)["pages"]}
        blog, shell, harness = (pages[url] for url in urls)
        self.assertEqual("usable", blog["content_state"])
        self.assertEqual("2026-10-06", blog["published_at"])
        self.assertEqual("provider_metadata", blog["published_at_source"])
        self.assertEqual("high", blog["published_at_confidence"])
        # Title and link chrome only: a definite verdict instead of a silent "ok".
        self.assertEqual("js_shell_suspected", shell["content_state"])
        self.assertIsNone(shell["published_at"])
        self.assertEqual("usable", harness["content_state"])
        self.assertIsNone(harness["published_at"])


class LivenessTests(unittest.TestCase):
    def test_only_urls_without_a_body_are_probed_and_only_404_or_410_is_dead(self):
        import urllib.error
        from unittest.mock import patch
        fetched = {"provider": "exa", "per_url": [
            {"url": "https://a.example/gone", "status": "unverified", "extraction_status": "request_failed"},
            {"url": "https://a.example/present", "status": "ok", "extraction_status": "extracted"},
            {"url": "https://a.example/unknown", "status": "unverified", "extraction_status": "request_failed"}]}
        probed = []
        def opened(request, timeout):
            probed.append(request.full_url)
            if request.full_url.endswith("/gone"):
                raise urllib.error.HTTPError(request.full_url, 410, "Gone", {}, None)
            raise urllib.error.URLError("unreachable")
        with patch("urllib.request.urlopen", side_effect=opened):
            result = SearchProviders._with_liveness(fetched)
        self.assertEqual(["https://a.example/gone"], result["dead_urls"])
        self.assertEqual(["dead", "not_probed", "unknown"], [row["liveness"] for row in result["per_url"]])
        self.assertEqual(["https://a.example/gone", "https://a.example/unknown"], probed)

    def test_a_refused_head_falls_back_to_one_get_and_success_is_still_unknown(self):
        import io
        import urllib.error
        from unittest.mock import patch
        methods = []
        def opened(request, timeout):
            methods.append(request.get_method())
            if request.get_method() == "HEAD":
                raise urllib.error.HTTPError(request.full_url, 405, "Method Not Allowed", {}, None)
            return io.BytesIO(b"")
        with patch("urllib.request.urlopen", side_effect=opened):
            self.assertEqual("unknown", SearchProviders._liveness("https://a.example/page"))
        self.assertEqual(["HEAD", "GET"], methods)


class CorroborationTests(unittest.TestCase):
    def test_two_providers_returning_one_url_are_marked_corroborated(self):
        from search_results import fuse_results
        def batch(provider, urls):
            return {"provider": provider, "target": "alpha", "query": "alpha docs", "status": "ok",
                    "results": [{"url": url, "title": url, "snippet": "s"} for url in urls]}
        fused = fuse_results({"limit_per_target": 5, "batches": [
            batch("exa", ["https://a.example/shared", "https://a.example/only"]),
            batch("parallel", ["https://a.example/shared"])]})
        hits = {row["url"]: row for row in fused["targets"][0]["results"]}
        self.assertTrue(hits["https://a.example/shared"]["corroborated"])
        self.assertEqual(2, hits["https://a.example/shared"]["provider_count"])
        self.assertFalse(hits["https://a.example/only"]["corroborated"])
        self.assertEqual(1, hits["https://a.example/only"]["provider_count"])
        self.assertIn("link overlap", fused["ranking"]["corroborated"])


if __name__ == "__main__":
    unittest.main()
