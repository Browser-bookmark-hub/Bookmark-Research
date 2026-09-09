#!/usr/bin/env python3
"""Offline validation pack: source fidelity, context and a research lifecycle.

Default inputs are synthetic. --package additionally checks a user-supplied
package without changing it or sending anything to web providers.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bookmark_index import BookmarkIndex
from research import ResearchSessions
from search_results import fuse_results
from settings import Settings


def fingerprints(package):
    return {str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.rglob("*")) if path.is_file()}


def raw_counts(package):
    urls = []
    sections = 0
    def walk(items):
        for item in items:
            if isinstance(item.get("url"), str) and item["url"]:
                urls.append(item["url"])
            walk(item.get("children", []))
    for path in package.rglob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("format") != "bookmark-canvas-section":
            continue
        sections += 1
        if value.get("fileRole") == "copy-anchor":
            continue
        walk([value["tree"]] if "tree" in value else value.get("items", []))
    return {"bookmarks": len(urls), "unique_urls": len(set(urls)), "sections": sections}


class FixtureProvider:
    """Recorded fictional responses; never instantiates a network client."""

    def __init__(self, fixture):
        self.fixture = fixture

    def search(self, targets, providers, limit_per_target):
        batches = [{"provider": provider, "target": target["target"], "query": target["query"],
                    "status": "ok", "retrieved_at": "2026-09-10T00:00:00Z", "results": [
                        {"url": url, "title": self.fixture["pages"][url].get("title", "Unavailable fixture"),
                         "snippet": "Synthetic search snippet; read the fixture page for evidence."}
                        for url in self.fixture["search_results"][target["target"]]]}
                   for provider in providers for target in targets]
        return {**fuse_results({"batches": batches, "limit_per_target": limit_per_target}),
                "batches": batches, "usage": {"tool_calls": len(batches)}}

    def fetch(self, urls, provider, archive, max_characters):
        rows = [{"url": url, **self.fixture["pages"].get(url, {"error": "No synthetic response recorded for this URL"})}
                for url in urls]
        return {"provider": provider, "urls": urls, "tool": "fixture_fetch", "request_arguments": {"urls": urls},
                "retrieved_at": "2026-09-10T00:00:00Z", "requested_max_characters": max_characters,
                "usage": {"tool_calls": 1}, "result": {"structuredContent": {"results": rows}}}


def verify_package(package, output, expected=None, queries=()):
    before = fingerprints(package)
    expected_raw = raw_counts(package)
    with BookmarkIndex(output / "index.sqlite3") as index:
        first = index.sync(package, "validation")
        status = index.status("validation")
        for name, number in {**expected_raw, **(expected or {})}.items():
            if status["counts"][name] != number:
                raise ValueError("Count mismatch for %s: raw/fixture=%s, index=%s" % (name, number, status["counts"][name]))
        second = index.sync(package, "validation")
        if second["changed_files"] != 0:
            raise ValueError("An unchanged package was not recognized incrementally")
        for case in queries:
            options = {key: value for key, value in case.items() if key != "total"}
            if index.search("validation", **options)["total"] != case["total"]:
                raise ValueError("Fixture scope query returned the wrong count")
        context = index.context("validation")
    if before != fingerprints(package):
        raise ValueError("Source package changed during validation")
    return {"counts": status["counts"], "source_files": len(before), "source_sha256": before,
            "source_unchanged": True, "unchanged_second_sync": True,
            "scope_queries_checked": len(queries), "warnings": first.get("warnings", []),
            "context_nodes": len(context["nodes"])}


def verify_research(fixture, output):
    sessions = ResearchSessions(output / "research", settings=Settings(output / "settings.json"),
                                engine=FixtureProvider(fixture), db_path=output / "fixture/index.sqlite3")
    with BookmarkIndex(output / "fixture/index.sqlite3") as index:
        rows = index.search("validation", targets=["https://docs.example.test/search"])["results"]
    refs = [{key: row[key] for key in ("source_id", "section_id", "item_id")} for row in rows]
    task = sessions.start(**fixture["brief"], bookmark_refs=refs)
    identifier = task["research_id"]
    for question, page in (("q1", "https://docs.example.test/search"), ("q2", "https://docs.example.test/limits")):
        sessions.search(identifier, question + "-search", [{"question_id": question, "query": fixture["brief"]["questions"][int(question[-1]) - 1]["question"]}])
        fetched = sessions.fetch(identifier, question + "-read", question, [page])
        source_id = fetched["sources"][0]["id"]
        text = sessions.source(identifier, source_id)["text"]
        sessions.record(identifier, {"kind": "source_review", "source_id": source_id, "verdict": "accepted",
                                    "text": "Matches the selected synthetic fixture page."})
        quote = text.splitlines()[0]
        claim = sessions.record(identifier, {"kind": "claim", "question_id": question, "statement": quote,
            "citations": [{"source_id": source_id, "quote": quote}]})["recorded"]["id"]
        sessions.record(identifier, {"kind": "answer", "question_id": question, "answer": quote, "claim_ids": [claim]})
        if question == "q1":
            sessions.record(identifier, {"kind": "gap", "question_id": "q2", "text": "Need the extraction limitations page."})
    failure = sessions.fetch(identifier, "q2-unavailable", "q2", ["https://docs.example.test/unavailable"])
    if failure["status"] != "error" or failure["sources"][0]["body_file"] is not None:
        raise ValueError("A failed fixture page was presented as source evidence")
    reopened = ResearchSessions(output / "research", settings=Settings(output / "settings.json"),
                                engine=FixtureProvider(fixture))
    replay = reopened.fetch(identifier, "q1-read", "q1", ["https://docs.example.test/search"])
    if not replay["replayed"]:
        raise ValueError("A saved operation was resubmitted")
    finished = reopened.finish(identifier, "Synthetic contract run: retrieval supports research; extracts may be partial.",
        limitations=["Fictional provider responses test the lifecycle, not real provider quality.",
                     "The unavailable source remains explicitly recorded as a retrieval failure."])
    return {"research_id": identifier, "status": finished["status"], "usage": finished["usage"],
            "bookmark_context_count": len(finished["bookmark_context"]), "sources": len(finished["sources"]),
            "claims": len(finished["claims"]), "artifacts": finished["artifacts"], "network_calls": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New or empty verification directory outside source packages and plugin")
    parser.add_argument("--package", help="Additionally verify a supplied real package read-only")
    args = parser.parse_args(argv)
    try:
        output = Settings.external_path(str(Path(args.output).expanduser().resolve()), "Verification directory")
        if output.exists() and any(output.iterdir()):
            raise ValueError("Use a new or empty output directory")
        fixture_path = ROOT / "tests/fixtures/research-scenario.json"
        if not fixture_path.is_file():
            raise ValueError("Run this from the source checkout or the test pack; production bundles exclude test fixtures")
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        output.mkdir(parents=True, exist_ok=True)
        summary = {"checked_at": datetime.now(timezone.utc).isoformat(), "network_calls": 0,
                   "fixture": verify_package(ROOT / "tests/fixtures/canvas", output / "fixture", fixture["expected_counts"], fixture["queries"]),
                   "research": verify_research(fixture, output)}
        if args.package:
            summary["provided_package"] = verify_package(Path(args.package).expanduser().resolve(), output / "provided")
        (output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
