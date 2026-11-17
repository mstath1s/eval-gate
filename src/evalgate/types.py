"""Core data types. Plain dataclasses, no dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Case:
    """One evaluation case, loaded from a suite file."""

    id: str
    input: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    system: str | None = None
    notes: str = ""


@dataclass
class Completion:
    """What a provider returned, plus what it cost to get it."""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    attempts: int = 1
    cost_usd: float | None = None
    error: str | None = None


@dataclass
class Grade:
    """One check's verdict on one answer."""

    grader: str
    passed: bool
    score: float
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    grades: list[Grade] = field(default_factory=list)
    answer: str = ""
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    error: str | None = None


@dataclass
class RunReport:
    """The whole run: what was asked, what came back, what it cost."""

    suite: str
    model: str
    started_at: str
    results: list[CaseResult] = field(default_factory=list)
    judge_cost_usd: float = 0.0
    notes: list[str] = field(default_factory=list)

    # --- derived metrics -------------------------------------------------
    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def model_cost_usd(self) -> float:
        return sum(r.cost_usd or 0.0 for r in self.results)

    @property
    def total_cost_usd(self) -> float:
        return self.model_cost_usd + self.judge_cost_usd

    @property
    def cost_unknown(self) -> bool:
        """True when at least one result carried no price for its model."""
        return any(r.cost_usd is None and r.error is None for r in self.results)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.error)

    def p95_latency_ms(self) -> int:
        if not self.results:
            return 0
        values = sorted(r.latency_ms for r in self.results)
        idx = max(0, min(len(values) - 1, int(round(0.95 * (len(values) - 1)))))
        return values[idx]

    def failed_grader_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            for grade in result.grades:
                if not grade.passed:
                    counts[grade.grader] = counts.get(grade.grader, 0) + 1
        return counts
