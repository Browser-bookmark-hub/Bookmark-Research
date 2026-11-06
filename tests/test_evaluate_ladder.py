"""The ladder gate rejects incomplete and silently degraded runs."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_ladder import CATEGORIES, evaluate, template


class EvaluateLadderTests(unittest.TestCase):
    @staticmethod
    def completed_template():
        data = template()
        for question in data["questions"]:
            question["prompt"] = "Frozen prompt for " + question["id"]
            question["target_refs"] = ["expected-ref"]
            question["runs"] = [
                {"steps": steps, "wall_seconds": float(steps), "q1_matches": 1,
                 "q1_citations": 1, "q2_claims": [{"claim": "Supported claim",
                 "source_ids": ["source-1"], "supported": True}],
                 "q3_content_state_misses": 0, "q4_silent_truncations": 0,
                 "q5_coverage_gaps": 0}
                for steps in (4, 3, 5)
            ]
        return data

    def test_ladder_requires_three_questions_per_category_and_three_runs(self):
        data = self.completed_template()
        data["questions"][0]["runs"].pop()
        with self.assertRaisesRegex(ValueError, "at least three runs"):
            evaluate(data)

    def test_clean_ladder_passes_all_automated_and_human_annotated_gates(self):
        result = evaluate(self.completed_template())
        self.assertTrue(result["gate_pass"])
        self.assertEqual(15, result["question_count"])
        self.assertEqual(45, result["run_count"])
        self.assertEqual(4, result["median_steps"])
        self.assertEqual(1.0, result["q1"]["rate"])
        self.assertEqual(1.0, result["q2"]["rate"])
        self.assertEqual({category: 3 for category in CATEGORIES}, result["category_counts"])

    def test_any_silent_truncation_fails_the_quality_gate(self):
        data = self.completed_template()
        data["questions"][4]["runs"][0]["q4_silent_truncations"] = 1
        self.assertFalse(evaluate(data)["gate_pass"])


if __name__ == "__main__":
    unittest.main()
