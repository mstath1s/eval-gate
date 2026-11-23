"""Loading a suite and running it.

Concurrency is bounded and results keep suite order, so a diff between two runs is readable and
an eval run does not hammer the provider's rate limit.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graders import DETERMINISTIC, grade_llm_judge
from .providers import ProviderError
from .types import Case, CaseResult, Grade, RunReport
from .validate import validate_suite


def load_suite(path: str | Path) -> dict:
    """Read and validate a suite file. Raises ValueError listing every problem it found.

    Validation is the whole check: ``validate_suite`` names the JSON path of each mistake, so a
    typo in ``cases[7].checks[1].equals`` costs one line of reading, not a debugging session.
    """
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"{source}: no such file") from None
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{source}: not valid JSON — line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from None

    validation = validate_suite(data, str(source))
    validation.raise_for_errors(source)

    data.setdefault("name", source.stem)
    data.setdefault("temperature", 0.0)
    return data


def _messages(case: Case) -> list[dict]:
    messages: list[dict] = []
    if case.system:
        messages.append({"role": "system", "content": case.system})
    messages.append({"role": "user", "content": case.input})
    return messages


def run_suite(
    suite: dict,
    provider: Any,
    model: str,
    judge_provider: Any | None = None,
    judge_model: str | None = None,
    max_workers: int = 4,
) -> RunReport:
    if judge_provider is not None and not judge_model:
        raise ProviderError("a judge provider needs a judge model")

    report = RunReport(
        suite=suite["name"],
        model=model,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    if judge_provider is not None:
        report.notes.append(f"llm_judge calls go to {judge_model} and are counted in judge_cost_usd")

    judge_costs: list[float] = []

    def judge(prompt: str) -> tuple[str, float | None]:
        completion = judge_provider.complete(
            [{"role": "user", "content": prompt}], judge_model, temperature=0.0
        )
        if completion.error:
            raise ProviderError(completion.error)
        judge_costs.append(completion.cost_usd or 0.0)
        return completion.text, completion.cost_usd

    def run_case(raw: dict) -> CaseResult:
        case = Case(
            id=raw["id"],
            input=raw["input"],
            checks=raw["checks"],
            system=raw.get("system") or suite.get("system"),
            notes=raw.get("notes", ""),
        )
        completion = provider.complete(
            _messages(case), model, temperature=float(suite.get("temperature", 0.0))
        )
        if completion.error:
            return CaseResult(
                case_id=case.id,
                passed=False,
                answer="",
                model=completion.model,
                error=completion.error,
            )

        result = CaseResult(
            case_id=case.id,
            passed=True,
            answer=completion.text,
            model=completion.model,
            latency_ms=completion.latency_ms,
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            cost_usd=completion.cost_usd,
        )
        for check in case.checks:
            name = check["grader"]
            params = {k: v for k, v in check.items() if k != "grader"}
            if name == "llm_judge":
                if judge_provider is None:
                    result.grades.append(
                        Grade(
                            grader="llm_judge",
                            passed=False,
                            score=0.0,
                            detail="no judge configured; run with --judge-model",
                        )
                    )
                    result.passed = False
                    continue
                try:
                    grade = grade_llm_judge(completion.text, params, judge)
                except ProviderError as exc:
                    grade = Grade("llm_judge", False, 0.0, f"judge call failed: {exc}")
            else:
                grade = DETERMINISTIC[name](completion.text, params)
            result.grades.append(grade)
            if not grade.passed:
                result.passed = False
        return result

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        report.results = list(pool.map(run_case, suite["cases"]))

    report.judge_cost_usd = round(sum(judge_costs), 8)
    return report
