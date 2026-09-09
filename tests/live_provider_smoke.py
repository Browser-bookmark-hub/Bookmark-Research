"""Opt-in public MCP smoke: three searches and three URL extractions at most.

No saved configuration, API credentials, source packages or user archives are
used. Schema recording is explicit so normal offline tests never need a service.
"""

import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from settings import Settings
from web_search import SearchProviders


def compact_schema(value):
    if isinstance(value, dict):
        return {key: compact_schema(item) for key, item in value.items() if key not in ("description", "title")}
    if isinstance(value, list):
        return [compact_schema(item) for item in value]
    return value


def write_json(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Authorize the six public search/extract smoke calls")
    parser.add_argument("--output", help="Write a public summary without source bodies or credentials")
    parser.add_argument("--record-schemas", help="Explicitly update a sanitized tools/list fixture")
    args = parser.parse_args()
    if not args.run_live:
        parser.error("Pass --run-live to contact the three public MCP providers")
    for key in ("EXA_API_KEY", "PARALLEL_API_KEY", "TAVILY_API_KEY"):
        os.environ.pop(key, None)
    names = ["exa", "parallel", "tavily"]
    pages = {"exa": "https://exa.ai/docs/reference/exa-mcp",
             "parallel": "https://docs.parallel.ai/integrations/mcp/search-mcp",
             "tavily": "https://docs.tavily.com/documentation/keyless"}
    stamp = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="bookmark-public-smoke-") as temporary:
        engine = SearchProviders(timeout=30, settings=Settings(Path(temporary) / "settings.json"))
        probe = engine.probe(names)
        searched = engine.search([{"target": "official MCP documentation",
                                   "query": "Exa Parallel Tavily MCP official search documentation"}], names, 2)
        def fetch(name):
            return engine.fetch([pages[name]], name, archive=False, max_characters=2500)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            fetched = list(pool.map(fetch, names))
        report = {"observed_at": stamp, "conditions": {"credentials": "cleared in smoke process",
                  "archive": False, "search_limit": 2, "requested_fetch_characters": 2500,
                  "native_research_invoked": False, "automatic_tool_retries": 0},
                  "probes": [{key: row[key] for key in ("provider", "status", "capabilities", "error", "error_kind", "retryable", "usage") if key in row}
                             for row in probe["providers"]],
                  "searches": [{**{key: row[key] for key in ("provider", "status", "error", "error_kind", "retryable", "usage", "tool") if key in row},
                                "urls": [item["url"] for item in row["results"]]} for row in searched["batches"]],
                  "fetches": [{key: row[key] for key in ("provider", "status", "error", "error_kind", "retryable", "usage", "tool", "per_url",
                                                        "character_limit_applied", "successful_url_count") if key in row} for row in fetched]}
        report["tool_calls"] = searched["usage"]["tool_calls"] + sum(row["usage"]["tool_calls"] for row in fetched)
        report["passed"] = (all(row["status"] == "ok" and row["results"] for row in searched["batches"])
                            and all(row["status"] == "ok" and row["successful_url_count"] == 1 for row in fetched))
        if args.record_schemas:
            catalogs = []
            for row in probe["providers"]:
                if row["status"] != "ok":
                    continue
                info = engine.registry["providers"][row["provider"]]
                selected = set(info["search_tools"] + info["fetch_tools"])
                catalogs.append({"provider": row["provider"], "endpoint": info["url"], "docs": info["docs"],
                    "protocol": engine._states[row["provider"]].client.protocol,
                    "advertised_tool_names": [tool["name"] for tool in row["tools"]],
                    "catalog_sha256": hashlib.sha256(json.dumps(row["tools"], sort_keys=True).encode()).hexdigest(),
                    "tools": [{"name": tool["name"], "inputSchema": compact_schema(tool["inputSchema"]),
                               "annotations": tool.get("annotations", {})} for tool in row["tools"] if tool["name"] in selected]})
            if len(catalogs) == len(names):
                write_json(args.record_schemas, {"observed_at": stamp, "source": "live tools/list; descriptions/titles omitted",
                                                "execution_authorization_implied": False, "providers": catalogs})
            else:
                report["schema_recording"] = "skipped: a provider catalog was unavailable"
        if args.output:
            write_json(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
