"""Annotated set metrics, semantic-label boundaries and controlled comparisons."""

import copy
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluation import evaluate


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent / "fixtures/research-quality.json").read_text())
        self.suite = self.fixture["suite"]
        self.runs = self.fixture["runs"]
        self.judgments = self.fixture["judgments"]

    def score(self):
        return evaluate(self.suite, self.runs, self.judgments)

    def test_fixture_scores_labeled_answers_and_support_with_sample_variance(self):
        original = copy.deepcopy(self.fixture)
        report = self.score()
        expected = self.fixture["expected"]
        self.assertEqual(report["run_count"], expected["run_count"])
        self.assertEqual(len(report["groups"]), expected["group_count"])
        for row in report["runs"]:
            self.assertAlmostEqual(row["metrics"]["answer_f1"], expected["answer_f1"][row["run_id"]])
            self.assertAlmostEqual(row["metrics"]["semantic_citation_accuracy"], expected["semantic_citation_accuracy"][row["run_id"]])
        direct = next(row for row in report["groups"][0]["systems"] if row["system_id"] == "fixture-direct")
        self.assertAlmostEqual(direct["metrics"]["answer_f1"]["sample_variance"], expected["direct_f1_sample_variance"])
        self.assertEqual(direct["metrics"]["answer_f1"]["n"], 2)
        self.assertTrue(report["groups"][0]["comparability"]["controlled"])
        self.assertEqual(report["kind"], "synthetic_demonstration")
        self.assertFalse(report["provider_quality_claim"])
        self.assertIn("do not measure any host", report["limitations"][0])
        self.assertEqual(self.fixture, original)

    def test_matching_quotes_without_judgments_does_not_score_semantics(self):
        report = evaluate(self.suite, self.runs)
        for row in report["runs"]:
            self.assertIsNone(row["metrics"]["answer_f1"])
            self.assertIsNone(row["metrics"]["semantic_citation_accuracy"])
            self.assertIsNone(row["metrics"]["report_quality_normalized"])
            self.assertEqual(row["citations"]["judged"], 0)
            self.assertIsNotNone(row["metrics"]["accounted_coverage"])
        self.assertEqual(report["runs"][0]["metrics"]["citation_presence"], 1)

    def test_partial_labels_do_not_inflate_full_semantic_scores(self):
        self.judgments[0]["answer_matches"] = self.judgments[0]["answer_matches"][:1]
        self.judgments[0]["citation_labels"] = self.judgments[0]["citation_labels"][:1]
        self.judgments[0]["report_scores"] = self.judgments[0]["report_scores"][:1]
        first = self.score()["runs"][0]
        self.assertIsNone(first["metrics"]["answer_f1"])
        self.assertIsNone(first["metrics"]["semantic_citation_accuracy"])
        self.assertIsNone(first["metrics"]["report_quality_normalized"])
        self.assertEqual(first["citations"]["accuracy_over_judged"], 1)
        self.assertEqual(first["citations"]["judgment_coverage"], 0.5)

    def test_uncertain_labels_remain_in_accuracy_denominator(self):
        row = next(row for row in self.score()["runs"] if row["run_id"] == "professional-1")
        self.assertEqual(row["citations"]["uncertain"], 1)
        self.assertEqual(row["metrics"]["semantic_citation_accuracy"], 0.5)
        self.assertEqual(row["metrics"]["semantic_claim_support"], 0.5)

    def test_no_gold_or_missing_measurements_stay_unknown(self):
        self.suite["tasks"][0]["gold_answers"] = None
        for judgment in self.judgments:
            judgment["answer_matches"] = []
        for run in self.runs:
            run["measurements"].update(cost_usd=None, latency_seconds=None)
        report = self.score()
        for row in report["runs"]:
            self.assertEqual(row["answers"]["status"], "missing_gold")
            self.assertIsNone(row["metrics"]["answer_f1"])
        for system in report["groups"][0]["systems"]:
            self.assertEqual(system["metrics"]["cost_usd"]["n"], 0)
            self.assertIsNone(system["metrics"]["cost_usd"]["mean"])
            self.assertIsNone(system["metrics"]["latency_seconds"]["sample_variance"])

    def test_single_repeat_has_no_variance_estimate(self):
        report = evaluate(self.suite, self.runs[:1], self.judgments[:1])
        metric = report["groups"][0]["systems"][0]["metrics"]["answer_f1"]
        self.assertEqual(metric["n"], 1)
        self.assertIsNone(metric["sample_variance"])
        self.assertIsNone(metric["sample_stddev"])

    def test_control_differences_are_reported_and_not_averaged_together(self):
        self.runs[1]["controls"]["model"] = "different-fixture-model"
        self.runs[1]["controls"]["time_window"] = "a different snapshot time"
        self.runs[1]["controls"]["budget"]["max_search_calls"] = 80
        report = self.score()
        group = report["groups"][0]
        self.assertFalse(group["comparability"]["controlled"])
        self.assertCountEqual(group["comparability"]["differences"], ["model", "budget", "time_window"])
        direct = [row for row in group["systems"] if row["system_id"] == "fixture-direct"]
        self.assertEqual(len(direct), 2)
        self.assertTrue(all(row["run_count"] == 1 for row in direct))
        self.runs[1]["controls"] = copy.deepcopy(self.runs[0]["controls"])
        self.runs[1]["controls"]["tools"].reverse()
        self.assertTrue(self.score()["groups"][0]["comparability"]["controlled"])

    def test_duplicate_answer_matches_cannot_increase_recall(self):
        run, judgment = self.runs[1], self.judgments[1]
        run["answers"].append({"answer_id": "alias", "text": "Another mention of Aurora"})
        judgment["answer_matches"].append({"answer_id": "alias", "gold_id": "aurora"})
        row = self.score()["runs"][1]
        self.assertEqual(row["answers"]["true_positives"], 1)
        self.assertEqual(row["answers"]["duplicate_gold_matches"], 1)
        self.assertEqual(row["metrics"]["answer_recall"], 0.5)
        self.assertAlmostEqual(row["metrics"]["answer_f1"], 2 / 3)

    def test_original_scope_denominator_and_failed_runs_are_retained(self):
        report = self.score()
        workflow = next(row for row in report["runs"] if row["run_id"] == "workflow-1")
        self.assertEqual(workflow["metrics"]["accounted_coverage"], 1)
        self.assertEqual(workflow["metrics"]["text_coverage"], 0.75)
        self.assertEqual(workflow["coverage"]["text"]["missing_ids"], ["src-outage"])
        failed = copy.deepcopy(self.runs[0])
        failed.update(status="failed", answers=[], claims=[], citations=[], report="")
        report = evaluate(self.suite, [failed])
        self.assertEqual(report["runs"][0]["metrics"]["answer_f1"], 0)
        self.assertEqual(report["groups"][0]["systems"][0]["failed_runs"], 1)

    def test_bad_ids_nonfinite_metrics_duplicate_pairs_and_rubrics_are_rejected(self):
        cases = []
        value = copy.deepcopy(self.fixture)
        value["runs"][0]["coverage"]["reviewed_source_ids"].append("src-outage")
        cases.append(value)
        value = copy.deepcopy(self.fixture)
        value["runs"][0]["measurements"]["cost_usd"] = math.nan
        cases.append(value)
        value = copy.deepcopy(self.fixture)
        value["judgments"][0]["rubric_version"] = "unrelated"
        cases.append(value)
        value = copy.deepcopy(self.fixture)
        value["judgments"][0]["citation_labels"][0]["citation_id"] = "invented"
        cases.append(value)
        value = copy.deepcopy(self.fixture)
        value["judgments"][0]["answer_matches"][0]["gold_id"] = "invented"
        cases.append(value)
        value = copy.deepcopy(self.fixture)
        value["runs"][0]["citations"].append({**value["runs"][0]["citations"][0], "citation_id": "inflated"})
        cases.append(value)
        value = copy.deepcopy(self.fixture)
        value["runs"][1]["repeat"] = 1
        cases.append(value)
        value = copy.deepcopy(self.fixture)
        value["judgments"][0]["report_scores"][0]["score"] = 5
        cases.append(value)
        for i, value in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(ValueError):
                evaluate(value["suite"], value["runs"], value["judgments"])

    def test_report_hashes_pin_exact_inputs_and_annotations(self):
        first = self.score()
        self.judgments[0]["citation_labels"][0]["reason"] += " Added a rationale."
        second = self.score()
        self.assertEqual(first["runs_sha256"], second["runs_sha256"])
        self.assertNotEqual(first["judgments_sha256"], second["judgments_sha256"])
        self.assertNotEqual(first["runs"][0]["judgment_sha256"], second["runs"][0]["judgment_sha256"])
        self.assertEqual(first["runs"][0]["metrics"], second["runs"][0]["metrics"])

    def test_verification_script_writes_reproducible_external_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="quality demo 中文 ") as temporary:
            command = [sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "scripts/verify_quality.py"), "--output", temporary]
            completed = subprocess.run(command, capture_output=True, text=True, check=True)
            result = json.loads(completed.stdout)
            self.assertTrue(result["passed"])
            self.assertFalse(result["provider_quality_claim"])
            self.assertEqual(result["network_calls"], 0)
            report = json.loads(Path(result["artifacts"]["evaluation"]).read_text())
            self.assertEqual(report["run_count"], 6)
            self.assertIn("synthetic", Path(result["artifacts"]["report"]).read_text().lower())
            self.assertEqual(json.loads(Path(result["artifacts"]["inputs"]).read_text()), self.fixture)


if __name__ == "__main__":
    unittest.main()
