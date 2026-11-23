"""One self-contained HTML file per run: no assets, no JavaScript, opens from disk or a PR comment.

This is the view for a human: the gate verdict first, then every case with its input, what each
grader said, and the ones that failed with room to explain themselves.
"""

from __future__ import annotations

import html
from pathlib import Path

from .explain import case_inputs
from .gate import Verdict
from .types import RunReport

CSS = """
:root { --ink:#16181d; --muted:#5b6270; --line:#e3e6ec; --bg:#fbfbfd; --card:#fff;
        --pass:#0a7c42; --fail:#b42318; --warn:#8a5a00; }
* { box-sizing: border-box; }
body { margin:0; padding:28px 32px 56px; background:var(--bg); color:var(--ink);
       font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif; }
h1 { font-size:22px; margin:2px 0 4px; letter-spacing:-.01em; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.09em; color:var(--muted);
     margin:34px 0 10px; font-weight:600; }
.kicker { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); }
.meta { color:var(--muted); font-size:12.5px; }
.badge { display:inline-block; padding:5px 12px; border-radius:999px; font-weight:700;
         font-size:12px; letter-spacing:.06em; }
.badge.pass { background:#e7f6ee; color:var(--pass); border:1px solid #bfe6d0; }
.badge.fail { background:#fdecea; color:var(--fail); border:1px solid #f5c2bd; }
.badge.none { background:#f1f2f5; color:var(--muted); border:1px solid var(--line); }
.head { display:flex; justify-content:space-between; align-items:flex-start; gap:24px; }
.metrics { display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:10px;
        padding:11px 15px; min-width:118px; }
.tile .v { font-size:19px; font-weight:650; letter-spacing:-.02em; }
.tile .l { font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }
table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line);
        border-radius:10px; overflow:hidden; }
th, td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-size:11px; text-transform:uppercase; letter-spacing:.07em; color:var(--muted);
     font-weight:600; background:#f7f8fa; }
tr:last-child td { border-bottom:none; }
td.mono, code, .ans { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
.pass { color:var(--pass); font-weight:600; }
.fail { color:var(--fail); font-weight:600; }
.why { color:var(--muted); font-size:12.5px; }
.chip { display:inline-block; margin:1px 4px 1px 0; padding:1px 7px; border-radius:5px;
        background:#fdecea; color:var(--fail); font-size:11.5px; font-family:ui-monospace,monospace; }
.checks { margin:6px 0 0; padding:0; list-style:none; }
.checks li { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; padding:1px 0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
        padding:14px 16px; margin-bottom:12px; }
.card h3 { margin:0 0 6px; font-size:13.5px; font-family:ui-monospace,monospace; }
footer { margin-top:38px; color:var(--muted); font-size:11.5px; }
"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.6f}"


def to_html(
    suite: dict,
    report: RunReport,
    verdict: Verdict | None,
    gate_config: dict | None,
    provider_note: str = "",
    title: str | None = None,
) -> str:
    inputs = case_inputs(suite)
    notes = {case.get("id", ""): case.get("notes", "") for case in suite.get("cases", [])}
    failing = [result for result in report.results if not result.passed]

    if verdict is None or gate_config is None:
        badge = '<span class="badge none">NO GATE</span>'
    else:
        badge = f'<span class="badge {"pass" if verdict.passed else "fail"}">GATE {"PASS" if verdict.passed else "FAIL"}</span>'

    tiles = [
        (f"{report.passed}/{report.total}", "cases passed"),
        (f"{report.pass_rate:.1%}", "pass rate"),
        (str(report.errors), "errors"),
        (f"{report.p95_latency_ms()} ms", "p95 latency"),
        (_money(report.total_cost_usd) if not report.cost_unknown else "unknown", "total cost"),
    ]

    parts: list[str] = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        f"<title>eval-gate — {_e(report.suite)}</title>",
        f"<style>{CSS}</style></head><body>",
        '<div class="head"><div>',
        '<div class="kicker">eval-gate · run report</div>',
        f"<h1>{_e(title or report.suite)}</h1>",
        f'<div class="meta">model <code>{_e(report.model)}</code> · started {_e(report.started_at)}',
        f" · {_e(provider_note)}</div>" if provider_note else f" · started {_e(report.started_at)}</div>",
        "</div><div>", badge, "</div></div>",
        '<div class="metrics">',
    ]
    parts += [f'<div class="tile"><div class="v">{_e(v)}</div><div class="l">{_e(l)}</div></div>'
              for v, l in tiles]
    parts.append("</div>")

    if verdict is not None and gate_config is not None:
        parts.append("<h2>What the gate checked</h2><table><tr><th>check</th><th>result</th>"
                     "<th>detail</th></tr>")
        for check in verdict.checks:
            state = 'class="pass">pass' if check.passed else 'class="fail">FAIL'
            parts.append(f"<tr><td class=\"mono\">{_e(check.name)}</td><td {state}</td>"
                         f"<td class=\"mono\">{_e(check.detail)}</td></tr>")
        parts.append("</table>")

    parts.append("<h2>Every case</h2><table><tr><th>case</th><th>result</th><th>input → answer</th>"
                 "<th>latency</th><th>cost</th></tr>")
    for result in report.results:
        state = ('class="fail">error' if result.error
                 else ('class="pass">pass' if result.passed else 'class="fail">FAIL'))
        chips = "".join(f'<span class="chip">{_e(g.grader)}</span>'
                        for g in result.grades if not g.passed)
        input_text = _e(inputs.get(result.case_id, ""))
        answer = _e(result.error or result.answer or "")
        parts.append(
            f'<tr><td class="mono">{_e(result.case_id)}</td>'
            f"<td {state}>{chips}</td>"
            f'<td><div class="why">{input_text}</div><div class="ans">{answer}</div></td>'
            f'<td class="mono">{result.latency_ms} ms</td>'
            f'<td class="mono">{_e("unknown" if result.cost_usd is None else f"${result.cost_usd:.8f}")}</td></tr>'
        )
    parts.append("</table>")

    if failing:
        parts.append("<h2>The cases that missed, in full</h2>")
        for result in failing:
            parts.append('<div class="card">')
            parts.append(f'<h3>{_e(result.case_id)}</h3>')
            if notes.get(result.case_id):
                parts.append(f'<div class="why">why this case exists: {_e(notes[result.case_id])}</div>')
            parts.append(f'<div class="why">input: {_e(inputs.get(result.case_id, ""))}</div>')
            parts.append(f'<div class="ans">answer: {_e(result.error or result.answer)}</div>')
            parts.append('<ul class="checks">')
            for grade in result.grades:
                mark = "pass" if grade.passed else "fail"
                parts.append(f'<li><span class="{mark}">{"PASS" if grade.passed else "FAIL"}</span> '
                             f'{_e(grade.grader)} — {_e(grade.detail)}</li>')
            parts.append("</ul></div>")

    if report.notes:
        parts.append("<h2>Notes</h2><ul>")
        parts += [f"<li class=\"why\">{_e(note)}</li>" for note in report.notes]
        parts.append("</ul>")

    parts.append('<footer>Generated by eval-gate. A gate is a floor, not a score: it shows that every '
                 "check you wrote passed, not that the answers are right.</footer></body></html>")
    return "\n".join(parts)


def write_html(path: str | Path, **kwargs) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_html(**kwargs), encoding="utf-8")
    return target
