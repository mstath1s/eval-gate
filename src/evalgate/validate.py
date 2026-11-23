"""Validation for suite files and gate files.

The point of this module is the error message. A suite is hand-edited JSON, so every problem has
to name the exact place it lives — ``cases[7].checks[1]`` — and say what the loader expected.
``load_suite`` calls this and refuses to run a suite that has errors. Warnings never block a run.

Grader parameters are declared once, in ``GRADER_SPEC``: required or optional, and the type each
one takes. Adding a grader means adding one line here, and the validator covers it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .graders import GRADER_NAMES

CASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
TYPE_WORDS = {"str": "a string", "scalar": "a string, number or boolean", "int": "a whole number",
              "bool": "true or false", "list": "an array", "str_list": "an array of strings",
              "type_map": "an object mapping key to type name"}

# grader -> {parameter: (kind, required)}
GRADER_SPEC: dict[str, dict[str, tuple[str, bool]]] = {
    "exact_match": {"equals": ("scalar", True)},
    "contains_all": {"all": ("str_list", True)},
    "must_not_contain": {"any": ("str_list", True)},
    "regex": {"pattern": ("str", True)},
    "json_keys": {"keys": ("str_list", True), "types": ("type_map", False)},
    "json_value": {"key": ("str", True), "equals": ("scalar", False), "in": ("list", False)},
    "llm_judge": {"rubric": ("str", True), "scale": ("int", False),
                  "min_score": ("int", False), "question": ("str", False)},
}

JSON_TYPES = {"string", "number", "boolean", "array", "object"}

# Kept here, not imported from gate.py, so validation never depends on the gate module: a gate is
# allowed to import the validator, never the other way round. ``tests/test_validate.py`` asserts
# that these keys and ``gate.DEFAULT_GATE`` stay in step.
GATE_KEYS = {
    "min_pass_rate": "rate",
    "max_error_rate": "rate",
    "max_p95_latency_ms": "int",
    "max_total_cost_usd": "usd",
    "max_failures_per_grader": "map",
    "require_all_cases": "bool",
}


@dataclass(frozen=True)
class Issue:
    level: str  # "error" or "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


@dataclass
class Validation:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, where: str, message: str) -> None:
        self.errors.append(Issue("error", where, message))

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(Issue("warning", where, message))

    def raise_for_errors(self, source: str | Path | None = None) -> None:
        if not self.errors:
            return
        head = f"{source}: " if source else ""
        body = "\n".join(f"  - {issue}" for issue in self.errors)
        raise ValueError(f"{head}{len(self.errors)} problem(s) in the suite:\n{body}")

    def summary(self) -> str:
        if "keys" in self.stats:
            head = f"gate keys recognised: {len(self.stats['keys'])}"
        else:
            head = (f"cases: {self.stats.get('cases', 0)} · checks: {self.stats.get('checks', 0)} · "
                    f"graders used: {', '.join(self.stats.get('graders', [])) or 'none'}")
        lines = [head, f"errors: {len(self.errors)} · warnings: {len(self.warnings)}"]
        for issue in self.errors:
            lines.append(f"  ERROR   {issue}")
        for issue in self.warnings:
            lines.append(f"  warning {issue}")
        return "\n".join(lines)


def _matches(kind: str, value: Any) -> bool:
    if kind == "str":
        return isinstance(value, str)
    if kind == "scalar":
        return isinstance(value, (str, int, float, bool))
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "list":
        return isinstance(value, list)
    if kind == "str_list":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if kind == "type_map":
        return isinstance(value, dict) and all(isinstance(k, str) for k in value)
    return False


def _validate_check(check: Any, where: str, result: Validation) -> str | None:
    """Check one grader block. Returns the grader name when it is usable."""
    if not isinstance(check, dict):
        result.error(where, "a check must be an object with a 'grader' key")
        return None
    name = check.get("grader")
    if not isinstance(name, str) or not name:
        result.error(f"{where}.grader", f"missing or not a string; known graders: {', '.join(GRADER_NAMES)}")
        return None
    if name not in GRADER_SPEC:
        result.error(f"{where}.grader", f"unknown grader {name!r}; known graders: {', '.join(GRADER_NAMES)}")
        return None

    spec = GRADER_SPEC[name]
    for param, (kind, required) in spec.items():
        path = f"{where}.{param}"
        if param not in check:
            if required:
                result.error(path, f"required for grader {name!r} ({TYPE_WORDS[kind]})")
            continue
        if not _matches(kind, check[param]):
            result.error(path, f"expected {TYPE_WORDS[kind]}, got {type(check[param]).__name__}")
    for param in set(check) - {"grader"} - set(spec):
        result.warn(f"{where}.{param}", f"grader {name!r} ignores this parameter (typo?)")

    if name == "json_value":
        given = [p for p in ("equals", "in") if p in check]
        if len(given) != 1:
            result.error(where, f"json_value needs exactly one of 'equals' or 'in', got {given or 'neither'}")
    if name == "json_keys":
        bad = sorted({t for t in (check.get("types") or {}).values() if t not in JSON_TYPES})
        if bad:
            result.error(f"{where}.types", f"unknown JSON type name(s) {bad}; use {sorted(JSON_TYPES)}")
    if name == "llm_judge":
        if "question" not in check:
            result.warn(where, "llm_judge without 'question': the judge sees the answer but not what was asked")
        if "min_score" in check and "scale" in check and int(check["min_score"]) > int(check["scale"]):
            result.error(where, "min_score is above scale, so this check can never pass")
    return name


def validate_suite(data: Any, source: str = "") -> Validation:
    result = Validation()
    if not isinstance(data, dict):
        result.error("(root)", "a suite must be a JSON object")
        return result

    for key, kind in (("name", str), ("version", int), ("temperature", (int, float)),
                      ("system", str), ("cases", list)):
        if key not in data:
            if key == "cases":
                result.error("cases", "required: a non-empty array of cases")
            continue
        if not isinstance(data[key], kind):
            result.error(key, f"expected {getattr(kind, '__name__', kind)}, got {type(data[key]).__name__}")

    temperature = data.get("temperature")
    if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
        if not 0.0 <= float(temperature) <= 1.0:
            result.error("temperature", f"must be between 0 and 1, got {temperature}")
        elif float(temperature) > 0.3:
            result.warn("temperature", "above 0.3 makes a pass/fail gate wobble between runs")

    cases = data.get("cases")
    if isinstance(cases, list) and not cases:
        result.error("cases", "a suite with no cases always passes the gate and proves nothing")

    seen_ids: dict[str, int] = {}
    graders: set[str] = set()
    total_checks = 0
    for index, raw in enumerate(cases if isinstance(cases, list) else []):
        where = f"cases[{index}]"
        if not isinstance(raw, dict):
            result.error(where, "a case must be an object")
            continue

        case_id = raw.get("id")
        if not isinstance(case_id, str) or not case_id:
            result.error(f"{where}.id", "required: a short stable identifier, e.g. \"triage-001\"")
        else:
            if not CASE_ID.match(case_id):
                result.error(f"{where}.id", f"{case_id!r} must be lowercase letters, digits, dot, dash or underscore")
            if case_id in seen_ids:
                result.error(f"{where}.id", f"duplicate id {case_id!r} (first used at cases[{seen_ids[case_id]}])")
            else:
                seen_ids[case_id] = index

        for key in ("input",):
            value = raw.get(key)
            if not isinstance(value, str) or not value.strip():
                result.error(f"{where}.{key}", "required: the text sent to the model")
        if "system" in raw and not isinstance(raw["system"], str):
            result.error(f"{where}.system", "must be a string when present")
        if not isinstance(raw.get("notes", ""), str):
            result.error(f"{where}.notes", "must be a string when present")
        elif "notes" not in raw:
            result.warn(where, "no 'notes': the run report cannot say why this case exists")

        checks = raw.get("checks")
        if not isinstance(checks, list) or not checks:
            result.error(f"{where}.checks", "required: a non-empty array of checks (a case with no checks always passes)")
            continue
        for position, check in enumerate(checks):
            name = _validate_check(check, f"{where}.checks[{position}]", result)
            if name:
                graders.add(name)
            total_checks += 1

    if len(seen_ids) < 5 and seen_ids:
        result.warn("cases", f"only {len(seen_ids)} case(s): a pass rate over fewer than five cases cannot support a gate")

    result.stats = {"cases": len(seen_ids), "checks": total_checks,
                    "graders": sorted(graders), "temperature": data.get("temperature", 0.0)}
    return result


def validate_gate(data: Any, source: str = "") -> Validation:
    result = Validation()
    if not isinstance(data, dict):
        result.error("(root)", "a gate must be a JSON object")
        return result

    unknown = sorted(set(data) - set(GATE_KEYS))
    if unknown:
        result.error("(root)", f"unknown gate key(s) {unknown}; known keys: {sorted(GATE_KEYS)}")

    for key in ("min_pass_rate", "max_error_rate"):
        if key in data:
            value = data[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 <= float(value) <= 1.0:
                result.error(key, f"expected a fraction between 0 and 1, got {value!r}")
    for key in ("max_p95_latency_ms",):
        if key in data and (not isinstance(data[key], int) or isinstance(data[key], bool) or data[key] < 0):
            result.error(key, f"expected a whole number of milliseconds ≥ 0, got {data[key]!r}")
    for key in ("max_total_cost_usd",):
        if key in data and (not isinstance(data[key], (int, float)) or isinstance(data[key], bool) or data[key] < 0):
            result.error(key, f"expected an amount in USD ≥ 0, got {data[key]!r}")
    if "require_all_cases" in data and not isinstance(data["require_all_cases"], bool):
        result.error("require_all_cases", f"expected true or false, got {data['require_all_cases']!r}")

    per_grader = data.get("max_failures_per_grader")
    if per_grader is not None:
        if not isinstance(per_grader, dict):
            result.error("max_failures_per_grader", "expected an object mapping grader name to a limit")
        else:
            for name, limit in per_grader.items():
                if name not in GRADER_SPEC:
                    result.warn(f"max_failures_per_grader.{name}",
                                f"unknown grader {name!r}: this limit can never fire")
                if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                    result.error(f"max_failures_per_grader.{name}", f"expected a whole number ≥ 0, got {limit!r}")

    result.stats = {"keys": sorted(data)}
    return result


def _load(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"{path}: no such file") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON — line {exc.lineno}, column {exc.colno}: {exc.msg}") from None
