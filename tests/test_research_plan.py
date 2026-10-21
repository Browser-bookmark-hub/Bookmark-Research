"""A question becomes a bounded local scope and a route suggestion, nothing more."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_bookmark_index import make_package

from bookmark_index import BookmarkIndex, url_kind
from mcp_server import StdioMcpServer
from raw_library import RawLibrary
from research_plan import ResearchPlan
from routing import ResearchRouting
from settings import Settings
from source_manager import SourceManager
from wiki import WikiStore

ALPHA = "https://example.test/alpha"


def write_card(root, name, section_id, label, items):
    """One temporary card under the protocol directory the importer requires."""
    path = root / "临时栏目" / "常规链式" / (name + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": "bookmark-canvas-section", "schemaVersion": 2,
        "id": section_id, "sectionType": "temporary", "label": label, "title": label + " card",
        "items": [{"id": "b%d" % index, "sectionId": section_id, **item} for index, item in enumerate(items)]},
        ensure_ascii=False), encoding="utf-8")


class ResearchPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(self.root / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.db = self.root / "index.sqlite3"
        self.settings = Settings(self.root / "settings.json")

    def indexed(self, build=make_package):
        package = Path(tempfile.mkdtemp(dir=self.root))
        build(package)
        index = BookmarkIndex(self.db)
        self.addCleanup(index.close)
        return index, SourceManager(index).sync(package, mode="snapshot")["source_id"]

    def test_terms_are_literal_runs_with_cjk_bigrams_and_single_characters_dropped(self):
        terms = BookmarkIndex.plan_terms("EmbeddingGemma 2 怎么本地部署")
        self.assertIn("EmbeddingGemma", terms)
        self.assertIn("本地", terms)
        self.assertIn("部署", terms)
        self.assertNotIn("2", terms)
        self.assertLessEqual(len(terms), 12)
        self.assertEqual(BookmarkIndex.plan_terms("Lumen"), ["Lumen"])
        self.assertEqual(BookmarkIndex.plan_terms("书"), ["书"])
        self.assertEqual(BookmarkIndex.plan_terms("A"), [])
        for bad in ("", "   ", None, 7):
            with self.assertRaises(ValueError):
                BookmarkIndex.plan_terms(bad)

    def two_common_one_rare(self, root):
        write_card(root, "R1 稀有", "temp-section-R1", "R1",
                   [{"type": "bookmark", "title": "EmbeddingGemma 2", "url": "https://example.test/rare"}])
        write_card(root, "P1 常见", "temp-section-P1", "P1",
                   [{"type": "bookmark", "title": "Lumen one", "url": "https://example.test/junk1"}])
        write_card(root, "P2 常见", "temp-section-P2", "P2",
                   [{"type": "bookmark", "title": "Lumen two", "url": "https://example.test/junk2"}])
        write_card(root, "B 两者", "temp-section-B", "B",
                   [{"type": "bookmark", "title": "EmbeddingGemma guide", "url": "https://example.test/both"},
                    {"type": "bookmark", "title": "Lumen three", "url": "https://example.test/junk3"}])

    def test_a_specific_term_outranks_a_common_one(self):
        index, source_id = self.indexed(self.two_common_one_rare)
        scope = index.plan_scope(source_id, "EmbeddingGemma Lumen")
        # The question only ever names terms; nothing tells the tool which card
        # matters. Weight is term length over the number of cards it matches:
        # EmbeddingGemma (14/2) beats Lumen (5/3), and a card matching both wins.
        self.assertEqual(["B", "R1", "P1"], [card["label"] for card in scope["cards"]])
        self.assertEqual(["EmbeddingGemma", "Lumen"], scope["cards"][0]["matched_terms"])
        self.assertGreater(scope["cards"][0]["score"], scope["cards"][1]["score"])
        self.assertGreater(scope["cards"][1]["score"], scope["cards"][2]["score"])
        # Raw instance counts do not decide the URL order: the rare card's URL
        # comes before a common card's URL that has just as many instances.
        urls = [row["url"] for row in scope["urls"]]
        self.assertEqual("https://example.test/both", urls[0])
        self.assertLess(urls.index("https://example.test/rare"), urls.index("https://example.test/junk1"))

    def common_card_holding_only_generic_urls(self, root):
        write_card(root, "Y 混合", "temp-section-Y", "Y",
                   [{"type": "bookmark", "title": "EmbeddingGemma guide", "url": "https://example.test/y-rare"},
                    {"type": "bookmark", "title": "CommonWord one", "url": "https://example.test/y1"},
                    {"type": "bookmark", "title": "CommonWord two", "url": "https://example.test/y2"}])
        write_card(root, "X 稀有", "temp-section-X", "X",
                   [{"type": "bookmark", "title": "EmbeddingGemma api", "url": "https://example.test/x-rare"}])
        for name in ("C1", "C2", "C3"):
            write_card(root, name, "temp-section-" + name, name,
                       [{"type": "bookmark", "title": "CommonWord " + name,
                         "url": "https://example.test/" + name.lower()}])

    def test_a_urls_own_term_decides_its_order_not_the_card_it_sits_in(self):
        index, source_id = self.indexed(self.common_card_holding_only_generic_urls)
        scope = index.plan_scope(source_id, "EmbeddingGemma CommonWord")
        # Y ranks first because it matched both terms, but the two URLs that
        # matched the specific name come first: relevance is the URL's own term.
        self.assertEqual(["Y", "X", "C1"], [card["label"] for card in scope["cards"]])
        urls = [row["url"] for row in scope["urls"]]
        self.assertEqual("https://example.test/y-rare", urls[0])
        self.assertEqual("https://example.test/x-rare", urls[1])
        self.assertLess(urls.index("https://example.test/x-rare"), urls.index("https://example.test/y1"))

    def test_a_question_with_no_searchable_term_is_reported(self):
        index, source_id = self.indexed()
        scope = index.plan_scope(source_id, "A")
        self.assertEqual([], scope["terms"])
        self.assertEqual([], scope["cards"])
        self.assertEqual([], scope["urls"])
        self.assertEqual(1, len(scope["errors"]))
        self.assertIn("no searchable term", scope["errors"][0])

    def test_one_url_in_two_cards_is_reported_once_with_both_instances(self):
        index, source_id = self.indexed()
        scope = index.plan_scope(source_id, "alpha")
        self.assertEqual(2, len(scope["cards"]))
        self.assertEqual([1, 1], [card["hits"] for card in scope["cards"]])
        self.assertEqual([["alpha"]], [card["matched_terms"] for card in scope["cards"][:1]])
        # The copy anchor shares the primary card's tree; it must not take a slot.
        self.assertTrue(all(card["anchor_of"] is None for card in scope["cards"]))
        self.assertEqual([2, 3], sorted(card["bookmarks"] for card in scope["cards"]))
        self.assertEqual([ALPHA], [row["url"] for row in scope["urls"]])
        self.assertEqual([2], [row["instances"] for row in scope["urls"]])
        self.assertEqual([2], [row["source_instances"] for row in scope["urls"]])
        self.assertEqual(2, len(scope["urls"][0]["section_ids"]))
        self.assertFalse(scope["truncated"])
        self.assertEqual([], scope["errors"])

    def test_urls_are_limited_and_the_truncation_is_disclosed(self):
        index, source_id = self.indexed()
        scope = index.plan_scope(source_id, "example", max_urls=2)
        self.assertEqual(2, len(scope["urls"]))
        self.assertTrue(scope["truncated"])
        self.assertLess(len(scope["urls"]), index.search(source_id, targets=["example"])["total"])
        untruncated = index.plan_scope(source_id, "example", max_urls=8)
        self.assertFalse(untruncated["truncated"])

    def test_limits_and_unknown_sources_are_refused(self):
        index, source_id = self.indexed()
        for limits in ({"max_cards": 0}, {"max_cards": 4}, {"max_cards": True},
                       {"max_urls": 0}, {"max_urls": 9}, {"max_urls": True}):
            with self.assertRaises(ValueError):
                index.plan_scope(source_id, "alpha", **limits)
        with self.assertRaises(ValueError):
            index.plan_scope("missing-source", "alpha")
        with self.assertRaises(ValueError):
            index.plan_scope(source_id, "")

    def test_no_match_is_reported_instead_of_widened(self):
        index, source_id = self.indexed()
        scope = index.plan_scope(source_id, "zzzqqqvvv")
        self.assertEqual([], scope["cards"])
        self.assertEqual([], scope["urls"])
        self.assertFalse(scope["truncated"])
        self.assertEqual(1, len(scope["errors"]))
        self.assertIn("No bookmark", scope["errors"][0])

    def test_a_title_only_match_returns_a_url_that_does_not_contain_the_term(self):
        index, source_id = self.indexed(lambda root: write_card(
            root, "A-9 仅标题", "temp-section-A-9", "A-9",
            [{"type": "bookmark", "title": "Lumen unlinked", "url": "https://example.test/plain"}]))
        scope = index.plan_scope(source_id, "Lumen")
        self.assertEqual(["A-9"], [card["label"] for card in scope["cards"]])
        self.assertEqual(["Lumen"], scope["cards"][0]["matched_terms"])
        # Discovery is by card, not by URL text: the bookmark matched on its
        # title, so its URL is returned even though the term is absent from it.
        self.assertEqual(["https://example.test/plain"], [row["url"] for row in scope["urls"]])
        self.assertEqual([], scope["errors"])

    def test_task_shape_and_route_come_from_the_existing_route_vocabulary(self):
        index, source_id = self.indexed()
        router = ResearchRouting(self.settings)
        plan = ResearchPlan(index=index, settings=self.settings)
        cases = (("Read https://example.test/1 directly", "lookup"),
                 ("alpha 是什么", "investigation"),
                 ("alpha 的深度对比报告", "batch_research"))
        for question, expected_shape in cases:
            built = plan.build(source_id, question)
            self.assertEqual(expected_shape, built["task_shape"], question)
            self.assertTrue(built["task_shape_reason"])
            route = router.route(task_shape=built["task_shape"], host="unknown", depth=None)
            self.assertEqual(route["selected"]["route"], built["route"], question)
            self.assertIn(built["route"], {candidate["route"] for candidate in route["candidates"]})
            self.assertEqual(route["depth"], built["depth"])
            self.assertEqual(route["next_action"], built["next_action"])

    def test_documentation_and_repository_hosts_are_treated_as_known_urls(self):
        for url, expected, marker in (
                ("https://github.com/example/lumen", "lookup", "github.com"),
                ("https://developers.google.com/edge/foresight", "lookup", "developers.google.com"),
                ("https://unsloth.ai/docs/zh/mo-xing/embeddinggemma-2", "investigation", ""),
                ("https://example.test/lumen", "investigation", "")):
            with self.subTest(url=url):
                index, source_id = self.indexed(lambda root: write_card(
                    root, "A-8 来源", "temp-section-A-8", "A-8",
                    [{"type": "bookmark", "title": "Lumen", "url": url}]))
                built = ResearchPlan(index=index, settings=self.settings).build(source_id, "Lumen 怎么用")
                self.assertEqual(expected, built["task_shape"])
                if marker:
                    self.assertIn(marker, built["task_shape_reason"])

    def test_question_urls_are_extracted_and_stripped_from_terms(self):
        index, source_id = self.indexed()
        question = "对比 https://a.test/x 和 https://b.test/y"
        self.assertEqual(["https://a.test/x", "https://b.test/y"], ResearchPlan.question_urls(question))
        # The URL is an instruction to read it, not a search term: its scheme
        # and host would otherwise match half the package.
        self.assertEqual(["对比", "和"], BookmarkIndex.plan_terms(question))
        built = ResearchPlan(index=index, settings=self.settings).build(source_id, question)
        self.assertEqual("lookup", built["task_shape"])
        self.assertEqual(["https://a.test/x", "https://b.test/y"], built["question_urls"])

    def topic_with_incidental_docs(self, root):
        write_card(root, "T 主题", "temp-section-T", "T",
                   [{"type": "bookmark", "title": "企业落地 案例", "url": "https://example.test/topic"}])
        write_card(root, "D 大卡", "temp-section-D", "D",
                   [{"type": "bookmark", "title": "RAG 企业落地 指南", "url": "https://docs.example.test/guide"},
                    {"type": "bookmark", "title": "RAG 概览", "url": "https://docs.example.test/overview"}])
        # A third card keeps RAG a common word here; in a two-card fixture the
        # term itself would reach one tree and read as a name.
        write_card(root, "T2 资料", "temp-section-T2", "T2",
                   [{"type": "bookmark", "title": "RAG 资料", "url": "https://example.test/rag-notes"}])

    def test_a_topic_question_is_not_downgraded_by_an_incidental_documentation_bookmark(self):
        index, source_id = self.indexed(self.topic_with_incidental_docs)
        built = ResearchPlan(index=index, settings=self.settings).build(source_id, "RAG 企业落地")
        # Every term here reaches two cards, so none of them names the docs page:
        # it stays evidence and does not decide the route.
        self.assertEqual("investigation", built["task_shape"])
        self.assertTrue(any(row["url"] == "https://docs.example.test/guide" for row in built["urls"]))

    def big_tree_and_topic_card(self, root):
        big = [{"type": "bookmark", "title": "Alpha Beta guide %d" % index,
                "url": "https://example.test/big/%d" % index} for index in range(2)]
        big += [{"type": "bookmark", "title": "Unrelated note %d" % index,
                 "url": "https://example.test/fill/%d" % index} for index in range(30)]
        write_card(root, "BIG 永久树", "temp-section-BIG", "BIG", big)
        write_card(root, "TOPIC 主题卡", "temp-section-TOPIC", "TOPIC",
                   [{"type": "bookmark", "title": "Alpha entry %d" % index,
                     "url": "https://example.test/topic/%d" % index} for index in range(9)])

    def test_card_density_outweighs_a_large_tree(self):
        index, source_id = self.indexed(self.big_tree_and_topic_card)
        scope = index.plan_scope(source_id, "Alpha Beta")
        # Raw weight favors the big tree (it matched both terms); density
        # (hits/bookmarks) puts the 9-of-9 topic card first, which raw hits
        # alone would not have done either.
        self.assertEqual(["TOPIC", "BIG"], [card["label"] for card in scope["cards"]])
        self.assertEqual(1.0, scope["cards"][0]["density"])
        self.assertAlmostEqual(2 / 32, scope["cards"][1]["density"], places=6)
        self.assertEqual({"Alpha": 2, "Beta": 1}, {term: count for term, count in scope["term_cards"].items()})
        self.assertEqual(["Alpha"], scope["cards"][0]["matched_terms"])

    def test_empty_scope_returns_no_route(self):
        index, source_id = self.indexed()
        plan = ResearchPlan(index=index, settings=self.settings)
        built = plan.build(source_id, "zzzqqqvvv")
        self.assertEqual([], built["cards"])
        self.assertEqual(1, len(built["errors"]))
        self.assertIsNone(built["route"])
        self.assertIsNone(built["route_id"])
        self.assertIsNone(built["entrypoint"])
        self.assertIsNone(built["depth"])
        self.assertIn("nothing", built["next_action"]["reason"])
        # A question that carries its own URL still gets the direct route even
        # when the package has no matching card.
        carried = plan.build(source_id, "Read https://a.test/x now")
        self.assertEqual("lookup", carried["task_shape"])
        self.assertEqual("direct_retrieval", carried["route"])

    def test_saved_depth_setting_is_respected(self):
        index, source_id = self.indexed()
        self.settings.update({"research": {"depth": "deep"}})
        plan = ResearchPlan(index=index, settings=self.settings)
        built = plan.build(source_id, "alpha 是什么")
        self.assertEqual("deep", built["depth"])
        expected = ResearchRouting(self.settings).route(task_shape=built["task_shape"], host="unknown", depth=None)
        self.assertEqual(expected["selected"]["route"], built["route"])
        self.assertEqual(expected["depth"], built["depth"])

    def test_the_tool_is_reachable_over_mcp(self):
        index, source_id = self.indexed()
        server = StdioMcpServer(self.db, settings=self.settings)
        self.addCleanup(server.close)
        server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                       "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                  "clientInfo": {"name": "fixture", "version": "1"}}})
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        listing = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertIn("plan_research", {tool["name"] for tool in listing})

        def call(arguments):
            return server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "plan_research", "arguments": arguments}})

        response = call({"source_id": source_id, "question": "alpha", "refresh": False})
        self.assertFalse(response["result"]["isError"], response)
        payload = response["result"]["structuredContent"]
        self.assertEqual([ALPHA], [row["url"] for row in payload["urls"]])
        self.assertEqual([], payload["question_urls"])
        self.assertEqual("investigation", payload["task_shape"])
        self.assertTrue(payload["route"])
        self.assertEqual(["search_web", "fetch_web"], payload["next_action"]["tools"])
        self.assertIn("wiki", payload)
        self.assertIn("archive", payload)
        self.assertIn("relevance", payload)
        self.assertIn("freshness", payload)
        self.assertIn("fetch", payload)
        self.assertIn("preflight_budget", payload)
        # A blank or partial question never reaches the tool: the server's
        # validator rejects it first, so no fetch or index work can happen.
        self.assertEqual(-32602, call({"source_id": source_id, "question": "   "})["error"]["code"])
        self.assertEqual(-32602, call({"source_id": source_id})["error"]["code"])
        self.assertEqual(-32602, call({"source_id": source_id, "question": "alpha", "max_urls": 9})["error"]["code"])

    def test_an_incidental_substring_does_not_become_a_lookup(self):
        items = [{"type": "bookmark", "title": "QuantumNous/new-api",
                  "url": "https://github.com/QuantumNous/new-api"}]
        items += [{"type": "bookmark", "title": "unrelated %d" % index,
                   "url": "https://example.test/fill/%d" % index} for index in range(9)]
        index, source_id = self.indexed(lambda root: write_card(
            root, "Q 量子", "temp-section-Q", "Q", items))
        built = ResearchPlan(index=index, settings=self.settings).build(
            source_id, "quantum entanglement agriculture breeding",
            include_wiki=False, include_archive=False)
        self.assertFalse(built["relevance"]["accepted"], built["relevance"])
        self.assertEqual([], built["cards"])
        self.assertEqual([], built["urls"])
        self.assertIsNone(built["route"])
        self.assertIn("single weak term", built["next_action"]["reason"])

    def test_a_single_cjk_entity_is_not_rejected_by_the_length_floor(self):
        index, source_id = self.indexed(lambda root: write_card(
            root, "书 单字", "temp-section-BOOK", "书",
            [{"type": "bookmark", "title": "书", "url": "https://example.test/book"}]))
        built = ResearchPlan(index=index, settings=self.settings).build(
            source_id, "书", include_wiki=False, include_archive=False)
        self.assertTrue(built["relevance"]["accepted"], built["relevance"])
        self.assertEqual(["书"], [card["label"] for card in built["cards"]])

    def test_a_long_unique_term_survives_the_single_hit_floor(self):
        items = [{"type": "bookmark", "title": "unique500", "url": "https://example.test/unique500"}]
        items += [{"type": "bookmark", "title": "filler %d" % index,
                   "url": "https://example.test/filler/%d" % index} for index in range(25)]
        index, source_id = self.indexed(lambda root: write_card(
            root, "U 唯一", "temp-section-UNIQUE", "U", items))
        built = ResearchPlan(index=index, settings=self.settings).build(
            source_id, "unique500", include_wiki=False, include_archive=False)
        self.assertTrue(built["relevance"]["accepted"], built["relevance"])
        self.assertEqual(["U"], [card["label"] for card in built["cards"]])

    def test_two_letter_uppercase_acronyms_count_as_meaningful(self):
        items = [{"type": "bookmark", "title": "书签 AI 升级", "url": "https://example.test/ai"}]
        items += [{"type": "bookmark", "title": "filler %d" % index,
                   "url": "https://example.test/filler/%d" % index} for index in range(9)]
        index, source_id = self.indexed(lambda root: write_card(
            root, "A 缩写", "temp-section-ACRONYM", "A", items))
        built = ResearchPlan(index=index, settings=self.settings).build(
            source_id, "书签 AI", include_wiki=False, include_archive=False)
        self.assertTrue(built["relevance"]["accepted"], built["relevance"])
        self.assertIn("AI", built["relevance"]["meaningful_terms"])

    def test_a_single_weak_cjk_term_is_rejected(self):
        items = [{"type": "bookmark", "title": "量子位 | AI", "url": "https://www.qbitai.com/"}]
        items += [{"type": "bookmark", "title": "unrelated %d" % index,
                   "url": "https://example.test/unrelated/%d" % index} for index in range(9)]
        index, source_id = self.indexed(lambda root: write_card(
            root, "W 弱词", "temp-section-W", "W", items))
        built = ResearchPlan(index=index, settings=self.settings).build(
            source_id, "量子纠缠在农业育种中的应用",
            include_wiki=False, include_archive=False)
        self.assertGreater(built["relevance"]["score"], built["relevance"]["min_relevance"])
        self.assertFalse(built["relevance"]["accepted"], built["relevance"])
        self.assertEqual([], built["cards"])
        self.assertIsNone(built["route"])

    def test_a_stale_missing_card_does_not_take_a_top_slot_but_keeps_its_urls(self):
        def build(root):
            write_card(root, "A-10-2 缺失", "temp-section-M", "A-10-2",
                       [{"type": "bookmark", "title": "Agent Runtime docs",
                         "url": "https://docs.example.test/agent-runtime"}])
            write_card(root, "A-10 当前", "temp-section-C", "A-10",
                       [{"type": "bookmark", "title": "Agent Runtime home",
                         "url": "https://example.test/"}])
        index, source_id = self.indexed(build)
        record = json.loads(index.connection.execute(
            "SELECT record_json FROM source_records WHERE source_id=?", (source_id,)).fetchone()[0])
        package = Path(record["input_path"])
        (package / "临时栏目" / "常规链式" / "A-10-2 缺失.json").unlink()
        scope = index.plan_scope(source_id, "Agent Runtime 云厂商", max_cards=2, max_urls=4)
        self.assertEqual(["A-10"], [card["label"] for card in scope["cards"]])
        self.assertEqual(["临时栏目/常规链式/A-10-2 缺失.json"], scope["stale_missing_files"])
        stale = [row for row in scope["urls"] if row["stale"]]
        self.assertEqual(["https://docs.example.test/agent-runtime"],
                         [row["url"] for row in stale])
        self.assertEqual("docs", stale[0]["url_kind"])

    def test_url_kind_prefers_documentation_over_homepage_and_login(self):
        index, source_id = self.indexed(lambda root: write_card(
            root, "K 类型", "temp-section-K", "K", [
                {"type": "bookmark", "title": "Lumen", "url": "https://example.test/"},
                {"type": "bookmark", "title": "Lumen", "url": "https://docs.example.test/guide"},
                {"type": "bookmark", "title": "Lumen", "url": "https://github.com/acme/repo"},
                {"type": "bookmark", "title": "Lumen", "url": "https://login.example.test/auth"},
            ]))
        scope = index.plan_scope(source_id, "Lumen", max_urls=8)
        kinds = [row["url_kind"] for row in scope["urls"]]
        self.assertEqual({"docs", "repo"}, set(kinds[:2]))
        self.assertEqual({"homepage", "login"}, set(kinds[2:]))
        self.assertEqual("docs", url_kind("https://docs.example.test/guide"))
        self.assertEqual("repo", url_kind("https://github.com/acme/repo"))
        self.assertEqual("login", url_kind("https://login.example.test/auth"))
        self.assertEqual("homepage", url_kind("https://example.test/"))
        self.assertEqual("local_file", url_kind("file:///tmp/report.pdf"))

    def test_homepage_limit_caps_navigational_noise(self):
        index, source_id = self.indexed(lambda root: write_card(
            root, "H 首页", "temp-section-H", "H", [
                {"type": "bookmark", "title": "Lumen", "url": "https://one.example.test/"},
                {"type": "bookmark", "title": "Lumen", "url": "https://two.example.test/"},
                {"type": "bookmark", "title": "Lumen", "url": "https://three.example.test/"},
                {"type": "bookmark", "title": "Lumen", "url": "https://docs.example.test/guide"},
            ]))
        scope = index.plan_scope(source_id, "Lumen", max_urls=8, homepage_limit=1)
        kinds = [row["url_kind"] for row in scope["urls"]]
        self.assertEqual("docs", kinds[0])
        self.assertEqual(1, kinds.count("homepage"))
        self.assertEqual(2, len(scope["urls"]))

    def test_freshness_keeps_high_and_low_confidence_time(self):
        index, source_id = self.indexed(lambda root: write_card(
            root, "F 时间", "temp-section-F", "F", [
                {"type": "bookmark", "title": "Lumen", "url": "https://example.test/lumen",
                 "dateAdded": 1577836800000}]))
        built = ResearchPlan(index=index, settings=self.settings).build(
            source_id, "Lumen 最新变化", include_wiki=False, include_archive=False)
        self.assertTrue(built["freshness"]["intent"])
        self.assertEqual("high", built["freshness"]["confidence"])
        self.assertIsNotNone(built["freshness"]["newest_high"])
        self.assertTrue(built["freshness"]["stale"])

    def test_preflight_wires_wiki_and_archive_without_raw_text(self):
        class FakeWiki:
            terms = None
            def search_terms(self, terms, limit=3):
                self.terms = terms
                return [{"page_id": "p1", "status": "current", "matched_terms": ["alpha"],
                         "actions": ["wiki_get"]}]
        class FakeRaw:
            terms = None
            def search_terms(self, terms, limit=5):
                self.terms = terms
                return [{"capture_id": "c1", "url": "https://example.test/alpha",
                         "title": "alpha", "matched_terms": ["alpha"]}]
        index, source_id = self.indexed()
        wiki, raw = FakeWiki(), FakeRaw()
        built = ResearchPlan(index=index, settings=self.settings, wiki=wiki, raw=raw).build(
            source_id, "alpha", include_wiki=True, include_archive=True)
        self.assertEqual(["alpha"], wiki.terms)
        self.assertEqual(["alpha"], raw.terms)
        self.assertEqual("p1", built["wiki"][0]["page_id"])
        self.assertEqual("c1", built["archive"][0]["capture_id"])
        self.assertNotIn("text", built["wiki"][0])

    def test_wiki_search_terms_merges_terms_and_actions(self):
        store = object.__new__(WikiStore)
        def search(term, limit=10):
            status = "needs_review" if term == "RAG" else "current"
            issues = [{"code": "source_capture_expired"}] if status == "needs_review" else []
            return {"results": [
                {"page_id": "p1", "revision": 1, "title": "RAG 企业落地", "snippet": "RAG 企业",
                 "validation": {"status": status, "issues": issues}},
                {"page_id": "p2", "revision": 1, "title": "other", "snippet": "other",
                 "validation": {"status": "current", "issues": []}},
            ]}
        store.search = search
        rows = WikiStore.search_terms(store, ["RAG", "企业"], limit=3)
        page = next(row for row in rows if row["page_id"] == "p1")
        self.assertEqual(["RAG", "企业"], page["matched_terms"])
        self.assertIn("wiki_refresh", page["actions"])
        self.assertEqual(1, page["expired_count"])
        self.assertEqual("needs_review", page["status"])

    def test_archive_search_terms_merges_capture_pointers(self):
        library = object.__new__(RawLibrary)
        def search(term, limit=10, occurrence_limit=50):
            return {"results": [{
                "sha256": "s1", "url": "https://example.test/a", "title": "alpha doc",
                "characters": 100, "occurrences": [{
                    "kind": "archive", "capture_id": "cap1", "url": "https://example.test/a",
                    "title": "alpha doc", "retrieved_at": "2026-10-01T00:00:00Z"}]}]}
        library.search = search
        rows = RawLibrary.search_terms(library, ["alpha", "doc"], limit=3)
        self.assertEqual(1, len(rows))
        self.assertEqual("cap1", rows[0]["capture_id"])
        self.assertEqual(["alpha", "doc"], rows[0]["matched_terms"])


if __name__ == "__main__":
    unittest.main()
