#!/usr/bin/env python3
"""Print a complete DSH workflow tool call; never start the workflow here."""

import argparse
import json
from pathlib import Path
import sys


def main():
    for stream in (sys.stdout, sys.stderr):  # Windows pipes default to the ANSI code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", default="bookmark-research",
                        choices=("bookmark-research", "bookmark-research-discovery"))
    parser.add_argument("--research-id")
    parser.add_argument("--question", help="Required by bookmark-research-discovery")
    parser.add_argument("--source-id", help="Required by bookmark-research-discovery")
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--group-size", type=int, default=12)
    parser.add_argument("--max-gap-rounds", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--method", default="comparison")
    parser.add_argument("--output-language", default="auto",
                        help="Output language name/code; auto follows the brief/questions, with English fallback")
    options = parser.parse_args()
    if options.workflow == "bookmark-research" and not options.research_id:
        parser.error("--research-id is required by bookmark-research")
    if options.workflow == "bookmark-research-discovery" and not (options.question and options.source_id):
        parser.error("--question and --source-id are required by bookmark-research-discovery")
    if not 1 <= options.group_size <= 50 or not 0 <= options.max_gap_rounds <= 4:
        parser.error("group-size must be 1..50 and max-gap-rounds must be 0..4")
    if options.workflow == "bookmark-research-discovery" and not 1 <= options.max_steps <= 6:
        parser.error("max-steps must be 1..6")
    if (not options.output_language.strip() or len(options.output_language) > 80
            or any(ord(char) < 32 or ord(char) == 127 for char in options.output_language)):
        parser.error("output-language must be 1..80 characters without control characters")
    options.output_language = options.output_language.strip()
    root = Path(__file__).resolve().parents[2]
    directory = root / "workflows" / options.workflow
    if directory.is_dir():
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        script = (directory / "script.js").read_text(encoding="utf-8")
    else:
        sys.path.insert(0, str(root / "scripts"))
        from host_assets import build_workflow
        definition, script = build_workflow(root, "dsh", options.workflow)
        meta = definition["meta"]
    args = {"run_key": options.run_key, "output_language": options.output_language}
    if options.workflow == "bookmark-research":
        args.update(research_id=options.research_id, group_size=options.group_size,
                    max_gap_rounds=options.max_gap_rounds, method=options.method)
    else:
        args.update(question=options.question, source_id=options.source_id, max_steps=options.max_steps)
    args["bridge_path"] = str(root / "hosts/shared/research-call.py")
    print(json.dumps({"meta": meta, "script": script, "args": args}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
