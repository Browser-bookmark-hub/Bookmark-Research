#!/usr/bin/env python3
"""Replay fixed retrieval plans against real captured text in an isolated Wiki."""
import argparse
import hashlib
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from raw_library import RawLibrary
from research import ResearchSessions
from settings import Settings
from wiki import WikiStore


def seed(fixture, sources, root):
    settings = Settings(root / "settings.json")
    settings.update({"wiki": {"directory": str(root / "wiki")},
                     "archive": {"directory": str(root / "archive")},
                     "output": {"directory": str(root / "research")}})
    sessions = ResearchSessions(root / "research", settings=settings, db_path=root / "index.sqlite3")
    wiki = WikiStore(settings=settings, research_sessions=sessions)
    provenance = []
    for page in fixture["sources"]:
        source = json.loads((sources / (page["id"] + "-source.json")).read_text())
        body = source["text"]
        if source["url"] != page["url"] or hashlib.sha256(body.encode()).hexdigest() != source["sha256"]:
            raise ValueError("Source identity or hash changed: " + page["id"])
        if not all(quote in body for quote in page["quotes"]):
            raise ValueError("A planned quote is absent from the capture: " + page["id"])
        rid = sessions.start(page["title"], [{"id": "q1", "question": "What does this source establish?"}],
                             providers=["exa"])["research_id"]
        sessions.import_evidence(rid, "import", "q1", page["url"], body,
            {"kind": "page", "provider": "captured-provider-response", "retrieved_at": source["retrieved_at"]})
        sessions.record(rid, {"kind": "source_review", "source_id": "s1", "verdict": "accepted",
                             "text": "Source passages read in the authoring session; this replay verifies their exact bytes."})
        sessions.record(rid, {"kind": "claim", "question_id": "q1", "statement": page["text"],
            "citations": [{"source_id": "s1", "quote": quote} for quote in page["quotes"]]})
        wiki.write(page["id"], {"title": page["title"], "kind": "entity", "aliases": page["aliases"],
            "sections": [{"heading": "Saved knowledge", "text": page["text"],
                          "claims": [{"research_id": rid, "claim_id": "c1"}]}], "links": page["links"],
            "review": {"method": "model", "reviewer": "Codex authoring session, 2026-10-10",
                       "note": "Manually authored synthesis and reviewed quotes; retrieval replay does not score semantic support."}},
            "Seed isolated retrieval diagnostic")
        provenance.append({key: source[key] for key in ("id", "url", "sha256", "retrieved_at", "capture_id")})
    return wiki, RawLibrary(settings=settings), provenance


def retrieve(wiki, raw, question, guided):
    # Gold labels are used only by score(), never for query selection or stopping.
    pages, urls, calls = {}, set(), []
    queries = question["queries"] if guided else question["queries"][:1]
    for query in queries:
        result = wiki.search(query, limit=5)
        calls.append({"tool": "wiki_search", "query": query, "total": result["total"]})
        for item in result["results"]:
            pages[item["page_id"]] = item["validation"]["status"]
        if guided and question.get("follow_links"):
            for page_id in list(pages):
                record = wiki.get(page_id)
                calls.append({"tool": "wiki_get", "page_id": page_id})
                for link in record["page"]["links"][:3]:
                    target = wiki.get(link["page_id"])
                    calls.append({"tool": "wiki_get", "page_id": link["page_id"]})
                    if target["validation"]["integrity"] == "valid":
                        pages[link["page_id"]] = target["validation"]["status"]
        if len(pages) >= question.get("min_pages", 1):
            break
    if guided and not pages:
        for query in question.get("archive_queries", []):
            result = raw.search(query, limit=5)
            calls.append({"tool": "search_archive", "query": query, "total": result["total"]})
            urls.update(item["url"] for item in result["results"])
            if urls:
                break
    return {"pages": sorted(pages), "urls": sorted(urls), "validation": pages, "calls": calls}


def score(question, result):
    gold = {"page:" + value for value in question.get("expected_pages", [])} | {
        "url:" + value for value in question.get("expected_urls", [])}
    found = {"page:" + value for value in result["pages"]} | {"url:" + value for value in result["urls"]}
    return {"supported_targets": len(gold & found), "expected_targets": len(gold),
            "complete": gold <= found if gold else not found,
            "recall": len(gold & found) / len(gold) if gold else None}


def run(fixture, sources, root):
    wiki, raw, provenance = seed(fixture, sources, root)
    # Build derived indexes once: report warm local retrieval, excluding ingestion.
    wiki.search("__warmup_no_match__")
    raw.refresh()
    rows = []
    for question in fixture["questions"]:
        row = {"id": question["id"], "question": question["question"]}
        for name, guided in (("first_query", False), ("guided_plan", True)):
            started = time.perf_counter()
            result = retrieve(wiki, raw, question, guided)
            row[name] = {**result, **score(question, result),
                         "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}
        rows.append(row)
    summaries = {}
    for name in ("first_query", "guided_plan"):
        count = sum(row[name]["expected_targets"] for row in rows)
        summaries[name] = {"complete_questions": sum(row[name]["complete"] for row in rows),
            "questions": len(rows), "target_recall": sum(row[name]["supported_targets"] for row in rows) / count,
            "median_ms": round(statistics.median(row[name]["elapsed_ms"] for row in rows), 3),
            "tool_calls": sum(len(row[name]["calls"]) for row in rows)}

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz or timezone.utc) + timedelta(days=31)

    with patch("wiki.datetime", Later):
        aged = wiki.search("Z.AI pricing")["results"]
        aged_warning = bool(aged) and all(row["validation"]["status"] == "needs_review" for row in aged)
        work_warning = wiki.work(page_id="zai-pricing")["items"][0]["status"] == "needs_review"
    record = wiki.get("mcp")
    # Controlled integrity failure, confined to this diagnostic's copied evidence.
    Path(record["evidence"][0]["citations"][0]["body_file"]).write_text("controlled corruption")
    corrupt_excluded = "mcp" not in {row["page_id"] for row in wiki.search("MCP")["results"]}
    return {"method": fixture["description"], "fixture_sha256": hashlib.sha256(
        json.dumps(fixture, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "network_during_replay": False, "semantic_answer_quality_scored": False,
        "source_provenance": provenance, "summary": summaries, "questions": rows,
        "controlled_checks": {"age_31_days_warns": aged_warning, "aged_work_requires_review": work_warning,
                              "corrupt_evidence_excluded": corrupt_excluded}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-dir", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=ROOT / "tests/fixtures/wiki-retrieval-questions.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    with tempfile.TemporaryDirectory(prefix="wiki-retrieval-replay-") as temporary:
        root = Path(temporary)
        with patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": str(root)}):
            result = run(fixture, args.sources_dir, root)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "summary": result["summary"],
                      "controlled_checks": result["controlled_checks"]}, ensure_ascii=False, indent=2))
    guided = result["summary"]["guided_plan"]
    passed = guided["complete_questions"] == guided["questions"] and all(result["controlled_checks"].values())
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
