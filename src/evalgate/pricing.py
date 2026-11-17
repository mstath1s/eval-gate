"""Cost accounting. A missing model returns None, never a guess."""

from __future__ import annotations

import json
from pathlib import Path


def load_pricing(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise ValueError(f"{path}: 'models' must be an object")
    return data


def resolve(pricing: dict, model: str) -> dict | None:
    """Find a price entry by model id, alias, or a dated suffix."""
    models = pricing.get("models", {})
    if model in models:
        return models[model]
    for entry in models.values():
        if model in entry.get("aliases", []):
            return entry
    # e.g. 'mistral-small-latest' vs 'mistral-small-4-0-26-03'
    for model_id, entry in models.items():
        if model.startswith(model_id.rsplit("-", 1)[0]) or model_id.startswith(model):
            return entry
    return None


def cost_usd(
    pricing: dict,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> float | None:
    entry = resolve(pricing, model)
    if entry is None:
        return None
    per_m = 1_000_000.0
    fresh = max(0, prompt_tokens - cached_tokens)
    total = (
        fresh * entry.get("input", 0.0)
        + cached_tokens * entry.get("cached_input", entry.get("input", 0.0))
        + completion_tokens * entry.get("output", 0.0)
    )
    return round(total / per_m, 8)
