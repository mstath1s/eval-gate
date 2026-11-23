from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalgate.explain import explain_run  # noqa: E402
from evalgate.gate import evaluate, load_gate  # noqa: E402
from evalgate.pricing import load_pricing  # noqa: E402
from evalgate.providers import FakeProvider  # noqa: E402
from evalgate.suite import load_suite, run_suite  # noqa: E402

PRICING = load_pricing(ROOT / "pricing.json")
PROVIDER = "fake (offline: latency and cost are simulated, not measured)"


class TestExplainRun(unittest.TestCase):
    def setUp(self):
        self.suite = load_suite(ROOT / "suites" / "support-triage.json")
        answers = json.loads((ROOT / "fixtures" / "offline" / "support-triage.json").read_text(encoding="utf-8"))
        self.report = run_suite(self.suite, FakeProvider(answers, PRICING), "mistral-small-latest")
        self.gate = load_gate(ROOT / "gates" / "default.json")
        self.verdict = evaluate(self.report, self.gate, expected_cases=len(self.suite["cases"]))
        self.text = explain_run(
            self.suite, self.report, self.verdict, self.gate,
            suite_path="suites/support-triage.json", provider_note=PROVIDER,
        )

    def test_every_case_appears_with_its_input_answer_and_notes(self):
        for case in self.suite["cases"]:
            self.assertIn(case["id"], self.text)
            self.assertIn(" ".join(case["input"].split())[:40], self.text)
            self.assertIn(" ".join(case["notes"].split())[:40], self.text)

    def test_the_setup_is_stated_before_any_result(self):
        head = self.text.split("CASE BY CASE")[0]
        self.assertIn("suites/support-triage.json", head)
        self.assertIn("temperature 0.0", head)
        self.assertIn("json_keys, json_value, must_not_contain", head)
        self.assertIn("simulated", head)

    def test_gate_section_carries_the_arithmetic_and_the_verdict(self):
        gate = self.text.split("THE GATE")[1]
        self.assertIn("10/12 passed (83.3%), need 90%", gate)
        self.assertIn("=> GATE: FAIL", gate)
        self.assertIn("triage-003", gate)

    def test_failing_case_is_explained_with_the_grader_that_caught_it(self):
        section = self.text.split("WHAT FAILED, IN WORDS")[1]
        self.assertIn("triage-008", section)
        self.assertIn("intent='account' (expected 'billing')", section)

    def test_the_limits_of_the_run_are_named(self):
        tail = self.text.split("WHAT THIS RUN DOES NOT TELL YOU")[1]
        self.assertIn("A gate is a floor, not a score", tail)
        self.assertIn("simulated", tail)
        self.assertIn("No case used llm_judge", tail)

    def test_a_run_without_a_gate_says_so_instead_of_inventing_a_verdict(self):
        text = explain_run(self.suite, self.report, None, None, provider_note=PROVIDER)
        self.assertIn("no gate configured", text)
        self.assertNotIn("=> GATE", text)


if __name__ == "__main__":
    unittest.main()
