"""Graders: the checks that decide whether one answer is acceptable.

Every grader takes the model's raw text plus its own parameters and returns a ``Grade``.
Deterministic graders are the default. ``llm_judge`` exists because some criteria ("is this
explanation actually correct?") cannot be expressed as a string match — it is opt-in per case,
costs money, and its own cost is tracked.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .types import Grade

FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Pull a JSON value out of a model answer, tolerating fences and chatter."""
    if not text:
        raise ValueError("empty answer")
    fenced = FENCE.search(text)
    candidate = fenced.group(1).strip() if fenced else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in answer")
    return json.loads(candidate[start : end + 1])


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def grade_exact_match(answer: str, params: dict) -> Grade:
    expected = params["equals"]
    ok = _normalize(answer) == _normalize(str(expected))
    return Grade("exact_match", ok, 1.0 if ok else 0.0, f"expected {expected!r}")


def grade_contains_all(answer: str, params: dict) -> Grade:
    needles = params["all"]
    haystack = _normalize(answer)
    missing = [n for n in needles if _normalize(n) not in haystack]
    ok = not missing
    detail = "all present" if ok else f"missing: {missing}"
    return Grade("contains_all", ok, 0.0 if missing else 1.0, detail)


def grade_must_not_contain(answer: str, params: dict) -> Grade:
    banned = params["any"]
    haystack = _normalize(answer)
    hits = [b for b in banned if _normalize(b) in haystack]
    ok = not hits
    return Grade("must_not_contain", ok, 0.0 if hits else 1.0, f"forbidden: {hits}" if hits else "clean")


def grade_regex(answer: str, params: dict) -> Grade:
    pattern = params["pattern"]
    ok = re.search(pattern, answer, re.MULTILINE) is not None
    return Grade("regex", ok, 1.0 if ok else 0.0, f"pattern {pattern!r}")


TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def grade_json_keys(answer: str, params: dict) -> Grade:
    keys = params["keys"]
    types = params.get("types", {})
    try:
        payload = extract_json(answer)
    except (ValueError, json.JSONDecodeError) as exc:
        return Grade("json_keys", False, 0.0, f"not JSON: {exc}")
    if not isinstance(payload, dict):
        return Grade("json_keys", False, 0.0, "JSON is not an object")
    missing = [k for k in keys if k not in payload]
    if missing:
        return Grade("json_keys", False, 0.0, f"missing keys: {missing}")
    bad = [
        k
        for k, wanted in types.items()
        if not TYPE_CHECKS.get(wanted, lambda _v: True)(payload.get(k))
    ]
    if bad:
        return Grade("json_keys", False, 0.0, f"wrong types: {bad}")
    return Grade("json_keys", True, 1.0, "schema ok")


def grade_json_value(answer: str, params: dict) -> Grade:
    key = params["key"]
    try:
        payload = extract_json(answer)
    except (ValueError, json.JSONDecodeError) as exc:
        return Grade("json_value", False, 0.0, f"not JSON: {exc}")
    if not isinstance(payload, dict) or key not in payload:
        return Grade("json_value", False, 0.0, f"no key {key!r}")
    value = payload[key]
    if "equals" in params:
        ok = _normalize(str(value)) == _normalize(str(params["equals"]))
        detail = f"{key}={value!r} (expected {params['equals']!r})"
        return Grade("json_value", ok, 1.0 if ok else 0.0, detail)
    if "in" in params:
        allowed = [_normalize(str(v)) for v in params["in"]]
        ok = _normalize(str(value)) in allowed
        detail = f"{key}={value!r} (expected one of {params['in']})"
        return Grade("json_value", ok, 1.0 if ok else 0.0, detail)
    return Grade("json_value", False, 0.0, "params need 'equals' or 'in'")


JUDGE_PROMPT = """You are grading a model answer against a rubric.

RUBRIC
{rubric}

USER INPUT
{question}

MODEL ANSWER
{answer}

Return only JSON: {{"score": <integer 1-{scale}>, "reason": "<one sentence>"}}.
1 means the answer clearly fails the rubric, {scale} means it clearly satisfies it."""


def grade_llm_judge(answer: str, params: dict, judge: Callable[[str], tuple[str, float | None]]) -> Grade:
    """Ask a second model to score the answer. ``judge`` returns (text, cost_usd)."""
    scale = int(params.get("scale", 5))
    min_score = int(params.get("min_score", 4))
    prompt = JUDGE_PROMPT.format(
        rubric=params["rubric"],
        question=params.get("question", ""),
        answer=answer,
        scale=scale,
    )
    raw, _cost = judge(prompt)
    try:
        payload = extract_json(raw)
        score = int(payload["score"])
        reason = str(payload.get("reason", ""))[:200]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return Grade("llm_judge", False, 0.0, f"judge output unparseable: {exc}")
    score = max(1, min(scale, score))
    ok = score >= min_score
    return Grade("llm_judge", ok, score / scale, f"{score}/{scale}: {reason}")


DETERMINISTIC = {
    "exact_match": grade_exact_match,
    "contains_all": grade_contains_all,
    "must_not_contain": grade_must_not_contain,
    "regex": grade_regex,
    "json_keys": grade_json_keys,
    "json_value": grade_json_value,
}

GRADER_NAMES = sorted(list(DETERMINISTIC) + ["llm_judge"])
