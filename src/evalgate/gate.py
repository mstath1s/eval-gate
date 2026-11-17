"""The gate itself: thresholds in, a verdict and an exit code out.

A gate is a small JSON file, so the thresholds live next to the code that ships them and every
change to them is a diff someone can argue with:

    {
      "min_pass_rate": 0.9,
      "max_error_rate": 0.0,
      "max_p95_latency_ms": 6000,
      "max_total_cost_usd": 0.05,
      "max_failures_per_grader": {"json_keys": 0, "llm_judge": 1},
      "require_all_cases": true
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .types import RunReport

DEFAULT_GATE = {
    "min_pass_rate": 0.9,
    "max_error_rate": 0.0,
    "max_p95_latency_ms": 0,
    "max_total_cost_usd": 0.0,
    "max_failures_per_grader": {},
    "require_all_cases": True,
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Verdict:
    passed: bool
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]


def load_gate(path: str | Path | None) -> dict:
    config = dict(DEFAULT_GATE)
    if path is None:
        return config
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    unknown = set(loaded) - set(DEFAULT_GATE)
    if unknown:
        raise ValueError(f"{path}: unknown gate keys {sorted(unknown)}")
    config.update(loaded)
    return config


def evaluate(report: RunReport, config: dict, expected_cases: int | None = None) -> Verdict:
    checks: list[Check] = []

    if config.get("require_all_cases") and expected_cases is not None:
        ok = report.total == expected_cases
        checks.append(Check("all_cases_ran", ok, f"{report.total}/{expected_cases} cases produced a result"))

    error_rate = report.errors / report.total if report.total else 1.0
    max_error_rate = float(config.get("max_error_rate", 0.0))
    checks.append(
        Check(
            "error_rate",
            error_rate <= max_error_rate,
            f"{report.errors} error(s) of {report.total}, limit {max_error_rate:.0%}",
        )
    )

    min_pass_rate = float(config.get("min_pass_rate", 0.9))
    checks.append(
        Check(
            "pass_rate",
            report.pass_rate >= min_pass_rate,
            f"{report.passed}/{report.total} passed ({report.pass_rate:.1%}), need {min_pass_rate:.0%}",
        )
    )

    failures = report.failed_grader_counts()
    for grader, limit in (config.get("max_failures_per_grader") or {}).items():
        seen = failures.get(grader, 0)
        checks.append(Check(f"grader:{grader}", seen <= int(limit), f"{seen} failure(s), limit {limit}"))

    max_p95 = int(config.get("max_p95_latency_ms", 0))
    if max_p95:
        p95 = report.p95_latency_ms()
        checks.append(Check("p95_latency_ms", p95 <= max_p95, f"{p95} ms, limit {max_p95} ms"))

    max_cost = float(config.get("max_total_cost_usd", 0.0))
    if max_cost:
        if report.cost_unknown:
            checks.append(
                Check(
                    "cost_usd",
                    False,
                    "at least one result has no price for its model; add it to pricing.json",
                )
            )
        else:
            total = report.total_cost_usd
            checks.append(Check("cost_usd", total <= max_cost, f"${total:.6f}, limit ${max_cost:.6f}"))

    return Verdict(passed=all(c.passed for c in checks), checks=checks)
