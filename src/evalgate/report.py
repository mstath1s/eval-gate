"""Report rendering: one JSON file for machines, one Markdown file for the pull request."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .gate import Verdict
from .types import RunReport


def to_dict(report: RunReport, verdict: Verdict | None, gate_config: dict | None) -> dict:
    return {
        "suite": report.suite,
        "model": report.model,
        "started_at": report.started_at,
        "metrics": {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "errors": report.errors,
            "pass_rate": round(report.pass_rate, 4),
            "p95_latency_ms": report.p95_latency_ms(),
            "model_cost_usd": round(report.model_cost_usd, 8),
            "judge_cost_usd": round(report.judge_cost_usd, 8),
            "total_cost_usd": round(report.total_cost_usd, 8),
            "cost_unknown": report.cost_unknown,
            "failed_graders": report.failed_grader_counts(),
        },
        "gate": None
        if verdict is None
        else {
            "passed": verdict.passed,
            "config": gate_config,
            "checks": [asdict(c) for c in verdict.checks],
        },
        "notes": report.notes,
        "results": [asdict(r) for r in report.results],
    }


def to_markdown(report: RunReport, verdict: Verdict | None, gate_config: dict | None) -> str:
    verdict_line = (
        "**GATE: PASS**" if verdict and verdict.passed else "**GATE: FAIL**" if verdict else "**no gate configured**"
    )
    lines = [
        f"# eval-gate — {report.suite}",
        "",
        f"- Model: `{report.model}`",
        f"- Run at: {report.started_at}",
        f"- Cases: {report.total} · passed {report.passed} · failed {report.failed} · errors {report.errors}",
        f"- Pass rate: {report.pass_rate:.1%}",
        f"- p95 latency: {report.p95_latency_ms()} ms",
        f"- Cost: ${report.total_cost_usd:.6f} (model ${report.model_cost_usd:.6f}"
        + (f", judge ${report.judge_cost_usd:.6f})" if report.judge_cost_usd else ")")
        + (" — **unknown for at least one model**" if report.cost_unknown else ""),
        "",
        verdict_line,
        "",
    ]

    if verdict is not None:
        lines.append("| check | result | detail |")
        lines.append("| --- | --- | --- |")
        for check in verdict.checks:
            lines.append(f"| {check.name} | {'pass' if check.passed else '**fail**'} | {check.detail} |")
        lines.append("")

    problems = [r for r in report.results if not r.passed]
    if problems:
        lines.append("## Failing cases")
        lines.append("")
        for result in problems:
            lines.append(f"### `{result.case_id}`")
            if result.error:
                lines.append(f"- error: {result.error}")
            for grade in result.grades:
                if not grade.passed:
                    lines.append(f"- {grade.grader}: {grade.detail}")
            if result.answer:
                preview = result.answer.strip().replace("\n", " ")[:200]
                lines.append(f"- answer: `{preview}`")
            lines.append("")

    lines.append("## All cases")
    lines.append("")
    lines.append("| case | result | latency | cost |")
    lines.append("| --- | --- | --- | --- |")
    for result in report.results:
        state = "error" if result.error else ("pass" if result.passed else "FAIL")
        cost = "—" if result.cost_usd is None else f"${result.cost_usd:.6f}"
        lines.append(f"| {result.case_id} | {state} | {result.latency_ms} ms | {cost} |")
    lines.append("")

    if report.notes:
        lines.append("## Notes")
        lines.append("")
        for note in report.notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)


def write(report: RunReport, verdict: Verdict | None, gate_config: dict | None, out_dir: Path, stamp: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report.suite}-{stamp}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(to_dict(report, verdict, gate_config), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(to_markdown(report, verdict, gate_config), encoding="utf-8")
    return json_path, md_path
