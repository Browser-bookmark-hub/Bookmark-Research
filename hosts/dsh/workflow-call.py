#!/usr/bin/env python3
"""Print a complete DSH workflow tool call; never start the workflow here."""

import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-id", required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--group-size", type=int, default=12)
    parser.add_argument("--max-gap-rounds", type=int, default=1)
    parser.add_argument("--method", default="comparison")
    parser.add_argument("--output-language", default="auto",
                        help="Output language name/code; auto follows the brief/questions, with English as fallback")
    options = parser.parse_args()
    if not 1 <= options.group_size <= 50 or not 0 <= options.max_gap_rounds <= 4:
        parser.error("group-size must be 1..50 and max-gap-rounds must be 0..4")
    if (not options.output_language.strip() or len(options.output_language) > 80
            or any(ord(char) < 32 or ord(char) == 127 for char in options.output_language)):
        parser.error("output-language must be 1..80 characters without control characters")
    options.output_language = options.output_language.strip()
    root = Path(__file__).resolve().parents[2]
    directory = root / "workflows/bookmark-research"
    if directory.is_dir():
        meta = json.loads((directory / "meta.json").read_text())
        script = (directory / "script.js").read_text()
    else:
        sys.path.insert(0, str(root / "scripts"))
        from host_assets import build_workflow
        definition, script = build_workflow(root, "dsh")
        meta = definition["meta"]
    args = vars(options)
    args["bridge_path"] = str(root / "hosts/shared/research-call.py")
    print(json.dumps({"meta": meta, "script": script, "args": args}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
