#!/usr/bin/env python3
"""Capture the production stdio tools/list response and measure its length.

This deliberately drives ``serve`` instead of serializing TOOL_SCHEMAS itself.
The resulting JSON artifact records the exact response line, tool names and
serializer so schema-size estimates cannot silently become the regression gate.
"""

import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mcp_server  # noqa: E402
from mcp_server import _legacy_compatibility_expired, serve  # noqa: E402
from settings import Settings  # noqa: E402


# Frozen 2026-11-06 quick catalog for before/after host comparisons.
LEGACY_TOOLS = (
    "sync_package", "index_status", "search_bookmarks", "lookup_url", "get_context",
    "traverse_graph", "plan_research", "search_web", "merge_search_results",
    "agentic_search", "fetch_web", "search_archive", "wiki_write", "wiki_get",
    "wiki_list", "wiki_search", "research_services", "research_service_prepare",
    "research_service_start", "research_service_status", "research_service_result",
    "research_service_cancel", "research_service_attach", "get_settings", "update_settings",
)
PRESETS = ("quick", "legacy", "deep", "all")


def _request(method, request_id=None, params=None):
    value = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        value["id"] = request_id
    if params is not None:
        value["params"] = params
    return value


def capture(preset, db_path=":memory:", excluded=()):
    """Return the parsed tools/list response and its exact emitted line."""
    if preset == "legacy" and _legacy_compatibility_expired(mcp_server.release_version()):
        raise ValueError("The legacy tool surface ended at 0.7.0")
    temporary = tempfile.TemporaryDirectory(prefix="bookmark-tools-list-")
    old_scope = os.environ.get("BOOKMARK_RESEARCH_TOOL_SCOPE")
    try:
        # Use an isolated settings file and an explicit environment scope so a
        # measurement cannot rewrite the user's config or inherit its preset.
        settings = Settings(Path(temporary.name) / "settings.json")
        if preset == "quick":
            names = [name for name in Settings.QUICK_TOOLS if name not in excluded]
            os.environ["BOOKMARK_RESEARCH_TOOL_SCOPE"] = ",".join(names)
        elif preset == "legacy":
            names = [name for name in LEGACY_TOOLS if name not in excluded]
            os.environ["BOOKMARK_RESEARCH_TOOL_SCOPE"] = ",".join(names)
        elif excluded:
            from mcp_server import TOOL_SCHEMAS
            names = [name for name in TOOL_SCHEMAS if name not in excluded]
            os.environ["BOOKMARK_RESEARCH_TOOL_SCOPE"] = ",".join(names)
        else:
            # Empty override deliberately exposes the full catalog for all/deep.
            os.environ["BOOKMARK_RESEARCH_TOOL_SCOPE"] = ""
        incoming = "\n".join([
            json.dumps(_request("initialize", 1, {"protocolVersion": "2025-11-25",
                                                   "capabilities": {},
                                                   "clientInfo": {"name": "bench-tools-list", "version": "1"}}),
                       ensure_ascii=False),
            json.dumps(_request("notifications/initialized"), ensure_ascii=False),
            json.dumps(_request("tools/list", 2), ensure_ascii=False),
            "",
        ])
        stdout, stderr = io.StringIO(), io.StringIO()
        serve(db_path, stdin=io.StringIO(incoming), stdout=stdout, stderr=stderr,
              settings=settings, workers=1, max_pending=1)
        lines = stdout.getvalue().splitlines(keepends=True)
        response_line = next((line for line in lines
                              if json.loads(line).get("id") == 2), None)
        if response_line is None:
            raise RuntimeError("stdio tools/list response was not emitted: " + stdout.getvalue())
        response = json.loads(response_line)
        if "error" in response:
            raise RuntimeError("tools/list failed: " + response["error"].get("message", "unknown error"))
        tools = response["result"]["tools"]
        return response, response_line, tools
    finally:
        if old_scope is None:
            os.environ.pop("BOOKMARK_RESEARCH_TOOL_SCOPE", None)
        else:
            os.environ["BOOKMARK_RESEARCH_TOOL_SCOPE"] = old_scope
        temporary.cleanup()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=PRESETS, default="quick")
    parser.add_argument("--db", default=":memory:")
    parser.add_argument("--exclude", action="append", default=[], help="Exclude a tool for a pre-change comparison")
    parser.add_argument("--out", type=Path, default=Path(".bench/tools-list.json"))
    args = parser.parse_args(argv)
    response, line, tools = capture(args.preset, db_path=args.db, excluded=args.exclude)
    serializer = "json.dumps(ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\\n'"
    artifact = {
        "preset": args.preset,
        "excluded": args.exclude,
        "tool_count": len(tools),
        "tool_names": [tool["name"] for tool in tools],
        "response_characters": len(line),
        "response_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(),
        "serializer": serializer,
        "response": response,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: artifact[key] for key in
                      ("preset", "excluded", "tool_count", "response_characters", "response_sha256")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
