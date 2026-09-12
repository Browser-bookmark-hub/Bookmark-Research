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
        inventory = index.inventory(["validation"])
    if (inventory["counts"]["unique_urls"] != status["counts"]["unique_urls"] or
            inventory["counts"]["bookmark_instances"] != status["counts"]["bookmarks"]):
        raise ValueError("Complete inventory changed the raw URL or bookmark-instance counts")
    for source_file in inventory["files"]:
        if before.get(source_file["file_path"]) != source_file["sha256"]:
            raise ValueError("Inventory source hash differs from the original file")
    sessions = ResearchSessions(output / "inventory-research", settings=Settings(output / "settings.json"),
                                db_path=output / "index.sqlite3")
    frozen = sessions.start("Offline inventory acceptance", [{"id": "q1", "question": "Were all original input IDs preserved?"}],
                            source_ids=["validation"], providers=["exa"])
    rows, offset, pages = [], 0, 0
    while offset is not None:
        page = sessions.inventory(frozen["research_id"], offset=offset, limit=100)
        rows.extend(page["items"])
        offset = page["next_offset"]
        pages += 1
    if [row["id"] for row in rows] != [row["id"] for row in inventory["entries"]]:
        raise ValueError("Frozen research inventory pagination lost or reordered inputs")
    manifest_path = Path(frozen["inventory_manifest"])
    if json.loads(manifest_path.read_text(encoding="utf-8")) != inventory:
        raise ValueError("Frozen manifest lost original bookmark metadata or relationships")
    sessions.finish(frozen["research_id"], "Offline inventory inspection only; source pages were not read.",
                    status="incomplete", limitations=["This is source-preservation acceptance, not substantive research."])
    if before != fingerprints(package):
        raise ValueError("Source package changed during validation")
    return {"counts": status["counts"], "source_files": len(before), "source_sha256": before,
            "source_unchanged": True, "unchanged_second_sync": True,
            "scope_queries_checked": len(queries), "warnings": first.get("warnings", []),
            "context_nodes": len(context["nodes"]),
            "inventory": {"counts": inventory["counts"], "input_version": inventory["input_version"],
                          "manifest_path": str(manifest_path), "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                          "pages_read": pages, "all_ids_preserved": True, "whole_scope_preserved": True,
                          "initial_fetch_plan": frozen["initial_fetch_plan"]}}


def verify_research(fixture, output):
    sessions = ResearchSessions(output / "research", settings=Settings(output / "settings.json"),
                                engine=FixtureProvider(fixture), db_path=output / "fixture/index.sqlite3")
    with BookmarkIndex(output / "fixture/index.sqlite3") as index:
        rows = index.search("validation", targets=["https://docs.example.test/search"])["results"]
    refs = [{key: row[key] for key in ("source_id", "section_id", "item_id")} for row in rows]
    task = sessions.start(**fixture["brief"], bookmark_refs=refs)
    identifier = task["research_id"]
    inventory = sessions.inventory(identifier)["items"]
    by_url = {row["original_url"]: row["id"] for row in inventory}

    def review(source, question):
        source_id = source["id"]
        entry = {"kind": "inventory_review", "inventory_id": by_url[source["url"]]}
        if source["body_file"] is None:
            sessions.record(identifier, {**entry, "disposition": "blocked",
                "text": "Synthetic source has no saved page body: " + source["extraction_status"]})
            return None, None
        text = sessions.source(identifier, source_id)["text"]
        sessions.record(identifier, {"kind": "source_review", "source_id": source_id, "verdict": "accepted",
                                    "text": "Matches the selected synthetic fixture page."})
        quote = text.splitlines()[0]
        claim = sessions.record(identifier, {"kind": "claim", "question_id": question, "statement": quote,
            "citations": [{"source_id": source_id, "quote": quote}]})["recorded"]["id"]
        sessions.record(identifier, {**entry, "disposition": "reviewed", "question_ids": [question],
                                    "source_ids": [source_id], "claim_ids": [claim], "text": quote})
        return quote, claim

    for question, page in (("q1", "https://docs.example.test/search"), ("q2", "https://docs.example.test/limits")):
        sessions.search(identifier, question + "-search", [{"question_id": question, "query": fixture["brief"]["questions"][int(question[-1]) - 1]["question"]}])
        fetched = sessions.fetch(identifier, question + "-read", question, [page])
        quote, claim = review(fetched["sources"][0], question)
        sessions.record(identifier, {"kind": "answer", "question_id": question, "answer": quote, "claim_ids": [claim]})
        if question == "q1":
            sessions.record(identifier, {"kind": "gap", "question_id": "q2", "text": "Need the extraction limitations page."})
    remaining = [row["original_url"] for row in sessions.coverage(identifier, filter="unreviewed")["items"]]
    last_batch = sessions.fetch(identifier, "q2-remaining-inputs", "q2", remaining)
    for source in last_batch["sources"]:
        review(source, "q2")
    failure = next(source for source in last_batch["sources"] if source["url"] == "https://docs.example.test/unavailable")
    if last_batch["status"] != "partial" or failure["body_file"] is not None:
        raise ValueError("A failed fixture page was presented as source evidence")
    reopened = ResearchSessions(output / "research", settings=Settings(output / "settings.json"),
                                engine=FixtureProvider(fixture))
    replay = reopened.fetch(identifier, "q1-read", "q1", ["https://docs.example.test/search"])
    if not replay["replayed"]:
        raise ValueError("A saved operation was resubmitted")
    coverage = reopened.coverage(identifier)
    if (coverage["total"] != fixture["expected_counts"]["unique_urls"] or
            coverage["metrics"]["accounted_for"]["rate"] != 1 or coverage["completion_ready"]):
        raise ValueError("Failed or missing fixture pages must remain explicit gaps in the complete input scope")
    try:
        reopened.finish(identifier, "This attempt must fail because original pages remain unread.")
    except ValueError as error:
        if "coverage incomplete" not in str(error):
            raise
    else:
        raise ValueError("The coverage gate accepted unread original fixture pages")
    finished = reopened.finish(identifier, "Synthetic contract run: supported answers with explicit unread input gaps.", status="incomplete",
        limitations=["Fictional provider responses test the lifecycle, not real provider quality.",
                     "Three original fixture pages have no body and remain blocked; no successful completion is claimed."])
    return {"research_id": identifier, "status": finished["status"], "usage": finished["usage"],
            "bookmark_context_count": len(finished["bookmark_context"]), "sources": len(finished["sources"]),
            "claims": len(finished["claims"]), "artifacts": finished["artifacts"], "network_calls": 0,
            "source_scope": finished["source_scope"], "coverage": coverage["metrics"],
            "completion_gate_rejected_unread_inputs": True}


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
