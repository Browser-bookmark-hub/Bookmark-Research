#!/usr/bin/env python3
"""Benchmark synchronization performance across full import, no-change rescan, and single-file edit.

Accepts any Canvas package directory, ZIP, or creates a synthetic package if omitted.
Runs all tests in an isolated temporary directory without touching original data.

Examples:
    python3 scripts/bench_sync.py
    python3 scripts/bench_sync.py /path/to/Bookmark-Canvas/bookmark/书签画布
    python3 scripts/bench_sync.py --json
    python3 scripts/bench_sync.py --threshold 0.05
"""

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bookmark_index import BookmarkIndex
from source_manager import SourceManager
from source_inputs import read_input


DEFAULT_PACKAGE = Path("/Users/kk/Downloads/kk/Bookmark-Canvas/bookmark/书签画布")


def make_synthetic_package(root, sections=10, items_per_section=50):
    root.mkdir(parents=True, exist_ok=True)
    canvas = root / "canvas.canvas"
    canvas.write_text(json.dumps({"nodes": [], "edges": []}, ensure_ascii=False), encoding="utf-8")
    for s in range(sections):
        section_dir = root / "临时栏目" / "常规链式"
        section_dir.mkdir(parents=True, exist_ok=True)
        items = [{"id": f"item-{s}-{i}", "sectionId": f"temp-section-{s}",
                  "type": "bookmark", "title": f"Bookmark {s}-{i}",
                  "url": f"https://example.test/{s}/{i}"} for i in range(items_per_section)]
        data = {
            "format": "bookmark-canvas-section",
            "schemaVersion": 2,
            "sectionType": "temporary",
            "id": f"temp-section-{s}",
            "label": f"T-{s}",
            "title": f"Test Card {s}",
            "tempKind": "regular",
            "items": items,
        }
        (section_dir / f"card-{s:03d}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return root


def run_benchmark(package_path, threshold=0.05):
    with tempfile.TemporaryDirectory(prefix="bookmark-bench-sync-") as tmpdir:
        work_dir = Path(tmpdir)
        db_path = work_dir / "index.sqlite3"
        pkg_copy = work_dir / "package"

        is_synthetic = False
        if package_path and Path(package_path).exists():
            orig = Path(package_path).expanduser().resolve()
            if orig.is_dir():
                shutil.copytree(orig, pkg_copy)
            else:
                shutil.copyfile(orig, pkg_copy)
        elif DEFAULT_PACKAGE.exists():
            shutil.copytree(DEFAULT_PACKAGE, pkg_copy)
        else:
            make_synthetic_package(pkg_copy)
            is_synthetic = True

        prepared = read_input(pkg_copy)
        total_files = len(prepared["files"])

        with BookmarkIndex(db_path) as index:
            manager = SourceManager(index)

            # 1. Full initial import
            t0 = time.perf_counter()
            full_result = manager.sync(pkg_copy, "bench_source", mode="live", completeness="complete")
            full_duration = time.perf_counter() - t0

            # 2. No-change rescan
            t0 = time.perf_counter()
            nochange_result = manager.refresh("bench_source", force=False)
            nochange_duration = time.perf_counter() - t0

            # 3. Single-file modification
            # Pick one json file in the package copy and append an item
            target_json = None
            if pkg_copy.is_dir():
                for p in sorted(pkg_copy.rglob("*.json")):
                    if not p.is_symlink() and p.is_file():
                        target_json = p
                        break

            if target_json is not None:
                content = json.loads(target_json.read_text(encoding="utf-8"))
                items = content.setdefault("items", [])
                items.append({
                    "id": "item-bench-mod-1",
                    "sectionId": content.get("id", "bench-section"),
                    "type": "bookmark",
                    "title": "Bench Added Bookmark",
                    "url": "https://example.test/bench-added"
                })
                time.sleep(0.01)
                target_json.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

            t0 = time.perf_counter()
            single_result = manager.refresh("bench_source", force=True)
            single_duration = time.perf_counter() - t0

        threshold_exceeded = nochange_duration > threshold

        return {
            "package_path": str(package_path or (pkg_copy if is_synthetic else DEFAULT_PACKAGE)),
            "is_synthetic": is_synthetic,
            "total_files": total_files,
            "threshold_seconds": threshold,
            "full_import": {
                "duration_seconds": round(full_duration, 4),
                "changed_files": full_result.get("changed_files", 0),
                "skipped_files": full_result.get("skipped_files", 0),
                "items_inserted": full_result.get("items_inserted", 0),
                "counts": full_result.get("counts", {}),
            },
            "no_change_rescan": {
                "duration_seconds": round(nochange_duration, 6),
                "changed_files": nochange_result.get("changed_files", 0),
                "state": nochange_result.get("state"),
                "threshold_exceeded": threshold_exceeded,
            },
            "single_file_change": {
                "duration_seconds": round(single_duration, 4),
                "changed_files": single_result.get("changed_files", 0),
                "items_updated": single_result.get("items_updated", 0),
                "items_inserted": single_result.get("items_inserted", 0),
            }
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", nargs="?", default=None, help="Canvas package path (directory or ZIP)")
    parser.add_argument("--threshold", type=float, default=0.05,
                        help="No-change rescan threshold in seconds (default 0.05 s / 50 ms)")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    results = run_benchmark(args.package, threshold=args.threshold)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        full = results["full_import"]
        nochange = results["no_change_rescan"]
        single = results["single_file_change"]

        print("=" * 66)
        print("Bookmark Research — Synchronization Benchmark")
        print(f"Target: {results['package_path']}")
        print(f"Total protocol files: {results['total_files']}")
        print("-" * 66)
        print(f"1. Full Import:        {full['duration_seconds']:8.4f} s  "
              f"(files: {full['changed_files']}, inserted: {full['items_inserted']})")

        nc_status = "WARNING: EXCEEDS THRESHOLD" if nochange["threshold_exceeded"] else "OK"
        print(f"2. No-change Rescan:   {nochange['duration_seconds']:8.6f} s  "
              f"(changed: {nochange['changed_files']}, state: {nochange['state']}) [{nc_status}]")
        if nochange["threshold_exceeded"]:
            print(f"   [!] No-change rescan took {nochange['duration_seconds']*1000:.2f} ms, "
                  f"exceeding threshold {args.threshold*1000:.1f} ms!")

        print(f"3. Single-file Change: {single['duration_seconds']:8.4f} s  "
              f"(changed: {single['changed_files']}, inserted: {single['items_inserted']}, updated: {single['items_updated']})")
        print("=" * 66)

    return 1 if results["no_change_rescan"]["threshold_exceeded"] else 0


if __name__ == "__main__":
    sys.exit(main())
