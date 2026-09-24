#!/usr/bin/env python3
"""Prepare exhaustive native Codex assignments; this script never spawns agents."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def main():
    for stream in (sys.stdout, sys.stderr):  # Windows pipes default to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-id", required=True)
    parser.add_argument("--group-size", type=int, default=12)
    parser.add_argument("--db")
    parser.add_argument("--config")
    options = parser.parse_args()
    if not 1 <= options.group_size <= 50:
        parser.error("group-size must be 1..50")
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("research_call", root / "hosts/shared/research-call.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    items = []
    offset = 0
    seen_offsets = set()
    total = None
    try:
        while offset is not None:
            if offset in seen_offsets:
                raise ValueError("Inventory pagination repeated an offset")
            seen_offsets.add(offset)
            response = bridge.call_tool({"name": "research_inventory", "arguments": {
                "research_id": options.research_id, "offset": offset, "limit": 100}}, options.db, options.config)
            if response["isError"]:
                raise ValueError(json.dumps(response["result"], ensure_ascii=False))
            page = response["result"]
            if total is not None and total != page["total"]:
                raise ValueError("Frozen inventory total changed while reading")
            total = page["total"]
            items.extend(page["items"])
            offset = page["next_offset"]
        ids = [row["id"] for row in items]
        if len(ids) != total or len(set(ids)) != total:
            raise ValueError("Inventory pages did not contain every unique source ID")
        groups = [{"group": index // options.group_size, "inventory_ids": ids[index:index + options.group_size]}
                  for index in range(0, len(ids), options.group_size)]
        print(json.dumps({"research_id": options.research_id, "total": total, "inventory_ids": ids,
                          "groups": groups, "instructions": str(root / "hosts/codex/delegate.md"),
                          "agents_started": 0}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
