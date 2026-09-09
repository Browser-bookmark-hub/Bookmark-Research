import copy
import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from search_results import MAX_SNIPPET_CHARS, RRF_K, fuse_results


def batch(target="alpha", provider="exa", query="alpha docs", results=None, **extra):
    value = {"provider": provider, "target": target, "query": query,
             "status": "ok", "results": [] if results is None else results}
    value.update(extra)
    return value


def hit(url, title="Title", **extra):
    return dict(url=url, title=title, **extra)


class FuseResultsTests(unittest.TestCase):
    def test_each_target_has_its_own_limit_and_ranking(self):
        output = fuse_results({"targets": ["alpha", "beta"], "limit_per_target": 1, "batches": [
            batch(results=[hit("https://a.example/1"), hit("https://a.example/2")]),
            batch(provider="tavily", results=[hit("https://a.example/2")]),
            batch(target="beta", query="beta docs", results=[hit("https://b.example/")]),
        ]})
        self.assertEqual(output["target_count"], 2)
        self.assertEqual([t["target"] for t in output["targets"]], ["alpha", "beta"])
        self.assertEqual([t["results"][0]["url"] for t in output["targets"]],
                         ["https://a.example/2", "https://b.example/"])
        self.assertTrue(output["targets"][0]["coverage"]["truncated"])
        self.assertFalse(output["targets"][1]["coverage"]["truncated"])

    def test_url_identity_preserves_queries_originals_and_provenance(self):
        original = "HTTPS://Example.COM:443/doc?lang=zh&utm_source=one#intro"
        same_page = "https://example.com/doc?lang=zh&utm_source=one#usage"
        different_page = "https://example.com/doc?lang=en&utm_source=one"
        output = fuse_results({"batches": [
            batch(results=[hit(original, snippet="Exa evidence")]),
            batch(provider="parallel", query="other query", results=[
                hit(same_page, text="Parallel evidence"), hit(different_page),
            ]),
        ]})
        results = output["targets"][0]["results"]
        self.assertEqual(len(results), 2)
        merged = results[0]
        self.assertEqual(merged["canonical_url"], "https://example.com/doc?lang=zh&utm_source=one")
        self.assertEqual(set(merged["raw_urls"]), {original, same_page})
        self.assertEqual(merged["provider_count"], 2)
        self.assertEqual(merged["evidence_count"], 2)
        self.assertEqual({s["snippet"] for s in merged["sources"]}, {"Exa evidence", "Parallel evidence"})
        self.assertAlmostEqual(merged["rrf_score"], 2 / (RRF_K + 1))
        self.assertFalse(output["ranking"]["independent_fact_confirmation"])

    def test_does_not_merge_query_order_tracking_params_schemes_or_routes(self):
        urls = [
            "https://example.com/p?a=1&b=2", "https://example.com/p?b=2&a=1",
            "https://example.com/p?a=1&b=2&utm_source=x", "http://example.com/p?a=1&b=2",
            "https://example.com/#/page-one", "https://example.com/#/page-two",
        ]
        output = fuse_results({"batches": [batch(results=[hit(url) for url in urls])]})
        self.assertEqual(len(output["targets"][0]["results"]), len(urls))

    def test_duplicate_batches_and_urls_do_not_add_score_or_evidence(self):
        one = batch(results=[hit("https://example.com/p", snippet="evidence")])
        baseline = fuse_results({"batches": [one]})["targets"][0]["results"][0]
        repeated = copy.deepcopy(one)
        repeated["provider"] = " EXA "
        repeated["results"].append(hit("https://EXAMPLE.com:443/p#fragment", rank=8))
        output = fuse_results({"batches": [one, repeated, one]})
        target = output["targets"][0]
        merged = target["results"][0]
        self.assertEqual(merged["rrf_score"], baseline["rrf_score"])
        self.assertEqual(merged["evidence_count"], 1)
        self.assertEqual(len(merged["sources"]), 1)
        self.assertEqual(target["coverage"]["submitted_batches"], 3)
        self.assertEqual(target["coverage"]["unique_queries"], 1)
        self.assertEqual(output["mode"], "single_provider_single_query")

    def test_empty_http_path_is_the_root_without_merging_other_trailing_slashes(self):
        output = fuse_results({"batches": [
            batch(results=[hit("https://example.com"), hit("https://example.com/page")]),
            batch(provider="parallel", results=[hit("https://example.com/"), hit("https://example.com/page/")]),
        ]})
        results = output["targets"][0]["results"]
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["canonical_url"], "https://example.com/")
        self.assertEqual(results[0]["provider_count"], 2)
        self.assertAlmostEqual(results[0]["rrf_score"], 2 / (RRF_K + 1))

    def test_single_provider_many_queries_is_never_multi_provider(self):
        output = fuse_results({"batches": [
            batch(query="company docs", results=[hit("https://example.com/")]),
            batch(query="company api", results=[hit("https://example.com/")]),
        ]})
        self.assertEqual(output["provider_count"], 1)
        self.assertEqual(output["mode"], "single_provider_multi_query")
        self.assertEqual(output["targets"][0]["results"][0]["evidence_count"], 2)

    def test_failures_and_missing_targets_remain_visible(self):
        output = fuse_results({"targets": ["alpha", "beta", "missing", "empty"], "batches": [
            batch(results=[hit("https://example.com/")]),
            batch(provider="tavily", status="error", error="rate limited"),
            batch(target="beta", query="beta docs", status="error", error="timeout"),
            batch(target="empty", query="nothing"),
        ]})
        self.assertEqual([t["status"] for t in output["targets"]], ["partial", "error", "missing", "empty"])
        self.assertEqual(output["missing_targets"], ["missing"])
        self.assertEqual(output["uncovered_targets"], ["beta", "missing", "empty"])
        self.assertEqual(output["provider_count"], 2)
        self.assertEqual(output["successful_provider_count"], 1)
        self.assertEqual([e["error"] for e in output["errors"]], ["rate limited", "timeout"])

    def test_retry_failure_is_kept_without_inflating_query_count(self):
        output = fuse_results({"batches": [
            batch(status="error", error="temporary outage"),
            batch(results=[hit("https://example.com/")]),
        ]})
        target = output["targets"][0]
        self.assertEqual(target["query_count"], 1)
        self.assertEqual(target["coverage"]["successful_queries"], 1)
        self.assertEqual(target["coverage"]["failed_queries"], 1)
        self.assertEqual(target["status"], "partial")
        self.assertEqual(target["results"][0]["evidence_count"], 1)

    def test_malformed_results_are_flagged_and_never_returned_as_links(self):
        bad = [hit("javascript:alert(1)"), hit("file:///tmp/a"), hit("https://"),
               hit("https://host:99999/a"), hit("https://bad host/a"),
               hit("https://user:pass@host/a"), hit("https://host/\n"),
               hit("https://example.com/", rank=0), hit("https://example.com/", rank=True),
               hit("https://example.com/", rank=10 ** 500), hit("https://[v1.fe]/"),
               hit("https://example.com/", text=[]), {}, None]
        output = fuse_results({"batches": [batch(results=bad + [hit("https://valid.example/")])]})
        target = output["targets"][0]
        self.assertEqual([h["url"] for h in target["results"]], ["https://valid.example/"])
        self.assertEqual(len(output["invalid_results"]), len(bad))
        self.assertEqual(target["status"], "partial")
        self.assertTrue(all("reason" in entry for entry in output["invalid_results"]))

    def test_bad_batches_do_not_discard_valid_siblings(self):
        output = fuse_results({"batches": [None, {}, batch(provider=""), batch(status="unknown"),
                                           batch(results="bad"), batch(results=[hit("https://ok.example/")])]})
        self.assertEqual(len(output["errors"]), 5)
        self.assertEqual(output["targets"][0]["results"][0]["url"], "https://ok.example/")
        self.assertEqual(output["targets"][0]["status"], "partial")
        json.dumps(output)

    def test_rejects_malformed_top_level_configuration(self):
        for payload in [None, [], {}, {"batches": {}}, {"batches": [], "limit_per_target": False},
                        {"batches": [], "limit_per_target": 0}, {"batches": [], "limit_per_target": 1.5},
                        {"batches": [], "targets": "alpha"}, {"batches": [], "targets": [None]}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                fuse_results(payload)

    def test_snippets_are_bounded_without_mutating_input(self):
        payload = {"batches": [batch(results=[hit("https://example.com/", text="x" * 10000)])]}
        before = copy.deepcopy(payload)
        output = fuse_results(payload)
        source = output["targets"][0]["results"][0]["sources"][0]
        self.assertEqual(len(source["snippet"]), MAX_SNIPPET_CHARS)
        self.assertTrue(source["snippet_truncated"])
        self.assertEqual(payload, before)
        self.assertLess(len(json.dumps(output)), 4000)

    def test_empty_input_and_duplicate_requested_targets(self):
        empty = fuse_results({"batches": []})
        self.assertEqual(empty["target_count"], 0)
        self.assertEqual(empty["mode"], "no_provider")
        missing = fuse_results({"batches": [], "targets": ["alpha", "alpha", "beta"]})
        self.assertEqual(missing["target_count"], 2)
        self.assertEqual(missing["missing_targets"], ["alpha", "beta"])

    def test_ipv6_default_ports_and_empty_queries_keep_conservative_identity(self):
        urls = ["https://[2001:DB8::1]:443/path#section", "https://[2001:db8::1]/path",
                "https://[2001:db8::1]:444/path", "https://example.com/path?", "https://example.com/path"]
        output = fuse_results({"batches": [batch(results=[hit(url) for url in urls])]})
        self.assertEqual(output["invalid_results"], [])
        results = output["targets"][0]["results"]
        self.assertEqual(len(results), 4)
        merged = next(row for row in results if row["canonical_url"] == "https://[2001:db8::1]/path")
        self.assertEqual(len(merged["raw_urls"]), 2)
        self.assertEqual(merged["evidence_count"], 1)


if __name__ == "__main__":
    unittest.main()
