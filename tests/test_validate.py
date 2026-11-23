from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalgate.gate import DEFAULT_GATE  # noqa: E402
from evalgate.suite import load_suite  # noqa: E402
from evalgate.validate import GATE_KEYS, validate_gate, validate_suite  # noqa: E402


def suite(**overrides) -> dict:
    base = {
        "name": "demo",
        "version": 1,
        "temperature": 0.0,
        "cases": [
            {"id": "case-1", "input": "hello", "notes": "why it exists",
             "checks": [{"grader": "exact_match", "equals": "hi"}]}
        ],
    }
    base.update(overrides)
    return base


class TestSuiteValidation(unittest.TestCase):
    def test_bundled_suite_is_clean(self):
        validation = validate_suite(json.loads((ROOT / "suites" / "support-triage.json").read_text(encoding="utf-8")))
        self.assertTrue(validation.ok, validation.errors)
        self.assertEqual(validation.stats["cases"], 12)
        self.assertEqual(validation.warnings, [])
        self.assertEqual(validation.stats["graders"], ["json_keys", "json_value", "must_not_contain"])

    def test_duplicate_ids_name_both_places(self):
        data = suite()
        data["cases"].append(dict(data["cases"][0]))
        validation = validate_suite(data)
        self.assertFalse(validation.ok)
        self.assertIn("duplicate id 'case-1'", str(validation.errors[0]))
        self.assertIn("cases[1].id", str(validation.errors[0]))
        self.assertIn("cases[0]", str(validation.errors[0]))

    def test_unknown_grader_names_the_path_and_the_options(self):
        data = suite()
        data["cases"][0]["checks"] = [{"grader": "vibes"}]
        validation = validate_suite(data)
        self.assertIn("cases[0].checks[0].grader", str(validation.errors[0]))
        self.assertIn("known graders", str(validation.errors[0]))

    def test_json_value_needs_exactly_one_of_equals_and_in(self):
        for params in ({"key": "k"}, {"key": "k", "equals": 1, "in": [1, 2]}):
            data = suite()
            data["cases"][0]["checks"] = [{"grader": "json_value", **params}]
            validation = validate_suite(data)
            self.assertFalse(validation.ok)
            self.assertIn("exactly one of 'equals' or 'in'", str(validation.errors[0]))

    def test_wrong_parameter_type_is_an_error_with_the_expected_kind(self):
        data = suite()
        data["cases"][0]["checks"] = [{"grader": "contains_all", "all": "not-a-list"}]
        validation = validate_suite(data)
        self.assertIn("expected an array of strings", str(validation.errors[0]))

    def test_json_keys_rejects_an_unknown_json_type(self):
        data = suite()
        data["cases"][0]["checks"] = [{"grader": "json_keys", "keys": ["a"], "types": {"a": "float"}}]
        self.assertIn("unknown JSON type name", str(validate_suite(data).errors[0]))

    def test_missing_input_and_empty_checks_are_errors(self):
        data = suite()
        data["cases"][0].pop("input")
        data["cases"][0]["checks"] = []
        errors = " | ".join(str(issue) for issue in validate_suite(data).errors)
        self.assertIn("cases[0].input", errors)
        self.assertIn("cases[0].checks", errors)

    def test_missing_notes_is_a_warning_not_an_error(self):
        data = suite()
        data["cases"][0].pop("notes")
        validation = validate_suite(data)
        self.assertTrue(validation.ok)
        self.assertIn("no 'notes'", str(validation.warnings[0]))

    def test_large_temperature_warns_because_a_gate_would_wobble(self):
        self.assertIn("wobble", str(validate_suite(suite(temperature=0.8)).warnings[0]))

    def test_llm_judge_without_a_question_warns_and_min_score_above_scale_errors(self):
        data = suite()
        data["cases"][0]["checks"] = [{"grader": "llm_judge", "rubric": "is it good", "scale": 5, "min_score": 7}]
        validation = validate_suite(data)
        self.assertIn("min_score is above scale", str(validation.errors[0]))
        self.assertIn("without 'question'", str(validation.warnings[0]))

    def test_raise_for_errors_lists_every_problem(self):
        data = suite()
        data["cases"][0]["checks"] = [{"grader": "nope"}, {"grader": "json_value", "key": "k"}]
        with self.assertRaises(ValueError) as caught:
            validate_suite(data).raise_for_errors("demo.json")
        message = str(caught.exception)
        self.assertIn("demo.json", message)
        self.assertIn("2 problem(s)", message)


class TestGateValidation(unittest.TestCase):
    def test_validator_and_gate_module_agree_on_the_keys(self):
        self.assertEqual(set(GATE_KEYS), set(DEFAULT_GATE))

    def test_bundled_gate_is_clean(self):
        self.assertTrue(validate_gate(json.loads((ROOT / "gates" / "default.json").read_text(encoding="utf-8"))).ok)

    def test_percent_written_where_a_fraction_belongs_is_an_error(self):
        validation = validate_gate({"min_pass_rate": 90})
        self.assertIn("fraction between 0 and 1", str(validation.errors[0]))

    def test_unknown_key_is_an_error_because_it_would_never_fire(self):
        self.assertIn("unknown gate key", str(validate_gate({"max_cost": 1}).errors[0]))

    def test_limit_on_an_unknown_grader_warns(self):
        validation = validate_gate({"max_failures_per_grader": {"json_key": 0}})
        self.assertTrue(validation.ok)
        self.assertIn("can never fire", str(validation.warnings[0]))

    def test_negative_latency_or_cost_is_an_error(self):
        self.assertIn("milliseconds", str(validate_gate({"max_p95_latency_ms": -1}).errors[0]))
        self.assertIn("amount in USD", str(validate_gate({"max_total_cost_usd": -0.1}).errors[0]))


class TestLoaderUsesTheValidator(unittest.TestCase):
    def test_load_suite_error_names_the_case_and_the_parameter(self):
        path = ROOT / "tests" / "_tmp_bad.json"
        path.write_text(json.dumps({
            "cases": [{"id": "case-1", "input": "x",
                       "checks": [{"grader": "json_value", "key": "k", "equals": 1, "in": [1]}]}]
        }), encoding="utf-8")
        try:
            with self.assertRaises(ValueError) as caught:
                load_suite(path)
            self.assertIn("cases[0].checks[0]", str(caught.exception))
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
