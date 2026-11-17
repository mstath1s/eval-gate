from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalgate.graders import (  # noqa: E402
    extract_json,
    grade_contains_all,
    grade_exact_match,
    grade_json_keys,
    grade_json_value,
    grade_llm_judge,
    grade_must_not_contain,
    grade_regex,
)


class TestExtractJson(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_fenced(self):
        self.assertEqual(extract_json('```json\n{"intent": "billing"}\n```'), {"intent": "billing"})

    def test_chatter_around_object(self):
        self.assertEqual(extract_json('Sure! {"intent": "refund"} hope that helps'), {"intent": "refund"})

    def test_empty_answer_raises(self):
        with self.assertRaises(ValueError):
            extract_json("")


class TestDeterministicGraders(unittest.TestCase):
    def test_exact_match_ignores_case_and_spacing(self):
        grade = grade_exact_match("  Refund   Approved ", {"equals": "refund approved"})
        self.assertTrue(grade.passed)

    def test_exact_match_reports_failure(self):
        grade = grade_exact_match("approved", {"equals": "rejected"})
        self.assertFalse(grade.passed)
        self.assertEqual(grade.score, 0.0)

    def test_contains_all_names_the_missing_needle(self):
        grade = grade_contains_all("refund in 14 days [doc:a]", {"all": ["14 days", "[doc:b]"]})
        self.assertFalse(grade.passed)
        self.assertIn("[doc:b]", grade.detail)

    def test_must_not_contain(self):
        self.assertFalse(grade_must_not_contain("we are ISO 27001 certified", {"any": ["iso 27001"]}).passed)
        self.assertTrue(grade_must_not_contain("INSUFFICIENT CONTEXT", {"any": ["iso 27001"]}).passed)

    def test_regex_is_multiline(self):
        answer = "line one\nfive users cost 124.95 USD"
        self.assertTrue(grade_regex(answer, {"pattern": r"124\.95"}).passed)

    def test_json_keys_missing(self):
        grade = grade_json_keys('{"intent": "billing"}', {"keys": ["intent", "confidence"]})
        self.assertFalse(grade.passed)
        self.assertIn("confidence", grade.detail)

    def test_json_keys_type_check(self):
        grade = grade_json_keys(
            '{"intent": "billing", "confidence": "high"}',
            {"keys": ["intent", "confidence"], "types": {"confidence": "number"}},
        )
        self.assertFalse(grade.passed)
        self.assertIn("wrong types", grade.detail)

    def test_json_keys_not_json(self):
        grade = grade_json_keys("I think this is billing.", {"keys": ["intent"]})
        self.assertFalse(grade.passed)
        self.assertIn("not JSON", grade.detail)

    def test_json_value_in(self):
        self.assertTrue(grade_json_value('{"intent": "refund"}', {"key": "intent", "in": ["refund", "billing"]}).passed)
        self.assertFalse(grade_json_value('{"intent": "technical"}', {"key": "intent", "in": ["refund", "billing"]}).passed)

    def test_json_value_boolean(self):
        self.assertTrue(grade_json_value('{"needs_human": true}', {"key": "needs_human", "equals": True}).passed)


class TestJudge(unittest.TestCase):
    def test_judge_pass(self):
        grade = grade_llm_judge(
            "124.95 USD [doc:pricing-7]",
            {"rubric": "states the total", "min_score": 4},
            judge=lambda _p: ('{"score": 5, "reason": "correct"}', 0.0001),
        )
        self.assertTrue(grade.passed)
        self.assertAlmostEqual(grade.score, 1.0)

    def test_judge_below_threshold(self):
        grade = grade_llm_judge(
            "about a hundred",
            {"rubric": "states the total", "min_score": 4},
            judge=lambda _p: ('{"score": 2, "reason": "vague"}', 0.0),
        )
        self.assertFalse(grade.passed)

    def test_judge_garbage_output_fails_closed(self):
        grade = grade_llm_judge(
            "answer",
            {"rubric": "anything", "min_score": 4},
            judge=lambda _p: ("I cannot grade this", 0.0),
        )
        self.assertFalse(grade.passed)
        self.assertIn("unparseable", grade.detail)


if __name__ == "__main__":
    unittest.main()
