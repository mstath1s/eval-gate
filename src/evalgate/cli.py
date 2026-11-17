"""Command line.

    python -m evalgate run --suite suites/support-triage.json --model mistral-small-latest \
        --gate gates/default.json --out out

Exit codes: 0 = gate passed, 1 = gate failed, 2 = bad configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .gate import evaluate, load_gate
from .graders import GRADER_NAMES
from .pricing import load_pricing
from .providers import FakeProvider, MistralProvider, ProviderError
from .report import to_markdown, write
from .suite import load_suite, run_suite

ROOT = Path(__file__).resolve().parents[2]


def _answers_for(suite_name: str, explicit: str | None) -> dict[str, str]:
    if explicit:
        path = Path(explicit)
    else:
        path = ROOT / "fixtures" / "offline" / f"{suite_name}.json"
    if not path.exists():
        raise ValueError(
            f"offline mode needs scripted answers; {path} does not exist. "
            f"Create it as a JSON object mapping each case input to an answer."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_run(args: argparse.Namespace) -> int:
    suite_path = Path(args.suite)
    suite = load_suite(suite_path)
    pricing = load_pricing(args.pricing)
    gate_config = load_gate(args.gate) if args.gate else None

    if args.offline:
        provider = FakeProvider(_answers_for(suite["name"], args.answers), pricing)
        provider_name = "fake (offline: latency and cost are simulated, not measured)"
    else:
        try:
            provider = MistralProvider(pricing=pricing)
        except ProviderError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        provider_name = "mistral"

    judge_provider = None
    if args.judge_model:
        if args.offline:
            judge_path = ROOT / "fixtures" / "offline" / "judge-answers.json"
            if not judge_path.exists():
                print(
                    f"error: --offline with --judge-model needs scripted verdicts; {judge_path} is missing",
                    file=sys.stderr,
                )
                return 2
            judge_provider = FakeProvider(
                json.loads(judge_path.read_text(encoding="utf-8")), pricing, match="contains"
            )
        else:
            try:
                judge_provider = MistralProvider(pricing=pricing)
            except ProviderError as exc:
                print(f"error: judge provider: {exc}", file=sys.stderr)
                return 2

    report = run_suite(
        suite,
        provider,
        args.model,
        judge_provider=judge_provider,
        judge_model=args.judge_model,
        max_workers=args.max_workers,
    )
    report.notes.append(f"provider: {provider_name}")

    verdict = evaluate(report, gate_config, expected_cases=len(suite["cases"])) if gate_config else None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path, md_path = write(report, verdict, gate_config, Path(args.out), stamp)

    if not args.quiet:
        print(to_markdown(report, verdict, gate_config))
    print(f"artifacts: {json_path} {md_path}", file=sys.stderr)

    if verdict is None:
        return 0
    return 0 if verdict.passed else 1


def cmd_graders(_args: argparse.Namespace) -> int:
    for name in GRADER_NAMES:
        print(name)
    return 0


def cmd_suites(_args: argparse.Namespace) -> int:
    for path in sorted((ROOT / "suites").glob("*.json")):
        print(path.relative_to(ROOT))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval-gate", description="A release gate for LLM features.")
    parser.add_argument("--version", action="version", version=f"eval-gate {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a suite and apply the gate")
    run.add_argument("--suite", required=True, help="path to a suite JSON file")
    run.add_argument("--model", default="mistral-small-latest", help="model id sent to the provider")
    run.add_argument("--gate", default="gates/default.json", help="gate JSON file ('' to skip the gate)")
    run.add_argument("--pricing", default=str(ROOT / "pricing.json"), help="pricing table")
    run.add_argument("--out", default=str(ROOT / "out"), help="directory for the JSON and Markdown report")
    run.add_argument("--offline", action="store_true", help="use scripted answers instead of the API")
    run.add_argument("--answers", default=None, help="scripted answers file for --offline")
    run.add_argument("--judge-model", default=None, help="model used by llm_judge checks")
    run.add_argument("--max-workers", type=int, default=4, help="parallel cases (keep low: rate limits)")
    run.add_argument("--quiet", action="store_true", help="do not print the Markdown report")
    run.set_defaults(func=cmd_run)

    graders = sub.add_parser("graders", help="list grader names")
    graders.set_defaults(func=cmd_graders)

    suites = sub.add_parser("suites", help="list bundled suites")
    suites.set_defaults(func=cmd_suites)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run" and args.gate == "":
        args.gate = None
    try:
        return args.func(args)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
