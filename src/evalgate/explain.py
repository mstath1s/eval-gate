"""A run, explained.

``report.to_markdown`` is the artifact for a pull request: dense, for someone who already knows
what they are reading. This module is for the person who wants to see the machine think — it
prints the setup, then every case with its input, the reason the case exists, the answer, and each
grader's verdict and detail, then the gate arithmetic line by line, then what the run cannot prove.

Nothing here is a summary of a summary: every number comes from the report object.
"""

from __future__ import annotations

from .gate import Verdict
from .types import RunReport


def _clip(text: str, width: int = 96) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def _case_notes(suite: dict) -> dict[str, str]:
    return {case.get("id", ""): case.get("notes", "") for case in suite.get("cases", [])}


def case_inputs(suite: dict) -> dict[str, str]:
    """The text sent to the model, by case id: a result carries the answer, not the question."""
    return {case.get("id", ""): case.get("input", "") for case in suite.get("cases", [])}


def _grader_rows(result) -> list[tuple[str, str, str]]:
    return [(("PASS" if grade.passed else "FAIL"), grade.grader, grade.detail) for grade in result.grades]


def explain_run(
    suite: dict,
    report: RunReport,
    verdict: Verdict | None,
    gate_config: dict | None,
    suite_path: str = "",
    provider_note: str = "",
) -> str:
    notes = _case_notes(suite)
    inputs = case_inputs(suite)
    graders = sorted({grade.grader for result in report.results for grade in result.grades})
    system = suite.get("system") or ""
    lines: list[str] = []

    lines.append(f"eval-gate · {report.suite} · {report.total} case(s) · model {report.model}")
    lines.append("=" * 100)
    lines.append("")
    lines.append("HOW THIS RUN WAS PUT TOGETHER")
    lines.append(f"  suite       {suite_path or '(in memory)'} · version {suite.get('version', '?')}")
    lines.append(f"  system      {(_clip(system, 84) + ' (' + str(len(system)) + ' chars)') if system else '(none: no system prompt)'}")
    lines.append(f"  temperature {suite.get('temperature', 0.0)}")
    lines.append(f"  graders     {', '.join(graders) or 'none'}")
    lines.append(f"  provider    {provider_note or report.model}")
    lines.append(f"  started     {report.started_at}")
    lines.append("  Each case sends the system prompt plus the case input, then runs every check on")
    lines.append("  the answer. A case passes only when all of its checks pass; the gate then looks at")
    lines.append("  the run as a whole, not at any single case.")
    lines.append("")

    lines.append("CASE BY CASE")
    for index, result in enumerate(report.results, 1):
        cost = "cost unknown" if result.cost_usd is None else f"${result.cost_usd:.8f}"
        lines.append("")
        lines.append(f"  {index:>2}. {result.case_id:<14} {'PASS' if result.passed else 'FAIL':<5} {result.latency_ms:>6} ms  {cost}")
        if notes.get(result.case_id):
            lines.append(f"      why     {_clip(notes[result.case_id])}")
        lines.append(f"      input   {_clip(inputs.get(result.case_id, ''))}")
        if result.error:
            lines.append(f"      error   {_clip(result.error)}")
        else:
            lines.append(f"      answer  {_clip(result.answer, 88)}")
            passed = sum(1 for grade in result.grades if grade.passed)
            lines.append(f"      checks  {passed}/{len(result.grades)} passed")
            for state, grader, detail in _grader_rows(result):
                lines.append(f"        {state}  {grader:<16} {_clip(detail, 62)}")

    lines.append("")
    lines.append("THE GATE")
    if verdict is None or gate_config is None:
        lines.append("  no gate configured: this run reports numbers and takes no decision.")
    else:
        labels = {
            "all_cases_ran": "all_cases_ran",
            "error_rate": "error_rate",
            "pass_rate": "pass_rate",
            "p95_latency_ms": "p95_latency_ms",
            "cost_usd": "cost_usd",
        }
        for check in verdict.checks:
            name = labels.get(check.name, check.name)
            lines.append(f"  {'PASS' if check.passed else 'FAIL'}  {name:<18} {_clip(check.detail, 74)}")
        failed = verdict.failures
        lines.append("")
        lines.append(
            f"  => GATE: {'PASS' if verdict.passed else 'FAIL'} — {len(verdict.checks) - len(failed)} of "
            f"{len(verdict.checks)} check(s) passed"
        )
        if failed:
            lines.append("")
            lines.append("WHAT FAILED, IN WORDS")
            for check in failed:
                lines.append(f"  {check.name}: {check.detail}")
                if check.name == "pass_rate":
                    bad = [r.case_id for r in report.results if not r.passed]
                    lines.append(f"    the cases that missed: {', '.join(bad)}")
                    for result in report.results:
                        if result.passed or result.error:
                            continue
                        reasons = "; ".join(
                            f"{grade.grader} said {_clip(grade.detail, 70)}"
                            for grade in result.grades
                            if not grade.passed
                        )
                        lines.append(f"      {result.case_id}: {reasons}")
                elif check.name == "error_rate":
                    lines.append(f"    cases with no usable answer: "
                                 f"{', '.join(r.case_id for r in report.results if r.error) or 'none'}")
                elif check.name == "cost_usd" and report.cost_unknown:
                    lines.append("    at least one answer has no price for its model; add the model to pricing.json")
                elif check.name.startswith("grader:"):
                    grader = check.name.split(":", 1)[1]
                    guilty = [r.case_id for r in report.results
                              if any(g.grader == grader and not g.passed for g in r.grades)]
                    lines.append(f"    cases where {grader} failed: {', '.join(guilty) or 'none'}")

    lines.append("")
    lines.append("WHAT THIS RUN DOES NOT TELL YOU")
    lines.append("  - A gate is a floor, not a score. It cannot say the answers are good, only that they")
    lines.append("    cleared the checks someone wrote for them.")
    if "fake" in (provider_note or ""):
        lines.append("  - Latency and cost here are simulated: the offline provider never calls a model, so")
        lines.append("    the p95 and the dollar figure measure the harness, not a provider.")
    if not any(grade.grader == "llm_judge" for result in report.results for grade in result.grades):
        lines.append("  - No case used llm_judge, so no answer was judged for meaning — only for shape and")
        lines.append("    for values written down in advance.")
    if gate_config is None:
        lines.append("  - No gate was applied, so this run has no verdict.")
    lines.append("")
    return "\n".join(lines)
