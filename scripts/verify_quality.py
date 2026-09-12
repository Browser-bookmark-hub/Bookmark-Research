#!/usr/bin/env python3
"""Run an offline annotated quality example; this does not run any provider."""

import argparse
import json
import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluation import evaluate
from research import ResearchSessions
from settings import Settings


def verify_expected(report, expected):
    if report["run_count"] != expected["run_count"] or len(report["groups"]) != expected["group_count"]:
        raise ValueError("Fixture run/group counts differ from the annotated expectation")
    for field in ("answer_f1", "semantic_citation_accuracy"):
        for run in report["runs"]:
            actual = run["metrics"][field]
            if actual is None or not math.isclose(actual, expected[field][run["run_id"]], abs_tol=1e-12):
                raise ValueError("Fixture annotation score mismatch: " + run["run_id"] + " / " + field)
    direct = next(system for group in report["groups"] for system in group["systems"] if system["system_id"] == "fixture-direct")
    if not math.isclose(direct["metrics"]["answer_f1"]["sample_variance"], expected["direct_f1_sample_variance"], abs_tol=1e-12):
        raise ValueError("Fixture sample variance mismatch")
    workflow = next(run for run in report["runs"] if run["run_id"] == "workflow-1")
    if workflow["metrics"]["text_coverage"] != expected["workflow_text_coverage"]:
        raise ValueError("Unavailable sources disappeared from the coverage denominator")


def markdown(report):
    fmt = lambda value: "not scored / unknown" if value is None else "%.4f" % value
    lines = ["# Annotated research evaluation", "", "Kind: **%s**" % report["kind"], "", report["limitations"][0], "",
             "No provider or model is invoked by this script. All semantic scores come from the supplied labels and rubric.", "",
             "| Run | Answer F1 | Semantic citation accuracy | Reviewed scope | Cost (USD) | Latency (s) | Measurement basis |",
             "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for run in report["runs"]:
        metrics = run["metrics"]
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" %
                     (run["run_id"], fmt(metrics["answer_f1"]), fmt(metrics["semantic_citation_accuracy"]),
                      fmt(metrics["reviewed_coverage"]), fmt(metrics["cost_usd"]), fmt(metrics["latency_seconds"]),
                      run["measurements"]["basis"]))
    lines.extend(["", "## Repeat variation and comparability", ""])
    for group in report["groups"]:
        lines.extend(["### %s / %s" % (group["task_id"], group["comparison_group"]), "",
                      "Declared controls match: %s. Differences: %s." %
                      (group["comparability"]["controlled"], ", ".join(group["comparability"]["differences"]) or "None"), "",
                      "| System | Repeats | Mean answer F1 | Sample variance |",
                      "| --- | ---: | ---: | ---: |"])
        for system in group["systems"]:
            stats = system["metrics"]["answer_f1"]
            lines.append("| %s | %s | %s | %s |" % (system["system_id"], stats["n"], fmt(stats["mean"]), fmt(stats["sample_variance"])))
        lines.append("")
    lines.extend(["## Interpretation limits", ""] + ["- " + item for item in report["limitations"]])
    lines.extend(["", "The JSON report retains rubric text, evaluator identity, null scores, missing source IDs, control differences and input hashes.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(Path(__file__).resolve().parents[1] / "tests/fixtures/research-quality.json"),
                        help="JSON with suite, runs, judgments and optional known fixture expectations")
    parser.add_argument("--output", help="Artifact directory outside plugins and canvas packages")
    args = parser.parse_args(argv)
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    report = evaluate(fixture["suite"], fixture["runs"], fixture.get("judgments"))
    if "expected" in fixture:
        verify_expected(report, fixture["expected"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Settings.external_path(args.output or str(Settings.data_directory() / "runs" / ("quality-" + stamp + "-" + uuid.uuid4().hex[:6])),
                                    "Evaluation output")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifacts = {"evaluation": str(output / "evaluation.json"), "report": str(output / "evaluation.md"), "inputs": str(output / "inputs.json")}
    ResearchSessions._write(Path(artifacts["evaluation"]), report)
    ResearchSessions._write(Path(artifacts["report"]), markdown(report))
    ResearchSessions._write(Path(artifacts["inputs"]), fixture)
    result = {"passed": True, "verification": "known_fixture_scores" if "expected" in fixture else "supplied_annotations_computed",
              "kind": report["kind"], "network_calls": 0, "provider_quality_claim": False, "artifacts": artifacts}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
