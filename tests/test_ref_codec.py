"""Short refs preserve full identity and handle hash collisions safely."""

import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import ref_codec


class RefCodecTests(unittest.TestCase):
    def tearDown(self):
        ref_codec.clear()

    def test_round_trip_is_short_and_identity_bound(self):
        ref = ref_codec.register("b", ("source-long-id", "section-long-id", "item-long-id"))
        self.assertLessEqual(len(ref), 8)
        self.assertEqual({"kind": "b", "identity": ["source-long-id", "section-long-id", "item-long-id"]},
                         ref_codec.resolve(ref))

    def test_scope_collision_gets_distinct_sequence(self):
        with patch.object(ref_codec, "_scope", return_value="same"):
            first = ref_codec.register("b", ("source-a", "section", "item"))
            second = ref_codec.register("b", ("source-b", "section", "item"))
        self.assertNotEqual(first, second)
        self.assertEqual(["source-a", "section", "item"], ref_codec.resolve(first)["identity"])
        self.assertEqual(["source-b", "section", "item"], ref_codec.resolve(second)["identity"])


if __name__ == "__main__":
    unittest.main()
