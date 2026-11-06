#!/usr/bin/env python3
"""Validate and summarize a 15-question research ladder capture.

The harness-specific runs are supplied as JSON so Codex/Claude/dsh can capture
their own traces without the evaluator pretending to run those hosts. Each
question needs three runs, Q1 and Q3-Q5 counts per run, and human Q2 claim
annotations for the median-step run.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path


CATEGORIES = ("L1", "L2", "L3", "L4", "L5")


def template():
    return {
        "schema_version": 1,
        "baseline_id": "",
        "tool_surface": "",
        "questions": [
            {"id": "%s-%s" % (category, number), "category": category,
             "prompt": "", "target_refs": [], "runs": []}
            for category in CATEGORIES for number in range(1, 4)
        ],
    }


def evaluate(data):
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ValueError("input must contain a questions array")
    questions = data["questions"]
    if len(questions) != 15:
        raise ValueError("the ladder must contain exactly 15 questions")
    ids, categories = set(), {category: 0 for category in CATEGORIES}
    all_runs = []
    q2_missing = []
    for question in questions:
        if not isinstance(question, dict) or not question.get("id"):
            raise ValueError("each question needs an id")
        if question["id"] in ids:
            raise ValueError("question IDs must be unique")
        ids.add(question["id"])
        category = question.get("category")
        if category not in categories:
            raise ValueError("question category must be one of " + ", ".join(CATEGORIES))
        categories[category] += 1
        if not isinstance(question.get("prompt"), str) or not question["prompt"].strip():
            raise ValueError("question %s has no frozen prompt" % question["id"])
        runs = question.get("runs")
        if not isinstance(runs, list) or len(runs) < 3:
            raise ValueError("question %s needs at least three runs" % question["id"])
        for run in runs:
            if not isinstance(run, dict):
                raise ValueError("runs must be objects")
            for field in ("steps", "wall_seconds", "q1_matches", "q1_citations",
                          "q3_content_state_misses", "q4_silent_truncations", "q5_coverage_gaps"):
                if field not in run:
                    raise ValueError("run for %s is missing %s" % (question["id"], field))
            if type(run["steps"]) is not int or run["steps"] < 0:
                raise ValueError("steps must be a non-negative integer")
            if not isinstance(run["wall_seconds"], (int, float)) or run["wall_seconds"] < 0:
                raise ValueError("wall_seconds must be non-negative")
            if type(run["q1_matches"]) is not int or type(run["q1_citations"]) is not int:
                raise ValueError("Q1 counts must be integers")
            if run["q1_matches"] < 0 or run["q1_citations"] < run["q1_matches"]:
                raise ValueError("invalid Q1 match counts")
            for field in ("q3_content_state_misses", "q4_silent_truncations", "q5_coverage_gaps"):
                if type(run[field]) is not int or run[field] < 0:
                    raise ValueError(field + " must be a non-negative integer")
            all_runs.append(run)
        median_steps = statistics.median(run["steps"] for run in runs)
        median_run = next(run for run in runs if run["steps"] == median_steps)
        if "q2_claims" not in median_run:
            q2_missing.append(question["id"])
        elif not isinstance(median_run["q2_claims"], list):
            raise ValueError("q2_claims must be a list of human annotations")
        else:
            for claim in median_run["q2_claims"]:
                if not isinstance(claim, dict) or claim.get("supported") not in (True, False):
                    raise ValueError("each Q2 annotation needs a boolean supported field")
                if not isinstance(claim.get("claim"), str) or not isinstance(claim.get("source_ids"), list):
                    raise ValueError("each Q2 annotation needs claim text and source_ids")
    if any(count != 3 for count in categories.values()):
        raise ValueError("the ladder requires exactly three questions in each L1-L5 category")
    citations = sum(run["q1_citations"] for run in all_runs)
    q1_matches = sum(run["q1_matches"] for run in all_runs)
    claim_rows = [claim for question in questions for run in question["runs"]
                  if run["steps"] == statistics.median(r["steps"] for r in question["runs"])
                  for claim in run.get("q2_claims", [])]
    supported = sum(claim["supported"] is True for claim in claim_rows)
    summary = {
        "baseline_id": data.get("baseline_id"),
        "tool_surface": data.get("tool_surface"),
        "question_count": len(questions),
        "run_count": len(all_runs),
        "category_counts": categories,
        "median_steps": statistics.median(statistics.median(run["steps"] for run in q["runs"])
                                           for q in questions),
        "median_wall_seconds": statistics.median(statistics.median(run["wall_seconds"] for run in q["runs"])
                                                  for q in questions),
        "q1": {"matches": q1_matches, "citations": citations,
               "rate": q1_matches / citations if citations else None},
        "q2": {"supported_claims": supported, "claims": len(claim_rows),
               "rate": supported / len(claim_rows) if claim_rows else None,
               "missing_median_run_annotations": q2_missing},
        "q3_content_state_misses": sum(run["q3_content_state_misses"] for run in all_runs),
        "q4_silent_truncations": sum(run["q4_silent_truncations"] for run in all_runs),
        "q5_coverage_gaps": sum(run["q5_coverage_gaps"] for run in all_runs),
        "gate_pass": bool(citations and not q2_missing and q1_matches == citations and
                           not any(run["q3_content_state_misses"] or run["q4_silent_truncations"] or
                                   run["q5_coverage_gaps"] for run in all_runs)),
    }
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", help="Harness ladder JSON with frozen questions and run traces")
    parser.add_argument("--template", action="store_true", help="Write an empty L1-L5, 15-question capture template")
    parser.add_argument("--out", type=Path, default=Path(".bench/ladder-summary.json"))
    args = parser.parse_args(argv)
    try:
        if args.template:
            if args.input is None:
                raise ValueError("provide an output path as input with --template")
            args.input.parent.mkdir(parents=True, exist_ok=True)
            args.input.write_text(json.dumps(template(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"template": str(args.input), "questions": 15}, ensure_ascii=False))
            return 0
        if args.input is None:
            raise ValueError("provide a ladder JSON input, or use --template <path>")
        data = json.loads(args.input.read_text(encoding="utf-8"))
        result = evaluate(data)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["gate_pass"] else 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
