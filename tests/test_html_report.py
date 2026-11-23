from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalgate.gate import evaluate, load_gate  # noqa: E402
from evalgate.html_report import to_html  # noqa: E402
from evalgate.pricing import load_pricing  # noqa: E402
from evalgate.providers import FakeProvider  # noqa: E402
from evalgate.suite import load_suite, run_suite  # noqa: E402
from evalgate.types import CaseResult, Grade, RunReport  # noqa: E402

PRICING = load_pricing(ROOT / "pricing.json")


class TestHtmlReport(unittest.TestCase):
    def setUp(self):
        self.suite = load_suite(ROOT / "suites" / "support-triage.json")
        answers = json.loads((ROOT / "fixtures" / "offline" / "support-triage.json").read_text(encoding="utf-8"))
        self.report = run_suite(self.suite, FakeProvider(answers, PRICING), "mistral-small-latest")
        self.gate = load_gate(ROOT / "gates" / "default.json")
        self.verdict = evaluate(self.report, self.gate, expected_cases=len(self.suite["cases"]))
        self.html = to_html(self.suite, self.report, self.verdict, self.gate,
                            provider_note="fake (offline)", title="support-triage")

    def test_it_is_one_self_contained_document(self):
        self.assertTrue(self.html.startswith("<!doctype html"))
        self.assertIn("<style>", self.html)
        self.assertNotIn("src=\"http", self.html)
        self.assertNotIn("https://cdn", self.html)

    def test_verdict_and_metrics_are_visible_before_the_details(self):
        head = self.html.split("Every case")[0]
        self.assertIn("GATE FAIL", head)
        self.assertIn("10/12", head)
        self.assertIn("83.3%", head)

    def test_every_case_and_every_failing_grader_appears(self):
        for case in self.suite["cases"]:
            self.assertIn(case["id"], self.html)
        self.assertEqual(self.html.count('class="chip"'), 2)

    def test_a_failing_case_gets_its_reason_and_grader_list(self):
        tail = self.html.split("The cases that missed")[1]
        self.assertIn("triage-003", tail)
        self.assertIn("why this case exists", tail)
        self.assertIn("expected &#x27;account&#x27;", tail)

    def test_input_text_is_escaped(self):
        suite = {"name": "demo", "cases": [{"id": "case-1", "input": "<script>alert(1)</script>", "checks": []}]}
        report = RunReport(suite="demo", model="m", started_at="now", results=[
            CaseResult(case_id="case-1", passed=False, answer="ok", grades=[Grade("exact_match", False, 0.0, "no")])
        ])
        html = to_html(suite, report, None, None)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("NO GATE", html)


if __name__ == "__main__":
    unittest.main()
