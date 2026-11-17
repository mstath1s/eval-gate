from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalgate.gate import DEFAULT_GATE, evaluate, load_gate  # noqa: E402
from evalgate.types import CaseResult, RunReport  # noqa: E402


def report(*results: CaseResult, judge_cost: float = 0.0) -> RunReport:
    rep = RunReport(suite="t", model="m", started_at="2026-01-01T00:00:00+00:00", results=list(results))
    rep.judge_cost_usd = judge_cost
    return rep


def ok(case_id: str, latency: int = 100, cost: float | None = 0.001) -> CaseResult:
    return CaseResult(case_id=case_id, passed=True, latency_ms=latency, cost_usd=cost)


def bad(case_id: str, latency: int = 100, cost: float | None = 0.001) -> CaseResult:
    return CaseResult(case_id=case_id, passed=False, latency_ms=latency, cost_usd=cost)


class TestEvaluate(unittest.TestCase):
    def test_green(self):
        config = dict(DEFAULT_GATE, min_pass_rate=0.9)
        verdict = evaluate(report(*[ok(f"c{i}") for i in range(10)]), config, expected_cases=10)
        self.assertTrue(verdict.passed, verdict.checks)

    def test_pass_rate_below_minimum(self):
        config = dict(DEFAULT_GATE, min_pass_rate=0.9)
        verdict = evaluate(report(*[ok("a"), ok("b"), bad("c")]), config, expected_cases=3)
        self.assertFalse(verdict.passed)
        self.assertIn("pass_rate", [c.name for c in verdict.failures])

    def test_errors_fail_the_gate(self):
        config = dict(DEFAULT_GATE, min_pass_rate=0.0, max_error_rate=0.0)
        errored = CaseResult(case_id="x", passed=False, error="HTTP 500")
        verdict = evaluate(report(errored), config, expected_cases=1)
        self.assertFalse(verdict.passed)
        self.assertIn("error_rate", [c.name for c in verdict.failures])

    def test_missing_cases_fail_when_required(self):
        config = dict(DEFAULT_GATE, min_pass_rate=0.0)
        verdict = evaluate(report(ok("a")), config, expected_cases=3)
        self.assertIn("all_cases_ran", [c.name for c in verdict.failures])

    def test_cost_limit(self):
        config = dict(DEFAULT_GATE, min_pass_rate=0.0, max_total_cost_usd=0.01)
        verdict = evaluate(report(ok("a", cost=0.02)), config, expected_cases=1)
        self.assertIn("cost_usd", [c.name for c in verdict.failures])

    def test_unknown_price_fails_closed(self):
        config = dict(DEFAULT_GATE, min_pass_rate=0.0, max_total_cost_usd=1.0)
        verdict = evaluate(report(ok("a", cost=None)), config, expected_cases=1)
        self.assertIn("cost_usd", [c.name for c in verdict.failures])
        self.assertIn("pricing.json", [c.detail for c in verdict.failures][0])

    def test_judge_cost_counts_towards_the_limit(self):
        config = dict(DEFAULT_GATE, min_pass_rate=0.0, max_total_cost_usd=0.015)
        rep = report(ok("a", cost=0.01), judge_cost=0.01)
        verdict = evaluate(rep, config, expected_cases=1)
        self.assertIn("cost_usd", [c.name for c in verdict.failures])

    def test_p95_latency(self):
        config = dict(DEFAULT_GATE, min_pass_rate=0.0, max_p95_latency_ms=1000)
        slow = [ok(f"c{i}", latency=5000) for i in range(4)]
        verdict = evaluate(report(*slow), config, expected_cases=4)
        self.assertIn("p95_latency_ms", [c.name for c in verdict.failures])

    def test_grader_specific_limit(self):
        from evalgate.types import Grade

        failing = CaseResult(
            case_id="c",
            passed=False,
            grades=[Grade("json_keys", False, 0.0, "missing keys")],
            cost_usd=0.0,
            latency_ms=10,
        )
        config = dict(DEFAULT_GATE, min_pass_rate=0.0, max_failures_per_grader={"json_keys": 0})
        verdict = evaluate(report(failing), config, expected_cases=1)
        self.assertIn("grader:json_keys", [c.name for c in verdict.failures])


class TestLoadGate(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(load_gate(None)["min_pass_rate"], DEFAULT_GATE["min_pass_rate"])

    def test_repo_gate_file_is_loadable(self):
        config = load_gate(ROOT / "gates" / "default.json")
        self.assertEqual(config["min_pass_rate"], 0.9)

    def test_typo_is_an_error_not_a_silent_default(self):
        path = ROOT / "tests" / "_tmp_gate.json"
        path.write_text('{"min_passrate": 0.5}', encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                load_gate(path)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
