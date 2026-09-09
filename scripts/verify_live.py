#!/usr/bin/env python3
"""Opt-in public-network smoke test; save inspectable provider evidence."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from web_search import SearchProviders
from settings import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Evidence directory outside any data package")
    parser.add_argument("--fetch-only", action="store_true", help="Skip search; verify actual extraction and archival")
    parser.add_argument("--fetch-url", action="append", help="Public URL to read; repeat for a bounded batch")
    parser.add_argument("--provider", choices=("exa", "parallel"), default="exa", help="Fetch provider")
    parser.add_argument("--max-characters", type=int, default=12000)
    args = parser.parse_args()
    output = Settings.external_path(str(Path(args.output).expanduser().resolve()), "Verification output directory")
    output.mkdir(parents=True, exist_ok=True)
    settings = Settings(output / "settings.json")
    settings.update({"archive": {"enabled": True, "directory": str(output / "knowledge")}})
    engine = SearchProviders(timeout=30, settings=settings)
    search = {"successful_provider_count": 0, "batches": [], "targets": []} if args.fetch_only else engine.search([
        {"target": "Agent Plugins", "query": "Agent Plugins official specification plugin.json MCP skills"},
        {"target": "DeepSeek Harness", "query": "DeepSeek Harness official plugin bundle MCP client"},
    ], limit_per_target=3)
    (output / "live-search.json").write_text(json.dumps(search, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        fetch = engine.fetch(args.fetch_url or ["https://agent-plugins.org/specification"],
                             provider=args.provider, max_characters=args.max_characters)
        fetch_ok = True
    except (RuntimeError, ValueError, OSError) as error:
        fetch = {"error": str(error)}
        fetch_ok = False
    (output / "live-fetch.json").write_text(json.dumps(fetch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "search_performed": not args.fetch_only,
        "successful_provider_count": search["successful_provider_count"],
        "batches": [{"provider": row["provider"], "target": row["target"], "status": row["status"],
                     "results": len(row["results"]), "error": row.get("error")} for row in search["batches"]],
        "targets": [{"target": row["target"], "status": row["status"], "urls": [r["url"] for r in row["results"]]}
                    for row in search["targets"]],
        "fetch_transport_ok": fetch_ok,
        "archive": fetch.get("archive"),
        "fetch_note": "Transport success does not assert origin freshness or per-URL extraction success; inspect live-fetch.json.",
        "evidence_directory": str(output),
    }
    (output / "live-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    archived = fetch.get("archive", {})
    archive_ok = archived.get("status") == "saved" and all(page["page_body_archived"] for page in archived.get("pages", []))
    return 0 if fetch_ok and archive_ok and all(row["status"] == "ok" and row["results"] for row in search["batches"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
