"""Score annotated research outputs without pretending to be a semantic judge.

The caller supplies a fixed task, gold answers and explicit human/model labels.
No provider or model is invoked here. Missing semantic annotations yield null
scores, and synthetic demonstrations are always identified as such.
"""

import hashlib
import json
import math
import statistics


def _object(value, required, optional=(), label="object"):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError(label + " has missing or unknown fields")
    return value


def _text(value, label, maximum=16000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError(label + " must be a nonempty bounded string")
    return value


def _rows(value, label, maximum=10000):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(label + " must be a bounded list")
    return value


def _ids(value, label):
    rows = _rows(value, label, 50000)
    for item in rows:
        _text(item, label, 300)
    if len(rows) != len(set(rows)):
        raise ValueError(label + " must not contain duplicates")
    return set(rows)


def _keyed(rows, key, label, fields, optional=()):
    result = {}
    for row in _rows(rows, label):
        _object(row, fields, optional, label)
        identifier = _text(row[key], label + " id", 300)
        if identifier in result:
            raise ValueError("Duplicate " + label + " id")
        result[identifier] = row
    return result


def _number(value, label, nullable=False, maximum=None):
    if value is None and nullable:
        return value
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(label + " must be a finite nonnegative number")
    return value


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _stats(values):
    values = [value for value in values if value is not None]
    return {"n": len(values), "mean": statistics.mean(values) if values else None,
            "sample_variance": statistics.variance(values) if len(values) >= 2 else None,
            "sample_stddev": statistics.stdev(values) if len(values) >= 2 else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def _suite(suite):
    _object(suite, ("schema_version", "suite_id", "kind", "tasks", "rubric"),
            ("description", "annotation", "sources"), "suite")
    if type(suite["schema_version"]) is not int or suite["schema_version"] != 1:
        raise ValueError("Unsupported evaluation suite version")
    _text(suite["suite_id"], "suite_id", 300)
    if suite["kind"] not in ("synthetic_fixture", "annotated_benchmark"):
        raise ValueError("suite kind must identify synthetic_fixture or annotated_benchmark")
    rubric = _object(suite["rubric"], ("id", "version", "answer_matching", "citation_support", "report_quality"), label="rubric")
    for key in ("id", "version", "answer_matching", "citation_support"):
        _text(rubric[key], "rubric " + key)
    if not isinstance(rubric["report_quality"], dict) or not 1 <= len(rubric["report_quality"]) <= 20:
        raise ValueError("report_quality must define 1 to 20 rubric dimensions on a 0 to 4 scale")
    for dimension, instruction in rubric["report_quality"].items():
        _text(dimension, "Report dimension", 300)
        _text(instruction, "Report rubric")
    tasks = _keyed(suite["tasks"], "task_id", "task", ("task_id", "prompt", "gold_answers", "scope_source_ids", "question_ids"))
    if not tasks:
        raise ValueError("An evaluation suite needs tasks")
    for task in tasks.values():
        _text(task["prompt"], "Task prompt")
        _ids(task["scope_source_ids"], "Scope source IDs")
        _ids(task["question_ids"], "Question IDs")
        if task["gold_answers"] is not None:
            gold = _keyed(task["gold_answers"], "id", "gold answer", ("id", "text"), ("source_ids", "quote"))
            for answer in gold.values():
                _text(answer["text"], "Gold answer")
    return tasks


def _run(run, tasks):
    _object(run, ("run_id", "task_id", "system_id", "mode", "comparison_group", "repeat", "controls", "answers", "claims",
                  "citations", "coverage", "measurements", "report"), ("artifacts", "status", "external_run_id"), "run")
    for key in ("run_id", "task_id", "system_id", "mode", "comparison_group"):
        _text(run[key], key, 300)
    if run["task_id"] not in tasks:
        raise ValueError("Run references an unknown task")
    if type(run["repeat"]) is not int or not 1 <= run["repeat"] <= 100000:
        raise ValueError("repeat must be a positive integer")
    if not isinstance(run["report"], str) or len(run["report"]) > 1000000 or "\x00" in run["report"]:
        raise ValueError("report must be bounded text, including an empty failed result")
    if run.get("status", "completed") not in ("completed", "incomplete", "failed"):
        raise ValueError("Run status must be completed, incomplete or failed")
    controls = _object(run["controls"], ("model", "tools", "budget", "input_version", "time_window", "harness_version"), label="controls")
    for field in ("model", "input_version", "time_window", "harness_version"):
        _text(controls[field], "Control " + field, 500)
    _ids(controls["tools"], "Tools")
    if not isinstance(controls["budget"], dict) or len(controls["budget"]) > 30:
        raise ValueError("budget must be a numeric limit mapping")
    for key, value in controls["budget"].items():
        _text(key, "Budget name", 300)
        _number(value, "Budget limit", nullable=True)
    answers = _keyed(run["answers"], "answer_id", "answer", ("answer_id", "text"))
    claims = _keyed(run["claims"], "claim_id", "claim", ("claim_id", "text"))
    for row in (*answers.values(), *claims.values()):
        _text(row["text"], "Answer or claim")
    citations = _keyed(run["citations"], "citation_id", "citation", ("citation_id", "claim_id", "source_id", "quote"),
                       ("url", "research_id", "source_sha256"))
    pairs = set()
    for citation in citations.values():
        _text(citation["claim_id"], "Citation claim", 300)
        if citation["claim_id"] not in claims:
            raise ValueError("Citation references an unknown claim")
        _text(citation["source_id"], "Citation source", 300)
        _text(citation["quote"], "Citation quote")
        pair = (citation["claim_id"], citation["source_id"])
        if pair in pairs:
            raise ValueError("Deduplicate claim/source citation pairs before evaluation")
        pairs.add(pair)
    coverage = _object(run["coverage"], ("accounted_source_ids", "text_source_ids", "reviewed_source_ids", "answered_question_ids"), label="coverage")
    sets = {key: _ids(value, key) for key, value in coverage.items()}
    task = tasks[run["task_id"]]
    if not (sets["reviewed_source_ids"] <= sets["text_source_ids"] <= sets["accounted_source_ids"] <= set(task["scope_source_ids"])):
        raise ValueError("Coverage must satisfy reviewed <= text <= accounted <= original scope")
    if not sets["answered_question_ids"] <= set(task["question_ids"]):
        raise ValueError("Answered question is outside the original task")
    measurements = _object(run["measurements"], ("cost_usd", "latency_seconds", "basis", "usage"), label="measurements")
    for key in ("cost_usd", "latency_seconds"):
        _number(measurements[key], key, nullable=True)
    if measurements["basis"] not in ("observed", "reported", "synthetic"):
        raise ValueError("Measurement basis must be observed, reported or synthetic")
    if not isinstance(measurements["usage"], dict) or len(measurements["usage"]) > 50:
        raise ValueError("usage must be a numeric measurement mapping")
    for key, value in measurements["usage"].items():
        _text(key, "Usage key", 300)
        _number(value, "Usage measurement", nullable=True)
    return answers, claims, citations


def _judgment(judgment, run, task, rubric):
    if judgment is None:
        return {}, {}, {}, None
    _object(judgment, ("run_id", "rubric_id", "rubric_version", "evaluator", "answer_matches", "citation_labels", "report_scores"), label="judgment")
    if judgment["rubric_id"] != rubric["id"] or judgment["rubric_version"] != rubric["version"]:
        raise ValueError("Judgment must identify the suite rubric and version")
    evaluator = _object(judgment["evaluator"], ("kind", "name", "version"), label="evaluator")
    if evaluator["kind"] not in ("human", "model", "synthetic"):
        raise ValueError("Evaluator kind must be human, model or synthetic")
    _text(evaluator["name"], "Evaluator name", 300)
    _text(evaluator["version"], "Evaluator version", 300)
    answers = _keyed(judgment["answer_matches"], "answer_id", "answer match", ("answer_id", "gold_id"))
    run_answers = {answer["answer_id"] for answer in run["answers"]}
    gold_ids = {answer["id"] for answer in task["gold_answers"] or []}
    if not set(answers) <= run_answers:
        raise ValueError("Answer annotation references a missing prediction")
    for row in answers.values():
        if row["gold_id"] is not None:
            _text(row["gold_id"], "Matched gold id", 300)
            if row["gold_id"] not in gold_ids:
                raise ValueError("Answer annotation references an unknown gold ID")
    citations = _keyed(judgment["citation_labels"], "citation_id", "citation label", ("citation_id", "label", "reason"))
    if not set(citations) <= {citation["citation_id"] for citation in run["citations"]}:
        raise ValueError("Citation judgment references a missing citation")
    for row in citations.values():
        if row["label"] not in ("supported", "unsupported", "uncertain"):
            raise ValueError("Unknown semantic citation label")
        _text(row["reason"], "Citation judgment reason")
    scores = _keyed(judgment["report_scores"], "dimension", "report score", ("dimension", "score", "reason"))
    for row in scores.values():
        if row["dimension"] not in rubric["report_quality"]:
            raise ValueError("Unknown report rubric dimension")
        _number(row["score"], "Report quality score", maximum=4)
        _text(row["reason"], "Report judgment reason")
    return answers, citations, scores, evaluator


def _score(run, task, rubric, shape, judgment):
    answers, claims, citations = shape
    matches, labels, report_scores, evaluator = _judgment(judgment, run, task, rubric)
    gold = task["gold_answers"]
    answer_scored = gold is not None and set(matches) == set(answers)
    true_ids = {match["gold_id"] for match in matches.values() if match["gold_id"] is not None}
    tp = len(true_ids)
    fp = sum(match["gold_id"] is None for match in matches.values())
    fn = len(gold) - tp if gold is not None else None
    precision = tp / (tp + fp) if tp + fp else (1.0 if not gold else 0.0)
    recall = tp / len(gold) if gold else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    supported = sum(row["label"] == "supported" for row in labels.values())
    fully_labeled = set(labels) == set(citations)
    semantic_accuracy = _ratio(supported, len(citations)) if fully_labeled else None
    supported_claims = {citations[key]["claim_id"] for key, label in labels.items() if label["label"] == "supported"}
    cited_claims = {row["claim_id"] for row in citations.values()}
    quality_complete = set(report_scores) == set(rubric["report_quality"])
    quality = statistics.mean(row["score"] / 4 for row in report_scores.values()) if quality_complete else None
    source_count, question_count = len(task["scope_source_ids"]), len(task["question_ids"])
    coverage = {"original_source_count": source_count, "original_question_count": question_count}
    coverage_metrics = {}
    for key, prefix in (("accounted_source_ids", "accounted"), ("text_source_ids", "text"), ("reviewed_source_ids", "reviewed"),
                        ("answered_question_ids", "questions")):
        expected = set(task["question_ids"] if prefix == "questions" else task["scope_source_ids"])
        actual = set(run["coverage"][key])
        coverage[prefix] = {"count": len(actual), "rate": _ratio(len(actual), len(expected)),
                            "missing_ids": sorted(expected - actual)[:100], "missing_count": len(expected - actual)}
        coverage_metrics[prefix + "_coverage"] = coverage[prefix]["rate"]
    return {"run_id": run["run_id"], "task_id": run["task_id"], "system_id": run["system_id"], "mode": run["mode"],
            "run_sha256": _fingerprint(run), "judgment_sha256": _fingerprint(judgment) if judgment is not None else None,
            "status": run.get("status", "completed"), "repeat": run["repeat"], "comparison_group": run["comparison_group"],
            "controls": run["controls"], "evaluator": evaluator, "measurements": run["measurements"],
            "metrics": {"answer_precision": precision if answer_scored else None, "answer_recall": recall if answer_scored else None,
                        "answer_f1": f1 if answer_scored else None, "semantic_citation_accuracy": semantic_accuracy,
                        "semantic_claim_support": _ratio(len(supported_claims), len(claims)) if fully_labeled else None,
                        "citation_presence": _ratio(len(cited_claims), len(claims)), "report_quality_normalized": quality,
                        "cost_usd": run["measurements"]["cost_usd"], "latency_seconds": run["measurements"]["latency_seconds"],
                        **coverage_metrics},
            "answers": {"status": "scored" if answer_scored else "missing_gold" if gold is None else "missing_annotations",
                        "gold_count": len(gold) if gold is not None else None, "prediction_count": len(answers), "annotated_count": len(matches),
                        "true_positives": tp if answer_scored else None, "false_positives": fp if answer_scored else None,
                        "false_negatives": fn if answer_scored else None, "duplicate_gold_matches": len(matches) - tp - fp},
            "citations": {"total": len(citations), "judged": len(labels), "judgment_coverage": _ratio(len(labels), len(citations)),
                          "supported": supported, "unsupported": sum(row["label"] == "unsupported" for row in labels.values()),
                          "uncertain": sum(row["label"] == "uncertain" for row in labels.values()),
                          "accuracy_over_judged": _ratio(supported, len(labels)),
                          "semantic_accuracy_requires_all_labels": True},
            "report_quality": {"scored_dimensions": {key: row["score"] for key, row in report_scores.items()},
                               "required_dimensions": list(rubric["report_quality"]), "complete": quality_complete},
            "coverage": coverage}


def _groups(evaluations):
    groups = {}
    for row in evaluations:
        groups.setdefault((row["task_id"], row["comparison_group"]), []).append(row)
    output = []
    for (task_id, group_id), rows in sorted(groups.items()):
        differences = []
        for key in ("model", "tools", "budget", "input_version", "time_window", "harness_version"):
            values = [sorted(row["controls"][key]) if key == "tools" else row["controls"][key] for row in rows]
            if len({_fingerprint(value) for value in values}) != 1:
                differences.append(key)
        if len({_fingerprint(row["evaluator"]) for row in rows}) != 1:
            differences.append("evaluator")
        if len({row["measurements"]["basis"] for row in rows}) != 1:
            differences.append("measurement_basis")
        if any(not row["controls"]["budget"] or any(value is None for value in row["controls"]["budget"].values()) for row in rows):
            differences.append("budget_not_fully_recorded")
        strata = {}
        for row in rows:
            controls = {**row["controls"], "tools": sorted(row["controls"]["tools"])}
            signature = _fingerprint({"controls": controls, "evaluator": row["evaluator"], "basis": row["measurements"]["basis"]})
            strata.setdefault((row["system_id"], row["mode"], signature), []).append(row)
        systems = []
        for (system_id, mode, signature), repeats in sorted(strata.items()):
            if len({row["repeat"] for row in repeats}) != len(repeats):
                raise ValueError("Duplicate repeat number under the same task, system and controls")
            systems.append({"system_id": system_id, "mode": mode, "condition_id": signature,
                            "run_ids": [row["run_id"] for row in repeats], "run_count": len(repeats),
                            "failed_runs": sum(row["status"] == "failed" for row in repeats),
                            "incomplete_runs": sum(row["status"] == "incomplete" for row in repeats),
                            "controls": repeats[0]["controls"], "evaluator": repeats[0]["evaluator"],
                            "measurement_basis": repeats[0]["measurements"]["basis"],
                            "metrics": {metric: _stats([row["metrics"][metric] for row in repeats]) for metric in repeats[0]["metrics"]}})
        output.append({"task_id": task_id, "comparison_group": group_id,
                       "comparability": {"controlled": not differences, "differences": differences,
                                         "note": "Only task and declared controls are checked; no causal claim or ranking is inferred."},
                       "systems": systems})
    return output


def evaluate(suite, runs, judgments=None):
    """Evaluate the same task across modes; consume labels, do not invent them.

    Answer matching is an explicit annotation to gold IDs. Duplicate matches to
    the same gold ID count once for set precision/recall; unmatched predictions
    are false positives. Citation pairs are unique claim/source combinations.
    All-unknown cost/latency stays null. One repeat has no variance estimate.
    """
    tasks = _suite(suite)
    run_rows = _rows(runs, "runs", 10000)
    shapes, by_id = {}, {}
    for run in run_rows:
        shape = _run(run, tasks)
        if run["run_id"] in by_id:
            raise ValueError("Duplicate evaluation run_id")
        by_id[run["run_id"]], shapes[run["run_id"]] = run, shape
    judge_rows = _rows([] if judgments is None else judgments, "judgments", 10000)
    by_judge = {}
    for judgment in judge_rows:
        if not isinstance(judgment, dict) or not isinstance(judgment.get("run_id"), str):
            raise ValueError("Each judgment needs run_id")
        if judgment["run_id"] not in by_id or judgment["run_id"] in by_judge:
            raise ValueError("Judgment run_id is unknown or duplicated")
        by_judge[judgment["run_id"]] = judgment
    evaluations = [_score(run, tasks[run["task_id"]], suite["rubric"], shapes[run["run_id"]], by_judge.get(run["run_id"]))
                   for run in run_rows]
    synthetic = suite["kind"] == "synthetic_fixture" or any(
        row["measurements"]["basis"] == "synthetic" or (row["evaluator"] or {}).get("kind") == "synthetic" for row in evaluations)
    return {"schema_version": 1, "suite_id": suite["suite_id"], "suite_sha256": _fingerprint(suite),
            "runs_sha256": _fingerprint(runs), "judgments_sha256": _fingerprint(judge_rows),
            "kind": "synthetic_demonstration" if synthetic else "annotated_run_evaluation",
            "provider_quality_claim": False, "run_count": len(evaluations), "task_count": len(tasks),
            "evaluated_task_count": len({row["task_id"] for row in evaluations}),
            "rubric": suite["rubric"], "runs": evaluations, "groups": _groups(evaluations),
            "limitations": [
                "Synthetic fixture outputs and labels demonstrate the evaluator; they do not measure any host, model or provider." if synthetic else
                "Scores depend on the supplied gold data, evaluator and declared controls; the program has not independently judged semantics.",
                "Coverage uses reported IDs. Source identity and actual reading require the research evidence audit.",
                "Exact quotes, regex matches and artifact hashes are not semantic citation judgments.",
                "Missing semantic annotations and unknown measurements remain null; partial citation labels are shown separately.",
                "Report quality uses supplied rubric scores. These are not RACE, FACT or public leaderboard scores.",
                "Mean and sample variance describe supplied repeats only; fewer than two observations have no variance estimate."
            ]}
