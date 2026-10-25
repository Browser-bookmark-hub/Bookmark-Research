#!/usr/bin/env python3
"""Deterministic local benchmark for the preflight path; no network.

This is a scale test, not a load test. It builds temporary Canvas packages,
saved captures and a synthetic Wiki search index, then measures the plugin code
in-process. It never writes to the configured user data directory.

Examples:
    python3 scripts/bench_preflight.py
    python3 scripts/bench_preflight.py --sizes 1000,10000,50000 --repeats 5
    python3 scripts/bench_preflight.py --archive-pages 100,500,1000 --json
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from archive import SourceArchive
from bookmark_index import BookmarkIndex
from raw_library import RawLibrary
from research_plan import ResearchPlan
from settings import Settings


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def make_package(root, bookmarks, sections):
    """A temporary Canvas package with a controlled number of bookmarks."""
    root.mkdir(parents=True, exist_ok=True)
    base, extra = divmod(bookmarks, sections)
    offset = 0
    for section in range(sections):
        count = base + (1 if section < extra else 0)
        items = [{"id": "b-%d-%d" % (section, index), "sectionId": "temp-section-bench-%d" % section,
                  "type": "bookmark", "title": "alpha beta topic %d item %d unique%d" %
                  (section, index, offset + index),
                  "url": "https://example.test/%d/%d" % (section, index)}
                 for index in range(count)]
        _write_json(root / "临时栏目" / "常规链式" / ("bench-%04d.json" % section), {
            "format": "bookmark-canvas-section", "schemaVersion": 2, "sectionType": "temporary",
            "id": "temp-section-bench-%d" % section, "label": "B%d" % section,
            "title": "Bench %d" % section, "tempKind": "regular", "items": items})
        offset += count
    return root


def _timings(call, repeats):
    call()  # warm-up
    values = []
    for _ in range(repeats):
        start = time.perf_counter()
        value = call()
        values.append((time.perf_counter() - start) * 1000.0)
    values.sort()
    middle = values[len(values) // 2]
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
    return round(middle, 2), round(p95, 2), value


def benchmark_packages(sizes, sections, repeats):
    rows = []
    for total in sizes:
        with tempfile.TemporaryDirectory(prefix="br-bench-") as name:
            base = Path(name)
            package = make_package(base / "package", total, sections)
            index = BookmarkIndex(base / "index.sqlite3")
            try:
                source_id = index.sync(str(package), "bench", completeness="partial")["source_id"]
                settings = Settings(base / "settings.json")
                plan = ResearchPlan(index, settings=settings)
                queries = ("alpha", "alpha beta", "unique%d" % max(1, total // 2))
                for query in queries:
                    median, p95, result = _timings(lambda: plan.build(
                        source_id, query, include_wiki=False, include_archive=False), repeats)
                    rows.append({"kind": "bookmark", "items": total, "sections": sections,
                                 "query": query, "p50_ms": median, "p95_ms": p95,
                                 "cards": len(result["cards"]), "urls": len(result["urls"]),
                                 "characters": result["preflight_budget"]["characters"],
                                 "matched": bool(result["cards"] or result["canvas_matches"])})
            finally:
                index.close()
    return rows


def benchmark_archive(pages, repeats):
    rows = []
    for count in pages:
        with tempfile.TemporaryDirectory(prefix="br-bench-archive-") as name:
            base = Path(name)
            archive = SourceArchive(base / "knowledge")
            urls = ["https://example.test/page/%d" % index for index in range(count)]
            archive.save({"provider": "exa", "tool": "bench", "urls": urls,
                          "request_arguments": {"urls": urls}, "requested_max_characters": 1200,
                          "retrieved_at": "2026-10-20T00:00:00Z",
                          "result": {"structuredContent": {"results": [
                              {"url": url, "title": "page %d" % index,
                               "text": "alpha beta page %d " % index + ("evidence " * 120)}
                              for index, url in enumerate(urls)]}}})
            library = RawLibrary(db_path=base / "raw.sqlite3", archive_directory=archive.directory,
                                 data_directory=base)
            for query in (["alpha"], ["alpha", "beta"]):
                median, p95, result = _timings(
                    lambda: library.search_terms(query, limit=5), repeats)
                rows.append({"kind": "archive", "documents": count, "query": " ".join(query),
                             "p50_ms": median, "p95_ms": p95, "results": len(result)})
    return rows


def benchmark_wiki_index(documents, repeats):
    """Index-only search cost; revision validation is exercised elsewhere."""
    from wiki_search import WikiSearchIndex
    rows = []
    for count in documents:
        with tempfile.TemporaryDirectory(prefix="br-bench-wiki-") as name:
            base = Path(name)
            store = WikiSearchIndex(base / "search.sqlite3")
            index = {"pages": {}}
            records = {}
            for number in range(count):
                page_id = "bench-%05d" % number
                pointer = {"sha256": "sha-%d" % number, "revision": 1,
                           "updated_at": "2026-10-20T00:00:00Z", "record_file": "unused"}
                record = {"page": {"title": "alpha beta %d" % number, "kind": "topic",
                                   "sections": [{"heading": "alpha", "text": "beta evidence %d" % number}]},
                          "evidence": [], "resolved_links": []}
                store.update(page_id, pointer, record)
                index["pages"][page_id] = pointer
                records[page_id] = record
            groups = WikiSearchIndex.terms("alpha beta")
            def call():
                rows, invalid = store.candidates(
                    index, lambda pointer: records[pointer["page_id"]] if "page_id" in pointer else None, groups)
                matches = [store.match(row, "alpha beta", groups) for row in rows]
                return [row for row in matches if row is not None]
            # candidates() needs pointer -> record; the pointer has no page_id, so
            # use the page id embedded by the caller instead.
            def load(pointer):
                return records[pointer["page_id"]]
            for page_id, pointer in index["pages"].items():
                pointer["page_id"] = page_id
            median, p95, result = _timings(call, repeats)
            rows.append({"kind": "wiki-index", "documents": count, "query": "alpha beta",
                         "p50_ms": median, "p95_ms": p95, "results": len(result)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="1000,5000,10000,50000",
                        help="bookmark counts, comma separated")
    parser.add_argument("--sections", type=int, default=38, help="sections per package")
    parser.add_argument("--archive-pages", default="100,500",
                        help="saved page counts, comma separated")
    parser.add_argument("--wiki-documents", default="100,1000",
                        help="synthetic Wiki index document counts, comma separated")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args()
    sizes = [int(value) for value in args.sizes.split(",") if value.strip()]
    pages = [int(value) for value in args.archive_pages.split(",") if value.strip()]
    documents = [int(value) for value in args.wiki_documents.split(",") if value.strip()]
    rows = []
    rows.extend(benchmark_packages(sizes, args.sections, args.repeats))
    rows.extend(benchmark_archive(pages, args.repeats))
    rows.extend(benchmark_wiki_index(documents, args.repeats))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print("| kind | items | query | p50 ms | p95 ms | cards | urls | chars | results |")
    print("|---|---:|---|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        print("| {kind} | {items} | {query} | {p50} | {p95} | {cards} | {urls} | {chars} | {results} |"
              .format(kind=row.get("kind", ""), items=row.get("items", row.get("documents", "")),
                      query=row.get("query", ""), p50=row.get("p50_ms", ""), p95=row.get("p95_ms", ""),
                      cards=row.get("cards", ""), urls=row.get("urls", ""),
                      chars=row.get("characters", ""), results=row.get("results", "")))


if __name__ == "__main__":
    main()
