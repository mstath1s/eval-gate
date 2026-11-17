from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalgate.providers import FakeProvider  # noqa: E402
from evalgate.pricing import load_pricing  # noqa: E402
from evalgate.suite import load_suite, run_suite  # noqa: E402

PRICING = load_pricing(ROOT / "pricing.json")


def fixtures(name: str) -> dict:
    return json.loads((ROOT / "fixtures" / "offline" / f"{name}.json").read_text(encoding="utf-8"))


class TestLoadSuite(unittest.TestCase):
    def test_bundled_suites_are_valid(self):
        triage = load_suite(ROOT / "suites" / "support-triage.json")
        grounded = load_suite(ROOT / "suites" / "grounded-answers.json")
        self.assertEqual(len(triage["cases"]), 12)
        self.assertEqual(len(grounded["cases"]), 6)

    def test_unknown_grader_is_rejected(self):
        path = ROOT / "tests" / "_tmp_suite.json"
        path.write_text(
            json.dumps({"cases": [{"id": "a", "input": "x", "checks": [{"grader": "vibes"}]}]}),
            encoding="utf-8",
        )
        try:
            with self.assertRaises(ValueError):
                load_suite(path)
        finally:
            path.unlink()

    def test_case_without_checks_is_rejected(self):
        path = ROOT / "tests" / "_tmp_suite.json"
        path.write_text(json.dumps({"cases": [{"id": "a", "input": "x", "checks": []}]}), encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                load_suite(path)
        finally:
            path.unlink()


class TestRunOffline(unittest.TestCase):
    def setUp(self):
        self.suite = load_suite(ROOT / "suites" / "support-triage.json")
        self.provider = FakeProvider(fixtures("support-triage"), PRICING)

    def test_shape_and_order(self):
        report = run_suite(self.suite, self.provider, "mistral-small-latest")
        self.assertEqual(report.total, 12)
        self.assertEqual([r.case_id for r in report.results], [c["id"] for c in self.suite["cases"]])
        self.assertEqual(report.errors, 0)

    def test_the_two_deliberate_fixture_failures_are_caught(self):
        report = run_suite(self.suite, self.provider, "mistral-small-latest")
        failed = sorted(r.case_id for r in report.results if not r.passed)
        self.assertEqual(failed, ["triage-003", "triage-008"])
        self.assertAlmostEqual(report.pass_rate, 10 / 12)

    def test_failure_detail_names_the_expected_value(self):
        report = run_suite(self.suite, self.provider, "mistral-small-latest")
        result = next(r for r in report.results if r.case_id == "triage-003")
        detail = " ".join(g.detail for g in result.grades if not g.passed)
        self.assertIn("account", detail)

    def test_costs_are_computed_from_the_pricing_table(self):
        report = run_suite(self.suite, self.provider, "mistral-small-latest")
        self.assertFalse(report.cost_unknown)
        self.assertGreater(report.total_cost_usd, 0.0)

    def test_missing_scripted_answer_is_an_error_not_a_pass(self):
        provider = FakeProvider({}, PRICING)
        report = run_suite(self.suite, provider, "mistral-small-latest")
        self.assertEqual(report.errors, 12)
        self.assertEqual(report.passed, 0)

    def test_unknown_model_makes_cost_unknown(self):
        report = run_suite(self.suite, self.provider, "not-a-priced-model")
        self.assertTrue(report.cost_unknown)

    def test_llm_judge_without_a_judge_fails_closed(self):
        grounded = load_suite(ROOT / "suites" / "grounded-answers.json")
        report = run_suite(grounded, FakeProvider(fixtures("grounded-answers"), PRICING), "mistral-small-latest")
        judged = next(r for r in report.results if r.case_id == "ground-003")
        self.assertFalse(judged.passed)
        detail = " ".join(g.detail for g in judged.grades)
        self.assertIn("no judge configured", detail)

    def test_judge_cost_is_tracked_separately(self):
        grounded = load_suite(ROOT / "suites" / "grounded-answers.json")
        answers = fixtures("grounded-answers")
        judge_answers = fixtures("judge-answers")
        report = run_suite(
            grounded,
            FakeProvider(answers, PRICING),
            "mistral-small-latest",
            judge_provider=FakeProvider(judge_answers, PRICING, match="contains"),
            judge_model="mistral-small-latest",
        )
        self.assertGreater(report.judge_cost_usd, 0.0)
        judged = next(r for r in report.results if r.case_id == "ground-003")
        self.assertTrue(judged.passed, [g.detail for g in judged.grades])


if __name__ == "__main__":
    unittest.main()
